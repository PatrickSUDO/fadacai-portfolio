#!/usr/bin/env python3
"""Study ETF-C (ETF portfolio construction), 2026-11-19 overnight pre-registration.

Frozen spec: research/overnight-study-2026-11-19.md, section "第三組 ETF-C".
Run:  python -B run_etfc.py            (single process, about a minute)
Outputs (ETFC_OUT_DIR or tools/backtests/data/overnight_2026-11-19/etf/):
  synthetic_validation.csv, portfolios.csv, windows.csv, drawdowns.csv,
  sensitivity.csv, bootstrap.csv, verdict.json          (summary.md: write_summary.py)

Everything is descriptive / nomination-only. ETF prices only; no trade ledger is read.
"""
from __future__ import annotations

import math
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.optimize import brentq

import etfc_common as C
from etfc_common import IDX, INSTR

BENCH = ["SPY", "QQQ", "SMH"]
CANDIDATES = ["S1", "S2", "S3", "R1", "R2", "V1", "V2", "V3", "T1", "C1"]
TIMED = ["R2", "V1", "V2", "V3", "T1", "C1"]
KIND = {"SPY": "benchmark", "QQQ": "benchmark", "SMH": "benchmark", "B6040": "benchmark",
        "S1": "static", "S2": "static", "S3": "static", "R1": "risk_balance",
        "R2": "timed", "V1": "timed", "V2": "timed", "V3": "timed", "T1": "timed", "C1": "timed"}
S1_PARTS = {"SPY": 0.4, "QQQ": 0.4, "SMH": 0.2}
S2_PARTS = {"QQQ2X": 1 / 3, "SMH2X": 1 / 3, "MDY": 1 / 3}
S3_PARTS = {"QQQ": 1 / 3, "SMH": 1 / 3, "MDY": 1 / 3}
B6040_PARTS = {"SPY": 0.6, "IEF": 0.4}
R1_ASSETS = ["QQQ", "TLT", "GLD"]
COMPONENTS = ["QQQ2X", "SMH2X", "MDY", "TLT", "GLD", "IEF", "BIL"]


class Cell:
    def __init__(self, name, dec, W, e_daily=None, make_W=None, note=""):
        self.name, self.dec, self.W = name, np.asarray(dec, int), np.asarray(W, float)
        self.e_daily, self.make_W, self.note = e_daily, make_W, note

    @property
    def e_dec(self):
        return None if self.e_daily is None else self.e_daily[self.dec]


# ------------------------------------------------------------------ constructions
def static_cell(data, name, parts, flag=None, t0=None):
    t0 = data.i_start if t0 is None else t0
    dec = data.dec_days(t0, data.year_end if flag is None else flag)
    return Cell(name, dec, C.static_w(parts, len(dec)))


def r1_daily_weights(data, L=252):
    """(T, A) inverse-volatility weights of QQQ / TLT / GLD from the last L daily
    close-to-close returns; NaN rows until all three have L returns."""
    cols = [IDX[s] for s in R1_ASSETS]
    vol = C.roll_vol(data.ret[:, cols], L)
    inv = 1.0 / vol
    w = inv / inv.sum(axis=1, keepdims=True)
    out = np.zeros((data.T, len(INSTR)))
    out[:, cols] = w
    out[~np.isfinite(w).all(axis=1)] = np.nan
    return out


def cell_R1(data, L=252, flag=None, name="R1"):
    flag = data.month_end if flag is None else flag
    wd = r1_daily_weights(data, L)
    t0 = C.first_finite(wd, data.i_start)
    dec = data.dec_days(t0, flag)
    return Cell(name, dec, wd[dec])


def exposure_series(base_ret, target, L):
    """clip(target / annualised std of the last L daily base returns, 0, 2)."""
    vol = C.roll_vol(base_ret, L)
    with np.errstate(divide="ignore", invalid="ignore"):
        e = np.clip(target / vol, 0.0, 2.0)
    return e


def timed_cell(data, name, e_daily, wb_fn, flag, t0_min, mix=None):
    """Generic exposure-timed cell. wb_fn(dec) -> (D, A) base weights at the decision
    days. mix = (share, other_W_fn) blends share x overlay + (1-share) x other."""
    t0 = C.first_finite(e_daily, t0_min)
    dec = data.dec_days(t0, flag)
    wb = wb_fn(dec)
    assert np.isfinite(wb).all()
    if mix is None:
        make_W = lambda E: C.overlay(wb, E)
    else:
        share, other = mix
        ow = other(dec)
        assert np.isfinite(ow).all()
        make_W = lambda E: share * C.overlay(wb, E) + (1.0 - share) * (ow if np.ndim(E) == 1 else ow[None])
    return Cell(name, dec, make_W(e_daily[dec]), e_daily=e_daily, make_W=make_W)


def s1_warm(data):
    """S1 run from the last session of 2003 (gross): its realised returns and drifted
    close weights are the inputs of V3. From 2005 on it is the same portfolio as S1."""
    t_w = data.idx_of("2003-12-31", "right")
    dec = data.dec_days(t_w, data.year_end)
    sim = C.simulate(data, dec, C.static_w(S1_PARTS, len(dec)), 0.0, record_w=True)
    return sim["ret"][:, 0], sim["w_close"]


