import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
PX = pd.read_csv("data/prices.csv", index_col=0, parse_dates=True)
PX = PX.loc[:"2026-10-22"]
RET = PX.drop(columns=["^IRX"]).pct_change()
# T-bill daily return from 13-week bill discount yield (^IRX, % annualized); ffill gaps; /252 per trading day
IRX = PX["^IRX"].ffill().clip(lower=0) / 100.0
RF_D = (IRX / 252.0).reindex(RET.index).ffill()
RET["TBILL"] = RF_D

W1 = ("2026-06-22", "2026-07-28")
W2 = ("2026-10-07", "2026-10-16")

def nav_from_ret(r):
    r = r.dropna()
    return (1 + r).cumprod()

def window_ret(nav, a, b):
    nav = nav.dropna()
    try:
        s = nav.loc[:a].iloc[-1]; e = nav.loc[:b].iloc[-1]
        return e / s - 1
    except Exception:
        return np.nan

def dd_series(nav):
    return nav / nav.cummax() - 1

def metrics(nav, label=""):
    nav = nav.dropna()
    r = nav.pct_change().dropna()
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(252)
    rf = RF_D.reindex(r.index).mean() * 252
    sharpe = (cagr - rf) / vol if vol > 0 else np.nan
    dd = dd_series(nav)
    mdd = dd.min()
    yr = nav.resample("YE").last().pct_change().dropna()
    # first partial year: include from first nav
    first_year = nav.index[0].year
    fy = nav[nav.index.year == first_year]
    yr_full = yr.copy()
    if len(fy) > 20 and first_year < nav.index[-1].year:
        yr_full.loc[pd.Timestamp(f"{first_year}-12-31")] = fy.iloc[-1] / fy.iloc[0] - 1
        yr_full = yr_full.sort_index()
    worst = yr_full.idxmin() if len(yr_full) else None
    r2022 = yr_full[yr_full.index.year == 2022]
    r2022 = r2022.iloc[0] if len(r2022) else np.nan
    return dict(label=label, start=str(nav.index[0].date()), end=str(nav.index[-1].date()), years=yrs,
                cagr=cagr, vol=vol, mdd=mdd, sharpe=sharpe, rf=rf,
                worst_year=(f"{worst.year}:{yr_full.min():+.1%}" if worst is not None else "n/a"), r2022=r2022,
                w1=window_ret(nav, *W1), w2=window_ret(nav, *W2))

def rebalance_nav(rets, weights, mode="M", band=0.05, start=None, end=None):
    """rets: DataFrame of daily returns (columns = assets); weights: dict target.
    mode: 'M' monthly, 'Q' quarterly, 'B' band threshold (abs deviation > band on any asset), 'D' daily, 'N' never (buy&hold)."""
    cols = list(weights)
    R = rets[cols].dropna()
    if start: R = R.loc[start:]
    if end: R = R.loc[:end]
    w_t = np.array([weights[c] for c in cols])
    vals = w_t.copy()
    out = np.empty(len(R)); out[0] = 1.0
    nav = 1.0
    idx = R.index
    rebs = 0
    for i in range(1, len(R)):
        row = R.iloc[i].values
        vals = vals * (1 + row)
        nav = vals.sum()
        out[i] = nav
        do = False
        if mode == "D": do = True
        elif mode == "M": do = idx[i].month != idx[i-1].month
        elif mode == "Q": do = (idx[i].month != idx[i-1].month) and idx[i].month in (1, 4, 7, 10)
        elif mode == "B": do = np.abs(vals / nav - w_t).max() > band
        if do:
            vals = nav * w_t; rebs += 1
    s = pd.Series(out, index=idx)
    s.attrs["rebalances"] = rebs
    return s

def dd_episodes(nav, thr=-0.10):
    """R15 style: count distinct episodes where drawdown from running peak breaches thr; episode ends at new peak.
    returns (n_episodes, frac_days_in_zone, list of (start, trough_date, depth, end/recover date, days_to_recover_from_breach))"""
    nav = nav.dropna(); dd = dd_series(nav)
    in_ep = False; eps = []; zone_days = 0; cur = None
    for d, v in dd.items():
        if not in_ep and v <= thr:
            in_ep = True; cur = dict(start=d, trough=d, depth=v)
        if in_ep:
            zone_days += 1
            if v < cur["depth"]: cur["depth"] = v; cur["trough"] = d
            if v >= 0:
                in_ep = False; cur["end"] = d; cur["days"] = (d - cur["start"]).days; eps.append(cur); cur = None
    if in_ep:
        cur["end"] = None; cur["days"] = (nav.index[-1] - cur["start"]).days; eps.append(cur)
    return len(eps), zone_days / len(dd), eps

def fmt_pct(x, d=1):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x*100:+.{d}f}%"
def fmt_num(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"

def fmt_u(x, d=1):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x*100:.{d}f}%"

def core_proxy(beta=0.835, start=None, end=None):
    """0.835×SMH proxy: daily-rebalanced beta×SMH + (1−beta)×T-bill (constant-beta account proxy)."""
    r = RET[["SMH","TBILL"]].dropna()
    if start: r = r.loc[start:]
    if end: r = r.loc[:end]
    return beta*r["SMH"] + (1-beta)*r["TBILL"]
