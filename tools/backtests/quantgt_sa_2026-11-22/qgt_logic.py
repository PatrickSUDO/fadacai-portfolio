import json,sys,warnings,glob,re; warnings.filterwarnings('ignore')
import pandas as pd, numpy as np, yfinance as yf
df=pd.read_csv(sys.argv[1])
# early small-cap check
for t in ('TTD','MSTR','SMCI','CVNA','W','APP','PLTR'):
    print(t, sorted(df[df.ticker==t].month)[:6])
u=json.load(open('briefing-out/cache/universe.json'))
def flat(x):
    out=set()
    if isinstance(x,dict):
        for v in x.values(): out|=flat(v)
    elif isinstance(x,list):
        for v in x: out|=flat(v) if not isinstance(v,str) else {v}
    return out
uni=sorted({t for t in flat(u) if re.fullmatch(r'[A-Z.\-]{1,6}',t)}|set(df.ticker))
print('universe',len(uni))
px=yf.download(uni,start='2015-06-01',auto_adjust=True,progress=False,threads=True)['Close']
px=px.dropna(axis=1,how='all'); me=px.resample('ME').last(); me.index=me.index.strftime('%Y-%m')
looks={'1m':(1,0),'3m':(3,0),'6m':(6,0),'12m':(12,0),'12-1':(12,1),'6-1':(6,1)}
mom={k:(me.shift(s)/me.shift(L)-1) for k,(L,s) in looks.items()}
nxt=me.shift(-1)/me-1
months=sorted(df.month.unique()); res={k:[] for k in looks}; rep={k:{} for k in looks}
for m in months:
    i=me.index.get_loc(m)-1 if m in me.index else None
    if i is None or i<12: continue
    pm=me.index[i]; picks=set(df[df.month==m].ticker)
    for k in looks:
        s=mom[k].loc[pm].dropna(); r=s.rank(ascending=False)
        got=[r.get(t) for t in picks if t in r]
        res[k].append((np.mean([g<=5 for g in got]),np.mean([g<=20 for g in got]),np.median([g/len(r) for g in got])))
        top=r[r<=5].index; rep[k][m]=nxt.loc[pm,top].mean()*100
print('lookback: picks in top5 / top20 / median pct-rank')
for k in looks: a=np.array(res[k]); print(' ',k,a.mean(0).round(2), 'n months',len(a))
q=df.groupby('month').return_pct.mean()
R=pd.DataFrame(rep); R['QGT']=q; R=R.dropna()
spy=yf.download('SPY',start='2015-06-01',auto_adjust=True,progress=False)['Close'].squeeze().resample('ME').last().pct_change()*100; spy.index=spy.index.strftime('%Y-%m'); R['SPY']=spy
def st(x): x=x/100; return 'CAGR %.0f%% MDD %.0f%% corr_QGT %.2f'%(((1+x).prod()**(12/len(x))-1)*100, (((1+x).cumprod()/(1+x).cumprod().cummax())-1).min()*100, np.corrcoef(x,R.QGT)[0,1])
for c in R: print(' replica',c,st(R[c]))
