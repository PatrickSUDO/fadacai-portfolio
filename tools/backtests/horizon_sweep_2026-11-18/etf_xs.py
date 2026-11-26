#!/usr/bin/env python3
"""US-A: ETF cross-sectional momentum / reversal x holding horizon.

2 universes x 7 signals x 2 directions x 7 horizons = 196 cells, three cost levels,
plus a 200-draw random-3-name null per (universe, H) on the same schedule at base cost.

Run:  python3 -B etf_xs.py [--workers 3] [--force]
Each (universe, H) batch is cached under <out>/parts/ so the run is resumable.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etf_common as C  # noqa: E402


# ------------------------------------------------------------------- signals
def xs_signal(carry: np.ndarray, L: int, skip: int = 0) -> np.ndarray:
    """S[t] = P[t-skip] / P[t-L] - 1 on carried adjusted closes (info <= close t)."""
    T, A = carry.shape
    S = np.full((T, A), np.nan)
    if L < T:
        S[L:] = carry[L - skip:T - skip] / carry[:T - L] - 1.0
    return S


def build_picks(S: np.ndarray, elig: np.ndarray, direction: str, n_pick: int = C.N_PICK,
                min_names: int = C.MIN_NAMES):
    """picks[t] = column indices of the top (momentum) or bottom (reversal) n_pick
    eligible names by S[t]; valid[t] = at least `min_names` eligible names with a
    finite signal. Ties are broken by column order (stable sort), never randomly."""
    val = np.where(elig & np.isfinite(S), S, np.nan)
    key = -val if direction == "momentum" else val
    order = np.argsort(key, axis=1, kind="stable")     # NaN sorts last
    n_ok = np.isfinite(val).sum(axis=1)
    return order[:, :n_pick].copy(), n_ok >= min_names


# -------------------------------------------------------------------- engine
ENTRY_MODES = ("day_one", "staggered")


def _schedule(H, offsets, n_cells, nc):
    offs = np.array(C.tranche_offsets(H) if offsets is None else offsets)
    K = len(offs)
    cell_acc = np.repeat(np.arange(n_cells), nc * K)
    off_acc = np.tile(offs, n_cells * nc)
    gid = np.repeat(np.arange(n_cells * nc), K)
    return K, cell_acc, off_acc, gid


def run_xs(adj_open, adj_close, rf, picks, valid, H, costs, t0, offsets=None,
           entry="day_one", slot_ok=None, fee_iters=0):
    """Simulate n_cells signal portfolios x len(costs) cost levels with tranches.

    picks : (n_cells, T, n_pick) int ; valid : (T,) bool (>= MIN_NAMES eligible).
    entry="day_one" (the frozen cells): every tranche enters at t0 (traded at the
    open of t0+1), then tranche k re-forms on decision days t0+offset_k,
    t0+offset_k+H, ...
    entry="staggered" (labelled sensitivity only): tranche k stays in cash until its
    own first decision day t0+offset_k, then re-forms every H sessions.
    If the universe has fewer than MIN_NAMES eligible names at the close of t, every
    invested tranche goes to cash at the next open and re-enters as soon as the count
    recovers.
    slot_ok (diagnostics only): (n_cells, T, n_pick) bool; a pick whose slot is False
    is replaced by cash for that holding period (per-slot trend filter).
    Returns nav, traded, fees with one column per (cell, cost) in C order.
    """
    assert entry in ENTRY_MODES
    picks = np.asarray(picks)
    n_cells, T, n_pick = picks.shape
    A = adj_close.shape[1]
    nc = len(costs)
    K, cell_acc, off_acc, gid = _schedule(H, offsets, n_cells, nc)
    cost_acc = np.tile(np.repeat(np.asarray(costs, float), K), n_cells)
    all_cash_on_purpose = np.zeros(len(gid), bool)

    def plan_fn(t, flat):
        if t < t0:
            return None
        if not valid[t]:
            idx = np.flatnonzero(~flat)
            return (idx, np.zeros((len(idx), A))) if len(idx) else None
        may_enter = flat & ~all_cash_on_purpose
        if entry == "staggered":
            may_enter &= (t - t0) >= off_acc
        idx = np.flatnonzero(may_enter | (((t - t0) % H) == off_acc))
        if not len(idx):
            return None
        W = np.zeros((len(idx), A))
        rows = np.arange(len(idx))[:, None]
        if slot_ok is None:
            W[rows, picks[cell_acc[idx], t]] = 1.0 / n_pick
        else:
            W[rows, picks[cell_acc[idx], t]] = slot_ok[cell_acc[idx], t] / n_pick
            all_cash_on_purpose[idx] = W.sum(axis=1) == 0
        return idx, W

    return C.simulate(adj_open, adj_close, rf, plan_fn, cost_acc, gid, n_cells * nc,
                      fee_iters=fee_iters)


def run_xs_null(adj_open, adj_close, rf, elig, valid, H, cost, t0, n_draws, rng,
                n_pick: int = C.N_PICK, offsets=None, entry="day_one"):
    """Random-pick null: same schedule, same number of names, same cost; every
    tranche of every draw picks n_pick eligible names uniformly at random."""
    assert entry in ENTRY_MODES
    T, A = adj_close.shape
    K, _, off_acc, gid = _schedule(H, offsets, n_draws, 1)

    def plan_fn(t, flat):
        if t < t0:
            return None
        if not valid[t]:
            idx = np.flatnonzero(~flat)
            return (idx, np.zeros((len(idx), A))) if len(idx) else None
        may_enter = flat if entry == "day_one" else flat & ((t - t0) >= off_acc)
        idx = np.flatnonzero(may_enter | (((t - t0) % H) == off_acc))
        if not len(idx):
            return None
        keys = rng.random((len(idx), A))
        keys[:, ~elig[t]] = 2.0
        p = np.argpartition(keys, n_pick, axis=1)[:, :n_pick]
        W = np.zeros((len(idx), A))
        W[np.arange(len(idx))[:, None], p] = 1.0 / n_pick
        return idx, W

    return C.simulate(adj_open, adj_close, rf, plan_fn, np.full(n_draws * K, cost), gid,
                      n_draws)


# --------------------------------------------------------------------- batch
def part_paths(u: str, H: int):
    base = os.path.join(C.PARTS_DIR, "usa_%s_H%d" % (u, H))
    return base + ".csv", base + "_meta.json", base + "_ret.npz", base + "_sens.csv"


def fix_suspect_opens(panel, cols, syms, ao):
    """Copy of adj_open with each suspect open (C.SUSPECT_OPENS) replaced by the
    previous adjusted close. Sensitivity only; the frozen cells keep the raw bar."""
    carry = C.ffill(panel.adj_close[:, cols])
    out = ao.copy()
    n = 0
    for sym, d in C.SUSPECT_OPENS:
        if sym in syms:
            t = int(np.searchsorted(panel.dates, np.datetime64(d)))
            assert str(panel.dates[t]) == d
            out[t, syms.index(sym)] = carry[t - 1, syms.index(sym)]
            n += 1
    return out, n


def run_batch(args):
    u, H, force = args
    p_csv, p_meta, p_npz, p_sens = part_paths(u, H)
    if not force and all(os.path.exists(x) for x in (p_csv, p_meta, p_sens)):
        return u, H, 0.0, "cached"
    tic = time.time()
    panel = C.build_panel()
    bench = C.bench_returns(panel)
    bounds = C.window_bounds(panel.dates)
    syms = C.UNIVERSES[u]
    cols = panel.cols(syms)
    ao, ac = panel.adj_open[:, cols], panel.adj_close[:, cols]
    bar = np.isfinite(ao) & np.isfinite(ac)
    elig = C.eligibility(bar)
    carry = C.ffill(ac)
    cells, picks = [], []
    valid = None
    for name, L, skip in C.XS_SIGNALS:
        S = xs_signal(carry, L, skip)
        for direction in ("momentum", "reversal"):
            pk, v = build_picks(S, elig, direction)
            # all eligible names have a finite signal (L <= 252 <= history), so the
            # "fewer than 6 names" rule is the same for every signal
            valid = v if valid is None else valid
            assert (v == valid).all(), "validity differs between signals"
            cells.append((name, L, direction))
            picks.append(pk)
    picks = np.stack(picks)
    t0 = int(np.flatnonzero(valid)[0])
    cost_names = list(C.COSTS)
    cost_vals = [C.COSTS[k] for k in cost_names]
    nav, traded, fees, info = run_xs(ao, ac, panel.rf, picks, valid, H, cost_vals, t0)
    ret_raw = C.nav_to_ret(nav)
    # A cell is not live before its first trade day (t0+1): its metrics and every
    # benchmark comparison use the live days only (same rule as US-B). Without this the
    # MA cells would be credited with 3.5 years of T-bill returns against SPY's
    # 2000-2003 bear market.
    ret = C.blank_before(ret_raw, t0)
    ew = "EW_" + u
    rows_by_w = C.metric_rows(ret, panel.rf, panel.dates, bounds, bench, ew, traded, fees, nav)
    # superseded convention, kept as labelled comparison columns only
    rows_cash = C.metric_rows(ret_raw, panel.rf, panel.dates, bounds, bench, ew + "_incl_cash")

    # null at base cost
    rng = np.random.default_rng([C.SEED, list(C.UNIVERSES).index(u), H])
    nnav, ntr, nfee, ninfo = run_xs_null(ao, ac, panel.rf, elig, valid, H, C.COSTS[C.BASE], t0,
                                         C.N_NULL_XS, rng)
    nret = C.blank_before(C.nav_to_ret(nnav), t0)
    # diagnostic only (not part of the pass line): the same random picks at zero cost,
    # to separate "picked better names" from "traded less than a random picker"
    rng0 = np.random.default_rng([C.SEED, list(C.UNIVERSES).index(u), H])
    gnav, _, _, _ = run_xs_null(ao, ac, panel.rf, elig, valid, H, 0.0, t0, C.N_NULL_XS, rng0)
    null_gross_full = C.window_perf(C.blank_before(C.nav_to_ret(gnav), t0), panel.rf, panel.dates,
                                    *bounds["FULL"])
    null_m = {w: C.window_perf(nret, panel.rf, panel.dates, *bounds[w]) for w in C.WINDOW_ORDER}
    i0, i1 = bounds["FULL"]
    nto, ndrag = C.turnover_stats(ntr, nfee, nnav, C.live_start(nret, i0), i1)

    rows = []
    nc = len(cost_names)
    cell_name = lambda c: "US-A|%s|%s|%s|H%d" % (u, c[0], c[2], H)  # noqa: E731
    for ci, (name, L, direction) in enumerate(cells):
        gb = ci * nc + cost_names.index(C.BASE)
        obs = rows_by_w["FULL"][gb]
        p_cagr = (1 + int((null_m["FULL"]["cagr"] >= obs["cagr"]).sum())) / (C.N_NULL_XS + 1)
        p_sharpe = (1 + int((null_m["FULL"]["sharpe"] >= obs["sharpe"]).sum())) / (C.N_NULL_XS + 1)
        obs_g = rows_by_w["FULL"][ci * nc + cost_names.index(C.GROSS)]
        p_gross = (1 + int((null_gross_full["cagr"] >= obs_g["cagr"]).sum())) / (C.N_NULL_XS + 1)
        for j, cn in enumerate(cost_names):
            g = ci * nc + j
            for w in C.WINDOW_ORDER:
                r = dict(rows_by_w[w][g])
                rc = rows_cash[w][g]
                r.update(study="US-A", universe=u, signal=name, direction=direction,
                         form="xs_top3_equal_weight", L=L, H=H, cost=cn,
                         cost_bps=C.COSTS[cn] * 1e4, n_tranches=min(H, C.MAX_TRANCHES),
                         bench_ew_name=ew, cell=cell_name((name, L, direction)),
                         null_p_cagr=p_cagr, null_p_sharpe=p_sharpe,
                         null_p=max(p_cagr, p_sharpe), null_p_gross_cagr_diag=p_gross,
                         null_median_cagr=float(np.median(null_m[w]["cagr"])),
                         null_median_sharpe=float(np.median(null_m[w]["sharpe"])),
                         cagr_incl_prestart_cash=rc["cagr"],
                         excess_cagr_vs_SPY_incl_prestart_cash=rc["excess_cagr_vs_SPY"],
                         excess_cagr_vs_EW_incl_prestart_cash=rc["excess_cagr_vs_EW"])
                rows.append(r)
    C.write_csv(p_csv, pd.DataFrame(rows))
    np.savez_compressed(p_npz, ret=ret.astype(np.float32),
                        cols=np.array(["%s|%s|%s" % (c[0], c[2], cn) for c in cells
                                       for cn in cost_names]))

    # ---- labelled sensitivities (never study cells, never in a pass line)
    labels = [(cell_name(c), cn) for c in cells for cn in cost_names]
    args = (panel.rf, panel.dates, bounds, bench, ew)
    sens = C.sens_rows("first_day_incl", "US-A", labels, ret, *args, include_first=True)
    snav, _, _, _ = run_xs(ao, ac, panel.rf, picks, valid, H, cost_vals, t0, entry="staggered")
    sens += C.sens_rows("stag_entry", "US-A", labels, C.blank_before(C.nav_to_ret(snav), t0), *args)
    cnav, _, _, _ = run_xs(ac, ac, panel.rf, picks, valid, H, cost_vals, t0)
    sens += C.sens_rows("exec_t1_close", "US-A", labels, C.blank_before(C.nav_to_ret(cnav), t0), *args)
    fnav, _, _, _ = run_xs(ao, ac, panel.rf, picks, valid, H, cost_vals, t0, fee_iters=4)
    sens += C.sens_rows("exact_fee", "US-A", labels, C.blank_before(C.nav_to_ret(fnav), t0), *args)
    ao_fix, n_fix = fix_suspect_opens(panel, cols, syms, ao)
    if n_fix:
        xnav, _, _, _ = run_xs(ao_fix, ac, panel.rf, picks, valid, H, cost_vals, t0)
        sens += C.sens_rows("suspect_open_fixed", "US-A", labels,
                            C.blank_before(C.nav_to_ret(xnav), t0), *args)
    C.write_csv(p_sens, pd.DataFrame(sens))

    q = lambda a, x: float(np.quantile(a, x))  # noqa: E731
    meta = {
        "universe": u, "H": H, "n_tranches": min(H, C.MAX_TRANCHES),
        "t0_signal_date": str(panel.dates[t0]), "first_trade_date": str(panel.dates[t0 + 1]),
        "n_eligible_on_t0": int(elig[t0].sum()),
        "n_eligible_on_2000-01-03": int(elig[bounds["FULL"][0]].sum()),
        "days_below_min_names_after_t0": int((~valid[t0:]).sum()),
        "engine_info": info, "null_engine_info": ninfo,
        "null": {w: {"cagr_median": q(null_m[w]["cagr"], .5), "cagr_p05": q(null_m[w]["cagr"], .05),
                     "cagr_p95": q(null_m[w]["cagr"], .95),
                     "sharpe_median": q(null_m[w]["sharpe"], .5),
                     "sharpe_p95": q(null_m[w]["sharpe"], .95),
                     "mdd_median": q(null_m[w]["mdd"], .5),
                     "calmar_median": q(null_m[w]["calmar"], .5)} for w in C.WINDOW_ORDER},
        "null_turnover_median_full": float(np.median(nto)),
        "null_gross_cagr_median_full": float(np.median(null_gross_full["cagr"])),
        "null_cost_drag_median_full": float(np.median(ndrag)),
        "seconds": round(time.time() - tic, 1),
    }
    C.write_json(p_meta, meta)
    return u, H, time.time() - tic, "ran"


# ------------------------------------------------------- sanity-anchor diagnostics
SECTORS_11 = "XLB XLE XLF XLI XLK XLP XLU XLV XLY XLRE XLC".split()
# the earlier project's universes (fadacai-etf-rotation, configs/default.yaml)
PRIOR_U3_19 = SECTORS_11 + "SMH XBI KRE ITB".split() + "TLT IEF GLD SLV".split()
PRIOR_LOOKBACKS = (126, 189, 252)
PRIOR_SMA = 210
PRIOR_OFFSETS = [0, 7, 14]


def ensemble_picks(carry, elig, lookbacks=PRIOR_LOOKBACKS, n_pick=C.N_PICK,
                   min_names=C.MIN_NAMES):
    """The earlier project's score: mean over lookbacks of the cross-sectional rank
    (ascending, average ties) of the L-day return among eligible names; top n_pick by
    rank-mean, ties broken by the higher longest-lookback return, then column order."""
    T, A = carry.shape
    rsum = np.zeros((T, A))
    last = None
    for L in lookbacks:
        S = xs_signal(carry, L)
        val = np.where(elig & np.isfinite(S), S, np.nan)
        rsum += pd.DataFrame(val).rank(axis=1, method="average").to_numpy()
        last = val
    rm = rsum / len(lookbacks)
    order = np.lexsort((np.broadcast_to(np.arange(A), (T, A)), -last, -rm), axis=1)
    return order[:, :n_pick].copy(), np.isfinite(rm).sum(axis=1) >= min_names


def sma_above(carry, window=PRIOR_SMA):
    """above[t, a]: adjusted close of t > mean of the last `window` closes (<= t);
    False until `window` closes exist."""
    sm = pd.DataFrame(carry).rolling(window, min_periods=window).mean().to_numpy()
    with np.errstate(invalid="ignore"):
        return np.isfinite(sm) & (carry > sm)


def run_anchor():
    """Sanity-anchor diagnostics (NOT cells of the study). The earlier project's
    result (monthly ETF momentum lagged SPY by 7.3pp/yr in 2018-2025) came from a
    different rule than the pre-registered EQ / ret_252 / H=21 cell: 11 SPDR sectors,
    126/189/252 rank-mean ensemble, top 3, each slot to T-bills unless the fund is
    above its 210-session average, 3 tranches. This steps from the study cell to that
    rule one change at a time, all through this study's engine at base cost."""
    panel = C.build_panel()
    bench = C.bench_returns(panel)
    bounds = C.window_bounds(panel.dates)
    variants = [
        # key, symbols, signal, per-slot SMA filter, tranche offsets (None = 21 tranches)
        ("EQ_27", C.EQ, "ret_252", False, None),
        ("EQ_27_ensemble", C.EQ, "ens", False, None),
        ("EQ_27_ensemble_sma210", C.EQ, "ens", True, None),
        ("SECTORS_11", SECTORS_11, "ret_252", False, None),
        ("SECTORS_11_ensemble", SECTORS_11, "ens", False, None),
        ("SECTORS_11_ensemble_sma210", SECTORS_11, "ens", True, None),
        ("SECTORS_11_ensemble_sma210_3tranches", SECTORS_11, "ens", True, PRIOR_OFFSETS),
        ("PRIOR_U3_19_ensemble", PRIOR_U3_19, "ens", False, None),
        ("PRIOR_U3_19_ensemble_sma210", PRIOR_U3_19, "ens", True, None),
    ]
    out = {}
    for label, syms, sig, filt, offs in variants:
        cols = panel.cols(syms)
        ao, ac = panel.adj_open[:, cols], panel.adj_close[:, cols]
        elig = C.eligibility(np.isfinite(ao) & np.isfinite(ac))
        carry = C.ffill(ac)
        if sig == "ret_252":
            pk, valid = build_picks(xs_signal(carry, 252), elig, "momentum")
        else:
            pk, valid = ensemble_picks(carry, elig)
        t0 = int(np.flatnonzero(valid)[0])
        slot_ok = None
        if filt:
            above = sma_above(carry)
            slot_ok = np.take_along_axis(above, pk, axis=1)[None]
        nav, tr, fee, _ = run_xs(ao, ac, panel.rf, pk[None], valid, 21, [C.COSTS[C.BASE]], t0,
                                 offsets=offs, slot_ok=slot_ok)
        ret = C.blank_before(C.nav_to_ret(nav), t0)
        ew = C.equal_weight_returns(ac, elig, panel.rf)
        res = {"rule": {"n_symbols": len(syms), "signal": sig, "sma210_slot_filter": filt,
                        "tranche_offsets": offs if offs is not None else "21 tranches",
                        "H": 21, "cost": C.BASE}}
        for w in C.WINDOW_ORDER:
            m = C.window_perf(ret[:, 0], panel.rf, panel.dates, *bounds[w])
            ex, ir = C.rel_perf(ret[:, 0], bench["SPY"], panel.dates, *bounds[w])
            exw, _ = C.rel_perf(ret[:, 0], ew, panel.dates, *bounds[w])
            res[w] = {"cagr": m["cagr"], "sharpe": m["sharpe"], "mdd": m["mdd"],
                      "excess_cagr_vs_SPY": ex, "ir_vs_SPY": ir, "excess_cagr_vs_own_EW": exw}
        i0, i1 = bounds["Wc"]
        held = np.zeros(len(syms))
        for t in range(i0, i1):
            held[pk[t]] += 1
        top = sorted(zip(syms, held / held.sum()), key=lambda x: -x[1])[:6]
        res["Wc_signal_day_share_of_top3_slots"] = {k: round(float(v), 3) for k, v in top}
        if filt:
            res["Wc_share_of_slots_in_cash"] = float(1.0 - slot_ok[0, i0:i1].mean())
        out[label] = res
    C.write_json(os.path.join(C.PARTS_DIR, "usa_anchor.json"), out)
    return out


def main(argv):
    workers = 3
    if "--workers" in argv:
        workers = min(3, int(argv[argv.index("--workers") + 1]))
    force = "--force" in argv
    C.ensure_dirs()
    tasks = [(u, H, force) for u in C.UNIVERSES for H in C.H_LIST]
    tic = time.time()
    if workers <= 1:
        res = [run_batch(t) for t in tasks]
    else:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(workers) as pool:
            res = []
            for r in pool.imap_unordered(run_batch, tasks):
                print("US-A %s H=%d: %s %.1fs" % (r[0], r[1], r[3], r[2]), flush=True)
                res.append(r)
    anchor = run_anchor()
    for k, v in anchor.items():
        print("anchor %-40s Wc excess vs SPY %+.4f  FULL %+.4f" % (
            k, v["Wc"]["excess_cagr_vs_SPY"], v["FULL"]["excess_cagr_vs_SPY"]))
    print("US-A done in %.1fs" % (time.time() - tic))


if __name__ == "__main__":
    main(sys.argv[1:])
