from lib import *
# expense ratios (approx, from issuer fact sheets as remembered; NOT live-verified)
ER = {"SOXL":0.0075,"USD":0.0095,"TQQQ":0.0084,"QLD":0.0095,"SSO":0.0089,"SPXL":0.0091,"UPRO":0.0091,"TECL":0.0094}
K  = {"SOXL":3,"USD":2,"TQQQ":3,"QLD":2,"SSO":2,"SPXL":3,"UPRO":3,"TECL":3}
UND= {"SOXL":"SOXX","USD":"SOXX","TQQQ":"QQQ","QLD":"QQQ","SSO":"SPY","SPXL":"SPY","UPRO":"SPY","TECL":"XLK"}
rows=[]; rows2=[]
for t in K:
    r = RET[t].dropna()
    u = RET[UND[t]].reindex(r.index)
    nav = nav_from_ret(r); m = metrics(nav, t)
    um = metrics(nav_from_ret(u), UND[t])
    ideal = nav_from_ret(K[t]*u); mi = metrics(ideal, f"{K[t]}x{UND[t]} ideal")
    rf = RF_D.reindex(r.index)
    theo = nav_from_ret(K[t]*u - (K[t]-1)*(rf+0.004/252) - ER[t]/252); mt = metrics(theo)
    fin = (K[t]-1)*(rf.mean()*252+0.004)
    rows.append(f"| {t} ({K[t]}x {UND[t]}) | {m['start']} | {fmt_pct(m['cagr'])} | {fmt_u(m['vol'])} | {fmt_pct(m['mdd'])} | {fmt_num(m['sharpe'])} | {m['worst_year']} | {fmt_pct(m['r2022'])} | {fmt_pct(m['w1'])} | {fmt_pct(m['w2'])} |")
    rows.append(f"| ↳ {UND[t]} 同期 | {um['start']} | {fmt_pct(um['cagr'])} | {fmt_u(um['vol'])} | {fmt_pct(um['mdd'])} | {fmt_num(um['sharpe'])} | {um['worst_year']} | {fmt_pct(um['r2022'])} | {fmt_pct(um['w1'])} | {fmt_pct(um['w2'])} |")
    rows2.append(f"| {t} | {fmt_pct(K[t]*um['cagr'])} | {fmt_pct(mi['cagr'])} | {fmt_pct(K[t]*um['cagr']-mi['cagr'])} | {fmt_pct(mt['cagr'])} | {fmt_pct(m['cagr'])} | {fmt_pct(mi['cagr']-m['cagr'])} | {fmt_pct(fin)} | {ER[t]*100:.2f}% | {fmt_pct(mi['cagr']-m['cagr']-fin-ER[t])} | {fmt_pct(rf.mean()*252)} |")
hdr = "| ETF | 起點 | CAGR | 年化波動 | MDD | Sharpe | 最差年 | 2022 | 06/22→07/28 | 10/07→10/16 |\n|---|---|---|---|---|---|---|---|---|---|\n"
hdr2 = "| ETF | k×標的CAGR(naive) | k×日報酬複利(理想,無費) | 波動衰減 = naive−理想 | 理論(理想−融資−ER) | 實際 CAGR | 理想−實際 = 總成本 | 其中融資 (k−1)(rf+0.4%) | ER | 殘差(追蹤/其他) | 期間平均 rf |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
open("out_t1.md","w").write("### 表1 單獨持有（成立以來→2026-10-22，yfinance auto_adjust）\n"+hdr+"\n".join(rows)+"\n\n### 表1b 衰減與成本分解（CAGR，pp/年）\n"+hdr2+"\n".join(rows2)+"\n")
print(open("out_t1.md").read())
# SMH vs SOXX check
for a,b in [("SMH","SOXX")]:
    r = RET[[a,b]].dropna().loc["2010-03-11":]
    print(a,b,"corr",r.corr().iloc[0,1].round(4), "CAGR", {c: round(metrics(nav_from_ret(r[c]))['cagr']*100,2) for c in r})
