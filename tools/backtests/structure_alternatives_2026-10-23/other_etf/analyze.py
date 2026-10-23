import pandas as pd, numpy as np, json, yfinance as yf
import os; OUT=os.path.dirname(os.path.abspath(__file__))
px=pd.read_csv(f"{OUT}/adj_close.csv",index_col=0,parse_dates=True)
raw=pd.read_csv(f"{OUT}/raw_close.csv",index_col=0,parse_dates=True)
meta=json.load(open(f"{OUT}/meta.json"))
ETFS="VOO SPY QQQ QQQM VUG IWF SCHG MGK IWY SPMO MTUM XMMO QMOM QUAL COWZ RSP SPLV USMV XLK VGT SMH SOXX IGV AIQ BOTZ FDN SKYY CIBR WCLD PAVE GRID URA NLR ITA XLE GLD JEPQ JEPI QYLD BUFR ARKK".split()
HOLD="AMAT AMD AVGO MU NVDA DIOD SNPS LITE CLS ANET CRM CRWD DDOG NET TWLO PLTR BE GLD XLE VOO".split()
END=pd.Timestamp("2026-10-22")
ret=px.pct_change()
rf=(px["^IRX"].ffill()/100/252).reindex(ret.index).ffill().fillna(0)   # daily T-bill
ret=ret.drop(columns=["^IRX"])

def stats(r, start, end=END):
    r=r.loc[start:end].dropna()
    if len(r)<200: return None
    rfp=rf.loc[r.index]
    n=len(r); yrs=n/252
    tr=(1+r).prod()-1; cagr=(1+tr)**(1/yrs)-1
    vol=r.std()*np.sqrt(252)
    ex=r-rfp; sharpe=ex.mean()/r.std()*np.sqrt(252)
    eq=(1+r).cumprod(); mdd=(eq/eq.cummax()-1).min()
    return dict(start=str(r.index[0].date()),yrs=round(yrs,1),cagr=cagr,vol=vol,mdd=mdd,sharpe=sharpe,total=tr)

def cal_ret(t, y):
    s=px[t].dropna()
    a=s[:f"{y-1}-12-31"]; b=s[:f"{y}-12-31"]
    if a.empty or b.empty or a.index[-1].year!=y-1: return np.nan
    return b.iloc[-1]/a.iloc[-1]-1

def roll_win(t, b, start):
    if t==b: return 0.0
    r=ret[[t,b]].loc[start:].dropna()
    if len(r)<300: return np.nan
    e=(1+r).cumprod(); w=e/e.shift(252)-1
    w=w.dropna()
    return (w[t]>w[b]).mean()

def alpha_beta(t, b, start):
    if t==b: return (0.0,1.0,0.0)
    r=ret[[t,b]].loc[start:].dropna()
    if len(r)<200: return (np.nan,np.nan,np.nan)
    y=r[t]-rf.loc[r.index]; x=r[b]-rf.loc[r.index]
    beta=np.cov(x,y)[0,1]/x.var(); alpha=(y.mean()-beta*x.mean())*252
    resid=y-beta*x; te=resid.std()*np.sqrt(252)
    return alpha,beta,te

rows=[]
for t in ETFS:
    m=meta.get(t,{})
    y=(m.get("ttm_yield") or 0)
    row=dict(ticker=t,name=m.get("name"),expense=m.get("expense"),yield_ttm=y*100,nra_drag=y*100*0.3,
             incept=str(px[t].dropna().index[0].date()),r2022=cal_ret(t,2022),ytd2026=px[t].dropna().iloc[-1]/px[t][:"2025-12-31"].dropna().iloc[-1]-1)
    for lab,st in [("15","2015-01-01"),("20","2020-01-01")]:
        s=stats(ret[t],st)
        if s and px[t].dropna().index[0]<=pd.Timestamp(st)+pd.Timedelta(days=10):
            row.update({f"cagr{lab}":s["cagr"],f"vol{lab}":s["vol"],f"mdd{lab}":s["mdd"],f"sharpe{lab}":s["sharpe"]})
            for b in ["SPY","QQQ","SMH"]:
                row[f"win{lab}_{b}"]=roll_win(t,b,st)
            row[f"corrSMH{lab}"]=1.0 if t=="SMH" else ret[[t,"SMH"]].loc[st:].dropna().corr().iloc[0,1]
            a,bq,te=alpha_beta(t,"QQQ",st); row[f"aQQQ{lab}"]=a; row[f"bQQQ{lab}"]=bq; row[f"teQQQ{lab}"]=te
            a,bs,te=alpha_beta(t,"SMH",st); row[f"aSMH{lab}"]=a; row[f"bSMH{lab}"]=bs
        else:
            for k in ["cagr","vol","mdd","sharpe","corrSMH","aQQQ","bQQQ","teQQQ","aSMH","bSMH"]: row[f"{k}{lab}"]=np.nan
            for b in ["SPY","QQQ","SMH"]: row[f"win{lab}_{b}"]=np.nan
    # since inception
    s=stats(ret[t],"2010-01-01")
    row.update(cagrInc=s["cagr"],sharpeInc=s["sharpe"],mddInc=s["mdd"])
    rows.append(row)
