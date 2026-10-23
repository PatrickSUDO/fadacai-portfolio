"""Test 1: forward returns after the account's own 2026 stock sells (zero-cost short upper bound).
Entry = adjusted close on sell date (if not a trading day -> next trading day). Exit = close k trading days later."""
import json, pandas as pd, numpy as np
from universe import LEDGER, semi_ai, ETFS
EXCL = {"SGOV", "BIL", "VOO", "GLD", "XLE"}
WINDOWS = (20, 40, 60)
px = pd.read_csv("prices_adjclose.csv", index_col=0, parse_dates=True)
SEMI = semi_ai()

rows = []
for line in open(LEDGER):
    r = json.loads(line)
    if r["side"] != "SOLD" or r.get("is_option") or not ("2026-01-01" <= r["date"] <= "2026-10-22"):
        continue
    if r["symbol"] in EXCL:
        continue
    rows.append(r)
led = pd.DataFrame(rows)
led["origin"] = led.get("origin").fillna("unknown") if "origin" in led else "unknown"
# merge by (symbol, date): notional sum; origin = notional-weighted majority
def merge(g):
    o = g.groupby("origin")["notional"].sum().idxmax()
    return pd.Series({"qty": g["qty"].sum(), "notional": g["notional"].sum(), "origin": o,
                      "origins": "|".join(sorted(set(g["origin"]))), "n_fills": len(g)})
ev = led.groupby(["symbol", "date"]).apply(merge, include_groups=False).reset_index()
ev["bench"] = ev["symbol"].map(lambda s: "SMH" if s in SEMI else "SPY")

idx = px.index
def fwd(sym, d, k):
    if sym not in px.columns: return np.nan, None
    pos = idx.searchsorted(pd.Timestamp(d))
    if pos >= len(idx): return np.nan, None
    s = px[sym]
    if pos + k >= len(idx): return np.nan, idx[pos]
    p0, p1 = s.iloc[pos], s.iloc[pos + k]
    if np.isnan(p0) or np.isnan(p1): return np.nan, idx[pos]
    return p1 / p0 - 1, idx[pos]

missing = []
for k in WINDOWS:
    a, b = [], []
    for _, e in ev.iterrows():
        ra, d0 = fwd(e.symbol, e.date, k)
        rb, _ = fwd(e.bench, e.date, k)
        if e.symbol not in px.columns and e.symbol not in missing: missing.append(e.symbol)
        a.append(ra); b.append(rb)
    ev[f"stock_{k}"] = a; ev[f"bench_{k}"] = b; ev[f"excess_{k}"] = ev[f"stock_{k}"] - ev[f"bench_{k}"]
ev["period"] = np.where(ev["date"] < "2026-03-01", "Jan-Feb", np.where(ev["date"] >= "2026-06-01", "Jun+", "Mar-May"))
ev.to_csv("test1_events.csv", index=False)

def stats(df, k, w=None):
    a, c = df[f"stock_{k}"], df[f"excess_{k}"]
    m = a.notna() & c.notna()
    a, c = a[m], c[m]
    if len(a) == 0: return None
    if w is None:
        wr_a = (a < 0).mean(); wr_c = (c < 0).mean(); mean_a = a.mean(); mean_c = c.mean()
    else:
        ww = w[m] / w[m].sum()
        wr_a = ww[a < 0].sum(); wr_c = ww[c < 0].sum(); mean_a = (a * ww).sum(); mean_c = (c * ww).sum()
    return dict(n=int(len(a)), short_win=round(100 * wr_a, 1), pair_win=round(100 * wr_c, 1),
                mean_stock=round(100 * mean_a, 2), median_stock=round(100 * a.median(), 2),
                mean_excess=round(100 * mean_c, 2), median_excess=round(100 * c.median(), 2),
                p10_excess=round(100 * c.quantile(.1), 2), p90_excess=round(100 * c.quantile(.9), 2),
                worst_stock=round(100 * a.max(), 1), worst_excess=round(100 * c.max(), 1),
                worst_sym=str(df.loc[c.idxmax(), "symbol"]) + " " + str(df.loc[c.idxmax(), "date"]))

out = {"n_events": int(len(ev)), "n_fills": int(len(led)), "missing_price": missing, "all": {}, "weighted": {}, "by_origin": {}, "by_period": {}}
for k in WINDOWS:
    out["all"][k] = stats(ev, k)
    out["weighted"][k] = stats(ev, k, ev["notional"])
    out["by_origin"][k] = {o: stats(g, k) for o, g in ev.groupby("origin")}
    out["by_period"][k] = {p: stats(g, k) for p, g in ev.groupby("period")}
json.dump(out, open("test1_stats.json", "w"), indent=1, default=str)

# markdown
L = []
L.append("| 窗 | n | 空個股勝率(a<0) | 空個股多基準勝率(c<0) | 平均個股 | 中位個股 | 平均超額 | 中位超額 | 超額P10 | 超額P90 | 最差個股(漲) | 最差超額 | 最差單筆 |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for lab, src in (("等權", out["all"]), ("金額加權", out["weighted"])):
    for k in WINDOWS:
        s = src[k]
        L.append(f"| {lab} {k}d | {s['n']} | {s['short_win']}% | {s['pair_win']}% | {s['mean_stock']}% | {s['median_stock']}% | {s['mean_excess']}% | {s['median_excess']}% | {s['p10_excess']}% | {s['p90_excess']}% | +{s['worst_stock']}% | +{s['worst_excess']}% | {s['worst_sym']} |")
L.append("")
L.append("| 分組 | 窗 | n | 空個股勝率 | 配對勝率 | 平均超額 | 中位超額 | 最差超額 |")
L.append("|---|---|---|---|---|---|---|---|")
for k in WINDOWS:
    for o, s in out["by_origin"][k].items():
        if s: L.append(f"| origin={o} | {k}d | {s['n']} | {s['short_win']}% | {s['pair_win']}% | {s['mean_excess']}% | {s['median_excess']}% | +{s['worst_excess']}% |")
for k in WINDOWS:
    for p, s in out["by_period"][k].items():
        if s: L.append(f"| 期間={p} | {k}d | {s['n']} | {s['short_win']}% | {s['pair_win']}% | {s['mean_excess']}% | {s['median_excess']}% | +{s['worst_excess']}% |")
L.append("")
top = ev.sort_values("notional", ascending=False).head(20)
L.append("| 賣出日 | 代號 | 金額 | origin | 基準 | 個股20d | 超額20d | 個股40d | 超額40d | 個股60d | 超額60d |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|")
f = lambda x: "n/a" if pd.isna(x) else f"{100*x:+.1f}%"
for _, e in top.iterrows():
    L.append(f"| {e.date} | {e.symbol} | ${e.notional:,.0f} | {e.origin} | {e.bench} | {f(e.stock_20)} | {f(e.excess_20)} | {f(e.stock_40)} | {f(e.excess_40)} | {f(e.stock_60)} | {f(e.excess_60)} |")
open("test1_tables.md", "w").write("\n".join(L))
print("\n".join(L)); print(json.dumps({k: out[k] for k in ("n_events", "n_fills", "missing_price")}))
