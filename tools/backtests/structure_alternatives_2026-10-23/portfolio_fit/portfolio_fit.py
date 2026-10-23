#!/usr/bin/env python3
"""portfolio_fit：把候選結構套到「帳戶板塊代理組合」P0 上。
骨架抄自 tools/backtests/options_long_short_2026-10-23/overlay_sim/part2_long_sample.py（stats / 波動目標段），
改成多資產月再平衡引擎 + LEAPS 合成 sleeve + 槓桿 ETF（實價 / 合成兩版）。
資料：prices.pkl（yfinance auto_adjust Close，2010-01→2026-10-22）。T-bill = ^IRX/100/252。
輸出：results_main.csv / results_2015.csv / results.md / yearly.csv / lev_etf_tracking.csv
"""
import os, json, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

OUT = os.path.dirname(os.path.abspath(__file__))
PX = pd.read_pickle(f"{OUT}/prices.pkl").ffill()
PX = PX[PX.index >= "2011-06-01"]
RF = (PX["^IRX"] / 100 / 252).fillna(0).clip(lower=0)          # 日 T-bill 報酬
R = PX.drop(columns=["^IRX"]).pct_change().fillna(0)
R["TBILL"] = RF
# 合成槓桿 ETF：k×標的日報酬 − (k−1)×rf（融資成本）− 費用率/252
FEES = {"SOXL": 0.0075, "USD": 0.0095, "QLD": 0.0095, "TQQQ": 0.0084}
def synth(under, k, fee):
    return k * R[under] - (k - 1) * RF - fee / 252
R["SOXL_syn"] = synth("SMH", 3, FEES["SOXL"]); R["USD_syn"] = synth("SMH", 2, FEES["USD"])
R["QLD_syn"] = synth("QQQ", 2, FEES["QLD"]); R["TQQQ_syn"] = synth("QQQ", 3, FEES["TQQQ"])

def month_ends(idx):
    return set(idx.to_series().groupby(idx.to_period("M")).last())

def run_portfolio(weights, start, end="2026-10-22", leaps=None):
    """weights: {ticker: w}（含 'TBILL'）。月底再平衡。
    leaps: dict(cap=本金權重, notional=曝險權重, carry=年化 carry 佔名目)。
    LEAPS sleeve：每月底重設本金 = cap×V，名目 = notional×V 固定一個月（像持有固定口數）；
    日損益 = 名目×(r_SMH − carry/252)；sleeve 歸零即停（最大損失 = 當月本金，deep ITM 實際會因 delta 下降而輕一點，這裡保守取滿）。"""
    idx = R.index[(R.index >= start) & (R.index <= end)]
    me = month_ends(idx)
    hold = {k: w for k, w in weights.items()}          # 當前各資產市值（起始 V=1）
    V = 1.0; hist = []
    lp = None
    if leaps:
        lp = dict(val=leaps["cap"], notional=leaps["notional"], carry=leaps["carry"])
    for t in idx:
        r = R.loc[t]
        for k in hold: hold[k] *= (1 + r[k])
        if lp:
            if lp["val"] > 0:
                lp["val"] += lp["notional"] * (r["SMH"] - lp["carry"] / 252)
                if lp["val"] <= 0: lp["val"] = 0.0; lp["notional"] = 0.0
        V = sum(hold.values()) + (lp["val"] if lp else 0.0)
        hist.append(V)
        if t in me:                                   # 月底再平衡
            hold = {k: w * V for k, w in weights.items()}
            if lp: lp = dict(val=leaps["cap"] * V, notional=leaps["notional"] * V, carry=leaps["carry"])
    eq = pd.Series(hist, index=idx); return eq / eq.iloc[0]

