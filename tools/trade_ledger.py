#!/usr/bin/env python3
"""
trade_ledger.py — Structured fill ledger with decision attribution and
benchmark-adjusted alpha scoring.

Answers the question the prose journals cannot: for each trade, *who decided*
(the plan, or a discretionary override), and did that decision beat simply
holding the benchmark?

Deterministic by design: ingest/dedup, order-registry matching, the origin
priority chain, split adjustment, and alpha arithmetic all live here. The calling
skill (/trade-review) supplies only the reasoning judgment ("was the signal
available at the time?").

Storage
  research/trade-ledger.jsonl    one fill per line, keyed by fill_id
  research/order-registry.json   {order_id: {...}} snapshots of resting orders
  briefing-out/cache/eod-prices.json   EODHD daily closes (benchmark + symbols)

Why the order registry: Firstrade's order_status endpoint returns ONLY currently
open orders — filled and cancelled ones vanish. So order_id → fill linkage is
prospective: snapshot each briefing, and when a fill lands we can match it to the
order that produced it. See ORIGIN_CHAIN below for how retro fills are handled.

Usage
  python3 tools/trade_ledger.py snapshot-orders
  python3 tools/trade_ledger.py ingest --range ly
  python3 tools/trade_ledger.py ingest --from 2026-01-01 --to 2026-07-25
  python3 tools/trade_ledger.py backfill-origin
  python3 tools/trade_ledger.py score --by origin
  python3 tools/trade_ledger.py score --by origin-side --since 2026-06-01
  python3 tools/trade_ledger.py stats
  python3 tools/trade_ledger.py orders
  python3 tools/trade_ledger.py annotate --id <fill_id> --origin user --evidence "..."
"""

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = ROOT / "research" / "trade-ledger.jsonl"
DEFAULT_REGISTRY = ROOT / "research" / "order-registry.json"
DEFAULT_FLAGS = ROOT / "research" / "position-flags.json"
PRICE_CACHE = ROOT / "briefing-out" / "cache" / "eod-prices.json"
FT_SERVER_DIR = Path("/Users/supatrick/laptop/mcp-servers/firstrade-server")

VALID_ORIGINS = {"system", "user", "unknown"}
VALID_CONF = {"high", "low"}

# ── benchmark map ───────────────────────────────────────────────────────────
# Semis / AI hardware move with SMH, not SPY; scoring a semi buy against SPY
# during a chip selloff manufactures fake alpha. Everything else → SPY.
SEMI_AI = {
    "AMD", "ANET", "ARM", "ASML", "AVGO", "COHR", "CRDO", "DIOD", "ICHR",
    "INTC", "LITE", "LRCX", "MRVL", "MU", "NVDA", "ON", "ONTO", "QCOM",
    "SNPS", "STX", "TSM", "CIEN", "CDNS", "KLAC", "AMAT", "TER",
}
BENCH_DEFAULT = "SPY.US"
BENCH_SEMI = "SMH.US"

# ── corporate actions ───────────────────────────────────────────────────────
# {symbol: [(effective_date, ratio)]} — a fill BEFORE effective_date has its price
# divided by ratio and its quantity multiplied by it, so both are comparable to
# post-split quotes and to the current share count.
# Add new splits here; ingest recomputes split_adj_price on every run.
SPLITS = {
    "NVDA": [("2024-06-10", 10.0)],
    "ANET": [("2024-12-04", 4.0)],
    "CRWD": [("2026-07-02", 4.0)],
}

EODHD_BASE = "https://eodhd.com/api"

ORIGIN_CHAIN = """\
origin — WHO DECIDED (the only axis that scores decision quality):
  1. fill matches a registry order whose id is referenced in plan.md → system/high
  2. fill matches a registry order NOT referenced in plan.md         → user/high
  3. no registry match while snapshots cover that date               → user/high
     (system orders are registered in plan.md before being placed, so a fill with
      no resting order behind it was entered live in the App)
  4. journal trade-table reason column keywords (+/-2 days)           → system|user/high
  5. fill price lands exactly on a plan.md ladder level               → system/low
  6. nothing matched                                                 → unknown

exec_via — HOW IT WAS ENTERED (never implies origin; 2026-06-18 was a
plan-directed cleanup executed by hand in the App):
  gtc-ladder  matched a resting limit order
  manual-app  multi-symbol burst, option contract, or average-price market fill
  unknown     no fingerprint
"""

# USER is tested BEFORE SYS, which is what makes the bare `\bplan\b` in SYS safe:
# negated mentions ("偏離 plan", "未列於 plan") are claimed by USER first. A bare
# `plan` is needed because journals write things like "plan 列移除不留 bench" —
# the 2026-06-18 cut rationale — which no `plan #N` / `plan.md` variant catches.
USER_REASON_PAT = re.compile(
    r"未列於\s*plan|未在\s*roster|偏離\s*plan|plan\s*外|不在\s*plan|"
    r"高於計畫目標區|高於階梯|屬追高|違反|手動|用戶|盤中低點|理由欄空白",
)
SYS_REASON_PAT = re.compile(
    r"\bplan\b|GTC|規則執行|harvest 訊號|梯級|階梯成交|飛輪|買梯|ladder|"
    r"停損規則|週三未動即砍|集中度|列移除",
    re.IGNORECASE,
)


# ── small helpers ───────────────────────────────────────────────────────────
def _today(asof=None):
    return date.fromisoformat(asof) if asof else date.today()


def fill_id(rec):
    """Stable id so re-ingesting the same window is idempotent."""
    raw = "|".join(str(rec.get(k, "")) for k in
                   ("date", "exec_time", "symbol", "side", "qty", "price"))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def benchmark_for(symbol):
    return BENCH_SEMI if symbol.upper() in SEMI_AI else BENCH_DEFAULT


def split_adjust(symbol, trade_date, price):
    """Divide by every split effective AFTER the trade date."""
    for eff, ratio in SPLITS.get(symbol.upper(), []):
        if trade_date < eff:
            price = price / ratio
    return round(price, 6)


def split_adjust_qty(symbol, trade_date, qty):
    """Multiply by every split effective AFTER the trade date.

    Needed to reconcile historical fills against today's share count: 3 pre-split
    NVDA shares are 30 shares now.
    """
    for eff, ratio in SPLITS.get(symbol.upper(), []):
        if trade_date < eff:
            qty = qty * ratio
    return qty


# ── Firstrade bridge ────────────────────────────────────────────────────────
def _ft_call(snippet):
    """Run a snippet inside the firstrade-server venv and parse its stdout JSON.

    The firstrade MCP server is stdio, so there is no HTTP bypass like
    tools/fmp_query.py. Shelling into its venv gives a fresh session every run and
    is immune to a stale MCP session in the calling Claude Code client.
    """
    code = (
        "import json, importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('ftsrv', '{FT_SERVER_DIR}/server.py')\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "_, data = m._get_data()\n"
        "acct = data.account_numbers[0]\n"
        f"{snippet}\n"
    )
    proc = subprocess.run(
        ["uv", "run", "python", "-c", code],
        cwd=str(FT_SERVER_DIR), capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"firstrade bridge failed: {proc.stderr.strip()[-500:]}")
    out = proc.stdout.strip()
    start = out.find("{")
    if start < 0:
        raise RuntimeError(f"firstrade bridge returned no JSON: {out[-300:]}")
    return json.loads(out[start:])


def fetch_history(date_range="ly", custom=None):
    if custom:
        snippet = (
            f"print(json.dumps(data.get_account_history(acct, date_range='cust', "
            f"custom_range=['{custom[0]}','{custom[1]}'])))"
        )
    else:
        snippet = (
            f"print(json.dumps(data.get_account_history(acct, date_range='{date_range}')))"
        )
    return _ft_call(snippet)


def fetch_orders():
    return _ft_call("print(json.dumps(data.get_orders(acct, per_page=0)))")


