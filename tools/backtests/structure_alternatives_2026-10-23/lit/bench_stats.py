import yfinance as yf, numpy as np, pandas as pd
tk=['SPY','QQQ','SMH','^VIX']
px=yf.download(tk,start='2009-12-31',end='2026-10-23',auto_adjust=True,progress=False)['Close']
m=px.resample('ME').last()
rf=0.0  # report raw; note separately
for t in ['SPY','QQQ','SMH']:
    r=m[t].pct_change().dropna()
    for s,e in [('2010-01','2025-12'),('2010-01','2026-09'),('2026-01','2026-10')]:
        rr=r.loc[s:e]; 
        if len(rr)<3: continue
        yrs=len(rr)/12; cagr=(1+rr).prod()**(1/yrs)-1; vol=rr.std()*np.sqrt(12)
        cum=(1+rr).cumprod(); mdd=(cum/cum.cummax()-1).min()
        print(f"{t} {s}..{e}: CAGR {cagr*100:.1f}% vol {vol*100:.1f}% Sharpe(rf=0) {cagr/vol:.2f} Sharpe(rf=1.5%) {(cagr-0.015)/vol:.2f} MDD {mdd*100:.1f}%")
# YTD 2026 to 10/22
d=px.loc['2025-12-31':]
for t in ['SPY','QQQ','SMH']:
    print(t,'YTD 2026 to',d.index[-1].date(), round((d[t].iloc[-1]/d[t].iloc[0]-1)*100,2))
# VIX vs realized SPY vol 2010-2026: average VRP in vol points
spy=px['SPY'].pct_change()
rv=spy.rolling(21).std()*np.sqrt(252)*100
# forward realized 21d vs VIX at t
fwd=rv.shift(-21)
vrp=(px['^VIX']-fwd).dropna()
print('VIX - fwd 21d realized vol, mean (vol pts) 2010-2026:', round(vrp.loc['2010':].mean(),2), 'median', round(vrp.loc['2010':].median(),2), 'pct positive', round((vrp.loc['2010':]>0).mean()*100,1))
print('mean VIX', round(px['^VIX'].loc['2010':].mean(),2), 'mean fwd RV', round(fwd.loc['2010':].mean(),2))
