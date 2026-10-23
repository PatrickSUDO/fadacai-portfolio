"""t-stats / bootstrap CIs for the headline numbers (events treated as independent; test2 events overlap in time so t is overstated)."""
import pandas as pd, numpy as np, json
rng = np.random.default_rng(0)
def tstat(x):
    x = x.dropna(); return dict(n=int(len(x)), mean_pct=round(100*x.mean(),2), se_pct=round(100*x.std(ddof=1)/np.sqrt(len(x)),2), t=round(float(x.mean()/(x.std(ddof=1)/np.sqrt(len(x)))),2))
def boot_win(x, neg=True, B=2000):
    x = x.dropna().values; samp = rng.choice(x, (B, len(x))); w = (samp < 0).mean(axis=1) if neg else (samp > 0).mean(axis=1)
    return [round(100*np.percentile(w,2.5),1), round(100*np.percentile(w,97.5),1)]
t1 = pd.read_csv("test1_events.csv"); t2 = pd.read_csv("test2_events.csv")
out = {"test1": {}, "test2": {}}
for k in (20,40,60):
    out["test1"][f"all_excess_{k}"] = tstat(t1[f"excess_{k}"]) | {"pair_win_CI95": boot_win(t1[f"excess_{k}"])}
    out["test1"][f"junplus_excess_{k}"] = tstat(t1[t1.period=="Jun+"][f"excess_{k}"]) | {"pair_win_CI95": boot_win(t1[t1.period=="Jun+"][f"excess_{k}"])}
    out["test1"][f"sys_user_excess_{k}"] = tstat(t1[t1.origin.isin(["system","user"])][f"excess_{k}"]) | {"pair_win_CI95": boot_win(t1[t1.origin.isin(["system","user"])][f"excess_{k}"])}
    for s in ("S1","S2","S3"):
        out["test2"][f"{s}_excess_{k}"] = tstat(t2[t2.signal==s][f"excess_{k}"]) | {"pair_win_CI95": boot_win(t2[t2.signal==s][f"excess_{k}"])}
# equal-$ short P&L sim for test1: $1 short per event, held k days, pair vs outright
for k in (20,40,60):
    d = t1.dropna(subset=[f"excess_{k}"])
    out["test1"][f"sum_pnl_per_$1_outright_short_{k}"] = round(float(-d[f"stock_{k}"].sum()),2)
    out["test1"][f"sum_pnl_per_$1_pair_short_{k}"] = round(float(-d[f"excess_{k}"].sum()),2)
    out["test1"][f"notional_weighted_pnl_outright_short_{k}_usd"] = round(float(-(d[f"stock_{k}"]*d.notional).sum()),0)
    out["test1"][f"notional_weighted_pnl_pair_short_{k}_usd"] = round(float(-(d[f"excess_{k}"]*d.notional).sum()),0)
    jp = d[d.period=="Jun+"]
    out["test1"][f"junplus_notional_weighted_pnl_pair_short_{k}_usd"] = round(float(-(jp[f"excess_{k}"]*jp.notional).sum()),0)
    out["test1"][f"junplus_notional_total_{k}_usd"] = round(float(jp.notional.sum()),0)
json.dump(out, open("significance.json","w"), indent=1)
print(json.dumps(out, indent=1))