def vol_target(eq, target, lookback=20, hyst=0.10):
    """抄 part2 (e)：週五決定下週曝險 = min(1, target/RV20)，變動 <10pp 不動；閒置放 T-bill。"""
    r = eq.pct_change().fillna(0); rf = RF.reindex(eq.index).fillna(0)
    vol = r.rolling(lookback).std() * np.sqrt(252); raw = (target / vol).clip(upper=1.0).fillna(1.0)
    wk = raw.where(raw.index.weekday == 4).ffill().fillna(1.0); held = [1.0]
    for v in wk.iloc[1:]: held.append(v if abs(v - held[-1]) >= hyst else held[-1])
    ex = pd.Series(held, index=eq.index).shift(1).fillna(1.0)
    out = (1 + ex * r + (1 - ex) * rf).cumprod(); return out / out.iloc[0], ex

def r15_count(eq, thr=-0.10):
    dd = eq / eq.cummax() - 1; n = 0; armed = True
    for v in dd:
        if v >= 0: armed = True
        elif v <= thr and armed: n += 1; armed = False
    return n

def stats(eq):
    rf = RF.reindex(eq.index).fillna(0)
    x = eq.pct_change().dropna(); yrs = len(x) / 252
    cagr = eq.iloc[-1] ** (1 / yrs) - 1; mdd = (eq / eq.cummax() - 1).min()
    sh = ((x - rf.reindex(x.index)).mean() / x.std()) * np.sqrt(252)
    yearly = eq.resample("YE").last().pct_change().dropna()
    mo = eq.resample("ME").last().pct_change().dropna(); pf = mo[mo > 0].sum() / abs(mo[mo < 0].sum())
    def w(a, b):
        s = eq[a:b]
        return s.iloc[-1] / s.iloc[0] - 1 if len(s) > 1 else np.nan
    rf_ann = float(rf.mean() * 252); vol_ = x.std() * np.sqrt(252)
    return dict(CAGR=cagr, vol=vol_, MDD=mdd, Sharpe=sh, Sharpe_geo=(cagr - rf_ann) / vol_, y2022=w("2022-01-01", "2022-12-31"),
                worst_year=yearly.min(), worst_year_label=str(yearly.idxmin().year),
                w_0622_0728=w("2026-06-22", "2026-07-28"), w_1007_1016=w("2026-10-07", "2026-10-16"),
                PF_monthly=pf, R15_triggers=r15_count(eq), n_years=yrs)

def lev(weights, leaps=None):
    k = {"SOXL": 3, "SOXL_syn": 3, "TQQQ": 3, "TQQQ_syn": 3, "USD": 2, "USD_syn": 2, "QLD": 2, "QLD_syn": 2, "TBILL": 0}
    if weights.get("TBILL", 0) < 0: k = dict(k, TBILL=1)   # 負 T-bill = 融資借款，算進曝險
    e = sum(w * k.get(t, 1) for t, w in weights.items())
    if leaps: e += leaps["notional"]
    return e

def max_loss(weights, leaps=None):
    """理論最大損失（佔本金）：T-bill 不會歸零；其餘持倉理論可歸零；LEAPS 封頂在本金。"""
    m = sum(w for t, w in weights.items() if t != "TBILL")
    if leaps: m += leaps["cap"]
    return m


def md_table(df, floatfmt=None):
    """無 tabulate 的簡易 markdown 表。"""
    def f(v):
        if isinstance(v, float): return (f"{v:{floatfmt}}" if floatfmt else f"{v:.3f}") if pd.notna(v) else "n/a"
        return str(v)
    head = "| " + " | ".join([""] + [str(c) for c in df.columns]) + " |"
    sep = "|" + "---|" * (len(df.columns) + 1)
    body = ["| " + " | ".join([str(i)] + [f(v) for v in row]) + " |" for i, row in zip(df.index, df.values)]
    return "\n".join([head, sep] + body)

P0 = {"SMH": 0.52, "IGV": 0.33, "SPY": 0.15}
P0b = {"SMH": 0.835, "TBILL": 0.165}

