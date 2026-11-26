"""XM-3 的帳本部分：把「三天內擇一天開盤買」的規則套在帳本裡實際的買進日。

* 只讀帳本的「日期」與「代號」；不讀金額、不把任何成交資料寫進程式碼。
* 結果只寫到 gitignore 的 tools/backtests/data/overnight_2026-11-19/xm/。
* 預註冊允許這一段用到 2025-12-31 之後的資料（帳本用到最後一筆成交）；
  實際能算到哪一天，受價格資料的最後日期限制（見輸出的 coverage）。
* 描述性、只能提名。

跑法：python -B ledger_timing.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import align  # noqa: E402
import common as C  # noqa: E402
import run_xm as R  # noqa: E402

N_BOOT = 2000
SEED = 20261119
METRICS = ["wait_vs_first", "avg_vs_first", "wait_vs_avg"]


def load_buys() -> pd.DataFrame:
    """股票與 ETF 的買進（排除選擇權與 origin_evidence 以 VOID 開頭的列）。只取日期與代號。"""
    rows = []
    for line in C._guard(C.LEDGER).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("is_option") or r.get("side") != "BOUGHT":
            continue
        if str(r.get("origin_evidence") or "").startswith("VOID"):
            continue
        rows.append({"date": pd.Timestamp(r["date"]), "symbol": r["symbol"]})
    return pd.DataFrame(rows).drop_duplicates().reset_index(drop=True)


def month_cluster_ci(df: pd.DataFrame, col: str, rng: np.random.Generator) -> tuple[float, float]:
    """按買進月份分群的 bootstrap 95% 區間（與本預註冊 PF 組的做法一致）。"""
    groups = [g[col].to_numpy() for _, g in df.groupby(df["d0"].dt.to_period("M"))]
    if len(groups) < 5:
        return (np.nan, np.nan)
    sums = np.array([g.sum() for g in groups])
    cnts = np.array([len(g) for g in groups])
    idx = rng.integers(0, len(groups), size=(N_BOOT, len(groups)))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def summarize(df: pd.DataFrame, meta: dict, rng: np.random.Generator) -> dict:
    row = dict(meta, n=len(df), n_months=int(df["d0"].dt.to_period("M").nunique()) if len(df) else 0)
    if len(df) == 0:
        return row
    row.update(first_month=str(df["d0"].min().to_period("M")), last_month=str(df["d0"].max().to_period("M")),
               share_buy_day1=float((df["buy_day"] == 1).mean()), share_buy_day2=float((df["buy_day"] == 2).mean()),
               share_buy_day3=float((df["buy_day"] == 3).mean()))
    for k in METRICS:
        lo, hi = month_cluster_ci(df, k, rng)
        row.update({f"{k}_bp": float(df[k].mean()), f"{k}_lo": lo, f"{k}_hi": hi})
    return row


def main() -> None:
    C.OUT_DIR.mkdir(parents=True, exist_ok=True)
    buys = load_buys()
    tw = C.load_tw(end=None)          # 帳本段：允許用到 2025-12-31 之後
    us = C.load_us(end=None)
    cal = us["SPY"].index
    rng = np.random.default_rng(SEED)

    buy_dates = pd.DatetimeIndex(sorted(buys["date"].unique()))
    per_obs = []                       # 每筆（變體, 標的, 預測變數, 對齊, 起始日）的改善幅度
    coverage = {"ledger_first_buy": str(buys["date"].min().date()), "ledger_last_buy": str(buys["date"].max().date()),
                "n_distinct_buy_dates": int(len(buy_dates)),
                "n_buy_dates_after_etf_price_end": int((buy_dates > cal.max()).sum()),
                "n_buy_dates_after_2025_12_31": int((buy_dates > C.END).sum()),
                "n_buy_dates_not_a_us_session_within_coverage": int((~buy_dates[buy_dates <= cal.max()].isin(cal)).sum()),
                "n_distinct_symbol_dates_in_six_targets": int(buys["symbol"].isin(C.TARGETS).sum()),
                "price_last_date": {}, "tw_last_date": str(tw["TAIEX_TR"].index.max().date())}
    for tgt in C.TARGETS:
        f = us[tgt]
        coverage["price_last_date"][tgt] = str(f["ao"].dropna().index.max().date())
        zs = R.build_z(f, tw, cal)
        own = pd.DatetimeIndex(sorted(buys.loc[buys["symbol"] == tgt, "date"].unique()))
        for (pred, rt), m in zs.items():
            if rt != "cc":
                continue
            for aname, zcol in R.ALIGNMENTS.items():
                valid = m[zcol].notna() & f["ao"].notna()
                if not valid.any():
                    continue
                g = pd.DataFrame({"ao": f["ao"], "z": m[zcol]}).loc[valid.idxmax():]
                imp = R.timing_improvements(g["ao"].to_numpy(), g["z"].to_numpy())
                imp.index = g.index[: len(imp)]
                imp = imp.dropna(subset=METRICS)       # 三天的開盤價都要有
                for variant, dates in (("A_ticker_matched", own), ("B_all_buy_dates", buy_dates)):
                    d = imp[imp.index.isin(dates)]
                    if len(d):
                        per_obs.append(d.assign(d0=d.index, variant=variant, target=tgt, predictor=pred, alignment=aname))
    obs = pd.concat(per_obs, ignore_index=True) if per_obs else pd.DataFrame()

    rows = []
    if len(obs):
        for (variant, aname, pred, tgt), d in obs.groupby(["variant", "alignment", "predictor", "target"]):
            rows.append(summarize(d, dict(variant=variant, alignment=aname, predictor=pred, target=tgt), rng))
        for (variant, aname, pred), d in obs.groupby(["variant", "alignment", "predictor"]):
            rows.append(summarize(d, dict(variant=variant, alignment=aname, predictor=pred, target="POOLED"), rng))
    out = pd.DataFrame(rows)
    out.to_csv(C.OUT_DIR / "ledger_timing.csv", index=False)

    main_rows = out[(out["alignment"] == "same_date") & (out["target"] == "POOLED")] if len(out) else out
    summary = {
        "nature": "descriptive / nomination-only; ledger-derived; keep in git-ignored path",
        "coverage": coverage,
        "interpretation": {
            "A_ticker_matched": "帳本裡買的剛好是六個標的之一的（代號, 日期）；用該標的自己的開盤價",
            "B_all_buy_dates": "帳本裡每一個有買進股票或 ETF 的日期當起始日，套在六個標的上",
            "ci": f"按買進月份分群的 bootstrap，{N_BOOT} 次",
        },
        "pooled_same_date": main_rows.to_dict(orient="records"),
    }
    (C.OUT_DIR / "ledger_timing.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(json.dumps(coverage, indent=1))
    if len(out):
        cols = ["variant", "alignment", "predictor", "target", "n", "n_months", "wait_vs_first_bp", "wait_vs_first_lo",
                "wait_vs_first_hi", "avg_vs_first_bp", "wait_vs_avg_bp", "wait_vs_avg_lo", "wait_vs_avg_hi"]
        print(out[out["alignment"] == "same_date"][cols].round(1).to_string())


if __name__ == "__main__":
    main()
