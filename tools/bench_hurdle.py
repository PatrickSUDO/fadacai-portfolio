#!/usr/bin/env python3
"""bench_hurdle.py — R35 新倉門檻裁決：新名字的 12 個月 EV 贏不贏對應基準 ETF（2026-10-20 用戶）

Usage: python3 tools/bench_hurdle.py TICKER --ev 25.9 [--bench SMH|QQQ|IGV|VOO]
  bench 缺省：trade_ledger.SEMI_AI → SMH；position_guard.SECTOR_ETF 軟體 → IGV；其餘 VOO。
  輸出 PASS/FAIL：EV ≥ hurdle + margin（research/benchmark-hurdles.json）。FAIL = 不開新倉，錢留在停泊（R33 VOO）。
  只管「新名字」；既有領導者加碼走 R30，不走這裡。
"""
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

def bench_for(tk: str) -> str:
    try:
        from trade_ledger import SEMI_AI
        if tk.upper() in SEMI_AI: return "SMH"
    except Exception:
        pass
    try:
        import position_guard as pg
        for etf, members in getattr(pg, "SECTOR_ETF", {}).items():
            if tk.upper() in members: return etf if etf in ("SMH", "IGV", "QQQ") else "VOO"
    except Exception:
        pass
    return "VOO"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("ticker"); ap.add_argument("--ev", type=float, required=True, help="12 個月 EV（%）"); ap.add_argument("--bench", default=None)
    a = ap.parse_args(); cfg = json.loads((ROOT / "research/benchmark-hurdles.json").read_text())
    b = (a.bench or bench_for(a.ticker)).upper(); h = cfg["hurdle_12m_pct"].get(b, cfg["hurdle_12m_pct"]["VOO"]); m = cfg["margin_pp"]
    ok = a.ev >= h + m
    print(json.dumps({"ticker": a.ticker.upper(), "bench": b, "hurdle_12m_pct": h, "margin_pp": m, "required_ev_pct": h + m, "ev_pct": a.ev,
                      "verdict": "PASS" if ok else "FAIL", "action": "可開新倉（仍受 R31/R34 sizing/C7）" if ok else "不開新倉；錢留在停泊 VOO（R33）。要曝險就買該基準 ETF"}, ensure_ascii=False))
    return 0 if ok else 2

if __name__ == "__main__":
    raise SystemExit(main())
