#!/usr/bin/env python3
"""US-C: overnight vs intraday vs close-to-close for SPY, QQQ, SMH.

Three equity curves per symbol:
  overnight      : buy at the close, sell at the next adjusted open, every day
  intraday       : buy at the adjusted open, sell at the same day's close, every day
  close_to_close : always hold (no trades)
Gross, and net at 1 / 2 / 5 bps per side with one round trip (two sides) per day for
the two trading legs. Break-even cost per side = the per-side cost at which the leg's
net total return over the window is exactly zero (second column: at which it only
matches always-holding). No cash interest is credited to the idle half of the day,
so overnight x intraday = close-to-close exactly (gross).

Run:  python3 -B overnight.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etf_common as C  # noqa: E402

LEGS = ["overnight", "intraday", "close_to_close"]


def leg_returns(adj_open_1d: np.ndarray, adj_close_1d: np.ndarray) -> dict:
    """Gross daily simple returns of the three legs; NaN up to and including the
    first bar. Day s: overnight = open[s]/close[s-1]-1, intraday = close[s]/open[s]-1."""
    T = len(adj_close_1d)
    on = np.full(T, np.nan)
    intr = np.full(T, np.nan)
    on[1:] = adj_open_1d[1:] / adj_close_1d[:-1] - 1.0
    intr[1:] = np.where(np.isfinite(on[1:]), adj_close_1d[1:] / adj_open_1d[1:] - 1.0, np.nan)
    cc = (1.0 + on) * (1.0 + intr) - 1.0
    return {"overnight": on, "intraday": intr, "close_to_close": cc}


def net_of_cost(gross: np.ndarray, cost: float, sides_per_day: int) -> np.ndarray:
    """Each side costs `cost` of the traded notional (the whole account)."""
    return (1.0 + gross) * (1.0 - cost) ** sides_per_day - 1.0


def breakeven_bps(growth: float, target_growth: float, n_days: int, sides_per_day: int = 2):
    """Per-side cost c (in bps) such that growth * (1-c)^(sides*n) == target_growth."""
    if not (np.isfinite(growth) and np.isfinite(target_growth)) or growth <= 0 or n_days <= 0:
        return float("nan")
    return float((1.0 - (target_growth / growth) ** (1.0 / (sides_per_day * n_days))) * 1e4)


def main():
    C.ensure_dirs()
    panel = C.build_panel()
    bench = C.bench_returns(panel)
    bounds = C.window_bounds(panel.dates)
    rows = []
    for sym in C.BENCH:
        a = panel.col(sym)
        ao, ac = panel.adj_open[:, a], panel.adj_close[:, a]
        bar = np.isfinite(ao) & np.isfinite(ac)
        first = int(np.flatnonzero(bar)[0])
        assert bar[first:].all()
        legs = leg_returns(ao, ac)
        assert np.allclose(legs["close_to_close"][first + 1:], bench[sym][first + 1:])
        own = bench[sym]
        bench_c = dict(bench)
        bench_c["OWN"] = own
        for leg in LEGS:
            sides = 0 if leg == "close_to_close" else 2
            for cn, cv in C.OVN_COSTS.items():
                net = net_of_cost(legs[leg], cv, sides)
                by_w = C.metric_rows(net[:, None], panel.rf, panel.dates, bounds, bench_c, "OWN")
                for w in C.WINDOW_ORDER:
                    i0, i1 = bounds[w]
                    j0 = C.live_start(legs[leg], i0)
                    n = i1 - j0
                    g_leg = float(np.prod(1.0 + legs[leg][j0 + 1:i1 + 1]))
                    g_cc = float(np.prod(1.0 + legs["close_to_close"][j0 + 1:i1 + 1]))
                    r = dict(by_w[w][0])
                    r.update(study="US-C", universe=sym, signal=leg, direction="long", form="leg",
                             L=np.nan, H=np.nan, cost=cn, cost_bps=cv * 1e4, n_tranches=1,
                             bench_ew_name="BH_%s_same_days" % sym,
                             cell="US-C|%s|%s" % (sym, leg),
                             turnover_ann=(sides / 2.0) * 252.0,
                             cost_drag_ann=(1.0 - (1.0 - cv) ** sides) * 252.0,
                             breakeven_bps_per_side=(breakeven_bps(g_leg, 1.0, n) if sides
                                                     else np.nan),
                             breakeven_bps_vs_hold=(breakeven_bps(g_leg, g_cc, n) if sides
                                                    else np.nan),
                             gross_mean_daily_bps=float(np.mean(legs[leg][j0 + 1:i1 + 1]) * 1e4),
                             share_positive_days=float(np.mean(legs[leg][j0 + 1:i1 + 1] > 0)))
                    rows.append(r)
    df = pd.DataFrame(rows)
    C.write_csv(os.path.join(C.PARTS_DIR, "usc.csv"), df)
    show = df[(df.window == "FULL")][["universe", "signal", "cost", "cagr", "sharpe", "mdd",
                                      "breakeven_bps_per_side"]]
    print(show.to_string(index=False))


if __name__ == "__main__":
    main()
