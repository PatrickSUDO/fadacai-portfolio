#!/usr/bin/env python3
"""
fetch_leading.py — 發現層硬數字前哨（leading indicators）fetcher。

Blocks（各自隔離，單塊失敗不殺其他 → carry_forward 前次值）:
  gauges             三儀表: credit_velocity (FRED HY OAS Δ5d/Δ20d) /
                     vix_term (^VIX vs ^VIX3M) / semis_breadth (SMH top-25 %>50DMA)
  earnings_crossread 財報季 cross-read 排序（早報者 → 晚報持倉讀序）
  pricing_watch      記憶體/功率元件報價新聞關鍵字抽取（純機械，不推方向）
  revision_delta     revision 二階導（今日 fundamentals cache vs archive 快照 diff）
  tw_monthly         台股功率元件月營收先行指標（TWSE/TPEx OpenAPI）

Output: briefing-out/cache/leading-indicators.json（TTL 20h）
Config: research/leading-config.json

Usage:
  python3 tools/fetch_leading.py                    # refresh if stale
  python3 tools/fetch_leading.py --force            # force refresh
  python3 tools/fetch_leading.py --force --only gauges,tw_monthly
  DRY_RUN=1 python3 tools/fetch_leading.py --force  # print plan, no write

所有旗標 display-only（記錄不阻擋，同影子訊號 A4）— 不 gate 任何動作。

NOTE: load_env/with_retry/is_cache_fresh/atomic_write duplicated from
fetch_macro.py (5th copy) — extract tools/fetch_common.py only in a dedicated
refactor touching all 5 fetchers at once.
"""

import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()

# TPEx openapi 憑證鏈在部分 python/launchd 組合下驗證失敗（Missing Subject Key
# Identifier）→ 僅對該 host 用 unverified context（先例 send_briefing.py）。
_TPEX_CTX = ssl._create_unverified_context()

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "briefing-out" / "cache"
CACHE_FILE = CACHE_DIR / "leading-indicators.json"
CONFIG_FILE = ROOT / "research" / "leading-config.json"
FUND_CACHE = CACHE_DIR / "fundamentals-snapshot.json"
EARNINGS_DATES_CACHE = CACHE_DIR / "earnings-dates.json"
ARCHIVE_DIR = CACHE_DIR / "archive"

CACHE_TTL_HOURS = 20  # 每日 runner 17:00 CET 必刷新；<24 避免 skip 漂移
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2"
EODHD_BASE = "https://eodhd.com/api"
TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
EODHD_DELAY = 0.4

BLOCK_NAMES = ["gauges", "earnings_crossread", "pricing_watch", "revision_delta", "tw_monthly"]


# ── helpers（複本，見檔頭 NOTE）────────────────────────────────────────────
def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                v = v.split("#")[0].strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                    v = v[1:-1]
                os.environ.setdefault(k.strip(), v)


def with_retry(fn, label: str, max_retries: int = 3):
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as e:
            print(f"[{label}] attempt {attempt}/{max_retries} failed: {e}",
                  file=sys.stderr)
            if attempt < max_retries:
                time.sleep(3 * attempt)
    return None


def is_cache_fresh(path: Path, ttl_hours: int) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < ttl_hours * 3600


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def percentile(value: float, sample: list) -> float:
    if not sample:
        return 50.0
    below = sum(1 for s in sample if s < value)
    return round(100 * below / len(sample), 1)


# ── generic small helpers ──────────────────────────────────────────────────
def now_utc_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def http_get_json(url: str, ctx=None, timeout: int = 25, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx or _SSL_CTX) as resp:
        return json.loads(resp.read().decode())


def fmp_query(tool: str, args: dict | None = None):
    """FMP free-tier 端點，走 tools/fmp_query.py 旁路 helper（docker container）。
    2026-07-28 實測免費可用：getTreasuryRates / getHistoricalIndustryPE /
    getSectorPESnapshot / getSectorPerformanceSnapshot / getAftermarketQuote /
    getShareFloat / getDividendsCalendar / getIndexQuote(^VIX)。"""
    cmd = [sys.executable, str(ROOT / "tools" / "fmp_query.py"), tool]
    if args:
        cmd += ["--args", json.dumps(args)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    lines = r.stdout.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("[", "{")):
            payload = json.loads("\n".join(lines[i:]))
            if isinstance(payload, dict) and "raw" in payload and "Error" in str(payload["raw"]):
                raise RuntimeError(f"fmp {tool}: {payload['raw']}")
            return payload
    raise RuntimeError(f"fmp {tool}: no JSON in output ({r.stdout[:80]!r})")


def carry_forward(prev: dict | None, block_name: str, reason: str) -> dict:
    prev_block = (prev or {}).get("blocks", {}).get(block_name)
    if prev_block:
        block = dict(prev_block)
        block["data_as_of"] = prev_block.get("data_as_of") or prev_block.get("generated_at")
        block["status"] = "carried_forward"
        block["carried_reason"] = reason[:200]
        return block
    return {"status": "error", "reason": reason[:200], "generated_at": now_utc_iso()}


