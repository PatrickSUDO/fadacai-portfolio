"""B/C/D 以 Firstrade get_option_chain / get_option_greeks（2026-10-23 盤前抓，bid/ask 為 10/22 收盤）手工轉錄計算。
delta：有券商 greeks 用券商值；QQQ / 第 D 段無 greeks → 由 mid 以 BS(r=4%) 反推 IV 再算 delta。"""
import json, math
R=0.04
def N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def bs(S,K,T,iv,cp):
    d1=(math.log(S/K)+(R+0.5*iv*iv)*T)/(iv*math.sqrt(T)); d2=d1-iv*math.sqrt(T)
    if cp=='C': return S*N(d1)-K*math.exp(-R*T)*N(d2), N(d1), N(d2)
    return K*math.exp(-R*T)*N(-d2)-S*N(-d1), N(d1)-1, N(d2)
def iv_from_mid(S,K,T,px,cp):
    lo,hi=0.01,3.0
    for _ in range(80):
        m=(lo+hi)/2; p,_,_=bs(S,K,T,m,cp)
        if p>px: hi=m
        else: lo=m
    return (lo+hi)/2
def pgt(S,K,T,iv):  # risk-neutral P(S_T > K)
    return N((math.log(S/K)+(R-0.5*iv*iv)*T)/(iv*math.sqrt(T)))
spot={"SMH":523.35,"QQQ":704.47,"AVGO":323.24,"CRWD":237.94,"DIOD":81.64,"XLE":67.57,"DDOG":257.75,"CRM":250.29,"TWLO":253.63,"ANET":171.07,"AMD":507.93}
# legs: K,bid,ask,delta(None->derive),iv(None->derive),oi
B={
"SMH":{"2026-11-20":dict(days=28,p5=(495,12.65,14.15,-.282,.478,1336),p15=(445,3.8,4.35,-.104,.523,294),c5=(550,13.9,15.5,.390,.390,957),c15=(600,3.4,3.95,.133,.377,6070),atm=(525,25.1,26.55,.555,.466,180),c10=(575,7.15,8.15,.240,.380,1931)),
       "2026-12-18":dict(days=56,p5=(495,18.15,20.2,-.311,.453,1075),p15=(445,7.4,8.45,-.148,.477,170),c5=(550,21.7,23.4,.434,.353,3242),c15=(600,8.0,9.0,.214,.352,5328),atm=(525,32.75,36.5,.565,.445,262),c10=(575,13.35,14.75,.313,.351,1107))},
"QQQ":{"2026-11-20":dict(days=28,p5=(670,8.94,9.09,None,None,38291),p15=(600,2.14,2.22,None,None,48632),c5=(740,6.05,6.19,None,None,12858),c15=(810,0.17,0.23,None,None,8915),atm=(704,21.70,21.98,None,None,180),c10=(775,1.13,1.20,None,None,51146)),
       "2026-12-18":dict(days=56,p5=(670,13.67,13.89,None,None,43669),p15=(600,4.47,4.62,None,None,45093),c5=(740,12.11,12.34,None,None,17189),c15=(810,1.15,1.24,None,None,17400),atm=(704,29.33,29.62,None,None,381),c10=(775,3.92,4.09,None,None,23102))},
"AVGO":{"2026-11-20":dict(days=28,p5=(305,7.5,7.85,-.287,.461,545),p15=(270,1.45,1.9,-.078,.489,2420),c5=(340,9.1,9.45,.374,.415,8002),c15=(370,2.79,2.95,.150,.418,7331),atm=(322.5,16.4,16.85,.552,.443,142),c10=(355,5.1,5.35,.246,.416,203)),
        "2026-12-18":dict(days=56,p5=(310,16.1,16.4,-.355,.475,7938),p15=(275,5.85,6.3,-.165,.497,4190),c5=(340,17.15,17.5,.444,.447,3884),c15=(370,8.6,8.85,.272,.453,8094),atm=(320,26.05,26.45,.580,.470,1746),c10=(350,13.75,14.05,.381,.449,7432))},
"CRWD":{"2026-11-20":dict(days=28,p5=(225,9.4,10.0,-.326,.604,3998),p15=(202.5,3.6,4.05,-.151,.631,261),c5=(250,10.7,11.05,.423,.559,2358),c15=(272.5,4.45,4.95,.234,.567,445),atm=(237.5,15.95,16.6,.553,.601,673),c10=(262.5,6.6,7.15,.316,.579,1164)),
        "2026-12-18":dict(days=56,p5=(225,16.1,17.65,-.348,.637,443),p15=(202.5,8.3,10.1,-.215,.662,154),c5=(250,18.45,19.3,.484,.611,1505),c15=(272.5,9.95,12.0,.342,.602,109),atm=(237.5,23.9,25.7,.569,.632,268),c10=(262.5,14.0,14.95,.402,.604,465))},
}
notes={"SMH":"12-04 週選 OI 全 0 且無 525 以下履約 → 改用 11-20 月選（28 天）","QQQ":"12-04 週選只有 710–745 履約 → 改用 11-20 月選；無券商 greeks，delta 由 mid 反推","AVGO":"12-04 週選 OI 全 0 → 改用 11-20；12-18 窗含財報（約 12/11）","CRWD":"12-04 週選 OI 全 0 → 改用 11-20；12-18 窗含財報（約 12/2）"}
out={"source":"Firstrade get_option_chain/get_option_greeks 2026-10-23 盤前（bid/ask=10/22 收盤）","notes":notes,"B":{},"C":{},"D":{}}
def leg(S,T,l,cp):
    K,bid,ask,dl,iv,oi=l; mid=(bid+ask)/2
    if iv is None: iv=iv_from_mid(S,K,T,mid,cp)
    if dl is None: _,dl,_=bs(S,K,T,iv,cp)
    return dict(K=K,bid=bid,ask=ask,mid=round(mid,2),delta=round(dl,3),iv=round(iv,3),oi=oi,spread=round(ask-bid,2),spread_pct=round((ask-bid)/mid*100,1))
