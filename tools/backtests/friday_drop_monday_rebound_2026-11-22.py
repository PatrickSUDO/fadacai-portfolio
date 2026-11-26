"""Friday-drop -> next-session rebound event study (2026-11-22).

Question: after a big down Friday, do US index ETFs rebound on the next session
(usually Monday), especially in Trump's second term (from 2025-01-20)? Is it
specific to Fridays or just the generic "day after a big drop" effect?

Data: yfinance daily, auto_adjust=True, through 2026-11-20.
  SPY (1993->), QQQ (1999->), SMH (2012-01-01-> only; earlier history defective),
  ^GSPC close-only (1950->) for a long close-to-close check.

Event: a Friday with close-to-close return <= X, X in {-0.5,-1.0,-1.5,-2.0}%.
Outcomes (next trading session): close->close, gap (event close -> next open),
intraday (next open -> next close), cumulative close->close over 3 and 5 sessions,
and close->close scaled by trailing 20-day realized vol (known at event close).
Controls (same period): (1) same-threshold drop Mon-Thu, (2) all days,
(3) the session after every Friday (= all Mondays, Tuesday after a Monday holiday).

Run: python3 tools/backtests/friday_drop_monday_rebound_2026-11-22.py
Output: tools/backtests/data/friday_drop_monday_rebound_2026-11-22.out.txt
"""
import io
import os
import sys
import warnings
from contextlib import redirect_stderr

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

END = "2026-11-21"  # yfinance end is exclusive -> data through 2026-11-20
LAST = pd.Timestamp("2026-11-20")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                   "friday_drop_monday_rebound_2026-11-22.out.txt")
THRESH = [-0.005, -0.010, -0.015, -0.020]
PRIMARY = -0.010
COST = 0.0002  # per side
B = 10_000
SEED = 20261122
TICKERS = [("SPY", "1993-01-01", True), ("QQQ", "1999-01-01", True),
           ("SMH", "2012-01-01", True), ("^GSPC", "1950-01-01", False)]
PERIODS = [
    ("Full", None, None),
    ("Start-2017-01-19", None, "2017-01-19"),
    ("Trump1", "2017-01-20", "2021-01-19"),
    ("Biden", "2021-01-20", "2025-01-17"),
    ("Trump2", "2025-01-20", "2026-11-20"),
]

lines = []


def p(s=""):
    lines.append(s)
    print(s)


def load(tk, start, ohlc):
    with redirect_stderr(io.StringIO()):
        df = yf.download(tk, start=start, end=END, auto_adjust=True,
                         progress=False, threads=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "Close"]].copy() if ohlc else df[["Close"]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[df.index <= LAST]
    return df


def sanity(tk, df):
    dup = int(df.index.duplicated().sum())
    nonpos = int((df <= 0).sum().sum())
    nan = int(df.isna().sum().sum())
    r = df["Close"].pct_change()
    big = r[r.abs() > 0.15]
    msg = (f"{tk:6s} {df.index[0].date()}..{df.index[-1].date()} rows={len(df)} "
           f"dup_dates={dup} nonpos_prices={nonpos} NaN={nan} |ret|>15%: {len(big)}")
    p(msg)
    for d, v in big.items():
        p(f"         flag {d.date()} {v*100:+.1f}%")
    if "Open" in df:
        g = df["Open"] / df["Close"].shift(1) - 1
        bg = g[g.abs() > 0.15]
        for d, v in bg.items():
            p(f"         flag gap {d.date()} {v*100:+.1f}%")
    return df[~df.index.duplicated()].dropna()


def build(df):
    c = df["Close"]
    o = pd.DataFrame(index=df.index)
    o["r"] = c.pct_change()
    o["dow"] = df.index.dayofweek
    o["next_date"] = pd.Series(df.index, index=df.index).shift(-1)
    o["cc"] = c.shift(-1) / c - 1
    if "Open" in df:
        o["gap"] = df["Open"].shift(-1) / c - 1
        o["intra"] = c.shift(-1) / df["Open"].shift(-1) - 1
    o["d3"] = c.shift(-3) / c - 1
    o["d5"] = c.shift(-5) / c - 1
    o["vol20"] = o["r"].rolling(20).std()
    o["z"] = o["cc"] / o["vol20"]
    o = o.iloc[1:]
    return o


def tstat(x):
    x = np.asarray(x)
    if len(x) < 2 or x.std(ddof=1) == 0:
        return np.nan
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))


