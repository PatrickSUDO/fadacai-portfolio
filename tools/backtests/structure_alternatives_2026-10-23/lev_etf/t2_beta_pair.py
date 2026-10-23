from lib import *
PAIRS = [("SOXL",3,"SMH"),("SOXL",3,"SOXX"),("USD",2,"SMH"),("TQQQ",3,"QQQ"),("QLD",2,"QQQ"),("SSO",2,"SPY"),("UPRO",3,"SPY")]
MODES = [("M","每月"),("Q","每季"),("B","±5pp 門檻")]
rows=[]; summary={}
for lev,k,und in PAIRS:
    w = 1.0/k
    common = RET[[lev,und,"TBILL"]].dropna()
    bench = nav_from_ret(common[und]); bm = metrics(bench, und)
    rows.append(f"| **100% {und}**（對照，{bm['start']} 起） | — | {fmt_pct(bm['cagr'])} | {fmt_u(bm['vol'])} | {fmt_pct(bm['mdd'])} | {fmt_num(bm['sharpe'])} | — | — | 100% | {fmt_pct(bm['r2022'])} | {fmt_pct(bm['w1'])} | {fmt_pct(bm['w2'])} |")
    for mode,mname in MODES:
        nav = rebalance_nav(common, {lev:w, "TBILL":1-w}, mode=mode)
        m = metrics(nav)
        diff = nav.pct_change().dropna() - bench.pct_change().reindex(nav.index).dropna()
        te = diff.std()*np.sqrt(252)
        td = m['cagr'] - bm['cagr']
        rows.append(f"| {int(round(w*100))}% {lev} + {int(round((1-w)*100))}% T-bill | {mname}（{nav.attrs['rebalances']} 次） | {fmt_pct(m['cagr'])} | {fmt_u(m['vol'])} | {fmt_pct(m['mdd'])} | {fmt_num(m['sharpe'])} | {fmt_pct(td)} | {fmt_u(te)} | {int(round(w*100))}% | {fmt_pct(m['r2022'])} | {fmt_pct(m['w1'])} | {fmt_pct(m['w2'])} |")
        summary[(lev,und,mode)] = dict(cagr=m['cagr'], mdd=m['mdd'], sharpe=m['sharpe'], td=td, te=te, bench_cagr=bm['cagr'], bench_mdd=bm['mdd'], bench_sharpe=bm['sharpe'])
hdr = "| 組合 | 再平衡 | CAGR | 年化波動 | MDD | Sharpe | 追蹤差 (CAGR−標的) | 追蹤誤差 (日差年化) | 最大可能損失 (槓桿ETF歸零) | 2022 | 06/22→07/28 | 10/07→10/16 |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n"
open("out_t2.md","w").write("### 表2 β 配對組合：1/k 槓桿 ETF + (1−1/k) T-bill 複製 1× 標的（槓桿 ETF 成立以來）\n"+hdr+"\n".join(rows)+"\n")
import json; json.dump({f"{a}|{b}|{c}":v for (a,b,c),v in summary.items()}, open("out_t2.json","w"), indent=1, default=float)
print(open("out_t2.md").read())
