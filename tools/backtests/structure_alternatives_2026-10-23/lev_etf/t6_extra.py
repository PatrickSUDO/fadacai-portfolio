from lib import *
import yfinance as yf
out=[]
# (a) buy & hold beta pair (no rebalance): cap holds, beta drifts
out.append("### 表6a β 配對「不再平衡」版（買進放著）：損失封頂成立，但 β 漂移\n| 組合 | 起點 | CAGR | MDD | Sharpe | 期末槓桿ETF權重 | 期末等效 β | 2022 | 06/22→07/28 |\n|---|---|---|---|---|---|---|---|---|")
for lev,k,und,start in [("SOXL",3,"SMH","2010-03-12"),("TQQQ",3,"QQQ","2010-02-12"),("SOXL",3,"SMH","2020-01-02"),("TQQQ",3,"QQQ","2020-01-02"),("SOXL",3,"SMH","2023-01-03")]:
    c = RET[[lev,"TBILL"]].dropna().loc[start:]
    nav = rebalance_nav(c, {lev:1/k,"TBILL":1-1/k}, mode="N")
    # end weight
    lev_nav = (1/k)*nav_from_ret(c[lev]); tb = (1-1/k)*nav_from_ret(c["TBILL"])
    w_end = lev_nav.iloc[-1]/(lev_nav.iloc[-1]+tb.iloc[-1]); w_max = (lev_nav/(lev_nav+tb)).max()
    m = metrics(nav); bm = metrics(nav_from_ret(RET[und].loc[c.index[0]:]))
    out.append(f"| {int(round(100/k))}% {lev} + T-bill 不再平衡 | {start} | {fmt_pct(m['cagr'])}（{und} {fmt_pct(bm['cagr'])}） | {fmt_pct(m['mdd'])}（{und} {fmt_pct(bm['mdd'])}） | {fmt_num(m['sharpe'])}（{und} {fmt_num(bm['sharpe'])}） | {fmt_u(w_end)}（峰 {fmt_u(w_max)}） | {w_end*k:.2f}（峰 {w_max*k:.2f}） | {fmt_pct(m['r2022'])} | {fmt_pct(m['w1'])} |")
# (b) high-rate subperiod beta pair
out.append("\n### 表6b 高利率期（2023-01-03→2026-10-22，rf 均值 4.47%）β 配對 vs 全額持有\n| 組合 | CAGR | 年化波動 | MDD | Sharpe | 追蹤差 |\n|---|---|---|---|---|---|")
for lev,k,und in [("SOXL",3,"SMH"),("TQQQ",3,"QQQ"),("QLD",2,"QQQ"),("SSO",2,"SPY")]:
    c = RET[[lev,und,"TBILL"]].dropna().loc["2023-01-03":]
    bm = metrics(nav_from_ret(c[und]))
    out.append(f"| 100% {und} | {fmt_pct(bm['cagr'])} | {fmt_u(bm['vol'])} | {fmt_pct(bm['mdd'])} | {fmt_num(bm['sharpe'])} | — |")
    for mode,mn in [("M","月"),("B","±5pp")]:
        m = metrics(rebalance_nav(c, {lev:1/k,"TBILL":1-1/k}, mode=mode))
        out.append(f"| {int(round(100/k))}% {lev} + T-bill（{mn}） | {fmt_pct(m['cagr'])} | {fmt_u(m['vol'])} | {fmt_pct(m['mdd'])} | {fmt_num(m['sharpe'])} | {fmt_pct(m['cagr']-bm['cagr'])} |")