def fetch_positions():
    """{'equities': {SYM: {qty, unit_cost, last}}, 'cash': float, 'equity_value': float}"""
    payload = _ft_call("print(json.dumps(data.get_positions(acct)))")
    bal = _ft_call("print(json.dumps(data.get_account_balances(acct)))")
    eq, opts, opt_value = {}, defaultdict(list), 0.0
    for item in payload.get("items", []):
        sym = (item.get("symbol") or "").strip().upper()
        if not sym:
            continue
        if item.get("sec_type") == 2:
            opt_value += float(item.get("market_value") or 0)
            root = re.match(r"^([A-Z]+)\d{6}[CP]\d+$", sym)
            opts[(root.group(1) if root else sym)].append({
                "contract": sym,
                "qty": float(item.get("quantity") or 0),
                "market_value": float(item.get("market_value") or 0),
                "unrealized": float(item.get("gainloss") or 0),
                "unrealized_pct": float(item.get("gainloss_percent") or 0),
            })
            continue
        eq[sym] = {"qty": float(item.get("quantity") or 0),
                   "unit_cost": float(item.get("unit_cost") or 0),
                   "last": float(item.get("last") or 0),
                   "market_value": float(item.get("market_value") or 0)}
    res = bal.get("result") or bal
    return {"equities": eq,
            "options_by_underlying": dict(opts),
            "cash": float(res.get("cash_balance") or 0),
            "equity_value": sum(v["market_value"] for v in eq.values()),
            "option_value": opt_value,
            "total_account_value": float(res.get("total_account_value") or 0)}


# ── parsing broker payloads ─────────────────────────────────────────────────
_EXEC_RE = re.compile(r"EXEC TIME:\s*([\d\-]{10}[ T][\d:]{8})")


def parse_history(payload):
    """Broker history JSON → list of fill records (BOUGHT/SOLD only)."""
    fills = []
    for item in payload.get("items", []):
        side = item.get("trans_str")
        if side not in ("BOUGHT", "SOLD"):
            continue
        price = float(item.get("trade_price") or 0)
        if price <= 0:                      # split share distributions etc.
            continue
        desc_arr = item.get("descriptionArray") or []
        joined = " ".join(desc_arr)
        exec_time = ""
        for seg in desc_arr:
            hit = _EXEC_RE.search(seg or "")
            if hit:
                exec_time = hit.group(1).replace("T", " ")
        head = (desc_arr[0] if desc_arr else "").strip()
        is_option = bool(re.match(r"(PUT|CALL)\s", head))
        symbol = (item.get("symbol") or "").strip().upper()
        qty = abs(float(item.get("quantity") or 0))
        rec = {
            "date": item.get("report_date"),
            "exec_time": exec_time,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "notional": round(price * qty * (100 if is_option else 1), 2),
            "amount": float(item.get("amount") or 0),
            "is_option": is_option,
            "avg_price_trade": "AVERAGE PRICE TRADE" in joined,
            "underlying": head.split()[1].upper() if is_option and len(head.split()) > 1 else symbol,
        }
        rec["split_adj_price"] = split_adjust(
            rec["underlying"] if is_option else symbol, rec["date"], price
        )
        rec["id"] = fill_id(rec)
        fills.append(rec)
    return fills


def parse_orders(payload, seen_on):
    """Broker order_status JSON → {order_id: registry entry}."""
    out = {}
    for it in payload.get("items", []):
        oid = it.get("id")
        if not oid:
            continue
        out[oid] = {
            "order_id": oid,
            "symbol": (it.get("symbol") or "").strip().upper(),
            "transaction": it.get("transaction"),
            "shares": float(it.get("shares") or 0),
            "filled": float(it.get("filled") or 0),
            "limit_price": float(it.get("limit_price") or 0),
            "avg_exe_price": float(it.get("avg_exe_price") or 0),
            "price_type": it.get("price_type"),
            "duration_type": it.get("duration_type"),
            "state": it.get("state"),
            "sec_type": it.get("sec_type"),
            "placed": (it.get("updated") or "")[:10],
            "first_seen": seen_on,
            "last_seen": seen_on,
        }
    return out


# ── plan.md / journal evidence ──────────────────────────────────────────────
_REF_RE = re.compile(r"G\d{5}-(\d{4})|`(\d{4})`")


def plan_order_refs(root=ROOT):
    """Order numbers plan.md (and journals) record as system-placed."""
    refs = set()
    texts = [root / "plan.md"]
    texts += sorted((root / "journal").glob("*.md"))
    for path in texts:
        if not path.exists():
            continue
        for m in _REF_RE.finditer(path.read_text(encoding="utf-8")):
            refs.add(m.group(1) or m.group(2))
    return refs


def _line_subject(line):
    """The ticker a plan.md line is *about*.

    plan.md rows name other tickers in passing ("補 MRVL/BE 空出名額"), so taking
    every uppercase token makes the line ambiguous and it gets dropped. The subject
    is the first cell of a table row, or the first bolded ticker of a bullet.
    """
    if line.startswith("|"):
        head = line.strip("|").split("|")[0]
        hit = re.search(r"([A-Z]{2,5})", head)
        return hit.group(1) if hit else None
    hit = re.search(r"\*\*~?~?([A-Z]{2,5})", line)
    return hit.group(1) if hit else None


def plan_ladder_levels(root=ROOT, symbols=None):
    """{SYMBOL: {price, ...}} limit levels named on GTC/ladder lines in plan.md."""
    levels = defaultdict(set)
    path = root / "plan.md"
    if not path.exists():
        return levels
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not re.search(r"GTC|掛單|買梯|階梯|限價", line):
            continue
        sym = _line_subject(line)
        if not sym or (symbols is not None and sym not in symbols):
            continue
        for p in re.findall(r"\$([\d,]+(?:\.\d+)?)", line):
            val = float(p.replace(",", ""))
            if val > 5:              # below this it is a percentage or cash figure
                levels[sym].add(round(val, 2))
    return levels


_TRADE_VERB = re.compile(
    r"加碼|減碼|清倉|新建倉|停利|平倉|買入|賣出|買進|Roll|harvest|已砍|認列出場|出清|回補|砍因"
)
_QTY_IN_TEXT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:股|口|株)")
# "砍因：..." is a post-hoc explanation — you only justify a cut after making it —
# so it counts as execution evidence even without a share count. This is what
# carries the 2026-06-18 BE/MRVL/VRT rationale ("plan 列移除不留 bench").
_EXPLAINER = re.compile(r"砍因|出場理由|減碼理由")
# A bullet must show evidence the trade actually happened, otherwise forward-looking
# lines ("明日待辦：GTC 買梯續掛") would be read as executed system decisions.
_EXECUTED = re.compile(r"\d+\s*(?:股|口|株)|@\s*~?\$?[\d,]+|已(?:成交|砍|平|清|執行|建|減)|✅")


def journal_reasons(root=ROOT, symbols=None):
    """[(journal_date, [SYMBOL], verdict, snippet)] from journal trade records.

    Scans both the trade tables (rows starting with `|`) and bullet lines — the
    2026-06-18 cleanup, the single largest alpha event, is recorded only as bullets
    ("砍因：BE β3.74 太投機（plan 列移除不留 bench）...").

    `symbols` restricts symbol extraction to tickers we hold fills for; without it
    tokens like GTC / EV / PE / AI get mistaken for tickers and tag unrelated fills.
    """
    out = []
    for path in sorted((root / "journal").glob("*.md")):
        jdate = path.stem
        for raw in path.read_text(encoding="utf-8").split("\n"):
            line = raw.strip()
            is_row = line.startswith("|")
            is_bullet = line.startswith(("-", "*", "> -")) or bool(re.match(r"^\d+\.", line))
            if not (is_row or is_bullet):
                continue
            if not _TRADE_VERB.search(line):
                continue
            if is_bullet and not (_EXECUTED.search(line) or _EXPLAINER.search(line)):
                continue
            syms = re.findall(r"\b([A-Z]{2,5})\b", line)
            if symbols is not None:
                syms = [s for s in syms if s in symbols]
            if not syms:
                continue
            if USER_REASON_PAT.search(line):
                verdict = "user"
            elif SYS_REASON_PAT.search(line):
                verdict = "system"
            else:
                continue
            out.append((jdate, syms, verdict, line[:200]))
    return out


# ── origin attribution ──────────────────────────────────────────────────────
def _match_registry(rec, registry):
    """Find a resting order that plausibly produced this fill."""
    want = "B" if rec["side"] == "BOUGHT" else "S"
    best = None
    for entry in registry.values():
        if entry["symbol"] != (rec["underlying"] if rec["is_option"] else rec["symbol"]):
            continue
        if (entry.get("transaction") or "")[:1] != want:
            continue
        lim = entry.get("limit_price") or 0
        if lim and abs(rec["price"] - lim) / lim > 0.02:
            continue
        if entry["shares"] and abs(rec["qty"] - entry["shares"]) > max(1.0, entry["shares"] * 0.5):
            continue
        if best is None or abs(rec["price"] - lim) < abs(rec["price"] - (best.get("limit_price") or 0)):
            best = entry
    return best


