#!/usr/bin/env python3
"""spx_dip_shadow.py — SPX 短線回檔「轉折」影子帳（2026-10-31 用戶：quantgt.io SPX 多頭訊號放進影子）

Why：quantgt.io 的 SPX 15 分鐘均值回歸多頭訊號，2026-02 ~ 09 可見的 26 個訊號日 5/10/20 日中位 +0.88/+1.18/+1.75%、
勝率 73/73/77%；但對照「SPY 收 5 日新低」這條免費規則（+0.75/+1.23/+1.72%、68/68/74%）沒有增量，26 天裡 15 天本身
就是 5 日新低、其餘都在距 10 日高 1–3% 的回檔。空頭訊號無 edge（4 月連錯 6 次）。所以不訂閱、不抓它的訊號，
直接用同等觸發自己登影子：**SPY 收盤 = 5 日新低 且 距 10 日高 ≤ −2%** → `cf-spx-dip`（correct_if=over：30 天後
SPY 絕對報酬 > 0 = 訊號對；`shadow_signals.py score` 對 ticker==基準 的列用絕對報酬）。

**display-only**：不進任何買進閘門（H12：技術面只描述狀態不產生觸發）。兩期 /trade-review 命中 >60% 且平均 >0
才討論要不要當 R30 回檔單的排序加分；多頭年買回檔本來就贏，命中率要對照同期「任一日」基準讀。

Usage:
  python3 tools/spx_dip_shadow.py scan [--asof YYYY-MM-DD] [--dry-run]
  python3 tools/spx_dip_shadow.py backfill --from 2026-02-01 [--to YYYY-MM-DD]   # note 標 backfill，計分時可分組
  python3 tools/spx_dip_shadow.py status
Cache：briefing-out/cache/spx-dip-shadow.json（當日狀態：距 10 日高、是否 5 日新低、最近一筆）
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from shadow_signals import load_signals, save_signals  # noqa: E402

CACHE = ROOT / "briefing-out" / "cache"
SUMMARY = CACHE / "spx-dip-shadow.json"
KIND = "cf-spx-dip"
TICKER = "SPY"
LOW_N = 5            # 收盤 = 5 日新低
HIGH_N = 10          # 距 10 日高
DD_MIN = -2.0        # ≤ −2%
DEDUP_DAYS = 5       # 連續回檔日只登一筆（回測 de-cluster 同窗）


def closes(start: str, end: str):
    import pandas as pd  # noqa: PLC0415
    import yfinance as yf  # noqa: PLC0415
    px = yf.download(TICKER, start=start, end=(date.fromisoformat(end) + timedelta(days=1)).isoformat(),
                     progress=False, auto_adjust=False)
    if isinstance(px.columns, pd.MultiIndex):
        px.columns = px.columns.get_level_values(0)
    c = px["Close"].dropna()
    # yfinance 在午夜後會多回一根隔日盤後 bar（2026-10-30 案）→ 只留 ≤ asof
    return c[c.index.date <= date.fromisoformat(end)]


def state(c, i: int) -> dict:
    """第 i 根收盤的狀態。"""
    win_lo = c.iloc[max(0, i - LOW_N + 1): i + 1]
    win_hi = c.iloc[max(0, i - HIGH_N + 1): i + 1]
    close = float(c.iloc[i])
    dd = (close / float(win_hi.max()) - 1) * 100
    return {"date": c.index[i].date().isoformat(), "close": round(close, 2),
            "is_low5": bool(close <= float(win_lo.min())) and len(win_lo) == LOW_N,
            "dd_from_high10_pct": round(dd, 2),
            "signal": bool(close <= float(win_lo.min())) and len(win_lo) == LOW_N and dd <= DD_MIN}


def _record(rows, st: dict, note_prefix: str) -> dict:
    row = {"date": st["date"], "ticker": TICKER, "signal": KIND, "ref_price": st["close"], "size_usd": None,
           "note": f"{note_prefix}SPY 收 {LOW_N} 日新低、距 {HIGH_N} 日高 {st['dd_from_high10_pct']:+.1f}%；"
                   "30d 絕對報酬 >0 = 訊號對（quantgt 多頭同等觸發，display-only）",
           "correct_if": "over", "mode": "shadow", "status": "open"}
    rows.append(row)
    return row


def _dup(rows, d: str) -> bool:
    dd = date.fromisoformat(d)
    return any(r.get("signal") == KIND and abs((dd - date.fromisoformat(r["date"])).days) < DEDUP_DAYS for r in rows)


def cmd_scan(args) -> int:
    asof = args.asof or date.today().isoformat()
    c = closes((date.fromisoformat(asof) - timedelta(days=40)).isoformat(), asof)
    if len(c) < HIGH_N:
        print(json.dumps({"error": "not enough bars"})); return 1
    st = state(c, len(c) - 1)
    rows = load_signals()
    out = {**st, "recorded": False, "dup": False}
    if st["signal"]:
        if _dup(rows, st["date"]):
            out["dup"] = True
        elif not args.dry_run:
            _record(rows, st, ""); save_signals(rows); out["recorded"] = True
    last = [r for r in rows if r.get("signal") == KIND]
    out["last_signal"] = last[-1]["date"] if last else None
    out["open_total"] = len(last)
    CACHE.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_backfill(args) -> int:
    end = args.to or date.today().isoformat()
    c = closes((date.fromisoformat(args.frm) - timedelta(days=30)).isoformat(), end)
    rows = load_signals()
    added = []
    for i in range(HIGH_N - 1, len(c)):
        st = state(c, i)
        if st["date"] < args.frm or not st["signal"] or _dup(rows, st["date"]):
            continue
        added.append(_record(rows, st, "backfill ")["date"])
    if added and not args.dry_run:
        save_signals(rows)
    print(json.dumps({"backfilled": added, "n": len(added), "dry_run": args.dry_run}, ensure_ascii=False))
    return 0


def cmd_status(_args) -> int:
    rows = [r for r in load_signals() if r.get("signal") == KIND]
    print(json.dumps({"n": len(rows), "backfill": sum("backfill" in (r.get("note") or "") for r in rows),
                      "dates": [r["date"] for r in rows]}, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("--asof"); s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_scan)
    b = sub.add_parser("backfill"); b.add_argument("--from", dest="frm", required=True); b.add_argument("--to")
    b.add_argument("--dry-run", action="store_true"); b.set_defaults(fn=cmd_backfill)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
