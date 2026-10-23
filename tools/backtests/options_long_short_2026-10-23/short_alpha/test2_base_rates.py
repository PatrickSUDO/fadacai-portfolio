"""Test 2 + 3: base rates of R36/R34-type weakness signals as SHORT signals, 2015-01-01 -> 2026-10-22.
Signal judged on close of day t; entry = close of day t+1 (next trading day); exit = close k trading days after entry.
First-occurrence filter: no same-signal day in the prior 60 trading days."""
import json, pandas as pd, numpy as np
from universe import test2_universe, sector_etf
px = pd.read_csv("prices_adjclose.csv", index_col=0, parse_dates=True)
UNI = [s for s in test2_universe() if s in px.columns]
WINDOWS = (20, 40, 60)
START, END = "2015-01-01", "2026-10-22"
spy = px["SPY"]

def first_occ(sig, gap=60):
    prior = sig.shift(1).rolling(gap, min_periods=1).max().fillna(0)
    return sig & (prior == 0)

events = []
for sym in UNI:
    etf_name = sector_etf(sym)
    s = px[sym].dropna(); e = px[etf_name].reindex(s.index); sp = spy.reindex(s.index)
    if len(s) < 300: continue
    sma50 = s.rolling(50).mean(); sma200 = s.rolling(200).mean(); ema200 = s.ewm(span=200, adjust=False).mean()
    rs90 = s / s.shift(90) - 1 - (e / e.shift(90) - 1)
    rs63_spy = s / s.shift(63) - 1 - (sp / sp.shift(63) - 1)
    etf_sma200 = e.rolling(200).mean()
    sigs = {
        "S1": (rs90 <= -0.10) & (s < sma50),
        "S2": (rs90 <= -0.10) & (s < sma50) & (s < ema200),
        "S3": (rs63_spy <= -0.15) & (s < sma50) & (sma50 < sma200),
    }
    for name, sig in sigs.items():
        sig = sig.fillna(False)
        fo = first_occ(sig)
        for t in s.index[fo & (s.index >= START) & (s.index <= END)]:
            pos = s.index.get_loc(t)
            if pos + 1 >= len(s): continue
            entry = pos + 1
            rec = dict(signal=name, symbol=sym, etf=etf_name, signal_date=str(t.date()), entry_date=str(s.index[entry].date()),
                       rs90=float(rs90.iloc[pos]), rs63_spy=float(rs63_spy.iloc[pos]),
                       etf_above_200=bool(e.iloc[pos] > etf_sma200.iloc[pos]) if not np.isnan(etf_sma200.iloc[pos]) else None,
                       year=t.year)
            for k in WINDOWS:
                if entry + k < len(s):
                    a = s.iloc[entry + k] / s.iloc[entry] - 1; b = e.iloc[entry + k] / e.iloc[entry] - 1
                else:
                    a = b = np.nan
                rec[f"stock_{k}"] = a; rec[f"etf_{k}"] = b; rec[f"excess_{k}"] = a - b
            events.append(rec)
ev = pd.DataFrame(events)
ev.to_csv("test2_events.csv", index=False)

def stats(df, k):
    a, c = df[f"stock_{k}"], df[f"excess_{k}"]
    m = a.notna() & c.notna(); a, c = a[m], c[m]
    if len(a) < 3: return dict(n=int(len(a)))
    short = -c  # pair short P&L
    sh = short.mean() / short.std(ddof=1) * np.sqrt(252 / k) if short.std(ddof=1) > 0 else np.nan
    tail = c.quantile(0.95)
    return dict(n=int(len(a)), short_win=round(100 * (a < 0).mean(), 1), pair_win=round(100 * (c < 0).mean(), 1),
                mean_stock=round(100 * a.mean(), 2), mean_excess=round(100 * c.mean(), 2), median_excess=round(100 * c.median(), 2),
                skew_excess=round(float(c.skew()), 2), worst5pct_excess=round(100 * c[c >= tail].mean(), 1),
                p10_excess=round(100 * c.quantile(.1), 1), p90_excess=round(100 * c.quantile(.9), 1),
                sharpe_pair_short_ann=round(float(sh), 2),
                buy_win=round(100 * (a > 0).mean(), 1), buy_pair_win=round(100 * (c > 0).mean(), 1),
                n_symbols=int(df.loc[m, "symbol"].nunique()))

out = {"universe": UNI, "n_universe": len(UNI), "entry_rule": "signal on close t, entry close t+1, exit close t+1+k",
       "by_signal": {}, "by_regime": {}, "by_year_S1": {}, "test3": {}}
for name in ("S1", "S2", "S3"):
    g = ev[ev.signal == name]
    out["by_signal"][name] = {k: stats(g, k) for k in WINDOWS}
    out["by_regime"][name] = {}
    for reg, gg in g.groupby("etf_above_200"):
        out["by_regime"][name]["etf>SMA200" if reg else "etf<SMA200"] = {k: stats(gg, k) for k in WINDOWS}
    out["by_signal"][name]["events_per_year"] = g.groupby("year").size().to_dict()
g1 = ev[ev.signal == "S1"]
for y, gg in g1.groupby("year"):
    out["by_year_S1"][int(y)] = stats(gg, 60)
