#!/usr/bin/env python3
"""backtest_option_overlay.py — 選擇權覆蓋對「SMH 型本子」能幫多少（2026-10-19 用戶問）

用 Black-Scholes 近似、每季滾動（63 個交易日）、隱含波動 = max(20 日實現波動 × 1.15 + 3pp 偏斜, 22%) 的粗模型，比四種覆蓋：
  A 不避險   B 保護性賣權（10% 價外，季滾）   C 領口（買 10% 價外 put、賣 10% 價外 call）
  D 賣權價差（買 10% 價外、賣 25% 價外）   E 掩護性買權（賣 7% 價外 call，月滾）
每季開倉時付/收權利金，到期按內含價值結算（忽略提前平倉與流動性）。這是「量級」估計，不是精確回測。
Usage: python3 tools/backtest_option_overlay.py [--start 2012-01-01]
"""
import argparse, math, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from math import log, sqrt, exp
from statistics import NormalDist
N = NormalDist().cdf
def bs(S, K, T, r, sig, call=True):
    if T <= 0: return max(0.0, (S - K) if call else (K - S))
    d1 = (log(S / K) + (r + sig * sig / 2) * T) / (sig * sqrt(T)); d2 = d1 - sig * sqrt(T)
    return S * N(d1) - K * exp(-r * T) * N(d2) if call else K * exp(-r * T) * N(-d2) - S * N(-d1)

def run(px, rf, mode, roll=63):
    """名目隨淨值調整：每次換倉把全部淨值換成股票並對等張數掛腿（權利金從股數裡扣/加）。腿每日按 BS 重估。"""
    r = px.pct_change().fillna(0); rv = (r.rolling(20).std() * np.sqrt(252)).fillna(0.3)
    shares = 1.0 / float(px.iloc[0]); cash = 0.0; legs = []; hist = []
    period = 21 if mode == "cc" else roll
    spec = {"put": [(0.90, False, +1)], "collar": [(0.90, False, +1), (1.10, True, -1)],
            "putspread": [(0.90, False, +1), (0.75, False, -1)], "cc": [(1.07, True, -1)], "none": []}[mode]
    for i in range(len(px)):
        S = float(px.iloc[i]); rfy = float(rf.iloc[i]) * 252
        iv = max(float(rv.iloc[i]) * 1.15 + 0.03, 0.22)
        if legs and i >= legs[0]["exp_i"]:
            for L in legs:
                cash += max(0.0, (S - L["K"]) if L["call"] else (L["K"] - S)) * L["qty"] * L["units"]
            legs = []
        if i > 20 and (i - 21) % period == 0 and spec:
            T = period / 252
            equity = shares * S + cash
            net_prem = sum(bs(S, S * m, T, rfy, iv + (0.0 if call else 0.04), call) * qty for m, call, qty in spec)
            shares = equity / (S + net_prem); cash = 0.0        # 權利金用股數吸收（買付、賣收）
            for m, call, qty in spec:
                legs.append({"K": S * m, "call": call, "qty": qty, "exp_i": i + period, "units": shares})
        mtm = sum(bs(S, L["K"], max((L["exp_i"] - i) / 252, 1e-6), rfy, iv + (0.0 if L["call"] else 0.04), L["call"]) * L["qty"] * L["units"] for L in legs)
        hist.append(shares * S + cash + mtm)
    eq = pd.Series(hist, index=px.index)
    return eq / eq.iloc[0]


def stats(eq, rf):
    x = eq.pct_change().dropna(); yrs = len(x) / 252
    cagr = eq.iloc[-1] ** (1 / yrs) - 1; mdd = (eq / eq.cummax() - 1).min()
    sh = ((x - rf.reindex(x.index).fillna(0)).mean() / x.std()) * np.sqrt(252)
    w = lambda a, b: (lambda s: s.iloc[-1] / s.iloc[0] - 1)(eq[a:b])
    return cagr, mdd, sh, w("2022-01-01", "2022-12-31"), w("2026-06-22", "2026-07-28"), w("2026-10-07", "2026-10-16")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--start", default="2012-01-01"); a = ap.parse_args()
    d = yf.download(["SMH", "^IRX"], start=a.start, progress=False, auto_adjust=True)["Close"].ffill().dropna()
    px = d["SMH"]; rf = (d["^IRX"] / 100 / 252).fillna(0)
    print(f"SMH {px.index[0].date()} → {px.index[-1].date()}（BS 粗模型，季滾；IV = 實現波動×1.15+3pp，put 另加 4pp 偏斜）")
    print(f"{'覆蓋':<28}{'年化':>7}{'最大回撤':>9}{'Sharpe':>8}{'2022':>8}{'6/22-7/28':>11}{'10/7-10/16':>12}")
    for label, mode in (("A 不避險", "none"), ("B 保護性賣權 10% 價外", "put"), ("C 領口 −10%/+10%", "collar"), ("D 賣權價差 −10%/−25%", "putspread"), ("E 掩護性買權 +7%（月滾）", "cc")):
        eq = run(px, rf, mode); c, m, s, y22, w1, w2 = stats(eq, rf)
        print(f"{label:<28}{c:+7.1%}{m:9.1%}{s:8.2f}{y22:+8.1%}{w1:+11.1%}{w2:+12.1%}")

if __name__ == "__main__":
    main()
