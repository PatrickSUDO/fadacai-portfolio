#!/usr/bin/env python3
"""Data, synthetic leveraged series, simulation engine and metrics for study ETF-C
(ETF portfolio construction) of the 2026-11-19 overnight pre-registration.

Spec (frozen): research/overnight-study-2026-11-19.md, section "第三組 ETF-C".
Raw data: fadacai-etf-rotation/data/raw/{eodhd,eodhd_explore}/<SYM>.json, READ-ONLY,
read directly (no loader of that repo, no network, nothing written back).

Conventions
-----------
* END DATE 2025-12-31: every later row is dropped right after reading.
* A decision dated t uses only data <= t (adjusted closes) and is executed at the
  adjusted open of t+1 (adj_open = open * adjusted_close / close).
* Day s of an account: holdings earn close[s-1] -> open[s]; trades happen at open[s];
  the new holdings earn open[s] -> close[s].
* Cash rate of day s = last ^IRX value dated strictly before s, / 100 / 252.
* BIL before its listing = an index that accrues that cash rate overnight.
* Synthetic L-times daily-reset product (spec formula, applied to adjusted closes):
      r_L[s] = L * r[s] - (L-1) * (irx[s] + 0.5%) / 252 - 0.95% / 252
  Its open is the previous synthetic close times (1 + L * overnight return of the
  underlying); the whole day's financing and fee are charged at the close.
* No trade data is read or embedded here: this half of the study uses ETF prices only.
"""
from __future__ import annotations

import json
import math
import os

import numpy as np
import pandas as pd

RAW_ROOT = "/Users/supatrick/laptop/project/fadacai-etf-rotation/data/raw"
RAW_DIRS = ("eodhd", "eodhd_explore")
HERE = os.path.dirname(os.path.abspath(__file__))
CANONICAL_OUT_DIR = os.path.normpath(
    os.path.join(HERE, "..", "..", "data", "overnight_2026-11-19", "etf"))
# The canonical directory is in a file-synced folder that may rename files that are
# rewritten quickly. ETFC_OUT_DIR lets a run work in scratch; the finished files are
# copied to the canonical directory once.
OUT_DIR = os.environ.get("ETFC_OUT_DIR") or CANONICAL_OUT_DIR

END_DATE = "2025-12-31"
CAL_START = "2003-01-02"          # warm-up only; no result uses a return before SIM_START
SIM_START = "2005-01-03"
WINDOWS = {
    "Wa": ("2005-01-03", "2012-12-31"),
    "Wb": ("2013-01-02", "2019-12-31"),
    "Wc": ("2020-01-02", "2025-12-31"),
    "FULL": ("2005-01-03", "2025-12-31"),
}
SUB_WINDOWS = ["Wa", "Wb", "Wc"]
WINDOW_ORDER = ["FULL", "Wa", "Wb", "Wc"]

ONE_X = ["SPY", "QQQ", "SMH", "MDY", "TLT", "IEF", "GLD", "BIL"]
LEV2_OF = ["SPY", "QQQ", "SMH", "TLT", "GLD"]            # underlyings that get a 2x twin
INSTR = ONE_X + [s + "2X" for s in LEV2_OF]
IDX = {s: i for i, s in enumerate(INSTR)}
BIL = IDX["BIL"]

FIN_SPREAD = 0.005      # spec: T-bill rate + 0.5% on the borrowed (L-1)
FEE = 0.0095            # spec: 0.95% a year
COSTS = {"base_5bp": 0.0005, "stress_10bp": 0.0010}
BASE, STRESS = "base_5bp", "stress_10bp"
SEED = 20261119
N_NULL = 1000
MIN_SHIFT = 252
N_BOOT = 2000
BOOT_BLOCK = 63

# Fixed calendar spans for the three named drawdowns (peak and trough closes of the
# S&P 500 in 2007-09 and 2020, and of the Nasdaq-100 in 2021-22).
EPISODES = {
    "2008": ("2007-10-09", "2009-03-09"),
    "2020": ("2020-02-19", "2020-03-23"),
    "2022": ("2021-11-19", "2022-12-28"),
}


