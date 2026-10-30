#!/usr/bin/env python3
"""core_satellite_backtest.py — 核心/衛星結構對照回測（2026-10-30 提案附件，規格先於結果寫定）

問題：同一批「你當時真的持有的名字」，若只做月度再平衡、不做月中擇時，並把一部分換成被動核心（VOO），
      2026 年會長什麼樣？差距 = 操作成本（擇時 + 閒置 + 早收割），不是選股。

規格（跑之前寫定，之後不調參數）：
  - 名單：每個格子日（每月第一個交易日）收盤時帳戶**實際持有**的現股（由 journal 2026-06-04 快照 + 成交帳正/反向重放；
    排除 ETF / SGOV / 選擇權）。格子日已知 → 無前視；含後來賣掉的輸家 → 無倖存者偏差。
  - 持有：格子日收盤建倉，持有到下一個格子日收盤再平衡。
  - 變體：core_share ∈ {0, 0.3, 0.5, 0.6}（核心 = VOO）× 名單 ∈ {全部, 依格子日實際市值前 10}；衛星等權。
    另跑「實際權重月再平衡、無核心」= 只拿掉月中操作。
  - 硬線：衛星名字收盤自格子進場價 −20% → 次日收盤出場、該筆資金改持 VOO 到下一格（R32 型成本線，次日執行不佔便宜）。
  - 成本：Firstrade 零手續費；滑價忽略（說明在提案）。
  - 對照：實際帳戶 = equity-marks（1/1 手動錨 + 6/01 起日標記）；基準 VOO / QQQ / SMH。
Usage: python3 tools/core_satellite_backtest.py [--start 2026-01-01] [--end 2026-10-29] [--out research/core-satellite-backtest-2026-10-30.json]
"""
import argparse, json, re, warnings, collections
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
SPLITS = {"CRWD": ("2026-07-02", 4.0)}            # 2026 窗內持有名字唯一分割；分割日前股數 ×4（yfinance 調整價基準）
NON_STOCK = {"SGOV", "BIL", "VOO", "GLD", "XLE", "SPY", "QQQ", "SMH", "IWM", "VO", "TMF", "TQQQ", "DIA", "IBB", "KWEB"}
RF = 0.0388
ANCHOR = ROOT / "journal/2026-06-04.md"            # 最早的完整持倉快照

def adj_qty(sym, date, qty):
    s = SPLITS.get(sym); return qty * s[1] if s and date < s[0] else qty

def load_fills():
    rows = [json.loads(l) for l in open(ROOT / "research/trade-ledger.jsonl") if l.strip()]
    out = []
    for r in rows:
        if r.get("is_option") or str(r.get("origin_evidence") or "").startswith("VOID"): continue
        q = adj_qty(r["symbol"], r["date"], float(r["qty"]))
        out.append((r["date"], r["symbol"], q if r["side"] == "BOUGHT" else -q))
    return out

def parse_anchor(path):
    txt = open(path).read(); sec = txt.split("## 完整持倉快照", 1)[1].split("\n## ", 1)[0]
    date = re.search(r"(\d{4}-\d{2}-\d{2})", Path(path).name).group(1); pos = {}
    for line in sec.splitlines():
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) >= 3 and c[1] == "現股": pos[c[0]] = adj_qty(c[0], date, float(c[2]))
    return date, pos

def positions_by_day(days, anchor_date, anchor_pos, fills):
    f = pd.DataFrame(fills, columns=["date", "sym", "q"]); f["date"] = pd.to_datetime(f["date"])
    f = f[(f.date >= days[0]) & (f.date <= days[-1])]
    off = sorted(set(f.date) - set(days))
    if off: print(f"⚠️ {len(off)} 筆成交日不在交易日序列（併入下一交易日）: {[str(d.date()) for d in off][:5]}")
    f["date"] = f["date"].map(lambda d: days[days.searchsorted(d)])
    piv = f.pivot_table(index="date", columns="sym", values="q", aggfunc="sum").reindex(days).fillna(0.0)
    for s in anchor_pos:
        if s not in piv.columns: piv[s] = 0.0
    cum = piv.cumsum(); a = pd.Timestamp(anchor_date)
    base = pd.Series({s: anchor_pos.get(s, 0.0) for s in cum.columns})
    pos = cum - cum.loc[a] + base
    return pos.where(pos.abs() > 1e-6, 0.0)

