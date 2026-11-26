import json,sys,warnings; warnings.filterwarnings('ignore')
import pandas as pd, numpy as np, yfinance as yf
h=json.load(open(sys.argv[1]))
rows=[]
for m in h:
    for p in m['picks']:
        if 'ticker' in p: rows.append(dict(month=m['month'],**{k:p.get(k) for k in ('ticker','sector','market_cap','entry_ts','exit_ts','return_pct')}))
df=pd.DataFrame(rows); print('months',df.month.nunique(),df.month.min(),df.month.max(),'picks',len(df),'per month',df.groupby('month').size().value_counts().to_dict())
print('extra keys', {k for m in h for k in m if k not in('month','picks')}, {k for m in h for p in m['picks'] for k in p})
pm=df.groupby('month').return_pct.mean()
bench=yf.download(['SPY','QQQ','MTUM','SMH'],start='2017-06-01',auto_adjust=True,progress=False)['Close']
bm=bench.resample('ME').last().pct_change()*100; bm.index=bm.index.strftime('%Y-%m')
j=pd.concat([pm.rename('QGT'),bm],axis=1).dropna(subset=['QGT'])
def stats(x):
    x=x.dropna()/100; n=len(x); cagr=(np.prod(1+x))**(12/n)-1; eq=(1+x).cumprod(); mdd=(eq/eq.cummax()-1).min()
    return f'n={n} CAGR {cagr*100:.1f}% vol {x.std()*np.sqrt(12)*100:.0f}% Sharpe {x.mean()/x.std()*np.sqrt(12):.2f} MDD {mdd*100:.0f}% worst {x.min()*100:.0f}%'
for lab,sub in (('all',j),('<=2023',j[j.index<='2023-12']),('2024',j[(j.index>='2024-01')&(j.index<='2024-12')]),('2025',j[(j.index>='2025-01')&(j.index<='2025-12')]),('2026',j[j.index>='2026-01'])):
    print('==',lab); [print('  ',c,stats(sub[c])) for c in ('QGT','SPY','QQQ','MTUM','SMH')]
    d=(sub.QGT-sub.SPY); print('   QGT-SPY monthly mean %.2f hit %.0f%% t=%.2f | vs MTUM mean %.2f hit %.0f%% | vs SMH mean %.2f'%(d.mean(),(d>0).mean()*100,d.mean()/d.std()*np.sqrt(len(d)),(sub.QGT-sub.MTUM).mean(),((sub.QGT-sub.MTUM)>0).mean()*100,(sub.QGT-sub.SMH).mean()))
print(j.tail(14).round(1).to_string())
print('sector mix:',df.sector.value_counts().head(8).to_dict())
print('mcap min/median $B', df.market_cap.min()/1e9, df.market_cap.median()/1e9)
print('top tickers', df.ticker.value_counts().head(15).to_dict())
# hold-over rate
prev=None; keep=[]
for m,g in df.sort_values('month').groupby('month'):
    s=set(g.ticker); 
    if prev is not None: keep.append(len(s&prev))
    prev=s
print('avg names carried over per month', np.mean(keep))
df.to_csv(sys.argv[2],index=False)
