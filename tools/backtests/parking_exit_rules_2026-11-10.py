"""U1 停泊池（VOO）要不要設退場條件 — 2026-11-10

問題：閒置現金停泊在 VOO（R33）。若加「跌破長均線就退到 T-bill」之類的退場條件，會不會比一直抱著好？
殖利率曲線倒掛時要不要更早退？VIX 飆高時要不要強制買回（cf-vix-spike 的反向保險）？

設計（事先寫定，不調參）：
- 標的 SPY 1993→（VOO 2010 才上市，用 SPY 代）；殖利率曲線 = ^TNX（10 年）− ^IRX（13 週 T-bill）
- 規則全部「月底收盤判定 → 次月第一個交易日起的部位」（daily shift(1)，不偷看）：
    A  SMA200：月底收盤 > 200 日均線才持有
    B  SMA200 與曲線同時為負才出場：月底收盤 < SMA200 且 10 年 ≤ 3 個月才出場，任一為正就持有
    C  10 個月均線：月底收盤 > 近 10 個月月底收盤均值才持有
- 覆寫 +V：VIX 收盤 ≥30 → 次日起強制持有至少 60 個交易日（期間再出現 ≥30 就重新起算）；套在 A／B／C 上
- 出場放 T-bill（^IRX/252）；不計交易成本與買賣價差
- 報 CAGR／波動／Sharpe（超額報酬對 T-bill）／最大回撤／在市比例／每年切換次數；分全期、1994–2009、2010→
- 專段：2022-07→2024-12 殖利率倒掛期間各規則在市比例與該段報酬

已知缺陷：^IRX 是貼現率不是債券等值殖利率（差 10–25bp，腳本列出月底判定會翻幾次）；SPY 1993→ 只含三次大空頭
（2000、2008、2022）+ 2020 急跌，A／C 的回撤優勢全靠 2000 與 2008 兩次；無成本、無稅。

首跑結論（2026-11-10，SPY 1994-01→2026-11-09）：
- 全期看起來像「免費砍半回撤」：買進持有 CAGR 10.8%／MDD −55.2%／Sharpe 0.51；A 10.7%／−24.1%／0.66；C 10.0%／−24.1%／0.61。
  但好處全在 1994–2009（A 11.9% vs 7.5%、MDD −19% vs −55%，靠 2000–02 與 2008 兩次長空頭）。
- 2010→ 反過來：買進持有 14.0%／MDD −33.7%／Sharpe 0.77；A 9.5%／−24.1%／0.66；C 8.2%／−24.1%／0.56。
  2010→ A 出場 14 段只有 1 段躲對（出場期間 SPY 下跌）、13 段賣錯，出場期間 SPY 平均 +5.3%；C 15 段躲對 1 段。
- 「SMA200 與曲線同時為負才出場」（B）33 年只出場 6 段、98% 時間在市 ≈ 買進持有（全期 10.6%／−55.2%／0.51）；
  2008 年曲線為正所以全程在場內。6 段中 2 段躲對（2000-10→2001-01 −4.3%、2020-03 −12.5%）、4 段賣錯（+6 到 +9%）。
- 倒掛期 2022-07→2024-12（曲線為負日數 82%，資料上 2022-11-10 起）：買進持有 +61.1%；A／C 在市 77%、+30.7%；
  B 在市 93%、+40.0%（2023-01 與 2023-11 兩次出場各錯過 +6.3%、+9.1%）。倒掛本身不是退場理由。
- VIX ≥30 覆寫：2010→ 把 A 從 9.5% 拉回 13.4%、C 從 8.2% 拉回 13.1%（仍低於買進持有 14.0%，MDD 回到 −33.7%）；
  1994–2009 反而把 A 從 11.9%／−19% 打回 9.7%／−50%（2008-09→2009-03 VIX 連續 ≥30 = 整段熊市被強制留在場內）。
  覆寫的效果就是「把濾網關掉」，加完 ≈ 買進持有。
- 判讀：**不成立**。均線退場只在「長而慢的空頭」有用，2010 後四次回檔（2011／2018／2020／2022）都是 V 型或月底才破線，
  月底判定賣在低點、買回在更高。加曲線條件 ≈ 沒有規則；加 VIX 覆寫 ≈ 取消規則。停泊池維持一直抱（R33 不動）。
"""
import numpy as np, pandas as pd, yfinance as yf, warnings
warnings.filterwarnings("ignore")

START = "1994-01-01"
raw = yf.download(["SPY", "^TNX", "^IRX", "^VIX"], period="max", progress=False, auto_adjust=True)["Close"]
px = raw["SPY"].dropna(); idx = px.index
tnx = raw["^TNX"].reindex(idx).ffill(); irx = raw["^IRX"].reindex(idx).ffill(); vix = raw["^VIX"].reindex(idx).ffill()
cash = (irx / 100 / 252).fillna(0)
r = px.pct_change()

ym = pd.Series(idx.to_period("M"), index=idx)
is_me = (ym != ym.shift(-1)); is_me.iloc[-1] = False          # 每月最後一個交易日（資料最後一列若月份未完不算）
me = idx[is_me.values]

sma200 = px.rolling(200).mean()
trend_d = (px > sma200).where(sma200.notna())
curve_d = (tnx > irx).where(tnx.notna() & irx.notna())
m = px[me]; ma10 = m.rolling(10).mean()
trend10_m = (m > ma10).where(ma10.notna())

def to_daily(hold_m):
    """月底判定 → 次一交易日起生效。"""
    return hold_m.astype(float).reindex(idx).ffill().shift(1)