# --------------------------------------------------------------------------- data
def raw_path(sym: str) -> str:
    for d in RAW_DIRS:
        p = os.path.join(RAW_ROOT, d, sym + ".json")
        if os.path.exists(p):
            return p
    raise FileNotFoundError(sym)


def read_raw(sym: str) -> pd.DataFrame:
    """Read one raw JSON; rows after END_DATE are dropped immediately."""
    with open(raw_path(sym)) as fh:
        df = pd.DataFrame(json.load(fh))
    df["date"] = df["date"].astype(str)
    df = df.loc[df["date"] <= END_DATE].reset_index(drop=True)
    assert (df["date"] <= END_DATE).all()
    return df


def load_symbol(sym: str, log: list) -> pd.DataFrame:
    """Bars with positive prices; a bar whose adjusted close is >5x or <0.2x the
    previous kept bar is dropped. Every drop is logged."""
    cols = ["open", "high", "low", "close", "adjusted_close"]
    df = read_raw(sym)
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
        log.append({"symbol": sym, "date": str(df.loc[int(j[0]), "date"]),
                    "reason": "adj_close_ratio_%.4f" % r[int(j[0])]})
        df = df.drop(index=int(j[0])).reset_index(drop=True)
    return df


def load_irx() -> tuple:
    df = read_raw("IRX_INDX")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).sort_values("date")
    return np.array(df["date"], dtype="datetime64[D]"), df["close"].to_numpy(float)


def synth_factors(on: np.ndarray, cc: np.ndarray, irx_ann: np.ndarray, L: float) -> tuple:
    """(overnight, intraday, close-to-close) gross factors of the synthetic L-times
    product. on / cc are the underlying's overnight and close-to-close gross factors."""
    fin = (L - 1.0) * (irx_ann + FIN_SPREAD) / 252.0 + FEE / 252.0
    cc_l = 1.0 + L * (cc - 1.0) - fin
    on_l = 1.0 + L * (on - 1.0)
    assert np.nanmin(cc_l) > 0 and np.nanmin(on_l) > 0
    return on_l, cc_l / on_l, cc_l


