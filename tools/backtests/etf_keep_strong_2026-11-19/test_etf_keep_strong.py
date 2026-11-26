"""Tests for the ETF keep-the-strong engine. pytest-style plain functions (pytest collects them);
`python3 test_etf_keep_strong.py` runs them with a tiny built-in runner when pytest is not installed."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D      # noqa: E402
import engine as E    # noqa: E402

C = E.COST_BASE


def toy_keep():
    A = [100, 100, 100, 100, 120, 126, 126, 126]
    B = [100, 105, 110, 110, 110, 121, 121, 121]
    Cc = [100, 100, 90, 90, 90, 99, 99, 99]
    return np.array([A, B, Cc], float).T


def toy_cull():
    A = [100, 100, 100, 100, 95, 95, 95, 95]
    B = [100, 105, 110, 110, 110, 121, 121, 121]
    Cc = [100, 100, 90, 90, 99, 99, 99, 99]
    return np.array([A, B, Cc], float).T


def toy_stay():
    A = [100, 100, 100, 100, 110, 110, 110, 110, 121, 121]
    B = [100, 105, 110, 110, 115.5, 115.5, 92.4, 92.4, 92.4, 92.4]
    Cc = [100, 100, 95, 95, 95, 95, 114, 114, 114, 114]
    return np.array([A, B, Cc], float).T


def run_toy(P, checks, form, cost=C):
    W = E.strategy_targets(P, checks, 2, 0, form)
    R = E.returns(P)
    out, wt = E.simulate(R, [c + 1 for c in checks], W[None], cost)
    return W, out[0], wt[0]


# ---------------------------------------------------------------- data end date
def test_clip_end_drops_rows_after_2025_12_31():
    idx = pd.to_datetime(["2025-12-30", "2025-12-31", "2026-01-02", "2026-06-01"])
    s = D.clip_end(pd.Series([1.0, 2.0, 3.0, 4.0], index=idx))
    assert list(s.values) == [1.0, 2.0] and s.index.max() == pd.Timestamp("2025-12-31")


def test_loaded_data_has_no_row_after_end_date():
    px = D.load_all()
    for k, s in px.items():
        assert s.index.max() <= pd.Timestamp(D.END_DATE), k
    df = D.common_frame(px, D.G7)
    assert df.index.max() <= pd.Timestamp("2025-12-31")


# ---------------------------------------------------------------- signal uses only data up to the check day
def test_signal_ignores_future_rows():
    rng = np.random.default_rng(1)
    P = 100 * np.cumprod(1 + rng.normal(0, 0.01, (400, 3)), axis=0)
    c = 300
    for form in E.FORMS:
        for L, skip in E.LOOKBACKS.values():
            w1 = E.strategy_targets(P, [c], L, skip, form)
            P2 = P.copy()
            P2[c + 1:] = rng.uniform(1, 1000, P2[c + 1:].shape)   # scramble everything after the check
            w2 = E.strategy_targets(P2, [c], L, skip, form)
            assert np.array_equal(w1, w2)


def test_momentum_definitions():
    P = np.arange(1, 301, dtype=float)[:, None] * np.array([[1.0, 2.0]])
    c = 280
    assert np.allclose(E.momentum(P, c, 126, 0), P[c] / P[c - 126] - 1)
    assert np.allclose(E.momentum(P, c, 252, 21), P[c - 21] / P[c - 252] - 1)


# ---------------------------------------------------------------- trade one session after the check
def test_trade_one_session_after_check_keep():
    P = toy_keep()
    W, r, wt = run_toy(P, [2, 4], "keep")
    assert np.allclose(W[0], [0, 1, 0]) and np.allclose(W[1], [1, 0, 0])
    assert np.allclose(r[:3], 0)                                   # nothing before the first trade
    assert np.isclose(r[3], -C)                                    # buy from cash at close of c+1
    assert np.isclose(r[4], 0.0)                                   # B earns R_B[4] = 0
    # session 5 = trade session of check 4: the OLD holding B still earns +10%; A's +5% is not earned
    assert np.isclose(r[5], 1.1 * (1 - 2 * C) - 1)
    assert np.allclose(r[6:], 0)                                   # A earns nothing afterwards
    assert np.allclose(wt[3], [0, 1, 0]) and np.allclose(wt[5], [1, 0, 0])


# ---------------------------------------------------------------- weights sum to one
def test_weights_sum_to_one():
    for P, chk in ((toy_keep(), [2, 4]), (toy_cull(), [2, 4]), (toy_stay(), [2, 4, 6])):
        for form in E.FORMS:
            W, r, wt = run_toy(P, chk, form)
            assert np.allclose(W.sum(1), 1.0)
            assert np.allclose(wt[chk[0] + 1:].sum(1), 1.0)
    rng = np.random.default_rng(3)
    for n in (3, 7):
        for form, ns in (("keep", None), ("cull", None), ("stay", 2)):
            Wr = E.random_targets(rng, 50, 10, n, form, ns)
            assert np.allclose(Wr.sum(2), 1.0)


# ---------------------------------------------------------------- cost only when a trade is needed
def test_cost_only_on_switches_stay():
    P = toy_stay()
    W, r, wt = run_toy(P, [2, 4, 6], "stay")
    assert np.allclose(W[0], [0, 1, 0]) and np.allclose(W[1], [0, 1, 0])   # B ranks 2nd -> stays
    assert np.allclose(W[2], [0, 0, 1])                                    # B ranks 3rd -> C
    r0 = run_toy(P, [2, 4, 6], "stay", cost=0.0)[1]
    diff = (1 - (1 + r) / (1 + r0))                                        # cost fraction per session
    # costs: initial buy (session 3) and the switch (session 7) only; none on session 5 (no switch)
    assert np.isclose(diff[3], C) and np.isclose(diff[7], 2 * C)
    assert np.allclose(np.delete(diff, [3, 7]), 0)
    # hand values
    assert np.isclose(r[4], 115.5 / 110 - 1) and np.isclose(r[5], 0.0)
    assert np.isclose(r[6], 92.4 / 115.5 - 1) and np.isclose(r[7], -2 * C)
    assert np.isclose(r[8], 0.0) and np.isclose(r[9], 0.0)


def test_cost_zero_when_target_unchanged_keep():
    P = np.array([[100, 100], [101, 100], [103, 100], [106, 100], [110, 100], [111, 100], [112, 100]], float)
    W, r, wt = run_toy(P, [2, 4], "keep")          # asset 0 always best
    r0 = run_toy(P, [2, 4], "keep", cost=0.0)[1]
    assert np.isclose(1 - (1 + r[3]) / (1 + r0[3]), C)       # only the first buy costs
    assert np.allclose(r[4:], r0[4:])


# ---------------------------------------------------------------- hand-computed toy: cull (汰弱)
def test_toy_cull_hand_computed():
    P = toy_cull()
    W, r, wt = run_toy(P, [2, 4], "cull")
    assert np.allclose(W[0], [0.5, 0.5, 0.0])                # sells weakest (C)
    assert np.allclose(W[1], [0.0, 0.5, 0.5])                # sells weakest (A), keeps B, adds C
    assert np.isclose(r[3], -C)                              # initial buy, turnover 1
    assert np.isclose(r[4], 0.5 * (-0.05))                   # A -5%, B 0%
    gA, gB = 0.5 * 0.95, 0.5 * 1.0
    tot = gA + gB
    assert np.isclose(r[4] + 1, tot)
    dA, dB = gA / tot, gB / tot                              # drifted weights at close 4
    g5A, g5B = dA * 1.0, dB * 1.1                            # session 5: A 0%, B +10%
    tot5 = g5A + g5B
    turnover = abs(0 - g5A / tot5) + abs(0.5 - g5B / tot5) + abs(0.5 - 0)
    assert np.isclose(turnover, 1.0)
    assert np.isclose(r[5], tot5 * (1 - C * turnover) - 1)
    assert np.allclose(r[6:], 0.0)                           # B 0%, C 0% afterwards


# ---------------------------------------------------------------- hand-computed toy: keep (留強)
def test_toy_keep_hand_computed():
    P = toy_keep()
    W, r, wt = run_toy(P, [2, 4], "keep")
    eq = np.cumprod(1 + r)
    assert np.isclose(eq[-1], (1 - C) * 1.0 * 1.1 * (1 - 2 * C))


# ---------------------------------------------------------------- hand-computed toy: stay (續抱)
def test_toy_stay_final_equity():
    P = toy_stay()
    _, r, _ = run_toy(P, [2, 4, 6], "stay")
    expected = (1 - C) * (115.5 / 110) * 1.0 * (92.4 / 115.5) * (1 - 2 * C)
    assert np.isclose(np.prod(1 + r), expected)


# ---------------------------------------------------------------- tranche blend, random control, misc
def test_tranche_blend_is_equal_average_and_checks_are_21_apart():
    rng = np.random.default_rng(5)
    P = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, (900, 3)), axis=0)
    res = E.run_tranches(P, 272, 63, 126, 0, "keep")
    assert res["tranche_rets"].shape[0] == 3
    assert np.allclose(res["blend"], res["tranche_rets"].mean(0))
    firsts = [t[0] for t in res["trade_idx"]]
    assert firsts == [273, 294, 315]
    res6 = E.run_tranches(P, 272, 126, 126, 0, "keep")
    assert res6["tranche_rets"].shape[0] == 6


def test_random_stay_has_exact_number_of_switches():
    rng = np.random.default_rng(7)
    W = E.random_targets(rng, 20, 12, 3, "stay", 4)
    for d in range(20):
        ch = sum(not np.allclose(W[d, j], W[d, j - 1]) for j in range(1, 12))
        assert ch == 4


def test_bh_adjust():
    q = E.bh_adjust([0.01, 0.04, 0.03, 0.5])
    assert np.allclose(q, [0.04, 0.0533333333, 0.0533333333, 0.5])


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:     # noqa: BLE001
                fails += 1
                print("FAIL", name, repr(e))
    print("failures:", fails)
    sys.exit(1 if fails else 0)
