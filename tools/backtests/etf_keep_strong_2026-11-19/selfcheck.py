#!/usr/bin/env python3
"""Self-check: buy-and-hold CAGR of QQQ, SMH, VOO(SPY-spliced) over periods that other scripts
reported. Part A uses the study data (<= 2025-12-31). Part B is a diagnostic only: it reads the
earlier script's local price cache through its own end date (2026-11-09) to compare with the
number printed by that script; it is not used in any study result."""
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D, engine as E

px = D.load_all()
out = {"A_study_data": {}, "B_diagnostic_old_cache_to_2026-11-09": {}}
def cg(s, a, b):
    s = s.loc[a:b]; r = s.pct_change().dropna()
    return round(E.cagr(r.to_numpy()) * 100, 2)
for a in ("2005-01-03", "2010-09-09", "2002-08-20"):
    out["A_study_data"][f"{a}->2025-12-31"] = {"QQQ": cg(px["QQQ"], a, D.END_DATE), "SMH": cg(px["SMH"], a, D.END_DATE),
        "VOO_or_SPY": cg(px["VOO_SPLICED"], a, D.END_DATE), "SPY": cg(px["SPY"], a, D.END_DATE)}
old = pd.read_pickle(D.OLD_PKL)["idx"]
spy = old["SPY"].dropna()
r_spy = spy.pct_change()
voo = px["VOO"].pct_change()
vr = voo.reindex(old.index).where(lambda x: x.notna(), r_spy.reindex(old.index))   # note: yf VOO
for a in ("2002-08-01", "2010-01-04"):
    e = "2026-11-09"
    out["B_diagnostic_old_cache_to_2026-11-09"][f"{a}->{e}"] = {
        "QQQ": cg(old["QQQ"].dropna(), a, e), "SMH": cg(old["SMH"].dropna(), a, e), "SPY": cg(spy, a, e)}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(D.OUT_DIR, "selfcheck.json"), "w"), indent=1)
