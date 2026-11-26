#!/usr/bin/env python3
"""Run the frozen ETF keep-the-strong study (research/etf-keep-strong-study-2026-11-19.md).
Nothing is tuned: lists, lookbacks, check periods, forms, cost, windows and pass lines are fixed here
exactly as in the spec. Outputs go to tools/backtests/data/etf_keep_strong_2026-11-19/ only."""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D          # noqa: E402
import engine as E        # noqa: E402

SEED = 20261119
N_NULL = 1000
MIN_HIST = 273
HS = (63, 126)
COST20 = 0.0020
WINDOWS = {"W2005_2012": ("2005-01-01", "2012-12-31"), "W2013_2019": ("2013-01-01", "2019-12-31"),
           "W2020_2025": ("2020-01-01", "2025-12-31")}
LAST18 = ("2024-07-01", "2025-12-31")
LISTS = {"G3": D.G3}
FORM_ZH = {"keep": "留強", "cull": "汰弱", "stay": "續抱"}


def seg(dates, a, b):
    m = (dates >= pd.Timestamp(a)) & (dates <= pd.Timestamp(b))
    return np.asarray(m)


def monthly(r, dates):
    s = pd.Series(np.log1p(r), index=dates)
    return np.expm1(s.groupby([s.index.year, s.index.month]).sum())


def ir_vs(r, b, dates):
    a = monthly(r, dates) - monthly(b, dates)
    return float(a.mean() / a.std(ddof=1) * np.sqrt(12))


def stats(r):
    return {"cagr": E.cagr(r), "mdd": E.mdd(r), "vol": E.vol(r)}