# ── block 1: gauges ────────────────────────────────────────────────────────
def fetch_hy_oas_series(api_key: str) -> list:
    """[{date, value}] newest first；無 key/失敗 → 免金鑰 fredgraph.csv fallback。"""
    if api_key:
        params = urllib.parse.urlencode({
            "series_id": "BAMLH0A0HYM2", "api_key": api_key,
            "file_type": "json", "sort_order": "desc", "limit": 400,
        })
        data = http_get_json(f"{FRED_URL}?{params}")
        obs = []
        for row in data.get("observations", []):
            if row.get("value") in (".", None, ""):
                continue
            try:
                obs.append({"date": row["date"], "value": float(row["value"])})
            except (ValueError, KeyError):
                continue
        if obs:
            return obs
    # keyless fallback
    req = urllib.request.Request(FRED_CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25, context=_SSL_CTX) as resp:
        lines = resp.read().decode().strip().splitlines()
    obs = []
    for line in lines[1:]:
        d, _, v = line.partition(",")
        try:
            obs.append({"date": d, "value": float(v)})
        except ValueError:
            continue
    obs.reverse()  # newest first
    return obs[:400]


def build_credit_velocity(obs: list, th: dict) -> dict:
    vals = [o["value"] for o in obs]  # newest first, business-daily
    latest = vals[0]
    d5 = round((latest - vals[5]) * 100, 1) if len(vals) > 5 else None
    d20 = round((latest - vals[20]) * 100, 1) if len(vals) > 20 else None
    flag = "stable"
    if d5 is not None and d20 is not None:
        if d5 >= th["widening_fast_5d_bps"] or d20 >= th["widening_fast_20d_bps"]:
            flag = "widening_fast"
        elif d5 >= th["widening_5d_bps"]:
            flag = "widening"
        elif d5 <= th["tightening_5d_bps"]:
            flag = "tightening"
    return {
        "series": "BAMLH0A0HYM2", "value": latest, "date": obs[0]["date"],
        "delta_5d_bps": d5, "delta_20d_bps": d20,
        "pct_1y": percentile(latest, vals[:252]),
        "velocity_flag": flag,
    }


def _yf_last(sym: str):
    import yfinance as yf
    t = yf.Ticker(sym)
    try:
        fi = t.fast_info
        for key in ("last_price", "lastPrice"):
            try:
                px = fi[key]
                if px:
                    return float(px)
            except (KeyError, TypeError):
                continue
    except Exception:
        pass
    hist = t.history(period="5d")
    closes = hist["Close"].dropna()
    return float(closes.iloc[-1]) if len(closes) else None


def build_vix_term(th: dict) -> dict:
    vix = _yf_last("^VIX")
    vix3m = _yf_last("^VIX3M")
    if not vix or not vix3m:
        raise RuntimeError(f"vix pair unavailable ({vix}, {vix3m})")
    ratio = round(vix / vix3m, 3)
    if ratio >= th["inverted"]:
        flag = "inverted"
    elif ratio >= th["flattening"]:
        flag = "flattening"
    else:
        flag = "contango"
    return {"vix": round(vix, 2), "vix3m": round(vix3m, 2), "ratio": ratio,
            "term_flag": flag, "source": "yfinance"}


def fetch_etf_constituents(bench: str, token: str) -> list | None:
    """EODHD ETF holdings（Fundamentals Data Feed）→ 動態成分；失敗回 None。"""
    if not token:
        return None
    params = urllib.parse.urlencode({"filter": "ETF_Data::Holdings",
                                     "api_token": token, "fmt": "json"})
    data = http_get_json(f"{EODHD_BASE}/fundamentals/{bench}.US?{params}")
    if not isinstance(data, dict) or not data:
        return None
    rows = [(k[:-3], (v or {}).get("Assets_%") or 0)
            for k, v in data.items() if k.endswith(".US")]
    rows.sort(key=lambda r: r[1], reverse=True)
    return [r[0] for r in rows[:25]] or None


