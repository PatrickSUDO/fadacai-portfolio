#!/usr/bin/env python3
"""rotation_corr.py — 輪動相關性儀表（2026-09-14，用戶提問「軟體 vs 硬體最近負相關？」）

機械地算籃子對的滾動相關，並用統計門檻擋住「明明沒相關硬說有」：
  * 短窗 20d / 中窗 60d / 基準 252d 的 Pearson ρ（等權日報酬）
  * Fisher z 95% CI；ρ 的敘述只准三種：正相關(CI 下界>0) / 負相關(CI 上界<0) / 不顯著(CI 跨 0)
  * regime-shift 旗標：短窗 CI 與基準 CI 不重疊 且 |Δρ|≥0.30 且連續 ≥3 天 — 其餘一律「無顯著變化」
  * 每天把狀態 append 到 research/rotation-corr-log.jsonl，供 /trade-review 驗 H8（旗標後 10 日兩籃相對報酬是否 ≥5pp）

display-only。不觸發任何加減碼。
Run: uv run --directory tools python3 tools/rotation_corr.py [--force]
Out: briefing-out/cache/rotation-corr.json（TTL 20h）+ 終端一行摘要
"""
import json, math, os, sys, time
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "research", "rotation-config.json")
OUT = os.path.join(ROOT, "briefing-out", "cache", "rotation-corr.json")
LOG = os.path.join(ROOT, "research", "rotation-corr-log.jsonl")
TTL_H = 20


def fisher_ci(r, n, z=1.96):
    if n < 4 or abs(r) >= 1:
        return (r, r)
    zr = math.atanh(r); se = 1 / math.sqrt(n - 3)
    return (math.tanh(zr - z * se), math.tanh(zr + z * se))


def describe(r, lo, hi):
    if lo > 0:
        return "正相關"
    if hi < 0:
        return "負相關"
    return "不顯著"


def main():
    force = "--force" in sys.argv
    if not force and os.path.exists(OUT) and (time.time() - os.path.getmtime(OUT)) < TTL_H * 3600:
        d = json.load(open(OUT)); print(d.get("banner", "(cache)")); return 0
    import yfinance as yf, pandas as pd
    cfg = json.load(open(CFG))
    tickers = sorted({t for b in cfg["baskets"].values() for t in b})
    start = (date.today() - timedelta(days=int(cfg["windows"]["baseline"] * 1.6) + 30)).isoformat()
    px = yf.download(tickers, start=start, auto_adjust=True, progress=False)["Close"].dropna(how="all")
    ret = px.pct_change().dropna(how="all")
    bask = {}
    for name, members in cfg["baskets"].items():
        cols = [m for m in members if m in ret.columns]
        if not cols:
            continue
        bask[name] = ret[cols].mean(axis=1)  # 等權
    W = cfg["windows"]; R = cfg["flag_rules"]
    # 讀取歷史 log 以判 persist
    hist = []
    if os.path.exists(LOG):
        hist = [json.loads(l) for l in open(LOG) if l.strip()]
    pairs_out = []
    for a, b in cfg["pairs"]:
        if a not in bask or b not in bask:
            continue
        df = pd.concat([bask[a], bask[b]], axis=1, keys=[a, b]).dropna()
        res = {"pair": f"{a}~{b}"}
        for label, w in (("short", W["short"]), ("mid", W["mid"]), ("baseline", W["baseline"])):
            sub = df.tail(w)
            n = len(sub)
            r = float(sub[a].corr(sub[b])) if n >= R["min_obs"] else float("nan")
            lo, hi = fisher_ci(r, n) if n >= R["min_obs"] else (float("nan"), float("nan"))
            res[label] = {"n": n, "rho": None if math.isnan(r) else round(r, 3),
                          "ci": [None if math.isnan(lo) else round(lo, 3), None if math.isnan(hi) else round(hi, 3)],
                          "label": describe(r, lo, hi) if n >= R["min_obs"] else "樣本不足"}
        s, bl = res["short"], res["baseline"]
        shift_today = False
        if s["rho"] is not None and bl["rho"] is not None:
            delta = s["rho"] - bl["rho"]
            no_overlap = (s["ci"][1] < bl["ci"][0]) or (s["ci"][0] > bl["ci"][1])
            shift_today = bool(no_overlap and abs(delta) >= R["min_abs_delta_vs_baseline"])
            res["delta_vs_baseline"] = round(delta, 3)
        # persist：往回看 log 中同 pair 最近 (persist_days-1) 天是否也 shift_today
        prev = [h for h in hist if h.get("pair") == res["pair"]][-(R["persist_days"] - 1):]
        persisted = shift_today and len(prev) == R["persist_days"] - 1 and all(h.get("shift_today") for h in prev)
        res["shift_today"] = shift_today
        res["regime_shift"] = persisted
        # 10 日相對報酬（供 H8 事後驗證：旗標日之後 10 日兩籃差）
        res["rel_ret_10d_pct"] = round(float((df[a].tail(10) - df[b].tail(10)).sum() * 100), 2)
        pairs_out.append(res)
    today = date.today().isoformat()
    with open(LOG, "a") as f:
        for p in pairs_out:
            f.write(json.dumps({"date": today, **{k: p[k] for k in ("pair", "shift_today", "regime_shift", "delta_vs_baseline", "rel_ret_10d_pct") if k in p},
                                "short_rho": p["short"]["rho"], "baseline_rho": p["baseline"]["rho"]}, ensure_ascii=False) + "\n")
    shifts = [p for p in pairs_out if p["regime_shift"]]
    key = next((p for p in pairs_out if p["pair"] == "own_software~own_semis"), None)
    banner = "🔁 輪動相關: "
    if key:
        banner += f"軟體~半導體 20d ρ {key['short']['rho']:+.2f}（{key['short']['label']}，基準 {key['baseline']['rho']:+.2f}）"
    banner += " | regime-shift: " + (", ".join(p["pair"] for p in shifts) if shifts else "無顯著變化")
    out = {"status": "ok", "generated_at": today, "windows": W, "flag_rules": R, "pairs": pairs_out,
           "regime_shifts": [p["pair"] for p in shifts], "banner": banner,
           "discipline": "display-only；『負相關』只在 95% CI 上界<0 時可寫；regime-shift 需 CI 不重疊+|Δρ|≥0.30+連 3 天；H8 由 /trade-review 驗"}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=2)
    print(banner)
    for p in pairs_out:
        print(f"  {p['pair']:<26} 20d {p['short']['rho']!s:>6} [{p['short']['label']}]  60d {p['mid']['rho']!s:>6}  252d {p['baseline']['rho']!s:>6}  Δ {p.get('delta_vs_baseline')!s:>6}  {'⚑shift' if p['shift_today'] else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
