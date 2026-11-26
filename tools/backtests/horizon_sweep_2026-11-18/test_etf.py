#!/usr/bin/env python3
"""Unit tests for the ETF half of the horizon study (tiny synthetic data).

Run:  python3 -B test_etf.py        (also collectable by pytest)
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etf_common as C  # noqa: E402
import etf_xs as XS  # noqa: E402
import index_ts as TS  # noqa: E402
import overnight as ON  # noqa: E402


def _world(T=700, A=8, seed=1, mode="overnight", sd=0.01):
    """iid returns. mode='overnight': the whole daily move happens between the
    previous close and the open (close == open). mode='intraday': open == previous
    close and the whole move happens during the session."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0, sd, size=(T, A))
    r[0] = 0.0
    close = 100.0 * np.cumprod(1.0 + r, axis=0)
    if mode == "overnight":
        opn = close.copy()
    else:
        opn = np.vstack([close[:1], close[:-1]])
    return r, opn, close


# ---------------------------------------------------------------- (1) hand case
def test_two_asset_hand_case_with_costs():
    close = np.array([[100.0, 100.0], [104.0, 100.0], [105.0, 99.0], [108.0, 97.0]])
    opn = np.array([[100.0, 100.0], [102.0, 99.0], [103.0, 101.0], [106.0, 98.0]])
    rf = np.array([0.0, 0.0001, 0.0002, 0.0003])
    cost = 0.001
    plans = {0: np.array([[1.0, 0.0]]), 1: np.array([[0.5, 0.5]])}

    def plan_fn(t, flat):
        return (np.array([0]), plans[t]) if t in plans else None

    nav, traded, fees, info = C.simulate(opn, close, rf, plan_fn, [cost], [0], 1)
    # day 1: cash earns rf, buy A at the open with everything, pay cost, A intraday
    v_open1 = 1.0 * (1 + 0.0001)
    fee1 = cost * v_open1
    v1 = (v_open1 - fee1) * 104.0 / 102.0
    # day 2: A overnight 104 -> 103, rebalance to 50/50 (sell half of A, buy B)
    v_open2 = v1 * 103.0 / 104.0
    tr2 = abs(0.5 * v_open2 - v_open2) + abs(0.5 * v_open2 - 0.0)
    fee2 = cost * tr2
    half = 0.5 * (v_open2 - fee2)
    v2 = half * 105.0 / 103.0 + half * 99.0 / 101.0
    # day 3: no trade; both legs overnight then intraday == close to close
    v3 = half * 108.0 / 103.0 + half * 97.0 / 101.0
    assert np.allclose(nav[:, 0], [1.0, v1, v2, v3], rtol=0, atol=1e-14)
    assert np.allclose(traded[:, 0], [0.0, v_open1, tr2, 0.0], atol=1e-14)
    assert np.allclose(fees[:, 0], [0.0, fee1, fee2, 0.0], atol=1e-14)
    # explicit numbers, independent of the formulas above
    assert abs(v1 - 0.9990999 * 104.0 / 102.0) < 1e-14 and abs(v1 - 1.0186900941) < 1e-9
    assert abs(tr2 - v_open2) < 1e-15 and abs(v_open2 - 1.0088949971) < 1e-9
    assert abs(v2 - 0.999 * 1.0088949971 * 0.5 * (105 / 103 + 99 / 101)) < 1e-9
    # zero cost version = pure price path
    nav0, *_ = C.simulate(opn, close, rf, plan_fn, [0.0], [0], 1)
    assert abs(nav0[1, 0] - 1.0001 * 104 / 102) < 1e-14
    # cash only: compounding of the daily rate
    navc, *_ = C.simulate(opn, close, rf, lambda t, f: None, [cost], [0], 1)
    assert np.allclose(navc[:, 0], np.cumprod(1 + rf))


def test_cost_scales_with_traded_notional_only():
    """Re-picking the same names only trades the drift, and a pure hold trades nothing."""
    r, opn, close = _world(T=60, A=2, seed=3, mode="intraday")
    rf = np.zeros(60)
    W = np.array([[0.5, 0.5]])
    nav, traded, fees, _ = C.simulate(opn, close, rf, lambda t, f: (np.array([0]), W),
                                      [0.001], [0], 1)
    assert traded[1, 0] == 1.0                      # initial entry: buys only
    assert (traded[2:, 0] < 0.05).all() and (traded[2:, 0] > 0).all()
    assert np.allclose(fees[:, 0], 0.001 * traded[:, 0])


# ------------------------------------------------------------ (2) look-ahead canary
def _xs_mean_daily(opn, close, S, H=1, direction="momentum"):
    T, A = close.shape
    elig = np.ones((T, A), bool)
    elig[:5] = False
    pk, valid = XS.build_picks(S, elig, direction)
    t0 = int(np.flatnonzero(valid)[0])
    nav, *_ = XS.run_xs(opn, close, np.zeros(T), pk[None], valid, H, [0.0], t0)
    ret = C.nav_to_ret(nav)[t0 + 2:T - 3, 0]
    return float(ret.mean()), float(ret.std(ddof=1) / math.sqrt(len(ret)))


