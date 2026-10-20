#!/usr/bin/env python3
"""backtest_sleeve.py — 非核心格（停泊/避險 sleeve）放什麼差多少（2026-10-20 用戶「XLE、GLD 也可以不用了，用 VOO 回測不同停泊避險方式」）

核心 = 55% SMH + 45% IGV（本子半導體/軟體比例的代理），非核心格固定權重 w、月再平衡；比：
  無 sleeve / SGOV(現金,^IRX) / GLD+XLE 各半（R25 現行） / GLD 單獨 / XLE 單獨 / VOO(SPY) / QQQ / TLT（長債）
w = 6%（現行 R25 目標）與 15%（有感的避險尺度）。指標：CAGR、最大回撤、Sharpe、2022、2026 兩次回撤、與核心的相關。
Usage: python3 tools/backtest_sleeve.py [--start 2012-01-01] [--w 6 15]
"""
import argparse, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf

def port(d, rf, weights):
    rr = d[list(weights)].pct_change().fillna(0); w = pd.Series(weights, dtype=float); vals = w.values.copy(); eq = [1.0]
    for i in range(1, len(rr)):
        vals = vals * (1 + rr.iloc[i].values)
        if rr.index[i].month != rr.index[i - 1].month: vals = vals.sum() * w.values
        eq.append(vals.sum())
    eq = pd.Series(eq, index=rr.index); x = eq.pct_change().dropna(); yrs = len(x) / 252
    win = lambda a, b: (lambda s: s.iloc[-1] / s.iloc[0] - 1)(eq[a:b])
    return dict(cagr=eq.iloc[-1] ** (1 / yrs) - 1, mdd=float((eq / eq.cummax() - 1).min()),
                sharpe=float(((x - rf.reindex(x.index).fillna(0)).mean() / x.std()) * np.sqrt(252)),
                y22=win("2022-01-01", "2022-12-31"), w1=win("2026-06-22", "2026-07-28"), w2=win("2026-10-07", "2026-10-16"))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--start", default="2012-01-01"); ap.add_argument("--w", type=float, nargs="+", default=[6, 15]); a = ap.parse_args()
    d = yf.download(["SMH", "IGV", "SPY", "QQQ", "GLD", "XLE", "TLT", "^IRX"], start=a.start, progress=False, auto_adjust=True)["Close"].ffill().dropna()
    rf = (d["^IRX"] / 100 / 252).fillna(0); d["CASH"] = (1 + rf).cumprod()
    core = {"SMH": 0.55, "IGV": 0.45}
    r = d.pct_change().dropna(); corer = (r["SMH"] * 0.55 + r["IGV"] * 0.45)
    print(f"核心 = 55% SMH + 45% IGV，{d.index[0].date()} → {d.index[-1].date()}；與核心的日相關：", {k: round(float(r[k].corr(corer)), 2) for k in ("SPY", "QQQ", "GLD", "XLE", "TLT")})
    for w in a.w:
        f = w / 100
        print(f"\n=== 非核心格 {w:.0f}% ===")
        print(f"{'放什麼':<18}{'年化':>7}{'最大回撤':>9}{'Sharpe':>8}{'2022':>8}{'6/22-7/28':>11}{'10/7-10/16':>12}")
        variants = [("無 sleeve（100% 核心）", {}), ("SGOV 現金", {"CASH": f}), ("GLD+XLE 各半（R25）", {"GLD": f / 2, "XLE": f / 2}), ("GLD 單獨", {"GLD": f}),
                    ("XLE 單獨", {"XLE": f}), ("VOO/SPY", {"SPY": f}), ("QQQ", {"QQQ": f}), ("TLT 長債", {"TLT": f})]
        for label, extra in variants:
            wts = {k: v * (1 - sum(extra.values())) for k, v in core.items()}; wts.update(extra)
            s = port(d, rf, wts)
            print(f"{label:<18}{s['cagr']:+7.1%}{s['mdd']:9.1%}{s['sharpe']:8.2f}{s['y22']:+8.1%}{s['w1']:+11.1%}{s['w2']:+12.1%}")

if __name__ == "__main__":
    main()
