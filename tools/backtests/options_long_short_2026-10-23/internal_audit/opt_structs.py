import json,re,collections,datetime as dt,csv,sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
LED = str(ROOT / 'research/trade-ledger.jsonl')
rows=[json.loads(l) for l in open(LED)]
opts=[r for r in rows if r.get('is_option')]
pat=re.compile(r'^([A-Z.]+)(\d{6})([CP])(\d{8})$')
def parse(sym):
    m=pat.match(sym); 
    if not m: return None
    u,e,cp,k=m.groups()
    return u,dt.date(2000+int(e[:2]),int(e[2:4]),int(e[4:6])),cp,int(k)/1000
# group by (underlying, expiry)
groups=collections.defaultdict(list)
bad=[]
for r in opts:
    p=parse(r['symbol'])
    if not p: bad.append(r['symbol']); continue
    u,e,cp,k=p
    groups[(u,e)].append(dict(r,cp=cp,strike=k,exp=e))
structs=[]
for (u,e),legs in sorted(groups.items(), key=lambda kv: min(x['date'] for x in kv[1])):
    legs.sort(key=lambda x:(x['date'],x['symbol']))
    # per-contract net position
    pos=collections.defaultdict(float); first={}
    open_d=min(l['date'] for l in legs); close_d=max(l['date'] for l in legs)
    day1=collections.defaultdict(float)
    for l in legs:
        q=l['qty']*(1 if l['side']=='BOUGHT' else -1)
        pos[l['symbol']]+=q
        if l['date']==open_d: day1[l['symbol']]+=q
    for l in legs:
        if l['symbol'] in first: continue
        q=day1.get(l['symbol'],0)
        if abs(q)<1e-9: q=l['qty']*(1 if l['side']=='BOUGHT' else -1)  # same-day scalp: use first trade sign
        first[l['symbol']]=(q,l['cp'],l['strike'])
    net=round(sum(l['amount'] for l in legs),2)
    still_open=any(abs(v)>1e-9 for v in pos.values())
    # initial legs: those opened on first date(s) — use sign of first trade per symbol
    longs=[(cp,k) for s,(q,cp,k) in first.items() if q>0]
    shorts=[(cp,k) for s,(q,cp,k) in first.items() if q<0]
    lc=[k for cp,k in longs if cp=='C']; lp=[k for cp,k in longs if cp=='P']
    sc=[k for cp,k in shorts if cp=='C']; sp=[k for cp,k in shorts if cp=='P']
    days=(dt.date.fromisoformat(close_d)-dt.date.fromisoformat(open_d)).days
    dte=(e-dt.date.fromisoformat(open_d)).days
    # price of underlying at open: approximate not available; LEAPS = dte>270 and long call
    typ='other'; dirn='?'; side='buyer'
    if lc and sc and not lp and not sp:
        if min(lc)<min(sc): typ='bull call spread'; dirn='看多'; side='buyer'
        else: typ='bear call spread'; dirn='看空'; side='seller'
    elif lp and sp and not lc and not sc:
        if min(lp)<min(sp): typ='bull put spread'; dirn='看多'; side='seller'
        else: typ='bear put spread'; dirn='看空'; side='buyer'
    elif lc and not sc and not lp and not sp:
        typ='LEAPS (long call)' if dte>270 else 'long call'; dirn='看多'
    elif lp and not sp and not lc and not sc:
        typ='long put'; dirn='看空'
    elif sc and not lc and not lp and not sp:
        typ='covered call'; dirn='中性/收租'; side='seller'
    elif sp and not lc and not lp and not sc:
        typ='short put'; dirn='看多'; side='seller'
    elif lc and lp and not sc and not sp:
        typ='long straddle/strangle'; dirn='中性(雙買)'
    elif sc and sp and not lc and not lp:
        typ='short strangle/iron'; dirn='中性(賣方)'; side='seller'
    elif lc and sc and lp and sp:
        typ='iron condor/complex'; dirn='中性'; side='seller'
    else:
        typ='other'; dirn='?'
    origins=collections.Counter(l.get('origin','unknown') for l in legs)
    structs.append(dict(underlying=u,expiry=e.isoformat(),type=typ,direction=dirn,side=side,open=open_d,close=close_d if not still_open else '(未平)',days=days,dte_at_open=dte,net_pnl=net,legs=len(legs),open_still=still_open,origin=';'.join(f'{k}:{v}' for k,v in origins.items()),strikes=' '.join(f"{'+' if q>0 else '-'}{cp}{k:g}" for s,(q,cp,k) in sorted(first.items()))))
