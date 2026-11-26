"""XM 日期對齊（預註冊「第一組 XM」最容易出錯的地方）。純函式，不讀檔。

時間順序（同一個日曆日期 D）：
    台股 D 收盤（台北 13:30 = 美東 D 日 00:30/01:30） → 美股 D 開盤 → 美股 D 收盤 → 台股 D+1 開盤

所以：
  * 美股交易日 D 可用的台股資料：日期 <= D。主分析只用「日期 == D」。
  * 台股交易日 T 可用的美股資料：日期 <  T（嚴格小於；美股 T 日還沒開盤）。
  * 台股日期 > D 的資料，對美股 D 永遠不可見。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WIN = 252  # 預註冊：β 與 z 都用過去 252 個交易日


def _as_dates(x) -> np.ndarray:
    arr = pd.DatetimeIndex(x).values.astype("datetime64[D]")
    if len(arr) > 1 and not (arr[1:] > arr[:-1]).all():
        raise ValueError("dates must be strictly increasing")
    return arr


def prev_us_index(tw_dates, us_dates) -> np.ndarray:
    """對每個台股交易日 T，回傳「日期嚴格小於 T 的最後一個美股交易日」的位置；沒有則 -1。"""
    tw, us = _as_dates(tw_dates), _as_dates(us_dates)
    return np.searchsorted(us, tw, side="left") - 1


def latest_tw_index(us_dates, tw_dates) -> np.ndarray:
    """對每個美股交易日 D，回傳「日期 <= D 的最後一個台股交易日」的位置；沒有則 -1。"""
    tw, us = _as_dates(tw_dates), _as_dates(us_dates)
    return np.searchsorted(tw, us, side="right") - 1


def build_surprise(tw_ret: pd.Series, us_cc: pd.Series, win: int = WIN) -> pd.DataFrame:
    """台股意外與 z 分數，定義在台股交易日 T 上。

    r_us_prev = 美股標的在「T 之前最後一個美股交易日」的收盤對收盤報酬（即預註冊的 D−1）。
    beta_T    = 過去 win 個有效觀測（不含 T 本身）的 OLS 斜率。
    surprise  = r_tw − beta × r_us_prev。
    z         = (surprise − 過去 win 個意外的平均) ÷ 過去 win 個意外的標準差（不含 T 本身）。
    """
    tw_ret = tw_ret.sort_index()
    us_cc = us_cc.sort_index()
    j = prev_us_index(tw_ret.index, us_cc.index)
    ok = j >= 0
    us_vals = us_cc.to_numpy(dtype=float)
    us_idx = us_cc.index.values
    r_us_prev = np.full(len(tw_ret), np.nan)
    r_us_prev[ok] = us_vals[j[ok]]
    us_prev_date = np.full(len(tw_ret), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    us_prev_date[ok] = us_idx[j[ok]]
    df = pd.DataFrame(
        {"r_tw": tw_ret.to_numpy(dtype=float), "us_prev_date": us_prev_date, "r_us_prev": r_us_prev},
        index=tw_ret.index,
    )
    v = df.dropna(subset=["r_tw", "r_us_prev"])
    cov = v["r_tw"].rolling(win, min_periods=win).cov(v["r_us_prev"]).shift(1)
    var = v["r_us_prev"].rolling(win, min_periods=win).var().shift(1)
    beta = cov / var
    s = v["r_tw"] - beta * v["r_us_prev"]
    mu = s.rolling(win, min_periods=win).mean().shift(1)
    sd = s.rolling(win, min_periods=win).std().shift(1)
    z = (s - mu) / sd
    df["beta"] = beta.reindex(df.index)
    df["surprise"] = s.reindex(df.index)
    df["z"] = z.reindex(df.index)
    return df


def map_to_us(z_tw: pd.Series, us_dates) -> pd.DataFrame:
    """把定義在台股日期上的 z 對到美股交易日 D。

    z_same     : 只有「台股當天也有開盤」（日期 == D）才有值 —— 主分析。
    z_stale    : 用日期 <= D 的最近一個台股交易日 —— 另報版本。
    stale_days : D 減去所用台股日期的日曆天數（同日 = 0）。
    """
    z_tw = z_tw.sort_index()
    us = pd.DatetimeIndex(us_dates)
    i = latest_tw_index(us, z_tw.index)
    ok = i >= 0
    tw_idx = z_tw.index.values
    zv = z_tw.to_numpy(dtype=float)
    tw_used = np.full(len(us), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    tw_used[ok] = tw_idx[i[ok]]
    z_stale = np.full(len(us), np.nan)
    z_stale[ok] = zv[i[ok]]
    stale = np.full(len(us), np.nan)
    stale[ok] = (us.values[ok].astype("datetime64[D]") - tw_used[ok].astype("datetime64[D]")).astype(float)
    if (stale[ok] < 0).any():
        raise AssertionError("look-ahead: a Taiwan row dated after the US session was selected")
    z_same = np.where(stale == 0, z_stale, np.nan)
    return pd.DataFrame(
        {"z_same": z_same, "z_stale": z_stale, "stale_days": stale, "tw_date_used": tw_used}, index=us
    )


def us_targets(adj_open: pd.Series, adj_close: pd.Series) -> pd.DataFrame:
    """美股標的在 D 日的四個目標與收盤對收盤報酬。索引必須是完整的美股交易日曆。"""
    ao, ac = adj_open.astype(float), adj_close.astype(float)
    out = pd.DataFrame({"ao": ao, "ac": ac})
    out["cc"] = ac / ac.shift(1) - 1.0
    out["gap"] = ao / ac.shift(1) - 1.0
    out["oc"] = ac / ao - 1.0
    out["oo1"] = ao.shift(-1) / ao - 1.0
    out["oo5"] = ao.shift(-5) / ao - 1.0
    return out


def circular_shifts(m: int, n_shift: int, min_shift: int, rng: np.random.Generator) -> np.ndarray:
    """圓形位移量：每個都在 [min_shift, m − min_shift] 之間（兩個方向都至少差 min_shift 天）。"""
    lo, hi = min_shift, m - min_shift
    if hi < lo:
        return np.array([], dtype=int)
    cand = np.arange(lo, hi + 1)
    if len(cand) >= n_shift:
        return rng.choice(cand, size=n_shift, replace=False)
    return rng.choice(cand, size=n_shift, replace=True)
