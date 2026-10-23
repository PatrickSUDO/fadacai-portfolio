import numpy as np, pandas as pd, yfinance as yf, json
# Annual returns from HFR Media Reference Guide 2024.09.09 (mondovisione mirror), tables per year; 2024 EH from HFR year-end (+12.3) / trade press (+12.0); 2025 EH +17.05 (Integrity Research)
eh = {2013:14.28,2014:1.81,2015:-0.97,2016:5.47,2017:13.29,2018:-7.14,2019:13.71,2020:17.89,2021:11.67,2022:-10.13,2023:11.37}
emn= {2013:6.46,2014:3.06,2015:4.27,2016:2.23,2017:4.88,2018:-0.98,2019:2.33,2020:-0.11,2021:7.05,2022:1.21,2023:5.97}
px=yf.download(['SPY','QQQ'],start='2012-12-20',end='2024-01-05',auto_adjust=True,progress=False)['Close']
ye=px.resample('YE').last(); yr=ye.pct_change().dropna()*100; yr.index=yr.index.year
def st(d,label):
    r=pd.Series(d)/100; yrs=len(r); cagr=(1+r).prod()**(1/yrs)-1; vol=r.std(ddof=1)
    print(f"{label} {min(d)}-{max(d)}: CAGR {cagr*100:.2f}% annual-return stdev {vol*100:.2f}% Sharpe(rf=1.2% avg T-bill 2013-23 approx) {(cagr-0.012)/vol:.2f} worst year {min(d.values()):.2f}")
st(eh,'HFRI Equity Hedge (Total)'); st(emn,'HFRI EH: Equity Market Neutral')
for t in ['SPY','QQQ']:
    d={int(y):float(v) for y,v in yr[t].loc[2013:2023].items()}; st(d,t+' (yfinance adj, calendar yrs)')
# BXM YTD derivation
bxm_last=2557.03; ye25=167.95/0.0730; print('BXM 2025-12-31 implied level (Barchart +167.95=+7.30% as of Jul-2026):',round(ye25,2),' -> YTD to 10/22/2026:',round((bxm_last/ye25-1)*100,2),'%')
print('S&P 500 TR YTD to 10/22/2026 (yfinance ^SP500TR): 12.98%')
