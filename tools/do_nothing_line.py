#!/usr/bin/env python3
"""do_nothing_line.py — 「完全不交易」對照線（2026-11-22 用戶：「做對照線」）

回答一個問題：這段期間的買賣，比起「期初持股原封不動」是加分還是扣分。

做法（每次從帳本整段重算，不留狀態）：
  1. 期初持股 = 現在的持股（research/position-state.json）倒推回去：扣掉期初之後帳本上的每一筆買賣。
     2026 年以前的帳本不完整，所以用倒推，不用從頭累加。拆股用 yfinance 的拆股紀錄換成現在的股數單位。
  2. 凍結線 = 期初那批股票用含息價一路算到期末；現金與選擇權當作不動。
  3. 實際線 = research/equity-marks.json 的帳戶總值標記（與 account_metrics 同一份）。
  4. 交易貢獻 = 實際報酬 − 凍結報酬。正數代表這段期間的買賣有加分。

限制（輸出裡也會印）：
  - 期初若持有選擇權，凍結線把它當作價值不變（沒有歷史選擇權報價）。「非股票佔比」那欄大的期間要保守看。
  - 年初到 6 月初只有三個手動淨值點，所以上半年只算成一整段。
  - 凍結線沒有停損也沒有再平衡，它是量尺，不是建議的做法。

Usage:
  python3 tools/do_nothing_line.py            # 印摘要並寫 briefing-out/cache/do-nothing-line.json
  python3 tools/do_nothing_line.py --lines    # 只印給報告用的三行
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
LEDGER = ROOT / "research" / "trade-ledger.jsonl"
STATE = ROOT / "research" / "position-state.json"
OUT = ROOT / "briefing-out" / "cache" / "do-nothing-line.json"
YEAR_START = "2026-01-01"          # equity-marks 的手動年初錨（= 2025-12-31 收盤）
PRICE_FROM = "2025-12-15"


def _marks():
    import account_metrics as A
    return A.load_series(None)     # [(date, value)]，與 R15 熔斷用同一份


def _fills():
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    return [f for f in rows if not f.get("is_option")], [f for f in rows if f.get("is_option")]


def _prices(symbols):
    """回 (close, adj, splits)：close 已調拆股未調息；adj 含息；splits = {sym: [(date, ratio)]}。"""
    import pandas as pd
    import yfinance as yf
    warnings.filterwarnings("ignore")
    raw = yf.download(sorted(symbols), start=PRICE_FROM, auto_adjust=False, actions=True, progress=False)
    close, adj = raw["Close"].ffill(), raw["Adj Close"].ffill()
    splits = {}
    if "Stock Splits" in raw:
        for s in raw["Stock Splits"]:
            ev = raw["Stock Splits"][s]
            splits[s] = [(d.strftime("%Y-%m-%d"), float(r)) for d, r in ev[ev.fillna(0) > 0].items()]
    return close, adj, splits


def _yf(sym: str) -> str:
    return sym.replace(".", "-")   # BRK.B → BRK-B


def build():
    import pandas as pd
    marks = _marks()
    if len(marks) < 3:
        return {"error": "淨值標記不足"}
    state = json.loads(STATE.read_text())
    asof = state["asof"]
    stock_fills, opt_fills = _fills()
    now_qty = {p["symbol"]: float(p["qty"]) for p in state["positions"]}
    after = [f for f in stock_fills if YEAR_START <= f["date"] <= asof]
    symbols = set(now_qty) | {f["symbol"] for f in after}
    close, adj, splits = _prices({_yf(s) for s in symbols})
    missing = sorted(s for s in symbols if _yf(s) not in close or close[_yf(s)].dropna().empty)

    def units(f):
        """成交股數換成現在的單位（之後每次拆股都乘上去）。"""
        q = abs(float(f["qty"]))
        for eff, ratio in splits.get(_yf(f["symbol"]), []):
            if f["date"] < eff:
                q *= ratio
        return q if f["side"] == "BOUGHT" else -q

    def holdings(d):
        """d 當天收盤後的持股：現在的持股扣掉 d 之後的淨買進。"""
        q = dict(now_qty)
        for f in after:
            if f["date"] > d:
                q[f["symbol"]] = q.get(f["symbol"], 0.0) - units(f)
        return {s: v for s, v in q.items() if abs(v) > 1e-6}

    def cash_at(d):
        """倒推現金：沒算之後收到的股息利息，所以略高估；只用來看非股票佔比。"""
        flow = sum(float(f.get("amount") or 0) for f in stock_fills + opt_fills if d < f["date"] <= asof)
        return float(state["cash"]) - flow

    def px(frame, sym, d):
        col = _yf(sym)
        if col not in frame:
            return None
        s = frame[col].loc[:pd.Timestamp(d)].dropna()
        return float(s.iloc[-1]) if len(s) else None

    val = dict(marks)

    def period(label, d0, d1):
        h = holdings(d0 if d0 != YEAR_START else "2025-12-31")
        p0d = "2025-12-31" if d0 == YEAR_START else d0
        stock0 = pnl = 0.0
        by, neg, nopx = {}, [], []
        for s, q in h.items():
            c0, a0, a1 = px(close, s, p0d), px(adj, s, p0d), px(adj, s, d1)
            if q < 0:
                neg.append(s)
            if not (c0 and a0 and a1):
                nopx.append(s)
                continue
            v0 = q * c0
            stock0 += v0
            by[s] = v0 * (a1 / a0 - 1)
            pnl += by[s]
        v0, v1 = val[d0], val[d1]
        actual, frozen = v1 / v0 - 1, pnl / v0
        cash0 = cash_at(p0d)
        top = sorted(by.items(), key=lambda kv: -kv[1])
        return {
            "label": label, "from": d0, "to": d1,
            "actual_pct": round(actual * 100, 2), "frozen_pct": round(frozen * 100, 2),
            "trading_contribution_pp": round((actual - frozen) * 100, 2),
            "trading_contribution_usd": round((actual - frozen) * v0),
            "start_value": round(v0), "end_value": round(v1), "frozen_end_value": round(v0 + pnl),
            "n_names": sum(1 for s, q in h.items() if abs(q * (px(close, s, p0d) or 0)) >= 0.001 * v0),  # 零股殘渣不算
            "stock_share_pct": round(stock0 / v0 * 100, 1),
            "non_stock_non_cash_pct": round((v0 - stock0 - cash0) / v0 * 100, 1),
            "frozen_best": [(s, round(v)) for s, v in top[:3]], "frozen_worst": [(s, round(v)) for s, v in top[-3:][::-1]],
            "negative_qty": neg, "no_price": nopx,
        }

    dates = [d for d, _ in marks]
    last = dates[-1]
    scanned = [d for d in dates if d > "2026-05-31"]
    month_ends = sorted({max(d for d in scanned if d[:7] == m) for m in {d[:7] for d in scanned}})
    bounds = [scanned[0]] + [d for d in month_ends if d > scanned[0]]
    peak_d = max(marks, key=lambda kv: kv[1])[0]
    periods = [period("今年以來", YEAR_START, last), period("高點至今", peak_d, last),
               period("上半年（年初→6 月初）", YEAR_START, scanned[0])]
    monthly = [period(b[:7], a, b) for a, b in zip(bounds[:-1], bounds[1:]) if a != b]
    return {"asof": last, "state_asof": asof, "generated": date.today().isoformat(),
            "periods": periods, "monthly": monthly, "missing_prices": missing,
            "note": "交易貢獻 = 實際 − 凍結；凍結線 = 期初持股含息不動，現金與選擇權當不動"}


def cached_or_build():
    """同一天、淨值標記沒更新就沿用快取，避免每次報告都重抓價格。"""
    try:
        old = json.loads(OUT.read_text())
        if old.get("generated") == date.today().isoformat() and old.get("asof") == _marks()[-1][0] and "error" not in old:
            return old
    except Exception:  # noqa: BLE001
        pass
    res = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


def lines(res):
    if "error" in res:
        return [f"不交易對照線：{res['error']}"]
    y, pk = res["periods"][0], res["periods"][1]
    out = [f"── 不交易對照線（至 {res['asof']}）──",
           f"今年以來  實際 {y['actual_pct']:+.1f}%｜年初持股不動 {y['frozen_pct']:+.1f}%｜交易貢獻 {y['trading_contribution_pp']:+.1f}pp（約 ${y['trading_contribution_usd']:+,}）",
           f"高點至今  實際 {pk['actual_pct']:+.1f}%｜高點持股不動 {pk['frozen_pct']:+.1f}%｜交易貢獻 {pk['trading_contribution_pp']:+.1f}pp"]
    if res["monthly"]:
        m = res["monthly"][-1]
        out.append(f"最近一期  {m['from']}→{m['to']}：實際 {m['actual_pct']:+.1f}%｜不動 {m['frozen_pct']:+.1f}%｜交易貢獻 {m['trading_contribution_pp']:+.1f}pp")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", action="store_true", help="只印給報告用的幾行")
    a = ap.parse_args()
    res = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("\n".join(lines(res)))
    if a.lines or "error" in res:
        return 0
    print("\n期間                    實際    不動   交易貢獻  期初檔數  股票佔比  非股票非現金")
    for p in res["periods"] + res["monthly"]:
        print(f"{p['label']:<20s} {p['actual_pct']:+7.1f}% {p['frozen_pct']:+7.1f}% {p['trading_contribution_pp']:+7.1f}pp"
              f" {p['n_names']:6d} {p['stock_share_pct']:8.1f}% {p['non_stock_non_cash_pct']:8.1f}%")
    y = res["periods"][0]
    print(f"\n年初持股不動的話：賺最多 {y['frozen_best']}；賠最多 {y['frozen_worst']}")
    for p in res["periods"] + res["monthly"]:
        if p["negative_qty"] or p["no_price"]:
            print(f"⚠️ {p['label']}：倒推出負股數 {p['negative_qty']}；無價格 {p['no_price']}")
    print("讀法：交易貢獻是正的＝這段的買賣有加分。凍結線只是量尺；「非股票非現金」大的期間（當時有選擇權）要保守看。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
