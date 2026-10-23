#!/usr/bin/env python3
"""第二部分：長樣本代理（SMH 2012→2026-10-22）。骨架複製自 tools/backtest_option_overlay.py（原檔不改）。
新增：(a) 空 SPY β 對沖  (b) 多 SMH + 空成分最弱 1/5  (c) 賣權價差實價 5.3%/年  (d) 保護性 put 實價 11.5%/年  (e) 波動目標 20%。
原 A–E（BS 模型價）一併重跑。輸出 part2_results.csv。"""
import math, os, json, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from statistics import NormalDist
N = NormalDist().cdf
OUT = os.path.dirname(os.path.abspath(__file__))
START = "2012-01-01"
# SMH 近似前 25 大（今日成分，倒推 → 存活者偏差：被剔除的弱名不在裡面，對「空最弱」這條腿是不利偏差）
COMPONENTS = ["NVDA", "TSM", "AVGO", "AMD", "ASML", "TXN", "QCOM", "AMAT", "LRCX", "MU", "KLAC", "INTC", "ADI", "MRVL", "NXPI",
              "MCHP", "ON", "MPWR", "SNPS", "CDNS", "TER", "STM", "SWKS", "QRVO", "ENTG"]

def bs(S, K, T, r, sig, call=True):
    if T <= 0: return max(0.0, (S - K) if call else (K - S))
    d1 = (math.log(S / K) + (r + sig * sig / 2) * T) / (sig * math.sqrt(T)); d2 = d1 - sig * math.sqrt(T)
    return S * N(d1) - K * math.exp(-r * T) * N(d2) if call else K * math.exp(-r * T) * N(-d2) - S * N(-d1)

def implied(fn, target, lo=0.03, hi=1.5):
    for _ in range(60):
        mid = (lo + hi) / 2
        if fn(mid) < target: lo = mid
        else: hi = mid
    return (lo + hi) / 2

# ---- 原檔 run（BS 模型價）照抄 ----
def run_model(px, rf, mode, roll=63):
    r = px.pct_change().fillna(0); rv = (r.rolling(20).std() * np.sqrt(252)).fillna(0.3)
    shares = 1.0 / float(px.iloc[0]); cash = 0.0; legs = []; hist = []
    period = 21 if mode == "cc" else roll
    spec = {"put": [(0.90, False, +1)], "collar": [(0.90, False, +1), (1.10, True, -1)],
            "putspread": [(0.90, False, +1), (0.75, False, -1)], "cc": [(1.07, True, -1)], "none": []}[mode]
    for i in range(len(px)):
        S = float(px.iloc[i]); rfy = float(rf.iloc[i]) * 252
        iv = max(float(rv.iloc[i]) * 1.15 + 0.03, 0.22)
        if legs and i >= legs[0]["exp_i"]:
            for L in legs: cash += max(0.0, (S - L["K"]) if L["call"] else (L["K"] - S)) * L["qty"] * L["units"]
            legs = []
        if i > 20 and (i - 21) % period == 0 and spec:
            T = period / 252; equity = shares * S + cash
            net_prem = sum(bs(S, S * m, T, rfy, iv + (0.0 if call else 0.04), call) * qty for m, call, qty in spec)
            shares = equity / (S + net_prem); cash = 0.0
            for m, call, qty in spec: legs.append({"K": S * m, "call": call, "qty": qty, "exp_i": i + period, "units": shares})
        mtm = sum(bs(S, L["K"], max((L["exp_i"] - i) / 252, 1e-6), rfy, iv + (0.0 if L["call"] else 0.04), L["call"]) * L["qty"] * L["units"] for L in legs)
        hist.append(shares * S + cash + mtm)
    eq = pd.Series(hist, index=px.index); return eq / eq.iloc[0]

