import yfinance as yf, pandas as pd, numpy as np
out={}
for t in ['^BXM','^BXMD','^PPUT','^CLL','^CLLZ','^PUT','^SP500TR','^GSPC']:
    try:
        h=yf.Ticker(t).history(period='2y',auto_adjust=False)['Close']
        h=h[~h.index.duplicated()]
        h.index=h.index.tz_localize(None)
        ye=h.loc[:'2025-12-31']
        if len(ye)==0: print(t,'no 2025 data; rows',len(h), h.index.min()); continue
        base=ye.iloc[-1]; last=h.iloc[-1]
        print(f"{t}: 2025-12-31 close {base:.2f} ({ye.index[-1].date()}), last {last:.2f} ({h.index[-1].date()}), YTD {(last/base-1)*100:.2f}%  | 2025 full-year: ", end='')
        y24=h.loc[:'2024-12-31']
        print(f"{(base/y24.iloc[-1]-1)*100:.2f}%" if len(y24) else 'n/a')
        out[t]=h
    except Exception as e: print(t,'ERR',e)
pd.DataFrame(out).to_csv('cboe_idx_2y.csv')
