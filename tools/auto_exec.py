#!/usr/bin/env python3
"""auto_exec.py — T6.5 機械單執行器（v1 = dry-run only，2026-09-14）

目的：把「今日待辦裡的機械單」的判定從模型手上拿走。模型只負責寫為什麼；哪些單該下、
下多少、依據哪條規則，由本工具從資料層算出，寫成 briefing-out/cache/auto-exec-plan.json。
briefing T6.5 只准執行本檔列出的 plan，不再自行判定機械觸發（判定散文 → code）。

v1 覆蓋（A–E 降風險/零風險，無金額上限；F 為唯一新增曝險類，單次 ≤$3k）：
  A. R23 自峰回撤線：position-state r23_armed + 前一收盤 ≤ 峰 × (1−20%/30%) → 減 1/3
  B. 用戶裁決收盤線：price-alerts 內 note 含「收盤」且 id 含 trim/derating 的 price_below → 收盤 < level → 依 note 股數
  C. 選擇權管理線：id 含 bcs-exit / option 的 price_below → 收盤 < level → 平倉指令（day，ET 7–16）
  D. R24 現金停泊：閒置 = 現金 − 在掛買單 − max(3% 總值, $8k) 緩衝 > $10k → 買 SGOV 至閒置 ≤ $5k（$8k 是留給手動掛單的錢，2026-09-16）
  E. R8 梯級 GTC 缺口：position-state gaps 中 kind 含 R8 → 掛下一級賣單（限價=級距價）
  F. R30 加碼候選（2026-09-14 買強）：guard add_candidates → 回檔 SMA20 限價 GTC 10 日，單次 ≤$3k；條件消失 → 撤單
  G. R25 修訂 sleeve：guard sleeve.actions（ETF 自峰 −10% / 合計 >8% / 帳戶自 sleeve 建立後峰 −10% 賣半）→ 賣單，所得進 SGOV
不覆蓋（仍由模型/用戶）：新倉、加碼、選擇權開倉、任何需要 thesis 判斷的動作。

五條件在此實作：①類別（上列五類）②量化觸發＝**前一收盤**（R17，盤中價不算）③金額上限只管新增曝險（A–C、E 為減碼/平倉、D 為現金等價，皆免）
④硬線：財報 ±48h（A/B/E 不執行；C 選擇權平倉仍執行）、R14 鎖住 R23（C3 裁決）、R8+R23 合計不賣穿 30% runner（C2，guard `sellable_before_floor`）、單一持倉 >10% 不由本工具處理（guard 已報）
⑦R28a 買方硬線：輸出 `buy_locked`（R23 觸線區 / 減碼後 30 天內的認列桶名字）；T6.5 對這些名字不得下任何買單
⑥現金閘（C6）：輸出 `cash_gate`（可用現金 / SGOV 停泊）；可用 < $3k 且有停泊 → 加一張 SGOV 賣單（T+1），T6.5 新曝險買單延一日
⑤跨日反轉：讀 briefing-out/cache/crossday-flags.json（crossday_check 若有輸出）→ 命中 ticker 的 A/B 延一日

--execute（v2，2026-09-15 起）：需 AUTO_EXEC_LIVE=1；evening_pass.sh 收盤後跑，現股 BUY/SELL 限價以 gt90 掛（次一交易日生效）、CANCEL 直撤；
複式單仍 Telegram 手掛。結果寫回 plan JSON `executed` + research/auto-exec-log.jsonl；briefing T6.5 讀到 executed 就只回報不重下。
Usage:
  uv run --directory tools python3 tools/auto_exec.py            # dry-run，寫 plan JSON + 印表
  uv run --directory tools python3 tools/auto_exec.py --execute  # v1 拒絕
"""
import json, math, os, re, sys
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
EXECUTE_UNLOCK = date(2026, 9, 15)   # 2026-09-15 用戶提前解鎖（MYRG 手動案：收盤破線到隔日 11:00 ET 才執行太慢）
IDLE_TRIGGER, IDLE_TARGET, BUFFER_PCT = 10_000, 5_000, 0.03
RESERVE_USD = 8_000   # 2026-09-16 用戶：SGOV 會排擠手動掛單的錢 → 緩衝 = max(3% 總值, $8k)，帳上永遠留這筆不停泊


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


