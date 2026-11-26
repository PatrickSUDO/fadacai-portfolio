"""US-E：自己的買點，如果固定抱 H 日（診斷，不是回測；沒有及格線）。

預註冊：research/horizon-study-2026-11-18.md 的 US-E（凍結）。
取帳本裡每一筆股票／ETF 買進（排除選擇權與 origin_evidence 以 VOID 開頭的列），
進場價 = 買進日收盤（還原價），看固定抱 H ∈ {5,10,21,63,126,252} 個交易日的報酬，
減去同期間 SPY／QQQ／SMH 的報酬。價格不足以覆蓋 H 日的買進，該 H 不計並報告筆數。
另附「已實現損益按實際持有天數分桶」的 FIFO 重算表——那張表是內生的（先看結果才決定
抱多久），只當對照。

隱私：本檔不含任何帳戶資料。所有由帳本衍生的輸出只寫在 gitignore 的
tools/backtests/data/horizon_sweep_2026-11-18/stocks/ 之下。
這一段是對帳本的診斷，是「回測到 2025-12-31」規則的唯一例外：會用到 2026 的價格。
不連網、不寫任何快取、不呼叫專案內會抓資料的函式（只借用 split_adjust_qty 這個純函式）。

用法：python3 -B own_buys.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stk_common as C  # noqa: E402

N_BOOT = 2000
BUCKETS = [("<7d", 0, 7), ("7-29d", 7, 30), ("30-90d", 30, 91),
           ("91-364d", 91, 365), (">=365d", 365, 10 ** 9)]
ENDOGENOUS_NOTE = ("ENDOGENOUS reference only: the holding period was chosen after seeing the "
                   "outcome (losers are cut fast), so this is not a horizon test")


# ── ledger ────────────────────────────────────────────────────────────────
def load_ledger(path: Path | None = None) -> list[dict]:
    """全部成交列，排除 origin_evidence 以 VOID 開頭者。維持檔案順序。"""
    path = C.LEDGER if path is None else path
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return [r for r in rows if not str(r.get("origin_evidence") or "").startswith("VOID")]


def stock_buys(fills: list[dict]) -> pd.DataFrame:
    rows = [f for f in fills if f["side"] == "BOUGHT" and not f.get("is_option")]
    df = pd.DataFrame({
        "date": pd.to_datetime([f["date"] for f in rows]),
        "symbol": [f["symbol"] for f in rows],
        "notional": [float(f["notional"]) for f in rows],
        "fill_px_split_adj": [float(f["split_adj_price"]) for f in rows],
        "origin": [f.get("origin") if isinstance(f.get("origin"), str) else "unknown" for f in rows],
    })
    df["month"] = df.date.dt.strftime("%Y-%m")
    df["year"] = df.date.dt.year.astype(str)
    return df.reset_index(drop=True)


# ── price book ────────────────────────────────────────────────────────────
def load_eod_ranked(path: Path | None = None) -> dict[str, list[tuple[str, pd.Series]]]:
    """eod-prices.json：每個代號的各把 key 依（筆數多、終點新）排序。
    不同 key 可能是不同日期抓的、還原基準不同，所以絕不拼接：一筆報酬只用同一把 key。"""
    path = C.EOD_JSON if path is None else path
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list] = {}
    for key, ser in raw.items():
        if not ser:
            continue
        sym = key.split("|")[0]
        s = pd.Series(ser, dtype=float)
        s.index = pd.to_datetime(s.index)
        out.setdefault(sym, []).append((key, s.sort_index()))
    for sym in out:
        out[sym].sort(key=lambda kv: (-len(kv[1]), -kv[1].index[-1].value))
    return out


def eod_lookup(eod: dict, symbol: str) -> list:
    for cand in (f"{symbol}.US", f"{symbol.replace('.', '-')}.US", f"{symbol.replace('.', '')}.US"):
        if cand in eod:
            return eod[cand]
    return []


def build_price_book(symbols, cal: pd.DatetimeIndex, frames: dict[str, pd.DataFrame],
                     eod: dict) -> dict[str, list[tuple[str, np.ndarray]]]:
    """symbol -> [(來源名, 對齊交易日曆的價格陣列)]，依優先序。
    優先序：weak_flag_px -> pkl stk -> pkl idx -> pkl lev2x -> eod（最長／最新的 key 在前）。"""
    book: dict[str, list] = {}
    for sym in symbols:
        lst = []
        for name, df in frames.items():
            if sym in df.columns:
                lst.append((name, df[sym].reindex(cal).to_numpy(dtype=float)))
        for key, s in eod_lookup(eod, sym):
            lst.append((f"eod:{key.split('|', 1)[1]}", s.reindex(cal).to_numpy(dtype=float)))
        book[sym] = lst
    return book


def fwd_return(arr: np.ndarray, i: int, H: int) -> float:
    """還原收盤 i -> i+H 的報酬；任一端缺價或超出範圍回 NaN。"""
    j = i + H
    if i < 0 or j >= len(arr):
        return np.nan
    a, b = arr[i], arr[j]
    if not (np.isfinite(a) and np.isfinite(b)) or a <= 0:
        return np.nan
    return float(b / a - 1.0)


def forward_table(buys: pd.DataFrame, cal: pd.DatetimeIndex, book: dict,
                  bench: dict[str, np.ndarray], horizons) -> pd.DataFrame:
    """每筆買進 × 每個 H 一列。status：ok / horizon_past_data_end / no_series_cover。"""
    pos = {d: i for i, d in enumerate(cal)}
    recs = []
    for fid, r in enumerate(buys.itertuples(index=False)):
        i = pos.get(r.date)
        for H in horizons:
            rec = {"fill": fid, "H": H, "ret": np.nan, "source": "", "alt_ret": np.nan,
                   "status": "ok"}
            if i is None:
                rec["status"] = "entry_date_not_a_session"
            elif i + H >= len(cal):
                rec["status"] = "horizon_past_data_end"
            else:
                got = []
                for name, arr in book.get(r.symbol, []):
                    v = fwd_return(arr, i, H)
                    if np.isfinite(v):
                        got.append((name, v))
                        if len(got) == 2:
                            break
                if not got:
                    rec["status"] = "no_series_cover"
                else:
                    rec["source"], rec["ret"] = got[0]
                    if len(got) > 1:
                        rec["alt_ret"] = got[1][1]
                    for b, arr in bench.items():
                        rec[f"bench_{b}"] = fwd_return(arr, i, H)
                        rec[f"ex_{b}"] = rec["ret"] - rec[f"bench_{b}"]
            recs.append(rec)
    out = pd.DataFrame(recs)
    return out.merge(buys.reset_index(names="fill"), on="fill", how="left")


# ── statistics ────────────────────────────────────────────────────────────
def cluster_boot_ci(x, w, clusters, n_boot: int = N_BOOT, seed: int = C.SEED) -> dict:
    """按群（買進月份）整群抽樣的 bootstrap 95% 區間：等權平均與金額加權平均。"""
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    codes, uniq = pd.factorize(np.asarray(clusters))
    M = len(uniq)
    nan = {"ew_lo": np.nan, "ew_hi": np.nan, "nw_lo": np.nan, "nw_hi": np.nan, "n_clusters": M}
    if M < 2:
        return nan
    n_m = np.bincount(codes, minlength=M).astype(float)
    sx = np.bincount(codes, weights=x, minlength=M)
    sw = np.bincount(codes, weights=w, minlength=M)
    swx = np.bincount(codes, weights=w * x, minlength=M)
    draw = np.random.default_rng(seed).integers(0, M, size=(n_boot, M))
    ew = sx[draw].sum(axis=1) / n_m[draw].sum(axis=1)
    nw = swx[draw].sum(axis=1) / sw[draw].sum(axis=1)
    return {"ew_lo": float(np.quantile(ew, 0.025)), "ew_hi": float(np.quantile(ew, 0.975)),
            "nw_lo": float(np.quantile(nw, 0.025)), "nw_hi": float(np.quantile(nw, 0.975)),
            "n_clusters": M}


def annualise(mean_ret: float, H: int) -> float:
    return float((1.0 + mean_ret) ** (252.0 / H) - 1.0) if mean_ret > -1 else np.nan


def summarise(ft: pd.DataFrame, cut_type: str, cut_value: str, mask: pd.Series) -> list[dict]:
    rows = []
    sub_all = ft[mask]
    for H, gH in sub_all.groupby("H", sort=True):
        ok = gH[gH.status == "ok"]
        base = {"cut_type": cut_type, "cut_value": cut_value, "H": int(H),
                "n_buys_in_cut": int(len(gH)), "n_fills": int(len(ok)),
                "n_symbols": int(ok.symbol.nunique()), "n_months": int(ok.month.nunique()),
                "n_dropped": int(len(gH) - len(ok)),
                "n_dropped_horizon_past_data_end": int((gH.status == "horizon_past_data_end").sum()),
                "n_dropped_no_series_cover": int(
                    gH.status.isin(["no_series_cover", "entry_date_not_a_session"]).sum())}
        if len(ok) == 0:
            for b in C.BENCH:
                rows.append({**base, "benchmark": b})
            continue
        w = ok.notional.to_numpy()
        raw_ew = float(ok.ret.mean())
        raw_nw = float(np.average(ok.ret, weights=w))
        for b in C.BENCH:
            ex = ok[f"ex_{b}"].to_numpy()
            ew = float(ex.mean())
            nw = float(np.average(ex, weights=w))
            ci = cluster_boot_ci(ex, w, ok.month.to_numpy())
            rows.append({**base, "benchmark": b,
                         "raw_mean_ew": raw_ew, "raw_mean_nw": raw_nw,
                         "raw_ann_ew": annualise(raw_ew, H), "raw_ann_nw": annualise(raw_nw, H),
                         "bench_mean_ew": float(ok[f"bench_{b}"].mean()),
                         "bench_mean_nw": float(np.average(ok[f"bench_{b}"], weights=w)),
                         "excess_mean_ew": ew, "excess_ew_ci_lo": ci["ew_lo"],
                         "excess_ew_ci_hi": ci["ew_hi"],
                         "excess_mean_nw": nw, "excess_nw_ci_lo": ci["nw_lo"],
                         "excess_nw_ci_hi": ci["nw_hi"],
                         "excess_median": float(np.median(ex)),
                         "hit_rate": float((ex > 0).mean()),
                         "excess_per_day_bp_ew": ew / H * 1e4,
                         "excess_per_day_bp_nw": nw / H * 1e4})
    return rows


# ── FIFO realised P&L by actual holding period (endogenous reference) ─────
def fifo_pieces(fills: list[dict], split_qty_fn) -> tuple[pd.DataFrame, dict]:
    """股票／ETF 的 FIFO 配對。amount 是含費用的真實現金流（買為負）。
    回傳每一段配對（賣出日、買進日、持有日曆天、損益、成本）與未配對統計。"""
    rows = [f for f in fills if not f.get("is_option")]
    rows = sorted(rows, key=lambda f: (f.get("date", ""), f.get("exec_time") or ""))  # stable
    lots: dict[str, list] = {}
    pieces = []
    n_unmatched_sells = 0
    n_partially_unmatched = 0
    for f in rows:
        sym, d = f["symbol"], f["date"]
        q = abs(float(split_qty_fn(sym, d, f["qty"])))
        if q == 0:
            continue
        amt = float(f.get("amount") or 0.0)
        if f["side"] == "BOUGHT":
            lots.setdefault(sym, []).append([q, amt / q, d])
            continue
        remaining, queue, matched = q, lots.get(sym, []), 0.0
        while remaining > 1e-9 and queue:
            lot = queue[0]
            take = min(lot[0], remaining)
            cost = -take * lot[1]
            pieces.append({"sell_date": d, "buy_date": lot[2], "qty": take, "cost": cost,
                           "pnl": take * (amt / q) - cost,
                           "days": (pd.Timestamp(d) - pd.Timestamp(lot[2])).days})
            lot[0] -= take
            remaining -= take
            matched += take
            if lot[0] <= 1e-9:
                queue.pop(0)
        if matched <= 1e-9:
            n_unmatched_sells += 1
        elif remaining > 1e-6:
            n_partially_unmatched += 1
    info = {"n_stock_fills": len(rows), "n_unmatched_sells_skipped": n_unmatched_sells,
            "n_partially_unmatched_sells": n_partially_unmatched,
            "n_open_lots": int(sum(len(v) for v in lots.values()))}
    return pd.DataFrame(pieces, columns=["sell_date", "buy_date", "qty", "cost", "pnl", "days"]), info


SPLIT_CANDIDATES = [2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 50]


def implied_split_factor(raw_px: float, adj_close: float) -> tuple[float, bool]:
    """成交原始價 ÷ 當日還原收盤 -> 推定「成交之後才發生」的拆股倍數（反向拆股 < 1）。
    還原價含除息調整，所以比值只會偏高不會偏低；容許「比值 ÷ 倍數」落在 0.94～1.30。
    回傳 (倍數, 是否判得出來)。判不出來時回 1。只用於穩健性對照，不取代專案慣例。"""
    if not (np.isfinite(raw_px) and np.isfinite(adj_close)) or raw_px <= 0 or adj_close <= 0:
        return 1.0, False
    r = raw_px / adj_close
    if 0.77 <= r <= 1.5:
        return 1.0, True
    best, best_err = None, np.inf
    for k in SPLIT_CANDIDATES + [1.0 / c for c in SPLIT_CANDIDATES]:
        x = r / k
        if 0.94 <= x <= 1.30 and abs(np.log(x)) < best_err:
            best, best_err = k, abs(np.log(x))
    return (1.0, False) if best is None else (float(best), True)


def implied_split_map(fills: list[dict], cal: pd.DatetimeIndex, book: dict) -> tuple[dict, dict]:
    """{(symbol, date): 倍數}，由價格資料推定；附統計。"""
    pos = {str(d.date()): i for i, d in enumerate(cal)}
    out, n_unresolved, n_no_price, n_stale, syms = {}, 0, 0, 0, set()
    for f in fills:
        if f.get("is_option"):
            continue
        key = (f["symbol"], f["date"])
        i = pos.get(f["date"])
        px = np.nan
        if i is not None:
            px = next((a[i] for _, a in book.get(f["symbol"], []) if np.isfinite(a[i])), np.nan)
        k, ok = implied_split_factor(float(f["price"]), px)
        if not np.isfinite(px):
            n_no_price += 1
        elif not ok:
            n_unresolved += 1
        if k != 1.0:
            syms.add(f["symbol"])
            sap = f.get("split_adj_price")
            if sap and abs(float(sap) / float(f["price"]) - 1.0) < 0.01:
                n_stale += 1          # 帳本的 split_adj_price 欄沒有反映這次拆股
        out.setdefault(key, k)
    return out, {"n_fills_without_price": n_no_price, "n_fills_ratio_unresolved": n_unresolved,
                 "n_symbols_with_implied_split": len(syms),
                 "n_fills_where_ledger_split_adj_price_is_unadjusted": n_stale}


def bucket_table(pieces: pd.DataFrame) -> pd.DataFrame:
    out = []
    for name, lo, hi in BUCKETS:
        g = pieces[(pieces.days >= lo) & (pieces.days < hi)]
        cost = float(g.cost.sum())
        out.append({"holding_bucket_calendar_days": name, "n_matched_pieces": int(len(g)),
                    "realised_pnl": round(float(g.pnl.sum()), 2), "cost_basis": round(cost, 2),
                    "pnl_over_cost": float(g.pnl.sum() / cost) if cost > 0 else np.nan,
                    "share_pieces_profitable": float((g.pnl > 0).mean()) if len(g) else np.nan})
    cost = float(pieces.cost.sum())
    out.append({"holding_bucket_calendar_days": "TOTAL", "n_matched_pieces": int(len(pieces)),
                "realised_pnl": round(float(pieces.pnl.sum()), 2), "cost_basis": round(cost, 2),
                "pnl_over_cost": float(pieces.pnl.sum() / cost) if cost > 0 else np.nan,
                "share_pieces_profitable": float((pieces.pnl > 0).mean()) if len(pieces) else np.nan})
    df = pd.DataFrame(out)
    df["note"] = ENDOGENOUS_NOTE
    return df


# ── cross-checks ──────────────────────────────────────────────────────────
def crosscheck_levels(a: pd.Series, b: pd.Series) -> dict | None:
    """兩條序列重疊期間的差異：level = 原始比值偏離 1 的最大值；
    shape = 比值除以自身中位數後偏離 1 的最大值（排除單純還原基準不同）。"""
    j = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    if len(j) < 5:
        return None
    ratio = j.b / j.a
    return {"n_overlap": int(len(j)), "level_max_abs": float((ratio - 1).abs().max()),
            "shape_max_abs": float((ratio / ratio.median() - 1).abs().max())}


def run() -> dict:
    t_start = time.time()
    C.OUT.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(C.REPO / "tools"))
    import trade_ledger  # 只借用純函式與拆股表；不呼叫任何會抓資料或寫檔的函式
    split_adjust_qty = trade_ledger.split_adjust_qty

    fills = load_ledger()
    buys = stock_buys(fills)

    # US-E 是唯一允許用 2026 價格的段落
    idx = C.load_idx(allow_2026=True)
    frames = {"weak_flag_px": C.load_roster(allow_2026=True),
              "pkl_stk": C.load_stk_pkl(allow_2026=True),
              "pkl_idx": idx[[c for c in idx.columns if not c.startswith("^")]],
              "pkl_lev2x": C.load_lev(allow_2026=True)}
    eod = load_eod_ranked()
    cal = idx["SPY"].dropna().loc["2023-01-01":].index
    symbols = sorted(buys.symbol.unique())
    all_stock_syms = sorted({f["symbol"] for f in fills if not f.get("is_option")})
    book = build_price_book(all_stock_syms, cal, frames, eod)
    bench = {b: idx[b].reindex(cal).to_numpy(dtype=float) for b in C.BENCH}

    ft = forward_table(buys, cal, book, bench, C.HORIZONS_E)
    ft.to_csv(C.OUT / "own_buys_fills.csv", index=False)       # 含真實交易；僅 gitignore 路徑

    # ── summaries ──
    rows = summarise(ft, "all", "all", pd.Series(True, index=ft.index))
    for y in sorted(ft.year.unique()):
        rows += summarise(ft, "entry_year", y, ft.year == y)
    for o in ["system", "user", "unknown"]:
        rows += summarise(ft, "origin", o, ft.origin == o)
    # 對照用：固定同一批買進（該 H 有資料者），看不同 H 的差別是不是樣本組成造成的
    okp = ft.assign(ok=ft.status == "ok").pivot(index="fill", columns="H", values="ok")
    for Hm in (126, 252):
        ids = okp.index[okp[[h for h in C.HORIZONS_E if h <= Hm]].all(axis=1)]
        rows += summarise(ft, "matched_sample", f"fills_with_H{Hm}", ft.fill.isin(ids) & (ft.H <= Hm))
    summ = pd.DataFrame(rows)
    summ.insert(0, "study", "US-E")
    summ.to_csv(C.OUT / "own_buys_summary.csv", index=False)

    # ── FIFO reference table ──
    pieces, fifo_info = fifo_pieces(fills, split_adjust_qty)
    bt = bucket_table(pieces)
    bt.insert(0, "split_basis", "ledger_split_table (project convention; primary)")
    # 穩健性對照：拆股倍數改由價格資料推定（帳本的拆股表不一定完整）
    smap, smap_info = implied_split_map(fills, cal, book)
    pieces2, fifo_info2 = fifo_pieces(fills, lambda s, d, q: q * smap.get((s, d), 1.0))
    bt2 = bucket_table(pieces2)
    bt2.insert(0, "split_basis", "price_implied_splits (robustness check)")
    pd.concat([bt, bt2], ignore_index=True).to_csv(
        C.OUT / "realised_by_holding_bucket.csv", index=False)

    # ── cross-checks ──
    wf = frames["weak_flag_px"]
    xrows = []
    for sym in sorted(set(wf.columns) | set(frames["pkl_stk"].columns)):
        keys = eod_lookup(eod, sym)
        if sym in wf.columns and keys:
            r = crosscheck_levels(wf[sym], keys[0][1])
            if r:
                xrows.append({"symbol": sym, "pair": "weak_flag_px~eod_longest_key", **r})
        if sym in wf.columns and sym in frames["pkl_stk"].columns:
            r = crosscheck_levels(wf[sym], frames["pkl_stk"][sym])
            if r:
                xrows.append({"symbol": sym, "pair": "weak_flag_px~pkl_stk", **r})
    xc = pd.DataFrame(xrows)
    xc["traded"] = xc.symbol.isin(symbols)
    xc["flag_gt_2pct_level"] = xc.level_max_abs > 0.02
    xc["flag_gt_2pct_shape"] = xc.shape_max_abs > 0.02
    xc.to_csv(C.OUT / "price_crosscheck.csv", index=False)

    okft = ft[ft.status == "ok"]
    both = okft[okft.alt_ret.notna()]
    alt_diff = (both.ret - both.alt_ret).abs()
    pos = {d: i for i, d in enumerate(cal)}
    ratio = []
    for r in buys.itertuples(index=False):
        srcs = book.get(r.symbol, [])
        px0 = next((a[pos[r.date]] for _, a in srcs if np.isfinite(a[pos[r.date]])), np.nan) \
            if r.date in pos else np.nan
        ratio.append(r.fill_px_split_adj / px0 if np.isfinite(px0) and px0 > 0 else np.nan)
    ratio = pd.Series(ratio)

    def tab(cut_type, cut_value, cols):
        s = summ[(summ.cut_type == cut_type) & (summ.cut_value == cut_value)]
        return s[["H", "benchmark"] + cols].to_dict("records")

    key_cols = ["n_fills", "n_symbols", "n_months", "n_dropped", "bench_mean_ew", "raw_mean_ew", "raw_ann_ew",
                "raw_mean_nw", "raw_ann_nw", "excess_mean_ew", "excess_ew_ci_lo", "excess_ew_ci_hi",
                "excess_mean_nw", "excess_nw_ci_lo", "excess_nw_ci_hi", "excess_median",
                "hit_rate", "excess_per_day_bp_ew", "excess_per_day_bp_nw"]
    n_src = pd.Series({s: len(v) for s, v in book.items()})
    part = {
        "study": "US-E",
        "note": "diagnostic on the user's own ledger, not a backtest; no pass line; uses 2026 prices",
        "n_buys": int(len(buys)), "n_symbols": int(buys.symbol.nunique()),
        "n_entry_months": int(buys.month.nunique()),
        "first_buy": str(buys.date.min().date()), "last_buy": str(buys.date.max().date()),
        "price_calendar_end": str(cal[-1].date()),
        "buys_by_year": buys.year.value_counts().sort_index().to_dict(),
        "buys_by_origin": buys.origin.value_counts().to_dict(),
        "n_buys_with_missing_origin_counted_unknown": int(sum(
            1 for f in fills if f["side"] == "BOUGHT" and not f.get("is_option")
            and not isinstance(f.get("origin"), str))),
        "n_symbols_in_ledger_split_table": int(len(getattr(trade_ledger, "SPLITS", {}))),
        "n_symbols_without_any_series": int((n_src == 0).sum()),
        "coverage_by_H": {str(H): {
            "n_ok": int(((ft.H == H) & (ft.status == "ok")).sum()),
            "n_dropped_horizon_past_data_end": int(((ft.H == H) & (ft.status == "horizon_past_data_end")).sum()),
            "n_dropped_no_series_cover": int(((ft.H == H) & ft.status.isin(
                ["no_series_cover", "entry_date_not_a_session"])).sum()),
            "share_from_eod_cache": float((okft[okft.H == H].source.str.startswith("eod:")).mean())
            if (okft.H == H).any() else None,
        } for H in C.HORIZONS_E},
        "all": tab("all", "all", key_cols),
        "by_year": {y: tab("entry_year", y, ["n_fills", "excess_mean_ew", "excess_mean_nw", "hit_rate"])
                    for y in sorted(ft.year.unique())},
        "by_origin": {o: tab("origin", o, ["n_fills", "excess_mean_ew", "excess_ew_ci_lo",
                                           "excess_ew_ci_hi", "excess_mean_nw", "hit_rate"])
                      for o in ["system", "user", "unknown"]},
        "matched_sample": {f"fills_with_H{Hm}": tab("matched_sample", f"fills_with_H{Hm}",
                                                    ["n_fills", "excess_mean_ew", "excess_mean_nw",
                                                     "hit_rate", "excess_per_day_bp_ew"])
                           for Hm in (126, 252)},
        "fifo_reference": {"label": ENDOGENOUS_NOTE, **fifo_info,
                           "buckets": bt.drop(columns="note").to_dict("records"),
                           "robustness_price_implied_splits": {
                               **fifo_info2, **smap_info,
                               "buckets": bt2.drop(columns="note").to_dict("records")}},
        "crosschecks": {
            "n_pairs_checked": int(len(xc)),
            "n_weak_flag_vs_eod_checked": int((xc.pair == "weak_flag_px~eod_longest_key").sum()),
            "n_level_disagree_gt_2pct": int(xc.flag_gt_2pct_level.sum()),
            "n_shape_disagree_gt_2pct": int(xc.flag_gt_2pct_shape.sum()),
            "n_shape_disagree_gt_2pct_traded": int((xc.flag_gt_2pct_shape & xc.traded).sum()),
            "max_shape_disagreement": float(xc.shape_max_abs.max()),
            "fwd_returns_with_two_sources": int(len(both)),
            "fwd_return_abs_diff_between_sources_max": float(alt_diff.max()) if len(both) else None,
            "fwd_return_abs_diff_gt_2pp": int((alt_diff > 0.02).sum()),
            "fill_px_vs_entry_close_n": int(ratio.notna().sum()),
            "fill_px_vs_entry_close_median_ratio": float(ratio.median()),
            "fill_px_vs_entry_close_n_off_by_gt_15pct": int(((ratio - 1).abs() > 0.15).sum()),
        },
        "runtime_sec": round(time.time() - t_start, 1),
    }
    C.write_json(C.OUT / "use_part.json", part)
    return part


if __name__ == "__main__":
    part = run()
    print(json.dumps({k: part[k] for k in ("n_buys", "n_symbols", "coverage_by_H", "crosschecks",
                                           "runtime_sec")}, indent=1, default=str))
    try:
        C.finalize()          # 兩段的 part json 都在才會寫 verdict.json / summary.md
    except (KeyError, AttributeError) as exc:
        print(f"finalize skipped (the other part's json is from an older run; rerun it): {exc!r}")