def build_semis_breadth(cfg_breadth: dict, th: dict) -> dict:
    import yfinance as yf
    bench_sym = cfg_breadth.get("benchmark", "SMH")
    live = None
    try:
        live = fetch_etf_constituents(bench_sym,
                                      os.environ.get("EODHD_API_TOKEN", "").strip())
    except Exception:
        live = None
    tickers = live or cfg_breadth["tickers"]
    universe_label = (f"{bench_sym} holdings (EODHD live, {len(tickers)})" if live
                     else cfg_breadth.get("universe_label", "static"))
    data = yf.download(tickers, period="4mo", progress=False, auto_adjust=True,
                       group_by="ticker", threads=True)
    above50 = above20 = n_valid = 0
    for sym in tickers:
        try:
            closes = data[sym]["Close"].dropna()
            if len(closes) < 50:
                continue
            last = float(closes.iloc[-1])
            n_valid += 1
            if last > float(closes.tail(50).mean()):
                above50 += 1
            if last > float(closes.tail(20).mean()):
                above20 += 1
        except Exception:
            continue
    if n_valid == 0:
        raise RuntimeError("no valid breadth tickers")
    pct50 = round(100 * above50 / n_valid, 1)
    pct20 = round(100 * above20 / n_valid, 1)
    flag = "neutral"
    if pct50 < th["weak_pct"]:
        flag = "weak"
    elif pct50 > th["strong_pct"]:
        flag = "strong"
    bench = cfg_breadth.get("benchmark", "SMH")
    smh_close = smh_high = pct_from_high = None
    divergence = False
    try:
        import yfinance as yf2
        hist = yf2.Ticker(bench).history(period="1y")["Close"].dropna()
        smh_close = round(float(hist.iloc[-1]), 2)
        smh_high = round(float(hist.max()), 2)
        pct_from_high = round(100 * (smh_close - smh_high) / smh_high, 1)
        divergence = (pct_from_high >= -th["divergence_52w_pct"]
                      and pct50 < th["divergence_breadth_pct"])
    except Exception:
        pass
    return {
        "universe": universe_label,
        "n_valid": n_valid,
        "pct_above_50dma": pct50, "pct_above_20dma": pct20,
        "breadth_flag": flag,
        "smh_close": smh_close, "smh_year_high": smh_high,
        "smh_pct_from_52w_high": pct_from_high,
        "divergence_flag": divergence,
    }


def build_gauges(cfg: dict, fred_key: str, errors: list) -> dict:
    th = cfg.get("gauges_thresholds", {}) if cfg else {}
    block = {"status": "ok", "generated_at": now_utc_iso()}
    sub_fail = 0

    obs = with_retry(lambda: fetch_hy_oas_series(fred_key), "HY_OAS", 3)
    if obs:
        block["credit_velocity"] = build_credit_velocity(
            obs, th.get("credit", {"widening_fast_5d_bps": 25, "widening_fast_20d_bps": 50,
                                   "widening_5d_bps": 10, "tightening_5d_bps": -10}))
    else:
        errors.append("gauges:credit_velocity")
        sub_fail += 1

    vt = with_retry(lambda: build_vix_term(
        th.get("vix_term", {"inverted": 1.0, "flattening": 0.95})), "VIX_TERM", 3)
    if vt:
        block["vix_term"] = vt
    else:
        errors.append("gauges:vix_term")
        sub_fail += 1

    if cfg and cfg.get("breadth"):
        br = with_retry(lambda: build_semis_breadth(
            cfg["breadth"], th.get("breadth", {"weak_pct": 40, "strong_pct": 80,
                                               "divergence_52w_pct": 5,
                                               "divergence_breadth_pct": 50})), "BREADTH", 3)
        if br:
            block["semis_breadth"] = br
        else:
            errors.append("gauges:semis_breadth")
            sub_fail += 1
    else:
        errors.append("gauges:semis_breadth_config_missing")
        sub_fail += 1

    # ── FMP free-tier 補充儀表（2026-07-28）────────────────────────────────
    # treasury 曲線：10Y 供 plan「10Y <4.35 再加滿」類閘門對照（display-only）
    try:
        row = fmp_query("getTreasuryRates")[0]
        y10, y2, m3 = row.get("year10"), row.get("year2"), row.get("month3")
        block["treasury"] = {
            "date": row.get("date"), "m3": m3, "y2": y2, "y10": y10,
            "y30": row.get("year30"),
            "spread_2s10s": round(y10 - y2, 2) if y10 and y2 else None,
            "spread_3m10y": round(y10 - m3, 2) if y10 and m3 else None,
            "source": "fmp:getTreasuryRates",
        }
    except Exception as e:
        errors.append(f"gauges:treasury ({e})"[:80])
        sub_fail += 1

    # 半導體行業 PE 溫度計：日頻 de-rating/re-rating 直接可見
    try:
        frm = (date.today() - timedelta(days=100)).isoformat()
        hist = fmp_query("getHistoricalIndustryPE",
                         {"industry": "Semiconductors", "from": frm,
                          "to": date.today().isoformat()})
        pes = sorted(((r["date"], float(r["pe"])) for r in hist if r.get("pe")),
                     reverse=True)
        if not pes:
            raise RuntimeError("empty PE series")
        vals = [p for _, p in pes]
        cur = vals[0]
        block["semis_industry_pe"] = {
            "industry": "Semiconductors", "date": pes[0][0], "pe": round(cur, 1),
            "delta_5d_pct": (round(100 * (cur - vals[5]) / vals[5], 1)
                             if len(vals) > 5 else None),
            "delta_20d_pct": (round(100 * (cur - vals[20]) / vals[20], 1)
                              if len(vals) > 20 else None),
            "pct_100d": percentile(cur, vals),
            "source": "fmp:getHistoricalIndustryPE",
        }
    except Exception as e:
        errors.append(f"gauges:semis_industry_pe ({e})"[:80])
        sub_fail += 1

    if sub_fail >= 5:
        raise RuntimeError("all gauges failed")
    if sub_fail:
        block["status"] = "partial"
    return block