def _burst_ids(fills, window_sec=360, min_symbols=3):
    """Fills belonging to a multi-symbol burst (manual App session fingerprint).

    Day-bucketed: a burst is by definition intraday, so comparing across days is
    both wrong and O(n^2) over the whole ledger.
    """
    by_day = defaultdict(list)
    for f in fills:
        if not f.get("exec_time"):
            continue
        try:
            f_ts = datetime.fromisoformat(f["exec_time"])
        except ValueError:
            continue
        by_day[f["date"]].append((f_ts, f))
    out = set()
    for same_day in by_day.values():
        same_day.sort(key=lambda pair: pair[0])
        for i, (t0, _) in enumerate(same_day):
            window = [rec for ts, rec in same_day if abs((ts - t0).total_seconds()) <= window_sec]
            if len({w["symbol"] for w in window}) >= min_symbols:
                out.update(w["id"] for w in window)
    return out


def attribute(fills, registry, *, refs=None, levels=None, reasons=None,
              snapshot_dates=None, respect_manual=True, journal_slack_days=2):
    """Run ORIGIN_CHAIN over fills, mutating origin/exec_via fields in place.

    origin and exec_via are deliberately independent. 2026-06-18 is the case that
    forces this: nine symbols were sold by hand in the App inside an hour, but the
    journal records the cut list as coming from plan v2 — system decision, manual
    execution. Inferring origin from execution fingerprints would have scored that
    session, the largest single alpha event in the book, as a discretionary trade.
    """
    symbols = {f["underlying"] if f["is_option"] else f["symbol"] for f in fills}
    refs = refs if refs is not None else plan_order_refs()
    levels = levels if levels is not None else plan_ladder_levels(symbols=symbols)
    reasons = reasons if reasons is not None else journal_reasons(symbols=symbols)
    snapshot_dates = snapshot_dates or set()
    bursts = _burst_ids(fills)

    reason_idx = defaultdict(list)
    for jdate, syms, verdict, snippet in reasons:
        for s in syms:
            reason_idx[s].append((jdate, verdict, snippet))

    for rec in fills:
        sym = rec["underlying"] if rec["is_option"] else rec["symbol"]
        hit = _match_registry(rec, registry)

        # ── exec_via: how the order reached the market ──────────────────────
        if hit:
            rec["exec_via"] = "gtc-ladder"
            rec["order_id"] = hit["order_id"]
        elif rec["is_option"] or rec["id"] in bursts or rec.get("avg_price_trade"):
            rec["exec_via"] = "manual-app"
        else:
            rec["exec_via"] = "unknown"

        if respect_manual and rec.get("origin_source") == "manual":
            continue

        # ── origin: who made the decision ──────────────────────────────────
        origin = conf = evidence = source = None
        if hit:
            num = hit["order_id"].split("-")[-1]
            if num in refs:
                origin, conf, source = "system", "high", "order_id"
                evidence = f"order {hit['order_id']} @${hit['limit_price']} recorded in plan.md"
            else:
                origin, conf, source = "user", "high", "order_id"
                evidence = f"order {hit['order_id']} @${hit['limit_price']} absent from plan.md"
        elif rec["date"] in snapshot_dates:
            origin, conf, source = "user", "high", "no_resting_order"
            evidence = "order snapshot covers this date yet no resting order matched"

        if origin is None:
            # Same-date evidence wins. Without that preference a symbol traded twice
            # in a week cross-contaminates: MU's 2026-06-18 fill matched the 06-16
            # journal row for a different, larger MU sale.
            cands = []
            for jdate, verdict, snippet in reason_idx.get(sym, []):
                delta = abs((date.fromisoformat(jdate) - date.fromisoformat(rec["date"])).days)
                if delta > journal_slack_days:
                    continue
                qtys = [float(q) for q in _QTY_IN_TEXT.findall(snippet)]
                qty_ok = (not qtys) or any(
                    abs(q - rec["qty"]) <= max(1.0, rec["qty"] * 0.25) for q in qtys
                )
                cands.append((delta, 0 if qty_ok else 1, verdict, jdate, snippet))
            cands.sort(key=lambda c: (c[1], c[0]))
            if cands and not (cands[0][0] > 0 and cands[0][1] == 1):
                _, _, verdict, jdate, snippet = cands[0]
                origin, conf, source = verdict, "high", "journal"
                conf = "high" if cands[0][0] == 0 else "low"
                evidence = f"journal {jdate}{'' if cands[0][0] == 0 else f' (±{cands[0][0]}d)'}: {snippet}"

        if origin is None and not rec["is_option"]:
            for lvl in levels.get(sym, ()):
                if abs(rec["price"] - lvl) < max(0.02, lvl * 0.001):
                    origin, conf, source = "system", "low", "ladder_price"
                    evidence = f"fill price matches plan.md ladder level ${lvl}"
                    break

        rec["origin"] = origin or "unknown"
        rec["origin_confidence"] = conf or "low"
        rec["origin_evidence"] = evidence or "no plan.md ref, journal reason, or ladder match"
        rec["origin_source"] = source or "none"
    return fills


# ── EOD prices ──────────────────────────────────────────────────────────────
def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.split("#")[0].strip().strip("'\""))


