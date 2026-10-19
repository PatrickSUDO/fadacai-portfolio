#!/usr/bin/env python3
"""backtest_vol_target.py — 「報酬差不多、回撤小很多」有沒有可能：波動目標 / 趨勢覆蓋 對 SMH、QQQ 的長期回測（2026-10-19 用戶問）

本子的曲線 ≈ SMH 曲線，所以拿 SMH/QQQ 當因子代理，測三種覆蓋（都是收盤判定、隔日執行、閒置部位放 T-bill）：
  A. 買抱
  B. 波動目標：曝險 = min(1, 目標年化波動 ÷ 20 日實現波動)，每週調一次（週五收盤），調整幅度 <10% 不動
  C. 趨勢覆蓋：收盤 > 200 日線 全倉，否則半倉
  D. B + C
指標：CAGR、最大回撤、Sharpe、最差年、年換手；另列 2022 熊市與 2026 兩次回撤各策略的表現。
Usage: python3 tools/backtest_vol_target.py [--target 20] [--start 2012-01-01]
"""
import argparse, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf

def run(px, rf_daily, target=0.20, mode="bh"):
    r = px.pct_change().fillna(0)
    vol = r.rolling(20).std() * np.sqrt(252)
    sma200 = px.rolling(200).mean()
    exp = pd.Series(1.0, index=px.index)
    if mode in ("vt", "both"):
        raw = (target / vol).clip(upper=1.0).fillna(1.0)
        # 週五收盤決定下週曝險；變動 <10% 不動（省換手）
        wk = raw.where(raw.index.weekday == 4).ffill().fillna(1.0)
        held = [1.0]
        for v in wk.iloc[1:]:
            held.append(v if abs(v - held[-1]) >= 0.10 else held[-1])
        exp = pd.Series(held, index=px.index)
    if mode in ("trend", "both"):
        tr = (px > sma200).astype(float).replace(0.0, 0.5).fillna(1.0)
        exp = exp * tr
    exp = exp.shift(1).fillna(1.0)          # 隔日生效
    strat = exp * r + (1 - exp) * rf_daily
    eq = (1 + strat).cumprod()
    turnover = exp.diff().abs().sum() / (len(px) / 252)
    return eq, exp, turnover

def stats(eq, rf_daily):
    r = eq.pct_change().dropna()
    yrs = len(r) / 252
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    mdd = (eq / eq.cummax() - 1).min()
    sharpe = ((r - rf_daily.reindex(r.index).fillna(0)).mean() / r.std()) * np.sqrt(252)
    yearly = eq.resample("YE").last().pct_change().dropna()
    return cagr, mdd, sharpe, (yearly.min() if len(yearly) else np.nan), yearly

def window(eq, a, b):
    s = eq[a:b]
    return s.iloc[-1] / s.iloc[0] - 1, (s / s.cummax() - 1).min()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--target", type=float, default=20); ap.add_argument("--start", default="2012-01-01")
    a = ap.parse_args(); target = a.target / 100
    data = yf.download(["SMH", "QQQ", "^IRX"], start=a.start, progress=False, auto_adjust=True)["Close"].ffill()
    rf = (data["^IRX"] / 100 / 252).fillna(0.0)   # 13 週 T-bill 年化 → 日
    for sym in ("SMH", "QQQ"):
        px = data[sym].dropna(); rfd = rf.reindex(px.index).fillna(0)
        print(f"\n=== {sym}  {px.index[0].date()} → {px.index[-1].date()}  波動目標 {a.target:.0f}% ===")
        print(f"{'策略':<16}{'CAGR':>8}{'最大回撤':>9}{'Sharpe':>8}{'最差年':>8}{'年換手':>7} | {'2022 熊市':>10} {'2026 6/22-7/28':>15} {'2026 10/7-10/16':>16}")
        for label, mode in (("A 買抱", "bh"), ("B 波動目標", "vt"), ("C 趨勢 200 日線", "trend"), ("D 兩者都用", "both")):
            eq, exp, to = run(px, rfd, target, mode)
            cagr, mdd, sh, wy, yearly = stats(eq, rfd)
            w22 = window(eq, "2022-01-01", "2022-12-31")[0]
            w1 = window(eq, "2026-06-22", "2026-07-28")[0]; w2 = window(eq, "2026-10-07", "2026-10-16")[0]
            print(f"{label:<16}{cagr:+8.1%}{mdd:9.1%}{sh:8.2f}{wy:+8.1%}{to:7.1f} | {w22:+10.1%} {w1:+15.1%} {w2:+16.1%}")
        eq_b, exp_b, _ = run(px, rfd, target, "vt")
        print(f"  （B 今天的曝險：{exp_b.iloc[-1]:.0%}；20 日實現波動 {px.pct_change().rolling(20).std().iloc[-1]*np.sqrt(252):.0%}）")

if __name__ == "__main__":
    main()