def build_cells(data, target_shift=0.0, vol_L=63, r1_L=252, sma_L=200, weekly=False):
    """The frozen constructions (defaults) or one sensitivity variant."""
    flag = data.week_end if weekly else data.month_end
    i0 = data.i_start
    cells = {}
    cells["S1"] = static_cell(data, "S1", S1_PARTS)
    cells["S2"] = static_cell(data, "S2", S2_PARTS)
    cells["S3"] = static_cell(data, "S3", S3_PARTS)
    cells["B6040"] = static_cell(data, "B6040", B6040_PARTS)

    # R1: inverse-vol QQQ / TLT / GLD
    r1 = cell_R1(data, r1_L, flag)
    cells["R1"] = r1
    r1_wd = r1_daily_weights(data, r1_L)
    r1_gross = C.simulate(data, r1.dec, r1.W, 0.0)["ret"][:, 0]

    # R2: R1 x min(2, 15% / realised vol of R1 over the last vol_L sessions)
    e = exposure_series(r1_gross, 0.15 + target_shift, vol_L)
    cells["R2"] = timed_cell(data, "R2", e, lambda dec: r1_wd[dec], flag, i0)

    # V1 / V2: single ETF, clip(target / vol, 0, 2)
    one = lambda s: (lambda dec: C.static_w({s: 1.0}, len(dec)))
    e_v1 = exposure_series(data.ret[:, IDX["QQQ"]], 0.18 + target_shift, vol_L)
    cells["V1"] = timed_cell(data, "V1", e_v1, one("QQQ"), flag, i0)
    e_v2 = exposure_series(data.ret[:, IDX["SPY"]], 0.15 + target_shift, vol_L)
    cells["V2"] = timed_cell(data, "V2", e_v2, one("SPY"), flag, i0)

    # V3: S1 as a whole at 18%
    s1_ret, s1_w = s1_warm(data)
    tgt = C.static_w(S1_PARTS, 1)[0]

    def s1_wb(dec):
        w = s1_w[dec].copy()
        w[data.year_end[dec]] = tgt          # S1 itself resets at that close
        return w
    e_v3 = exposure_series(s1_ret, 0.18 + target_shift, vol_L)
    cells["V3"] = timed_cell(data, "V3", e_v3, s1_wb, flag, i0)

    # T1: 2x QQQ above the sma_L-day average of QQQ (adjusted closes), else BIL
    px = pd.Series(data.adj_close[:, IDX["QQQ"]])
    sma = px.rolling(sma_L, min_periods=sma_L).mean().to_numpy()
    e_t1 = np.where(np.isfinite(sma), np.where(px.to_numpy() > sma, 2.0, 0.0), np.nan)
    cells["T1"] = timed_cell(data, "T1", e_t1, one("QQQ"), flag, i0)

    # C1: 70% V1 + 30% R1, target mix reset at every adjustment
    cells["C1"] = timed_cell(data, "C1", e_v1, one("QQQ"), flag, int(r1.dec[0]),
                             mix=(0.7, lambda dec: r1_wd[dec]))
    return cells


SENS_VARIANTS = {
    "target_minus_3pp": dict(target_shift=-0.03),
    "target_plus_3pp": dict(target_shift=+0.03),
    "lookback_21": dict(vol_L=21),
    "lookback_126": dict(vol_L=126),
    "weekly": dict(weekly=True),
    # lookback variants of the two cells whose only lookback is not the 63-day one
    "R1_lookback_21": dict(r1_L=21),
    "R1_lookback_126": dict(r1_L=126),
    "T1_lookback_21": dict(sma_L=21),
    "T1_lookback_126": dict(sma_L=126),
}
SENS_OF = {
    "R1": ["R1_lookback_21", "R1_lookback_126", "weekly"],
    "R2": ["target_minus_3pp", "target_plus_3pp", "lookback_21", "lookback_126", "weekly"],
    "V1": ["target_minus_3pp", "target_plus_3pp", "lookback_21", "lookback_126", "weekly"],
    "V2": ["target_minus_3pp", "target_plus_3pp", "lookback_21", "lookback_126", "weekly"],
    "V3": ["target_minus_3pp", "target_plus_3pp", "lookback_21", "lookback_126", "weekly"],
    "T1": ["T1_lookback_21", "T1_lookback_126", "weekly"],
    "C1": ["target_minus_3pp", "target_plus_3pp", "lookback_21", "lookback_126", "weekly"],
}
SENS_NARROW = {"R1": ["weekly"], "T1": ["weekly"]}     # narrow reading, reported as well


