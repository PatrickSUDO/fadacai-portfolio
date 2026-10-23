import yfinance as yf, pandas as pd, numpy as np, warnings, json
warnings.filterwarnings("ignore")
out={}
def dl(t,start="2000-01-01"):
    try:
        d=yf.download(t,start=start,auto_adjust=True,progress=False)["Close"]
        if isinstance(d,pd.DataFrame): d=d.iloc[:,0]
        return d.dropna()
    except Exception as e:
        print("FAIL",t,e); return None
def cagr(s): 
    yrs=(s.index[-1]-s.index[0]).days/365.25; return (s.iloc[-1]/s.iloc[0])**(1/yrs)-1
def mdd(s): return (s/s.cummax()-1).min()
# 1. BXM/BXMD/PUT 2026 YTD + since 2016
for t in ["^BXM","^BXMD","^PUT","^SPXTR","^GSPC","PUTW","SPY"]:
    s=dl(t,"2015-12-31")
    if s is None or len(s)<10: continue
    y=s[s.index>="2025-12-31"]
    out[t]={"last_date":str(s.index[-1].date()),"ytd_2026":float(y.iloc[-1]/y.iloc[0]-1) if len(y)>1 else None,
            "cagr_since_2016":float(cagr(s)),"mdd_since_2016":float(mdd(s)),
            "ret_2025":float(s[(s.index>="2024-12-31")&(s.index<="2025-12-31")].pipe(lambda x:x.iloc[-1]/x.iloc[0]-1))}
# 2. HFEA 55/45 quarterly rebalance 2022 + since 2010
u=dl("UPRO","2009-06-25");tm=dl("TMF","2009-06-25")
df=pd.concat([u,tm],axis=1).dropna();df.columns=["UPRO","TMF"]
def hfea(df,w=(0.55,0.45)):
    r=df.pct_change().fillna(0);v=1.0;wu,wt=w;vals=[]
    q=None
    for d,row in r.iterrows():
        wu*=1+row.UPRO; wt*=1+row.TMF; v=wu+wt
        if q is not None and (d.month-1)//3!=q: wu,wt=v*w[0],v*w[1]
        q=(d.month-1)//3; vals.append(v)
    return pd.Series(vals,index=df.index)
h=hfea(df)
h22=h[(h.index>="2021-12-31")&(h.index<="2022-12-31")]
out["HFEA_55_45_q"]={"cagr_since_2009":float(cagr(h)),"mdd":float(mdd(h)),"ret_2022":float(h22.iloc[-1]/h22.iloc[0]-1),
 "dd_from_2021peak_to_trough":float((h[h.index>="2021-01-01"]/h[h.index>="2021-01-01"].cummax()-1).min()),
 "spy_cagr_same":float(cagr(dl("SPY","2009-06-25").reindex(h.index).dropna()))}
# 3. QUAL vs SPY since 2013-07-18 ; MTUM vs SPY since 2013-04-16
for a,b,st in [("QUAL","SPY","2013-07-18"),("MTUM","SPY","2013-04-16"),("SPMO","SPY","2015-10-09"),("RSP","SPY","2003-04-24")]:
    sa=dl(a,st);sb=dl(b,st);ix=sa.index.intersection(sb.index)
    out[f"{a}_vs_{b}"]={"start":str(ix[0].date()),"end":str(ix[-1].date()),a:float(cagr(sa[ix])),b:float(cagr(sb[ix])),f"mdd_{a}":float(mdd(sa[ix])),f"mdd_{b}":float(mdd(sb[ix]))}
# 4. leveraged ETF decay: Avellaneda-Zhang: L_T/L_0 = (S_T/S_0)^b * exp(((b-b^2)/2) * sigma^2 T + ...)  ; compute realized sigma for SMH, QQQ, SPY and breakeven drift
for t in ["SMH","QQQ","SPY"]:
    s=dl(t,"2010-03-11");r=np.log(s).diff().dropna()
    sig=float(r.std()*np.sqrt(252));mu=float(r.mean()*252)  # log drift
    # growth rate of b-x LETF (ignoring financing/fees): g(b)= b*mu_arith - b^2 sig^2/2 where mu_arith = mu + sig^2/2
    mua=mu+sig**2/2
    g={b:b*mua-(b**2)*sig**2/2 for b in [1,2,3]}
    bstar=mua/sig**2
    out[f"LETF_{t}"]={"realized_sigma":sig,"arith_mu":mua,"growth_1x":g[1],"growth_2x":g[2],"growth_3x":g[3],"optimal_b_kelly":bstar,"vol_drag_2x":sig**2,"vol_drag_3x":3*sig**2}
# 5. TQQQ/SOXL/UPRO since inception check + SOXL 2022 calendar
for t in ["TQQQ","SOXL","UPRO","SSO","QLD","USD"]:
    s=dl(t,"2006-01-01");out[f"{t}_inc"]={"start":str(s.index[0].date()),"cagr":float(cagr(s)),"mdd":float(mdd(s))}
# 6. covered call ETFs vs underlying
for a,b in [("QYLD","QQQ"),("JEPQ","QQQ"),("JEPI","SPY"),("XYLD","SPY")]:
    sa=dl(a,"2013-01-01");sb=dl(b,"2013-01-01");ix=sa.index.intersection(sb.index)
    out[f"{a}_vs_{b}"]={"start":str(ix[0].date()),a:float(cagr(sa[ix])),b:float(cagr(sb[ix])),f"mdd_{a}":float(mdd(sa[ix])),f"mdd_{b}":float(mdd(sb[ix]))}
json.dump(out,open(__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)),'calc.json'),'w'),indent=1)
print(json.dumps(out,indent=1))
