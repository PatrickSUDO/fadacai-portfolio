"""Price loading for the ETF keep-the-strong study (spec: research/etf-keep-strong-study-2026-11-19.md).

Adjusted (total-return) closes only. Every row after END_DATE is dropped right after reading.
Sources, in order: local raw JSON of the sibling data repo (read-only), then local pickle caches of
earlier scripts, then a one-time fetch with yfinance (auto_adjust closes) cached under the git-ignored
data folder. No account, trade or personal data is read or sent.
"""
from __future__ import annotations

import json
import os

import pandas as pd

END_DATE = "2025-12-31"
HERE = os.path.dirname(os.path.abspath(__file__))
BACKTESTS = os.path.normpath(os.path.join(HERE, ".."))
REPO = os.path.normpath(os.path.join(BACKTESTS, "..", ".."))
OUT_DIR = os.path.join(BACKTESTS, "data", "etf_keep_strong_2026-11-19")
CACHE_DIR = os.path.join(OUT_DIR, "cache")
RAW_ROOT = os.environ.get("ETFKS_RAW_ROOT") or os.path.normpath(
    os.path.join(REPO, "..", "fadacai-etf-rotation", "data", "raw"))
RAW_DIRS = ("eodhd", "eodhd_explore")
OLD_PKL = os.path.join(BACKTESTS, "data", "trend_switch_ema_macd_2026-11-16.px.pkl")  # has IGV
YF_CACHE = os.path.join(CACHE_DIR, "yf_VOX_IBB_VOO.pkl")

G3 = ["QQQ", "SMH", "IGV"]
G7 = ["QQQ", "SMH", "IGV", "XLK", "XLY", "VOX", "IBB"]


def clip_end(s):
    """Drop every row dated after END_DATE (Series or DataFrame with a DatetimeIndex)."""
    out = s.loc[s.index <= pd.Timestamp(END_DATE)]
    assert (out.index <= pd.Timestamp(END_DATE)).all()
    return out


def _raw_json(sym):
    for d in RAW_DIRS:
        p = os.path.join(RAW_ROOT, d, sym + ".json")
        if os.path.exists(p):
            df = pd.DataFrame(json.load(open(p)))
            df["date"] = pd.to_datetime(df["date"].astype(str))
            s = pd.to_numeric(df.set_index("date")["adjusted_close"], errors="coerce")
            return s
    return None


def _from_pkls(sym):
    if sym == "IGV" and os.path.exists(OLD_PKL):
        return pd.read_pickle(OLD_PKL)["idx"]["IGV"]
    if os.path.exists(YF_CACHE):
        d = pd.read_pickle(YF_CACHE)
        if sym in d.columns:
            return d[sym]
    return None


def _fetch(syms):
    import warnings
    import yfinance as yf
    warnings.filterwarnings("ignore")
    os.makedirs(CACHE_DIR, exist_ok=True)
    d = yf.download(syms, period="max", progress=False, auto_adjust=True)["Close"]
    d.to_pickle(YF_CACHE)
    return d


def load_series(sym, log=None):
    src = "eodhd_json"
    s = _raw_json(sym)
    if s is None:
        src = "pkl_cache"
        s = _from_pkls(sym)
    if s is None:
        src = "yfinance_fetch"
        _fetch(["VOX", "IBB", "VOO"])
        s = _from_pkls(sym)
    if s is None:
        return None
    s = clip_end(s.dropna().sort_index())
    s = s[~s.index.duplicated(keep="last")]
    s = s[s > 0]
    if log is not None:
        log.append({"symbol": sym, "source": src, "first": str(s.index[0].date()),
                    "last": str(s.index[-1].date()), "rows": int(len(s))})
    return s


def load_all(log=None):
    """dict symbol -> adjusted close Series (<= END_DATE). VOO is spliced with SPY returns
    before its listing (same convention as the 2026-11-10 script)."""
    px = {}
    for sym in sorted(set(G7) | {"SPY", "VOO"}):
        s = load_series(sym, log)
        if s is not None:
            px[sym] = s
    if "VOO" in px and "SPY" in px:
        r = px["VOO"].pct_change()
        rs = px["SPY"].pct_change()
        rr = r.reindex(px["SPY"].index)
        rr = rr.where(rr.notna(), rs)
        first = px["VOO"].index[0]
        rr = rr.copy()
        rr.loc[first] = rs.loc[first] if first in rs.index else 0.0
        rr.iloc[0] = 0.0
        px["VOO_SPLICED"] = (1 + rr.fillna(0)).cumprod()
    return px


def common_frame(px, names):
    df = pd.concat({n: px[n] for n in names}, axis=1, join="inner").sort_index()
    assert df.index.max() <= pd.Timestamp(END_DATE)
    return df
