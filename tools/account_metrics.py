#!/usr/bin/env python3
"""
account_metrics.py — 帳戶績效四指標：MDD / Sharpe / Profit Factor / CAGR。

資料現實：券商 API 不給每日淨值曲線 → 淨值標記從 journal/ 與 briefing-out/
的每日快照刮取（系統 2026-06-01 起才有記錄），profit factor 從
research/trade-ledger.jsonl 的成交 FIFO 配對（帳回溯至 2023-07，成本基礎完整）。

Usage:
  python3 tools/account_metrics.py scan                # 重掃標記 → research/equity-marks.json
  python3 tools/account_metrics.py add DATE VALUE [--note "券商對帳單"]   # 手動錨（如 1/1 淨值）
  python3 tools/account_metrics.py report [--live V] [--pf-from 2026-01-01]

誠實標示：
- MDD 基於離散標記（低估真實 MDD，盤中低點與缺日不在內）
- 年化波動只用相鄰 ≤3 日的標記段（2026-10-23 修：長空窗攤進分母曾把 17.3% 算成實際 33–39% 的一半）
- 標記不足一年時 CAGR/Sharpe 為年化外推，僅供方向參考
- 「組合市值」類標記（不含現金）同檔找得到現金才併入，否則剔除
"""

import argparse
import json
import math
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trade_ledger import split_adjust, split_adjust_qty  # noqa: E402 — split 處理共用

MARKS_FILE = ROOT / "research" / "equity-marks.json"
LEDGER_FILE = ROOT / "research" / "trade-ledger.jsonl"
OUT_FILE = ROOT / "briefing-out" / "cache" / "account-metrics.json"
MACRO_FILE = ROOT / "briefing-out" / "cache" / "macro-snapshot.json"

# 波動估計參數：相鄰標記最多隔幾個日曆日才算連續段（3 = 容許週末 Fri→Mon）；至少幾個交易日才報波動
VOL_MAX_GAP_DAYS = 3
VOL_MIN_TRADING_DAYS = 10


def _weekdays_between(d0: date, d1: date) -> int:
    """(d0, d1] 之間的平日數，當作交易日數近似（標記只落在交易日，假日誤差可忽略）。"""
    n, d = 0, d0
    while d < d1:
        d = date.fromordinal(d.toordinal() + 1)
        if d.weekday() < 5:
            n += 1
    return n


# 已知髒標記（掃描時自動剔除，附理由）
EXCLUDE = {
    "2026-06-03": "自述日變動 +0.18% 與前日標記 +6.4% 矛盾；該日 briefing 在破損工作區執行",
}

RE_TOTAL = re.compile(r"(?:帳戶|組合)總值[^0-9$]*\$\s*([0-9,]+(?:\.[0-9]+)?[KkMm]?)")
RE_TOTAL2 = re.compile(r"(?:^|\|)\s*(?:[-*]\s*)?總值\s*\**\$\s*([0-9,]+(?:\.[0-9]+)?[KkMm]?)", re.M)
RE_PORT = re.compile(r"組合市值[^0-9$]*\$\s*([0-9,]+(?:\.[0-9]+)?[KkMm]?)")
RE_CASH = re.compile(r"現金[^0-9$%]*\$\s*([0-9,]+(?:\.[0-9]+)?)")


def _num(s):
    # 「$263.4K」簡寫（2026-09-30：9/29 briefing 寫 K 被讀成 $263.4 → 假熔斷）
    mult = {"k": 1e3, "m": 1e6}.get(s[-1].lower(), 1)
    return float(s.rstrip("KkMm").replace(",", "")) * mult