# ── block 2: earnings_crossread ────────────────────────────────────────────
def _yf_earnings_dates(sym: str) -> list:
    """回傳 [date, ...]（date objects，desc）。"""
    import yfinance as yf
    t = yf.Ticker(sym)
    try:
        df = t.get_earnings_dates(limit=8)
    except AttributeError:
        df = t.earnings_dates
    if df is None or df.empty:
        return []
    return sorted({idx.date() for idx in df.index}, reverse=True)


def resolve_us_leader(sym: str, held_dates: dict, today: date) -> dict:
    out = {"sym": sym, "date_source": None}
    dates = None
    if with_retry:  # per-leader retry(2)
        dates = with_retry(lambda: _yf_earnings_dates(sym), f"earnings {sym}", 2)
    if dates:
        past = [d for d in dates if d <= today]
        future = [d for d in dates if d > today]
        if past and (today - past[0]).days <= 10:
            out.update({"next_date": past[0].isoformat(), "reported_within_10d": True,
                        "days_since": (today - past[0]).days, "date_source": "yfinance"})
            return out
        if future:
            nxt = min(future)
            out.update({"next_date": nxt.isoformat(), "days_until": (nxt - today).days,
                        "date_source": "yfinance"})
            return out
    # fallback: earnings-dates.json（持倉才有）
    ent = held_dates.get(sym)
    if ent and ent.get("next_date"):
        nxt = date.fromisoformat(ent["next_date"])
        out.update({"next_date": ent["next_date"], "date_source": "earnings-dates.json"})
        if nxt >= today:
            out["days_until"] = (nxt - today).days
        elif (today - nxt).days <= 10:
            out["reported_within_10d"] = True
            out["days_since"] = (today - nxt).days
        return out
    out["error"] = "date_unresolved"
    return out


def build_crossread(cfg: dict, errors: list) -> dict:
    today = date.today()
    dates_payload = load_json(EARNINGS_DATES_CACHE) or {}
    held_dates = dates_payload.get("tickers", {})
    chains_out = []
    for chain in cfg.get("crossread_chains", []):
        leaders_out = []
        active = False
        for leader in chain.get("leaders", []):
            ltype = leader.get("type", "us_earnings")
            if ltype == "us_earnings":
                info = resolve_us_leader(leader["sym"], held_dates, today)
                if info.get("error"):
                    errors.append(f"crossread:{leader['sym']}_date")
                if info.get("reported_within_10d") or (info.get("days_until") is not None
                                                       and info["days_until"] <= 7):
                    active = True
                leaders_out.append(info)
            elif ltype == "monthly_rev":
                lo, hi = leader.get("window_days", [8, 12])
                in_window = lo <= today.day <= hi
                nxt = (today.replace(day=leader.get("day_of_month", 10))
                       if today.day <= hi else
                       (today.replace(day=1) + timedelta(days=32)).replace(
                           day=leader.get("day_of_month", 10)))
                if in_window:
                    active = True
                leaders_out.append({"sym": leader["sym"], "type": "monthly_rev",
                                    "next_date": nxt.isoformat(), "in_window": in_window,
                                    "date_source": "recurrence"})
            else:  # news_only — 無排程，靠 pricing_watch 承接
                leaders_out.append({"sym": leader["sym"], "type": "news_only",
                                    "name": leader.get("name"),
                                    "recurrence": leader.get("recurrence")})
        followers_out = []
        for f in chain.get("followers", []):
            ent = held_dates.get(f)
            followers_out.append({"sym": f, "next_date": (ent or {}).get("next_date")})
        chains_out.append({
            "id": chain["id"], "label": chain.get("label", chain["id"]),
            "active": active, "leaders": leaders_out, "followers": followers_out,
            "metric": chain.get("metric"), "read": chain.get("read"),
        })
    return {"status": "ok", "generated_at": now_utc_iso(), "chains": chains_out,
            "_active_rule": "any leader reported_within_10d OR days_until<=7 OR monthly window"}


# ── block 3: pricing_watch ─────────────────────────────────────────────────
def _kw_pattern(kw: str):
    pat = r"(?<![A-Za-z0-9])" + re.escape(kw) + r"(?![A-Za-z0-9])"
    flags = 0 if kw.isupper() else re.IGNORECASE
    return re.compile(pat, flags)


def eodhd_news(sym: str, from_date: str, token: str) -> list:
    params = urllib.parse.urlencode({"s": sym, "from": from_date, "limit": 15,
                                     "api_token": token, "fmt": "json"})
    return http_get_json(f"{EODHD_BASE}/news?{params}") or []