rowsB=[]
for t,ex in B.items():
    S=spot[t]; out["B"][t]={}
    for exp,d in ex.items():
        T=d["days"]/365
        p5=leg(S,T,d["p5"],'P'); p15=leg(S,T,d["p15"],'P'); c5=leg(S,T,d["c5"],'C'); c15=leg(S,T,d["c15"],'C'); atm=leg(S,T,d["atm"],'C'); c10=leg(S,T,d["c10"],'C')
        res={"days":d["days"],"legs":dict(p5=p5,p15=p15,c5=c5,c15=c15,atm=atm,c10=c10)}
        def credit_spread(s,l,width,pwin,name):
            credit=s['bid']-l['ask']; credit_mid=s['mid']-l['mid']; maxloss=width-credit
            ev=pwin*credit-(1-pwin)*maxloss; fr_close=s['spread']+l['spread']
            return dict(name=name,short_K=s['K'],long_K=l['K'],credit_natural=round(credit,2),credit_mid=round(credit_mid,2),open_friction=round(credit_mid-credit,2),width=width,max_loss=round(maxloss,2),
                        p_win_implied=round(pwin,3),p_breakeven=round(maxloss/width,3),edge_needed_pp=round((maxloss/width-pwin)*100,1),ev_binary=round(ev,2),ev_pct_maxloss=round(ev/maxloss*100,1),close_friction=round(fr_close,2),ev_after_close_friction=round(ev-fr_close,2),credit_pct_width=round(credit/width*100,1))
        # (1) bull put: sell p5 buy p15
        res["bull_put"]=credit_spread(p5,p15,p5['K']-p15['K'],1-abs(p5['delta']),"bull put −5/−15")
        res["bull_put"]["be"]=round(p5['K']-res["bull_put"]["credit_natural"],2); res["bull_put"]["be_pct"]=round((res["bull_put"]["be"]/S-1)*100,1)
        # (2) bear call: sell c5 buy c15
        res["bear_call"]=credit_spread(c5,c15,c15['K']-c5['K'],1-c5['delta'],"bear call +5/+15")
        res["bear_call"]["be"]=round(c5['K']+res["bear_call"]["credit_natural"],2); res["bear_call"]["be_pct"]=round((res["bear_call"]["be"]/S-1)*100,1)
        # (3a) debit bull call: buy atm (ask) sell c10 (bid)
        debit=atm['ask']-c10['bid']; debit_mid=atm['mid']-c10['mid']; width=c10['K']-atm['K']; be=atm['K']+debit
        ivbe=(atm['iv']+c10['iv'])/2; pwin=pgt(S,be,T,ivbe); pmax=pgt(S,c10['K'],T,c10['iv']); pzero=1-pgt(S,atm['K'],T,atm['iv'])
        maxgain=width-debit; ev=pwin*maxgain-(1-pwin)*debit; fr=atm['spread']+c10['spread']
        res["debit_bull_call"]=dict(long_K=atm['K'],short_K=c10['K'],debit_natural=round(debit,2),debit_mid=round(debit_mid,2),open_friction=round(debit-debit_mid,2),width=width,max_gain=round(maxgain,2),be=round(be,2),be_pct=round((be/S-1)*100,1),p_win_implied=round(pwin,3),p_maxgain=round(pmax,3),p_total_loss=round(pzero,3),p_breakeven=round(debit/width,3),edge_needed_pp=round((debit/width-pwin)*100,1),ev_binary=round(ev,2),ev_pct_debit=round(ev/debit*100,1),close_friction=round(fr,2),ev_after_close_friction=round(ev-fr,2),gain_to_loss=round(maxgain/debit,2))
        # (3b) debit bear put: buy p5 (ask) sell p15 (bid)
        debit=p5['ask']-p15['bid']; debit_mid=p5['mid']-p15['mid']; width=p5['K']-p15['K']; be=p5['K']-debit
        ivbe=(p5['iv']+p15['iv'])/2; pwin=1-pgt(S,be,T,ivbe); pmax=1-pgt(S,p15['K'],T,p15['iv']); pzero=pgt(S,p5['K'],T,p5['iv'])
        maxgain=width-debit; ev=pwin*maxgain-(1-pwin)*debit; fr=p5['spread']+p15['spread']
        res["debit_bear_put"]=dict(long_K=p5['K'],short_K=p15['K'],debit_natural=round(debit,2),debit_mid=round(debit_mid,2),open_friction=round(debit-debit_mid,2),width=width,max_gain=round(maxgain,2),be=round(be,2),be_pct=round((be/S-1)*100,1),p_win_implied=round(pwin,3),p_maxgain=round(pmax,3),p_total_loss=round(pzero,3),p_breakeven=round(debit/width,3),edge_needed_pp=round((debit/width-pwin)*100,1),ev_binary=round(ev,2),ev_pct_debit=round(ev/debit*100,1),close_friction=round(fr,2),ev_after_close_friction=round(ev-fr,2),gain_to_loss=round(maxgain/debit,2))
        out["B"][t][exp]=res
        for k in ["bull_put","bear_call","debit_bull_call","debit_bear_put"]:
            r=res[k]; rowsB.append((t,exp,d["days"],k,r))
