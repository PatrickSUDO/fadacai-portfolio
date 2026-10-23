import yfinance as yf, pandas as pd, json, sys, time
import os; OUT=os.path.dirname(os.path.abspath(__file__))
ETFS="VOO SPY QQQ QQQM VUG IWF SCHG MGK IWY SPMO MTUM XMMO QMOM QUAL COWZ RSP SPLV USMV XLK VGT SMH SOXX IGV AIQ BOTZ FDN SKYY CIBR WCLD PAVE GRID URA NLR ITA XLE GLD JEPQ JEPI QYLD BUFR ARKK".split()
HOLD="AMAT AMD AVGO MU NVDA DIOD SNPS LITE CLS ANET CRM CRWD DDOG NET TWLO PLTR BE GLD XLE VOO".split()
ALL=sorted(set(ETFS+HOLD+["^IRX"]))
df=yf.download(ALL,start="2010-01-01",end="2026-10-23",auto_adjust=True,progress=False,threads=True)
px=df["Close"]
px.to_csv(f"{OUT}/adj_close.csv")
raw=yf.download(ALL,start="2010-01-01",end="2026-10-23",auto_adjust=False,progress=False,threads=True)["Close"]
raw.to_csv(f"{OUT}/raw_close.csv")
missing=[t for t in ALL if t not in px.columns or px[t].dropna().empty]
print("missing:",missing)
print("first dates:")
for t in ETFS: 
    s=px[t].dropna(); print(t, s.index[0].date(), s.index[-1].date(), len(s))
# meta: expense ratio, yield, dividends
meta={}
for t in ETFS:
    try:
        tk=yf.Ticker(t); info=tk.info
        div=tk.dividends
        ttm=float(div[div.index>=pd.Timestamp("2025-10-22",tz=div.index.tz)].sum()) if len(div) else 0.0
        last=float(raw[t].dropna().iloc[-1])
        meta[t]={"expense":info.get("netExpenseRatio") or info.get("annualReportExpenseRatio"),"yield_info":info.get("yield") or info.get("dividendYield"),"ttm_div":ttm,"last_px":last,"ttm_yield":ttm/last,"name":info.get("longName"),"aum":info.get("totalAssets")}
    except Exception as e:
        meta[t]={"error":str(e)}
    time.sleep(0.3)
json.dump(meta,open(f"{OUT}/meta.json","w"),indent=1)
print(json.dumps(meta,indent=1)[:4000])
