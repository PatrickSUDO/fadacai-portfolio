"""U3 板塊相關性加速當「延後一天買」旗標 — 2026-11-10

問題：板塊之間的相關性突然升高（大家一起動）常被說成「系統性賣壓開始」。能不能當成買單的煞車——旗標亮時把買單延後一天或五天？

設計（事先寫定，X 只試三個）：
- 九檔板塊 SPDR（XLB XLE XLF XLI XLK XLP XLU XLV XLY，1998-12→）日報酬，36 對的 20 日、60 日滾動相關各自取平均
- 旗標（t 日收盤可知）= 20 日平均相關 > X × 60 日平均相關，X ∈ {1.10, 1.17, 1.25}
- 量測旗標日收盤之後 SPY、SMH 的次 1／5／20 日報酬（收盤對收盤），對照非旗標日
- 去叢集：旗標日 5 個交易日內只算第一次；對照組次 1 日用全部非旗標日、次 5／20 日取非旗標日每 5 日取一（避免重疊樣本灌水）
- t 值 = Welch 兩樣本；20 日窗樣本仍重疊，另列「重疊校正 t」＝ t ÷ 2（√(20/5)）
- 「延後買有沒有好處」＝旗標日之後的次 1／5 日報酬是否為負（延後 = 少掉那段報酬；為正代表延後反而買貴）
- 另報旗標日與 VIX 收盤 ≥25 的重疊比例；分 1999–2009、2010→

已知缺陷：相關性比值在 60 日平均相關很低時（如 2017、2021 部分時段）分母小、旗標容易亮，亮的未必是「恐慌」；
板塊 SPDR 只有九檔（2015 後新增的 XLRE／XLC 不含）；SMH 2000-05 起；未計交易成本；只看指數層、未測個股。

首跑結論（2026-11-10，1999-03→2026-11-09，6,951 個交易日）：
- 旗標頻率：X=1.10 亮 25.5% 的日子（去叢集 368 次）、1.17 亮 14.5%（222 次）、1.25 亮 6.7%（110 次）。
- 次 1 日（延後一天）：三個 X、兩檔、兩段共 18 格，旗標 vs 非旗標 t 值全在 −1.2 到 +0.8 之間。
  全期 SPY 旗標後次 1 日 +0.00%／−0.03%／−0.00%（非旗標 +0.04–0.05%）；2010→ SPY 三個 X 都是 +0.05–0.06% = 與非旗標相同。
- 次 5 日（延後五天）：2010→ SPY 旗標後 +0.39%／+0.34%／+0.15%（非旗標 +0.23–0.29%），延後五天買得更便宜的比例 31–39%（任意日 39%）＝延後反而買貴。
  唯一像訊號的是 X=1.25 的 SMH：全期次 5 日 −0.65%（n=102，t0 −1.15、對非旗標 t −1.68），來源是 1999–2009 的 35 次（−1.69%）；2010→ 只剩 −0.11%（n=67）。
- 次 20 日：2010→ X=1.10 SMH 旗標後 +3.07% vs 非旗標 +1.77%（校正 t +1.07）＝方向跟「煞車」相反；X=1.17／1.25 無差別。
- 與 VIX ≥25 的重疊：旗標日中 VIX≥25 佔 19–21%，全部日子本來就 19% → 旗標與恐慌無關。
  旗標日有 18% 出現在 60 日平均相關 < 0.30 的低相關期（全部日子 8%），2017 年 86 天、2010 年 0 天——它量到的是「低相關期的均值回歸」不是賣壓。
- 判讀：**不成立**。延後一天沒有可量測的好處；延後五天在 2010 後平均買貴 0.1–0.4%。三個 X 的符號不一致、分段不一致，不做旗標。
"""
import itertools
import numpy as np, pandas as pd, yfinance as yf, warnings
warnings.filterwarnings("ignore")

SECT = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
XS = (1.10, 1.17, 1.25)
HZ = (1, 5, 20)
raw = yf.download(SECT + ["SPY", "SMH", "^VIX"], period="max", progress=False, auto_adjust=True)["Close"]
R = raw[SECT].pct_change().dropna(how="any"); idx = R.index
pairs = list(itertools.combinations(SECT, 2))
c20 = pd.concat([R[a].rolling(20).corr(R[b]) for a, b in pairs], axis=1).mean(axis=1)
c60 = pd.concat([R[a].rolling(60).corr(R[b]) for a, b in pairs], axis=1).mean(axis=1)
ratio = (c20 / c60).where(c60.notna())
vix = raw["^VIX"].reindex(idx).ffill()
valid = ratio.dropna().index

