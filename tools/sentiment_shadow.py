"""EODHD news-sentiment shadow test on archived snapshots (added 2026-09-11).
S_t = mean article polarity in day-t archive snapshot; test vs forward 5d excess return (vs SPY), pooled + per-ticker.
Run at /trade-review: uv run --directory tools python3 tools/sentiment_shadow.py
First run 2026-09-11 (33 days): pooled rho -0.17 (contrarian) but per-ticker median -0.03, 10/22 positive -> no timing signal; 55% of readings >0.90 (saturated).
"""
import json, glob, os, math, statistics as st
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd

ROOT = "/Users/supatrick/laptop/project/fadacai-portfolio/briefing-out/cache/archive"
days = sorted(glob.glob(f"{ROOT}/*/news-articles.json"))
rows = []
for f in days:
    day = f.split("/")[-2]
    d = json.load(open(f))
    for tk, v in (d.get("tickers") or {}).items():
        arts = v.get("articles") or []
        pols = [a.get("sentiment", {}).get("polarity") for a in arts if a.get("sentiment")]
        pols = [p for p in pols if isinstance(p, (int, float))]
        if len(pols) >= 2:
            rows.append((day, tk, st.mean(pols), len(pols)))
df = pd.DataFrame(rows, columns=["day", "tk", "S", "n_art"])
df["day"] = pd.to_datetime(df["day"])
print(f"obs={len(df)} tickers={df.tk.nunique()} days={df.day.nunique()}  {df.day.min().date()}→{df.day.max().date()}")
q = df.S.quantile([.05, .25, .5, .75, .95]).round(3).to_dict()
print("polarity distribution (5/25/50/75/95 pct):", q)
print(f"share of readings > 0.90: {(df.S>0.90).mean():.0%}")

tks = sorted(df.tk.unique().tolist()) + ["SPY"]
px = yf.download(tks, start="2026-07-15", end="2026-09-12", auto_adjust=True, progress=False)["Close"]
px = px.dropna(how="all")

def fwd_ret(tk, day, h=5):
    s = px[tk].dropna()
    idx = s.index.searchsorted(day)
    if idx >= len(s) or idx + h >= len(s):
        return None
    return s.iloc[idx + h] / s.iloc[idx] - 1

out = []
for _, r in df.iterrows():
    if r.tk not in px.columns:
        continue
    fr = fwd_ret(r.tk, r.day); fs = fwd_ret("SPY", r.day)
    if fr is None or fs is None:
        continue
    out.append((r.day, r.tk, r.S, fr - fs, fr))
res = pd.DataFrame(out, columns=["day", "tk", "S", "xret5", "ret5"])
# delta
res = res.sort_values(["tk", "day"])
res["S_lag"] = res.groupby("tk")["S"].shift(3)   # ~5 trading days back in snapshot days
res["dS"] = res.S - res.S_lag
print(f"\nusable obs={len(res)}  (with dS: {res.dS.notna().sum()})")

def report(x, y, name):
    m = res[[x, y]].dropna()
    rho = m[x].rank().corr(m[y].rank())
    t1, t3 = m[x].quantile(1/3), m[x].quantile(2/3)
    lo, hi = m[m[x] <= t1][y], m[m[x] >= t3][y]
    print(f"{name}: spearman={rho:+.3f}  bottom-tercile mean {y}={lo.mean():+.2%} (n={len(lo)}) | top-tercile {hi.mean():+.2%} (n={len(hi)})  diff={hi.mean()-lo.mean():+.2%}")

report("S", "xret5", "level S vs fwd5 excess")
report("S", "ret5", "level S vs fwd5 raw   ")
report("dS", "xret5", "delta S vs fwd5 excess")
report("dS", "ret5", "delta S vs fwd5 raw   ")
# per-ticker sign consistency
signs = res.groupby("tk").apply(lambda g: g.S.rank().corr(g.xret5.rank()) if len(g) > 8 else None).dropna()
print(f"\nper-ticker spearman(level S, xret5): median={signs.median():+.3f}, positive in {(signs>0).sum()}/{len(signs)} tickers")
print("effective independent samples ≈ days/5 * tickers/ρ_cross ... treat n as ~%d not %d" % (res.day.nunique()//5 * 3, len(res)))
