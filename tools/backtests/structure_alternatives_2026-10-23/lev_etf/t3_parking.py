from lib import *
rows=[]
for start,label in [("2012-01-03","2012→2026"),("2006-06-22","2006-06（QLD/SSO 成立）→2026")]:
    core = core_proxy(start=start)
    for park in [0.10, 0.20]:
        for inst in ["VOO","QLD","SSO","QQQ","SPY"]:
            if inst=="VOO" and start<"2010-09-10":
                inst2="SPY"; note="(VOO 未成立，用 SPY 代)"
            else: inst2=inst; note=""
            df = pd.concat([core.rename("CORE"), RET[inst2].rename("PARK")], axis=1).dropna()
            nav = rebalance_nav(df, {"CORE":1-park, "PARK":park}, mode="M")
            m = metrics(nav)
            rows.append(f"| {label} | {int(park*100)}% | {inst}{note} | {fmt_pct(m['cagr'])} | {fmt_u(m['vol'])} | {fmt_pct(m['mdd'])} | {fmt_num(m['sharpe'])} | {fmt_pct(m['r2022'])} | {fmt_pct(m['w1'])} | {fmt_pct(m['w2'])} |")
    cm = metrics(nav_from_ret(core))
    rows.append(f"| {label} | 0% | 純 0.835×SMH 代理 | {fmt_pct(cm['cagr'])} | {fmt_u(cm['vol'])} | {fmt_pct(cm['mdd'])} | {fmt_num(cm['sharpe'])} | {fmt_pct(cm['r2022'])} | {fmt_pct(cm['w1'])} | {fmt_pct(cm['w2'])} |")
hdr="| 期間 | 停泊格 | 停泊工具 | CAGR | 年化波動 | MDD | Sharpe | 2022 | 06/22→07/28 | 10/07→10/16 |\n|---|---|---|---|---|---|---|---|---|---|\n"
open("out_t3.md","w").write("### 表3 R33/R36 停泊格替換：(1−p)×[0.835×SMH 代理] + p×停泊工具，每月再平衡\n"+hdr+"\n".join(rows)+"\n")
print(open("out_t3.md").read())
