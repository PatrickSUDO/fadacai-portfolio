"""第二組 PF：帳本與持有期規則（診斷，沒有及格線）。

預註冊：research/overnight-study-2026-11-19.md 的「第二組 PF」（凍結）。
  PF-1  R14（新倉 30 個日曆日最短持有）有沒有被遵守
  PF-2  最短持有 N ∈ {21, 63, 126} 個交易日的反事實（含硬停損版）
  PF-3  每筆買進抱 63／126 個交易日對 SMH、QQQ 的超額，按是否半導體／AI 硬體分組
  PF-4  規則建議（由 pf_report.py 依這裡算出的數字產生）

隱私：本檔不含任何帳戶資料。所有輸出只寫在 gitignore 的
tools/backtests/data/overnight_2026-11-19/ledger/ 之下。
不連網、不寫任何快取、不呼叫專案內會抓資料或寫檔的函式
（只借用 tools/trade_ledger.py 的 SPLITS 表、SEMI_AI 集合與 split_adjust_qty 純函式）。

用法：python -B pf_run.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger_common as C  # noqa: E402

READING_FILE = "r14_exception_reading.json"     # 人工判讀（放在 gitignore 的結果目錄，不在程式裡）
UNRECORDED = "未記錄"

# 從 journal 文字自動貼的初步標籤（只是關鍵字比對；最後以人工判讀檔為準）
AUTO_PATTERNS = [
    ("journal 明文記為 R14 bypass", re.compile(r"R14\s*bypass|bypass.{0,8}R14|R14.{0,24}(推翻|違反)", re.I)),
    ("例外 1：thesis 證偽條件", re.compile(r"thesis-close|thesis[^，。；\n]{0,16}(證偽|已破|被觸發)|證偽條件", re.I)),
    ("例外 2：財報／8-K 爆雷", re.compile(r"爆雷|8-K", re.I)),
    ("例外 3：旗標 forced", re.compile(r"forced", re.I)),
]
JOURNAL_KEYWORDS = re.compile(
    r"R14|R16|R23|R36|清倉|出清|賣|砍|停損|出場|bypass|例外|thesis|證偽|forced|旗標|失守|裁決")


# ══ PF-1 ═══════════════════════════════════════════════════════════════════
def r14_episodes(fills: list[dict], factors: dict, effective: str = C.R14_EFFECTIVE,
                 lock_days: int = C.R14_DAYS) -> list[dict]:
    """由零建倉的部位（建倉日 >= effective）與其 30 個日曆日窗內的賣出。
    「由零」沿用 tools/position_guard.py 的口徑：只看帳本、持股不低於 0、<= 1e-6 視為零。
    窗內 = (賣出日 − 建倉日) 的日曆天數 < lock_days（guard 的鎖也是 days < 30）。
    違反 = 窗內清倉，或窗內累計賣出 > 截至該筆的累計買進的一半。"""
    held: dict[str, float] = {}
    active: dict[str, dict] = {}
    done: list[dict] = []
    for f in fills:
        sym = f["symbol"]
        q = abs(float(f["qty"])) * factors[f["row"]]
        h = held.get(sym, 0.0)
        if f["side"] == "BOUGHT":
            if h <= 1e-6:
                if sym in active:
                    done.append(active.pop(sym))
                active[sym] = {"symbol": sym, "start_date": f["date"], "start_row": f["row"],
                               "start_bucket": f.get("bucket"), "start_origin": f["origin"],
                               "bought_cum": 0.0, "sold_in_window": 0.0, "sold_total": 0.0,
                               "window_sell_rows": [], "n_sells_in_window": 0,
                               "breach": "", "breach_date": "", "breach_days": None,
                               "max_sold_frac_in_window": 0.0, "closed_date": "",
                               "closed_days": None, "n_buys": 0}
            ep = active[sym]
            ep["bought_cum"] += q
            ep["n_buys"] += 1
            held[sym] = h + q
            continue
        new_h = max(0.0, h - q)
        held[sym] = new_h
        ep = active.get(sym)
        if ep is None:
            continue
        days = (pd.Timestamp(f["date"]) - pd.Timestamp(ep["start_date"])).days
        ep["sold_total"] += min(q, h)
        if days < lock_days:
            ep["sold_in_window"] += min(q, h)
            ep["n_sells_in_window"] += 1
            ep["window_sell_rows"].append(f["row"])
            frac = ep["sold_in_window"] / ep["bought_cum"] if ep["bought_cum"] > 0 else 0.0
            ep["max_sold_frac_in_window"] = max(ep["max_sold_frac_in_window"], frac)
            if not ep["breach"]:
                if new_h <= 1e-6:
                    ep["breach"] = "清倉"
                elif frac > 0.5:
                    ep["breach"] = "減碼過半"
                if ep["breach"]:
                    ep["breach_date"], ep["breach_days"] = f["date"], days
        if new_h <= 1e-6:
            ep["closed_date"], ep["closed_days"] = f["date"], days
            done.append(active.pop(sym))
    done.extend(active.values())
    return sorted([e for e in done if e["start_date"] >= effective],
                  key=lambda e: (e["start_date"], e["start_row"]))


def symbol_class(sym: str, roster: dict, bucket) -> str:
    if sym in (roster.get("cash_equivalents") or []):
        return "現金等價物"
    if sym in (roster.get("benchmark_parking") or []) or sym in (roster.get("benchmark_slots") or []):
        return "基準停泊 ETF"
    if bucket == "hedge" or sym in (roster.get("passive_sleeve") or []):
        return "避險部位"
    return "個股部位"


def journal_evidence(symbol: str, start: str, end: str, journal_dir: Path | None = None,
                     pad_days: int = 3, max_chars: int = 220) -> list[str]:
    """journal 裡日期落在 [start, end + pad] 、提到該代號且含決策關鍵字的列。"""
    journal_dir = C.JOURNAL_DIR if journal_dir is None else journal_dir
    lo, hi = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=pad_days)
    pat = re.compile(rf"(?<![A-Za-z]){re.escape(symbol)}(?![A-Za-z])")
    out = []
    for path in sorted(journal_dir.glob("*.md")):
        try:
            d = pd.Timestamp(path.stem)
        except ValueError:
            continue
        if not (lo <= d <= hi):
            continue
        for raw in path.read_text(encoding="utf-8").split("\n"):
            line = raw.strip()
            if pat.search(line) and JOURNAL_KEYWORDS.search(line):
                out.append(f"[{path.stem}] {line[:max_chars]}")
    return out


def label_category(label) -> str:
    """把標籤歸成五類，用來比較「關鍵字自動標籤」與「人工判讀」是否同一類。"""
    t = str(label or "")
    if "bypass" in t.lower():
        return "bypass"
    for n in ("1", "2", "3"):
        if f"例外 {n}" in t:
            return f"exception_{n}"
    if "不適用" in t:
        return "not_applicable"
    return "unrecorded"


def auto_label(lines: list[str]) -> str:
    text = "\n".join(lines)
    for label, pat in AUTO_PATTERNS:
        if pat.search(text):
            return label
    return UNRECORDED


def pf1(fills: list[dict], factors: dict, pieces: pd.DataFrame, seeded_before: dict,
        last_ledger_date: str) -> tuple[pd.DataFrame, dict]:
    roster = json.loads(C.ROSTER_JSON.read_text(encoding="utf-8"))
    reading_path = C.OUT / READING_FILE
    reading = json.loads(reading_path.read_text(encoding="utf-8")) if reading_path.exists() else {}
    by_row = {f["row"]: f for f in fills}
    rows = []
    for ep in r14_episodes(fills, factors):
        sym = ep["symbol"]
        win = pieces[pieces.sell_row.isin(ep["window_sell_rows"])]
        elapsed = (pd.Timestamp(last_ledger_date) - pd.Timestamp(ep["start_date"])).days
        ev_end = ep["breach_date"] or ep["start_date"]
        jl = journal_evidence(sym, ep["start_date"], ev_end) if ep["breach"] else []
        sells = [by_row[r] for r in ep["window_sell_rows"]]
        key = f"{sym}|{ep['start_date']}"
        rd = reading.get(key, {})
        rows.append({
            "symbol": sym, "class": symbol_class(sym, roster, ep["start_bucket"]),
            "ledger_bucket_at_entry": ep["start_bucket"] or "",
            "entry_origin": ep["start_origin"],
            "established": ep["start_date"],
            "window_end_exclusive": str((pd.Timestamp(ep["start_date"])
                                         + pd.Timedelta(days=C.R14_DAYS)).date()),
            "window_complete": bool(elapsed >= C.R14_DAYS or ep["closed_date"]),
            "pre_ledger_inventory_before_entry_shares": round(float(seeded_before.get(ep["start_row"], 0.0)), 4),
            "n_buys_in_episode": ep["n_buys"],
            "n_sells_in_window": ep["n_sells_in_window"],
            "max_sold_fraction_in_window": round(ep["max_sold_frac_in_window"], 4),
            "breach": ep["breach"] or "無",
            "breach_date": ep["breach_date"], "breach_days_after_entry": ep["breach_days"],
            "closed_date": ep["closed_date"], "closed_days_after_entry": ep["closed_days"],
            "window_sell_proceeds": round(float(win.proceeds.sum()), 2),
            "window_sell_cost": round(float(win.cost.sum()), 2),
            "window_sell_realised_pnl": round(float(win.pnl.sum()), 2),
            "sell_origins": "|".join(sorted({s["origin"] for s in sells})),
            "exception_auto_label": auto_label(jl) if ep["breach"] else "",
            "exception_reading": (rd.get("label") or UNRECORDED) if ep["breach"] else "",
            "exception_reading_reason": rd.get("reason", "") if ep["breach"] else "",
            "ledger_evidence": " ‖ ".join(str(s.get("origin_evidence") or "")[:260] for s in sells)
            if ep["breach"] else "",
            "journal_evidence": " ‖ ".join(jl[-14:]),      # 最接近賣出日的 14 列
        })
    df = pd.DataFrame(rows)
    stock = df[df["class"] == "個股部位"] if len(df) else df
    br = df[df.breach != "無"] if len(df) else df
    br_stock = br[br["class"] == "個股部位"] if len(br) else br
    info = {
        "rule_effective": C.R14_EFFECTIVE, "window_rule": f"calendar days since entry < {C.R14_DAYS}",
        "n_new_positions": int(len(df)),
        "n_new_positions_by_class": df["class"].value_counts().to_dict() if len(df) else {},
        "n_window_complete": int(df.window_complete.sum()) if len(df) else 0,
        "n_window_still_open": int((~df.window_complete).sum()) if len(df) else 0,
        "n_breach_all": int(len(br)),
        "n_breach_stock_positions": int(len(br_stock)),
        "n_breach_non_stock": int(len(br) - len(br_stock)),
        "breach_type_stock": br_stock.breach.value_counts().to_dict() if len(br_stock) else {},
        "exception_reading_stock": br_stock.exception_reading.value_counts().to_dict()
        if len(br_stock) else {},
        "exception_auto_label_stock": br_stock.exception_auto_label.value_counts().to_dict()
        if len(br_stock) else {},
        "exception_category_stock": br_stock.exception_reading.map(label_category).value_counts().to_dict()
        if len(br_stock) else {},
        "n_reading_category_differs_from_auto_label": int(
            (br_stock.exception_reading.map(label_category)
             != br_stock.exception_auto_label.map(label_category)).sum()) if len(br_stock) else 0,
        "breach_realised_pnl_stock": round(float(br_stock.window_sell_realised_pnl.sum()), 2)
        if len(br_stock) else 0.0,
        "breach_proceeds_stock": round(float(br_stock.window_sell_proceeds.sum()), 2)
        if len(br_stock) else 0.0,
        "breach_n_losing_stock": int((br_stock.window_sell_realised_pnl < 0).sum())
        if len(br_stock) else 0,
        "breach_realised_pnl_non_stock": round(
            float(br.window_sell_realised_pnl.sum() - br_stock.window_sell_realised_pnl.sum()), 2)
        if len(br) else 0.0,
        "n_stock_positions": int(len(stock)),
        "n_stock_window_complete": int(stock.window_complete.sum()) if len(stock) else 0,
        "n_stock_trim_in_window_not_breach": int(((stock.breach == "無")
                                                  & (stock.n_sells_in_window > 0)).sum())
        if len(stock) else 0,
        "n_stock_closed_on_day_30_to_34": int(
            stock.closed_days_after_entry.between(C.R14_DAYS, C.R14_DAYS + 4).sum())
        if len(stock) else 0,
        "n_stock_closed_exactly_on_day_30": int((stock.closed_days_after_entry == C.R14_DAYS).sum())
        if len(stock) else 0,
        "n_entries_with_pre_ledger_inventory_over_1_share": int(
            (df.pre_ledger_inventory_before_entry_shares > 1.0).sum()) if len(df) else 0,
        "reading_file_present": bool(reading),
    }
    return df, info


# ══ PF-2 ═══════════════════════════════════════════════════════════════════
def counterfactual_piece(proceeds: float, cost: float, arr: np.ndarray, i_buy: int, i_sell: int,
                         i_T: int, alt: dict[str, np.ndarray]) -> dict:
    """一段配對的反事實。全部以「T = 買進後第 N 個交易日收盤」時的美元計。
      實際   ：賣出拿回 proceeds，之後放在 alt 到 T。
      反事實 ：不賣，抱到 T 收盤；價值 = proceeds × 還原價(T) ÷ 還原價(賣出日)。
      差額   = 反事實 − 實際（正 = 規定抱滿 N 日會比較好）。
      硬停損版：收盤 ÷ 成本 <= 0.75 的第一天收盤出場，之後的錢同樣放 alt 到 T。
               收盤 ÷ 成本 = (proceeds ÷ cost) × 還原價(t) ÷ 還原價(賣出日)。
    alt 的陣列是對齊同一日曆的價格；CASH 以 None 表示（報酬 0）。"""
    def alt_ratio(name, a, b):
        s = alt[name]
        return 1.0 if s is None else float(s[b] / s[a])

    g = float(arr[i_T] / arr[i_sell])
    out = {"hold_ratio": g}
    path = arr[i_buy:i_T + 1] / arr[i_sell] * (proceeds / cost)
    hit = np.where(np.isfinite(path) & (path <= C.STOP_LEVEL))[0]
    t_stop = int(i_buy + hit[0]) if len(hit) else None
    out["stop_triggered"] = t_stop is not None
    out["stop_before_actual_sale"] = bool(t_stop is not None and t_stop < i_sell)
    out["stop_path_incomplete"] = bool(not np.isfinite(arr[i_buy:i_T + 1]).all())
    for name in alt:
        actual = proceeds * alt_ratio(name, i_sell, i_T)
        out[f"diff_{name}"] = proceeds * g - actual
        if t_stop is None:
            out[f"diffstop_{name}"] = out[f"diff_{name}"]
        else:
            v_stop = proceeds * float(arr[t_stop] / arr[i_sell])
            out[f"diffstop_{name}"] = v_stop * alt_ratio(name, t_stop, i_T) - actual
    return out


def pf2_pieces(pieces: pd.DataFrame, cal: pd.DatetimeIndex, last_px: int, book: dict,
               alt: dict[str, np.ndarray]) -> pd.DataFrame:
    """每一段配對 × 每個 N 一列。status：ok / held_at_least_N / horizon_past_data_end / no_price_cover。"""
    pos = {d: i for i, d in enumerate(cal)}
    recs = []
    for p in pieces.itertuples(index=False):
        ib, isell = pos[pd.Timestamp(p.buy_date)], pos[pd.Timestamp(p.sell_date)]
        held = isell - ib
        for N in C.N_LIST:
            rec = {"symbol": p.symbol, "buy_row": p.buy_row, "sell_row": p.sell_row,
                   "buy_date": p.buy_date, "sell_date": p.sell_date, "held_sessions": held,
                   "N": N, "proceeds": p.proceeds, "cost": p.cost, "pnl": p.pnl,
                   "buy_origin": p.buy_origin, "sell_origin": p.sell_origin,
                   "buy_year": p.buy_date[:4], "buy_month": p.buy_date[:7], "source": ""}
            iT = ib + N
            if held >= N:
                rec["status"] = "held_at_least_N"
            elif iT > last_px or isell > last_px:
                rec["status"] = "horizon_past_data_end"
            else:
                g, src, arr = C.price_ratio(book.get(p.symbol, []), isell, iT)
                if arr is None or p.cost <= 0 or p.proceeds <= 0:
                    rec["status"] = "no_price_cover"
                else:
                    rec["status"] = "ok"
                    rec["source"] = src
                    rec.update(counterfactual_piece(p.proceeds, p.cost, arr, ib, isell, iT, alt))
            recs.append(rec)
    return pd.DataFrame(recs)


def pf2_summarise(pp: pd.DataFrame, fifo_variant: str) -> pd.DataFrame:
    rows = []
    cuts = [("all", "all", lambda d: d)]
    for y in sorted(pp.buy_year.unique()):
        cuts.append(("buy_year", y, lambda d, y=y: d[d.buy_year == y]))
    for o in ["system", "user", "unknown"]:
        cuts.append(("buy_origin", o, lambda d, o=o: d[d.buy_origin == o]))
    for o in ["system", "user", "unknown"]:
        cuts.append(("sell_origin_supplementary", o, lambda d, o=o: d[d.sell_origin == o]))
    for N in C.N_LIST:
        dN = pp[pp.N == N]
        for cut_type, cut_value, fn in cuts:
            d = fn(dN)
            short = d[d.status != "held_at_least_N"]
            ok = d[d.status == "ok"]
            base = {"fifo_variant": fifo_variant, "N": N, "cut_type": cut_type, "cut_value": cut_value,
                    "n_pieces_held_under_N": int(len(short)),
                    "n_excluded_horizon_past_data_end": int((d.status == "horizon_past_data_end").sum()),
                    "n_excluded_no_price_cover": int((d.status == "no_price_cover").sum()),
                    "n_pieces": int(len(ok)), "n_buy_lots": int(ok.buy_row.nunique()),
                    "n_symbols": int(ok.symbol.nunique()), "n_buy_months": int(ok.buy_month.nunique()),
                    "proceeds_sum": round(float(ok.proceeds.sum()), 2),
                    "realised_pnl_sum": round(float(ok.pnl.sum()), 2)}
            for version, pref in (("no_stop", "diff_"), ("hard_stop_25pct", "diffstop_")):
                for a in C.ALTS:
                    r = dict(base, version=version, alt=a)
                    if len(ok):
                        x = ok[pref + a].to_numpy(dtype=float)
                        lo, hi, M = C.cluster_boot_total(x, ok.buy_month.to_numpy())
                        r.update({"diff_total": round(float(x.sum()), 2),
                                  "diff_over_proceeds": float(x.sum() / ok.proceeds.sum()),
                                  "ci_lo": lo, "ci_hi": hi,
                                  "share_pieces_positive": float((x > 0).mean()),
                                  "n_stop_triggered": int(ok.stop_triggered.sum())
                                  if version != "no_stop" else 0,
                                  "n_stop_before_actual_sale": int(ok.stop_before_actual_sale.sum())
                                  if version != "no_stop" else 0,
                                  "n_stop_path_incomplete": int(ok.stop_path_incomplete.sum())
                                  if version != "no_stop" else 0})
                    rows.append(r)
    cols = ["fifo_variant", "version", "N", "alt", "cut_type", "cut_value", "n_pieces_held_under_N",
            "n_excluded_horizon_past_data_end", "n_excluded_no_price_cover", "n_pieces", "n_buy_lots",
            "n_symbols", "n_buy_months", "proceeds_sum", "realised_pnl_sum", "diff_total",
            "diff_over_proceeds", "ci_lo", "ci_hi", "share_pieces_positive", "n_stop_triggered",
            "n_stop_before_actual_sale", "n_stop_path_incomplete"]
    return pd.DataFrame(rows).reindex(columns=cols)


def prewritten_reading(summ: pd.DataFrame, fifo_variant: str, version: str) -> dict:
    """事前寫定的讀法（N = 63）：差額為正、區間不含 0、對 SPY 與 SMH 都成立、
    2025 與 2026 兩個買進年度子樣本同向（本研究的保守讀法：兩年都要是正的）。"""
    s = summ[(summ.fifo_variant == fifo_variant) & (summ.version == version) & (summ.N == 63)]
    out = {"fifo_variant": fifo_variant, "version": version, "N": 63, "checks": {}}
    ok_all = True
    for a in ("SPY", "SMH"):
        tot = s[(s.alt == a) & (s.cut_type == "all")].iloc[0]
        yr = {y: s[(s.alt == a) & (s.cut_type == "buy_year") & (s.cut_value == y)] for y in ("2025", "2026")}
        yv = {y: (float(v.diff_total.iloc[0]) if len(v) and pd.notna(v.diff_total.iloc[0]) else None)
              for y, v in yr.items()}
        c = {"diff_total": float(tot.diff_total), "ci_lo": float(tot.ci_lo), "ci_hi": float(tot.ci_hi),
             "n_pieces": int(tot.n_pieces),
             "positive": bool(tot.diff_total > 0),
             "ci_excludes_zero": bool(tot.ci_lo > 0 or tot.ci_hi < 0),
             "diff_2025": yv["2025"], "diff_2026": yv["2026"],
             "years_same_sign": bool(yv["2025"] is not None and yv["2026"] is not None
                                     and np.sign(yv["2025"]) == np.sign(yv["2026"])
                                     and yv["2025"] != 0),
             "years_both_positive": bool(yv["2025"] is not None and yv["2026"] is not None
                                         and yv["2025"] > 0 and yv["2026"] > 0)}
        c["all_conditions"] = bool(c["positive"] and c["ci_excludes_zero"] and c["ci_lo"] > 0
                                   and c["years_both_positive"])
        ok_all = ok_all and c["all_conditions"]
        out["checks"][a] = c
    out["extend_r14_to_63_supported"] = bool(ok_all)
    return out


# ══ PF-3 ═══════════════════════════════════════════════════════════════════
def pf3_table(fills: list[dict], cal: pd.DatetimeIndex, last_px: int, book: dict,
              bench: dict[str, np.ndarray], semi: set, new_rows: set) -> pd.DataFrame:
    """每筆買進 × 每個 H 一列。進場價 = 買進日還原收盤（與 2026-11-18 研究相同）。"""
    pos = {d: i for i, d in enumerate(cal)}
    recs = []
    for f in fills:
        if f["side"] != "BOUGHT":
            continue
        i = pos[pd.Timestamp(f["date"])]
        for H in C.H_LIST:
            rec = {"row": f["row"], "symbol": f["symbol"], "date": f["date"], "month": f["date"][:7],
                   "notional": float(f["notional"]), "H": H,
                   "group": "半導體／AI 硬體" if f["symbol"].upper() in semi else "其他",
                   "period": "R35 之後" if f["date"] >= C.R35_EFFECTIVE else "R35 之前",
                   "is_new_position": f["row"] in new_rows, "ret": np.nan, "source": ""}
            if i + H > last_px:
                rec["status"] = "horizon_past_data_end"
            else:
                g, src, _ = C.price_ratio(book.get(f["symbol"], []), i, i + H)
                if not np.isfinite(g):
                    rec["status"] = "no_price_cover"
                else:
                    rec["status"], rec["source"], rec["ret"] = "ok", src, g - 1.0
                    for b, arr in bench.items():
                        rec[f"bench_{b}"] = float(arr[i + H] / arr[i] - 1.0)
                        rec[f"ex_{b}"] = rec["ret"] - rec[f"bench_{b}"]
            recs.append(rec)
    return pd.DataFrame(recs)


def pf3_summarise(ft: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for period in ["全部", "R35 之前", "R35 之後"]:
        dp = ft if period == "全部" else ft[ft.period == period]
        for group in ["全部", "半導體／AI 硬體", "其他"]:
            dg = dp if group == "全部" else dp[dp.group == group]
            for H in C.H_LIST:
                d = dg[dg.H == H]
                ok = d[d.status == "ok"]
                base = {"period": period, "group": group, "H": H, "n_buys_in_cut": int(len(d)),
                        "n_new_position_buys_in_cut": int(d.is_new_position.sum()),
                        "n_ok": int(len(ok)),
                        "n_dropped_horizon_past_data_end": int((d.status == "horizon_past_data_end").sum()),
                        "n_dropped_no_price_cover": int((d.status == "no_price_cover").sum()),
                        "n_symbols": int(ok.symbol.nunique()), "n_months": int(ok.month.nunique())}
                for b in C.HURDLE_BENCH:
                    r = dict(base, benchmark=b)
                    if len(ok):
                        ex = ok[f"ex_{b}"].to_numpy(dtype=float)
                        w = ok.notional.to_numpy(dtype=float)
                        ci = C.cluster_boot_mean(ex, w, ok.month.to_numpy())
                        r.update({"raw_mean_ew": float(ok.ret.mean()),
                                  "bench_mean_ew": float(ok[f"bench_{b}"].mean()),
                                  "excess_mean_ew": float(ex.mean()),
                                  "excess_ew_ci_lo": ci["ew_lo"], "excess_ew_ci_hi": ci["ew_hi"],
                                  "excess_mean_nw": float(np.average(ex, weights=w)),
                                  "excess_nw_ci_lo": ci["nw_lo"], "excess_nw_ci_hi": ci["nw_hi"],
                                  "excess_median": float(np.median(ex)),
                                  "hit_rate": float((ex > 0).mean())})
                    rows.append(r)
    cols = ["period", "group", "H", "benchmark", "n_buys_in_cut", "n_new_position_buys_in_cut", "n_ok",
            "n_dropped_horizon_past_data_end", "n_dropped_no_price_cover", "n_symbols", "n_months",
            "raw_mean_ew", "bench_mean_ew", "excess_mean_ew", "excess_ew_ci_lo", "excess_ew_ci_hi",
            "excess_mean_nw", "excess_nw_ci_lo", "excess_nw_ci_hi", "excess_median", "hit_rate"]
    return pd.DataFrame(rows).reindex(columns=cols)


# ══ helpers ════════════════════════════════════════════════════════════════
def pre_ledger_seeds(fills: list[dict], factors: dict) -> tuple[dict, dict]:
    """帳本起點之前就有的庫存（下限估計）：讓累計持股永遠不為負所需的最小起始股數。
    回傳（{symbol: 起始股數}, {買進列 row: 該筆買進之前的「含起始庫存」持股}）。"""
    run: dict[str, float] = {}
    low: dict[str, float] = {}
    for f in fills:
        q = abs(float(f["qty"])) * factors[f["row"]] * (1 if f["side"] == "BOUGHT" else -1)
        run[f["symbol"]] = run.get(f["symbol"], 0.0) + q
        low[f["symbol"]] = min(low.get(f["symbol"], 0.0), run[f["symbol"]])
    seeds = {s: -v for s, v in low.items() if -v > 1e-6}
    cur = dict(seeds)
    before = {}
    for f in fills:
        q = abs(float(f["qty"])) * factors[f["row"]]
        s = f["symbol"]
        if f["side"] == "BOUGHT":
            before[f["row"]] = cur.get(s, 0.0)
            cur[s] = cur.get(s, 0.0) + q
        else:
            cur[s] = cur.get(s, 0.0) - q
    return seeds, before


def seeded_fills(fills: list[dict], seeds: dict, min_seed: float = 0.5) -> list[dict]:
    """穩健性對照用：在每個有起始庫存的代號最前面插入一筆「帳本之前的買進」（成本不明，設 0）。
    小於 min_seed 股的零頭（股息再投入的零股）不插入。配到這筆的賣出不會進 PF-2。"""
    out = []
    for sym, q in sorted(seeds.items()):
        if q >= min_seed:
            out.append({"symbol": sym, "date": "PRE", "side": "BOUGHT", "qty": q, "amount": 0.0,
                        "row": -1, "origin": "pre_ledger", "_factor": 1.0})
    return out + list(fills)


def new_position_rows(fills: list[dict], factors: dict) -> set:
    held: dict[str, float] = {}
    out = set()
    for f in fills:
        q = abs(float(f["qty"])) * factors[f["row"]]
        h = held.get(f["symbol"], 0.0)
        if f["side"] == "BOUGHT":
            if h <= 1e-6:
                out.add(f["row"])
            held[f["symbol"]] = h + q
        else:
            held[f["symbol"]] = max(0.0, h - q)
    return out


def reconcile_positions(open_lots: dict) -> dict:
    """帳本推出的未平倉股數 vs 券商目前持股（只當拆股處理的旁證）。"""
    try:
        ps = json.loads(C.POSITION_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"available": False}
    broker = {p["symbol"]: float(p["qty"]) for p in ps.get("positions", [])}
    led = {s: sum(x[0] for x in v) for s, v in open_lots.items()}
    led = {s: q for s, q in led.items() if q > 1e-6}
    keys = set(broker) | set(led)
    diff = {k: abs(broker.get(k, 0.0) - led.get(k, 0.0)) for k in keys}
    return {"available": True, "asof": ps.get("asof"), "n_broker_positions": len(broker),
            "n_ledger_open_symbols": len(led),
            "n_symbols_only_in_ledger": int(sum(1 for k in led if k not in broker)),
            "n_symbols_only_at_broker": int(sum(1 for k in broker if k not in led)),
            "n_symbols_qty_diff_over_1_share": int(sum(1 for v in diff.values() if v > 1.0)),
            "n_symbols_qty_diff_under_1_share_nonzero": int(sum(1 for v in diff.values() if 1e-3 < v <= 1.0))}


# ══ main ═══════════════════════════════════════════════════════════════════
def run() -> dict:
    t0 = time.time()
    C.OUT.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(C.REPO / "tools"))
    import trade_ledger as TL  # 只借用 SPLITS、SEMI_AI、split_adjust_qty；不呼叫任何抓資料或寫檔的函式

    fills = C.load_ledger()
    ledger_info = dict(C.load_ledger.info)
    last_date = max(f["date"] for f in fills)
    symbols = sorted({f["symbol"] for f in fills})
    frames = C.load_frames()
    eod = C.load_eod_ranked()
    silver = C.load_silver(symbols)
    cal, last_px = C.build_calendar(frames, last_date)
    book = C.build_price_book(symbols, cal, frames, eod, silver)
    idx = frames["pkl_idx"]
    bench_px = {b: idx[b].reindex(cal).to_numpy(dtype=float) for b in ("SPY", "SMH", "QQQ")}
    pos = {d: i for i, d in enumerate(cal)}
    n_off_calendar = sum(1 for f in fills if pd.Timestamp(f["date"]) not in pos)
    assert n_off_calendar == 0, "a fill date is not in the session calendar"

    # ── split validation ──
    factors, factor_info = C.implied_split_factors(fills, cal, book)
    sil_events = C.silver_split_events(silver, symbols, min(f["date"] for f in fills))
    split_tab, split_info = C.split_validation(fills, factors, TL, sil_events)
    split_tab.to_csv(C.OUT / "split_validation.csv", index=False)

    pieces, fifo_info, open_lots = C.fifo_pieces(fills, lambda f: factors[f["row"]])
    pieces_tbl, fifo_tbl_info, open_tbl = C.fifo_pieces(fills, lambda f: C.ledger_table_factor(TL, f))
    recon = {"price_implied_splits": reconcile_positions(open_lots),
             "ledger_split_table": reconcile_positions(open_tbl)}

    seeds, seeded_before = pre_ledger_seeds(fills, factors)
    sfills = seeded_fills(fills, seeds)
    pieces_seed_all, fifo_seed_info, _ = C.fifo_pieces(
        sfills, lambda f: f.get("_factor") if "_factor" in f else factors[f["row"]])
    pieces_seed = pieces_seed_all[pieces_seed_all.buy_row >= 0].reset_index(drop=True)

    # ── PF-1 ──
    r14, r14_info = pf1(fills, factors, pieces, seeded_before, last_date)
    r14.to_csv(C.OUT / "r14_compliance.csv", index=False)

    # ── PF-2 ──
    alt = {"SPY": bench_px["SPY"], "SMH": bench_px["SMH"], "CASH": None}
    variants = {"primary_ledger_fifo_price_implied_splits": pieces,
                "robust_seeded_pre_ledger_inventory": pieces_seed,
                "robust_ledger_split_table": pieces_tbl}
    summ_parts, piece_tabs = [], {}
    for name, pcs in variants.items():
        pp = pf2_pieces(pcs, cal, last_px, book, alt)
        piece_tabs[name] = pp
        summ_parts.append(pf2_summarise(pp, name))
    summ2 = pd.concat(summ_parts, ignore_index=True)
    summ2.to_csv(C.OUT / "min_hold_counterfactual.csv", index=False)
    pp0 = piece_tabs["primary_ledger_fifo_price_implied_splits"]
    pp0[pp0.status != "held_at_least_N"].to_csv(C.OUT / "min_hold_pieces.csv", index=False)

    readings = {f"{v}|{ver}": prewritten_reading(summ2, v, ver)
                for v in variants for ver in ("no_stop", "hard_stop_25pct")}
    primary_reading = readings["primary_ledger_fifo_price_implied_splits|no_stop"]

    # 集中度（只當提醒）：N=63 的差額有多少來自最大的幾個代號、最大的幾個月份
    ok63 = pp0[(pp0.N == 63) & (pp0.status == "ok")]
    conc = {}
    for a in ("SPY", "SMH"):
        by_sym = ok63.groupby("symbol")[f"diff_{a}"].sum().sort_values()
        by_mon = ok63.groupby("buy_month")[f"diff_{a}"].sum().sort_values()
        tot = float(ok63[f"diff_{a}"].sum())
        conc[a] = {"total": tot,
                   "top3_symbols_positive_sum": float(by_sym.tail(3).clip(lower=0).sum()),
                   "bottom3_symbols_negative_sum": float(by_sym.head(3).clip(upper=0).sum()),
                   "total_without_top3_symbols": float(by_sym.iloc[:-3].sum()) if len(by_sym) > 3 else None,
                   "top3_months_positive_sum": float(by_mon.tail(3).clip(lower=0).sum()),
                   "total_without_top3_months": float(by_mon.iloc[:-3].sum()) if len(by_mon) > 3 else None,
                   "n_symbols_positive": int((by_sym > 0).sum()), "n_symbols": int(len(by_sym)),
                   "n_months_positive": int((by_mon > 0).sum()), "n_months": int(len(by_mon))}
    cash_eq = set(json.loads(C.ROSTER_JSON.read_text(encoding="utf-8")).get("cash_equivalents") or [])
    okall = pp0[pp0.status == "ok"]
    conc["cash_equivalent_pieces_by_N"] = {
        str(N): {"n_pieces": int(((okall.N == N) & okall.symbol.isin(cash_eq)).sum()),
                 "proceeds": round(float(okall[(okall.N == N) & okall.symbol.isin(cash_eq)].proceeds.sum()), 2)}
        for N in C.N_LIST}
    # R14 生效後買進的批次，有多少進得了各個 N 的反事實（太近的還沒滿 N 日）
    post = pp0[(pp0.buy_date >= C.R14_EFFECTIVE) & (pp0.status != "held_at_least_N")]
    conc["post_r14_pieces_by_N"] = {
        str(N): {"n_held_under_N": int((post.N == N).sum()),
                 "n_ok": int(((post.N == N) & (post.status == "ok")).sum())} for N in C.N_LIST}

    # ── PF-3 ──
    new_rows = new_position_rows(fills, factors)
    ft = pf3_table(fills, cal, last_px, book, {b: bench_px[b] for b in C.HURDLE_BENCH},
                   set(TL.SEMI_AI), new_rows)
    ft.to_csv(C.OUT / "hurdle_fills.csv", index=False)
    hurdle = pf3_summarise(ft)
    hurdle.to_csv(C.OUT / "hurdle.csv", index=False)
    post = ft[(ft.period == "R35 之後") & (ft.H == C.H_LIST[0])]
    r35_idx = int(np.searchsorted(cal.values, np.datetime64(C.R35_EFFECTIVE)))
    earliest = {}
    for H in C.H_LIST:
        need = r35_idx + H - last_px          # 還差幾個交易日
        d = pd.bdate_range(cal[last_px], periods=max(need, 0) + 1)[-1]
        earliest[str(H)] = {"sessions_still_needed_for_first_buy": int(max(need, 0)),
                            "approx_first_evaluable_date_ignoring_holidays": str(d.date())}
    r35_info = {"r35_effective": C.R35_EFFECTIVE, "n_buys_after_r35": int(len(post)),
                "n_new_position_buys_after_r35": int(post.is_new_position.sum()),
                "n_symbols_after_r35": int(post.symbol.nunique()),
                "n_after_r35_with_63_sessions": int(((ft.period == "R35 之後") & (ft.H == 63)
                                                     & (ft.status == "ok")).sum()),
                "n_after_r35_with_126_sessions": int(((ft.period == "R35 之後") & (ft.H == 126)
                                                      & (ft.status == "ok")).sum()),
                "max_sessions_elapsed_since_r35": int(last_px - r35_idx),
                "earliest_evaluable": earliest}

    def recs(df):
        return json.loads(df.to_json(orient="records", force_ascii=False))

    share_eod = float(pp0[pp0.status == "ok"].source.str.startswith("eod:").mean())
    share_silver = float((pp0[pp0.status == "ok"].source == "silver_adj").mean())
    verdict = {
        "study": "PF (ledger and holding-period rule), overnight-study-2026-11-19",
        "nature": "descriptive diagnostic; nomination-only; no pass line; uses prices after 2025-12-31 "
                  "because the pre-registration lets PF run to the last ledger fill",
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ledger": {**ledger_info, "first_fill": min(f["date"] for f in fills), "last_fill": last_date,
                   "n_buys": int(sum(1 for f in fills if f["side"] == "BOUGHT")),
                   "n_sells": int(sum(1 for f in fills if f["side"] == "SOLD")),
                   "n_symbols": len(symbols),
                   "origin_counts_buys": pd.Series([f["origin"] for f in fills
                                                    if f["side"] == "BOUGHT"]).value_counts().to_dict()},
        "prices": {"calendar_last_priced_session": str(cal[last_px].date()),
                   "n_symbols_without_any_series": int(sum(1 for s in symbols if not book.get(s))),
                   "n_fills_in_symbols_without_any_series": int(
                       sum(1 for f in fills if not book.get(f["symbol"]))),
                   "n_symbols_with_silver": int(sum(1 for s in symbols
                                                    if len(C.silver_lookup(silver, s)))),
                   "n_symbols_only_in_silver": int(sum(
                       1 for s in symbols if book.get(s) and all(n == "silver_adj" for n, _ in book[s]))),
                   "silver_max_date": str(silver.date.max().date()) if len(silver) else None,
                   "pf2_share_from_eod_cache": share_eod, "pf2_share_from_silver": share_silver},
        "splits": {**split_info, **factor_info,
                   "fifo_price_implied": fifo_info, "fifo_ledger_table": fifo_tbl_info,
                   "fifo_seeded": fifo_seed_info,
                   "realised_pnl_price_implied": round(float(pieces.pnl.sum()), 2),
                   "realised_pnl_ledger_table": round(float(pieces_tbl.pnl.sum()), 2),
                   "n_pieces_price_implied": int(len(pieces)), "n_pieces_ledger_table": int(len(pieces_tbl)),
                   "reconciliation_vs_broker": recon,
                   "n_symbols_with_pre_ledger_inventory_over_half_share": int(
                       sum(1 for q in seeds.values() if q >= 0.5)),
                   "n_pieces_seeded_variant": int(len(pieces_seed)),
                   "n_pieces_matched_to_pre_ledger_lot": int((pieces_seed_all.buy_row < 0).sum())},
        "PF1": r14_info,
        "PF2": {"definition": "diff = value at T of holding to the N-th session close minus value at T of "
                              "the actual sale proceeds parked in the alternative; T = buy date + N sessions",
                "prewritten_reading_primary": primary_reading,
                "prewritten_reading_all_variants": readings,
                "concentration_N63_primary_no_stop": conc,
                "table_primary": recs(summ2[(summ2.fifo_variant == "primary_ledger_fifo_price_implied_splits")
                                            & (summ2.cut_type.isin(["all", "buy_year", "buy_origin"]))]),
                "table_robust_all_cut": recs(summ2[(summ2.fifo_variant != "primary_ledger_fifo_price_implied_splits")
                                                   & (summ2.cut_type == "all")])},
        "PF3": {"table": recs(hurdle), "r35": r35_info,
                "n_semi_symbols_traded": int(sum(1 for s in symbols if s.upper() in TL.SEMI_AI)),
                "share_from_eod_cache": float(ft[ft.status == "ok"].source.str.startswith("eod:").mean())},
        "runtime_sec": round(time.time() - t0, 1),
    }
    C.write_json(C.OUT / "verdict.json", verdict)
    return verdict


if __name__ == "__main__":
    v = run()
    print(json.dumps({"ledger": v["ledger"], "prices": v["prices"], "PF1": v["PF1"],
                      "reading": v["PF2"]["prewritten_reading_primary"],
                      "r35": v["PF3"]["r35"], "runtime_sec": v["runtime_sec"]},
                     ensure_ascii=False, indent=1, default=str))