def intraday_last(symbols: list[str]) -> dict:
    """盤中最新價（--preclose 用；1 分 K 最後一根）。失敗 → 退回 prev_close。"""
    try:
        import yfinance as yf
        px = yf.download(symbols, period="1d", interval="1m", auto_adjust=True, progress=False)["Close"]
        if hasattr(px, "columns"):
            px = px.dropna(how="all")
            last = px.iloc[-1]
            asof = px.index[-1].to_pydatetime().isoformat(timespec="minutes")
            out = {"asof": f"intraday {asof}", **{s: float(last[s]) for s in symbols if s in last and not math.isnan(float(last[s]))}}
            if len(out) > 1:
                return out
        return prev_close(symbols)
    except Exception:  # noqa: BLE001
        return prev_close(symbols)


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
    # 安全閘：live 券商持倉抓不到時 guard 退回 FIFO 重建（可能缺舊清倉紀錄、股數失真、冒出殭屍部位如 TMF）。
    # 絕不在 FIFO fallback 狀態上執行真單，dry-run 也標不可靠。
    stale_state = st.get("source") != "firstrade-live"
    if stale_state and execute:
        print(f"⛔ position-state source={st.get('source')}（非 firstrade-live）→ 拒絕執行；先修復 Firstrade session 再跑")
        OUT.write_text(json.dumps({"asof": today.isoformat(), "mode": "aborted", "reason": f"state source={st.get('source')}", "plan": [], "skipped": []}, ensure_ascii=False))
        return 5
    alerts = (_load(ALERTS, {}) or {}).get("alerts", [])
    earn = _load(EARN, {})
    reg = _load(REGISTRY, {})
    xday = _load(XDAY, {})
    reversed_tks = set(xday.get("tickers", [])) if isinstance(xday, dict) else set()
    positions = {p["symbol"]: p for p in st.get("positions", [])}
    syms = sorted(set(positions) | {a.get("symbol") for a in alerts if a.get("symbol")} | {"SGOV"})
    syms = [s for s in syms if s and not s.startswith("^")]
    # --preclose（2026-09-15 用戶採用）：15:45 ET 用即時價當「準收盤」，線要多破 BUF=0.5% 才算，賣單 day 貼盤當天成交；
    # 沒有 --preclose（22:20 evening 補網）：用真正收盤，gt90 隔日生效。
    preclose = "--preclose" in argv
    BUF = 0.005 if preclose else 0.0
    DUR_SELL = "day" if preclose else "gt90"
    closes = intraday_last(syms) if preclose else prev_close(syms)
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
        stage = 30 if dd <= -(0.30 + BUF) else (20 if dd <= -(0.20 + BUF) else None)
        if stage is None:
            continue
        if p.get("r14_locked"):
            skip(sym, "R23", "R14 30 天鎖（C3 裁決：鎖住 R23）"); continue
        if in_earnings_window(sym, earn, today):
            skip(sym, "R23", "財報 ±48h（R9）"); continue
        if sym in reversed_tks:
            skip(sym, "R23", "T5.5 跨日反轉，延一日"); continue
        qty = math.floor(p["qty"] / 3)
        # C2：R8+R23 合計不得賣穿 30% runner（guard 已算 sellable_before_floor）
        left = p.get("sellable_before_floor")
        if left is not None and qty > left:
            if left < 1:
                skip(sym, "R23", f"已賣 {p.get('cum_sold_pct', 0):.0f}%，觸 30% runner 保底（C2）"); continue
            qty = int(left)
        if qty < 1:
            skip(sym, "R23", "1/3 不足 1 股"); continue
        plan.append({"rule": f"R23-{stage}", "symbol": sym, "action": "SELL", "qty": qty,
                     "order": {"type": "limit", "limit": round(c * 0.997, 2), "duration": DUR_SELL},
                     "basis": f"前收 {c:.2f} ≤ 峰 {peak:.2f} × (1−{stage}%)（{dd:+.1%}）；armed；減 1/3",
                     "after": ["snapshot-orders", "register-order --rule R23", "trade_ledger flag/resolve-flag trimmed", "thesis 留痕（+30d 驗）"]})

    # ── B. 用戶裁決收盤線 / C. 選擇權管理線 ─────────────────────────────────
    for a in alerts:
        if a.get("type") != "price_below" or a.get("status") == "removed":
            continue
        sym, lvl, note, aid = a.get("symbol"), a.get("level"), a.get("note") or "", a.get("id") or ""
        c = close_of(sym)
        if not (sym and lvl and c) or c >= lvl * (1 - BUF):
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
            plan.append({"rule": "user-close-line", "symbol": sym, "action": "SELL", "qty": qty, "alert_id": aid,
                         "order": {"type": "limit", "limit": round(c * 0.997, 2), "duration": DUR_SELL},
                         "basis": f"前收 {c:.2f} < 裁決線 {lvl}（{aid}）", "note": note[:160],
                         "after": ["snapshot-orders", "register-order --rule user-close-line", "resolve-flag trimmed", "remove/keep alert per note"]})

    # ── D. R24 現金停泊 ───────────────────────────────────────────────────
    cash = float(st.get("cash") or 0)
    pending_buys = sum((o.get("shares", 0) or 0) * (o.get("limit_price", 0) or 0)
                       for o in (reg.get("orders") or {}).values()
                       if o.get("state") == "ORDER-SUBMITTED" and o.get("transaction") == "B" and o.get("sec_type") == 1)
    total = float(st.get("total_account_value") or 0)
    buffer = max(BUFFER_PCT * total, RESERVE_USD)
    idle = cash - pending_buys - buffer
    sgov_px = close_of("SGOV") or 100.5
    if idle > IDLE_TRIGGER:
        qty = math.floor((idle - IDLE_TARGET) / sgov_px)
        plan.append({"rule": "R24", "symbol": "SGOV", "action": "BUY", "qty": qty,
                     "order": {"type": "limit", "limit": round(sgov_px + 0.01, 2), "duration": "gtc"},
                     "basis": f"閒置 = 現金 {cash:,.0f} − 在掛買單 {pending_buys:,.0f} − 緩衝 {buffer:,.0f}（max 3%, $8k）= {idle:,.0f} > 10k",
                     "after": ["register-order --rule R24"]})
    else:
        skipped.append({"symbol": "SGOV", "rule": "R24", "why": f"閒置 {idle:,.0f} ≤ 10k（現金 {cash:,.0f}、在掛買 {pending_buys:,.0f}）"})

    # ── E. R8 缺口 ──────────────────────────────────────────────────────────
    #   gaps 是字串（guard 的 f-string）。只認「SYM: R8 未實現 …級距但無在掛賣單」這一種，
    #   不要誤抓「TMF: … R8/R23 無法判定」這類含 R8 字樣但非缺單的行。
    for g in st.get("gaps", []) or []:
        if not isinstance(g, str) or "R8 未實現" not in g:
            continue
        sym = g.split(":", 1)[0].strip()
        plan.append({"rule": "R8-gap", "symbol": sym, "action": "SELL_GTC_TIER",
                     "qty": None, "order": {"type": "limit", "duration": "gtc"}, "basis": g[:200],
                     "after": ["register-order --rule R8（限價=級距價，需人工確認股數）"]})

    parked = float(st.get("parked_cash_equiv") or 0)
    # 在掛的現金等價賣單（SGOV 解泊，T+1）視為即將到位的現金，避免重複出解泊單
    pending_ce_sells = sum((o.get('shares', 0) or 0) * (o.get('limit_price', 0) or 0)
                           for o in (reg.get('orders') or {}).values()
                           if o.get('state') == 'ORDER-SUBMITTED' and o.get('transaction') == 'S' and o.get('symbol') in ('SGOV', 'BIL'))
    cash_available = cash - pending_buys + pending_ce_sells
    # ── F. R30 加碼候選（買強，2026-09-14）：回檔 SMA20 限價 GTC 10 日；候選消失 → 撤掛 R30 單 ─────
    r30_syms = set()
    for c in st.get("add_candidates", []) or []:
        sym = c["symbol"]
        r30_syms.add(sym)
        if sym in reversed_tks:
            skip(sym, "R30", "T5.5 跨日反轉，延一日"); continue
        if cash_available < c["room_usd"] and parked <= 0:
            skip(sym, "R30", f"可用現金 {cash_available:,.0f} < 額度 {c['room_usd']:,.0f} 且無 SGOV 停泊"); continue
        # 兩分支（R20 對稱）：走強分支 = 前收 ≥ 20 日高（突破確認）→ 當日 day 單貼盤接一半額度；否則回檔分支 = SMA20 限價 GTC
        prev = close_of(sym) or c["last"]
        breakout = prev >= c["high20"] * 0.999
        if breakout:
            limit = round(prev * 1.002, 2)
            qty = math.floor(min(c["room_usd"], 3_000) * 0.5 / limit)
        else:
            limit = min(c["sma20"], c["last"] * 0.995) if c["last"] > c["sma20"] else round(c["last"] * 0.995, 2)
            qty = math.floor(min(c["room_usd"], 3_000) / limit)
        if qty < 1:
            skip(sym, "R30", "額度不足 1 股"); continue
        existing = [oid for oid, o in (reg.get("orders") or {}).items()
                    if o.get("symbol") == sym and o.get("rule_ref") == "R30" and o.get("transaction") == "B"
                    and str(o.get("state", "")).startswith(("ORDER-SUBMITTED", "ORDER-REQUESTED"))]
        if existing:
            skip(sym, "R30", f"已有 R30 在掛買單 {existing}"); continue
        # 冷卻：同標的 14 日曆日內有任何買進成交（R30 或用戶手動皆算）→ 不再加（TWLO 9/15 R30 成交、AMD 9/15 用戶手買 6 股，當晚都不能再疊）
        recent_fill = [oid for oid, o in (reg.get("orders") or {}).items()
                       if o.get("symbol") == sym and o.get("transaction") == "B" and "FILLED" in str(o.get("state", ""))
                       and (o.get("updated") or o.get("rule_registered_at") or o.get("first_seen") or "")[:10] >= (today - timedelta(days=14)).isoformat()]
        if recent_fill:
            skip(sym, "R30", f"14 日內已有買進成交 {recent_fill}，冷卻中（一次一梯，不疊）"); continue
        plan.append({"rule": "R30-add", "symbol": sym, "action": "BUY", "qty": qty,
                     "order": ({"type": "limit", "limit": limit, "duration": "day", "branch": "breakout"} if breakout
                               else {"type": "limit", "limit": round(limit, 2), "duration": "gtc", "expires_days": 10, "branch": "pullback"}),
                     "basis": (f"買強：+{c['unrealized_pct']:.0f}%、rev {c['rev_up_30d']:g}↑:{c['rev_down_30d']:g}↓、價 {c['last']} > SMA50 {c['sma50']}、權重 {c['weight_pct']}% → "
                               + (f"走強分支：前收 {prev:.2f} ≥ 20 日高 {c['high20']}，當日接半額度" if breakout else f"回檔分支：SMA20 {c['sma20']} 限價 GTC 10 日")
                               + f"，額度 ${c['room_usd']:,.0f}"),
                     "after": ["register-order --rule R30", "shadow record --kind cf-r30-add --correct-if over", "thesis 留痕（+30d 驗）"]})
    for oid, o in (reg.get("orders") or {}).items():
        if o.get("rule_ref") == "R30" and o.get("transaction") == "B" and o.get("symbol") not in r30_syms \
                and str(o.get("state", "")).startswith(("ORDER-SUBMITTED", "ORDER-REQUESTED")):
            plan.append({"rule": "R30-cancel", "symbol": o["symbol"], "action": "CANCEL", "qty": o.get("shares"),
                         "order": {"id": oid}, "basis": "R30 條件已不成立（revision 轉弱 / 跌破 SMA50 / 進 R28a 鎖 / 財報窗）→ 撤回檔買單", "after": []})

    # ── G. R25 修訂 sleeve 動作（guard 已算）───────────────────────────────
    for a in (st.get("sleeve") or {}).get("actions", []) or []:
        sleeve_pos = [p for p in positions.values() if p.get("bucket") == "sleeve(ETF)"]
        for p in sleeve_pos:
            if a["symbol"] not in ("SLEEVE", p["symbol"]):
                continue
            c = close_of(p["symbol"]) or p.get("last") or 0
            if a["action"] == "BUY_TO":
                # R25 規則 1 + 規則 4：目標權重平均分給 sleeve ETF，每檔分兩批——一半貼盤 day、一半 −4.5% GTC
                n_etf = max(len(sleeve_pos), 1)
                per = a.get("target_weight_pct", 8.0) / n_etf
                need_usd = max(0.0, (per - (p.get("weight_pct") or 0)) / 100 * total)
                if need_usd < 300 or not c:
                    continue
                if any(o.get("symbol") == p["symbol"] and o.get("rule_ref") == "R25" and o.get("transaction") == "B"
                       and str(o.get("state", "")).startswith(("ORDER-SUBMITTED", "ORDER-REQUESTED")) for o in (reg.get("orders") or {}).values()):
                    skip(p["symbol"], "R25", "已有 R25 在掛買單"); continue
                q1 = math.floor(need_usd * 0.5 / c); q2 = math.floor(need_usd * 0.5 / (c * 0.955))
                if q1 >= 1:
                    plan.append({"rule": "R25-sleeve", "symbol": p["symbol"], "action": "BUY", "qty": q1,
                                 "order": {"type": "limit", "limit": round(c * 1.002, 2), "duration": "day"},
                                 "basis": f"{a['why']} → sleeve 補到 {a.get('target_weight_pct')}%（第一批貼盤）", "after": ["register-order --rule R25"]})
                if q2 >= 1:
                    plan.append({"rule": "R25-sleeve-ladder", "symbol": p["symbol"], "action": "BUY", "qty": q2,
                                 "order": {"type": "limit", "limit": round(c * 0.955, 2), "duration": "gt90"},
                                 "basis": f"{a['why']} → 第二批 −4.5% GTC（R25 規則 4）", "after": ["register-order --rule R25"]})
                continue
            if a["action"] == "SELL_HALF":
                qty = math.floor(p["qty"] / 2)
            elif a["action"] in ("TRIM", "TRIM_TO"):
                tgt = a.get("target_weight_pct", 6.0)
                if a["symbol"] == "SLEEVE":
                    share = (p.get("weight_pct") or 0) / max((st.get("sleeve") or {}).get("weight_pct") or 1, 0.01)
                    tgt = tgt * share
                qty = math.floor(max(0.0, (p.get("weight_pct") or 0) - tgt) / 100 * total / c) if c else 0
            else:
                continue
            if qty >= 1:
                plan.append({"rule": "R25-sleeve", "symbol": p["symbol"], "action": "SELL", "qty": qty,
                             "order": {"type": "limit", "limit": round(c * 0.997, 2), "duration": DUR_SELL},
                             "basis": f"{a['why']} → {a['action']}；賣出所得停泊 SGOV（R24），redeploy 走飛輪", "after": ["register-order --rule R25", "R24 SGOV 買單同日"]})

    # ── H. 陳舊自動賣單：R23 / user-close-line / R25 的在掛賣單若非今日掛且仍未成交 → 撤（隔晚依新收盤重算重掛）──
    for oid, o in (reg.get("orders") or {}).items():
        rr = o.get("rule_ref") or ""
        if o.get("transaction") == "S" and rr.split("-")[0] in ("R23", "user", "R25") \
                and str(o.get("state", "")).startswith(("ORDER-SUBMITTED", "ORDER-REQUESTED")) \
                and (o.get("rule_registered_at") or o.get("first_seen") or "") < (today - timedelta(days=1)).isoformat():
            plan.append({"rule": f"{rr}-cancel", "symbol": o["symbol"], "action": "CANCEL", "qty": o.get("shares"),
                         "order": {"id": oid}, "basis": f"自動賣單 {oid}（{rr}）掛超過一個交易日未成交 → 撤，今晚依新收盤重算", "after": []})

    # ── 去重 / 優先序（衝突 C2 型）：同一標的同向只出一張單。用戶裁決收盤線 > R23（9/2 裁決：MYRG 以 $274 線取代 R23），
    #    R23-30 > R23-20；合併時在 basis 註明被吸收的規則，避免兩條規則各賣一次把認列桶賣穿 30% runner。
    merged, seen = [], {}
    prio = {"user-close-line": 3, "R23-30": 2, "R23-20": 1}
    for p in plan:
        # 分批梯（*-ladder）是刻意的第二張單，不與第一批合併
        key = (p["symbol"], p["action"], "ladder" if str(p.get("rule", "")).endswith("-ladder") else "")
        if key not in seen:
            seen[key] = len(merged); merged.append(dict(p)); continue
        i = seen[key]; cur = merged[i]
        keep, drop = (p, cur) if prio.get(p["rule"], 0) > prio.get(cur["rule"], 0) else (cur, p)
        keep = dict(keep); keep["basis"] += f"｜同日 {drop['rule']} 亦觸發，已合併（不重複賣）"
        keep["merged_rules"] = sorted({cur.get("rule"), p.get("rule")} | set(cur.get("merged_rules", [])))
        merged[i] = keep
    plan = merged

    # ── 已在券商的同規則同向單 → 移到 skipped（晚間 pass 掛過的單，早上 briefing 讀 plan 不得重下）──
    open_by_key = {}
    for oid, o in (reg.get("orders") or {}).items():
        if str(o.get("state", "")).startswith(("ORDER-SUBMITTED", "ORDER-REQUESTED")):
            open_by_key.setdefault((o.get("symbol"), o.get("transaction"), (o.get("rule_ref") or "").split("-")[0]), []).append(oid)
    kept = []
    for p in plan:
        side = {"SELL": "S", "BUY": "B"}.get(p.get("action"))
        base = (p.get("rule") or "").split("-")[0] if p.get("rule") not in ("user-close-line",) else "user"
        dup = open_by_key.get((p.get("symbol"), side, base)) if side else None
        if dup:
            skip(p["symbol"], p["rule"], f"已在券商在掛 {dup}（昨晚 evening pass 掛的）— 不重下")
        else:
            kept.append(p)
    plan = kept

    # R28a：買方硬線清單（T6.5 條件 4 讀此；guard 已算）
    buy_locked = {s: p["buy_locked"] for s, p in positions.items() if p.get("buy_locked")}

    # C6：T6.5 新增曝險買單的現金可用性（現金停在 SGOV 時要先賣，T+1 才能用）
    r30_notional = sum(p["qty"] * p["order"]["limit"] for p in plan if p.get("rule") == "R30-add")
    if r30_notional and cash_available < r30_notional and parked > 0:
        plan.append({"rule": "R24-unpark", "symbol": "SGOV", "action": "SELL",
                     "qty": math.ceil(min(parked, r30_notional - cash_available) / sgov_px),
                     "order": {"type": "limit", "limit": round(sgov_px - 0.01, 2), "duration": "day"},
                     "basis": f"R30 買單合計 {r30_notional:,.0f} > 可用現金 {cash_available:,.0f}，SGOV 停泊 {parked:,.0f} → 先解泊（C6，T+1）", "after": ["register-order --rule R24"]})
    cash_gate = {"cash_available": round(cash_available, 2), "parked_sgov": round(parked, 2),
                 "rule": "新倉/加碼買單金額 ≤ cash_available 才可當日執行；不足且 parked_sgov > 0 → 今日先掛 SGOV 賣（T+1），買單延一日；兩者皆無 → 列 🎯 待辦不下單"}
    if cash_available < 3_000 and parked > 0 and not any(p.get("rule") == "R24-unpark" for p in plan):
        plan.append({"rule": "R24-unpark", "symbol": "SGOV", "action": "SELL", "qty": math.ceil(min(parked, 3_000 - cash_available) / sgov_px),
                     "order": {"type": "limit", "limit": round(sgov_px - 0.01, 2), "duration": "day"},
                     "basis": f"可用現金 {cash_available:,.0f} < $3k 新曝險上限，SGOV 停泊 {parked:,.0f} → 先解泊（C6，T+1）",
                     "after": ["register-order --rule R24"]})

    out = {"asof": today.isoformat(), "close_asof": closes.get("asof"), "pass": "preclose" if preclose else "close",
           "buffer": BUF, "mode": "dry-run" if not execute else "execute",
           "execute_unlock": EXECUTE_UNLOCK.isoformat(), "px_note": px_note,
           "plan": plan, "skipped": skipped, "cash_gate": cash_gate, "buy_locked": buy_locked,
           "discipline": "T6.5 只執行本清單；新倉/加碼/選擇權開倉不在此；所有觸發以前一收盤判定（R17）"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    if stale_state:
        print(f"⚠️ position-state source={st.get('source')}（非 firstrade-live）→ 以下 plan 不可靠，僅供參考，execute 已被拒")
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
            print(f"⛔ --execute 鎖定中至 {EXECUTE_UNLOCK}")
            return 3
        if os.environ.get("AUTO_EXEC_LIVE") != "1":
            print("⛔ --execute 需要環境變數 AUTO_EXEC_LIVE=1（evening_pass.sh 會設；手動跑要明示）")
            return 3
        executed = execute_plan(plan, reg, today)
        out["executed"] = executed
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
        with open(ROOT / "research" / "auto-exec-log.jsonl", "a") as fh:
            for e in executed:
                fh.write(json.dumps({"date": today.isoformat(), **e}, ensure_ascii=False) + "\n")
        return 0 if all(e.get("status") in ("placed", "cancelled", "skipped") for e in executed) else 4
    return 0


# ── v2 執行層（2026-09-15 用戶解鎖：MYRG 手動案——收盤破線到隔日 11:00 ET 才執行太慢）──────
# 走 trade_ledger._ft_call（firstrade-server venv 內全新 session），下 gt90 限價單：收盤後掛、次一交易日生效。
# 只做現股 BUY/SELL 限價與 CANCEL；CLOSE_SPREAD 仍推 Telegram 手掛（複式單只收 ET 7–16）。
def _ft_stock_order(sym, side, qty, price, duration="gt90"):
    import trade_ledger as tl
    snippet = (f"print(m._stock_order({sym!r}, {side!r}, {int(qty)}, 'limit', {duration!r}, {float(price)}, None, False))")
    return tl._ft_call(snippet)


def _ft_cancel(order_id):
    import trade_ledger as tl
    return tl._ft_call(f"print(m.cancel_order({order_id!r}))")


def _note_defensive_trim(sym, order_id, rule, today):
    """在該標的的 open 旗標 history 追加 action=trimmed（無旗標則建一個 r23-auto，deadline +21d）。"""
    import subprocess
    try:
        d = _load(FLAGS, {"flags": []})
        f = next((x for x in d["flags"] if x.get("ticker") == sym and x.get("status") in ("open", "forced")), None)
        if f is None:
            subprocess.run([sys.executable, str(ROOT / "tools" / "trade_ledger.py"), "flag", "--ticker", sym, "--slug", "r23-auto",
                            "--reason", f"auto_exec {rule} 減碼 {today}（{order_id}）；殘倉交 R28b/R29 判定", "--deadline", (today + timedelta(days=21)).isoformat()],
                           capture_output=True, text=True, timeout=60)
            d = _load(FLAGS, {"flags": []})
            f = next((x for x in d["flags"] if x.get("ticker") == sym and x.get("status") in ("open", "forced")), None)
        if f is not None:
            f.setdefault("history", []).append({"date": today.isoformat(), "event": "auto_exec_trim", "action": "trimmed",
                                                "note": f"{rule} {order_id}（day/gt90 限價，成交以 trade-ledger 為準）"})
            FLAGS.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    except Exception:  # noqa: BLE001
        pass


def execute_plan(plan, reg, today):
    import subprocess
    results = []
    open_same = {}
    for oid, o in (reg.get("orders") or {}).items():
        if str(o.get("state", "")).startswith(("ORDER-SUBMITTED", "ORDER-REQUESTED")):
            open_same.setdefault((o.get("symbol"), o.get("transaction")), []).append((oid, o.get("rule_ref")))
    for p in plan:
        rule, sym, act = p.get("rule"), p.get("symbol"), p.get("action")
        rec = {"rule": rule, "symbol": sym, "action": act, "qty": p.get("qty"), "limit": (p.get("order") or {}).get("limit")}
        try:
            if act == "CANCEL":
                r = _ft_cancel(p["order"]["id"])
                rec.update(status="cancelled", broker=r)
            elif act in ("BUY", "SELL") and (p.get("order") or {}).get("type") == "limit" and p.get("qty"):
                side = "S" if act == "SELL" else "B"
                dup = [oid for oid, rr in open_same.get((sym, side), []) if (rr or "").split("-")[0] == (rule or "").split("-")[0]]
                if dup:
                    rec.update(status="skipped", why=f"同規則同向已有在掛單 {dup}"); results.append(rec); continue
                dur = "day" if (p.get("order") or {}).get("duration") == "day" else "gt90"
                r = _ft_stock_order(sym, act.lower(), p["qty"], p["order"]["limit"], dur)
                res = r.get("result") or r
                oid = res.get("order_id") if isinstance(res, dict) else None
                if not oid:
                    rec.update(status="error", broker=r); results.append(rec); continue
                rec.update(status="placed", order_id=oid, state=res.get("state"), duration=dur)
                if base_rule in ("R23", "user-close-line"):  # 防守型減碼留痕到旗標 → guard 的 R28a 鎖 / R28b 判定吃得到
                    _note_defensive_trim(sym, oid, rule, today)
                if p.get("alert_id"):  # 用戶收盤線已執行 → 撤警報，不再每晚重發
                    subprocess.run([sys.executable, str(ROOT / "tools" / "price_alerts.py"), "remove", "--id", p["alert_id"]],
                                   capture_output=True, text=True, timeout=30)
                base_rule = (rule or "").split("-")[0] if rule not in ("user-close-line", "options-mgmt") else rule
                subprocess.run([sys.executable, str(ROOT / "tools" / "trade_ledger.py"), "register-order", "--id", oid,
                                "--rule", base_rule, "--note", f"auto_exec evening {today}: {p.get('basis','')[:120]}"],
                               capture_output=True, text=True, timeout=60)
                kind = {"R30": "cf-r30-add", "R23": "cf-r23-exec", "user": "cf-r23-exec", "R25": "cf-r25-sleeve"}.get(base_rule.split("-")[0])
                if kind:
                    subprocess.run([sys.executable, str(ROOT / "tools" / "shadow_signals.py"), "record", "--kind", kind, "--ticker", sym,
                                    "--price", str(p["order"]["limit"]), "--size", str(round(p["qty"] * p["order"]["limit"], 2)),
                                    "--correct-if", "over" if act == "BUY" else "under", "--note", f"auto_exec {rule} {oid}"],
                                   capture_output=True, text=True, timeout=60)
            else:
                rec.update(status="skipped", why="非現股限價單（CLOSE_SPREAD/GTC-tier 類）→ Telegram 手掛")
        except Exception as e:  # noqa: BLE001
            rec.update(status="error", error=str(e)[-200:])
        results.append(rec)
    try:
        subprocess.run([sys.executable, str(ROOT / "tools" / "trade_ledger.py"), "snapshot-orders"], capture_output=True, text=True, timeout=120)
    except Exception:  # noqa: BLE001
        pass
    return results


def audit(day: str | None = None) -> int:
    """乾跑對照：當天 plan vs 實際（order-registry 當天出現的單 + trade-ledger 當天成交）。
    三類差異：missed（plan 有、實際沒下）/ unplanned（實際下了機械型賣單、plan 沒有）/ mismatch（股數差）。
    exit 2 = 有差異（runner 直推 Telegram）；0 = 一致或當天無 plan。結果 append 到 research/auto-exec-audit.jsonl。
    時序：runner 早上（ET 11:00）用「前一收盤」產 plan → 同日 briefing 執行 → 同日事後 audit，三者同一個 date。
    手動在盤後跑 main() 會產生「今日 asof、明日才執行」的 plan，此時 --audit 會報預告性 missed，忽略即可（不要寫進帳）。"""
    day = day or date.today().isoformat()
    plan_doc = _load(OUT, {})
    plan = plan_doc.get("plan", []) if plan_doc.get("asof") == day else []
    reg = _load(REGISTRY, {})
    fills = []
    led = ROOT / "research" / "trade-ledger.jsonl"
    if led.exists():
        for line in led.read_text().splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("date") == day:
                fills.append(r)
    orders_today = [o for o in (reg.get("orders") or {}).values()
                    if (o.get("placed") or o.get("first_seen")) == day]
    side_map = {"SELL": "S", "BUY": "B"}
    issues = []
    for p in plan:
        if p["action"] not in side_map:
            continue  # spread/GTC-tier 類先不比對
        want = side_map[p["action"]]
        got_o = [o for o in orders_today if o.get("symbol") == p["symbol"] and o.get("transaction") == want]
        got_f = [f for f in fills if f.get("symbol") == p["symbol"] and f.get("side", "").upper().startswith("SOLD" if want == "S" else "BOUGHT")]
        if not got_o and not got_f:
            issues.append({"type": "missed", "symbol": p["symbol"], "rule": p["rule"], "qty": p.get("qty"),
                           "msg": f"plan 要 {p['action']} {p['symbol']} {p.get('qty')}，當天無掛單也無成交"})
        else:
            qty_got = sum((o.get("shares") or 0) for o in got_o) or sum((f.get("qty") or 0) for f in got_f)
            if p.get("qty") and abs(qty_got - p["qty"]) > 0.5:
                issues.append({"type": "mismatch", "symbol": p["symbol"], "rule": p["rule"],
                               "msg": f"plan {p['qty']} 股 vs 實際 {qty_got:g} 股"})
    planned_sells = {p["symbol"] for p in plan if p["action"] == "SELL"}
    # 規則單成交也算 planned：有 rule_ref 的單（register-order 登記過）= 系統決策，不論是機器掛的還是用戶照 plan 手動下的
    # （9/15 MYRG：9/14 plan 的 14 股由用戶 09:35 手動執行，plan 當天早上重算後已無此項 → 舊邏輯誤報 unplanned）
    for oid, o in (reg.get("orders") or {}).items():
        if o.get("rule_ref") and o.get("transaction") == "S" and "FILLED" in str(o.get("state", "")) \
                and (o.get("rule_registered_at") or o.get("first_seen") or "")[:10] == day:
            planned_sells.add(o.get("symbol"))
    st = _load(STATE, {})
    buckets = {p["symbol"]: p.get("bucket") for p in st.get("positions", [])}
    for f in fills:
        if f.get("side", "").upper().startswith("SOLD") and f.get("symbol") not in planned_sells \
                and buckets.get(f.get("symbol")) == "認列" and not f.get("symbol", "").endswith(("C", "P")) \
                and len(f.get("symbol", "")) <= 5:
            issues.append({"type": "unplanned", "symbol": f["symbol"],
                           "msg": f"認列桶 {f['symbol']} 賣 {f.get('qty')} 股不在 plan（模型自判機械觸發？或非機械賣出）"})
    rec = {"date": day, "plan_n": len(plan), "issues": issues}
    with open(ROOT / "research" / "auto-exec-audit.jsonl", "a") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if not plan and not issues:
        print(f"🧾 auto_exec audit {day}：當天無 plan、無認列桶非計畫賣出"); return 0
    if not issues:
        print(f"🧾 auto_exec audit {day}：plan {len(plan)} 項全部對上 ✅"); return 0
    print(f"🧾 auto_exec audit {day}：{len(issues)} 項差異")
    for i in issues:
        print(f"  ✗ {i['type']:<9} {i['symbol']:<6} {i['msg']}")
    return 2


if __name__ == "__main__":
    if "--audit" in sys.argv:
        d = [a for a in sys.argv[1:] if re.match(r"\d{4}-\d{2}-\d{2}$", a)]
        sys.exit(audit(d[0] if d else None))
    sys.exit(main(sys.argv[1:]))
