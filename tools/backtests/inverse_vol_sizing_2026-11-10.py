"""T4 部位大小按波動倒數：R30／H10 每筆金額固定（≤$3,000／≤2%），高波動名字是不是該買少一點？
資料：research/trade-ledger.jsonl 2026-06-01 起的現股買進成交（非選擇權；剔除 ETF：SMH IGV SPY GLD VOO XLE SGOV BIL）。
同一檔同一天的多筆成交併成一筆決定。基準同帳本規則：tools/trade_ledger.py SEMI_AI 用 SMH，其餘 SPY。
量測（收盤對收盤，yfinance auto_adjust=True）：買進日收盤 → 第 H 個交易日收盤（H 預設 30）個股 − 基準超額；
  期間最深回撤＝之後 H 日內最低價 ÷ 買進日收盤 − 1。另列「以實際成交價為起點」版。
兩種加權：
  實際＝成交金額。
  波動倒數＝成交金額 ×（買進前一日「樣本內所有買過的名字」60 日波動的中位數 ÷ 該股 60 日波動），夾在 0.5–1.0 倍
          （只縮高波動、不放大低波動；省下的錢視為留在基準 → 超額 0）。
回報：兩種加權的金額加權平均超額、超額損益總額、最差單筆損益與最差單筆回撤金額、波動高低兩半各自的平均超額。
差異的不確定性：以「檔」為單位重抽的 bootstrap（同一檔的多次買進不獨立）。樣本只有幾個月、單一行情段。
用法：python3 inverse_vol_sizing_2026-11-10.py [H=30] [--refresh]
輸出：data/inverse_vol_sizing_2026-11-10.out.txt

首跑結論（2026-11-10）：
- 樣本：145 筆個股成交併成 139 筆決定、38 檔；滿 30 個交易日可計分 119 筆（36 檔，6/1→9/28 買進），合計 $236,658。
- 30 日金額加權平均超額：實際 +0.09%、波動倒數 +0.74%，差 +0.65pp（以檔重抽 95% 區間 [+0.13, +1.20]pp）；扣 β 版差 +0.51pp（[+0.01, +1.10]）。
  20 日 +0.58pp、10 日 +0.23pp，同向。倍數平均只有 0.92（43% 的單被縮、幾乎沒有碰到 0.5 下限），所以效果小。
- 最差單筆 30 日損益：實際 −$979（MRVL 6/15，−47.1%）→ 波動倒數 −$686（MDB 6/1）；最差單筆期間回撤 −$1,231 → −$1,098。
  超額損益合計 +$203 → +$1,606；30 日損益合計 −$5,509 → −$3,367。
- 高波動名字沒有比較賺，是比較賠：高波動半（n=59，β 1.49）等權超額 −4.40%、勝率 42%、最深回撤平均 −23.7%；
  低波動半（n=60，β 0.92）+4.17%、57%、−10.9%。扣 β 後仍 −3.33% vs +2.82%；每檔先平均再比 −7.43% vs +0.31%（36 檔）。
- 限制：只有 4 個買進月、單一行情段（期間基準平均 −2.7%，高 β 名字在跌勢裡本來就吃虧）；119 筆決定來自 36 檔、同檔多次買進高度相關；
  事後回算（倍數用買進前一日資料，無偷看）；未計「省下的錢」的再部署；ETF 已剔除。方向支持、幅度與持續性證據不足。
"""
import sys, json, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = HERE / "data"; DATA.mkdir(exist_ok=True)
NAME = "inverse_vol_sizing_2026-11-10"
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
HMAIN = int(ARGS[0]) if ARGS else 30
REFRESH = "--refresh" in sys.argv
PKL = DATA / "inverse_vol_px_2026-11-10.pkl"
ETFS = {"SMH", "IGV", "SPY", "GLD", "VOO", "XLE", "SGOV", "BIL", "QQQ"}
SEMI_AI = {"AMD","ANET","ARM","ASML","AVGO","COHR","CRDO","DIOD","ICHR","INTC","LITE","LRCX","MRVL","MU","NVDA","ON","ONTO",
           "QCOM","SNPS","STX","TSM","CIEN","CDNS","KLAC","AMAT","TER"}   # = tools/trade_ledger.py SEMI_AI（2026-11-10 抄錄）
SINCE = "2026-06-01"

