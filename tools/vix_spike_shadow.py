#!/usr/bin/env python3
"""vix_spike_shadow.py — VIX 飆升「買指數」影子帳 cf-vix-spike（2026-11-07 用戶「加入這個影子，希望以後能好好利用做出新策略」）

Why：事件研究（tools/backtests/vix_spike_timing_2026-11-07.py，1990→）VIX 收盤首次站上 30（前 20 個交易日沒站過，64 次）
之後 SPY 60 日 +5.8% vs 任意日 +2.7%、250 日 +17% vs +12%；站上 40（21 次）SPY 250 日 +29.7%／勝率 90%，QQQ +40%、SMH +48%。
優勢在 3–12 個月、不在 20 天；代價是 60 日內中位再跌 −5 到 −8%，熊市會連發（2008-09→2009-03 七次、2022 六次）。
看水位不看漲幅（單日 +25% 但低水位 ≈ 無）；等 VIX 回落 20% 的「確認版」比第一次站上還差。本書個股 2021→ 只 9 次、
60 日 +10.8% vs 基準 +9.4% → 個股層噪音大，要用就買指數（VOO/SMH），所以影子登 SPY（絕對報酬計分）+ SMH（對 SPY 相對）。

觸發：VIX 收盤 ≥30 且前 20 個交易日沒有任何收盤 ≥30 → 登一筆 tier=30；收盤 ≥40 且前 20 日沒有 ≥40 → 另登 tier=40。
**display-only**：不進任何買進閘門。`shadow_signals.py score` 30 天只是早讀；本工具 `score` 另算 20/60/120/250 日
（SPY/QQQ/SMH 絕對報酬），寫 cache。兩期 /trade-review 之後才討論要不要動用 $8k 緩衝分段買指數／2× ETF
（2× 研究：tools/backtests/vix_leveraged_etf_2026-11-07.py、research/vix-usage-evaluation-2026-11-07.md）。

Usage:
  python3 tools/vix_spike_shadow.py scan [--asof YYYY-MM-DD] [--dry-run]       # runner 每日跑
  python3 tools/vix_spike_shadow.py backfill --from 2024-01-01 [--to DATE]      # note 標 backfill，計分可分組
  python3 tools/vix_spike_shadow.py score [--asof DATE]                         # 20/60/120/250 日絕對報酬 → cache
  python3 tools/vix_spike_shadow.py status
Cache：briefing-out/cache/vix-spike-shadow.json（今日 VIX、20 日內最高、距觸發、最近一筆、長 horizon 計分）
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
SUMMARY = CACHE / "vix-spike-shadow.json"
KIND = "cf-vix-spike"
TIERS = (30, 40)
LOOKBACK = 20          # 前 20 個交易日沒站過 = 首次（回測 de-cluster 同窗）
LEGS = ("SPY", "SMH")  # SPY 絕對報酬；SMH 對 SPY 相對（trade_ledger.benchmark_for 不把 SMH 當半導體名）
HORIZONS = (20, 60, 120, 250)


def _px(symbols, start: str, end: str):
    import pandas as pd  # noqa: PLC0415
    import yfinance as yf  # noqa: PLC0415
    px = yf.download(list(symbols), start=start, end=(date.fromisoformat(end) + timedelta(days=1)).isoformat(),
                     progress=False, auto_adjust=True)
    c = px["Close"] if isinstance(px.columns, pd.MultiIndex) else px[["Close"]].rename(columns={"Close": symbols[0]})
    return c[c.index.date <= date.fromisoformat(end)]


def tier_hits(v, i: int) -> list[int]:
    """第 i 根 VIX 收盤觸發哪些 tier（首次：前 LOOKBACK 根都沒 ≥tier）。"""
    close = float(v.iloc[i]); prev = v.iloc[max(0, i - LOOKBACK): i]
    return [t for t in TIERS if close >= t and len(prev) == LOOKBACK and float(prev.max()) < t]


def _existing(rows, d: str, tier: int):
    return [r for r in rows if r.get("signal") == KIND and r.get("tier") == tier
            and abs((date.fromisoformat(d) - date.fromisoformat(r["date"])).days) <= LOOKBACK * 1.5]


def _record(rows, d: str, tier: int, vix_close: float, legs_px: dict, prefix: str) -> list[dict]:
    out = []
    for leg in LEGS:
        if legs_px.get(leg) is None:
            continue
        row = {"date": d, "ticker": leg, "signal": KIND, "tier": tier, "vix_close": round(vix_close, 2),
               "ref_price": round(float(legs_px[leg]), 2), "size_usd": None,
               "note": f"{prefix}VIX 收 {vix_close:.1f} 首次站上 {tier}（前 {LOOKBACK} 日未見）→ 影子買 {leg}；"
                       "主驗收 60/250 日（vix_spike_shadow.py score），30 日 score 只是早讀；display-only",
               "correct_if": "over", "mode": "shadow", "status": "open"}
        rows.append(row); out.append(row)
    return out


def cmd_scan(args) -> int:
    asof = args.asof or date.today().isoformat()
    px = _px(["^VIX", *LEGS], (date.fromisoformat(asof) - timedelta(days=60)).isoformat(), asof)
    v = px["^VIX"].dropna()
    if len(v) < LOOKBACK + 1:
        print(json.dumps({"error": "not enough VIX bars"})); return 1
    i = len(v) - 1; d = v.index[i].date().isoformat(); close = float(v.iloc[i])
    hits = tier_hits(v, i)
    rows = load_signals(); recorded, dup = [], []
    for t in hits:
        if _existing(rows, d, t):
            dup.append(t)
        elif not args.dry_run:
            _record(rows, d, t, close, {l: px[l].dropna().iloc[-1] for l in LEGS if l in px}, "")
            recorded.append(t)
    if recorded:
        save_signals(rows)
    mine = [r for r in rows if r.get("signal") == KIND]
    out = {"date": d, "vix_close": round(close, 2), "max_prev20": round(float(v.iloc[max(0, i - LOOKBACK): i].max()), 2),
           "tiers_hit": hits, "recorded": recorded, "dup": dup, "dry_run": args.dry_run,
           "last_signal": (mine[-1]["date"], mine[-1].get("tier")) if mine else None,
           "events_total": len({(r["date"], r.get("tier")) for r in mine})}
    CACHE.mkdir(parents=True, exist_ok=True)
    prev = json.loads(SUMMARY.read_text()) if SUMMARY.exists() else {}
    SUMMARY.write_text(json.dumps({**prev, **out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_backfill(args) -> int:
    end = args.to or date.today().isoformat()
    px = _px(["^VIX", *LEGS], (date.fromisoformat(args.frm) - timedelta(days=45)).isoformat(), end)
    v = px["^VIX"].dropna(); rows = load_signals(); added = []
    for i in range(LOOKBACK, len(v)):
        d = v.index[i].date().isoformat()
        if d < args.frm:
            continue
        for t in tier_hits(v, i):
            if _existing(rows, d, t):
                continue
            legs = {l: (px[l].loc[v.index[i]] if v.index[i] in px.index else None) for l in LEGS if l in px}
            _record(rows, d, t, float(v.iloc[i]), legs, "backfill "); added.append((d, t))
    if added and not args.dry_run:
        save_signals(rows)
    print(json.dumps({"backfilled": added, "n": len(added), "dry_run": args.dry_run}, ensure_ascii=False))
    return 0


def cmd_score(args) -> int:
    """長 horizon 絕對報酬（SPY/QQQ/SMH），每個事件一列；同 tier 彙總均值/勝率。"""
    asof = args.asof or date.today().isoformat()
    events = sorted({(r["date"], r.get("tier"), r.get("vix_close")) for r in load_signals() if r.get("signal") == KIND})
    if not events:
        print(json.dumps({"n": 0})); return 0
    syms = ["SPY", "QQQ", "SMH"]
    px = _px(syms, (date.fromisoformat(events[0][0]) - timedelta(days=5)).isoformat(), asof)
    out = []
    for d, tier, vc in events:
        import pandas as pd  # noqa: PLC0415
        ts = pd.Timestamp(d)
        if ts not in px.index:
            continue
        i = px.index.get_loc(ts); row = {"date": d, "tier": tier, "vix_close": vc}
        for s in syms:
            for h in HORIZONS:
                row[f"{s}_{h}d"] = round((float(px[s].iloc[i + h]) / float(px[s].iloc[i]) - 1) * 100, 1) if i + h < len(px) else None
        out.append(row)
    summary = {}
    for tier in TIERS:
        for s in syms:
            for h in HORIZONS:
                vals = [r[f"{s}_{h}d"] for r in out if r["tier"] == tier and r.get(f"{s}_{h}d") is not None]
                if vals:
                    summary[f"tier{tier}_{s}_{h}d"] = {"n": len(vals), "mean_pct": round(sum(vals) / len(vals), 1),
                                                       "hit_pct": round(100 * sum(x > 0 for x in vals) / len(vals), 0)}
    prev = json.loads(SUMMARY.read_text()) if SUMMARY.exists() else {}
    SUMMARY.write_text(json.dumps({**prev, "score_asof": asof, "events": out, "summary": summary}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print(json.dumps({"events": out, "summary": summary}, ensure_ascii=False))
    return 0


def cmd_status(_args) -> int:
    rows = [r for r in load_signals() if r.get("signal") == KIND]
    print(json.dumps({"rows": len(rows), "events": sorted({(r["date"], r.get("tier")) for r in rows}),
                      "backfill": sum("backfill" in (r.get("note") or "") for r in rows)}, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("--asof"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_scan)
    b = sub.add_parser("backfill"); b.add_argument("--from", dest="frm", required=True); b.add_argument("--to")
    b.add_argument("--dry-run", action="store_true"); b.set_defaults(fn=cmd_backfill)
    sc = sub.add_parser("score"); sc.add_argument("--asof"); sc.set_defaults(fn=cmd_score)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
