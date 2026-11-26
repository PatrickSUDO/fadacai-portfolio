"""XM 共用：路徑、讀檔（讀進來就切終點）、Newey-West 迴歸、交易規則模擬。

唯讀：不寫回任何來源資料；不讀 holdout／forward／sealed-input 路徑。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import align

END = pd.Timestamp("2025-12-31")  # 預註冊：回測終點
START = pd.Timestamp("2005-01-03")
WINDOWS = {
    "Wa": (pd.Timestamp("2005-01-03"), pd.Timestamp("2012-12-31")),
    "Wb": (pd.Timestamp("2013-01-02"), pd.Timestamp("2019-12-31")),
    "Wc": (pd.Timestamp("2020-01-02"), pd.Timestamp("2025-12-31")),
    "full": (START, END),
}
TARGETS = ["SPY", "QQQ", "SMH", "TSM", "NVDA", "AMD"]
ETF_TARGETS = ["SPY", "QQQ", "SMH"]
STOCK_TARGETS = ["TSM", "NVDA", "AMD"]
PREDICTORS = ["TAIEX_TR", "0050", "2330", "SEMI4"]
SEMI4 = ["2330", "2454", "2303", "3711"]
SEMI4_MIN_MEMBERS = 3  # 3711 於 2018-04-30 才上市；之前用其餘三檔等權（見 interpretation choices）
TRADING_DAYS = 252

REPO = Path(__file__).resolve().parents[4]  # fadacai-portfolio
PROJ = REPO.parent
TW_PANEL = PROJ / "fadacai-tw" / "data" / "curated" / "panel.parquet"
TW_TEJ = PROJ / "fadacai-tw" / "data" / "curated" / "tej" / "prices.parquet"
EODHD_DIR = PROJ / "fadacai-etf-rotation" / "data" / "raw" / "eodhd"
US_STOCKS = PROJ / "fadacai-ranker" / "data" / "silver" / "prices_adjusted" / "prices.parquet"
OUT_DIR = REPO / "tools" / "backtests" / "data" / "overnight_2026-11-19" / "xm"
LEDGER = REPO / "research" / "trade-ledger.jsonl"

_FORBIDDEN = ("holdout", "forward", "sealed-input")


def _guard(p: Path) -> Path:
    s = str(p).lower()
    if any(f in s for f in _FORBIDDEN):
        raise PermissionError(f"forbidden path: {p}")
    return p


# ── 讀檔（end 預設 = 2025-12-31；只有帳本那一段可以傳更晚的 end）──────────────
def load_tw(end: pd.Timestamp | None = END) -> dict[str, pd.DataFrame]:
    """四個台股預測標的的日報酬，索引 = 台股交易日曆（TAIEX_TR 的日期）。欄：cc、oc（SEMI4 以外另有 gap）。"""
    filt = [("symbol", "in", ["TAIEX_TR", "0050"])]
    if end is not None:
        filt.append(("date", "<=", end.date()))
    p = pq.read_table(_guard(TW_PANEL), filters=filt,
                      columns=["date", "symbol", "adj_open", "adj_close"]).to_pandas()
    p["date"] = pd.to_datetime(p["date"])
    filt = [("stock_id", "in", SEMI4)]
    if end is not None:
        filt.append(("date", "<=", end.to_pydatetime()))
    t = pq.read_table(_guard(TW_TEJ), filters=filt,
                      columns=["date", "stock_id", "adj_open", "adj_close"]).to_pandas()
    t["date"] = pd.to_datetime(t["date"])
    if end is not None:
        assert p["date"].max() <= end and t["date"].max() <= end
    cal = pd.DatetimeIndex(sorted(p.loc[p["symbol"] == "TAIEX_TR", "date"].unique()))

    def rets(g: pd.DataFrame) -> pd.DataFrame:
        g = g.set_index("date").sort_index().reindex(cal)  # 缺一天 → 前後報酬都是 NaN
        return pd.DataFrame({"cc": g["adj_close"] / g["adj_close"].shift(1) - 1.0,
                             "oc": g["adj_close"] / g["adj_open"] - 1.0,
                             "gap": g["adj_open"] / g["adj_close"].shift(1) - 1.0})

    out = {
        "TAIEX_TR": rets(p[p["symbol"] == "TAIEX_TR"][["date", "adj_open", "adj_close"]]),
        "0050": rets(p[p["symbol"] == "0050"][["date", "adj_open", "adj_close"]]),
    }
    members = {s: rets(t[t["stock_id"] == s][["date", "adj_open", "adj_close"]]) for s in SEMI4}
    out["2330"] = members["2330"]
    semi = {}
    for col in ("cc", "oc"):
        m = pd.concat([members[s][col] for s in SEMI4], axis=1)
        semi[col] = m.mean(axis=1, skipna=True).where(m.notna().sum(axis=1) >= SEMI4_MIN_MEMBERS)
    out["SEMI4"] = pd.DataFrame(semi)
    return out


def _load_json_rows(sym: str, end: pd.Timestamp | None) -> pd.DataFrame:
    rows = json.loads(_guard(EODHD_DIR / f"{sym}.json").read_text())
    if end is not None:
        cut = end.strftime("%Y-%m-%d")
        rows = [r for r in rows if r["date"] <= cut]  # 讀進來就切
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def load_us(end: pd.Timestamp | None = END) -> dict[str, pd.DataFrame]:
    """六個美股標的。索引 = 美股交易日曆（SPY 的日期）。還原開盤 = open × adjusted_close ÷ close。"""
    raw = {s: _load_json_rows(s, end) for s in ETF_TARGETS}
    filt = [("symbol", "in", STOCK_TARGETS)]
    if end is not None:
        filt.append(("date", "<=", end.strftime("%Y-%m-%d")))
    u = pq.read_table(_guard(US_STOCKS), filters=filt,
                      columns=["date", "symbol", "open", "close", "adjusted_close"]).to_pandas()
    u["date"] = pd.to_datetime(u["date"])
    for s in STOCK_TARGETS:
        raw[s] = u[u["symbol"] == s].drop(columns="symbol").set_index("date").sort_index()
    cal = raw["SPY"].index
    out = {}
    for s in TARGETS:
        g = raw[s]
        if end is not None:
            assert g.index.max() <= end
        g = g[["open", "close", "adjusted_close"]].astype(float).reindex(cal)
        ao = g["open"] * g["adjusted_close"] / g["close"]
        out[s] = align.us_targets(ao, g["adjusted_close"])
    return out


def load_cash(us_cal: pd.DatetimeIndex, end: pd.Timestamp | None = END) -> pd.Series:
    """每個美股交易日的現金日報酬 = 前一個交易日已知的 13 週國庫券利率 ÷ 252。"""
    irx = _load_json_rows("IRX_INDX", end)["close"].astype(float)
    y = irx.reindex(irx.index.union(us_cal)).ffill().reindex(us_cal).shift(1)
    return (y / 100.0 / TRADING_DAYS).rename("cash")


def window_of(dates: pd.DatetimeIndex) -> np.ndarray:
    w = np.full(len(dates), "", dtype=object)
    for name in ("Wa", "Wb", "Wc"):
        a, b = WINDOWS[name]
        w[(dates >= a) & (dates <= b)] = name
    return w


# ── 統計 ─────────────────────────────────────────────────────────────────────
def nw_lag(n: int, h: int = 1) -> int:
    """Newey-West 落後期數：慣例 floor(4·(n/100)^(2/9))，重疊 h 日報酬時至少 h−1。"""
    return int(max(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)), h - 1, 1))


def nw_ols(y: np.ndarray, X: np.ndarray, lag: int) -> dict:
    """OLS 係數與 Newey-West（Bartlett 核）標準誤。X 需自帶常數項。"""
    y = np.asarray(y, float)
    X = np.asarray(X, float)
    n, k = X.shape
    if n <= k + 2:
        return {"coef": np.full(k, np.nan), "se": np.full(k, np.nan), "t": np.full(k, np.nan), "n": n, "r2": np.nan}
    xtx_inv = np.linalg.pinv(X.T @ X)
    b = xtx_inv @ X.T @ y
    e = y - X @ b
    xe = X * e[:, None]
    S = xe.T @ xe
    for l in range(1, min(lag, n - 1) + 1):
        w = 1.0 - l / (lag + 1.0)
        G = xe[l:].T @ xe[:-l]
        S += w * (G + G.T)
    V = xtx_inv @ S @ xtx_inv * n / (n - k)
    se = np.sqrt(np.clip(np.diag(V), 0, None))
    tss = ((y - y.mean()) ** 2).sum()
    r2 = 1.0 - (e @ e) / tss if tss > 0 else np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        t = b / se
    return {"coef": b, "se": se, "t": t, "n": n, "r2": r2}


def nw_mean(x: np.ndarray, h: int = 1) -> dict:
    """平均數與 Newey-West 95% 區間。"""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 10:
        return {"mean": np.nan if n == 0 else float(x.mean()), "lo": np.nan, "hi": np.nan, "n": n}
    r = nw_ols(x, np.ones((n, 1)), nw_lag(n, h))
    m, se = float(r["coef"][0]), float(r["se"][0])
    return {"mean": m, "lo": m - 1.96 * se, "hi": m + 1.96 * se, "n": n}


def bh_qvalues(p: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg q 值（控制偽發現率）。NaN 原樣回傳。"""
    p = np.asarray(p, float)
    q = np.full(len(p), np.nan)
    ok = ~np.isnan(p)
    m = int(ok.sum())
    if m == 0:
        return q
    idx = np.where(ok)[0]
    order = idx[np.argsort(p[idx])]
    ranked = p[order] * m / np.arange(1, m + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    q[order] = np.minimum(ranked, 1.0)
    return q


# ── 交易規則模擬（全部回傳「整段的對數總報酬」，可一次算很多列訊號）──────────────
def intraday_logtotal(sig: np.ndarray, oc: np.ndarray, cash: np.ndarray, cost: float) -> np.ndarray:
    """R1／R2：訊號日開盤買、收盤賣（兩邊各付 cost），其餘日子放現金。sig 形狀 (k, m)。"""
    net = (1.0 + oc) * (1.0 - cost) / (1.0 + cost) - 1.0
    r = np.where(sig, net[None, :], cash[None, :])
    return np.log1p(r).sum(axis=1)


def tranche_decision_index(n_int: int, H: int, k: int) -> np.ndarray:
    """分批慣例：min(H,21) 批，全部在模擬起點進場，之後各自照錯開的位移（k）每 H 天決定一次。

    回傳每個區間 j（第 j 天開盤 → 第 j+1 天開盤）所屬的決定日位置。
    """
    j = np.arange(n_int)
    if k == 0:
        return j - (j % H)
    return np.where(j < k, 0, j - ((j - k) % H))


def tranche_logtotal(sig: np.ndarray, oo1: np.ndarray, cash: np.ndarray, cost: float, H: int = 5) -> np.ndarray:
    """R3：訊號日開盤買、抱 H 個交易日後的開盤賣。sig 形狀 (k, n)，n = 交易日數。

    用 n−1 個「開盤到隔日開盤」區間；最後一天開盤強制平倉。批與批之間不互相再平衡。
    同一批連續兩次都有訊號時不賣再買（不付成本）。
    """
    n_tr = min(H, 21)
    n_int = sig.shape[1] - 1
    if n_int <= 0:
        return np.zeros(sig.shape[0])
    r_in, r_out = oo1[:n_int], cash[:n_int]
    lc = np.log1p(-cost)
    eq = np.zeros(sig.shape[0])
    for k in range(n_tr):
        dec = tranche_decision_index(n_int, H, k)
        pos = sig[:, dec]
        r = np.where(pos, r_in[None, :], r_out[None, :])
        le = np.log1p(r).sum(axis=1)
        trades = (pos[:, 0].astype(int) + np.abs(np.diff(pos.astype(np.int8), axis=1)).sum(axis=1)
                  + pos[:, -1].astype(int))
        eq += np.exp(le + trades * lc)
    return np.log(eq / n_tr)


def cagr(logtotal, n_periods: int):
    if n_periods <= 0:
        return np.nan
    return np.expm1(np.asarray(logtotal) * TRADING_DAYS / n_periods)
