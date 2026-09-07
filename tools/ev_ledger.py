#!/usr/bin/env python3
"""
ev_ledger.py — Pre-register EV / probability-distribution forecasts, resolve
them mechanically against realized prices when the horizon expires, and report
calibration stats.

Complements thesis_ledger.py: thesis ledger verifies *claims* (judgment call at
resolve time); EV ledger verifies *distributions* (zero judgment — fetch price,
classify bucket, score). Purpose: make the probability-honesty-checker's output
itself measurable (are our 30% buckets hitting 30%? are bears systematically
too fat?). Consumed by /trade-review; adjustments go to prompts/rules via
RULES-LEDGER — NOT to any fitted model (see 2026-08-03 design discussion:
symbolic self-optimization only until n>150 resolved independent forecasts).

Storage: research/ev-ledger.jsonl (one JSON object per line, atomic rewrite)

Bucket boundaries are locked at add time from the three scenario fair values:
  realized < mid(fv_bear, fv_base)          → bear
  realized > mid(fv_base, fv_bull)          → bull
  else                                       → base
Entries missing fair values resolve EV-error only (no bucket / no Brier).

Luck-vs-model split (2026-09-06, feedback/skill-vs-luck.md):
  in_range  — realized inside the pre-registered range
              [fv_bear − ½(fv_base−fv_bear), fv_bull + ½(fv_bull−fv_base)].
              Outside = the model had no branch for what happened → model miss,
              NOT bad luck. Only an outcome inside the distribution can be luck.
  stats     — Brier skill score vs climatology / uniform, independent n
              (target dates within 14 days = one cluster), and the thesis × EV
              2×2 (thesis passed but realized < EV = "priced-in candidate").

PORTFOLIO / MARKET / _PORTFOLIO / MACRO tickers resolve against
research/equity-marks.json (nearest usable mark within ±4 days).
"""

import argparse
import json
import sys
import tempfile
import os
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "research" / "ev-ledger.jsonl"
EQUITY_MARKS = ROOT / "research" / "equity-marks.json"
THESIS_LEDGER = ROOT / "research" / "thesis-ledger.json"
CLUSTER_DAYS = 14             # resolved entries with target_date within this = 1 independent obs

PORTFOLIO_TICKERS = {"PORTFOLIO", "MARKET", "_PORTFOLIO", "MACRO"}
MARK_TOLERANCE_DAYS = 4       # equity-mark nearest-neighbour window
PROB_SUM_TOLERANCE = 2.0      # probs must sum to 100 ± this
HORIZON_BANDS = [(0, 14, "≤14d"), (15, 60, "15–60d"), (61, 200, "61–200d"),
                 (201, 10**6, ">200d")]


# ── storage ─────────────────────────────────────────────────────────────────
def load():
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def save(entries):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(LEDGER.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, LEDGER)


def today():
    return date.today().isoformat()


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


# ── price fetch ─────────────────────────────────────────────────────────────
def fetch_close_on_or_after(ticker, target, window_days=7):
    """First daily close on/after target date. Falls back to intraday price
    when target is today and the close doesn't exist yet."""
    import yfinance as yf
    start = parse_date(target)
    end = start + timedelta(days=window_days)
    hist = yf.Ticker(ticker).history(start=start.isoformat(),
                                     end=end.isoformat(), interval="1d")
    if hist is not None and len(hist) > 0:
        first = hist.iloc[0]
        dt = str(hist.index[0].date())
        return float(first["Close"]), dt, "yfinance_close"
    # target may be today with no daily bar yet → live-ish price
    info = yf.Ticker(ticker).fast_info
    px = info.get("last_price") or info.get("lastPrice")
    if px:
        return float(px), today(), "yfinance_intraday"
    raise RuntimeError(f"no price for {ticker} on/after {target}")


def fetch_equity_mark(target):
    """Nearest usable equity mark within ±MARK_TOLERANCE_DAYS of target."""
    data = json.loads(EQUITY_MARKS.read_text())
    marks = data if isinstance(data, list) else data.get("marks", [])
    t = parse_date(target)
    best = None
    for m in marks:
        if m.get("excluded"):
            continue
        d = parse_date(m["date"])
        delta = abs((d - t).days)
        if delta <= MARK_TOLERANCE_DAYS:
            # prefer smaller delta; tie → prefer on/after target
            key = (delta, 0 if d >= t else 1)
            if best is None or key < best[0]:
                best = (key, m)
    if best is None:
        raise RuntimeError(f"no equity mark within ±{MARK_TOLERANCE_DAYS}d of {target}")
    m = best[1]
    return float(m["value"]), m["date"], "equity-marks"