rng = np.random.default_rng(SEED)


def perm_two(a, b):
    """Two-sided permutation p for mean(a)-mean(b), labels shuffled."""
    a, b = np.asarray(a), np.asarray(b)
    if len(a) < 2 or len(b) < 2:
        return np.nan
    obs = a.mean() - b.mean()
    pool = np.concatenate([a, b])
    n, N = len(a), len(pool)
    tot = pool.sum()
    cnt = 0
    for s in range(0, B, 1000):
        k = min(1000, B - s)
        idx = np.argpartition(rng.random((k, N)), n - 1, axis=1)[:, :n]
        sa = pool[idx].sum(axis=1)
        d = sa / n - (tot - sa) / (N - n)
        cnt += int((np.abs(d) >= abs(obs) - 1e-15).sum())
    return (cnt + 1) / (B + 1)


def perm_subset(a, allx):
    """Two-sided p for mean(a)-mean(all): random n-subsets of all (a is a subset)."""
    a, allx = np.asarray(a), np.asarray(allx)
    if len(a) < 2:
        return np.nan
    mu = allx.mean()
    obs = a.mean() - mu
    n, N = len(a), len(allx)
    cnt = 0
    for s in range(0, B, 1000):
        k = min(1000, B - s)
        idx = np.argpartition(rng.random((k, N)), n - 1, axis=1)[:, :n]
        d = allx[idx].mean(axis=1) - mu
        cnt += int((np.abs(d) >= abs(obs) - 1e-15).sum())
    return (cnt + 1) / (B + 1)


def slice_period(o, a, b):
    m = pd.Series(True, index=o.index)
    if a:
        m &= o.index >= pd.Timestamp(a)
    if b:
        m &= o.index <= pd.Timestamp(b)
    return o[m]


def fmt_pct(x, w=7, d=2):
    return f"{x*100:+{w}.{d}f}" if pd.notna(x) else " " * (w - 2) + "na"


cells = 0      # (ticker x period x threshold x outcome) event cells with n>=1
perms = 0      # permutation tests run
data = {}

p("Friday-drop -> next-session rebound event study  (run 2026-11-22, data through 2026-11-20)")
p("yfinance auto_adjust=True; SMH restricted to 2012-01-01+; ^GSPC close-only (no gap/intraday).")
p(f"Permutation tests: {B} shuffles, seed {SEED}. Cost for trade check: {COST*1e4:.0f} bp per side.")
p("Units: returns in %, z = next-session return / trailing 20-day daily vol (incl. event day).")
p()
p("=== 0. Sanity check ===")
for tk, st, ohlc in TICKERS:
    df = load(tk, st, ohlc)
    df = sanity(tk, df)
    data[tk] = build(df)
p()

OUTS_FULL = [("cc", "next c->c"), ("gap", "gap c->o"), ("intra", "intraday o->c"),
             ("d3", "3-sess c->c"), ("d5", "5-sess c->c"), ("z", "vol-scaled z")]

summary_rows = []

