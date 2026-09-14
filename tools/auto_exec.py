#!/usr/bin/env python3
"""auto_exec.py — T6.5 機械單執行器（v1 = dry-run only，2026-09-14）

目的：把「今日待辦裡的機械單」的判定從模型手上拿走。模型只負責寫為什麼；哪些單該下、
下多少、依據哪條規則，由本工具從資料層算出，寫成 briefing-out/cache/auto-exec-plan.json。
briefing T6.5 只准執行本檔列出的 plan，不再自行判定機械觸發（判定散文 → code）。

v1 覆蓋（全部是「降風險或零風險」類，T6.5 條件 3 無金額上限者）：
  A. R23 自峰回撤線：position-state r23_armed + 前一收盤 ≤ 峰 × (1−20%/30%) → 減 1/3
  B. 用戶裁決收盤線：price-alerts 內 note 含「收盤」且 id 含 trim/derating 的 price_below → 收盤 < level → 依 note 股數
  C. 選擇權管理線：id 含 bcs-exit / option 的 price_below → 收盤 < level → 平倉指令（day，ET 7–16）
  D. R24 現金停泊：閒置 = 現金 − 在掛買單 − 3% 緩衝 > $10k → 買 SGOV 至閒置 ≤ $5k
  E. R8 梯級 GTC 缺口：position-state gaps 中 kind 含 R8 → 掛下一級賣單（限價=級距價）
不覆蓋（仍由模型/用戶）：新倉、加碼、選擇權開倉、任何需要 thesis 判斷的動作。

五條件在此實作：①類別（上列五類）②量化觸發＝**前一收盤**（R17，盤中價不算）③金額上限只管新增曝險（A–C、E 為減碼/平倉、D 為現金等價，皆免）
④硬線：財報 ±48h（A/B/E 不執行；C 選擇權平倉仍執行）、R14 鎖住 R23（C3 裁決）、單一持倉 >10% 不由本工具處理（guard 已報）
⑤跨日反轉：讀 briefing-out/cache/crossday-flags.json（crossday_check 若有輸出）→ 命中 ticker 的 A/B 延一日

--execute 目前**被鎖**（v1）：印出「dry-run only，解鎖日 2026-09-28（兩週乾跑後由用戶裁決）」。
Usage:
  uv run --directory tools python3 tools/auto_exec.py            # dry-run，寫 plan JSON + 印表
  uv run --directory tools python3 tools/auto_exec.py --execute  # v1 拒絕
"""
import json, math, re, sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "research" / "position-state.json"
ALERTS = ROOT / "research" / "price-alerts.json"
FLAGS = ROOT / "research" / "position-flags.json"
REGISTRY = ROOT / "research" / "order-registry.json"
EARN = ROOT / "briefing-out" / "cache" / "earnings-dates.json"
XDAY = ROOT / "briefing-out" / "cache" / "crossday-flags.json"
OUT = ROOT / "briefing-out" / "cache" / "auto-exec-plan.json"
EXECUTE_UNLOCK = date(2026, 9, 28)
IDLE_TRIGGER, IDLE_TARGET, BUFFER_PCT = 10_000, 5_000, 0.03


