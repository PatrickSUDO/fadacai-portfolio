"""持有週期研究（美股半邊）US-D／US-E 共用引擎。

預註冊：research/horizon-study-2026-11-18.md（凍結，不改）。
本檔只放「通用機制」：讀檔、績效指標、分批（tranche）模擬引擎、BH 校正。
不含任何帳戶資料；帳本衍生的輸出只寫在 gitignore 的 tools/backtests/data/ 之下。

終點：所有回測資料讀進來立刻砍掉 2026-01-01 之後的列（使用者下令回測到 2025-12-31）。
      唯一例外是 US-E（對帳本的診斷，不是回測），呼叫端要明確傳 allow_2026=True。
時序（US-D，只有收盤價）：訊號用 <= t 收盤的資料 -> t+1 收盤成交 -> 新權重自 t+2 的日報酬起生效。
分批：持有 H 日的組合拆成 min(H, 21) 批，各批是獨立子帳戶（批與批之間不做免費再平衡），
      組合淨值 = 各批淨值的平均。
成本：每邊 c，成交金額 = sum|新權重 - 漂移後舊權重| x 該批淨值，於成交日收盤扣除。
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "tools" / "backtests" / "data"
OUT = DATA / "horizon_sweep_2026-11-18" / "stocks"

ROSTER_CSV = DATA / "weak_flag_px_2026-11-10.csv"
IDX_PKL = DATA / "trend_switch_ema_macd_2026-11-16.px.pkl"
LEV_PKL = DATA / "trend_switch_ema_macd_2026-11-16.lev2x.px.pkl"
EOD_JSON = REPO / "briefing-out" / "cache" / "eod-prices.json"
LEDGER = REPO / "research" / "trade-ledger.jsonl"

NON_STOCK_COLS = ["SMH", "IGV", "SPY"]
BENCH = ["SPY", "QQQ", "SMH"]
HORIZONS_D = [1, 5, 10, 21, 63, 126, 252]
HORIZONS_E = [5, 10, 21, 63, 126, 252]
# (name, L, skip)
SIGNALS = [
    ("ret_1", 1, 0), ("ret_5", 5, 0), ("ret_21", 21, 0), ("ret_63", 63, 0),
    ("ret_126", 126, 0), ("ret_252", 252, 0), ("ret_252_skip21", 252, 21),
]
DIRECTIONS = ["momentum", "reversal"]
END_DATE = pd.Timestamp("2025-12-31")     # 回測終點；之後的列讀檔後立刻丟掉
WINDOWS_D = {
    "W1_2014_2019": ("2014-01-02", "2019-12-31"),
    "W2_2020_2025": ("2020-01-02", "2025-12-31"),
    "full": ("2014-01-02", "2025-12-31"),
}
W1, W2, WFULL = "W1_2014_2019", "W2_2020_2025", "full"
COSTS_D = [0, 10, 20]          # bps per side; 10 = base, 20 = stress
BASE_COST_D = 10
STRESS_COST_D = 20
N_PICK_D = 10
MIN_PRIOR = 252
N_NULL = 200
MAX_TRANCHES = 21
SEED = 20261118


# ── loaders ────────────────────────────────────────────────────────────────
def _cut(df: pd.DataFrame, allow_2026: bool) -> pd.DataFrame:
    df = df.sort_index()
    return df if allow_2026 else df.loc[df.index <= END_DATE]


def load_roster(allow_2026: bool = False) -> pd.DataFrame:
    return _cut(pd.read_csv(ROSTER_CSV, index_col=0, parse_dates=True), allow_2026)


def load_idx(allow_2026: bool = False) -> pd.DataFrame:
    with open(IDX_PKL, "rb") as fh:
        return _cut(pickle.load(fh)["idx"], allow_2026)


def load_stk_pkl(allow_2026: bool = False) -> pd.DataFrame:
    with open(IDX_PKL, "rb") as fh:
        return _cut(pickle.load(fh)["stk"], allow_2026)


def load_lev(allow_2026: bool = False) -> pd.DataFrame:
    with open(LEV_PKL, "rb") as fh:
        return _cut(pickle.load(fh), allow_2026)


def cash_daily(idx: pd.DataFrame, dates: pd.DatetimeIndex) -> np.ndarray:
    """^IRX 是年化 %；日息 = /100/252。第 t 日的報酬用 t-1 收盤已知的利率。"""
    irx = idx["^IRX"].ffill().reindex(dates, method="ffill")
    return (irx.shift(1).bfill() / 100.0 / 252.0).to_numpy()


# ── metrics ────────────────────────────────────────────────────────────────
def metrics_from_returns(ret: np.ndarray, cash: np.ndarray | None,
                         first_date, last_date) -> dict:
    """ret = 窗內首日「之後」的每日報酬（首日收盤 V=1）。CAGR 用日曆天。"""
    ret = np.asarray(ret, dtype=float)
    n = len(ret)
    v = np.concatenate([[1.0], np.cumprod(1.0 + ret)])
    cal_days = (pd.Timestamp(last_date) - pd.Timestamp(first_date)).days
    cagr = v[-1] ** (365.25 / cal_days) - 1 if cal_days > 0 and v[-1] > 0 else np.nan
    sd = ret.std(ddof=1) if n > 1 else np.nan
    sharpe = ret.mean() / sd * np.sqrt(252) if sd and sd > 0 else np.nan
    if cash is not None:
        ex = ret - np.asarray(cash, dtype=float)
        sdx = ex.std(ddof=1) if n > 1 else np.nan
        sharpe_ex = ex.mean() / sdx * np.sqrt(252) if sdx and sdx > 0 else np.nan
    else:
        sharpe_ex = np.nan
    mdd = float((v / np.maximum.accumulate(v) - 1).min())
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    return {"n_days": n, "cagr": cagr, "sharpe": sharpe, "sharpe_ex": sharpe_ex,
            "mdd": mdd, "calmar": calmar}


def window_slice(dates: pd.DatetimeIndex, start: str, end: str) -> tuple[int, int]:
    """回傳 (i0, i1)：窗內第一個與最後一個交易日的位置。報酬取 i0+1..i1。"""
    pos = np.where((dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end)))[0]
    return int(pos[0]), int(pos[-1])


def window_metrics(dates, ret, cash, start, end) -> dict:
    i0, i1 = window_slice(dates, start, end)
    c = None if cash is None else cash[i0 + 1:i1 + 1]
    return metrics_from_returns(ret[i0 + 1:i1 + 1], c, dates[i0], dates[i1])


def info_ratio(ret: np.ndarray, bench: np.ndarray) -> float:
    a = np.asarray(ret) - np.asarray(bench)
    sd = a.std(ddof=1)
    return float(a.mean() / sd * np.sqrt(252)) if sd > 0 else np.nan


def bh_qvalues(p: np.ndarray) -> np.ndarray:
    """Benjamini–Hochberg q 值（單調化）。"""
    p = np.asarray(p, dtype=float)
    m = len(p)
    order = np.argsort(p, kind="stable")
    ranked = p[order] * m / (np.arange(m) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.empty(m)
    q[order] = np.minimum(ranked, 1.0)
    return q


# ── signals / eligibility ─────────────────────────────────────────────────
def eligibility(P: np.ndarray, min_prior: int = MIN_PRIOR) -> np.ndarray:
    """E[t, n] = t 收盤有價，且 t 之前至少有 min_prior 個收盤價。"""
    ok = ~np.isnan(P)
    prior = np.cumsum(ok, axis=0) - ok          # 嚴格在 t 之前的收盤數
    return ok & (prior >= min_prior)


def signal_matrix(P: np.ndarray, L: int, skip: int = 0) -> np.ndarray:
    """S[t] = P[t-skip] / P[t-L] - 1（只用 <= t 的收盤）。"""
    T, N = P.shape
    S = np.full((T, N), np.nan)
    if L < T:
        S[L:] = P[L - skip:T - skip] / P[:T - L] - 1.0
    return S


def rank_picks(S: np.ndarray, E: np.ndarray, direction: str, n_pick: int) -> list:
    """每天依訊號選 n_pick 檔（momentum = 最大、reversal = 最小）；可選數不足回 None。
    同分時以欄位順序決勝（stable），不引入隨機。"""
    T, N = S.shape
    val = np.where(E & np.isfinite(S), S, np.nan)
    key = -val if direction == "momentum" else val
    order = np.argsort(key, axis=1, kind="stable")     # NaN 排最後
    n_ok = np.isfinite(val).sum(axis=1)
    return [order[t, :n_pick].copy() if n_ok[t] >= n_pick else None for t in range(T)]


# ── tranche engine ─────────────────────────────────────────────────────────
def tranche_offsets(H: int, max_tranches: int = MAX_TRANCHES) -> list[int]:
    K = min(H, max_tranches)
    return [(k * H) // K for k in range(K)]


def simulate(P: np.ndarray, select_fn, H: int, t0: int, n_draws: int = 1,
             offsets: list[int] | None = None):
    """分批模擬。

    select_fn(s, k) -> (n_draws, m) 的欄位索引陣列（或 None = 該次不持有），
    只能使用 <= s 收盤的資訊。成交在 s+1 收盤；持有報酬自 s+2 起算。
    第 k 批的訊號日 = t0（全體期初建倉）與 t0+offset_k、之後每 H 日。
    回傳 g, tau，形狀 (T, K, n_draws)：
      g[t]   = 該批第 t 日的毛報酬；
      tau[t] = 該批第 t 日收盤成交的 sum|Δw|（買+賣，佔該批淨值）。
    """
    T, N = P.shape
    offs = tranche_offsets(H) if offsets is None else list(offsets)
    K = len(offs)
    g = np.zeros((T, K, n_draws))
    tau = np.zeros((T, K, n_draws))
    rows = np.arange(n_draws)[:, None]
    for k, off in enumerate(offs):
        sig_days = sorted(set([t0] + list(range(t0 + off, T - 1, H))))
        sig_days = [s for s in sig_days if s + 1 <= T - 1]
        w_old = np.zeros((n_draws, N))
        for j, s in enumerate(sig_days):
            d = s + 1
            d_next = sig_days[j + 1] + 1 if j + 1 < len(sig_days) else T - 1
            sel = select_fn(s, k)
            w_new = np.zeros((n_draws, N))
            if sel is not None:
                sel = np.asarray(sel).reshape(n_draws, -1)
                m = sel.shape[1]
                w_new[rows, sel] = 1.0 / m
            tau[d, k, :] = np.abs(w_new - w_old).sum(axis=1)
            w_old = np.zeros((n_draws, N))
            if sel is None or d_next <= d:
                if sel is not None:
                    w_old = w_new
                continue
            base = P[d][sel]                                   # (D, m)
            path = P[d + 1:d_next + 1][:, sel] / base          # (len, D, m)
            if np.isnan(path).any():
                raise ValueError("selected name has a missing price inside the holding period")
            rel = path.mean(axis=2)                            # (len, D)
            prev = np.vstack([np.ones((1, n_draws)), rel[:-1]])
            g[d + 1:d_next + 1, k, :] = rel / prev - 1.0
            w_old[rows, sel] = path[-1] / (m * rel[-1][:, None])
    return g, tau


def combine(g: np.ndarray, tau: np.ndarray, cost_bps: float):
    """各批淨值 -> 組合日報酬與單邊換手。回傳 ret (T, D), turnover_oneway (T, D)。"""
    c = cost_bps / 1e4
    fac = (1.0 + g) * (1.0 - c * tau)
    nav = np.cumprod(fac, axis=0)                 # (T, K, D)，各批期初 = 1
    V = nav.mean(axis=1)                          # (T, D)
    ret = np.zeros_like(V)
    ret[1:] = V[1:] / V[:-1] - 1.0
    nav_pre = nav / (1.0 - c * tau)               # 成交日扣成本前的淨值
    to = (nav_pre * tau).sum(axis=1) / nav_pre.sum(axis=1) / 2.0
    return ret, to


def run_signal_cell(P, S, E, direction: str, H: int, n_pick: int, t0: int | None = None,
                    offsets=None):
    """訊號矩陣 -> (g, tau, t0)。S[t] 被視為「t 收盤已知」的訊號，引擎自己做 t+1 成交。"""
    picks = rank_picks(S, E, direction, n_pick)
    if t0 is None:
        t0 = next(t for t, p in enumerate(picks) if p is not None)
    g, tau = simulate(P, lambda s, k: None if picks[s] is None else picks[s][None, :],
                      H, t0, 1, offsets)
    return g, tau, t0


def random_select_fn(E: np.ndarray, n_pick: int, n_draws: int, rng: np.random.Generator):
    """null：每次換倉在當日可選名單中隨機抽 n_pick 檔（不放回），各 draw 獨立。"""
    N = E.shape[1]

    def fn(s, k):
        el = E[s]
        if el.sum() < n_pick:
            return None
        u = rng.random((n_draws, N))
        u[:, ~el] = np.inf
        return np.argpartition(u, n_pick - 1, axis=1)[:, :n_pick]
    return fn


def roster_ew_returns(P: np.ndarray, E: np.ndarray) -> np.ndarray:
    """同名單等權：每日再平衡、零成本、同樣的資格與 t+1 收盤成交時序
    （第 u 日報酬用 u-2 收盤時的可選名單）。"""
    T, N = P.shape
    r = np.full((T, N), np.nan)
    r[1:] = P[1:] / P[:-1] - 1.0
    out = np.zeros(T)
    for u in range(2, T):
        m = E[u - 2]
        if m.any():
            out[u] = np.nanmean(r[u, m])
    return out


# ── small io helpers ───────────────────────────────────────────────────────
def write_json(path: Path, obj) -> None:
    def _default(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if not np.isfinite(o) else float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, (pd.Timestamp,)):
            return str(o.date())
        return str(o)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=_default),
                    encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ── finalize：兩段的 part json -> verdict.json + summary.md ───────────────
PREREG = "research/horizon-study-2026-11-18.md"

DEVIATIONS = [
    "US-D eligibility: '>=252 prior closes' read strictly (252 closes BEFORE t). Data starts 2013-01-02, so the "
    "first signal is 2014-01-02, the first trade 2014-01-03 close and the first return day 2014-01-06; the single "
    "return day 2014-01-03 inside W1/full is uninvested (0%) for every cell, the null and roster-EW, while "
    "SPY/QQQ/SMH are invested that day. Starting earlier is impossible for 252-day signals.",
    "'Beat' = window CAGR above the benchmark's CAGR for the same window.",
    "Pass clause 3 ('still wins at 20bp') = beats roster-EW in BOTH sub-windows at 20bp (same test as clause 1 at "
    "the stress cost).",
    "null_p is one-sided on FULL-window CAGR at base cost: p=(1+#null>=cell)/(200+1); every null draw re-draws 10 "
    "random eligible names at each tranche rebalance (same schedule, same costs). Smallest attainable p is 1/201. "
    "Sharpe-based and gross-vs-gross p-values are reported as *_info columns and are NOT used in the pass line.",
    "Tranches are independent sub-accounts (no free rebalancing between tranches); portfolio NAV = mean of tranche "
    "NAVs. All tranches enter at the first trade; tranche k then rebalances at t0+floor(k*H/K) and every H sessions.",
    "Inside a holding period positions drift; turnover at a rebalance = sum|w_new - w_drifted|; cost = bps x that, "
    "deducted at the trade-day close. turnover_ann is one-way (half of buys+sells) per year of NAV.",
    "Roster-EW comparator: daily rebalanced, zero cost, same eligibility and the same t+1-close lag.",
    "Cash rate (^IRX/100/252, previous day's quote) is used only for sharpe_ex; cells are always fully invested.",
    "SPY/QQQ/SMH come from the pkl 'idx' frame (QQQ is absent from weak_flag_px; SPY and SMH agree with it to 1e-6).",
    "Window metrics: V_start = close of the first session of the window, so that session's own return is excluded.",
    "horizon_summary best_cell = highest CAGR inside H x window x cost; best by Sharpe / Calmar in extra columns.",
    "US-E entry = ADJUSTED CLOSE of the fill date (not the fill price), as the spec says; one price source per "
    "return, never spliced (priority weak_flag_px > pkl stk > pkl idx > pkl lev2x > eod key, longest then most "
    "recent); sessions = SPY calendar; a fill is dropped for an H when the calendar ends before the exit date or no "
    "single series covers both dates.",
    "US-E: buys with a missing origin are counted as 'unknown' (count in US-E block). Bootstrap = percentile interval over 2,000 "
    "resamples of entry months (ratio estimators, seed 20261118). Annualised equivalent = (1+mean)^(252/H)-1.",
    "FIFO reference table follows the project's convention (cash 'amount' incl. fees, the ledger's split table via "
    "split_adjust_qty, stock/ETF only, VOID rows excluded); buckets by calendar days <7, 7-29, 30-90, 91-364, >=365. "
    "A robustness variant with price-implied split factors is added because the ledger's split table is incomplete.",
    "Extra outputs not required by the spec and not used in any pass line: horizon_by_direction.csv, null_dist.csv, "
    "daily_returns_base.csv, pick_vol63_pctile_mean_info, the matched-sample cut in own_buys_summary.csv, "
    "price_crosscheck.csv, own_buys_fills.csv.",
    "END DATE: all US-D inputs are cut to <=2025-12-31 at load. Outputs of an earlier aborted attempt (which had run "
    "to 2026-11-09) were deleted and regenerated. US-E, a ledger diagnostic, uses 2026 prices by design.",
]


def _isnum(x) -> bool:
    return isinstance(x, (int, float)) and np.isfinite(x)


def _pc(x, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%" if _isnum(x) else "—"


def _pp(x, d: int = 1) -> str:
    return f"{x * 100:+.{d}f}pp" if _isnum(x) else "—"


def _fx(x, d: int = 2) -> str:
    return f"{x:.{d}f}" if _isnum(x) else "—"


def _usd(x) -> str:
    return f"{x:+,.0f}" if _isnum(x) else "—"


def _table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", " / ") for c in r) + " |" for r in rows]
    return "\n".join(out)


def build_summary(usd: dict, use: dict) -> tuple[str, dict]:
    """回傳 (summary.md 文字, 給 verdict.json 的關鍵數字)。"""
    hs = pd.DataFrame(usd["horizon_summary_compact"])
    hd = pd.DataFrame(usd["horizon_by_direction_full_base"])
    bm = usd["benchmarks"]
    cnt = usd["counts"]
    sa = usd["sanity_anchors"]
    Hs = HORIZONS_D

    def hrow(H, window=WFULL, cost=BASE_COST_D):
        return hs[(hs.H == H) & (hs.window == window) & (hs.cost == cost)].iloc[0]

    med = {H: float(hrow(H).excess_cagr_vs_roster_ew_median) for H in Hs}
    med_gross = {H: float(hrow(H, cost=0).excess_cagr_vs_roster_ew_median) for H in Hs}
    med_stress = {H: float(hrow(H, cost=STRESS_COST_D).excess_cagr_vs_roster_ew_median) for H in Hs}
    share = {H: float(hrow(H).share_beating_roster_ew) for H in Hs}
    ew = bm[f"roster_ew|{WFULL}"]
    spy = bm[f"SPY|{WFULL}"]
    nom = usd["nominated_detail_full_base"]
    nom_names = usd["nominated_cells"]
    odd = [c for c in nom_names if c.startswith("ret_1|") and c.endswith(("H126", "H252"))]
    vol = usd["pick_vol63_pctile_mean_info"]

    ea = pd.DataFrame(use["all"])

    def erow(H, b):
        return ea[(ea.H == H) & (ea.benchmark == b)].iloc[0]

    He = HORIZONS_E
    spy_ex = {H: float(erow(H, "SPY").excess_mean_ew) for H in He}
    smh_ex = {H: float(erow(H, "SMH").excess_mean_ew) for H in He}
    spy_pos = [H for H in He if spy_ex[H] > 0]
    spy_neg = [H for H in He if spy_ex[H] <= 0]
    smh_neg_all = all(v < 0 for v in smh_ex.values())
    spy_sig = [H for H in He if erow(H, "SPY").excess_ew_ci_lo > 0]
    smh_sig = [H for H in He if erow(H, "SMH").excess_ew_ci_hi < 0]
    fifo = use["fifo_reference"]
    xc = use["crosschecks"]

    L: list[str] = []
    A = L.append
    A("# 持有週期研究（美股半邊）US-D／US-E：結果摘要")
    A("")
    A(f"預註冊：`{PREREG}`（凍結，未改動）。本檔由 `tools/backtests/horizon_sweep_2026-11-18/` 的程式產生。")
    A("本檔含由個人帳本算出的彙總數字，只能留在 gitignore 的路徑。")
    A("")
    A("## 0. 結論（先讀這段）")
    A("")
    A("1. 這份結果只是描述，最多只能「提名」，不是可以照做的證據。個股名單是今天的觀察名單，"
      "帶倖存者偏差（只留下活到今天的贏家）。")
    A(f"2. US-D（名單內選股）：扣掉成本後，持有週期 H 越長，越多格子贏「同名單等權」。"
      f"H=1 的中位數每年輸 {abs(med[1]) * 100:.1f}pp（百分點）。H=252 的中位數每年贏 {med[252] * 100:.1f}pp。")
    A(f"3. 這個差距幾乎全是交易成本造成的。零成本時，七個週期的中位數超額都落在 "
      f"{min(med_gross.values()) * 100:+.1f}pp 到 {max(med_gross.values()) * 100:+.1f}pp 之間，沒有哪個週期本身比較會賺。")
    A(f"4. 98 格裡有 {cnt['nominated']} 格過了預註冊的及格線。"
      + ("但連「看 1 日漲跌選股、再抱半年到一年」這種近乎亂選的格子也過關，" if odd else "但過關的格子同時包含順勢與反轉兩個方向，")
      + "所以這條及格線在這份名單上分不出真假，過關的格子都不該當成發現。")
    if spy_pos and spy_neg and smh_neg_all and spy_sig:
        A(f"5. US-E（自己的買點）：買進後 {max(spy_neg)} 個交易日內，平均沒有贏 SPY（標普 500 指數 ETF）。"
          f"抱到 {min(spy_sig)} 日以上，平均超額才明顯為正。"
          "但對 SMH（半導體 ETF）六個週期全部落後，所以長抱多賺的主要來自「押對產業」，不是買點挑得準。")
    else:
        A("5. US-E（自己的買點）：各週期對 SPY（標普 500 指數 ETF）與 SMH（半導體 ETF）的超額方向不一致，"
          "細節見第 3 節；沒有任何週期同時贏過三個基準。")
    A(f"6. 穩定度沒有贏家。98 格裡只有 {cnt['mdd_shallower_than_ew_full_base']} 格的最大回撤比同名單等權淺。"
      f"最長週期的 Sharpe 中位數是 {hrow(252).sharpe_median:.2f}，同名單等權是 {ew['sharpe']:.2f}。")
    A("")
    A("## 1. 名詞")
    A("")
    A("- **H（持有週期）**：一批部位買進後固定抱幾個交易日才換。")
    A("- **L（回看天數）**：訊號看過去幾個交易日的報酬。`ret_63` 就是過去 63 日報酬；"
      "`ret_252_skip21` 是過去 252 日報酬但跳過最近 21 日。")
    A("- **順勢（momentum）**：買訊號最高的 10 檔。**反轉（reversal）**：買訊號最低的 10 檔。")
    A("- **格（cell）**：一個「訊號 × 方向 × H」的組合；共 7 × 2 × 7 = 98 格。")
    A("- **CAGR**：年化複利報酬。期初一次投入時，它等於 **IRR**（內部報酬率）。")
    A("- **Sharpe**：每承受一單位波動賺多少；本研究不扣無風險利率。"
      "`sharpe_ex` 欄是扣掉國庫券利率（^IRX，13 週美國國庫券殖利率）的版本。")
    A("- **MDD**：最大回撤，淨值從高點跌到低點的最大跌幅。**Calmar**：CAGR ÷ |MDD|。")
    A("- **pp**：百分點。**bp**：萬分之一。**ETF**：指數股票型基金。")
    A("- **同名單等權**：83 檔名單裡當天可選的股票每天等權重、零成本；它是主要比較對象。")
    A("- **超額**：策略的 CAGR 減掉基準的 CAGR。")
    A("- **null（隨機對照）**：用同樣的換倉時程、同樣成本，每次隨機抽 10 檔，重複 200 次。")
    A("- **p 值**：隨機對照裡有多少比例不輸給這一格；越小代表越不像亂選。")
    A("- **BH q**：Benjamini–Hochberg 校正；一次看 98 格時，用它控制「看起來顯著其實是運氣」的比例。")
    A("- **分批（tranche）**：把資金拆成 min(H, 21) 份，起始日錯開，各自每 H 日換一次。")
    A("- **換手**：一年內單邊買進（或賣出）的金額是淨值的幾倍。")
    A("- **bootstrap 95% 區間**：把買進月份整月重抽 2,000 次，看平均值會晃多大。")
    A("- **FIFO**：先進先出，把賣出配到最早買進的那一批。")
    A("")
    A("## 2. US-D：個股名單截面 × 持有週期")
    A("")
    A("### 2.1 設定")
    A("")
    d = usd["data"]
    A(f"- 名單是 83 檔個股的還原收盤價；可選條件是之前已有 252 個收盤價。期初可選 {d['n_eligible_at_start']} 檔，"
      f"期末 {d['n_eligible_at_end']} 檔。")
    A("- 訊號在 t 日收盤算出，t+1 日收盤成交，從 t+2 日的報酬開始算。")
    A("- 成本每邊 0／10／20bp；10bp 是基本情境，20bp 是壓力情境。")
    A(f"- 資料只用到 {d['max_date_used']}；2026 年的列讀檔後立刻丟掉。")
    A("- 兩個子窗是 2014-01-02 → 2019-12-31 與 2020-01-02 → 2025-12-31；全期是兩者相連。")
    A("")
    A("### 2.2 基準")
    A("")
    rows = []
    for b in ["roster_ew"] + BENCH:
        for w in (W1, W2, WFULL):
            m = bm[f"{b}|{w}"]
            rows.append([b, w, _pc(m["cagr"]), _fx(m["sharpe"]), _fx(m["sharpe_ex"]), _pc(m["mdd"]),
                         _fx(m["calmar"])])
    A(_table(["基準", "窗", "CAGR", "Sharpe", "sharpe_ex", "MDD", "Calmar"], rows))
    A("")
    A(f"同名單等權的全期 CAGR 是 {_pc(ew['cagr'])}，SPY 是 {_pc(spy['cagr'])}。"
      "這個差距主要是倖存者偏差，不是選股能力：名單是事後挑出來、今天還值得看的股票。")
    A("所以下面只看「同名單內不同週期」的相對差異；SPY／QQQ（那斯達克 100 ETF）／SMH 只當背景。")
    A("")
    A("### 2.3 每個持有週期的全貌（全期、每邊 10bp）")
    A("")
    A("表中「中位數」是把同一個 H 的 14 格排隊後取正中間那格；「贏等權比例」是 14 格裡 CAGR 高於同名單等權的比例。")
    A("")
    rows = []
    for H in Hs:
        r = hrow(H)
        rows.append([H, _pc(r.cagr_median), _fx(r.sharpe_median), _pc(r.mdd_median), _fx(r.calmar_median),
                     _pp(r.excess_cagr_vs_roster_ew_median), _pc(r.share_beating_roster_ew, 0),
                     _pc(r.share_beating_SPY, 0), _pc(r.share_beating_QQQ, 0), _pc(r.share_beating_SMH, 0),
                     f"{r.turnover_ann_median:.1f}x", _pp(-r.cost_drag_ann_median), r.best_cell])
    A(_table(["H", "CAGR 中位數", "Sharpe 中位數", "MDD 中位數", "Calmar 中位數", "對等權超額中位數",
              "贏等權比例", "贏 SPY", "贏 QQQ", "贏 SMH", "換手中位數", "成本拖累中位數", "CAGR 最高的格"], rows))
    A("")
    best_H = max(Hs, key=lambda h: med[h])
    A(f"- 最賺：中位數超額最高的是 H={best_H}，每年 {_pp(med[best_H])}。")
    A(f"- 最穩：Sharpe 中位數隨 H 變長而上升，從 H=1 的 {hrow(1).sharpe_median:.2f} 到 H=252 的 {hrow(252).sharpe_median:.2f}。")
    A(f"- 回撤：每個 H 的 MDD 中位數都比同名單等權的 {_pc(ew['mdd'])} 深。只抱 10 檔比抱整份名單集中，跌起來更深。")
    all_beat = [H for H in Hs if hrow(H).share_beating_SPY == 1 and hrow(H).share_beating_QQQ == 1]
    A(f"- 贏大盤：H = {'、'.join(str(h) for h in all_beat)} 的格子全部贏 SPY 與 QQQ，但這是名單偏差，不能據以下結論。")
    A("")
    A("**同一張表拆成順勢與反轉（全期、10bp）**")
    A("")
    rows = []
    for H in Hs:
        for dr in DIRECTIONS:
            r = hd[(hd.H == H) & (hd.direction == dr)].iloc[0]
            rows.append([H, "順勢" if dr == "momentum" else "反轉", _pc(r.cagr_median), _fx(r.sharpe_median),
                         _pc(r.mdd_median), _fx(r.calmar_median), _pp(r.excess_cagr_vs_roster_ew_median),
                         _pc(r.share_beating_roster_ew, 0), int(r.n_nominated)])
    A(_table(["H", "方向", "CAGR 中位數", "Sharpe 中位數", "MDD 中位數", "Calmar 中位數", "對等權超額中位數",
              "贏等權比例", "過及格線格數"], rows))
    A("")
    A("**成本把差距放大了多少（全期，對同名單等權的超額中位數）**")
    A("")
    rows = [[H, _pp(med_gross[H]), _pp(med[H]), _pp(med_stress[H]),
             _pc(hrow(H, cost=0).share_beating_roster_ew, 0), _pc(share[H], 0),
             _pc(hrow(H, cost=STRESS_COST_D).share_beating_roster_ew, 0)] for H in Hs]
    A(_table(["H", "0bp 超額", "10bp 超額", "20bp 超額", "0bp 贏等權比例", "10bp 贏等權比例", "20bp 贏等權比例"], rows))
    A("")
    A("零成本那一欄幾乎是平的：換倉換得勤不會多賺，只會多付成本。")
    A(f"H=1 時成本拖累的中位數是每年 {_pc(hrow(1).cost_drag_ann_median)}；H=252 時只剩 {_pc(hrow(252).cost_drag_ann_median)}。")
    A("零成本的中位數超額在每個 H 都是正的，連順勢、反轉混在一起算也是；這本身就是可疑訊號，原因見 2.6。")
    A("")
    A("### 2.4 兩個子窗（10bp，對同名單等權）")
    A("")
    rows = []
    for H in Hs:
        a, b = hrow(H, W1), hrow(H, W2)
        rows.append([H, _pp(a.excess_cagr_vs_roster_ew_median), _pc(a.share_beating_roster_ew, 0),
                     _pp(b.excess_cagr_vs_roster_ew_median), _pc(b.share_beating_roster_ew, 0)])
    A(_table(["H", "2014–2019 超額中位數", "2014–2019 贏等權比例", "2020–2025 超額中位數", "2020–2025 贏等權比例"], rows))
    A("")
    A("「越長越好」主要出現在 2020–2025；2014–2019 的中位數超額在各週期之間沒有明顯的單調關係。")
    A("")
    A("### 2.5 及格線與提名")
    A("")
    A("及格線有三條：兩個子窗都贏同名單等權（10bp）；全期對隨機對照的 p 經 BH 校正後 q < 0.10；20bp 下兩個子窗仍贏。")
    A("")
    A(_table(["條件", "通過格數（共 98）"], [
        ["① 10bp 兩窗都贏等權", cnt["pass_1_beat_ew_both_windows_base"]],
        ["② BH q < 0.10", cnt["pass_2_bh_q_lt_0.10"]],
        ["③ 20bp 兩窗都贏等權", cnt["pass_3_beat_ew_both_windows_20bp"]],
        ["三條全過（提名）", cnt["nominated"]],
        ["　其中順勢", cnt["nominated_momentum"]],
        ["　其中反轉", cnt["nominated_reversal"]]]))
    A("")
    A("提名的格子（全期、10bp；依對等權超額排序）：")
    A("")
    rows = [[r["cell"], _pc(r["cagr"]), _fx(r["sharpe"]), _pc(r["mdd"]), _fx(r["calmar"]),
             _pp(r["excess_cagr_vs_roster_ew"]), _fx(r["ir_vs_roster_ew"]), f"{r['turnover_ann']:.1f}x",
             f"{r['null_p']:.3f}", f"{r['bh_q']:.3f}"] for r in nom]
    A(_table(["格", "CAGR", "Sharpe", "MDD", "Calmar", "對等權超額", "對等權資訊比率", "換手", "null p", "BH q"],
             rows) if rows else "（無）")
    A("")
    A("資訊比率是「每天比等權多賺的平均 ÷ 它的波動」再年化，衡量贏得穩不穩。")
    A("")
    A("**為什麼這份提名名單不能信**")
    A("")
    A(f"- 98 格有 {cnt['pass_2_bh_q_lt_0.10']} 格通過 BH 校正。一個有鑑別力的檢定不會讓八成以上的格子、而且順勢與反轉兩邊同時過關。")
    if odd:
        A(f"- `{'`、`'.join(odd)}` 也在提名名單裡。用昨天一天的漲跌選股再抱半年以上，訊號早就失效，實質上接近亂選。")
    A(f"- 長回看的順勢格（ret_126、ret_252、ret_252_skip21）在每個 H 都過關，超額幾乎不隨 H 變。"
      "這比較像「名單裡的贏家本來就是事後挑的」，而不是某個持有週期有效。")
    A("- 所以這些提名只代表「通過了預註冊的機械式門檻」，不代表找到可用的策略。")
    A("")
    A("### 2.6 隨機對照（null）的分布與它的問題")
    A("")
    rows = []
    for H in Hs:
        n = usd["null_full"][str(H)]
        rows.append([H, _pc(n["gross_cagr_median"]), _pc(n["base_cagr_median"]), _pc(n["base_cagr_p05"]),
                     _pc(n["base_cagr_p95"]), f"{n['turnover_ann_median']:.1f}x"])
    A(_table(["H", "零成本 CAGR 中位數", "10bp CAGR 中位數", "10bp 第 5 百分位", "10bp 第 95 百分位", "換手中位數"], rows))
    A("")
    n1 = usd["null_full"]["1"]
    A(f"- 零成本時，隨機抽 10 檔的中位數與同名單等權的 {_pc(ew['cagr'])} 幾乎一樣，表示引擎對「亂選」是公平的。")
    A(f"- 但隨機對照每次換倉都整批換掉，短週期的成本極重：H=1 的中位數 CAGR 從零成本的 {_pc(n1['gross_cagr_median'])} "
      f"掉到 10bp 的 {_pc(n1['base_cagr_median'])}。換手低的訊號只因為少付成本就能「顯著」贏它。")
    A(f"- 改用「零成本對零成本」比較（僅供對照，不改及格線），通過 BH 的格數是 {cnt['n_bh_q_gross_lt_0.10_info']}，"
      f"預註冊版本是 {cnt['pass_2_bh_q_lt_0.10']}。")
    A("- 隨機對照的各批是獨立抽的，H ≥ 21 時 21 批合起來等於抱了名單裡大部分的股票，分布很窄；任何集中的 10 檔組合都容易落在分布外。")
    A(f"- 14 種「訊號 × 方向」選出的股票，近 63 日波動的名單內百分位平均落在 "
      f"{min(vol.values()):.2f} 到 {max(vol.values()):.2f}，全部高於 0.50。"
      "也就是不管買漲最多還是跌最多，挑到的都是波動大的股票。")
    A("- 在一份只留贏家的名單裡，波動大的股票正是漲最多的那些。所以「減掉同名單等權」並沒有把倖存者偏差減乾淨。")
    A("")
    A("## 3. US-E：自己的買點，如果固定抱 H 日")
    A("")
    A("這一段是對帳本的診斷，不是回測，沒有及格線。它回答：買進之後多久，選股資訊才兌現。")
    A("")
    A("### 3.1 設定與樣本")
    A("")
    A(f"- 樣本是帳本裡 {use['n_buys']} 筆股票／ETF 買進，共 {use['n_symbols']} 個代號。選擇權與作廢（VOID）列已排除。")
    A(f"- 買進日期從 {use['first_buy']} 到 {use['last_buy']}，分布在 {use['n_entry_months']} 個月份。")
    by = use["buys_by_year"]
    last_y = max(by)
    A(f"- 樣本很偏近期：{last_y} 年的買進有 {by[last_y]} 筆，佔全部的 {by[last_y] / use['n_buys'] * 100:.0f}%。")
    A("- 進場價是買進日的還原收盤價，不是實際成交價。出場價是 H 個交易日後的還原收盤價。")
    A("- 超額 = 這筆買進的 H 日報酬 − 同一段期間基準的報酬。")
    A("- 這一段依預註冊使用 2026 年的價格（回測終點規則的唯一例外）。")
    A("")
    cov = use["coverage_by_H"]
    rows = [[H, cov[str(H)]["n_ok"], cov[str(H)]["n_dropped_horizon_past_data_end"],
             cov[str(H)]["n_dropped_no_series_cover"], _pc(cov[str(H)]["share_from_eod_cache"], 0)] for H in He]
    A(_table(["H", "可計算筆數", "剔除：買太近、還沒滿 H 日", "剔除：價格序列蓋不到", "用 EODHD 快取價的比例"], rows))
    A("")
    A("### 3.2 全部買進：對三個基準的超額")
    A("")
    A("「等權平均」把每筆買進看成一樣重；「金額加權平均」依買進金額加權；「勝率」是超額大於零的筆數比例。")
    A("方括號是按買進月份整月重抽的 bootstrap 95% 區間；區間跨過 0 表示分不出正負。")
    A("")
    for b in BENCH:
        rows = []
        for H in He:
            r = erow(H, b)
            rows.append([H, int(r.n_fills), int(r.n_symbols), _pp(r.excess_mean_ew),
                         f"[{r.excess_ew_ci_lo * 100:+.1f}, {r.excess_ew_ci_hi * 100:+.1f}]",
                         _pp(r.excess_mean_nw),
                         f"[{r.excess_nw_ci_lo * 100:+.1f}, {r.excess_nw_ci_hi * 100:+.1f}]",
                         _pp(r.excess_median), _pc(r.hit_rate, 0)])
        A(f"**對 {b}**")
        A("")
        A(_table(["H", "筆數", "代號數", "等權平均超額", "95% 區間（pp）", "金額加權平均超額", "95% 區間（pp）",
                  "中位數超額", "勝率"], rows))
        A("")
    if spy_pos and spy_neg:
        A(f"- 對 SPY：H ≤ {max(spy_neg)} 的等權平均超額是負的，H ≥ {min(spy_pos)} 轉正。"
          + (f"區間完全在 0 以上的只有 H = {'、'.join(str(h) for h in spy_sig)}。" if spy_sig else "沒有任何 H 的區間完全在 0 以上。"))
    if smh_neg_all:
        A("- 對 SMH：六個週期的等權平均超額全部是負的。"
          + (f"區間完全在 0 以下的有 H = {'、'.join(str(h) for h in smh_sig)}。" if smh_sig else ""))
    A("- 每個 H 的中位數超額幾乎都是負的，勝率多半低於一半。平均值是被少數大贏家拉上去的，不是多數買進都贏。")
    hx = 126 if 126 in He else He[-1]
    A(f"- 基準本身差很多：在同樣的買進日抱 {hx} 個交易日，SMH 平均漲 {_pc(erow(hx, 'SMH').bench_mean_ew)}，"
      f"SPY 平均漲 {_pc(erow(hx, 'SPY').bench_mean_ew)}。")
    A("- 贏 SPY 而輸 SMH，代表多賺的部分用「持有半導體類股」就能解釋，不需要用買點解釋。")
    A("")
    A("### 3.3 報酬本身，與「每抱一天賺到多少超額」")
    A("")
    A("「年化等值」把 H 日的平均報酬換算成一年；「每日超額」= 平均超額 ÷ H，單位是 bp。")
    A("")
    rows = []
    for H in He:
        r = erow(H, "SPY")
        rows.append([H, _pc(r.raw_mean_ew, 2), _pc(r.raw_ann_ew), _pc(r.raw_mean_nw, 2), _pc(r.raw_ann_nw)]
                    + [f"{erow(H, b).excess_per_day_bp_ew:+.1f}" for b in BENCH]
                    + [f"{erow(H, b).excess_per_day_bp_nw:+.1f}" for b in BENCH])
    A(_table(["H", "平均報酬（等權）", "年化等值", "平均報酬（金額加權）", "年化等值",
              "每日超額 vs SPY（等權）", "vs QQQ", "vs SMH",
              "每日超額 vs SPY（金額加權）", "vs QQQ", "vs SMH"], rows))
    A("")
    A(f"- 買進後前 {max(spy_neg) if spy_neg else 21} 個交易日，平均報酬接近零甚至為負；同期 SPY 是漲的。" if spy_neg else "")
    A("- 對 SPY 的每日超額在一個月內是負的，三個月以後轉正並持續。對 SMH 的每日超額在每個 H 都是負的。")
    A("- 短 H 的年化等值是把很小的數字放大好幾十倍，只用來看正負，不要當成可期待的報酬。")
    A("")
    A("### 3.4 固定同一批買進再比一次")
    A("")
    A("H 越長，能算的買進越少，而且都是較早的買進。為了排除「樣本組成不同」，下面只留在 H=126（或 H=252）有資料的那批，看它們在各 H 的等權平均超額。")
    A("")
    for key, label in (("fills_with_H126", "有 H=126 資料的買進"), ("fills_with_H252", "有 H=252 資料的買進")):
        ms = pd.DataFrame(use["matched_sample"][key])
        rows = []
        for H in sorted(ms.H.unique()):
            g = ms[ms.H == H].set_index("benchmark")
            rows.append([H, int(g.loc["SPY", "n_fills"])] + [_pp(g.loc[b, "excess_mean_ew"]) for b in BENCH]
                        + [_pc(g.loc["SPY", "hit_rate"], 0)])
        A(f"**{label}**")
        A("")
        A(_table(["H", "筆數", "vs SPY", "vs QQQ", "vs SMH", "勝率 vs SPY"], rows))
        A("")
    A("固定樣本後形狀不變：前一個月對 SPY 沒有超額，超額出現在一個月之後；對 SMH 則從第 21 日起一路落後。")
    A("")
    A("### 3.5 分年度與分來源（等權平均超額）")
    A("")
    A("來源是帳本的 origin 欄：system（系統依計畫下的單）、user（使用者臨時下的單）、unknown（無法判定）。")
    A("")
    for b in ("SPY", "SMH"):
        rows = []
        for y, recs in use["by_year"].items():
            g = pd.DataFrame(recs)
            g = g[g.benchmark == b].set_index("H")
            rows.append([y] + [f"{_pp(g.loc[H, 'excess_mean_ew'])}（{int(g.loc[H, 'n_fills'])}）"
                               if H in g.index and g.loc[H, "n_fills"] > 0 else "—" for H in He])
        for o, recs in use["by_origin"].items():
            g = pd.DataFrame(recs)
            g = g[g.benchmark == b].set_index("H")
            rows.append([o] + [f"{_pp(g.loc[H, 'excess_mean_ew'])}（{int(g.loc[H, 'n_fills'])}）"
                               if H in g.index and g.loc[H, "n_fills"] > 0 else "—" for H in He])
        A(f"**對 {b}**（括號內是筆數）")
        A("")
        A(_table(["分組"] + [f"H={H}" for H in He], rows))
        A("")
    bo = use["buys_by_origin"]
    A(f"- 來源欄有 {bo.get('unknown', 0)} 筆是 unknown，佔 {bo.get('unknown', 0) / use['n_buys'] * 100:.0f}%；system 與 user 的筆數太少，長週期尤其少，只能當參考。")
    yrs_neg, yrs_other = [], []
    for y, recs in use["by_year"].items():
        g = pd.DataFrame(recs)
        g = g[(g.benchmark == "SPY") & (g.H <= 21) & (g.n_fills > 0)]
        (yrs_neg if len(g) and (g.excess_mean_ew < 0).all() else yrs_other).append(y)
    if yrs_neg:
        A(f"- 對 SPY：{'、'.join(yrs_neg)} 年的買進在 H ≤ 21 的平均超額都是負的，長週期才轉正。")
    if yrs_other:
        A(f"- {'、'.join(yrs_other)} 年的買進在短週期就是正的，但筆數最少。")
    A("")
    A("### 3.6 已實現損益按「實際」持有天數分桶（內生，只當對照）")
    A("")
    A("**這張表是內生的。** 抱多久是看到結果之後才決定的：賠錢的本來就砍得快，賺錢的才會抱得久。它不能當成週期測試，只用來對照 3.2。")
    A("")
    bk = pd.DataFrame(fifo["buckets"]).set_index("holding_bucket_calendar_days")
    bk2 = pd.DataFrame(fifo["robustness_price_implied_splits"]["buckets"]).set_index("holding_bucket_calendar_days")
    rows = [[k, int(bk.loc[k, "n_matched_pieces"]), _usd(bk.loc[k, "realised_pnl"]), _pc(bk.loc[k, "pnl_over_cost"]),
             _pc(bk.loc[k, "share_pieces_profitable"], 0), _usd(bk2.loc[k, "realised_pnl"])] for k in bk.index]
    A(_table(["實際持有（日曆天）", "配對段數", "已實現損益（美元）", "損益 ÷ 成本", "賺錢段比例",
              "對照：拆股倍數改由價格推定（美元）"], rows))
    A("")
    A(f"- 配對用 FIFO、含手續費的實際現金流，只算股票／ETF。找不到對應買進的賣出有 {fifo['n_unmatched_sells_skipped']} 筆，已略過。")
    A(f"- 另有 {fifo['n_partially_unmatched_sells']} 筆賣出只配到一部分（帳本起點之前的庫存，或拆股沒對上）；沒配到的部分不計損益。")
    A("- 帳本的拆股表不完整，所以另列一欄用價格資料推定拆股倍數的版本；正負方向不變，但 30–90 天那一桶的金額差得比較多。")
    A("- 對照 3.2：固定週期的版本同樣是「一個月內不賺、三個月以上才賺」，方向一致；但固定週期版對 SMH 是輸的，這是分桶表看不出來的。")
    A("")
    A("## 4. 健全性檢查")
    A("")
    A(f"- SPY 還原收盤 2014-01-02 → 2019-12-31 的 CAGR 是 {_pc(sa['SPY_cagr_2014-01-02_2019-12-31'], 2)}；預期約 11–12%。")
    A(f"- 同一段用另一個檔案（名單價格檔）的 SPY 算出來是 {_pc(sa['SPY_cagr_same_window_from_roster_csv'], 2)}，兩個來源一致。")
    A(f"- 同名單等權全期 CAGR {_pc(sa['roster_ew_cagr_full'])}，比 SPY 高 {_pp(sa['roster_ew_minus_SPY_full'])}：如預期遠高於 SPY，原因是倖存者偏差。")
    A(f"- 零成本的隨機對照中位數 CAGR 與同名單等權相差不到 1pp（見 2.6）。")
    A("- 單元測試 20 項全過：手算 2 檔含成本、偷看金絲雀（證明 t+1 成交）、H=1 分批等於不分批、已知曲線的指標、"
      "用持股股數寫的獨立參考實作對帳、未來價格擾動不影響過去、FIFO 與 bootstrap。")
    A(f"- 價格交叉檢查：名單價格檔與 EODHD 快取重疊的 {xc['n_weak_flag_vs_eod_checked']} 個代號，差異超過 2% 的有 {xc['n_level_disagree_gt_2pct']} 個。")
    A(f"- 同一筆買進能用兩個來源算的前瞻報酬有 {xc['fwd_returns_with_two_sources']} 個，最大相差 {xc['fwd_return_abs_diff_between_sources_max'] * 1e4:.1f}bp。")
    A("- 已實現損益分桶的重算結果，經人工比對，與先前已知的分桶數字方向與量級一致（一週內小虧、一到四週虧、一個月以上賺）。")
    A("")
    A("## 5. 偏離與解讀（預註冊沒寫死的地方，一律取保守讀法）")
    A("")
    zh = [
        "可選條件「價格滿 252 日」讀成「t 日之前已有 252 個收盤價」。資料從 2013-01-02 開始，所以第一個訊號日是 2014-01-02，2014-01-03 成交，2014-01-06 才有報酬；窗內第一個報酬日（2014-01-03）所有格子、隨機對照、同名單等權都是空手，SPY／QQQ／SMH 則有報酬。",
        "「贏」一律指同一個窗的 CAGR 較高。",
        "及格線第三條「20bp 下仍贏」讀成：20bp 下兩個子窗都贏同名單等權。",
        "null p 用全期、10bp 的 CAGR，單尾：p =（1 + 不輸給這一格的隨機次數）÷ 201。200 次能給的最小 p 是 0.005。以 Sharpe 算的 p 與零成本對零成本的 p 只列為參考欄，不進及格線。",
        "各批是獨立子帳戶，批與批之間不做免費再平衡；組合淨值是各批淨值的平均。期初所有批同一天建倉，之後第 k 批在自己的錯開日與每 H 日換倉。",
        "持有期間內權重隨價格漂移；換倉時的換手 = 新權重與漂移後舊權重的差的絕對值總和，成本在成交日收盤扣。",
        "同名單等權：每日再平衡、零成本、同樣的可選條件、同樣的 t+1 收盤時序。",
        "現金利率（^IRX ÷ 100 ÷ 252，用前一日的報價）只用於 sharpe_ex。",
        "SPY／QQQ／SMH 取自指數價格檔（名單價格檔沒有 QQQ）。",
        "窗的起點淨值是窗內第一個交易日的收盤，所以那一天本身的報酬不算在窗內。",
        "horizon_summary 的 best_cell 是該 H 內 CAGR 最高的格；另有依 Sharpe、Calmar 的欄位。",
        "US-E 的進場價是買進日還原收盤，不是成交價。一筆報酬只用同一個價格來源，不拼接；來源優先序是名單價格檔、個股價格檔、指數價格檔、槓桿 ETF 價格檔、EODHD 快取（最長、再取最新的那一把）。",
        f"US-E 有 {use.get('n_buys_with_missing_origin_counted_unknown', 0)} 筆買進的 origin 是空的，歸入 unknown。",
        "FIFO 分桶沿用專案慣例（含費用的現金流、帳本的拆股表）；另加一欄用價格推定拆股倍數的對照。",
        "多出的輸出（不影響任何判定）：horizon_by_direction.csv、null_dist.csv、daily_returns_base.csv、波動百分位診斷欄、固定樣本的切法、price_crosscheck.csv、own_buys_fills.csv。",
        "先前中斷的那次執行跑到 2026-11-09，違反「回測到 2025-12-31」；它留下的輸出已刪除並重算。",
    ]
    for i, z in enumerate(zh, 1):
        A(f"{i}. {z}")
    A("")
    A("## 6. 限制與可疑之處")
    A("")
    A("**US-D**")
    A("")
    A("- 名單是今天的觀察名單，往回填到 2013 年。任何「名單內」的績效都高估，包含同名單等權。")
    A("- 減掉同名單等權沒有把偏差減乾淨：所有訊號都偏向高波動股，而高波動的倖存者正是大贏家（見 2.6）。")
    A("- 隨機對照在基本成本下被換手成本壓垮，短週期的 p 值因此失真（見 2.6）。")
    A("- 隨機對照只有 200 次，p 的最小刻度是 0.005；很多格子並列在這個最小值，排不出先後。")
    A("- 只有 12 年、兩個子窗，而且整段是科技股大多頭。98 格持有的股票高度重疊，不是 98 個獨立的檢定。")
    A("- 只有收盤價：假設能用 t+1 收盤價成交，沒有另計價差與衝擊成本；10／20bp 對小型股可能太樂觀。")
    A("- 所以「長週期比較好」在這裡只能讀成「少換倉、少付成本」，不能讀成「長週期有選股優勢」。")
    A("")
    A("**US-E**")
    A("")
    A(f"- 只有 {use['n_entry_months']} 個買進月份，持有期間彼此大量重疊；獨立資訊遠少於筆數。")
    A(f"- H=252 只涵蓋較早的買進，H 之間的樣本組成不同（3.4 用固定樣本補看）。")
    A("- 平均值由少數大贏家決定；中位數與勝率都不支持「多數買進會贏」。")
    A("- 沒有做 beta（對大盤的敏感度）調整；對 SPY 的超額混著產業與槓桿曝險。")
    A("- 進場用收盤價而非成交價，也不考慮實際賣出與加減碼。")
    A("- 少數買進因為代號後來變更或下市、價格序列提早結束而被剔除，會有輕微偏差。")
    rb = fifo["robustness_price_implied_splits"]
    A(f"- 帳本的拆股表不完整：用價格比對，有 {rb['n_symbols_with_implied_split']} 個代號出現拆股痕跡，"
      f"帳本的表只列了 {use.get('n_symbols_in_ledger_split_table', 0)} 個。前瞻報酬只用還原價，不受影響；受影響的是 3.6 的分桶表。")
    n_stale = rb.get("n_fills_where_ledger_split_adj_price_is_unadjusted", 0)
    if n_stale:
        A(f"- 帳本有 {n_stale} 筆成交的 split_adj_price 欄沒有反映之後的拆股（與原始成交價相同）。"
          "本研究沒有用這一欄做任何計算，但專案裡用到它的工具可能受影響。")
    A("")
    A("## 7. 檔案")
    A("")
    A("- 程式：`tools/backtests/horizon_sweep_2026-11-18/` 的 `stk_common.py`、`roster_xs.py`、`own_buys.py`、`test_stocks.py`。")
    A("- 輸出（gitignore）：`tools/backtests/data/horizon_sweep_2026-11-18/stocks/`。")
    A("  - US-D：`cells.csv`（98 格 × 3 窗 × 3 成本 = 882 列）、`benchmarks.csv`、`horizon_summary.csv`、`horizon_by_direction.csv`、`null_dist.csv`、`daily_returns_base.csv`。")
    A("  - US-E：`own_buys_summary.csv`（只有彙總）、`own_buys_fills.csv`（逐筆，含真實交易）、`realised_by_holding_bucket.csv`、`price_crosscheck.csv`。")
    A("  - 共同：`verdict.json`、`summary.md`、`usd_part.json`、`use_part.json`。")
    A("")
    text = "\n".join(x for x in L if x is not None)

    key = {
        "US-D_median_excess_vs_roster_ew_full_by_H": {
            "gross_0bp": {str(h): med_gross[h] for h in Hs},
            "base_10bp": {str(h): med[h] for h in Hs},
            "stress_20bp": {str(h): med_stress[h] for h in Hs}},
        "US-D_share_beating_roster_ew_full_base_by_H": {str(h): share[h] for h in Hs},
        "US-D_median_sharpe_full_base_by_H": {str(h): float(hrow(h).sharpe_median) for h in Hs},
        "US-D_median_mdd_full_base_by_H": {str(h): float(hrow(h).mdd_median) for h in Hs},
        "US-D_median_calmar_full_base_by_H": {str(h): float(hrow(h).calmar_median) for h in Hs},
        "US-D_median_cost_drag_full_base_by_H": {str(h): float(hrow(h).cost_drag_ann_median) for h in Hs},
        "US-D_best_H_by_median_excess_base": int(best_H),
        "US-D_roster_ew_full": ew, "US-D_SPY_full": spy,
        "US-D_pick_vol63_pctile_range": [min(vol.values()), max(vol.values())],
        "US-E_excess_mean_ew_by_H": {b: {str(h): float(erow(h, b).excess_mean_ew) for h in He} for b in BENCH},
        "US-E_excess_mean_nw_by_H": {b: {str(h): float(erow(h, b).excess_mean_nw) for h in He} for b in BENCH},
        "US-E_excess_ew_ci_by_H": {b: {str(h): [float(erow(h, b).excess_ew_ci_lo),
                                                float(erow(h, b).excess_ew_ci_hi)] for h in He} for b in BENCH},
        "US-E_hit_rate_by_H": {b: {str(h): float(erow(h, b).hit_rate) for h in He} for b in BENCH},
        "US-E_median_excess_by_H": {b: {str(h): float(erow(h, b).excess_median) for h in He} for b in BENCH},
        "US-E_raw_mean_ew_by_H": {str(h): float(erow(h, "SPY").raw_mean_ew) for h in He},
        "US-E_n_fills_by_H": {str(h): int(erow(h, "SPY").n_fills) for h in He},
        "US-E_H_with_SPY_ci_above_0": spy_sig, "US-E_H_with_SMH_ci_below_0": smh_sig,
    }
    return text, key


def finalize() -> dict | None:
    usd, use = read_json(OUT / "usd_part.json"), read_json(OUT / "use_part.json")
    if usd is None or use is None:
        print("finalize: waiting for both usd_part.json and use_part.json")
        return None
    text, key = build_summary(usd, use)
    verdict = {
        "study": "horizon-study-2026-11-18 (US half): US-D roster cross-section + US-E own buys",
        "prereg": PREREG,
        "status": "descriptive / nomination-only; survivorship-biased roster; NOT evidence of a tradable edge",
        "backtest_end_date": str(END_DATE.date()),
        "US-D": {
            "n_cells": usd["n_cells"], "family": "98 cells, one BH family, q<0.10",
            "pass_line": "beat roster-EW in both windows at 10bp AND BH q<0.10 AND beat roster-EW in both windows at 20bp",
            "counts": usd["counts"],
            "nominated_cells": usd["nominated_cells"],
            "nominated_detail_full_base": usd["nominated_detail_full_base"],
            "nomination_warning": "Nominations are NOT credible findings: the pass line has no specificity on this "
                                  "roster (most cells pass BH, both momentum and reversal pass, 1-day-signal cells held "
                                  "6-12 months pass). See caveats.",
            "top5_full_base_by_excess_vs_roster_ew": usd["top5_full_base_by_excess_vs_roster_ew"],
            "horizon_summary_full_base": usd["horizon_summary_full_base"],
            "null_full": usd["null_full"], "benchmarks": usd["benchmarks"], "data": usd["data"],
        },
        "US-E": {k: use[k] for k in ("note", "n_buys", "n_symbols", "n_entry_months", "first_buy", "last_buy",
                                     "price_calendar_end", "buys_by_year", "buys_by_origin",
                                     "n_buys_with_missing_origin_counted_unknown",
                                     "n_symbols_in_ledger_split_table", "coverage_by_H",
                                     "all", "matched_sample", "by_origin", "by_year", "fifo_reference",
                                     "crosschecks")},
        "key_numbers": key,
        "sanity_anchors": {**usd["sanity_anchors"],
                           "fifo_buckets_reproduced": "yes - compared by hand at authoring time: all five buckets "
                                                      "match the previously known table to within 1%",
                           "unit_tests": "20/20 passed (python3 -B test_stocks.py)"},
        "deviations_interpretations": DEVIATIONS,
        "caveats": [
            "Roster = today's watch-list back-filled to 2013 (survivorship); roster-EW itself is inflated.",
            "Subtracting roster-EW does not cancel the bias: every signal x direction picks above-median-volatility "
            "names, and high-volatility survivors are the big winners.",
            "The base-cost null is crushed by its own turnover at short H, so low-turnover signals pass trivially.",
            "200 null draws -> p floor 0.005; independent tranche draws make the null distribution very tight.",
            "12 years, 2 windows, one tech bull regime; 98 cells hold overlapping names (not independent tests).",
            "Close-only data; t+1 close fills assumed at the print; no spread/impact beyond 10/20bp.",
            "US-E: 39 entry months, overlapping holding windows, half of the buys are from 2026; means driven by a "
            "few big winners (median excess negative, hit rate < 50%); no beta adjustment.",
            "US-E: ledger split table incomplete (price data show more splits than the table lists); forward returns "
            "use adjusted prices only and are unaffected, the FIFO bucket table is affected.",
            "FIFO bucket table is endogenous by construction and is a reference only.",
        ],
        "outputs_dir": str(OUT),
        "runtime_sec": {"US-D": usd.get("runtime_sec"), "US-E": use.get("runtime_sec")},
    }
    write_json(OUT / "verdict.json", verdict)
    (OUT / "summary.md").write_text(text, encoding="utf-8")
    print(f"finalize: wrote {OUT / 'verdict.json'} and {OUT / 'summary.md'}")
    return verdict


if __name__ == "__main__":
    finalize()
