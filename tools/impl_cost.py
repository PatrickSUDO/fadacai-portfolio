#!/usr/bin/env python3
"""impl_cost.py — 實作成本：選股 vs 操作（2026-10-20 用戶「組合跟操作感覺比 SMH/QQQ 還糟」）

兩個數字，每期 /trade-review 第 0 節必列：
  1. 期內賣出 vs 抱到今天（依標的/依月）：賣出款若留在股票會多/少多少；若改買 SMH 會多/少多少
  2. 當前持倉等權買抱同期報酬 vs 帳戶同期報酬 vs SMH/QQQ/SPY（有倖存者偏差：名單取期末）
Usage: python3 tools/impl_cost.py [--since 2026-01-01] [--acct-start 198412 --acct-now 243838]
"""
import argparse, json, warnings, collections; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--since", default="2026-01-01")
    ap.add_argument("--acct-start", type=float, default=None); ap.add_argument("--acct-now", type=float, default=None); a = ap.parse_args()
    led = [json.loads(l) for l in open(ROOT / "research/trade-ledger.jsonl") if l.strip()]
    sells = [r for r in led if r.get("date", "") >= a.since and r.get("side") == "SOLD" and not r.get("is_option")
             and r["symbol"] not in ("SGOV", "BIL") and not str(r.get("origin_evidence") or "").startswith("VOID")]
    st = json.load(open(ROOT / "research/position-state.json")); held = [p["symbol"] for p in st["positions"] if p.get("bucket") in ("認列", "信念")]
    syms = sorted({r["symbol"] for r in sells} | set(held) | {"SMH", "QQQ", "SPY"})
    px = yf.download(syms, start=pd.Timestamp(a.since) - pd.Timedelta(days=10), progress=False, auto_adjust=True)["Close"].ffill()
    smh = px["SMH"].dropna()
    by = collections.defaultdict(lambda: [0.0, 0, 0.0]); bym = collections.defaultdict(float); tot_vs_smh = 0.0
    for r in sells:
        s = r["symbol"]
        if s not in px.columns or px[s].dropna().empty: continue
        now = float(px[s].dropna().iloc[-1]); q = float(r["qty"]); pr = float(r["price"])
        d = (pr - now) * q; by[s][0] += d; by[s][1] += 1; by[s][2] += pr * q; bym[r["date"][:7]] += d
        s0 = smh[r["date"][:10]:]; s0 = float(s0.iloc[0]) if len(s0) else float(smh.iloc[-1])
        tot_vs_smh += pr * q * (float(smh.iloc[-1]) / s0 - 1)
    tot_d = sum(v[0] for v in by.values()); tot_amt = sum(v[2] for v in by.values())
    print(f"=== {a.since} 起賣出 vs 抱到今天（+ = 賣對）：合計 {tot_d:+,.0f}（賣出總額 ${tot_amt:,.0f}）；賣出款改買 SMH 會多 {tot_vs_smh:+,.0f} ===")
    for s, (d, n, amt) in sorted(by.items(), key=lambda kv: kv[1][0])[:8]:
        print(f"  {s:<5} n={n:2d} 賣 ${amt:>9,.0f}  vs抱著 {d:+9,.0f}  {'仍持有' if s in held else '已清倉'}")
    print("  依月：", {k: round(v) for k, v in sorted(bym.items())})
    eq = sum(px[k].dropna()[a.since:] / px[k].dropna()[a.since:].iloc[0] for k in held if k in px.columns) / len(held)
    mdd = lambda s: float((s / s.cummax() - 1).min())
    line = f"=== 持倉 {len(held)} 檔等權買抱 {a.since} 起 {eq.iloc[-1]-1:+.1%}（MDD {mdd(eq):.1%}）"
    for b in ("SMH", "QQQ", "SPY"):
        s = px[b].dropna()[a.since:]; line += f"｜{b} {s.iloc[-1]/s.iloc[0]-1:+.1%}（MDD {mdd(s):.1%}）"
    if a.acct_start and a.acct_now: line += f"｜帳戶 {a.acct_now/a.acct_start-1:+.1%} → 實作成本 {(eq.iloc[-1]-1)-(a.acct_now/a.acct_start-1):+.1%}"
    print(line + "（名單取期末，有倖存者偏差）")

if __name__ == "__main__":
    main()
