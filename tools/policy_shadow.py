#!/usr/bin/env python3
"""policy_shadow.py — 配置政策影子帳：波動目標／停泊改現金／R15 照舊或放寬（2026-11-20 用戶「先都加入影子好了，後面裁決，長期抗戰」）

Why：2026-11-20 回撤檢討（tools/backtests/drawdown_postmortem_2026-11-20.py）量到今年 −29.7% 的回撤全部來自曝險，
而所有測過的做法裡 Calmar 穩定勝出的只有「波動變大就降曝險」（strategy_leaderboard_2026-11-20.py、vol_target_robustness_2026-11-20.py；
10/23 兩份評估、11/09 HMM 對照列、11/19 隔夜研究的方向相同）。它 10/23 未採用（少賺超過當時的 2pp 線、與 R15／R33 互咬），
11/19 留下「要不要改用 Calmar 當標準」未裁決。這支工具不下單、不改任何規則，只把幾條「如果照做」的淨值線每天往前記，到期照事前寫好的條件裁決。

每條線都用**同一個個股格報酬**（你實際的選股與進出：今日市值 − 今日淨買進，除以昨日市值），只差「抱多少」與「沒抱的放哪」：
  actual     實際配置：個股、VOO、現金類照實際比重（收盤對收盤；選擇權不計）——對照基準
  park_sgov  實際配置，但停泊的 VOO 改放 SGOV ——單獨驗 R33
  vt20/25/30 波動目標：個股曝險 = min(1, 目標 ÷ 個股格 20 日實現波動)，週五收盤決定、變動 <10 個百分點不動、隔日生效，其餘放 SGOV
  vt25_voo   波動目標 25%，其餘放 VOO ——驗「波動目標若保留 R33」
  vt25_r15   波動目標 25%，但回檔熔斷期間（帳戶自峰 −10%）信念桶不減、只減認列桶 ——驗「波動目標若保留 R15」
每次調整扣 10bp。登記日 REG 之後才算前瞻紀錄；REG 之前（2026-06-02 起）是回填，只當背景。

事前寫定的裁決條件（SPEC；登記後不得改，要改只能另登一條新影子）：
  最早裁決：登記滿 252 個交易日，且期間 SMH 出過一段回升（自登記後低點 +30%）與一段下跌（自登記後高點 −15%）；最晚 504 個交易日強制裁決。
  波動目標過關（三個目標值各自判定，過關者取年化最高的）：
    ① Calmar 高於 actual　② 最大回撤比 actual 淺 ≥5 個百分點　③ 年化不低於 actual 3 個百分點　④ Calmar 高於「同樣平均曝險的固定配置」
  R33（停泊 VOO）要改：vt25 的最大回撤比 vt25_voo 淺 ≥3 個百分點且 Calmar 較高 → 波動目標的閒置部位改放現金類；
    單獨改（不管波動目標）：park_sgov 的 Calmar 高於 actual 且年化不低於 actual 1 個百分點。帳本原有的「連兩期落後 SGOV ≥5pp → 覆審」照舊。
  R15（回檔期間信念桶禁減碼）要改：vt25 的最大回撤比 vt25_r15 淺 ≥3 個百分點且 Calmar 較高 → 給波動目標的減碼開例外；否則 R15 不動、波動目標只套認列桶。

資料：research/position-state.json（即時部位）＋ research/trade-ledger.jsonl（成交，往回還原每日收盤部位）＋ research/roster.json（桶別）
＋ research/equity-marks.json（帳戶淨值，算比重與熔斷）＋ yfinance 收盤價。只處理收盤已定的日子（美東 16:30 後才算當日）。
輸出：research/policy-shadow.jsonl（每日一列，只增不改）、briefing-out/cache/policy-shadow.json（摘要，briefing／trade-review 讀）。

Usage:
  python3 tools/policy_shadow.py update [--rebuild] [--dry-run]   # runner 每日跑；--rebuild 從頭重算（會覆寫 jsonl）
  python3 tools/policy_shadow.py status                           # 人讀的摘要；到裁決點 exit 2；條件被改或紀錄斷更 exit 3
  python3 tools/policy_shadow.py selftest

門檻已鎖（2026-11-21 用戶「裁決門檻要照這組數字登記」）：REG／SPEC／VT／線名單／成本／回看日數／調整門檻合成一個指紋 REGISTERED_FP，
任何一個被改，update 與 status 都直接報錯（exit 3），runner 會推 Telegram。要換條件 → 另開一支新影子，不要改這支。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import warnings
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "research" / "trade-ledger.jsonl"
STATE = ROOT / "research" / "position-state.json"
ROSTER = ROOT / "research" / "roster.json"
MARKS = ROOT / "research" / "equity-marks.json"
LOG = ROOT / "research" / "policy-shadow.jsonl"
CACHE = ROOT / "briefing-out" / "cache" / "policy-shadow.json"

REG = "2026-11-20"          # 登記日：這天收盤之後才是前瞻紀錄
NAV_START = "2026-06-01"    # 回填起點（之後才有每日淨值標記）
HIST_START = "2025-12-31"   # 部位還原與波動暖機起點
COST, VOL_LB, STEP = 0.001, 20, 0.10
OTHER_ETF = {"GLD", "SPY", "TLT", "IEF", "BND"}
SPEC = {
    "min_days": 252, "max_days": 504, "rebound_leg": 0.30, "decline_leg": -0.15,
    "vt": {"mdd_better_pp": 5.0, "cagr_floor_pp": -3.0},
    "r33": {"mdd_better_pp": 3.0, "standalone_cagr_floor_pp": -1.0},
    "r15": {"mdd_better_pp": 3.0},
}
POL = {
    "actual": "實際配置（對照）", "park_sgov": "實際配置，停泊改 SGOV",
    "vt20": "波動目標 20%", "vt25": "波動目標 25%", "vt30": "波動目標 30%",
    "vt25_voo": "波動目標 25%，其餘放 VOO", "vt25_r15": "波動目標 25%，熔斷期信念桶不減",
}
VT = {"vt20": (0.20, "sgov"), "vt25": (0.25, "sgov"), "vt30": (0.30, "sgov"), "vt25_voo": (0.25, "voo")}

# 登記指紋（2026-11-21 用戶確認門檻）。上面的 REG／SPEC／VT／POL／COST／VOL_LB／STEP 任何一個被改，指紋就對不上。
# 不要改這個值，也不要改上面的數字：要換條件就另開一支新影子（新檔名、新登記日）。
REGISTERED_FP = "cd432dd81c185923"
STALE_BDAYS = 5             # 最新一列落後超過這麼多個工作日 → status exit 3（每日更新壞了，runner 推 Telegram）


def _fingerprint() -> str:
    blob = json.dumps({"reg": REG, "spec": SPEC, "vt": VT, "lines": sorted(POL), "cost": COST, "vol_lb": VOL_LB, "step": STEP}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _guard() -> str | None:
    """條件與登記一致回 None；不一致回一句錯誤訊息。"""
    fp = _fingerprint()
    if fp == REGISTERED_FP: return None
    return (f"⛔ 政策影子帳：裁決條件或影子線的定義與登記不符（登記指紋 {REGISTERED_FP}、現在 {fp}）。"
            "登記後不能改——把 tools/policy_shadow.py 的數字改回原樣；要換條件請另登一條新影子。")


def _final_day() -> pd.Timestamp:
    """最後一個收盤已定的日曆日（美東 16:30 之後才算當日）。"""
    now = datetime.now(ZoneInfo("America/New_York"))
    d = pd.Timestamp(now.date())
    return d if (now.hour, now.minute) >= (16, 30) else d - pd.Timedelta(days=1)


def _signed_qty(f: dict) -> float:
    sp = f.get("split_adj_price") or f.get("price")
    q = f["notional"] / sp if sp else f["qty"]
    return q if str(f["side"]).upper().startswith("B") else -q


def build_inputs() -> tuple[pd.DataFrame, dict]:
    """還原每日收盤部位 → 個股格／信念／認列／VOO／現金類／其他 的市值與報酬，加上比重與熔斷旗標。"""
    import yfinance as yf

    st = json.loads(STATE.read_text()); ro = json.loads(ROSTER.read_text())
    anchor = st.get("asof")
    live = {p["symbol"]: float(p["qty"]) for p in st.get("positions", []) if abs(float(p.get("qty") or 0)) > 1e-9}
    conv = set(ro.get("buckets", {}).get("信念", []))
    cashlike = set(ro.get("cash_equivalents", [])) | {"SGOV", "BIL"}
    park = set(ro.get("benchmark_parking", [])) | {"VOO"}
    other = OTHER_ETF | set(ro.get("passive_sleeve", []))

    def cls(s: str) -> str:
        return "cl" if s in cashlike else "voo" if s in park else "other" if s in other else "conv" if s in conv else "harv"

    allf = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    allf = [f for f in allf if HIST_START < f["date"] <= anchor]
    fills = sorted((f for f in allf if not f.get("is_option")), key=lambda f: f["date"])
    pos0 = defaultdict(float); pos0.update(live)
    for f in fills:
        pos0[f["symbol"]] -= _signed_qty(f)
    syms = sorted(set(pos0) | {f["symbol"] for f in fills}); ym = {s: s.replace(".", "-") for s in syms}
    raw = yf.download(sorted(set(ym.values())), start="2025-12-20", progress=False, auto_adjust=False)["Close"]
    adj = yf.download(["VOO", "SGOV", "SMH"], start="2025-06-01", progress=False, auto_adjust=True)["Close"]
    last = min(_final_day(), pd.Timestamp(anchor))
    days = raw.index[(raw.index >= HIST_START) & (raw.index <= last)]
    nopx = [s for s in syms if ym[s] not in raw.columns or raw[ym[s]].reindex(days).isna().all()]
    by = defaultdict(list)
    for f in fills:
        i = days.searchsorted(pd.Timestamp(f["date"]))
        if i < len(days): by[days[i]].append(f)
    cur = dict(pos0); rows = []
    for d in days:
        nb = defaultdict(float)
        for f in by.get(d, []):
            s = f["symbol"]; cur[s] = cur.get(s, 0.0) + _signed_qty(f)
            if s not in nopx: nb[cls(s)] += -f["amount"]
        mv = defaultdict(float)
        for s, q in cur.items():
            if abs(q) < 1e-6 or s in nopx: continue
            p = raw.at[d, ym[s]]
            if np.isnan(p): p = raw[ym[s]].loc[:d].ffill().iloc[-1]
            if not np.isnan(p): mv[cls(s)] += q * p
        rows.append({"date": d, **{f"mv_{k}": mv[k] for k in ("conv", "harv", "voo", "cl", "other")}, **{f"nb_{k}": nb[k] for k in ("conv", "harv", "other")}})
    F = pd.DataFrame(rows).set_index("date")
    F["mv_s"] = F.mv_conv + F.mv_harv; F["nb_s"] = F.nb_conv + F.nb_harv
    amt = pd.Series(0.0, index=days)                      # 每日現金流（含選擇權）；現金往回推：收盤現金 = 即時現金 − 之後所有成交的現金流
    for f in allf:
        i = days.searchsorted(pd.Timestamp(f["date"]))
        if i < len(days): amt.iloc[i] += float(f.get("amount") or 0.0)
    F["cash"] = float(st.get("cash") or 0.0) - amt.sum() + amt.cumsum()
    for k in ("s", "conv", "harv", "other"):
        prev = F[f"mv_{k}"].shift(1)
        F[f"r_{k}"] = ((F[f"mv_{k}"] - F[f"nb_{k}"]) / prev - 1).where(prev > 1.0, 0.0).fillna(0.0)
    F["r_voo"] = adj["VOO"].pct_change().reindex(F.index).fillna(0.0)
    F["r_sgov"] = adj["SGOV"].pct_change().reindex(F.index).fillna(0.0)
    F["smh"] = adj["SMH"].reindex(F.index).ffill()
    F["vol20"] = F.r_s.rolling(VOL_LB).std() * np.sqrt(252)
    m = json.loads(MARKS.read_text())
    mk = pd.Series({x["date"]: x["value"] for x in m.get("manual", []) + [y for y in m.get("marks", []) if not y.get("excluded") and y.get("kind") == "total"]}).sort_index()
    mk.index = pd.to_datetime(mk.index); mk = mk[~mk.index.duplicated(keep="last")]
    tot = mk.reindex(F.index.union(mk.index)).ffill().reindex(F.index)
    F["mark"] = tot
    # 比重用收盤還原的總值（個股＋ETF＋現金；選擇權市值不計、股息不計），不用盤中淨值標記——標記有時是前一日的快照
    F["total"] = (F.mv_s + F.mv_voo + F.mv_cl + F.mv_other + F.cash).clip(lower=1.0)
    for k in ("s", "voo", "cl", "other"):
        F[f"w_{k}"] = (F[f"mv_{k}"] / F["total"]).clip(lower=0, upper=1.5)
    F["conv_share"] = (F.mv_conv / F.mv_s).where(F.mv_s > 1.0, 0.0)
    F["breaker"] = (tot / tot.cummax() - 1) <= -0.10
    meta = {"anchor": anchor, "source": st.get("source"), "no_price": nopx, "conviction": sorted(conv), "last_final": str(last.date())}
    return F, meta


def step_day(prev: dict, x: dict, lag: dict, friday: bool) -> dict:
    """一天的各線報酬與狀態。prev＝前一列（nav／exp／held／cf），x＝當日報酬與波動，lag＝前一日收盤的比重、信念占比、熔斷。"""
    nav, exp, held = dict(prev["nav"]), {}, dict(prev["held"])
    r_s, r_voo, r_sg = x["r_s"], x["r_voo"], x["r_sgov"]
    for p, (tgt, idle) in VT.items():
        e = prev["held"][p]; exp[p] = e
        ret = e * r_s + (1 - e) * (r_sg if idle == "sgov" else r_voo) - COST * abs(e - prev["exp"][p])
        nav[p] = prev["nav"][p] * (1 + ret)
        if friday and x["vol20"] == x["vol20"] and x["vol20"] > 0:
            rawe = min(1.0, tgt / x["vol20"])
            if abs(rawe - held[p]) >= STEP - 1e-9: held[p] = rawe
    e = prev["held"]["vt25"]; cs = lag["conv_share"]
    cf = max(prev["cf"], e) if lag["breaker"] else e
    hf = 0.0 if cs >= 0.999 else float(np.clip((e - cs * cf) / (1 - cs), 0.0, 1.0))
    real = cs * cf + (1 - cs) * hf; exp["vt25_r15"] = real
    ret = cs * cf * x["r_conv"] + (1 - cs) * hf * x["r_harv"] + (1 - real) * r_sg - COST * abs(real - prev["exp"]["vt25_r15"])
    nav["vt25_r15"] = prev["nav"]["vt25_r15"] * (1 + ret)
    exp["actual"] = exp["park_sgov"] = lag["w_s"]
    nav["actual"] = prev["nav"]["actual"] * (1 + lag["w_s"] * r_s + lag["w_voo"] * r_voo + lag["w_cl"] * r_sg + lag["w_other"] * x["r_other"])
    nav["park_sgov"] = prev["nav"]["park_sgov"] * (1 + lag["w_s"] * r_s + (lag["w_voo"] + lag["w_cl"]) * r_sg + lag["w_other"] * x["r_other"])
    return {"nav": nav, "exp": exp, "held": held, "cf": cf}


def run_engine(F: pd.DataFrame, rows: list[dict]) -> list[dict]:
    """rows＝已存的列（可空）。回傳要新增的列。暖機期（NAV_START 之前）只更新曝險狀態、不累計淨值。"""
    idx = list(F.index)
    if rows:
        prev = {k: rows[-1][k] for k in ("nav", "exp", "held", "cf")}; start = F.index.searchsorted(pd.Timestamp(rows[-1]["date"])) + 1
    else:
        prev = {"nav": {p: 100.0 for p in POL}, "exp": {p: 1.0 for p in POL}, "held": {p: 1.0 for p in VT}, "cf": 1.0}; start = 1
    out = []
    for i in range(start, len(idx)):
        d = idx[i]; a = F.iloc[i]; b = F.iloc[i - 1]
        x = {k: float(a[k]) for k in ("r_s", "r_conv", "r_harv", "r_other", "r_voo", "r_sgov")}; x["vol20"] = float(a["vol20"])
        lag = {k: (0.0 if np.isnan(b[k]) else float(b[k])) for k in ("w_s", "w_voo", "w_cl", "w_other", "conv_share")}; lag["breaker"] = bool(b["breaker"])
        new = step_day(prev, x, lag, d.weekday() == 4)
        if str(d.date()) < NAV_START: new["nav"] = dict(prev["nav"])
        prev = new
        if str(d.date()) >= NAV_START:
            out.append({"date": str(d.date()), "pre": str(d.date()) <= REG, "r_s": round(x["r_s"], 6), "r_conv": round(x["r_conv"], 6), "r_harv": round(x["r_harv"], 6),
                        "r_voo": round(x["r_voo"], 6), "r_sgov": round(x["r_sgov"], 6), "vol20": None if np.isnan(x["vol20"]) else round(x["vol20"], 4),
                        "w_s": round(lag["w_s"], 4), "w_voo": round(lag["w_voo"], 4), "conv_share": round(lag["conv_share"], 4), "breaker": lag["breaker"],
                        "smh": None if np.isnan(a["smh"]) else round(float(a["smh"]), 2), "mark": None if np.isnan(a["mark"]) else round(float(a["mark"]), 2),
                        "nav": {p: round(v, 4) for p, v in new["nav"].items()}, "exp": {p: round(v, 4) for p, v in new["exp"].items()},
                        "held": {p: round(v, 4) for p, v in new["held"].items()}, "cf": round(new["cf"], 4)})
    return out


def _stats(nav: pd.Series) -> dict:
    n = len(nav) - 1
    if n < 1: return {"days": 0}
    r = nav.pct_change().dropna(); tot = nav.iloc[-1] / nav.iloc[0] - 1; mdd = float((nav / nav.cummax() - 1).min())
    ann = (1 + tot) ** (252 / n) - 1 if n >= 60 else None
    return {"days": n, "ret": round(tot, 4), "mdd": round(mdd, 4), "vol": round(float(r.std() * np.sqrt(252)), 4) if n >= 5 else None,
            "ann": None if ann is None else round(ann, 4), "calmar": None if (ann is None or n < 126 or mdd >= 0) else round(ann / abs(mdd), 2)}


def summarize(rows: list[dict], meta: dict | None = None) -> dict:
    df = pd.DataFrame([{"date": r["date"], **{f"nav_{p}": r["nav"][p] for p in POL}, **{f"exp_{p}": r["exp"].get(p) for p in POL},
                        "r_s": r["r_s"], "r_sgov": r["r_sgov"], "smh": r["smh"]} for r in rows]).set_index("date")
    post = df[df.index >= REG]; pre = df[df.index <= REG]
    n = max(len(post) - 1, 0); lines = {}
    for p, lab in POL.items():
        lines[p] = {"label": lab, "reg": _stats(post[f"nav_{p}"]) if len(post) else {"days": 0}, "pre": _stats(pre[f"nav_{p}"]) if len(pre) > 1 else {"days": 0},
                    "exposure_now": None if df[f"exp_{p}"].iloc[-1] is None else round(float(df[f"exp_{p}"].iloc[-1]), 3),
                    "next_exposure": rows[-1]["held"].get(p)}
    ctrl = {}
    if n >= 1:
        for p in ("vt20", "vt25", "vt30"):
            eb = float(post[f"exp_{p}"].iloc[1:].mean()); nav = (1 + eb * post.r_s.iloc[1:] + (1 - eb) * post.r_sgov.iloc[1:]).cumprod()
            ctrl[p] = {"avg_exposure": round(eb, 3), **_stats(pd.concat([pd.Series([1.0]), nav]))}
    smh = post.smh.dropna(); legs = {"rebound": False, "decline": False}
    if len(smh) > 1:
        legs["rebound"] = bool((smh / smh.cummin() - 1).max() >= SPEC["rebound_leg"]); legs["decline"] = bool((smh / smh.cummax() - 1).min() <= SPEC["decline_leg"])
    ready = (n >= SPEC["min_days"] and legs["rebound"] and legs["decline"]) or n >= SPEC["max_days"]
    crit = {}
    if ready:
        a = lines["actual"]["reg"]
        def gt(x, y, k="calmar"): return bool(x.get(k) is not None and y.get(k) is not None and x[k] > y[k])      # 缺值一律算不過
        def better(x, y, pp): return bool(x.get("mdd") is not None and y.get("mdd") is not None and x["mdd"] - y["mdd"] >= pp / 100)
        def floor(x, y, pp): return bool(x.get("ann") is not None and y.get("ann") is not None and x["ann"] - y["ann"] >= pp / 100)
        for p in ("vt20", "vt25", "vt30"):
            v = lines[p]["reg"]; c = ctrl.get(p, {})
            crit[p] = {"calmar_gt_actual": gt(v, a), "mdd_better_5pp": better(v, a, SPEC["vt"]["mdd_better_pp"]),
                       "cagr_floor": floor(v, a, SPEC["vt"]["cagr_floor_pp"]), "calmar_gt_same_exposure": gt(v, c)}
            crit[p]["pass"] = all(crit[p].values())
        v, w, r15, ps = (lines[k]["reg"] for k in ("vt25", "vt25_voo", "vt25_r15", "park_sgov"))
        crit["r33_within_vt"] = {"pass": better(v, w, SPEC["r33"]["mdd_better_pp"]) and gt(v, w)}
        crit["r33_standalone"] = {"pass": gt(ps, a) and floor(ps, a, SPEC["r33"]["standalone_cagr_floor_pp"])}
        crit["r15_exception"] = {"pass": better(v, r15, SPEC["r15"]["mdd_better_pp"]) and gt(v, r15)}
    return {"asof": rows[-1]["date"], "registered": REG, "fingerprint": _fingerprint(), "days_since_reg": n, "spec": SPEC, "lines": lines, "same_exposure_control": ctrl, "legs": legs,
            "ruling_due": bool(ready), "criteria": crit, "breaker_now": rows[-1]["breaker"], "vol20_now": rows[-1]["vol20"], "meta": meta or {}}


def _load_rows() -> list[dict]:
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()] if LOG.exists() else []


def cmd_update(a) -> int:
    g = _guard()
    if g: print(g); return 3
    F, meta = build_inputs()
    rows = [] if a.rebuild else _load_rows()
    new = run_engine(F, rows)
    allrows = rows + new
    if not allrows:
        print("policy_shadow：沒有可處理的日子"); return 1
    summ = summarize(allrows, meta)
    if a.dry_run:
        print(f"[dry-run] 會新增 {len(new)} 列（到 {allrows[-1]['date']}）")
    else:
        LOG.parent.mkdir(parents=True, exist_ok=True); CACHE.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("w" if a.rebuild else "a") as fh:
            for r in new: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        CACHE.write_text(json.dumps(summ, ensure_ascii=False, indent=1))
    print(f"policy_shadow：新增 {len(new)} 列，最新 {allrows[-1]['date']}；登記後第 {summ['days_since_reg']} 個交易日" + ("；⚠️ 無報價不計：" + ",".join(meta["no_price"]) if meta["no_price"] else ""))
    if meta.get("source") != "firstrade-live": print(f"⚠️ 部位來源不是即時（{meta.get('source')}），這次的列可能要 --rebuild")
    return 0


def _pct(v, sign=True): return "　—　" if v is None else (f"{v*100:+.1f}%" if sign else f"{v*100:.0f}%")


def cmd_status(a) -> int:
    g = _guard()
    if g: print(g); return 3
    rows = _load_rows()
    if not rows: print("policy_shadow：尚無紀錄，先跑 update --rebuild"); return 1
    s = summarize(rows)
    behind = max(0, len(pd.bdate_range(s["asof"], _final_day())) - 1)
    if behind > STALE_BDAYS:
        print(f"⚠️ 政策影子帳斷更：最新一列停在 {s['asof']}，已落後 {behind} 個工作日。每日更新可能壞了——"
              "手動跑 python3 tools/policy_shadow.py update 看錯誤訊息；修好後缺的日子會自動補回。")
        return 3
    n = s["days_since_reg"]
    print(f"政策影子帳（只記錄、不下單）｜登記 {REG}｜最新 {s['asof']}｜登記後第 {n} 個交易日｜個股格 20 日波動 {_pct(s['vol20_now'], False)}｜熔斷{'生效' if s['breaker_now'] else '未生效'}")
    print("線　　　　　　　　　　　　　　｜登記後報酬｜最大回撤｜Calmar｜今日曝險→下次｜登記前（6/02 起，樣本內）報酬／回撤")
    for p, L in s["lines"].items():
        r, q = L["reg"], L["pre"]; nx = L["next_exposure"]
        print(f"  {L['label']:<22}｜{_pct(r.get('ret')):>8}｜{_pct(r.get('mdd')):>8}｜{('—' if r.get('calmar') is None else r['calmar']):>5}｜"
              f"{_pct(L['exposure_now'], False):>4}" + (f"→{_pct(nx, False)}" if nx is not None else "　　 ") + f"｜{_pct(q.get('ret'))}／{_pct(q.get('mdd'))}")
    for p, c in s["same_exposure_control"].items():
        print(f"  （對照）同 {POL[p]} 平均曝險 {_pct(c['avg_exposure'], False)} 的固定配置：{_pct(c.get('ret'))}／{_pct(c.get('mdd'))}")
    lg = s["legs"]
    print(f"裁決條件：滿 {SPEC['min_days']} 日（現 {n}）且 SMH 回升段{'✓' if lg['rebound'] else '✗'}、下跌段{'✓' if lg['decline'] else '✗'}；最晚第 {SPEC['max_days']} 日；條件已鎖（指紋 {REGISTERED_FP}）。" + ("⚠️ 已到裁決點" if s["ruling_due"] else "觀察中，不裁決"))
    if s["ruling_due"]:
        for k, c in s["criteria"].items(): print(f"  {k}: {'過' if c.get('pass') else '不過'} {json.dumps({x: y for x, y in c.items() if x != 'pass'}, ensure_ascii=False)}")
    return 2 if s["ruling_due"] else 0


def cmd_selftest(a) -> int:
    prev = {"nav": {p: 100.0 for p in POL}, "exp": {p: 1.0 for p in POL}, "held": {p: 0.5 for p in VT}, "cf": 1.0}
    x = {"r_s": -0.10, "r_conv": -0.10, "r_harv": -0.10, "r_other": 0.0, "r_voo": -0.02, "r_sgov": 0.0, "vol20": 0.50}
    lag = {"w_s": 0.6, "w_voo": 0.3, "w_cl": 0.0, "w_other": 0.0, "conv_share": 0.4, "breaker": True}
    o = step_day(prev, x, lag, True)
    assert abs(o["nav"]["vt25"] - 100 * (1 - 0.05 - COST * 0.5)) < 1e-9, o["nav"]["vt25"]            # 曝險 50%，跌 10% → −5%，另扣調整成本
    assert abs(o["nav"]["vt25_voo"] - 100 * (1 - 0.05 - 0.01 - COST * 0.5)) < 1e-9                  # 閒置放 VOO 多跌 1%
    assert abs(o["held"]["vt25"] - 0.5) < 1e-9 and abs(o["held"]["vt30"] - 0.6) < 1e-9             # 25%÷50%＝0.5 不動；30%÷50%＝0.6 變動達 0.1 就換
    assert abs(o["held"]["vt20"] - 0.4) < 1e-9                                                     # 20%÷50%＝0.4，差剛好 0.1 → 換
    assert abs(o["exp"]["vt25_r15"] - (0.4 * 1.0 + 0.6 * (0.5 - 0.4) / 0.6)) < 1e-9                # 熔斷中信念桶維持 100%，認列桶吸收全部減碼
    assert abs(o["nav"]["actual"] - 100 * (1 + 0.6 * -0.10 + 0.3 * -0.02)) < 1e-9
    assert abs(o["nav"]["park_sgov"] - 100 * (1 + 0.6 * -0.10)) < 1e-9
    lag2 = dict(lag, breaker=False); o2 = step_day(prev, x, lag2, False)
    assert abs(o2["exp"]["vt25_r15"] - 0.5) < 1e-9                                                  # 沒熔斷時與 vt25 相同
    nav = pd.Series([100, 110, 99, 120.0]); st = _stats(nav); assert abs(st["mdd"] - (99 / 110 - 1)) < 1e-4 and st["calmar"] is None
    # 走一遍「到裁決點」的路徑：520 個合成交易日（先跌後漲再跌），確認條件算得出來、不會因缺值炸掉
    rng = np.random.default_rng(7); days = pd.bdate_range(REG, periods=521); rows = []; st_ = dict(prev, held={p: 0.6 for p in VT}); smh = 400.0
    for i, d in enumerate(days):
        drift = -0.004 if i < 60 else 0.004 if i < 260 else -0.002
        rs = float(rng.normal(drift, 0.03)); smh *= 1 + rs * 0.9
        xx = {"r_s": rs, "r_conv": rs * 0.8, "r_harv": rs * 1.1, "r_other": 0.0, "r_voo": rs * 0.4, "r_sgov": 0.00015, "vol20": 0.45}
        ll = {"w_s": 0.65, "w_voo": 0.27, "w_cl": 0.0, "w_other": 0.0, "conv_share": 0.36, "breaker": i < 200}
        st_ = step_day(st_, xx, ll, d.weekday() == 4) if i else st_
        rows.append({"date": str(d.date()), "pre": i == 0, "r_s": rs, "r_sgov": 0.00015, "smh": smh, "breaker": ll["breaker"], "vol20": 0.45,
                     "nav": dict(st_["nav"]), "exp": {**{p: st_["held"][p] for p in VT}, "vt25_r15": 0.6, "actual": 0.65, "park_sgov": 0.65}, "held": dict(st_["held"]), "cf": st_["cf"]})
    sm = summarize(rows); assert sm["days_since_reg"] == 520 and sm["ruling_due"] and set(sm["criteria"]) >= {"vt20", "vt25", "vt30", "r33_within_vt", "r33_standalone", "r15_exception"}, sm["criteria"]
    assert all(isinstance(c["pass"], bool) for c in sm["criteria"].values())
    assert _guard() is None, _guard()                                                               # 現行條件就是登記的那一組
    keep = SPEC["vt"]["mdd_better_pp"]; SPEC["vt"]["mdd_better_pp"] = 4.0
    try: assert _guard() is not None                                                                # 門檻被動過 → 擋下
    finally: SPEC["vt"]["mdd_better_pp"] = keep
    print("selftest ok"); return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="配置政策影子帳（只記錄、不下單）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("update"); u.add_argument("--rebuild", action="store_true"); u.add_argument("--dry-run", action="store_true"); u.set_defaults(fn=cmd_update)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