def test_lookahead_canary_cross_section():
    T = 700
    # World 1: every move happens overnight. A signal equal to the NEXT day's return,
    # fed at lag 0, is traded at the next open -- after the move -- so it must earn
    # nothing abnormal. Only a deliberate extra forward shift makes it pay.
    r, opn, close = _world(T, 8, seed=11, mode="overnight")
    nxt = np.vstack([r[1:], np.zeros((1, 8))])                 # S[t] = r[t+1]
    nxt2 = np.vstack([r[2:], np.zeros((2, 8))])                # S[t] = r[t+2] (shifted forward)
    m_canary, se = _xs_mean_daily(opn, close, nxt)
    m_shift, _ = _xs_mean_daily(opn, close, nxt2)
    assert abs(m_canary) < 4 * se and abs(m_canary) < 0.001, m_canary
    assert m_shift > 0.006, m_shift                            # ~ +0.9%/day for top 3 of 8
    # World 2: every move happens intraday. A signal known at the close of t (today's
    # return) must not earn today's return; the engine starts earning at t+1.
    r, opn, close = _world(T, 8, seed=12, mode="intraday")
    m_today, se = _xs_mean_daily(opn, close, r)                # S[t] = r[t]
    nxt = np.vstack([r[1:], np.zeros((1, 8))])
    m_peek, _ = _xs_mean_daily(opn, close, nxt)                # genuine peeking IS rewarded
    assert abs(m_today) < 4 * se and abs(m_today) < 0.001, m_today
    assert m_peek > 0.006, m_peek


def test_lookahead_canary_time_series():
    T = 1500
    r, opn, close = _world(T, 1, seed=21, mode="overnight")
    rr = r[:, 0]
    dec_next = np.concatenate([(rr[1:] > 0).astype(float), [0.0]])      # dec[t] = r[t+1] > 0
    dec_next2 = np.concatenate([(rr[2:] > 0).astype(float), [0.0, 0.0]])
    nav, *_ = TS.run_ts(opn[:, 0], close[:, 0], np.zeros(T), np.stack([dec_next, dec_next2]),
                        1, [0.0], 5)
    ret = C.nav_to_ret(nav)[10:T - 3]
    se = ret[:, 0].std(ddof=1) / math.sqrt(len(ret))
    assert abs(ret[:, 0].mean()) < 4 * se and abs(ret[:, 0].mean()) < 0.0008
    assert ret[:, 1].mean() > 0.003                           # E[max(r,0)] ~ 0.4%/day
    # intraday world: decision from today's return earns nothing today
    r, opn, close = _world(T, 1, seed=22, mode="intraday")
    rr = r[:, 0]
    dec_today = (rr > 0).astype(float)
    nav, *_ = TS.run_ts(opn[:, 0], close[:, 0], np.zeros(T), dec_today[None], 1, [0.0], 5)
    ret = C.nav_to_ret(nav)[10:T - 3, 0]
    assert abs(ret.mean()) < 4 * ret.std(ddof=1) / math.sqrt(len(ret))


def test_signals_use_only_past_closes():
    rng = np.random.default_rng(5)
    P = 100 * np.cumprod(1 + rng.normal(0, 0.01, size=(400, 4)), axis=0)
    S = XS.xs_signal(P, 21)
    S2 = XS.xs_signal(P, 252, 21)
    t = 300
    assert np.allclose(S[t], P[t] / P[t - 21] - 1)
    assert np.allclose(S2[t], P[t - 21] / P[t - 252] - 1)
    Pm = P.copy()
    Pm[t + 1:] *= 3.0                                           # change the future only
    assert np.array_equal(XS.xs_signal(Pm, 21)[:t + 1], S[:t + 1], equal_nan=True)
    assert np.array_equal(XS.xs_signal(Pm, 252, 21)[:t + 1], S2[:t + 1], equal_nan=True)
    assert not np.array_equal(XS.xs_signal(Pm, 21)[t + 1], S[t + 1])
    d = TS.ts_decision(P[:, 0], 63)
    assert np.array_equal(TS.ts_decision(Pm[:, 0], 63)[:t + 1], d[:t + 1], equal_nan=True)
    assert d[t] == float(P[t, 0] / P[t - 63, 0] - 1 > 0)


# ------------------------------------------------------------- (3) tranche tests
def _direct_daily(opn, close, pk, valid, t0, cost):
    """Independent reference for H=1: one account, re-formed every day."""
    T, A = close.shape
    v = np.ones(T)
    w = np.zeros(A)            # dollar holdings
    cash = 1.0
    for s in range(1, T):
        w = w * opn[s] / close[s - 1]
        t = s - 1
        if t >= t0 and valid[t]:
            nv = w.sum() + cash
            tgt = np.zeros(A)
            tgt[pk[t]] = nv / len(pk[t])
            fee = cost * np.abs(tgt - w).sum()
            w = np.zeros(A)
            w[pk[t]] = (nv - fee) / len(pk[t])
            cash = 0.0
        w = w * close[s] / opn[s]
        v[s] = w.sum() + cash
    return v


