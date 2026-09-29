#!/usr/bin/env python3
"""backtest_r23.py — R23 自峰回撤線 v1 vs v2（washout 確認）回測（2026-09-29 /trade-review 補做）

為什麼放 tools/ 而不是 scratchpad：2026-09-02 建線時的 `scratchpad/backtest_peak_dd.py` 已隨 session 消失，
9/29 想驗 v2 只能重寫。規則的回測腳本是規則的一部分，要跟規則一起活著。

方法（與 9/2 原回測同一套骨架，數字可對照：原 14 檔 / 20 觸發 / 省 +$4,817 / whipsaw −$309）：
  - 認列桶宇宙 = 現任認列桶 + 2026 年出場過的認列桶名字（信念桶 / sleeve / 樂透 / 現金停泊不套 R23，排除）
  - 部位由 research/trade-ledger.jsonl 重建（split 調整；帳本早於 2023-07 的 lots 缺 → 股數為負者視為無部位，屬近似）
  - 成交凍結於 --freeze（預設 2026-09-01，即 R23 上線前一日）：之後的真實 R23 減碼不進部位，由模擬自己開火
  - arm：自 since 日起收盤峰值 ≥ 均價 × 1.20；觸發：收盤 ≤ 峰 × 0.80 → 次日開盤價賣 1/3；賣後 since = 賣出日（峰值重算）
  - v2：觸發日基準（SMH / SPY，同 trade_ledger 分表）單日 ≤ −2% → 不開火；之後第一個基準 > −2% 且收盤仍 ≤ 線的日子才賣
  - 計分：每段減碼 30 個日曆日後，(賣價 − 30d 價) × 股數 → 正 = 省下的回撤，負 = whipsaw（與 RULES-LEDGER R23 計分口徑一致）

Usage:
  python3 tools/backtest_r23.py [--start 2026-01-02] [--end 2026-09-28] [--freeze 2026-09-01] [--bench-drop -0.02] [--json]
"""
import argparse, json, sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from trade_ledger import SEMI_AI, load_fills, split_adjust_qty  # noqa: E402

CURRENT_HARVEST = ["AMD", "ANET", "CLS", "CRM", "DDOG", "DIOD", "HWM", "LITE", "LRCX", "NET", "PWR", "SNPS", "TWLO"]
EXITED_HARVEST_2026 = ["MYRG", "CRDO", "ONTO", "STRL", "COHR", "ON", "ARM", "MRVL"]
ARM, LINE = 0.20, 0.20


def bench_for(sym):
    return "SMH" if sym.upper() in SEMI_AI else "SPY"


def rebuild(fills, universe, freeze):
    """每檔每日 (qty, avg_cost) 變動點：date → (qty, cost)。"""
    events = defaultdict(list)
    for f in sorted(fills, key=lambda r: (r["date"], r.get("exec_time") or "")):
        if f["is_option"] or f["symbol"] not in universe or f["date"] > freeze:
            continue
        q = split_adjust_qty(f["symbol"], f["date"], float(f["qty"]))
        events[f["symbol"]].append((f["date"], f["side"], q, float(f.get("split_adj_price") or f["price"])))
    return events


def load_prices(symbols, start, end):
    import yfinance as yf
    px = yf.download(sorted(set(symbols)), start=(date.fromisoformat(start) - timedelta(days=120)).isoformat(),
                     end=(date.fromisoformat(end) + timedelta(days=45)).isoformat(), auto_adjust=False, progress=False)
    return px["Close"], px["Open"]