T=pd.DataFrame(rows).set_index("ticker")
T.to_csv(f"{OUT}/table_all.csv")

# ---- Q2 momentum sub-periods
mom={}
for t in ["SPMO","MTUM","XMMO","QMOM","QQQ","SPY"]:
    mom[t]={}
    for lab,(a,b) in {"incept→2019":("2010-01-01","2019-12-31"),"2020→2022":("2020-01-01","2022-12-31"),"2023→":("2023-01-01",END),"incept→":("2010-01-01",END)}.items():
        s=stats(ret[t],a,b)
        if s: mom[t][lab]=dict(start=s["start"],cagr=s["cagr"],sharpe=s["sharpe"],mdd=s["mdd"])
    # alpha vs SPY since inception and since 2020
    for lab,st in [("inc","2010-01-01"),("20","2020-01-01")]:
        a,b,te=alpha_beta(t,"SPY",st); mom[t][f"aSPY_{lab}"]=a; mom[t][f"bSPY_{lab}"]=b
json.dump(mom,open(f"{OUT}/momentum.json","w"),indent=1,default=float)

# ---- Q3 parking blend: proxy = 0.835*SMH + 0.165*rf ; portfolio = 90% proxy + 10% ETF, daily rebalance
def blend(etf,start):
    r=ret[["SMH",etf]].loc[start:].dropna() if etf!="SMH" else ret[["SMH"]].loc[start:].dropna()
    proxy=0.835*r["SMH"]+0.165*rf.loc[r.index]
    port=0.9*proxy+0.1*r[etf]
    return stats(proxy,start), stats(port,start), r[etf].corr(r["SMH"])
park={}
for st in ["2015-10-12","2020-01-01"]:
    park[st]={}
    for e in ["VOO","SPMO","QUAL","RSP","SCHG","MTUM","QQQ","SPY","GLD","USMV","COWZ","SPLV","XLE","JEPI"]:
        if px[e].dropna().index[0]>pd.Timestamp(st)+pd.Timedelta(days=10): continue
        p0,p1,c=blend(e,st)
        park[st][e]=dict(proxy_cagr=p0["cagr"],proxy_mdd=p0["mdd"],proxy_sharpe=p0["sharpe"],cagr=p1["cagr"],mdd=p1["mdd"],sharpe=p1["sharpe"],vol=p1["vol"],corrSMH=c)
    # also 100% proxy + 10% cash
    r=ret["SMH"].loc[st:].dropna(); proxy=0.835*r+0.165*rf.loc[r.index]; port=0.9*proxy+0.1*rf.loc[r.index]
    s=stats(port,st); park[st]["CASH(T-bill)"]=dict(cagr=s["cagr"],mdd=s["mdd"],sharpe=s["sharpe"],vol=s["vol"],corrSMH=0.0)
json.dump(park,open(f"{OUT}/parking.json","w"),indent=1,default=float)

# ---- Q4 R36 software benchmarks
sw={}
for t in ["IGV","WCLD","SKYY","AIQ","CIBR","FDN","XLK","VGT","QQQ","SMH","SOXX","VOO"]:
    sw[t]={}
    for lab,st in [("15","2015-01-01"),("20","2020-01-01"),("23","2023-01-01"),("inc","2010-01-01")]:
        s=stats(ret[t],st)
        if s and px[t].dropna().index[0]<=pd.Timestamp(st)+pd.Timedelta(days=10) or lab=="inc":
            a,b,te=alpha_beta(t,"QQQ",st if lab!="inc" else "2010-01-01")
            sw[t][lab]=dict(start=s["start"],cagr=s["cagr"],sharpe=s["sharpe"],mdd=s["mdd"],aQQQ=a,bQQQ=b,win_QQQ=roll_win(t,"QQQ",st))
    sw[t]["ytd2026"]=float(T.loc[t,"ytd2026"]) if t in T.index else np.nan