def _excerpt(text: str, pos: int, width: int = 240) -> str:
    start = max(0, pos - 80)
    end = min(len(text), start + width)
    seg = text[start:end].strip().replace("\n", " ")
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{seg}{suffix}"


def build_pricing_watch(cfg: dict, token: str, errors: list) -> dict:
    if not token:
        raise RuntimeError("EODHD_API_TOKEN_missing")
    pw = cfg["pricing_watch"]
    lookback = pw.get("lookback_days", 7)
    from_date = (date.today() - timedelta(days=lookback)).isoformat()
    block = {"status": "ok", "generated_at": now_utc_iso(), "lookback_days": lookback}
    any_ok = False
    for cat in ("memory", "power"):
        cat_cfg = pw.get(cat)
        if not cat_cfg:
            continue
        patterns = [(_kw_pattern(k), k) for k in cat_cfg["keywords"]]
        items, seen = [], set()
        cat_err = 0
        for sym in cat_cfg["symbols"]:
            arts = with_retry(lambda s=sym: eodhd_news(s, from_date, token),
                              f"news {sym}", 2)
            time.sleep(EODHD_DELAY)
            if arts is None:
                errors.append(f"pricing:{sym}")
                cat_err += 1
                continue
            any_ok = True
            for a in arts:
                title = a.get("title", "") or ""
                content = a.get("content", "") or ""
                norm = re.sub(r"\W+", "", title.lower())[:60]
                if norm in seen:
                    continue
                hits, first_pos, in_text = [], None, ""
                for pat, kw in patterns:
                    m = pat.search(content) or pat.search(title)
                    if m:
                        hits.append(kw)
                        if first_pos is None:
                            in_text = content if pat.search(content) else title
                            first_pos = m.start()
                if not hits:
                    continue
                seen.add(norm)
                items.append({
                    "symbol": sym, "date": (a.get("date") or "")[:10], "title": title,
                    "keywords": hits[:6],
                    "excerpt": _excerpt(in_text, first_pos),
                    "link": a.get("link", ""),
                    "source": urllib.parse.urlparse(a.get("link", "")).netloc,
                })
        items.sort(key=lambda x: x["date"], reverse=True)
        block[cat] = {"n_hits": len(items[:6]), "items": items[:6]}
        if cat_err == len(cat_cfg["symbols"]):
            block["status"] = "partial"
    if not any_ok:
        raise RuntimeError("all pricing_watch symbols failed")
    return block


# ── block 4: revision_delta ────────────────────────────────────────────────
def _fund_tickers(payload: dict) -> dict:
    return payload.get("tickers", {}) if payload else {}


def _payload_date(payload: dict):
    try:
        return datetime.fromisoformat(payload["generated_at"]).date()
    except Exception:
        return None


def list_archive_snapshots() -> list:
    """[(generated_at_date, payload)]，以 payload generated_at 為準、去重。"""
    out, seen = [], set()
    if not ARCHIVE_DIR.exists():
        return out
    for day_dir in sorted(ARCHIVE_DIR.iterdir()):
        f = day_dir / "fundamentals-snapshot.json"
        if not f.is_file():
            continue
        payload = load_json(f)
        d = _payload_date(payload) if payload else None
        if d is None or d in seen:
            continue
        seen.add(d)
        out.append((d, payload))
    return sorted(out, key=lambda x: x[0])


def period_metrics(entry: dict, period: str):
    fe = (entry.get("snapshot") or {}).get("forward_estimates") or {}
    p = fe.get(period)
    if not p:
        return None
    n = p.get("eps_num_analysts")
    up, down = p.get("revisions_up_30d"), p.get("revisions_down_30d")
    if n is None or up is None or down is None:
        return None
    return {
        "net_ratio": round((up - down) / max(n, 1), 3),
        "rev30_pct": p.get("eps_revision_30d_pct"),
        "n_analysts": n, "period_date": p.get("date"),
    }