INTERPRETATION_CHOICES = [
    "Windows: every session dated inside the window counts; V=1 at the close of the last session before the window (the close of 2005-01-03 for Wa and FULL).",
    "Entry: first decision at the close of 2005-01-03, traded at the open of 2005-01-04; cash before. No tranches (this group has no holding horizon).",
    "Benchmarks SPY / QQQ / SMH: close-to-close buy and hold, no cost. 60/40: annual rebalance through the engine, with costs.",
    "R1 goes live when QQQ, TLT and GLD all have 252 daily returns (2005-11-17); R2 when R1 itself has 63 daily returns (2006-02-21); C1 with R1. All comparisons use the portfolio's own live days.",
    "Monthly = decision at the last session of the calendar month, trade at the next open; annual = last session of the year; weekly = last session of the ISO week.",
    "No no-trade band: every adjustment trades fully to target.",
    "Cost per side (5 bp, stress 10 bp) on all traded notional, including BIL legs, 1x<->2x swaps and the initial purchase; fee solved to its self-financing fixed point.",
    "Volatility = std (ddof 1) of the last 63 close-to-close daily returns x sqrt(252), adjusted closes. The 200-day average uses adjusted closes.",
    "R2 / V3 portfolio volatility = realised volatility of the base portfolio's own simulated (gross) daily returns. R2 weights = R1 target weights at that date; V3 weights = S1's drifted weights (40/40/20 at the year-end decision).",
    "Exposure e > 1: per asset (e-1) in the synthetic 2x twin and (2-e) in the 1x ETF; e <= 1: e in 1x and 1-e in BIL. No margin. Synthetic 2x SPY / QQQ / SMH / TLT / GLD use the spec formula; only 3x QQQ can be validated.",
    "Synthetic open = previous synthetic close x (1 + L x underlying overnight return); the day's financing and fee are charged at the close. T-bill rate = last 13-week value dated strictly before the day, / 252.",
    "BIL before 2007-05-31 = 13-week T-bill rate / 252 accrued overnight. Cash-excess Sharpe uses the same rate.",
    "C1: at every monthly adjustment the target is 0.7 x V1 target + 0.3 x R1 target.",
    "Control test: only the daily exposure series is rolled (offset between 252 and n-252 sessions, 1,000 distinct offsets, inside the live period); base weights, decision days and costs unchanged; p = max(one-sided p of CAGR, one-sided p of Calmar); BH over the six timed cells. For C1 only V1's exposure is rolled. The spec does not name the statistic; single-metric q-values are reported for information.",
    "Sensitivity, one change at a time, base cost: target +-3pp and weekly as written; 'lookback 21/126' replaces the 63-day volatility lookback for R2 / V1 / V2 / V3 / C1, the 252-day lookback for R1 and the 200-day average for T1; R1's weights inside R2 and C1 stay at 252 days. S1 / S2 / S3 have no variant: line 5 is not applicable (not counted as a pass).",
    "Lines 1-3 compare with SPY on the same days; line 4 = lines 1-3 recomputed at 10 bp.",
    "Bootstrap: paired circular block, 63-session blocks, 2,000 draws, percentile interval; CAGR geometric with 252 sessions a year.",
    "Drawdown episodes: fixed spans 2007-10-09..2009-03-09, 2020-02-19..2020-03-23, 2021-11-19..2022-12-28; span return and deepest drawdown inside the span. Worst year = calendar years in which the portfolio was live all year.",
    "Monthly investing: one unit at the first open of each month bought at target weights (new money is not used to rebalance), whole account reset at the first open of each year; S3 / SPY / QQQ rows with the same cash flows are added as references.",
    "Single-instrument reference rows (synthetic 2x QQQ, synthetic 2x SMH, MDY, TLT, GLD, IEF, BIL) are context only, not candidates.",
]


# ---------------------------------------------------------------------- evaluation
def bench_series(data):
    """Close-to-close buy-and-hold returns of SPY / QQQ / SMH, no cost, V=1 at the
    close of the simulation start."""
    out = {}
    for s in BENCH:
        r = data.ret[:, IDX[s]].copy()
        r[:data.i_start + 1] = np.nan
        out[s] = r
    return out


def year_table(data, ret, v1):
    rows = []
    for y in range(2005, 2026):
        i1 = int(np.flatnonzero(data.years == y)[-1])
        j0 = data.i_start if y == 2005 else int(np.flatnonzero(data.years == y - 1)[-1])
        if v1 > j0:
            continue
        rows.append((y, float(np.prod(1.0 + ret[j0 + 1:i1 + 1]) - 1.0)))
    return rows


def full_metrics(data, ret, v1, bench):
    """Full-period metrics plus same-day comparisons with the three benchmark ETFs."""
    j0, i1 = C.window_slice(data, v1, "FULL")
    m = C.slice_perf(data, ret, j0, i1)
    yrs = year_table(data, ret, v1)
    wy = min(yrs, key=lambda x: x[1])
    m.update(worst_year=wy[0], worst_year_ret=wy[1], n_full_years=len(yrs))
    for b in BENCH:
        bm = C.slice_perf(data, bench[b], j0, i1)
        d = ret[j0 + 1:i1 + 1] - bench[b][j0 + 1:i1 + 1]
        m["te_vs_" + b] = float(d.std(ddof=1) * math.sqrt(252))
        for k in ("cagr", "sharpe", "sharpe_ex", "mdd", "calmar"):
            m[b.lower() + "_" + k + "_same"] = bm[k]
        m["cagr_minus_" + b.lower()] = m["cagr"] - bm["cagr"]
        m["sharpe_minus_" + b.lower()] = m["sharpe"] - bm["sharpe"]
    return m


def window_rows(data, name, cost, ret, v1, bench):
    rows = []
    for w in C.WINDOW_ORDER:
        sl = C.window_slice(data, v1, w)
        if sl is None:
            continue
        m = C.slice_perf(data, ret, *sl)
        row = {"portfolio": name, "cost": cost, "window_type": "window", "window": w, **m}
        for b in BENCH:
            bm = C.slice_perf(data, bench[b], *sl)
            row[b.lower() + "_cagr_same"] = bm["cagr"]
            row[b.lower() + "_mdd_same"] = bm["mdd"]
            row[b.lower() + "_calmar_same"] = bm["calmar"]
            row["cagr_minus_" + b.lower()] = m["cagr"] - bm["cagr"]
        rows.append(row)
    for y, r in year_table(data, ret, v1):
        j0 = data.i_start if y == 2005 else int(np.flatnonzero(data.years == y - 1)[-1])
        i1 = int(np.flatnonzero(data.years == y)[-1])
        row = {"portfolio": name, "cost": cost, "window_type": "year", "window": "Y%d" % y,
               "n_days": i1 - j0, "start_date": str(data.dates[j0]), "end_date": str(data.dates[i1]),
               "total_return": r}
        for b in BENCH:
            row[b.lower() + "_total_return_same"] = float(np.prod(1.0 + bench[b][j0 + 1:i1 + 1]) - 1.0)
        rows.append(row)
    return rows


