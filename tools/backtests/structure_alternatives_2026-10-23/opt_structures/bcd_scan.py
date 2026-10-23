"""B/C/D 結構計算：yfinance 鏈（10/22 收盤 bid/ask/IV）+ BS delta。輸出 bcd.json"""
import yfinance as yf, json, math, datetime as dt, numpy as np
R=0.04
def N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def bs_delta(S,K,T,iv,cp):
    if iv<=0 or T<=0: return float('nan')
    d1=(math.log(S/K)+(R+0.5*iv*iv)*T)/(iv*math.sqrt(T))
    return N(d1) if cp=='C' else N(d1)-1
def d2(S,K,T,iv):
    return (math.log(S/K)+(R-0.5*iv*iv)*T)/(iv*math.sqrt(T))
today=dt.date(2026,10,23)
def chain(t,exp):
    tk=yf.Ticker(t); oc=tk.option_chain(exp)
    def rows(df,cp):
        out=[]
        for _,r in df.iterrows():
            out.append(dict(K=float(r.strike),bid=float(r.bid or 0),ask=float(r.ask or 0),last=float(r.lastPrice or 0),iv=float(r.impliedVolatility or 0),oi=int(r.openInterest or 0),cp=cp))
        return out
    return rows(oc.calls,'C'),rows(oc.puts,'P')
def nearest(rows,K): return min(rows,key=lambda r:abs(r['K']-K))
def mid(r): return (r['bid']+r['ask'])/2 if r['bid']>0 and r['ask']>0 else r['last']
def T_of(exp): return ((dt.date.fromisoformat(exp)-today).days)/365
spots={}
def spot(t):
    if t not in spots: spots[t]=float(yf.Ticker(t).fast_info.last_price)
    return spots[t]
res={"note":"yfinance 選擇權 bid/ask/IV = 2026-10-22 收盤值（抓取時間 2026-10-23 盤前）；delta 以 BS(r=4%) 由 yfinance IV 算","B":{},"C":{},"D":{}}
# ---- B. spreads
for t in ["SMH","QQQ","AVGO","CRWD"]:
    S=spot(t); res["B"][t]={"spot":S,"exp":{}}
    for exp in ["2026-12-04","2026-12-18"]:
        try: calls,puts=chain(t,exp)
        except Exception as e: res["B"][t]["exp"][exp]={"err":str(e)}; continue
        T=T_of(exp); days=(dt.date.fromisoformat(exp)-today).days
        o={"days":days}
        def leg(r,side):
            px=r['bid'] if side=='sell' else r['ask']
            return dict(K=r['K'],px=px,bid=r['bid'],ask=r['ask'],iv=r['iv'],delta=bs_delta(S,r['K'],T,r['iv'],r['cp']),oi=r['oi'],spread=r['ask']-r['bid'])
        # (1) bull put spread sell -5% buy -15%
        sp=nearest(puts,S*0.95); lp=nearest(puts,S*0.85)
        s=leg(sp,'sell'); l=leg(lp,'buy'); credit=s['px']-l['px']; width=s['K']-l['K']
        pwin=1-abs(s['delta']); maxloss=width-credit
        ev=pwin*credit-(1-pwin)*maxloss; fr=s['spread']+l['spread']
        o["bull_put"]=dict(short=s,long=l,credit=round(credit,2),credit_mid=round(mid(sp)-mid(lp),2),width=width,max_loss=round(maxloss,2),be=round(s['K']-credit,2),p_win_implied=round(pwin,3),ev_binary=round(ev,2),close_friction=round(fr,2),ev_after_friction=round(ev-fr,2),p_breakeven=round(maxloss/width,3),edge_needed_pp=round((maxloss/width-pwin)*100,1),credit_pct_width=round(credit/width*100,1))
        # (2) bear call spread sell +5% buy +15%
        sc=nearest(calls,S*1.05); lc=nearest(calls,S*1.15)
        s=leg(sc,'sell'); l=leg(lc,'buy'); credit=s['px']-l['px']; width=l['K']-s['K']
        pwin=1-s['delta']; maxloss=width-credit; ev=pwin*credit-(1-pwin)*maxloss; fr=s['spread']+l['spread']
        o["bear_call"]=dict(short=s,long=l,credit=round(credit,2),credit_mid=round(mid(sc)-mid(lc),2),width=width,max_loss=round(maxloss,2),be=round(s['K']+credit,2),p_win_implied=round(pwin,3),ev_binary=round(ev,2),close_friction=round(fr,2),ev_after_friction=round(ev-fr,2),p_breakeven=round(maxloss/width,3),edge_needed_pp=round((maxloss/width-pwin)*100,1),credit_pct_width=round(credit/width*100,1))
        # (3a) debit bull call buy ATM sell +10%
        bc=nearest(calls,S); sc2=nearest(calls,S*1.10)
        b=leg(bc,'buy'); s=leg(sc2,'sell'); debit=b['px']-s['px']; width=s['K']-b['K']; be=b['K']+debit
        ivbe=(b['iv']+s['iv'])/2; pwin=N(d2(S,be,T,ivbe)); maxgain=width-debit
        pmax=N(d2(S,s['K'],T,s['iv'])); ploss=1-N(d2(S,b['K'],T,b['iv']))
        ev=pwin*maxgain-(1-pwin)*debit; fr=b['spread']+s['spread']
        o["debit_bull_call"]=dict(long=b,short=s,debit=round(debit,2),debit_mid=round(mid(bc)-mid(sc2),2),width=width,max_gain=round(maxgain,2),be=round(be,2),be_pct=round((be/S-1)*100,1),p_win_implied=round(pwin,3),p_maxgain=round(pmax,3),p_fullloss=round(ploss,3),ev_binary=round(ev,2),close_friction=round(fr,2),ev_after_friction=round(ev-fr,2),p_breakeven=round(debit/width,3),edge_needed_pp=round((debit/width-pwin)*100,1))
        # (3b) debit bear put buy -5% sell -15%
        bp=nearest(puts,S*0.95); sp2=nearest(puts,S*0.85)
        b=leg(bp,'buy'); s=leg(sp2,'sell'); debit=b['px']-s['px']; width=b['K']-s['K']; be=b['K']-debit
        ivbe=(b['iv']+s['iv'])/2; pwin=1-N(d2(S,be,T,ivbe)); maxgain=width-debit
        ev=pwin*maxgain-(1-pwin)*debit; fr=b['spread']+s['spread']
        o["debit_bear_put"]=dict(long=b,short=s,debit=round(debit,2),debit_mid=round(mid(bp)-mid(sp2),2),width=width,max_gain=round(maxgain,2),be=round(be,2),be_pct=round((be/S-1)*100,1),p_win_implied=round(pwin,3),ev_binary=round(ev,2),close_friction=round(fr,2),ev_after_friction=round(ev-fr,2),p_breakeven=round(debit/width,3),edge_needed_pp=round((debit/width-pwin)*100,1))
        atm=nearest(calls,S); o["atm_iv"]=atm['iv']
        res["B"][t]["exp"][exp]=o