def build_revision_delta(cfg: dict, errors: list) -> dict:
    rc = cfg["revision_delta"]
    today = date.today()
    current = load_json(FUND_CACHE)
    if not current:
        raise RuntimeError("fundamentals-snapshot.json missing")
    snaps = list_archive_snapshots()
    block = {"status": "ok", "generated_at": now_utc_iso(),
             "days_available": (today - snaps[0][0]).days if snaps else 0,
             "windows": {}, "book": None, "tickers": {}}

    chosen = {}
    for w in rc["windows"]:
        target = today - timedelta(days=w["days"])
        best, best_gap = None, None
        for d, payload in snaps:
            gap = abs((d - target).days)
            if gap <= w["tolerance"] and (best_gap is None or gap < best_gap):
                best, best_gap = (d, payload), gap
        key = f"{w['days']}d"
        if best:
            chosen[key] = best
            block["windows"][key] = {"available": True, "compared_against": best[0].isoformat()}
        else:
            avail_from = (snaps[0][0] + timedelta(days=w["days"] - w["tolerance"])
                          ).isoformat() if snaps else None
            block["windows"][key] = {"available": False, "available_from": avail_from,
                                     "compared_against": None}

    cur_t = _fund_tickers(current)
    min_n = rc["min_analysts"]
    if not chosen:
        # archive 窗尚無快照 → archive-diff 法暫停；vendor 7d 法（下方）照算
        block["status"] = "warming_up"
    for wkey, (prev_date, prev_payload) in chosen.items():
        is_30d = wkey == "30d"
        drop_ratio = rc["decel_net_ratio_drop_30d"] if is_30d else rc["decel_net_ratio_drop"]
        drop_pp = rc["decel_rev30_drop_pp_30d"] if is_30d else rc["decel_rev30_drop_pp"]
        prev_t = _fund_tickers(prev_payload)
        book_now = book_prev = book_n = 0
        for sym in sorted(set(cur_t) & set(prev_t)):
            for period in rc["periods"]:
                m_now = period_metrics(cur_t[sym], period)
                m_prev = period_metrics(prev_t[sym], period)
                if not m_now or not m_prev:
                    continue
                rec = block["tickers"].setdefault(sym, {}).setdefault(period, {})
                if m_now["period_date"] != m_prev["period_date"]:
                    rec[f"{wkey}_period_rolled"] = True
                    continue
                if m_now["n_analysts"] < min_n or m_prev["n_analysts"] < min_n:
                    continue
                dn = abs(m_now["n_analysts"] - m_prev["n_analysts"])
                coverage_shift = dn > max(2, rc["max_analyst_count_change_pct"] / 100
                                          * m_prev["n_analysts"])
                d_net = round(m_now["net_ratio"] - m_prev["net_ratio"], 3)
                d_rev = (round(m_now["rev30_pct"] - m_prev["rev30_pct"], 2)
                         if m_now["rev30_pct"] is not None and m_prev["rev30_pct"] is not None
                         else None)
                decel = (not coverage_shift
                         and m_now["net_ratio"] >= 0
                         and d_net <= -drop_ratio
                         and d_rev is not None and d_rev <= -drop_pp
                         and (m_now["rev30_pct"] or 0) >= 0)
                rec.update({
                    f"{wkey}_net_ratio": m_now["net_ratio"],
                    f"{wkey}_net_ratio_prev": m_prev["net_ratio"],
                    f"{wkey}_d_net_ratio": d_net,
                    f"{wkey}_rev30_pct": m_now["rev30_pct"],
                    f"{wkey}_d_rev30_pp": d_rev,
                    f"{wkey}_n_analysts": m_now["n_analysts"],
                    f"{wkey}_coverage_shift": coverage_shift,
                    f"{wkey}_decel_flag": decel,
                })
                if period == "curr_fy" and not coverage_shift:
                    book_n += 1
                    book_now += 1 if m_now["net_ratio"] > 0 else 0
                    book_prev += 1 if m_prev["net_ratio"] > 0 else 0
        if wkey == "7d" and book_n:
            b_now = round(100 * book_now / book_n, 1)
            b_prev = round(100 * book_prev / book_n, 1)
            mom = round(b_now - b_prev, 1)
            block["book"] = {
                "period": "curr_fy", "n_qualified": book_n,
                "breadth_pos_pct": b_now, "breadth_pos_pct_prev_7d": b_prev,
                "momentum_7d_pp": mom,
                "book_decel": (b_now >= rc["book_decel_breadth_floor"]
                               and mom <= rc["book_decel_momentum_pp"]),
                "book_rollover": (b_now < rc["book_decel_breadth_floor"] <= b_prev),
            }
    # ── vendor 原生 7d 曲線（Fundamentals Data Feed）— 不依賴 archive，自首日可用 ──
    # 判定：月度上修廣（net30 高或 rev30 高）但最近一週停了（net7 ≤ 0 且 rev7 ≤ 0）
    vendor_flagged = []
    v_n = v_pos7 = v_pos30 = 0
    for sym in sorted(cur_t):
        fe = (cur_t[sym].get("snapshot") or {}).get("forward_estimates") or {}
        for period in rc["periods"]:
            p = fe.get(period)
            if not p:
                continue
            n = p.get("eps_num_analysts")
            if not n or n < min_n:
                continue
            up7, down7 = p.get("revisions_up_7d"), p.get("revisions_down_7d")
            if up7 is None and down7 is None:
                continue  # vendor 7d 欄位缺（訂閱外/資料洞）→ 該票跳過
            net7 = round(((up7 or 0) - (down7 or 0)) / max(n, 1), 3)
            net30 = round(((p.get("revisions_up_30d") or 0)
                           - (p.get("revisions_down_30d") or 0)) / max(n, 1), 3)
            rev7 = p.get("eps_revision_7d_pct")
            rev30 = p.get("eps_revision_30d_pct")
            decel = ((net30 >= rc.get("vendor_decel_net30_min", 0.15)
                      or (rev30 or 0) >= rc.get("vendor_decel_rev30_min_pct", 1.0))
                     and net7 <= 0 and rev7 is not None and rev7 <= 0)
            rec = block["tickers"].setdefault(sym, {}).setdefault(period, {})
            rec.update({"vendor_net7": net7, "vendor_net30": net30,
                        "vendor_rev7_pct": rev7, "vendor_rev30_pct": rev30,
                        "vendor_decel_flag": decel})
            if decel and sym not in vendor_flagged:
                vendor_flagged.append(sym)
            if period == "curr_fy":
                v_n += 1
                v_pos7 += 1 if net7 > 0 else 0
                v_pos30 += 1 if net30 > 0 else 0
    if v_n:
        b7, b30 = round(100 * v_pos7 / v_n, 1), round(100 * v_pos30 / v_n, 1)
        block["vendor_book"] = {
            "period": "curr_fy", "n_qualified": v_n,
            "breadth_pos_7d_pct": b7, "breadth_pos_30d_pct": b30,
            "drop_pp": round(b7 - b30, 1),
            "book_decel": (b30 >= rc["book_decel_breadth_floor"]
                           and (b7 - b30) <= -rc.get("vendor_book_decel_drop_pp", 25)),
        }
        if block["status"] == "warming_up":
            block["status"] = "ok"  # vendor 法已可用；archive 窗狀態見 windows

    # decel 摘要（skill 直接讀這裡）— 兩法分列供 /trade-review 各驗命中率，union 供顯示
    archive_flagged = sorted({s for s, periods in block["tickers"].items()
                              for p, rec in periods.items()
                              if any(k in ("7d_decel_flag", "30d_decel_flag") and v
                                     for k, v in rec.items())})
    block["decel_tickers_archive"] = archive_flagged
    block["decel_tickers_vendor"] = sorted(vendor_flagged)
    block["decel_tickers"] = sorted(set(archive_flagged) | set(vendor_flagged))
    return block