class Data:
    """Master calendar (SPY sessions CAL_START..END_DATE) and per-instrument factors.

    on[s, a]   = adj_open[s] / adj_close[s-1]      (overnight gross factor)
    intr[s, a] = adj_close[s] / adj_open[s]        (intraday gross factor)
    cc = on * intr. NaN where the instrument (or its previous close) does not exist.
    """

    def __init__(self, with_tqqq: bool = True):
        log: list = []
        spy = load_symbol("SPY", log)
        spy = spy.loc[spy["date"] >= CAL_START].reset_index(drop=True)
        self.dates_s = spy["date"].to_numpy()
        self.dates = np.array(self.dates_s, dtype="datetime64[D]")
        assert str(self.dates[-1]) <= END_DATE
        T = self.T = len(self.dates)
        pos = {d: i for i, d in enumerate(self.dates_s)}
        idates, ivals = load_irx()
        p = np.searchsorted(idates, self.dates, side="left") - 1
        assert (p >= 0).all()
        self.irx_ann = ivals[p] / 100.0            # annual rate known before day s
        self.rf = self.irx_ann / 252.0             # daily cash rate of day s
        A = len(INSTR)
        self.on = np.full((T, A), np.nan)
        self.intr = np.full((T, A), np.nan)
        self.adj_close = np.full((T, A), np.nan)   # 1x instruments only (signals)
        self.quality = {}
        raw = {}
        for s in ONE_X + (["TQQQ"] if with_tqqq else []):
            df = load_symbol(s, log)
            df = df.loc[df["date"] >= CAL_START]
            ii = np.array([pos.get(d, -1) for d in df["date"]])
            assert (ii >= 0).all(), "off-calendar bar in " + s
            ac = np.full(T, np.nan)
            ao = np.full(T, np.nan)
            adj = df["adjusted_close"].to_numpy(float)
            ac[ii] = adj
            ao[ii] = df["open"].to_numpy(float) * adj / df["close"].to_numpy(float)
            first = int(ii[0])
            assert np.isfinite(ac[first:]).all(), "missing bar after listing in " + s
            on = np.full(T, np.nan)
            on[1:] = ao[1:] / ac[:-1]
            intr = ac / ao
            intr[~np.isfinite(on)] = np.nan
            raw[s] = (on, intr, ac, first)
            gap = on - 1.0
            self.quality[s] = {
                "first_bar": str(self.dates[first]), "n_bars": int(len(df)),
                "max_abs_overnight_gap": float(np.nanmax(np.abs(gap))),
                "n_overnight_gap_gt_1pct": int(np.nansum(np.abs(gap) > 0.01)),
            }
        for s in ONE_X:
            on, intr, ac, first = raw[s]
            if s == "BIL":
                # before BIL has a previous close: the 13-week T-bill rate, accrued overnight
                pre = ~np.isfinite(on)
                on = np.where(pre, 1.0 + self.rf, on)
                intr = np.where(pre, 1.0, intr)
                self.bil_first_factor_day = str(self.dates[first + 1])
            a = IDX[s]
            self.on[:, a], self.intr[:, a], self.adj_close[:, a] = on, intr, ac
        for s in LEV2_OF:
            a = IDX[s]
            on_l, intr_l, _ = synth_factors(self.on[:, a], self.on[:, a] * self.intr[:, a],
                                            self.irx_ann, 2.0)
            self.on[:, IDX[s + "2X"]], self.intr[:, IDX[s + "2X"]] = on_l, intr_l
        self.cc = self.on * self.intr
        self.ret = self.cc - 1.0                   # close-to-close simple returns (T, A)
        if with_tqqq:
            on, intr, ac, first = raw["TQQQ"]
            self.tqqq_cc = on * intr
            self.tqqq_on = on
        self.dropped = log
        self.i_start = int(np.searchsorted(self.dates, np.datetime64(SIM_START)))
        assert str(self.dates[self.i_start]) == SIM_START
        d = pd.DatetimeIndex(self.dates)
        nxt_m = np.append(d.month[1:], -1)
        nxt_y = np.append(d.year[1:], -1)
        wk = d.isocalendar().week.to_numpy() + 100 * d.isocalendar().year.to_numpy()
        nxt_w = np.append(wk[1:], -1)
        self.month_end = np.asarray(d.month != nxt_m)
        self.year_end = np.asarray(d.year != nxt_y)
        self.week_end = np.asarray(wk != nxt_w)
        self.years = d.year.to_numpy()

    def col(self, s: str) -> int:
        return IDX[s]

    def idx_of(self, date: str, side: str = "left") -> int:
        if side == "left":
            return int(np.searchsorted(self.dates, np.datetime64(date), side="left"))
        return int(np.searchsorted(self.dates, np.datetime64(date), side="right")) - 1

    def dec_days(self, t0: int, flag: np.ndarray) -> np.ndarray:
        """Decision days: t0 (entry), then every flagged day after t0 that still has a
        next session to trade on."""
        later = np.flatnonzero(flag)
        later = later[(later > t0) & (later <= self.T - 2)]
        return np.concatenate([[t0], later]).astype(int)


def roll_vol(ret: np.ndarray, L: int) -> np.ndarray:
    """Annualised std (ddof=1) of the last L daily returns up to and including t.
    NaN until L returns exist. Works on (T,) or (T, A)."""
    df = pd.DataFrame(ret) if np.ndim(ret) == 2 else pd.Series(ret)
    out = df.rolling(L, min_periods=L).std(ddof=1).to_numpy() * math.sqrt(252.0)
    return out


