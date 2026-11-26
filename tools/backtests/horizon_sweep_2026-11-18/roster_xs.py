"""US-D：個股名單截面（順勢／反轉）× 持有週期。

預註冊：research/horizon-study-2026-11-18.md 的 US-D（凍結）。
名單 = weak_flag_px 的 83 檔個股（今天的觀察名單，有倖存者偏差，只看名單內相對差異）。
7 訊號 × 2 方向 × 7 個 H = 98 格；買 10 檔等權；t 收盤出訊號、t+1 收盤成交；
成本每邊 0／10（base）／20（壓力）bp；null = 同時程隨機選 10 檔 200 次（base 成本）。
窗：2014-01-02 → 2019-12-31、2020-01-02 → 2025-12-31、全期（2026 的列讀檔後即丟）。
及格線：兩窗都贏同名單等權、BH q < 0.10、20bp 下仍贏。

用法：python3 -B roster_xs.py
輸出：tools/backtests/data/horizon_sweep_2026-11-18/stocks/（gitignore）
      cells.csv / benchmarks.csv / horizon_summary.csv / horizon_by_direction.csv /
      null_dist.csv / daily_returns_base.csv / usd_part.json
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stk_common as C  # noqa: E402

BENCH_ALL = ["roster_ew"] + C.BENCH
NULL_CHUNK = 50
PASS_1 = "pass_1_beat_ew_both_windows_base"
PASS_2 = "pass_2_bh_q_lt_0.10"
PASS_3 = "pass_3_beat_ew_both_windows_20bp"


def cell_name(sig: str, direction: str, H: int) -> str:
    return f"{sig}|{direction}|H{H}"


def run() -> dict:
    t_start = time.time()
    C.OUT.mkdir(parents=True, exist_ok=True)
    px = C.load_roster()          # 2026 的列已在 loader 內丟掉
    idx = C.load_idx()
    assert px.index.max() <= C.END_DATE and idx.index.max() <= C.END_DATE
    stocks = px.drop(columns=C.NON_STOCK_COLS)
    assert stocks.shape[1] == 83, stocks.shape
    dates = stocks.index
    P = stocks.to_numpy(dtype=float)
    T, N = P.shape
    E = C.eligibility(P)
    n_elig = E.sum(axis=1)
    t0 = int(np.argmax(n_elig >= C.N_PICK_D))
    cash = C.cash_daily(idx, dates)

    # ── benchmarks ──
    bench_ret = {"roster_ew": C.roster_ew_returns(P, E)}
    for b in C.BENCH:
        s = idx[b].reindex(dates)
        assert s.notna().all(), b
        bench_ret[b] = s.pct_change().fillna(0.0).to_numpy()
    bench_m = {(b, w): C.window_metrics(dates, bench_ret[b], cash, a, z)
               for b in BENCH_ALL for w, (a, z) in C.WINDOWS_D.items()}
    bench_rows = []
    for b in BENCH_ALL:
        for w, (a, z) in C.WINDOWS_D.items():
            i0, i1 = C.window_slice(dates, a, z)
            row = {"study": "US-D", "benchmark": b, "window": w,
                   "window_start": str(dates[i0].date()), "window_end": str(dates[i1].date()),
                   **bench_m[(b, w)], "turnover_ann": 0.0, "cost_drag_ann": 0.0}
            for b2 in BENCH_ALL:
                row[f"excess_cagr_vs_{b2}"] = bench_m[(b, w)]["cagr"] - bench_m[(b2, w)]["cagr"]
                row[f"ir_vs_{b2}"] = (np.nan if b2 == b else C.info_ratio(
                    bench_ret[b][i0 + 1:i1 + 1], bench_ret[b2][i0 + 1:i1 + 1]))
            row["note"] = ("survivorship-biased (today's roster back-filled); relative comparator only"
                           if b == "roster_ew" else "context only")
            bench_rows.append(row)
    pd.DataFrame(bench_rows).to_csv(C.OUT / "benchmarks.csv", index=False)

    # ── cells ──
    sigs = {name: C.signal_matrix(P, L, skip) for name, L, skip in C.SIGNALS}
    # 診斷欄（不影響任何判定）：被選中的股票，其近 63 日波動在當日可選名單中的百分位。
    # 0.5 = 跟名單平均一樣；明顯高於 0.5 = 這個訊號其實在挑「波動大的股票」。
    r_d = np.full((T, N), np.nan)
    r_d[1:] = P[1:] / P[:-1] - 1.0
    vol = pd.DataFrame(r_d).rolling(63, min_periods=63).std().to_numpy()
    vol_pct = pd.DataFrame(np.where(E, vol, np.nan)).rank(axis=1, pct=True).to_numpy()
    pick_vol = {}
    for name, _L, _skip in C.SIGNALS:
        for direction in C.DIRECTIONS:
            picks = C.rank_picks(sigs[name], E, direction, C.N_PICK_D)
            pick_vol[(name, direction)] = float(np.mean(
                [np.nanmean(vol_pct[t, pk]) for t, pk in enumerate(picks)
                 if pk is not None and t >= t0]))
    rows = []
    daily = {}
    null_rows = []
    null_stats = {}
    for H in C.HORIZONS_D:
        for name, L, skip in C.SIGNALS:
            for direction in C.DIRECTIONS:
                g, tau, _ = C.run_signal_cell(P, sigs[name], E, direction, H, C.N_PICK_D, t0)
                gross = {}
                for cost in C.COSTS_D:
                    ret, to = C.combine(g, tau, cost)
                    ret, to = ret[:, 0], to[:, 0]
                    if cost == C.BASE_COST_D:
                        daily[cell_name(name, direction, H)] = ret
                    for w, (a, z) in C.WINDOWS_D.items():
                        i0, i1 = C.window_slice(dates, a, z)
                        m = C.window_metrics(dates, ret, cash, a, z)
                        if cost == 0:
                            gross[w] = m["cagr"]
                        row = {"study": "US-D", "universe": "roster83", "signal": name,
                               "direction": direction, "form": f"xs_top{C.N_PICK_D}_ew",
                               "L": L, "skip": skip, "H": H, "cost": cost, "window": w,
                               "cell": cell_name(name, direction, H), **m,
                               "pick_vol63_pctile_mean_info": pick_vol[(name, direction)],
                               "turnover_ann": to[i0 + 1:i1 + 1].sum() / (m["n_days"] / 252.0),
                               "cost_drag_ann": gross[w] - m["cagr"]}
                        for b in BENCH_ALL:
                            row[f"excess_cagr_vs_{b}"] = m["cagr"] - bench_m[(b, w)]["cagr"]
                            row[f"ir_vs_{b}"] = C.info_ratio(ret[i0 + 1:i1 + 1],
                                                             bench_ret[b][i0 + 1:i1 + 1])
                        rows.append(row)
        # ── null：同時程、同檔數；base 成本（判定用）＋ 零成本（僅供對照）──
        rng = np.random.default_rng(C.SEED + H)
        parts = {w: {"cagr": [], "sharpe": [], "cagr_gross": [], "turnover_ann": []}
                 for w in C.WINDOWS_D}
        for _ in range(C.N_NULL // NULL_CHUNK):
            fn = C.random_select_fn(E, C.N_PICK_D, NULL_CHUNK, rng)
            g, tau = C.simulate(P, fn, H, t0, NULL_CHUNK)
            ret, to = C.combine(g, tau, C.BASE_COST_D)
            ret0, _ = C.combine(g, tau, 0)
            for d in range(NULL_CHUNK):
                for w, (a, z) in C.WINDOWS_D.items():
                    i0, i1 = C.window_slice(dates, a, z)
                    m = C.window_metrics(dates, ret[:, d], None, a, z)
                    m0 = C.window_metrics(dates, ret0[:, d], None, a, z)
                    parts[w]["cagr"].append(m["cagr"])
                    parts[w]["sharpe"].append(m["sharpe"])
                    parts[w]["cagr_gross"].append(m0["cagr"])
                    parts[w]["turnover_ann"].append(
                        to[i0 + 1:i1 + 1, d].sum() / (m["n_days"] / 252.0))
            del g, tau, ret, ret0
        null_stats[H] = {w: {k: np.array(v) for k, v in d.items()} for w, d in parts.items()}
        for w in C.WINDOWS_D:
            for i in range(C.N_NULL):
                null_rows.append({"H": H, "window": w, "draw": i,
                                  **{k: null_stats[H][w][k][i] for k in parts[w]}})
        print(f"H={H:>3} done  ({time.time() - t_start:.1f}s)", flush=True)

    cells = pd.DataFrame(rows)
    pd.DataFrame(null_rows).to_csv(C.OUT / "null_dist.csv", index=False)

    # ── null p（全期、base 成本、CAGR；單尾）→ BH（98 格一個 family）──
    full = cells[cells.window == C.WFULL]
    base_full = full[full.cost == C.BASE_COST_D].set_index("cell")
    gross_full = full[full.cost == 0].set_index("cell")
    p, p_sh, p_gross = {}, {}, {}
    for c, r in base_full.iterrows():
        nc = null_stats[int(r.H)][C.WFULL]
        p[c] = (1 + int((nc["cagr"] >= r.cagr).sum())) / (C.N_NULL + 1)
        p_sh[c] = (1 + int((nc["sharpe"] >= r.sharpe).sum())) / (C.N_NULL + 1)
        p_gross[c] = (1 + int((nc["cagr_gross"] >= gross_full.loc[c, "cagr"]).sum())) / (C.N_NULL + 1)
    names = list(p)
    assert len(names) == 98
    q = dict(zip(names, C.bh_qvalues(np.array([p[c] for c in names]))))
    q_gross = dict(zip(names, C.bh_qvalues(np.array([p_gross[c] for c in names]))))

    piv = cells.pivot_table(index="cell", columns=["cost", "window"],
                            values="excess_cagr_vs_roster_ew")
    pass1 = (piv[(C.BASE_COST_D, C.W1)] > 0) & (piv[(C.BASE_COST_D, C.W2)] > 0)
    pass3 = (piv[(C.STRESS_COST_D, C.W1)] > 0) & (piv[(C.STRESS_COST_D, C.W2)] > 0)
    cells["null_p"] = cells.cell.map(p)
    cells["bh_q"] = cells.cell.map(q)
    cells["null_p_sharpe_info"] = cells.cell.map(p_sh)
    cells["null_p_gross_info"] = cells.cell.map(p_gross)
    cells["bh_q_gross_info"] = cells.cell.map(q_gross)
    cells[PASS_1] = cells.cell.map(pass1)
    cells[PASS_2] = cells.bh_q < 0.10
    cells[PASS_3] = cells.cell.map(pass3)
    cells["nominated"] = cells[PASS_1] & cells[PASS_2] & cells[PASS_3]
    cells.to_csv(C.OUT / "cells.csv", index=False)

    dd = pd.DataFrame(daily, index=dates)
    for b in BENCH_ALL:
        dd[f"bench_{b}"] = bench_ret[b]
    dd.round(8).to_csv(C.OUT / "daily_returns_base.csv")

    # ── horizon summary ──
    def summarise(df, keys):
        out = []
        for key, gdf in df.groupby(keys, sort=True):
            key = key if isinstance(key, tuple) else (key,)
            r = dict(zip(keys, key))
            r["n_cells"] = len(gdf)
            for col in ["cagr", "sharpe", "sharpe_ex", "mdd", "calmar"] + \
                       [f"excess_cagr_vs_{b}" for b in BENCH_ALL]:
                r[f"{col}_median"] = gdf[col].median()
                r[f"{col}_best"] = gdf[col].max()       # mdd：max = 回撤最淺
                r[f"{col}_worst"] = gdf[col].min()
            for b in BENCH_ALL:
                r[f"share_beating_{b}"] = float((gdf[f"excess_cagr_vs_{b}"] > 0).mean())
            r["share_sharpe_above_roster_ew"] = float(
                (gdf.sharpe > bench_m[("roster_ew", r["window"])]["sharpe"]).mean())
            r["share_calmar_above_roster_ew"] = float(
                (gdf.calmar > bench_m[("roster_ew", r["window"])]["calmar"]).mean())
            r["turnover_ann_median"] = gdf.turnover_ann.median()
            r["cost_drag_ann_median"] = gdf.cost_drag_ann.median()
            r["best_cell"] = gdf.loc[gdf.cagr.idxmax(), "cell"]          # 依 CAGR
            r["best_cell_by_sharpe"] = gdf.loc[gdf.sharpe.idxmax(), "cell"]
            r["best_cell_by_calmar"] = gdf.loc[gdf.calmar.idxmax(), "cell"]
            r["n_nominated"] = int(gdf.nominated.sum())
            H = int(r["H"])
            ns = null_stats[H][r["window"]]
            if r["cost"] == C.BASE_COST_D:
                nc = ns["cagr"]
            elif r["cost"] == 0:
                nc = ns["cagr_gross"]
            else:
                nc = None
            if nc is not None:
                r["null_cagr_median"] = float(np.median(nc))
                r["null_cagr_p05"] = float(np.quantile(nc, 0.05))
                r["null_cagr_p95"] = float(np.quantile(nc, 0.95))
                r["null_turnover_ann_median"] = float(np.median(ns["turnover_ann"]))
            out.append(r)
        return pd.DataFrame(out)

    hs = summarise(cells, ["H", "window", "cost"])
    hs.insert(0, "study", "US-D")
    hs.to_csv(C.OUT / "horizon_summary.csv", index=False)
    hd = summarise(cells, ["H", "direction", "window", "cost"])
    hd.insert(0, "study", "US-D")
    hd.to_csv(C.OUT / "horizon_by_direction.csv", index=False)

    # ── part json ──
    cell_level = cells.drop_duplicates("cell").set_index("cell")
    nominated = sorted(cell_level.index[cell_level.nominated])
    bf = cells[(cells.cost == C.BASE_COST_D) & (cells.window == C.WFULL)]
    keep = ["cell", "cagr", "sharpe", "mdd", "calmar", "excess_cagr_vs_roster_ew",
            "ir_vs_roster_ew", "turnover_ann", "cost_drag_ann", "null_p", "bh_q",
            "null_p_gross_info", "bh_q_gross_info"]
    top = bf.sort_values("excess_cagr_vs_roster_ew", ascending=False).head(5)
    nom_rows = bf[bf.nominated].sort_values("excess_cagr_vs_roster_ew", ascending=False)
    hs_base_full = hs[(hs.cost == C.BASE_COST_D) & (hs.window == C.WFULL)]
    hd_base_full = hd[(hd.cost == C.BASE_COST_D) & (hd.window == C.WFULL)]
    i0f, i1f = C.window_slice(dates, *C.WINDOWS_D[C.WFULL])
    part = {
        "study": "US-D",
        "n_cells": 98,
        "n_rows_cells_csv": int(len(cells)),
        "data": {"first_date": str(dates[0].date()), "last_date": str(dates[-1].date()),
                 "n_dates": int(T), "n_stocks": int(N),
                 "sim_first_signal_date": str(dates[t0].date()),
                 "sim_first_trade_date": str(dates[t0 + 1].date()),
                 "sim_first_return_date": str(dates[t0 + 2].date()),
                 "n_eligible_at_start": int(n_elig[t0]), "n_eligible_at_end": int(n_elig[-1]),
                 "n_never_eligible_before_end": int((~E.any(axis=0)).sum()),
                 "max_date_used": str(dates.max().date())},
        "counts": {
            PASS_1: int(cell_level[PASS_1].sum()),
            PASS_2: int(cell_level[PASS_2].sum()),
            PASS_3: int(cell_level[PASS_3].sum()),
            "nominated": len(nominated),
            "nominated_momentum": int(sum("|momentum|" in c for c in nominated)),
            "nominated_reversal": int(sum("|reversal|" in c for c in nominated)),
            "nominated_and_gross_null_q_lt_0.10_info": int(
                (cell_level.nominated & (cell_level.bh_q_gross_info < 0.10)).sum()),
            "min_null_p": float(cell_level.null_p.min()),
            "min_bh_q": float(cell_level.bh_q.min()),
            "n_null_p_le_0.05": int((cell_level.null_p <= 0.05).sum()),
            "n_null_p_gross_le_0.05_info": int((cell_level.null_p_gross_info <= 0.05).sum()),
            "n_bh_q_gross_lt_0.10_info": int((cell_level.bh_q_gross_info < 0.10).sum()),
            "beat_ew_full_base": int((bf.excess_cagr_vs_roster_ew > 0).sum()),
            "beat_ew_full_base_momentum": int(
                ((bf.excess_cagr_vs_roster_ew > 0) & (bf.direction == "momentum")).sum()),
            "beat_ew_full_base_reversal": int(
                ((bf.excess_cagr_vs_roster_ew > 0) & (bf.direction == "reversal")).sum()),
            "sharpe_above_ew_full_base": int(
                (bf.sharpe > bench_m[("roster_ew", C.WFULL)]["sharpe"]).sum()),
            "calmar_above_ew_full_base": int(
                (bf.calmar > bench_m[("roster_ew", C.WFULL)]["calmar"]).sum()),
            "mdd_shallower_than_ew_full_base": int(
                (bf.mdd > bench_m[("roster_ew", C.WFULL)]["mdd"]).sum()),
        },
        "nominated_cells": nominated,
        "nominated_detail_full_base": nom_rows[keep].to_dict("records"),
        "top5_full_base_by_excess_vs_roster_ew": top[keep].to_dict("records"),
        "horizon_summary_full_base": hs_base_full.to_dict("records"),
        "horizon_summary_compact": hs[[
            "H", "window", "cost", "n_cells", "cagr_median", "sharpe_median", "mdd_median",
            "calmar_median", "excess_cagr_vs_roster_ew_median", "share_beating_roster_ew",
            "share_beating_SPY", "share_beating_QQQ", "share_beating_SMH",
            "turnover_ann_median", "cost_drag_ann_median", "best_cell"]].to_dict("records"),
        "pick_vol63_pctile_mean_info": {f"{k[0]}|{k[1]}": v for k, v in pick_vol.items()},
        "horizon_by_direction_full_base": hd_base_full.to_dict("records"),
        "null_full": {str(H): {
            "base_cagr_median": float(np.median(null_stats[H][C.WFULL]["cagr"])),
            "base_cagr_p05": float(np.quantile(null_stats[H][C.WFULL]["cagr"], 0.05)),
            "base_cagr_p95": float(np.quantile(null_stats[H][C.WFULL]["cagr"], 0.95)),
            "gross_cagr_median": float(np.median(null_stats[H][C.WFULL]["cagr_gross"])),
            "turnover_ann_median": float(np.median(null_stats[H][C.WFULL]["turnover_ann"])),
        } for H in C.HORIZONS_D},
        "benchmarks": {f"{b}|{w}": bench_m[(b, w)] for b in BENCH_ALL for w in C.WINDOWS_D},
        "sanity_anchors": {
            "SPY_cagr_2014-01-02_2019-12-31": bench_m[("SPY", C.W1)]["cagr"],
            "SPY_cagr_expected_range": "roughly 0.11-0.12",
            "SPY_cagr_same_window_from_roster_csv": float(
                (px["SPY"].loc["2019-12-31"] / px["SPY"].loc["2014-01-02"]) ** (
                    365.25 / (pd.Timestamp("2019-12-31") - pd.Timestamp("2014-01-02")).days) - 1),
            "roster_ew_cagr_full": bench_m[("roster_ew", C.WFULL)]["cagr"],
            "roster_ew_cagr_W1": bench_m[("roster_ew", C.W1)]["cagr"],
            "roster_ew_cagr_W2": bench_m[("roster_ew", C.W2)]["cagr"],
            "SPY_cagr_full": bench_m[("SPY", C.WFULL)]["cagr"],
            "QQQ_cagr_full": bench_m[("QQQ", C.WFULL)]["cagr"],
            "SMH_cagr_full": bench_m[("SMH", C.WFULL)]["cagr"],
            "roster_ew_minus_SPY_full": bench_m[("roster_ew", C.WFULL)]["cagr"]
            - bench_m[("SPY", C.WFULL)]["cagr"],
            "roster_ew_label": "survivorship-biased: today's watch-list back-filled to 2013",
            "uninvested_return_days_in_full_window": int(
                (np.abs(bench_ret["roster_ew"][i0f + 1:i1f + 1]) == 0).sum()),
        },
        "runtime_sec": round(time.time() - t_start, 1),
    }
    C.write_json(C.OUT / "usd_part.json", part)
    return part


if __name__ == "__main__":
    part = run()
    print({k: part[k] for k in ("counts", "nominated_cells", "sanity_anchors", "runtime_sec")})
    try:
        C.finalize()          # 兩段的 part json 都在才會寫 verdict.json / summary.md
    except (KeyError, AttributeError) as exc:
        print(f"finalize skipped (the other part's json is from an older run; rerun it): {exc!r}")