def decluster(days, gap=5):
    keep = []; last = None
    for d in days:
        i = idx.get_loc(d)
        if last is None or i - last > gap:
            keep.append(d); last = i
    return pd.DatetimeIndex(keep)

def welch(a, b):
    a = a.dropna(); b = b.dropna()
    if len(a) < 3 or len(b) < 3: return np.nan
    return (a.mean() - b.mean()) / np.sqrt(a.var() / len(a) + b.var() / len(b))

def tzero(a):
    a = a.dropna(); return a.mean() / a.std() * np.sqrt(len(a)) if len(a) > 2 else np.nan

print(f"U3 板塊相關性加速旗標 — 九檔板塊 SPDR 共同資料 {idx[0].date()} → {idx[-1].date()}；旗標可算起 {valid[0].date()}")
print(f"36 對平均相關：20 日 平均 {c20.mean():.2f}（5–95 分位 {c20.quantile(.05):.2f}–{c20.quantile(.95):.2f}）；60 日 平均 {c60.mean():.2f}（最低 {c60.min():.2f}）")
print("去叢集 5 日；括號＝勝率；t＝旗標 vs 非旗標 Welch；t0＝旗標組平均對 0\n")

fwd = {}
for sym in ("SPY", "SMH"):
    s = raw[sym].reindex(idx)
    fwd[sym] = {h: (s.shift(-h) / s - 1) for h in HZ}

PERIODS = (("全期", valid[0], None), ("1999–2009", valid[0], "2009-12-31"), ("2010→", "2010-01-01", None))
for X in XS:
    flag = (ratio > X).reindex(valid)
    print(f"===== X = {X:.2f}：旗標日 {int(flag.sum())} / {len(flag)}（{flag.mean():.1%}）=====")
    for lab, a, b in PERIODS:
        f = flag.loc[a:b]
        ev = decluster(f[f].index); non_all = f[~f].index; non = non_all[::5]
        vx = vix.reindex(f.index)
        print(f" [{lab}] 旗標日 {int(f.sum())}（{f.mean():.1%}）→ 去叢集事件 {len(ev)}；對照 非旗標日 {len(non_all)}（次 5／20 日每 5 日取一 = {len(non)}）；"
              f"旗標日中 VIX≥25 佔 {(vx[f] >= 25).mean():.0%}（全部日子 VIX≥25 佔 {(vx >= 25).mean():.0%}）；"
              f"VIX≥25 的日子中旗標亮 {f[vx >= 25].mean():.0%}")
        for sym in ("SPY", "SMH"):
            parts = []
            for h in HZ:
                x = fwd[sym][h].reindex(ev).dropna(); y = fwd[sym][h].reindex(non_all if h == 1 else non).dropna()
                t = welch(x, y); adj = f"／校正 {t / 2:+.2f}" if h == 20 else ""
                parts.append(f"次{h:>2}日 旗標 {x.mean():+.2%}（{(x > 0).mean():.0%}，n={len(x)}，t0={tzero(x):+.2f}）vs 非旗標 {y.mean():+.2%}（{(y > 0).mean():.0%}，n={len(y)}） t={t:+.2f}{adj}")
            print(f"   {sym}  " + "\n        ".join(parts))
    print()

# 延後買的直接量法：旗標日下單 vs 延後 1／5 日下單，成交價差（負＝延後買得更便宜）
print("===== 延後買的直接量法：延後 d 日成交價 ÷ 旗標日收盤 − 1（負＝延後較便宜；對照＝任意日延後）=====")
for X in XS:
    flag = (ratio > X).reindex(valid)
    for lab, a, b in PERIODS:
        f = flag.loc[a:b]; ev = decluster(f[f].index)
        row = []
        for sym in ("SPY", "SMH"):
            for h in (1, 5):
                x = fwd[sym][h].reindex(ev).dropna(); base = fwd[sym][h].reindex(f.index).dropna()
                row.append(f"{sym} 延後{h}日 {x.mean():+.2%}（較便宜的比例 {(x < 0).mean():.0%}；任意日 {base.mean():+.2%}／{(base < 0).mean():.0%}）")
        print(f"  X={X:.2f} [{lab}] n={len(ev)}  " + "；".join(row))

# 旗標亮的年份分布（看是不是集中在少數年）
print("\n===== 旗標日逐年分布（X=1.17）=====")
flag = (ratio > 1.17).reindex(valid)
by = flag.groupby(flag.index.year).sum().astype(int)
print("  " + "  ".join(f"{y}:{n}" for y, n in by.items()))
lowc = c60.reindex(valid) < 0.3
print(f"  旗標日中 60 日平均相關 < 0.30（分母小）的比例：{lowc[flag].mean():.0%}（全部日子 {lowc.mean():.0%}）")
