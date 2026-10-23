import pandas as pd, numpy as np, json
OUT="."
T=pd.read_csv("table_all.csv",index_col=0)
px=pd.read_csv("adj_close.csv",index_col=0,parse_dates=True); ret=px.pct_change()
rf=(px["^IRX"].ffill()/100/252).reindex(ret.index).ffill().fillna(0)
def stats(r,start):
    r=r.loc[start:].dropna(); n=len(r); tr=(1+r).prod()-1; cagr=(1+tr)**(252/n)-1
    eq=(1+r).cumprod(); return cagr,(r-rf.loc[r.index]).mean()/r.std()*np.sqrt(252),(eq/eq.cummax()-1).min()
def ab(t,b,start):
    r=ret[[t,b]].loc[start:].dropna(); y=r[t]-rf.loc[r.index]; x=r[b]-rf.loc[r.index]
    beta=np.cov(x,y)[0,1]/x.var(); return (y.mean()-beta*x.mean())*252,beta
def win(t,b,start):
    r=ret[[t,b]].loc[start:].dropna(); e=(1+r).cumprod(); w=(e/e.shift(252)-1).dropna(); return (w[t]>w[b]).mean()
# SPMO/QMOM/CIBR vs QQQ since own inception
extra={}
for t in ["SPMO","QMOM","CIBR","COWZ","AIQ","PAVE","WCLD","QQQM","JEPQ","JEPI","BUFR"]:
    st=px[t].dropna().index[0]+pd.Timedelta(days=1)
    c,s,m=stats(ret[t],st); cq,sq,mq=stats(ret["QQQ"],st); cs,ss,ms=stats(ret["SMH"],st); cv,sv,mv=stats(ret["VOO"],st)
    a,b=ab(t,"QQQ",st)
    extra[t]=dict(start=str(st.date()),cagr=c,sharpe=s,mdd=m,qqq_cagr=cq,qqq_sharpe=sq,smh_cagr=cs,voo_cagr=cv,aQQQ=a,bQQQ=b,winQQQ=win(t,"QQQ",st),winSMH=win(t,"SMH",st))
json.dump(extra,open("since_inception_vs_bench.json","w"),indent=1,default=float)
print(pd.DataFrame(extra).T.round(3).to_string())
p=lambda x: "—" if pd.isna(x) else f"{x*100:.1f}%"
f2=lambda x: "—" if pd.isna(x) else f"{x:.2f}"
L=[]
L.append("### 表 1 總表（按 2015→ Sharpe 排序；2015 後成立者排在下方按 2020→ Sharpe；資料 yfinance 調整收盤=含息總報酬，rf=^IRX，至 2026-10-22）")
L.append("| ETF | 成立 | 費用率 | 配息率 | NRA 30% 年拖累 | CAGR 15→ | 波動 15→ | MDD 15→ | Sharpe 15→ | CAGR 20→ | 波動 20→ | MDD 20→ | Sharpe 20→ | 2022 | 2026 YTD | 12M勝QQQ 15→ | 12M勝SMH 15→ | 12M勝QQQ 20→ | 12M勝SMH 20→ | 與SMH相關 15→ |")
L.append("|"+"---|"*20)
A=T[T.sharpe15.notna()].sort_values("sharpe15",ascending=False); B=T[T.sharpe15.isna()].sort_values("sharpe20",ascending=False)
for df in [A,B]:
    for t,r in df.iterrows():
        L.append(f"| {t} | {r.incept[:7]} | {r.expense:.2f}% | {r.yield_ttm:.2f}% | {r.nra_drag:.2f}% | {p(r.cagr15)} | {p(r.vol15)} | {p(r.mdd15)} | {f2(r.sharpe15)} | {p(r.cagr20)} | {p(r.vol20)} | {p(r.mdd20)} | {f2(r.sharpe20)} | {p(r.r2022)} | {p(r.ytd2026)} | {p(r.win15_QQQ)} | {p(r.win15_SMH)} | {p(r.win20_QQQ)} | {p(r.win20_SMH)} | {f2(r.corrSMH15 if not pd.isna(r.corrSMH15) else r.corrSMH20)} |")
