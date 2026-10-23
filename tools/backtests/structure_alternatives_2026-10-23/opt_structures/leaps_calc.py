"""A. LEAPS 股票替代計算。資料 = Firstrade get_option_chain / get_option_greeks（2026-10-23 盤前抓，bid/ask 為 10/22 收盤；delta/IV 為券商算）"""
import json, math
spot={"SMH":523.35,"QQQ":704.47,"NVDA":212.21,"AVGO":323.24,"MU":856.49,"CRWD":237.94,"PLTR":196.19}  # 10/22 收盤（Firstrade prev_close / yfinance）
days={"2028-01-21":455,"2027-06-17":237}
R=0.04
# (K, bid, ask, delta, iv) from Firstrade
D={
"SMH":{"2028-01-21":[(420,156.5,161.5,.803,.414),(400,170,175,.828,.425),(380,184.5,189.5,.861,.404),(350,207,211.5,.883,.443)],
       "2027-06-17":[(430,126.25,130.9,.8065,.421),(420,133.6,138.35,.823,.427),(400,148.55,153.5,.852,.440),(385,160.6,165.5,.886,.412)]},
"QQQ":{"2028-01-21":[(590,168.5,173.5,.818,.275),(575,180,185,.830,.291),(550,200,205,.857,.299),(530,216,221,.883,.294)],
       "2027-06-17":[(610,128.38,131.95,.805,.289),(600,136.8,139.91,.823,.291),(580,153.39,156.59,.850,.303),(550,178.87,182.33,.883,.322)]},
"NVDA":{"2028-01-21":[(165,68.3,69.6,.811,.428),(160,71.7,73,.827,.431),(150,78.5,80.25,.857,.436),(140,84.3,88.5,.883,.444)],
        "2027-06-17":[(170,55.2,56.2,.817,.433),(165,57.35,61,.8365,.439),(160,61.2,64.85,.855,.443),(150,69.35,71.9,.888,.454)]},
"AVGO":{"2028-01-21":[(250,106.8,109.9,.800,.459),(240,112.6,116.25,.822,.455),(230,119.5,122.85,.8415,.457),(210,133.5,136.95,.881,.449)],
        "2027-06-17":[(260,84.95,87.65,.802,.455),(250,92,94.7,.829,.457),(240,99.25,101.6,.854,.459),(230,106.95,109.75,.877,.462)]},
"MU":{"2028-01-21":[(670,306.3,319.4,.8006,.541),(640,323.75,336.85,.820,.545),(600,348.8,360.15,.843,.568),(560,374.85,387.2,.868,.567),(540,388.3,400.8,.879,.571)],
      "2027-06-17":[(680,251.7,259.3,.803,.558),(650,271.6,279.8,.825,.578),(620,291.05,301.4,.852,.571),(590,314.65,323.55,.874,.573)]},
"CRWD":{"2028-01-21":[(180,92.2,99,.8025,.608),(170,96,105,.825,.608),(160,102.3,111,.848,.601),(145,112,121,.878,.613)],
        "2027-06-17":[(182.5,75.25,81.15,.808,.593),(175,79.5,86.55,.829,.603),(165,87.1,93.05,.857,.608),(155,94.5,100.25,.880,.623)]},
"PLTR":{"2028-01-21":[(145,76.5,79.6,.814,.562),(140,79.5,82.5,.825,.588),(130,85.8,88.35,.852,.590),(120,92.5,95.75,.880,.579)],
        "2027-06-17":[(150,61.55,63.75,.807,.585),(145,64.9,67.7,.826,.586),(135,71.8,74.3,.861,.590),(130,75.9,78.65,.877,.594)]},
}
out={}
rows=[]
for t,ex in D.items():
    S=spot[t]; out[t]={}
    for exp,legs in ex.items():
        T=days[exp]/365; out[t][exp]=[]
        for K,bid,ask,dl,iv in legs:
            mid=(bid+ask)/2; intr=max(S-K,0); tv=mid-intr; notional=K+mid
            carry=tv/notional/T
            freed=(S-mid)*100
            fin=K*(1-math.exp(-R*T))  # 融資成分（持有 K 現金的利息）
            put_embedded=tv-fin        # put-call parity：TV = put(K) + K(1-e^-rT)（忽略股利）
            r=dict(K=K,bid=bid,ask=ask,mid=round(mid,2),delta=dl,iv=iv,intrinsic=round(intr,2),time_value=round(tv,2),tv_pct_spot=round(tv/S*100,2),
                   notional=round(notional,2),carry_pct_yr=round(carry*100,2),
                   cap_leaps_100=round(mid*100),cap_stock_100=round(S*100),freed_cash=round(freed),
                   net_carry_voo9=round(freed*0.09*T - tv*100), net_carry_tbill4=round(freed*0.04*T - tv*100),
                   net_carry_voo9_pct_yr=round((freed*0.09 - tv*100/T)/(S*100)*100,2), net_carry_tbill4_pct_yr=round((freed*0.04 - tv*100/T)/(S*100)*100,2),
                   max_loss_pct_notional=round(mid/notional*100,1), max_loss_pct_stock=round(mid/S*100,1),
                   spread_pct_mid=round((ask-bid)/mid*100,1), spread_usd_100=round((ask-bid)*100),
                   financing_component=round(fin,2), embedded_put_value=round(put_embedded,2), embedded_put_pct_yr=round(put_embedded/S/T*100,2), K_pct_spot=round(K/S*100,1))
            out[t][exp].append(r); rows.append((t,exp,r))
json.dump({"spot":spot,"days":days,"source":"Firstrade get_option_chain+get_option_greeks 2026-10-23 盤前（bid/ask=10/22 收盤）","data":out},open("leaps_firstrade.json","w"),indent=1)
print("tkr exp K(%S) delta mid TV TV%S carry%/yr | freed$ netVOO9 netTbill4 | maxloss%notional spread% | embPut%/yr")
for t,exp,r in rows:
    print(f"{t:5}{exp} {r['K']:>6}({r['K_pct_spot']:>5}%) d{r['delta']:.3f} mid{r['mid']:>7} TV{r['time_value']:>6} {r['tv_pct_spot']:>5}% {r['carry_pct_yr']:>5}%/y | {r['freed_cash']:>6} {r['net_carry_voo9']:>6} {r['net_carry_tbill4']:>6} | {r['max_loss_pct_notional']:>4}% {r['spread_pct_mid']:>4}% | put{r['embedded_put_pct_yr']:>5}%/y")