print("=== B ===")
for t,exp,days,k,r in rowsB:
    if k in("bull_put","bear_call"):
        print(f"{t:5}{exp} {days:2}d {k:15} {r['short_K']}/{r['long_K']} credit nat {r['credit_natural']:>6} (mid {r['credit_mid']}) width {r['width']} maxloss {r['max_loss']} BE {r['be']}({r['be_pct']}%) pWin {r['p_win_implied']} pBE {r['p_breakeven']} edge {r['edge_needed_pp']}pp EV {r['ev_binary']} ({r['ev_pct_maxloss']}% of maxloss) closeFr {r['close_friction']} EVafter {r['ev_after_close_friction']}")
    else:
        print(f"{t:5}{exp} {days:2}d {k:15} {r['long_K']}/{r['short_K']} debit nat {r['debit_natural']:>6} (mid {r['debit_mid']}) width {r['width']} maxgain {r['max_gain']} BE {r['be']}({r['be_pct']}%) pWin {r['p_win_implied']} pMax {r['p_maxgain']} pZero {r['p_total_loss']} pBE {r['p_breakeven']} edge {r['edge_needed_pp']}pp EV {r['ev_binary']} ({r['ev_pct_debit']}% of debit) closeFr {r['close_friction']} EVafter {r['ev_after_close_friction']}")