_lines = []
def P(*a):
    s = " ".join(str(x) for x in a); print(s); _lines.append(s)

def load_buys():
    rows = [json.loads(l) for l in open(ROOT / "research/trade-ledger.jsonl") if l.strip()]
    b = [r for r in rows if r["date"] >= SINCE and r["side"] == "BOUGHT" and not r.get("is_option")]
    n_all = len(b); etf = [r for r in b if r["symbol"] in ETFS]; b = [r for r in b if r["symbol"] not in ETFS]
    df = pd.DataFrame([{"date": pd.Timestamp(r["date"]), "sym": r["symbol"], "notional": float(r["notional"]),
                        "qty": float(r["qty"]), "px": float(r.get("split_adj_price") or r["price"]), "origin": r.get("origin", "")} for r in b])
    g = df.groupby(["sym", "date"]).agg(notional=("notional", "sum"), qty=("qty", "sum"), fills=("px", "size"),
                                        origin=("origin", "first")).reset_index()
    vw = df.assign(v=df["px"] * df["qty"]).groupby(["sym", "date"])[["v", "qty"]].sum()
    g["fill_px"] = (vw["v"] / vw["qty"]).values
    return g.sort_values(["date", "sym"]).reset_index(drop=True), n_all, len(etf), len(df)

def load_px(syms):
    if PKL.exists() and not REFRESH:
        d = pd.read_pickle(PKL)
        if set(syms) <= set(d["Close"].columns): return d
    import yfinance as yf
    d = yf.download(sorted(set(syms) | {"SMH", "SPY"}), start="2025-11-01", progress=False, auto_adjust=True, threads=True)[["Close", "Low"]]
    d.to_pickle(PKL); return d

def enrich(g, px, H):
    C, L = px["Close"], px["Low"]; R = C.pct_change()
    vol = R.rolling(60).std().shift(1)                       # 買進前一日為止的 60 日日波動
    names = sorted(g["sym"].unique())
    med = vol[[n for n in names if n in vol.columns]].median(axis=1)
    out = []; skipped = []
    for r in g.itertuples():
        s = r.sym; b = "SMH" if s in SEMI_AI else "SPY"
        if s not in C.columns or C[s].dropna().empty: skipped.append((s, str(r.date.date()), "無價格")); continue
        c = C[s].dropna(); idx = c.index
        if r.date not in idx: skipped.append((s, str(r.date.date()), "非交易日")); continue
        i = idx.get_loc(r.date); v = vol[s].get(r.date, np.nan); m = med.get(r.date, np.nan)
        beta = (R[s].rolling(60).cov(R[b]) / R[b].rolling(60).var()).shift(1).get(r.date, np.nan)   # 買進前 60 日對基準 β
        rec = dict(sym=s, date=r.date, bench=b, notional=r.notional, fills=r.fills, fill_px=r.fill_px, close0=c.iloc[i],
                   vol=v, med=m, beta=beta, ratio=v / m if m and not np.isnan(v) else np.nan)
        if i + H < len(idx):
            cb = C[b].reindex(idx)
            rs, rb = c.iloc[i + H] / c.iloc[i] - 1, cb.iloc[i + H] / cb.iloc[i] - 1
            rec.update(ret=rs, bret=rb, x=rs - rb, xb=rs - beta * rb, dd=L[s].reindex(idx).iloc[i + 1:i + H + 1].min() / c.iloc[i] - 1,
                       x_fill=(c.iloc[i + H] / r.fill_px - 1) - rb, ret_fill=c.iloc[i + H] / r.fill_px - 1)
        out.append(rec)
    d = pd.DataFrame(out)
    d["mult"] = (1 / d["ratio"]).clip(0.5, 1.0)
    d["w_iv"] = d["notional"] * d["mult"]
    return d, skipped

def wavg(x, w):
    m = x.notna() & w.notna(); return (x[m] * w[m]).sum() / w[m].sum()

def boot_diff(d, col, B=5000, seed=7):
    """波動倒數加權 − 實際加權 的金額加權平均超額之差；以檔為單位重抽。"""
    rng = np.random.default_rng(seed); syms = d["sym"].unique(); grp = {s: d[d["sym"] == s] for s in syms}; res = []
    for _ in range(B):
        pick = rng.choice(syms, len(syms), replace=True); s = pd.concat([grp[k] for k in pick])
        res.append(wavg(s[col], s["w_iv"]) - wavg(s[col], s["notional"]))
    return np.percentile(res, [2.5, 50, 97.5]), np.mean(np.array(res) > 0)

