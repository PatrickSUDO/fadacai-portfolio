#!/usr/bin/env python3
"""Shared data loading, simulation engine, metrics and report assembly for the ETF
half of the 2026-11-18 horizon study (US-A / US-B / US-C).

Spec (frozen): research/horizon-study-2026-11-18.md
Raw data: fadacai-etf-rotation/data/raw/{eodhd,eodhd_explore}/<SYM>.json, READ-ONLY.
No network, no parquet, no import of the fadacai_etf_rotation package.

Timing convention used everywhere in this half
----------------------------------------------
* A decision dated t uses only adjusted closes <= t.
* It is executed at the adjusted open of t+1 (adj_open = open * adjusted_close / close).
* Day s of an account = outgoing holdings earn close[s-1] -> open[s], then the trade
  happens at open[s], then incoming holdings earn open[s] -> close[s].
* Cash earns the ^IRX daily rate of day s on the balance held over the night
  s-1 -> s (rate = previous available IRX value, strictly before s, / 100 / 252).
* END DATE: every row dated after 2025-12-31 is dropped immediately after reading.

Window metric convention (same as the stock half, stk_common.py)
----------------------------------------------------------------
V = 1 at the close of the first session of the window; the returns used are those
of the following sessions up to the window end; CAGR uses the calendar days between
those two closes.

Report assembly:  python3 -B etf_common.py report
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

RAW_ROOT = "/Users/supatrick/laptop/project/fadacai-etf-rotation/data/raw"
RAW_DIRS = ("eodhd", "eodhd_explore")
HERE = os.path.dirname(os.path.abspath(__file__))
CANONICAL_OUT_DIR = os.path.normpath(os.path.join(HERE, "..", "data", "horizon_sweep_2026-11-18", "etf"))
# The canonical directory sits in a file-synced folder that renames files rewritten
# in quick succession ("name [conflicted].csv"). HORIZON_ETF_OUT_DIR lets a run work
# in a scratch directory; the finished tree is then copied to CANONICAL_OUT_DIR once.
OUT_DIR = os.environ.get("HORIZON_ETF_OUT_DIR") or CANONICAL_OUT_DIR
PARTS_DIR = os.path.join(OUT_DIR, "parts")
END_DATE = "2025-12-31"

EQ = ("SPY QQQ SMH XLB XLE XLF XLI XLK XLP XLU XLV XLY XLRE XLC XBI ITB KRE MDY DIA IWM "
      "IYR EFA EEM VNQ GDX XME SLX").split()
MA = "SPY QQQ IWM EFA EEM TLT IEF LQD HYG AGG GLD SLV DBC USO VNQ UUP".split()
UNIVERSES = {"EQ": EQ, "MA": MA}
BENCH = ["SPY", "QQQ", "SMH"]
ALL_SYMS = list(dict.fromkeys(EQ + MA))
assert len(EQ) == 27 and len(MA) == 16

H_LIST = [1, 5, 10, 21, 63, 126, 252]
XS_SIGNALS = [("ret_1", 1, 0), ("ret_5", 5, 0), ("ret_21", 21, 0), ("ret_63", 63, 0),
              ("ret_126", 126, 0), ("ret_252", 252, 0), ("ret_252_skip21", 252, 21)]
TS_L_LIST = [1, 5, 10, 21, 63, 126, 252]
MAX_TRANCHES = 21
MIN_HISTORY = 252
MIN_NAMES = 6
N_PICK = 3
N_NULL_XS = 200
N_NULL_TS = 1000
MIN_SHIFT = 252
# Open prints that look wrong but are NOT covered by the spec's bad-bar filter. The
# frozen cells keep them; a labelled sensitivity replaces them by the previous close.
SUSPECT_OPENS = [("XLV", "2002-01-08")]

WINDOWS = {
    "Wa": ("2000-01-03", "2009-12-31"),
    "Wb": ("2010-01-04", "2017-12-29"),
    "Wc": ("2018-01-02", "2025-12-31"),
    "FULL": ("2000-01-03", "2025-12-31"),
}
WINDOW_ORDER = ["Wa", "Wb", "Wc", "FULL"]
SUB_WINDOWS = ["Wa", "Wb", "Wc"]
COSTS = {"gross_0bp": 0.0, "base_5bp": 0.0005, "stress_10bp": 0.0010}   # US-A / US-B
BASE, STRESS, GROSS = "base_5bp", "stress_10bp", "gross_0bp"
OVN_COSTS = {"gross_0bp": 0.0, "1bp": 0.0001, "2bp": 0.0002, "5bp": 0.0005}  # US-C
SEED = 20261118
METRIC_COLS = ["n_days", "start_date", "end_date", "cagr", "irr", "sharpe", "sharpe_ex",
               "mdd", "calmar", "total_return"]


# --------------------------------------------------------------------------- data
def raw_path(sym: str) -> str:
    for d in RAW_DIRS:
        p = os.path.join(RAW_ROOT, d, sym + ".json")
        if os.path.exists(p):
            return p
    raise FileNotFoundError(sym)


def read_raw(sym: str) -> pd.DataFrame:
    """Read one raw JSON and drop every row after END_DATE straight away."""
    with open(raw_path(sym)) as fh:
        raw = json.load(fh)
    df = pd.DataFrame(raw)
    df["date"] = df["date"].astype(str)
    df = df.loc[df["date"] <= END_DATE].reset_index(drop=True)
    assert (df["date"] <= END_DATE).all()
    return df


def clean_bars(df: pd.DataFrame, sym: str, log: list) -> pd.DataFrame:
    """Drop obviously bad bars: non-positive / missing prices, and bars whose
    adjusted close is >5x or <0.2x the previous kept bar. Every drop is logged."""
    cols = ["open", "high", "low", "close", "adjusted_close"]
    df = df.copy()
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    bad = df[cols].isna().any(axis=1) | (df[cols] <= 0).any(axis=1)
    for d in df.loc[bad, "date"]:
        log.append({"symbol": sym, "date": str(d), "reason": "non_positive_or_missing_price"})
    df = df.loc[~bad].reset_index(drop=True)
    while True:
        r = (df["adjusted_close"] / df["adjusted_close"].shift(1)).to_numpy()
        j = np.where((r > 5) | (r < 0.2))[0]
        if len(j) == 0:
            break
        i = int(j[0])
        log.append({"symbol": sym, "date": str(df.loc[i, "date"]),
                    "reason": "adj_close_ratio_%.4f" % r[i]})
        df = df.drop(index=i).reset_index(drop=True)
    return df


def load_symbol(sym: str, log: list | None = None) -> pd.DataFrame:
    return clean_bars(read_raw(sym), sym, log if log is not None else [])


def cash_rate_from_series(idates: np.ndarray, vals: np.ndarray, dates: np.ndarray) -> np.ndarray:
    """Daily cash rate for each calendar day s: last IRX value dated strictly before
    s, / 100 / 252; 0 before the IRX series starts."""
    pos = np.searchsorted(idates, dates, side="left") - 1
    return np.where(pos >= 0, vals[np.clip(pos, 0, None)] / 100.0 / 252.0, 0.0)


def load_cash_rate(dates: np.ndarray) -> np.ndarray:
    df = read_raw("IRX_INDX")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).sort_values("date")
    idates = np.array(df["date"], dtype="datetime64[D]")
    return cash_rate_from_series(idates, df["close"].to_numpy(float), dates)


def ffill(a: np.ndarray) -> np.ndarray:
    """Forward-fill NaNs down the rows (used for marking only)."""
    a = np.asarray(a, float)
    if a.ndim == 1:
        return ffill(a[:, None])[:, 0]
    T = a.shape[0]
    idx = np.where(np.isfinite(a), np.arange(T)[:, None], 0)
    np.maximum.accumulate(idx, axis=0, out=idx)
    return np.take_along_axis(a, idx, axis=0)


@dataclass
class Panel:
    dates: np.ndarray            # datetime64[D], SPY master calendar
    syms: list
    adj_close: np.ndarray        # (T, A); NaN where the symbol has no bar
    adj_open: np.ndarray         # (T, A); NaN where the symbol has no bar
    rf: np.ndarray               # (T,) daily cash rate
    dropped: list = field(default_factory=list)
    quality: dict = field(default_factory=dict)

    @property
    def bar(self) -> np.ndarray:
        return np.isfinite(self.adj_close) & np.isfinite(self.adj_open)

    @property
    def carry(self) -> np.ndarray:
        return ffill(self.adj_close)

    def col(self, sym: str) -> int:
        return self.syms.index(sym)

    def cols(self, syms) -> list:
        return [self.syms.index(s) for s in syms]


def build_panel(syms: list | None = None) -> Panel:
    syms = list(ALL_SYMS if syms is None else syms)
    log: list = []
    spy = load_symbol("SPY", log if "SPY" in syms else [])
    dates_s = spy["date"].to_numpy()
    dates = np.array(dates_s, dtype="datetime64[D]")
    assert str(dates[-1]) <= END_DATE
    T = len(dates)
    pos = {d: i for i, d in enumerate(dates_s)}
    ac = np.full((T, len(syms)), np.nan)
    ao = np.full((T, len(syms)), np.nan)
    quality = {}
    for a, s in enumerate(syms):
        df = spy if s == "SPY" else load_symbol(s, log)
        ii = np.array([pos.get(d, -1) for d in df["date"]])
        keep = ii >= 0
        adj = df["adjusted_close"].to_numpy(float)
        opn = df["open"].to_numpy(float) * adj / df["close"].to_numpy(float)
        ac[ii[keep], a] = adj[keep]
        ao[ii[keep], a] = opn[keep]
        first = int(ii[keep][0])
        missing = [str(dates[i]) for i in range(first, T) if not np.isfinite(ac[i, a])]
        gap = opn[1:] / adj[:-1] - 1.0
        big = np.where(np.abs(gap) > 0.15)[0] + 1
        quality[s] = {
            "first_bar": str(df["date"].iloc[0]), "last_bar": str(df["date"].iloc[-1]),
            "n_bars": int(len(df)), "off_calendar_rows": int((~keep).sum()),
            "missing_after_first_bar": missing,
            "open_equals_prev_close_days": int((df["open"].to_numpy()[1:] ==
                                                df["close"].to_numpy()[:-1]).sum()),
            "overnight_gap_gt_15pct": [{"date": str(df["date"].iloc[i]),
                                        "gap": round(float(gap[i - 1]), 4)} for i in big],
        }
    return Panel(dates, syms, ac, ao, load_cash_rate(dates), log, quality)


def window_bounds(dates: np.ndarray) -> dict:
    """name -> (i0, i1): first and last session of the window on the master calendar."""
    out = {}
    for name, (a, b) in WINDOWS.items():
        i0 = int(np.searchsorted(dates, np.datetime64(a), side="left"))
        i1 = int(np.searchsorted(dates, np.datetime64(b), side="right")) - 1
        out[name] = (i0, i1)
    return out


# ------------------------------------------------------------------------ metrics
def perf(ret: np.ndarray, rf: np.ndarray, cal_days: float) -> dict:
    """Metrics for daily simple returns (V_start = 1 before the first return).
    ret may be (n,) or (n, G).
    CAGR = (V_end/V_start)^(365.25/cal_days)-1 ; Sharpe = mean/std(ddof=1)*sqrt(252)
    with no risk-free subtraction ; sharpe_ex on returns minus daily cash rate ;
    MDD = min(V/cummax(V)-1) ; Calmar = CAGR/|MDD| ; IRR == CAGR (lump sum)."""
    r = np.asarray(ret, float)
    one = r.ndim == 1
    if one:
        r = r[:, None]
    n = r.shape[0]
    if n < 2 or cal_days <= 0:
        nanv = np.full(r.shape[1], np.nan)
        out = dict(n_days=n, cagr=nanv, irr=nanv, sharpe=nanv, sharpe_ex=nanv, mdd=nanv,
                   calmar=nanv, total_return=nanv)
    else:
        v = np.cumprod(1.0 + r, axis=0)
        cagr = v[-1] ** (365.25 / cal_days) - 1.0
        sd = r.std(axis=0, ddof=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            sharpe = np.where(sd > 0, r.mean(axis=0) / sd * math.sqrt(252), np.nan)
            ex = r - np.asarray(rf, float)[:, None]
            sdx = ex.std(axis=0, ddof=1)
            sharpe_ex = np.where(sdx > 0, ex.mean(axis=0) / sdx * math.sqrt(252), np.nan)
            v1 = np.vstack([np.ones((1, r.shape[1])), v])
            mdd = (v1 / np.maximum.accumulate(v1, axis=0) - 1.0).min(axis=0)
            calmar = np.where(mdd < 0, cagr / np.abs(mdd), np.nan)
        out = dict(n_days=n, cagr=cagr, irr=cagr, sharpe=sharpe, sharpe_ex=sharpe_ex, mdd=mdd,
                   calmar=calmar, total_return=v[-1] - 1.0)
    if one:
        out = {k: (float(v[0]) if isinstance(v, np.ndarray) else v) for k, v in out.items()}
    return out


def live_start(ret: np.ndarray, i0: int, include_first: bool = False):
    """Index j0 whose close is the V=1 point. Frozen convention: i0 itself (the close
    of the window's first session), or (first finite return - 1) when the series is
    not alive yet at i0. include_first=True (sensitivity only): the close of the last
    session BEFORE the window when the series is already alive on i0, so that the
    first session's return is counted. None if never alive."""
    r = np.asarray(ret, float)
    probe = r if r.ndim == 1 else r[:, 0]
    fin = np.flatnonzero(np.isfinite(probe))
    if len(fin) == 0:
        return None
    lo = i0 - 1 if (include_first and i0 >= 1) else i0
    return max(lo, int(fin[0]) - 1)


def window_perf(ret: np.ndarray, rf: np.ndarray, dates: np.ndarray, i0: int, i1: int,
                include_first: bool = False) -> dict:
    """Slice ONE continuous daily-return series to the window: V=1 at the close of
    day j0 (= i0 unless the series starts later), returns of days j0+1..i1."""
    r = np.asarray(ret, float)
    j0 = live_start(r, i0, include_first)
    if j0 is None or j0 >= i1:
        out = perf(r[:0], rf[:0], 0)
        out.update(start_date="", end_date="")
        return out
    cal = int((dates[i1] - dates[j0]) / np.timedelta64(1, "D"))
    out = perf(r[j0 + 1:i1 + 1], rf[j0 + 1:i1 + 1], cal)
    out.update(start_date=str(dates[j0]), end_date=str(dates[i1]))
    return out


def rel_perf(ret: np.ndarray, bench: np.ndarray, dates: np.ndarray, i0: int, i1: int,
             include_first: bool = False) -> tuple:
    """(excess CAGR, information ratio) of ret vs bench on the common days of the
    window. excess CAGR = CAGR(ret) - CAGR(bench) over the same days;
    IR = mean(daily active)/std(daily active, ddof=1)*sqrt(252)."""
    ja, jb = live_start(ret, i0, include_first), live_start(bench, i0, include_first)
    if ja is None or jb is None:
        return (np.nan, np.nan)
    j0 = max(ja, jb)
    if j0 >= i1 - 1:
        return (np.nan, np.nan)
    a = np.asarray(ret, float)[j0 + 1:i1 + 1]
    b = np.asarray(bench, float)[j0 + 1:i1 + 1]
    cd = int((dates[i1] - dates[j0]) / np.timedelta64(1, "D"))
    ca = np.prod(1 + a) ** (365.25 / cd) - 1
    cb = np.prod(1 + b) ** (365.25 / cd) - 1
    d = a - b
    sd = d.std(ddof=1)
    ir = d.mean() / sd * math.sqrt(252) if sd > 0 else np.nan
    return (float(ca - cb), float(ir))


def blank_before(ret: np.ndarray, t0: int) -> np.ndarray:
    """Copy of a daily-return array with every day up to and including the decision
    day t0 set to NaN: the series is 'not live' before its first trade day t0+1, so
    window metrics and benchmark comparisons use the live days only."""
    out = np.array(ret, float, copy=True)
    out[:t0 + 1] = np.nan
    return out


def bh_qvalues(p) -> np.ndarray:
    """Benjamini-Hochberg step-up q-values (hand-rolled; scipy is not installed)."""
    p = np.asarray(p, float)
    q = np.full(p.shape, np.nan)
    ok = np.where(np.isfinite(p))[0]
    m = len(ok)
    if m == 0:
        return q
    order = ok[np.argsort(p[ok], kind="stable")]
    ranked = p[order] * m / np.arange(1, m + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    q[order] = np.minimum(ranked, 1.0)
    return q


def nav_to_ret(nav: np.ndarray) -> np.ndarray:
    r = np.zeros_like(nav)
    r[1:] = nav[1:] / nav[:-1] - 1.0
    return r


# ----------------------------------------------------------------------- tranches
def tranche_offsets(H: int) -> list:
    """min(H, 21) tranches; start days spread evenly over the H-day cycle."""
    K = min(H, MAX_TRANCHES)
    return [(k * H) // K for k in range(K)]


# ------------------------------------------------------------------------- engine
def simulate(adj_open, adj_close, rf, plan_fn, cost, gid, n_groups, t_first=0, fee_iters=0):
    """Daily sub-account simulator.

    adj_open / adj_close : (T, A), NaN where the asset has no bar that day.
    rf                   : (T,) daily cash rate.
    plan_fn(t, flat)     : decisions taken at the close of day t. Returns None or
                           (idx, W): account indices and their target weight rows
                           (each row sums to 1, or to 0 for "all cash"). `flat`
                           is a bool array, True for accounts holding only cash.
    cost                 : (N,) per-side cost rate of each account.
    gid                  : (N,) group id; group NAV = mean of its accounts' NAV
                           (independent sub-accounts, no hidden rebalancing).
    Trades decided at t are executed at adj_open[t+1]. Returns group NAV (T, G),
    traded notional and fees per group (in units of initial group capital) and an
    info dict.

    Fee model (frozen cells, fee_iters=0): fee = cost x sum|W x NAV_pre_fee - holding|,
    i.e. the traded notional is measured against the pre-fee NAV (first-order
    approximation). fee_iters > 0 (sensitivity only) iterates
    fee = cost x sum|W x (NAV - fee) - holding| to its fixed point, the exact
    self-financing fee.
    """
    adj_open = np.asarray(adj_open, float)
    adj_close = np.asarray(adj_close, float)
    T, A = adj_close.shape
    cost = np.asarray(cost, float)
    gid = np.asarray(gid, int)
    N = len(cost)
    bar = np.isfinite(adj_close) & np.isfinite(adj_open)
    carry = ffill(adj_close)
    prev = np.vstack([np.full((1, A), np.nan), carry[:-1]])
    with np.errstate(invalid="ignore", divide="ignore"):
        on = np.where(bar & np.isfinite(prev), adj_open / prev, 1.0)
        intr = np.where(bar, adj_close / adj_open, 1.0)
    h = np.zeros((N, A))
    c = np.ones(N)
    invested = np.zeros(N, bool)
    cnt = np.bincount(gid, minlength=n_groups).astype(float)
    nav = np.ones((T, n_groups))
    traded = np.zeros((T, n_groups))
    fees = np.zeros((T, n_groups))
    n_skipped = 0
    n_trades = 0
    for s in range(t_first + 1, T):
        h *= on[s]
        c *= 1.0 + rf[s]
        plan = plan_fn(s - 1, ~invested)
        if plan is not None and len(plan[0]):
            idx, W = plan
            hold = h[idx]
            nv = hold.sum(axis=1) + c[idx]
            tgt = W * nv[:, None]
            diff = np.abs(tgt - hold)
            ok = bar[s]
            if not ok.all():
                # an asset without a bar today cannot be traded: the whole
                # rebalance of that account is skipped and counted
                skip = (diff[:, ~ok] > 0).any(axis=1)
                if skip.any():
                    n_skipped += int(skip.sum())
                    keep = ~skip
                    idx, W, hold, nv, diff = idx[keep], W[keep], hold[keep], nv[keep], diff[keep]
            if len(idx):
                tr = diff.sum(axis=1)
                fee = cost[idx] * tr
                for _ in range(fee_iters):
                    tr = np.abs(W * (nv - fee)[:, None] - hold).sum(axis=1)
                    fee = cost[idx] * tr
                nv2 = nv - fee
                wsum = W.sum(axis=1)
                h[idx] = W * nv2[:, None]
                c[idx] = nv2 * np.where(np.abs(1.0 - wsum) < 1e-12, 0.0, 1.0 - wsum)
                invested[idx] = wsum > 0
                traded[s] = np.bincount(gid[idx], weights=tr, minlength=n_groups) / cnt
                fees[s] = np.bincount(gid[idx], weights=fee, minlength=n_groups) / cnt
                n_trades += len(idx)
        h *= intr[s]
        nav[s] = np.bincount(gid, weights=h.sum(axis=1) + c, minlength=n_groups) / cnt
    return nav, traded, fees, {"n_skipped_untradable": n_skipped, "n_account_trades": n_trades}


def turnover_stats(traded: np.ndarray, fees: np.ndarray, nav: np.ndarray, j0: int, i1: int):
    """Annualised one-way turnover (x NAV / year) and cost drag (fraction of NAV / year)
    over days j0+1..i1. One-way = (buys + sells) / 2. Denominator = previous close NAV."""
    if j0 is None or j0 >= i1:
        return np.full(nav.shape[1], np.nan), np.full(nav.shape[1], np.nan)
    den = nav[j0:i1]
    yrs = (i1 - j0) / 252.0
    to = (traded[j0 + 1:i1 + 1] / den).sum(axis=0) / 2.0 / yrs
    drag = (fees[j0 + 1:i1 + 1] / den).sum(axis=0) / yrs
    return to, drag


# ------------------------------------------------------------------ benchmarks
def buy_hold_returns(adj_close_1d: np.ndarray) -> np.ndarray:
    """Close-to-close total return on adjusted close; NaN up to and including the
    first bar (carried over missing bars)."""
    p = ffill(adj_close_1d)
    r = np.full(len(p), np.nan)
    r[1:] = p[1:] / p[:-1] - 1.0
    return r


def eligibility(bar: np.ndarray, min_history: int = MIN_HISTORY) -> np.ndarray:
    """eligible[t, a]: the symbol has a bar on t and at least `min_history` bars
    strictly before t."""
    prior = np.cumsum(bar, axis=0) - bar
    return bar & (prior >= min_history)


def equal_weight_returns(adj_close: np.ndarray, elig: np.ndarray, rf: np.ndarray,
                         min_names: int = MIN_NAMES, blank_prelive: bool = True) -> np.ndarray:
    """Daily-rebalanced equal weight of the names eligible at the previous close,
    zero cost, close to close. After the first day with >= min_names eligible names,
    days with fewer names earn cash (same no-position rule as the strategy).
    blank_prelive=True: NaN up to and including that first day (the benchmark is not
    live before the universe exists, exactly like the strategy cells).
    blank_prelive=False: cash at the IRX rate before it (the superseded convention,
    kept for the labelled 'incl_prestart_cash' comparison columns)."""
    carry = ffill(adj_close)
    T = carry.shape[0]
    r = np.zeros(T)
    with np.errstate(invalid="ignore", divide="ignore"):
        cc = carry[1:] / carry[:-1] - 1.0
    e = elig[:-1]
    n = e.sum(axis=1)
    s = np.where(e, np.nan_to_num(cc), 0.0).sum(axis=1)
    r[1:] = np.where(n >= min_names, s / np.maximum(n, 1), rf[1:])
    if blank_prelive:
        ok = np.flatnonzero(elig.sum(axis=1) >= min_names)
        r = blank_before(r, int(ok[0]) if len(ok) else T - 1)
    return r


def bench_returns(panel: Panel) -> dict:
    """SPY / QQQ / SMH buy-and-hold and the two same-universe equal-weight series.
    EW_<u> is not live before the universe has MIN_NAMES eligible names;
    EW_<u>_incl_cash is the superseded variant that holds cash before that."""
    out = {b: buy_hold_returns(panel.adj_close[:, panel.col(b)]) for b in BENCH}
    for u, syms in UNIVERSES.items():
        cols = panel.cols(syms)
        el = eligibility(panel.bar[:, cols])
        out["EW_" + u] = equal_weight_returns(panel.adj_close[:, cols], el, panel.rf)
        out["EW_" + u + "_incl_cash"] = equal_weight_returns(panel.adj_close[:, cols], el,
                                                             panel.rf, blank_prelive=False)
    return out


def metric_rows(ret2d, rf, dates, bounds, bench: dict, ew_key, traded=None, fees=None, nav=None,
                include_first: bool = False):
    """Per window, per column of ret2d: metric dict + excess/IR vs SPY, QQQ, SMH and
    `ew_key` (reported in the *_EW columns). Returns {window: list of dicts}."""
    ret2d = np.asarray(ret2d, float)
    G = ret2d.shape[1]
    out = {}
    for w in WINDOW_ORDER:
        i0, i1 = bounds[w]
        m = window_perf(ret2d, rf, dates, i0, i1, include_first)
        j0 = live_start(ret2d, i0, include_first)
        if traded is not None:
            to, drag = turnover_stats(traded, fees, nav, j0, i1)
        rows = []
        for g in range(G):
            row = {k: (float(v[g]) if isinstance(v, np.ndarray) else v) for k, v in m.items()}
            row["window"] = w
            if traded is not None:
                row["turnover_ann"] = float(to[g])
                row["cost_drag_ann"] = float(drag[g])
            for label, key in (("SPY", "SPY"), ("QQQ", "QQQ"), ("SMH", "SMH"), ("EW", ew_key)):
                ex, ir = rel_perf(ret2d[:, g], bench[key], dates, i0, i1, include_first)
                row["excess_cagr_vs_" + label] = ex
                row["ir_vs_" + label] = ir
            rows.append(row)
        out[w] = rows
    return out


SENS_KEEP = ("n_days", "start_date", "cagr", "sharpe", "mdd", "calmar", "excess_cagr_vs_SPY",
             "ir_vs_SPY", "excess_cagr_vs_EW")


def sens_rows(variant, study, labels, ret2d, rf, dates, bounds, bench, ew_key,
              include_first: bool = False) -> list:
    """Rows of a labelled SENSITIVITY run (never a study cell, never in a pass line).
    labels: one (cell, cost) per column of ret2d."""
    by_w = metric_rows(ret2d, rf, dates, bounds, bench, ew_key, include_first=include_first)
    rows = []
    for g, (cell, cost) in enumerate(labels):
        for w in WINDOW_ORDER:
            r = {"study": study, "variant": variant, "cell": cell, "cost": cost, "window": w}
            r.update({k: by_w[w][g][k] for k in SENS_KEEP})
            rows.append(r)
    return rows


def calmar_better(cagr, mdd, bh_cagr, bh_mdd, mode="literal"):
    """Is the cell's Calmar 'better' than buy-and-hold's in one window?  (US-B pass_1)

    literal   : Calmar > buy-and-hold Calmar as plain numbers (the frozen clause).
                When both CAGRs are negative this ranking is inverted with respect to
                drawdown: a deeper drawdown gives a 'higher' (less negative) Calmar.
    economic  : both CAGR > 0 -> compare the ratios; cell > 0 >= buy-and-hold -> better;
                cell <= 0 < buy-and-hold -> worse; both <= 0 -> better only if the cell
                dominates (higher CAGR and a drawdown that is not deeper).
    strict    : literal AND economic (the most conservative reading).
    Inputs are arrays (or scalars); NaN in any input -> False."""
    cagr, mdd, bh_cagr, bh_mdd = (np.asarray(x, float) for x in (cagr, mdd, bh_cagr, bh_mdd))
    with np.errstate(divide="ignore", invalid="ignore"):
        cal = np.where(mdd < 0, cagr / np.abs(mdd), np.nan)
        bcal = np.where(bh_mdd < 0, bh_cagr / np.abs(bh_mdd), np.nan)
        lit = cal > bcal
        both_pos = (cagr > 0) & (bh_cagr > 0)
        eco = np.where(both_pos, lit,
                       np.where((cagr > 0) & (bh_cagr <= 0), True,
                                np.where((cagr <= 0) & (bh_cagr > 0), False,
                                         (cagr > bh_cagr) & (mdd >= bh_mdd))))
    ok = np.isfinite(cagr) & np.isfinite(mdd) & np.isfinite(bh_cagr) & np.isfinite(bh_mdd)
    eco = eco.astype(bool) & ok
    lit = lit & ok
    if mode == "literal":
        return lit
    if mode == "economic":
        return eco
    if mode == "strict":
        return lit & eco
    raise ValueError(mode)


# ------------------------------------------------------------------------- io
def ensure_dirs():
    os.makedirs(PARTS_DIR, exist_ok=True)


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, np.floating):
        return None if not np.isfinite(o) else float(o)
    return o


def write_json(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(_clean(obj), fh, ensure_ascii=False, indent=2, default=_json_default)
    os.replace(tmp, path)


def read_json(path: str):
    with open(path) as fh:
        return json.load(fh)


def write_csv(path: str, df: pd.DataFrame) -> None:
    tmp = path + ".tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)


# ===================================================================== report
EXC = ["SPY", "QQQ", "SMH", "EW"]
STUDY_NAME = {"US-A": "ETF 截面輪動", "US-B": "指數進出場", "US-C": "隔夜／盤中"}
VARIANT_NAME = {
    "first_day_incl": "窗第一天的報酬也算進去",
    "stag_entry": "各批錯開進場（輪到自己才建倉）",
    "exec_t1_close": "改在隔天收盤價成交",
    "exact_fee": "手續費用精確解",
    "suspect_open_fixed": "可疑開盤價改用前一日收盤",
}
LONG_H = [h for h in H_LIST if h >= 63]
SHORT_SIGNALS = ("ret_1", "ret_5")


def _load_parts():
    import glob

    def main_parts(prefix):
        return sorted(f for f in glob.glob(os.path.join(PARTS_DIR, prefix + "_*_H*.csv"))
                      if not f.endswith("_sens.csv") and "conflicted" not in f)
    usa, usb = main_parts("usa"), main_parts("usb")
    sens = sorted(f for f in glob.glob(os.path.join(PARTS_DIR, "us[ab]_*_sens.csv"))
                  if "conflicted" not in f)
    assert len(usa) == len(UNIVERSES) * len(H_LIST), "US-A parts incomplete: %d" % len(usa)
    assert len(usb) == len(BENCH) * len(H_LIST), "US-B parts incomplete: %d" % len(usb)
    assert len(sens) == len(usa) + len(usb), "sensitivity parts incomplete: %d" % len(sens)
    A = pd.concat([pd.read_csv(f) for f in usa], ignore_index=True)
    B = pd.concat([pd.read_csv(f) for f in usb], ignore_index=True)
    S = pd.concat([pd.read_csv(f) for f in sens], ignore_index=True)
    Cc = pd.read_csv(os.path.join(PARTS_DIR, "usc.csv"))
    assert A["cell"].nunique() == 196 and B["cell"].nunique() == 294
    metas = {os.path.basename(f)[:-10]: read_json(f)
             for f in sorted(glob.glob(os.path.join(PARTS_DIR, "us[ab]_*_meta.json")))
             if "conflicted" not in f}
    assert len(metas) == len(usa) + len(usb)
    return A, B, Cc, S, metas


def _bench_table(panel, bench, bounds, metas):
    rows = []
    ma_t0 = int(np.searchsorted(panel.dates, np.datetime64(metas["usa_MA_H1"]["t0_signal_date"])))
    series = {name: bench[name] for name in BENCH + ["EW_EQ", "EW_MA"]}
    series["SPY_same_days_as_MA"] = blank_before(bench["SPY"], ma_t0)
    notes = {"EW": "daily-rebalanced equal weight of eligible names, zero cost; not live "
                   "before the universe has 6 eligible names",
             "SPY_same_days_as_MA": "SPY buy-and-hold over the days the MA cells are live "
                                    "(reference for the MA universe)"}
    for name, ser in series.items():
        for w in WINDOW_ORDER:
            m = window_perf(ser, panel.rf, panel.dates, *bounds[w])
            ex, ir = rel_perf(ser, bench["SPY"], panel.dates, *bounds[w])
            r = {"study": "US-A/US-C", "benchmark": name, "window": w,
                 "note": ("buy-and-hold total return (adjusted close)" if name in BENCH else
                          notes["EW"] if name.startswith("EW_") else notes[name])}
            r.update({k: m[k] for k in METRIC_COLS})
            r.update(excess_cagr_vs_SPY=ex, ir_vs_SPY=ir)
            rows.append(r)
    for sym in BENCH:
        mt = metas["usb_%s_H1" % sym]
        for w in WINDOW_ORDER:
            r = {"study": "US-B", "benchmark": "BH_%s_same_days" % sym, "window": w,
                 "note": "buy-and-hold over the days the US-B cells are live (first trade %s)"
                         % mt["first_trade_date"]}
            r.update({k: mt["own_buy_hold"][w].get(k) for k in METRIC_COLS})
            rows.append(r)
    return pd.DataFrame(rows)


def _piv(df, cost, col):
    return df[df.cost == cost].pivot(index="cell", columns="window", values=col)


def _usb_clauses(df, cost, mode="literal"):
    """US-B pass_1 (Calmar better than buy-and-hold in all three windows, under the
    given reading of 'better') and pass_2 (full CAGR >= buy-and-hold - 1pp)."""
    d = df[(df.cost == cost) & df.window.isin(SUB_WINDOWS)]
    ok = calmar_better(d["cagr"], d["mdd"], d["bh_cagr"], d["bh_mdd"], mode)
    c1 = pd.Series(ok, index=d.index).groupby(d["cell"]).all()
    f = df[(df.cost == cost) & (df.window == "FULL")].set_index("cell")
    c2 = f["cagr"] >= f["bh_cagr"] - 0.01
    return c1, c2.reindex(c1.index)


def _pass_lines(A, B, bt):
    """Cell-level pass-line clauses, exactly the frozen pass lines (see summary)."""
    spy_mdd = bt[(bt.benchmark == "SPY") & (bt.study == "US-A/US-C")].set_index("window")["mdd"]

    a = pd.DataFrame(index=sorted(A["cell"].unique()))
    one = A[(A.cost == BASE) & (A.window == "FULL")].set_index("cell")
    a["null_p"] = one["null_p"]
    a["bh_q"] = bh_qvalues(a["null_p"].to_numpy())
    # alternative single-statistic readings, reported for transparency only
    a["bh_q_cagr_only"] = bh_qvalues(one["null_p_cagr"].reindex(a.index).to_numpy())
    a["bh_q_sharpe_only"] = bh_qvalues(one["null_p_sharpe"].reindex(a.index).to_numpy())
    a["bh_q_gross_diag"] = bh_qvalues(one["null_p_gross_cagr_diag"].reindex(a.index).to_numpy())
    a["pass_1"] = (_piv(A, BASE, "excess_cagr_vs_SPY")[SUB_WINDOWS] > 0).all(axis=1)
    a["pass_2"] = (_piv(A, BASE, "excess_cagr_vs_EW")[SUB_WINDOWS] > 0).all(axis=1)
    a["pass_3"] = a["bh_q"] < 0.10
    a["pass_4"] = ((_piv(A, STRESS, "excess_cagr_vs_SPY")[SUB_WINDOWS] > 0).all(axis=1)
                   & (_piv(A, STRESS, "excess_cagr_vs_EW")[SUB_WINDOWS] > 0).all(axis=1))
    mdd = _piv(A, BASE, "mdd")[WINDOW_ORDER]
    a["pass_5"] = (mdd.sub(spy_mdd[WINDOW_ORDER], axis=1) >= -0.10).all(axis=1)
    a["n_pass"] = a[["pass_1", "pass_2", "pass_3", "pass_4", "pass_5"]].sum(axis=1)
    a["nominated"] = a["n_pass"] == 5

    b = pd.DataFrame(index=sorted(B["cell"].unique()))
    one = B[(B.cost == BASE) & (B.window == "FULL")].set_index("cell")
    b["null_p"] = one["null_p"]
    b["bh_q"] = bh_qvalues(b["null_p"].to_numpy())
    b["bh_q_cagr_only"] = bh_qvalues(one["null_p_cagr"].reindex(b.index).to_numpy())
    b["bh_q_calmar_only"] = bh_qvalues(one["null_p_calmar"].reindex(b.index).to_numpy())
    b["pass_1"], b["pass_2"] = _usb_clauses(B, BASE, "literal")       # the frozen clause
    lit_cols = (_piv(B, BASE, "calmar")[SUB_WINDOWS] > _piv(B, BASE, "bh_calmar")[SUB_WINDOWS]).all(axis=1)
    assert (lit_cols.reindex(b.index) == b["pass_1"]).all()
    # two other readings of "Calmar better" when CAGRs are negative: transparency only
    b["pass_1_economic"] = _usb_clauses(B, BASE, "economic")[0]
    b["pass_1_strict"] = _usb_clauses(B, BASE, "strict")[0]
    b["pass_3"] = b["bh_q"] < 0.10
    s1, s2 = _usb_clauses(B, STRESS, "literal")
    b["pass_4"] = s1 & s2
    b["pass_5"] = np.nan
    b["n_pass"] = b[["pass_1", "pass_2", "pass_3", "pass_4"]].sum(axis=1)
    b["nominated"] = b["n_pass"] == 4
    return a, b


def closest_cells(p: pd.DataFrame, study: str, n: int = 8) -> list:
    """The n cells closest to the pass line. ONE ordering for summary.md and
    verdict.json: most clauses passed first; for US-B then the three-window Calmar
    clause; then the smaller null p; then the cell name (deterministic)."""
    d = p.copy()
    d["_cell"] = d.index
    by = ["n_pass", "pass_1", "null_p", "_cell"] if study == "US-B" else ["n_pass", "null_p", "_cell"]
    asc = [False, False, True, True] if study == "US-B" else [False, True, True]
    return list(d.sort_values(by, ascending=asc, kind="stable").head(n).index)


def _summ(g):
    out = {"n_cells": int(g["cell"].nunique())}
    for col, hi in (("cagr", True), ("sharpe", True), ("mdd", True), ("calmar", True)):
        out[col + "_median"] = g[col].median()
        out[col + "_best"] = g[col].max()
        out[col + "_worst"] = g[col].min()
    for b in EXC:
        e = g["excess_cagr_vs_" + b]
        out["excess_cagr_vs_%s_median" % b] = e.median()
        out["excess_cagr_vs_%s_best" % b] = e.max()
        out["excess_cagr_vs_%s_worst" % b] = e.min()
        out["share_beat_" + b] = float((e > 0).mean()) if e.notna().any() else np.nan
        out["n_beat_" + b] = int((e > 0).sum()) if e.notna().any() else np.nan
    out["turnover_ann_median"] = g["turnover_ann"].median()
    out["cost_drag_ann_median"] = g["cost_drag_ann"].median()
    for col in ("cagr", "sharpe", "calmar"):
        out["best_cell_by_" + col] = (g.loc[g[col].idxmax(), "cell"] if g[col].notna().any()
                                      else "")
    e = g["excess_cagr_vs_SPY"]
    out["best_cell_by_excess_vs_SPY"] = g.loc[e.idxmax(), "cell"] if e.notna().any() else ""
    out["n_nominated"] = int(g["nominated"].fillna(False).astype(bool).sum())
    # superseded convention (US-A only): pre-start cash counted inside the window
    for b in ("SPY", "EW"):
        col = "excess_cagr_vs_%s_incl_prestart_cash" % b
        e = g[col] if col in g else pd.Series(dtype=float)
        ok = len(e) and e.notna().any()
        out[col + "_median"] = e.median() if ok else np.nan
        out["share_beat_%s_incl_prestart_cash" % b] = float((e > 0).mean()) if ok else np.nan
    return out


def _horizon_summary(cells):
    rows = []
    for study, df in cells.groupby("study", sort=True):
        if study == "US-C":
            groups = [("ALL", df)] + [(u, d) for u, d in df.groupby("universe")]
            key = "signal"
        else:
            groups = ([("ALL", df)] + [(u, d) for u, d in df.groupby("universe")]
                      + [(u, d) for u, d in df.groupby("direction")])
            key = "H"
        for gname, d in groups:
            for (h, w, c), g in d.groupby([key, "window", "cost"], sort=False):
                r = {"study": study, "group": gname,
                     "H": (h if key == "H" else np.nan),
                     "h_label": ("H=%d" % h if key == "H" else str(h)), "window": w, "cost": c}
                r.update(_summ(g.reset_index(drop=True)))
                rows.append(r)
    hs = pd.DataFrame(rows)
    hs["_w"] = hs["window"].map({w: i for i, w in enumerate(WINDOW_ORDER)})
    hs = hs.sort_values(["study", "group", "cost", "_w", "H", "h_label"], kind="stable")
    return hs.drop(columns="_w").reset_index(drop=True)


# ------------------------------------------------------------- sensitivities
SENS_FROZEN = ["cagr", "sharpe", "mdd", "calmar", "excess_cagr_vs_SPY", "excess_cagr_vs_EW"]


def _sens_frame(S, cells):
    """Sensitivity rows next to the frozen value of the same cell x cost x window."""
    key = ["cell", "cost", "window"]
    fz = cells[cells.study.isin(["US-A", "US-B"])][key + ["universe", "signal", "direction", "L", "H"]
                                                   + SENS_FROZEN]
    fz = fz.rename(columns={c: c + "_frozen" for c in SENS_FROZEN})
    out = S.merge(fz, on=key, how="left", validate="many_to_one")
    assert out["H"].notna().all()
    out["H"] = out["H"].astype(int)
    out["d_cagr"] = out["cagr"] - out["cagr_frozen"]
    out["variant_note"] = "SENSITIVITY ONLY - not a study cell, not in any pass line"
    lead = ["study", "variant", "cell", "universe", "signal", "direction", "L", "H", "cost", "window"]
    return out[lead + [c for c in out.columns if c not in lead]]


def _sens_summary(SF):
    rows = []
    for (study, variant), d0 in SF.groupby(["study", "variant"], sort=True):
        groups = [("ALL", d0)] + [(u, d) for u, d in d0.groupby("universe")]
        for gname, d in groups:
            for (h, w, c), g in d.groupby(["H", "window", "cost"], sort=True):
                r = {"study": study, "variant": variant, "group": gname, "H": int(h), "window": w,
                     "cost": c, "n_cells": int(len(g)),
                     "cagr_median_frozen": g["cagr_frozen"].median(),
                     "cagr_median_variant": g["cagr"].median(),
                     "max_abs_d_cagr": g["d_cagr"].abs().max(),
                     "median_abs_d_cagr": g["d_cagr"].abs().median()}
                for b in ("SPY", "EW"):
                    v, f = g["excess_cagr_vs_" + b], g["excess_cagr_vs_%s_frozen" % b]
                    r["excess_cagr_vs_%s_median_frozen" % b] = f.median()
                    r["excess_cagr_vs_%s_median_variant" % b] = v.median()
                    r["n_beat_%s_frozen" % b] = int((f > 0).sum())
                    r["n_beat_%s_variant" % b] = int((v > 0).sum())
                    r["n_sign_flips_vs_" + b] = int(((v > 0) != (f > 0)).sum())
                rows.append(r)
    out = pd.DataFrame(rows)
    out["_w"] = out["window"].map({w: i for i, w in enumerate(WINDOW_ORDER)})
    out = out.sort_values(["study", "variant", "group", "cost", "_w", "H"], kind="stable")
    return out.drop(columns="_w").reset_index(drop=True)


def _variant_pass_counts(SF, study, variant):
    """Pass-line clauses recomputed on a sensitivity variant (null / BH not re-run)."""
    d = SF[(SF.study == study) & (SF.variant == variant)]
    if d.empty:
        return {}
    if study == "US-A":
        p1 = (_piv(d, BASE, "excess_cagr_vs_SPY")[SUB_WINDOWS] > 0).all(axis=1)
        p2 = (_piv(d, BASE, "excess_cagr_vs_EW")[SUB_WINDOWS] > 0).all(axis=1)
        p4 = ((_piv(d, STRESS, "excess_cagr_vs_SPY")[SUB_WINDOWS] > 0).all(axis=1)
              & (_piv(d, STRESS, "excess_cagr_vs_EW")[SUB_WINDOWS] > 0).all(axis=1))
        wb = _piv(d, BASE, "excess_cagr_vs_SPY")["Wb"]
        return {"n_cells": int(len(p1)), "pass_1": int(p1.sum()), "pass_2": int(p2.sum()),
                "pass_4": int(p4.sum()), "pass_1_and_2": int((p1 & p2).sum()),
                "n_beat_SPY_in_Wb": int((wb > 0).sum())}
    p1, p2 = _usb_clauses(d, BASE)
    s1, s2 = _usb_clauses(d, STRESS)
    return {"n_cells": int(len(p1)), "pass_1": int(p1.sum()), "pass_2": int(p2.sum()),
            "pass_4": int((s1 & s2).sum()), "pass_1_and_2": int((p1 & p2).sum())}


def _pct(x, d=1):
    return "n/a" if x is None or not np.isfinite(x) else "%.*f%%" % (d, 100 * x)


def _pp(x, d=1):
    return "n/a" if x is None or not np.isfinite(x) else "%+.*fpp" % (d, 100 * x)


def _ppabs(x, d=2):
    return "n/a" if x is None or not np.isfinite(x) else "%.*fpp" % (d, 100 * abs(x))


def _num(x, d=2):
    return "n/a" if x is None or not np.isfinite(x) else "%.*f" % (d, x)


def _md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _short(cell):
    return cell.split("|", 1)[1].replace("|", " ")


# Templates: {name} placeholders are filled from the measured `facts` of the run.
DEVIATIONS = [
    "窗內績效的起算點：淨值 V=1 定在該窗第一個交易日的收盤，報酬從下一個交易日算起，CAGR 用這兩個收盤之間的日曆天。"
    "這與個股那一半（stk_common.py）相同。代價是每個窗第一天的報酬不屬於任何一個子窗。"
    "若把第一天也算進去，SPY 在 Wb 的 CAGR 會從 {spy_wb} 變成 {spy_wb_alt}。SPY 在 Wc 會從 {spy_wc} 變成 {spy_wc_alt}。"
    "策略與基準用同一個算法，所以超額幾乎不變：US-A 的 {fd_n} 個「格 × 子窗」裡，對 SPY 超額的正負號有 {fd_flips} 個改變。"
    "三窗都贏 SPY 的格數仍是 {fd_p1}。這個算法沒有改，只補上影響大小（`sensitivity.csv` 的 first_day_incl）。",
    "分批：每一批是獨立的子帳戶，組合淨值是各批淨值的平均，批與批之間不再平衡。第 k 批的起始偏移 = floor(k×H÷批數)。"
    "凍結的格子採「模擬第一天所有批次同時建倉，之後各批照自己的偏移每 H 日換一次」；這是本次執行指令指定的讀法，好處是第一天就滿倉。"
    "規格原文寫「起始日錯開」，字面讀法是各批輪到自己才建倉、之前抱現金。"
    "多數序列在評估窗開始前沒有暖身期，所以頭 H 天所有批次抱的是同一天選出來的部位。"
    "兩種讀法在 H ≤ 21 幾乎沒有差別，全期 CAGR 單格最多差 {stag_short_max}。"
    "在 H ≥ 63 有差別。US-A 單格最多差 {stagA_max}。US-B 單格最多差 {stagB_max}。"
    "這個選擇是中性的，不是較保守的讀法。字面讀法列為敏感度（表 3f、表 4d、`sensitivity.csv` 的 stag_entry），不進及格線。",
    "US-A 的模擬起點與「尚未上線」的日子：起點是該宇宙第一次有 6 檔以上可選的那天（EQ 是 {eq_t0}，MA 是 {ma_t0}）。"
    "在那之前，格子與同宇宙等權基準都視為尚未上線，不計入任何績效。對 SPY／QQQ／SMH 的超額只用雙方都上線的日子，與 US-B 的做法相同。"
    "上一版把那段期間當成「抱現金領 T-bill 利息」並計入 Wa 與全期，等於讓 MA 的格子拿三年半的利息去跟 2000–2003 年下跌中的 SPY 比。"
    "舊算法的數字保留在 `*_incl_prestart_cash` 欄位，只供對照。"
    "副作用：EQ 的全期從 2000 年初算起，MA 的全期從 2003 年年中算起，兩者的 CAGR 不能直接相比；跨宇宙比較請看「對 SPY 超額」。",
    "US-A「可選檔數 < 6 不開倉」：若建倉後某天可選檔數掉到 6 以下，所有批次隔天開盤出清，回到 6 檔以上再進場。實際資料中建倉後沒有發生過。",
    "US-A 排名同分時以清單順序決勝，不引入隨機。入選資格 = 當天有報價，而且之前至少有 252 根日線。",
    "US-A「贏」的定義：同一個窗、同一段日期的 CAGR 比基準高。對 QQQ／SMH 的超額只在雙方都有資料的日子計算（SMH 從 2000-05-05 起）。",
    "US-A 的隨機對照（null）：每一批每次換倉時從可選名單隨機抽 3 檔，同時程、base 成本，200 組。p 值是單尾，"
    "取全期 CAGR 與全期 Sharpe 兩個 p 之中較大的那個（較保守）。200 組的 p 最小只能到 1/201。",
    "US-A 的 MDD 條款：規格沒寫是哪個窗，採最嚴格的讀法：三窗與全期四個窗都不能比 SPY 深超過 10pp。",
    "US-A 的 10bp 條款：10bp 下三窗仍同時贏 SPY 與同宇宙等權才算過。",
    "US-B 的起算日：每個標的一律等到自己累積滿 252 根日線才開始（SPY 1999-01-04、QQQ 2000-03-08、SMH 2001-05-07），"
    "七個回看長度 L 用同一個起點。買進持有的比較對象也只算同一段日子。這樣長 L 不會因為「還沒訊號所以抱現金」而白賺。",
    "US-B 的反向版本 = 順勢版本的補集：過去 L 日報酬 ≤ 0 才持有，其餘時間放 T-bill。",
    "US-B 的 null：把每一批的部位序列用同一個位移量做圓形位移，位移量在 252 到（天數 − 252）之間不重複抽 1,000 個。"
    "統計量是全期 base 成本的 CAGR 與 Calmar，null_p 取兩者較大的 p。null 用向量化算法，從全期窗起點把各批淨值重設為 1；"
    "與主引擎的全期 CAGR 差距最大 {fast_gap}（只有 SPY 有差，因為它在窗之前已跑了一年）。",
    "US-B 的 Calmar 條款遇到負報酬時的讀法：凍結的條款直接比較 Calmar 的數值。"
    "Wa 窗三檔買進持有的 CAGR 都是負的，Calmar 也是負的；兩個負數相比時，回撤越深的 Calmar 反而越「高」，排序會顛倒。"
    "Wa 有 {cal_perv} 個「格 × 窗」的 CAGR 與 MDD 都優於買進持有，卻被判成 Calmar 沒有比較好；反方向（兩項都較差卻被判成較好）有 {cal_perv_rev} 個。"
    "另外算了兩種讀法。經濟讀法：兩邊 CAGR 都為正才比比值；兩邊都不為正時，要 CAGR 較高而且回撤不更深才算優。嚴格讀法：字面與經濟兩種都成立。"
    "{cal_counts_txt}與 pass_2 同時成立的格數是 {cal_joint}。"
    "正式的 pass_1 欄位維持字面讀法；另外兩種放在 `pass_1_economic`、`pass_1_strict` 欄。",
    "US-B 沒有「同宇宙等權」：欄位 excess_cagr_vs_EW／ir_vs_EW 放的是同一標的、同一段日子的買進持有。US-C 也一樣。",
    "US-B 的 10bp 條款：Calmar 三窗條款與全期 CAGR 條款在 10bp 下重算都要成立；null 只在 base 成本算。",
    "US-C：閒置的半天不計現金利息，所以隔夜段 × 盤中段剛好等於一直抱。兩條交易腿每天算兩邊成本。"
    "打平成本 = 讓該窗淨總報酬剛好為零的每邊成本；另附一欄「打平到等於一直抱」。一直抱那條沒有交易成本。",
    "現金利率：用嚴格早於當天的最後一筆 ^IRX 值 ÷100 ÷252，利息在隔夜那一段入帳；^IRX 開始前視為 0。",
    "手續費是一階近似，不是精確解：費用 = 成本 × |目標部位 − 現有部位|，其中目標部位用扣費前的淨值計算。"
    "精確解要用扣費後的淨值反覆代入到收斂。兩者在 US-A 全部格、全部窗、全部成本下，CAGR 最多差 {fee_max}（`sensitivity.csv` 的 exact_fee）。",
    "壞資料過濾只用規格寫的兩條（價格 ≤ 0、相鄰還原收盤比 >5 或 <0.2），結果沒有任何一根被剔除。隔夜跳空超過 15% 的日線只記錄不剔除。"
    "其中 XLV 2002-01-08 的開盤價是 22.44，前一日收盤是 27.65，看起來是錯價。規格沒有這種過濾，所以保留。"
    "把它換成前一日收盤價重跑 EQ 宇宙（敏感度 suspect_open_fixed），持有 1 日的格子受影響最大。它們的 CAGR 在 Wa 最多差 {xlv_wa_h1}，在全期最多差 {xlv_full_h1}。"
    "持有 5 日以上的格子在任何窗最多差 {xlv_h5p}。"
    "MDY 與 DIA 在第一筆交易（{eq_first_trade}）之前各有 {fill_pre} 根「開盤價等於收盤價」的日線，是資料商補值。那段期間沒有任何交易，所以不影響結果。",
    "額外的診斷欄 null_p_gross_cagr_diag（同一組隨機選股在零成本下的比較）、sanity anchor 的各個版本、以及 `sensitivity.csv` 的全部列，"
    "都不是研究的格子，不進及格線、不進 BH 校正。",
]

CAVEATS = [
    "全部結果是描述性的，只能提名。2018 年以後的資料在 fadacai-etf-rotation 已經是「用掉的窗」，這裡沒有任何一段是沒看過的樣本外資料。",
    "一共看了 196 + 294 格。從這麼多格裡挑出來的「最佳格」一定高估，所以週期層的結論只看中位數與贏基準的比例。",
    "持有 63 日以上的列對「分批第一天怎麼進場」敏感（偏離第 2 條、表 3f、表 4d）。不要在 63、126、252 日這三個週期之間排名次。",
    "US-A 的隨機對照偏鬆，有三個原因。第一，隨機選股每次換倉幾乎全換，短週期的成本遠高於慢訊號，慢訊號在短 H 會「因為少交易」而贏。"
    "第二，21 批各自獨立抽籤，等於分散到幾十檔，分布比真正只抱 3 檔的策略窄很多。"
    "第三，它不控制風格偏向。「1 日訊號配 63 日以上持有」的 12 格本質上接近隨機選股，卻有 {n_rand_min} 格在 CAGR 的 p 上拿到最小值；"
    "可能的原因是單日漲跌最極端的名單偏向高波動 ETF。",
    "200 組隨機的 p 最小是 0.005；196 格做 BH 校正時，至少要有 10 格同時達到最小 p 才可能有任何一格 q < 0.10。",
    "ETF 名單是今天回頭選的：QQQ、SMH 這些事後最強的標的在名單裡，本身就是後見之明。等權基準也吃到同樣的偏差。",
    "早年宇宙很小：EQ 在 2000 年初只有 12 檔可選，MA 要到 2003 年年中才湊滿 6 檔。Wa 的結果比後兩窗更不可靠，MA 的 Wa 也沒有經過 2000–2002 年的空頭。",
    "成交價假設是還原後的開盤價，加上固定的每邊成本，沒有另外模擬價差、滑價與稅。早年成交量小的 ETF，開盤價本身可能不準。"
    "短訊號、短週期的格子特別依賴這個假設（表 3g）。把成交改到隔天收盤後，全期對 SPY 超額最高的那一格（{best_cell}）的 CAGR 從 {best_open} 變成 {best_close}。"
    "受影響最大的是訊號只看 1 或 5 日、而且持有不超過 5 日的那 {n_short} 格。它們全期 CAGR 的變動中位數是 {short_med}，最大 {short_max}。"
    "其餘 {n_other} 格的變動中位數是 {other_med}。所以短週期反轉那幾格的好成績不能當成穩健的結果。",
    "SMH 在 2011 年以前是 HOLDRS 結構（固定持股的信託，不是指數型 ETF），那一段的價格不能當成今天這檔 SMH 的歷史。",
    "US-B 的 QQQ 起算日 2000-03-08 幾乎就是網路泡沫高點，SMH 則是從 2001-05 才開始；兩者的 Wa 都不是完整的十年。",
    "US-C 的隔夜／盤中策略需要每天在收盤與開盤各成交一次；每邊 1–2bp 的成本對散戶帳戶並不實際，而且績效對開盤價的品質非常敏感。",
    "Sharpe 依專案慣例不扣無風險利率；扣掉 T-bill 的版本在 sharpe_ex 欄。現金部位多的格子（US-B）兩者差距較大。",
]

PRIOR_RESULT = {
    "source": "fadacai-etf-rotation (docs/protocol/PREREGISTRATION.md section 3, configs/default.yaml)",
    "rule": "primary arm A1: 11 SPDR sector funds, rank-mean of 126/189/252-session returns, top 3, "
            "each slot to the cash proxy unless the fund is above its 210-session average, "
            "3 tranches (offsets 0/7/14), 21-session grid, 5 bps per side",
    "reported_excess_cagr_vs_SPY_2018_2025": -0.073,
}
ANCHOR_STEPS = [
    ("EQ_27", "EQ 27 檔", "252 日單一回看", "無", "21 批", "預註冊的格子（US-A EQ ret_252 momentum H21）"),
    ("EQ_27_ensemble", "EQ 27 檔", "126／189／252 日排名平均", "無", "21 批", "只換訊號"),
    ("EQ_27_ensemble_sma210", "EQ 27 檔", "126／189／252 日排名平均", "有", "21 批", "再加均線濾網"),
    ("SECTORS_11", "11 檔類股", "252 日單一回看", "無", "21 批", "只換宇宙"),
    ("SECTORS_11_ensemble", "11 檔類股", "126／189／252 日排名平均", "無", "21 批", "換宇宙與訊號"),
    ("SECTORS_11_ensemble_sma210", "11 檔類股", "126／189／252 日排名平均", "有", "21 批", "再加均線濾網"),
    ("SECTORS_11_ensemble_sma210_3tranches", "11 檔類股", "126／189／252 日排名平均", "有", "3 批",
     "舊專案主規則的對照版（like-for-like）"),
    ("PRIOR_U3_19_ensemble", "舊專案 19 檔", "126／189／252 日排名平均", "無", "21 批", "舊專案的穩健性宇宙"),
    ("PRIOR_U3_19_ensemble_sma210", "舊專案 19 檔", "126／189／252 日排名平均", "有", "21 批", "同上，加均線濾網"),
]
LIKE_FOR_LIKE = "SECTORS_11_ensemble_sma210_3tranches"


def _anchors(panel, bench, bounds, A, anchor_diag):
    out = {}
    spy = bench["SPY"]
    for w in SUB_WINDOWS + ["FULL"]:
        i0, i1 = bounds[w]
        m = window_perf(spy, panel.rf, panel.dates, i0, i1)
        alt = window_perf(spy, panel.rf, panel.dates, i0, i1, include_first=True)
        out["SPY_buy_hold_" + w] = {
            "start": m["start_date"], "end": m["end_date"], "cagr": m["cagr"], "sharpe": m["sharpe"],
            "mdd": m["mdd"], "cagr_if_first_day_return_included": alt["cagr"],
            "sharpe_if_first_day_return_included": alt["sharpe"]}
    out["expected"] = {"Wb": "CAGR roughly 13%", "Wa": "CAGR roughly -1%, MDD about -55%",
                       "Wc": "CAGR roughly 14.2%, MDD about -33.7%, Sharpe about 0.78"}
    cell = A[(A.universe == "EQ") & (A.signal == "ret_252") & (A.direction == "momentum")
             & (A.H == 21) & (A.cost == BASE)].set_index("window")
    out["EQ_ret252_momentum_H21_base"] = {
        w: {"cagr": float(cell.loc[w, "cagr"]),
            "excess_cagr_vs_SPY": float(cell.loc[w, "excess_cagr_vs_SPY"])} for w in WINDOW_ORDER}
    out["prior_result"] = PRIOR_RESULT
    out["pre_registered_cell_is_the_prior_rule"] = False
    out["why_not_the_same_rule"] = ("the pre-registered cell uses the 27-name EQ universe, a single "
                                    "252-session lookback, no trend filter and 21 tranches")
    out["prior_rule_diagnostics"] = anchor_diag
    wc = lambda k: anchor_diag.get(k, {}).get("Wc", {}).get("excess_cagr_vs_SPY")  # noqa: E731
    like = wc(LIKE_FOR_LIKE)
    out["like_for_like_key"] = LIKE_FOR_LIKE
    out["like_for_like_Wc_excess_cagr_vs_SPY"] = like
    out["prior_result_reproduced_in_direction_by_like_for_like"] = (
        bool(like < 0) if like is not None else None)
    out["like_for_like_minus_prior_result_pp"] = (
        float(100 * (like - PRIOR_RESULT["reported_excess_cagr_vs_SPY_2018_2025"]))
        if like is not None else None)
    ens = wc("EQ_27_ensemble")
    out["pre_registered_cell_Wc_excess_is_fragile"] = (
        bool(float(cell.loc["Wc", "excess_cagr_vs_SPY"]) > 0 > ens) if ens is not None else None)
    return out


def _facts(cells, SF, SS, a_pass, b_pass, anchors, panel, metas):
    A = cells[cells.study == "US-A"]
    B = cells[cells.study == "US-B"]
    f = {}
    an = anchors
    f["spy_wb"] = _pct(an["SPY_buy_hold_Wb"]["cagr"], 2)
    f["spy_wb_alt"] = _pct(an["SPY_buy_hold_Wb"]["cagr_if_first_day_return_included"], 2)
    f["spy_wc"] = _pct(an["SPY_buy_hold_Wc"]["cagr"], 2)
    f["spy_wc_alt"] = _pct(an["SPY_buy_hold_Wc"]["cagr_if_first_day_return_included"], 2)

    def ss(study, variant, **kw):
        d = SS[(SS.study == study) & (SS.variant == variant) & (SS.group == kw.pop("group", "ALL"))
               & (SS.cost == kw.pop("cost", BASE))]
        for k, v in kw.items():
            d = d[d[k].isin(v)] if isinstance(v, (list, tuple)) else d[d[k] == v]
        return d

    fd = ss("US-A", "first_day_incl", window=SUB_WINDOWS)
    f["fd_n"] = int(fd["n_cells"].sum())
    f["fd_flips"] = int(fd["n_sign_flips_vs_SPY"].sum())
    f["fd_p1"] = _variant_pass_counts(SF, "US-A", "first_day_incl")["pass_1"]
    f["_fd_pass_usa"] = _variant_pass_counts(SF, "US-A", "first_day_incl")
    f["_fd_pass_usb"] = _variant_pass_counts(SF, "US-B", "first_day_incl")

    sa, sb = ss("US-A", "stag_entry", window="FULL"), ss("US-B", "stag_entry", window="FULL")
    f["_stagA_max"] = float(sa[sa.H >= 63]["max_abs_d_cagr"].max())
    f["_stagB_max"] = float(sb[sb.H >= 63]["max_abs_d_cagr"].max())
    f["_stag_short_max"] = float(max(sa[sa.H <= 21]["max_abs_d_cagr"].max(),
                                     sb[sb.H <= 21]["max_abs_d_cagr"].max()))
    f["stagA_max"], f["stagB_max"] = _ppabs(f["_stagA_max"]), _ppabs(f["_stagB_max"])
    f["stag_short_max"] = _ppabs(f["_stag_short_max"])
    f["_stagA_max_wa"] = float(ss("US-A", "stag_entry", window="Wa")["max_abs_d_cagr"].max())
    f["_stag_pass_usa"] = _variant_pass_counts(SF, "US-A", "stag_entry")
    f["_stag_pass_usb"] = _variant_pass_counts(SF, "US-B", "stag_entry")
    sfb = SF[(SF.study == "US-B") & (SF.variant == "stag_entry") & (SF.cost == BASE)
             & (SF.window == "FULL")]
    f["_stagB_max_by_symbol"] = {u: float(g["d_cagr"].abs().max()) for u, g in sfb.groupby("universe")}

    f["eq_t0"] = metas["usa_EQ_H1"]["t0_signal_date"]
    f["ma_t0"] = metas["usa_MA_H1"]["t0_signal_date"]
    f["eq_first_trade"] = metas["usa_EQ_H1"]["first_trade_date"]
    f["fast_gap"] = _ppabs(max(v["max_abs_gap_fast_vs_engine_full_cagr"]
                               for k, v in metas.items() if k.startswith("usb_")))

    sub = B[(B.cost == BASE) & B.window.isin(SUB_WINDOWS)]
    lit = calmar_better(sub["cagr"], sub["mdd"], sub["bh_cagr"], sub["bh_mdd"], "literal")
    dom = ((sub["cagr"] > sub["bh_cagr"]) & (sub["mdd"] > sub["bh_mdd"])).to_numpy()
    sub_dom = ((sub["cagr"] < sub["bh_cagr"]) & (sub["mdd"] < sub["bh_mdd"])).to_numpy()
    f["cal_perv"] = int((dom & ~lit).sum())
    f["cal_perv_rev"] = int((sub_dom & lit).sum())
    f["_cal_perv_windows"] = sorted(sub.loc[dom & ~lit, "window"].unique().tolist())
    f["cal_lit"] = int(b_pass["pass_1"].sum())
    f["cal_eco"] = int(b_pass["pass_1_economic"].sum())
    f["cal_strict"] = int(b_pass["pass_1_strict"].sum())
    f["_cal_same_cells"] = bool((b_pass["pass_1"] == b_pass["pass_1_economic"]).all())
    joint = [int((b_pass[c] & b_pass["pass_2"]).sum()) for c in ("pass_1", "pass_1_economic",
                                                                "pass_1_strict")]
    f["cal_joint"] = "、".join(str(x) for x in sorted(set(joint)))
    if f["cal_lit"] == f["cal_eco"] == f["cal_strict"] and f["_cal_same_cells"]:
        f["cal_counts_txt"] = "三種讀法的 pass_1 都是 %d 格，而且是同一批格子。" % f["cal_lit"]
    else:
        f["cal_counts_txt"] = ("字面讀法的 pass_1 是 %d 格。經濟讀法是 %d 格。嚴格讀法是 %d 格。"
                               % (f["cal_lit"], f["cal_eco"], f["cal_strict"]))
    f["_cal_joint"] = joint

    ef = SF[(SF.study == "US-A") & (SF.variant == "exact_fee")]
    f["_fee_max"] = float(ef["d_cagr"].abs().max())
    f["fee_max"] = _ppabs(f["_fee_max"], 3)
    f["_fee_max_at"] = ef.loc[ef["d_cagr"].abs().idxmax(), ["cell", "cost", "window"]].tolist()

    xo = SF[(SF.study == "US-A") & (SF.variant == "suspect_open_fixed") & (SF.cost == BASE)]
    f["_xlv_wa_h1"] = float(xo[(xo.H == 1) & (xo.window == "Wa")]["d_cagr"].abs().max())
    f["_xlv_full_h1"] = float(xo[(xo.H == 1) & (xo.window == "FULL")]["d_cagr"].abs().max())
    f["_xlv_h5p"] = float(xo[xo.H >= 5]["d_cagr"].abs().max())
    f["xlv_wa_h1"], f["xlv_full_h1"] = _ppabs(f["_xlv_wa_h1"]), _ppabs(f["_xlv_full_h1"])
    f["xlv_h5p"] = _ppabs(f["_xlv_h5p"])
    f["_xlv_flips_vs_EW_Wa"] = int(ss("US-A", "suspect_open_fixed", window="Wa")["n_sign_flips_vs_EW"].sum())

    first_trade = f["eq_first_trade"]
    fills = {}
    for s in ("MDY", "DIA"):
        df = load_symbol(s)
        eq = df[df["open"] == df["close"]]
        fills[s] = {"before_first_trade": int((eq["date"] < first_trade).sum()),
                    "in_1998_1999": int((eq["date"] < "2000-01-01").sum()),
                    "from_first_trade_on": int((eq["date"] >= first_trade).sum())}
    f["_open_equals_close"] = fills
    f["fill_pre"] = "／".join(str(fills[s]["before_first_trade"]) for s in ("MDY", "DIA"))

    ce = SF[(SF.study == "US-A") & (SF.variant == "exec_t1_close") & (SF.cost == BASE)
            & (SF.window == "FULL")]
    best = ce.loc[ce["excess_cagr_vs_SPY_frozen"].idxmax()]
    f["best_cell"] = _short(best["cell"])
    f["best_open"], f["best_close"] = _pct(best["cagr_frozen"]), _pct(best["cagr"])
    f["_best_cell"] = {"cell": best["cell"], "cagr_open_fill": float(best["cagr_frozen"]),
                       "cagr_t1_close_fill": float(best["cagr"]),
                       "excess_vs_SPY_open_fill": float(best["excess_cagr_vs_SPY_frozen"]),
                       "excess_vs_SPY_t1_close_fill": float(best["excess_cagr_vs_SPY"])}
    short = ce["signal"].isin(SHORT_SIGNALS) & (ce["H"] <= 5)
    f["n_short"], f["n_other"] = int(short.sum()), int((~short).sum())
    f["_short_med"] = float(ce.loc[short, "d_cagr"].abs().median())
    f["_short_max"] = float(ce.loc[short, "d_cagr"].abs().max())
    f["_other_med"] = float(ce.loc[~short, "d_cagr"].abs().median())
    f["short_med"], f["short_max"] = _ppabs(f["_short_med"]), _ppabs(f["_short_max"])
    f["other_med"] = _ppabs(f["_other_med"])
    f["_exec_pass_usa"] = _variant_pass_counts(SF, "US-A", "exec_t1_close")

    af = A[(A.cost == BASE) & (A.window == "FULL")]
    f["_n_beat_spy_full"] = int((af["excess_cagr_vs_SPY"] > 0).sum())
    f["_n_beat_spy_full_incl_cash"] = int((af["excess_cagr_vs_SPY_incl_prestart_cash"] > 0).sum())
    ma = af[af.universe == "MA"]
    f["_n_beat_spy_full_MA"] = int((ma["excess_cagr_vs_SPY"] > 0).sum())
    f["_n_beat_spy_full_MA_incl_cash"] = int((ma["excess_cagr_vs_SPY_incl_prestart_cash"] > 0).sum())
    near_random = A[(A.signal == "ret_1") & (A.H >= 63) & (A.cost == BASE) & (A.window == "FULL")]
    assert len(near_random) == 12
    f["n_rand_min"] = int((near_random["null_p_cagr"] <= 1.0 / (N_NULL_XS + 1) + 1e-12).sum())
    return f


def _summary_md(cells, bt, hs, a_pass, b_pass, verdict, metas, panel, SF, SS, facts):
    L = []
    add = L.append
    hsA = hs[(hs.study == "US-A") & (hs.group == "ALL") & (hs.window == "FULL")
             & (hs.cost == BASE)].sort_values("H").reset_index(drop=True)
    hsB = hs[(hs.study == "US-B") & (hs.group == "ALL") & (hs.window == "FULL")
             & (hs.cost == BASE)].sort_values("H").reset_index(drop=True)
    nA, nB = int(a_pass["nominated"].sum()), int(b_pass["nominated"].sum())
    Ab = cells[(cells.study == "US-A") & (cells.cost == BASE)]
    Bb = cells[(cells.study == "US-B") & (cells.cost == BASE)]
    Cg = cells[(cells.study == "US-C")]

    def ss(study, variant, window="FULL", cost=BASE, group="ALL"):
        d = SS[(SS.study == study) & (SS.variant == variant) & (SS.group == group)
               & (SS.cost == cost) & (SS.window == window)]
        return d.set_index("H")

    stA, stB = ss("US-A", "stag_entry"), ss("US-B", "stag_entry")
    stA_wa = ss("US-A", "stag_entry", "Wa")
    exA = ss("US-A", "exec_t1_close")

    # ----- numbers used in sections 0 and 6
    med = hsA.set_index("H")["excess_cagr_vs_SPY_median"]
    h_lo, h_hi = int(med.idxmin()), int(med.idxmax())
    all_neg = bool((med < 0).all())
    long_spread = float(med[LONG_H].max() - med[LONG_H].min())
    med_st = stA["excess_cagr_vs_SPY_median_variant"]
    h_hi_st = int(med_st.idxmax())
    h_long = max(H_LIST)
    n_long, n_long_st = int(stA.loc[h_long, "n_beat_SPY_frozen"]), int(stA.loc[h_long, "n_beat_SPY_variant"])
    n_beat_full = facts["_n_beat_spy_full"]
    n_p1 = verdict["counts"]["US-A"]["pass_1"]
    Bf = Bb[Bb.window == "FULL"]
    b_med_ex = float(Bf["excess_cagr_vs_EW"].median())
    b_n_beat = int((Bf["excess_cagr_vs_EW"] > 0).sum())
    b_mdd_gain = float((Bf["mdd"] - Bf["bh_mdd"]).median())
    cfull = Cg[(Cg.window == "FULL")]

    def be(sym, leg="overnight"):
        return float(cfull[(cfull.universe == sym) & (cfull.signal == leg)
                           & (cfull.cost == "gross_0bp")]["breakeven_bps_per_side"].iloc[0])

    def ccagr(sym, leg, cost):
        return float(cfull[(cfull.universe == sym) & (cfull.signal == leg)
                           & (cfull.cost == cost)]["cagr"].iloc[0])
    on_dom = all(ccagr(s, "overnight", "gross_0bp") > ccagr(s, "intraday", "gross_0bp") for s in BENCH)
    on5_neg = all(ccagr(s, "overnight", "5bp") < 0 for s in BENCH)

    add("# 持有週期研究（美股 ETF 半邊）：US-A／US-B／US-C 結果（修正版）")
    add("")
    add("規格：`research/horizon-study-2026-11-18.md`（已凍結，未修改）。回測終點一律 2025-12-31，2026 年的資料讀檔後立刻丟棄。"
        "本版是獨立驗證之後的修正版，取代 `etf.superseded-1/` 裡的上一版；改了什麼見 0a 節。產出時間：%s。"
        % verdict["generated_at"])
    add("")
    add("## 0. 結論（先讀這段）")
    add("")
    add("1. 以下全部是描述性結果，只能提名，不能當成已驗證的策略。ETF 輪動（US-A）的 196 格裡，通過全部事前及格線的有 %d 格。"
        "指數進出場（US-B）的 294 格裡有 %d 格。" % (nA, nB))
    add("2. ETF 輪動：%s。這裡的「典型」是同一個持有週期下 28 個訊號組合「對 SPY 超額報酬」的中位數，每一格只跟同一段日子的 SPY 比。"
        "最差的是持有 %d 日，中位數 %s。最好的是持有 %d 日，中位數 %s。"
        % ("沒有任何一個持有週期的典型結果贏過大盤" if all_neg else "只有部分持有週期的典型結果贏過大盤",
           h_lo, _pp(med[h_lo]), h_hi, _pp(med[h_hi])))
    add("3. 持有 63 日以上的三個週期分不出高下。它們的中位數彼此只差 %s。最長的週期對算法最敏感："
        "把「各批第一天一起進場」改成「各批錯開進場」，它全期贏過 SPY 的格數就從 %d 格變成 %d 格。"
        "全部 196 格裡，三個時間窗都贏 SPY 的有 %d 格。"
        % (_ppabs(long_spread, 1), n_long, n_long_st, n_p1))
    add("4. 指數進出場：看過去報酬決定抱或不抱，典型結果是回撤變淺、報酬變低。全期年化報酬的中位數比買進持有少 %s 個百分點。"
        "最大回撤的中位數比買進持有淺 %s 個百分點。294 格裡全期年化報酬贏過買進持有的有 %d 格。"
        % (_num(-100 * b_med_ex, 1), _num(100 * b_mdd_gain, 1), b_n_beat))
    s5 = ("5. 隔夜與盤中：" + ("三檔的毛報酬都集中在隔夜那一段。" if on_dom else "三檔的隔夜段與盤中段沒有一致的高低。")
          + "但這個做法每天要進出一次，SPY 隔夜段的打平成本只有每邊 %s bp，SMH 是每邊 %s bp。"
          % (_num(be("SPY"), 1), _num(be("SMH"), 1))
          + ("每邊成本 5 bp 時，三檔的隔夜段都變成負報酬。" if on5_neg else ""))
    add(s5)
    add("6. 最需要記住的限制有四個。隨機選股的對照組偏鬆，所以 p 值偏樂觀。2018 年以後的資料在別的專案已經看過。"
        "SMH 在 2011 年以前是 HOLDRS 結構，不是今天這檔 ETF。短訊號、短週期的格子高度依賴「隔天開盤價成交」這個假設。")
    add("")

    # ----- section 0a: what changed
    add("## 0a. 這一版改了什麼（獨立驗證後的修正）")
    add("")
    add("兩組獨立驗證者一共提出 13 點意見。其中 3 件事被兩邊各提一次，所以下表合併成 10 列。逐點重現後都成立。提名結果沒有變：兩段都是 0 格。")
    add("")
    rows = [
        ["MA 宇宙在 2003 年年中以前只有現金，上一版把那段利息算進 Wa 與全期，再拿去跟下跌中的 SPY 比",
         "成立（重大）",
         "US-A 的格子與等權基準在第一筆交易之前視為尚未上線，超額只用共同上線的日子（偏離第 3 條）",
         "全期贏 SPY 的格數：%d → %d（其中 MA：%d → %d）"
         % (facts["_n_beat_spy_full_incl_cash"], facts["_n_beat_spy_full"],
            facts["_n_beat_spy_full_MA_incl_cash"], facts["_n_beat_spy_full_MA"])],
        ["分批的進場方式會移動 H ≥ 63 的數字；「持有 252 日有 46% 贏 SPY」不穩",
         "成立（重大）",
         "凍結的格子不動；加上「各批錯開進場」的敏感度（表 3f、表 4d），並拿掉「越長越好」的說法",
         "持有 %d 日贏 SPY 的格數：%d（凍結）對 %d（錯開）" % (h_long, n_long, n_long_st)],
        ["Sanity anchor 沒重現的原因寫錯了",
         "成立",
         "第 7 節改寫：預註冊的格子不是舊策略；補上照舊規則重跑的對照表",
         "照舊規則重跑，Wc 對 SPY 超額 %s（舊結果 −7.3pp）"
         % _pp(verdict["sanity_anchors"]["like_for_like_Wc_excess_cagr_vs_SPY"])],
        ["US-B 的 Calmar 條款在負報酬時排序顛倒",
         "成立（不影響格數）",
         "正式欄位維持字面讀法，另加兩種讀法的欄位（偏離第 13 條）",
         "三種讀法的 pass_1 都是 %d 格" % facts["cal_lit"]],
        ["每個窗第一天的報酬沒有被算進任何子窗",
         "成立（上一版已揭露）",
         "算法不改（與個股那一半一致），補上影響大小（偏離第 1 條）",
         "對 SPY 超額的正負號：%d 個裡變了 %d 個" % (facts["fd_n"], facts["fd_flips"])],
        ["XLV 2002-01-08 的可疑開盤價沒有過濾",
         "成立",
         "保留該日線（規格沒有這種過濾），補上敏感度（偏離第 19 條）",
         "持有 1 日的格子在 Wa 最多差 %s" % facts["xlv_wa_h1"]],
        ["訊號只看 1 日的格子（含 US-A 最好的那一格）高度依賴開盤價成交",
         "成立",
         "加上「改在隔天收盤成交」的敏感度（表 3g、注意事項第 8 條）",
         "最好的那一格 CAGR：%s → %s" % (facts["best_open"], facts["best_close"])],
        ["verdict.json 與表 4c 的「最接近及格線」排序不一致",
         "成立",
         "兩處改用同一個排序函式",
         "兩處現在是同一批格子"],
        ["手續費是一階近似；第 8 節標題說「一律取較保守」不精確；H=126 與 H=252 的 Sharpe 中位數其實打平",
         "成立",
         "新增偏離第 18 條並量出差距；標題改寫；打平的地方直接寫打平",
         "精確解與近似解的 CAGR 最多差 %s" % facts["fee_max"]],
        ["上一份執行報告說最接近的六格「只輸在 Wb」",
         "成立（報告用語）",
         "表 3e 現在列出三個窗各自的超額",
         "那六格在 Wb 與 Wc 都輸 SPY"],
    ]
    add(_md_table(["驗證意見", "判定", "怎麼處理", "關鍵數字"], rows))
    add("")

    # ----- section 1
    add("## 1. 怎麼讀")
    add("")
    add("- **ETF**（Exchange-Traded Fund）＝指數股票型基金。**US-A／US-B／US-C** 是預註冊文件裡三個小節的代號。")
    add("- **H**＝持有週期：一批部位買進後固定抱幾個交易日才換。**L**＝回看長度：訊號看過去幾個交易日的報酬。")
    add("- **CAGR**（Compound Annual Growth Rate）＝年化複利報酬。**IRR**（Internal Rate of Return）＝內部報酬率；期初一次投入時兩者相同，所以表裡只列 CAGR。")
    add("- **Sharpe**＝每承擔一單位波動賺到多少報酬（日報酬平均 ÷ 標準差 × √252，不扣無風險利率）。`sharpe_ex` 是扣掉 T-bill 利息後的版本。")
    add("- **MDD**（Maximum Drawdown）＝最大回撤：淨值從高點往下掉最深的幅度。**Calmar**＝CAGR ÷ |MDD|，回撤每 1 單位換到多少年化報酬。")
    add("- **pp**＝百分點。**bp**＝基點，萬分之一。**成本**以每邊計：買一次、賣一次各收一次。base＝每邊 5bp，壓力＝每邊 10bp，毛＝不計成本。")
    add("- **換手**＝一年內單邊成交金額是淨值的幾倍。**成本拖累**＝一年被成本吃掉的淨值比例。")
    add("- **中位數**＝把同一週期的所有格子由小到大排，中間那一格；用它代表「典型」結果，避免只看最好的一格。**贏基準比例**＝該週期的格子裡 CAGR 高於基準的比例。")
    add("- **超額**＝這一格的 CAGR 減掉基準在同一段日子的 CAGR。格子還沒上線的日子不算，基準也不算那幾天。")
    add("- **基準**：SPY、QQQ、SMH 買進持有（含息），加上**同宇宙等權**（EW, Equal Weight：把當天可選的 ETF 平均持有、每日再平衡、不計成本）。")
    add("- **宇宙**：EQ＝27 檔股票型 ETF；MA＝16 檔多資產 ETF（股、債、黃金、原物料、美元）。")
    add("- **窗**：Wa＝2000-01-03 至 2009-12-31；Wb＝2010-01-04 至 2017-12-29；Wc＝2018-01-02 至 2025-12-31；全期＝2000-01-03 至 2025-12-31。")
    add("- **null**＝對照組：如果訊號完全沒用，會得到什麼結果。**p 值**＝對照組裡有多大比例不輸給這一格；越小越不像運氣。"
        "**BH q**（Benjamini–Hochberg）＝同時看很多格時，把 p 值調嚴之後的數字；及格線是 q < 0.10。")
    add("- **IR**（Information Ratio）＝每天比基準多賺的平均 ÷ 它的波動 × √252。**IRX**＝13 週美國國庫券殖利率指數，這裡當現金利率。**SMA**（Simple Moving Average）＝簡單移動平均。")
    add("- **順勢**（momentum）＝買過去漲最多的；**反轉**（reversal）＝買過去跌最多的。US-B 的**反向**（contrarian）＝過去報酬不為正才持有。")
    add("- 時序：訊號只用當天收盤以前的資料，隔天用還原開盤價成交。每個週期拆成 min(H, 21) 批；凍結的格子是第一天全部建倉，之後各批錯開換倉。")
    add("- **敏感度**＝只改一個假設重跑一次，看數字動多少。敏感度的結果不是研究的格子，不進及格線。")
    add("")

    # ----- section 2
    add("## 2. 基準（買進持有與等權）")
    add("")
    rows = []
    label = {"SPY_same_days_as_MA": "SPY（只算 MA 上線的日子）"}
    for name in BENCH + ["SPY_same_days_as_MA", "EW_EQ", "EW_MA"]:
        d = bt[(bt.benchmark == name) & (bt.study == "US-A/US-C")].set_index("window")
        for w in WINDOW_ORDER:
            r = d.loc[w]
            rows.append([label.get(name, name), w, r["start_date"], _pct(r["cagr"]), _num(r["sharpe"]),
                         _pct(r["mdd"]), _num(r["calmar"])])
    add(_md_table(["基準", "窗", "起算日", "CAGR", "Sharpe", "MDD", "Calmar"], rows))
    add("")
    add("SMH 從 2000-05-05 才有資料，所以它的 Wa 與全期比別人短。MA 宇宙與 EW_MA 從 %s 才上線，它們的 Wa 與全期也從那天算起。"
        "「SPY（只算 MA 上線的日子）」是給 MA 的格子對照用的。" % facts["ma_t0"])
    add("")

    # ----- section 3
    add("## 3. US-A：ETF 截面輪動 × 持有週期")
    add("")
    add("每天把宇宙裡的 ETF 依過去報酬排名，買前 3 名（順勢）或後 3 名（反轉），抱 H 日。"
        "2 個宇宙 × 7 個訊號 × 2 個方向 = 每個 H 有 28 格。")
    add("")
    add("**表 3a：各持有週期的整體表現（全期、base 成本、28 格）**")
    add("")
    rows = []
    for _, r in hsA.iterrows():
        h = int(r["H"])
        n1 = int(a_pass.loc[[c for c in a_pass.index if c.endswith("|H%d" % h)], "pass_1"].sum())
        rows.append(["%d" % h, int(r["n_cells"]), _pp(r["excess_cagr_vs_SPY_median"]),
                     "%d（%s）" % (r["n_beat_SPY"], _pct(r["share_beat_SPY"], 0)),
                     _pp(r["excess_cagr_vs_EW_median"]),
                     "%d（%s）" % (r["n_beat_EW"], _pct(r["share_beat_EW"], 0)), n1,
                     _pct(r["cagr_median"]), _num(r["sharpe_median"]),
                     _pct(r["mdd_median"]), _num(r["calmar_median"]),
                     _num(r["turnover_ann_median"], 1) + "×", _pct(r["cost_drag_ann_median"], 2),
                     "%s（%s）" % (_short(r["best_cell_by_excess_vs_SPY"]),
                                 _pp(r["excess_cagr_vs_SPY_best"]))])
    add(_md_table(["H（日）", "格數", "對 SPY 超額中位", "贏 SPY 格數（比例）", "對等權超額中位",
                   "贏等權格數（比例）", "三窗都贏 SPY 格數", "CAGR 中位", "Sharpe 中位", "MDD 中位",
                   "Calmar 中位", "換手中位", "成本拖累中位", "對 SPY 超額最高的格"], rows))
    add("")
    add("讀法：同一列是同一個持有週期。EQ 的全期從 2000 年初算起，MA 從 2003 年年中算起，所以 28 格混在一起的 CAGR、Sharpe、MDD 中位數只能參考。"
        "跨宇宙可以比的是「超額」那幾欄，因為每一格都只跟同一段日子的基準比。"
        "「最高的格」只是讓你知道上限在哪，它是從 28 格裡挑出來的，一定高估。")
    add("")
    add("**表 3a′：修正前後對照（全期、base 成本、28 格）。「修正前」把 MA 上線前的現金利息算進去。**")
    add("")
    rows = []
    for _, r in hsA.iterrows():
        rows.append(["%d" % int(r["H"]), _pp(r["excess_cagr_vs_SPY_incl_prestart_cash_median"]),
                     _pp(r["excess_cagr_vs_SPY_median"]),
                     _pct(r["share_beat_SPY_incl_prestart_cash"], 0), _pct(r["share_beat_SPY"], 0)])
    add(_md_table(["H（日）", "對 SPY 超額中位：修正前", "修正後", "贏 SPY 比例：修正前", "修正後"], rows))
    add("")
    add("**表 3b：分宇宙、分方向的 CAGR 中位數與對 SPY 超額中位數（全期、base 成本、每格 7 個訊號）**")
    add("")
    f = Ab[Ab.window == "FULL"]
    rows = []
    for h in H_LIST:
        row = ["%d" % h]
        for u in UNIVERSES:
            for d_ in ("momentum", "reversal"):
                g = f[(f.universe == u) & (f.direction == d_) & (f.H == h)]
                row.append("%s／%s" % (_pct(g["cagr"].median()), _pp(g["excess_cagr_vs_SPY"].median())))
        rows.append(row)
    add(_md_table(["H（日）", "EQ 順勢", "EQ 反轉", "MA 順勢", "MA 反轉"], rows))
    add("")
    spy_full = bt[(bt.benchmark == "SPY") & (bt.window == "FULL")].iloc[0]
    spy_ma = bt[(bt.benchmark == "SPY_same_days_as_MA") & (bt.window == "FULL")].iloc[0]
    add("對照用的 SPY 年化報酬分兩段看。EQ 那一段從 2000 年初起算，是 %s。MA 那一段從 2003 年年中起算，是 %s。"
        % (_pct(spy_full["cagr"]), _pct(spy_ma["cagr"])))
    add("")
    add("**表 3c：分時間窗的對 SPY 超額中位數與贏 SPY 比例（base 成本、28 格）**")
    add("")
    rows = []
    for h in H_LIST:
        row = ["%d" % h]
        for w in SUB_WINDOWS:
            r = hs[(hs.study == "US-A") & (hs.group == "ALL") & (hs.window == w) & (hs.cost == BASE)
                   & (hs.H == h)].iloc[0]
            row.append("%s／%s" % (_pp(r["excess_cagr_vs_SPY_median"]), _pct(r["share_beat_SPY"], 0)))
        rows.append(row)
    add(_md_table(["H（日）", "Wa 2000–2009", "Wb 2010–2017", "Wc 2018–2025"], rows))
    add("")
    add("Wa 那一欄，MA 的 14 格從 2003 年年中才算起，沒有經過 2000–2002 年的空頭。")
    add("")
    add("**表 3d：成本的影響：CAGR 中位數（全期、28 格）**")
    add("")
    rows = []
    for h in H_LIST:
        row = ["%d" % h]
        for c in (GROSS, BASE, STRESS):
            r = hs[(hs.study == "US-A") & (hs.group == "ALL") & (hs.window == "FULL") & (hs.cost == c)
                   & (hs.H == h)].iloc[0]
            row.append(_pct(r["cagr_median"]))
        mt = [metas["usa_%s_H%d" % (u, h)]["null"]["FULL"]["cagr_median"] for u in UNIVERSES]
        row.append("%s／%s" % (_pct(mt[0]), _pct(mt[1])))
        rows.append(row)
    add(_md_table(["H（日）", "毛", "base 5bp", "壓力 10bp", "隨機選 3 檔的 CAGR 中位（EQ／MA，base）"], rows))
    add("")
    add("隨機選股在 H=1 的年化報酬是大幅負值，因為每天幾乎全部換倉，成本吃掉一切。這也是對照組在短週期偏鬆的原因。")
    add("")
    add("**及格線**（五條都要過才算提名）：")
    add("")
    cnt = verdict["counts"]["US-A"]
    add(_md_table(["條款", "內容", "過關格數（共 196）"], [
        ["pass_1", "base 成本下 Wa、Wb、Wc 三窗的 CAGR 都高於 SPY", cnt["pass_1"]],
        ["pass_2", "base 成本下三窗的 CAGR 都高於同宇宙等權", cnt["pass_2"]],
        ["pass_3", "全期對隨機選股的 p 值經 BH 校正後 q < 0.10", cnt["pass_3"]],
        ["pass_4", "每邊 10bp 下三窗仍同時贏 SPY 與同宇宙等權", cnt["pass_4"]],
        ["pass_5", "四個窗的 MDD 都不比 SPY 深超過 10pp", cnt["pass_5"]],
        ["nominated", "五條全過", cnt["nominated"]]]))
    add("")
    alt = cnt["alt_readings_q_lt_0.10"]
    add("pass_3 的格數會隨讀法改變：只看 CAGR 的 p 是 %d 格，只看 Sharpe 的 p 是 %d 格。提名數不受影響，因為 pass_1 沒有任何一格通過。"
        % (alt["bh_q_cagr_only"], alt["bh_q_sharpe_only"]))
    add("")
    wins = {w: Ab[Ab.window == w].set_index("cell")["excess_cagr_vs_SPY"] for w in WINDOW_ORDER}
    fb = Ab[Ab.window == "FULL"].set_index("cell")
    rows = [[_short(c), int(a_pass.loc[c, "n_pass"]),
             "".join("○" if a_pass.loc[c, "pass_%d" % i] else "×" for i in range(1, 6)),
             _pct(fb.loc[c, "cagr"]), _pp(wins["FULL"][c]),
             "／".join(_pp(wins[w][c]) for w in SUB_WINDOWS), _pct(fb.loc[c, "mdd"]),
             _num(a_pass.loc[c, "bh_q"], 3), _num(fb.loc[c, "null_p_gross_cagr_diag"], 3)]
            for c in closest_cells(a_pass, "US-A")]
    add("**表 3e：過關條數最多的 8 格（base 成本）**")
    add("")
    add(_md_table(["格", "過關條數", "pass_1–5", "全期 CAGR", "全期對 SPY 超額", "對 SPY 超額：Wa／Wb／Wc",
                   "全期 MDD", "BH q", "零成本對照 p（診斷）"], rows))
    add("")
    add("「零成本對照 p」是把這一格與隨機選股都拿掉成本再比一次，用來分辨「選得比較好」與「只是交易比較少」。它是診斷，不進及格線。")
    add("")
    add("**表 3f：分批進場方式的敏感度（base 成本、28 格）。箭頭左邊是凍結的算法（第一天全部建倉），右邊是各批錯開進場。**")
    add("")
    rows = []
    for h in H_LIST:
        r = stA.loc[h]
        rows.append(["%d" % h,
                     "%s → %s" % (_pp(r["excess_cagr_vs_SPY_median_frozen"]), _pp(r["excess_cagr_vs_SPY_median_variant"])),
                     "%d → %d" % (r["n_beat_SPY_frozen"], r["n_beat_SPY_variant"]),
                     "%d → %d" % (r["n_beat_EW_frozen"], r["n_beat_EW_variant"]),
                     "%s → %s" % (_pct(r["cagr_median_frozen"]), _pct(r["cagr_median_variant"])),
                     _ppabs(r["max_abs_d_cagr"]), _ppabs(stA_wa.loc[h, "max_abs_d_cagr"])])
    add(_md_table(["H（日）", "對 SPY 超額中位（全期）", "贏 SPY 格數（全期）", "贏等權格數（全期）",
                   "CAGR 中位（全期）", "單格 CAGR 最大差距：全期", "單格 CAGR 最大差距：Wa"], rows))
    add("")
    pv = facts["_stag_pass_usa"]
    add("錯開進場的算法下，三窗都贏 SPY 的格數是 %d，三窗都贏同宇宙等權的格數是 %d。提名數同樣是 0。"
        % (pv["pass_1"], pv["pass_2"]))
    add("H ≤ 21 兩種算法幾乎一樣。H ≥ 63 的差距來自模擬的頭 H 天：凍結的算法在那段時間所有批次抱同一天選出來的部位。")
    add("")
    add("**表 3g：成交價的敏感度（全期、base 成本）。把「隔天開盤成交」改成「隔天收盤成交」，CAGR 變動多少。**")
    add("")
    ce = SF[(SF.study == "US-A") & (SF.variant == "exec_t1_close") & (SF.cost == BASE)
            & (SF.window == "FULL")]
    rows = []
    for h in H_LIST:
        g = ce[ce.H == h]
        sh = g["signal"].isin(SHORT_SIGNALS)
        rows.append(["%d" % h, _ppabs(g["d_cagr"].abs().max()),
                     _ppabs(g.loc[sh, "d_cagr"].abs().median()), _ppabs(g.loc[~sh, "d_cagr"].abs().median()),
                     "%d → %d" % (exA.loc[h, "n_beat_SPY_frozen"], exA.loc[h, "n_beat_SPY_variant"])])
    add(_md_table(["H（日）", "單格最大變動", "訊號看 1 或 5 日的 8 格：變動中位", "其餘 20 格：變動中位",
                   "贏 SPY 格數（開盤 → 收盤）"], rows))
    add("")
    bc = facts["_best_cell"]
    add("全期對 SPY 超額最高的那一格是 %s。開盤成交時它的 CAGR 是 %s，改成隔天收盤成交是 %s。"
        "它對 SPY 的超額從 %s 變成 %s。慢訊號的格子幾乎不受影響。"
        % (facts["best_cell"], facts["best_open"], facts["best_close"],
           _pp(bc["excess_vs_SPY_open_fill"]), _pp(bc["excess_vs_SPY_t1_close_fill"])))
    add("")

    # ----- section 4
    add("## 4. US-B：指數的回看 L × 持有 H 進出場矩陣")
    add("")
    add("對 SPY、QQQ、SMH 各自做：過去 L 日報酬為正就持有（順勢）或不為正才持有（反向），否則放 T-bill；每 H 日重新決定一次。"
        "每個標的每個 H 有 14 格。買進持有的數字只算同一段日子。")
    add("")
    add("**表 4a：各持有週期的整體表現（全期、base 成本、三檔合計 42 格）**")
    add("")
    rows = []
    for _, r in hsB.iterrows():
        h = int(r["H"])
        g = Bb[(Bb.window == "FULL") & (Bb.H == h)]
        cal_beat = float((g["calmar"] > g["bh_calmar"]).mean())
        rows.append(["%d" % h, int(r["n_cells"]), _pct(r["cagr_median"]),
                     _pp(r["excess_cagr_vs_EW_median"]),
                     "%d（%s）" % (r["n_beat_EW"], _pct(r["share_beat_EW"], 0)),
                     _num(r["sharpe_median"]), _pct(r["mdd_median"]), _num(r["calmar_median"]),
                     _pct(cal_beat, 0), _num(r["turnover_ann_median"], 1) + "×",
                     _pct(r["cost_drag_ann_median"], 2),
                     "%s（%s）" % (_short(r["best_cell_by_calmar"]), _num(r["calmar_best"]))])
    add(_md_table(["H（日）", "格數", "CAGR 中位", "對買進持有超額中位", "CAGR 贏買進持有格數（比例）",
                   "Sharpe 中位", "MDD 中位", "Calmar 中位", "Calmar 贏買進持有比例", "換手中位",
                   "成本拖累中位", "Calmar 最高的格"], rows))
    add("")
    add("**表 4b：分標的、分方向（全期、base 成本、每格 7 個回看長度）：CAGR 中位／Calmar 中位**")
    add("")
    rows = []
    for sym in BENCH:
        bh = bt[(bt.benchmark == "BH_%s_same_days" % sym) & (bt.window == "FULL")].iloc[0]
        rows.append([sym + " 買進持有", "%s／%s（起算 %s，MDD %s）"
                     % (_pct(bh["cagr"]), _num(bh["calmar"]), bh["start_date"], _pct(bh["mdd"]))]
                    + [""] * (len(H_LIST) - 1))
        for d_ in ("momentum", "contrarian"):
            row = ["%s %s" % (sym, "順勢" if d_ == "momentum" else "反向")]
            for h in H_LIST:
                g = Bb[(Bb.window == "FULL") & (Bb.universe == sym) & (Bb.direction == d_) & (Bb.H == h)]
                row.append("%s／%s" % (_pct(g["cagr"].median()), _num(g["calmar"].median())))
            rows.append(row)
    add(_md_table(["標的與方向"] + ["H=%d" % h for h in H_LIST], rows))
    add("")
    add("SMH 的數字涵蓋 2011 年以前的 HOLDRS 時期，那一段不能直接當成今天這檔 ETF 的歷史。")
    add("")
    cnt = verdict["counts"]["US-B"]
    add("**及格線**（四條都要過才算提名）：")
    add("")
    add(_md_table(["條款", "內容", "過關格數（共 294）"], [
        ["pass_1", "base 成本下三窗的 Calmar 都高於買進持有（字面讀法）", cnt["pass_1"]],
        ["pass_2", "base 成本下全期 CAGR 不低於買進持有減 1pp", cnt["pass_2"]],
        ["pass_3", "圓形位移對照的 p 值經 BH 校正後 q < 0.10", cnt["pass_3"]],
        ["pass_4", "每邊 10bp 下前兩條仍成立", cnt["pass_4"]],
        ["nominated", "四條全過", cnt["nominated"]]]))
    add("")
    alt = cnt["alt_readings_q_lt_0.10"]
    add("null 的讀法不影響結論：若只看 Calmar 的 p，會有 %d 格 q < 0.10；只看 CAGR 的 p 則是 %d 格。"
        "不論哪一種讀法，同時通過 pass_1 與 pass_2 的格子都是 0，所以提名數不變。"
        % (alt["bh_q_calmar_only"], alt["bh_q_cagr_only"]))
    add("")
    add("pass_1 在負報酬的窗有排序顛倒的問題（偏離第 13 條）。Wa 窗有 %d 個「格 × 窗」報酬與回撤都比買進持有好，卻被判成 Calmar 沒有比較好。"
        "改用經濟讀法或嚴格讀法，pass_1 的格數分別是 %d 與 %d，與字面讀法是同一批格子。"
        % (facts["cal_perv"], facts["cal_eco"], facts["cal_strict"]))
    add("")
    fb = Bb[Bb.window == "FULL"].set_index("cell")
    rows = [[_short(c), int(b_pass.loc[c, "n_pass"]),
             "".join("○" if b_pass.loc[c, "pass_%d" % i] else "×" for i in range(1, 5)),
             _pct(fb.loc[c, "cagr"]), _pct(fb.loc[c, "bh_cagr"]), _num(fb.loc[c, "calmar"]),
             _num(fb.loc[c, "bh_calmar"]), _pct(fb.loc[c, "frac_time_in_market"], 0),
             _num(b_pass.loc[c, "null_p"], 3), _num(b_pass.loc[c, "bh_q"], 3)]
            for c in closest_cells(b_pass, "US-B")]
    add("**表 4c：最接近及格線的 8 格（先排過關條數，再排三窗 Calmar 條款，再排 null p；全期、base 成本）。verdict.json 的 closest_cells 用同一個排序。**")
    add("")
    add(_md_table(["格", "過關條數", "pass_1–4", "CAGR", "買進持有 CAGR", "Calmar", "買進持有 Calmar",
                   "在場時間比例", "null p", "BH q"], rows))
    add("")
    add("**表 4d：分批進場方式的敏感度（全期、base 成本、42 格）。箭頭左邊是凍結的算法，右邊是各批錯開進場。**")
    add("")
    sfb = SF[(SF.study == "US-B") & (SF.variant == "stag_entry") & (SF.cost == BASE) & (SF.window == "FULL")]
    rows = []
    for h in H_LIST:
        r = stB.loc[h]
        g = sfb[sfb.H == h]
        rows.append(["%d" % h, "%s → %s" % (_pct(r["cagr_median_frozen"]), _pct(r["cagr_median_variant"])),
                     "%d → %d" % (r["n_beat_EW_frozen"], r["n_beat_EW_variant"])]
                    + [_ppabs(g[g.universe == s]["d_cagr"].abs().max()) for s in BENCH])
    add(_md_table(["H（日）", "CAGR 中位", "CAGR 贏買進持有格數"] + ["單格最大差距：" + s for s in BENCH], rows))
    add("")
    pvb, pfb = facts["_stag_pass_usb"], verdict["counts"]["US-B"]
    add("SPY 幾乎不受影響，因為它在評估窗之前已經跑了一年。QQQ 的起算日是網路泡沫高點，錯開進場等於晚一點才滿倉，所以差距最大。")
    add("錯開進場的算法下，pass_1 是 %d 格（凍結的算法是 %d 格）。pass_2 是 %d 格（凍結的算法是 %d 格）。同時通過兩條的仍是 %d 格。"
        % (pvb["pass_1"], pfb["pass_1"], pvb["pass_2"], pfb["pass_2"], pvb["pass_1_and_2"]))
    add("")

    # ----- section 5
    add("## 5. US-C：隔夜 vs 盤中")
    add("")
    add("隔夜段＝收盤買、隔天開盤賣。盤中段＝開盤買、當天收盤賣。一直抱＝兩段相乘。兩條交易腿每天要成交兩邊。這一段沒有修正，數字與上一版相同。")
    add("")
    add("**表 5a：全期（毛報酬與扣成本後的 CAGR）**")
    add("")
    rows = []
    for sym in BENCH:
        for leg, nm in (("overnight", "隔夜段"), ("intraday", "盤中段"), ("close_to_close", "一直抱")):
            g = cfull[(cfull.universe == sym) & (cfull.signal == leg)].set_index("cost")
            rows.append([sym, nm, g.loc["gross_0bp", "start_date"], _pct(g.loc["gross_0bp", "cagr"]),
                         _num(g.loc["gross_0bp", "sharpe"]), _pct(g.loc["gross_0bp", "mdd"]),
                         _pct(g.loc["1bp", "cagr"]), _pct(g.loc["2bp", "cagr"]), _pct(g.loc["5bp", "cagr"]),
                         (_num(g.loc["gross_0bp", "breakeven_bps_per_side"]) if leg != "close_to_close"
                          else "不適用")])
    add(_md_table(["標的", "腿", "起算日", "毛 CAGR", "毛 Sharpe", "毛 MDD", "淨 CAGR 1bp", "淨 CAGR 2bp",
                   "淨 CAGR 5bp", "打平成本（每邊 bp）"], rows))
    add("")
    add("打平成本為負，表示那一段連不計成本都是虧的。")
    add("")
    add("**表 5b：分時間窗：毛 CAGR（隔夜／盤中／一直抱）與隔夜段的打平成本**")
    add("")
    rows = []
    for sym in BENCH:
        for w in SUB_WINDOWS:
            g = Cg[(Cg.universe == sym) & (Cg.window == w) & (Cg.cost == "gross_0bp")].set_index("signal")
            rows.append([sym, w, _pct(g.loc["overnight", "cagr"]), _pct(g.loc["intraday", "cagr"]),
                         _pct(g.loc["close_to_close", "cagr"]),
                         _num(g.loc["overnight", "breakeven_bps_per_side"]),
                         _num(g.loc["intraday", "breakeven_bps_per_side"])])
    add(_md_table(["標的", "窗", "隔夜段毛 CAGR", "盤中段毛 CAGR", "一直抱 CAGR", "隔夜段打平成本（bp）",
                   "盤中段打平成本（bp）"], rows))
    add("")

    # ----- section 6
    add("## 6. 對使用者問題的直接回答（描述性）")
    add("")

    def top2(series):
        s = series.sort_values(ascending=False)
        return int(s.index[0]), float(s.iloc[0]), int(s.index[1]), float(s.iloc[1])

    add("- **獲利最好的週期（ETF 輪動）**：用對 SPY 超額的中位數看，凍結的算法下最好的是持有 %d 日，數值 %s。"
        "各批錯開進場的算法下，最好的是持有 %d 日，數值 %s。%s"
        % (h_hi, _pp(med[h_hi]), h_hi_st, _pp(med_st[h_hi_st]),
           "兩種算法下，每個週期的中位數都是負的。" if (all_neg and (med_st < 0).all()) else ""))
    h1, v1, h2, v2 = top2(hsA.set_index("H")["sharpe_median"])
    c1, cv1, c2, cv2 = top2(hsA.set_index("H")["calmar_median"])
    add("- **最穩的週期（ETF 輪動）**：Sharpe 中位數最高的是持有 %d 日，數值 %s。%s"
        "Calmar 中位數最高的是持有 %d 日，數值 %s。%s"
        % (h1, _num(v1, 3),
           ("第二名是持有 %d 日，數值 %s，兩者實際上打平。" % (h2, _num(v2, 3))) if v1 - v2 < 0.01 else "",
           c1, _num(cv1, 3),
           ("第二名是持有 %d 日，數值 %s，兩者實際上打平。" % (c2, _num(cv2, 3))) if cv1 - cv2 < 0.005 else ""))
    nb = stA["n_beat_SPY_frozen"]
    hb = int(nb.idxmax())
    add("- **最能打敗大盤的週期（ETF 輪動）**：全期贏 SPY 格數最多的是持有 %d 日，有 %d 格。"
        "同一個週期在錯開進場的算法下只有 %d 格。三個窗都贏 SPY 的格子，全部 196 格裡%s。"
        % (hb, int(nb[hb]), int(stA.loc[hb, "n_beat_SPY_variant"]),
           "一格都沒有" if n_p1 == 0 else "有 %d 格" % n_p1))
    wb = hs[(hs.study == "US-A") & (hs.group == "ALL") & (hs.window == "Wb") & (hs.cost == BASE)]
    wb_max = float(wb["share_beat_SPY"].max())
    add("- **為什麼三窗都贏這麼難**：2010–2017 這個窗（Wb）裡，%s。"
        "2000–2009（Wa）贏 SPY 的比例較高，但同宇宙等權在那個窗也贏 SPY。MA 宇宙的 Wa 從 2003 年年中才開始，沒有經過前三年的空頭。"
        % ("196 格沒有任何一格贏過 SPY" if wb_max == 0 else
           "各週期贏 SPY 的格子比例最高只有 %s" % _pct(wb_max, 0)))
    add("- **縮短週期**：持有 1 到 10 日的中位數結果明顯較差，主因是換手。持有 1 日的成本拖累中位數是每年 %s。持有 252 日是 %s。"
        "短週期裡少數看起來不錯的反轉格，靠的是開盤價成交這個假設（表 3g）。"
        % (_pct(hsA.iloc[0]["cost_drag_ann_median"], 1), _pct(hsA.iloc[-1]["cost_drag_ann_median"], 2)))
    bh1, bv1, bh2, bv2 = top2(hsB.set_index("H")["cagr_median"])
    bc1 = int(hsB.set_index("H")["calmar_median"].idxmax())
    add("- **指數進出場**：CAGR 中位數最高的是持有 %d 日，Calmar 中位數最高的是持有 %d 日。不論哪個週期，報酬中位數都低於買進持有。"
        "持有 126 日與 252 日的數字對分批進場方式敏感（表 4d），不宜在長週期之間排名次。" % (bh1, bc1))
    add("- **一句話**：在這批資料裡，拉長持有週期主要是少付成本、往「買進持有」靠近，沒有哪個週期的典型結果贏過大盤。")
    add("")

    # ----- section 7
    add("## 7. Sanity anchors（對帳）")
    add("")
    an = verdict["sanity_anchors"]
    rows = []
    for w, exp in (("Wb", "CAGR 約 13%"), ("Wa", "CAGR 約 −1%、MDD 約 −55%"),
                   ("Wc", "CAGR 約 14.2%、MDD 約 −33.7%、Sharpe 約 0.78")):
        s = an["SPY_buy_hold_" + w]
        rows.append(["SPY 買進持有 " + w, exp, "CAGR %s、MDD %s、Sharpe %s"
                     % (_pct(s["cagr"], 2), _pct(s["mdd"], 1), _num(s["sharpe"], 3)),
                     "CAGR %s、Sharpe %s" % (_pct(s["cagr_if_first_day_return_included"], 2),
                                           _num(s["sharpe_if_first_day_return_included"], 3))])
    add(_md_table(["項目", "預期", "本次結果", "若把窗第一天的報酬也算進去"], rows))
    add("")
    eqc = an["EQ_ret252_momentum_H21_base"]
    diag = an["prior_rule_diagnostics"]
    add("舊結果來自 fadacai-etf-rotation：月頻動能輪動在 2018–2025 每年輸 SPY 7.3 個百分點。"
        "那條規則與本研究預註冊的格子不是同一條規則，差別有四個。宇宙是 11 檔類股 ETF。訊號是 126、189、252 日三個報酬排名的平均。"
        "每個入選標的要站上自己的 210 日 SMA，否則那一份改放現金。只分 3 批。")
    add("")
    add("預註冊的 EQ、252 日順勢、H=21 那一格在 Wc 對 SPY 的超額是 %s。它不是舊策略，所以這個數字不能直接拿來對帳。"
        "上一版把落差歸因於「EQ 含 SMH、QQQ」，這個說法沒有被驗證，已撤回。" % _pp(eqc["Wc"]["excess_cagr_vs_SPY"]))
    add("")
    add("**表 7a：從預註冊的格子一步一步換成舊規則（全部用本研究的引擎、H=21、base 成本；都是診斷，不是研究的格子）**")
    add("")
    rows = []
    for key, uni, sig, filt, tr, note in ANCHOR_STEPS:
        if key in diag:
            d = diag[key]
            rows.append([uni, sig, filt, tr, _pp(d["Wc"]["excess_cagr_vs_SPY"]),
                         _pp(d["FULL"]["excess_cagr_vs_SPY"]), note])
    add(_md_table(["宇宙", "訊號", "210 日均線濾網", "批數", "Wc 對 SPY 超額", "全期對 SPY 超額", "說明"], rows))
    add("")
    like = an["like_for_like_Wc_excess_cagr_vs_SPY"]
    if like is not None:
        add("照舊規則重跑的那一列，Wc 對 SPY 的超額是 %s。舊結果是 −7.3pp，方向相同，幅度相近。"
            "剩下的差距沒有逐項驗證；可能的來源是現金工具（舊專案用 BIL，這裡用 ^IRX）與成交細節。" % _pp(like))
        ens = diag.get("EQ_27_ensemble", {}).get("Wc", {}).get("excess_cagr_vs_SPY")
        if ens is not None:
            add("這張表也顯示預註冊那一格的正超額很脆弱。同一個 EQ 宇宙，只把單一 252 日回看換成三個回看的排名平均，Wc 的超額就變成 %s。"
                % _pp(ens))
    add("")

    # ----- sections 8, 9
    add("## 8. 偏離與詮釋（規格沒寫清楚的地方；每一條各自說明取捨）")
    add("")
    add("多數條目取較保守的讀法。第 2 條（分批進場）是中性的選擇，第 18 條（手續費）是近似，這兩條不能說是「較保守」。")
    add("")
    for i, d in enumerate(verdict["deviations_interpretations"], 1):
        add("%d. %s" % (i, d))
    add("")
    add("## 9. 注意事項")
    add("")
    for i, d in enumerate(verdict["caveats"], 1):
        add("%d. %s" % (i, d))
    add("")
    dq = verdict["data_quality"]
    add("資料檢查：剔除的壞日線 %d 根。上市後缺日線的有 %s。隔夜跳空超過 15%% 的日線 %d 根（只記錄）。成交日遇到無報價而略過的換倉 %d 次。"
        % (len(dq["dropped_bars"]), "、".join("%s %d 天" % (k, len(v)) for k, v in
                                          dq["missing_bars_after_listing"].items()) or "無",
           sum(len(v) for v in dq["overnight_gap_gt_15pct"].values()), dq["n_skipped_untradable_rebalances"]))
    add("")
    add("檔案：`cells.csv`（每格 × 窗 × 成本一列）、`benchmarks.csv`、`horizon_summary.csv`、`verdict.json`；"
        "敏感度在 `sensitivity.csv`（逐格）與 `sensitivity_summary.csv`（逐週期）；中間檔在 `parts/`。")
    return "\n".join(L) + "\n"


def report():
    tic = time.time()
    A, B, Cc, S, metas = _load_parts()
    panel = build_panel()
    bench = bench_returns(panel)
    bounds = window_bounds(panel.dates)
    bt = _bench_table(panel, bench, bounds, metas)
    a_pass, b_pass = _pass_lines(A, B, bt)
    pass_cols = ["bh_q", "pass_1", "pass_2", "pass_3", "pass_4", "pass_5", "n_pass", "nominated"]
    A = A.merge(a_pass[pass_cols + ["bh_q_cagr_only", "bh_q_sharpe_only", "bh_q_gross_diag"]],
                left_on="cell", right_index=True, how="left")
    B = B.merge(b_pass[pass_cols + ["bh_q_cagr_only", "bh_q_calmar_only", "pass_1_economic",
                                    "pass_1_strict"]],
                left_on="cell", right_index=True, how="left")
    for c in pass_cols:
        Cc[c] = np.nan
    Cc["nominated"] = False
    Cc["null_p"] = np.nan
    cells = pd.concat([A, B, Cc], ignore_index=True)
    lead = ["study", "universe", "signal", "direction", "form", "L", "H", "cost", "cost_bps", "window",
            "n_days", "start_date", "end_date", "cagr", "irr", "sharpe", "sharpe_ex", "mdd", "calmar",
            "total_return", "turnover_ann", "cost_drag_ann"]
    for b in EXC:
        lead += ["excess_cagr_vs_" + b, "ir_vs_" + b]
    lead += ["bench_ew_name", "null_p", "bh_q", "pass_1", "pass_2", "pass_3", "pass_4", "pass_5",
             "n_pass", "nominated", "cell"]
    cells = cells[lead + [c for c in cells.columns if c not in lead]]
    assert cells["end_date"].dropna().astype(str).max() <= END_DATE
    hs = _horizon_summary(cells)
    SF = _sens_frame(S, cells)
    SS = _sens_summary(SF)

    anchor_path = os.path.join(PARTS_DIR, "usa_anchor.json")
    anchor_diag = read_json(anchor_path) if os.path.exists(anchor_path) else {}
    anchors = _anchors(panel, bench, bounds, A, anchor_diag)
    facts = _facts(cells, SF, SS, a_pass, b_pass, anchors, panel, metas)
    pub = {k: v for k, v in facts.items() if not k.startswith("_")}

    def counts(p, n):
        d = {"n_cells": int(len(p))}
        for i in range(1, n + 1):
            d["pass_%d" % i] = int(p["pass_%d" % i].sum())
        d["nominated"] = int(p["nominated"].sum())
        d["n_pass_distribution"] = {int(k): int(v) for k, v in p["n_pass"].value_counts().sort_index().items()}
        d["min_null_p"] = float(p["null_p"].min())
        d["min_bh_q"] = float(p["bh_q"].min())
        d["alt_readings_q_lt_0.10"] = {c: int((p[c] < 0.10).sum()) for c in p.columns
                                       if c.startswith("bh_q_")}
        alt = [c for c in p.columns if c.startswith("bh_q_")]
        core = [c for c in ("pass_1", "pass_2", "pass_4", "pass_5") if p[c].notna().any()]
        d["nominated_under_any_alt_reading"] = int(
            (p[core].astype(bool).all(axis=1) & (p[alt] < 0.10).any(axis=1)).sum())
        return d

    def cell_card(df, c, extra=()):
        d = df[(df.cell == c) & (df.cost == BASE)].set_index("window")
        out = {"cell": c}
        for w in WINDOW_ORDER:
            out[w] = {k: float(d.loc[w, k]) for k in ("cagr", "sharpe", "mdd", "calmar",
                                                      "excess_cagr_vs_SPY", "excess_cagr_vs_EW",
                                                      "turnover_ann")}
        for k in ("null_p", "bh_q", "n_pass") + tuple(extra):
            out[k] = float(d.loc["FULL", k])
        return out

    hkeys = ("n_cells", "cagr_median", "cagr_best", "cagr_worst", "sharpe_median", "mdd_median",
             "calmar_median", "excess_cagr_vs_SPY_median", "share_beat_SPY", "n_beat_SPY",
             "excess_cagr_vs_EW_median", "share_beat_EW", "n_beat_EW", "turnover_ann_median",
             "cost_drag_ann_median", "best_cell_by_cagr", "best_cell_by_sharpe",
             "best_cell_by_calmar", "best_cell_by_excess_vs_SPY",
             "excess_cagr_vs_SPY_incl_prestart_cash_median", "share_beat_SPY_incl_prestart_cash")

    def hkey(study, win=("FULL",), cost=BASE):
        out = {}
        d = hs[(hs.study == study) & (hs.group == "ALL") & (hs.cost == cost)]
        for w in win:
            out[w] = {}
            for _, r in d[d.window == w].iterrows():
                out[w][r["h_label"]] = {k: r[k] for k in hkeys}
        return out

    def sens_by_h(study, variant, window="FULL"):
        d = SS[(SS.study == study) & (SS.variant == variant) & (SS.group == "ALL")
               & (SS.cost == BASE) & (SS.window == window)]
        return {"H=%d" % r["H"]: {k: r[k] for k in d.columns if k not in
                                  ("study", "variant", "group", "H", "window", "cost")}
                for _, r in d.iterrows()}

    b_cal = {"n_cell_windows_dominating_but_scored_not_better": facts["cal_perv"],
             "n_cell_windows_dominated_but_scored_better": facts["cal_perv_rev"],
             "windows_affected": facts["_cal_perv_windows"],
             "pass_1_literal": facts["cal_lit"], "pass_1_economic": facts["cal_eco"],
             "pass_1_strict": facts["cal_strict"],
             "same_cells_literal_vs_economic": facts["_cal_same_cells"],
             "pass_1_and_pass_2_[literal, economic, strict]": facts["_cal_joint"]}
    usc = Cc[(Cc.window == "FULL")]
    verdict = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "spec": "research/horizon-study-2026-11-18.md (frozen; sections US-A, US-B, US-C)",
        "status": "descriptive / nomination-only",
        "revision": {
            "n": 2, "supersedes": CANONICAL_OUT_DIR + ".superseded-1",
            "reason": "repair after independent verification (audit + re-implementation lenses)",
            "changes": [
                "US-A cells and the same-universe equal-weight benchmarks are not live before "
                "their first trade day; excess vs SPY/QQQ/SMH uses common live days only "
                "(MA: from %s). Superseded numbers kept in *_incl_prestart_cash columns."
                % facts["ma_t0"],
                "Tranche start-up: frozen cells unchanged (all tranches enter on day one); "
                "the literal 'cash until own offset' reading added as labelled sensitivity "
                "stag_entry for every US-A and US-B cell.",
                "Sanity-anchor section reworded: the pre-registered cell is not the earlier "
                "project's rule; like-for-like diagnostics added.",
                "US-B pass_1: literal clause kept; pass_1_economic / pass_1_strict columns added.",
                "closest_cells: one ordering shared by summary.md and verdict.json.",
                "Sensitivities added: first_day_incl, exec_t1_close, exact_fee, "
                "suspect_open_fixed (sensitivity.csv, sensitivity_summary.csv).",
                "Wording: section 8 header softened; ties reported as ties.",
            ],
            "before_after": {
                "US-A_n_cells_beating_SPY_full_base": [facts["_n_beat_spy_full_incl_cash"],
                                                       facts["_n_beat_spy_full"]],
                "US-A_MA_n_cells_beating_SPY_full_base": [facts["_n_beat_spy_full_MA_incl_cash"],
                                                          facts["_n_beat_spy_full_MA"]],
            },
        },
        "end_date": END_DATE, "last_bar_used": str(panel.dates[-1]),
        "output_dir": CANONICAL_OUT_DIR,
        "counts": {"US-A": counts(a_pass, 5), "US-B": counts(b_pass, 4),
                   "US-C": {"n_cells": int(Cc["cell"].nunique()), "nominated": 0,
                            "note": "no pass line (descriptive legs)"}},
        "nominated_cells": ([cell_card(A, c) for c in a_pass.index[a_pass["nominated"]]]
                            + [cell_card(B, c) for c in b_pass.index[b_pass["nominated"]]]),
        "closest_cells": {
            "US-A": [cell_card(A, c, ("null_p_gross_cagr_diag",)) for c in closest_cells(a_pass, "US-A")],
            "US-B": [cell_card(B, c, ("frac_time_in_market",)) for c in closest_cells(b_pass, "US-B")]},
        "key_numbers": {
            "benchmarks_full": {r["benchmark"]: {k: r[k] for k in ("start_date", "cagr", "sharpe",
                                                                  "sharpe_ex", "mdd", "calmar")}
                                for _, r in bt[bt.window == "FULL"].iterrows()},
            "US-A_by_H_base": hkey("US-A", WINDOW_ORDER),
            "US-A_by_H_stress_full": hkey("US-A", ("FULL",), STRESS)["FULL"],
            "US-A_by_H_gross_full": hkey("US-A", ("FULL",), GROSS)["FULL"],
            "US-B_by_H_base": hkey("US-B", WINDOW_ORDER),
            "US-A_null_cagr_median_full_base": {k[4:]: v["null"]["FULL"]["cagr_median"]
                                                for k, v in metas.items() if k.startswith("usa_")},
            "US-C_full": {"%s|%s|%s" % (r["universe"], r["signal"], r["cost"]):
                          {"cagr": r["cagr"], "sharpe": r["sharpe"], "mdd": r["mdd"],
                           "breakeven_bps_per_side": r["breakeven_bps_per_side"],
                           "breakeven_bps_vs_hold": r["breakeven_bps_vs_hold"]}
                          for _, r in usc.iterrows()},
        },
        "sensitivities": {
            "note": "labelled sensitivities; none is a study cell and none enters a pass line",
            "tranche_start_up_stag_entry": {
                "US-A_full_base_by_H": sens_by_h("US-A", "stag_entry"),
                "US-A_Wa_base_by_H": sens_by_h("US-A", "stag_entry", "Wa"),
                "US-B_full_base_by_H": sens_by_h("US-B", "stag_entry"),
                "US-B_max_abs_d_cagr_full_by_symbol": facts["_stagB_max_by_symbol"],
                "pass_counts_US-A": facts["_stag_pass_usa"], "pass_counts_US-B": facts["_stag_pass_usb"]},
            "window_first_day_incl": {
                "US-A_n_cell_subwindows": facts["fd_n"],
                "US-A_sign_flips_of_excess_vs_SPY": facts["fd_flips"],
                "pass_counts_US-A": facts["_fd_pass_usa"], "pass_counts_US-B": facts["_fd_pass_usb"]},
            "execution_at_t1_close": {
                "US-A_full_base_by_H": sens_by_h("US-A", "exec_t1_close"),
                "best_cell_by_excess_vs_SPY": facts["_best_cell"],
                "short_signal_short_H_cells": {"n": facts["n_short"],
                                               "median_abs_d_cagr": facts["_short_med"],
                                               "max_abs_d_cagr": facts["_short_max"]},
                "other_cells": {"n": facts["n_other"], "median_abs_d_cagr": facts["_other_med"]},
                "pass_counts_US-A": facts["_exec_pass_usa"]},
            "exact_fee": {"US-A_max_abs_d_cagr_any_cell_window_cost": facts["_fee_max"],
                          "at": facts["_fee_max_at"]},
            "suspect_open_fixed": {
                "bars": SUSPECT_OPENS,
                "EQ_max_abs_d_cagr_H1_Wa": facts["_xlv_wa_h1"],
                "EQ_max_abs_d_cagr_H1_full": facts["_xlv_full_h1"],
                "EQ_max_abs_d_cagr_H_ge_5_any_window": facts["_xlv_h5p"],
                "EQ_sign_flips_of_excess_vs_EW_in_Wa": facts["_xlv_flips_vs_EW_Wa"]},
            "US-B_calmar_clause_readings": b_cal,
        },
        "sanity_anchors": anchors,
        "smh_note": "SMH before 2011 was a HOLDRS trust (fixed basket), not an index ETF; every "
                    "SMH number that includes pre-2011 data is flagged in summary.md.",
        "simulation_start": {k: {"t0_signal_date": v["t0_signal_date"],
                                 "first_trade_date": v["first_trade_date"]}
                             for k, v in metas.items() if k.endswith("_H1")},
        "deviations_interpretations": [d.format(**pub) for d in DEVIATIONS],
        "caveats": [c.format(**pub) for c in CAVEATS],
        "data_quality": {
            "dropped_bars": panel.dropped,
            "missing_bars_after_listing": {s: q["missing_after_first_bar"] for s, q in
                                           panel.quality.items() if q["missing_after_first_bar"]},
            "overnight_gap_gt_15pct": {s: q["overnight_gap_gt_15pct"] for s, q in
                                       panel.quality.items() if q["overnight_gap_gt_15pct"]},
            "open_equals_prev_close_days": {s: panel.quality[s]["open_equals_prev_close_days"]
                                            for s in BENCH},
            "open_equals_close_bars": facts["_open_equals_close"],
            "n_skipped_untradable_rebalances": int(sum(
                v["engine_info"]["n_skipped_untradable"]
                + v.get("null_engine_info", {}).get("n_skipped_untradable", 0)
                for v in metas.values())),
            "first_bar": {s: q["first_bar"] for s, q in panel.quality.items()},
        },
        "usb_fast_path_vs_engine_max_abs_full_cagr_gap": float(max(
            v["max_abs_gap_fast_vs_engine_full_cagr"] for k, v in metas.items() if k.startswith("usb_"))),
        "compute_seconds_parts": float(sum(v.get("seconds", 0) for v in metas.values())),
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    write_csv(os.path.join(OUT_DIR, "cells.csv"), cells)
    write_csv(os.path.join(OUT_DIR, "benchmarks.csv"), bt)
    write_csv(os.path.join(OUT_DIR, "horizon_summary.csv"), hs)
    write_csv(os.path.join(OUT_DIR, "sensitivity.csv"), SF)
    write_csv(os.path.join(OUT_DIR, "sensitivity_summary.csv"), SS)
    write_json(os.path.join(OUT_DIR, "verdict.json"), verdict)
    md = _summary_md(cells, bt, hs, a_pass, b_pass, verdict, metas, panel, SF, SS, facts)
    with open(os.path.join(OUT_DIR, "summary.md"), "w") as fh:
        fh.write(md)
    print("report written to %s in %.1fs" % (OUT_DIR, time.time() - tic))
    print("cells %d rows | US-A nominated %d | US-B nominated %d"
          % (len(cells), verdict["counts"]["US-A"]["nominated"], verdict["counts"]["US-B"]["nominated"]))
    return verdict


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        report()
    else:
        print("usage: python3 -B etf_common.py report")
