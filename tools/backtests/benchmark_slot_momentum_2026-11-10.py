"""U2 基準格用動能輪動 — 2026-11-10

問題：弱倉換成對應基準 ETF（R36，SMH／IGV／QQQ／VOO）。若基準格不照板塊對應、改成「每月底持有四檔中過去 12 個月最強的一檔」，
會不會比各自買進持有或四檔等權好？代價是不是把半導體集中再加重？

設計（事先寫定，只試兩組）：
- 四檔：VOO（2010-09 前用 SPY 報酬接上）、QQQ、SMH、IGV；起點 = 四檔都有資料後滿 12 個月（IGV 2001-07 上市 → 2002-08 起）
- M12：月底算過去 12 個月總報酬最高者；M12-1：過去 12 個月但跳過最近 1 個月（t−12 → t−1）
- 月底收盤判定 → 次月第一個交易日起持有一個月（daily shift(1)）；永遠滿倉、不放現金
- 對照：四檔各自買進持有、四檔等權（月底再平衡）
- 報 CAGR／波動／Sharpe（對 ^IRX）／最大回撤／年換手（輪動＝每次換檔 100%；等權＝再平衡單邊換手）、持有 SMH 的月份比例
- 分全期、2002-08–2009、2010→；另報輪動 vs 等權、vs SMH 的月超額 t 值

已知缺陷：四檔是「現在知道它們是贏家」才選的（尤其 SMH）；只有四檔、相關 0.8–0.9，輪動的自由度很小；
SMH 2000–2011 是 HOLDRS 結構（成分固定、集中度高）；無交易成本；月頻 290 個月、實際獨立的動能週期只有幾段。

首跑結論（2026-11-10，2002-08→2026-11-09，292 個月）：
- 全期輪動沒有贏等權：M12 CAGR 13.9%／MDD −61.4%／Sharpe 0.56；M12-1 15.4%／−54.5%／0.61；
  四檔等權 14.8%／−53.2%／0.65；QQQ 15.6%／0.69；SMH 16.8%／−67.9%／0.60。
  月超額對等權 M12 −0.02%（t −0.09）、M12-1 +0.09%（t +0.50）；對 SMH −0.33%（t −1.36）、−0.22%（t −0.92）。
- 分段方向相反：2002-08–2009 M12 CAGR −0.0%、M12-1 3.0% vs 等權 6.7%（2004–05 追高 SMH 兩年連輸）；
  2010→ M12 20.6%、M12-1 21.4% vs 等權 18.5%（月超額 t +0.96／+1.19）vs SMH 24.7%。
  2010 後的「贏等權」來自 49% 的月份押在 SMH，不是擇時：輪動對 SMH 買進持有 2010→ 月超額 −0.36%（t −1.65）。
- 集中度：輪動持有 SMH 的月份 全期 41%／40%、2010→ 49%／49%（等權固定 25%）；波動 26% vs 等權 22.7%。年換檔 2.7–3.1 次。
- 逐年：25 年中 M12 贏等權 12 年、贏 SMH 8 年；M12-1 贏等權 12 年、贏 SMH 10 年。
- 判讀：**不成立**。四檔相關 0.75–0.91，動能輪動等於「多數時間持有 SMH、偶爾在轉折月被洗出去」，
  報酬介於等權與 SMH 之間、回撤不比等權淺，同時把半導體比重從 25% 拉到 40–49%——正好是使用者不要的方向。
  基準格維持照板塊對應（R36 現行做法）。
"""
import numpy as np, pandas as pd, yfinance as yf, warnings
warnings.filterwarnings("ignore")

raw = yf.download(["SPY", "VOO", "QQQ", "SMH", "IGV", "^IRX"], period="max", progress=False, auto_adjust=True)["Close"]
ret = raw[["SPY", "VOO", "QQQ", "SMH", "IGV"]].pct_change()
R = pd.DataFrame({"VOO": ret["VOO"].where(ret["VOO"].notna(), ret["SPY"]), "QQQ": ret["QQQ"], "SMH": ret["SMH"], "IGV": ret["IGV"]})
R = R.loc[R.dropna().index[0]:].dropna(how="any")
idx = R.index; N = list(R.columns)
cash = (raw["^IRX"].reindex(idx).ffill() / 100 / 252).fillna(0)
P = (1 + R).cumprod()
ym = pd.Series(idx.to_period("M"), index=idx)
is_me = (ym != ym.shift(-1)); is_me.iloc[-1] = False
me = idx[is_me.values]; Pm = P.loc[me]

mom = {"M12 過去 12 個月最強": Pm / Pm.shift(12) - 1, "M12-1 跳過最近 1 個月": Pm.shift(1) / Pm.shift(12) - 1}
picks = {k: v.dropna().idxmax(axis=1) for k, v in mom.items()}
first_sig = max(p.index[0] for p in picks.values())
START = idx[idx.get_loc(first_sig) + 1]

S = {}; H = {}
for k, pk in picks.items():
    h = pk.reindex(idx).ffill().shift(1)                # 月底選 → 次日起持有
    H[k] = h
    S[k] = pd.Series(R.to_numpy()[np.arange(len(idx)), [N.index(x) if isinstance(x, str) else 0 for x in h]], index=idx).where(h.notna())
