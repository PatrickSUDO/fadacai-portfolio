#!/usr/bin/env python3
"""smalln_shadow.py — 小覆蓋名字（分析師 <8 家）revision 訊號被門檻擋下的影子帳（H13，2026-10-08 用戶採用）

Why：規則「<8 家不單獨觸發加減碼」（momentum-valuation-symmetry.md 第 6 節）2026-07-01 補上時沒有結構化案例。
2026-10-08 兩個切片的實測（archive 52 天 54 檔；SA 榜 83 檔首次進榜）都顯示 7–10 月小 N 名字跟著上修訊號做
是負貢獻（<8 家：20 日對 SPY 命中 25–29%、平均 −4% ~ −10%），但樣本小、單一 regime（大型股集中的估值壓縮期）。
用戶問「這樣會不會錯過」——答案是把「錯過」變成可計分的東西：凡小 N 名字出現「上修家數 > 下修」或
「共識 EPS 30 日 ≥ +5%」、且過 H12 趨勢濾網（>SMA50 且 >EMA200）、卻只因 N<8 不能當觸發 → 自動登影子
`cf-smalln-block`（correct_if=under：之後跑輸基準 = 擋對），30 天後由 `shadow_signals.py score` 機械計分。
兩期 /trade-review 命中 >55% 且平均 >0 → 門檻放到 5 家並附幅度條件；仍為負 → 規則留著且帶命中率。

Regime 開關：`fetch_leading.py` gauges.smallcap_rs（IWM 對 SPY 20/60 日相對強度）；smallcap_leading 連續
≥20 日才開啟放寬討論。本工具只把當時 regime 寫進每筆影子，供分組計分。**全部 display-only，不阻擋、不觸發。**

Usage:
  python3 tools/smalln_shadow.py scan [--dry-run] [--asof YYYY-MM-DD] [--max-fetch 25]
  python3 tools/smalln_shadow.py status
Cache：briefing-out/cache/analyst-n.json（yfinance 分析師數，TTL 7 天）、briefing-out/cache/smalln-shadow.json（當日摘要）
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
from shadow_signals import load_signals, save_signals  # noqa: E402

CACHE = ROOT / "briefing-out" / "cache"
N_CACHE = CACHE / "analyst-n.json"
SUMMARY = CACHE / "smalln-shadow.json"
SNAP = CACHE / "fundamentals-snapshot.json"
LEADING = CACHE / "leading-indicators.json"
SMALL_N = 8            # 規則門檻（momentum-valuation-symmetry.md 第 6 節）
PCT_MIN = 5.0          # 共識 EPS 30 日變動 ≥ +5% 也算上修訊號（不看家數）
DEDUP_DAYS = 30
N_TTL_DAYS = 7
SNAP_MAX_AGE_H = 36
KIND = "cf-smalln-block"


def _log(msg: str) -> None:
    print(msg, flush=True)


def _read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def universe() -> dict[str, str]:
    """{ticker: source}，source ∈ bench | sa；排除現持倉、現金等價、sleeve。"""
    out: dict[str, str] = {}
    b = _read_json(ROOT / "research" / "bench.json", {}) or {}
    for t in (b.get("L1") or []) + (b.get("L2") or []):
        out[t.upper()] = "bench"
    files = sorted(glob.glob(str(ROOT / "research" / "sa-quant-scans" / "api-*-*.json")))
    latest: dict[str, str] = {}
    for f in files:
        m = re.search(r"api-(\d{4}-\d{2}-\d{2})-(strong-buy|alpha-pick)\.json$", f)
        if m:
            latest[m.group(2)] = f   # sorted → 最後一個是最新
    for f in latest.values():
        d = _read_json(Path(f), {}) or {}
        for s in d.get("slugs") or []:
            t = (s if isinstance(s, str) else (s.get("ticker") or s.get("slug") or "")).upper()
            if t and t not in out:
                out[t] = "sa"
    r = _read_json(ROOT / "research" / "roster.json", {}) or {}
    held = set()
    for v in (r.get("buckets") or {}).values():
        held |= {x.upper() for x in v}
    held |= {x.upper() for x in (r.get("cash_equivalents") or []) + (r.get("passive_sleeve") or [])}
    return {t: s for t, s in out.items() if t not in held}


def analyst_counts(tickers: list[str], asof: date) -> dict[str, int | None]:
    cache = _read_json(N_CACHE, {}) or {}
    need = [t for t in tickers
            if t not in cache or (asof - date.fromisoformat(cache[t].get("asof", "2000-01-01"))).days > N_TTL_DAYS]
    if need:
        import yfinance as yf
        for t in need:
            try:
                n = yf.Ticker(t).info.get("numberOfAnalystOpinions")
            except Exception:  # noqa: BLE001
                n = None
            cache[t] = {"n": n, "asof": asof.isoformat()}
        N_CACHE.parent.mkdir(parents=True, exist_ok=True)
        N_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return {t: cache.get(t, {}).get("n") for t in tickers}


def ensure_fundamentals(tickers: list[str], max_fetch: int, dry_run: bool) -> dict:
    snap = _read_json(SNAP, {}) or {}
    tk = snap.get("tickers", {})
    stale = []
    gen = snap.get("generated_at") or ""
    try:
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(gen.replace("Z", "+00:00"))).total_seconds() / 3600
    except Exception:  # noqa: BLE001
        age_h = 1e9
    for t in tickers:
        if t not in tk or age_h > SNAP_MAX_AGE_H:
            stale.append(t)
    stale = stale[:max_fetch]
    if stale and not dry_run:
        _log(f"  fetch_fundamentals --ticker {','.join(stale)}（merge）")
        subprocess.run([sys.executable, str(TOOLS / "fetch_fundamentals.py"), "--ticker", ",".join(stale)],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=600)
        snap = _read_json(SNAP, {}) or {}
    return snap.get("tickers", {})


def revision_signal(entry: dict) -> dict | None:
    fe = ((entry or {}).get("snapshot") or {}).get("forward_estimates") or {}
    c = fe.get("curr_fy") or fe.get("next_fy") or {}
    if not c:
        return None
    up = float(c.get("revisions_up_30d") or 0)
    dn = float(c.get("revisions_down_30d") or 0)
    pct = c.get("eps_revision_30d_pct")
    n_eod = c.get("eps_num_analysts")
    fired = (up > dn) or (pct is not None and float(pct) >= PCT_MIN)
    return {"up": up, "down": dn, "pct30": pct, "n_eodhd": n_eod, "fired": fired}


def trend_ok(tickers: list[str]) -> dict[str, dict]:
    """H12 趨勢濾網：收盤 > SMA50 且 > EMA200。抓不到 → None（不擋、標 unknown）。"""
    import yfinance as yf
    out: dict[str, dict] = {}
    if not tickers:
        return out
    px = yf.download(tickers, period="1y", progress=False, auto_adjust=True)["Close"]
    if len(tickers) == 1:
        px = px.to_frame(tickers[0])
    for t in tickers:
        try:
            s = px[t].dropna()
            if len(s) < 200:
                out[t] = {"ok": None, "last": float(s.iloc[-1]) if len(s) else None}
                continue
            last = float(s.iloc[-1]); sma50 = float(s.tail(50).mean()); ema200 = float(s.ewm(span=200, adjust=False).mean().iloc[-1])
            out[t] = {"ok": last > sma50 and last > ema200, "last": round(last, 2), "sma50": round(sma50, 2), "ema200": round(ema200, 2)}
        except Exception:  # noqa: BLE001
            out[t] = {"ok": None, "last": None}
    return out


def regime_now() -> str:
    d = _read_json(LEADING, {}) or {}
    g = (((d.get("blocks") or {}).get("gauges") or d.get("gauges") or {}).get("smallcap_rs")) or {}
    return g.get("regime") or "unknown"


def cmd_scan(args) -> int:
    asof = date.fromisoformat(args.asof) if args.asof else date.today()
    uni = universe()
    ns = analyst_counts(sorted(uni), asof)
    small = sorted(t for t, n in ns.items() if n is not None and n < SMALL_N)
    _log(f"universe {len(uni)}（bench {sum(1 for s in uni.values() if s=='bench')} / SA {sum(1 for s in uni.values() if s=='sa')}）→ <{SMALL_N} 家：{len(small)} 檔 {small}")
    tk = ensure_fundamentals(small, args.max_fetch, args.dry_run)
    sigs = {t: revision_signal(tk.get(t)) for t in small}
    fired = [t for t, s in sigs.items() if s and s["fired"]]
    trends = trend_ok(fired)
    regime = regime_now()
    existing = load_signals()
    recent = {r["ticker"] for r in existing if r.get("signal") == KIND
              and (asof - date.fromisoformat(r["date"])).days <= DEDUP_DAYS}
    recorded, dup, no_trend, no_price = [], [], [], []
    rows = []
    for t in fired:
        s = sigs[t]; tr = trends.get(t, {})
        if tr.get("ok") is False:
            no_trend.append(t); continue
        if not tr.get("last"):
            no_price.append(t); continue
        if t in recent:
            dup.append(t); continue
        note = (f"H13 小 N 影子：N={ns[t]}（EODHD {s['n_eodhd']}）up:down={s['up']:.0f}:{s['down']:.0f} "
                f"pct30={s['pct30']} 來源={uni[t]} regime={regime} 趨勢={'過' if tr.get('ok') else '未知'}；"
                f"revision 訊號成立但 <{SMALL_N} 家門檻不得單獨觸發 → 未買。30d 跑輸基準 = 擋對")
        rows.append({"date": asof.isoformat(), "ticker": t, "signal": KIND, "ref_price": tr["last"], "size_usd": None,
                     "note": note, "correct_if": "under", "mode": "shadow", "status": "open",
                     "n_analysts": ns[t], "rev_up": s["up"], "rev_down": s["down"], "pct30": s["pct30"],
                     "source": uni[t], "regime": regime, "trend_ok": tr.get("ok")})
        recorded.append(t)
    if rows and not args.dry_run:
        save_signals(existing + rows)
    summary = {"asof": asof.isoformat(), "regime": regime, "universe": len(uni), "small_n": small,
               "n_by_ticker": {t: ns[t] for t in small}, "fired": fired, "recorded": recorded,
               "skipped_dup": dup, "blocked_by_trend": no_trend, "no_price": no_price,
               "signals": {t: sigs[t] for t in fired}, "trend": trends, "dry_run": args.dry_run,
               "note": "display-only（H13）；計分 shadow_signals.py score；兩期 /trade-review 後裁門檻"}
    if not args.dry_run:
        SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    _log(f"fired {len(fired)} → 登錄 {len(recorded)} {recorded}｜重複 {len(dup)}｜趨勢未過 {len(no_trend)} {no_trend}｜regime={regime}")
    return 0


def cmd_status(_args) -> int:
    s = _read_json(SUMMARY, {}) or {}
    print(json.dumps(s, ensure_ascii=False, indent=1))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan", help="掃小 N 名字的上修訊號，登影子 cf-smalln-block")
    sc.add_argument("--dry-run", action="store_true")
    sc.add_argument("--asof", default=None)
    sc.add_argument("--max-fetch", type=int, default=25, help="單次最多補抓幾檔 EODHD fundamentals")
    sc.set_defaults(fn=cmd_scan)
    st = sub.add_parser("status", help="印出最近一次摘要")
    st.set_defaults(fn=cmd_status)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