# ---- C collars (K,bid,ask)
C={
"DIOD":{"shares":169,"2026-12-18":dict(days=56,put=(75,3.7,6.7,9),calls=[(80,7.6,11.3,2),(85,6.1,9.1,47),(90,4.9,6.5,26),(95,3.7,5.5,274),(100,2.35,4.1,269)]),
        "2027-03-19":dict(days=147,put=(75,8.1,11.9,9),calls=[(80,13.2,17.4,92),(85,11.1,15.0,4),(90,9.2,13.3,18),(95,7.5,11.5,28),(100,6.0,10.2,5)])},
"XLE":{"shares":114,"2027-01-15":dict(days=84,put=(60,0.63,1.09,31103),calls=[(70,2.5,2.77,22910),(75,1.09,1.35,9316),(80,0.45,0.6,10410)]),
       "2027-03-19":dict(days=147,put=(61,1.52,1.88,746),calls=[(70,3.6,4.05,1604),(72,2.76,3.45,1111),(75,2.05,2.45,7965),(80,1.11,1.42,3764)])},
"CRWD":{"shares":"需補到 100","2027-01-15":dict(days=84,put=(215,13.2,17.6,898),calls=[(250,22.35,24.05,4187),(255,20.15,23.55,471),(257.5,20.1,21.0,542),(260,18.8,20.15,1518),(262.5,17.8,19.95,1000),(265,15.65,18.6,1620),(267.5,15.5,18.9,694),(270,14.85,17.15,810),(272.5,13.75,17.5,465),(275,14.3,15.4,752),(280,13.2,14.15,522),(290,10.6,11.8,1033),(300,9.1,9.85,2640)]),
        "2027-02-19":dict(days=119,put=(210,14.5,17.9,310),calls=[(250,25.45,30.0,668),(260,23.0,25.4,295),(270,18.65,24.55,799),(280,16.9,19.4,736),(290,13.8,18.45,1544),(300,12.75,14.25,577)])},
}
print("=== C ===")
for t,v in C.items():
    S=spot[t]; out["C"][t]={"shares":v["shares"]}
    for exp,d in v.items():
        if exp=="shares": continue
        K,pb,pa,poi=d["put"]; pmid=(pb+pa)/2
        nat=[c for c in d["calls"] if c[1]>=pa and c[0]>S]; mid_=[c for c in d["calls"] if (c[1]+c[2])/2>=pmid and c[0]>S]
        cn=min(nat,key=lambda c:c[0]) if nat else None; cm=max(mid_,key=lambda c:c[0]) if mid_ else None
        r=dict(days=d["days"],put_K=K,put_bid=pb,put_ask=pa,put_oi=poi,put_pct_spot=round(pa/S*100,2),put_spread_pct_mid=round((pa-pb)/pmid*100,1),floor_pct=round((K/S-1)*100,1),
               call_natural=(dict(K=cn[0],bid=cn[1],ask=cn[2],oi=cn[3],cap_pct=round((cn[0]/S-1)*100,1),net_credit=round(cn[1]-pa,2)) if cn else None),
               call_at_mid_maxcap=(dict(K=cm[0],mid=round((cm[1]+cm[2])/2,2),cap_pct=round((cm[0]/S-1)*100,1)) if cm else None))
        out["C"][t][exp]=r; print(t,exp,r)
# ---- D CSP 2026-11-27 (35d)
D={
"DDOG":dict(sma20=271.35,earn="2026-11-04(窗內)",sma_put=(270,27.4,32.8,0),otm_put=(250,16.7,22.4,6)),
"CRM":dict(sma20=234.8,earn="2026-12-03(窗外)",sma_put=(235,5.95,6.8,59),otm_put=(240,7.3,9.15,53)),
"TWLO":dict(sma20=277.54,earn="2026-10-30(窗內)",sma_put=(275,35.6,39.5,3),otm_put=(245,18.3,21.5,7)),
"ANET":dict(sma20=199.42,earn="2026-11-04(窗內)",sma_put=(200,30.4,32.85,11),otm_put=(165,8.3,10.0,440)),
"AMD":dict(sma20=592.91,earn="2026-11-04(窗內)",sma_put=(595,92.85,99.35,32),otm_put=(500,32.25,34.65,1041)),
}
print("=== D (2026-11-27, 35d) ===")
days=35; T=days/365
for t,d in D.items():
    S=spot[t]; o={"spot":S,"sma20":d["sma20"],"sma20_vs_spot_pct":round((d["sma20"]/S-1)*100,1),"earnings":d["earn"]}
    for tag in ["sma_put","otm_put"]:
        K,bid,ask,oi=d[tag]; mid=(bid+ask)/2; iv=iv_from_mid(S,K,T,mid,'P'); _,dl,_=bs(S,K,T,iv,'P')
        intr=max(K-S,0); extr=bid-intr
        o[tag]=dict(K=K,bid=bid,ask=ask,oi=oi,iv=round(iv,3),delta=round(dl,3),assign_prob=round(abs(dl),2),intrinsic=round(intr,2),extrinsic_bid=round(extr,2),yield_bid_pct=round(bid/K*100,2),extrinsic_yield_pct=round(extr/K*100,2),ann_extrinsic_pct=round(extr/K*365/days*100,1),cash_locked=K*100,be=round(K-bid,2),be_vs_spot_pct=round(((K-bid)/S-1)*100,1),spread_pct_mid=round((ask-bid)/mid*100,1),itm=K>S)
    out["D"][t]=o; print(t,json.dumps(o,ensure_ascii=False))
json.dump(out,open("bcd_firstrade.json","w"),indent=1,ensure_ascii=False)
