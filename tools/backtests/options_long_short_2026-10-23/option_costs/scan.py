import yfinance as yf, pandas as pd, numpy as np, json, math, datetime as dt, sys

class norm:
    @staticmethod
    def cdf(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def brentq(f,a,b,it=200):
    fa,fb=f(a),f(b)
    if fa*fb>0: raise ValueError('no bracket')
    for _ in range(it):
        m=(a+b)/2; fm=f(m)
        if fa*fm<=0: b,fb=m,fm
        else: a,fa=m,fm
        if b-a<1e-6: break
    return (a+b)/2
import os; OUT = os.path.dirname(os.path.abspath(__file__)) + '/'
TICKERS=["SMH","QQQ","SPY","AVGO","BE","DIOD","NET","CLS","AMAT","CRWD","MU"]
today=dt.date(2026,10,23); r=0.04
def bs_put(S,K,T,s): 
    d1=(math.log(S/K)+(r+s*s/2)*T)/(s*math.sqrt(T)); d2=d1-s*math.sqrt(T)
    return K*math.exp(-r*T)*norm.cdf(-d2)-S*norm.cdf(-d1)
def iv_put(S,K,T,p):
    try: return brentq(lambda s: bs_put(S,K,T,s)-p,0.01,5.0)
    except Exception: return float('nan')
def pick_exp(exps,lo,hi):
    c=[(e,(dt.date.fromisoformat(e)-today).days) for e in exps]
    c=[x for x in c if lo<=x[1]<=hi]
    if not c:
        c=[(e,d) for e,d in [(e,(dt.date.fromisoformat(e)-today).days) for e in exps]]
        c=sorted(c,key=lambda x:abs(x[1]-(lo+hi)/2))[:1]
    return sorted(c,key=lambda x:x[1])[-1] if lo>100 else sorted(c,key=lambda x:x[1])[0]
def nearest(df,K):
    i=(df['strike']-K).abs().idxmin(); return df.loc[i]
def row_info(row,S,T):
    bid,ask=float(row['bid']),float(row['ask']); mid=(bid+ask)/2 if bid>0 and ask>0 else float(row['lastPrice'])
    return dict(strike=float(row['strike']),bid=bid,ask=ask,mid=round(mid,2),last=float(row['lastPrice']),
                yf_iv=round(float(row['impliedVolatility']),4),oi=int(row['openInterest']) if not pd.isna(row['openInterest']) else None,
                vol=int(row['volume']) if not pd.isna(row['volume']) else None,
                bs_iv_mid=round(iv_put(S,float(row['strike']),T,mid),4) if mid>0 else None,
                spread_pct_mid=round((ask-bid)/mid*100,1) if mid>0 and bid>0 else None)
res={}; fails=[]
for t in TICKERS:
    try:
        tk=yf.Ticker(t); h=tk.history(period="6mo")
        S=float(h['Close'].iloc[-1]); lastdate=str(h.index[-1].date())
        fi=tk.fast_info; live=fi.get('lastPrice') or fi.get('last_price')
        lr=np.log(h['Close']).diff().dropna()
        rv20=float(lr[-20:].std()*math.sqrt(252)); rv60=float(lr[-60:].std()*math.sqrt(252))
        exps=tk.options
        e1=pick_exp(exps,55,70); e2=pick_exp(exps,115,130)
        d=dict(spot_close=round(S,2),close_date=lastdate,live=live,rv20=round(rv20,4),rv60=round(rv60,4),expiries={})
        for e,days in (e1,e2):
            ch=tk.option_chain(e); puts=ch.puts; calls=ch.calls; T=days/365
            atm=nearest(puts,S); p10=nearest(puts,S*0.90); p05=nearest(puts,S*0.95); p15=nearest(puts,S*0.85)
            atm_i=row_info(atm,S,T); p10_i=row_info(p10,S,T); p05_i=row_info(p05,S,T); p15_i=row_info(p15,S,T)
            atm_iv = atm_i['bs_iv_mid'] if atm_i['bs_iv_mid'] and not math.isnan(atm_i['bs_iv_mid']) else atm_i['yf_iv']
            def cost(x): 
                c=x['ask']/S*100; return dict(buy_cost_pct=round(c,2),annualized_pct=round(c*365/days,1))
            debit=p05_i['ask']-p15_i['bid']; width=p05_i['strike']-p15_i['strike']
            d['expiries'][e]=dict(days=days,atm=atm_i,atm_iv_used=atm_iv,vrp_vs_rv20=round(atm_iv-rv20,4),
                put10=dict(**p10_i,**cost(p10_i)),put05=dict(**p05_i,**cost(p05_i)),put15=p15_i,
                bear_put_spread_5_15=dict(long=p05_i['strike'],short=p15_i['strike'],debit_cons=round(debit,2),debit_pct_spot=round(debit/S*100,2),
                    width=width,max_gain=round(width-debit,2),gain_loss_ratio=round((width-debit)/debit,2) if debit>0 else None,
                    debit_mid=round(p05_i['mid']-p15_i['mid'],2)))
            if t in("CRWD","MU") and days<45: pass
        # CC: ~30d, +7% call
        e30=sorted([(e,(dt.date.fromisoformat(e)-today).days) for e in exps],key=lambda x:abs(x[1]-30))[0]
        ch=tk.option_chain(e30[0]); c7=nearest(ch.calls,S*1.07)
        d['cc_30d_7pct']=dict(exp=e30[0],days=e30[1],strike=float(c7['strike']),bid=float(c7['bid']),ask=float(c7['ask']),
            bid_pct_spot=round(float(c7['bid'])/S*100,2),yf_iv=round(float(c7['impliedVolatility']),4))
        res[t]=d; print(t,"ok",S,e1,e2,file=sys.stderr)
    except Exception as ex:
        fails.append((t,str(ex))); print(t,"FAIL",ex,file=sys.stderr)
res['_fails']=fails; res['_meta']=dict(run=str(dt.datetime.now()),source="yfinance via scan.py; bs_iv_mid = own Black-Scholes IV from bid/ask mid, r=4%")
json.dump(res,open(OUT+"yf_scan.json","w"),indent=1,default=str)
print(json.dumps({t:{k:v for k,v in d.items() if k!='expiries'} for t,d in res.items() if not t.startswith('_')},indent=0,default=str)[:3000])