json.dump(sw,open(f"{OUT}/software_bench.json","w"),indent=1,default=float)

# ---- Q5 income / buffer: exact NRA after-tax (reinvest 70% of distributions)
def aftertax_index(t, start, keep=0.7):
    tk=yf.Ticker(t); div=tk.dividends
    div.index=div.index.tz_localize(None)
    p=raw[t].dropna().loc[start:]
    div=div.reindex(p.index).fillna(0)
    r=p.pct_change().fillna(0)+ (div*keep)/p.shift(1)
    r=r.iloc[1:]
    return r
inc={}
for t,b,st in [("JEPQ","QQQ","2022-05-04"),("QYLD","QQQ","2015-01-01"),("QYLD","QQQ","2020-01-01"),("JEPI","SPY","2020-05-21"),("BUFR","SPY","2020-08-11"),("JEPQ","QQQ","2023-01-01")]:
    key=f"{t}_{st}"
    s_t=stats(ret[t],st); s_b=stats(ret[b],st)
    at_t=stats(aftertax_index(t,st),st); at_b=stats(aftertax_index(b,st),st)
    pr_t=stats(raw[t].pct_change(),st)
    inc[key]=dict(bench=b,start=s_t["start"],tr_cagr=s_t["cagr"],tr_sharpe=s_t["sharpe"],tr_mdd=s_t["mdd"],price_cagr=pr_t["cagr"],
                  aftertax_cagr=at_t["cagr"],bench_tr_cagr=s_b["cagr"],bench_aftertax_cagr=at_b["cagr"],bench_mdd=s_b["mdd"],bench_sharpe=s_b["sharpe"],
                  gap_pretax=s_t["cagr"]-s_b["cagr"],gap_aftertax=at_t["cagr"]-at_b["cagr"],
                  upcap=None)
    # up/down capture monthly
    m=(1+ret[[t,b]].loc[st:].dropna()).resample("ME").prod()-1
    up=m[m[b]>0]; dn=m[m[b]<0]
    inc[key]["upcap"]=float(up[t].mean()/up[b].mean()); inc[key]["downcap"]=float(dn[t].mean()/dn[b].mean())
json.dump(inc,open(f"{OUT}/income.json","w"),indent=1,default=float)

# ---- Q6 20 holdings equal-weight buy&hold 2026 YTD
base=px.loc[:"2025-12-31"].iloc[-1]; last=px.loc[:END].iloc[-1]
ytd=(last/base-1)
hold_ytd=ytd[HOLD]
ew=hold_ytd.mean()
# also daily-rebalanced EW and MDD
r=ret[HOLD].loc["2026-01-01":END]
ewd=r.mean(axis=1); eq=(1+ewd).cumprod(); 
# buy&hold path
bh=(px[HOLD].loc["2026-01-01":END]/base[HOLD]).mean(axis=1)
q6=dict(ew_buyhold_ytd=float(ew),ew_dailyrebal_ytd=float(eq.iloc[-1]-1),ew_bh_mdd=float((bh/bh.cummax()-1).min()),
        per_stock=hold_ytd.round(4).to_dict(),etf_ytd=ytd[ETFS].round(4).to_dict(),
        ew_vol=float(ewd.std()*np.sqrt(252)))
json.dump(q6,open(f"{OUT}/ytd2026.json","w"),indent=1,default=float)

pd.set_option("display.width",250); pd.set_option("display.max_columns",60)
print(T[["incept","expense","yield_ttm","cagr15","vol15","mdd15","sharpe15","cagr20","vol20","mdd20","sharpe20","r2022","ytd2026","corrSMH15","win15_QQQ","win15_SMH","win20_QQQ","win20_SMH"]].sort_values("sharpe15",ascending=False).round(3).to_string())
print(T[["aQQQ15","bQQQ15","teQQQ15","aQQQ20","bQQQ20","aSMH15","bSMH15","aSMH20","bSMH20","cagrInc","sharpeInc","mddInc"]].round(3).to_string())
print(json.dumps(mom,indent=1,default=float))
print(json.dumps(park,indent=1,default=float))
print(json.dumps(sw,indent=1,default=float))
print(json.dumps(inc,indent=1,default=float))
print(json.dumps(q6,indent=1,default=float))
