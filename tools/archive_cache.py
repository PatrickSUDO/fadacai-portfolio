#!/usr/bin/env python3
"""
archive_cache.py — Freeze each day's decision inputs so a past call can be re-derived.

Every cache under briefing-out/cache/ is overwritten daily. That makes one class of
question permanently unanswerable: "given only what was known on 2026-06-24, was that
call reasonable?" Reviewing a past decision with today's data is contaminated by
hindsight — the only clean protocol is to hand a model the original data cut with no
outcome and let it derive independently. That requires the inputs to still exist.

This is the one task in the improvement plan with a real deadline: a day that is not
archived is lost for good, exactly like the resting-order snapshots.

Cost is trivial — roughly 400KB/day, ~95MB/year, inside an already-gitignored tree.

Retention: keep every day for KEEP_DAILY_DAYS, then thin to month-start snapshots,
which preserves a usable long-run series without unbounded growth.

Usage
  python3 tools/archive_cache.py                 # archive today, then prune
  python3 tools/archive_cache.py --asof 2026-07-25
  python3 tools/archive_cache.py --list
  python3 tools/archive_cache.py --prune-only
"""

import argparse
import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "briefing-out" / "cache"
ARCHIVE = CACHE / "archive"

# Decision inputs worth freezing. Anything derived (eod-prices) is reproducible from
# the vendor and is deliberately excluded to keep the archive small.
TARGETS = [
    "fundamentals-snapshot.json",
    "macro-snapshot.json",
    "news-articles.json",
    "twitter-signals.json",
    "earnings-history.json",
    "earnings-dates.json",
    "pmcc-scan.json",
    "leading-indicators.json",
    "account-metrics.json",
]

KEEP_DAILY_DAYS = 120     # every day inside this window
# older than that: keep only the first archived day of each month


def _today(asof=None):
    return date.fromisoformat(asof) if asof else date.today()


def archive(asof=None, targets=TARGETS):
    day = _today(asof).isoformat()
    dest = ARCHIVE / day
    dest.mkdir(parents=True, exist_ok=True)
    copied, missing, total = [], [], 0
    for name in targets:
        src = CACHE / name
        if not src.exists():
            missing.append(name)
            continue
        shutil.copy2(src, dest / name)
        size = src.stat().st_size
        total += size
        copied.append({"file": name, "bytes": size})
    return {"date": day, "dir": str(dest.relative_to(ROOT)), "copied": copied,
            "missing": missing, "total_bytes": total}


def prune(asof=None, keep_daily_days=KEEP_DAILY_DAYS):
    """Keep everything recent; thin older archives to one per month."""
    if not ARCHIVE.exists():
        return {"removed": [], "kept": 0}
    cutoff = _today(asof) - timedelta(days=keep_daily_days)
    days = sorted(p for p in ARCHIVE.iterdir() if p.is_dir())
    seen_months, removed = set(), []
    for p in days:
        try:
            d = date.fromisoformat(p.name)
        except ValueError:
            continue
        if d >= cutoff:
            continue
        key = (d.year, d.month)
        if key in seen_months:
            shutil.rmtree(p)
            removed.append(p.name)
        else:
            seen_months.add(key)          # first archived day of that month survives
    return {"removed": removed, "kept": len([p for p in ARCHIVE.iterdir() if p.is_dir()])}


def listing():
    if not ARCHIVE.exists():
        return {"days": 0, "range": None, "total_bytes": 0}
    days = sorted(p.name for p in ARCHIVE.iterdir() if p.is_dir())
    total = sum(f.stat().st_size for f in ARCHIVE.rglob("*") if f.is_file())
    return {"days": len(days), "range": [days[0], days[-1]] if days else None,
            "total_bytes": total, "total_mb": round(total / 1e6, 1),
            "latest": days[-5:] if days else []}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Freeze daily decision inputs")
    ap.add_argument("--asof", default=None, help="YYYY-MM-DD (default today)")
    ap.add_argument("--list", action="store_true", dest="do_list")
    ap.add_argument("--prune-only", action="store_true")
    ap.add_argument("--keep-daily-days", type=int, default=KEEP_DAILY_DAYS)
    args = ap.parse_args(argv)

    if args.do_list:
        print(json.dumps(listing(), ensure_ascii=False, indent=2))
        return 0
    out = {}
    if not args.prune_only:
        out["archived"] = archive(args.asof)
    out["pruned"] = prune(args.asof, args.keep_daily_days)
    out["archive_state"] = listing()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