def test_tranche_h1_equals_untranched_and_hk_is_mean_of_tranches():
    T, A = 300, 7
    rng = np.random.default_rng(31)
    r = rng.normal(0.0003, 0.012, size=(T, A))
    close = 50 * np.cumprod(1 + r, axis=0)
    opn = np.vstack([close[:1], close[:-1] * (1 + rng.normal(0, 0.004, size=(T - 1, A)))])
    elig = np.ones((T, A), bool)
    elig[:30] = False
    S = XS.xs_signal(close, 10)
    pk, valid = XS.build_picks(S, elig, "momentum")
    t0 = int(np.flatnonzero(valid)[0])
    rf = np.zeros(T)
    assert C.tranche_offsets(1) == [0]
    nav, *_ = XS.run_xs(opn, close, rf, pk[None], valid, 1, [0.0005], t0)
    ref = _direct_daily(opn, close, pk, valid, t0, 0.0005)
    assert np.allclose(nav[:, 0], ref, rtol=1e-12, atol=0)
    # H = 5: five tranches; the portfolio is the mean of the five separately run tranches
    assert C.tranche_offsets(5) == [0, 1, 2, 3, 4]
    assert C.tranche_offsets(63) == [3 * k for k in range(21)] and len(C.tranche_offsets(252)) == 21
    nav5, tr5, fee5, _ = XS.run_xs(opn, close, rf, pk[None], valid, 5, [0.0005], t0)
    singles = [XS.run_xs(opn, close, rf, pk[None], valid, 5, [0.0005], t0, offsets=[k])[0][:, 0]
               for k in range(5)]
    assert np.allclose(nav5[:, 0], np.mean(singles, axis=0), rtol=1e-12)
    # every tranche is invested from the first trade day (full notional traded on t0+1)
    assert abs(tr5[t0 + 1, 0] - 1.0) < 1e-12
    # tranche k re-forms on t0+k, t0+k+5, ...: single-tranche turnover days
    one = XS.run_xs(opn, close, rf, pk[None], valid, 5, [0.0005], t0, offsets=[2])[1][:, 0]
    days = np.flatnonzero(one > 0)
    assert days[0] == t0 + 1 and set(days[1:]) <= set(range(t0 + 3, T, 5))


def test_min_names_rule_and_eligibility():
    T, A = 600, 7
    rng = np.random.default_rng(41)
    close = 20 * np.cumprod(1 + rng.normal(0, 0.01, size=(T, A)), axis=0)
    close[:100, 5:] = np.nan                       # two names list on day 100
    opn = close.copy()
    bar = np.isfinite(close)
    elig = C.eligibility(bar, 252)
    assert not elig[251].any() and elig[252, :5].all() and not elig[252, 5:].any()
    assert not elig[351, 5:].any() and elig[352].all()
    S = XS.xs_signal(C.ffill(close), 21)
    pk, valid = XS.build_picks(S, elig, "reversal")
    assert not valid[351] and valid[352]           # 5 names < 6 -> no positions
    t0 = int(np.flatnonzero(valid)[0])
    rf = np.full(T, 0.0001)
    nav, tr, _, _ = XS.run_xs(opn, close, rf, pk[None], valid, 21, [0.0], t0)
    assert np.allclose(nav[:t0 + 1, 0], np.cumprod(1 + rf)[:t0 + 1] / (1 + rf[0]))  # cash at IRX
    assert tr[:t0 + 1].sum() == 0 and tr[t0 + 1, 0] > 0.99
    lo = np.argsort(S[400])[:3]
    assert set(pk[400]) == set(lo)                 # reversal = bottom 3
    ew = C.equal_weight_returns(close, elig, rf)
    assert np.isnan(ew[:t0 + 1]).all()             # benchmark not live before the universe exists
    ew_cash = C.equal_weight_returns(close, elig, rf, blank_prelive=False)
    assert np.allclose(ew_cash[1:t0 + 1], rf[1:t0 + 1])      # superseded variant: cash at IRX
    cc = close[t0 + 1] / close[t0] - 1
    assert abs(ew[t0 + 1] - cc.mean()) < 1e-14 and ew_cash[t0 + 1] == ew[t0 + 1]


def test_missing_bar_is_not_traded_and_is_carried():
    close = np.array([[10.0, 10.0], [11.0, 10.0], [np.nan, 10.0], [12.0, 10.0]])
    opn = close.copy()
    W_a, W_b = np.array([[1.0, 0.0]]), np.array([[0.0, 1.0]])
    plans = {0: W_a, 1: W_b}                       # the switch out of A falls on A's missing day
    nav, tr, _, info = C.simulate(opn, close, np.zeros(4),
                                  lambda t, f: (np.array([0]), plans[t]) if t in plans else None,
                                  [0.0], [0], 1)
    assert info["n_skipped_untradable"] == 1
    assert np.allclose(nav[:, 0], [1.0, 1.0, 1.0, 12.0 / 11.0]) and tr[2, 0] == 0


