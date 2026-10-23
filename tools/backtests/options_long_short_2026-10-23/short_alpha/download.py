import yfinance as yf, pandas as pd, sys, json
from universe import *
syms = sorted(set(test2_universe()) | ledger_sold_symbols() | {"SMH", "IGV", "SPY"})
print(len(syms), "tickers")
df = yf.download(syms, start="2014-01-01", end="2026-10-24", auto_adjust=True, progress=False, threads=True)
close = df["Close"]
failed = [s for s in syms if s not in close.columns or close[s].dropna().empty]
close = close.drop(columns=[c for c in failed if c in close.columns])
close.to_csv("prices_adjclose.csv")
json.dump({"requested": syms, "failed": failed, "n_ok": close.shape[1],
           "first_date": str(close.index.min().date()), "last_date": str(close.index.max().date())},
          open("download_meta.json", "w"), indent=1)
print("failed:", failed); print(close.shape, close.index.min(), close.index.max())