def build(start):
    """回傳 {label: (weights, leaps, vt_target, note)}"""
    C = {}
    C["P0 52%SMH+33%IGV+15%SPY"] = (P0, None, None, "基準代理")
    C["P0b 83.5%SMH+16.5%T-bill"] = (P0b, None, None, "對照")
    C["參考 P0×1.36（融資rf，帳戶波動對照）"] = ({"SMH": 0.52*1.36, "IGV": 0.33*1.36, "SPY": 0.15*1.36, "TBILL": -0.36}, None, None, "參考")
    C["SMH 買抱"] = ({"SMH": 1.0}, None, None, "基準")
    C["QQQ 買抱"] = ({"QQQ": 1.0}, None, None, "基準")
    C["SPY 買抱"] = ({"SPY": 1.0}, None, None, "基準")
    C["IGV 買抱"] = ({"IGV": 1.0}, None, None, "基準")
    # S1 停泊格 10%（P0 的 15% SPY 內含 10% 停泊）
    for t in ("QQQ", "SPMO", "QLD"):
        if t == "SPMO" and start < "2015-10-12": continue
        C[f"S1 停泊10%→{t}"] = ({"SMH": 0.52, "IGV": 0.33, "SPY": 0.05, t: 0.10}, None, None, "停泊格換標的")
    C["S1 停泊10%→QLD(合成2×QQQ)"] = ({"SMH": 0.52, "IGV": 0.33, "SPY": 0.05, "QLD_syn": 0.10}, None, None, "合成")
    # S2 半導體格
    C["S2 52%SMH→17%SOXL+35%T-bill"] = ({"SOXL": 0.17, "TBILL": 0.35, "IGV": 0.33, "SPY": 0.15}, None, None, "β配對")
    C["S2 52%SMH→17%SOXL(合成3×SMH)+35%T-bill"] = ({"SOXL_syn": 0.17, "TBILL": 0.35, "IGV": 0.33, "SPY": 0.15}, None, None, "合成")
    C["S2 52%SMH→26%USD+26%T-bill"] = ({"USD": 0.26, "TBILL": 0.26, "IGV": 0.33, "SPY": 0.15}, None, None, "β配對")
    C["S2 52%SMH→26%USD(合成2×SMH)+26%T-bill"] = ({"USD_syn": 0.26, "TBILL": 0.26, "IGV": 0.33, "SPY": 0.15}, None, None, "合成")
    # S3 軟體格
    C["S3 33%IGV→16.5%QLD+16.5%T-bill"] = ({"SMH": 0.52, "QLD": 0.165, "TBILL": 0.165, "SPY": 0.15}, None, None, "β配對")
    C["S3 33%IGV→16.5%QLD(合成)+16.5%T-bill"] = ({"SMH": 0.52, "QLD_syn": 0.165, "TBILL": 0.165, "SPY": 0.15}, None, None, "合成")
    C["S3 33%IGV→33%QQQ"] = ({"SMH": 0.52, "QQQ": 0.33, "SPY": 0.15}, None, None, "換指數")
    # S4 LEAPS
    for c in (0.06, 0.09):
        C[f"S4 52%SMH→20%LEAPS(名目52%,carry{c:.0%})+32%VOO"] = ({"VOO": 0.32, "IGV": 0.33, "SPY": 0.15}, dict(cap=0.20, notional=0.52, carry=c), None, "LEAPS 合成")
        C[f"S4b 全組合 30%LEAPS(名目78%,carry{c:.0%})+70%VOO"] = ({"VOO": 0.70}, dict(cap=0.30, notional=0.78, carry=c), None, "1.5× 內嵌")
    # S5 波動目標
    for tg in (0.25, 0.30):
        C[f"S5 P0 波動目標{tg:.0%}（週調，閒置T-bill）"] = (P0, None, tg, "overlay")
    # S6 衛星 10%
    for t in ("SOXL", "TQQQ", "SOXL_syn", "TQQQ_syn"):
        C[f"S6 P0 10%→{t}（自SMH/IGV等比扣）"] = ({"SMH": 0.52 - 0.10 * 0.52 / 0.85, "IGV": 0.33 - 0.10 * 0.33 / 0.85, "SPY": 0.15, t: 0.10}, None, None, "衛星")
    # S7 動能衛星 20%（自三格等比扣）
    for t in ("SPMO", "MTUM"):
        if t == "SPMO" and start < "2015-10-12": continue
        if t == "MTUM" and start < "2013-04-18": continue
        C[f"S7 P0 20%→{t}（三格等比扣）"] = ({"SMH": 0.52 * 0.8, "IGV": 0.33 * 0.8, "SPY": 0.15 * 0.8, t: 0.20}, None, None, "動能衛星")
    # S8 疊加：S1(QQQ) + S4(20% LEAPS carry 6%) + S5(25%)
    C["S8 S1(QQQ)+S4(20%LEAPS c6%)+S5(25%)"] = ({"VOO": 0.32, "IGV": 0.33, "SPY": 0.05, "QQQ": 0.10}, dict(cap=0.20, notional=0.52, carry=0.06), 0.25, "疊加")
    C["S8b S1(QQQ)+S4(20%LEAPS c6%) 無波動目標"] = ({"VOO": 0.32, "IGV": 0.33, "SPY": 0.05, "QQQ": 0.10}, dict(cap=0.20, notional=0.52, carry=0.06), None, "疊加拆解")
    C["S9 S3(QQQ)+S5(25%)"] = ({"SMH": 0.52, "QQQ": 0.33, "SPY": 0.15}, None, 0.25, "探索組合")
    C["S9 S3(QQQ)+S5(30%)"] = ({"SMH": 0.52, "QQQ": 0.33, "SPY": 0.15}, None, 0.30, "探索組合")
    if start >= "2015-10-12":
        C["S9 S3(QQQ)+S7(SPMO 20%)"] = ({"SMH": 0.52*0.8, "QQQ": 0.33*0.8, "SPY": 0.15*0.8, "SPMO": 0.20}, None, None, "探索組合")
        C["S9 S3(QQQ)+S7(SPMO 20%)+S5(30%)"] = ({"SMH": 0.52*0.8, "QQQ": 0.33*0.8, "SPY": 0.15*0.8, "SPMO": 0.20}, None, 0.30, "探索組合")
        C["S9 S7(SPMO 20%)+S5(30%)"] = ({"SMH": 0.52*0.8, "IGV": 0.33*0.8, "SPY": 0.15*0.8, "SPMO": 0.20}, None, 0.30, "探索組合")
    return C

