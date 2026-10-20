#!/usr/bin/env python3
"""discovery_scan.py — 發現層：跨板塊「及早選到」掃描（R34，2026-10-20 用戶「關鍵是怎麼及早選到」）

Why：2026 YTD 贏 SMH 的非半導體大型股 48 檔，**全部**在年內出現過同一個可機械偵測的新鮮訊號
（63 日對 SPY 相對強度 ≥ +15pp 且 收盤 > SMA50 > SMA200，且前 60 個交易日沒出現過），
首次訊號日中位 2025-12-03、訊號後到 10/20 中位還有 +64%。但訊號精確率只有 28%（全宇宙 417 次新鮮訊號，
之後 63 日對 SPY 超額平均 −0.4%、勝率 43%）。**結論：這個訊號是「必要條件」不是「充分條件」——及早選到靠的是
撒網小倉 + 確認加碼 + 快砍啞火，不是預測。** 本工具只做撒網：每日列新鮮訊號，寫發現帳，63 日後機械計分。

Usage:
  python3 tools/discovery_scan.py scan [--refresh-universe] [--rs 15] [--top 45]
  python3 tools/discovery_scan.py score        # 到期（≥63 交易日）訊號補 63 日對 SPY 超額
  python3 tools/discovery_scan.py stats
輸出：briefing-out/cache/discovery.json（當日新鮮訊號，板塊各最多 3 檔）、research/discovery-signals.jsonl（發現帳）
display-only：進 briefing Key Alerts 一行 + L2 候選；進場走 R34 sizing（starter 1%，+20 日仍過濾網且修正 up>down 才補；RS63 轉負砍）。
"""
import argparse, json, warnings, collections, glob, re
from datetime import date
from pathlib import Path
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "briefing-out" / "cache"; UNI = CACHE / "universe.json"; OUT = CACHE / "discovery.json"
LEDGER = ROOT / "research" / "discovery-signals.jsonl"
SECTORS = ['technology','healthcare','financial-services','consumer-cyclical','industrials','communication-services','consumer-defensive','energy','basic-materials','real-estate','utilities']
SEMI = {'NVDA','AVGO','AMD','MU','TSM','ASML','AMAT','LRCX','KLAC','QCOM','TXN','ADI','MRVL','ARM','INTC','NXPI','MCHP','ON','MPWR','SNDK','STX','WDC'}

def load_universe(refresh: bool, top: int) -> dict:
    if UNI.exists() and not refresh:
        d = json.loads(UNI.read_text())
        if (date.today() - date.fromisoformat(d.get("asof", "2000-01-01"))).days < 7:
            return d["tickers"]
    uni = {}
    for k in SECTORS:
        try:
            for t in list(yf.Sector(k).top_companies.index)[:top]:
                uni[t] = k
        except Exception:
            pass
    # SA 榜 + bench 一併納入（板塊標 unknown）
    for f in glob.glob(str(ROOT / "research/sa-quant-scans/api-*-*.json")):
        try:
            for s in json.load(open(f)).get("slugs") or []:
                t = (s if isinstance(s, str) else s.get("ticker") or s.get("slug") or "").upper()
                if t and t not in uni: uni[t] = "sa-list"
        except Exception:
            pass
    b = json.loads((ROOT / "research/bench.json").read_text()) if (ROOT / "research/bench.json").exists() else {}
    for t in (b.get("L1") or []) + (b.get("L2") or []):
        uni.setdefault(t, "bench")
    UNI.write_text(json.dumps({"asof": date.today().isoformat(), "tickers": uni}, ensure_ascii=False, indent=1))
    return uni

