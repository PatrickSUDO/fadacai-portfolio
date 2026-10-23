#!/usr/bin/env python3
"""第三部分：Sharpe 代數。帳戶 μ=27%、σ=17.3%、rf=4%。加對沖腿 H：名目 w、年化淨成本 c（= 期望漂移 −c，假設腿本身無 α）、
與帳戶相關 ρ、腿本身波動 σ_H。  μ' = μ − w·c ；σ'² = σ² + w²σ_H² + 2wρσσ_H ；Sharpe' = (μ' − rf)/σ'。"""
import math, os, itertools, json
OUT = os.path.dirname(os.path.abspath(__file__))
MU, SIG, RF = 0.27, 0.173, 0.04
base = (MU - RF) / SIG
def sharpe(w, c, rho, sh):
    mu = MU - w * c; var = SIG**2 + (w * sh)**2 + 2 * w * rho * SIG * sh
    return (mu - RF) / math.sqrt(var), math.sqrt(var), mu
lines = [f"帳戶基準 Sharpe = (27% − 4%) / 17.3% = {base:.2f}", ""]
tabs = {}
for sh in (0.173, 0.30, 0.08):
    hdr = f"| c \\ w | ρ=−0.6 | ρ=−0.8 | ρ=−0.95 |\n|---|---|---|---|"
    rows = []
    for c, w in itertools.product((0.03, 0.053, 0.08, 0.115), (0.25, 0.5, 1.0)):
        cells = []
        for rho in (-0.6, -0.8, -0.95):
            s, v, m = sharpe(w, c, rho, sh)
            cells.append(f"**{s:.2f}**（σ' {v:.1%}）" if s > base else f"{s:.2f}（σ' {v:.1%}）")
        rows.append(f"| c={c:.1%}, w={w:.2f} | " + " | ".join(cells) + " |")
    tabs[sh] = hdr + "\n" + "\n".join(rows)
    lines += [f"### σ_H = {sh:.1%}", tabs[sh], ""]
# 盈虧平衡成本：給定 w、ρ、σ_H，Sharpe 不變所需的 c
be = {}
for sh in (0.173, 0.30, 0.08):
    for w in (0.25, 0.5, 1.0):
        for rho in (-0.6, -0.8, -0.95):
            v = math.sqrt(SIG**2 + (w * sh)**2 + 2 * w * rho * SIG * sh)
            c_be = ((MU - RF) - base * v) / w
            be[f"sH={sh:.3f},w={w},rho={rho}"] = round(c_be, 4)
open(f"{OUT}/part3_tables.md", "w").write("\n".join(lines) + "\n### 盈虧平衡成本 c*（Sharpe 剛好不變）\n" + json.dumps(be, indent=1))
print("\n".join(lines)); print(json.dumps(be, indent=1))
