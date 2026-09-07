#!/usr/bin/env python3
"""
etf_copy_strategies.py — 13F 抄單 / 國會議員抄單的實盤 ETF 代理回測（已扣費用的真錢版本）

  GURU  Global X Guru（13F 對沖基金重倉，2012-）
  GVIP  Goldman Hedge Industry VIP（13F 對沖基金前十大，2016-）
  NANC  Unusual Whales 民主黨議員交易（含 Pelosi，2023-02-）
  KRUZ  Unusual Whales 共和黨議員交易（2023-02-）

對 SPY / QQQ 各算：CAGR、日報酬回歸 β、年化 α 與 t 值、MDD。
結論（2026-09-05 首跑）：四支 α 的 t 值全 <2；GURU 14 年年化 α −2.7%；NANC 對 QQQ β 0.79、α +1.1%（t 0.4），
本質是稀釋版 QQQ。詳 README.md。

用法：python3 tools/backtests/etf_copy_strategies.py
"""
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

PROXIES = {"GURU": "13F 對沖基金重倉 (2012-)", "GVIP": "13F 對沖基金 VIP top10 (2016-)",
           "NANC": "國會民主黨(含Pelosi)交易 (2023-02-)", "KRUZ": "國會共和黨交易 (2023-02-)"}
BENCH = ["SPY", "QQQ"]


def stats(r, b):
    df = pd.concat([r, b], axis=1).dropna()
    df.columns = ["p", "b"]
    n = len(df)
    yrs = n / 252
    tr_p = (1 + df.p).prod() - 1
    tr_b = (1 + df.b).prod() - 1
    beta = np.cov(df.p, df.b)[0, 1] / df.b.var()
    alpha_d = df.p.mean() - beta * df.b.mean()
    resid = df.p - beta * df.b
    t = alpha_d / (resid.std() / np.sqrt(n))
    eq, eqb = (1 + df.p).cumprod(), (1 + df.b).cumprod()
    return dict(start=df.index[0].date(), yrs=round(yrs, 1),
                cagr=(1 + tr_p) ** (1 / yrs) - 1, cagr_b=(1 + tr_b) ** (1 / yrs) - 1,
                beta=beta, alpha=alpha_d * 252, t=t,
                mdd=(eq / eq.cummax() - 1).min(), mdd_b=(eqb / eqb.cummax() - 1).min())


def main():
    px = yf.download(list(PROXIES) + BENCH, start="2012-01-01", auto_adjust=True, progress=False)["Close"]
    ret = px.pct_change()
    for tk in PROXIES:
        for b in BENCH:
            r = stats(ret[tk], ret[b])
            print(f"{tk:5s} vs {b:4s} | {r['start']} ({r['yrs']}y) | CAGR {r['cagr']*100:6.1f}% vs {r['cagr_b']*100:6.1f}% "
                  f"| β {r['beta']:4.2f} | α/yr {r['alpha']*100:+6.1f}% (t={r['t']:+.2f}) "
                  f"| MDD {r['mdd']*100:.0f}% vs {r['mdd_b']*100:.0f}%")
    sub = ret[["NANC", "KRUZ", "SPY", "QQQ"]].dropna()
    yr = (1 + sub).groupby(sub.index.year).prod() - 1
    print("\n年度報酬 (%):")
    print((yr * 100).round(1).to_string())


if __name__ == "__main__":
    main()