def scan_file(path: Path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    m = RE_TOTAL.search(text) or RE_TOTAL2.search(text)
    if m:
        return {"value": _num(m.group(1)), "kind": "total"}
    # 組合市值（不含現金）不可與帳戶總值混列；現金正則在長文件裡易誤抓 →
    # 一律標 portfolio_only，不進曲線（2026-07-29 修：7/10 曾因誤合成多出 $39k）
    mp = RE_PORT.search(text)
    if mp:
        return {"value": _num(mp.group(1)), "kind": "portfolio_only"}
    return None


def cmd_scan():
    prev = json.loads(MARKS_FILE.read_text()) if MARKS_FILE.exists() else {}
    manual = prev.get("manual", [])
    marks = {}
    sources = [(ROOT / "journal", r"(\d{4}-\d{2}-\d{2})\.md$", "journal"),
               (ROOT / "briefing-out", r"(\d{4}-\d{2}-\d{2})-full\.md$", "briefing")]
    # 封存的舊 briefing（prune_reports.py 搬到 briefing-out/archive/YYYY-MM/，2026-11-06）也要掃，
    # 否則 scan 每次從頭重建時，journal 沒寫淨值的舊日期會整筆消失
    arch = ROOT / "briefing-out" / "archive"
    if arch.exists():
        sources += [(d, r"(\d{4}-\d{2}-\d{2})-full\.md$", "briefing") for d in sorted(arch.iterdir()) if d.is_dir()]
    for dirpath, pat, src in sources:
        if not dirpath.exists():
            continue
        for f in sorted(dirpath.iterdir()):
            m = re.search(pat, f.name)
            if not m:
                continue
            hit = scan_file(f)
            if not hit:
                continue
            d = m.group(1)
            # journal 優先於 briefing；total 優先於 portfolio_only
            if d in marks and (marks[d]["source"] == "journal" or
                               (marks[d]["kind"] != "portfolio_only" and hit["kind"] == "portfolio_only")):
                continue
            marks[d] = {"date": d, "source": src, **hit,
                        "excluded": d in EXCLUDE,
                        **({"exclude_reason": EXCLUDE[d]} if d in EXCLUDE else {})}
    out = {"scanned_at": datetime.now().isoformat(timespec="seconds"),
           "marks": sorted(marks.values(), key=lambda x: x["date"]),
           "manual": manual}
    MARKS_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    usable = [m for m in out["marks"] if not m["excluded"] and m["kind"] != "portfolio_only"]
    print(f"scanned {len(out['marks'])} marks ({len(usable)} usable, "
          f"{len(manual)} manual), range "
          f"{out['marks'][0]['date']} → {out['marks'][-1]['date']}")
    return 0


def cmd_add(d: str, value: float, note: str):
    datetime.strptime(d, "%Y-%m-%d")
    data = json.loads(MARKS_FILE.read_text()) if MARKS_FILE.exists() else {"marks": [], "manual": []}
    data.setdefault("manual", []).append(
        {"date": d, "value": value, "kind": "total", "source": "manual", "note": note})
    MARKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"added manual mark {d} = {value:,.2f}")
    return 0


def load_series(live: float | None):
    data = json.loads(MARKS_FILE.read_text())
    pts = {}
    for m in data.get("marks", []):
        if m.get("excluded") or m.get("kind") == "portfolio_only":
            continue
        pts[m["date"]] = m["value"]
    for m in data.get("manual", []):
        pts[m["date"]] = m["value"]  # 手動錨覆蓋同日刮取值
    if live is not None:
        pts[date.today().isoformat()] = live
    return sorted(pts.items())