def run_all(start, tag):
    C = build(start); rows = {}; eqs = {}
    for label, (w, lp, vt, note) in C.items():
        eq = run_portfolio(w, start, leaps=lp)
        avg_ex = 1.0
        if vt: eq, ex = vol_target(eq, vt); avg_ex = float(ex.mean())
        s = stats(eq); s["leverage"] = lev(w, lp) * (avg_ex if vt else 1.0); s["max_loss"] = max_loss(w, lp)
        s["avg_exposure"] = avg_ex; s["note"] = note
        rows[label] = s; eqs[label] = eq
    tab = pd.DataFrame(rows).T
    base = tab.loc["P0 52%SMH+33%IGV+15%SPY"]
    tab["dCAGR_pp"] = (tab["CAGR"] - base["CAGR"]) * 100; tab["dMDD_pp"] = (tab["MDD"] - base["MDD"]) * 100
    tab["pass"] = (tab["dCAGR_pp"] >= -2.0) & (tab["dMDD_pp"] >= 5.0)
    tab.to_csv(f"{OUT}/results_{tag}.csv")
    pd.DataFrame(eqs).to_csv(f"{OUT}/equity_{tag}.csv")
    yearly = pd.DataFrame({k: e.resample("YE").last().pct_change().dropna() for k, e in eqs.items()})
    yearly.index = yearly.index.year; yearly.to_csv(f"{OUT}/yearly_{tag}.csv")
    return tab, eqs, yearly