def lines_123(data, ret, v1, spy):
    """Pass lines 1-3 against SPY on the portfolio's own live days."""
    j0, i1 = C.window_slice(data, v1, "FULL")
    m, s = C.slice_perf(data, ret, j0, i1), C.slice_perf(data, spy, j0, i1)
    l1 = bool(m["cagr"] >= s["cagr"] and m["calmar"] > s["calmar"])
    gaps = {}
    for w in C.SUB_WINDOWS:
        sl = C.window_slice(data, v1, w)
        gaps[w] = C.slice_perf(data, ret, *sl)["cagr"] - C.slice_perf(data, spy, *sl)["cagr"]
    l2 = bool(all(g >= -0.02 for g in gaps.values()))
    l3 = bool(m["mdd"] >= s["mdd"] - 0.05)
    return {"line1": l1, "line1_cagr_ok": bool(m["cagr"] >= s["cagr"]),
            "line1_calmar_ok": bool(m["calmar"] > s["calmar"]), "line2": l2, "line3": l3,
            "window_cagr_gap_vs_spy": gaps, "mdd_gap_vs_spy": m["mdd"] - s["mdd"],
            "calmar": m["calmar"], "spy_calmar_same": s["calmar"]}


def drawdown_rows(data, name, ret, v1):
    rows = []
    for ep, (a, b) in C.EPISODES.items():
        ia, ib = data.idx_of(a), data.idx_of(b, "right")
        row = {"portfolio": name, "episode": ep, "span_start": a, "span_end": b}
        if v1 <= ia:
            v = np.concatenate([[1.0], np.cumprod(1.0 + ret[ia + 1:ib + 1])])
            dd = v / np.maximum.accumulate(v) - 1.0
            k = int(np.argmin(dd))
            row.update(span_return=float(v[-1] - 1.0), mdd_in_span=float(dd[k]),
                       trough_date=str(data.dates[ia + k]))
        rows.append(row)
    j0, i1 = C.window_slice(data, v1, "FULL")
    d = C.dd_detail(data, ret, j0, i1)
    rows.append({"portfolio": name, "episode": "FULL_MDD", "span_start": str(data.dates[j0]),
                 "span_end": str(data.dates[i1]), "mdd_in_span": d["mdd"],
                 "peak_date": d["peak_date"], "trough_date": d["trough_date"],
                 "recovery_date": d["recovery_date"],
                 "sessions_peak_to_recovery": d["sessions_peak_to_recovery"]})
    return rows


def null_test(data, cell, obs_ret, cost, seed):
    """Circular-shift control: the daily exposure series is rolled by a random offset
    (>= MIN_SHIFT sessions from either end) inside the live period; base weights,
    decision days and costs are unchanged. One-sided p for CAGR and for Calmar;
    the reported p is the larger of the two."""
    t0 = int(cell.dec[0])
    n = data.T - t0
    e = cell.e_daily
    assert np.isfinite(e[t0:]).all()
    rng = np.random.default_rng(seed)
    shifts = rng.choice(np.arange(C.MIN_SHIFT, n - C.MIN_SHIFT + 1), size=C.N_NULL, replace=False)
    pos = t0 + ((cell.dec[None, :] - t0 + shifts[:, None]) % n)
    sim = C.simulate(data, cell.dec, cell.make_W(e[pos]), cost)
    j0, i1 = C.window_slice(data, t0, "FULL")
    cal = int((data.dates[i1] - data.dates[j0]) / np.timedelta64(1, "D"))
    nul = C.perf(sim["ret"][j0 + 1:i1 + 1], data.rf[j0 + 1:i1 + 1], cal)
    obs = C.perf(obs_ret[j0 + 1:i1 + 1], data.rf[j0 + 1:i1 + 1], cal)
    p = lambda k: (1 + int(np.sum(nul[k] >= obs[k] - 1e-12))) / (C.N_NULL + 1)
    return {"null_p_cagr": p("cagr"), "null_p_calmar": p("calmar"),
            "null_p": max(p("cagr"), p("calmar")), "null_p_sharpe_info": p("sharpe"),
            "null_p_mdd_info": p("mdd"),
            "null_median_cagr": float(np.median(nul["cagr"])),
            "null_median_calmar": float(np.median(nul["calmar"])),
            "null_median_sharpe": float(np.median(nul["sharpe"])),
            "null_median_mdd": float(np.median(nul["mdd"])),
            "obs_cagr": obs["cagr"], "obs_calmar": obs["calmar"], "obs_sharpe": obs["sharpe"],
            "obs_mdd": obs["mdd"], "n_shifts": int(len(shifts)), "shift_min": int(shifts.min()),
            "shift_max": int(shifts.max()), "null_n_days": int(n)}


