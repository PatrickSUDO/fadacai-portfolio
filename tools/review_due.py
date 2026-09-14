#!/usr/bin/env python3
"""Review cadence checker (2026-09-14).

Why this exists: the "交易檢討已到期 → 執行 /trade-review" reminder lived only as prose in
briefing SKILL.md Step 0.75.5 and the 2026-09-14 telegram tier simply skipped it (16 days
after the last review). Same lesson as flag discipline: a rule that lives in prose gets
dropped; a rule that lives in code and pushes to Telegram on its own cannot be skipped.

Checks (all dates derived from files, never from memory):
  trade-review     research/last-trade-review.txt              cadence 14d  (hard: >14 due, >21 🔴)
  portfolio-review newest briefing-out/portfolio-review-*.md   cadence 30d  (info: >30 due, >45 🔴)
  sa-quant-scan    newest research/sa-quant-scans/*.md         cadence 35d  (info: >35 due, >50 🔴)

Usage:
  python3 tools/review_due.py            # human lines; exit 2 if anything due, else 0
  python3 tools/review_due.py --json     # machine-readable (also written to briefing-out/cache/review-due.json)
"""
import glob
import json
import os
import re
import sys
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "briefing-out", "cache", "review-due.json")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

CHECKS = [
    # key, label, cadence_days, red_days, how to find last date
    ("trade-review", "/trade-review 交易檢討", 14, 21, "file:research/last-trade-review.txt"),
    ("portfolio-review", "/portfolio-review 全書檢視", 30, 45, "glob:briefing-out/portfolio-review-*.md"),
    ("sa-quant-scan", "SA 量化榜掃描", 35, 50, "glob:research/sa-quant-scans/*.md"),
]


def _last_date(spec: str):
    kind, _, path = spec.partition(":")
    full = os.path.join(ROOT, path)
    if kind == "file":
        if not os.path.exists(full):
            return None
        m = DATE_RE.search(open(full).read())
        return date.fromisoformat(m.group(1)) if m else None
    # glob: take the max date embedded in filenames (NOT mtime — mtime lies after edits/restores)
    dates = []
    for f in glob.glob(full):
        m = DATE_RE.search(os.path.basename(f))
        if m:
            try:
                dates.append(date.fromisoformat(m.group(1)))
            except ValueError:
                pass
    return max(dates) if dates else None


def run(today: date | None = None) -> dict:
    today = today or date.today()
    items = []
    for key, label, cadence, red, spec in CHECKS:
        last = _last_date(spec)
        days = (today - last).days if last else None
        if last is None:
            status = "unknown"
        elif days > red:
            status = "red"
        elif days > cadence:
            status = "due"
        else:
            status = "ok"
        items.append({
            "key": key, "label": label, "last": last.isoformat() if last else None,
            "days": days, "cadence_days": cadence, "red_days": red, "status": status,
        })
    out = {"asof": today.isoformat(), "items": items,
           "any_due": any(i["status"] in ("due", "red", "unknown") for i in items)}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out


def lines(out: dict) -> list[str]:
    res = []
    for i in out["items"]:
        if i["status"] == "ok":
            continue
        icon = "🔴" if i["status"] == "red" else "📋"
        if i["status"] == "unknown":
            res.append(f"📋 {i['label']}：找不到上次日期（{i['key']}）→ 請確認檔案")
            continue
        res.append(
            f"{icon} {i['label']}已到期（上次 {i['last']}，{i['days']} 天前；週期 {i['cadence_days']} 天）"
            + ("→ 今天執行，不再延" if i["status"] == "red" else "→ 執行")
        )
    return res


if __name__ == "__main__":
    out = run()
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for ln in lines(out):
            print(ln)
        if not out["any_due"]:
            print("✅ 檢討/review 週期皆未到期")
    sys.exit(2 if out["any_due"] else 0)
