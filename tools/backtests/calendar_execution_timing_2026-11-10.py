"""U5 月內日期效應（執行時點）— 2026-11-10

問題：月度買單（monthly_grid，每月第 1 個交易日收盤）下在哪一天有差嗎？月底月初效應、選擇權結算週、FOMC 前一日值不值得避開或搶？

設計（事先寫定）：
(i)  月底月初窗 TOM = 每月最後 1 個交易日 + 次月第 1–3 個交易日（共 4 天；日報酬 = 收盤對收盤）。
     窗內 vs 窗外平均日報酬、Welch t，分 1993–2009、2010–2019、2020→；另單獨報「每月第 1 個交易日」那天的報酬
     （買單在那天收盤成交 → 那天的漲幅是買不到的）。
(ii) 每月固定在第 k 個交易日收盤買進等額並一直持有，k = −2、−1、1…21（負數 = 月底前第幾天；該月交易日不足 k 天 → 用該月最後一天）。
     2010-01 → 最後一個完整月份，期末資產倍數（期末市值 ÷ 總投入）與年化內部報酬率（XIRR，二分法）。
     報最好與最差 k 的差距、相鄰 k 是否平滑（k=1…21 序列的一階自相關、相鄰差 ÷ 全距）、前後半段名次是否一致（Spearman）。
     補充直接量法：第 k 日收盤相對當月第 1 日收盤的平均價差與 t 值（買貴或買便宜多少）。
(iii) 選擇權結算週（每月第三個週五所在的週一到週五）vs 其他日；FOMC 決議日與前一個交易日 vs 其他日（2010→）。
     FOMC 日期 = 例行會議第二天（聲明發布日），2010–2026 共 135 次，寫死在下方：
     2021–2026 於 2026-11-10 對 federalreserve.gov/monetarypolicy/fomccalendars.htm 逐筆核對；2010–2020 憑公開排程記憶寫入、
     未逐筆線上核對（腳本檢查皆為交易日且落在週二到週四）。不含臨時會議（2020-03-03、2020-03-15；原訂 2020-03-18 例會取消）
     與 2025-08-22 書面表決。

已知缺陷：日曆效應是被挖掘最多的一類（多重比較）；每月只有一個觀測，2010→ 約 200 個月，t 值門檻應高於 2；
SMH 2000-05 起、QQQ 1999-03 起；未計交易成本；(ii) 各 k 的差距含「晚買少抱幾天」的機械成分（XIRR 已按日計，仍有殘差）。

首跑結論（2026-11-10，SPY 1993-01→2026-10、QQQ 1999-03→、SMH 2000-06→）：
(i)  四天窗整體：SPY 窗內 +7.9bp vs 窗外 +4.0bp（全期 t +1.24）；2010–2019 +6.1 vs +5.3（t +0.18）、2020→ +9.3 vs +5.6（t +0.50）。QQQ／SMH 同樣 t < 1.3。
     效應集中在「第 1 個交易日」：SPY 全期 +21.9bp（n=405，t0 +3.54），但 1993–2009 +29.1bp（t0 +3.02）→ 2010–2019 +14.6bp（t0 +1.47）→ 2020→ +14.9bp（t0 +1.19）。
     QQQ 第 1 日 2010–2019 +17.8bp、2020→ +20.0bp；SMH +21.3bp、+13.6bp（t0 全 < 1.6）。月底最後一日 SPY −4.5bp（無）。
     對月度買單的含意：下在第 1 日收盤 = 買不到當天那段。2010→ 前月最後一日收盤比第 1 日收盤便宜 SPY 0.13%（t −1.7）、QQQ 0.17%（t −1.8）、SMH 0.14%（t −1.0）。
(ii) 2010-01→2026-10 每個 k 202 筆：XIRR 全距 SPY 5bp（14.34–14.39%）、QQQ 5bp（18.71–18.76%）、SMH 8bp（28.03–28.11%）。
     期末倍數全距 SPY 0.96%、QQQ 1.18%、SMH 1.30%，且隨 k 單調下降（k=1 SPY 3.832 → k=21 3.797）＝早買多抱幾天的漂移，不是日期效應。
     序列平滑（k=1…21 一階自相關 +0.75 到 +0.85、相鄰差 = 全距的 13–16%），前後半段名次 Spearman +0.63 到 +0.73（三檔都是 k≈12 最差、k≈16 最好）
     ——形狀是穩定的（月中結算週偏弱），但幅度只有 5–8bp 年化，沒有可執行的差距。
(iii) 結算週：1993–2009 SPY 結算週 +6.7bp vs 其他 +2.8bp（t +0.83）；2010→ 反過來 +2.1bp vs +6.9bp（t −1.29）；QQQ／SMH 2010→ 同為偏弱（t −1.39／−1.08）。兩段符號相反。
     FOMC 前一日（2010→ 134 次）：SPY +3.0bp vs 其他日 +5.7bp（t −0.30）、QQQ +6.5bp（t −0.05）、SMH +6.2bp（t −0.25）＝沒有東西。
     FOMC 決議日：SPY +11.8bp（t +0.63）、QQQ +23.3bp（t +1.37）、SMH +39.1bp（t +1.78），SMH 的數字幾乎全來自 2020→（+78.5bp，n=54）；2010–2019 只有 +12.6bp（t +0.34）。
判讀：四天窗、結算週、FOMC 前一日＝**不成立**；固定買進日＝**不成立**（k 之間無可執行差距）；
     「第 1 個交易日偏強」＝**證據不足**（全期顯著、2010 後幅度減半且單段 t < 2，但三檔三段符號全同）。
     實務含意只有一條、而且很小：月度買單若現金前一天就到位，下在前月最後一日收盤比下在第 1 日收盤平均便宜約 0.13–0.17%（每筆 $3k 約 $4–5）；不值得為此改流程。
"""
import numpy as np, pandas as pd, yfinance as yf, warnings
warnings.filterwarnings("ignore")