# ETF-level sub-split
out["by_etf_S1"] = {e: {k: stats(gg, k) for k in WINDOWS} for e, gg in g1.groupby("etf")}

# Test 3: weakest third by rs90 (pooled terciles across all S1 events) vs rest
q = g1["rs90"].quantile(1 / 3)
weak = g1[g1.rs90 <= q]; rest = g1[g1.rs90 > q]
out["test3"] = {"tercile_cut_rs90": round(100 * q, 1), "weakest_third": {k: stats(weak, k) for k in WINDOWS},
                "rest": {k: stats(rest, k) for k in WINDOWS}}
# also split by regime inside weakest third
out["test3"]["weakest_third_by_regime"] = {("etf>SMA200" if r else "etf<SMA200"): stats(gg, 60) for r, gg in weak.groupby("etf_above_200")}
out["test3"]["rest_by_regime"] = {("etf>SMA200" if r else "etf<SMA200"): stats(gg, 60) for r, gg in rest.groupby("etf_above_200")}
json.dump(out, open("test2_stats.json", "w"), indent=1, default=str)

L = []
L.append("| 訊號 | 窗 | 事件數 | 檔數 | 空個股勝率 | 配對勝率(空股多ETF) | 平均個股 | 平均超額 | 中位超額 | 偏態 | 最差5%超額均值 | P10/P90 超額 | 配對空方年化Sharpe | 反向買勝率/買配對勝率 |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for name in ("S1", "S2", "S3"):
    for k in WINDOWS:
        s = out["by_signal"][name][k]
        L.append(f"| {name} | {k}d | {s['n']} | {s['n_symbols']} | {s['short_win']}% | {s['pair_win']}% | {s['mean_stock']}% | {s['mean_excess']}% | {s['median_excess']}% | {s['skew_excess']} | +{s['worst5pct_excess']}% | {s['p10_excess']}% / {s['p90_excess']}% | {s['sharpe_pair_short_ann']} | {s['buy_win']}% / {s['buy_pair_win']}% |")
L.append("")
L.append("| 訊號 | regime(板塊ETF vs 200日線) | 窗 | 事件數 | 空個股勝率 | 配對勝率 | 平均超額 | 中位超額 | 最差5%超額 | 配對空方年化Sharpe |")
L.append("|---|---|---|---|---|---|---|---|---|---|")
for name in ("S1", "S2", "S3"):
    for reg, d in out["by_regime"][name].items():
        for k in WINDOWS:
            s = d[k]
            L.append(f"| {name} | {reg} | {k}d | {s['n']} | {s['short_win']}% | {s['pair_win']}% | {s['mean_excess']}% | {s['median_excess']}% | +{s['worst5pct_excess']}% | {s['sharpe_pair_short_ann']} |")
L.append("")
L.append("| S1 事件年份 | 事件數 | 空個股勝率60d | 配對勝率60d | 平均超額60d | 中位超額60d |")
L.append("|---|---|---|---|---|---|")
for y, s in out["by_year_S1"].items():
    L.append(f"| {y} | {s['n']} | {s.get('short_win','')}% | {s.get('pair_win','')}% | {s.get('mean_excess','')}% | {s.get('median_excess','')}% |")
L.append("")
L.append("| S1 按板塊ETF | 窗 | 事件數 | 空個股勝率 | 配對勝率 | 平均超額 | 中位超額 | 最差5% |")
L.append("|---|---|---|---|---|---|---|---|")
for e, d in out["by_etf_S1"].items():
    for k in WINDOWS:
        s = d[k]; L.append(f"| {e} | {k}d | {s['n']} | {s['short_win']}% | {s['pair_win']}% | {s['mean_excess']}% | {s['median_excess']}% | +{s['worst5pct_excess']}% |")
L.append("")
L.append(f"| 測試3 分組（S1，rs90 三分位切點 {out['test3']['tercile_cut_rs90']}pp） | 窗 | 事件數 | 空個股勝率 | 配對勝率 | 平均超額 | 中位超額 | 最差5%超額 | 配對空方年化Sharpe |")
L.append("|---|---|---|---|---|---|---|---|---|")
for grp in ("weakest_third", "rest"):
    for k in WINDOWS:
        s = out["test3"][grp][k]
        L.append(f"| {'最弱1/3' if grp=='weakest_third' else '其餘2/3'} | {k}d | {s['n']} | {s['short_win']}% | {s['pair_win']}% | {s['mean_excess']}% | {s['median_excess']}% | +{s['worst5pct_excess']}% | {s['sharpe_pair_short_ann']} |")
for grp in ("weakest_third_by_regime", "rest_by_regime"):
    for reg, s in out["test3"][grp].items():
        L.append(f"| {'最弱1/3' if grp.startswith('weakest') else '其餘2/3'} × {reg} | 60d | {s['n']} | {s['short_win']}% | {s['pair_win']}% | {s['mean_excess']}% | {s['median_excess']}% | +{s['worst5pct_excess']}% | {s['sharpe_pair_short_ann']} |")
open("test2_tables.md", "w").write("\n".join(L))
print("\n".join(L))
print("n universe", len(UNI), "events", len(ev), ev.groupby("signal").size().to_dict())