L.append("")
L.append("### 表 2 對 QQQ 回歸的 α/β 拆解（日報酬超額回歸，α 年化；僅列 2015 起有資料者 + 2020→ 全員）")
L.append("| ETF | α/年 15→ | β 15→ | 追蹤誤差 15→ | α/年 20→ | β 20→ | 對 SMH α 15→ | 對 SMH β 15→ | 對 SMH α 20→ | 對 SMH β 20→ | 判讀 |")
L.append("|"+"---|"*11)
def judge(r):
    a=r.aQQQ20; b=r.bQQQ20
    if pd.isna(a): return "—"
    if a>0.02 and b>1.1: return "高 β 板塊 + 正 α（半導體板塊 β）"
    if a>0.02: return "正 α（非 QQQ β 來源：資產類別/板塊/因子）"
    if b>1.1: return "純高 β，α≤0"
    if a<-0.03: return "負 α"
    return "≈QQQ 縮放版"
for t,r in T.sort_values("aQQQ20",ascending=False).iterrows():
    if t=="QQQ": continue
    L.append(f"| {t} | {p(r.aQQQ15)} | {f2(r.bQQQ15)} | {p(r.teQQQ15)} | {p(r.aQQQ20)} | {f2(r.bQQQ20)} | {p(r.aSMH15)} | {f2(r.bSMH15)} | {p(r.aSMH20)} | {f2(r.bSMH20)} | {judge(r)} |")
L.append("")
park=json.load(open("parking.json"))
L.append("### 表 3 停泊格替換：組合 = 90% × (0.835×SMH + 0.165×T-bill) + 10% × 停泊 ETF，每日再平衡；兩段起點 2015-10-12（SPMO 成立）與 2020-01-01")
L.append("| 停泊 ETF | 與SMH相關 15→ | CAGR 15→ | MDD 15→ | Sharpe 15→ | CAGR 20→ | MDD 20→ | Sharpe 20→ | 對比 VOO 版 Sharpe 15→ |")
L.append("|"+"---|"*9)
v15=park["2015-10-12"]["VOO"]["sharpe"]
L.append(f"| （純代理，無停泊格） | 1.00 | {p(park['2015-10-12']['VOO']['proxy_cagr'])} | {p(park['2015-10-12']['VOO']['proxy_mdd'])} | {f2(park['2015-10-12']['VOO']['proxy_sharpe'])} | {p(park['2020-01-01']['VOO']['proxy_cagr'])} | {p(park['2020-01-01']['VOO']['proxy_mdd'])} | {f2(park['2020-01-01']['VOO']['proxy_sharpe'])} | — |")
for e in ["VOO","SPY","QQQ","SCHG","MTUM","SPMO","QUAL","RSP","USMV","SPLV","COWZ","XLE","GLD","CASH(T-bill)"]:
    a=park["2015-10-12"].get(e); b=park["2020-01-01"].get(e)
    L.append(f"| {e} | {f2(a['corrSMH']) if a else f2(b['corrSMH'])} | {p(a['cagr']) if a else '—'} | {p(a['mdd']) if a else '—'} | {f2(a['sharpe']) if a else '—'} | {p(b['cagr'])} | {p(b['mdd'])} | {f2(b['sharpe'])} | {('%+.3f'%(a['sharpe']-v15)) if a else '—'} |")
L.append("")
sw=json.load(open("software_bench.json"))
L.append("### 表 4 R36 基準格候選（軟體/AI 基準 vs QQQ；α 為對 QQQ 年化）")
L.append("| ETF | 成立 | CAGR 15→ | Sharpe 15→ | MDD 15→ | 12M勝QQQ 15→ | CAGR 20→ | Sharpe 20→ | α/β vs QQQ 20→ | 12M勝QQQ 20→ | CAGR 23→ | α/β 23→ | 2026 YTD |")
L.append("|"+"---|"*13)
for t in ["QQQ","IGV","WCLD","SKYY","AIQ","CIBR","FDN","XLK","VGT","SMH","SOXX","VOO"]:
    d=sw[t]; g=lambda k,f: f(d[k]) if k in d else "—"
    def ab_(k): return f"{d[k]['aQQQ']*100:+.1f}% / {d[k]['bQQQ']:.2f}" if k in d else "—"
    L.append(f"| {t} | {T.loc[t,'incept'][:7]} | {g('15',lambda x:p(x['cagr']))} | {g('15',lambda x:f2(x['sharpe']))} | {g('15',lambda x:p(x['mdd']))} | {g('15',lambda x:p(x['win_QQQ']))} | {g('20',lambda x:p(x['cagr']))} | {g('20',lambda x:f2(x['sharpe']))} | {ab_('20')} | {g('20',lambda x:p(x['win_QQQ']))} | {g('23',lambda x:p(x['cagr']))} | {ab_('23')} | {p(d['ytd2026'])} |")