# ── block 5: tw_monthly ────────────────────────────────────────────────────
def _tw_num(v):
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _roc_month(v: str):
    digits = re.sub(r"\D", "", str(v or ""))
    if len(digits) >= 5:
        year, month = int(digits[:-2]) + 1911, int(digits[-2:])
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
    return None


def parse_tw_row(row: dict):
    def find(substr, exclude=None):
        for k, v in row.items():
            if substr in k and (exclude is None or exclude not in k):
                return v
        return None
    code = row.get("公司代號") or row.get("SecuritiesCompanyCode") or find("公司代號")
    name = row.get("公司名稱") or row.get("CompanyName") or find("公司名稱")
    month = _roc_month(find("年月"))
    rev = _tw_num(find("當月營收", exclude="去年"))
    rev_prev_m = _tw_num(find("上月營收"))
    rev_last_y = _tw_num(find("去年當月營收"))
    mom = _tw_num(find("上月比較增減"))
    yoy = _tw_num(find("去年同月增減"))
    if yoy is None and rev and rev_last_y:
        yoy = round(100 * (rev - rev_last_y) / rev_last_y, 2)
    if mom is None and rev and rev_prev_m:
        mom = round(100 * (rev - rev_prev_m) / rev_prev_m, 2)
    if not code or not month or rev is None:
        return None
    return {"code": str(code), "name": name, "data_month": month,
            "rev_month_ntd_k": rev,
            "mom_pct": round(mom, 2) if mom is not None else None,
            "yoy_pct": round(yoy, 2) if yoy is not None else None}