W = {
    "買進持有": pd.Series(1.0, index=idx),
    "A SMA200（月底判定）": to_daily(trend_d[me]),
    "B SMA200 與曲線同時為負才出場": to_daily(((trend_d[me] == 1) | (curve_d[me] == 1)).where(trend_d[me].notna() & curve_d[me].notna())),
    "C 10 個月均線": to_daily(trend10_m),
}
forced = (vix >= 30).astype(float).rolling(60).max().shift(1).fillna(0)   # t 日 ≥30 → t+1…t+60 強制持有
for k in ("A SMA200（月底判定）", "B SMA200 與曲線同時為負才出場", "C 10 個月均線"):
    W[k.split(" ")[0] + "+V " + k.split(" ", 1)[1] + " ＋VIX≥30 買回 60 日"] = np.maximum(W[k], forced).where(W[k].notna())

def metrics(w, a, b=None):
    w = w.loc[a:b]; rr = (r * w + cash * (1 - w)).loc[a:b].dropna(); w = w.reindex(rr.index)
    yrs = len(rr) / 252; eq = (1 + rr).cumprod()
    cagr = eq.iloc[-1] ** (1 / yrs) - 1; vol = rr.std() * np.sqrt(252)
    sh = (rr - cash.reindex(rr.index)).mean() / rr.std() * np.sqrt(252)
    mdd = (eq / eq.cummax() - 1).min()
    return cagr, vol, sh, mdd, w.mean(), (w.diff().abs() > 0).sum() / yrs, eq.iloc[-1] - 1

print(f"U1 停泊池退場條件 — SPY {idx[0].date()} → {idx[-1].date()}；統計起點 {START}（均線暖身後）")
print("訊號月底收盤判定 → 次月第一個交易日起部位；出場放 T-bill（^IRX）；無交易成本\n")
for lab, a, b in (("全期 1994→", START, None), ("1994–2009", START, "2009-12-31"), ("2010→", "2010-01-01", None)):
    print(f"[{lab}]  {'規則':<40}{'CAGR':>7}{'波動':>7}{'Sharpe':>7}{'MDD':>8}{'在市%':>7}{'切換/年':>8}")
    for k, w in W.items():
        c, v, s, md, im, sw, _ = metrics(w, a, b)
        print(f"   {k:<40}{c:>7.1%}{v:>7.1%}{s:>7.2f}{md:>8.1%}{im:>7.0%}{sw:>8.1f}")
    print()

a, b = "2022-07-01", "2024-12-31"
inv = (curve_d.loc[a:b] == 0)
invd = curve_d[curve_d == 0].loc["2022-01-01":"2025-12-31"]
print(f"[殖利率倒掛期 {a} → {b}]  曲線為負（10 年 ≤ 3 個月）日數比例 {inv.mean():.0%}；"
      f"資料上倒掛首日 {invd.index[0].date()}、末日 {invd.index[-1].date()}")
print(f"   {'規則':<40}{'在市%':>7}{'區間報酬':>10}{'區間 MDD':>10}")
for k, w in W.items():
    c, v, s, md, im, sw, tot = metrics(w, a, b)
    print(f"   {k:<40}{im:>7.0%}{tot:>10.1%}{md:>10.1%}")

# B 規則出場段落（供人檢視）
wB = W["B SMA200 與曲線同時為負才出場"].loc[START:]
out = (wB == 0); grp = (out != out.shift()).cumsum()
print("\n[B 規則出場段落]（次日生效日 → 回場前一日；SPY 該段報酬）")
for _, g in out[out].groupby(grp[out]):
    d0, d1 = g.index[0], g.index[-1]
    print(f"   {d0.date()} → {d1.date()}  {len(g):>4} 日  SPY {(1 + r.loc[d0:d1]).prod() - 1:+.1%}")
for k in ("A SMA200（月底判定）", "C 10 個月均線"):
    w = W[k].loc[START:]; o = (w == 0); g2 = (o != o.shift()).cumsum()
    segs = [(g.index[0], g.index[-1]) for _, g in o[o].groupby(g2[o])]
    rets = np.array([(1 + r.loc[d0:d1]).prod() - 1 for d0, d1 in segs])
    post = [s for s in segs if s[0] >= pd.Timestamp("2010-01-01")]
    rp = np.array([(1 + r.loc[d0:d1]).prod() - 1 for d0, d1 in post])
    print(f"[{k}] 出場 {len(segs)} 段；出場期間 SPY 下跌（＝躲對）{(rets < 0).sum()} 段、上漲（＝賣錯）{(rets > 0).sum()} 段；"
          f"2010→ {len(post)} 段中躲對 {(rp < 0).sum()}、賣錯 {(rp > 0).sum()}，出場期間 SPY 平均 {rp.mean():+.1%}")

# 覆寫觸發概況
tr = (vix >= 30).loc[START:]
ep = ((forced.loc[START:] == 1) & (forced.loc[START:].shift() != 1)).sum()
print(f"\n[VIX 覆寫] VIX 收盤 ≥30 日數 {tr.sum()}（{tr.mean():.1%}）；強制持有段落 {ep} 段；強制持有日比例 {forced.loc[START:].mean():.0%}")

# ^IRX 貼現率 vs 債券等值殖利率：月底曲線判定翻幾次
d = irx / 100; bey = 365 * d / (360 - 91 * d) * 100
flip = ((tnx > irx) != (tnx > bey))[me].loc[START:]
print(f"[缺陷檢查] ^IRX 改用債券等值殖利率後，月底曲線正負判定不同的月份：{flip.sum()} / {len(flip)}")