for tk, _, ohlc in TICKERS:
    o = data[tk]
    p("=" * 110)
    p(f"=== {tk} ===")
    for pname, a, b in PERIODS:
        op = slice_period(o, a, b)
        if len(op) == 0:
            continue
        p(f"--- {tk} | {pname} | {op.index[0].date()}..{op.index[-1].date()} | sessions={len(op)} ---")
        # (a) all thresholds, next close->close
        p("  [all thresholds] outcome = next-session close->close")
        p("    X      grp       n    mean%  median%  hit%     t   med|r|%   z_mean | diff vs MonThu (p)  | diff vs All (p)")
        allcc = op["cc"].dropna()
        frifull = op[op["dow"] == 4]["cc"].dropna()
        for X in THRESH:
            ev = op[(op["dow"] == 4) & (op["r"] <= X)]
            c1 = op[(op["dow"] < 4) & (op["r"] <= X)]
            e, c = ev["cc"].dropna(), c1["cc"].dropna()
            ez, cz = ev["z"].dropna(), c1["z"].dropna()
            if len(e):
                cells += 1
            p1 = perm_two(e, c); p2 = perm_subset(e, allcc); perms += 2
            for g, x, xz in (("Fri", e, ez), ("MonThu", c, cz)):
                if len(x) == 0:
                    p(f"  {X*100:+5.1f}  {g:7s} {0:5d}")
                    continue
                tail = ""
                if g == "Fri":
                    tail = (f" | {fmt_pct(e.mean()-c.mean() if len(c) else np.nan)} (p={p1:.3f})"
                            f" | {fmt_pct(e.mean()-allcc.mean())} (p={p2:.3f})")
                p(f"  {X*100:+5.1f}  {g:7s} {len(x):5d} {fmt_pct(x.mean())} {fmt_pct(x.median())} "
                  f"{(x>0).mean()*100:5.0f} {tstat(x):+6.2f} {x.abs().median()*100:8.2f} "
                  f"{xz.mean() if len(xz) else np.nan:+8.3f}{tail}")
        for g, x, xz in (("AllDays", allcc, op["z"].dropna()),
                         ("AfterFri", frifull, op[op['dow'] == 4]["z"].dropna())):
            p(f"   ctrl  {g:8s}{len(x):5d} {fmt_pct(x.mean())} {fmt_pct(x.median())} "
              f"{(x>0).mean()*100:5.0f} {tstat(x):+6.2f} {x.abs().median()*100:8.2f} {xz.mean():+8.3f}")
        # primary threshold, all outcomes
        X = PRIMARY
        ev = op[(op["dow"] == 4) & (op["r"] <= X)]
        c1 = op[(op["dow"] < 4) & (op["r"] <= X)]
        c3 = op[op["dow"] == 4]
        p(f"  [primary X={X*100:+.1f}%] all outcomes")
        p("    outcome         grp       n    mean%  median%  hit%     t | Fri-MonThu (p)     | Fri-All (p)")
        for col, lab in OUTS_FULL:
            if col not in op:
                continue
            e = ev[col].dropna(); c = c1[col].dropna(); al = op[col].dropna(); m = c3[col].dropna()
            if col == "cc":
                pa, pb = None, None  # already above
            if len(e):
                if col != "cc":
                    cells += 1
            p1 = perm_two(e, c); p2 = perm_subset(e, al); perms += 2
            sc = 1 if col == "z" else 100
            def row(g, x, tail=""):
                if len(x) == 0:
                    return f"    {lab:14s}  {g:7s} {0:5d}"
                return (f"    {lab:14s}  {g:7s} {len(x):5d} {x.mean()*sc:+8.3f} {x.median()*sc:+8.3f} "
                        f"{(x>0).mean()*100:5.0f} {tstat(x):+6.2f}{tail}")
            p(row("Fri", e, f" | {(e.mean()-c.mean())*sc if len(c) and len(e) else np.nan:+7.3f} (p={p1:.3f})"
                             f" | {(e.mean()-al.mean())*sc if len(e) else np.nan:+7.3f} (p={p2:.3f})"))
            p(row("MonThu", c)); p(row("AllDays", al)); p(row("AfterFri", m))
            if col == "cc":
                summary_rows.append((tk, pname, len(e), e.mean() if len(e) else np.nan,
                                     e.median() if len(e) else np.nan,
                                     (e > 0).mean() if len(e) else np.nan, tstat(e),
                                     c.mean() if len(c) else np.nan, len(c), al.mean(),
                                     m.mean(), e.mean() - c.mean() if len(c) else np.nan, p1,
                                     e.mean() - al.mean(), p2,
                                     ev["z"].dropna().mean() if len(e) else np.nan,
                                     c1["z"].dropna().mean(), op["z"].dropna().mean(),
                                     e.abs().median() if len(e) else np.nan, al.abs().median()))
        p()

p("=" * 110)
p(f"=== SUMMARY, primary X={PRIMARY*100:+.1f}%, outcome next-session close->close (%) ===")
p("tick   period            nFri  meanFri medFri hit%    t  | nMT meanMT | meanAll meanAftFri | Fri-MT  p     | Fri-All p     | zFri  zMT  zAll | med|r| Fri/All")
for r in summary_rows:
    (tk, pn, n, mu, md, hit, t, cmu, cn, amu, fmu, d1, p1, d2, p2, zf, zc, za, mf, ma) = r
    p(f"{tk:6s} {pn:16s} {n:5d} {fmt_pct(mu)} {fmt_pct(md,6)} {hit*100 if n else np.nan:4.0f} {t:+5.2f} |"
      f" {cn:4d} {fmt_pct(cmu)} | {fmt_pct(amu)} {fmt_pct(fmu)} | {fmt_pct(d1)} {p1:.3f} |"
      f" {fmt_pct(d2)} {p2:.3f} | {zf:+.2f} {zc:+.2f} {za:+.2f} | {mf*100 if n else np.nan:.2f}/{ma*100:.2f}")