def tracking():
    """實價槓桿 ETF vs 合成：年化報酬差、相關、β（2012→）。"""
    rows = []
    for a, s_, u, k in (("SOXL", "SOXL_syn", "SMH", 3), ("USD", "USD_syn", "SMH", 2), ("QLD", "QLD_syn", "QQQ", 2), ("TQQQ", "TQQQ_syn", "QQQ", 3)):
        x = R.loc["2012-01-01":"2026-10-22", [a, s_, u]]
        ea = (1 + x[a]).cumprod(); es = (1 + x[s_]).cumprod(); yrs = len(x) / 252
        rows.append(dict(etf=a, under=u, k=k, cagr_actual=ea.iloc[-1] ** (1 / yrs) - 1, cagr_synth=es.iloc[-1] ** (1 / yrs) - 1,
                         corr_daily=x[a].corr(x[s_]), beta_to_under=x[a].cov(x[u]) / x[u].var(), vol_actual=x[a].std() * np.sqrt(252),
                         mdd_actual=(ea / ea.cummax() - 1).min(), mdd_synth=(es / es.cummax() - 1).min()))
    t = pd.DataFrame(rows).set_index("etf"); t.to_csv(f"{OUT}/lev_etf_tracking.csv"); return t

def fmt(tab):
    cols = ["CAGR", "vol", "MDD", "Sharpe", "Sharpe_geo", "y2022", "worst_year", "worst_year_label", "w_0622_0728", "w_1007_1016", "PF_monthly", "R15_triggers", "leverage", "max_loss", "dCAGR_pp", "dMDD_pp", "pass"]
    t = tab[cols].copy()
    for c in ("CAGR", "vol", "MDD", "y2022", "worst_year", "w_0622_0728", "w_1007_1016", "max_loss"): t[c] = t[c].map(lambda v: f"{v*100:+.1f}%" if pd.notna(v) else "n/a")
    for c in ("Sharpe", "Sharpe_geo", "PF_monthly", "leverage"): t[c] = t[c].map(lambda v: f"{v:.2f}")
    for c in ("dCAGR_pp", "dMDD_pp"): t[c] = t[c].map(lambda v: f"{v:+.1f}")
    t["pass"] = t["pass"].map(lambda v: "✅" if v else "")
    t.columns = ["CAGR", "年化波動", "MDD", "Sharpe(日算術)", "Sharpe(幾何)", "2022", "最差年", "最差年份", "06/22→07/28", "10/07→10/16", "月PF", "R15次", "內嵌槓桿", "理論最大損失", "ΔCAGR pp", "ΔMDD pp", "合格"]
    return md_table(t)

def main():
    tab1, eqs1, y1 = run_all("2012-01-01", "main")
    tab2, eqs2, y2 = run_all("2015-10-12", "2015")
    trk = tracking()
    pd.set_option("display.width", 300)
    md = ["# portfolio_fit 結果（2026-10-23 產出，資料至 2026-10-22）", "",
          "資料：yfinance auto_adjust Close；T-bill = ^IRX/100/252；月底再平衡；LEAPS 合成見腳本 docstring。",
          "合格 = CAGR ≥ P0 − 2pp 且 MDD 淺 ≥ 5pp。內嵌槓桿 = Σ(權重×倍數)+LEAPS 名目（波動目標版乘平均曝險）。", "",
          "## 全樣本 2012-01-03 → 2026-10-22", "", fmt(tab1), "",
          "## 2015-10-12 → 2026-10-22（SPMO 成立後，含 S1/S7 SPMO、MTUM）", "", fmt(tab2), "",
          "## 槓桿 ETF 實價 vs 合成（k×標的 − (k−1)×rf − 費用）2012→", "", md_table(trk, '.3f'), "",
          "## 逐年報酬（全樣本，P0 與主要候選）", ""]
    pick = [c for c in y1.columns if c.startswith(("P0", "S2 52%SMH→17%SOXL+", "S3 33%IGV→33%QQQ", "S4 52%", "S5", "S6 P0 10%→SOXL（", "S8 "))]
    md.append(md_table((y1[pick] * 100).round(1), '+.1f')); md.append("")
    open(f"{OUT}/results.md", "w").write("\n".join(md))
    print("\n".join(md))

if __name__ == "__main__":
    main()
