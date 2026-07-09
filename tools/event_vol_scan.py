#!/usr/bin/env python3
"""
event_vol_scan.py — 財報/重大事件前「末日 buy call / 雙買 straddle」機會掃描引擎。

對每個候選 ticker：
  1. 事件日：briefing-out/cache/earnings-dates.json（fresh）→ EODHD calendar/earnings fallback
  2. 選事件後第一個到期（AMC → 事件日+1 起算）的期權鏈（yfinance 本地庫，不經 MCP）
  3. ATM straddle mid → 隱含移動 %；再取 1×IM 的 OTM call 當末日 call 候選
  4. 歷史基準：earnings-history.json 的 last_8q 財報日 × 日線 → 過去 8 季實際 |移動| 均值/中位
  5. VRP = 隱含移動 ÷ 歷史中位移動（<0.85 = 雙買便宜；>1.2 = IV crush 風險）
  6. 方向 skew：fundamentals-snapshot 的 beat rate / avg surprise / 30d revisions
  7. 濾網：5 日漲幅 >30% 排除（凸性已消耗）、ATM OI、bid-ask spread

輸出 markdown 表 + （--json）機器可讀完整欄位。判斷層（thesis、口數、掛單）留給 skill。

用法：
  python3 tools/event_vol_scan.py --tickers TSLA,GOOGL,MYRG --days 14
  python3 tools/event_vol_scan.py --tickers MU --extra-events SPY:2026-07-15:CPI,QQQ:2026-07-29:FOMC \
      --account-value 264592 --json briefing-out/cache/event-vol-scan.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    print("ERROR: 本機 python 缺 yfinance（pip install yfinance）", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "briefing-out" / "cache"
EODHD_BASE = "https://eodhd.com/api"

# ── 判準常數（源 feedback/options-leaps-playbook.md + tiered-profit-taking）──
RUNUP_EXCLUDE = 0.30      # 5 日漲幅 > 30% → 凸性已消耗，排除
RUNUP_WARN = 0.15         # 5 日漲幅 > 15% → 警示
VRP_CHEAP = 0.85          # 隱含/歷史 < 0.85 → 雙買有 edge
VRP_RICH = 1.20           # 隱含/歷史 > 1.20 → IV crush 風險
MIN_OI = 500              # ATM 總 OI 門檻
MAX_SPREAD_PCT = 0.15     # bid-ask/mid 上限
LOTTERY_BUDGET_PCT = 0.02 # 樂透總預算 ≤ 2% 帳戶（Quarter-Kelly 上限）
CALL_BEAT_MIN = 87.5      # buy call 方向票需 beat rate ≥ 7/8
CALL_SURPRISE_MIN = 5.0   # 且 avg surprise ≥ +5%
MIN_HIST_MOVE = 0.04      # 雙買至少要有 4% 的歷史中位移動才值得付 premium


def _load_env_token() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("EODHD_API_TOKEN="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("EODHD_API_TOKEN", "")


def _load_cache(name: str) -> dict:
    p = CACHE_DIR / name
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def next_earnings(ticker: str, today: date, horizon: int, dates_cache: dict, token: str) -> tuple[str, str] | None:
    """回 (date, timing)；cache 優先，miss 再打 EODHD calendar。不在窗內回 None。"""
    ent = (dates_cache.get("tickers") or {}).get(ticker)
    if ent and ent.get("next_date"):
        d = ent["next_date"]
        try:
            dd = date.fromisoformat(d)
            if today <= dd <= today + timedelta(days=horizon):
                return d, (ent.get("timing") or "AMC")
            return None  # cache 明確說事件在窗外
        except ValueError:
            pass
    if not token:
        return None
    try:  # EODHD fallback（cache 沒這檔才打）
        r = requests.get(
            f"{EODHD_BASE}/calendar/earnings",
            params={"api_token": token, "fmt": "json", "symbols": f"{ticker}.US",
                    "from": today.isoformat(), "to": (today + timedelta(days=horizon)).isoformat()},
            timeout=20,
        )
        r.raise_for_status()
        rows = (r.json() or {}).get("earnings", [])
        if rows:
            row = sorted(rows, key=lambda x: x.get("report_date", "9999"))[0]
            return row["report_date"], ("BMO" if str(row.get("before_after_market", "")).startswith("Before") else "AMC")
    except Exception:
        pass
    return None


def _mid(bid: float, ask: float, last: float) -> float | None:
    """mid 價；bid/ask 缺用 lastPrice 補，全缺回 None。"""
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2
    return last if last and last > 0 else None


def _nearest_row(df, target: float):
    if df is None or len(df) == 0:
        return None
    idx = (df["strike"] - target).abs().idxmin()
    return df.loc[idx]


def hist_earnings_moves(closes, last_8q: list[dict]) -> list[float]:
    """過去 8 季財報的 1 日實際 |移動|。AMC: close(D+1)/close(D)；BMO: close(D)/close(D-1)。"""
    moves = []
    dates = list(closes.index.date)
    for q in last_8q or []:
        try:
            d = date.fromisoformat(q["date"])
        except Exception:
            continue
        after = [i for i, x in enumerate(dates) if x >= d]
        if not after:
            continue
        i = after[0]  # 財報日（或其後第一個交易日）
        try:
            if (q.get("timing") or "AMC") == "BMO":
                mv = closes.iloc[i] / closes.iloc[i - 1] - 1
            else:  # AMC → 反應在次一交易日
                mv = closes.iloc[i + 1] / closes.iloc[i] - 1
            moves.append(abs(float(mv)))
        except Exception:
            continue
    return moves


def scan_one(ticker: str, event_date: str, timing: str, label: str,
             hist_cache: dict, fund_cache: dict) -> dict:
    """單一 ticker × 事件 → 全欄位 dict（機械計算，不做投資判斷之外的裁決）。"""
    out: dict = {"ticker": ticker, "event": label, "event_date": event_date, "timing": timing}
    tk = yf.Ticker(ticker)

    hist = tk.history(period="2y", auto_adjust=True)
    if hist is None or len(hist) < 30:
        out["error"] = "價格歷史不足"
        return out
    closes = hist["Close"]
    spot = float(closes.iloc[-1])
    out["spot"] = round(spot, 2)
    out["runup_5d"] = round(float(closes.iloc[-1] / closes.iloc[-6] - 1), 4) if len(closes) >= 6 else None

    # 事件後第一個到期
    eff = date.fromisoformat(event_date) + timedelta(days=1 if timing != "BMO" else 0)
    expiries = [e for e in (tk.options or []) if date.fromisoformat(e) >= eff]
    if not expiries:
        out["error"] = "無事件後到期的期權鏈"
        return out
    expiry = expiries[0]
    out["expiry"] = expiry
    out["dte"] = (date.fromisoformat(expiry) - date.today()).days

    chain = tk.option_chain(expiry)
    calls, puts = chain.calls, chain.puts
    c_atm, p_atm = _nearest_row(calls, spot), _nearest_row(puts, spot)
    if c_atm is None or p_atm is None:
        out["error"] = "鏈上無 ATM 報價"
        return out
    c_mid = _mid(float(c_atm.get("bid") or 0), float(c_atm.get("ask") or 0), float(c_atm.get("lastPrice") or 0))
    p_mid = _mid(float(p_atm.get("bid") or 0), float(p_atm.get("ask") or 0), float(p_atm.get("lastPrice") or 0))
    if not c_mid or not p_mid:
        out["error"] = "ATM 無有效報價"
        return out

    straddle = c_mid + p_mid
    implied_move = straddle / spot
    atm_oi = int((c_atm.get("openInterest") or 0) + (p_atm.get("openInterest") or 0))
    spread_pct = None
    if c_atm.get("bid") and c_atm.get("ask") and c_mid:
        spread_pct = round(float(c_atm["ask"] - c_atm["bid"]) / c_mid, 4)
    out.update({
        "atm_strike": float(c_atm["strike"]),
        "straddle_cost": round(straddle, 2),
        "implied_move": round(implied_move, 4),
        "atm_oi": atm_oi,
        "atm_call_spread_pct": spread_pct,
        "atm_iv": round(float(c_atm.get("impliedVolatility") or 0), 4),
    })

    # 末日 OTM call 候選（1× 隱含移動處的 strike）
    c_otm = _nearest_row(calls, spot * (1 + implied_move))
    if c_otm is not None:
        otm_mid = _mid(float(c_otm.get("bid") or 0), float(c_otm.get("ask") or 0), float(c_otm.get("lastPrice") or 0))
        out["otm_call"] = {
            "strike": float(c_otm["strike"]),
            "mid": round(otm_mid, 2) if otm_mid else None,
            "oi": int(c_otm.get("openInterest") or 0),
            "iv": round(float(c_otm.get("impliedVolatility") or 0), 4),
        }

    # 歷史財報移動基準（僅財報事件有）
    q8 = ((hist_cache.get("tickers") or {}).get(ticker) or {}).get("last_8q")
    moves = hist_earnings_moves(closes, q8) if q8 else []
    if moves:
        moves_sorted = sorted(moves)
        med = moves_sorted[len(moves) // 2] if len(moves) % 2 else (moves_sorted[len(moves)//2 - 1] + moves_sorted[len(moves)//2]) / 2
        out["hist_moves_n"] = len(moves)
        out["hist_move_avg"] = round(sum(moves) / len(moves), 4)
        out["hist_move_med"] = round(med, 4)
        out["vrp_hist"] = round(implied_move / med, 2) if med > 0 else None

    # 20d 實現波動 ×√T 次級基準（ETF/新股用）
    rets = closes.pct_change().dropna()
    if len(rets) >= 21:
        rv20 = float(rets.iloc[-20:].std())
        out["rv_move_to_expiry"] = round(rv20 * math.sqrt(max(out["dte"], 1) * 5 / 7), 4)
        out["vrp_rv"] = round(implied_move / out["rv_move_to_expiry"], 2) if out["rv_move_to_expiry"] else None

    # 方向 skew（財報事件才有意義）
    fund = (fund_cache.get("tickers") or {}).get(ticker) or {}
    br = fund.get("base_rate") or {}
    cf = ((fund.get("snapshot") or {}).get("forward_estimates") or {}).get("curr_fy") or {}
    out["beat_pct"] = br.get("beat_pct")
    out["avg_surprise_pct"] = br.get("avg_surprise_pct")
    out["surprise_unreliable"] = br.get("avg_surprise_unreliable")
    out["rev_up_30d"] = cf.get("revisions_up_30d")
    out["rev_dn_30d"] = cf.get("revisions_down_30d")

    # ── 機械裁決 ──────────────────────────────────────────────
    flags = []
    if out["runup_5d"] is not None and out["runup_5d"] > RUNUP_EXCLUDE:
        out["verdict"] = "EXCLUDE"
        flags.append(f"5日已漲 {out['runup_5d']:+.0%} 凸性消耗")
    elif atm_oi < MIN_OI or (spread_pct is not None and spread_pct > MAX_SPREAD_PCT):
        out["verdict"] = "EXCLUDE"
        flags.append(f"流動性不足(OI {atm_oi}/spread {spread_pct})")
    else:
        vrp = out.get("vrp_hist")
        beat = out.get("beat_pct") or 0
        up, dn = out.get("rev_up_30d") or 0, out.get("rev_dn_30d") or 0
        surprise_ok = (out.get("avg_surprise_pct") or 0) >= CALL_SURPRISE_MIN and not out.get("surprise_unreliable")
        directional = beat >= CALL_BEAT_MIN and up >= 5 * max(dn, 1) and surprise_ok
        if directional and (vrp is None or vrp <= VRP_RICH):
            out["verdict"] = "BUY_CALL"
            flags.append(f"beat {beat:.0f}% + rev {up:.0f}:{dn:.0f} 方向凸性")
        elif vrp is not None and vrp < VRP_CHEAP and (out.get("hist_move_med") or 0) >= MIN_HIST_MOVE:
            out["verdict"] = "STRADDLE"
            flags.append(f"隱含 {implied_move:.1%} < 歷史中位 {out['hist_move_med']:.1%}（VRP {vrp}）")
        elif vrp is not None and vrp > VRP_RICH:
            out["verdict"] = "SKIP_RICH"
            flags.append(f"隱含/歷史 {vrp} 過貴，IV crush 風險")
        elif vrp is None and (out.get("vrp_rv") or 99) < VRP_CHEAP:
            out["verdict"] = "STRADDLE_RV"
            flags.append(f"無財報基準；隱含 < 實現波動基準（VRP_rv {out.get('vrp_rv')}）")
        else:
            out["verdict"] = "WATCH"
            flags.append("無明確 edge")
        if out["runup_5d"] is not None and out["runup_5d"] > RUNUP_WARN:
            flags.append(f"⚠️5日已漲 {out['runup_5d']:+.0%}")
    out["flags"] = flags
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", required=True, help="逗號分隔，如 TSLA,GOOGL,MYRG")
    ap.add_argument("--days", type=int, default=14, help="事件窗（天，預設 14）")
    ap.add_argument("--extra-events", default="", help="非財報事件：TICKER:YYYY-MM-DD:LABEL,...（如 SPY:2026-07-15:CPI）")
    ap.add_argument("--account-value", type=float, default=None, help="帳戶總值 → 算 2%% 樂透預算")
    ap.add_argument("--json", default=None, help="輸出完整 JSON 到此路徑")
    args = ap.parse_args()

    today = date.today()
    token = _load_env_token()
    dates_cache = _load_cache("earnings-dates.json")
    hist_cache = _load_cache("earnings-history.json")
    fund_cache = _load_cache("fundamentals-snapshot.json")

    jobs: list[tuple[str, str, str, str]] = []  # (ticker, date, timing, label)
    for t in [x.strip().upper() for x in args.tickers.split(",") if x.strip()]:
        ev = next_earnings(t, today, args.days, dates_cache, token)
        if ev:
            jobs.append((t, ev[0], ev[1], "財報"))
    for spec in [x.strip() for x in args.extra_events.split(",") if x.strip()]:
        try:
            t, d, label = spec.split(":", 2)
            if today <= date.fromisoformat(d) <= today + timedelta(days=args.days):
                jobs.append((t.upper(), d, "BMO", label))
        except ValueError:
            print(f"WARN: --extra-events 格式錯誤，略過 {spec}", file=sys.stderr)

    results = [scan_one(t, d, tm, lb, hist_cache, fund_cache) for t, d, tm, lb in jobs]

    # ── markdown 輸出 ──
    budget = args.account_value * LOTTERY_BUDGET_PCT if args.account_value else None
    print(f"# 事件前買方掃描（{today.isoformat()}，窗 {args.days} 天，事件 {len(results)} 個）")
    if budget:
        print(f"樂透總預算上限：${budget:,.0f}（帳戶 {LOTTERY_BUDGET_PCT:.0%}，Quarter-Kelly）")
    print()
    print("| Ticker | 事件(日期/前後) | 現價 | 到期(DTE) | 隱含移動 | 歷史中位(8Q) | VRP | beat/rev | 末日call(1IM) | straddle成本 | 裁決 | 備註 |")
    print("|--------|----------------|-----:|-----------|--------:|------------:|----:|---------|--------------|------------:|------|------|")
    for r in sorted(results, key=lambda x: (x.get("event_date") or "9999")):
        if r.get("error"):
            print(f"| {r['ticker']} | {r['event']} {r['event_date']} | — | — | — | — | — | — | — | — | ERROR | {r['error']} |")
            continue
        hist_med = f"{r['hist_move_med']:.1%}({r.get('hist_moves_n')}Q)" if r.get("hist_move_med") else "—"
        vrp = r.get("vrp_hist") if r.get("vrp_hist") is not None else (f"rv:{r.get('vrp_rv')}" if r.get("vrp_rv") else "—")
        beat = f"{r.get('beat_pct') or '—'}%/{int(r.get('rev_up_30d') or 0)}:{int(r.get('rev_dn_30d') or 0)}"
        otm = r.get("otm_call") or {}
        otm_s = f"${otm.get('strike')}C @{otm.get('mid')} (OI {otm.get('oi')})" if otm else "—"
        print(f"| {r['ticker']} | {r['event']} {r['event_date']} {r['timing']} | {r['spot']} | {r['expiry']}({r['dte']}d) "
              f"| {r['implied_move']:.1%} | {hist_med} | {vrp} | {beat} | {otm_s} "
              f"| ${r['straddle_cost']} | **{r['verdict']}** | {'；'.join(r['flags'])} |")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"generated_at": datetime.now().isoformat(), "window_days": args.days,
             "lottery_budget": budget, "results": results}, ensure_ascii=False, indent=2))
        print(f"\nJSON → {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