def cmd_scan(a):
    uni = load_universe(a.refresh_universe, a.top)
    roster = json.loads((ROOT / "research/roster.json").read_text())
    held = set(sum(roster.get("buckets", {}).values(), [])) | set(roster.get("passive_sleeve", [])) | set(roster.get("cash_equivalents", []))
    tk = sorted(set(uni) - held)
    px = yf.download(tk + ["SPY", "SMH"], period="15mo", progress=False, auto_adjust=True, threads=True)["Close"].ffill()
    spy = px["SPY"]; today = px.index[-1].strftime("%Y-%m-%d")
    fresh, allsig, active = [], 0, []
    for t in tk:
        if t not in px.columns: continue
        s = px[t].dropna()
        if len(s) < 230: continue
        rs = (s / s.shift(63) - 1) - (spy.reindex(s.index) / spy.reindex(s.index).shift(63) - 1)
        sma50 = s.rolling(50).mean(); sma200 = s.rolling(200).mean()
        sig = (rs >= a.rs / 100) & (s > sma50) & (sma50 > sma200)
        if not bool(sig.iloc[-1]): continue
        allsig += 1
        ext50 = float(s.iloc[-1] / sma50.iloc[-1] - 1) * 100
        active.append({"ticker": t, "sector": uni.get(t), "rs63_pp": round(float(rs.iloc[-1]) * 100, 1), "ext_sma50_pct": round(ext50, 1), "semi": t in SEMI,
                       "days_in_signal": int(sig.iloc[::-1].cummin().sum())})
        if bool(sig.iloc[-61:-1].any()): continue           # 前 60 日出現過 → 不新鮮
        fresh.append({"ticker": t, "sector": uni.get(t), "close": round(float(s.iloc[-1]), 2), "rs63_pp": round(float(rs.iloc[-1]) * 100, 1),
                      "ext_sma50_pct": round(ext50, 1), "ytd_pct": round(float(s.iloc[-1] / s[s.index.year == date.today().year].iloc[0] - 1) * 100, 1) if (s.index.year == date.today().year).any() else None,
                      "semi": t in SEMI, "note": "延伸 >25% 只觀察不起手（R31 精神）" if ext50 > 25 else ""})
    fresh.sort(key=lambda r: -r["rs63_pp"])
    # 板塊各最多 3 檔進顯示；全部進發現帳
    shown, cnt = [], collections.Counter()
    for r in fresh:
        if cnt[r["sector"]] < 3: shown.append(r); cnt[r["sector"]] += 1
    # 發現帳（同日同標的去重）
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()] if LEDGER.exists() else []
    seen = {(r["date"], r["ticker"]) for r in rows}
    new = [{"date": today, **{k: r[k] for k in ("ticker", "sector", "close", "rs63_pp", "ext_sma50_pct", "semi")}, "status": "open"} for r in fresh if (today, r["ticker"]) not in seen]
    with LEDGER.open("a", encoding="utf-8") as fh:
        for r in new: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    active.sort(key=lambda r: -r["rs63_pp"])
    OUT.write_text(json.dumps({"asof": today, "universe": len(tk), "in_signal": allsig, "fresh": fresh, "shown": shown, "active_top": active[:15],
                               "rule": "display-only（R34）：新鮮訊號 = 63 日對 SPY ≥ +15pp 且 收盤>SMA50>SMA200 且前 60 日未出現；精確率 ~28%，是撒網不是預測。進場走 R34 sizing"}, ensure_ascii=False, indent=1))
    print(f"universe {len(tk)}｜在訊號中 {allsig}｜今日新鮮 {len(fresh)}（登帳 {len(new)}）")
    for r in shown: print(f"  {r['ticker']:<6}{str(r['sector']):<22} RS63 {r['rs63_pp']:+6.1f}pp  距 SMA50 {r['ext_sma50_pct']:+5.1f}%  YTD {r['ytd_pct']}  {r['note']}")
    print("  仍在訊號中（非新鮮，供參考）前 12：", ", ".join(f"{r['ticker']}({r['sector'][:4]} RS{r['rs63_pp']:+.0f} {r['days_in_signal']}d)" for r in active[:12]))
    return 0

def cmd_score(a):
    if not LEDGER.exists(): print("no ledger"); return 0
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    due = [r for r in rows if r.get("status") == "open" and (date.today() - date.fromisoformat(r["date"])).days >= 92]
    if not due: print("nothing due"); return 0
    tk = sorted({r["ticker"] for r in due} | {"SPY"})
    px = yf.download(tk, start=min(r["date"] for r in due), progress=False, auto_adjust=True)["Close"].ffill()
    for r in due:
        try:
            s = px[r["ticker"]].dropna(); i = s.index.get_indexer([pd.Timestamp(r["date"])], method="bfill")[0]
            if i + 63 >= len(s): continue
            ex = (float(s.iloc[i + 63] / s.iloc[i] - 1) - float(px["SPY"].loc[s.index[i + 63]] / px["SPY"].loc[s.index[i]] - 1)) * 100
            r.update(status="scored", excess_63d_pp=round(ex, 1), hit=ex > 0)
        except Exception:
            pass
    LEDGER.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print("scored", sum(1 for r in due if r.get("status") == "scored")); return 0

def cmd_stats(a):
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()] if LEDGER.exists() else []
    sc = [r for r in rows if r.get("status") == "scored"]
    print(f"發現帳 {len(rows)} 筆，已計分 {len(sc)}" + (f"：勝率 {np.mean([r['hit'] for r in sc]):.0%}，63 日超額平均 {np.mean([r['excess_63d_pp'] for r in sc]):+.1f}pp" if sc else ""))
    return 0

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("--refresh-universe", action="store_true"); s.add_argument("--rs", type=float, default=15); s.add_argument("--top", type=int, default=45); s.set_defaults(fn=cmd_scan)
    sub.add_parser("score").set_defaults(fn=cmd_score); sub.add_parser("stats").set_defaults(fn=cmd_stats)
    a = ap.parse_args(); return a.fn(a)

if __name__ == "__main__":
    raise SystemExit(main())