# ---- 新：固定實價成本（權利金 = prem_pct × 當時股票市值，IV 由該價反推、週期內固定）----
def run_fixed(px, rf, spec, period, prem_pct):
    shares = 1.0 / float(px.iloc[0]); cash = 0.0; legs = []; hist = []; iv_used = []
    for i in range(len(px)):
        S = float(px.iloc[i]); rfy = float(rf.iloc[i]) * 252
        if legs and i >= legs[0]["exp_i"]:
            for L in legs: cash += max(0.0, (S - L["K"]) if L["call"] else (L["K"] - S)) * L["qty"] * L["units"]
            legs = []
        if i > 20 and (i - 21) % period == 0:
            T = period / 252; equity = shares * S + cash
            iv = implied(lambda s: sum(bs(S, S * m, T, rfy, s, call) * qty for m, call, qty in spec) / S, prem_pct, 0.03, 0.9)
            iv_used.append(iv)
            shares = equity / (S * (1 + prem_pct)); cash = 0.0
            for m, call, qty in spec: legs.append({"K": S * m, "call": call, "qty": qty, "exp_i": i + period, "units": shares, "iv": iv})
        mtm = sum(bs(S, L["K"], max((L["exp_i"] - i) / 252, 1e-6), rfy, L["iv"], L["call"]) * L["qty"] * L["units"] for L in legs)
        hist.append(shares * S + cash + mtm)
    eq = pd.Series(hist, index=px.index); return eq / eq.iloc[0], float(np.median(iv_used))

def stats(eq, rf):
    x = eq.pct_change().dropna(); yrs = len(x) / 252
    cagr = eq.iloc[-1] ** (1 / yrs) - 1; mdd = (eq / eq.cummax() - 1).min()
    sh = ((x - rf.reindex(x.index).fillna(0)).mean() / x.std()) * np.sqrt(252)
    yearly = eq.resample("YE").last().pct_change().dropna()
    mo = eq.resample("ME").last().pct_change().dropna(); pf = mo[mo > 0].sum() / abs(mo[mo < 0].sum())
    w = lambda a, b: (lambda s: s.iloc[-1] / s.iloc[0] - 1)(eq[a:b])
    return dict(CAGR=cagr, MDD=mdd, Sharpe=sh, vol=x.std() * np.sqrt(252), worst_year=yearly.min(), worst_year_label=str(yearly.idxmin().year),
                y2022=w("2022-01-01", "2022-12-31"), w_0622_0728=w("2026-06-22", "2026-07-28"), w_1007_1016=w("2026-10-07", "2026-10-16"), PF_monthly=pf)