def test_null_picks_are_eligible_and_random():
    T, A = 400, 9
    rng = np.random.default_rng(51)
    close = 30 * np.cumprod(1 + rng.normal(0, 0.01, size=(T, A)), axis=0)
    close[:, 8] = 30.0 * 1.05 ** np.arange(T)      # a rocket that is never eligible
    elig = np.ones((T, A), bool)
    elig[:, 8] = False
    elig[:20] = False
    valid = elig.sum(axis=1) >= 6
    nav, tr, fee, _ = XS.run_xs_null(close, close, np.zeros(T), elig, valid, 5, 0.0005, 20, 50,
                                     np.random.default_rng(1))
    assert nav.shape == (T, 50) and nav[-1].max() < 5.0     # nobody held the rocket
    assert len(np.unique(np.round(nav[-1], 10))) == 50      # draws differ
    assert np.allclose(fee, 0.0005 * tr)


# ----------------------------------------------------------------- (4) metrics
def test_metrics_on_known_curve():
    ret = np.array([0.10, -0.20, 0.05])
    m = C.perf(ret, np.zeros(3), 365.25)
    assert abs(m["cagr"] - (1.1 * 0.8 * 1.05 - 1)) < 1e-15 and m["irr"] == m["cagr"]
    assert abs(m["mdd"] - (-0.20)) < 1e-15
    assert abs(m["calmar"] - (-0.076 / 0.20)) < 1e-12
    assert abs(m["sharpe"] - (-0.0166666667 / 0.1607275127 * math.sqrt(252))) < 1e-6
    mx = C.perf(ret, np.full(3, 0.01), 365.25)
    assert abs(mx["sharpe_ex"] - (-0.0266666667 / 0.1607275127 * math.sqrt(252))) < 1e-6
    assert mx["sharpe"] == m["sharpe"]                       # no risk-free subtraction
    # CAGR uses calendar days: doubling over 730.5 calendar days = sqrt(2)-1 per year
    g = 2.0 ** (1 / 500) - 1
    m2 = C.perf(np.full(500, g), np.zeros(500), 730.5)
    assert abs(m2["cagr"] - (math.sqrt(2) - 1)) < 1e-12 and m2["mdd"] == 0.0
    assert math.isnan(m2["calmar"])
    # drawdown from the starting value counts
    assert abs(C.perf(np.array([-0.1, 0.2]), np.zeros(2), 10)["mdd"] + 0.1) < 1e-15
    # window slicing: V=1 at the close of the first window day
    dates = np.array(["2020-01-01", "2020-01-02", "2020-01-03", "2021-01-02"], dtype="datetime64[D]")
    r = np.array([0.5, 0.10, -0.20, 0.05])
    w = C.window_perf(r, np.zeros(4), dates, 0, 3)
    assert w["n_days"] == 3 and abs(w["total_return"] - (1.1 * 0.8 * 1.05 - 1)) < 1e-15
    assert abs(w["cagr"] - ((0.924) ** (365.25 / 367) - 1)) < 1e-15
    # a series that starts inside the window is measured from its own first close
    r2 = np.array([np.nan, np.nan, 0.10, 0.10])
    w2 = C.window_perf(r2, np.zeros(4), dates, 0, 3)
    assert w2["start_date"] == "2020-01-02" and w2["n_days"] == 2
    ex, ir = C.rel_perf(r, r2, dates, 0, 3)
    cd = 366
    assert abs(ex - ((0.8 * 1.05) ** (365.25 / cd) - 1.21 ** (365.25 / cd))) < 1e-12