L.append("")
inc=json.load(open("income.json"))
L.append("### 表 5 收租/緩衝型 vs 基準（總報酬 CAGR；NRA 稅後 = 配息只再投入 70%；基準同法計）")
L.append("| ETF（起點） | 基準 | ETF 總報酬 CAGR | ETF 價格 CAGR | ETF 稅後 CAGR | 基準總報酬 CAGR | 基準稅後 CAGR | 稅前差 | 稅後差 | ETF MDD | 基準 MDD | ETF Sharpe | 基準 Sharpe | 月上行捕獲 | 月下行捕獲 |")
L.append("|"+"---|"*15)
for k,d in inc.items():
    L.append(f"| {k.split('_')[0]}（{d['start']}） | {d['bench']} | {p(d['tr_cagr'])} | {p(d['price_cagr'])} | {p(d['aftertax_cagr'])} | {p(d['bench_tr_cagr'])} | {p(d['bench_aftertax_cagr'])} | {d['gap_pretax']*100:+.1f}pp | {d['gap_aftertax']*100:+.1f}pp | {p(d['tr_mdd'])} | {p(d['bench_mdd'])} | {f2(d['tr_sharpe'])} | {f2(d['bench_sharpe'])} | {f2(d['upcap'])} | {f2(d['downcap'])} |")
L.append("")
mom=json.load(open("momentum.json"))
L.append("### 表 6 動能 ETF 分段（成立前因子回測 yfinance 無資料，只列成立後；對 SPY 年化 α/β）")
L.append("| ETF | 成立 | 成立→2019 CAGR / Sharpe | 2020→2022 CAGR / Sharpe | 2023→ CAGR / Sharpe | 成立→ CAGR / Sharpe / MDD | α/β vs SPY 成立→ | α/β vs SPY 20→ |")
L.append("|"+"---|"*8)
for t in ["SPMO","MTUM","XMMO","QMOM","QQQ","SPY"]:
    d=mom[t]; s=lambda k: f"{d[k]['cagr']*100:.1f}% / {d[k]['sharpe']:.2f}" if k in d else "—"
    L.append(f"| {t} | {d['incept→']['start']} | {s('incept→2019')} | {s('2020→2022')} | {s('2023→')} | {s('incept→')} / {p(d['incept→']['mdd'])} | {d['aSPY_inc']*100:+.1f}% / {d['bSPY_inc']:.2f} | {d['aSPY_20']*100:+.1f}% / {d['bSPY_20']:.2f} |")
L.append("")
q6=json.load(open("ytd2026.json"))
L.append("### 表 7 2026 YTD（2025-12-31 收盤 → 2026-10-22，含息）：帳戶 20 檔等權買抱 vs ETF")
L.append(f"| 組合 | 2026 YTD |\n|---|---|\n| 20 檔等權買抱（不再平衡） | {p(q6['ew_buyhold_ytd'])}（路徑 MDD {p(q6['ew_bh_mdd'])}，年化波動 {p(q6['ew_vol'])}） |\n| 20 檔等權每日再平衡 | {p(q6['ew_dailyrebal_ytd'])} |\n| 帳戶實際（主程提供） | +27.4% |")
ey=sorted(q6["etf_ytd"].items(),key=lambda x:-x[1])
L.append("| ETF | " + " | ".join(k for k,_ in ey)+" |"); L.append("|---|"+"---|"*len(ey)); L.append("| YTD | "+" | ".join(p(v) for _,v in ey)+" |")
L.append("| 個股 | " + " | ".join(k for k in q6["per_stock"])+" |"); L.append("|---|"+"---|"*len(q6["per_stock"])); L.append("| YTD | "+" | ".join(p(v) for v in q6["per_stock"].values())+" |")
open("tables.md","w").write("\n".join(L))
print(len("\n".join(L)))