def first_finite(x: np.ndarray, lo: int) -> int:
    """First index >= lo at which x (1-d, or all columns of 2-d) is finite."""
    ok = np.isfinite(x) if x.ndim == 1 else np.isfinite(x).all(axis=1)
    j = np.flatnonzero(ok[lo:])
    assert len(j), "signal never defined"
    return lo + int(j[0])


# ------------------------------------------------------------------------- engine
def simulate(data: Data, dec: np.ndarray, W: np.ndarray, cost: float, record_w: bool = False):
    """Daily simulator, vectorised over N accounts that share the decision days.

    dec : (D,) sorted decision days; the decision of day t trades at the open of t+1.
    W   : (D, A) or (N, D, A) target weights over INSTR; every row sums to 1.
    Before the first trade the account is cash (earns the cash rate overnight).
    Fee = cost x traded notional, solved to its self-financing fixed point.
    Returns dict(nav (T, N), ret (T, N; NaN up to dec[0]), traded, fee, [w_close]).
    """
    W = np.asarray(W, float)
    if W.ndim == 2:
        W = W[None]
    N, D, A = W.shape
    assert D == len(dec) and A == len(INSTR)
    assert np.allclose(W.sum(axis=2), 1.0, atol=1e-9), "target rows must sum to 1"
    assert (W >= -1e-12).all(), "no shorts, no margin"
    T = data.T
    on, intr, rf = data.on, data.intr, data.rf
    h = np.zeros((N, A))
    c = np.ones(N)
    nav = np.ones((T, N))
    traded = np.zeros((T, N))
    fees = np.zeros((T, N))
    wc = np.full((T, A), np.nan) if record_w else None
    ptr = 0
    for s in range(int(dec[0]) + 1, T):
        held = (h > 0).any(axis=0)
        assert np.isfinite(on[s, held]).all() and np.isfinite(intr[s, held]).all()
        h *= np.where(held, on[s], 1.0)
        c *= 1.0 + rf[s]
        if ptr < D and dec[ptr] == s - 1:
            w = W[:, ptr]
            need = (w > 0).any(axis=0)
            assert np.isfinite(on[s, need]).all(), "target on an instrument without a bar"
            nv = h.sum(axis=1) + c
            fee = np.zeros(N)
            for _ in range(4):
                tr = np.abs(w * (nv - fee)[:, None] - h).sum(axis=1)
                fee = cost * tr
            nv2 = nv - fee
            h = w * nv2[:, None]
            c = np.zeros(N)
            traded[s], fees[s] = tr, fee
            ptr += 1
        held = (h > 0).any(axis=0)
        h *= np.where(held, intr[s], 1.0)
        nav[s] = h.sum(axis=1) + c
        if record_w:
            wc[s] = h[0] / nav[s, 0]
    ret = np.full((T, N), np.nan)
    j0 = int(dec[0])
    ret[j0 + 1:] = nav[j0 + 1:] / nav[j0:-1] - 1.0
    out = {"nav": nav, "ret": ret, "traded": traded, "fee": fees, "v1": j0}
    if record_w:
        out["w_close"] = wc
    return out


def overlay(wb: np.ndarray, e: np.ndarray) -> np.ndarray:
    """Target weights for exposure e on base weights wb, with no margin.

    wb : (D, A) base weights over INSTR (non-zero only on 1x instruments).
    e  : (D,) or (N, D) exposure in [0, 2].
    e <= 1 : e x base in the 1x instruments, 1-e in BIL.
    e > 1  : (e-1) x base in the synthetic 2x twins, (2-e) x base in the 1x instruments.
    Returns (N, D, A) (or (D, A) for 1-d e)."""
    e = np.asarray(e, float)
    one = e.ndim == 1
    if one:
        e = e[None]
    assert np.isfinite(e).all() and (e >= 0).all() and (e <= 2.0 + 1e-12).all()
    lo = np.clip(e, 0.0, 1.0)
    hi = np.clip(e - 1.0, 0.0, 1.0)
    W = wb[None] * (lo - hi)[..., None]
    for s in LEV2_OF:
        W[:, :, IDX[s + "2X"]] += wb[None, :, IDX[s]] * hi
    used = wb.sum(axis=0) > 0
    for a in np.flatnonzero(used):
        assert INSTR[a] in LEV2_OF, "base asset without a 2x twin: " + INSTR[a]
    W[:, :, BIL] += 1.0 - lo
    return W[0] if one else W