# ── scoring ─────────────────────────────────────────────────────────────────
def classify_bucket(entry, realized):
    fvs = [entry.get("fv_bull"), entry.get("fv_base"), entry.get("fv_bear")]
    if any(v is None for v in fvs):
        return None
    lo = (entry["fv_bear"] + entry["fv_base"]) / 2.0
    hi = (entry["fv_base"] + entry["fv_bull"]) / 2.0
    if realized < lo:
        return "bear"
    if realized > hi:
        return "bull"
    return "base"


def brier(entry, bucket):
    ps = [entry.get("p_bull"), entry.get("p_base"), entry.get("p_bear")]
    if bucket is None or any(p is None for p in ps):
        return None
    o = {"bull": (1, 0, 0), "base": (0, 1, 0), "bear": (0, 0, 1)}[bucket]
    return round(sum((p / 100.0 - oi) ** 2 for p, oi in zip(ps, o)), 4)


def range_check(entry, realized):
    """(in_range, tail): was the outcome inside the pre-registered distribution?
    Outside → model miss (no branch existed), not luck."""
    fvs = [entry.get("fv_bull"), entry.get("fv_base"), entry.get("fv_bear")]
    if any(v is None for v in fvs):
        return None, None
    lo = entry["fv_bear"] - 0.5 * (entry["fv_base"] - entry["fv_bear"])
    hi = entry["fv_bull"] + 0.5 * (entry["fv_bull"] - entry["fv_base"])
    if realized < lo:
        return False, "below"
    if realized > hi:
        return False, "above"
    return True, None


def thesis_verdict(ref):
    """Verdict of a thesis-ledger entry (passed/failed/partial) or None."""
    if not ref or not THESIS_LEDGER.exists():
        return None
    try:
        data = json.loads(THESIS_LEDGER.read_text())
    except Exception:  # noqa: BLE001
        return None
    for t in data.get("theses", []):
        if t.get("id") == ref:
            st = t.get("status")
            if st in ("passed", "failed", "partial"):
                return st
            hist = t.get("history") or []
            if hist and hist[-1].get("verdict") in ("passed", "failed", "partial"):
                return hist[-1]["verdict"]
            return None
    return None


def independent_n(entries):
    """Greedy clustering on target_date: entries within CLUSTER_DAYS of the
    cluster anchor count as one independent observation."""
    dates = sorted(parse_date(e["target_date"]) for e in entries)
    n, anchor = 0, None
    for d in dates:
        if anchor is None or (d - anchor).days > CLUSTER_DAYS:
            n += 1
            anchor = d
    return n


def horizon_band(days):
    for lo, hi, label in HORIZON_BANDS:
        if lo <= days <= hi:
            return label
    return "?"


# ── commands ────────────────────────────────────────────────────────────────
def cmd_add(a):
    entries = load()
    fdate = a.forecast_date or today()
    target = (parse_date(fdate) + timedelta(days=a.horizon_days)).isoformat()
    slug = a.slug or f"f{fdate.replace('-', '')}-h{a.horizon_days}"
    eid = f"{a.ticker.upper()}:{slug}"

    probs = (a.p_bull, a.p_base, a.p_bear)
    if any(p is not None for p in probs):
        if any(p is None for p in probs):
            sys.exit("give all three of --p-bull/--p-base/--p-bear or none")
        s = sum(probs)
        if abs(s - 100.0) > PROB_SUM_TOLERANCE:
            sys.exit(f"probs sum to {s}, outside 100±{PROB_SUM_TOLERANCE}")

    ev_pct = a.ev_pct
    if ev_pct is None and a.ev_price is not None:
        ev_pct = round((a.ev_price / a.spot - 1) * 100, 2)
    if ev_pct is None:
        sys.exit("need --ev-pct or --ev-price")
    if a.thesis_ref and a.p_up_given_thesis is None:
        sys.exit("--thesis-ref 需搭配 --p-up-given-thesis <0-100>（priced-in 檢查：thesis 對 ≠ 漲；"
                 "附 --priced-in-basis 'thesis 值 vs 共識'）")
    if a.p_up_given_thesis is not None and not 0 <= a.p_up_given_thesis <= 100:
        sys.exit("--p-up-given-thesis must be 0–100")

    entry = {
        "id": eid, "ticker": a.ticker.upper(), "forecast_date": fdate,
        "horizon_days": a.horizon_days, "target_date": target,
        "spot": a.spot,
        "p_bull": a.p_bull, "p_base": a.p_base, "p_bear": a.p_bear,
        "fv_bull": a.fv_bull, "fv_base": a.fv_base, "fv_bear": a.fv_bear,
        "ev_price": a.ev_price, "ev_pct": ev_pct,
        "source": a.source, "model": a.model, "thesis_ref": a.thesis_ref,
        "p_up_given_thesis": a.p_up_given_thesis, "priced_in_basis": a.priced_in_basis,
        "note": a.note, "status": "pending", "created_at": today(),
        "resolution": None,
    }
    existing = [i for i, e in enumerate(entries) if e["id"] == eid]
    action = "updated" if existing else "inserted"
    if existing:
        if entries[existing[0]]["status"] != "pending":
            sys.exit(f"{eid} already resolved — refusing to overwrite")
        entries[existing[0]] = entry
    else:
        entries.append(entry)
    save(entries)
    print(json.dumps({"action": action, "id": eid, "target_date": target}))