p()

# Trump-2 event list
p("=== Trump-2 events at X=-1.0% (Friday c->c <= -1%), SPY and QQQ ===")
for tk in ("SPY", "QQQ"):
    o = slice_period(data[tk], "2025-01-20", "2026-11-20")
    ev = o[(o["dow"] == 4) & (o["r"] <= PRIMARY)]
    p(f"  {tk}: n={len(ev)}")
    p("    Friday       Fri%    next session   gap%  intra%  c->c%")
    for d, row in ev.iterrows():
        nd = row["next_date"].date() if pd.notna(row["next_date"]) else "n/a"
        p(f"    {d.date()} {row['r']*100:+6.2f}   {str(nd):12s} {fmt_pct(row['gap'],6)} "
          f"{fmt_pct(row['intra'],6)} {fmt_pct(row['cc'],6)}")
p()

# Application A
p("=== Application A: buy Friday close after Fri <= -1%, sell next close, 2 bp/side ===")
p("tick   period            years trades tr/yr  mean_net%  hit%  total%  annual_contrib%  worst%  (same rule on Mon-Thu drops: trades mean_net% total%)")
for tk in ("SPY", "QQQ", "SMH"):
    o = data[tk]
    for pname, a, b in PERIODS:
        op = slice_period(o, a, b)
        yrs = (op.index[-1] - op.index[0]).days / 365.25
        res = []
        for mask in ((op["dow"] == 4) & (op["r"] <= PRIMARY), (op["dow"] < 4) & (op["r"] <= PRIMARY)):
            x = op.loc[mask, "cc"].dropna()
            net = (1 - COST) * (1 + x) * (1 - COST) - 1
            tot = (1 + net).prod() - 1
            res.append((len(net), net.mean(), (net > 0).mean(), tot, net.min()))
        n, mu, hit, tot, worst = res[0]
        ann = (1 + tot) ** (1 / yrs) - 1
        p(f"{tk:6s} {pname:16s} {yrs:5.1f} {n:6d} {n/yrs:5.1f} {fmt_pct(mu,8,3)} {hit*100:5.0f} "
          f"{fmt_pct(tot,7,1)} {fmt_pct(ann,8,2)} {fmt_pct(worst,7,2)}   "
          f"({res[1][0]} {fmt_pct(res[1][1],7,3)} {fmt_pct(res[1][3],7,1)})")
p("  Note: the Mon-Thu-drop version overlaps nothing with the Friday version; it is the generic after-drop trade.")
p()

# Application B
p("=== Application B: execution timing on Fri <= -1% (no extra trades) ===")
p("  Buyer advantage of buying at Friday close (positive = Friday close was cheaper):")
p("    vs next open  = next_open/Fri_close - 1 (= gap);  vs next close = next_close/Fri_close - 1.")
p("  Seller advantage of selling at Friday close = minus the above.")
p("  Baseline 'AllDays' = same quantity for buying at any day's close vs the next session.")
p("tick   period             n   vsOpen mean/med  FriBetter%  | vsClose mean/med  FriBetter% | AllDays vsOpen  vsClose")
for tk in ("SPY", "QQQ", "SMH"):
    o = data[tk]
    for pname, a, b in PERIODS:
        op = slice_period(o, a, b)
        ev = op[(op["dow"] == 4) & (op["r"] <= PRIMARY)]
        g, c = ev["gap"].dropna(), ev["cc"].dropna()
        p(f"{tk:6s} {pname:16s} {len(c):4d}  {fmt_pct(g.mean(),6)}/{fmt_pct(g.median(),6)}   {(g>0).mean()*100:5.0f}"
          f"       | {fmt_pct(c.mean(),6)}/{fmt_pct(c.median(),6)}   {(c>0).mean()*100:5.0f}"
          f"      | {fmt_pct(op['gap'].mean(),6)} {fmt_pct(op['cc'].mean(),6)}")
p("  For a seller the advantage of selling at Friday close is the negative of each mean; "
  "'FriBetter%' for a seller = 100 - the buyer figure.")
p()

p("=== Multiple testing ===")
p(f"  Event cells (ticker x period x threshold x outcome) with n>=1 examined: {cells}")
p(f"  Permutation tests run: {perms}")
p("  With this many cells, a handful of p<0.05 results is expected by chance alone (~5%).")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"\n[wrote {OUT}]", file=sys.stderr)
