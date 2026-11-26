#!/usr/bin/env python3
"""Self-checks for study ETF-C.  Run:  python -B test_etfc.py
Covers: end-date filter, synthetic formula, no-margin exposure split, engine against an
independent scalar loop, buy-and-hold identity, no look-ahead, circular shift, monthly
investing against a share-count calculation."""
from __future__ import annotations

import copy
import math

import numpy as np

import etfc_common as C
import run_etfc as R
from etfc_common import IDX


def test_end_date(data):
    assert str(data.dates[-1]) == "2025-12-31"
    for s in C.ONE_X + ["TQQQ", "IRX_INDX"]:
        assert C.read_raw(s)["date"].max() <= C.END_DATE


def test_synth_formula(data):
    on = np.array([1.01]); cc = np.array([1.02]); irx = np.array([0.04])
    o, i, c = C.synth_factors(on, cc, irx, 2.0)
    assert abs(c[0] - (1 + 2 * 0.02 - 1 * (0.04 + 0.005) / 252 - 0.0095 / 252)) < 1e-15
    assert abs(o[0] - 1.02) < 1e-15 and abs(o[0] * i[0] - c[0]) < 1e-15
    o, i, c = C.synth_factors(on, cc, irx, 3.0)
    assert abs(c[0] - (1 + 3 * 0.02 - 2 * 0.045 / 252 - 0.0095 / 252)) < 1e-15
    # the 2x twin in the panel is that formula applied to the 1x close-to-close return
    q, l = IDX["QQQ"], IDX["QQQ2X"]
    s = data.i_start + 100
    exp = 1 + 2 * (data.cc[s, q] - 1) - (data.irx_ann[s] + 0.005) / 252 - 0.0095 / 252
    assert abs(data.cc[s, l] - exp) < 1e-12


def test_overlay():
    wb = C.static_w({"QQQ": 0.5, "TLT": 0.3, "GLD": 0.2}, 5)
    e = np.array([0.0, 0.4, 1.0, 1.5, 2.0])
    W = C.overlay(wb, e)
    assert np.allclose(W.sum(axis=1), 1.0) and (W >= 0).all()
    lev = np.array([2.0 if s.endswith("2X") else (0.0 if s == "BIL" else 1.0) for s in C.INSTR])
    assert np.allclose(W @ lev, e)                       # effective exposure, no margin
    assert W[0, C.BIL] == 1.0 and W[4, IDX["QQQ2X"]] == 0.5 and W[4, IDX["QQQ"]] == 0.0


def test_engine_reference(data, cells):
    c = cells["V1"]
    q, l, b = IDX["QQQ"], IDX["QQQ2X"], C.BIL
    r = data.ret[:, q]
    cost = 0.0005
    h = [0.0, 0.0, 0.0]
    cash = 1.0
    decs = set(c.dec.tolist())
    ref = []
    for s in range(data.i_start + 1, data.T):
        for k, a in enumerate((q, l, b)):
            h[k] *= data.on[s, a]
        cash *= 1 + data.rf[s]
        if s - 1 in decs:
            vol = np.std(r[s - 63:s], ddof=1) * math.sqrt(252)
            e = min(2.0, max(0.0, 0.18 / vol))
            w = [e, 0.0, 1 - e] if e <= 1 else [2 - e, e - 1, 0.0]
            nv, fee = sum(h) + cash, 0.0
            for _ in range(60):
                fee = cost * sum(abs(w[k] * (nv - fee) - h[k]) for k in range(3))
            h, cash = [w[k] * (nv - fee) for k in range(3)], 0.0
        for k, a in enumerate((q, l, b)):
            h[k] *= data.intr[s, a]
        ref.append(sum(h) + cash)
    sim = C.simulate(data, c.dec, c.W, cost)
    assert np.max(np.abs(np.array(ref) / sim["nav"][data.i_start + 1:, 0] - 1)) < 1e-10


def test_buy_hold_identity(data):
    dec = np.array([data.i_start])
    sim = C.simulate(data, dec, C.static_w({"SPY": 1.0}, 1), 0.0)
    r = sim["ret"][:, 0]
    spy = data.ret[:, IDX["SPY"]]
    assert np.allclose(r[data.i_start + 2:], spy[data.i_start + 2:], atol=1e-12)
    assert np.isnan(r[:data.i_start + 1]).all()


