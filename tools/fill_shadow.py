#!/usr/bin/env python3
"""fill_shadow.py — 成交當下自動登的兩個影子（2026-11-10 用戶「財報窗放影子、波動倒數也放影子」）

兩個假說都來自 2026-11-10 的回測（tools/backtests/README.md 同日段），都只是「值得記錄」而不是「值得改規則」：

1. **波動倒數部位**（`cf-volsize-high` / `cf-volsize-low`）
   回測 `inverse_vol_sizing_2026-11-10.py`：2026-06→09 的 119 筆個股買進，高波動半 30 日超額 −4.4%、低波動半 +4.2%；
   金額改成「× 中位波動 ÷ 該股波動，夾 0.5–1.0」後金額加權超額 +0.65pp。只有四個買進月、基準在跌。
   登錄：每筆個股買進（同檔同日併一筆）算 `vol_ratio` = 該股 60 日日波動 ÷ 近 120 天買過的個股的 60 日波動中位數。
     ratio > 1 → `cf-volsize-high`、correct_if=under（高波動買單跑輸基準 = 假說對）
     ratio ≤ 1 → `cf-volsize-low`、 correct_if=over （低波動買單跑贏基準 = 假說對）
   `mult` = clip(1/ratio, 0.5, 1.0) 是「若照波動倒數會下的金額倍數」，`score` 用它算兩種加權的差。

2. **財報前賣出**（`cf-preearn-sell`）
   回測 `earnings_window_direction_2026-11-10.py`：30 檔 903 次財報，財報前 10 日內賣出、到財報反應後一日平均少賺
   1.1–1.5pp（t 2.3–2.7）；拉長到 60 日不顯著，且名單是今天的贏家。
   登錄：每筆個股賣出（同檔同日併一筆），若下一次財報在之後 10 個交易日內 → correct_if=under
   （賣出後跑輸基準 = 賣對；命中率低 = 賣早）。`score` 另算「賣出價 → 財報反應後一日收盤」的超額（回測顯著的那一窗）。

**display-only**：不擋單、不改金額、不延後賣單。兩期 /trade-review 後才討論要不要動 H10／R30 的金額公式或 R8 的掛單時點。
ETF、現金等價物、選擇權不登。

Usage:
  python3 tools/fill_shadow.py scan [--days 7] [--asof YYYY-MM-DD] [--dry-run]     # runner 每日跑；看最近 N 天成交
  python3 tools/fill_shadow.py backfill --from YYYY-MM-DD [--to ...] [--dry-run]    # note 標 backfill
  python3 tools/fill_shadow.py score [--asof YYYY-MM-DD]                            # 寫 briefing-out/cache/fill-shadow.json
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from shadow_signals import load_signals, save_signals  # noqa: E402
from trade_ledger import benchmark_for  # noqa: E402

LEDGER = ROOT / "research" / "trade-ledger.jsonl"
ROSTER = ROOT / "research" / "roster.json"
EARN_CACHE = ROOT / "briefing-out" / "cache" / "earnings-dates.json"
SUMMARY = ROOT / "briefing-out" / "cache" / "fill-shadow.json"
K_HIGH, K_LOW, K_PRE = "cf-volsize-high", "cf-volsize-low", "cf-preearn-sell"
VOL_N = 60               # 日波動視窗
REF_DAYS = 120           # 參考中位數：近 120 個日曆日買過的個股
PRE_WINDOW = 10          # 財報前幾個交易日內的賣出才登
HORIZON = 30             # volsize 計分：買進後 30 個交易日
MIN_NOTIONAL = 200       # 零股／畸零單不登（2026-10-20 GOOGL $1.14 這種）
ETFS = {"SPY", "VOO", "IVV", "QQQ", "QQQM", "SMH", "SOXX", "IGV", "IWM", "DIA", "VTI", "VGT", "XLK", "XLE", "XLF",
        "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLC", "GLD", "IAU", "SLV", "TLT", "IEF", "SHY", "SGOV", "BIL",
        "QLD", "USD", "TQQQ", "SOXL", "SSO", "UPRO", "TECL", "VO", "VXUS", "ARKK", "URA", "ITA", "PAVE"}


def _etfs() -> set:
    try:
        r = json.loads(ROSTER.read_text())
        extra = set(r.get("cash_equivalents", [])) | set(r.get("benchmark_parking", [])) | set(r.get("passive_sleeve", [])) | set(r.get("benchmark_slots", []))
    except Exception:  # noqa: BLE001
        extra = set()
    return ETFS | {str(x).upper() for x in extra}


def stock_fills(frm: str, to: str, side: str) -> list[dict]:
    """ledger 裡 [frm, to] 的個股成交，同檔同日併一筆（金額合計、均價）。"""
    etf, agg = _etfs(), {}
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        f = json.loads(line)
        if f.get("is_option") or f.get("side") != side or not (frm <= f.get("date", "") <= to):
            continue
        sym = f["symbol"].upper()
        if sym in etf or not f.get("qty") or not f.get("price"):
            continue
        a = agg.setdefault((f["date"], sym), {"date": f["date"], "symbol": sym, "qty": 0.0, "notional": 0.0, "origins": set()})
        a["qty"] += abs(f["qty"]); a["notional"] += abs(f.get("notional") or f["qty"] * f["price"]); a["origins"].add(f.get("origin") or "unknown")
    out = []
    for a in agg.values():
        if a["notional"] < MIN_NOTIONAL:
            continue
        a["price"] = round(a["notional"] / a["qty"], 4); a["notional"] = round(a["notional"], 2); a["origin"] = "/".join(sorted(a.pop("origins")))
        out.append(a)
    return sorted(out, key=lambda x: (x["date"], x["symbol"]))


def closes(symbols, start: str, end: str):
    import pandas as pd  # noqa: PLC0415
    import yfinance as yf  # noqa: PLC0415
    syms = sorted({s.replace(".", "-") for s in symbols})
    px = yf.download(syms, start=start, end=(date.fromisoformat(end) + timedelta(days=1)).isoformat(), progress=False, auto_adjust=True)["Close"]
    if isinstance(px, pd.Series):
        px = px.to_frame(syms[0])
    px = px[px.index.date <= date.fromisoformat(end)]      # yfinance 午夜後會多回一根隔日 bar
    px.columns = [c.replace("-", ".") for c in px.columns]
    return px


def _dup(rows, d, sym, kinds) -> bool:
    return any(r.get("date") == d and r.get("ticker") == sym and r.get("signal") in kinds for r in rows)


def volsize_rows(buys, existing, tag=""):
    """每筆買進 → 一列影子。參考中位數只用買進日「之前」的資料（波動 shift 1 日）。"""
    import numpy as np  # noqa: PLC0415
    if not buys:
        return []
    first = min(b["date"] for b in buys); last = max(b["date"] for b in buys)
    ref_from = (date.fromisoformat(first) - timedelta(days=REF_DAYS)).isoformat()
    ref_buys = stock_fills(ref_from, last, "BOUGHT")
    px = closes({b["symbol"] for b in ref_buys} | {b["symbol"] for b in buys},
                (date.fromisoformat(ref_from) - timedelta(days=VOL_N * 2)).isoformat(), last)
    vol = np.log(px).diff().rolling(VOL_N).std().shift(1)
    out = []
    for b in buys:
        d, sym = b["date"], b["symbol"]
        if _dup(existing + out, d, sym, (K_HIGH, K_LOW)) or sym not in vol.columns:
            continue
        row_i = vol.index[vol.index.date <= date.fromisoformat(d)]
        if not len(row_i):
            continue
        v = vol.loc[row_i[-1]]
        lo = (date.fromisoformat(d) - timedelta(days=REF_DAYS)).isoformat()
        names = {x["symbol"] for x in ref_buys if lo <= x["date"] <= d} | {sym}
        ref = v[[n for n in names if n in v.index]].dropna()
        if sym not in ref.index or len(ref) < 5:
            continue
        ratio = float(ref[sym] / ref.median()); mult = float(min(1.0, max(0.5, 1 / ratio)))
        high = ratio > 1
        out.append({"date": d, "ticker": sym, "signal": K_HIGH if high else K_LOW, "ref_price": b["price"], "size_usd": b["notional"],
                    "vol_ratio": round(ratio, 2), "mult": round(mult, 2), "vol60_daily_pct": round(float(ref[sym]) * 100, 2),
                    "ref_names": int(len(ref)), "origin": b["origin"],
                    "note": f"{tag}買進 ${b['notional']:,.0f}；60 日波動是近期買進名字中位數的 {ratio:.2f} 倍 → 波動倒數會下 {mult:.2f} 倍"
                            f"（${b['notional'] * mult:,.0f}）；{'高波動：跑輸基準' if high else '低波動：跑贏基準'} = 假說對（display-only）",
                    "correct_if": "under" if high else "over", "mode": "shadow", "status": "open"})
    return out


def next_earnings(sym: str, d: str, use_cache: bool):
    """回傳 (日期, timing)；找不到回 (None, None)。live 掃描先讀 briefing 快取，回補與快取沒有的走 yfinance。"""
    if use_cache:
        try:
            t = json.loads(EARN_CACHE.read_text())["tickers"].get(sym)
            if t and t.get("next_date") and t["next_date"] >= d:
                return t["next_date"], (t.get("timing") or "")
        except Exception:  # noqa: BLE001
            pass
    try:
        import yfinance as yf  # noqa: PLC0415
        ed = yf.Ticker(sym.replace(".", "-")).get_earnings_dates(limit=16)
        ts = sorted(t for t in ed.index if t.date().isoformat() >= d)
        if ts:
            t = ts[0]
            return t.date().isoformat(), ("AMC" if t.hour >= 16 else "BMO" if t.hour < 10 else "")
    except Exception:  # noqa: BLE001
        pass
    return None, None


def preearn_rows(sells, existing, use_cache: bool, tag=""):
    import numpy as np  # noqa: PLC0415
    out = []
    for s in sells:
        d, sym = s["date"], s["symbol"]
        if _dup(existing + out, d, sym, (K_PRE,)):
            continue
        e, timing = next_earnings(sym, d, use_cache)
        if not e:
            continue
        n = int(np.busday_count(d, e))
        if n > PRE_WINDOW or n < 0 or (n == 0 and timing != "AMC"):   # 當日盤前已公布的不算「財報前」
            continue
        out.append({"date": d, "ticker": sym, "signal": K_PRE, "ref_price": s["price"], "size_usd": s["notional"],
                    "earnings_date": e, "earnings_timing": timing, "days_to_earnings": n, "origin": s["origin"],
                    "note": f"{tag}賣出 ${s['notional']:,.0f}，距財報（{e} {timing or '時段未知'}）{n} 個交易日；"
                            "之後跑輸基準 = 賣對，命中率低 = 財報前賣早（display-only）",
                    "correct_if": "under", "mode": "shadow", "status": "open"})
    return out


def _run(frm: str, to: str, dry: bool, use_cache: bool, tag: str) -> dict:
    rows = load_signals()
    new = volsize_rows(stock_fills(frm, to, "BOUGHT"), rows, tag) + preearn_rows(stock_fills(frm, to, "SOLD"), rows, use_cache, tag)
    if new and not dry:
        save_signals(rows + new)
    return {"window": [frm, to], "dry_run": dry, "recorded": len(new),
            "by_kind": {k: sum(r["signal"] == k for r in new) for k in (K_HIGH, K_LOW, K_PRE)},
            "rows": [{k: r.get(k) for k in ("date", "ticker", "signal", "size_usd", "vol_ratio", "mult", "earnings_date", "days_to_earnings")} for r in new]}


def cmd_scan(a) -> int:
    asof = a.asof or date.today().isoformat()
    out = _run((date.fromisoformat(asof) - timedelta(days=a.days)).isoformat(), asof, a.dry_run, True, "")
    print(json.dumps(out, ensure_ascii=False)); return 0


def cmd_backfill(a) -> int:
    out = _run(a.frm, a.to or date.today().isoformat(), a.dry_run, False, "backfill ")
    print(json.dumps(out, ensure_ascii=False)); return 0


def cmd_score(a) -> int:
    """volsize：買進後 30 個交易日對基準超額，兩種加權的差。preearn：賣出價 → 財報反應後一日收盤的超額。"""
    import numpy as np  # noqa: PLC0415
    asof = a.asof or date.today().isoformat()
    rows = [r for r in load_signals() if r.get("signal") in (K_HIGH, K_LOW, K_PRE)]
    if not rows:
        print(json.dumps({"n": 0, "note": "尚無 fill_shadow 影子"})); return 0
    syms = {r["ticker"] for r in rows}; bench = {s: benchmark_for(s)[:-3] for s in syms}
    px = closes(syms | set(bench.values()), (date.fromisoformat(min(r["date"] for r in rows)) - timedelta(days=5)).isoformat(), asof)
    idx = px.index

    def loc(d):       # d 當日或之前最後一根的位置
        p = np.flatnonzero(idx.date <= date.fromisoformat(d)); return int(p[-1]) if len(p) else None

    def excess(sym, p0, i0, i1):
        b = bench[sym]
        if sym not in px.columns or b not in px.columns or i1 >= len(idx):
            return None
        s1, b0, b1 = px[sym].iloc[i1], px[b].iloc[i0], px[b].iloc[i1]
        if not (np.isfinite(s1) and np.isfinite(b0) and np.isfinite(b1)):
            return None
        return float(s1 / p0 - 1 - (b1 / b0 - 1))

    vs, pe = [], []
    for r in rows:
        i0 = loc(r["date"])
        if i0 is None:
            continue
        # 用當日還原收盤當起點（ref_price 是未還原成交價，遇配息會差一點；兩種加權同一把尺）
        p0 = float(px[r["ticker"]].iloc[i0]) if r["ticker"] in px.columns else None
        if not p0 or not np.isfinite(p0):
            continue
        if r["signal"] in (K_HIGH, K_LOW):
            x = excess(r["ticker"], p0, i0, i0 + HORIZON)
            if x is not None:
                vs.append({"date": r["date"], "ticker": r["ticker"], "high": r["signal"] == K_HIGH, "x": x,
                           "size": r.get("size_usd") or 0.0, "mult": r.get("mult") or 1.0})
        else:
            ie = loc(r["earnings_date"])
            if ie is None or idx[ie].date() < date.fromisoformat(r["earnings_date"]):
                continue                                     # 財報日還沒到
            i1 = ie + (1 if r.get("earnings_timing") == "BMO" else 2)   # 反應日後一日；時段未知取 +2 涵蓋盤後
            x = excess(r["ticker"], p0, i0, i1)
            if x is not None:
                pe.append({"date": r["date"], "ticker": r["ticker"], "x": x, "size": r.get("size_usd") or 0.0,
                           "days_to_earnings": r.get("days_to_earnings")})

    def band(xs):
        return None if not xs else {"n": len(xs), "mean_excess_pct": round(100 * float(np.mean([v["x"] for v in xs])), 2),
                                    "share_positive_pct": round(100 * float(np.mean([v["x"] > 0 for v in xs])), 1)}

    def wavg(xs, w):
        tot = sum(w); return round(100 * sum(v["x"] * wi for v, wi in zip(xs, w)) / tot, 2) if tot else None

    out = {"asof": asof, "recorded": {k: sum(r["signal"] == k for r in rows) for k in (K_HIGH, K_LOW, K_PRE)},
           "volsize": {"horizon_trading_days": HORIZON, "high_vol": band([v for v in vs if v["high"]]), "low_vol": band([v for v in vs if not v["high"]]),
                       "actual_weighted_excess_pct": wavg(vs, [v["size"] for v in vs]) if vs else None,
                       "inverse_vol_weighted_excess_pct": wavg(vs, [v["size"] * v["mult"] for v in vs]) if vs else None,
                       "reading": "假說成立＝高波動組平均超額低於低波動組，且波動倒數加權 > 實際加權；n<60 或買進月份 <6 個不裁決"},
           "preearn_sell": {**(band(pe) or {"n": 0}), "size_weighted_excess_pct": wavg(pe, [v["size"] for v in pe]) if pe else None,
                            "window": "賣出日收盤 → 財報反應後一日收盤，個股減基準",
                            "reading": "平均超額 > 0 ＝賣出後股價跑贏基準＝賣早；n<30 不裁決"},
           "display_only": True}
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False)); return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("--days", type=int, default=7); s.add_argument("--asof"); s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_scan)
    b = sub.add_parser("backfill"); b.add_argument("--from", dest="frm", required=True); b.add_argument("--to"); b.add_argument("--dry-run", action="store_true")
    b.set_defaults(fn=cmd_backfill)
    c = sub.add_parser("score"); c.add_argument("--asof"); c.set_defaults(fn=cmd_score)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
