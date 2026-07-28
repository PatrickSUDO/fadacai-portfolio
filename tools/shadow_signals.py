#!/usr/bin/env python3
"""
shadow_signals.py — Record candidate risk signals without acting on them, then
score whether they were right.

A signal earns the authority to block a trade only after it has been measured.
Phase 1 therefore records flags and leaves every decision untouched; /trade-review
scores flags once they are 30 days old, and only then do we decide whether to
promote one to a hard gate.

First tenant: the A4 self-valuation overvaluation flag. CLAUDE.md 0e deliberately
keeps A4 out of median(A1,A2,A3) and out of EV, so when it read −50% on ON two days
before a −21% crash it changed nothing. A one-month forward test over the 2026-06-24
snapshot found the overvalued extreme informative — ONTO/ARM/ON/MYRG all
underperformed, mean −15.9% excess alpha, Spearman +0.45 (n=12) — while the
undervalued extreme carried no signal at all. n=12 across a single regime is enough
to justify tracking, not enough to justify blocking.

On not pre-filtering: DDOG was the one clear false positive (A4 −71% on a PE of 553,
then +19.0% alpha, the snapshot itself noting "我極保守"). Excluding high-PE names
looks tempting until you notice ARM sat at PE 474 and was a true positive at −20.9%.
PE cannot separate them at n=2, so `high_pe` is recorded as an attribute and scored
as a hypothesis rather than applied as a rule. Shadow mode blocks nothing, so
pre-filtering would only destroy the evidence needed to settle the question.

Storage: research/shadow-signals.jsonl  (one flag per line, deduped by ticker+date)

Usage
  python3 tools/shadow_signals.py flag                 # from the fundamentals cache
  python3 tools/shadow_signals.py flag --asof 2026-07-25
  python3 tools/shadow_signals.py score                # flags at least 30 days old
  python3 tools/shadow_signals.py list --open
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIGNALS = ROOT / "research" / "shadow-signals.jsonl"
FUNDAMENTALS = ROOT / "briefing-out" / "cache" / "fundamentals-snapshot.json"

# A4 overvaluation flag thresholds
A4_DIVERGENCE_MAX = -0.35     # own_target vs street_target: -35% or worse
HIGH_PE = 200.0               # recorded as an attribute, NOT an exclusion (see module docstring)
MATURE_DAYS = 30              # a flag is scorable this many days after being raised

SIGNAL_A4 = "a4-overvalued"


def _today(asof=None):
    return date.fromisoformat(asof) if asof else date.today()


def load_signals(path=SIGNALS):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").split("\n") if ln.strip()]


def save_signals(rows, path=SIGNALS):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for r in sorted(rows, key=lambda r: (r["date"], r["ticker"], r["signal"])):
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def a4_flags(cache, asof):
    """Evaluate the A4 overvaluation rule over every ticker in the cache."""
    raised, skipped = [], []
    for ticker, blob in (cache.get("tickers") or {}).items():
        sv = (blob or {}).get("self_valuation") or {}
        snap = (blob or {}).get("snapshot") or {}
        hl = snap.get("highlights") or {}
        own = sv.get("own_target_price")
        street = hl.get("wall_street_target")
        pe = hl.get("pe_ratio")
        conf = sv.get("confidence")

        if not own or not street:
            skipped.append({"ticker": ticker, "why": "missing own_target or wall_street_target"})
            continue
        if conf != "ok":
            skipped.append({"ticker": ticker, "why": f"self_valuation confidence={conf}"})
            continue
        divergence = (own - street) / street
        if divergence > A4_DIVERGENCE_MAX:
            continue
        raised.append({
            "date": asof,
            "ticker": ticker,
            "signal": SIGNAL_A4,
            "divergence_pct": round(divergence * 100, 1),
            "own_target": own,
            "street_target": street,
            "pe_ratio": pe,
            # Hypothesis under test, not a filter: DDOG (PE 553) was the false
            # positive, ARM (PE 474) a true positive. `score` reports hit rate split
            # on this so the question gets settled by data.
            "high_pe": bool(pe and pe > HIGH_PE),
            "confidence": conf,
            "mode": "shadow",
            "status": "open",
        })
    return raised, skipped


def cmd_flag(args):
    if not FUNDAMENTALS.exists():
        _emit({"error": f"no fundamentals cache at {FUNDAMENTALS} — run fetch_fundamentals.py"})
        return 1
    cache = json.loads(FUNDAMENTALS.read_text(encoding="utf-8"))
    asof = _today(args.asof).isoformat()
    raised, skipped = a4_flags(cache, asof)

    existing = load_signals(args.signals)
    seen = {(r["date"], r["ticker"], r["signal"]) for r in existing}
    new = [r for r in raised if (r["date"], r["ticker"], r["signal"]) not in seen]
    save_signals(existing + new, args.signals)
    _emit({
        "asof": asof,
        "cache_generated_at": cache.get("generated_at"),
        "flags_raised": len(raised),
        "newly_recorded": len(new),
        "flags": sorted(raised, key=lambda r: r["divergence_pct"]),
        "excluded": skipped if args.verbose else len(skipped),
        "rule": f"A4vsA3 <= {A4_DIVERGENCE_MAX * 100:.0f}% AND self_valuation.confidence == ok",
        "pe_note": (f"pe_ratio > {HIGH_PE:.0f} is tagged high_pe and scored separately, "
                    f"not excluded — see module docstring"),
        "mode": "shadow — records only, blocks nothing (Phase 1)",
    })
    return 0


def cmd_score(args):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from trade_ledger import benchmark_for, eod_series, load_env, _asof_close  # noqa: PLC0415

    load_env()
    rows = load_signals(args.signals)
    if not rows:
        _emit({"error": "no shadow signals recorded yet — run `flag` first"})
        return 1
    today = _today(args.asof)
    mature = [r for r in rows
              if (today - date.fromisoformat(r["date"])).days >= args.mature_days]
    if not mature:
        _emit({"signals": len(rows), "mature": 0,
               "note": f"no flag is {args.mature_days} days old yet; nothing to score",
               "earliest_flag": min(r["date"] for r in rows)})
        return 0

    start = min(r["date"] for r in mature)
    series, scored = {}, []
    for r in mature:
        sym, bench = r["ticker"], benchmark_for(r["ticker"])[:-3]
        for s in (sym, bench):
            if s not in series:
                try:
                    series[s] = eod_series(f"{s}.US", start, today.isoformat())
                except Exception as exc:                        # noqa: BLE001
                    series[s] = {}
                    print(f"⚠️  {s}: {exc}", file=sys.stderr)
        p0 = _asof_close(series[sym], r["date"])
        p1 = _asof_close(series[sym], today.isoformat())
        b0 = _asof_close(series[bench], r["date"])
        b1 = _asof_close(series[bench], today.isoformat())
        if not (p0 and p1 and b0 and b1):
            continue
        alpha = (p1 / p0 - 1) - (b1 / b0 - 1)
        # The flag claims the name is overvalued, so it is right when the name
        # underperforms its benchmark.
        scored.append({**{k: r[k] for k in ("date", "ticker", "signal", "divergence_pct")},
                       "benchmark": bench,
                       "price_then": p0, "price_now": p1,
                       "excess_alpha_pct": round(alpha * 100, 1),
                       "flag_correct": alpha < 0,
                       "high_pe": r.get("high_pe", False),
                       "days_held": (today - date.fromisoformat(r["date"])).days})

    def _band(rows_):
        if not rows_:
            return None
        return {"n": len(rows_),
                "hit_rate_pct": round(100 * sum(1 for s in rows_ if s["flag_correct"]) / len(rows_), 1),
                "mean_excess_alpha_pct": round(
                    sum(s["excess_alpha_pct"] for s in rows_) / len(rows_), 1)}

    _emit({
        "signals_total": len(rows),
        "scored": len(scored),
        "overall": _band(scored),
        # The DDOG-vs-ARM question: is A4 unreliable on triple-digit multiples?
        "by_pe_band": {
            f"pe_over_{HIGH_PE:.0f}": _band([s for s in scored if s["high_pe"]]),
            f"pe_under_{HIGH_PE:.0f}": _band([s for s in scored if not s["high_pe"]]),
        },
        "detail": sorted(scored, key=lambda s: s["excess_alpha_pct"]),
        "baseline": ("2026-07-25 backtest over the 2026-06-24 snapshot: 4/4 correct "
                     "(ONTO/ARM/ON/MYRG), mean -15.9% alpha, Spearman +0.45 "
                     "(n=12, single regime). DDOG was the lone false positive at +19.0%."),
        "promotion_rule": ("stay in shadow for at least 2 review cycles; promote to a "
                           "hard gate only if hit rate and mean alpha hold up, and only "
                           "with a PE carve-out if by_pe_band actually justifies one"),
    })
    return 0


def cmd_list(args):
    rows = load_signals(args.signals)
    if args.open:
        rows = [r for r in rows if r.get("status") == "open"]
    _emit({"count": len(rows), "signals": rows})
    return 0


def _emit(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _build_parser():
    p = argparse.ArgumentParser(description="Shadow-mode signal recorder and scorer")
    p.add_argument("--signals", default=str(SIGNALS))
    p.add_argument("--asof", default=None, help="override today (YYYY-MM-DD)")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("flag", help="evaluate rules against the fundamentals cache")
    f.add_argument("--verbose", action="store_true", help="list excluded tickers and why")

    s = sub.add_parser("score", help="score flags that have matured")
    s.add_argument("--mature-days", type=int, default=MATURE_DAYS)

    li = sub.add_parser("list", help="dump recorded flags")
    li.add_argument("--open", action="store_true")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)
    try:
        return {"flag": cmd_flag, "score": cmd_score, "list": cmd_list}[args.cmd](args)
    except Exception as exc:                                    # noqa: BLE001
        _emit({"error": str(exc), "cmd": args.cmd})
        return 1


if __name__ == "__main__":
    sys.exit(main())
