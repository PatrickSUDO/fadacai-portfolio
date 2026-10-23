import yfinance as yf, pandas as pd, numpy as np
tk=['^PPUT','^CLL','^BXM','^BXMD','^PUT','^SP500TR','^GSPC','^CLLZ']
px=yf.download(tk,start='1986-06-01',end='2026-10-23',auto_adjust=False,progress=False)['Close']
print(px.notna().sum()); print(px.dropna(how='all').head(3)); print(px.tail(3))
px.to_csv('cboe_idx_yf.csv')
