#!/usr/bin/env python3
"""backtest_coverage.py — 分析師覆蓋（N）對 revision 訊號預測力的回測（H13，2026-10-08）

讀 briefing-out/cache/archive/<day>/fundamentals-snapshot.json（每日凍結快照），以 curr_fy 的
revisions_up_30d / revisions_down_30d / eps_revision_30d_pct / eps_num_analysts 做訊號，
看 20 個交易日對 SPY 的超額，按 N 分三桶（<8 / 8–14 / ≥15），每檔每 20 交易日只取一筆獨立樣本。
/trade-review 每期重跑一次累積樣本；結果進 RULES-LEDGER H13。

Usage: python3 tools/backtest_coverage.py   （需 yfinance；在 repo 根目錄跑）
"""
import json,os,collections,statistics as st,warnings
warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd
base='briefing-out/cache/archive'; recs=[]; N_now={}
for day in sorted(os.listdir(base)):
    f=f'{base}/{day}/fundamentals-snapshot.json'
    if not os.path.exists(f): continue
    t=json.load(open(f)); t=t.get('tickers',t)
    for tk,x in t.items():
        c=(((x.get('snapshot') or {}).get('forward_estimates') or {}).get('curr_fy')) or {}
        n=c.get('eps_num_analysts')
        if n is None: continue
        recs.append((day,tk,float(n),float(c.get('revisions_up_30d') or 0),float(c.get('revisions_down_30d') or 0),c.get('eps_revision_30d_pct'))); N_now[tk]=float(n)
tks=sorted(N_now)+['SPY']
px=yf.download(tks,start='2026-07-20',end='2026-10-09',progress=False,auto_adjust=True)['Close']
px.index=[d.strftime('%Y-%m-%d') for d in px.index]; dates=list(px.index)
def fwd(tk,day,h=20):
    if day not in dates or tk not in px.columns: return None
    i=dates.index(day)
    if i+h>=len(dates): return None
    r=px[tk].iloc[i+h]/px[tk].iloc[i]-1; b=px['SPY'].iloc[i+h]/px['SPY'].iloc[i]-1
    return None if (pd.isna(r) or pd.isna(b)) else float(r-b)
buck=lambda n:'<8' if n<8 else ('8-14' if n<15 else '>=15')
def run(label,sigfn):
    out=collections.defaultdict(list); seen=set()
    for day,tk,n,up,dn,pct in recs:
        sig=sigfn(up,dn,pct)
        if not sig: continue
        ex=fwd(tk,day)
        if ex is None: continue
        key=(tk,dates.index(day)//20,sig)
        if key in seen: continue
        seen.add(key); out[(buck(n),'UP' if sig>0 else 'DOWN')].append(sig*ex)
    print(f'== {label} (獨立樣本：每檔每 20 交易日一筆) ==')
    for b in ('<8','8-14','>=15'):
        for s in ('UP','DOWN'):
            v=out.get((b,s),[])
            if len(v)<2: print(f'  {b:5} {s:4} n={len(v)}'); continue
            print(f'  {b:5} {s:4} n={len(v):2d} 跟著訊號做的 20 日超額：命中 {sum(1 for x in v if x>0)/len(v):.0%}  平均 {st.mean(v):+.1%}  中位 {st.median(v):+.1%}')
run('A. 用「上修家數 > 下修家數」當訊號', lambda up,dn,pct: 1 if up>dn else (-1 if dn>up else 0))
run('B. 用「共識 EPS 30 日變動 ≥ ±3%」當訊號（不看家數）', lambda up,dn,pct: (1 if pct>=3 else (-1 if pct<=-3 else 0)) if pct is not None else 0)
run('C. 兩者同向才算', lambda up,dn,pct: (1 if (up>dn and pct is not None and pct>=3) else (-1 if (dn>up and pct is not None and pct<=-3) else 0)))