def _load(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def prev_close(symbols: list[str]) -> dict:
    """前一交易日收盤（R17 只認收盤）。yfinance 失敗 → 回 {}（呼叫端退回 position-state last 並標 ⚠️）。"""
    try:
        import yfinance as yf
        px = yf.download(symbols, period="7d", auto_adjust=True, progress=False)["Close"]
        if hasattr(px, "columns"):
            last = px.dropna(how="all").iloc[-1]
            asof = px.dropna(how="all").index[-1].date().isoformat()
            return {"asof": asof, **{s: float(last[s]) for s in symbols if s in last and not math.isnan(float(last[s]))}}
        return {}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def in_earnings_window(sym: str, earn: dict, today: date, hours=48) -> bool:
    d = (earn.get("tickers") or {}).get(sym, {}).get("next_date")
    if not d:
        return False
    nd = date.fromisoformat(d)
    return abs((nd - today).days) <= 2


def main(argv):
    execute = "--execute" in argv
    today = date.today()
    st = _load(STATE, {})
    alerts = (_load(ALERTS, {}) or {}).get("alerts", [])
    earn = _load(EARN, {})
    reg = _load(REGISTRY, {})
    xday = _load(XDAY, {})
    reversed_tks = set(xday.get("tickers", [])) if isinstance(xday, dict) else set()
    positions = {p["symbol"]: p for p in st.get("positions", [])}
    syms = sorted(set(positions) | {a.get("symbol") for a in alerts if a.get("symbol")} | {"SGOV"})
    syms = [s for s in syms if s and not s.startswith("^")]
    closes = prev_close(syms)
    px_note = "" if closes and "error" not in closes else f"⚠️ yfinance 失敗（{closes.get('error','空')}），退回 position-state last（非收盤，僅 dry-run 參考）"

    def close_of(s):
        if s in closes:
            return closes[s]
        return positions.get(s, {}).get("last")

    plan, skipped = [], []

    def skip(sym, rule, why):
        skipped.append({"symbol": sym, "rule": rule, "why": why})

    # ── A. R23 ─────────────────────────────────────────────────────────────
    for sym, p in positions.items():
        if p.get("bucket") != "認列" or not p.get("r23_armed"):
            continue
        peak, c = p.get("peak_close"), close_of(sym)
        if not (peak and c):
            continue
        dd = c / peak - 1
        stage = 30 if dd <= -0.30 else (20 if dd <= -0.20 else None)
        if stage is None:
            continue
        if p.get("r14_locked"):
            skip(sym, "R23", "R14 30 天鎖（C3 裁決：鎖住 R23）"); continue
        if in_earnings_window(sym, earn, today):
            skip(sym, "R23", "財報 ±48h（R9）"); continue
        if sym in reversed_tks:
            skip(sym, "R23", "T5.5 跨日反轉，延一日"); continue
        qty = math.floor(p["qty"] / 3)
        if qty < 1:
            skip(sym, "R23", "1/3 不足 1 股"); continue
        plan.append({"rule": f"R23-{stage}", "symbol": sym, "action": "SELL", "qty": qty,
                     "order": {"type": "limit", "limit": round(c * 0.995, 2), "duration": "day"},
                     "basis": f"前收 {c:.2f} ≤ 峰 {peak:.2f} × (1−{stage}%)（{dd:+.1%}）；armed；減 1/3",
                     "after": ["snapshot-orders", "register-order --rule R23", "trade_ledger flag/resolve-flag trimmed", "thesis 留痕（+30d 驗）"]})

    # ── B. 用戶裁決收盤線 / C. 選擇權管理線 ─────────────────────────────────
    for a in alerts:
        if a.get("type") != "price_below" or a.get("status") == "removed":
            continue
        sym, lvl, note, aid = a.get("symbol"), a.get("level"), a.get("note") or "", a.get("id") or ""
        c = close_of(sym)
        if not (sym and lvl and c) or c >= lvl:
            continue
        if "bcs-exit" in aid or "option" in aid.lower():
            plan.append({"rule": "options-mgmt", "symbol": sym, "action": "CLOSE_SPREAD", "qty": None,
                         "order": {"type": "spread", "duration": "day", "window": "ET 07:00–16:00"},
                         "basis": f"前收 {c:.2f} < 結構線 {lvl}（{aid}）", "note": note[:160],
                         "after": ["register-order --rule options-mgmt", "remove alert"]})
            continue
        if "收盤" in note and ("trim" in aid or "derating" in aid or "減" in note):
            if in_earnings_window(sym, earn, today):
                skip(sym, "close-line", "財報 ±48h"); continue
            if sym in reversed_tks:
                skip(sym, "close-line", "T5.5 跨日反轉，延一日"); continue
            m = re.search(r"賣\s*[A-Z]*\s*(\d+)\s*股", note)
            p = positions.get(sym, {})
            qty = int(m.group(1)) if m else (math.floor(p.get("qty", 0) / 3) if "1/3" in note else None)
            if not qty:
                skip(sym, "close-line", "note 內無股數，需人工"); continue
            plan.append({"rule": "user-close-line", "symbol": sym, "action": "SELL", "qty": qty,
                         "order": {"type": "limit", "limit": round(c * 0.995, 2), "duration": "day"},
                         "basis": f"前收 {c:.2f} < 裁決線 {lvl}（{aid}）", "note": note[:160],
                         "after": ["snapshot-orders", "register-order --rule user-close-line", "resolve-flag trimmed", "remove/keep alert per note"]})

    # ── D. R24 現金停泊 ───────────────────────────────────────────────────
    cash = float(st.get("cash") or 0)
    pending_buys = sum((o.get("shares", 0) or 0) * (o.get("limit_price", 0) or 0)
                       for o in (reg.get("orders") or {}).values()
                       if o.get("state") == "ORDER-SUBMITTED" and o.get("transaction") == "B" and o.get("sec_type") == 1)
    total = float(st.get("total_account_value") or 0)
    idle = cash - pending_buys - BUFFER_PCT * total
    sgov_px = close_of("SGOV") or 100.5
    if idle > IDLE_TRIGGER:
        qty = math.floor((idle - IDLE_TARGET) / sgov_px)
        plan.append({"rule": "R24", "symbol": "SGOV", "action": "BUY", "qty": qty,
                     "order": {"type": "limit", "limit": round(sgov_px + 0.01, 2), "duration": "gtc"},
                     "basis": f"閒置 = 現金 {cash:,.0f} − 在掛買單 {pending_buys:,.0f} − 3% 緩衝 {BUFFER_PCT*total:,.0f} = {idle:,.0f} > 10k",
                     "after": ["register-order --rule R24"]})
    else:
        skipped.append({"symbol": "SGOV", "rule": "R24", "why": f"閒置 {idle:,.0f} ≤ 10k（現金 {cash:,.0f}、在掛買 {pending_buys:,.0f}）"})

    # ── E. R8 缺口 ──────────────────────────────────────────────────────────
    for g in st.get("gaps", []) or []:
        txt = json.dumps(g, ensure_ascii=False)
        if "R8" in txt:
            plan.append({"rule": "R8-gap", "symbol": g.get("symbol") or g.get("ticker"), "action": "SELL_GTC_TIER",
                         "qty": None, "order": {"type": "limit", "duration": "gtc"}, "basis": txt[:200],
                         "after": ["register-order --rule R8"]})

    # ── 去重 / 優先序（衝突 C2 型）：同一標的同向只出一張單。用戶裁決收盤線 > R23（9/2 裁決：MYRG 以 $274 線取代 R23），
    #    R23-30 > R23-20；合併時在 basis 註明被吸收的規則，避免兩條規則各賣一次把認列桶賣穿 30% runner。
    merged, seen = [], {}
    prio = {"user-close-line": 3, "R23-30": 2, "R23-20": 1}
    for p in plan:
        key = (p["symbol"], p["action"])
        if key not in seen:
            seen[key] = len(merged); merged.append(dict(p)); continue
        i = seen[key]; cur = merged[i]
        keep, drop = (p, cur) if prio.get(p["rule"], 0) > prio.get(cur["rule"], 0) else (cur, p)
        keep = dict(keep); keep["basis"] += f"｜同日 {drop['rule']} 亦觸發，已合併（不重複賣）"
        keep["merged_rules"] = sorted({cur.get("rule"), p.get("rule")} | set(cur.get("merged_rules", [])))
        merged[i] = keep
    plan = merged

    out = {"asof": today.isoformat(), "close_asof": closes.get("asof"), "mode": "dry-run" if not execute else "execute",
           "execute_unlock": EXECUTE_UNLOCK.isoformat(), "px_note": px_note,
           "plan": plan, "skipped": skipped,
           "discipline": "T6.5 只執行本清單；新倉/加碼/選擇權開倉不在此；所有觸發以前一收盤判定（R17）"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(f"🤖 auto_exec {out['mode']}（收盤 {out['close_asof']}）{px_note}")
    if plan:
        for p in plan:
            print(f"  ▶ {p['rule']:<15} {p['action']:<14} {p['symbol']:<6} {p.get('qty') or '':>4}  {p['basis']}")
    else:
        print("  （無機械單觸發）")
    for s in skipped:
        print(f"  · skip {s['rule']:<12} {s['symbol']:<6} {s['why']}")
    if execute:
        if today < EXECUTE_UNLOCK:
            print(f"⛔ --execute 鎖定中：v1 dry-run 至 {EXECUTE_UNLOCK}，屆時由用戶裁決解鎖（兩週乾跑對照實際 T6.5 結果）")
            return 3
        print("⛔ execute 路徑尚未實作（v2）")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