def _resolve_entry(entry, realized=None, realized_date=None, method="manual"):
    if realized is None:
        if entry["ticker"] in PORTFOLIO_TICKERS:
            realized, realized_date, method = fetch_equity_mark(entry["target_date"])
        else:
            realized, realized_date, method = fetch_close_on_or_after(
                entry["ticker"], entry["target_date"])
    realized_pct = round((realized / entry["spot"] - 1) * 100, 2)
    bucket = classify_bucket(entry, realized)
    in_range, tail = range_check(entry, realized)
    entry["status"] = "resolved"
    entry["resolution"] = {
        "resolved_at": today(), "realized": round(realized, 2),
        "realized_date": realized_date, "method": method,
        "realized_pct": realized_pct,
        "vs_ev_pp": round(realized_pct - entry["ev_pct"], 2),
        "bucket": bucket, "brier": brier(entry, bucket),
        "in_range": in_range, "tail": tail,
    }
    return entry


def cmd_resolve(a):
    entries = load()
    idx = [i for i, e in enumerate(entries) if e["id"] == a.id]
    if not idx:
        sys.exit(f"not found: {a.id}")
    e = entries[idx[0]]
    if e["status"] == "resolved" and not a.force:
        sys.exit(f"{a.id} already resolved (--force to redo)")
    if e["target_date"] > today() and not a.force:
        sys.exit(f"{a.id} not due until {e['target_date']} (--force to resolve early)")
    realized = a.realized
    if realized is None and a.realized_pct is not None:
        realized = e["spot"] * (1 + a.realized_pct / 100.0)
    entries[idx[0]] = _resolve_entry(e, realized=realized,
                                     realized_date=a.realized_date,
                                     method="manual" if realized else "manual")
    save(entries)
    print(json.dumps(entries[idx[0]]["resolution"], ensure_ascii=False))


def cmd_resolve_due(a):
    entries = load()
    done, failed = [], []
    for i, e in enumerate(entries):
        if e["status"] == "pending" and e["target_date"] <= today():
            try:
                entries[i] = _resolve_entry(dict(e))
                done.append(entries[i])
            except Exception as ex:  # noqa: BLE001
                failed.append({"id": e["id"], "error": str(ex)})
    save(entries)
    for e in done:
        r = e["resolution"]
        print(f"✅ {e['id']}: EV {e['ev_pct']:+.2f}% → realized "
              f"{r['realized_pct']:+.2f}% (Δ {r['vs_ev_pp']:+.2f}pp, "
              f"bucket={r['bucket']}, brier={r['brier']}, {r['method']})")
    for f in failed:
        print(f"⚠️ {f['id']}: {f['error']}")
    if not done and not failed:
        print("nothing due")


def cmd_due(a):
    entries = load()
    due = [e for e in entries
           if e["status"] == "pending" and e["target_date"] <= today()]
    print(json.dumps({"count": len(due), "due": [
        {"id": e["id"], "target_date": e["target_date"], "ev_pct": e["ev_pct"]}
        for e in due]}, ensure_ascii=False, indent=1))