closed=[s for s in structs if not s['open_still']]
out=str(Path(__file__).resolve().parent) + '/'
with open(out+'option_structures.csv','w') as f:
    w=csv.DictWriter(f,fieldnames=list(structs[0].keys())); w.writeheader(); w.writerows(structs)
json.dump(structs,open(out+'option_structures.json','w'),ensure_ascii=False,indent=1)
print('unparsed',bad)
print('structures',len(structs),'closed',len(closed),'open',len(structs)-len(closed))
def stat(name,ss):
    ss=[s for s in ss if not s['open_still']]
    n=len(ss); w=sum(1 for s in ss if s['net_pnl']>0); pnl=sum(s['net_pnl'] for s in ss)
    gp=sum(s['net_pnl'] for s in ss if s['net_pnl']>0); gl=-sum(s['net_pnl'] for s in ss if s['net_pnl']<0)
    pf=gp/gl if gl else float('inf')
    print(f'| {name} | {n} | {w} | {w/n*100 if n else 0:.0f}% | {pnl:+,.0f} | {gp:,.0f} / {gl:,.0f} | {pf:.2f} |')
    return n,w,pnl,pf
print('| 分組 | n | 勝 | 勝率 | 淨損益 | 毛利/毛損 | PF |')
stat('全部已結',structs)
stat('看空（long put + bear spreads）',[s for s in structs if s['direction']=='看空'])
stat('  其中 long put',[s for s in structs if s['type']=='long put'])
stat('  其中 bear call spread',[s for s in structs if s['type']=='bear call spread'])
stat('  其中 bear put spread',[s for s in structs if s['type']=='bear put spread'])
stat('看多（long call/LEAPS/bull spreads/short put）',[s for s in structs if s['direction']=='看多'])
stat('  其中 LEAPS',[s for s in structs if s['type'].startswith('LEAPS')])
stat('  其中 long call（非LEAPS）',[s for s in structs if s['type']=='long call'])
stat('  其中 bull put spread',[s for s in structs if s['type']=='bull put spread'])
stat('  其中 bull call spread',[s for s in structs if s['type']=='bull call spread'])
stat('中性/收租（covered call 等）',[s for s in structs if s['direction'].startswith('中性')])
stat('賣方（net credit 結構）',[s for s in structs if s['side']=='seller'])
stat('買方（net debit 結構）',[s for s in structs if s['side']=='buyer'])
stat('持有 <15 天',[s for s in structs if s['days']<15])
stat('持有 ≥15 天',[s for s in structs if s['days']>=15])
stat('持有 <15 天 且 買方',[s for s in structs if s['days']<15 and s['side']=='buyer'])
stat('持有 ≥15 天 且 買方',[s for s in structs if s['days']>=15 and s['side']=='buyer'])
stat('2026-07-01 起開倉',[s for s in structs if s['open']>='2026-07-01'])
stat('  7/1 起賣方',[s for s in structs if s['open']>='2026-07-01' and s['side']=='seller'])
stat('  7/1 起買方',[s for s in structs if s['open']>='2026-07-01' and s['side']=='buyer'])
print()
print('| # | 標的 | 到期 | 類型 | 方向 | 腿 | 開倉 | 平倉 | 天 | 淨損益 | origin |')
print('|---|---|---|---|---|---|---|---|---|---|---|')
for i,s in enumerate(structs,1):
    print(f"| {i} | {s['underlying']} | {s['expiry']} | {s['type']} | {s['direction']} | {s['strikes']} | {s['open']} | {s['close']} | {s['days']} | {s['net_pnl']:+,.0f} | {s['origin']} |")