def _price_cache():
    if PRICE_CACHE.exists():
        try:
            return json.loads(PRICE_CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_price_cache(cache):
    PRICE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PRICE_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def eod_series(eodhd_symbol, start, end, cache=None, token=None):
    """{'YYYY-MM-DD': close} for one EODHD symbol, memoised on disk."""
    import requests

    cache = cache if cache is not None else _price_cache()
    key = f"{eodhd_symbol}|{start}|{end}"
    if key in cache:
        return cache[key]
    token = token or os.environ.get("EODHD_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("EODHD_API_TOKEN not set — cannot score alpha")
    resp = requests.get(
        f"{EODHD_BASE}/eod/{eodhd_symbol}",
        params={"api_token": token, "from": start, "to": end, "fmt": "json", "period": "d"},
        timeout=30,
    )
    resp.raise_for_status()
    series = {row["date"]: float(row["adjusted_close"] or row["close"])
              for row in resp.json() if row.get("date")}
    cache[key] = series
    _save_price_cache(cache)
    return series


def _asof_close(series, day):
    """Last close at or before `day` (handles weekends/holidays)."""
    keys = sorted(k for k in series if k <= day)
    return series[keys[-1]] if keys else None


def _daily_returns(series):
    """{date: pct_change} from a {date: close} series."""
    days = sorted(series)
    out = {}
    for prev, cur in zip(days, days[1:]):
        if series[prev]:
            out[cur] = series[cur] / series[prev] - 1
    return out


# ── beta ────────────────────────────────────────────────────────────────────
BETA_WINDOW_DAYS = 252        # ~1 trading year
BETA_MIN_OBS = 40             # below this the estimate is noise → fall back to 1.0
BETA_CAP = 5.0                # guard against a single bad print blowing up the fit


def regression_beta(stock_series, bench_series, *, end=None, window=BETA_WINDOW_DAYS):
    """Beta of a stock against THE BENCHMARK IT IS SCORED AGAINST.

    This is the whole point: broker-supplied betas are measured against a broad
    index. Applying a SPY-beta to an SMH-relative return over-adjusts semis badly —
    SMH itself carries roughly 1.5-1.8x SPY beta, so a semi's beta versus SMH is far
    below its beta versus SPY. Scoring with the wrong beta was what made the 2026-06-18
    de-risking look like +$7.6k of stock-selection alpha when much of it was simply
    removing beta before a drawdown.

    Returns (beta, n_obs). Falls back to (1.0, n) when there is too little overlap,
    which degrades to the naive benchmark-difference alpha rather than to nonsense.
    """
    sr, br = _daily_returns(stock_series), _daily_returns(bench_series)
    days = sorted(set(sr) & set(br))
    if end:
        days = [d for d in days if d <= end]
    days = days[-window:]
    n = len(days)
    if n < BETA_MIN_OBS:
        return 1.0, n
    xs = [br[d] for d in days]
    ys = [sr[d] for d in days]
    mx = sum(xs) / n
    my = sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    if var <= 0:
        return 1.0, n
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
    return max(-BETA_CAP, min(BETA_CAP, beta)), n


# ── alpha scoring ───────────────────────────────────────────────────────────
def _load_series(symbols, start, today, cache=None):
    """{symbol: {date: close}} with benchmarks always included."""
    cache = cache if cache is not None else _price_cache()
    series = {}
    for sym in sorted(set(symbols) | {BENCH_DEFAULT[:-3], BENCH_SEMI[:-3]}):
        try:
            series[sym] = eod_series(f"{sym}.US", start, today, cache=cache)
        except Exception as exc:                              # noqa: BLE001
            series[sym] = {}
            print(f"⚠️  {sym}: {exc}", file=sys.stderr)
    return series


def score(fills, *, since=None, asof=None, skip_options=True, beta_start=None):
    """Attach benchmark-adjusted alpha to each scorable fill.

    Two numbers per fill, and the beta-adjusted one is the answer:
      alpha       = stock_ret - bench_ret            (naive, beta=1 assumed)
      alpha_beta  = stock_ret - beta * bench_ret     (isolates selection skill)

    Both are negated for sells: a good sell is one where the thing you sold
    underperformed. The naive figure is retained only so the size of the beta
    contamination stays visible — selling a beta-3.7 name into a decline earns a
    large naive alpha while adding no selection skill at all.
    """
    load_env()
    today = _today(asof).isoformat()
    rows = [f for f in fills
            if (not since or f["date"] >= since)
            and not (skip_options and f["is_option"])]
    if not rows:
        return []
    # Beta needs a long history even when scoring a short window.
    hist_start = beta_start or min(f["date"] for f in rows)
    hist_start = min(hist_start, (_today(asof) - timedelta(days=520)).isoformat())
    need = {(f["underlying"] if f["is_option"] else f["symbol"]) for f in rows}
    series = _load_series(need, hist_start, today)

    betas = {}
    for f in rows:
        sym = f["underlying"] if f["is_option"] else f["symbol"]
        bench = benchmark_for(sym)[:-3]
        if (sym, bench) not in betas:
            betas[(sym, bench)] = regression_beta(
                series.get(sym, {}), series.get(bench, {}), end=today)

    scored = []
    for f in rows:
        sym = f["underlying"] if f["is_option"] else f["symbol"]
        bench = benchmark_for(sym)[:-3]
        now = _asof_close(series.get(sym, {}), today)
        b_now = _asof_close(series.get(bench, {}), today)
        b_then = _asof_close(series.get(bench, {}), f["date"])
        if not (now and b_now and b_then):
            f["alpha"] = f["alpha_beta"] = None
            continue
        beta, n_obs = betas[(sym, bench)]
        stock_ret = now / f["split_adj_price"] - 1
        bench_ret = b_now / b_then - 1
        naive = stock_ret - bench_ret
        adj = stock_ret - beta * bench_ret
        flip = 1 if f["side"] == "BOUGHT" else -1
        f["alpha"] = round(flip * naive, 6)
        f["alpha_beta"] = round(flip * adj, 6)
        f["beta"] = round(beta, 3)
        f["beta_obs"] = n_obs
        f["benchmark"] = bench
        f["price_now"] = now
        scored.append(f)
    return scored


def aggregate(scored, key_fn, field="alpha_beta"):
    """Weight alpha by dollars at risk. `field` selects beta-adjusted vs naive."""
    buckets = defaultdict(list)
    for f in scored:
        buckets[key_fn(f)].append(f)
    out = {}
    for k, group in sorted(buckets.items(), key=lambda kv: str(kv[0])):
        notional = sum(g["notional"] for g in group)
        if notional <= 0:
            continue
        dollars = sum(g[field] * g["notional"] for g in group)
        naive_dollars = sum(g["alpha"] * g["notional"] for g in group)
        out[str(k)] = {
            "n": len(group),
            "alpha_weighted_pct": round(dollars / notional * 100, 2),
            "win_rate_pct": round(100 * sum(1 for g in group if g[field] > 0) / len(group), 1),
            "alpha_dollars": round(dollars, 2),
            "naive_alpha_dollars": round(naive_dollars, 2),
            "beta_contamination_dollars": round(naive_dollars - dollars, 2),
            "avg_beta": round(sum(g.get("beta", 1.0) * g["notional"] for g in group) / notional, 2),
            "notional": round(notional, 2),
        }
    return out


# ── holding alpha ───────────────────────────────────────────────────────────
def holding_alpha(positions, fills, *, window_days=90, asof=None):
    """Is holding each position still adding value, and was the original entry good?

    Two views per position, because they answer different questions:
      trailing  — last `window_days` versus the benchmark. Decision-relevant: should
                  this still be held? Available for every position.
      inception — average cost basis to today. Historical: was the entry good?
                  Only where the ledger's fills reconcile to the current share count;
                  lots opened before the account history began cannot be dated.

    Without this, a fill-level alpha metric silently rewards churn and scores a
    position held correctly for a year as contributing nothing. The book's two
    winners (MU +66%, CRWD +58%) were earned by holding, and no transaction metric
    can see that.
    """
    load_env()
    today = _today(asof)
    today_s = today.isoformat()
    then_s = (today - timedelta(days=window_days)).isoformat()
    eq = positions["equities"]
    hist_start = min(then_s, (today - timedelta(days=520)).isoformat())
    series = _load_series(eq.keys(), hist_start, today_s)

    # Entry date must be COST-WEIGHTED, not the earliest buy. Firstrade's unit_cost
    # blends every lot, so pairing it with the first purchase date charges the
    # position with benchmark movement it was never exposed to — that mispricing is
    # what produced impossible readings like MU -77% and LRCX -127%.
    net, wsum, csum = defaultdict(float), defaultdict(float), defaultdict(float)
    for f in sorted(fills, key=lambda r: r["date"]):
        if f["is_option"]:
            continue
        s = f["symbol"]
        q = split_adjust_qty(s, f["date"], f["qty"])
        net[s] += q if f["side"] == "BOUGHT" else -q
        if f["side"] == "BOUGHT":
            cost = q * f["split_adj_price"]
            wsum[s] += date.fromisoformat(f["date"]).toordinal() * cost
            csum[s] += cost
    entry_date = {s: date.fromordinal(round(wsum[s] / csum[s])).isoformat()
                  for s in csum if csum[s] > 0}

    rows = []
    for sym, pos in sorted(eq.items()):
        bench = benchmark_for(sym)[:-3]
        ss, bs = series.get(sym, {}), series.get(bench, {})
        beta, n_obs = regression_beta(ss, bs, end=today_s)
        p_now, b_now = _asof_close(ss, today_s), _asof_close(bs, today_s)
        row = {"symbol": sym, "qty": pos["qty"], "benchmark": bench,
               "beta": round(beta, 3), "beta_obs": n_obs,
               "market_value": round(pos["market_value"], 2),
               "weight_pct": round(100 * pos["market_value"] / positions["equity_value"], 2)
               if positions["equity_value"] else None}

        p_then, b_then = _asof_close(ss, then_s), _asof_close(bs, then_s)
        if p_now and p_then and b_now and b_then:
            sr, br = p_now / p_then - 1, b_now / b_then - 1
            row["trailing"] = {
                "days": window_days,
                "return_pct": round(sr * 100, 1),
                "bench_return_pct": round(br * 100, 1),
                "alpha_beta_pct": round((sr - beta * br) * 100, 1),
                "alpha_dollars": round((sr - beta * br) * pos["market_value"], 2),
            }

        reconciles = abs(net.get(sym, 0) - pos["qty"]) < max(1.0, pos["qty"] * 0.05)
        if reconciles and sym in entry_date and pos["unit_cost"] > 0:
            inc = entry_date[sym]
            b_inc = _asof_close(bs, inc)
            if p_now and b_inc and b_inc > 0:
                sr = p_now / pos["unit_cost"] - 1
                br = b_now / b_inc - 1
                # Log space for the beta leg: beta scales periodic returns, so
                # beta x a large cumulative return is not an expected return and
                # blows up over long holds.
                la = math.log1p(sr) - beta * math.log1p(br)
                row["inception"] = {
                    "cost_weighted_entry": inc,
                    "days_held": (today - date.fromisoformat(inc)).days,
                    "unit_cost": pos["unit_cost"],
                    "return_pct": round(sr * 100, 1),
                    "bench_return_pct": round(br * 100, 1),
                    "excess_return_pct": round((sr - br) * 100, 1),
                    "alpha_beta_pct": round((math.exp(la) - 1) * 100, 1),
                    "alpha_dollars": round((math.exp(la) - 1) * pos["market_value"], 2),
                }
        else:
            row["inception_unavailable"] = (
                "lots predate the account history" if not reconciles else "no cost basis")
        rows.append(row)
    return rows


# ── beta capture ────────────────────────────────────────────────────────────
def reconstruct_holdings(positions, fills, *, start, asof=None):
    """{date: {symbol: qty}} walked backward from today's share count.

    Flows are removed by construction, so returns computed from this are clean.
    Positions whose earliest lots predate the account history are still correct here:
    those lots never moved inside the window, so subtracting the window's fills is
    all that is required.
    """
    today = _today(asof)
    qty = {s: v["qty"] for s, v in positions["equities"].items()}
    by_day = defaultdict(list)
    for f in fills:
        if not f["is_option"] and start <= f["date"] <= today.isoformat():
            by_day[f["date"]].append(f)

    out, cur = {}, dict(qty)
    day = today
    while day.isoformat() >= start:
        d = day.isoformat()
        out[d] = dict(cur)
        for f in by_day.get(d, []):
            q = split_adjust_qty(f["symbol"], d, f["qty"])
            # undo the fill to get the prior day's holding
            cur[f["symbol"]] = cur.get(f["symbol"], 0.0) + (-q if f["side"] == "BOUGHT" else q)
        day -= timedelta(days=1)
    return out


def beta_capture(positions, fills, *, window_days=180, asof=None, bench=None):
    """Did the book capture its beta when the benchmark rose, and shed it when it fell?

    Alpha answers "is there skill". This answers the other half: "are we actually
    participating". They can disagree — the 2026-06-18 de-risking earned real alpha
    by cutting beta before a drawdown, but the identical decision in a rally shows up
    here as upside left on the table. Reporting only alpha would score beta timing as
    free.

    Returns up/down beta from separate regressions plus the intercept alpha. Measures
    the equity sleeve only; cash drag is reported alongside, not folded in.
    """
    load_env()
    today = _today(asof)
    today_s = today.isoformat()
    start = (today - timedelta(days=window_days)).isoformat()
    eq = positions["equities"]
    series = _load_series(eq.keys(), start, today_s)
    holdings = reconstruct_holdings(positions, fills, start=start, asof=asof)
    benches = [bench] if bench else [BENCH_DEFAULT[:-3], BENCH_SEMI[:-3]]

    # flow-free daily portfolio return: prior-day weights x today's stock returns
    rets = {s: _daily_returns(series.get(s, {})) for s in eq}
    days = sorted(d for d in holdings if d > start)
    port = {}
    for d in days:
        prev = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
        held = holdings.get(prev) or holdings.get(d) or {}
        vals, contrib = 0.0, 0.0
        for s, q in held.items():
            px = _asof_close(series.get(s, {}), prev)
            r = rets.get(s, {}).get(d)
            if not px or q <= 0 or r is None:
                continue
            vals += px * q
            contrib += px * q * r
        if vals > 0:
            port[d] = contrib / vals

    out = {"window_days": window_days, "trading_days": len(port),
           "equity_sleeve_only": True,
           "cash_pct_now": round(100 * positions["cash"] / positions["total_account_value"], 2)
           if positions["total_account_value"] else None}
    for b in benches:
        br = _daily_returns(series.get(b, {}))
        pairs = [(br[d], port[d]) for d in sorted(port) if d in br]
        if len(pairs) < BETA_MIN_OBS:
            out[b] = {"error": f"only {len(pairs)} overlapping days"}
            continue

        def _fit(sel):
            xs = [x for x, _ in sel]
            ys = [y for _, y in sel]
            n = len(xs)
            if n < 8:
                return None
            mx, my = sum(xs) / n, sum(ys) / n
            var = sum((x - mx) ** 2 for x in xs)
            if var <= 0:
                return None
            beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
            alpha_bps = (my - beta * mx) * 10000
            return {"n_days": n, "beta": round(beta, 3),
                    "alpha_per_day_bps": round(alpha_bps, 2),
                    "alpha_cumulative_pct": round(alpha_bps / 10000 * n * 100, 1),
                    # mean daily moves, NOT a compounded return — the product over a
                    # sign-filtered subset is not an economically meaningful figure
                    "mean_bench_move_pct": round(mx * 100, 3),
                    "mean_port_move_pct": round(my * 100, 3)}

        up = _fit([p for p in pairs if p[0] > 0])
        dn = _fit([p for p in pairs if p[0] < 0])
        full = _fit(pairs)
        entry = {"full": full, "up_days": up, "down_days": dn}
        if up and dn and dn["beta"]:
            ratio = up["beta"] / dn["beta"]
            entry["capture_ratio_up_over_down"] = round(ratio, 2)
            entry["reading"] = (
                "capturing upside, shedding downside — the profile you want"
                if ratio > 1.05 else
                "symmetric" if ratio >= 0.95 else
                "absorbing more downside beta than it captures on the way up")
            # Harvesting into strength and laddering into weakness mechanically pushes
            # this below 1: exposure is cut as the benchmark rises and added as it
            # falls. Alpha alone cannot see that cost, which is why it is reported here.
            entry["structural_note"] = (
                "tiered profit-taking sells into strength while buy ladders add into "
                "weakness; both push up-beta down and down-beta up by construction"
                if ratio < 0.95 else None)
        out[b] = entry
    return out


def _prod(rets):
    v = 1.0
    for r in rets:
        v *= (1 + r)
    return v


# ── position flags: the deferral register ───────────────────────────────────
# Measured 2026-07-25: the single most expensive mechanism in the book is a position
# being flagged as deteriorating and then never actioned. TSLA LEAPS was marked a
# 降桶候選 on 07-01 and deferred through 07-08, 07-09 ("solved" by writing a PMCC
# instead of deciding), 07-13 ("on-track"), 07-24 (rolled) → -52.7% / -$6,399. ON was
# flagged 06-26 with an explicit 勿再向下加碼, then added to on 07-06 → -$2,301.
# Together -$8,700.
#
# The leak is that both flags lived only in briefing prose. Their thesis-ledger
# entries carry history: 0 — nothing counted the deferrals, so every briefing restated
# the same warning as if it were new. This register makes an owed decision a piece of
# data, counts deferrals, and prices what the delay has cost so far.
FORCED_AFTER_DEFERRALS = 3


def load_flags(path=DEFAULT_FLAGS):
    p = Path(path)
    if not p.exists():
        return {"flags": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save_flags(data, path=DEFAULT_FLAGS):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def flag_id(ticker, slug):
    return f"{ticker.strip().upper()}:{re.sub(r'[^a-z0-9-]+', '-', slug.strip().lower()).strip('-')}"


def open_flag(data, *, ticker, slug, reason, deadline, price_at_flag=None, asof=None):
    fid = flag_id(ticker, slug)
    asof = asof or date.today().isoformat()
    for f in data["flags"]:
        if f["id"] == fid and f["status"] == "open":
            return {"action": "already_open", "id": fid, "deferrals": f["deferrals"]}
    data["flags"].append({
        "id": fid, "ticker": ticker.strip().upper(), "slug": slug,
        "reason": reason, "opened": asof, "deadline": deadline,
        "price_at_flag": price_at_flag, "deferrals": 0,
        "status": "open", "history": [],
    })
    return {"action": "opened", "id": fid, "deadline": deadline}


def defer_flag(data, *, flag_id_, to, reason, asof=None):
    asof = asof or date.today().isoformat()
    f = next((x for x in data["flags"] if x["id"] == flag_id_ and x["status"] == "open"), None)
    if f is None:
        return {"action": "not_found", "id": flag_id_}
    f["deferrals"] += 1
    old, f["deadline"] = f["deadline"], to
    f["history"].append({"date": asof, "event": "deferred",
                         "from": old, "to": to, "reason": reason})
    forced = f["deferrals"] >= FORCED_AFTER_DEFERRALS
    if forced:
        f["status"] = "forced"
    return {"action": "deferred", "id": flag_id_, "deferrals": f["deferrals"],
            "forced": forced,
            "requirement": (f"deferral #{f['deferrals']} — at {FORCED_AFTER_DEFERRALS} the "
                            "position must be trimmed by a third or the flag explicitly "
                            "withdrawn with a written reason") if forced else None}


def resolve_flag(data, *, flag_id_, action, note, realized_pnl=None, asof=None):
    asof = asof or date.today().isoformat()
    f = next((x for x in data["flags"] if x["id"] == flag_id_ and x["status"] in
              ("open", "forced")), None)
    if f is None:
        return {"action": "not_found", "id": flag_id_}
    f["status"] = "resolved"
    f["history"].append({"date": asof, "event": "resolved", "action": action,
                         "note": note, "realized_pnl": realized_pnl})
    return {"action": "resolved", "id": flag_id_, "deferrals": f["deferrals"],
            "resolution": action}


def flag_report(data, positions, fills=None, *, asof=None):
    """Open flags with days outstanding, deferral count, and what the delay has cost.

    Three cost views, because they answer different things:
      cost_since_flag        equity held through the flag, priced from the flag date
      option_unrealized      option-backed flags (TSLA LEAPS) — the position is a
                             contract, so the underlying's move understates it
      post_flag_fills        anything bought AFTER the flag was raised. ON was told
                             勿再向下加碼 on 06-26 and added 12 shares on 07-06; this
                             is where that shows up.
    """
    load_env()
    today = _today(asof)
    today_s = today.isoformat()
    live = [f for f in data["flags"] if f["status"] in ("open", "forced")]
    if not live:
        return []
    eq = positions["equities"]
    opts = positions.get("options_by_underlying") or {}
    syms = {f["ticker"] for f in live}
    series = _load_series(syms & set(eq) | (syms & set(opts)),
                          min(f["opened"] for f in live), today_s)
    by_ticker = defaultdict(list)
    for f in (fills or []):
        if not f["is_option"]:
            by_ticker[f["symbol"]].append(f)

    rows = []
    for f in live:
        tkr = f["ticker"]
        pos = eq.get(tkr)
        row = {k: f[k] for k in ("id", "ticker", "reason", "opened", "deadline",
                                 "deferrals", "status")}
        row["days_open"] = (today - date.fromisoformat(f["opened"])).days
        row["overdue_days"] = max(0, (today - date.fromisoformat(f["deadline"])).days)
        row["forced"] = f["deferrals"] >= FORCED_AFTER_DEFERRALS
        p0 = f.get("price_at_flag") or _asof_close(series.get(tkr, {}), f["opened"])
        p1 = _asof_close(series.get(tkr, {}), today_s) or (pos or {}).get("last")
        if p0 and p1:
            row["underlying_at_flag"] = round(p0, 2)
            row["underlying_now"] = round(p1, 2)
            row["underlying_move_pct"] = round((p1 / p0 - 1) * 100, 1)
        if pos and p0 and p1:
            row["cost_since_flag"] = round((p1 - p0) * pos["qty"], 2)
        if tkr in opts:
            row["option_legs"] = opts[tkr]
            row["option_unrealized"] = round(sum(o["unrealized"] for o in opts[tkr]), 2)
        if not pos and tkr not in opts:
            row["note"] = "position no longer held — resolve this flag"

        after = [x for x in by_ticker.get(tkr, []) if x["date"] > f["opened"]]
        if after:
            adds = [x for x in after if x["side"] == "BOUGHT"]
            spent = sum(x["qty"] * x["split_adj_price"] for x in adds)
            worth = sum(x["qty"] * p1 for x in adds) if p1 else None
            row["post_flag_fills"] = {
                "buys": len(adds),
                "shares_added": round(sum(x["qty"] for x in adds), 2),
                "spent": round(spent, 2),
                "worth_now": round(worth, 2) if worth is not None else None,
                "pnl": round(worth - spent, 2) if worth is not None else None,
                "dates": sorted({x["date"] for x in adds}),
                "verdict": "added after the flag was raised" if adds else None,
            }
        rows.append(row)
    rows.sort(key=lambda r: (not r["forced"], -(r.get("overdue_days") or 0),
                             (r.get("option_unrealized") or 0) + (r.get("cost_since_flag") or 0)))
    return rows


# ── file IO ─────────────────────────────────────────────────────────────────
def load_fills(path=DEFAULT_LEDGER):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def save_fills(fills, path=DEFAULT_LEDGER):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".trade-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for rec in sorted(fills, key=lambda r: (r["date"], r.get("exec_time") or "", r["symbol"])):
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, str(p))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def load_registry(path=DEFAULT_REGISTRY):
    p = Path(path)
    if not p.exists():
        return {"orders": {}, "snapshots": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save_registry(reg, path=DEFAULT_REGISTRY):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


# ── CLI ─────────────────────────────────────────────────────────────────────
EXIT_OK, EXIT_GENERIC = 0, 1


def _emit(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_snapshot_orders(args):
    reg = load_registry(args.registry)
    seen = _today(args.asof).isoformat()
    payload = fetch_orders()
    fresh = parse_orders(payload, seen)
    added, updated = 0, 0
    for oid, entry in fresh.items():
        if oid in reg["orders"]:
            reg["orders"][oid].update({"last_seen": seen, "state": entry["state"],
                                       "filled": entry["filled"]})
            updated += 1
        else:
            reg["orders"][oid] = entry
            added += 1
    gone = [o for o, e in reg["orders"].items()
            if e["last_seen"] < seen and e.get("state") == "ORDER-SUBMITTED"]
    for oid in gone:
        reg["orders"][oid]["state"] = "GONE-FILLED-OR-CANCELLED"
    if seen not in reg["snapshots"]:
        reg["snapshots"].append(seen)
        reg["snapshots"].sort()
    save_registry(reg, args.registry)
    _emit({"snapshot_date": seen, "open_orders": len(fresh), "new": added,
           "refreshed": updated, "left_book": gone,
           "snapshot_days_recorded": len(reg["snapshots"])})


def cmd_ingest(args):
    window = args.date_range
    if args.history_file:
        payload = json.loads(Path(args.history_file).read_text(encoding="utf-8"))
        if "items" not in payload:                 # MCP wrapper {acct: {...}}
            payload = next(iter(payload.values()))
        window = f"file:{Path(args.history_file).name}"
    elif args.date_from:
        date_to = args.date_to or _today(args.asof).isoformat()
        payload = fetch_history(custom=[args.date_from, date_to])
        window = f"{args.date_from}..{date_to}"
    else:
        payload = fetch_history(date_range=args.date_range)

    incoming = parse_history(payload)
    existing = {f["id"]: f for f in load_fills(args.ledger)}
    added = 0
    for rec in incoming:
        if rec["id"] in existing:
            keep = {k: existing[rec["id"]][k] for k in
                    ("origin", "origin_confidence", "origin_evidence", "origin_source",
                     "thesis_id", "bucket", "note")
                    if k in existing[rec["id"]]}
            rec.update(keep)
        else:
            added += 1
        existing[rec["id"]] = rec
    save_fills(list(existing.values()), args.ledger)
    _emit({"fetched": len(incoming), "new": added, "ledger_total": len(existing),
           "range": window,
           "earliest": min((f["date"] for f in existing.values()), default=None),
           "latest": max((f["date"] for f in existing.values()), default=None)})


def cmd_backfill_origin(args):
    fills = load_fills(args.ledger)
    if not fills:
        _emit({"error": "ledger empty — run ingest first"})
        return EXIT_GENERIC
    reg = load_registry(args.registry)
    attribute(fills, reg["orders"], snapshot_dates=set(reg.get("snapshots", [])),
              respect_manual=not args.force)
    save_fills(fills, args.ledger)

    def _cov(rows):
        if not rows:
            return {"fills": 0}
        by_origin, by_source, by_exec = defaultdict(int), defaultdict(int), defaultdict(int)
        for f in rows:
            by_origin[f"{f['origin']}/{f['origin_confidence']}"] += 1
            by_source[f["origin_source"]] += 1
            by_exec[f.get("exec_via", "unknown")] += 1
        known = sum(1 for f in rows if f["origin"] != "unknown")
        return {
            "fills": len(rows),
            "origin_attributed": known,
            "origin_coverage_pct": round(100 * known / len(rows), 1),
            "origin_high_confidence": sum(1 for f in rows if f["origin"] != "unknown"
                                          and f["origin_confidence"] == "high"),
            "by_origin": dict(by_origin),
            "by_evidence_source": dict(by_source),
            "by_exec_via": dict(by_exec),
        }

    # Journals only start 2026-06-04, so whole-ledger coverage understates how well
    # attribution works where evidence actually exists. Report both.
    journal_start = min((p.stem for p in (ROOT / "journal").glob("*.md")), default=None)
    out = {"all": _cov(fills)}
    if journal_start:
        out["journaled_window"] = {
            "since": journal_start,
            **_cov([f for f in fills if f["date"] >= journal_start]),
        }
    if args.since:
        out["since_" + args.since] = _cov([f for f in fills if f["date"] >= args.since])
    out["note"] = ("exec_via is an independent axis and never implies origin; "
                   "see `stats` → origin_chain")
    out["unknown_sample"] = [
        {"id": f["id"], "date": f["date"], "symbol": f["symbol"], "side": f["side"],
         "price": f["price"], "exec_via": f.get("exec_via")}
        for f in fills if f["origin"] == "unknown"
        and (not journal_start or f["date"] >= journal_start)][: args.limit]
    _emit(out)
    return EXIT_OK


def cmd_score(args):
    fills = load_fills(args.ledger)
    scored = score(fills, since=args.since, asof=args.asof,
                   skip_options=not args.include_options)
    keys = {
        "origin": lambda f: f["origin"],
        "side": lambda f: f["side"],
        "origin-side": lambda f: f"{f['origin']} {'買' if f['side'] == 'BOUGHT' else '賣'}",
        "symbol": lambda f: f["symbol"],
        "bucket": lambda f: f.get("bucket") or "unassigned",
        "confidence": lambda f: f"{f['origin']}/{f['origin_confidence']}",
        "model": lambda f: f.get("model") or "unrecorded",
    }
    hi = [f for f in scored if f["origin_confidence"] == "high"]
    in_window = [f for f in fills
                 if (not args.since or f["date"] >= args.since)
                 and (args.include_options or not f["is_option"])]
    _emit({
        "scored": len(scored),
        "unscorable": len(in_window) - len(scored),
        "options_excluded": sum(1 for f in fills
                                if f["is_option"] and (not args.since or f["date"] >= args.since))
        if not args.include_options else 0,
        "asof": _today(args.asof).isoformat(),
        "metric": ("alpha_beta = stock_ret − beta × bench_ret, beta regressed on the same "
                   "benchmark used for scoring. naive_alpha_dollars assumes beta=1; the gap "
                   "between them is beta contamination, not skill."),
        f"by_{args.by}": aggregate(scored, keys[args.by]),
        f"by_{args.by}_high_confidence_only": aggregate(hi, keys[args.by]),
        "best": [_brief(f) for f in sorted(
            scored, key=lambda f: -f["alpha_beta"] * f["notional"])[:args.limit]],
        "worst": [_brief(f) for f in sorted(
            scored, key=lambda f: f["alpha_beta"] * f["notional"])[:args.limit]],
    })


def _brief(f):
    return {"date": f["date"], "symbol": f["symbol"], "side": f["side"],
            "qty": f["qty"], "price": f["price"], "origin": f["origin"],
            "beta": f.get("beta"),
            "alpha_beta_pct": round(f["alpha_beta"] * 100, 1),
            "alpha_beta_dollars": round(f["alpha_beta"] * f["notional"]),
            "naive_alpha_pct": round(f["alpha"] * 100, 1),
            "evidence": f.get("origin_evidence", "")[:110]}


def cmd_stats(args):
    fills = load_fills(args.ledger)
    reg = load_registry(args.registry)
    if not fills:
        _emit({"error": "ledger empty — run ingest first"})
        return EXIT_GENERIC
    known = sum(1 for f in fills if f.get("origin", "unknown") != "unknown")
    open_orders = [e for e in reg["orders"].values() if e.get("state") == "ORDER-SUBMITTED"]
    jstart = min((p.stem for p in (ROOT / "journal").glob("*.md")), default=None)
    jwin = [f for f in fills if jstart and f["date"] >= jstart]
    jknown = sum(1 for f in jwin if f.get("origin", "unknown") != "unknown")
    _emit({
        "fills": len(fills),
        "equity_fills": sum(1 for f in fills if not f["is_option"]),
        "option_fills": sum(1 for f in fills if f["is_option"]),
        "date_span": [min(f["date"] for f in fills), max(f["date"] for f in fills)],
        "attribution_coverage_pct": round(100 * known / len(fills), 1),
        "attribution_coverage_journaled_pct": round(100 * jknown / len(jwin), 1) if jwin else None,
        "journaled_since": jstart,
        "coverage_note": ("whole-ledger coverage is floored by pre-journal fills "
                          "(no evidence exists for them); track the journaled figure, "
                          "and expect order-registry snapshots to drive it toward 100% "
                          "for fills from the first snapshot onward"),
        "origin_counts": dict(sorted(
            ((k, sum(1 for f in fills if f.get("origin") == k)) for k in VALID_ORIGINS),
            key=lambda kv: -kv[1])),
        "order_registry": {"tracked": len(reg["orders"]), "currently_open": len(open_orders),
                           "snapshot_days": len(reg.get("snapshots", []))},
        "origin_chain": ORIGIN_CHAIN.strip().split("\n"),
    })
    return EXIT_OK


def cmd_orders(args):
    reg = load_registry(args.registry)
    today = _today(args.asof)
    rows = []
    for e in reg["orders"].values():
        if args.all or e.get("state") == "ORDER-SUBMITTED":
            placed = e.get("placed") or e.get("first_seen")
            try:
                age = (today - date.fromisoformat(placed)).days
            except (TypeError, ValueError):
                age = None
            rows.append({**{k: e[k] for k in ("order_id", "symbol", "transaction",
                                              "shares", "limit_price", "state")},
                         "placed": placed, "age_days": age,
                         "in_plan": (e["order_id"].split("-")[-1] in plan_order_refs())})
    rows.sort(key=lambda r: -(r["age_days"] or 0))
    _emit({"orders": rows, "count": len(rows),
           "stale_over_30d": [r["order_id"] for r in rows
                              if (r["age_days"] or 0) > 30 and r["state"] == "ORDER-SUBMITTED"]})


def cmd_holding_alpha(args):
    pos = fetch_positions()
    rows = holding_alpha(pos, load_fills(args.ledger),
                         window_days=args.window, asof=args.asof)
    def _agg(key):
        have = [r for r in rows if key in r]
        mv = sum(r["market_value"] for r in have)
        if not have or mv <= 0:
            return None
        return {"positions": len(have),
                "alpha_weighted_pct": round(
                    sum(r[key]["alpha_beta_pct"] * r["market_value"] for r in have) / mv, 2),
                "alpha_dollars": round(sum(r[key]["alpha_dollars"] for r in have), 2),
                "win_rate_pct": round(
                    100 * sum(1 for r in have if r[key]["alpha_beta_pct"] > 0) / len(have), 1),
                "market_value": round(mv, 2)}
    rows.sort(key=lambda r: -(r.get("trailing", {}).get("alpha_dollars") or 0))
    _emit({
        "asof": _today(args.asof).isoformat(),
        "equity_value": round(pos["equity_value"], 2),
        "cash_pct": round(100 * pos["cash"] / pos["total_account_value"], 2)
        if pos["total_account_value"] else None,
        "trailing_aggregate": _agg("trailing"),
        "inception_aggregate": _agg("inception"),
        "inception_unavailable": [r["symbol"] for r in rows if "inception" not in r],
        "inception_selection_bias_warning": (
            "the measurable subset skews to recently opened positions — long-held lots "
            "predate the account history and drop out, and those are disproportionately "
            "the winners. Read per-position, not as an aggregate."),
        "note": ("trailing answers 'should this still be held'; inception answers 'was the "
                 "entry good'. Holding alpha must sit beside trade alpha or the system "
                 "rewards churn and scores a correctly-held position as contributing nothing."),
        "positions": rows,
    })


def cmd_beta_capture(args):
    pos = fetch_positions()
    _emit(beta_capture(pos, load_fills(args.ledger),
                       window_days=args.window, asof=args.asof, bench=args.bench))


def cmd_flag(args):
    data = load_flags(args.flags)
    res = open_flag(data, ticker=args.ticker, slug=args.slug, reason=args.reason,
                    deadline=args.deadline, price_at_flag=args.price, asof=args.asof)
    save_flags(data, args.flags)
    _emit(res)
    return EXIT_OK if res["action"] == "opened" else EXIT_GENERIC


def cmd_defer(args):
    data = load_flags(args.flags)
    res = defer_flag(data, flag_id_=args.flag_id, to=args.to, reason=args.reason,
                     asof=args.asof)
    save_flags(data, args.flags)
    _emit(res)
    return EXIT_OK if res["action"] == "deferred" else EXIT_GENERIC


def cmd_resolve_flag(args):
    data = load_flags(args.flags)
    res = resolve_flag(data, flag_id_=args.flag_id, action=args.action, note=args.note,
                       realized_pnl=args.realized_pnl, asof=args.asof)
    save_flags(data, args.flags)
    _emit(res)
    return EXIT_OK if res["action"] == "resolved" else EXIT_GENERIC


def cmd_flags(args):
    data = load_flags(args.flags)
    rows = flag_report(data, fetch_positions(), load_fills(args.ledger), asof=args.asof)
    forced = [r for r in rows if r["forced"]]
    overdue = [r for r in rows if r["overdue_days"] > 0 and not r["forced"]]
    _emit({
        "open_flags": len(rows),
        "forced_action_required": [r["id"] for r in forced],
        "overdue": [r["id"] for r in overdue],
        "total_cost_since_flag": round(sum(
            (r.get("cost_since_flag") or 0) + (r.get("option_unrealized") or 0)
            for r in rows), 2),
        "total_post_flag_add_pnl": round(sum(
            (r.get("post_flag_fills") or {}).get("pnl") or 0 for r in rows), 2),
        "rule": (f"{FORCED_AFTER_DEFERRALS} deferrals forces a decision: trim a third, or "
                 "withdraw the flag in writing with a reason"),
        "why": ("flags that live only in prose get restated daily and never actioned — "
                "TSLA LEAPS -$6,399 and ON -$2,301 were both flagged and both deferred, "
                "and neither deferral was ever recorded anywhere"),
        "flags": rows,
    })
    return EXIT_OK


def cmd_annotate(args):
    fills = load_fills(args.ledger)
    hit = next((f for f in fills if f["id"] == args.fill_id), None)
    if not hit:
        _emit({"error": f"fill {args.fill_id} not found"})
        return EXIT_GENERIC
    hit["origin"] = args.origin
    hit["origin_confidence"] = "high"
    hit["origin_evidence"] = args.evidence
    hit["origin_source"] = "manual"
    if args.bucket:
        hit["bucket"] = args.bucket
    if args.thesis_id:
        hit["thesis_id"] = args.thesis_id
    # Which model produced a system decision, so `score --by model` can answer
    # empirically whether the expensive tier earns its cost — and so a later,
    # stronger model's disagreement can be checked against a track record rather
    # than assumed to be an improvement.
    if args.model:
        hit["model"] = args.model
    if args.effort:
        hit["effort"] = args.effort
    save_fills(fills, args.ledger)
    _emit({"updated": _brief_min(hit)})
    return EXIT_OK


def _brief_min(f):
    return {k: f.get(k) for k in ("id", "date", "symbol", "side", "origin",
                                  "origin_evidence", "bucket", "thesis_id",
                                  "model", "effort")}


def _build_parser():
    p = argparse.ArgumentParser(description="Trade ledger — fill attribution & alpha scoring")
    p.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    p.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    p.add_argument("--flags", default=str(DEFAULT_FLAGS))
    p.add_argument("--asof", default=None, help="override today (YYYY-MM-DD)")
    sub = p.add_subparsers(dest="cmd", required=True)

    fl = sub.add_parser("flag", help="register a position that owes a decision")
    fl.add_argument("--ticker", required=True)
    fl.add_argument("--slug", required=True, help="short kebab-case handle, e.g. leaps-derate")
    fl.add_argument("--reason", required=True)
    fl.add_argument("--deadline", required=True, help="YYYY-MM-DD by which a decision is due")
    fl.add_argument("--price", type=float, default=None, help="price at flag (else EOD close)")

    df = sub.add_parser("defer", help="push a flag's deadline out — counted, not free")
    df.add_argument("--id", dest="flag_id", required=True)
    df.add_argument("--to", required=True, help="new deadline YYYY-MM-DD")
    df.add_argument("--reason", required=True)

    rf = sub.add_parser("resolve-flag", help="close a flag with the action taken")
    rf.add_argument("--id", dest="flag_id", required=True)
    rf.add_argument("--action", required=True,
                    help="trimmed | exited | withdrawn | rolled | held-with-reason")
    rf.add_argument("--note", required=True)
    rf.add_argument("--realized-pnl", type=float, default=None, dest="realized_pnl")

    sub.add_parser("flags", help="open flags: days outstanding, deferrals, cost since raised")

    sub.add_parser("snapshot-orders", help="record currently resting orders (run each briefing)")

    i = sub.add_parser("ingest", help="pull fills from broker history into the ledger")
    i.add_argument("--range", dest="date_range", default="ly",
                   help="today|1w|1m|2m|mtd|ytd|ly (default ly)")
    i.add_argument("--from", dest="date_from", default=None, help="YYYY-MM-DD (implies custom range)")
    i.add_argument("--to", dest="date_to", default=None, help="YYYY-MM-DD")
    i.add_argument("--history-file", default=None, help="use a pre-dumped history JSON instead")

    b = sub.add_parser("backfill-origin", help="run the origin priority chain over all fills")
    b.add_argument("--force", action="store_true", help="also overwrite manual annotations")
    b.add_argument("--since", default=None, help="extra coverage breakdown from this date")
    b.add_argument("--limit", type=int, default=15)

    s = sub.add_parser("score", help="benchmark-adjusted alpha")
    s.add_argument("--by", default="origin",
                   choices=["origin", "side", "origin-side", "symbol", "bucket",
                            "confidence", "model"])
    s.add_argument("--since", default=None, help="YYYY-MM-DD")
    s.add_argument("--limit", type=int, default=5)
    s.add_argument("--include-options", action="store_true",
                   help="options are excluded by default (multi-leg structures score misleadingly)")

    ha = sub.add_parser("holding-alpha",
                        help="per-position holding alpha (trailing window + since inception)")
    ha.add_argument("--window", type=int, default=90, help="trailing window in days")

    bc = sub.add_parser("beta-capture",
                        help="up/down beta — is the book participating on the way up?")
    bc.add_argument("--window", type=int, default=180, help="lookback in days")
    bc.add_argument("--bench", default=None, help="single benchmark, e.g. SMH (default: both)")

    sub.add_parser("stats", help="coverage and ledger health")

    o = sub.add_parser("orders", help="resting orders with age + dead-order flags")
    o.add_argument("--all", action="store_true", help="include orders that left the book")

    a = sub.add_parser("annotate", help="manually set a fill's decision origin")
    a.add_argument("--id", dest="fill_id", required=True)
    a.add_argument("--origin", required=True, choices=sorted(VALID_ORIGINS))
    a.add_argument("--evidence", required=True)
    a.add_argument("--bucket", default=None)
    a.add_argument("--thesis-id", dest="thesis_id", default=None)
    a.add_argument("--model", default=None,
                   help="model that made the call, e.g. claude-opus-4-8 (system origin only)")
    a.add_argument("--effort", default=None, help="reasoning effort at decision time")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)
    try:
        handler = {
            "snapshot-orders": cmd_snapshot_orders,
            "ingest": cmd_ingest,
            "backfill-origin": cmd_backfill_origin,
            "score": cmd_score,
            "holding-alpha": cmd_holding_alpha,
            "beta-capture": cmd_beta_capture,
            "stats": cmd_stats,
            "orders": cmd_orders,
            "flag": cmd_flag,
            "defer": cmd_defer,
            "resolve-flag": cmd_resolve_flag,
            "flags": cmd_flags,
            "annotate": cmd_annotate,
        }[args.cmd]
        return handler(args) or EXIT_OK
    except Exception as exc:                                   # noqa: BLE001
        _emit({"error": str(exc), "cmd": args.cmd})
        return EXIT_GENERIC


if __name__ == "__main__":
    sys.exit(main())
