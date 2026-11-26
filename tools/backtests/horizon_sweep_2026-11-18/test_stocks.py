"""US-D／US-E 引擎的單元測試（全部用極小的合成資料，不碰帳本）。

用法：python3 -B test_stocks.py      （也相容 pytest）

涵蓋：
 (1) 可手算的 2 檔案例（含成本、含漂移後再平衡的換手）
 (2) 偷看金絲雀：訊號 = 「下一日報酬」，以 lag 0 餵進管線不得有異常獲利；
     只有刻意再往前移一天（訊號 = 實際持有那天的報酬）才會暴利 → 證明成交在 t+1 收盤
 (3) H=1 的分批 = 不分批的組合；分批數與錯開規則；組合淨值 = 各批淨值平均
 (4) 已知淨值曲線上的績效指標
 另：資格、訊號、BH、同名單等權、未來價格擾動不影響過去、回測終點、
     US-E 的前瞻報酬／分群 bootstrap／FIFO 分桶。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stk_common as C  # noqa: E402
import own_buys as U  # noqa: E402


def _close(a, b, tol=1e-12):
    return np.allclose(a, b, rtol=0, atol=tol, equal_nan=True)


def _explicit_cell(P, S, direction, H, n_pick, t0=0, offsets=None):
    E = np.ones_like(P, dtype=bool)
    return C.run_signal_cell(P, S, E, direction, H, n_pick, t0, offsets)


# ── (1) hand-computable 2-asset cases incl. costs ─────────────────────────
def test_hand_two_asset_switching_with_cost():
    P = np.array([[100.0, 100.0], [110.0, 100.0], [121.0, 90.0],
                  [121.0, 99.0], [133.1, 99.0], [133.1, 108.9]])
    S = np.array([[1, 0], [0, 1], [0, 1], [1, 0], [1, 0], [0, 0]], dtype=float)
    g, tau, _ = _explicit_cell(P, S, "momentum", H=1, n_pick=1)
    # 訊號日 0 選 A -> 第 1 日收盤買進 -> 第 2 日賺 A 的 +10%
    # 訊號日 1 選 B -> 第 2 日收盤換股 -> 第 3 日賺 B 的 +10%
    assert _close(g[:, 0, 0], [0, 0, 0.10, 0.10, 0, 0])
    assert _close(tau[:, 0, 0], [0, 1, 2, 0, 2, 0])
    ret0, to0 = C.combine(g, tau, 0)
    assert _close(np.prod(1 + ret0[:, 0]), 1.21)
    assert _close(to0[:, 0], [0, 0.5, 1, 0, 1, 0])
    ret, _ = C.combine(g, tau, 10)          # 每邊 10bp
    assert _close(ret[:, 0], [0, -0.001, 1.1 * 0.998 - 1, 0.10, -0.002, 0])
    # 手算：0.999 x (1.1 x 0.998) x 1.1 x 0.998 = 1.20395967516
    assert abs(np.prod(1 + ret[:, 0]) - 1.20395967516) < 1e-10
    # 反轉 = 選訊號最小者 -> 持股對調
    g2, _, _ = _explicit_cell(P, S, "reversal", H=1, n_pick=1)
    assert _close(g2[:, 0, 0], [0, 0, -0.10, 0.0, 0.10, 0.10])


def test_hand_two_asset_drift_rebalance_turnover():
    P = np.array([[10.0, 10.0], [10.0, 10.0], [12.0, 10.0],
                  [12.0, 10.0], [12.0, 10.0], [12.0, 10.0]])
    S = np.zeros_like(P)
    g, tau, _ = _explicit_cell(P, S, "momentum", H=2, n_pick=2, offsets=[0])
    assert _close(g[:, 0, 0], [0, 0, 0.10, 0, 0, 0])
    # 第 3 日再平衡：權重漂到 12/22、10/22 -> 拉回 0.5/0.5，sum|dw| = 2 x (12/22 - 0.5) = 1/11
    assert _close(tau[:, 0, 0], [0, 1, 0, 1 / 11, 0, 0])
    ret, to = C.combine(g, tau, 20)
    assert _close(to[:, 0], [0, 0.5, 0, 1 / 22, 0, 0])
    # 手算：0.998 x 1.1 x (1 - 0.002/11) = 1.0976004
    assert abs(np.prod(1 + ret[:, 0]) - 1.0976004) < 1e-10


# ── (2) look-ahead canary ─────────────────────────────────────────────────
def _canary_setup(seed=7, T=1500, N=30):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0, 0.02, size=(T, N))
    r[0] = 0.0
    P = 100.0 * np.cumprod(1.0 + r, axis=0)
    return P, r


def test_lookahead_canary_execution_is_t_plus_1():
    P, r = _canary_setup()
    T, N = P.shape
    E = np.ones((T, N), dtype=bool)
    ew = r.mean(axis=1)

    def run(S):
        g, tau, _ = C.run_signal_cell(P, S, E, "momentum", 1, 10, 0)
        ret, _ = C.combine(g, tau, 0)
        return ret[:, 0]

    # 金絲雀：S[t] = 第 t+1 日的報酬（t 收盤時還不知道）。lag 0 直接餵。
    S_next = np.full((T, N), np.nan)
    S_next[:-1] = r[1:]
    ret = run(S_next)
    active = (ret - ew)[2:-1]
    se = active.std(ddof=1) / np.sqrt(len(active))
    # 管線在 t+1 收盤才成交，賺到的是 t+2 的報酬 -> 偷看到的 t+1 報酬用不上
    assert abs(active.mean()) < 4 * se, (active.mean(), se)
    assert abs(active.mean()) < 0.001

    # 刻意再往前移一天：S[t] = 第 t+2 日的報酬（正好是持有的那一天）-> 暴利
    S_hold = np.full((T, N), np.nan)
    S_hold[:-2] = r[2:]
    ret2 = run(S_hold)
    active2 = (ret2 - ew)[2:-1]
    assert active2.mean() > 0.015, active2.mean()        # 理論值約 1.07 sigma = 2.1%/日
    assert active2.mean() > 50 * abs(active.mean())

    # 逐日對帳：金絲雀組合第 u 日的報酬 = 以第 u-1 日報酬排名選出的前 10 名在第 u 日的平均
    for u in (5, 400, 1200):
        top = np.argsort(-r[u - 1], kind="stable")[:10]
        assert abs(ret[u] - r[u, top].mean()) < 1e-12


def test_future_prices_do_not_change_the_past():
    P, _ = _canary_setup(seed=11, T=400, N=12)
    E = C.eligibility(P, min_prior=20)
    cut = 250
    P2 = P.copy()
    P2[cut + 1:] *= np.random.default_rng(3).uniform(0.5, 2.0, size=P2[cut + 1:].shape)
    for L, skip in ((1, 0), (21, 0), (63, 21)):
        S, S2 = C.signal_matrix(P, L, skip), C.signal_matrix(P2, L, skip)
        assert _close(S[:cut + 1], S2[:cut + 1])
        for H in (1, 5, 63):
            g, tau, t0 = C.run_signal_cell(P, S, E, "momentum", H, 3, 100)
            g2, tau2, _ = C.run_signal_cell(P2, S2, E, "momentum", H, 3, 100)
            ret, _ = C.combine(g, tau, 10)
            ret2, _ = C.combine(g2, tau2, 10)
            assert _close(ret[:cut + 1], ret2[:cut + 1]), (L, H)
    assert _close(C.roster_ew_returns(P, E)[:cut + 1], C.roster_ew_returns(P2, E)[:cut + 1])


def test_null_selection_uses_only_eligibility_at_signal_day():
    P, _ = _canary_setup(seed=5, T=120, N=8)
    E = np.ones_like(P, dtype=bool)
    E[:, 0] = False                               # 第 0 檔永遠不可選
    fn = C.random_select_fn(E, 3, 40, np.random.default_rng(1))
    g, tau = C.simulate(P, fn, 5, 10, 40)
    sel = fn(10, 0)
    assert sel.shape == (40, 3) and (sel != 0).all()
    assert all(len(set(row)) == 3 for row in sel)
    assert g.shape == (120, 5, 40) and (g[:12] == 0).all()   # t0=10 -> 第 11 日成交 -> 第 12 日起有報酬
    assert (tau[11] == 1).all()                               # 期初全部批次同時建倉


# ── (3) tranches ──────────────────────────────────────────────────────────
def test_tranche_h1_equals_untranched_portfolio():
    P, r = _canary_setup(seed=21, T=300, N=9)
    T, N = P.shape
    E = np.ones((T, N), dtype=bool)
    S = C.signal_matrix(P, 5)
    t0 = 5
    assert C.tranche_offsets(1) == [0]
    g, tau, _ = C.run_signal_cell(P, S, E, "momentum", 1, 3, t0)
    assert g.shape[1] == 1
    ret, to = C.combine(g, tau, 10)
    # 獨立的參考實作：每日再平衡、等權 3 檔、t 訊號 -> t+1 收盤成交 -> t+2 報酬
    V, w = 1.0, np.zeros(N)
    ref = np.zeros(T)
    for d in range(1, T):
        gross = float(w @ r[d])
        w_drift = w * (1 + r[d]) / (1 + gross) if w.sum() > 0 else w
        w_new = w_drift
        cost = 0.0
        s = d - 1
        if s >= t0:
            top = np.argsort(-S[s], kind="stable")[:3]
            w_new = np.zeros(N)
            w_new[top] = 1 / 3
            cost = 0.001 * np.abs(w_new - w_drift).sum()
        V_new = V * (1 + gross) * (1 - cost)
        ref[d] = V_new / V - 1
        V, w = V_new, w_new
    assert _close(ret[:, 0], ref, 1e-12)


def test_tranche_rules_and_averaging():
    for H in C.HORIZONS_D:
        offs = C.tranche_offsets(H)
        assert len(offs) == min(H, 21) and offs[0] == 0
        assert len(set(offs)) == len(offs) and max(offs) < H
    assert C.tranche_offsets(5) == [0, 1, 2, 3, 4]
    assert C.tranche_offsets(63)[:3] == [0, 3, 6]
    P, _ = _canary_setup(seed=33, T=200, N=8)
    E = np.ones_like(P, dtype=bool)
    S = C.signal_matrix(P, 5)
    # 所有批次同一個起始位移 -> 與單一批次完全相同
    g1, tau1, _ = C.run_signal_cell(P, S, E, "momentum", 5, 3, 10, offsets=[0])
    g5, tau5, _ = C.run_signal_cell(P, S, E, "momentum", 5, 3, 10, offsets=[0] * 5)
    assert _close(C.combine(g1, tau1, 10)[0], C.combine(g5, tau5, 10)[0])
    # 錯開的批次：組合淨值 = 各批（單獨模擬）淨值的平均；期初全部批次同日建倉
    g, tau, _ = C.run_signal_cell(P, S, E, "momentum", 5, 3, 10)
    assert g.shape[1] == 5 and (tau[11, :, 0] == 1).all()
    ret, _ = C.combine(g, tau, 10)
    navs = []
    for off in C.tranche_offsets(5):
        gk, tk, _ = C.run_signal_cell(P, S, E, "momentum", 5, 3, 10, offsets=[off])
        navs.append(np.cumprod(1 + C.combine(gk, tk, 10)[0][:, 0]))
    assert _close(np.cumprod(1 + ret[:, 0]), np.mean(navs, axis=0), 1e-12)
    # 第 k 批在 t0+k 之後每 5 日換一次：成交日 = t0+1（期初）與 t0+k+1, t0+k+6, ...
    for k in range(5):
        days = set(range(10 + k + 1, 200, 5)) | {11}
        traded = set(np.nonzero(tau[:, k, 0] > 0)[0])
        assert traded <= days


def test_share_based_reference_matches_engine():
    """用「持股股數」寫的獨立參考實作（另一套算法）對帳：H>1、多批、含成本。"""
    P, _ = _canary_setup(seed=44, T=260, N=10)
    T, N = P.shape
    E = np.ones((T, N), dtype=bool)
    S = C.signal_matrix(P, 21)
    t0, n_pick = 21, 3
    for H, bps in ((5, 10), (63, 20), (10, 0)):
        for direction in C.DIRECTIONS:
            picks = C.rank_picks(S, E, direction, n_pick)
            g, tau, _ = C.run_signal_cell(P, S, E, direction, H, n_pick, t0)
            ret, to = C.combine(g, tau, bps)
            c = bps / 1e4
            navs, traded_tot, nav_pre_tot = [], np.zeros(T), np.zeros(T)
            for off in C.tranche_offsets(H):
                sig = set([t0] + list(range(t0 + off, T - 1, H)))
                shares, cash, nav = np.zeros(N), 1.0, np.ones(T)
                for d in range(T):
                    v = cash + float(shares @ P[d])
                    nav_pre_tot[d] += v
                    if d - 1 in sig:
                        tgt = np.zeros(N)
                        tgt[picks[d - 1]] = 1.0 / n_pick
                        traded = float(np.abs(tgt * v - shares * P[d]).sum())
                        traded_tot[d] += traded
                        v -= c * traded
                        shares, cash = tgt * v / P[d], 0.0
                    nav[d] = v
                navs.append(nav)
            V = np.mean(navs, axis=0)
            assert _close(np.cumprod(1 + ret[:, 0]), V, 1e-10), (H, bps, direction)
            assert _close(to[:, 0], traded_tot / nav_pre_tot / 2.0, 1e-10), (H, bps, direction)


# ── (4) metrics on a known curve ──────────────────────────────────────────
def test_metrics_known_curve():
    ret = np.array([0.10, -0.50, 1.00, 1.00, 0.0, 0.0])      # V: 1, 1.1, .55, 1.1, 2.2, 2.2, 2.2
    m = C.metrics_from_returns(ret, None, "2020-01-01", "2022-01-01")   # 731 個日曆天
    assert abs(m["cagr"] - (2.2 ** (365.25 / 731) - 1)) < 1e-12
    assert abs(m["mdd"] - (-0.5)) < 1e-12
    assert abs(m["calmar"] - m["cagr"] / 0.5) < 1e-12
    assert m["n_days"] == 6 and np.isnan(m["sharpe_ex"])
    r4 = np.array([0.02, -0.01, 0.02, -0.01])
    m = C.metrics_from_returns(r4, np.full(4, 0.001), "2021-01-04", "2021-01-08")
    # 平均 0.005；樣本標準差 = sqrt(4 x 0.015^2 / 3) = 0.0173205
    assert abs(m["sharpe"] - 0.005 / np.sqrt(0.0003) * np.sqrt(252)) < 1e-9
    assert abs(m["sharpe"] - 4.5826) < 1e-3
    assert abs(m["sharpe_ex"] - 0.004 / np.sqrt(0.0003) * np.sqrt(252)) < 1e-9
    assert abs(m["mdd"] - (-0.01)) < 1e-12


def test_window_metrics_slices_one_continuous_simulation():
    dates = pd.bdate_range("2019-12-27", periods=8)          # 12/27,30,31, 1/1,2,3,6,7
    ret = np.array([0.5, 0.5, 0.5, 0.5, 0.5, 0.10, -0.20, 0.25])
    m = C.window_metrics(dates, ret, None, "2020-01-02", "2020-01-07")
    # 窗內第一個交易日 2020-01-02 的收盤是 V=1；它當天的報酬（0.5）不算在窗內
    assert m["n_days"] == 3
    v_end = 1.10 * 0.80 * 1.25
    assert abs(m["cagr"] - (v_end ** (365.25 / 5) - 1)) < 1e-9
    assert abs(m["mdd"] - (-0.20)) < 1e-12
    assert abs(C.info_ratio(ret, ret * 0)) > 0 and np.isnan(C.info_ratio(ret, ret))


# ── signals / eligibility / BH / roster EW ────────────────────────────────
def test_eligibility_and_signals():
    P = np.array([[np.nan, 1.0], [np.nan, 2.0], [np.nan, 4.0], [5.0, 8.0],
                  [6.0, 16.0], [9.0, 32.0], [18.0, 64.0]])
    E = C.eligibility(P, min_prior=2)
    assert E[:, 1].tolist() == [False, False, True, True, True, True, True]
    assert E[:, 0].tolist() == [False, False, False, False, False, True, True]   # 需 2 個「之前」的收盤
    S = C.signal_matrix(P, 2)
    assert np.isnan(S[:2]).all() and _close(S[2:, 1], [3, 3, 3, 3, 3])
    assert abs(S[5, 0] - (9 / 5 - 1)) < 1e-12
    S = C.signal_matrix(P, 3, skip=1)                 # P[t-1] / P[t-3] - 1
    assert _close(S[3:, 1], [3, 3, 3, 3]) and abs(S[6, 0] - (9 / 5 - 1)) < 1e-12
    picks = C.rank_picks(C.signal_matrix(P, 2), E, "momentum", 1)
    assert picks[1] is None and picks[2].tolist() == [1] and picks[6].tolist() == [1]
    assert C.rank_picks(C.signal_matrix(P, 2), E, "reversal", 1)[6].tolist() == [0]
    assert C.rank_picks(C.signal_matrix(P, 2), E, "momentum", 2)[4] is None     # 可選數不足


def test_bh_qvalues():
    assert _close(C.bh_qvalues([0.01, 0.02, 0.03, 0.04, 0.05]), [0.05] * 5)
    assert _close(C.bh_qvalues([0.9, 0.001, 0.5]), [0.9, 0.003, 0.75])
    q = C.bh_qvalues(np.full(98, 1 / 201))            # 200 次 null 的最小 p，98 格全中
    assert _close(q, 1 / 201)


def test_roster_ew_timing():
    P, r = _canary_setup(seed=9, T=60, N=6)
    P[:10, 0] = np.nan
    E = C.eligibility(P, min_prior=5)
    ew = C.roster_ew_returns(P, E)
    assert ew[:7].tolist() == [0.0] * 7               # 第 5 日才有資格 -> 第 6 日成交 -> 第 7 日起有報酬
    for u in (7, 16, 17, 40):
        assert abs(ew[u] - r[u, E[u - 2]].mean()) < 1e-12
    assert not E[14, 0] and E[15, 0]                  # 第 0 檔第 10 日才有價；之前滿 5 個收盤（10..14）-> 第 15 日可選


def test_backtest_end_date_is_enforced():
    for w, (a, z) in C.WINDOWS_D.items():
        assert pd.Timestamp(z) <= C.END_DATE, w
    assert C.WINDOWS_D[C.W1] == ("2014-01-02", "2019-12-31")
    assert C.WINDOWS_D[C.W2] == ("2020-01-02", "2025-12-31")
    assert C.WINDOWS_D[C.WFULL] == ("2014-01-02", "2025-12-31")
    assert C.COSTS_D == [0, 10, 20] and C.HORIZONS_D == [1, 5, 10, 21, 63, 126, 252]
    assert len(C.SIGNALS) * len(C.DIRECTIONS) * len(C.HORIZONS_D) == 98
    for loader in (C.load_roster, C.load_idx, C.load_stk_pkl, C.load_lev):
        df = loader()
        assert df.index.max() <= C.END_DATE, loader.__name__
        assert loader(allow_2026=True).index.max() > C.END_DATE      # 例外只給 US-E 用


# ── US-E helpers ──────────────────────────────────────────────────────────
def test_forward_returns_and_drop_reasons():
    cal = pd.bdate_range("2024-01-01", periods=12)
    a = np.array([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21], dtype=float)
    b = a.copy()
    b[8:] = np.nan                                    # 這條來源比較短
    bench = {"SPY": np.full(12, 100.0) * (1.01 ** np.arange(12)),
             "QQQ": np.full(12, 50.0), "SMH": np.full(12, 20.0)}
    buys = pd.DataFrame({"date": [cal[0], cal[5], cal[0]], "symbol": ["AAA", "AAA", "ZZZ"],
                         "notional": [100.0, 300.0, 50.0], "fill_px_split_adj": [10.0, 15.0, 1.0],
                         "origin": ["user", "system", "unknown"]})
    buys["month"] = buys.date.dt.strftime("%Y-%m")
    buys["year"] = buys.date.dt.year.astype(str)
    book = {"AAA": [("short", b), ("long", a)], "ZZZ": []}
    ft = U.forward_table(buys, cal, book, bench, [5, 10])
    r = ft.set_index(["fill", "H"])
    assert abs(r.loc[(0, 5), "ret"] - 0.5) < 1e-12 and r.loc[(0, 5), "source"] == "short"
    assert abs(r.loc[(0, 5), "alt_ret"] - 0.5) < 1e-12
    assert abs(r.loc[(0, 5), "ex_SPY"] - (0.5 - (1.01 ** 5 - 1))) < 1e-12
    assert abs(r.loc[(0, 5), "ex_QQQ"] - 0.5) < 1e-12
    # 第 0 筆的 H=10：短來源蓋不到出場日 -> 整筆改用長來源（不拼接）
    assert r.loc[(0, 10), "source"] == "long" and abs(r.loc[(0, 10), "ret"] - 1.0) < 1e-12
    assert r.loc[(1, 5), "source"] == "long" and abs(r.loc[(1, 5), "ret"] - 20 / 15 + 1) < 1e-12
    assert r.loc[(1, 10), "status"] == "horizon_past_data_end" and np.isnan(r.loc[(1, 10), "ret"])
    assert r.loc[(2, 5), "status"] == "no_series_cover"
    rows = pd.DataFrame(U.summarise(ft, "all", "all", pd.Series(True, index=ft.index)))
    s = rows[(rows.H == 5) & (rows.benchmark == "QQQ")].iloc[0]
    assert s.n_fills == 2 and s.n_dropped == 1 and s.n_symbols == 1
    assert abs(s.excess_mean_ew - (0.5 + 1 / 3) / 2) < 1e-12
    assert abs(s.excess_mean_nw - (100 * 0.5 + 300 / 3) / 400) < 1e-12
    assert s.hit_rate == 1.0 and abs(s.excess_per_day_bp_ew - s.excess_mean_ew / 5 * 1e4) < 1e-9
    assert abs(s.raw_ann_ew - ((1 + s.raw_mean_ew) ** (252 / 5) - 1)) < 1e-9
    assert U.fwd_return(a, 11, 1) != U.fwd_return(a, 11, 1)          # NaN：超出範圍


def test_cluster_bootstrap():
    x = np.array([0.10, 0.10, 0.10, -0.20, -0.20, 0.05])
    w = np.array([1.0, 1.0, 1.0, 3.0, 3.0, 2.0])
    cl = np.array(["a", "a", "a", "b", "b", "c"])
    ci = U.cluster_boot_ci(x, w, cl)
    assert ci == U.cluster_boot_ci(x, w, cl)                         # 固定種子 -> 可重現
    assert ci["n_clusters"] == 3
    # 整群抽樣：等權平均只可能落在群平均的組合範圍內
    assert -0.20 - 1e-12 <= ci["ew_lo"] <= x.mean() <= ci["ew_hi"] <= 0.10 + 1e-12
    assert ci["nw_lo"] <= np.average(x, weights=w) <= ci["nw_hi"]
    # 群內完全相同、群間不同 -> 區間寬度由群數決定，不因群內筆數變多而縮小
    ci_big = U.cluster_boot_ci(np.repeat(x, 50), np.repeat(w, 50), np.repeat(cl, 50))
    assert abs(ci_big["ew_lo"] - ci["ew_lo"]) < 1e-12 and abs(ci_big["ew_hi"] - ci["ew_hi"]) < 1e-12
    assert np.isnan(U.cluster_boot_ci(x[:3], w[:3], cl[:3])["ew_lo"])   # 只有一群 -> 無區間


def test_fifo_buckets_with_split():
    def split_qty(sym, d, q):                        # 合成：XX 在 2024-03-01 一拆二
        return q * 2 if (sym == "XX" and d < "2024-03-01") else q
    fills = [
        {"date": "2024-01-02", "symbol": "XX", "side": "BOUGHT", "qty": 10, "amount": -1000.0},
        {"date": "2024-01-05", "symbol": "XX", "side": "SOLD", "qty": 5, "amount": 600.0},     # 3 天
        {"date": "2024-02-20", "symbol": "XX", "side": "BOUGHT", "qty": 10, "amount": -1200.0},
        {"date": "2024-06-03", "symbol": "XX", "side": "SOLD", "qty": 30, "amount": 2400.0},   # 拆股後
        {"date": "2024-06-03", "symbol": "YY", "side": "SOLD", "qty": 1, "amount": 50.0},      # 無庫存
        {"date": "2024-06-04", "symbol": "XX", "side": "BOUGHT", "qty": 1, "amount": -70.0,
         "is_option": True},
        {"date": "2025-07-01", "symbol": "XX", "side": "SOLD", "qty": 10, "amount": 100.0},
    ]
    pieces, info = U.fifo_pieces(fills, split_qty)
    # 第 1 賣：拆股調整後 10 股，成本 50/股 -> 損益 600 - 500 = +100，持有 3 天
    assert pieces.iloc[0].days == 3 and abs(pieces.iloc[0].pnl - 100.0) < 1e-9
    # 第 2 賣 30 股 @80：先配剩下的 10 股（成本 50，153 天）再配 20 股（成本 60，104 天）
    assert pieces.iloc[1].days == 153 and abs(pieces.iloc[1].pnl - (800 - 500)) < 1e-9
    assert pieces.iloc[2].days == 104 and abs(pieces.iloc[2].pnl - (1600 - 1200)) < 1e-9
    assert len(pieces) == 3 and info["n_unmatched_sells_skipped"] == 2
    bt = U.bucket_table(pieces).set_index("holding_bucket_calendar_days")
    assert bt.loc["<7d", "realised_pnl"] == 100.0 and bt.loc["91-364d", "realised_pnl"] == 700.0
    assert bt.loc["TOTAL", "realised_pnl"] == 800.0 and bt.loc["TOTAL", "cost_basis"] == 2200.0
    assert bt.note.str.startswith("ENDOGENOUS").all()
    assert [b[0] for b in U.BUCKETS] == ["<7d", "7-29d", "30-90d", "91-364d", ">=365d"]


def test_implied_split_factor():
    f = U.implied_split_factor
    assert f(100.0, 99.0) == (1.0, True) and f(100.0, 80.0) == (1.0, True)     # 除息調整，不是拆股
    assert f(900.0, 88.0) == (10.0, True)             # 之後一拆十（還原價再低一點是除息）
    assert f(400.0, 99.0) == (4.0, True) and f(220.0, 100.0) == (2.0, True)
    assert f(4.5, 40.0) == (0.1, True)                # 之後十併一
    assert f(100.0, 60.0) == (1.0, False)             # 1.67 倍：判不出來 -> 不調整
    assert f(100.0, float("nan")) == (1.0, False)
    cal = pd.bdate_range("2024-01-01", periods=5)
    book = {"XX": [("s", np.array([50.0, 50.0, 50.0, 50.0, 50.0]))]}
    fills = [{"date": "2024-01-02", "symbol": "XX", "side": "BOUGHT", "qty": 10, "price": 100.0},
             {"date": "2024-01-04", "symbol": "XX", "side": "SOLD", "qty": 20, "price": 51.0}]
    m, info = U.implied_split_map(fills, cal, book)
    assert m == {("XX", "2024-01-02"): 2.0, ("XX", "2024-01-04"): 1.0}
    assert info["n_symbols_with_implied_split"] == 1


def test_ledger_filters():
    fills = [{"date": "2024-01-02", "symbol": "AA", "side": "BOUGHT", "notional": 1.0,
              "split_adj_price": 1.0, "is_option": False, "origin": "user"},
             {"date": "2024-01-02", "symbol": "AA", "side": "BOUGHT", "notional": 1.0,
              "split_adj_price": 1.0, "is_option": True, "origin": "user"},
             {"date": "2024-01-03", "symbol": "AA", "side": "SOLD", "notional": 1.0,
              "split_adj_price": 1.0, "is_option": False, "origin": "user"},
             {"date": "2024-01-03", "symbol": "BB", "side": "BOUGHT", "notional": 2.0,
              "split_adj_price": 1.0, "is_option": False, "origin": float("nan")}]
    b = U.stock_buys(fills)
    assert len(b) == 2 and b.origin.tolist() == ["user", "unknown"] and b.month.tolist() == ["2024-01"] * 2
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "l.jsonl"
        p.write_text("\n".join(json.dumps(x) for x in [
            {"symbol": "A", "origin_evidence": "VOID: duplicate"},
            {"symbol": "B", "origin_evidence": "order 1"}, {"symbol": "C"}]), encoding="utf-8")
        assert [r["symbol"] for r in U.load_ledger(p)] == ["B", "C"]


def test_crosscheck_levels():
    idx = pd.bdate_range("2024-01-01", periods=10)
    a = pd.Series(np.arange(10, 20, dtype=float), index=idx)
    r = U.crosscheck_levels(a, a * 1.05)              # 只是還原基準不同
    assert abs(r["level_max_abs"] - 0.05) < 1e-12 and r["shape_max_abs"] < 1e-12
    b = a.copy()
    b.iloc[:3] *= 2                                   # 前段沒做拆股調整
    assert U.crosscheck_levels(a, b)["shape_max_abs"] > 0.9


def _all_tests():
    return [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]


if __name__ == "__main__":
    failed = 0
    for name, fn in _all_tests():
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as exc:                      # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"{len(_all_tests()) - failed}/{len(_all_tests())} passed")
    sys.exit(1 if failed else 0)
