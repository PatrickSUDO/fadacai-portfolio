#!/usr/bin/env python3
"""
check_trading_day.py — Exit 0 if TWSE (台灣證券交易所) is open today, exit 1 otherwise.

Supports FAKE_DATE env var (YYYY-MM-DD) for testing non-trading days.

Usage:
  python3 tools/check_trading_day.py && echo "trading day" || echo "holiday/weekend"
"""

import os
import sys
from datetime import date, datetime


def is_trading_day(check_date: date) -> bool:
    try:
        import exchange_calendars as xcals
        twse = xcals.get_calendar("XTAI")  # 台灣證券交易所
        return twse.is_session(check_date.isoformat())
    except ImportError:
        # fallback: skip weekends only (no holiday check)
        print("[check_trading_day] exchange_calendars not installed, falling back to weekday check",
              file=sys.stderr)
        return check_date.weekday() < 5  # 0-4 = Mon-Fri


def main() -> int:
    raw = os.environ.get("FAKE_DATE", "").strip()
    if raw:
        try:
            check_date = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            print(f"Invalid FAKE_DATE: {raw}", file=sys.stderr)
            return 2
    else:
        check_date = date.today()

    if is_trading_day(check_date):
        print(f"{check_date} is a TWSE trading day")
        return 0
    else:
        print(f"{check_date} is NOT a TWSE trading day — skipping briefing")
        return 1


if __name__ == "__main__":
    sys.exit(main())
