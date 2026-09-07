#!/usr/bin/env python3
"""
price_alerts.py — 自動價格警報：條件觸發 → Telegram 推送。

Firstrade 非官方 lib 無警報 endpoint（僅 account/order/symbols/watchlist），
原生 App 警報無法程式化 → 以 yfinance 報價自建。launchd 每 15 分鐘輪詢，
盤中時窗（ET 09:25–16:10 交易日）以外直接靜默退出。

Usage:
  python3 tools/price_alerts.py                 # 評估 + 推送（launchd 入口）
  python3 tools/price_alerts.py --dry-run       # 評估但不送、不寫狀態
  python3 tools/price_alerts.py --force         # 跳過盤中時窗 gate（測試）
  python3 tools/price_alerts.py list            # 列出警報與狀態
  python3 tools/price_alerts.py add --symbol NVDA --below 190 --note "說明" \
      [--mode once|once_per_day] [--expires YYYY-MM-DD] [--id 自訂ID]
  python3 tools/price_alerts.py add --symbol GLD --rolling-high 60 --note "說明"
  python3 tools/price_alerts.py remove --id <ID>
  python3 tools/price_alerts.py test            # 送一則測試訊息驗證管線

Alert types:
  price_below / price_above — 現價 vs level
  rolling_high — 現價 > 前 N 個交易日收盤最高（不含今日）

mode: once_per_day（預設，每日至多一發）| once（觸發後自動停用）
狀態與定義同存 research/price-alerts.json。
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from send_briefing import load_env, send_telegram  # noqa: E402
from check_trading_day import is_trading_day  # noqa: E402

ALERTS_FILE = ROOT / "research" / "price-alerts.json"
ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    return datetime.now(ET)


def load_alerts() -> dict:
    if not ALERTS_FILE.exists():
        return {"alerts": []}
    return json.loads(ALERTS_FILE.read_text(encoding="utf-8"))


def save_alerts(data: dict) -> None:
    ALERTS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def in_market_window(ts: datetime) -> bool:
    if not is_trading_day(ts.date()):
        return False
    hm = ts.hour * 60 + ts.minute
    return (9 * 60 + 25) <= hm <= (16 * 60 + 10)


def is_active(a: dict, today_iso: str) -> bool:
    if a.get("status") in ("triggered", "disabled"):
        return False
    exp = a.get("expires")
    if exp and today_iso > exp:
        return False
    if a.get("mode", "once_per_day") == "once_per_day" and a.get("last_fired") == today_iso:
        return False
    return True


def fetch_last_prices(symbols: list[str]) -> dict[str, float]:
    import yfinance as yf

    out: dict[str, float] = {}
    for s in symbols:
        try:
            fi = yf.Ticker(s).fast_info
            px = None
            for key in ("last_price", "lastPrice"):
                try:
                    px = fi[key]
                    break
                except (KeyError, TypeError):
                    continue
            if px is None:
                px = getattr(fi, "last_price", None)
            if px:
                out[s] = float(px)
        except Exception as e:  # noqa: BLE001 — 單一 symbol 失敗不擋其他警報
            print(f"[warn] quote failed {s}: {e}", file=sys.stderr)
    return out


def fetch_rolling_high(symbol: str, lookback: int, today) -> float | None:
    """前 lookback 個交易日的收盤最高（不含今日）。"""
    import yfinance as yf

    try:
        hist = yf.Ticker(symbol).history(period=f"{lookback * 2}d")
        closes = hist["Close"].dropna()
        if len(closes) and closes.index[-1].date() == today:
            closes = closes.iloc[:-1]
        closes = closes.iloc[-lookback:]
        if closes.empty:
            return None
        return float(closes.max())
    except Exception as e:  # noqa: BLE001
        print(f"[warn] history failed {symbol}: {e}", file=sys.stderr)
        return None


def fetch_peak_close(symbol: str, since_iso: str, today) -> float | None:
    """自 since 起的收盤峰值（不含今日）— R23 認列桶自峰回撤線用。"""
    import yfinance as yf

    try:
        hist = yf.Ticker(symbol).history(start=since_iso)
        closes = hist["Close"].dropna()
        if len(closes) and closes.index[-1].date() == today:
            closes = closes.iloc[:-1]
        if closes.empty:
            return None
        return float(closes.max())
    except Exception as e:  # noqa: BLE001
        print(f"[warn] history failed {symbol}: {e}", file=sys.stderr)
        return None


def evaluate(dry_run: bool = False, force: bool = False) -> int:
    ts = now_et()
    if not force and not in_market_window(ts):
        return 0  # 盤外靜默退出（launchd 每 15 分呼叫一次）

    data = load_alerts()
    today_iso = ts.date().isoformat()
    active = [a for a in data["alerts"] if is_active(a, today_iso)]
    if not active:
        print(f"[{ts:%H:%M} ET] no active alerts")
        return 0

    plain_syms = sorted({a["symbol"] for a in active if a["type"] in ("price_below", "price_above")})
    prices = fetch_last_prices(plain_syms)

    fired: list[str] = []
    for a in active:
        sym, typ = a["symbol"], a["type"]
        line = None
        if typ in ("price_below", "price_above"):
            px = prices.get(sym)
            if px is None:
                continue
            if typ == "price_below" and px <= a["level"]:
                line = f"• {sym} ${px:,.2f} ≤ {a['level']:g} — {a['note']}"
            elif typ == "price_above" and px >= a["level"]:
                line = f"• {sym} ${px:,.2f} ≥ {a['level']:g} — {a['note']}"
        elif typ == "rolling_high":
            px = fetch_last_prices([sym]).get(sym)
            threshold = fetch_rolling_high(sym, a.get("lookback", 60), ts.date())
            if px is not None and threshold is not None and px > threshold:
                line = (
                    f"• {sym} ${px:,.2f} 創 {a.get('lookback', 60)} 日新高"
                    f"（前高 ${threshold:,.2f}）— {a['note']}"
                )
        elif typ == "peak_dd":
            px = fetch_last_prices([sym]).get(sym)
            peak = fetch_peak_close(sym, a.get("since", "2026-01-01"), ts.date())
            if px is not None and peak is not None:
                threshold = peak * (1 - a["level"] / 100.0)
                if px <= threshold:
                    line = (
                        f"• {sym} ${px:,.2f} 自峰 ${peak:,.2f} 回撤 {(px / peak - 1) * 100:.1f}%"
                        f"（≤ −{a['level']:g}% 線 ${threshold:,.2f}）— {a['note']}"
                    )
        else:
            print(f"[warn] unknown alert type: {typ}", file=sys.stderr)
            continue

        if line:
            fired.append(line)
            a["last_fired"] = today_iso
            a["fired_count"] = a.get("fired_count", 0) + 1
            if a.get("mode", "once_per_day") == "once":
                a["status"] = "triggered"

    if not fired:
        print(f"[{ts:%H:%M} ET] {len(active)} active, none fired")
        return 0

    msg = f"🔔 價格警報 {ts:%m-%d %H:%M} ET\n" + "\n".join(fired)
    if dry_run:
        print("[DRY-RUN] would send:\n" + msg)
        return 0
    send_telegram(msg)
    save_alerts(data)
    print(f"[{ts:%H:%M} ET] sent {len(fired)} alert(s)")
    return 0


def cmd_list() -> int:
    data = load_alerts()
    today_iso = now_et().date().isoformat()
    if not data["alerts"]:
        print("（無警報）")
        return 0
    for a in data["alerts"]:
        state = "✅ active" if is_active(a, today_iso) else f"⏸ {a.get('status') or 'cooldown/expired'}"
        if a["type"] == "rolling_high":
            cond = f"{a['symbol']} > {a.get('lookback', 60)}日高"
        elif a["type"] == "peak_dd":
            cond = f"{a['symbol']} ≤ 自峰 −{a['level']:g}%（峰自 {a.get('since')}）"
        else:
            cmp_str = "≤" if a["type"] == "price_below" else "≥"
            cond = f"{a['symbol']} {cmp_str} {a['level']:g}"
        extra = f" fired={a.get('fired_count', 0)}" if a.get("fired_count") else ""
        exp = f" exp={a['expires']}" if a.get("expires") else ""
        print(f"{state}  [{a['id']}]  {cond}  mode={a.get('mode', 'once_per_day')}{exp}{extra}\n"
              f"        {a['note']}")
    return 0


def cmd_add(args) -> int:
    data = load_alerts()
    if args.rolling_high:
        typ, level, lookback = "rolling_high", None, args.rolling_high
        default_id = f"{args.symbol}-high{args.rolling_high}d"
    elif args.peak_dd is not None:
        if not args.since:
            print("error: --peak-dd 需要 --since YYYY-MM-DD（峰值起算日＝建倉日）", file=sys.stderr)
            return 1
        typ, level, lookback = "peak_dd", args.peak_dd, None
        default_id = f"{args.symbol}-peakdd{args.peak_dd:g}"
    elif args.below is not None:
        typ, level, lookback = "price_below", args.below, None
        default_id = f"{args.symbol}-below-{args.below:g}"
    elif args.above is not None:
        typ, level, lookback = "price_above", args.above, None
        default_id = f"{args.symbol}-above-{args.above:g}"
    else:
        print("error: 需要 --below / --above / --rolling-high 其一", file=sys.stderr)
        return 1

    alert_id = args.id or default_id
    if any(a["id"] == alert_id for a in data["alerts"]):
        print(f"error: id 已存在: {alert_id}（用 remove 先刪或換 --id）", file=sys.stderr)
        return 1

    entry = {
        "id": alert_id,
        "symbol": args.symbol.upper() if not args.symbol.startswith("^") else args.symbol,
        "type": typ,
        "note": args.note,
        "mode": args.mode,
        "created": now_et().date().isoformat(),
        "status": None,
        "last_fired": None,
        "fired_count": 0,
    }
    if level is not None:
        entry["level"] = level
    if lookback is not None:
        entry["lookback"] = lookback
    if typ == "peak_dd":
        entry["since"] = args.since
    if args.expires:
        entry["expires"] = args.expires

    data["alerts"].append(entry)
    save_alerts(data)
    print(f"added: {alert_id}")
    return 0


def cmd_remove(alert_id: str) -> int:
    data = load_alerts()
    before = len(data["alerts"])
    data["alerts"] = [a for a in data["alerts"] if a["id"] != alert_id]
    if len(data["alerts"]) == before:
        print(f"error: id 不存在: {alert_id}", file=sys.stderr)
        return 1
    save_alerts(data)
    print(f"removed: {alert_id}")
    return 0


def cmd_test() -> int:
    ts = now_et()
    send_telegram(f"🔔 價格警報系統測試 {ts:%m-%d %H:%M} ET — 管線正常（launchd 每 15 分輪詢，盤中生效）")
    print("test message sent")
    return 0


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="自動價格警報 → Telegram")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="跳過盤中時窗 gate")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run")
    sub.add_parser("list")
    sub.add_parser("test")
    p_add = sub.add_parser("add")
    p_add.add_argument("--symbol", required=True)
    p_add.add_argument("--below", type=float)
    p_add.add_argument("--above", type=float)
    p_add.add_argument("--rolling-high", type=int, metavar="N")
    p_add.add_argument("--peak-dd", type=float, metavar="PCT",
                       help="R23：現價 ≤ 自 --since 起收盤峰值 × (1−PCT/100) 時觸發")
    p_add.add_argument("--since", metavar="YYYY-MM-DD", help="--peak-dd 峰值起算日（建倉日）")
    p_add.add_argument("--note", required=True)
    p_add.add_argument("--mode", choices=["once", "once_per_day"], default="once_per_day")
    p_add.add_argument("--expires", metavar="YYYY-MM-DD")
    p_add.add_argument("--id")
    p_rm = sub.add_parser("remove")
    p_rm.add_argument("--id", required=True)

    args = parser.parse_args()
    cmd = args.cmd or "run"
    if cmd == "run":
        return evaluate(dry_run=args.dry_run, force=args.force)
    if cmd == "list":
        return cmd_list()
    if cmd == "add":
        return cmd_add(args)
    if cmd == "remove":
        return cmd_remove(args.id)
    if cmd == "test":
        return cmd_test()
    return 1


if __name__ == "__main__":
    sys.exit(main())