def build_tw_monthly(cfg: dict, prev: dict | None, errors: list) -> dict:
    tw_cfg = cfg["tw_monthly"]
    rows = []
    twse = with_retry(lambda: http_get_json(TWSE_URL), "TWSE", 3)
    if twse:
        rows += [(r, "twse") for r in twse]
    else:
        errors.append("tw:twse")
    tpex = with_retry(lambda: http_get_json(TPEX_URL, ctx=_TPEX_CTX), "TPEx", 3)
    if tpex:
        rows += [(r, "tpex") for r in tpex]
    else:
        errors.append("tw:tpex")
    if not rows:
        raise RuntimeError("TWSE and TPEx both failed")

    wanted = {c["code"]: (c["name"], mkt)
              for mkt in ("twse", "tpex") for c in tw_cfg.get(mkt, [])}
    prev_block = (prev or {}).get("blocks", {}).get("tw_monthly") or {}
    prev_hist = {c["code"]: c.get("yoy_history", [])
                 for c in prev_block.get("companies", [])}

    companies = []
    for row, mkt in rows:
        parsed = parse_tw_row(row)
        if not parsed or parsed["code"] not in wanted:
            continue
        code = parsed["code"]
        parsed["market"] = wanted[code][1]
        hist = [h for h in prev_hist.get(code, []) if h.get("month") != parsed["data_month"]]
        hist.insert(0, {"month": parsed["data_month"], "yoy_pct": parsed["yoy_pct"]})
        hist = sorted(hist, key=lambda h: h["month"], reverse=True)[:13]
        parsed["yoy_history"] = hist
        parsed["history_months"] = len(hist)
        ys = [h["yoy_pct"] for h in hist if h["yoy_pct"] is not None]
        parsed["turned_negative"] = (ys[0] < 0 <= ys[1]) if len(ys) >= 2 else None
        parsed["accel_flag"] = (ys[0] > ys[1] > ys[2]) if len(ys) >= 3 else None
        companies.append(parsed)

    if not companies:
        raise RuntimeError("no configured TW companies found in API data")
    missing = sorted(set(wanted) - {c["code"] for c in companies})
    data_month = max(c["data_month"] for c in companies)
    return {
        "status": "ok" if not missing else "partial",
        "generated_at": now_utc_iso(),
        "data_month": data_month,
        "is_new_month": data_month != prev_block.get("data_month"),
        "companies": sorted(companies, key=lambda c: c["code"]),
        "missing_codes": missing,
        "flags_note": ("accel = YoY 連 2 月走升（需 3 點）；turned_negative = 最新 YoY<0 "
                       "且前月≥0（需 2 點）；不足 → null（warming up）"),
    }


# ── main ───────────────────────────────────────────────────────────────────
def main() -> int:
    load_env()
    argv = sys.argv[1:]
    force = "--force" in argv
    dry_run = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")
    only = None
    for i, a in enumerate(argv):
        if a == "--only" and i + 1 < len(argv):
            only = {s.strip() for s in argv[i + 1].split(",") if s.strip()}
        elif a.startswith("--only="):
            only = {s.strip() for s in a.split("=", 1)[1].split(",") if s.strip()}

    if not force and is_cache_fresh(CACHE_FILE, CACHE_TTL_HOURS):
        print(f"✅ leading cache fresh (< {CACHE_TTL_HOURS}h), skipping")
        return 0

    cfg = load_json(CONFIG_FILE)
    prev = load_json(CACHE_FILE)
    fred_key = os.environ.get("FRED_API_KEY", "").strip()
    eodhd_token = os.environ.get("EODHD_API_TOKEN", "").strip()

    if dry_run:
        print(f"[DRY-RUN] config={'ok' if cfg else 'MISSING'} "
              f"fred_key={'yes' if fred_key else 'no'} eodhd={'yes' if eodhd_token else 'no'}")
        for b in BLOCK_NAMES:
            print(f"[DRY-RUN] would build block: {b}"
                  + (" (skipped by --only)" if only and b not in only else ""))
        return 0

    errors: list = []
    builders = {
        "gauges": lambda: build_gauges(cfg or {}, fred_key, errors),
        "earnings_crossread": lambda: build_crossread(cfg or {}, errors),
        "pricing_watch": lambda: build_pricing_watch(cfg or {}, eodhd_token, errors),
        "revision_delta": lambda: build_revision_delta(cfg or {}, errors),
        "tw_monthly": lambda: build_tw_monthly(cfg or {}, prev, errors),
    }
    config_needed = {"earnings_crossread", "pricing_watch", "revision_delta", "tw_monthly"}

    blocks = {}
    for name in BLOCK_NAMES:
        if only and name not in only:
            prev_block = (prev or {}).get("blocks", {}).get(name)
            blocks[name] = prev_block or {"status": "error", "reason": "not_built (--only)"}
            continue
        if not cfg and name in config_needed:
            blocks[name] = carry_forward(prev, name, "config_missing")
            errors.append(f"{name}:config_missing")
            continue
        try:
            blocks[name] = builders[name]()
            print(f"✅ {name}: {blocks[name].get('status')}")
        except Exception as e:
            blocks[name] = carry_forward(prev, name, str(e))
            errors.append(f"{name}:{e}")
            print(f"⚠️ {name}: {blocks[name]['status']} ({e})", file=sys.stderr)

    statuses = {b.get("status") for b in blocks.values()}
    if statuses <= {"ok", "warming_up", "partial"} and "partial" not in statuses:
        top = "ok"
    elif statuses <= {"error"}:
        top = "skipped"
    else:
        top = "partial"
    payload = {
        "status": top,
        "generated_at": now_utc_iso(),
        "config_version": (cfg or {}).get("version"),
        "errors": errors,
        "blocks": blocks,
    }
    if top == "skipped":
        payload["reason"] = "all_blocks_failed"
    atomic_write(CACHE_FILE, payload)
    print(f"💾 wrote {CACHE_FILE.relative_to(ROOT)} (status={top}, errors={len(errors)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