def report(d0, H, main=True):
    d = d0.dropna(subset=["x", "ratio"]).copy()
    P(f"\n### H={H} 個交易日｜可計分 {len(d)} 筆決定（{d['sym'].nunique()} 檔，買進日 {d['date'].min().date()} → {d['date'].max().date()}）；買進金額合計 ${d['notional'].sum():,.0f}，單筆中位 ${d['notional'].median():,.0f}")
    P(f"  波動倒數倍數：平均 {d['mult'].mean():.2f}、被縮（<1.0）的 {(d['mult']<1).mean()*100:.0f}%、縮到下限 0.5 的 {(d['mult']<=0.5).mean()*100:.0f}%；調整後金額合計 ${d['w_iv'].sum():,.0f}（原本的 {d['w_iv'].sum()/d['notional'].sum()*100:.0f}%）")
    P(f"  60 日日波動：樣本中位 {d['vol'].median()*100:.2f}%（年化約 {d['vol'].median()*np.sqrt(252)*100:.0f}%）、最低 {d['vol'].min()*100:.2f}%、最高 {d['vol'].max()*100:.2f}%")
    P(f"  等權（每筆決定一票）：平均超額 {d['x'].mean()*100:+.2f}%、中位 {d['x'].median()*100:+.2f}%、勝率 {(d['x']>0).mean()*100:.0f}%、個股報酬平均 {d['ret'].mean()*100:+.2f}%、最深回撤平均 {d['dd'].mean()*100:+.1f}%")
    for lab, w in (("實際金額", "notional"), ("波動倒數", "w_iv")):
        pnl = d[w] * d["ret"]; xp = d[w] * d["x"]; ddp = d[w] * d["dd"]
        i1, i2 = pnl.idxmin(), ddp.idxmin()
        P(f"  [{lab}] 金額加權平均超額 {wavg(d['x'], d[w])*100:+.2f}%（成交價起算版 {wavg(d['x_fill'], d[w])*100:+.2f}%、扣 β 版 {wavg(d['xb'], d[w])*100:+.2f}%）｜金額加權個股報酬 {wavg(d['ret'], d[w])*100:+.2f}%｜金額加權最深回撤 {wavg(d['dd'], d[w])*100:+.1f}%")
        P(f"      超額損益合計 ${xp.sum():+,.0f}、{H} 日損益合計 ${pnl.sum():+,.0f}｜最差單筆 {H} 日損益 ${pnl.min():+,.0f}（{d.loc[i1,'sym']} {d.loc[i1,'date'].date()}，{d.loc[i1,'ret']*100:+.1f}%）｜最差單筆期間回撤 ${ddp.min():+,.0f}（{d.loc[i2,'sym']} {d.loc[i2,'date'].date()}，{d.loc[i2,'dd']*100:+.1f}%）")
    ci, pp = boot_diff(d, "x"); cib, ppb = boot_diff(d, "xb")
    P(f"  波動倒數 − 實際（金額加權平均超額）：{(wavg(d['x'], d['w_iv'])-wavg(d['x'], d['notional']))*100:+.2f}pp；以檔重抽 bootstrap 95% 區間 [{ci[0]*100:+.2f}, {ci[2]*100:+.2f}]pp、差 > 0 的比例 {pp*100:.0f}%")
    P(f"  同上但超額改扣 β 版（個股 − β×基準，β＝買進前 60 日）：{(wavg(d['xb'], d['w_iv'])-wavg(d['xb'], d['notional']))*100:+.2f}pp；95% 區間 [{cib[0]*100:+.2f}, {cib[2]*100:+.2f}]pp、差 > 0 的比例 {ppb*100:.0f}%")
    # 波動高低兩半
    cut = d["ratio"].median(); hi, lo = d[d["ratio"] > cut], d[d["ratio"] <= cut]
    P(f"  波動高低兩半（依 該股波動 ÷ 當時中位數，樣本切點 {cut:.2f}）：")
    for lab, s in (("高波動半", hi), ("低波動半", lo)):
        P(f"    {lab} n={len(s):>2}（{s['sym'].nunique()} 檔）日波動中位 {s['vol'].median()*100:.2f}%、平均 β {s['beta'].mean():.2f}｜等權平均超額 {s['x'].mean()*100:+.2f}%（扣 β 版 {s['xb'].mean()*100:+.2f}%）、中位 {s['x'].median()*100:+.2f}%、勝率 {(s['x']>0).mean()*100:.0f}%｜金額加權超額 {wavg(s['x'], s['notional'])*100:+.2f}%｜個股報酬平均 {s['ret'].mean()*100:+.2f}%｜最深回撤平均 {s['dd'].mean()*100:+.1f}%、最差 {s['dd'].min()*100:+.1f}%｜超額標準差 {s['x'].std()*100:.1f}%")
    P(f"    高 − 低 等權平均超額 {(hi['x'].mean()-lo['x'].mean())*100:+.2f}pp（扣 β 版 {(hi['xb'].mean()-lo['xb'].mean())*100:+.2f}pp）；波動比與超額的秩相關 {d['ratio'].rank().corr(d['x'].rank()):+.2f}（扣 β 版 {d['ratio'].rank().corr(d['xb'].rank()):+.2f}，n={len(d)}）；期間基準平均報酬 {d['bret'].mean()*100:+.2f}%")
    # 每檔平均後再比（防單一檔多次買進主導）
    per = d.groupby("sym").agg(x=("x", "mean"), xb=("xb", "mean"), ratio=("ratio", "mean"), n=("x", "size"))
    c2 = per["ratio"].median()
    P(f"    先每檔平均再比：高波動 {(per['ratio']>c2).sum()} 檔平均超額 {per.loc[per['ratio']>c2,'x'].mean()*100:+.2f}%、低波動 {(per['ratio']<=c2).sum()} 檔 {per.loc[per['ratio']<=c2,'x'].mean()*100:+.2f}%；秩相關 {per['ratio'].rank().corr(per['x'].rank()):+.2f}（扣 β 版：高 {per.loc[per['ratio']>c2,'xb'].mean()*100:+.2f}%、低 {per.loc[per['ratio']<=c2,'xb'].mean()*100:+.2f}%、秩相關 {per['ratio'].rank().corr(per['xb'].rank()):+.2f}；n={len(per)} 檔）")
    if main:
        P("  分月（買進月）等權平均超額／金額加權：實際 vs 波動倒數")
        for m, s in d.groupby(d["date"].dt.to_period("M")):
            P(f"    {m} n={len(s):>2}  等權 {s['x'].mean()*100:+6.2f}%  實際加權 {wavg(s['x'], s['notional'])*100:+6.2f}%  波動倒數加權 {wavg(s['x'], s['w_iv'])*100:+6.2f}%  基準平均 {s['bret'].mean()*100:+6.2f}%")
        P("  逐筆（依超額由差到好；倍數 = 波動倒數倍數）")
        for r in d.sort_values("x").itertuples():
            P(f"    {r.date.date()} {r.sym:<5} ${r.notional:>7,.0f} 倍數 {r.mult:.2f} 日波動 {r.vol*100:.2f}% 個股 {r.ret*100:+6.1f}% 基準({r.bench}) {r.bret*100:+6.1f}% 超額 {r.x*100:+6.1f}% 最深回撤 {r.dd*100:+6.1f}%")

def main():
    g, n_all, n_etf, n_stock = load_buys()
    px = load_px(list(g["sym"].unique()))
    P(f"T4 部位大小按波動倒數｜帳本 {SINCE} 起現股買進 {n_all} 筆成交，剔除 ETF {n_etf} 筆 → 個股 {n_stock} 筆成交、併成 {len(g)} 筆決定（同檔同日合併）、{g['sym'].nunique()} 檔")
    P(f"價格至 {px['Close'].index.max().date()}；買進日 {g['date'].min().date()} → {g['date'].max().date()}")
    for H, main_flag in ((HMAIN, True), (20, False), (10, False)):
        if H == HMAIN and not main_flag: continue
        d, skipped = enrich(g, px, H)
        if main_flag:
            P(f"跳過：{skipped or '無'}；未滿 {H} 個交易日無法計分的決定 {d['x'].isna().sum() if 'x' in d else len(d)} 筆")
        report(d, H, main_flag)
    (DATA / f"{NAME}.out.txt").write_text("\n".join(_lines) + "\n")
    print(f"\n→ {DATA / (NAME + '.out.txt')}")

if __name__ == "__main__":
    main()
