"""隔夜研究 2026-11-19「第一組 XM：看台股做美股」。

預註冊：research/overnight-study-2026-11-19.md（凍結；本程式不加訊號、不調參數）。
輸出（gitignore 路徑）：cells.csv、regressions.csv、timing.csv、reverse.csv、alignment.csv、
sens_smh_*.csv、verdict.json。全部是描述性、只能提名。帳本那一段在 ledger_timing.py。

跑法：python -B run_xm.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import align  # noqa: E402
import common as C  # noqa: E402

SEED = 20261119
N_SHIFT = 1000          # 預註冊：圓形位移 1,000 次
MIN_SHIFT = 21          # 預註冊：位移 >= 21 日
COSTS_BP = [1, 2, 5]    # 預註冊：每邊成本
PASS_COST_BP = 2
RULES = {               # 預註冊 XM-2（凍結）
    "R1": {"kind": "intraday", "sig": lambda z: z > 0.5},
    "R2": {"kind": "intraday", "sig": lambda z: z < -0.5},
    "R3": {"kind": "hold5", "sig": lambda z: z > 1.0},
}
ALIGNMENTS = {"same_date": "z_same", "stale_latest": "z_stale"}
REG_SPECS = {           # 名稱: (y 欄, 是否控制跳空, 重疊天數, 角色)
    "gap~z": ("gap", False, 1, "descriptive"),
    "oc~z+gap": ("oc", True, 1, "XM-1"),
    "oo1~z+gap": ("oo1", True, 1, "descriptive"),
    "oo5~z+gap": ("oo5", True, 5, "XM-1"),
}
# 資料品質：EODHD 的 SMH 還原因子在這兩天有不合理的跳動（見 verdict.json 的 data_quality）
SMH_SUSPECT = [pd.Timestamp("2007-10-12"), pd.Timestamp("2011-10-04")]


INTERPRETATION_CHOICES = [
    "對應美股標的 = 該格要預測的那個美股標的：每一對（美股標的 × 台股預測變數）各算自己的 β、意外與 z。",
    "72 格交易規則、XM-3 進場時點只用『收盤對收盤』版本的台股意外 z；『開盤對收盤』版本只進 regressions.csv（只報告）。",
    "TAIEX_TR 在資料裡沒有開盤價，所以它沒有『開盤對收盤』版本；不拿別的指數代替。",
    "四大半導體等權：3711 於 2018-04-30 才有資料，之前用其餘三檔等權（至少三檔有報酬才算）；不拿前身公司代替。",
    "β 與 z 定義在台股交易日上：β = 過去 252 個台股交易日（不含當天）的 OLS 斜率；z = 意外減過去 252 個意外的平均、除以其標準差（不含當天）。暖身共 504 個台股交易日。",
    "D−1 照字面 = 台股該日之前最後一個美股交易日的單日報酬；台股連休後不累加多個美股交易日。",
    "主分析的有效日 = 美股交易日 D、台股同日有開盤、且 z 存在。R1／R2 與其對照只在有效日上計算，以每年 252 日年化。",
    "另報版本（stale_latest）= 用日期不晚於 D 的最近一個台股交易日；不進及格線，BH 另成一族。",
    "R2『反向版』= 條件反過來（z < −0.5），仍是開盤買、收盤賣；不放空。",
    "R3 = 訊號日開盤買、第 5 個交易日開盤賣；5 批，全部在模擬起點決定一次，之後各自每 5 天決定一次；同一批連續有訊號就不賣再買。",
    "沒持倉的日子（或那一批）領國庫券利率（前一日已知的 IRX ÷ 252）。『贏現金』= 淨年化高於同期間現金年化。",
    "『無條件同一段』= 每個有效日都做同一段並付同樣的每邊成本（R1／R2 每天來回一次；R3 等於一直滿倉、只付進出場成本）。另報更嚴格的旗標：也要贏零成本的無條件版本（pass_strict）。",
    "及格線：每邊 2 bp；Wa、Wb、Wc 三窗各自都要贏無條件、贏現金、淨年化 > 0，全期淨年化 > 0，且 BH q < 0.10。",
    "圓形位移檢定：在有效日序列上把 z 位移 k 天（21 <= k <= 有效日數 − 21，1,000 個不重複的 k），統計量 = 全期每邊 2 bp 的對數總報酬，單尾 p = (1 + 對照組不輸的次數) ÷ 1001；BH 在 72 格上做。",
    "Newey-West 落後期數 = max(floor(4·(n/100)^(2/9)), h−1)；台股休市被剔除的日子前後視為相鄰觀測。",
    "XM-3：起始日 = 每一個美股交易日（z 開始存在之後）；z 不存在的日子（台股休市）不觸發；用還原開盤價；區間 = Newey-West 95%。",
    "XM-3 及格線取嚴格讀法：『等 z < 0』必須同時比『第一天就買』與『三天平均』都好 5 bp 以上，且各自至少兩窗的區間下緣 > 0；另報只比第一天的字面讀法（pass_literal）。",
    "XM-3 帳本段兩種讀法都報：A = 帳本買的剛好是六個標的之一；B = 帳本每個買進日當起始日、套在六個標的上。區間 = 按買進月份分群的 bootstrap。",
    "XM-4：只用『上一個台股收盤之後確實有新的美股交易日』的台股日；美股六個標的各跑一次。",
    "迴歸另報 gap~z 與 oo1~z+gap（預註冊列為目標但 XM-1 沒指定），標為 descriptive，不進任何及格線。",
    "SMH 兩個可疑還原因子日（2007-10-12、2011-10-04）在主結果裡原樣保留；另跑一個拿掉這兩天的敏感度（sens_smh_*.csv，只報告）。",
]

# ── 每個（美股標的 × 台股預測變數）的 z ─────────────────────────────────────────
def build_z(us_frame: pd.DataFrame, tw: dict, cal: pd.DatetimeIndex) -> dict:
    out = {}
    for pred in C.PREDICTORS:
        for rt in ("cc", "oc"):
            r = tw[pred][rt]
            if r.notna().sum() == 0:      # TAIEX_TR 沒有開盤價 → 沒有開盤對收盤
                continue
            s = align.build_surprise(r, us_frame["cc"])
            out[(pred, rt)] = align.map_to_us(s["z"], cal)
    return out


def analysis_frame(us_frame: pd.DataFrame, cash: pd.Series, m: pd.DataFrame, zcol: str) -> pd.DataFrame:
    A = us_frame.copy()
    A["cash"] = cash
    A["z"] = m[zcol]
    A["stale_days"] = m["stale_days"]
    return A[(A.index >= C.START) & (A.index <= C.END)]


# ── XM-1 迴歸 ────────────────────────────────────────────────────────────────
def regressions(A: pd.DataFrame, meta: dict) -> list[dict]:
    rows = []
    for wname, (a, b) in C.WINDOWS.items():
        sub = A[(A.index >= a) & (A.index <= b)]
        for spec, (ycol, use_gap, h, role) in REG_SPECS.items():
            cols = ["z", ycol] + (["gap"] if use_gap and ycol != "gap" else [])
            d = sub[cols].dropna()
            n = len(d)
            row = dict(meta, window=wname, spec=spec, role=role, n=n,
                       first_date=d.index.min().date().isoformat() if n else "",
                       last_date=d.index.max().date().isoformat() if n else "")
            if n < 30:
                rows.append(row)
                continue
            X = [np.ones(n), d["z"].to_numpy()]
            if "gap" in cols[2:]:
                X.append(d["gap"].to_numpy() * 1e4)
            lag = C.nw_lag(n, h)
            r = C.nw_ols(d[ycol].to_numpy() * 1e4, np.column_stack(X), lag)
            row.update(nw_lag=lag, b_z_bp=r["coef"][1], se_z_bp=r["se"][1], t_z=r["t"][1], r2=r["r2"],
                       b_gap=r["coef"][2] if len(X) == 3 else np.nan,
                       t_gap=r["t"][2] if len(X) == 3 else np.nan)
            rows.append(row)
    return rows


# ── XM-2 交易規則 ────────────────────────────────────────────────────────────
def _welch_t(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 5 or len(b) < 5:
        return np.nan
    v = a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)
    return float((a.mean() - b.mean()) / np.sqrt(v)) if v > 0 else np.nan


def simulate_rule(sub: pd.DataFrame, rule: str, cost: float, z_rows: np.ndarray | None = None) -> dict | None:
    """在一個窗內模擬。z_rows 給定時（形狀 (k, 有效日數)）回傳每一列的對數總報酬（位移對照用）。"""
    elig = (sub["z"].notna() & sub["oc"].notna()).to_numpy()
    if elig.sum() == 0:
        return None
    first = int(np.argmax(elig))
    g = sub.iloc[first:]
    e = elig[first:]
    z_e = g["z"].to_numpy()[e]
    Z = z_e[None, :] if z_rows is None else z_rows
    sigfn = RULES[rule]["sig"]
    if RULES[rule]["kind"] == "intraday":
        oc, cash = g["oc"].to_numpy()[e], g["cash"].to_numpy()[e]
        n_per = int(e.sum())
        lt = C.intraday_logtotal(sigfn(Z), oc, cash, cost)
        if z_rows is not None:
            return {"lt": lt}
        allon = np.ones((1, n_per), bool)
        return {"lt": lt[0], "n_per": n_per,
                "lt_uncond": C.intraday_logtotal(allon, oc, cash, cost)[0],
                "lt_uncond_gross": C.intraday_logtotal(allon, oc, cash, 0.0)[0],
                "lt_cash": float(np.log1p(cash).sum()),
                "seg": oc, "sig_e": sigfn(z_e), "g": g, "e": e}
    # hold5：在完整美股日曆上跑；台股休市或 z 不存在的日子不能進場
    n = len(g)
    oo1 = np.nan_to_num(g["oo1"].to_numpy(), nan=0.0)
    cash = g["cash"].to_numpy()
    S = np.zeros((Z.shape[0], n), bool)
    S[:, e] = sigfn(Z)
    lt = C.tranche_logtotal(S, oo1, cash, cost, H=5)
    if z_rows is not None:
        return {"lt": lt}
    U = e[None, :].copy()
    return {"lt": lt[0], "n_per": n - 1,
            "lt_uncond": C.tranche_logtotal(U, oo1, cash, cost, H=5)[0],
            "lt_uncond_gross": C.tranche_logtotal(U, oo1, cash, 0.0, H=5)[0],
            "lt_cash": float(np.log1p(cash[: n - 1]).sum()),
            "seg": g["oo5"].to_numpy()[e], "sig_e": sigfn(z_e), "g": g, "e": e}


def cells(A: pd.DataFrame, meta: dict, seed_key: list[int]) -> list[dict]:
    rows = []
    for ri, rule in enumerate(RULES):
        for wname, (a, b) in C.WINDOWS.items():
            sub = A[(A.index >= a) & (A.index <= b)]
            p_perm = np.nan
            n_shift_used = 0
            for cbp in COSTS_BP:
                c = cbp / 1e4
                r = simulate_rule(sub, rule, c)
                row = dict(meta, rule=rule, window=wname, cost_bp=cbp)
                if r is None:
                    rows.append(dict(row, n_elig=0))
                    continue
                g, e = r["g"], r["e"]
                seg, sig_e = r["seg"], r["sig_e"]
                ok = ~np.isnan(seg)
                n_sess = len(g)
                lt_bh = float(np.log(g["ac"].iloc[-1] / g["ao"].iloc[0]) + 2 * np.log1p(-c))
                if wname == "full" and cbp == PASS_COST_BP:
                    m = int(e.sum())
                    rng = np.random.default_rng([SEED] + seed_key + [ri])
                    ks = align.circular_shifts(m, N_SHIFT, MIN_SHIFT, rng)
                    if len(ks):
                        z_e = g["z"].to_numpy()[e]
                        Zs = z_e[(np.arange(m)[None, :] + ks[:, None]) % m]
                        null = simulate_rule(sub, rule, c, z_rows=Zs)["lt"]
                        p_perm = float((1 + (null >= r["lt"] - 1e-12).sum()) / (len(ks) + 1))
                        n_shift_used = len(ks)
                row.update(
                    first_date=g.index[0].date().isoformat(), last_date=g.index[-1].date().isoformat(),
                    n_sessions=n_sess, n_elig=int(e.sum()), n_signal=int(sig_e.sum()),
                    signal_share=float(sig_e.mean()),
                    cagr_strat=float(C.cagr(r["lt"], r["n_per"])),
                    cagr_uncond=float(C.cagr(r["lt_uncond"], r["n_per"])),
                    cagr_uncond_gross=float(C.cagr(r["lt_uncond_gross"], r["n_per"])),
                    cagr_cash=float(C.cagr(r["lt_cash"], r["n_per"])),
                    cagr_buyhold=float(C.cagr(lt_bh, n_sess)),
                    seg_mean_sig_bp=float(np.mean(seg[ok & sig_e]) * 1e4) if (ok & sig_e).any() else np.nan,
                    seg_mean_all_bp=float(np.mean(seg[ok]) * 1e4) if ok.any() else np.nan,
                    seg_diff_t_naive=_welch_t(seg[ok & sig_e], seg[ok & ~sig_e]),
                    p_perm=p_perm if cbp == PASS_COST_BP else np.nan,
                    n_shift=n_shift_used if cbp == PASS_COST_BP else 0,
                )
                rows.append(row)
    return rows


# ── XM-3 進場時點 ────────────────────────────────────────────────────────────
def timing_improvements(ao: np.ndarray, z: np.ndarray) -> pd.DataFrame:
    """每個起始日 j：三天內擇一天開盤買。回傳改善幅度（bp，正 = 買得比較便宜）與買在第幾天。"""
    n = len(ao)
    j = np.arange(max(n - 2, 0))
    neg = np.nan_to_num(z, nan=1.0) < 0          # z 不存在（台股休市等）→ 不觸發
    day = np.where(neg[j], 0, np.where(neg[j + 1], 1, 2))
    forced = ~neg[j] & ~neg[j + 1] & ~neg[j + 2]
    p_first = ao[j]
    p_wait = ao[j + day]
    p_avg = (ao[j] + ao[j + 1] + ao[j + 2]) / 3.0
    return pd.DataFrame({
        "wait_vs_first": (p_first - p_wait) / p_first * 1e4,
        "avg_vs_first": (p_first - p_avg) / p_first * 1e4,
        "wait_vs_avg": (p_avg - p_wait) / p_first * 1e4,
        "buy_day": day + 1, "forced_day3": forced,
    })


def timing(A: pd.DataFrame, meta: dict) -> list[dict]:
    valid = A["z"].notna() & A["ao"].notna()
    rows = []
    if not valid.any():
        return rows
    g = A.loc[valid.idxmax():]
    imp = timing_improvements(g["ao"].to_numpy(), g["z"].to_numpy())
    imp.index = g.index[: len(imp)]
    for wname, (a, b) in C.WINDOWS.items():
        d = imp[(imp.index >= a) & (imp.index <= b)]
        row = dict(meta, window=wname, n_starts=len(d),
                   first_date=d.index.min().date().isoformat() if len(d) else "",
                   last_date=d.index.max().date().isoformat() if len(d) else "")
        if len(d):
            row.update(share_buy_day1=float((d["buy_day"] == 1).mean()),
                       share_buy_day2=float((d["buy_day"] == 2).mean()),
                       share_buy_day3=float((d["buy_day"] == 3).mean()),
                       share_forced_day3=float(d["forced_day3"].mean()))
            for k in ("wait_vs_first", "avg_vs_first", "wait_vs_avg"):
                r = C.nw_mean(d[k].to_numpy(), h=3)
                row.update({f"{k}_bp": r["mean"], f"{k}_lo": r["lo"], f"{k}_hi": r["hi"]})
        rows.append(row)
    return rows


# ── XM-4 反方向 ──────────────────────────────────────────────────────────────
def reverse(tw: dict, us: dict, cal: pd.DatetimeIndex) -> list[dict]:
    t = tw["0050"]
    tw_cal = t.index
    j = align.prev_us_index(tw_cal, cal)
    prev_tw = np.r_[np.datetime64("NaT", "ns"), tw_cal.values[:-1]]
    us_prev_date = np.full(len(tw_cal), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    us_prev_date[j >= 0] = cal.values[j[j >= 0]]
    fresh = us_prev_date >= prev_tw      # 上一個台股收盤之後，確實有一場新的美股
    n_between = np.searchsorted(cal.values, tw_cal.values, side="left") - np.searchsorted(
        cal.values, prev_tw, side="left")
    rows = []
    for sym in C.TARGETS:
        cc = us[sym]["cc"].to_numpy()
        r_us = np.full(len(tw_cal), np.nan)
        r_us[j >= 0] = cc[j[j >= 0]]
        df = pd.DataFrame({"us": r_us, "gap": t["gap"].to_numpy(), "oc": t["oc"].to_numpy(),
                           "fresh": fresh, "n_between": n_between}, index=tw_cal)
        df = df[(df.index >= C.START) & (df.index <= C.END)]
        for aname, d0 in (("fresh_us_session", df[df["fresh"]]), ("all_incl_stale", df)):
            for wname, (a, b) in C.WINDOWS.items():
                d = d0[(d0.index >= a) & (d0.index <= b)].dropna(subset=["us", "gap", "oc"])
                n = len(d)
                for spec, ycol, ctrl in (("gap~us", "gap", False), ("oc~us", "oc", False), ("oc~us+gap", "oc", True)):
                    row = dict(us_symbol=sym, tw_symbol="0050", alignment=aname, window=wname, spec=spec, n=n,
                               n_multi_us_sessions=int((d["n_between"] > 1).sum()),
                               n_tw_days_stale_excluded=int((~df.loc[(df.index >= a) & (df.index <= b), "fresh"]).sum())
                               if aname == "fresh_us_session" else 0)
                    if n >= 30:
                        X = [np.ones(n), d["us"].to_numpy()]
                        if ctrl:
                            X.append(d["gap"].to_numpy())
                        lag = C.nw_lag(n, 1)
                        r = C.nw_ols(d[ycol].to_numpy(), np.column_stack(X), lag)
                        row.update(nw_lag=lag, b_us=r["coef"][1], t_us=r["t"][1], r2=r["r2"],
                                   b_gap=r["coef"][2] if ctrl else np.nan, t_gap=r["t"][2] if ctrl else np.nan,
                                   corr=float(np.corrcoef(d["us"], d[ycol])[0, 1]),
                                   y_mean_bp=float(d[ycol].mean() * 1e4))
                    rows.append(row)
    return rows


# ── 對齊統計 ─────────────────────────────────────────────────────────────────
def alignment_counts(cal: pd.DatetimeIndex, tw_cal: pd.DatetimeIndex) -> list[dict]:
    m = align.map_to_us(pd.Series(0.0, index=tw_cal), cal)
    rows = []
    for wname, (a, b) in C.WINDOWS.items():
        u = m[(m.index >= a) & (m.index <= b)]
        t = tw_cal[(tw_cal >= a) & (tw_cal <= b)]
        st = u.loc[u["stale_days"] > 0, "stale_days"]
        rows.append(dict(
            window=wname, us_sessions=len(u), us_no_same_date_tw=int((u["stale_days"] != 0).sum()),
            share_no_same_date_tw=float((u["stale_days"] != 0).mean()),
            tw_sessions=len(t), tw_no_same_date_us=int((~t.isin(cal)).sum()),
            stale_1d=int((st == 1).sum()), stale_2d=int((st == 2).sum()), stale_3d=int((st == 3).sum()),
            stale_4d=int((st == 4).sum()), stale_5d_plus=int((st >= 5).sum()),
            stale_mean_days=float(st.mean()) if len(st) else 0.0, stale_max_days=float(st.max()) if len(st) else 0.0))
    return rows


# ── 一個美股標的的全部分析 ────────────────────────────────────────────────────
def analyze_target(ti: int, tgt: str, us_frame: pd.DataFrame, tw: dict, cal, cash, do_timing=True):
    regs, cls, tim = [], [], []
    zs = build_z(us_frame, tw, cal)
    for (pred, rt), m in zs.items():
        pi = C.PREDICTORS.index(pred)
        for ai, (aname, zcol) in enumerate(ALIGNMENTS.items()):
            A = analysis_frame(us_frame, cash, m, zcol)
            meta = dict(target=tgt, predictor=pred, tw_ret_type=rt, alignment=aname)
            if aname == "stale_latest":
                sd = A.loc[A["z"].notna(), "stale_days"]
                meta["n_stale_rows"] = int((sd > 0).sum())
                meta["max_stale_days"] = float(sd.max()) if len(sd) else np.nan
            else:
                meta["n_stale_rows"] = 0
                meta["max_stale_days"] = 0.0
            regs += regressions(A, meta)
            if rt == "cc":                 # 72 格與進場時點只用收盤對收盤版本的 z（見 interpretation choices）
                cls += cells(A, meta, [ti, pi, ai])
                if do_timing:
                    tim += timing(A, meta)
    return regs, cls, tim


def add_pass_columns(cells_df: pd.DataFrame) -> pd.DataFrame:
    """BH q 值（每個對齊版本各自一族 72 格）與預註冊及格線。只有 same_date 版本算數。"""
    df = cells_df.copy()
    key = ["target", "predictor", "rule", "alignment"]
    full2 = df[(df["window"] == "full") & (df["cost_bp"] == PASS_COST_BP)].copy()
    full2["q_bh"] = np.nan
    for aname in ALIGNMENTS:
        mk = full2["alignment"] == aname
        full2.loc[mk, "q_bh"] = C.bh_qvalues(full2.loc[mk, "p_perm"].to_numpy())
    w2 = df[(df["cost_bp"] == PASS_COST_BP)].copy()
    w2["beats_uncond"] = w2["cagr_strat"] > w2["cagr_uncond"]
    w2["beats_uncond_gross"] = w2["cagr_strat"] > w2["cagr_uncond_gross"]
    w2["beats_cash"] = w2["cagr_strat"] > w2["cagr_cash"]
    w2["net_pos"] = w2["cagr_strat"] > 0
    win = w2[w2["window"].isin(["Wa", "Wb", "Wc"])].groupby(key).agg(
        n_win=("window", "size"), win_beats_uncond=("beats_uncond", "sum"),
        win_beats_uncond_gross=("beats_uncond_gross", "sum"),
        win_beats_cash=("beats_cash", "sum"), win_net_pos=("net_pos", "sum")).reset_index()
    full2 = full2.merge(win, on=key, how="left")
    full2["pass_ex_q"] = ((full2["win_beats_uncond"] == 3) & (full2["win_beats_cash"] == 3)
                          & (full2["win_net_pos"] == 3) & (full2["cagr_strat"] > 0))
    full2["pass"] = full2["pass_ex_q"] & (full2["q_bh"] < 0.10)
    full2["pass_strict"] = full2["pass"] & (full2["win_beats_uncond_gross"] == 3)
    add = full2[key + ["q_bh", "win_beats_uncond", "win_beats_uncond_gross", "win_beats_cash", "win_net_pos",
                       "pass_ex_q", "pass", "pass_strict"]]
    return df.merge(add, on=key, how="left")


def add_timing_pass(t: pd.DataFrame) -> pd.DataFrame:
    key = ["target", "predictor", "alignment"]
    w = t[t["window"].isin(["Wa", "Wb", "Wc"])]
    agg = w.groupby(key).agg(
        win_ci_pos_vs_first=("wait_vs_first_lo", lambda s: int((s > 0).sum())),
        win_ci_pos_vs_avg=("wait_vs_avg_lo", lambda s: int((s > 0).sum())),
        win_ci_neg_vs_first=("wait_vs_first_hi", lambda s: int((s < 0).sum()))).reset_index()
    f = t[t["window"] == "full"][key + ["wait_vs_first_bp", "wait_vs_avg_bp"]].rename(
        columns={"wait_vs_first_bp": "full_vs_first", "wait_vs_avg_bp": "full_vs_avg"})
    agg = agg.merge(f, on=key)
    agg["pass_literal"] = (agg["full_vs_first"] > 5) & (agg["win_ci_pos_vs_first"] >= 2)
    agg["pass"] = agg["pass_literal"] & (agg["full_vs_avg"] > 5) & (agg["win_ci_pos_vs_avg"] >= 2)
    return t.merge(agg.drop(columns=["full_vs_first", "full_vs_avg"]), on=key, how="left")


def neutralize_days(frame: pd.DataFrame, dates: list[pd.Timestamp]) -> pd.DataFrame:
    """敏感度用：把可疑日的還原因子跳動從所有報酬裡拿掉（相關觀測設為缺值）。"""
    f = frame.copy()
    idx = f.index
    for d in dates:
        if d not in idx:
            continue
        p = idx.get_loc(d)
        f.iloc[p, f.columns.get_indexer(["cc", "gap"])] = np.nan
        f.iloc[p - 1, f.columns.get_loc("oo1")] = np.nan        # 模擬時缺值視為 0 報酬
        f.iloc[max(p - 5, 0):p, f.columns.get_loc("oo5")] = np.nan
    return f


def main() -> None:
    t0 = time.time()
    C.OUT_DIR.mkdir(parents=True, exist_ok=True)
    tw = C.load_tw()
    us = C.load_us()
    cal = us["SPY"].index
    cash = C.load_cash(cal)
    assert cal.max() <= C.END and all(v.index.max() <= C.END for v in tw.values())
    tw_cal = tw["TAIEX_TR"].index

    al = pd.DataFrame(alignment_counts(cal, tw_cal))
    al.to_csv(C.OUT_DIR / "alignment.csv", index=False)

    regs, cls, tim = [], [], []
    for ti, tgt in enumerate(C.TARGETS):
        r, c, t = analyze_target(ti, tgt, us[tgt], tw, cal, cash)
        regs += r
        cls += c
        tim += t
        print(f"[{time.time() - t0:6.1f}s] {tgt} done", flush=True)
    regs = pd.DataFrame(regs)
    cls = add_pass_columns(pd.DataFrame(cls))
    tim = add_timing_pass(pd.DataFrame(tim))
    rev = pd.DataFrame(reverse(tw, us, cal))

    # 敏感度：SMH 兩個可疑日拿掉（只報告；不改主結果）
    smh2 = neutralize_days(us["SMH"], SMH_SUSPECT)
    r2, c2, _ = analyze_target(C.TARGETS.index("SMH"), "SMH", smh2, tw, cal, cash, do_timing=False)
    sens_regs = pd.DataFrame(r2)
    merged = pd.concat([cls[cls["target"] != "SMH"].drop(columns=[c for c in cls.columns if c in (
        "q_bh", "win_beats_uncond", "win_beats_uncond_gross", "win_beats_cash", "win_net_pos",
        "pass_ex_q", "pass", "pass_strict")]), pd.DataFrame(c2)], ignore_index=True)
    sens_cells = add_pass_columns(merged)
    sens_cells = sens_cells[sens_cells["target"] == "SMH"]

    regs.to_csv(C.OUT_DIR / "regressions.csv", index=False)
    cls.to_csv(C.OUT_DIR / "cells.csv", index=False)
    tim.to_csv(C.OUT_DIR / "timing.csv", index=False)
    rev.to_csv(C.OUT_DIR / "reverse.csv", index=False)
    sens_regs.to_csv(C.OUT_DIR / "sens_smh_regressions.csv", index=False)
    sens_cells.to_csv(C.OUT_DIR / "sens_smh_cells.csv", index=False)

    # ── verdict ──
    main_full = cls[(cls["alignment"] == "same_date") & (cls["window"] == "full") & (cls["cost_bp"] == PASS_COST_BP)]
    stale_full = cls[(cls["alignment"] == "stale_latest") & (cls["window"] == "full") & (cls["cost_bp"] == PASS_COST_BP)]
    sens_full = sens_cells[(sens_cells["alignment"] == "same_date") & (sens_cells["window"] == "full")
                           & (sens_cells["cost_bp"] == PASS_COST_BP)]
    prim = regs[(regs["alignment"] == "same_date") & (regs["tw_ret_type"] == "cc") & regs["window"].isin(["Wa", "Wb", "Wc"])]

    def reg_summary(spec: str, d: pd.DataFrame = prim) -> dict:
        x = d[d["spec"] == spec].dropna(subset=["t_z"])
        piv = x.pivot_table(index=["target", "predictor"], columns="window", values="t_z")
        same_sign_sig = int(((piv.abs() > 1.96).all(axis=1) & ((piv > 0).all(axis=1) | (piv < 0).all(axis=1))).sum())
        return dict(n_regressions=int(len(x)), n_abs_t_gt_1_96=int((x["t_z"].abs() > 1.96).sum()),
                    n_t_gt_1_96=int((x["t_z"] > 1.96).sum()), n_t_lt_minus_1_96=int((x["t_z"] < -1.96).sum()),
                    expected_by_chance=round(0.05 * len(x), 1), max_abs_t=float(x["t_z"].abs().max()),
                    median_b_z_bp=float(x["b_z_bp"].median()),
                    n_pairs_significant_same_sign_all_3_windows=same_sign_sig, n_pairs=int(len(piv)))

    tmain = tim[(tim["alignment"] == "same_date") & (tim["window"] == "full")]
    verdict = {
        "study": "XM (Taiwan session -> US session)",
        "prereg": "research/overnight-study-2026-11-19.md",
        "nature": "descriptive / nomination-only",
        "end_date": C.END.date().isoformat(),
        "data_max_dates": {"us": cal.max().date().isoformat(), "tw": tw_cal.max().date().isoformat()},
        "runtime_sec": round(time.time() - t0, 1),
        "alignment_counts": al.to_dict(orient="records"),
        "XM1": {"oc~z+gap": reg_summary("oc~z+gap"), "oo5~z+gap": reg_summary("oo5~z+gap"),
                "gap~z (descriptive)": reg_summary("gap~z")},
        "XM2": {
            "n_cells": int(len(main_full)), "cost_bp_per_side": PASS_COST_BP, "n_shift": N_SHIFT,
            "n_pass": int(main_full["pass"].sum()), "n_pass_strict": int(main_full["pass_strict"].sum()),
            "n_pass_ignoring_q": int(main_full["pass_ex_q"].sum()),
            "n_q_lt_0_10": int((main_full["q_bh"] < 0.10).sum()), "min_q": float(main_full["q_bh"].min()),
            "min_p": float(main_full["p_perm"].min()), "n_p_lt_0_05": int((main_full["p_perm"] < 0.05).sum()),
            "n_net_cagr_pos_full": int((main_full["cagr_strat"] > 0).sum()),
            "n_beats_cash_all_3_windows": int((main_full["win_beats_cash"] == 3).sum()),
            "n_beats_uncond_all_3_windows": int((main_full["win_beats_uncond"] == 3).sum()),
            "n_beats_uncond_gross_all_3_windows": int((main_full["win_beats_uncond_gross"] == 3).sum()),
            "by_rule": {r: {"n_pass": int(g["pass"].sum()), "n_pass_ignoring_q": int(g["pass_ex_q"].sum()),
                            "median_cagr_strat": float(g["cagr_strat"].median()),
                            "median_cagr_uncond": float(g["cagr_uncond"].median()),
                            "median_cagr_cash": float(g["cagr_cash"].median()),
                            "min_p": float(g["p_perm"].min())} for r, g in main_full.groupby("rule")},
            "passing_cells": main_full.loc[main_full["pass"], ["target", "predictor", "rule"]].to_dict(orient="records"),
            "stale_version_report_only": {"n_pass": int(stale_full["pass"].sum()),
                                          "n_pass_ignoring_q": int(stale_full["pass_ex_q"].sum()),
                                          "min_q": float(stale_full["q_bh"].min())},
            "sens_smh_suspect_days_report_only": {"n_cells": int(len(sens_full)), "n_pass": int(sens_full["pass"].sum()),
                                                  "n_pass_ignoring_q": int(sens_full["pass_ex_q"].sum())},
        },
        "XM3": {
            "n_cells": int(len(tmain)), "n_pass": int(tmain["pass"].sum()),
            "n_pass_literal_vs_first_only": int(tmain["pass_literal"].sum()),
            "mean_wait_vs_first_bp_range": [float(tmain["wait_vs_first_bp"].min()), float(tmain["wait_vs_first_bp"].max())],
            "mean_wait_vs_avg_bp_range": [float(tmain["wait_vs_avg_bp"].min()), float(tmain["wait_vs_avg_bp"].max())],
            "mean_avg_vs_first_bp_range": [float(tmain["avg_vs_first_bp"].min()), float(tmain["avg_vs_first_bp"].max())],
            "ledger_part": "see ledger_timing.csv / ledger_timing.json in this directory (git-ignored)",
        },
        "XM4": "report-only; see reverse.csv",
        "interpretation_choices": INTERPRETATION_CHOICES,
        "data_quality": {
            "TAIEX_TR_has_no_open": True,
            "SMH_suspect_adjustment_days": [d.date().isoformat() for d in SMH_SUSPECT],
            "us_stock_targets_start": "2007-01-03 (TSM/NVDA/AMD); z needs 504 Taiwan sessions of warm-up",
            "tej_start": "2005-01-03 (2330/2454/2303); 3711 from 2018-04-30",
            "first_valid_z_date": {f"{t}|{p}": str(g["first_date"].min()) for (t, p), g in
                                   main_full.groupby(["target", "predictor"])},
        },
    }
    (C.OUT_DIR / "verdict.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=2, default=str))
    print(json.dumps({k: verdict[k] for k in ("runtime_sec", "XM1", "XM2", "XM3")}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