print("rf 2023→:", RF_D.loc["2023-01-03":].mean()*252)
# (c) decay by rate regime
out.append("\n### 表6c 理想 k×日複利 − 實際 CAGR（總成本 pp/年）分利率期\n| ETF | 2010/成立→2021（rf 均值） | 2022→2026-10（rf 均值） | 理論 (k−1)(rf+0.4%)+ER 低利率期 | 理論 高利率期 |\n|---|---|---|---|---|")
ER = {"SOXL":0.0075,"TQQQ":0.0084,"QLD":0.0095,"SSO":0.0089,"UPRO":0.0091,"TECL":0.0094}
K  = {"SOXL":3,"TQQQ":3,"QLD":2,"SSO":2,"UPRO":3,"TECL":3}
UND= {"SOXL":"SOXX","TQQQ":"QQQ","QLD":"QQQ","SSO":"SPY","UPRO":"SPY","TECL":"XLK"}
for t in K:
    cells=[]
    for a,b in [(None,"2021-12-31"),("2022-01-03",None)]:
        r = RET[t].dropna(); r = r.loc[a or r.index[0]: b or r.index[-1]]
        if a and r.index[0] < pd.Timestamp("2010-01-01"): pass
        u = RET[UND[t]].reindex(r.index); rf = RF_D.reindex(r.index)
        gap = metrics(nav_from_ret(K[t]*u))['cagr'] - metrics(nav_from_ret(r))['cagr']
        theo = (K[t]-1)*(rf.mean()*252+0.004)+ER[t]
        cells += [f"{fmt_pct(gap)}（rf {fmt_u(rf.mean()*252)}）", theo]
    out.append(f"| {t} | {cells[0]} | {cells[2]} | {fmt_pct(cells[1])} | {fmt_pct(cells[3])} |")
# (d) dividends TTM
out.append("\n### 表6d 配息（TTM 至 2026-10-22，yfinance dividends；NRA 預扣 30%）\n| ETF | TTM 配息率 | 30% 預扣 ≈ 年拖累 |\n|---|---|---|")
for t in ["SOXL","TQQQ","QLD","SSO","SMH","QQQ","SPY","VOO","SGOV"]:
    try:
        d = yf.Ticker(t).dividends
        d.index = d.index.tz_localize(None)
        ttm = d.loc["2025-10-23":"2026-10-22"].sum(); y = ttm/float(PX[t].dropna().iloc[-1])
        note = "（QII，免預扣）" if t=="SGOV" else ""
        out.append(f"| {t} | {fmt_u(y,2)} | {fmt_u(0 if t=='SGOV' else y*0.3,2)}{note} |")
    except Exception as e: out.append(f"| {t} | 抓取失敗 {e} | |")
# (e) 100% SMH other periods and beta of parking instruments to SMH
out.append("\n### 表6e 參考：100% SMH 各期間 + 停泊工具對 SMH 的日 β / 相關（2012→2026）\n| 項目 | 值 |\n|---|---|")
for s in ["2012-01-03","2020-01-02"]:
    m = metrics(nav_from_ret(RET["SMH"].loc[s:]))
    out.append(f"| 100% SMH {s}→ | CAGR {fmt_pct(m['cagr'])}、波動 {fmt_u(m['vol'])}、MDD {fmt_pct(m['mdd'])}、Sharpe {fmt_num(m['sharpe'])} |")
r = RET.loc["2012-01-03":, ["SMH","VOO","SPY","QQQ","QLD","SSO","TQQQ","SOXL"]].dropna()
for c in ["VOO","QQQ","QLD","SSO","TQQQ","SOXL"]:
    b = r[c].cov(r["SMH"])/r["SMH"].var(); rho = r[c].corr(r["SMH"])
    out.append(f"| {c} 對 SMH | β {b:.2f}、相關 {rho:.2f} |")
# (f) today's cost
rf_today = float(PX["^IRX"].dropna().iloc[-1])/100
out.append(f"\n### 表6f 今日成本（^IRX 2026-10-22 = {rf_today*100:.2f}%）\n| ETF | k | ER | 內嵌融資 (k−1)(rf+0.4%) | 合計拖累 pp/年 | 以 1/k 配對後對組合的拖累 |\n|---|---|---|---|---|---|")
for t,er in [("SOXL",0.0075),("TQQQ",0.0084),("USD",0.0095),("QLD",0.0095),("SSO",0.0089),("UPRO",0.0091),("TECL",0.0094)]:
    k = 3 if t in ("SOXL","TQQQ","UPRO","TECL") else 2
    fin = (k-1)*(rf_today+0.004); tot = fin+er
    out.append(f"| {t} | {k} | {er*100:.2f}% | {fin*100:.2f}pp | {tot*100:.2f}pp | {tot/k*100:.2f}pp（T-bill 腿收 {(1-1/k)*rf_today*100:.2f}pp，淨 {((1-1/k)*rf_today - tot/k)*100:+.2f}pp） |")
open("out_t6.md","w").write("\n".join(out)+"\n"); print("\n".join(out))