def static_w(parts: dict, D: int) -> np.ndarray:
    W = np.zeros((D, len(INSTR)))
    for s, w in parts.items():
        W[:, IDX[s]] = w
    return W


# ------------------------------------------------------------------------ metrics
def perf(ret: np.ndarray, rf: np.ndarray, cal_days: float) -> dict:
    """CAGR = V_end^(365.25/cal_days)-1; Sharpe = mean/std(ddof=1)*sqrt(252) (no cash
    subtraction); sharpe_ex on returns minus the daily cash rate; MDD on V with V=1
    before the first return; Calmar = CAGR/|MDD|. ret may be (n,) or (n, G)."""
    r = np.asarray(ret, float)
    one = r.ndim == 1
    if one:
        r = r[:, None]
    n = r.shape[0]
    if n < 2 or cal_days <= 0:
        nanv = np.full(r.shape[1], np.nan)
        out = dict(n_days=n, cagr=nanv, vol=nanv, sharpe=nanv, sharpe_ex=nanv, mdd=nanv,
                   calmar=nanv, total_return=nanv)
    else:
        v = np.cumprod(1.0 + r, axis=0)
        cagr = v[-1] ** (365.25 / cal_days) - 1.0
        sd = r.std(axis=0, ddof=1)
        ex = r - np.asarray(rf, float)[:, None]
        with np.errstate(divide="ignore", invalid="ignore"):
            sharpe = np.where(sd > 0, r.mean(axis=0) / sd * math.sqrt(252), np.nan)
            sharpe_ex = np.where(ex.std(axis=0, ddof=1) > 0,
                                 ex.mean(axis=0) / ex.std(axis=0, ddof=1) * math.sqrt(252), np.nan)
            v1 = np.vstack([np.ones((1, r.shape[1])), v])
            mdd = (v1 / np.maximum.accumulate(v1, axis=0) - 1.0).min(axis=0)
            calmar = np.where(mdd < 0, cagr / np.abs(mdd), np.nan)
        out = dict(n_days=n, cagr=cagr, vol=sd * math.sqrt(252), sharpe=sharpe,
                   sharpe_ex=sharpe_ex, mdd=mdd, calmar=calmar, total_return=v[-1] - 1.0)
    if one:
        out = {k: (float(v[0]) if isinstance(v, np.ndarray) else v) for k, v in out.items()}
    return out


def window_slice(data: Data, v1: int, win: str):
    """(j0, i1) for a window: V=1 at the close of day j0, returns of days j0+1..i1.
    j0 = the last session before the window (the simulation start for Wa / FULL), or
    the portfolio's own V=1 day when it goes live later. None if no live day."""
    a, b = WINDOWS[win]
    first = data.idx_of(a)
    i1 = data.idx_of(b, "right")
    j0 = data.i_start if first <= data.i_start else first - 1
    j0 = max(j0, v1)
    return (j0, i1) if j0 < i1 else None


def slice_perf(data: Data, ret: np.ndarray, j0: int, i1: int) -> dict:
    cal = int((data.dates[i1] - data.dates[j0]) / np.timedelta64(1, "D"))
    out = perf(ret[j0 + 1:i1 + 1], data.rf[j0 + 1:i1 + 1], cal)
    out.update(start_date=str(data.dates[j0]), end_date=str(data.dates[i1]))
    return out


