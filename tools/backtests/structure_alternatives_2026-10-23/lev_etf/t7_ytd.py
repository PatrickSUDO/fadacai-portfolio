from lib import *
rows=["### 表6g 2026 YTD（2026-01-02→10-22）：波動與 β 配對追蹤","| 項目 | 值 |","|---|---|"]
for t in ["SMH","SOXL","QQQ","TQQQ","SPY"]:
    r = RET[t].loc["2026-01-02":].dropna(); nav = nav_from_ret(r); m = metrics(nav)
    rows.append(f"| {t} YTD 報酬 / 年化波動 / MDD | {fmt_pct(nav.iloc[-1]-1)} / {fmt_u(m['vol'])} / {fmt_pct(m['mdd'])} |")
for lev,k,und in [("SOXL",3,"SMH"),("TQQQ",3,"QQQ"),("QLD",2,"QQQ"),("SSO",2,"SPY")]:
    c = RET[[lev,und,"TBILL"]].dropna().loc["2026-01-02":]
    b = nav_from_ret(c[und]).iloc[-1]-1
    for mode,mn in [("M","月"),("B","±5pp")]:
        nav = rebalance_nav(c,{lev:1/k,"TBILL":1-1/k},mode=mode)
        rows.append(f"| {int(round(100/k))}% {lev}+T-bill（{mn}）YTD vs 100% {und} | {fmt_pct(nav.iloc[-1]-1)} vs {fmt_pct(b)}（差 {fmt_pct(nav.iloc[-1]-1-b)}） |")
for s in [0.20,0.30,0.36,0.45]:
    rows.append(f"| 理論波動衰減／單位 β，σ={int(s*100)}%：3x 為 σ²(k−1)/2 | {fmt_u(s*s*1.0)}（2x：{fmt_u(s*s*0.5)}） |")
open("out_t6.md","a").write("\n"+"\n".join(rows)+"\n"); print("\n".join(rows))