SYMS = ["SPY", "QQQ", "SMH"]
FOMC = """2010-01-27 2010-03-16 2010-04-28 2010-06-23 2010-08-10 2010-09-21 2010-11-03 2010-12-14
2011-01-26 2011-03-15 2011-04-27 2011-06-22 2011-08-09 2011-09-21 2011-11-02 2011-12-13
2012-01-25 2012-03-13 2012-04-25 2012-06-20 2012-08-01 2012-09-13 2012-10-24 2012-12-12
2013-01-30 2013-03-20 2013-05-01 2013-06-19 2013-07-31 2013-09-18 2013-10-30 2013-12-18
2014-01-29 2014-03-19 2014-04-30 2014-06-18 2014-07-30 2014-09-17 2014-10-29 2014-12-17
2015-01-28 2015-03-18 2015-04-29 2015-06-17 2015-07-29 2015-09-17 2015-10-28 2015-12-16
2016-01-27 2016-03-16 2016-04-27 2016-06-15 2016-07-27 2016-09-21 2016-11-02 2016-12-14
2017-02-01 2017-03-15 2017-05-03 2017-06-14 2017-07-26 2017-09-20 2017-11-01 2017-12-13
2018-01-31 2018-03-21 2018-05-02 2018-06-13 2018-08-01 2018-09-26 2018-11-08 2018-12-19
2019-01-30 2019-03-20 2019-05-01 2019-06-19 2019-07-31 2019-09-18 2019-10-30 2019-12-11
2020-01-29 2020-04-29 2020-06-10 2020-07-29 2020-09-16 2020-11-05 2020-12-16
2021-01-27 2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15
2022-01-26 2022-03-16 2022-05-04 2022-06-15 2022-07-27 2022-09-21 2022-11-02 2022-12-14
2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13
2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18
2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10
2026-01-28 2026-03-18 2026-04-29 2026-06-17 2026-07-29 2026-09-16 2026-10-28 2026-12-09""".split()