for n in N:
    S[f"{n} 買進持有"] = R[n]
# 等權月底再平衡（權重日內漂移）
w = np.full(4, 0.25); ew = []; to = []; Rv = R.to_numpy(); mev = is_me.to_numpy()
for i in range(len(idx)):
    g = w * (1 + Rv[i]); tot = g.sum(); ew.append(tot - 1); w = g / tot
    if mev[i]:
        to.append((idx[i], 0.5 * np.abs(w - 0.25).sum())); w = np.full(4, 0.25)
S["四檔等權（月底再平衡）"] = pd.Series(ew, index=idx)
ew_to = pd.Series(dict(to))

def metrics(rr, a, b=None):
    rr = rr.loc[a:b].dropna(); yrs = len(rr) / 252; eq = (1 + rr).cumprod()
    return (eq.iloc[-1] ** (1 / yrs) - 1, rr.std() * np.sqrt(252),
            (rr - cash.reindex(rr.index)).mean() / rr.std() * np.sqrt(252), (eq / eq.cummax() - 1).min(), yrs)

def monthly(rr, a, b=None):
    rr = rr.loc[a:b].dropna(); return (1 + rr).groupby(rr.index.to_period("M")).prod() - 1

print(f"U2 基準格動能輪動 — 四檔共同資料 {idx[0].date()} → {idx[-1].date()}；策略起點 {START.date()}（VOO 於 {raw['VOO'].dropna().index[0].date()} 前用 SPY）")
print("月底收盤選 → 次月第一個交易日起持有；永遠滿倉；無交易成本\n")
for lab, a, b in (("全期", START, None), ("2002-08–2009", START, "2009-12-31"), ("2010→", "2010-01-01", None)):
    print(f"[{lab}]  {'策略':<26}{'CAGR':>7}{'波動':>7}{'Sharpe':>7}{'MDD':>8}{'年換手':>8}{'換檔/年':>8}  持有月份比例 " + "／".join(N))
    for k, rr in S.items():
        c, v, s, md, yrs = metrics(rr, a, b)
        if k in H:
            h = H[k].loc[a:b].dropna(); sw = (h != h.shift()).sum() - 1
            hm = picks[k].loc[pd.Timestamp(a) - pd.Timedelta(days=5):b]; hm = hm[hm.index < idx[-1]]
            share = "／".join(f"{(hm == n).mean():.0%}" for n in N)
            print(f"   {k:<26}{c:>7.1%}{v:>7.1%}{s:>7.2f}{md:>8.1%}{sw / yrs:>8.0%}{sw / yrs:>8.1f}  {share}")
        elif "等權" in k:
            t = ew_to.loc[a:b].sum() / yrs
            print(f"   {k:<26}{c:>7.1%}{v:>7.1%}{s:>7.2f}{md:>8.1%}{t:>8.0%}{'12.0':>8}  各 25%")
        else:
            print(f"   {k:<26}{c:>7.1%}{v:>7.1%}{s:>7.2f}{md:>8.1%}{0:>8.0%}{'0.0':>8}")
    for k in H:
        m = monthly(S[k], a, b)
        for bk in ("四檔等權（月底再平衡）", "SMH 買進持有", "QQQ 買進持有"):
            d = (m - monthly(S[bk], a, b)).dropna()
            print(f"      {k} − {bk}：月超額平均 {d.mean():+.2%}、t={d.mean() / d.std() * np.sqrt(len(d)):+.2f}、勝月 {(d > 0).mean():.0%}、n={len(d)} 月")
    print()

# 逐年：輪動 vs 等權 vs SMH（看優勢集中在哪幾年）
print("[逐年報酬]  年份   M12    M12-1   等權    SMH    QQQ    VOO    IGV   M12 年底持有")
yr = lambda rr: ((1 + rr.loc[START:].dropna()).groupby(rr.loc[START:].dropna().index.year).prod() - 1)
tab = pd.DataFrame({k: yr(v) for k, v in S.items()})
k1, k2 = list(H)
for y, row in tab.iterrows():
    hy = H[k1].loc[str(y)].dropna()
    print(f"            {y}  {row[k1]:>+6.0%} {row[k2]:>+6.0%} {row['四檔等權（月底再平衡）']:>+6.0%} {row['SMH 買進持有']:>+6.0%} {row['QQQ 買進持有']:>+6.0%} {row['VOO 買進持有']:>+6.0%} {row['IGV 買進持有']:>+6.0%}   {hy.iloc[-1] if len(hy) else ''}")
print(f"\n   M12 贏等權的年數 {(tab[k1] > tab['四檔等權（月底再平衡）']).sum()} / {len(tab)}；贏 SMH 的年數 {(tab[k1] > tab['SMH 買進持有']).sum()} / {len(tab)}")
print(f"   M12-1 贏等權的年數 {(tab[k2] > tab['四檔等權（月底再平衡）']).sum()} / {len(tab)}；贏 SMH 的年數 {(tab[k2] > tab['SMH 買進持有']).sum()} / {len(tab)}")
print("\n四檔日報酬相關（策略起點→）：")
print(R.loc[START:].corr().round(2).to_string())
