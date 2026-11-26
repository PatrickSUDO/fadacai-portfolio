#!/usr/bin/env python3
"""US-B: single-index lookback L x holding H in/out matrix for SPY, QQQ, SMH.

Rule: at the close of a decision day, past-L-day total return > 0 -> hold the index
(momentum form) or hold cash (contrarian form, the exact complement); otherwise the
opposite. Cash earns the ^IRX daily rate. Trades at the next adjusted open. min(H, 21)
staggered tranches. 3 symbols x 7 L x 7 H x 2 forms = 294 cells, three cost levels.
Null: 1,000 circular shifts (offset >= 252 sessions) of the tranche position series,
at base cost, for CAGR and Calmar.

Run:  python3 -B index_ts.py [--workers 3] [--force]
Each (symbol, H) batch is cached under <out>/parts/ so the run is resumable.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etf_common as C  # noqa: E402

SHIFT_CHUNK = 40


# ------------------------------------------------------------------ decisions
def ts_decision(carry: np.ndarray, L: int) -> np.ndarray:
    """mom[t] = 1.0 if P[t]/P[t-L]-1 > 0 else 0.0 (NaN where P[t-L] does not exist).
    Uses closes <= t only."""
    T = len(carry)
    d = np.full(T, np.nan)
    if L < T:
        r = carry[L:] / carry[:T - L] - 1.0
        d[L:] = np.where(np.isfinite(r), (r > 0).astype(float), np.nan)
    return d


def live_index(bar_1d: np.ndarray, min_history: int = C.MIN_HISTORY) -> int:
    """First day with at least `min_history` bars strictly before it."""
    prior = np.cumsum(bar_1d) - bar_1d
    return int(np.flatnonzero(bar_1d & (prior >= min_history))[0])


# --------------------------------------------------------------------- engine
def run_ts(adj_open, adj_close, rf, dec, H, costs, t0, offsets=None, entry="day_one"):
    """dec: (n_cells, T) target weight (0/1) decided at each close.
    entry="day_one" (the frozen cells): every tranche takes its first decision at t0,
    then tranche k re-decides at t0+offset_k, t0+offset_k+H, ...
    entry="staggered" (labelled sensitivity only): tranche k stays in cash until its
    own first decision day t0+offset_k.  One column per (cell, cost)."""
    assert entry in ("day_one", "staggered")
    dec = np.asarray(dec, float)
    n_cells, T = dec.shape
    offs = np.array(C.tranche_offsets(H) if offsets is None else offsets)
    K = len(offs)
    nc = len(costs)
    cell_acc = np.repeat(np.arange(n_cells), nc * K)
    cost_acc = np.tile(np.repeat(np.asarray(costs, float), K), n_cells)
    off_acc = np.tile(offs, n_cells * nc)
    gid = np.repeat(np.arange(n_cells * nc), K)
    all_idx = np.arange(len(gid))

    def plan_fn(t, flat):
        if t < t0:
            return None
        if t == t0 and entry == "day_one":
            idx = all_idx
        else:
            idx = np.flatnonzero(((t - t0) % H) == off_acc)
        if not len(idx):
            return None
        return idx, dec[cell_acc[idx], t][:, None]

    ao = np.asarray(adj_open, float).reshape(T, 1)
    ac = np.asarray(adj_close, float).reshape(T, 1)
    return C.simulate(ao, ac, rf, plan_fn, cost_acc, gid, n_cells * nc)


# ------------------------------------------------- vectorised path for the null
def tranche_positions(dec_1d: np.ndarray, H: int, t0: int, offsets=None) -> np.ndarray:
    """pos[k, s] = weight tranche k holds at the close of day s, i.e. its latest
    scheduled decision taken at a close <= s-1 (0 before the first trade)."""
    T = len(dec_1d)
    offs = C.tranche_offsets(H) if offsets is None else offsets
    pos = np.zeros((len(offs), T))
    for k, off in enumerate(offs):
        mark = np.full(T, -1)
        days = np.unique(np.concatenate([[t0], np.arange(t0 + off, T, H)]))
        mark[days] = days
        src = np.maximum.accumulate(mark)
        src_prev = np.concatenate([[-1], src[:-1]])
        pos[k] = np.where(src_prev >= 0, dec_1d[np.clip(src_prev, 0, None)], 0.0)
    return pos


def leg_logs(adj_open_1d, adj_close_1d, rf):
    """log overnight, log intraday and log cash factors per day (0 for day 0)."""
    T = len(adj_close_1d)
    lon = np.zeros(T)
    lon[1:] = np.log(adj_open_1d[1:] / adj_close_1d[:-1])
    lin = np.log(adj_close_1d / adj_open_1d)
    lin[0] = 0.0
    return lon, lin, np.log1p(rf)


def fast_nav(P: np.ndarray, lon, lin, lrf, cost: float) -> np.ndarray:
    """Group NAV path for binary tranche positions.
    P: (K, S, n) positions held at the close of the n window days (S = variants).
    lon/lin/lrf: (n,) for the same days. Returns (S, n-1): NAV after each of the
    n-1 return days (V=1 at the close of the first day). Same accounting as
    etf_common.simulate: overnight on the old position (cash earns lrf), switch at
    the open paying `cost` on the whole sub-account, intraday on the new position."""
    Pp, Pn = P[..., :-1], P[..., 1:]
    lf = lrf[1:] + Pp * (lon[1:] - lrf[1:]) + Pn * lin[1:]
    if cost > 0:
        lf = lf + np.log1p(-cost) * np.abs(Pn - Pp)
    return np.exp(np.cumsum(lf, axis=-1)).mean(axis=0)


def path_stats(nav: np.ndarray, cal_days: float):
    """(cagr, calmar) for NAV paths (S, m) with V_start = 1."""
    cagr = nav[:, -1] ** (365.25 / cal_days) - 1.0
    peak = np.maximum(np.maximum.accumulate(nav, axis=1), 1.0)
    mdd = (nav / peak - 1.0).min(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        calmar = np.where(mdd < 0, cagr / np.abs(mdd), np.nan)
    return cagr, calmar


def shift_null(pos_win: np.ndarray, lon, lin, lrf, cost, cal_days, shifts):
    """Circular-shift null. pos_win: (K, n) tranche positions over the evaluation
    days. Every tranche is rolled by the same offset. Returns obs (shift 0) and null
    arrays of (cagr, calmar)."""
    K, n = pos_win.shape
    obs = path_stats(fast_nav(pos_win[:, None, :], lon, lin, lrf, cost), cal_days)
    base = np.arange(n)
    nc, nk = [], []
    for a in range(0, len(shifts), SHIFT_CHUNK):
        sh = shifts[a:a + SHIFT_CHUNK]
        idx = (base[None, :] - sh[:, None]) % n
        cg, cm = path_stats(fast_nav(pos_win[:, idx], lon, lin, lrf, cost), cal_days)
        nc.append(cg)
        nk.append(cm)
    return (float(obs[0][0]), float(obs[1][0])), np.concatenate(nc), np.concatenate(nk)


def one_sided_p(null: np.ndarray, obs: float) -> float:
    if not np.isfinite(obs):
        return 1.0
    return (1 + int(np.nansum(null >= obs - 1e-12))) / (len(null) + 1)


# ---------------------------------------------------------------------- batch
def part_paths(sym: str, H: int):
    base = os.path.join(C.PARTS_DIR, "usb_%s_H%d" % (sym, H))
    return base + ".csv", base + "_meta.json", base + "_sens.csv"


def run_batch(args):
    sym, H, force = args
    p_csv, p_meta, p_sens = part_paths(sym, H)
    if not force and all(os.path.exists(x) for x in (p_csv, p_meta, p_sens)):
        return sym, H, 0.0, "cached"
    tic = time.time()
    panel = C.build_panel()
    bench = C.bench_returns(panel)
    bounds = C.window_bounds(panel.dates)
    a = panel.col(sym)
    ao, ac = panel.adj_open[:, a], panel.adj_close[:, a]
    bar = np.isfinite(ao) & np.isfinite(ac)
    first = int(np.flatnonzero(bar)[0])
    assert bar[first:].all(), "US-B symbol has a missing bar"
    carry = C.ffill(ac)
    t0 = live_index(bar)
    T = len(carry)
    cells, dec = [], []
    for L in C.TS_L_LIST:
        m = ts_decision(carry, L)
        assert np.isfinite(m[t0:]).all()
        mm = np.nan_to_num(m, nan=0.0)
        cells.append((L, "momentum"))
        dec.append(mm)
        cells.append((L, "contrarian"))
        dec.append(np.where(np.isfinite(m), 1.0 - mm, 0.0))
    dec = np.stack(dec)
    cost_names = list(C.COSTS)
    cost_vals = [C.COSTS[k] for k in cost_names]
    nav, traded, fees, info = run_ts(ao, ac, panel.rf, dec, H, cost_vals, t0)
    ret = C.blank_before(C.nav_to_ret(nav), t0)   # not live before the first trade day
    own = C.blank_before(bench[sym], t0)          # buy-and-hold over the same days
    bench_b = dict(bench)
    bench_b["OWN"] = own
    rows_by_w = C.metric_rows(ret, panel.rf, panel.dates, bounds, bench_b, "OWN",
                              traded, fees, nav)
    own_m = {w: C.window_perf(own, panel.rf, panel.dates, *bounds[w]) for w in C.WINDOW_ORDER}

    # circular-shift null on the FULL window, base cost
    i0, i1 = bounds["FULL"]
    j0 = max(i0, t0)
    n = i1 - j0 + 1
    cal = int((panel.dates[i1] - panel.dates[j0]) / np.timedelta64(1, "D"))
    lon, lin, lrf = leg_logs(np.nan_to_num(ao, nan=1.0), np.nan_to_num(carry, nan=1.0), panel.rf)
    lon, lin, lrf = lon[j0:i1 + 1], lin[j0:i1 + 1], lrf[j0:i1 + 1]
    rng = np.random.default_rng([C.SEED, 7, C.BENCH.index(sym)])
    shifts = rng.choice(np.arange(C.MIN_SHIFT, n - C.MIN_SHIFT + 1), size=C.N_NULL_TS,
                        replace=False)
    rows = []
    nc = len(cost_names)
    max_gap = 0.0
    for ci, (L, direction) in enumerate(cells):
        pos = tranche_positions(dec[ci], H, t0)[:, j0:i1 + 1]
        (o_cagr, o_calmar), n_cagr, n_calmar = shift_null(pos, lon, lin, lrf, C.COSTS[C.BASE],
                                                          cal, shifts)
        p_cagr = one_sided_p(n_cagr, o_cagr)
        p_calmar = one_sided_p(n_calmar, o_calmar)
        gb = ci * nc + cost_names.index(C.BASE)
        max_gap = max(max_gap, abs(o_cagr - rows_by_w["FULL"][gb]["cagr"]))
        frac_in = float(pos.mean())
        for j, cn in enumerate(cost_names):
            g = ci * nc + j
            for w in C.WINDOW_ORDER:
                r = dict(rows_by_w[w][g])
                r.update(study="US-B", universe=sym, signal="ret_%d_gt0" % L, direction=direction,
                         form="ts_in_out_cash_irx", L=L, H=H, cost=cn,
                         cost_bps=C.COSTS[cn] * 1e4, n_tranches=min(H, C.MAX_TRANCHES),
                         bench_ew_name="BH_%s_same_days" % sym,
                         cell="US-B|%s|ret_%d_gt0|%s|H%d" % (sym, L, direction, H),
                         null_p_cagr=p_cagr, null_p_calmar=p_calmar,
                         null_p=max(p_cagr, p_calmar),
                         null_median_cagr=float(np.nanmedian(n_cagr)),
                         null_median_calmar=float(np.nanmedian(n_calmar)),
                         obs_fast_cagr=o_cagr, obs_fast_calmar=o_calmar,
                         frac_time_in_market=frac_in,
                         bh_cagr=own_m[w]["cagr"], bh_sharpe=own_m[w]["sharpe"],
                         bh_mdd=own_m[w]["mdd"], bh_calmar=own_m[w]["calmar"])
                rows.append(r)
    C.write_csv(p_csv, pd.DataFrame(rows))

    # ---- labelled sensitivities (never study cells, never in a pass line)
    labels = [("US-B|%s|ret_%d_gt0|%s|H%d" % (sym, L, d, H), cn) for (L, d) in cells
              for cn in cost_names]
    sargs = (panel.rf, panel.dates, bounds, bench_b, "OWN")
    sens = C.sens_rows("first_day_incl", "US-B", labels, ret, *sargs, include_first=True)
    snav, _, _, _ = run_ts(ao, ac, panel.rf, dec, H, cost_vals, t0, entry="staggered")
    sens += C.sens_rows("stag_entry", "US-B", labels, C.blank_before(C.nav_to_ret(snav), t0), *sargs)
    sens = pd.DataFrame(sens)
    for w in C.WINDOW_ORDER:                  # buy-and-hold over the same days, same convention
        mi = C.window_perf(own, panel.rf, panel.dates, *bounds[w], include_first=True)
        for variant, m in (("first_day_incl", mi), ("stag_entry", own_m[w])):
            k = (sens.window == w) & (sens.variant == variant)
            sens.loc[k, "bh_cagr"] = m["cagr"]
            sens.loc[k, "bh_mdd"] = m["mdd"]
            sens.loc[k, "bh_calmar"] = m["calmar"]
    C.write_csv(p_sens, sens)
    meta = {"symbol": sym, "H": H, "t0_signal_date": str(panel.dates[t0]),
            "first_trade_date": str(panel.dates[t0 + 1]),
            "null_window_start": str(panel.dates[j0]), "null_n_days": n,
            "shift_min": int(shifts.min()), "shift_max": int(shifts.max()),
            "n_shifts": int(len(shifts)),
            "max_abs_gap_fast_vs_engine_full_cagr": max_gap, "engine_info": info,
            "own_buy_hold": {w: {k: own_m[w][k] for k in C.METRIC_COLS} for w in C.WINDOW_ORDER},
            "seconds": round(time.time() - tic, 1)}
    C.write_json(p_meta, meta)
    return sym, H, time.time() - tic, "ran"


def main(argv):
    workers = 3
    if "--workers" in argv:
        workers = min(3, int(argv[argv.index("--workers") + 1]))
    force = "--force" in argv
    C.ensure_dirs()
    # heavy (H >= 21) batches first so the pool stays balanced
    tasks = [(s, H, force) for H in sorted(C.H_LIST, reverse=True) for s in C.BENCH]
    tic = time.time()
    if workers <= 1:
        for t in tasks:
            r = run_batch(t)
            print("US-B %s H=%d: %s %.1fs" % (r[0], r[1], r[3], r[2]), flush=True)
    else:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(workers) as pool:
            for r in pool.imap_unordered(run_batch, tasks):
                print("US-B %s H=%d: %s %.1fs" % (r[0], r[1], r[3], r[2]), flush=True)
    print("US-B done in %.1fs" % (time.time() - tic))


if __name__ == "__main__":
    main(sys.argv[1:])