raw = yf.download(SYMS, period="max", progress=False, auto_adjust=True)["Close"]
cal = raw["SPY"].dropna().index
C = raw.reindex(cal); R = C.pct_change()

# 交易日在月內的序號：dom = 1,2,…；rev = −1（最後一天）,−2,…
ym = pd.Series(cal.to_period("M"), index=cal)
dom = ym.groupby(ym).cumcount() + 1
rev = -(ym.groupby(ym).cumcount(ascending=False) + 1)
last_full = ym.iloc[-1] - 1                                                    # 最後一個完整月份（資料當月一律視為未完）
complete = ym <= last_full
rev = rev.where(complete)                                                        # 未完月份不知道誰是月底

def welch(a, b):
    a = a.dropna(); b = b.dropna()
    return (a.mean() - b.mean()) / np.sqrt(a.var() / len(a) + b.var() / len(b)) if len(a) > 2 and len(b) > 2 else np.nan

def t0(a):
    a = a.dropna(); return a.mean() / a.std() * np.sqrt(len(a)) if len(a) > 2 else np.nan

PER3 = (("1993–2009", None, "2009-12-31"), ("2010–2019", "2010-01-01", "2019-12-31"), ("2020→", "2020-01-01", None), ("全期", None, None))
print(f"U5 月內日期效應 — 資料 {cal[0].date()} → {cal[-1].date()}；最後完整月份 {last_full}（QQQ {raw['QQQ'].dropna().index[0].date()} 起、SMH {raw['SMH'].dropna().index[0].date()} 起）")

# ---------- (i) TOM ----------
tom = ((rev == -1) | (dom <= 3)) & complete
d1 = (dom == 1) & complete
print("\n===== (i) 月底月初窗 TOM（月底最後 1 日 + 月初前 3 日）=====  單位：平均日報酬 bp；括號＝勝率")
for sym in SYMS:
    r = R[sym].where(complete)
    for lab, a, b in PER3:
        x = r[tom].loc[a:b].dropna(); y = r[~tom].loc[a:b].dropna(); z = r[d1].loc[a:b].dropna()
        if len(x) < 20: continue
        rest = r[~d1].loc[a:b].dropna()
        share = x.sum() / (x.sum() + y.sum()) if (x.sum() + y.sum()) != 0 else np.nan
        print(f"  {sym} [{lab:<9}] 窗內 {x.mean() * 1e4:>+6.1f}bp（{(x > 0).mean():.0%}，n={len(x)}）窗外 {y.mean() * 1e4:>+5.1f}bp（{(y > 0).mean():.0%}，n={len(y)}）t={welch(x, y):+.2f}"
              f"｜窗內佔日數 {len(x) / (len(x) + len(y)):.0%}、佔總算術報酬 {share:.0%}"
              f"｜第 1 個交易日 {z.mean() * 1e4:>+6.1f}bp（{(z > 0).mean():.0%}，n={len(z)}，t0={t0(z):+.2f}，對其他日 t={welch(z, rest):+.2f}）")
print("  --- TOM 四天各自的平均（全期／2010→）---")
for sym in SYMS:
    r = R[sym].where(complete); parts = []
    for lab, mask in (("月底最後1日", rev == -1), ("第1日", dom == 1), ("第2日", dom == 2), ("第3日", dom == 3)):
        x = r[mask].dropna(); x2 = x.loc["2010-01-01":]
        parts.append(f"{lab} {x.mean() * 1e4:+.1f}bp(t0 {t0(x):+.1f})／{x2.mean() * 1e4:+.1f}bp(t0 {t0(x2):+.1f})")
    print(f"  {sym}  " + "；".join(parts))

# ---------- (ii) 固定買進日 ----------
KS = [-2, -1] + list(range(1, 22))
def buy_dates(k, a, b):
    out = []
    months = [m for m in ym[complete].unique() if (a is None or m >= pd.Period(a, "M")) and (b is None or m <= pd.Period(b, "M"))]
    for mth in months:
        days = cal[(ym == mth).values]
        out.append(days[k] if k < 0 else days[min(k, len(days)) - 1])
    return pd.DatetimeIndex(out)