# ---- C. collars
col={"DIOD":["2026-12-18","2027-03-19"],"XLE":["2027-01-15","2027-02-19"],"CRWD":["2027-01-15","2027-02-19"]}
for t,exps in col.items():
    S=spot(t); res["C"][t]={"spot":S,"exp":{}}
    for exp in exps:
        try: calls,puts=chain(t,exp)
        except Exception as e: res["C"][t]["exp"][exp]={"err":str(e)}; continue
        T=T_of(exp); days=(dt.date.fromisoformat(exp)-today).days
        p=nearest(puts,S*0.90); pask=p['ask']; pmid=mid(p)
        cands=[c for c in calls if c['K']>S and c['bid']>=pask]
        c=min(cands,key=lambda c:c['K']) if cands else None
        cands_m=[c for c in calls if c['K']>S and mid(c)>=pmid]
        cm=min(cands_m,key=lambda c:c['K']) if cands_m else None
        res["C"][t]["exp"][exp]=dict(days=days,put=dict(K=p['K'],bid=p['bid'],ask=p['ask'],iv=p['iv'],delta=bs_delta(S,p['K'],T,p['iv'],'P'),pct_otm=round((p['K']/S-1)*100,1),spread_pct_mid=round((p['ask']-p['bid'])/max(pmid,0.01)*100,1)),
            call_natural=(dict(K=c['K'],bid=c['bid'],ask=c['ask'],iv=c['iv'],delta=bs_delta(S,c['K'],T,c['iv'],'C'),cap_pct=round((c['K']/S-1)*100,1)) if c else None),
            call_mid=(dict(K=cm['K'],bid=cm['bid'],ask=cm['ask'],cap_pct=round((cm['K']/S-1)*100,1)) if cm else None),
            n_calls=len(calls))
# ---- D. CSP at SMA20
res["D"]["exp_choice"]="2026-12-04 (42d)"
for t in ["DDOG","CRM","TWLO","ANET","AMD"]:
    S=spot(t); h=yf.Ticker(t).history(period="3mo")["Close"]; sma20=float(h.tail(20).mean()); sma50=float(h.tail(50).mean())
    try:
        cal=yf.Ticker(t).calendar; ed=cal.get("Earnings Date") if isinstance(cal,dict) else None
        ed=[str(x) for x in ed] if ed else None
    except Exception as e: ed=f"err {e}"
    o={"spot":S,"sma20":round(sma20,2),"sma20_vs_spot_pct":round((sma20/S-1)*100,1),"sma50":round(sma50,2),"earnings":ed,"exp":{}}
    for exp in ["2026-11-27","2026-12-04"]:
        try: calls,puts=chain(t,exp)
        except Exception as e: o["exp"][exp]={"err":str(e)}; continue
        T=T_of(exp); days=(dt.date.fromisoformat(exp)-today).days
        p=nearest(puts,sma20); y=p['bid']/p['K']
        o["exp"][exp]=dict(days=days,K=p['K'],bid=p['bid'],ask=p['ask'],mid=mid(p),iv=p['iv'],delta=round(bs_delta(S,p['K'],T,p['iv'],'P'),3),yield_pct=round(y*100,2),ann_pct=round(y*365/days*100,1),cash_locked=p['K']*100,oi=p['oi'],spread_pct_mid=round((p['ask']-p['bid'])/max(mid(p),0.01)*100,1),be=round(p['K']-p['bid'],2),be_vs_spot_pct=round(((p['K']-p['bid'])/S-1)*100,1))
    res["D"][t]=o
res["spots"]=spots
json.dump(res,open("bcd.json","w"),indent=1,default=str)
print(json.dumps(res,indent=1,default=str)[:200]); print("OK")
