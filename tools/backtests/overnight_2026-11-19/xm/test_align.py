"""XM 對齊與模擬的單元測試。跑法：python -B test_align.py（不需要 pytest）。

重點：台股日期晚於美股交易日 D 的資料必須碰不到；兩邊各自放假的情況都要對。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import align  # noqa: E402
import common as C  # noqa: E402

D = pd.Timestamp


def test_prev_us_is_strictly_before():
    us = pd.DatetimeIndex(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])
    tw = pd.DatetimeIndex(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-08"])
    j = align.prev_us_index(tw, us)
    assert j[0] == -1                      # 沒有更早的美股日
    assert us[j[1]] == D("2020-01-02")     # 同日的美股（01-03）還沒開盤，不能用
    assert us[j[2]] == D("2020-01-03")     # 週一用週五
    assert us[j[3]] == D("2020-01-07")
    assert all(us[j[i]] < tw[i] for i in range(1, 4))


def test_latest_tw_never_after_us_day():
    tw = pd.DatetimeIndex(["2020-01-02", "2020-01-03", "2020-01-08"])
    us = pd.DatetimeIndex(["2020-01-01", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"])
    i = align.latest_tw_index(us, tw)
    assert i[0] == -1                      # 台股還沒有資料
    assert tw[i[1]] == D("2020-01-03")     # 同日可用（台股先收盤）
    assert tw[i[2]] == D("2020-01-03") and tw[i[3]] == D("2020-01-03")  # 台股休市 → 最近一個
    assert tw[i[4]] == D("2020-01-08")
    assert all(tw[i[k]] <= us[k] for k in range(1, 5))


def test_map_to_us_holidays_both_sides():
    # 台股 01-06、01-07 休市（美股有開）；美股 01-09 休市（台股有開）
    tw = pd.DatetimeIndex(["2020-01-02", "2020-01-03", "2020-01-08", "2020-01-09", "2020-01-10"])
    z_tw = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5], index=tw)
    us = pd.DatetimeIndex(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08", "2020-01-10"])
    m = align.map_to_us(z_tw, us)
    # 主分析：台股休市的美股日沒有值
    assert np.isnan(m.loc["2020-01-06", "z_same"]) and np.isnan(m.loc["2020-01-07", "z_same"])
    assert m.loc["2020-01-03", "z_same"] == 0.2 and m.loc["2020-01-08", "z_same"] == 0.3
    # 另報版本：用最近一個台股交易日，並標過期天數
    assert m.loc["2020-01-06", "z_stale"] == 0.2 and m.loc["2020-01-06", "stale_days"] == 3
    assert m.loc["2020-01-07", "z_stale"] == 0.2 and m.loc["2020-01-07", "stale_days"] == 4
    # 美股休市那天的台股資料（01-09 的 0.4）永遠不會被任何美股日用到
    assert 0.4 not in set(m["z_same"].dropna()) and 0.4 not in set(m["z_stale"].dropna())
    assert m.loc["2020-01-10", "z_same"] == 0.5 and m.loc["2020-01-10", "stale_days"] == 0
    # 沒有任何一列用到未來的台股日期
    assert (m["tw_date_used"] <= m.index).all()


def test_future_taiwan_row_unreachable():
    # 只有「未來」的台股資料時，美股日一律拿不到值
    z_tw = pd.Series([9.0], index=pd.DatetimeIndex(["2020-01-03"]))
    m = align.map_to_us(z_tw, pd.DatetimeIndex(["2020-01-02"]))
    assert np.isnan(m["z_same"].iloc[0]) and np.isnan(m["z_stale"].iloc[0])


def _synthetic(seed=0, n=1400):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2010-01-01", periods=n)
    us = days[rng.random(n) > 0.04]
    tw = days[rng.random(n) > 0.06]
    us_cc = pd.Series(rng.normal(0, 0.01, len(us)), index=us)
    tw_ret = pd.Series(rng.normal(0, 0.012, len(tw)), index=tw)
    return tw_ret, us_cc, us


def test_poison_future_does_not_change_past_z():
    """把 D 之後的台股資料、D 當天起的美股資料全部改掉，D 當天與之前的 z 不得改變。"""
    tw_ret, us_cc, us = _synthetic()
    base = align.map_to_us(align.build_surprise(tw_ret, us_cc)["z"], us)
    rng = np.random.default_rng(1)
    checked = 0
    for pos in rng.choice(np.arange(700, len(us) - 5), size=25, replace=False):
        d = us[pos]
        tw2 = tw_ret.copy()
        tw2[tw2.index > d] += 5.0           # 台股：日期晚於 D 的全部污染
        us2 = us_cc.copy()
        us2[us2.index >= d] -= 5.0          # 美股：D 當天（含）之後的收盤報酬全部污染
        alt = align.map_to_us(align.build_surprise(tw2, us2)["z"], us)
        for col in ("z_same", "z_stale"):
            a, b = base.loc[:d, col].to_numpy(), alt.loc[:d, col].to_numpy()
            assert np.array_equal(np.isnan(a), np.isnan(b))
            assert np.allclose(a[~np.isnan(a)], b[~np.isnan(b)], rtol=0, atol=1e-12), (d, col)
        checked += int(base.loc[:d, "z_same"].notna().sum() > 0)
    assert checked == 25


def test_poison_is_detected_when_rule_is_broken():
    """反向驗證：污染 D 當天的台股資料，z 必須改變（確認上面的測試不是空測）。"""
    tw_ret, us_cc, us = _synthetic()
    base = align.map_to_us(align.build_surprise(tw_ret, us_cc)["z"], us)
    d = base["z_same"].dropna().index[-10]
    tw2 = tw_ret.copy()
    tw2[d] += 0.05
    alt = align.map_to_us(align.build_surprise(tw2, us_cc)["z"], us)
    assert abs(alt.loc[d, "z_same"] - base.loc[d, "z_same"]) > 1.0


def test_beta_and_z_use_only_prior_window():
    tw_ret, us_cc, _ = _synthetic(seed=3)
    s = align.build_surprise(tw_ret, us_cc)
    v = s.dropna(subset=["r_tw", "r_us_prev"])
    assert v["beta"].notna().idxmax() == v.index[align.WIN]          # 前 252 筆之後才有 β
    assert v["z"].notna().idxmax() == v.index[2 * align.WIN]         # 再 252 筆之後才有 z
    k = 2 * align.WIN + 37
    w = v.iloc[k - align.WIN:k]
    beta = np.cov(w["r_tw"], w["r_us_prev"], ddof=1)[0, 1] / np.var(w["r_us_prev"], ddof=1)
    assert np.isclose(v["beta"].iloc[k], beta)
    sw = v["surprise"].iloc[k - align.WIN:k]
    z = (v["surprise"].iloc[k] - sw.mean()) / sw.std(ddof=1)
    assert np.isclose(v["z"].iloc[k], z)
    assert (s["us_prev_date"].dropna() < s.index[s["us_prev_date"].notna()]).all()


def test_us_targets():
    idx = pd.bdate_range("2020-01-01", periods=8)
    ao = pd.Series([10, 11, 12, 13, 14, 15, 16, 17.0], index=idx)
    ac = pd.Series([10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5], index=idx)
    t = align.us_targets(ao, ac)
    assert np.isclose(t["gap"].iloc[1], 11 / 10.5 - 1) and np.isnan(t["gap"].iloc[0])
    assert np.isclose(t["oc"].iloc[2], 12.5 / 12 - 1)
    assert np.isclose(t["oo1"].iloc[2], 13 / 12 - 1) and np.isnan(t["oo1"].iloc[-1])
    assert np.isclose(t["oo5"].iloc[2], 17 / 12 - 1) and t["oo5"].iloc[3:].isna().all()


def test_circular_shifts():
    rng = np.random.default_rng(0)
    k = align.circular_shifts(3000, 1000, 21, rng)
    assert len(k) == 1000 and k.min() >= 21 and k.max() <= 3000 - 21 and len(set(k)) == 1000
    assert len(align.circular_shifts(30, 10, 21, rng)) == 0


def test_intraday_rule():
    oc = np.array([0.01, -0.02, 0.03])
    cash = np.array([0.001, 0.001, 0.001])
    sig = np.array([[True, False, True]])
    lt = C.intraday_logtotal(sig, oc, cash, 0.0)[0]
    assert np.isclose(np.exp(lt), 1.01 * 1.001 * 1.03)
    lt2 = C.intraday_logtotal(sig, oc, cash, 0.0002)[0]
    assert np.isclose(np.exp(lt2), 1.01 * 1.03 * 1.001 * ((1 - 0.0002) / (1 + 0.0002)) ** 2)


def test_tranche_rule():
    n = 21
    oo1 = np.full(n, 0.01)
    cash = np.zeros(n)
    sig = np.zeros((1, n), bool)
    sig[0, 3] = True                        # 第 3 天有訊號 → 那一批抱 5 個區間
    lt = C.tranche_logtotal(sig, oo1, cash, 0.0, H=5)[0]
    assert np.isclose(np.exp(lt), (4 + 1.01 ** 5) / 5)
    lt_c = C.tranche_logtotal(sig, oo1, cash, 0.001, H=5)[0]
    assert np.isclose(np.exp(lt_c), (4 + 1.01 ** 5 * 0.999 ** 2) / 5)
    # 起點有訊號：五批全部進場，第 k 批在第 k 天開盤重新決定（k=0 的那批抱滿 5 天）
    sig0 = np.zeros((1, n), bool)
    sig0[0, 0] = True
    lt0 = C.tranche_logtotal(sig0, oo1, cash, 0.0, H=5)[0]
    assert np.isclose(np.exp(lt0), (1.01 ** 5 + 1.01 + 1.01 ** 2 + 1.01 ** 3 + 1.01 ** 4) / 5)
    # 每天都有訊號 = 一直滿倉，只付進場與最後出場的成本
    sig1 = np.ones((1, n), bool)
    lt1 = C.tranche_logtotal(sig1, oo1, cash, 0.001, H=5)[0]
    assert np.isclose(np.exp(lt1), 1.01 ** 20 * 0.999 ** 2)
    # 每一天恰好屬於一批的決定日
    decs = [set(C.tranche_decision_index(20, 5, k)) for k in range(5)]
    for d in range(1, 20):
        assert sum(d in s for s in decs) == 1


def test_nw_and_bh():
    rng = np.random.default_rng(0)
    x = rng.normal(size=4000)
    y = 0.5 * x + rng.normal(size=4000)
    r = C.nw_ols(y, np.column_stack([np.ones(4000), x]), C.nw_lag(4000))
    assert abs(r["coef"][1] - 0.5) < 0.05 and r["t"][1] > 20
    q = C.bh_qvalues(np.array([0.001, 0.01, 0.02, 0.8, np.nan]))
    assert np.allclose(q[:4], [0.004, 0.02, 0.02 * 4 / 3, 0.8]) and np.isnan(q[4])


def test_real_data_end_date_and_alignment():
    """整合測試：真資料讀進來不得晚於 2025-12-31；主分析每一列的台股日期都等於美股日期。"""
    if not C.TW_PANEL.exists():
        print("  (skip: data not present)")
        return
    tw = C.load_tw()
    us = C.load_us()
    assert all(v.index.max() <= C.END for v in tw.values())
    assert all(v.index.max() <= C.END for v in us.values())
    s = align.build_surprise(tw["0050"]["cc"], us["SPY"]["cc"])
    m = align.map_to_us(s["z"], us["SPY"].index)
    ok = m["z_same"].notna()
    assert (m.loc[ok, "tw_date_used"] == m.index[ok]).all()
    assert (m["tw_date_used"].dropna() <= m.index[m["tw_date_used"].notna()]).all()
    assert (s["us_prev_date"].dropna() < s.index[s["us_prev_date"].notna()]).all()
    # 台股休市的美股日：主分析沒有值
    tw_cal = tw["TAIEX_TR"].index
    assert m.loc[~m.index.isin(tw_cal), "z_same"].isna().all()


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