def main():
    d = yf.download(["SMH", "SPY", "^IRX"] + COMPONENTS, start="2011-01-01", end="2026-10-24", progress=False, auto_adjust=True)["Close"].ffill()
    failed = [c for c in COMPONENTS if c not in d.columns or d[c].dropna().empty]
    comps = [c for c in COMPONENTS if c not in failed]
    d = d[d.index >= pd.Timestamp("2011-06-01")]
    px_all = d["SMH"]; rf_all = (d["^IRX"] / 100 / 252).fillna(0)
    r_all = d.pct_change().fillna(0)
    # 滾動 252 日 β（SMH 對 SPY），用到 t-1
    cov = r_all["SMH"].rolling(252).cov(r_all["SPY"]); var = r_all["SPY"].rolling(252).var()
    beta = (cov / var).shift(1)
    # 最弱 1/5 成分籤（月底決定、下月持有）：63 日報酬 − SMH 63 日報酬
    rs = d[comps].pct_change(63) .sub(d["SMH"].pct_change(63), axis=0)
    month_end = d.index.to_series().groupby(d.index.to_period("M")).last()
    weak_basket = pd.Series(0.0, index=d.index); picks = {}
    for k, me in enumerate(month_end):
        row = rs.loc[me].dropna()
        if len(row) < 10: continue
        n_pick = max(1, round(len(row) / 5)); w = row.nsmallest(n_pick).index.tolist()
        nxt = month_end.iloc[k + 1] if k + 1 < len(month_end) else d.index[-1]
        msk = (d.index > me) & (d.index <= nxt)
        weak_basket[msk] = r_all.loc[msk, w].mean(axis=1); picks[str(me.date())] = w
    start = pd.Timestamp(START); idx = d.index >= start
    px = px_all[idx]; rf = rf_all[idx]; r = r_all.loc[idx, "SMH"]; rspy = r_all.loc[idx, "SPY"]; b = beta[idx].fillna(1.0); wb = weak_basket[idx]
    print(f"SMH {px.index[0].date()} → {px.index[-1].date()}；成分 {len(comps)} 檔（下載失敗 {failed}）；滾動β中位 {b.median():.2f}")
    res = {}
    eqs = {}
    for label, mode in (("A 不避險（買抱 SMH）", "none"), ("B 保護性賣權 10% 價外 季滾（BS模型價）", "put"), ("C 領口 −10%/+10%（BS）", "collar"),
                        ("D 賣權價差 −10%/−25%（BS）", "putspread"), ("E 掩護性買權 +7% 月滾（BS）", "cc")):
        eqs[label] = run_model(px, rf, mode)
    for h in (0.25, 0.5, 1.0):
        rr = r - h * b * rspy - h * b * 0.005 / 252
        eqs[f"(a) 空SPY β對沖 h={h:.2f}（滾動252日β，借券0.5%）"] = (1 + rr).cumprod()
    leg = -wb - 0.01 / 252                                       # 空腿本身：單名借券 1%/年
    eqs["(b) 空腿本身：空最弱1/5成分 等權 月換（1元名目）"] = (1 + leg).cumprod()
    for n in (0.2, 0.5):
        eqs[f"(b) 多SMH + 空最弱1/5 名目{n:.0%}"] = (1 + r + n * leg).cumprod()
    eq, iv = run_fixed(px, rf, [(0.90, False, +1), (0.75, False, -1)], 105, 0.022); eqs[f"(c) 賣權價差 −10/−25 5月滾 實價2.2%/期（隱含IV中位 {iv:.0%}）"] = eq
    eq, iv = run_fixed(px, rf, [(0.90, False, +1)], 42, 0.019); eqs[f"(d) 保護性put 10%價外 60日滾 實價1.9%/期（隱含IV中位 {iv:.0%}）"] = eq
    # (e) 波動目標 20%（抄 backtest_vol_target.run mode=vt）
    vol = r.rolling(20).std() * np.sqrt(252); raw = (0.20 / vol).clip(upper=1.0).fillna(1.0)
    wk = raw.where(raw.index.weekday == 4).ffill().fillna(1.0); held = [1.0]
    for v in wk.iloc[1:]: held.append(v if abs(v - held[-1]) >= 0.10 else held[-1])
    ex = pd.Series(held, index=px.index).shift(1).fillna(1.0)
    eqs["(e) 波動目標 20%（週調，閒置放T-bill）"] = (1 + ex * r + (1 - ex) * rf).cumprod()
    eqs["對照 SPY 買抱"] = (1 + rspy).cumprod()
    for k, e in eqs.items(): res[k] = stats(e, rf)
    tab = pd.DataFrame(res).T
    tab.to_csv(f"{OUT}/part2_results.csv")
    json.dump(dict(components=comps, failed=failed, picks_last6={k: picks[k] for k in list(picks)[-6:]}, beta_median=float(b.median())), open(f"{OUT}/part2_meta.json", "w"), ensure_ascii=False, indent=1)
    pd.set_option("display.width", 260); pd.set_option("display.max_colwidth", 60)
    print(tab.to_string(float_format=lambda x: f"{x:+.3f}"))
    print("最近 6 個月的空腿名單：", {k: picks[k] for k in list(picks)[-6:]})

if __name__ == "__main__":
    main()
