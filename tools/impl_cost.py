#!/usr/bin/env python3
"""impl_cost.py — 實作成本：選股 vs 操作（2026-10-20 用戶「組合跟操作感覺比 SMH/QQQ 還糟」）

兩個數字，每期 /trade-review 第 0 節必列：
  1. 期內賣出 vs 抱到今天（依標的/依月）：賣出款若留在股票會多/少多少；若改買 SMH 會多/少多少
  2. **期初名單**買抱同期報酬 vs 帳戶同期報酬 vs SMH/QQQ/SPY——名單取 `--since` 當日收盤實際持有的現股
     （journal 2026-06-04 快照 + 成交帳重放，含期內清倉者；無倖存者偏差）。實際權重版 = 只拿掉期內操作；等權版 = 再拿掉權重判斷。
     2026-10-30 修：舊版取「現在仍持有的名字」等權買抱，期末名單只剩贏家，+62% 是倖存者偏差（core_satellite_backtest 查出）。
Usage: python3 tools/impl_cost.py [--since 2026-01-01] [--acct-start 198412 --acct-now 243838]
"""
import argparse, json, sys, warnings, collections; warnings.filterwarnings("ignore")
import numpy as np, yfinance as yf, pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import core_satellite_backtest as csb  # noqa: E402

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--since", default="2026-01-01")
    ap.add_argument("--acct-start", type=float, default=None); ap.add_argument("--acct-now", type=float, default=None); a = ap.parse_args()
    led = [json.loads(l) for l in open(ROOT / "research/trade-ledger.jsonl") if l.strip()]
    sells = [r for r in led if r.get("date", "") >= a.since and r.get("side") == "SOLD" and not r.get("is_option")
             and r["symbol"] not in ("SGOV", "BIL") and not str(r.get("origin_evidence") or "").startswith("VOID")]
    st = json.load(open(ROOT / "research/position-state.json")); held = [p["symbol"] for p in st["positions"] if p.get("bucket") in ("認列", "信念")]
    anchor_date, anchor_pos = csb.parse_anchor(csb.ANCHOR); fills = csb.load_fills()
    syms = sorted(({r["symbol"] for r in sells} | set(held) | {s for d, s, _ in fills if d >= a.since[:4] + "-01-01" and s not in csb.NON_STOCK} | set(anchor_pos)
                   | {"SMH", "QQQ", "SPY", "VOO"}) - {"SGOV", "BIL"})
    # 價格從 min(since, 快照錨 6/04) 前 10 天抓：positions_by_day 需要錨日落在序列內（短窗 --since 10/14 也要能重放）
    px_start = min(pd.Timestamp(a.since), pd.Timestamp(anchor_date)) - pd.Timedelta(days=10)
    px = yf.download(syms, start=px_start, progress=False, auto_adjust=True)["Close"].ffill()
    px = px.loc[px["VOO"].dropna().index]
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
    # ── 2. 期初名單買抱（無倖存者偏差）──
    days = px.index
    pos = csb.positions_by_day(days, anchor_date, anchor_pos, fills)
    g = days[days >= pd.Timestamp(a.since)][0]
    held0 = [s for s in pos.columns if pos.at[g, s] > 0.5 and s not in csb.NON_STOCK and s in px.columns and not np.isnan(px.at[g, s])]
    gone = [s for s in held0 if s not in held]
    mv = {s: pos.at[g, s] * px.at[g, s] for s in held0}; tot = sum(mv.values()) or 1.0
    paths = px.loc[g:, held0] / px.loc[g, held0]
    act_w = (paths * pd.Series({s: mv[s] / tot for s in held0})).sum(axis=1); eq = paths.mean(axis=1)
    mdd = lambda s: float((s / s.cummax() - 1).min())
    line = (f"=== 期初（{g.date()}）名單 {len(held0)} 檔買抱至今：實際權重 {act_w.iloc[-1]-1:+.1%}（MDD {mdd(act_w):.1%}）｜等權 {eq.iloc[-1]-1:+.1%}（MDD {mdd(eq):.1%}）")
    for b in ("SMH", "QQQ", "SPY"):
        s = px[b].dropna()[g:]; line += f"｜{b} {s.iloc[-1]/s.iloc[0]-1:+.1%}（MDD {mdd(s):.1%}）"
    if a.acct_start and a.acct_now:
        acct = a.acct_now / a.acct_start - 1
        line += f"｜帳戶 {acct:+.1%} → 操作成本（實際權重 − 帳戶）{(act_w.iloc[-1]-1)-acct:+.1%}；權重判斷價值（實際權重 − 等權）{(act_w.iloc[-1]-eq.iloc[-1]):+.1%}"
    print(line + f"（含期內清倉 {len(gone)} 檔：{' '.join(gone) if gone else '無'}；無倖存者偏差）")

if __name__ == "__main__":
    main()