def metrics(v, rf=RF):
    v = v.dropna(); r = v.pct_change().dropna(); n = len(r)
    tot = v.iloc[-1] / v.iloc[0] - 1; ann = (1 + tot) ** (252 / max(n, 1)) - 1
    vol = r.std() * np.sqrt(252); mdd = float((v / v.cummax() - 1).min())
    return {"total_return_pct": round(100 * tot, 2), "ann_return_pct": round(100 * ann, 2), "ann_vol_pct": round(100 * vol, 2),
            "mdd_pct": round(100 * mdd, 2), "sharpe": round((ann - rf) / vol, 2) if vol > 0 else None, "days": int(n)}

def simulate(pos, px, grids, last_day, core_share, top_n=None, actual_weights=False, hard_line=-0.20, basis="grid", core="VOO", cooldown_grids=2):
    """basis="grid"：硬線以每格進場價為基準（月月重設，較嚴）；"first_entry"：以該名字首次進入名單的格子價為基準（近 R32 成本線）。
    停出後冷卻 cooldown_grids 格不得重進（需重新提名）。"""
    out = []; v = 1.0; roster = {}; entry = {}; banned = {}; hits = []
    for i, g in enumerate(grids):
        nxt = grids[i + 1] if i + 1 < len(grids) else last_day
        seg = px.loc[g:nxt]; held = pos.loc[g]
        names = [s for s in held.index if held[s] > 0.5 and s not in NON_STOCK and s in px.columns and not np.isnan(px.at[g, s]) and banned.get(s, -1) < i]
        mv = {s: held[s] * px.at[g, s] for s in names}
        if top_n: names = sorted(names, key=lambda s: -mv[s])[:top_n]
        for s in list(entry):
            if held.get(s, 0) <= 0.5: entry.pop(s)                        # 真的賣光才重設首次進場價
        for s in names: entry.setdefault(s, float(px.at[g, s]))
        roster[str(g.date())] = names
        tot_mv = sum(mv[s] for s in names) or 1.0
        w = {s: (1 - core_share) * (mv[s] / tot_mv if actual_weights else 1 / len(names)) for s in names}
        cp = seg[core] / seg[core].iloc[0]; total = core_share * cp.copy()
        for s in names:
            p = seg[s] / seg[s].iloc[0]
            if hard_line is not None:
                ref = entry[s] if basis == "first_entry" else float(seg[s].iloc[0])
                hit = seg.index[(seg[s] / ref - 1) <= hard_line]
                if len(hit):
                    k = seg.index.get_loc(hit[0]) + 1                       # 次日收盤執行
                    if k < len(seg):
                        h = seg.index[k]; p = p.copy(); p.loc[h:] = p.loc[h] * (seg[core].loc[h:] / seg[core].loc[h])
                        hits.append((str(h.date()), s, round(float(seg[s].loc[h] / ref - 1) * 100, 1))); banned[s] = i + cooldown_grids; entry.pop(s, None)
            total = total + w[s] * p
        sv = v * total; out.append(sv.iloc[:-1] if i + 1 < len(grids) else sv); v = float(sv.iloc[-1])
    return pd.concat(out), roster, hits

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--start", default="2026-01-01"); ap.add_argument("--end", default="2026-10-29")
    ap.add_argument("--out", default="research/core-satellite-backtest-2026-10-30.json"); a = ap.parse_args()
    anchor_date, anchor_pos = parse_anchor(ANCHOR); fills = load_fills()
    syms = sorted({s for _, s, _ in fills if s not in NON_STOCK} | set(anchor_pos) | {"VOO", "QQQ", "SMH", "SPY", "QLD", "USD", "VO"})
    px = yf.download(syms, start=pd.Timestamp(a.start) - pd.Timedelta(days=7), end=pd.Timestamp(a.end) + pd.Timedelta(days=1),
                     progress=False, auto_adjust=True)["Close"].ffill()
    px = px.loc[px["VOO"].dropna().index]
    pre = px.index[px.index < pd.Timestamp(a.start)][-1]                     # 前一交易日（12/31）作為持倉起點
    days = px.index[(px.index >= pre) & (px.index <= pd.Timestamp(a.end))]; px = px.loc[days]
    missing = [s for s in syms if s not in px.columns or px[s].dropna().empty]
    if missing: print("⚠️ 無價格資料（略過）:", missing)
    pos = positions_by_day(days, anchor_date, anchor_pos, fills)
    # —— 驗證 1：終點 vs live 快照 ——
    st = json.load(open(ROOT / "research/position-state.json")); live = {p["symbol"]: float(p["qty"]) for p in st["positions"]}
    end_pos = pos.iloc[-1]; diffs = {s: (round(float(end_pos.get(s, 0)), 2), live.get(s)) for s in set(live) | set(end_pos[end_pos > 0.5].index)
                                     if s not in NON_STOCK and abs(float(end_pos.get(s, 0)) - (live.get(s) or 0)) > 0.6}
    print(f"驗證 1（{a.end} 重放 vs live）：差異 {len(diffs)} 檔 {diffs if diffs else '✅ 全對'}")
    # —— 驗證 2：起點 vs 1/1 手動錨（現金 13,362 + 18 檔）——
    p0 = pos.iloc[0]; names0 = [s for s in p0.index if p0[s] > 0.5 and s not in NON_STOCK]
    v0 = sum(p0[s] * px.at[days[0], s] for s in names0 if not np.isnan(px.at[days[0], s])) + 13362
    print(f"驗證 2（{days[0].date()} 重放 {len(names0)} 檔 + 現金 13,362 = ${v0:,.0f} vs 手動錨 $198,412，差 {v0/198412-1:+.1%}）")
    # —— 格子 ——
    inwin = days[days >= pd.Timestamp(a.start)]
    grids = list(inwin[~inwin.to_period("M").duplicated()]); last = days[-1]
    # —— 實際帳戶 ——
    em = json.load(open(ROOT / "research/equity-marks.json"))
    marks = {m["date"]: m["value"] for m in em.get("manual", [])}; marks.update({m["date"]: m["value"] for m in em["marks"] if not m.get("excluded")})
    acct = pd.Series(marks); acct.index = pd.to_datetime(acct.index); acct = acct.sort_index()
    acct = acct[(acct.index >= pd.Timestamp(a.start) - pd.Timedelta(days=1)) & (acct.index <= pd.Timestamp(a.end))]
    sub_start = pd.Timestamp("2026-06-04")
    res = {"spec": __doc__.strip().splitlines()[0], "window": [str(days[0].date()), str(a.end)], "grids": [str(g.date()) for g in grids],
           "validation": {"end_vs_live_diffs": diffs, "start_names": len(names0), "start_value_recon": round(v0), "start_value_anchor": 198412},
           "actual": {"full": metrics(acct), "since_0604": metrics(acct[acct.index >= sub_start]), "n_marks": int(len(acct))},
           "benchmarks": {}, "variants": {}, "roster": None, "monthly": {}}
    for b in ("VOO", "QQQ", "SMH", "QLD", "USD", "VO"):
        s = px[b].dropna(); res["benchmarks"][b] = {"full": metrics(s), "since_0604": metrics(s[s.index >= sub_start])}
    variants = {
        "A1_等權_月再平衡_無硬線": dict(core_share=0.0, hard_line=None),
        "A1_等權_月再平衡_硬線20格子": dict(core_share=0.0, hard_line=-0.20, basis="grid"),
        "A1_等權_月再平衡_硬線20首次": dict(core_share=0.0, hard_line=-0.20, basis="first_entry"),
        "A2_實際權重_月再平衡_無硬線": dict(core_share=0.0, actual_weights=True, hard_line=None),
        "A2_實際權重_月再平衡_硬線20首次": dict(core_share=0.0, actual_weights=True, hard_line=-0.20, basis="first_entry"),
        "B50_全名單等權_無硬線": dict(core_share=0.5, hard_line=None),
        "B50_實際權重_無硬線": dict(core_share=0.5, actual_weights=True, hard_line=None),
        "B50_前10等權_無硬線": dict(core_share=0.5, top_n=10, hard_line=None),
        "B50_前10等權_硬線20首次": dict(core_share=0.5, top_n=10, hard_line=-0.20, basis="first_entry"),
        "B50_前10等權_硬線30首次": dict(core_share=0.5, top_n=10, hard_line=-0.30, basis="first_entry"),
        "B30_前10等權_無硬線": dict(core_share=0.3, top_n=10, hard_line=None),
        "B30_實際權重_無硬線": dict(core_share=0.3, actual_weights=True, hard_line=None),
        "B60_前10等權_無硬線": dict(core_share=0.6, top_n=10, hard_line=None),
    }
    paths = {}
    for k, kw in variants.items():
        v, roster, hits = simulate(pos, px, grids, last, **kw); paths[k] = v
        res["variants"][k] = {"full": metrics(v), "since_0604": metrics(v[v.index >= sub_start]), "params": kw, "hard_line_hits": hits}
        if k == "A1_等權_月再平衡_無硬線": res["roster"] = roster
    # —— 月報酬（實際 vs 兩個主要變體）——
    def monthly(s): return (s.resample("ME").last().pct_change().dropna() * 100).round(1)
    for k in ("A2_實際權重_月再平衡_無硬線", "B50_實際權重_無硬線", "B50_前10等權_無硬線"):
        res["monthly"][k] = {str(d.date())[:7]: float(x) for d, x in monthly(paths[k]).items()}
    res["monthly"]["VOO"] = {str(d.date())[:7]: float(x) for d, x in monthly(px["VOO"]).items()}
    res["monthly"]["SMH"] = {str(d.date())[:7]: float(x) for d, x in monthly(px["SMH"]).items()}
    # —— 衛星籃子 β（對 QQQ / SMH / 定期定額帳戶籃子 QLD+USD+VO 等權）——
    r = paths["A1_等權_月再平衡_無硬線"].pct_change().dropna()
    dca = px[["QLD", "USD", "VO"]].pct_change().dropna().mean(axis=1)
    def beta(x, y): j = pd.concat([x, y], axis=1).dropna(); return round(float(np.cov(j.iloc[:, 0], j.iloc[:, 1])[0, 1] / j.iloc[:, 1].var()), 2), round(float(j.corr().iloc[0, 1]), 2)
    res["satellite_beta"] = {"vs_QQQ": beta(r, px["QQQ"].pct_change()), "vs_SMH": beta(r, px["SMH"].pct_change()), "vs_DCA_basket": beta(r, dca)}
    res["actual"]["account_metrics_ref"] = {"cmd": "account_metrics.py report（2026-10-30 跑）", "ytd_pct": 27.59, "mdd_pct": -18.82, "ann_vol_pct": 32.5, "sharpe": 0.94,
                                            "note": "marks 1–5 月稀疏，本檔 actual.full 的波動/Sharpe 無意義，以此為準"}
    nodes = [d for d in ("2026-02-13", "2026-06-02", "2026-07-28", "2026-10-29") if pd.Timestamp(d) in acct.index]
    res["nodes"] = {"帳戶": {d: round(100 * (acct[pd.Timestamp(d)] / acct.iloc[0] - 1), 1) for d in nodes}}
    for k in ("A1_等權_月再平衡_無硬線", "A2_實際權重_月再平衡_無硬線", "B50_實際權重_無硬線", "B50_前10等權_無硬線"):
        s = paths[k]; res["nodes"][k] = {d: round(100 * (s[:pd.Timestamp(d)].iloc[-1] / s.iloc[0] - 1), 1) for d in nodes}
    for b in ("VOO", "QQQ", "SMH"):
        s = px[b]; res["nodes"][b] = {d: round(100 * (s[:pd.Timestamp(d)].iloc[-1] / s.iloc[0] - 1), 1) for d in nodes}
    (ROOT / a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    # —— 輸出 ——
    print(f"\n格子日：{', '.join(res['grids'])}\n")
    print("| 變體 | 全年報酬 | 全年 MDD | 年化波動 | Sharpe | 6/04 起報酬 | 6/04 起 MDD |"); print("|---|---|---|---|---|---|---|")
    def row(name, d): f, s = d["full"], d["since_0604"]; print(f"| {name} | {f['total_return_pct']:+.1f}% | {f['mdd_pct']:.1f}% | {f['ann_vol_pct']:.1f}% | {f['sharpe']} | {s['total_return_pct']:+.1f}% | {s['mdd_pct']:.1f}% |")
    ref = res["actual"]["account_metrics_ref"]; sa = res["actual"]["since_0604"]
    print(f"| 實際帳戶（account_metrics / marks） | {ref['ytd_pct']:+.1f}% | {ref['mdd_pct']:.1f}% | {ref['ann_vol_pct']:.1f}% | {ref['sharpe']} | {sa['total_return_pct']:+.1f}% | {sa['mdd_pct']:.1f}% |")
    for b in ("VOO", "QQQ", "SMH"): row(b, res["benchmarks"][b])
    for k, d in res["variants"].items(): row(k, d)
    print("\n硬線觸發：", {k: len(d["hard_line_hits"]) for k, d in res["variants"].items() if d["hard_line_hits"]})
    print("\n自 1/1 累積 %（節點對照）："); print(pd.DataFrame(res["nodes"]).T.to_string())
    print("\n衛星籃子 β/相關（等權全名單）：", res["satellite_beta"])
    print("月報酬 %："); print(pd.DataFrame(res["monthly"]).to_string())
    print(f"\n→ {a.out}")

if __name__ == "__main__":
    main()