def cmd_list(a):
    entries = load()
    if a.ticker:
        entries = [e for e in entries if e["ticker"] == a.ticker.upper()]
    if a.status:
        entries = [e for e in entries if e["status"] == a.status]
    for e in entries:
        r = e.get("resolution") or {}
        tail = (f" → {r.get('realized_pct'):+.2f}% Δ{r.get('vs_ev_pp'):+.2f}pp "
                f"[{r.get('bucket')}]" if r else "")
        print(f"{e['status']:8s} {e['id']:42s} {e['forecast_date']} "
              f"h{e['horizon_days']:<4d} EV {e['ev_pct']:+6.2f}%{tail}")


def cmd_stats(a):
    entries = load()
    resolved = [e for e in entries if e["status"] == "resolved"]
    pending = [e for e in entries if e["status"] == "pending"]
    print(f"total {len(entries)} | resolved {len(resolved)} | pending {len(pending)}")
    if not resolved:
        return
    errs = [e["resolution"]["vs_ev_pp"] for e in resolved]
    print(f"\nEV error (realized − EV, pp): mean {sum(errs)/len(errs):+.2f} | "
          f"mean|.| {sum(abs(x) for x in errs)/len(errs):.2f} | n={len(errs)}")
    n_ind = independent_n(resolved)
    print(f"獨立 n（target_date {CLUSTER_DAYS} 天內視同一叢）: {n_ind} / {len(resolved)} 筆"
          f"{'  ⚠️ n<30 只記方向，不改規則' if n_ind < 30 else ''}")
    withp = [e for e in resolved if e["resolution"]["bucket"] is not None
             and e.get("p_bull") is not None]
    briers = [e["resolution"]["brier"] for e in withp
              if e["resolution"]["brier"] is not None]
    if briers:
        n = len(withp)
        bs = sum(briers) / len(briers)
        # climatology reference: always forecast the realized bucket frequencies
        freq = {cls: sum(1 for e in withp if e["resolution"]["bucket"] == cls) / n
                for cls in ("bull", "base", "bear")}
        bs_clim = sum(sum((freq[c] - (1.0 if e["resolution"]["bucket"] == c else 0.0)) ** 2
                          for c in ("bull", "base", "bear")) for e in withp) / n
        bs_unif = 2.0 / 3.0
        bss_clim = 1 - bs / bs_clim if bs_clim > 0 else float("nan")
        bss_unif = 1 - bs / bs_unif
        print(f"Brier mean {bs:.4f} | n={len(briers)}")
        print(f"Brier skill score: vs climatology(基準=永遠報實際落桶頻率) {bss_clim:+.3f} | "
              f"vs uniform(1/3) {bss_unif:+.3f}   ← >0 才算技能；<0 = 不如不預測")
    # in-range: outcome inside pre-registered distribution?
    ranged = []
    for e in resolved:
        r = e["resolution"]
        ir = r.get("in_range")
        if ir is None and e.get("fv_bull") is not None:
            ir, tl = range_check(e, r["realized"])
            r["in_range"], r["tail"] = ir, tl
        if ir is not None:
            ranged.append(e)
    if ranged:
        outside = [e for e in ranged if not e["resolution"]["in_range"]]
        print(f"\n落在事前分布內: {len(ranged)-len(outside)}/{len(ranged)}"
              f"  （分布外 = 模型漏了一支，不是運氣）")
        for e in outside:
            r = e["resolution"]
            print(f"  ✗ {e['id']:42s} realized {r['realized_pct']:+.1f}% "
                  f"{'低於' if r['tail']=='below' else '高於'}分布邊界")
    # calibration: avg predicted prob vs realized frequency
    if withp:
        n = len(withp)
        print(f"\ncalibration (n={n} with probs+bucket):")
        print(f"{'class':6s} {'avg predicted':>14s} {'realized freq':>14s}")
        for cls, pk in (("bull", "p_bull"), ("base", "p_base"), ("bear", "p_bear")):
            pred = sum(e[pk] for e in withp) / n
            freq_c = 100.0 * sum(1 for e in withp
                                 if e["resolution"]["bucket"] == cls) / n
            print(f"{cls:6s} {pred:13.1f}% {freq_c:13.1f}%")
    # thesis × pricing 2×2 (thesis verdict from thesis-ledger; pricing = realized vs EV)
    quad = {"命中": [], "對但沒用": [], "運氣好": [], "失效": [], "partial": []}
    for e in resolved:
        v = thesis_verdict(e.get("thesis_ref"))
        if v is None:
            continue
        d = e["resolution"]["vs_ev_pp"]
        if v == "partial":
            quad["partial"].append(e)
        elif v == "passed":
            quad["命中" if d >= 0 else "對但沒用"].append(e)
        else:
            quad["運氣好" if d >= 0 else "失效"].append(e)
    if any(quad.values()):
        print("\nthesis × 定價 2×2（thesis 由 thesis-ledger 判、定價 = realized ≥ EV）:")
        print(f"  {'':10s}{'realized ≥ EV':>14s}{'realized < EV':>14s}")
        print(f"  {'thesis 對':10s}{len(quad['命中']):>14d}{len(quad['對但沒用']):>14d}")
        print(f"  {'thesis 錯':10s}{len(quad['運氣好']):>14d}{len(quad['失效']):>14d}"
              f"   (partial {len(quad['partial'])})")
        if quad["對但沒用"]:
            print("  priced-in 候選（thesis 對、定價錯 → 查買進當時共識是否已高於 thesis）:")
            for e in quad["對但沒用"]:
                print(f"    {e['id']:42s} Δ {e['resolution']['vs_ev_pp']:+.1f}pp")
        if quad["運氣好"]:
            print("  運氣好（thesis 錯但賺 → 不計命中）: " + ", ".join(e["id"] for e in quad["運氣好"]))
    # priced-in branch calibration: pre-registered P(up | thesis right) vs realized
    pu = [e for e in quad["命中"] + quad["對但沒用"] if e.get("p_up_given_thesis") is not None]
    if pu:
        pred = sum(e["p_up_given_thesis"] for e in pu) / len(pu)
        real = 100.0 * sum(1 for e in pu if e["resolution"]["vs_ev_pp"] >= 0) / len(pu)
        print(f"\npriced-in 校準：事前 P(漲|thesis 對) 均 {pred:.0f}% vs 實際 {real:.0f}% (n={len(pu)})")
    # by horizon band / model
    for key, label in (
            (lambda e: horizon_band(e["horizon_days"]), "horizon"),
            (lambda e: e.get("model") or "?", "model")):
        groups = {}
        for e in resolved:
            groups.setdefault(key(e), []).append(e["resolution"]["vs_ev_pp"])
        print(f"\nby {label}:")
        for g, xs in sorted(groups.items()):
            print(f"  {g:12s} n={len(xs):<3d} mean Δ {sum(xs)/len(xs):+.2f}pp "
                  f"| mean|Δ| {sum(abs(x) for x in xs)/len(xs):.2f}pp")


