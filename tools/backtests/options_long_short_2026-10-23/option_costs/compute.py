import json, math
import os; B = os.path.dirname(os.path.abspath(__file__)) + '/'
d=json.load(open(B+'ft_chains_raw.json')); yf=json.load(open(B+'yf_scan.json'))
r=0.04
def N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def bs_put(S,K,T,s):
    d1=(math.log(S/K)+(r+s*s/2)*T)/(s*math.sqrt(T)); d2=d1-s*math.sqrt(T)
    return K*math.exp(-r*T)*N(-d2)-S*N(-d1)
def iv(S,K,T,p):
    lo,hi=0.01,4.0
    if bs_put(S,K,T,lo)>p: return None
    for _ in range(100):
        m=(lo+hi)/2
        if bs_put(S,K,T,m)>p: hi=m
        else: lo=m
    return (lo+hi)/2
def near(ch,K):
    k=min(ch,key=lambda s:abs(float(s)-K)); return float(k),ch[k]
out={}; rows=[]
for t,exps in d['puts'].items():
    S=d['spot'][t]; rv20=yf[t]['rv20']; rv60=yf[t]['rv60']
    out[t]={'spot':S,'rv20':rv20,'rv60':rv60,'exp':{}}
    for e,ch in exps.items():
        days=d['days'][e]; T=days/365
        def info(K):
            k,(b,a)=near(ch,K); mid=(a+b)/2
            return dict(strike=k,bid=b,ask=a,mid=round(mid,2),iv_mid=iv(S,k,T,mid),
                        spread_pct=round((a-b)/mid*100,1),ask_pct_spot=round(a/S*100,2),ann_pct=round(a/S*100*365/days,1))
        atm=info(S); p5=info(.95*S); p10=info(.90*S); p15=info(.85*S)
        debit=p5['ask']-p15['bid']; width=p5['strike']-p15['strike']
        sp=dict(long=p5['strike'],short=p15['strike'],debit=round(debit,2),debit_pct=round(debit/S*100,2),width=width,
                max_gain=round(width-debit,2),gain_to_loss=round((width-debit)/debit,2),debit_mid=round(p5['mid']-p15['mid'],2))
        rec=dict(days=days,atm=atm,put5=p5,put10=p10,put15=p15,bear_put_5_15=sp,
                 vrp_vs_rv20=round(atm['iv_mid']-rv20,3) if atm['iv_mid'] else None)
        out[t]['exp'][e]=rec
# IV ratios (60d ATM)
idx={t:out[t]['exp']['20261218']['atm']['iv_mid'] for t in ['SMH','QQQ','SPY']}
for t in out:
    a=out[t]['exp']['20261218']['atm']['iv_mid']
    out[t]['iv_ratio_60d']={k:round(a/v,2) for k,v in idx.items()}
# CC
for t,c in d['cc_calls_20261120'].items():
    out[t]['cc_28d']=dict(c,bid_pct_spot=round(c['bid']/c['spot']*100,2),otm_pct=round((c['strike']/c['spot']-1)*100,1),
        monthly_ann=round(c['bid']/c['spot']*100*365/28,1),feasible=c['shares_held']>=100,
        note=("需買 %d 股補到 100"%(100-c['shares_held']) if c['shares_held']<100 else ""))
# hedge ledger
S=d['spot']['SMH']; expo=0.835*231200; notional=S*100
p10=out['SMH']['exp']['20261218']['put10']; days=56
k25,(b25,a25)=near(d['puts']['SMH']['20261218'],0.75*S)
n_full=expo/notional
def ledger(n,label,prem_per):
    cost=n*prem_per*100; ann=cost*365/days
    return dict(label=label,contracts=round(n,2),contracts_rounded=round(n),cost_per_roll=round(cost),annual_cost=round(ann),annual_pct_total_value=round(ann/242997*100,2),annual_pct_equity=round(ann/231200*100,2))
spread_debit=p10['ask']-b25
hedge=dict(beta_exposure=round(expo),smh_spot=S,notional_per_contract=notional,put10=dict(strike=p10['strike'],ask=p10['ask']),
  put25=dict(strike=k25,bid=b25),spread_10_25_debit=round(spread_debit,2),spread_width=p10['strike']-k25,
  rows=[ledger(n_full,'全額 10%OTM put',p10['ask']),ledger(n_full/2,'半額 10%OTM put',p10['ask']),
        ledger(n_full,'全額 −10/−25 賣權價差',spread_debit),ledger(n_full/2,'半額 −10/−25 賣權價差',spread_debit)])
# 4-contract rounded versions
for rw in hedge['rows']:
    n=rw['contracts_rounded']; per=p10['ask'] if 'put' in rw['label'] and '價差' not in rw['label'] else spread_debit
    rw['rounded_cost_per_roll']=round(n*per*100); rw['rounded_annual_cost']=round(n*per*100*365/days)
out['_hedge_ledger']=hedge
json.dump(out,open(B+'computed.json','w'),indent=1)
# print tables
print("| 標的 | 現價(10/22收) | 到期(天) | ATM IV(mid) | RV20 | RV60 | VRP | 10%OTM put 履約 | ask | 成本% | 年化% | 5%OTM 年化% | bid-ask%(10%put) | 熊市價差5/15 debit% | 最大獲利/損失 | IV÷SMH | IV÷QQQ | IV÷SPY |")
print("|"+"---|"*18)
for t in d['puts']:
    for e in ['20261218','20270219','20270319']:
        if e not in out[t]['exp']: continue
        x=out[t]['exp'][e]; a=x['atm']; p=x['put10']; s=x['bear_put_5_15']; ir=out[t]['iv_ratio_60d']
        f=lambda v: "%.1f"%(v*100) if v else "n/a"
        print(f"| {t} | {out[t]['spot']} | {e[:4]}-{e[4:6]}-{e[6:]} ({x['days']}) | {f(a['iv_mid'])} | {out[t]['rv20']*100:.1f} | {out[t]['rv60']*100:.1f} | {('%+.1f'%(x['vrp_vs_rv20']*100)) if x['vrp_vs_rv20'] is not None else 'n/a'} | {p['strike']:g} | {p['ask']} | {p['ask_pct_spot']} | {p['ann_pct']} | {x['put5']['ann_pct']} | {p['spread_pct']} | {s['debit_pct']} | {s['gain_to_loss']} | {ir['SMH']} | {ir['QQQ']} | {ir['SPY']} |")
print()
print(json.dumps(hedge,indent=1,ensure_ascii=False))
print(json.dumps({t:out[t].get('cc_28d') for t in ['CRWD','MU']},indent=1,ensure_ascii=False))
