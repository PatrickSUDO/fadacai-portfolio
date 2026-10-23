from lib import *
rows=[]
def add(name, nav):
    n, frac, eps = dd_episodes(nav)
    m = metrics(nav)
    deepest = min(eps, key=lambda e:e["depth"]) if eps else None
    rec = [e["days"] for e in eps if e["end"] is not None]
    rows.append(f"| {name} | {m['start']} | {n} | {fmt_u(frac)} | {fmt_pct(deepest['depth']) if deepest else 'n/a'} | {int(np.median(rec)) if rec else 'n/a'} | {max(rec) if rec else 'n/a'} | {len(eps)-len(rec)} |")
    return eps
start="2010-03-12"
core = core_proxy(start=start)
E = {}
E["SMH"] = add("100% SMH", nav_from_ret(RET["SMH"].loc[start:]))
E["core"] = add("0.835×SMH 代理", nav_from_ret(core))
E["SOXL"] = add("100% SOXL", nav_from_ret(RET["SOXL"].loc[start:]))
E["TQQQ"] = add("100% TQQQ", nav_from_ret(RET["TQQQ"].loc[start:]))
E["QQQ"] = add("100% QQQ", nav_from_ret(RET["QQQ"].loc[start:]))
E["SPY"] = add("100% SPY", nav_from_ret(RET["SPY"].loc[start:]))
for lev,k,und in [("SOXL",3,"SMH"),("TQQQ",3,"QQQ"),("QLD",2,"QQQ"),("SSO",2,"SPY")]:
    c = RET[[lev,"TBILL"]].dropna().loc[start:]
    for mode,mn in [("M","月"),("B","±5pp")]:
        E[f"{lev}pair{mode}"] = add(f"{int(round(100/k))}% {lev} + T-bill（{mn}）", rebalance_nav(c, {lev:1/k, "TBILL":1-1/k}, mode=mode))
for sat in ["SOXL","TQQQ","SMH"]:
    df = pd.concat([core.rename("CORE"), RET[sat].rename("SAT")], axis=1).dropna()
    E[f"sat{sat}"] = add(f"90% 代理 + 10% {sat}（月）", rebalance_nav(df, {"CORE":0.9,"SAT":0.1}, mode="M"))
for p,inst in [(0.1,"VOO"),(0.1,"QLD"),(0.1,"SSO"),(0.2,"QLD"),(0.2,"SSO")]:
    df = pd.concat([core.rename("CORE"), RET[inst].rename("PARK")], axis=1).dropna()
    E[f"park{inst}{p}"] = add(f"{int((1-p)*100)}% 代理 + {int(p*100)}% {inst} 停泊（月）", rebalance_nav(df, {"CORE":1-p,"PARK":p}, mode="M"))
hdr="| 組合 | 起點 | 自峰 −10% 觸發次數 | 在熔斷區天數比例 | 最深一次 | 中位修復天數（跨過−10%→新高） | 最長修復天數 | 尚未修復 |\n|---|---|---|---|---|---|---|---|\n"
# behaviour of lev ETF during core breaker episodes
beh=[]
smh_nav = nav_from_ret(RET["SMH"].loc[start:]); soxl_nav = nav_from_ret(RET["SOXL"].loc[start:]); qqq_nav=nav_from_ret(RET["QQQ"].loc[start:]); tqqq_nav=nav_from_ret(RET["TQQQ"].loc[start:])
for e in E["core"]:
    s, t = e["start"], e["trough"]; en = e["end"] or smh_nav.index[-1]
    def seg(nav, a, b): return nav.loc[:b].iloc[-1]/nav.loc[:a].iloc[-1]-1
    # pre-breach peak → trough, trough → end (recovery)
    peak_date = smh_nav.loc[:s].idxmax()
    beh.append(f"| {s.date()} | {t.date()} | {en.date() if e['end'] is not None else '未修復'} | {fmt_pct(e['depth'])} | {fmt_pct(seg(smh_nav,s,t))} / {fmt_pct(seg(soxl_nav,s,t))} | {fmt_pct(seg(smh_nav,t,en))} / {fmt_pct(seg(soxl_nav,t,en))} | {fmt_pct(seg(qqq_nav,s,t))} / {fmt_pct(seg(tqqq_nav,s,t))} | {fmt_pct(seg(qqq_nav,t,en))} / {fmt_pct(seg(tqqq_nav,t,en))} |")
hdr2="| 代理組合跨 −10% 日 | 谷底 | 修復日 | 代理最深 | 跨線→谷底 SMH / SOXL | 谷底→修復 SMH / SOXL | 跨線→谷底 QQQ / TQQQ | 谷底→修復 QQQ / TQQQ |\n|---|---|---|---|---|---|---|---|\n"
open("out_t5.md","w").write("### 表5 R15 互動：自峰 −10% 熔斷（2010-03-12 起，日收盤）\n"+hdr+"\n".join(rows)+"\n\n### 表5b 代理組合熔斷期內，槓桿 ETF 的行為（跌更深、彈更快）\n"+hdr2+"\n".join(beh)+"\n")
print(open("out_t5.md").read())
