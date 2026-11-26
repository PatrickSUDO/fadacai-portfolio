import json,glob,re,collections,sys
import pandas as pd, numpy as np, yfinance as yf
D='research/sa-quant-scans/'
lists=collections.defaultdict(dict)
for f in sorted(glob.glob(D+'api-*.json')):
    m=re.match(r'.*api-(\d{4}-\d\d-\d\d)-(.+)\.json',f); d=json.load(open(f))
    lists[m.group(2)][m.group(1)]=(set(s.upper() for s in d['slugs']), d.get('metrics',{}))
ev=[]
for name in ('strong-buy','alpha-pick'):
    dates=sorted(lists[name]); seen=set(lists[name][dates[0]][0])
    for t in seen: ev.append((name,dates[0],t,'initial',lists[name][dates[0]][1].get(t.lower(),{}).get('marketcap_display')))
    for dt in dates[1:]:
        cur,met=lists[name][dt]
        for t in cur-seen: ev.append((name,dt,t,'new',met.get(t.lower(),{}).get('marketcap_display')))
        seen|=cur
    print(name,'scans',len(dates),dates[0],dates[-1])
df=pd.DataFrame(ev,columns=['list','date','t','kind','mcap'])
tick=sorted(set(df.t))+['SPY','IWM','SMH']
px=yf.download(tick,start='2026-07-01',auto_adjust=True,progress=False)['Close']
def fwd(t,d,h):
    if t not in px or px[t].dropna().empty: return None
    idx=px.index[px.index>=pd.Timestamp(d)]
    if len(idx)<=h: return None
    a,b=idx[0],idx[h]
    if pd.isna(px[t].get(a)) or pd.isna(px[t].get(b)): return None
    return (px[t][b]/px[t][a]-1)*100, (px['SPY'][b]/px['SPY'][a]-1)*100, (px['IWM'][b]/px['IWM'][a]-1)*100
for h in (20,40):
    r=[fwd(t,d,h) for t,d in zip(df.t,df.date)]
    df[f'r{h}']=[x[0] if x else np.nan for x in r]; df[f'xs{h}']=[x[0]-x[1] if x else np.nan for x in r]; df[f'xi{h}']=[x[0]-x[2] if x else np.nan for x in r]
df['big']=df.mcap.fillna(0)>=1e10
def summ(g,lab):
    out=[lab,len(g)]
    for h in (20,40):
        x=g[f'xs{h}'].dropna(); xi=g[f'xi{h}'].dropna()
        out+= [len(x), round(x.mean(),1) if len(x) else None, round(x.median(),1) if len(x) else None, round((x>0).mean()*100) if len(x) else None, round(xi.mean(),1) if len(xi) else None]
    print(out)
print('[label,n, n20,mean_xsSPY20,med20,hit20,mean_xsIWM20, n40,mean40,med40,hit40,mean_xsIWM40]')
for (l,k),g in df.groupby(['list','kind']): summ(g,f'{l}/{k}')
for l,g in df.groupby('list'): summ(g[g.big],f'{l}/mcap>=10B'); summ(g[~g.big],f'{l}/<10B')
# by cohort date
for (l,d),g in df[df.kind=='new'].groupby(['list','date']): summ(g,f'{l} {d}')
df.to_csv(sys.argv[1],index=False)
print(df[df.big].sort_values('date')[['list','date','t','kind','xs20','xs40']].to_string())