def test_no_lookahead(data, cells):
    X = data.idx_of("2015-06-30", "right")
    d2 = copy.deepcopy(data)
    rng = np.random.default_rng(7)
    noise = np.exp(rng.normal(0, 0.03, size=(data.T - X - 1, len(C.ONE_X))))
    for k, s in enumerate(C.ONE_X):
        a = IDX[s]
        d2.on[X + 1:, a] *= noise[:, k]
        d2.adj_close[X + 1:, a] *= np.cumprod(noise[:, k])
    for s in C.LEV2_OF:
        a = IDX[s]
        o, i, _ = C.synth_factors(d2.on[:, a], d2.on[:, a] * d2.intr[:, a], d2.irx_ann, 2.0)
        d2.on[:, IDX[s + "2X"]], d2.intr[:, IDX[s + "2X"]] = o, i
    d2.cc = d2.on * d2.intr
    d2.ret = d2.cc - 1.0
    c2 = R.build_cells(d2)
    for name, c in cells.items():
        k = c.dec <= X
        assert (c.dec[k] == c2[name].dec[k]).all(), name
        assert np.allclose(c.W[k], c2[name].W[k], atol=1e-12, equal_nan=True), name
        a = C.simulate(data, c.dec, c.W, 0.0005)["nav"][:X + 1, 0]
        b = C.simulate(d2, c2[name].dec, c2[name].W, 0.0005)["nav"][:X + 1, 0]
        assert np.allclose(a, b, rtol=1e-12), name
        assert not np.allclose(c.W[~k], c2[name].W[~k]) or name in ("S1", "S2", "S3", "B6040")


def test_decision_calendar(data, cells):
    d = data.dates
    for name in ("V1", "R1", "T1"):
        dec = cells[name].dec[1:]
        m = d[dec].astype("datetime64[M]")
        assert (d[dec + 1].astype("datetime64[M]") != m).all()       # trades on a new month
        assert len(np.unique(m)) == len(m)
    for name in ("S1", "S2", "S3"):
        dec = cells[name].dec[1:]
        assert (d[dec + 1].astype("datetime64[Y]") != d[dec].astype("datetime64[Y]")).all()
        assert len(dec) == 20                                        # year-ends 2005..2024
    assert cells["S1"].dec[0] == data.i_start


def test_shift(data, cells):
    c = cells["V1"]
    t0 = int(c.dec[0])
    n = data.T - t0
    k = 777
    pos = t0 + ((np.arange(t0, data.T) - t0 + k) % n)
    assert sorted(pos.tolist()) == list(range(t0, data.T))            # a permutation of live days
    assert np.isclose(np.sort(c.e_daily[pos]).sum(), np.sort(c.e_daily[t0:]).sum())


def test_dca_share_count(data):
    cost = 0.0005
    out = R.dca(data, {"SPY": 1.0}, cost)
    a = IDX["SPY"]
    lvl = np.cumprod(np.where(np.isfinite(data.cc[:, a]), data.cc[:, a], 1.0))   # adjusted close index
    units, n = 0.0, 0
    for s in range(data.i_start + 1, data.T):
        if data.month_end[s - 1] or s - 1 == data.i_start:
            open_px = lvl[s - 1] * data.on[s, a]
            units += (1 - cost) / open_px
            n += 1
    assert n == out["dca_n_contributions"] == 252
    assert abs(units * lvl[-1] / n / out["dca_multiple"] - 1) < 1e-4


def main():
    data = C.Data()
    cells = R.build_cells(data)
    tests = [(test_end_date, (data,)), (test_synth_formula, (data,)), (test_overlay, ()),
             (test_engine_reference, (data, cells)), (test_buy_hold_identity, (data,)),
             (test_no_lookahead, (data, cells)), (test_decision_calendar, (data, cells)),
             (test_shift, (data, cells)), (test_dca_share_count, (data,))]
    for fn, args in tests:
        fn(*args)
        print("ok  ", fn.__name__)
    print("all %d checks passed" % len(tests))


if __name__ == "__main__":
    main()