def equity_metrics(series):
    if len(series) < 3:
        return {"error": f"標記不足（{len(series)} 點），無法計算"}
    dates = [datetime.strptime(d, "%Y-%m-%d").date() for d, _ in series]
    vals = [v for _, v in series]
    days = (dates[-1] - dates[0]).days or 1
    total_ret = vals[-1] / vals[0] - 1
    cagr = (vals[-1] / vals[0]) ** (365.0 / days) - 1

    peak, peak_d, mdd, mdd_from, mdd_to = vals[0], dates[0], 0.0, None, None
    for dt, v in zip(dates, vals):
        if v > peak:
            peak, peak_d = v, dt
        dd = v / peak - 1
        if dd < mdd:
            mdd, mdd_from, mdd_to = dd, peak_d, dt
    current_dd = vals[-1] / peak - 1  # 供 R15 回檔熔斷（−10% 閘）判定

    # 波動估計（2026-10-23 修）：只用相鄰 ≤ VOL_MAX_GAP_DAYS 個日曆日的標記段（含週末 Fri→Mon），
    # 以交易日數攤分再乘 252 年化。長空窗不進估計——舊版把 1/1 手動錨 → 6/1 首個刮取標記之間
    # 151 天的單一段攤進分母，等於把五個月空窗當零波動，年化波動算成 17.3%，重算為 33–39%，
    # 且與同期 β_SPY 2.6 在數學上互斥（隱含相關 >1）。Sharpe 改用 CAGR（整段幾何年化）減 rf。
    seg = []  # (log return, 交易日數)
    for i in range(1, len(series)):
        gap = (dates[i] - dates[i - 1]).days
        if gap <= 0 or gap > VOL_MAX_GAP_DAYS:
            continue
        td = _weekdays_between(dates[i - 1], dates[i])
        if td <= 0:
            continue
        seg.append((math.log(vals[i] / vals[i - 1]), td))
    total_td = sum(td for _, td in seg)
    rf = 0.04
    try:
        rf = json.loads(MACRO_FILE.read_text())["series"]["fed_funds"]["value"] / 100
    except Exception:
        pass
    if total_td >= VOL_MIN_TRADING_DAYS:
        mean_td = sum(lr for lr, _ in seg) / total_td
        var_d = sum((lr - mean_td * td) ** 2 / td for lr, td in seg) / total_td
        vol_ann = math.sqrt(var_d * 252)
        sharpe = (cagr - rf) / vol_ann if vol_ann else None
    else:
        vol_ann, sharpe = None, None

    # Sharpe 標準誤（2026-11-10，Lo 2002 的 IID 近似）：年化 SE² = (1 + SR_ann²/504) ÷ 年數。
    # 年數取 CAGR 的整段視窗；短窗下 SE≈1/√年數，半年帳的 Sharpe 與 0 或 2 都分不開——照實印出來。
    # 日報酬一階自相關只在「相鄰兩段都是單日」的配對 ≥30 組時才報（標記不等距時估不準），僅顯示不修正。
    years = days / 365.0
    sharpe_se = math.sqrt((1 + (sharpe or 0) ** 2 / 504) / years) if sharpe is not None and years > 0 else None
    rho1 = None
    one = [lr for lr, td in seg if td == 1]
    pairs = [(seg[i - 1][0], seg[i][0]) for i in range(1, len(seg)) if seg[i - 1][1] == 1 and seg[i][1] == 1]
    if len(pairs) >= 30 and len(one) >= 30:
        mx = sum(a for a, _ in pairs) / len(pairs); my = sum(b for _, b in pairs) / len(pairs)
        cov = sum((a - mx) * (b - my) for a, b in pairs)
        den = math.sqrt(sum((a - mx) ** 2 for a, _ in pairs) * sum((b - my) ** 2 for _, b in pairs))
        rho1 = cov / den if den else None

    return {
        "window": {"from": series[0][0], "to": series[-1][0], "days": days,
                   "n_marks": len(series)},
        "start_value": vals[0], "end_value": vals[-1],
        "total_return_pct": round(total_ret * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "mdd_pct": round(mdd * 100, 2),
        "mdd_from": mdd_from.isoformat() if mdd_from else None,
        "mdd_to": mdd_to.isoformat() if mdd_to else None,
        "current_drawdown_pct": round(current_dd * 100, 2),
        "peak_value": peak, "peak_date": peak_d.isoformat(),
        "circuit_breaker_active": current_dd <= -0.10,
        "vol_ann_pct": round(vol_ann * 100, 2) if vol_ann is not None else None,
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "sharpe_se": round(sharpe_se, 2) if sharpe_se is not None else None,
        "sharpe_ci95": [round(sharpe - 1.96 * sharpe_se, 2), round(sharpe + 1.96 * sharpe_se, 2)] if sharpe_se is not None else None,
        "sharpe_distinguishable_from_zero": (abs(sharpe) > 1.96 * sharpe_se) if sharpe_se is not None else None,
        "daily_autocorr_lag1": round(rho1, 2) if rho1 is not None else None,
        "rf_used_pct": round(rf * 100, 2),
        "vol_method": {"max_gap_days": VOL_MAX_GAP_DAYS, "segments_used": len(seg),
                       "trading_days_used": total_td, "sharpe_numerator": "cagr - rf"},
    }


def profit_factor(pf_from: str):
    """FIFO 配對已實現損益（含選擇權；amount 為含費用真實現金流）。"""
    fills = [json.loads(l) for l in LEDGER_FILE.read_text().splitlines() if l.strip()]
    fills.sort(key=lambda f: (f.get("date", ""), f.get("exec_time") or ""))
    lots = {}  # symbol -> list of [qty_adj, amount_per_unit]
    wins = losses = 0.0
    n_win = n_loss = n_unmatched = 0
    for f in fills:
        sym, d = f["symbol"], f["date"]
        q = abs(split_adjust_qty(f.get("underlying") or sym, d, f["qty"]))
        if q == 0:
            continue
        amt = f.get("amount") or 0.0
        if f["side"] == "BOUGHT":
            lots.setdefault(sym, []).append([q, amt / q])  # amt<0
        else:  # SOLD
            remaining, realized, matched = q, 0.0, 0.0
            queue = lots.get(sym, [])
            while remaining > 1e-9 and queue:
                lot = queue[0]
                take = min(lot[0], remaining)
                realized += take * lot[1]          # 負的成本
                lot[0] -= take
                remaining -= take
                matched += take
                if lot[0] <= 1e-9:
                    queue.pop(0)
            if matched <= 1e-9:
                n_unmatched += 1
                continue
            realized += amt * (matched / q)        # 賣出現金流按配對比例
            if d >= pf_from:
                if realized >= 0:
                    wins += realized
                    n_win += 1
                else:
                    losses += -realized
                    n_loss += 1
    return {
        "from": pf_from,
        "gross_profit": round(wins, 2), "gross_loss": round(losses, 2),
        "profit_factor": round(wins / losses, 2) if losses else None,
        "closed_wins": n_win, "closed_losses": n_loss,
        "win_rate_pct": round(100 * n_win / (n_win + n_loss), 1) if n_win + n_loss else None,
        "unmatched_sells_skipped": n_unmatched,
    }


def position_stats(pf_from: str):
    """以「部位」為單位的打擊率 × 賠率（2026-11-10）。

    profit_factor() 把每一筆賣出當一次輸贏——梯級停利把一個部位拆成很多小「贏」，打擊率被灌水。
    這裡把同一標的「從 0 股買到再回到 0 股」算一個部位（尚未清完但已有賣出的也算，另計 open），
    只計 pf_from 之後賣出的已實現。回答：是「常贏但贏得小」（負偏態）還是「少贏但贏得大」。
    """
    fills = [json.loads(l) for l in LEDGER_FILE.read_text().splitlines() if l.strip()]
    fills.sort(key=lambda f: (f.get("date", ""), f.get("exec_time") or ""))
    lots, epi, done = {}, {}, []   # epi[sym] = {"pnl":, "cost":, "sells":, "first":}
    for f in fills:
        sym, d = f["symbol"], f["date"]
        q = abs(split_adjust_qty(f.get("underlying") or sym, d, f["qty"]))
        if q == 0:
            continue
        amt = f.get("amount") or 0.0
        if f["side"] == "BOUGHT":
            lots.setdefault(sym, []).append([q, amt / q])
            epi.setdefault(sym, {"pnl": 0.0, "cost": 0.0, "sells": 0, "first": d, "is_option": bool(f.get("is_option"))})
            continue
        remaining, cost, matched, queue = q, 0.0, 0.0, lots.get(sym, [])
        while remaining > 1e-9 and queue:
            lot = queue[0]; take = min(lot[0], remaining)
            cost += take * -lot[1]; lot[0] -= take; remaining -= take; matched += take
            if lot[0] <= 1e-9:
                queue.pop(0)
        if matched <= 1e-9:
            continue
        e = epi.setdefault(sym, {"pnl": 0.0, "cost": 0.0, "sells": 0, "first": d, "is_option": bool(f.get("is_option"))})
        if d >= pf_from:
            e["pnl"] += amt * (matched / q) - cost; e["cost"] += cost; e["sells"] += 1
        if not queue:                                   # 回到 0 股 → 部位結束
            if e["sells"]:
                done.append({**e, "symbol": sym, "closed": d, "open": False})
            epi.pop(sym, None)
    done += [{**e, "symbol": sym, "closed": None, "open": True} for sym, e in epi.items() if e["sells"]]
    pos = [p for p in done if p["cost"] > 0]
    if not pos:
        return {"from": pf_from, "n_positions": 0}
    for p in pos:
        p["ret"] = p["pnl"] / p["cost"]
    w = [p for p in pos if p["pnl"] >= 0]; l = [p for p in pos if p["pnl"] < 0]
    avg = lambda xs: sum(xs) / len(xs) if xs else None
    aw, al = avg([p["pnl"] for p in w]), avg([-p["pnl"] for p in l])
    rets = [p["ret"] for p in pos]; m = avg(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / len(rets)) if len(rets) > 2 else 0
    skew = (sum((r - m) ** 3 for r in rets) / len(rets)) / sd ** 3 if sd else None
    gp = sum(p["pnl"] for p in w); top3 = sum(sorted((p["pnl"] for p in w), reverse=True)[:3])
    hit = len(w) / len(pos); payoff = (aw / al) if (aw and al) else None
    shape = None
    if payoff is not None:
        shape = ("常贏但贏得小（負偏態輪廓）" if hit >= 0.55 and payoff < 1 else
                 "少贏但贏得大（正偏態輪廓）" if hit < 0.5 and payoff > 1.2 else "中性")
    return {
        "from": pf_from, "n_positions": len(pos), "n_still_open": sum(p["open"] for p in pos),
        "n_sell_fills": sum(p["sells"] for p in pos),
        "hit_rate_pct": round(hit * 100, 1),
        "avg_win_usd": round(aw, 0) if aw else None, "avg_loss_usd": round(al, 0) if al else None,
        "payoff_ratio": round(payoff, 2) if payoff else None,
        "avg_win_ret_pct": round(100 * avg([p["ret"] for p in w]), 1) if w else None,
        "avg_loss_ret_pct": round(100 * avg([p["ret"] for p in l]), 1) if l else None,
        "expectancy_usd": round(sum(p["pnl"] for p in pos) / len(pos), 0),
        "ret_skew": round(skew, 2) if skew is not None else None,
        "top3_share_of_gross_profit_pct": round(100 * top3 / gp, 1) if gp else None,
        "shape": shape,
        "top3": [{"symbol": p["symbol"], "pnl": round(p["pnl"], 0)} for p in sorted(w, key=lambda p: -p["pnl"])[:3]],
        "worst3": [{"symbol": p["symbol"], "pnl": round(p["pnl"], 0)} for p in sorted(l, key=lambda p: p["pnl"])[:3]],
    }


def cmd_report(live: float | None, pf_from: str):
    series = load_series(live)
    eq = equity_metrics(series)
    pf = profit_factor(pf_from)
    ps = position_stats(pf_from)
    out = {"generated_at": datetime.now().isoformat(timespec="seconds"),
           "equity": eq, "profit_factor": pf, "position_stats": ps,
           "caveats": [
               "MDD 基於離散標記，低估真實 MDD（盤中/缺日不在內）",
               "淨值紀錄自 2026-06-01 起；年化數字為短窗外推，僅供方向參考",
               f"年化波動只用相鄰 ≤{VOL_MAX_GAP_DAYS} 日的標記段估計（長空窗不進分母）；Sharpe = (CAGR − rf) ÷ 年化波動",
               "profit factor 為 FIFO 已實現（含選擇權、含費用），未配對賣出已剔除",
               "Sharpe 標準誤 ≈ 1/√年數（Lo 2002 IID 近似）；95% 區間含 0 = 目前的 Sharpe 與 0 無法區分",
               "position_stats 以部位（同標的由 0 股買到回到 0 股）計，不以每筆賣出計；未清完但已有賣出的部位也算",
           ]}
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if "error" in eq:
        print(eq["error"])
        return 1
    w = eq["window"]
    print(f"── 帳戶績效（{w['from']} → {w['to']}，{w['days']} 天，{w['n_marks']} 個標記）──")
    print(f"期間報酬  {eq['total_return_pct']:+.2f}%   （${eq['start_value']:,.0f} → ${eq['end_value']:,.0f}）")
    print(f"CAGR      {eq['cagr_pct']:+.2f}%（年化外推）")
    print(f"MDD       {eq['mdd_pct']:.2f}%   （{eq['mdd_from']} 峰 → {eq['mdd_to']} 谷）")
    cb = "🔴 熔斷生效（R15）" if eq["circuit_breaker_active"] else "正常"
    print(f"當前回撤  {eq['current_drawdown_pct']:.2f}%（峰 {eq['peak_date']} ${eq['peak_value']:,.0f}）→ {cb}")
    vm = eq.get("vol_method", {})
    vol_txt = f"{eq['vol_ann_pct']:.1f}%" if eq.get("vol_ann_pct") is not None else "n/a（連續標記段不足）"
    print(f"Sharpe    {eq['sharpe']}      （年化波動 {vol_txt}，rf {eq['rf_used_pct']}%；"
          f"{vm.get('segments_used', 0)} 段 / {vm.get('trading_days_used', 0)} 交易日，空窗 >{vm.get('max_gap_days', '?')} 日不計）")
    if eq.get("sharpe_se") is not None:
        lo, hi = eq["sharpe_ci95"]
        verdict = "與 0 可區分" if eq["sharpe_distinguishable_from_zero"] else "與 0 無法區分（樣本太短，別當結論）"
        rho = f"；日報酬一階自相關 {eq['daily_autocorr_lag1']:+.2f}" if eq.get("daily_autocorr_lag1") is not None else ""
        print(f"  └ 標準誤 ±{eq['sharpe_se']}，95% 區間 {lo} ～ {hi} → {verdict}{rho}")
    print(f"ProfitFactor {pf['profit_factor']}（{pf['from']} 起：+${pf['gross_profit']:,.0f} / −${pf['gross_loss']:,.0f}，"
          f"勝率 {pf['win_rate_pct']}%（{pf['closed_wins']}W/{pf['closed_losses']}L），未配對剔除 {pf['unmatched_sells_skipped']} 筆）")
    if ps.get("n_positions"):
        print(f"以部位計  {ps['n_positions']} 個部位（{ps['n_sell_fills']} 筆賣出，{ps['n_still_open']} 個尚未清完）："
              f"打擊率 {ps['hit_rate_pct']}% × 賠率 {ps['payoff_ratio']}"
              f"（平均贏 ${ps['avg_win_usd']:,.0f}／{ps['avg_win_ret_pct']}%，平均賠 ${ps['avg_loss_usd']:,.0f}／{ps['avg_loss_ret_pct']}%）")
        print(f"  └ 每部位期望值 ${ps['expectancy_usd']:,.0f}；報酬偏態 {ps['ret_skew']}；前三大贏家佔總獲利 {ps['top3_share_of_gross_profit_pct']}%"
              f"（{'、'.join(t['symbol'] for t in ps['top3'])}）→ {ps['shape']}")
    try:   # 不交易對照線（2026-11-22 用戶「做對照線」）：買賣比起期初持股不動是加分還是扣分；失敗不影響上面的數字
        import do_nothing_line as dnl
        print("\n".join(dnl.lines(dnl.cached_or_build())))
    except Exception as e:  # noqa: BLE001
        print(f"不交易對照線：略過（{type(e).__name__}）")
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("scan")
    pa = sub.add_parser("add")
    pa.add_argument("date")
    pa.add_argument("value", type=float)
    pa.add_argument("--note", default="")
    pr = sub.add_parser("report")
    pr.add_argument("--live", type=float)
    pr.add_argument("--pf-from", default="2026-01-01")
    args = p.parse_args()
    if args.cmd == "scan":
        return cmd_scan()
    if args.cmd == "add":
        return cmd_add(args.date, args.value, args.note)
    if args.cmd == "report":
        if not MARKS_FILE.exists():
            cmd_scan()
        return cmd_report(args.live, args.pf_from)
    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