def turnover(sim: dict, j0: int, i1: int, k: int = 0) -> tuple:
    """Annualised one-way turnover (x NAV / year) and cost drag (per year)."""
    den = sim["nav"][j0:i1, k]
    yrs = (i1 - j0) / 252.0
    return (float((sim["traded"][j0 + 1:i1 + 1, k] / den).sum() / 2.0 / yrs),
            float((sim["fee"][j0 + 1:i1 + 1, k] / den).sum() / yrs))


def dd_detail(data: Data, ret: np.ndarray, j0: int, i1: int) -> dict:
    """Peak / trough / recovery dates of the deepest drawdown in days j0..i1."""
    v = np.concatenate([[1.0], np.cumprod(1.0 + ret[j0 + 1:i1 + 1])])
    peak = np.maximum.accumulate(v)
    dd = v / peak - 1.0
    k = int(np.argmin(dd))
    p = int(np.flatnonzero(v[:k + 1] == peak[k])[-1])
    rec = np.flatnonzero(v[k:] >= peak[k])
    return {"mdd": float(dd[k]), "peak_date": str(data.dates[j0 + p]),
            "trough_date": str(data.dates[j0 + k]),
            "recovery_date": str(data.dates[j0 + k + int(rec[0])]) if len(rec) else "",
            "sessions_peak_to_recovery": int(k + rec[0] - p) if len(rec) else None}


def bh_qvalues(p) -> np.ndarray:
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


def block_bootstrap_diff(rp: np.ndarray, rb: np.ndarray, rf: np.ndarray, seed: int) -> dict:
    """Paired circular block bootstrap (fixed block BOOT_BLOCK sessions, N_BOOT draws)
    of portfolio-minus-benchmark differences in Sharpe, cash-excess Sharpe and CAGR
    (geometric, 252 sessions a year). Percentile 95% interval."""
    n = len(rp)
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(n / BOOT_BLOCK))
    out = {k: [] for k in ("sharpe", "sharpe_ex", "cagr")}
    X = np.stack([rp, rb, rf], axis=1)
    for a in range(0, N_BOOT, 250):
        m = min(250, N_BOOT - a)
        starts = rng.integers(0, n, size=(m, nb))
        idx = (starts[:, :, None] + np.arange(BOOT_BLOCK)[None, None, :]) % n
        idx = idx.reshape(m, -1)[:, :n]
        S = X[idx]                                          # (m, n, 3)
        p, b, f = S[:, :, 0], S[:, :, 1], S[:, :, 2]
        sh = lambda x: x.mean(axis=1) / x.std(axis=1, ddof=1) * math.sqrt(252)
        cg = lambda x: np.exp(np.log1p(x).sum(axis=1) * 252.0 / n) - 1.0
        out["sharpe"].append(sh(p) - sh(b))
        out["sharpe_ex"].append(sh(p - f) - sh(b - f))
        out["cagr"].append(cg(p) - cg(b))
    res = {}
    sh1 = lambda x: x.mean() / x.std(ddof=1) * math.sqrt(252)
    cg1 = lambda x: math.exp(np.log1p(x).sum() * 252.0 / n) - 1.0
    point = {"sharpe": sh1(rp) - sh1(rb), "sharpe_ex": sh1(rp - rf) - sh1(rb - rf),
             "cagr": cg1(rp) - cg1(rb)}
    for k, v in out.items():
        v = np.concatenate(v)
        res[k + "_diff"] = float(point[k])
        res[k + "_diff_lo"] = float(np.percentile(v, 2.5))
        res[k + "_diff_hi"] = float(np.percentile(v, 97.5))
        res[k + "_diff_p_le0"] = float((v <= 0).mean())
    res["n_days"] = n
    return res


# ---------------------------------------------------------------------- utilities
def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    return o


def write_json(path: str, obj) -> None:
    with open(path, "w") as fh:
        json.dump(_clean(obj), fh, ensure_ascii=False, indent=1, allow_nan=False)
        fh.write("\n")


def write_csv(path: str, df: pd.DataFrame) -> None:
    df.to_csv(path, index=False, float_format="%.6g")