def xirr(dates, amounts):
    t = np.array([(d - dates[0]).days / 365.0 for d in dates]); a = np.array(amounts, float)
    f = lambda r_: (a / (1 + r_) ** t).sum()
    lo, hi = -0.9, 2.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0: hi = mid
        else: lo = mid
    return (lo + hi) / 2

def dca(sym, k, a, b, end):
    bd = buy_dates(k, a, b); px = C[sym]
    units = (1 / px.loc[bd]).sum(); fv = units * px.loc[end]
    return fv / len(bd), xirr(list(bd) + [end], [-1.0] * len(bd) + [fv]), len(bd)

print("\n===== (ii) 每月固定第 k 個交易日收盤買進等額、一直持有 =====")
END = cal[-1]
res = {}
for sym in SYMS:
    rows = {k: dca(sym, k, "2010-01", None, END) for k in KS}
    res[sym] = rows
    irr = pd.Series({k: v[1] for k, v in rows.items()}); mult = pd.Series({k: v[0] for k, v in rows.items()})
    seq = irr.loc[list(range(1, 22))]
    ac1 = seq.autocorr(1); adj = seq.diff().abs().mean(); rng = irr.max() - irr.min()
    # 前後半段名次一致性
    h1 = pd.Series({k: dca(sym, k, "2010-01", "2017-12", cal[cal <= "2017-12-31"][-1])[1] for k in KS})
    h2 = pd.Series({k: dca(sym, k, "2018-01", None, END)[1] for k in KS})
    rho = h1.rank().corr(h2.rank())
    print(f"  {sym}  2010-01 → {last_full}，每個 k {rows[1][2]} 筆；期末 {END.date()}")
    print("     k    : " + " ".join(f"{k:>6}" for k in KS))
    print("     倍數  : " + " ".join(f"{mult[k]:>6.3f}" for k in KS))
    print("     XIRR : " + " ".join(f"{irr[k]:>6.2%}" for k in KS))
    print(f"     最好 k={irr.idxmax()}（{irr.max():.2%}，倍數 {mult[irr.idxmax()]:.3f}）、最差 k={irr.idxmin()}（{irr.min():.2%}，倍數 {mult[irr.idxmin()]:.3f}）；"
          f"XIRR 全距 {rng * 1e4:.0f}bp、倍數全距 {(mult.max() / mult.min() - 1):.2%}；k=1 排名 {int(irr.rank(ascending=False)[1])}/{len(KS)}（{irr[1]:.2%}）")
    print(f"     平滑度：k=1…21 一階自相關 {ac1:+.2f}；相鄰 k 平均絕對差 {adj * 1e4:.1f}bp（= 全距的 {adj / rng:.0%}）；XIRR 對 k 的線性斜率 {np.polyfit(range(1, 22), seq.values, 1)[0] * 1e4:+.2f}bp／日")
    print(f"     前後半段名次一致性（2010–2017 vs 2018→ 各自 XIRR 的 Spearman）：{rho:+.2f}；前半最好 k={h1.idxmax()}、後半最好 k={h2.idxmax()}；前半最差 k={h1.idxmin()}、後半最差 k={h2.idxmin()}")

print("  --- 直接量法：第 k 日收盤 ÷ 當月第 1 日收盤 − 1 的月平均（2010→；正＝比第 1 日買貴）---")
months = [m for m in ym[complete].unique() if m >= pd.Period("2010-01", "M")]
for sym in SYMS:
    px = C[sym]; parts = []
    base = pd.Series({m: px.loc[cal[(ym == m).values][0]] for m in months})
    prev_last = pd.Series({m: px.loc[cal[(ym == (m - 1)).values][-1]] for m in months})
    x = (prev_last / base - 1); parts.append(f"前月最後1日 {x.mean():+.2%}(t {t0(x):+.1f})")
    for k in (2, 3, 5, 10, 15, 20, -1):
        pk = pd.Series({m: px.loc[(lambda d: d[k] if k < 0 else d[min(k, len(d)) - 1])(cal[(ym == m).values])] for m in months})
        x = pk / base - 1
        parts.append(f"k={k} {x.mean():+.2%}(t {t0(x):+.1f})")
    print(f"  {sym}  " + "；".join(parts) + f"   n={len(months)} 月")