# ── cli ─────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="pre-register an EV forecast (upsert while pending)")
    a.add_argument("--ticker", required=True)
    a.add_argument("--slug", help="id suffix; default fYYYYMMDD-hN")
    a.add_argument("--forecast-date", help="default today")
    a.add_argument("--horizon-days", type=int, required=True)
    a.add_argument("--spot", type=float, required=True)
    a.add_argument("--p-bull", type=float)
    a.add_argument("--p-base", type=float)
    a.add_argument("--p-bear", type=float)
    a.add_argument("--fv-bull", type=float)
    a.add_argument("--fv-base", type=float)
    a.add_argument("--fv-bear", type=float)
    a.add_argument("--ev-price", type=float)
    a.add_argument("--ev-pct", type=float)
    a.add_argument("--source", default="manual")
    a.add_argument("--model", default="claude-opus-4-8")
    a.add_argument("--thesis-ref")
    a.add_argument("--p-up-given-thesis", type=float,
                   help="P(price up | thesis right) in %%; required with --thesis-ref")
    a.add_argument("--priced-in-basis", help="one line: thesis value vs consensus already priced")
    a.add_argument("--note")
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("resolve", help="resolve one entry (auto price unless --realized)")
    r.add_argument("--id", required=True)
    r.add_argument("--realized", type=float, help="manual realized price/value")
    r.add_argument("--realized-pct", type=float, help="manual realized return %%")
    r.add_argument("--realized-date")
    r.add_argument("--force", action="store_true")
    r.set_defaults(func=cmd_resolve)

    rd = sub.add_parser("resolve-due", help="auto-resolve everything past target date")
    rd.set_defaults(func=cmd_resolve_due)

    d = sub.add_parser("due", help="list entries past target date")
    d.set_defaults(func=cmd_due)

    li = sub.add_parser("list", help="list entries")
    li.add_argument("--ticker")
    li.add_argument("--status")
    li.set_defaults(func=cmd_list)

    st = sub.add_parser("stats", help="EV error, Brier, calibration table")
    st.set_defaults(func=cmd_stats)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