# ------------------------------------------------------------ synthetic validation
def synthetic_validation(data):
    """Synthetic 3x QQQ (spec formula) against real TQQQ, close to close."""
    q = IDX["QQQ"]
    on3, intr3, cc3 = C.synth_factors(data.on[:, q], data.cc[:, q], data.irx_ann, 3.0)
    real = data.tqqq_cc - 1.0
    syn = cc3 - 1.0
    ok = np.isfinite(real)
    first = int(np.flatnonzero(ok)[0])
    rows = []

    def one(label, a, b):
        ia = max(data.idx_of(a), first)            # first return day
        ib = data.idx_of(b, "right")
        r, s = real[ia:ib + 1], syn[ia:ib + 1]
        cal = int((data.dates[ib] - data.dates[ia - 1]) / np.timedelta64(1, "D"))
        pr, ps = C.perf(r, data.rf[ia:ib + 1], cal), C.perf(s, data.rf[ia:ib + 1], cal)
        d = s - r
        slope = float(np.cov(r, s)[0, 1] / np.var(s, ddof=1))
        rows.append({"period": label, "start_date": str(data.dates[ia - 1]),
                     "end_date": str(data.dates[ib]), "n_days": int(len(r)),
                     "cagr_real_tqqq": pr["cagr"], "cagr_synth_3x": ps["cagr"],
                     "cagr_gap_synth_minus_real": ps["cagr"] - pr["cagr"],
                     "tracking_error_ann": float(d.std(ddof=1) * math.sqrt(252)),
                     "mean_daily_diff_bp": float(d.mean() * 1e4),
                     "corr": float(np.corrcoef(r, s)[0, 1]), "slope_real_on_synth": slope,
                     "vol_real": pr["vol"], "vol_synth": ps["vol"],
                     "mdd_real": pr["mdd"], "mdd_synth": ps["mdd"],
                     "total_return_real": pr["total_return"], "total_return_synth": ps["total_return"]})
    one("FULL_2010-02-11_2025", "2010-02-12", "2025-12-31")
    one("2010-2012", "2010-02-12", "2012-12-31")
    one("Wb_2013-2019", "2013-01-02", "2019-12-31")
    one("Wc_2020-2025", "2020-01-02", "2025-12-31")
    for y in range(2011, 2026):
        one("Y%d" % y, "%d-01-01" % y, "%d-12-31" % y)
    df = pd.DataFrame(rows)
    # overnight leg (the split used for trading at the open)
    d_on = (on3 - data.tqqq_on)[first:]
    extra = {"overnight_leg_te_ann": float(np.nanstd(d_on, ddof=1) * math.sqrt(252)),
             "overnight_leg_mean_diff_bp": float(np.nanmean(d_on) * 1e4),
             "max_abs_daily_diff": float(np.nanmax(np.abs(syn[first:] - real[first:]))),
             "max_abs_daily_diff_date": str(data.dates[first + int(np.nanargmax(np.abs(syn[first:] - real[first:])))])}
    return df, extra


# ---------------------------------------------------------------- monthly investing
def dca(data, parts, cost):
    """One unit of new money at the first open of every month (first: the open after
    the simulation start), split by the target weights; all holdings are reset to the
    target weights at the first open of every year. Returns money-weighted results."""
    cols = np.array([IDX[s] for s in parts])
    w = np.array([parts[s] for s in parts], float)
    i0, T = data.i_start, data.T
    h = np.zeros(len(cols))
    paid, v_prev = 0.0, 0.0
    flows, twr, worst = [], [], (0.0, "")
    for s in range(i0 + 1, T):
        if h.sum() > 0:
            h = h * data.on[s, cols]
        v_open = h.sum()
        cf = 0.0
        if data.month_end[s - 1] or s - 1 == i0:
            cf = 1.0
            if data.year_end[s - 1] and v_open > 0:
                fee = 0.0
                for _ in range(4):
                    fee = cost * np.abs(w * (v_open + cf - fee) - h).sum()
                h = w * (v_open + cf - fee)
            else:
                h = h + w * cf * (1.0 - cost)
            paid += cf
            flows.append((s, cf))
        h = h * data.intr[s, cols]
        v = h.sum()
        twr.append((v / (v_open + cf)) * ((v_open / v_prev) if v_prev > 0 else 1.0) - 1.0)
        v_prev = v
        if v / paid - 1.0 < worst[0]:
            worst = (v / paid - 1.0, str(data.dates[s]))
    end = data.dates[T - 1]
    yrs = np.array([float((end - data.dates[s]) / np.timedelta64(1, "D")) / 365.25 for s, _ in flows])
    amt = np.array([c for _, c in flows])
    irr = brentq(lambda r: (amt * (1.0 + r) ** yrs).sum() - v_prev, -0.95, 3.0)
    twr = np.array(twr)
    cal = int((end - data.dates[i0]) / np.timedelta64(1, "D"))
    pm = C.perf(twr, data.rf[i0 + 1:], cal)
    return {"dca_irr": float(irr), "dca_multiple": float(v_prev / paid), "dca_paid_in": paid,
            "dca_n_contributions": len(flows), "dca_worst_value_vs_paid_in": worst[0],
            "dca_worst_value_vs_paid_in_date": worst[1], "cagr": pm["cagr"], "mdd": pm["mdd"],
            "vol": pm["vol"], "sharpe": pm["sharpe"], "sharpe_ex": pm["sharpe_ex"],
            "calmar": pm["calmar"], "n_days": pm["n_days"],
            "start_date": str(data.dates[i0]), "end_date": str(end)}


