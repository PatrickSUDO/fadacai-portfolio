from lib import *
rows=[]
for start,label in [("2010-03-12","2010-03（SOXL 成立）→2026"),("2012-01-03","2012→2026"),("2020-01-02","2020→2026")]:
    core = core_proxy(start=start)
    cm = metrics(nav_from_ret(core))
    rows.append(f"| {label} | 100% 代理（無衛星） | {fmt_pct(cm['cagr'])} | {fmt_u(cm['vol'])} | {fmt_pct(cm['mdd'])} | {fmt_num(cm['sharpe'])} | {fmt_pct(cm['r2022'])} | {fmt_pct(cm['w1'])} | {fmt_pct(cm['w2'])} |")
    for sat in ["SOXL","TQQQ","SMH","QQQ","USD","QLD"]:
        df = pd.concat([core.rename("CORE"), RET[sat].rename("SAT")], axis=1).dropna()
        nav = rebalance_nav(df, {"CORE":0.9, "SAT":0.1}, mode="M")
        m = metrics(nav)
        rows.append(f"| {label} | 90% 代理 + 10% {sat} | {fmt_pct(m['cagr'])} | {fmt_u(m['vol'])} | {fmt_pct(m['mdd'])} | {fmt_num(m['sharpe'])} | {fmt_pct(m['r2022'])} | {fmt_pct(m['w1'])} | {fmt_pct(m['w2'])} |")
    # same beta: 10% SOXL ≈ 30% SMH exposure → compare 70% core + 30% SMH? instead compare beta-matched: core(0.835)*0.9 + 0.3 SMH vs core*0.9+0.1 SMH
    df = pd.concat([core.rename("CORE"), RET["SMH"].rename("SAT")], axis=1).dropna()
    nav = rebalance_nav(df, {"CORE":0.9, "SAT":0.3}, mode="M")  # weights sum 1.2 → implies 20% borrowed; skip
hdr="| 期間 | 組合（每月再平衡） | CAGR | 年化波動 | MDD | Sharpe | 2022 | 06/22→07/28 | 10/07→10/16 |\n|---|---|---|---|---|---|---|---|---|\n"
open("out_t4.md","w").write("### 表4 衛星：90%×[0.835×SMH 代理] + 10% 衛星，每月再平衡\n"+hdr+"\n".join(rows)+"\n")
print(open("out_t4.md").read())
