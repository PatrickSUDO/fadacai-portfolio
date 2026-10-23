import yfinance as yf, pandas as pd, sys
tickers = ["SOXL","USD","TQQQ","QLD","SSO","SPXL","UPRO","TECL","SMH","SOXX","QQQ","SPY","VOO","^IRX","BIL","SGOV"]
out = {}
failed = []
for t in tickers:
    try:
        df = yf.download(t, start="1990-01-01", end="2026-10-23", auto_adjust=True, progress=False)
        if df is None or len(df)==0:
            failed.append(t); continue
        s = df["Close"]
        if isinstance(s, pd.DataFrame): s = s.iloc[:,0]
        s.name = t
        out[t] = s
        print(t, s.index[0].date(), s.index[-1].date(), len(s), round(float(s.iloc[-1]),2))
    except Exception as e:
        failed.append(t); print("FAIL", t, e)
px = pd.concat(out.values(), axis=1, sort=True)
px.to_csv("data/prices.csv")
print("failed:", failed)