# ----------------------------------------------------------------------------- main
def main():
    t_start = time.time()
    os.makedirs(C.OUT_DIR, exist_ok=True)
    out = lambda f: os.path.join(C.OUT_DIR, f)
    data = C.Data()
    assert str(data.dates[-1]) <= C.END_DATE
    bench = bench_series(data)

    # 1. synthetic validation first: nothing below is produced unless this is written
    val, val_extra = synthetic_validation(data)
    C.write_csv(out("synthetic_validation.csv"), val)
    print(val.head(4).to_string())
    print(val_extra)

    # 2. frozen cells, base and stress cost
    cells = build_cells(data)
    sims, port_rows, win_rows, dd_rows, lines = {}, [], [], [], {}
    for cost_name, cost in C.COSTS.items():
        for b in BENCH:
            m = full_metrics(data, bench[b], data.i_start, bench)
            port_rows.append({"portfolio": b, "kind": "benchmark", "cost": cost_name, **m})
            win_rows += window_rows(data, b, cost_name, bench[b], data.i_start, bench)
            if cost_name == C.BASE:
                dd_rows += drawdown_rows(data, b, bench[b], data.i_start)
        for comp in COMPONENTS:      # single instruments held close to close, for context only
            r = data.ret[:, IDX[comp]].copy()
            r[:data.i_start + 1] = np.nan
            port_rows.append({"portfolio": comp, "kind": "component_reference", "cost": cost_name,
                              **full_metrics(data, r, data.i_start, bench)})
            win_rows += window_rows(data, comp, cost_name, r, data.i_start, bench)
            if cost_name == C.BASE:
                dd_rows += drawdown_rows(data, comp, r, data.i_start)
        for name, cell in cells.items():
            sim = C.simulate(data, cell.dec, cell.W, cost)
            ret, v1 = sim["ret"][:, 0], sim["v1"]
            sims[(name, cost_name)] = (ret, v1)
            m = full_metrics(data, ret, v1, bench)
            j0, i1 = C.window_slice(data, v1, "FULL")
            to, drag = C.turnover(sim, j0, i1)
            row = {"portfolio": name, "kind": KIND[name], "cost": cost_name, **m,
                   "turnover_one_way_per_year": to, "cost_drag_per_year": drag,
                   "n_decisions": int(len(cell.dec)), "first_trade_date": str(data.dates[v1 + 1])}
            if cell.e_daily is not None:
                e = cell.e_dec
                row.update(avg_exposure=float(e.mean()), min_exposure=float(e.min()),
                           max_exposure=float(e.max()), share_decisions_above_1=float((e > 1).mean()),
                           share_decisions_at_cap_2=float((e >= 2 - 1e-9).mean()))
            lines[(name, cost_name)] = lines_123(data, ret, v1, bench["SPY"])
            row.update({k: lines[(name, cost_name)][k] for k in ("line1", "line2", "line3")})
            port_rows.append(row)
            win_rows += window_rows(data, name, cost_name, ret, v1, bench)
            if cost_name == C.BASE:
                dd_rows += drawdown_rows(data, name, ret, v1)
    print("frozen cells done %.1fs" % (time.time() - t_start))

    # 3. sensitivity (report only; base cost)
    sens_rows, sens_cells = [], {}
    for vname, kw in SENS_VARIANTS.items():
        sens_cells[vname] = build_cells(data, **kw)
    for name, variants in SENS_OF.items():
        for vname in variants:
            cell = sens_cells[vname][name]
            sim = C.simulate(data, cell.dec, cell.W, C.COSTS[C.BASE])
            ret, v1 = sim["ret"][:, 0], sim["v1"]
            j0, i1 = C.window_slice(data, v1, "FULL")
            m, s, q = (C.slice_perf(data, r, j0, i1) for r in (ret, bench["SPY"], bench["QQQ"]))
            to, drag = C.turnover(sim, j0, i1)
            l = lines_123(data, ret, v1, bench["SPY"])
            sens_rows.append({
                "portfolio": name, "variant": vname.replace("R1_", "").replace("T1_", ""),
                "cost": C.BASE, "start_date": m["start_date"], "end_date": m["end_date"],
                "n_days": m["n_days"], "cagr": m["cagr"], "vol": m["vol"], "sharpe": m["sharpe"],
                "sharpe_ex": m["sharpe_ex"], "mdd": m["mdd"], "calmar": m["calmar"],
                "spy_cagr_same": s["cagr"], "spy_mdd_same": s["mdd"], "spy_calmar_same": s["calmar"],
                "qqq_cagr_same": q["cagr"], "qqq_calmar_same": q["calmar"],
                "calmar_above_spy": bool(m["calmar"] > s["calmar"]),
                "cagr_minus_spy": m["cagr"] - s["cagr"], "line1": l["line1"], "line2": l["line2"],
                "line3": l["line3"], "turnover_one_way_per_year": to, "cost_drag_per_year": drag,
                "avg_exposure": float(cell.e_dec.mean()) if cell.e_daily is not None else np.nan,
                "in_narrow_reading": bool(name not in SENS_NARROW or vname in SENS_NARROW[name])})
    sens = pd.DataFrame(sens_rows)
    C.write_csv(out("sensitivity.csv"), sens)
    print("sensitivity done %.1fs" % (time.time() - t_start))

    # 4. circular-shift control for the timed cells (base cost), BH over the six
    nulls = {}
    for k, name in enumerate(TIMED):
        nulls[name] = null_test(data, cells[name], sims[(name, C.BASE)][0], C.COSTS[C.BASE],
                                C.SEED + k)
    qv = C.bh_qvalues([nulls[n]["null_p"] for n in TIMED])
    for n, q in zip(TIMED, qv):
        nulls[n]["null_q"] = float(q)
    # information only: what BH would give if the statistic were one metric alone
    alt_q = {}
    for k in ("cagr", "calmar", "sharpe_info", "mdd_info"):
        qa = C.bh_qvalues([nulls[n]["null_p_" + k] for n in TIMED])
        alt_q[k.replace("_info", "")] = {n: float(q) for n, q in zip(TIMED, qa)}

    # diagnostic (not a result): BIL traded at its previous close plus the day's return
    # instead of its own open print, to size the effect of noisy BIL opens
    d2 = C.Data(with_tqqq=False)
    d2.on[:, C.BIL] = d2.on[:, C.BIL] * d2.intr[:, C.BIL]
    d2.intr[:, C.BIL] = 1.0
    bil_diag = {}
    for name in TIMED:
        cell = cells[name]
        r2 = C.simulate(d2, cell.dec, cell.W, C.COSTS[C.BASE])["ret"][:, 0]
        j0, i1 = C.window_slice(data, int(cell.dec[0]), "FULL")
        a, b = C.slice_perf(data, sims[(name, C.BASE)][0], j0, i1), C.slice_perf(d2, r2, j0, i1)
        bil_diag[name] = {"cagr_change": b["cagr"] - a["cagr"], "mdd_change": b["mdd"] - a["mdd"]}
    gap = np.abs(data.on[:, C.BIL] - 1.0 - data.rf)
    bil_diag["n_sessions_bil_open_gap_gt_25bp"] = int((gap[data.i_start:] > 0.0025).sum())
    print("null done %.1fs" % (time.time() - t_start))

    # 5. block bootstrap of differences vs SPY and vs QQQ (base cost, common days)
    boot_rows = []
    series = {b: (bench[b], data.i_start) for b in BENCH}
    series.update({n: sims[(n, C.BASE)] for n in cells})
    for name, (ret, v1) in series.items():
        for b in ("SPY", "QQQ"):
            if name == b:
                continue
            j0, i1 = C.window_slice(data, v1, "FULL")
            sl = slice(j0 + 1, i1 + 1)
            r = C.block_bootstrap_diff(ret[sl], bench[b][sl], data.rf[sl], C.SEED + 1000 + (i1 - j0))
            boot_rows.append({"portfolio": name, "benchmark": b, "cost": C.BASE,
                              "start_date": str(data.dates[j0]), "end_date": str(data.dates[i1]),
                              "block_sessions": C.BOOT_BLOCK, "n_boot": C.N_BOOT, **r})
    boot = pd.DataFrame(boot_rows)
    C.write_csv(out("bootstrap.csv"), boot)
    print("bootstrap done %.1fs" % (time.time() - t_start))

    # 6. monthly investing version of S2 (with same-cash-flow references)
    dca_rows = {}
    for label, parts in (("S2_DCA", S2_PARTS), ("S3_DCA", S3_PARTS), ("SPY_DCA", {"SPY": 1.0}),
                         ("QQQ_DCA", {"QQQ": 1.0})):
        for cost_name, cost in C.COSTS.items():
            r = dca(data, parts, cost)
            dca_rows[(label, cost_name)] = r
            port_rows.append({"portfolio": label, "kind": "monthly_investing" if label == "S2_DCA"
                              else "monthly_investing_reference", "cost": cost_name, **r})

    # 7. pass lines and verdict
    sens_share, verdict_cells = {}, {}
    for name in CANDIDATES:
        b, s = lines[(name, C.BASE)], lines[(name, C.STRESS)]
        v = {"kind": KIND[name], "has_timing_component": name in TIMED,
             "line1_cagr_ge_spy_and_calmar_gt_spy": b["line1"],
             "line1_cagr_ok": b["line1_cagr_ok"], "line1_calmar_ok": b["line1_calmar_ok"],
             "line2_each_window_within_2pp_of_spy": b["line2"],
             "line3_mdd_within_5pp_of_spy": b["line3"],
             "line4_lines_1_to_3_hold_at_10bp": bool(s["line1"] and s["line2"] and s["line3"]),
             "window_cagr_gap_vs_spy": b["window_cagr_gap_vs_spy"],
             "mdd_gap_vs_spy": b["mdd_gap_vs_spy"]}
        if name in SENS_OF:
            g = sens.loc[sens["portfolio"] == name]
            share = float(g["calmar_above_spy"].mean())
            gn = g.loc[g["in_narrow_reading"]]
            v.update(line5_share_of_variants_calmar_gt_spy=share, line5_n_variants=int(len(g)),
                     line5_sensitivity=bool(share >= 0.75),
                     line5_narrow_reading_share=float(gn["calmar_above_spy"].mean()),
                     line5_narrow_reading=bool(gn["calmar_above_spy"].mean() >= 0.75))
        else:
            v.update(line5_share_of_variants_calmar_gt_spy=None, line5_n_variants=0,
                     line5_sensitivity=None)
        if name in TIMED:
            v.update(line6_null_q_lt_0p10=bool(nulls[name]["null_q"] < 0.10), null=nulls[name])
        else:
            v.update(line6_null_q_lt_0p10=None)
        req = [v["line1_cagr_ge_spy_and_calmar_gt_spy"], v["line2_each_window_within_2pp_of_spy"],
               v["line3_mdd_within_5pp_of_spy"], v["line4_lines_1_to_3_hold_at_10bp"]]
        if v["line5_sensitivity"] is not None:
            req.append(v["line5_sensitivity"])
        if v["line6_null_q_lt_0p10"] is not None:
            req.append(v["line6_null_q_lt_0p10"])
        v["n_lines_applicable"] = len(req)
        v["n_lines_passed"] = int(sum(req))
        v["passes_all_applicable_lines"] = bool(all(req))
        v["nominated_for_forward_tracking"] = bool(all(req))
        verdict_cells[name] = v

    ports = pd.DataFrame(port_rows)
    for name in CANDIDATES:
        m = (ports["portfolio"] == name) & (ports["cost"] == C.BASE)
        v = verdict_cells[name]
        ports.loc[m, "line4"] = v["line4_lines_1_to_3_hold_at_10bp"]
        ports.loc[m, "line5"] = v["line5_sensitivity"]
        ports.loc[m, "line5_share"] = v["line5_share_of_variants_calmar_gt_spy"]
        ports.loc[m, "line6"] = v["line6_null_q_lt_0p10"]
        ports.loc[m, "pass_all_applicable"] = v["passes_all_applicable_lines"]
        if name in TIMED:
            for k in ("null_p_cagr", "null_p_calmar", "null_p", "null_q"):
                ports.loc[m, k] = nulls[name][k]
    C.write_csv(out("portfolios.csv"), ports)
    C.write_csv(out("windows.csv"), pd.DataFrame(win_rows))
    C.write_csv(out("drawdowns.csv"), pd.DataFrame(dd_rows))

    full = val.iloc[0]
    passed = [n for n in CANDIDATES if verdict_cells[n]["passes_all_applicable_lines"]]
    verdict = {
        "study": "ETF-C (ETF portfolio construction)",
        "spec": "research/overnight-study-2026-11-19.md, section 第三組 ETF-C (frozen)",
        "status": "descriptive / nomination-only",
        "end_date": C.END_DATE, "last_session_used": str(data.dates[-1]),
        "period": [C.SIM_START, C.END_DATE], "windows": C.WINDOWS,
        "costs_per_side": C.COSTS,
        "n_candidates": len(CANDIDATES), "n_pass_all_applicable_lines": len(passed),
        "passed": passed,
        "pass_line_counts": {
            "line1": int(sum(verdict_cells[n]["line1_cagr_ge_spy_and_calmar_gt_spy"] for n in CANDIDATES)),
            "line2": int(sum(verdict_cells[n]["line2_each_window_within_2pp_of_spy"] for n in CANDIDATES)),
            "line3": int(sum(verdict_cells[n]["line3_mdd_within_5pp_of_spy"] for n in CANDIDATES)),
            "line4": int(sum(verdict_cells[n]["line4_lines_1_to_3_hold_at_10bp"] for n in CANDIDATES)),
            "line5": "%d of %d with sensitivity variants" % (
                sum(bool(verdict_cells[n]["line5_sensitivity"]) for n in SENS_OF), len(SENS_OF)),
            "line6": "%d of %d timed" % (
                sum(bool(verdict_cells[n]["line6_null_q_lt_0p10"]) for n in TIMED), len(TIMED)),
        },
        "cells": verdict_cells,
        "risk_choice_cells_no_control_test": ["S1", "S2", "S3", "R1"],
        "timed_cells_with_control_test": TIMED,
        "synthetic_validation": {
            "period": [full["start_date"], full["end_date"]],
            "cagr_real_tqqq": full["cagr_real_tqqq"], "cagr_synth_3x": full["cagr_synth_3x"],
            "cagr_gap_synth_minus_real": full["cagr_gap_synth_minus_real"],
            "tracking_error_ann": full["tracking_error_ann"], "corr": full["corr"],
            "worst_year_gap": float(val.loc[val["period"].str.startswith("Y"), "cagr_gap_synth_minus_real"].min()),
            "best_year_gap": float(val.loc[val["period"].str.startswith("Y"), "cagr_gap_synth_minus_real"].max()),
            **val_extra},
        "monthly_investing": {k[0] + "@" + k[1]: v for k, v in dca_rows.items()},
        "live_start": {n: str(data.dates[sims[(n, C.BASE)][1]]) for n in cells},
        "data_quality": {"dropped_bars": data.dropped, "per_symbol": data.quality,
                         "bil_real_factors_from": data.bil_first_factor_day},
        "null_test": {"n_shifts": C.N_NULL, "min_shift_sessions": C.MIN_SHIFT,
                      "statistic": "max(p_CAGR, p_Calmar), one-sided", "bh_family": TIMED,
                      "information_only_q_if_single_metric": alt_q,
                      "information_only_n_q_lt_0p10": {
                          k: int(sum(q < 0.10 for q in v.values())) for k, v in alt_q.items()}},
        "diagnostics": {"bil_traded_at_close_equivalent": bil_diag},
        "bootstrap": {"type": "paired circular block", "block_sessions": C.BOOT_BLOCK,
                      "n_boot": C.N_BOOT},
        "interpretation_choices": INTERPRETATION_CHOICES,
        "runtime_seconds": round(time.time() - t_start, 1),
    }
    C.write_json(out("verdict.json"), verdict)
    print("passed:", passed, "| runtime %.1fs" % (time.time() - t_start))


if __name__ == "__main__":
    sys.exit(main())
