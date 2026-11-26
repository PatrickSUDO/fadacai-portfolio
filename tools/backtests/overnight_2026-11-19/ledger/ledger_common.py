"""第二組 PF（帳本與持有期規則）：共用的載入、價格簿、拆股驗證、先進先出配對。

預註冊：research/overnight-study-2026-11-19.md 的「第二組 PF」（凍結；診斷、沒有及格線）。

隱私：本檔不含任何帳戶資料、成交、代號清單。拆股倍數是在執行時由價格資料推定的，
不寫死在程式裡。所有由帳本衍生的輸出只寫在 gitignore 的
tools/backtests/data/overnight_2026-11-19/ledger/ 之下。

日期規則：PF 用到帳本，所以價格用到資料終點（預註冊：「帳本用到最後一筆成交」）。
唯一的例外是 ranker 的 silver 價格：一律在讀檔時就只取 2025-12-31 以前的列。
不連網、不寫任何快取、不呼叫專案內會抓資料或寫檔的函式。
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[4]
DATA = REPO / "tools" / "backtests" / "data"
OUT = DATA / "overnight_2026-11-19" / "ledger"

LEDGER = REPO / "research" / "trade-ledger.jsonl"
JOURNAL_DIR = REPO / "journal"
ROSTER_JSON = REPO / "research" / "roster.json"
POSITION_STATE = REPO / "research" / "position-state.json"

# 價格來源：沿用 2026-11-18 研究（horizon_sweep_2026-11-18/own_buys.py）的來源與優先序
ROSTER_CSV = DATA / "weak_flag_px_2026-11-10.csv"
IDX_PKL = DATA / "trend_switch_ema_macd_2026-11-16.px.pkl"
LEV_PKL = DATA / "trend_switch_ema_macd_2026-11-16.lev2x.px.pkl"
EOD_JSON = REPO / "briefing-out" / "cache" / "eod-prices.json"
SILVER_PARQUET = Path("/Users/supatrick/laptop/project/fadacai-ranker/data/silver/"
                      "prices_adjusted/prices.parquet")
SILVER_END = "2025-12-31"          # silver 價格讀檔時就截到這一天
CAL_START = "2023-01-01"

# 凍結的研究參數（全部來自預註冊或規則檔，不掃描）
N_LIST = [21, 63, 126]             # PF-2 的最短持有交易日數
H_LIST = [63, 126]                 # PF-3 的固定持有交易日數
ALTS = ["SPY", "SMH", "CASH"]      # 提早賣掉拿回的錢改放哪裡
HURDLE_BENCH = ["SMH", "QQQ"]      # PF-3 的基準
STOP_LEVEL = 0.75                  # 硬停損：收盤 ÷ 成本 <= 0.75（自成本跌 25%）
R14_EFFECTIVE = "2026-07-29"       # R14 生效日
R14_DAYS = 30                      # 與 tools/position_guard.py 的 R14_DAYS 相同（持有天數 < 30 = 鎖）
R35_EFFECTIVE = "2026-10-20"       # R35 採用日
N_BOOT = 10_000
SEED = 20261119

SPLIT_CANDIDATES = [2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 50]


# ── ledger ────────────────────────────────────────────────────────────────
def load_ledger(path: Path | None = None) -> list[dict]:
    """股票／ETF 成交（排除選擇權與 origin_evidence 以 VOID 開頭的列）。
    依（日期、成交時間）穩定排序，其餘維持檔案順序；每列加上 `row`（排序後的序號）。"""
    path = LEDGER if path is None else path
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    n_all = len(rows)
    n_void = sum(1 for r in rows if str(r.get("origin_evidence") or "").startswith("VOID"))
    n_opt = sum(1 for r in rows if r.get("is_option"))
    rows = [r for r in rows
            if not r.get("is_option")
            and not str(r.get("origin_evidence") or "").startswith("VOID")]
    rows = sorted(rows, key=lambda f: (f.get("date", ""), f.get("exec_time") or ""))
    for i, r in enumerate(rows):
        r["row"] = i
        if not isinstance(r.get("origin"), str):
            r["origin"] = "unknown"
    load_ledger.info = {"n_rows_in_file": n_all, "n_void_rows": n_void, "n_option_rows": n_opt,
                        "n_stock_etf_rows_used": len(rows)}
    return rows


# ── price sources ─────────────────────────────────────────────────────────
def load_frames() -> dict[str, pd.DataFrame]:
    """還原收盤價的寬表，依優先序：weak_flag_px -> pkl stk -> pkl idx -> pkl lev2x。"""
    with open(IDX_PKL, "rb") as fh:
        pk = pickle.load(fh)
    with open(LEV_PKL, "rb") as fh:
        lev = pickle.load(fh)
    idx = pk["idx"].sort_index()
    return {
        "weak_flag_px": pd.read_csv(ROSTER_CSV, index_col=0, parse_dates=True).sort_index(),
        "pkl_stk": pk["stk"].sort_index(),
        "pkl_idx": idx[[c for c in idx.columns if not c.startswith("^")]],
        "pkl_lev2x": lev.sort_index(),
    }


def load_eod_ranked(path: Path | None = None) -> dict[str, list[tuple[str, pd.Series]]]:
    """eod-prices.json：每個代號的各把 key 依（筆數多、終點新）排序。
    不同 key 是不同日期抓的、還原基準可能不同，所以絕不拼接：一筆報酬只用同一把 key。"""
    path = EOD_JSON if path is None else path
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


def load_silver(symbols) -> pd.DataFrame:
    """ranker silver 日線（date, symbol, close, adjusted_close），讀檔時就截到 2025-12-31。"""
    import pyarrow.compute as pc
    import pyarrow.dataset as ds

    cand = set()
    for s in symbols:
        cand |= {s, s.replace(".", "-"), s.replace(".", "")}
    table = ds.dataset(str(SILVER_PARQUET)).to_table(
        columns=["date", "symbol", "close", "adjusted_close"],
        filter=(pc.field("symbol").isin(sorted(cand)))
        & (pc.field("date") <= SILVER_END) & (pc.field("date") >= CAL_START))
    df = table.to_pandas()
    df["date"] = pd.to_datetime(df["date"])
    assert df.empty or df["date"].max() <= pd.Timestamp(SILVER_END)
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)


def silver_lookup(silver: pd.DataFrame, symbol: str) -> pd.DataFrame:
    for cand in (symbol, symbol.replace(".", "-"), symbol.replace(".", "")):
        g = silver[silver.symbol == cand]
        if len(g):
            return g
    return silver.iloc[0:0]


def build_calendar(frames: dict, last_ledger_date: str) -> tuple[pd.DatetimeIndex, int]:
    """交易日曆 = SPY 有價格的日子；之後到帳本最後一筆成交之間補上平日（只用來數交易日，
    那幾天沒有價格）。回傳（日曆, 最後一個有 SPY 價格的位置）。"""
    spy = frames["pkl_idx"]["SPY"].dropna().loc[CAL_START:]
    cal = spy.index
    last_px = len(cal) - 1
    extra = pd.bdate_range(cal[-1] + pd.Timedelta(days=1), pd.Timestamp(last_ledger_date))
    if len(extra):
        cal = cal.append(extra)
    return cal, last_px


def build_price_book(symbols, cal: pd.DatetimeIndex, frames: dict, eod: dict,
                     silver: pd.DataFrame) -> dict[str, list[tuple[str, np.ndarray]]]:
    """symbol -> [(來源名, 對齊交易日曆的還原收盤價陣列)]，依優先序。
    weak_flag_px -> pkl stk -> pkl idx -> pkl lev2x -> eod（最長／最新的 key 在前）-> silver。"""
    book: dict[str, list] = {}
    for sym in symbols:
        lst = []
        for name, df in frames.items():
            if sym in df.columns:
                lst.append((name, df[sym].reindex(cal).to_numpy(dtype=float)))
        for key, s in eod_lookup(eod, sym):
            lst.append((f"eod:{key.split('|', 1)[1]}", s.reindex(cal).to_numpy(dtype=float)))
        g = silver_lookup(silver, sym)
        if len(g):
            s = pd.Series(g.adjusted_close.to_numpy(dtype=float), index=g.date.to_numpy())
            lst.append(("silver_adj", s.reindex(cal).to_numpy(dtype=float)))
        book[sym] = lst
    return book


def price_ratio(book_entry: list, i: int, j: int) -> tuple[float, str, np.ndarray | None]:
    """同一個來源內 i -> j 的還原價比值（j 的價 ÷ i 的價）。任一端缺價就換下一個來源。
    回傳（比值, 來源名, 該來源的整條陣列）；都不行回 (nan, '', None)。"""
    for name, arr in book_entry:
        if i < 0 or j >= len(arr) or i >= len(arr):
            continue
        a, b = arr[i], arr[j]
        if np.isfinite(a) and np.isfinite(b) and a > 0:
            return float(b / a), name, arr
    return np.nan, "", None


def first_price(book_entry: list, i: int) -> float:
    for _, arr in book_entry:
        if 0 <= i < len(arr) and np.isfinite(arr[i]):
            return float(arr[i])
    return np.nan


# ── split validation (price-implied) ──────────────────────────────────────
def implied_split_factor(raw_px: float, adj_close: float) -> tuple[float, bool]:
    """成交原始價 ÷ 當日還原收盤 -> 推定「成交之後才發生」的拆股倍數（反向拆股 < 1）。
    還原價含除息調整，所以比值只會偏高不會偏低；容許「比值 ÷ 倍數」落在 0.94～1.30。
    回傳 (倍數, 是否判得出來)。判不出來回 (1, False)。（與 2026-11-18 研究同一套寫法。）"""
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


def implied_split_factors(fills: list[dict], cal: pd.DatetimeIndex, book: dict) -> tuple[dict, dict]:
    """每一列成交的「一股等於現在幾股」倍數，由價格推定。{row: 倍數}。
    成交當天沒有價格或比值判不出來的列：沿用同一代號、日期最接近的已判定列的倍數；
    整個代號都判不出來就用 1。"""
    pos = {d: i for i, d in enumerate(cal)}
    resolved: dict[int, float] = {}
    pending: list[dict] = []
    n_no_price = n_unresolved = 0
    for f in fills:
        i = pos.get(pd.Timestamp(f["date"]))
        px = first_price(book.get(f["symbol"], []), i) if i is not None else np.nan
        k, ok = implied_split_factor(float(f["price"]), px)
        if ok:
            resolved[f["row"]] = k
        else:
            pending.append(f)
            if np.isfinite(px):
                n_unresolved += 1
            else:
                n_no_price += 1
    by_sym: dict[str, list] = {}
    for f in fills:
        if f["row"] in resolved:
            by_sym.setdefault(f["symbol"], []).append((pd.Timestamp(f["date"]), resolved[f["row"]]))
    out = dict(resolved)
    n_borrowed = n_default = 0
    for f in pending:
        cands = by_sym.get(f["symbol"], [])
        if cands:
            d = pd.Timestamp(f["date"])
            out[f["row"]] = min(cands, key=lambda c: abs((c[0] - d).days))[1]
            n_borrowed += 1
        else:
            out[f["row"]] = 1.0
            n_default += 1
    info = {"n_fills_without_price_on_fill_date": n_no_price,
            "n_fills_ratio_unresolved": n_unresolved,
            "n_fills_factor_borrowed_from_nearest_fill": n_borrowed,
            "n_fills_factor_defaulted_to_1": n_default}
    return out, info


def ledger_table_factor(trade_ledger_mod, f: dict) -> float:
    """專案 SPLITS 表給的倍數（對照用）。"""
    return float(trade_ledger_mod.split_adjust_qty(f["symbol"], f["date"], 1.0))


def silver_split_events(silver: pd.DataFrame, symbols, start: str) -> pd.DataFrame:
    """silver 的（原始收盤 ÷ 還原收盤）比值若單日跳動 > 40%，視為拆股事件（獨立證據，有確切日期）。
    只看 2025-12-31 以前；40% 的門檻避開除息與分拆造成的小階梯。"""
    recs = []
    for sym in symbols:
        g = silver_lookup(silver, sym)
        g = g[g.date >= pd.Timestamp(start)]
        if len(g) < 2:
            continue
        r = (g.close / g.adjusted_close).to_numpy(dtype=float)
        step = r[:-1] / r[1:]
        for i in np.where(np.abs(np.log(step)) > np.log(1.4))[0]:
            recs.append({"symbol": sym, "effective_date": str(g.date.iloc[i + 1].date()),
                         "ratio": float(round(step[i], 3))})
    return pd.DataFrame(recs, columns=["symbol", "effective_date", "ratio"])


def split_validation(fills: list[dict], factors: dict, trade_ledger_mod,
                     silver_events: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """逐代號比較：價格推定的倍數 vs 專案 SPLITS 表 vs silver 的拆股事件。"""
    rows = []
    by_sym: dict[str, list] = {}
    for f in fills:
        by_sym.setdefault(f["symbol"], []).append(f)
    table = getattr(trade_ledger_mod, "SPLITS", {})
    for sym, fs in sorted(by_sym.items()):
        imp = [factors[f["row"]] for f in fs]
        led = [ledger_table_factor(trade_ledger_mod, f) for f in fs]
        has_imp = any(abs(k - 1.0) > 1e-9 for k in imp)
        in_table = sym.upper() in table
        if not (has_imp or in_table):
            continue
        mism = [f for f, a, b in zip(fs, imp, led) if abs(a - b) > 1e-9]
        chg = [(fs[n - 1]["date"], fs[n]["date"]) for n in range(1, len(fs))
               if abs(imp[n] - imp[n - 1]) > 1e-9]
        ev = silver_events[silver_events.symbol == sym] if len(silver_events) else silver_events
        # silver 的事件是否落在「倍數改變」的兩筆成交之間
        confirmed = None
        if len(ev) and chg:
            confirmed = all(any(a < e <= b for a, b in chg) or not (fs[0]["date"] < e <= fs[-1]["date"])
                            for e in ev.effective_date)
        rows.append({
            "symbol": sym, "n_fills": len(fs),
            "in_ledger_split_table": in_table,
            "price_implied_factors_seen": "|".join(f"{k:g}" for k in sorted(set(imp), reverse=True)),
            "factor_changes_between_fills": "|".join(f"{a}..{b}" for a, b in chg),
            "fills_straddle_a_split": bool(chg),
            "n_fills_where_table_disagrees_with_price": len(mism),
            "silver_events": "|".join(f"{e}x{r:g}" for e, r in zip(ev.effective_date, ev.ratio))
            if len(ev) else "",
            "silver_event_dates_consistent_with_fills": confirmed,
        })
    df = pd.DataFrame(rows)
    info = {
        "n_symbols_with_price_implied_split": int(
            sum(1 for r in rows if r["price_implied_factors_seen"] not in ("1",))),
        "n_symbols_in_ledger_split_table": int(len(table)),
        "n_table_symbols_confirmed_by_price": int(
            sum(1 for r in rows if r["in_ledger_split_table"]
                and r["n_fills_where_table_disagrees_with_price"] == 0)),
        "n_symbols_missing_from_table": int(
            sum(1 for r in rows if not r["in_ledger_split_table"])),
        "n_missing_symbols_whose_fills_straddle_the_split": int(
            sum(1 for r in rows if not r["in_ledger_split_table"] and r["fills_straddle_a_split"])),
        "n_fills_where_table_disagrees_with_price": int(
            sum(r["n_fills_where_table_disagrees_with_price"] for r in rows)),
    }
    return df, info


# ── FIFO ──────────────────────────────────────────────────────────────────
PIECE_COLS = ["symbol", "buy_row", "sell_row", "buy_date", "sell_date", "qty", "cost", "proceeds",
              "pnl", "buy_origin", "sell_origin"]


def fifo_pieces(fills: list[dict], factor_of) -> tuple[pd.DataFrame, dict, dict]:
    """先進先出配對。amount 是含費用的真實現金流（買為負）。qty 先乘上拆股倍數，換成現在的股數。
    回傳（每一段配對, 統計, 尚未賣出的批次 {symbol: [[剩餘股數, 每股成本, 買進日, buy_row], ...]}）。"""
    lots: dict[str, list] = {}
    pieces = []
    n_unmatched = n_partial = 0
    unmatched_qty_notional = 0.0
    for f in fills:
        sym, d = f["symbol"], f["date"]
        q = abs(float(f["qty"])) * float(factor_of(f))
        if q == 0:
            continue
        amt = float(f.get("amount") or 0.0)
        if f["side"] == "BOUGHT":
            lots.setdefault(sym, []).append([q, -amt / q, d, f["row"], f["origin"]])
            continue
        remaining, queue, matched = q, lots.get(sym, []), 0.0
        while remaining > 1e-9 and queue:
            lot = queue[0]
            take = min(lot[0], remaining)
            cost = take * lot[1]
            proceeds = take * (amt / q)
            pieces.append({"symbol": sym, "buy_row": lot[3], "sell_row": f["row"],
                           "buy_date": lot[2], "sell_date": d, "qty": take, "cost": cost,
                           "proceeds": proceeds, "pnl": proceeds - cost,
                           "buy_origin": lot[4], "sell_origin": f["origin"]})
            lot[0] -= take
            remaining -= take
            matched += take
            if lot[0] <= 1e-9:
                queue.pop(0)
        if matched <= 1e-9:
            n_unmatched += 1
        elif remaining > 1e-6:
            n_partial += 1
        if remaining > 1e-6:
            unmatched_qty_notional += remaining * (amt / q)
    info = {"n_sells_fully_unmatched": n_unmatched, "n_sells_partially_unmatched": n_partial,
            "unmatched_sell_proceeds": round(unmatched_qty_notional, 2),
            "n_open_lots": int(sum(len(v) for v in lots.values()))}
    return pd.DataFrame(pieces, columns=PIECE_COLS), info, lots


# ── statistics ────────────────────────────────────────────────────────────
def cluster_boot_total(x, clusters, n_boot: int = N_BOOT, seed: int = SEED) -> tuple[float, float, int]:
    """按群（買進月份）整群重抽的 bootstrap 95% 區間，統計量是「總和」。回傳 (下界, 上界, 群數)。"""
    x = np.asarray(x, dtype=float)
    codes, uniq = pd.factorize(np.asarray(clusters))
    M = len(uniq)
    if M < 2:
        return np.nan, np.nan, M
    sx = np.bincount(codes, weights=x, minlength=M)
    draw = np.random.default_rng(seed).integers(0, M, size=(n_boot, M))
    tot = sx[draw].sum(axis=1)
    return float(np.quantile(tot, 0.025)), float(np.quantile(tot, 0.975)), M


def cluster_boot_mean(x, w, clusters, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """按群整群重抽的 bootstrap 95% 區間：等權平均與金額加權平均。"""
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


def write_json(path: Path, obj) -> None:
    def default(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if not np.isfinite(o) else float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, (pd.Timestamp,)):
            return str(o.date())
        return str(o)

    def clean(o):
        if isinstance(o, float) and not np.isfinite(o):
            return None
        if isinstance(o, dict):
            return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        return o

    path.write_text(json.dumps(clean(obj), ensure_ascii=False, indent=1, default=default),
                    encoding="utf-8")