def test_bh_qvalues_and_cash_rate():
    q = C.bh_qvalues([0.01, 0.04, 0.03, 0.005])
    assert np.allclose(q, [0.02, 0.04, 0.04, 0.02])
    q = C.bh_qvalues([0.5, np.nan, 0.001])
    assert np.isnan(q[1]) and np.allclose(q[[0, 2]], [0.5, 0.002])
    idates = np.array(["2020-01-02", "2020-01-06"], dtype="datetime64[D]")
    dates = np.array(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"], dtype="datetime64[D]")
    rf = C.cash_rate_from_series(idates, np.array([2.52, 5.04]), dates)
    assert np.allclose(rf, [0.0, 1e-4, 1e-4, 2e-4])            # previous available value only


def test_turnover_and_cost_drag():
    T = 253
    close = np.column_stack([np.full(T, 10.0), np.full(T, 10.0)])
    flip = {t: np.array([[1.0, 0.0]]) if t % 2 == 0 else np.array([[0.0, 1.0]]) for t in range(T)}
    nav, tr, fee, _ = C.simulate(close, close, np.zeros(T), lambda t, f: (np.array([0]), flip[t]),
                                 [0.001], [0], 1)
    to, drag = C.turnover_stats(tr, fee, nav, 1, 252)          # days 2..252: full switch daily
    assert abs(to[0] - 251 / (251 / 252)) < 1e-9               # one-way = 1 x NAV per day
    assert abs(drag[0] - 0.002 * 252) < 1e-9                   # two sides x 10 bps


# ------------------------------------------------------------ US-B vector path
def test_fast_path_matches_engine_and_shift_null():
    T = 900
    rng = np.random.default_rng(61)
    r = rng.normal(0.0004, 0.012, size=T)
    close = 80 * np.cumprod(1 + r)
    opn = np.concatenate([close[:1], close[:-1] * (1 + rng.normal(0, 0.005, size=T - 1))])
    rf = np.full(T, 0.00012)
    t0 = 260
    dec = np.nan_to_num(TS.ts_decision(close, 21))
    for H in (1, 5, 63):
        nav, *_ = TS.run_ts(opn, close, rf, dec[None], H, [0.0005], t0)
        ret = C.nav_to_ret(nav)[:, 0]
        pos = TS.tranche_positions(dec, H, t0)[:, t0:]
        lon, lin, lrf = TS.leg_logs(opn, close, rf)
        fast = TS.fast_nav(pos[:, None, :], lon[t0:], lin[t0:], lrf[t0:], 0.0005)[0]
        assert np.allclose(fast, np.cumprod(1 + ret[t0 + 1:]), rtol=1e-10), H
    pos = TS.tranche_positions(dec, 5, t0)[:, t0:]
    n = pos.shape[1]
    shifts = np.array([0, 252, n - 252])
    (oc, ok), nc, nk = TS.shift_null(pos, lon[t0:], lin[t0:], lrf[t0:], 0.0005, 900.0, shifts)
    assert abs(nc[0] - oc) < 1e-12 and abs(nk[0] - ok) < 1e-12   # shift 0 == observed
    assert abs(nc[1] - oc) > 1e-6                                 # a real shift changes it
    # always-in is invariant to shifting -> p = 1
    ones = np.ones((1, n))
    (oc, ok), nc, nk = TS.shift_null(ones, lon[t0:], lin[t0:], lrf[t0:], 0.0005, 900.0,
                                     np.array([300, 400]))
    assert TS.one_sided_p(nc, oc) == 1.0 and TS.one_sided_p(nk, ok) == 1.0
    # contrarian is the exact complement of momentum
    assert TS.live_index(np.ones(600, bool)) == 252


# -------------------------------------------------------------------- US-C
def test_overnight_legs_and_breakeven():
    rng = np.random.default_rng(71)
    T = 300
    close = 40 * np.cumprod(1 + rng.normal(0.0005, 0.01, size=T))
    opn = np.concatenate([close[:1], close[:-1] * (1 + rng.normal(0.0003, 0.004, size=T - 1))])
    legs = ON.leg_returns(opn, close)
    assert np.isnan(legs["overnight"][0])
    assert np.allclose((1 + legs["overnight"][1:]) * (1 + legs["intraday"][1:]),
                       close[1:] / close[:-1])
    assert abs(legs["overnight"][5] - (opn[5] / close[4] - 1)) < 1e-15
    g = float(np.prod(1 + legs["overnight"][1:]))
    be = ON.breakeven_bps(g, 1.0, T - 1)
    net = ON.net_of_cost(legs["overnight"][1:], be / 1e4, 2)
    assert abs(np.prod(1 + net) - 1.0) < 1e-10                  # zero profit at break-even
    assert np.allclose(ON.net_of_cost(legs["intraday"][1:], 0.0001, 2),
                       (1 + legs["intraday"][1:]) * 0.9999 ** 2 - 1)


# ------------------------------------------------- repair-round regression tests
def test_prelive_cash_is_not_scored_against_benchmark():
    """A universe that only exists from day t0 must not be credited with T-bill
    returns earned before t0 while the benchmark is falling (the MA-universe bug)."""
    T, A, t_live = 400, 6, 200
    rng = np.random.default_rng(81)
    r = rng.normal(0.0, 0.01, size=(T, A))
    close = 100 * np.cumprod(1 + r, axis=0)
    opn = np.vstack([close[:1], close[:-1]])
    elig = np.ones((T, A), bool)
    elig[:t_live] = False
    S = XS.xs_signal(close, 5)
    pk, valid = XS.build_picks(S, elig, "momentum")
    t0 = int(np.flatnonzero(valid)[0])
    assert t0 == t_live
    rf = np.full(T, 0.0002)
    nav, tr, fee, _ = XS.run_xs(opn, close, rf, pk[None], valid, 5, [0.0], t0)
    raw = C.nav_to_ret(nav)
    live = C.blank_before(raw, t0)
    assert np.isnan(live[:t0 + 1]).all() and np.array_equal(live[t0 + 1:], raw[t0 + 1:])
    # benchmark: -0.5% a day before the universe exists, then identical to the cell
    bench = np.where(np.arange(T) <= t0, -0.005, raw[:, 0])
    bench[0] = np.nan
    dates = np.datetime64("2000-01-03") + np.arange(T).astype("timedelta64[D]")
    bounds = {w: (1, T - 1) for w in C.WINDOW_ORDER}
    b = {"SPY": bench, "QQQ": bench, "SMH": bench, "EW": C.blank_before(bench, t0)}
    rows = C.metric_rows(live, rf, dates, bounds, b, "EW", tr, fee, nav)["FULL"][0]
    assert rows["start_date"] == str(dates[t0])             # V=1 at the decision-day close
    assert abs(rows["excess_cagr_vs_SPY"]) < 1e-12          # same returns on the live days
    assert abs(rows["excess_cagr_vs_EW"]) < 1e-12
    old = C.metric_rows(raw, rf, dates, bounds, b, "EW")["FULL"][0]
    assert old["excess_cagr_vs_SPY"] > 0.5                  # the superseded convention's artefact
    # turnover is annualised over the live days only
    yrs = (T - 1 - t0) / 252.0
    assert abs(rows["turnover_ann"] - (tr[t0 + 1:, 0] / nav[t0:-1, 0]).sum() / 2 / yrs) < 1e-12


def test_tranche_entry_modes():
    """Frozen cells: every tranche enters on day one. Sensitivity: tranche k stays in
    cash until its own first decision day. Both then re-form on the same schedule."""
    T, A, H = 200, 7, 5
    rng = np.random.default_rng(82)
    close = 50 * np.cumprod(1 + rng.normal(0.0003, 0.012, size=(T, A)), axis=0)
    opn = np.vstack([close[:1], close[:-1] * (1 + rng.normal(0, 0.004, size=(T - 1, A)))])
    elig = np.ones((T, A), bool)
    elig[:30] = False
    pk, valid = XS.build_picks(XS.xs_signal(close, 10), elig, "momentum")
    t0 = int(np.flatnonzero(valid)[0])
    rf = np.full(T, 0.0001)
    run = lambda **kw: XS.run_xs(opn, close, rf, pk[None], valid, H, [0.0005], t0, **kw)  # noqa: E731
    nav_d, tr_d, _, _ = run()
    nav_s, tr_s, _, _ = run(entry="staggered")
    assert abs(tr_d[t0 + 1, 0] - np.cumprod(1 + rf)[t0 + 1] / (1 + rf[0])) < 1e-12   # all in on day one
    assert abs(tr_s[t0 + 1, 0] - tr_d[t0 + 1, 0] / H) < 1e-12                        # one tranche of five
    for k in range(H):
        one_s = run(entry="staggered", offsets=[k])
        one_d = run(offsets=[k])
        first = int(np.flatnonzero(one_s[1][:, 0] > 0)[0])
        assert first == t0 + k + 1                           # cash until its own offset
        assert np.allclose(one_s[0][:first, 0], np.cumprod(1 + rf)[:first] / (1 + rf[0]))
        if k == 0:
            assert np.array_equal(one_s[0], one_d[0])
        else:   # after its first re-form the tranche holds the same names either way
            a, b = one_s[0][:, 0], one_d[0][:, 0]
            assert np.allclose(a[t0 + k + 2:] / a[t0 + k + 1:-1], b[t0 + k + 2:] / b[t0 + k + 1:-1],
                               rtol=1e-9)
    assert not np.allclose(nav_s[:, 0], nav_d[:, 0])
    # H = 1 has a single tranche: the two modes are the same thing
    assert np.array_equal(XS.run_xs(opn, close, rf, pk[None], valid, 1, [0.0005], t0)[0],
                          XS.run_xs(opn, close, rf, pk[None], valid, 1, [0.0005], t0, entry="staggered")[0])
    # null follows the same rule
    n_s = XS.run_xs_null(opn, close, rf, elig, valid, H, 0.0, t0, 3, np.random.default_rng(1),
                         entry="staggered")[1]
    assert abs(n_s[t0 + 1, 0] - np.cumprod(1 + rf)[t0 + 1] / (1 + rf[0]) / H) < 1e-12
    # in / out pipeline
    dec = np.ones((1, T))
    ts_d = TS.run_ts(opn[:, 0], close[:, 0], rf, dec, H, [0.0], t0)
    ts_s = TS.run_ts(opn[:, 0], close[:, 0], rf, dec, H, [0.0], t0, entry="staggered")
    assert abs(ts_d[1][t0 + 1, 0] - H * ts_s[1][t0 + 1, 0]) < 1e-12
    assert (ts_s[1][t0 + 1:t0 + H + 1, 0] > 0).all() and ts_s[1][t0 + H + 1:, 0].sum() == 0
    assert np.allclose(ts_s[0][t0 + H + 5:, 0] / ts_s[0][t0 + H + 4:-1, 0],
                       ts_d[0][t0 + H + 5:, 0] / ts_d[0][t0 + H + 4:-1, 0])


def test_calmar_better_readings():
    """Negative Calmars rank the wrong way round: the literal clause is kept, two
    alternative readings are reported next to it."""
    f = C.calmar_better
    # both positive: plain ratio comparison under every reading
    for mode in ("literal", "economic", "strict"):
        assert f(0.10, -0.20, 0.08, -0.40, mode) and not f(0.05, -0.50, 0.08, -0.40, mode)
    # buy-and-hold -1% / -55% (Calmar -0.018); cell -0.5% / -10% (Calmar -0.05): the cell
    # is better on both counts but its Calmar is 'lower'
    assert not f(-0.005, -0.10, -0.01, -0.55, "literal")
    assert f(-0.005, -0.10, -0.01, -0.55, "economic")
    assert not f(-0.005, -0.10, -0.01, -0.55, "strict")
    # cell -5% / -60% vs buy-and-hold -3% / -30%: worse on both counts, 'higher' Calmar
    assert f(-0.05, -0.60, -0.03, -0.30, "literal")
    assert not f(-0.05, -0.60, -0.03, -0.30, "economic")
    assert not f(-0.05, -0.60, -0.03, -0.30, "strict")
    # mixed signs agree under every reading
    for mode in ("literal", "economic", "strict"):
        assert f(0.01, -0.30, -0.01, -0.10, mode) and not f(-0.01, -0.10, 0.01, -0.30, mode)
    out = f(np.array([0.1, np.nan]), np.array([-0.2, -0.2]), np.array([0.08, 0.08]),
            np.array([-0.4, -0.4]), "strict")
    assert out.tolist() == [True, False]


def test_window_first_day_option():
    """Frozen convention: V=1 at the close of the window's first session. Sensitivity:
    V=1 at the previous close, so the first session's return is counted."""
    dates = np.array(["2019-12-31", "2020-01-02", "2020-01-03", "2021-01-04"], dtype="datetime64[D]")
    r = np.array([np.nan, 0.10, -0.20, 0.05])
    w = C.window_perf(r, np.zeros(4), dates, 1, 3)
    assert w["n_days"] == 2 and w["start_date"] == "2020-01-02"
    assert abs(w["total_return"] - (0.8 * 1.05 - 1)) < 1e-15
    wi = C.window_perf(r, np.zeros(4), dates, 1, 3, include_first=True)
    assert wi["n_days"] == 3 and wi["start_date"] == "2019-12-31"
    assert abs(wi["total_return"] - (1.1 * 0.8 * 1.05 - 1)) < 1e-15
    assert abs(wi["cagr"] - (0.924 ** (365.25 / 370) - 1)) < 1e-15
    # a series that starts inside the window is unaffected
    r2 = np.array([np.nan, np.nan, 0.10, 0.10])
    assert C.live_start(r2, 1) == C.live_start(r2, 1, include_first=True) == 1
    ex, _ = C.rel_perf(r, r2, dates, 1, 3, include_first=True)
    assert abs(ex - ((0.8 * 1.05) ** (365.25 / 368) - 1.21 ** (365.25 / 368))) < 1e-12


def test_exact_fee_fixed_point():
    """fee_iters > 0 solves fee = cost x |W x (NAV - fee) - holding| ; the frozen
    engine uses the pre-fee NAV (first-order approximation)."""
    close = np.array([[100.0, 100.0], [100.0, 100.0], [110.0, 90.0], [110.0, 90.0]])
    cost = 0.01
    plans = {0: np.array([[1.0, 0.0]]), 1: np.array([[0.5, 0.5]])}
    plan = lambda t, f: (np.array([0]), plans[t]) if t in plans else None  # noqa: E731
    nav_a, tr_a, fee_a, _ = C.simulate(close, close, np.zeros(4), plan, [cost], [0], 1)
    nav_x, tr_x, fee_x, _ = C.simulate(close, close, np.zeros(4), plan, [cost], [0], 1, fee_iters=60)
    assert abs(fee_a[1, 0] - cost) < 1e-15                   # approximation: cost x NAV
    assert abs(fee_x[1, 0] - cost / (1 + cost)) < 1e-14      # exact: fee = cost x (NAV - fee)
    assert abs(nav_x[1, 0] + fee_x[1, 0] - 1.0) < 1e-14
    # day 2: holding h in A (after +10%), rebalance to 50/50; check the fixed point
    h = nav_x[1, 0] * 1.10
    f2 = fee_x[2, 0]
    assert abs(f2 - cost * (abs(0.5 * (h - f2) - h) + 0.5 * (h - f2))) < 1e-13
    assert abs(tr_x[2, 0] * cost - f2) < 1e-15 and nav_x[-1, 0] > nav_a[-1, 0]
    assert abs(nav_x[-1, 0] / nav_a[-1, 0] - 1) < 2 * cost ** 2


def test_closest_cells_single_ordering():
    """summary.md and verdict.json must list the same 'closest' cells."""
    import pandas as pd
    p = pd.DataFrame({"n_pass": [1, 1, 1, 2, 0], "pass_1": [False, True, True, False, False],
                      "null_p": [0.01, 0.50, 0.20, 0.90, 0.001]}, index=list("abcde"))
    assert C.closest_cells(p, "US-B", 4) == ["d", "c", "b", "a"]     # n_pass, pass_1, null_p
    assert C.closest_cells(p, "US-A", 4) == ["d", "a", "c", "b"]     # n_pass, null_p
    q = p.iloc[::-1]                                                 # row order must not matter
    assert C.closest_cells(q, "US-B", 4) == ["d", "c", "b", "a"]
    tie = pd.DataFrame({"n_pass": [1, 1], "pass_1": [True, True], "null_p": [0.3, 0.3]}, index=["z", "y"])
    assert C.closest_cells(tie, "US-B") == ["y", "z"]


def test_t1_close_execution_variant():
    """Passing the close as the 'open' executes at the close of t+1 (sensitivity)."""
    close = np.array([[100.0], [110.0], [121.0], [133.1]])
    opn = np.array([[100.0], [100.0], [110.0], [121.0]])       # all moves are intraday
    plan = lambda t, f: (np.array([0]), np.array([[1.0]])) if t == 0 else None  # noqa: E731
    nav_o, *_ = C.simulate(opn, close, np.zeros(4), plan, [0.0], [0], 1)
    nav_c, *_ = C.simulate(close, close, np.zeros(4), plan, [0.0], [0], 1)
    assert np.allclose(nav_o[:, 0], [1.0, 1.10, 1.21, 1.331])  # open fill earns day 1
    assert np.allclose(nav_c[:, 0], [1.0, 1.00, 1.10, 1.21])   # close fill starts a day later


def test_suspect_open_replaced_only_in_sensitivity():
    dates = np.array(["2002-01-04", "2002-01-07", "2002-01-08", "2002-01-09"], dtype="datetime64[D]")
    ac = np.array([[18.6, 50.0], [18.63, 50.0], [18.73, 50.0], [18.63, 50.0]])
    ao = ac.copy()
    ao[2, 0] = 15.12                                           # the bad print
    panel = C.Panel(dates, ["XLV", "SPY"], ac, ao, np.zeros(4))
    fixed, n = XS.fix_suspect_opens(panel, [0, 1], ["XLV", "SPY"], ao)
    assert n == 1 and fixed[2, 0] == 18.63 and ao[2, 0] == 15.12   # original untouched
    assert np.array_equal(np.delete(fixed.ravel(), 4), np.delete(ao.ravel(), 4))
    assert XS.fix_suspect_opens(panel, [1], ["SPY"], ao[:, 1:])[1] == 0
    assert ("XLV", "2002-01-08") in C.SUSPECT_OPENS


def test_prior_rule_diagnostics_building_blocks():
    """Rank-mean ensemble, 210-style average filter and per-slot cash routing used by
    the sanity-anchor diagnostics (not study cells)."""
    T, A = 40, 4
    close = np.ones((T, A)) * 100.0
    close[:, 0] = 100 + np.arange(T) * 1.0        # steady winner
    close[:, 1] = 100 - np.arange(T) * 0.5        # steady loser
    close[:, 2] = 100 + np.arange(T) * 0.5
    close[:, 3] = 100 + np.arange(T) * 0.25
    elig = np.ones((T, A), bool)
    elig[:12] = False
    pk, valid = XS.ensemble_picks(close, elig, lookbacks=(3, 6, 9), n_pick=2, min_names=4)
    assert valid[12] and not valid[11] and list(pk[30]) == [0, 2]
    # ties in the rank-mean are broken by the longest-lookback return
    S3, S9 = XS.xs_signal(close, 3), XS.xs_signal(close, 9)
    c2 = close.copy()
    c2[:, 2] = close[:, 0]                        # identical series -> tie -> column order
    pk2, _ = XS.ensemble_picks(c2, elig, lookbacks=(3, 6, 9), n_pick=1, min_names=4)
    assert pk2[30, 0] == 0 and S3[30, 0] > S3[30, 2] and S9[30, 0] > S9[30, 2]
    above = XS.sma_above(close, 10)
    assert not above[:9].any() and above[20, 0] and not above[20, 1]
    assert above[9, 0] == (close[9, 0] > close[:10, 0].mean())
    # slot filter: a pick below its average is replaced by cash for the holding period
    picks = np.zeros((1, T, 2), int)
    picks[0, :, 1] = 1                            # always "pick" the winner and the loser
    slot_ok = np.take_along_axis(above, picks[0], axis=1)[None]
    valid = np.ones(T, bool)
    rf = np.full(T, 0.001)
    nav, tr, _, _ = XS.run_xs(close, close, rf, picks, valid, 5, [0.0], 12, offsets=[0], slot_ok=slot_ok)
    assert abs(tr[13, 0] - 0.5 * np.prod(1 + rf[1:14])) < 1e-12        # only the winner is bought
    exp = 0.5 * close[14, 0] / close[13, 0] + 0.5 * (1 + rf[14])
    assert abs(nav[14, 0] / nav[13, 0] - exp) < 1e-12
    # an account that is all cash on purpose waits for its schedule (no daily re-entry)
    none_ok = np.zeros_like(slot_ok)
    nav0, tr0, _, _ = XS.run_xs(close, close, rf, picks, valid, 5, [0.0], 12, offsets=[0], slot_ok=none_ok)
    assert tr0.sum() == 0 and np.allclose(nav0[:, 0], np.cumprod(1 + rf) / (1 + rf[0]))


# ---------------------------------------------------------------- real data guard
def test_no_2026_rows_and_adjusted_open():
    if not os.path.isdir(C.RAW_ROOT):
        return
    df = C.read_raw("SPY")
    assert df["date"].max() == "2025-12-31" and df["date"].min() < "1999-01-01"
    assert C.read_raw("IRX_INDX")["date"].max() <= "2025-12-31"
    panel = C.build_panel(["SPY", "QQQ"])
    assert str(panel.dates[-1]) == "2025-12-31"
    i = len(df) - 1
    exp = df["open"].iloc[i] * df["adjusted_close"].iloc[i] / df["close"].iloc[i]
    assert abs(panel.adj_open[i, 0] - exp) < 1e-12
    assert set(C.EQ) <= set(C.ALL_SYMS) and all(os.path.exists(C.raw_path(s)) for s in C.ALL_SYMS)


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print("PASS", name)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            import traceback
            print("FAIL", name, repr(exc))
            traceback.print_exc()
    print("%d tests, %d failed" % (len(fns), failed))
    sys.exit(1 if failed else 0)