# ---------- (iii) 結算週與 FOMC ----------
print("\n===== (iii) 選擇權結算週（第三個週五所在週）vs 其他日 =====  平均日報酬 bp")
days = pd.Series(cal, index=cal)
fri3 = set()
for m in ym.unique():
    f = [d for d in pd.date_range(m.start_time, m.end_time, freq="D") if d.weekday() == 4]
    fri3.add(f[2].normalize())
wk_fri = days.apply(lambda d: (d + pd.Timedelta(days=4 - d.weekday())).normalize())
opex = wk_fri.isin(fri3)
for sym in SYMS:
    r = R[sym]
    for lab, a, b in (("1993–2009", None, "2009-12-31"), ("2010→", "2010-01-01", None), ("全期", None, None)):
        x = r[opex].loc[a:b].dropna(); y = r[~opex].loc[a:b].dropna()
        if len(x) < 20: continue
        wk = (1 + r.loc[a:b].dropna()).groupby(wk_fri.reindex(r.loc[a:b].dropna().index)).prod() - 1
        wx = wk[wk.index.isin(fri3)]; wy = wk[~wk.index.isin(fri3)]
        print(f"  {sym} [{lab:<9}] 結算週 {x.mean() * 1e4:>+5.1f}bp（n={len(x)}）其他 {y.mean() * 1e4:>+5.1f}bp（n={len(y)}）t={welch(x, y):+.2f}"
              f"｜以週為單位：結算週 {wx.mean():+.2%}（{(wx > 0).mean():.0%}，n={len(wx)}）其他週 {wy.mean():+.2%}（{(wy > 0).mean():.0%}，n={len(wy)}）t={welch(wx, wy):+.2f}")

print("\n===== (iii) FOMC 決議日與前一個交易日 vs 其他日（2010→）=====  平均日報酬 bp")
fomc = pd.DatetimeIndex(FOMC)
bad = [d.date() for d in fomc if d <= cal[-1] and (d not in cal or d.weekday() not in (1, 2, 3))]
fomc = fomc[fomc.isin(cal)]
print(f"  清單 {len(FOMC)} 次、落在資料期內 {len(fomc)} 次；檢查不通過（非交易日或非週二到週四）：{bad if bad else '無'}")
pos = np.array([cal.get_loc(d) for d in fomc])
day0 = pd.Series(False, index=cal); day0.iloc[pos] = True
pre = pd.Series(False, index=cal); pre.iloc[pos - 1] = True
for sym in SYMS:
    r = R[sym]
    for lab, a, b in (("2010–2019", "2010-01-01", "2019-12-31"), ("2020→", "2020-01-01", None), ("2010→", "2010-01-01", None)):
        rr = r.loc[a:b].dropna(); p = rr[pre.reindex(rr.index)]; z = rr[day0.reindex(rr.index)]; o = rr[~(pre | day0).reindex(rr.index)]
        print(f"  {sym} [{lab:<9}] 前一日 {p.mean() * 1e4:>+6.1f}bp（{(p > 0).mean():.0%}，n={len(p)}，t0={t0(p):+.2f}，對其他日 t={welch(p, o):+.2f}）"
              f"｜決議日 {z.mean() * 1e4:>+6.1f}bp（{(z > 0).mean():.0%}，n={len(z)}，t0={t0(z):+.2f}，對其他日 t={welch(z, o):+.2f}）｜其他日 {o.mean() * 1e4:>+5.1f}bp（n={len(o)}）")
