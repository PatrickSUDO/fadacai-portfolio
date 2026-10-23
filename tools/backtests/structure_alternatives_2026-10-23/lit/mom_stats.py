import pandas as pd, numpy as np, io, sys
def load(path, col):
    lines = open(path).read().splitlines()
    rows=[]
    for l in lines:
        p=l.split(',')
        if len(p)>=2 and p[0].strip().isdigit() and len(p[0].strip())==6:
            rows.append((p[0].strip(), [float(x) for x in p[1:]]))
    idx=pd.to_datetime([r[0] for r in rows], format='%Y%m')
    return pd.DataFrame([r[1] for r in rows], index=idx)
mom = load('ff/F-F_Momentum_Factor.CSV',0); mom.columns=['Mom']
ff = load('ff/F-F_Research_Data_Factors.CSV',0); ff.columns=['MktRF','SMB','HML','RF']
df = mom.join(ff, how='inner')/100
def stats(r, label):
    ann = r.mean()*12; vol = r.std()*np.sqrt(12); sh = ann/vol
    cum=(1+r).cumprod(); dd=(cum/cum.cummax()-1).min()
    print(f"{label}: mean {ann*100:.1f}%/yr vol {vol*100:.1f}% Sharpe(mean/vol, excess for Mom) {sh:.2f} MDD {dd*100:.1f}% skew {r.skew():.2f} n={len(r)} {r.index[0].date()}..{r.index[-1].date()}")
for s,e in [('1927-01','2026-08'),('2010-01','2026-08'),('2000-01','2026-08')]:
    d=df.loc[s:e]
    stats(d['Mom'], f'Mom L/S {s}-{e}')
    stats(d['MktRF'], f'Mkt-RF {s}-{e}')
# 2009 crash
d9=df.loc['2009-03':'2009-05','Mom']; print('Mom Mar-May 2009 cum:', ((1+d9).prod()-1)*100)
print('Mom 2009 full year:', ((1+df.loc['2009','Mom']).prod()-1)*100)
print('Mom 1932 Jul-Aug:', ((1+df.loc['1932-07':'1932-08','Mom']).prod()-1)*100)
print('Mom worst months:'); print((df['Mom'].sort_values().head(8)*100).round(1))
print('Mom 2020 full year:', ((1+df.loc['2020','Mom']).prod()-1)*100)
print('Mom 2025..2026 ytd:', ((1+df.loc['2025','Mom']).prod()-1)*100, ((1+df.loc['2026','Mom']).prod()-1)*100)
