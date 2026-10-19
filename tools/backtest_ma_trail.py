#!/usr/bin/env python3
"""backtest_ma_trail.py — 「沿 N 日線停利/再進」對持倉名單的回測（2026-10-19 用戶問「改成沿十日線停利會不會比較好」）

對 roster 認列+信念桶每檔：收盤 < SMA(N) 隔日出、收盤 > SMA(N) 隔日回，對比買抱；印 YTD / 9/1 起的平均報酬、勝檔數、交易次數、MDD，
以及本波（10/7 起）逐檔首次跌破日與之後走勢。結果進 RULES-LEDGER H14。每期 /trade-review 可重跑。
Usage: python3 tools/backtest_ma_trail.py（repo 根目錄；需 yfinance）
"""
import json,warnings,statistics as st; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np
r=json.load(open('research/roster.json')); names=r['buckets']['認列']+r['buckets']['信念']
px=yf.download(names+['SPY','SMH'],start='2025-06-01',progress=False,auto_adjust=True)['Close'].dropna(how='all')
def sim(s, n, start, end=None):
    """從 start 起持有；收盤 < SMA(n) 隔日開盤賣出（近似用隔日收盤）、收盤 > SMA(n) 隔日買回。回傳 (策略報酬, 買抱報酬, 交易次數, 最大回撤策略, 最大回撤買抱)"""
    s=s.dropna(); ma=s.rolling(n).mean(); s=s[start:end]; ma=ma[start:end]
    if len(s)<n+5: return None
    pos=1; eq=[1.0]; bh=[1.0]; trades=0
    for i in range(1,len(s)):
        ret=s.iloc[i]/s.iloc[i-1]-1
        eq.append(eq[-1]*(1+ret*pos)); bh.append(bh[-1]*(1+ret))
        new=1 if s.iloc[i]>ma.iloc[i] else 0
        if new!=pos: trades+=1; pos=new
    eq=pd.Series(eq); bh=pd.Series(bh)
    mdd=lambda x: float((x/x.cummax()-1).min())
    return eq.iloc[-1]-1, bh.iloc[-1]-1, trades, mdd(eq), mdd(bh)
for n in (10,20,50):
    print(f'\n=== 沿 SMA{n} 停利/再進（收盤判定，隔日執行）vs 買抱 ===')
    for window,(a,b) in {'2026 YTD':('2026-01-02',None),'9/1 起':('2026-09-01',None),'10/7 起（這波）':('2026-10-07',None)}.items():
        rows=[]
        for t in names:
            if t not in px.columns: continue
            out=sim(px[t],n,a,b)
            if out: rows.append((t,)+out)
        if not rows: continue
        strat=st.mean(x[1] for x in rows); bh=st.mean(x[2] for x in rows); tr=st.mean(x[3] for x in rows)
        win=sum(1 for x in rows if x[1]>x[2]); 
        print(f'  {window:<12} 平均報酬 策略 {strat:+.1%} vs 買抱 {bh:+.1%} | 策略勝 {win}/{len(rows)} 檔 | 平均交易 {tr:.1f} 次 | 平均MDD 策略 {st.mean(x[4] for x in rows):.1%} vs 買抱 {st.mean(x[5] for x in rows):.1%}')
# 這波細看 SMA10：每檔何時跌破、以後怎麼走
print('\n=== SMA10 這波（10/7 起）逐檔：首次收盤跌破日 → 跌破價 vs 10/19 價 → 之後又站回幾次 ===')
for t in names:
    if t not in px.columns: continue
    s=px[t].dropna(); ma=s.rolling(10).mean(); w=s['2026-10-01':]; m=ma['2026-10-01':]
    below=w[w<m]
    if len(below)==0: print(f'  {t:<5} 沒跌破'); continue
    d0=below.index[0]; p0=float(w.loc[d0]); last=float(s.iloc[-1])
    flips=int(((w>m).astype(int).diff().abs()>0).sum())
    print(f'  {t:<5} 跌破 {d0.strftime("%m/%d")} @{p0:.2f} → 今 {last:.2f}（{100*(last/p0-1):+.1f}%）| 10 月翻轉 {flips} 次')