def simulate(sym, ev, close, opn, bench_close, start, end, washout, bench_drop):
    """回傳該檔的減碳段列表。"""
    days = [d for d in close.index if start <= d.date().isoformat() <= end and not (close[sym][d] != close[sym][d])]
    if not days:
        return []
    evi = 0
    qty = cost_total = 0.0
    # 先套用 start 前的成交
    while evi < len(ev) and ev[evi][0] < start:
        _, side, q, p = ev[evi]
        if side == "BOUGHT":
            qty, cost_total = qty + q, cost_total + q * p
        else:
            avg = cost_total / qty if qty else 0
            qty, cost_total = qty - q, cost_total - q * avg
        evi += 1
    since = start
    trims, pending = [], False
    idx = list(close.index)
    for d in days:
        ds = d.date().isoformat()
        while evi < len(ev) and ev[evi][0] <= ds:
            _, side, q, p = ev[evi]
            if side == "BOUGHT":
                if qty <= 0:            # 帳本負股數 = 缺舊 lots；新建倉時重置
                    qty, cost_total, since = 0.0, 0.0, ds
                qty, cost_total = qty + q, cost_total + q * p
            else:
                avg = cost_total / qty if qty > 0 else 0
                qty, cost_total = qty - q, cost_total - q * avg
            evi += 1
        if qty <= 0:
            since, pending = ds, False
            continue
        avg = cost_total / qty
        window = close[sym][(close.index >= since) & (close.index <= d)].dropna()
        if window.empty:
            continue
        peak = float(window.max())
        c = float(close[sym][d])
        armed = peak >= avg * (1 + ARM)
        breached = armed and c <= peak * (1 - LINE)
        if not breached:
            pending = False
            continue
        b = bench_for(sym)
        bi = idx.index(d)
        bmove = float(bench_close[b][d] / bench_close[b][idx[bi - 1]] - 1) if bi > 0 else 0.0
        if washout and bmove <= bench_drop:
            pending = True      # 等下一個非 washout 收盤
            continue
        # 開火：次日開盤賣 1/3
        if bi + 1 >= len(idx):
            break
        nd = idx[bi + 1]
        sell_px = float(opn[sym][nd]) if opn[sym][nd] == opn[sym][nd] else float(close[sym][nd])
        q_sell = qty / 3
        d30 = nd + timedelta(days=30)
        after = close[sym][close.index >= d30].dropna()
        p30 = float(after.iloc[0]) if not after.empty else None
        trims.append({"symbol": sym, "trigger": ds, "sell_date": nd.date().isoformat(), "bench": b, "bench_move": round(bmove, 4),
                      "peak": round(peak, 2), "close": round(c, 2), "sell_px": round(sell_px, 2), "qty": round(q_sell, 2),
                      "p30": round(p30, 2) if p30 else None,
                      "saved_usd": round(q_sell * (sell_px - p30), 0) if p30 else None,
                      "delayed_from": None})
        qty, cost_total = qty - q_sell, cost_total - q_sell * avg
        since, pending = nd.date().isoformat(), False
    return trims


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-02"); ap.add_argument("--end", default="2026-09-28")
    ap.add_argument("--freeze", default="2026-09-01"); ap.add_argument("--bench-drop", type=float, default=-0.02)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    universe = CURRENT_HARVEST + EXITED_HARVEST_2026
    ev = rebuild(load_fills(), set(universe), a.freeze)
    close, opn = load_prices(universe + ["SMH", "SPY"], a.start, a.end)
    out = {}
    for label, washout in (("v1", False), ("v2", True)):
        trims = []
        for sym in universe:
            if sym not in ev or sym not in close.columns:
                continue
            trims += simulate(sym, ev[sym], close, opn, close, a.start, a.end, washout, a.bench_drop)
        scored = [t for t in trims if t["saved_usd"] is not None]
        out[label] = {"trims": len(trims), "scored": len(scored),
                      "saved_usd": round(sum(t["saved_usd"] for t in scored if t["saved_usd"] > 0)),
                      "whipsaw_usd": round(sum(t["saved_usd"] for t in scored if t["saved_usd"] < 0)),
                      "net_usd": round(sum(t["saved_usd"] for t in scored)),
                      "hit": sum(1 for t in scored if t["saved_usd"] > 0),
                      "washout_day_trims": sum(1 for t in trims if t["bench_move"] <= a.bench_drop),
                      "detail": trims}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1)); return
    for label in ("v1", "v2"):
        r = out[label]
        print(f"\n{label}: 觸發 {r['trims']} 段（可計分 {r['scored']}，命中 {r['hit']}）｜省 +${r['saved_usd']:,} / whipsaw ${r['whipsaw_usd']:,} / 淨 ${r['net_usd']:,}"
              + (f"｜其中 washout 日開火 {r['washout_day_trims']} 段" if label == "v1" else ""))
        for t in r["detail"]:
            flag = " ⚡washout" if t["bench_move"] <= a.bench_drop else ""
            print(f"  {t['symbol']:5} 觸發 {t['trigger']} 賣 {t['sell_date']} @{t['sell_px']:>8} ×{t['qty']:>6}  {t['bench']} {t['bench_move']:+.1%}{flag}  30d {t['p30']}  → {t['saved_usd']}")
    v1, v2 = out["v1"], out["v2"]
    print(f"\nΔ(v2 − v1) 淨 ${v2['net_usd'] - v1['net_usd']:+,}｜段數 {v2['trims'] - v1['trims']:+d}")


if __name__ == "__main__":
    main()