def main():
    os.makedirs(D.OUT_DIR, exist_ok=True)
    log = []
    px = D.load_all(log)
    lists = {"G3": D.G3[:]}
    g7 = [s for s in D.G7 if s in px]
    dropped = [s for s in D.G7 if s not in px]
    lists["G7"] = g7
    voo = px["VOO_SPLICED"]
    meta = {"data_log": log, "g7_dropped": dropped, "seed": SEED, "n_null": N_NULL}
    cells, wins, nulls, yearly, benchs = [], [], [], [], []
    cell_rows = {}
    for lname, names in lists.items():
        df = D.common_frame(px, names)
        dates_all = df.index
        P = df.to_numpy(float)
        T, n = P.shape
        R = E.returns(P)
        S = MIN_HIST - 1                       # 0-based index of the 273rd common session
        Ev = S + 105 + 2                       # first session on which every tranche (H=126, k=5) earns
        dates = dates_all[Ev:]
        iq, ism = names.index("QQQ"), names.index("SMH")
        vr = voo.pct_change().reindex(dates_all).fillna(0.0).to_numpy()   # VOO (SPY-spliced) returns
        qqq, smh = R[Ev:, iq], R[Ev:, ism]
        voo_r = vr[Ev:]
        meta[lname] = {"tickers": names, "common_first": str(dates_all[0].date()),
                       "start_S": str(dates_all[S].date()), "eval_start": str(dates[0].date()),
                       "eval_end": str(dates[-1].date()), "n_sessions": int(len(dates))}
        ew = {H: E.equal_weight_bench(R, Ev, H) for H in HS}
        # benchmark rows
        bsets = {"QQQ": qqq, "SMH": smh, "VOO": voo_r, "EW_H63": ew[63], "EW_H126": ew[126]}
        for bn, br in bsets.items():
            for wn, (a, b) in {"FULL": (str(dates[0].date()), D.END_DATE), **WINDOWS}.items():
                m = seg(dates, a, b)
                if m.sum() < 20:
                    continue
                st = stats(br[m])
                benchs.append({"list": lname, "name": bn, "window": wn, "start": str(dates[m][0].date()),
                               "end": str(dates[m][-1].date()), "sessions": int(m.sum()), **st,
                               "sharpe_noRf": float(br[m].mean() / br[m].std(ddof=1) * np.sqrt(252))})
        # null draws for L-independent forms
        null_cache = {}
        rng_id = 0
        for H in HS:
            for form in ("keep", "cull"):
                rng_id += 1
                rng = np.random.default_rng(SEED + 1000 * (lname == "G7") + 10 * rng_id)
                nb = E.null_blend(R, S, H, form, rng, N_NULL, n, T)
                null_cache[(H, form)] = E.cagr_many(nb[:, Ev:])
        for li, (lbn, (L, skip)) in enumerate(E.LOOKBACKS.items()):
            for H in HS:
                for fi, form in enumerate(E.FORMS):
                    cid = f"{lname}_{lbn}_H{H}_{form}"
                    res = E.run_tranches(P, S, H, L, skip, form)
                    assert res["first_live"] + 1 <= Ev
                    r = res["blend"][Ev:]
                    tr = res["tranche_rets"][:, Ev:]
                    r20 = E.run_tranches(P, S, H, L, skip, form, COST20)["blend"][Ev:]
                    # null
                    if form == "stay":
                        sw = [int(sum(f)) for f in res["switch_flags"]]
                        rng = np.random.default_rng(SEED + 100000 + 1000 * (lname == "G7") + 100 * li + 10 * HS.index(H))
                        nb = E.null_blend(R, S, H, "stay", rng, N_NULL, n, T, switches=sw)
                        nc = E.cagr_many(nb[:, Ev:])
                    else:
                        nc = null_cache[(H, form)]
                    sc = E.cagr(r)
                    nge = int((nc >= sc).sum())
                    p = (1 + nge) / (N_NULL + 1)
                    # switches per year (trade session within evaluation period)
                    yrs = len(r) / 252
                    spy = []
                    for tidx, fl in zip(res["trade_idx"], res["switch_flags"]):
                        cnt = sum(1 for t, f in zip(tidx[1:], fl) if f and t >= Ev)
                        spy.append(cnt / yrs)
                    smh_share = float(res["blend_w"][Ev:, ism].mean())
                    tcag = [E.cagr(x) for x in tr]
                    full = stats(r)
                    b_q, b_s, b_e = stats(qqq), stats(smh), stats(ew[H])
                    row = {"cell": cid, "list": lname, "lookback": lbn, "H": H, "form": form,
                           "n_tranches": H // 21, "start": str(dates[0].date()), "end": str(dates[-1].date()),
                           "cagr": full["cagr"], "mdd": full["mdd"], "vol": full["vol"],
                           "qqq_cagr": b_q["cagr"], "smh_cagr": b_s["cagr"], "ew_cagr": b_e["cagr"],
                           "ex_qqq": full["cagr"] - b_q["cagr"], "ex_smh": full["cagr"] - b_s["cagr"],
                           "ex_ew": full["cagr"] - b_e["cagr"], "qqq_mdd": b_q["mdd"],
                           "mdd_minus_qqq": full["mdd"] - b_q["mdd"],
                           "ir_vs_qqq": ir_vs(r, qqq, dates), "cagr_cost20bp": E.cagr(r20),
                           "switches_per_year": float(np.mean(spy)), "smh_time_share": smh_share,
                           "tranche_cagr_min": min(tcag), "tranche_cagr_max": max(tcag),
                           "null_mean": float(nc.mean()), "null_p": p}
                    # windows
                    wex = []
                    for wn, (a, b) in WINDOWS.items():
                        m = seg(dates, a, b)
                        if m.sum() < 20:
                            continue
                        c_s, c_q = E.cagr(r[m]), E.cagr(qqq[m])
                        wins.append({"cell": cid, "list": lname, "window": wn, "start": str(dates[m][0].date()),
                                     "end": str(dates[m][-1].date()), "sessions": int(m.sum()),
                                     "cagr": c_s, "mdd": E.mdd(r[m]), "qqq_cagr": c_q, "smh_cagr": E.cagr(smh[m]),
                                     "ew_cagr": E.cagr(ew[H][m]), "ex_qqq": c_s - c_q,
                                     "ex_smh": c_s - E.cagr(smh[m]), "ex_ew": c_s - E.cagr(ew[H][m])})
                        wex.append(c_s - c_q)
                    row["min_window_ex_qqq"] = min(wex)
                    # last 18 months
                    m = seg(dates, *LAST18)
                    cum = lambda x: float(np.prod(1 + x[m]) - 1)
                    row.update({"l18_ret": cum(r), "l18_qqq": cum(qqq), "l18_smh": cum(smh), "l18_ew": cum(ew[H]),
                                "l18_ex_qqq": cum(r) - cum(qqq)})
                    cells.append(row)
                    nulls.append({"cell": cid, "strategy_cagr": sc, "null_mean": float(nc.mean()),
                                  "null_median": float(np.median(nc)), "null_p05": float(np.percentile(nc, 5)),
                                  "null_p95": float(np.percentile(nc, 95)), "draws_ge_strategy": nge,
                                  "p": p, "ew_cagr": b_e["cagr"], "null_mean_minus_ew": float(nc.mean() - b_e["cagr"]),
                                  "n_draws": N_NULL, "stay_switches_per_tranche": (sw if form == "stay" else "")})
                    # yearly
                    ys = pd.DataFrame({"s": r, "q": qqq, "m": smh, "v": voo_r, "e": ew[H]}, index=dates)
                    yy = (1 + ys).groupby(ys.index.year).prod() - 1
                    for yr, rw in yy.iterrows():
                        yearly.append({"cell": cid, "year": int(yr), "strategy": rw["s"], "QQQ": rw["q"],
                                       "SMH": rw["m"], "VOO": rw["v"], "EW": rw["e"],
                                       "beats_QQQ": bool(rw["s"] > rw["q"]), "beats_EW": bool(rw["s"] > rw["e"])})
    cdf = pd.DataFrame(cells)
    cdf["bh_q"] = E.bh_adjust(cdf["null_p"].to_numpy())
    fails = []
    for _, x in cdf.iterrows():
        f = []
        if not (x.ex_qqq > 0 and x.ex_ew > 0):
            f.append("1_cagr_vs_qqq_and_ew")
        if not (x.min_window_ex_qqq >= -0.005):
            f.append("2_window_lag_over_0.5pp")
        if not (x.ir_vs_qqq >= 0.30):
            f.append("3_ir_vs_qqq_ge_0.30")
        if not (x.bh_q < 0.10):
            f.append("4_bh_q_lt_0.10")
        if not (x.cagr_cost20bp > x.qqq_cagr):
            f.append("5_cost20bp_beats_qqq")
        if not (x.mdd_minus_qqq >= -0.05):
            f.append("6_mdd_over_5pp_deeper")
        fails.append(f)
    cdf["failing_lines"] = [";".join(f) for f in fails]
    cdf["pass"] = [len(f) == 0 for f in fails]
    cdf.to_csv(os.path.join(D.OUT_DIR, "cells.csv"), index=False)
    pd.DataFrame(benchs).to_csv(os.path.join(D.OUT_DIR, "benchmarks.csv"), index=False)
    pd.DataFrame(wins).to_csv(os.path.join(D.OUT_DIR, "windows.csv"), index=False)
    ndf = pd.DataFrame(nulls)
    ndf["bh_q"] = cdf["bh_q"].to_numpy()
    ndf.to_csv(os.path.join(D.OUT_DIR, "null.csv"), index=False)
    pd.DataFrame(yearly).to_csv(os.path.join(D.OUT_DIR, "yearly.csv"), index=False)
    verdict = {"meta": meta, "n_cells": len(cdf), "nominated": cdf.loc[cdf["pass"], "cell"].tolist(),
               "cells": {x.cell: {"pass": bool(x["pass"]), "failing_lines": x.failing_lines.split(";") if x.failing_lines else [],
                                  "null_p": x.null_p, "bh_q": x.bh_q} for _, x in cdf.iterrows()}}
    with open(os.path.join(D.OUT_DIR, "verdict.json"), "w") as fh:
        json.dump(verdict, fh, ensure_ascii=False, indent=1, default=str)
    print(cdf[["cell", "cagr", "ex_qqq", "ex_smh", "ex_ew", "mdd", "null_p", "bh_q", "pass", "failing_lines"]].to_string())
    print(json.dumps(meta, indent=1, default=str))


if __name__ == "__main__":
    main()
