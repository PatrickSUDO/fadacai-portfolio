#!/usr/bin/env python3
"""monthly_grid.py — 月度格子（2026-10-30 用戶裁決，核心／衛星提案 P4 輕版）

每月第一個交易日（美東）推一則 Telegram：格子日名單、權重、桶別、R29 最弱兩檔、R30 候選、現金／停泊。
目的：把「加減碼決定」收斂到每月一個時點看一次全局；月中 briefing 的待辦暫不壓（回測：月中操作全年 −4pp 報酬換 +4pp 回撤，
中性，先觀察）。只讀 position_guard 產出的 research/position-state.json，不下單、不改任何狀態檔（除了自己的 state）。
依據：tools/core_satellite_backtest.py（實際權重月再平衡 2026 +31.3% vs 帳戶 +27.6%）。
State: briefing-out/cache/monthly-grid.json {"last_fired": "YYYY-MM", "n": 格子序號}
Usage: python3 tools/monthly_grid.py [--force] [--dry-run]
"""
from __future__ import annotations
import json, sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "research" / "position-state.json"
MY_STATE = ROOT / "briefing-out" / "cache" / "monthly-grid.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))
FIRST_GRID = "2026-11"   # 第 1 格；之後每月 +1


def is_first_session_of_month(today: date) -> bool:
    """今天是否為本月第一個交易日：本月在今天之前沒有任何 VOO 已觀測 session。runner 只在交易日跑，故只需排除「月初前幾天是假日」。"""
    import yfinance as yf
    hist = yf.Ticker("VOO").history(period="1mo", auto_adjust=False)
    if hist.empty:
        raise RuntimeError("yfinance returned no VOO rows")
    sessions = [d.date() for d in hist.index]
    earlier_this_month = [d for d in sessions if d.year == today.year and d.month == today.month and d < today]
    if earlier_this_month:
        return False
    if today.weekday() >= 5:
        return False
    return True


def fmt_row(p: dict) -> str:
    w = p.get("weight_pct") or 0; u = p.get("unrealized_pct"); rs = p.get("rs90_vs_sector_pct")
    up, dn = p.get("rev_up_30d"), p.get("rev_down_30d")
    rev = f"修正 {int(up)}↑{int(dn)}↓" if up is not None and dn is not None else "修正 n/a"
    rs_s = f"RS90 {rs:+.0f}pp" if rs is not None else "RS90 n/a"
    u_s = f"{u:+.0f}%" if u is not None else "n/a"
    b = {"信念": "🔵", "認列": "🟢"}.get(p.get("bucket"), "⚪")
    sold = f"｜已減 {p.get('cum_sold_pct'):.0f}%" if (p.get("cum_sold_pct") or 0) > 0 else ""
    return f"{b} {p['symbol']:<5} {w:4.1f}%  未實現 {u_s}  {rs_s}  {rev}{sold}"


def build_message(st: dict, n: int, today: date) -> str:
    pos = [p for p in st.get("positions", []) if p.get("bucket") in ("信念", "認列")]
    pos.sort(key=lambda p: -(p.get("weight_pct") or 0))
    total = st.get("total_account_value") or 0
    cash = st.get("cash") or 0
    parked = sum((p.get("weight_pct") or 0) for p in st.get("positions", []) if p.get("symbol") == "VOO")
    conv = sum(1 for p in pos if p.get("bucket") == "信念")
    weakest = st.get("weakest_two") or []
    adds = st.get("add_candidates") or []
    lines = [f"📅 月度格子 {today.isoformat()}（第 {n} 格）｜總值 ${total:,.0f}｜現金 {cash/total*100 if total else 0:.1f}%｜VOO 停泊 {parked:.1f}%",
             f"衛星 {len(pos)} 檔（信念 {conv}／認列 {len(pos)-conv}）｜目標 10–14 檔，慢慢收（用戶 2026-10-30：檔數待實驗）", ""]
    lines += [fmt_row(p) for p in pos]
    lines.append("")
    if weakest:
        ws = [w if isinstance(w, str) else (w.get("symbol") or str(w)) for w in weakest]
        lines.append(f"R29 最弱兩檔（90 日對板塊落後）：{' / '.join(ws)} → 本格要不要減一檔？減則所得走 R30 加碼領導者，不新增名字")
    if adds:
        ad = [a if isinstance(a, str) else (a.get("symbol") or str(a)) for a in adds]
        lines.append(f"R30 買強候選（未實現>0、修正↑>↓、>SMA50、權重<8.5%）：{' / '.join(ad)} → 回檔 SMA20 GTC ≤$3k")
    top3 = [p["symbol"] for p in pos[:3]]
    lines.append(f"選擇權參考（非規則）：賣方可考慮的不含前三名持有 α：{' '.join(top3)} 不掛 call")
    lines.append("")
    lines.append("→ 動作：本月的加減碼決定在這裡一次看完；月中只處理硬線（>10%、R32 gate、旗標 deadline）、財報事件。R23 已改影子，不會自動賣。")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    force = "--force" in argv; dry = "--dry-run" in argv
    today = datetime.now(ZoneInfo("America/New_York")).date()
    my = json.loads(MY_STATE.read_text()) if MY_STATE.is_file() else {"last_fired": None, "n": 0}
    ym = today.strftime("%Y-%m")
    if not force:
        if my.get("last_fired") == ym:
            print(f"monthly grid: already fired for {ym}"); return 0
        if not is_first_session_of_month(today):
            print(f"monthly grid: {today} is not the first session of {ym}"); return 0
    st = json.loads(STATE.read_text())
    if st.get("source") != "firstrade-live":
        print(f"monthly grid: position-state source={st.get('source')} (not live) → skip"); return 0
    n = (my.get("n") or 0) + 1
    msg = build_message(st, n, today)
    if len(msg) > 3000:
        msg = msg[:2950] + "\n…（截斷）"
    if dry:
        print(msg); return 0
    from send_briefing import load_env, send_telegram  # noqa: E402
    load_env(); send_telegram(msg)
    MY_STATE.parent.mkdir(parents=True, exist_ok=True)
    MY_STATE.write_text(json.dumps({"last_fired": ym, "n": n, "sent_at": datetime.now().isoformat(timespec="seconds")}, indent=2) + "\n")
    print(f"monthly grid fired: {ym} (#{n})"); return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
