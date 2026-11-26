#!/usr/bin/env python3
"""r37_guard.py — R37「選擇權只留長天期買權」的每日檢查（2026-11-22 用戶：「加警示」）

R37 生效日之後才開的選擇權部位，逐筆對照四個條件；不合的回一行缺口文字，交給 position_guard 的缺口清單。
只讀帳本與即時持倉，不下單、不改任何檔案。

檢查什麼：
  - 賣方開倉（掩護性買權、賣出賣權、價差的短腿）與買進賣權：一律不合。
  - 買進買權：①開倉時距到期 ≥ 365 天、開倉 delta ≥ 0.80（由成交價反推，估算值，留 0.03 容差）
              ②標的在信念桶  ④開倉權利金 ≤ 帳戶 4%、開倉前後 3 天內有 ev-ledger 登錄
  - ③開倉未滿 90 天就平倉。
  - ④同時持有的買權超過 2 筆。
  - 即時持倉有、帳本沒有的合約（帳本還沒同步，無法判定）。

不會一直吵：
  - 部位已結束的違規只報 STALE_DAYS 天。
  - journal 當日檔有一行同時含「R37 bypass」與標的代號 → 視為用戶已留痕，不再報（沿用 R28 bypass 的做法）。
  - 抓不到標的價格時不檢查 delta，不因為網路問題誤報。

Usage:
  python3 tools/r37_guard.py          # 用帳本單獨跑一次（不連券商）
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "research" / "trade-ledger.jsonl"
ROSTER = ROOT / "research" / "roster.json"
EV_LEDGER = ROOT / "research" / "ev-ledger.jsonl"

R37_START = "2026-11-22"
MIN_DTE_DAYS = 365
MIN_DELTA = 0.80
DELTA_TOL = 0.03          # delta 是由成交價反推的估算，邊界留容差
MIN_HOLD_DAYS = 90
MAX_PREMIUM_PCT = 4.0
MAX_POSITIONS = 2
EV_WINDOW_DAYS = 3
STALE_DAYS = 14           # 已結束的違規只報這麼多天
RF = 0.04
BYPASS_TAG = "R37 bypass"
_OCC = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")
_EPS = 1e-9


def parse_occ(sym):
    m = _OCC.match(sym or "")
    if not m:
        return None
    root, ymd, cp, k = m.groups()
    try:
        exp = dt.date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
    except ValueError:
        return None
    return root, exp, cp, int(k) / 1000.0


def load_option_fills(path=LEDGER):
    rows = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    out = [f for f in rows if f.get("is_option")]
    out.sort(key=lambda f: (f["date"], f.get("exec_time", "")))
    return out


def _d(s):
    return dt.date.fromisoformat(s[:10])


def _bypassed(root, date_str, journal_dir):
    try:
        txt = (Path(journal_dir) / f"{date_str}.md").read_text()
    except OSError:
        return False
    return any(BYPASS_TAG in ln and root in ln for ln in txt.splitlines())


def _spot_yf(root, date_str):
    """開倉當日標的收盤價；抓不到回 None（呼叫端就不檢查 delta）。"""
    try:
        import warnings
        import yfinance as yf
        warnings.filterwarnings("ignore")
        d0 = _d(date_str)
        h = yf.Ticker(root.replace(".", "-")).history(start=(d0 - dt.timedelta(days=7)).isoformat(),
                                                    end=(d0 + dt.timedelta(days=1)).isoformat(), auto_adjust=False)
        return float(h["Close"].dropna().iloc[-1]) if len(h) else None
    except Exception:  # noqa: BLE001
        return None


def _delta(price, S, K, T, cp):
    try:
        from position_guard import _implied_delta
        return _implied_delta(price, S, K, T, RF, cp)[0]
    except Exception:  # noqa: BLE001
        return None


def check(opt_fills, *, today, roster=None, total=None, live_opts=None, ev_rows=None,
          spot_at=_spot_yf, journal_dir=ROOT / "journal", start=R37_START):
    """回缺口文字的 list（空 = 合規）。參數都可注入，方便用假資料測。"""
    roster, ev_rows = roster or {}, ev_rows or []
    conviction = set((roster.get("buckets") or {}).get("信念", []))
    pos, opened, early = {}, {}, []
    for f in opt_fills:
        c = f["symbol"]
        q = abs(float(f["qty"])) * (1 if f["side"] == "BOUGHT" else -1)
        old = pos.get(c, 0.0)
        new = old + q
        pos[c] = new
        if f["date"] < start:
            continue
        if old * q >= 0:                       # 往同方向加，或從零開始 = 開倉
            o = opened.setdefault(c, {"date": f["date"], "last": f["date"], "long": q > 0, "premium": 0.0, "price": None})
            o["last"] = f["date"]
            o["premium"] += abs(float(f.get("notional") or 0))
            o["price"] = o["price"] or float(f.get("split_adj_price") or f.get("price") or 0)
        elif c in opened and opened[c]["long"]:  # 平掉 R37 之後才開的買方部位
            held = (_d(f["date"]) - _d(opened[c]["date"])).days
            if held < MIN_HOLD_DAYS:
                early.append((c, f["date"], held))

    gaps = []
    for c, o in opened.items():
        occ = parse_occ(c)
        if not occ:
            continue
        root, exp, cp, K = occ
        still = abs(pos.get(c, 0.0)) > _EPS and exp >= today   # 過期作廢的沒有平倉成交，要用到期日判
        if not still and (today - _d(o["last"])).days > STALE_DAYS:
            continue
        if _bypassed(root, o["date"], journal_dir):
            continue
        bad = []
        if not o["long"]:
            bad.append("賣方開倉（" + ("賣出買權" if cp == "C" else "賣出賣權") + "）不在允許範圍")
        elif cp == "P":
            bad.append("買進賣權不在允許範圍")
        else:
            dte = (exp - _d(o["date"])).days
            if dte < MIN_DTE_DAYS:
                bad.append(f"①距到期 {dte} 天，不到 12 個月")
            S = spot_at(root, o["date"]) if spot_at else None
            if S and o["price"]:
                dl = _delta(o["price"], S, K, max(dte, 0) / 365.0, cp)
                if dl is not None and dl < MIN_DELTA - DELTA_TOL:
                    bad.append(f"①開倉 delta 約 {dl:.2f}（估算），低於 {MIN_DELTA:.2f}")
            if root not in conviction:
                bad.append("②標的不在信念桶")
            if total and o["premium"] / total * 100 > MAX_PREMIUM_PCT:
                bad.append(f"④權利金佔帳戶 {o['premium'] / total * 100:.1f}%，超過 {MAX_PREMIUM_PCT:g}%")
            d0 = _d(o["date"])
            if not any(r.get("ticker") == root and r.get("forecast_date")
                       and abs((_d(r["forecast_date"]) - d0).days) <= EV_WINDOW_DAYS for r in ev_rows):
                bad.append("④開倉沒有登錄 ev-ledger")
        if bad:
            gaps.append(f"R37 {c}（{o['date']} 開倉{'' if still else '，已結束'}）：" + "；".join(bad)
                        + f" → 不合「只留長天期買權」，/trade-review 檢討；已留痕可在當日 journal 加「{BYPASS_TAG} {root}」")
    for c, date_str, held in early:
        root = parse_occ(c)[0] if parse_occ(c) else c
        if (today - _d(date_str)).days > STALE_DAYS or _bypassed(root, date_str, journal_dir):
            continue
        gaps.append(f"R37 {c}：第 {held} 天平倉（{date_str}），③最短持有 {MIN_HOLD_DAYS} 天"
                    f" → 需有 thesis gate 失敗紀錄；有的話在當日 journal 加「{BYPASS_TAG} {root}」")
    n_calls = [c for c, q in pos.items() if q > _EPS and parse_occ(c) and parse_occ(c)[2] == "C" and parse_occ(c)[1] >= today]
    if len(n_calls) > MAX_POSITIONS:
        gaps.append(f"R37 ④同時持有買權 {len(n_calls)} 筆，超過 {MAX_POSITIONS} 筆：" + "、".join(sorted(n_calls)))
    for root, items in (live_opts or {}).items():
        for it in items:
            c = it.get("contract") or ""
            if abs(float(it.get("qty") or 0)) > _EPS and abs(pos.get(c, 0.0)) <= _EPS:
                gaps.append(f"R37 {c}：帳上有這口、帳本沒有 → 先同步帳本（trade_ledger ingest）才能判定合不合 R37")
    return gaps


def gaps_for_guard(live, roster, total, today):
    """給 position_guard 用：自己讀帳本與 ev-ledger；任何失敗都回空，不影響守門主流程。"""
    try:
        ev = [json.loads(l) for l in EV_LEDGER.read_text().splitlines() if l.strip()] if EV_LEDGER.exists() else []
        return check(load_option_fills(), today=today, roster=roster, total=total, ev_rows=ev,
                     live_opts=(live or {}).get("options_by_underlying"))
    except Exception as e:  # noqa: BLE001
        return [f"R37 檢查略過（{type(e).__name__}）"]


def main():
    roster = json.loads(ROSTER.read_text()) if ROSTER.exists() else {}
    gaps = gaps_for_guard(None, roster, None, dt.date.today())
    print("\n".join(f"- {g}" for g in gaps) if gaps else f"✅ R37：{R37_START} 之後沒有不合規的新選擇權部位")
    return 2 if gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
