"""qqq_leaps_dip_2026-11-20.py — 網路流傳的「QQQ 單日跌 ≥1% 就買 Delta 0.60、一年以上的 call，賺 50% 就賣、不停損」經不經得起回測？
（2026-11-20 用戶「這合理嗎經的起回測嗎」；原文宣稱勝率約 91%、2.5 萬美元做到 20 萬以上）

資料：QQQ 1999-03→（未還原收盤價定價、還原價當買進持有對照）、^VXN 2001-01→（之前用 QQQ 已實現波動代理）、^IRX。
權利金為 Black-Scholes 估值，無歷史選擇權報價。長天期 IV 用均值回歸期限結構：
    IV(τ) = m + (VXN − m) × (1 − e^{−κτ}) / (κτ)，m = VXN 過去 3 年中位數，κ = 3
2026-11-20 實價校準（Firstrade，QQQ 620.6、VXN 40.2、2028-01-21 到期 427 天、履約價 635、delta 0.599）：
IV 26.5%、買賣中價 80.08 = 現價 12.9%、買賣價差 4.7%（單邊 2.3%）。另跑「IV 直接等於 VXN」當敏感度。
單邊成本預設 1.5%（平靜日約 1%、大跌日約 2.3%）。未建模：履約價偏斜隨現價移動、提前履約、零股口數（組合模擬允許小數口）。

首跑結論（2026-11-20）：
- 91% 勝率只在多頭段成立：2010–2019 88%、2023→ 98%；全期（1999→，1,287 筆）67%，1999–2002 43%、2022 58%。
  輸的平均 −76%、三分之二歸零 → 損益兩平勝率約 60%，全期每筆 +11%、PF 1.44。
- 「跌 ≥1% 才買」沒有加分：任意日買同一張 call 勝率 72%、每筆 +20%、PF 2.06——跌 1% 的日子集中在空頭。
- +50% 約等於 QQQ 一年內漲 13%；任意日一年內曾漲 ≥12% 的比例 75%，勝率就是這個基準機率。
- 原文沒寫下注比例，而結果完全由它決定：每次訊號投 5% 且不設上限 → 2000、2008、2022 三次都買到現金用完、淨值歸零；
  「2.5 萬 → 20 萬」只有 2023 起算、不設上限重押才湊得出（7 倍、途中回撤 −78%）。
- 加「在手權利金 ≤ 淨值 20%」上限後變成股票替代結構：2010→ 11.4 倍／回撤 −29% vs QQQ 15.4 倍／−35%；上限 30% 是 26 倍／−39%
  = 約 1.35 倍曝險的槓桿，不是超額。裁決：不加（同 2026-10-23 LEAPS 股票替代與不開槓桿硬線）。
- 多空濾網（H 段）：事後標籤（一年後 QQQ 收高／收低）勝率 84% vs 21%；當下看得到的 200 日線只分出 69% vs 61%，
  「距一年高點 ≤10%」73% vs「>20%」55%（越跌越買最差，PF 0.77）。濾網後不設上限仍歸零（空頭都從線上、高點附近開始），
  上限 20% 的組合只從 8.8 倍變 9.5 倍。分辨多空頭的價值幾乎全在事後那一段。
- 200／400 日線當開關（I 段，2000-11→）：逐筆線上 PF 2.2–2.6、線下 1.06–1.09。LEAPS 組合上限 20%「只擋進場」
  12 倍／回撤 −25 到 −30% vs 不用開關 9.5 倍／−46%，但 2010→ 無差別（11.3 vs 11.3／10.2 倍，仍輸 QQQ 15.4 倍）；
  「轉空全賣」讓不設上限版不歸零，卻把有上限版報酬砍半。直接持有 QQQ：2000-11→ 200 日線 11.0 倍／−23%、400 日線 14.9 倍／−25%
  vs 買進持有 9.1 倍／−76%，好處全在 2000–2009；2010→ 每年少賺 5.9pp（200）／3.0pp（400）換回撤 −35% → −23／−25%。
  QLD 2010→ 69.9 倍 → 19.4／39.7 倍。= 多年空頭的保險，保費在多頭十年每年 3–6pp；400 優於 200 是事後挑的，差距在噪音內。

用法：python3 tools/backtests/qqq_leaps_dip_2026-11-20.py
"""
import numpy as np, pandas as pd, yfinance as yf, warnings
from statistics import NormalDist
warnings.filterwarnings("ignore")
ND = NormalDist()
Q = 0.006            # QQQ 股息率近似
KAPPA = 3.0

def ncdf(x):
    """Abramowitz-Stegun 7.1.26，誤差 <1.5e-7"""
    x = np.asarray(x, dtype=float); s = np.sign(x); a = np.abs(x) / np.sqrt(2)
    t = 1 / (1 + 0.3275911 * a)
    y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-a * a)
    return 0.5 * (1 + s * y)

def bs_call(S, K, tau, r, sig):
    S = np.asarray(S, float); tau = np.asarray(tau, float); r = np.asarray(r, float); sig = np.asarray(sig, float)
    out = np.maximum(S - K, 0.0)
    ok = tau > 1e-9
    if np.any(ok):
        t = np.where(ok, tau, 1.0); sq = sig * np.sqrt(t)
        d1 = (np.log(S / K) + (r - Q + sig ** 2 / 2) * t) / sq; d2 = d1 - sq
        v = S * np.exp(-Q * t) * ncdf(d1) - K * np.exp(-r * t) * ncdf(d2)
        out = np.where(ok, v, out)
    return out

raw = yf.download(['QQQ', '^VXN', '^IRX', 'QLD'], period='max', progress=False, auto_adjust=False)
px_s = raw['Close']['QQQ'].dropna()
adj_s = raw['Adj Close']['QQQ'].reindex(px_s.index)
qld_s = raw['Adj Close']['QLD'].reindex(px_s.index)
dates = px_s.index; n = len(px_s)
px = px_s.values; ret = px_s.pct_change().values
rf = (raw['Close']['^IRX'] / 100).reindex(dates).ffill().fillna(0.04).values
vxn_raw = raw['Close']['^VXN'].reindex(dates)
rv = pd.Series(ret, index=dates)
proxy = (0.5 * rv.rolling(20).std() + 0.5 * rv.rolling(60).std()) * np.sqrt(252) * 100   # VXN 前的代理
vxn_s = vxn_raw.fillna(proxy).ffill().bfill()
vxn = vxn_s.values / 100
med = vxn_s.rolling(756, min_periods=60).median().bfill().values / 100

def iv_at(idx, tau, mode):
    idx = np.asarray(idx); tau = np.asarray(tau, float)
    if mode == 'flat': return vxn[idx] * np.ones_like(tau)
    kt = np.maximum(KAPPA * tau, 1e-6); w = (1 - np.exp(-kt)) / kt
    return med[idx] + (vxn[idx] - med[idx]) * w

def build(entries, Tdays, mode='mr', cost=0.015, delta=0.60, target=0.50):
    """每個進場日一筆：回傳 DataFrame 與每筆的每日估值路徑（供組合模擬）。"""
    rows = []; paths = {}
    T = Tdays / 252
    for i in entries:
        S0 = px[i]; r = rf[i]; sig = float(iv_at(i, T, mode))
        d1 = ND.inv_cdf(min(delta * np.exp(Q * T), 0.999))
        K = S0 * np.exp(-d1 * sig * np.sqrt(T) + (r - Q + sig ** 2 / 2) * T)
        c0 = float(bs_call(S0, K, T, r, sig)); buy = c0 * (1 + cost)
        j_exp = i + Tdays; j_end = min(j_exp, n - 1)
        idx = np.arange(i + 1, j_end + 1)
        if len(idx) == 0: continue
        tau = (j_exp - idx) / 252
        vals = bs_call(px[idx], K, tau, rf[idx], iv_at(idx, tau, mode)) * (1 - cost)
        hit = np.where(vals >= buy * (1 + target))[0]
        if len(hit):
            k = hit[0]; status = 'win'; r_ = vals[k] / buy - 1; j_exit = idx[k]
        elif j_exp <= n - 1:
            k = len(idx) - 1; status = 'expired'; r_ = vals[k] / buy - 1; j_exit = idx[k]
        else:
            k = len(idx) - 1; status = 'open'; r_ = vals[k] / buy - 1; j_exit = idx[k]
        mae = vals[:k + 1].min() / buy - 1
        rows.append(dict(i=i, date=dates[i], S0=S0, K=K, prem_pct=c0 / S0, iv=sig, status=status, ret=r_,
                         days=j_exit - i, j_exit=j_exit, mae=mae, und_ret=px[j_exit] / S0 - 1))
        paths[i] = (buy, idx[:k + 1], vals[:k + 1], status)
    return pd.DataFrame(rows), paths

def summarize(df, label):
    c = df[df.status != 'open']
    if len(c) == 0: print(f'{label:<28} 無已結束樣本'); return
    w = c[c.status == 'win']; l = c[c.status == 'expired']
    gain = c.ret[c.ret > 0].sum(); loss = -c.ret[c.ret < 0].sum()
    pf = gain / loss if loss > 0 else float('inf')
    lo = f'{l.ret.mean()*100:+5.0f}%' if len(l) else '   — '
    zero = f'{(l.ret <= -0.95).mean()*100:3.0f}%' if len(l) else '  — '
    print(f'{label:<28} n={len(c):>4} 勝率 {len(w)/len(c)*100:5.1f}%  每筆平均 {c.ret.mean()*100:+6.1f}%  '
          f'輸的平均 {lo}  輸的歸零比例 {zero}  PF {pf:5.2f}  贏的中位持有 {w.days.median() if len(w) else float("nan"):4.0f} 日  '
          f'途中最深中位 {c.mae.median()*100:+4.0f}%  未結 {int((df.status=="open").sum())}')

ERAS = [('1999–2002 網路泡沫', '1999', '2002'), ('2003–2007', '2003', '2007'), ('2008–2009 金融海嘯', '2008', '2009'),
        ('2010–2019', '2010', '2019'), ('2020–2021', '2020', '2021'), ('2022 升息', '2022', '2022'), ('2023→', '2023', '2030')]

sig_days = np.where(ret <= -0.01)[0]
all_days = np.arange(60, n - 1)
print(f'QQQ {dates[0].date()} → {dates[-1].date()}，{n} 個交易日；單日跌 ≥1% 共 {len(sig_days)} 天（{len(sig_days)/n*100:.1f}%，每年約 {len(sig_days)/(n/252):.0f} 次）')
T0 = 427 * 252 // 365
print(f'IV 模型校準：今日 VXN {vxn[-1]*100:.1f}、3 年中位 {med[-1]*100:.1f} → 模型 427 天 IV {float(iv_at(n-1, 427/365, "mr"))*100:.1f}%（實價 26.5%）')
d_, _ = build([n - 2], T0); print(f'模型上一個交易日 delta 0.60／427 天 call 權利金 = 現價 {d_.prem_pct.iloc[0]*100:.1f}%（今日實價 12.9%）')

print('\n=== A. 逐筆（每個訊號日各買一筆，互不影響）：到期 1 年、Delta 0.60、+50% 賣、不停損 ===')
for mode, mlabel in [('mr', '期限結構 IV（主）'), ('flat', 'IV＝VXN（敏感度）')]:
    df, paths = build(sig_days, 252, mode)
    print(f'--- {mlabel} ---')
    summarize(df, '全期 訊號日')
    summarize(build(all_days[::3], 252, mode)[0], '全期 任意日（每 3 日取樣）')
    for name, a, b in ERAS:
        summarize(df[(df.date >= a) & (df.date <= b + '-12-31')], name)

print('\n=== B. 到期長短（期限結構 IV，全期訊號日）===')
for Td, lab in [(252, '1 年'), (378, '1.5 年'), (504, '2 年')]:
    summarize(build(sig_days, Td)[0], f'到期 {lab}')
print('--- 2 年到期分時期 ---')
df2, paths2 = build(sig_days, 504)
for name, a, b in ERAS:
    summarize(df2[(df2.date >= a) & (df2.date <= b + '-12-31')], name)

print('\n=== C. 「+50% 需要 QQQ 漲多少」與基準機率 ===')
df1, paths1 = build(sig_days, 252)
w = df1[df1.status == 'win']
print(f'贏的那些筆，賣出當下 QQQ 自進場漲幅：中位 {w.und_ret.median()*100:+.1f}%（25–75 分位 {w.und_ret.quantile(.25)*100:+.1f}% ～ {w.und_ret.quantile(.75)*100:+.1f}%）')
fwd_max = np.array([px[i + 1:i + 253].max() / px[i] - 1 for i in range(n - 253)])
for th in (0.08, 0.10, 0.12, 0.15):
    print(f'  任意日買進，一年內 QQQ 曾經高出買價 ≥{th*100:.0f}% 的比例：{(fwd_max >= th).mean()*100:.1f}%')

def portfolio(paths, f, start, end=None, cap=None):
    """每個訊號日拿當時淨值的 f 買一筆（現金不夠就買到現金用完）；現金放 T-bill；淨值以每日估值計。
    cap：在手選擇權的買進成本合計不得超過當時淨值的 cap（None = 不設限，買到現金用完）。"""
    i0 = np.searchsorted(dates, pd.Timestamp(start)); i1 = n - 1 if end is None else min(n - 1, np.searchsorted(dates, pd.Timestamp(end)))
    cash = 1.0; pos = []   # (entry_i, qty)
    val_at = {}            # entry_i -> dict day->value
    eq = np.empty(i1 - i0 + 1)
    for t in range(i0, i1 + 1):
        if t > i0: cash *= 1 + rf[t - 1] / 252
        mtm = 0.0; keep = []; basis = 0.0
        for (e, qty) in pos:
            buy, idx, vals, status = paths[e]
            k = t - e - 1
            if k >= len(vals) - 1 and status != 'open':
                cash += qty * vals[-1]
            else:
                mtm += qty * vals[min(k, len(vals) - 1)]; keep.append((e, qty)); basis += qty * buy
        pos = keep
        equity = cash + mtm
        if t in paths:
            alloc = min(f * equity, cash)
            if cap is not None: alloc = min(alloc, max(cap * equity - basis, 0.0))
            if alloc > 1e-9:
                buy = paths[t][0]; pos.append((t, alloc / buy)); cash -= alloc
        eq[t - i0] = equity
    return pd.Series(eq, index=dates[i0:i1 + 1])

def stats(s):
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1 if s.iloc[-1] > 0 else -1
    mdd = (s / s.cummax() - 1).min()
    return s.iloc[-1] / s.iloc[0], cagr, mdd

print('\n=== D. 組合模擬（每個訊號日投入當時淨值的 f；1 年到期；期限結構 IV；單邊成本 1.5%）===')
print('    欄位：期末倍數／年化／最大回撤。對照：QQQ 買進持有（含息）、QLD 2 倍 ETF')
for start, end in [('1999-06-01', None), ('2003-01-02', None), ('2007-01-03', None), ('2010-01-04', None), ('2016-01-04', None), ('2021-01-04', None)]:
    line = f'{start}→ '
    for f in (0.02, 0.05, 0.10, 0.20):
        m, c, d = stats(portfolio(paths1, f, start, end))
        line += f'| f={f*100:>2.0f}% {m:7.1f}× {c*100:+6.1f}% {d*100:5.0f}% '
    m, c, d = stats(adj_s[start:]); line += f'| QQQ {m:6.1f}× {c*100:+5.1f}% {d*100:4.0f}% '
    q = qld_s[start:].dropna()
    if len(q) and q.index[0] <= pd.Timestamp(start) + pd.Timedelta(days=10):
        m, c, d = stats(q); line += f'| QLD {m:6.1f}× {c*100:+5.1f}% {d*100:4.0f}%'
    print(line)

print('\n--- 同上但 2 年到期 ---')
for start in ['1999-06-01', '2007-01-03', '2010-01-04', '2021-01-04']:
    line = f'{start}→ '
    for f in (0.02, 0.05, 0.10, 0.20):
        m, c, d = stats(portfolio(paths2, f, start)); line += f'| f={f*100:>2.0f}% {m:7.1f}× {c*100:+6.1f}% {d*100:5.0f}% '
    print(line)

print('\n=== E. 壞年份的淨值路徑（f=5% 與 10%，1 年到期，起點各自歸 1）===')
for a, b in [('2000-01-03', '2003-12-31'), ('2007-10-01', '2010-12-31'), ('2021-11-01', '2024-06-28')]:
    for f in (0.05, 0.10):
        s = portfolio(paths1, f, a, b); q = adj_s[a:b]
        print(f'{a}→{b} f={f*100:.0f}%：最低點 {s.min():.2f}（{s.idxmin().date()}），期末 {s.iloc[-1]:.2f}；QQQ 最低 {q.min()/q.iloc[0]:.2f}、期末 {q.iloc[-1]/q.iloc[0]:.2f}')

print('\n=== F. 加「在手權利金成本 ≤ 淨值 cap」上限（每筆 5%，1 年到期）：期末倍數／年化／最大回撤 ===')
for start in ['1999-06-01', '2003-01-02', '2007-01-03', '2010-01-04', '2013-01-02', '2016-01-04', '2019-01-02', '2021-01-04', '2023-01-03']:
    line = f'{start}→今 '
    for cap in (0.10, 0.20, 0.30, 0.50):
        m, c, d = stats(portfolio(paths1, 0.05, start, cap=cap)); line += f'| cap {cap*100:.0f}% {m:6.1f}× {c*100:+6.1f}% {d*100:4.0f}% '
    m, c, d = stats(adj_s[start:]); line += f'| QQQ {m:5.1f}× {c*100:+5.1f}% {d*100:4.0f}%'
    print(line)
print('--- 同上，2 年到期 ---')
for start in ['1999-06-01', '2003-01-02', '2007-01-03', '2010-01-04', '2016-01-04', '2021-01-04', '2023-01-03']:
    line = f'{start}→今 '
    for cap in (0.10, 0.20, 0.30, 0.50):
        m, c, d = stats(portfolio(paths2, 0.05, start, cap=cap)); line += f'| cap {cap*100:.0f}% {m:6.1f}× {c*100:+6.1f}% {d*100:4.0f}% '
    print(line)
print('--- 壞年份（cap 20%／30%，1 年到期，起點歸 1）---')
for a, b in [('2000-01-03', '2003-12-31'), ('2007-10-01', '2010-12-31'), ('2021-11-01', '2024-06-28')]:
    for cap in (0.20, 0.30):
        s_ = portfolio(paths1, 0.05, a, b, cap=cap); q = adj_s[a:b]
        print(f'{a}→{b} cap {cap*100:.0f}%：最低 {s_.min():.2f}（{s_.idxmin().date()}），期末 {s_.iloc[-1]:.2f}；QQQ 最低 {q.min()/q.iloc[0]:.2f}、期末 {q.iloc[-1]/q.iloc[0]:.2f}')

print('\n=== G. 成本敏感度（全期訊號日，1 年到期）===')
for cst in (0.0, 0.01, 0.015, 0.025):
    summarize(build(sig_days, 252, cost=cst)[0], f'單邊成本 {cst*100:.1f}%')

print('\n=== H. 「能分辨多空頭就好了」：當下看得到的濾網 vs 事後才知道的標籤（1 年到期）===')
sma200 = px_s.rolling(200).mean().values
hi252 = px_s.rolling(252).max().values
fwd1y = np.array([px[min(i + 252, n - 1)] / px[i] - 1 if i + 252 <= n - 1 else np.nan for i in range(n)])
sd = sig_days[sig_days >= 252]
FILTERS = [('不濾（對照）', sd),
           ('當下：收盤 > 200 日線', sd[px[sd] > sma200[sd]]),
           ('當下：收盤 < 200 日線', sd[px[sd] <= sma200[sd]]),
           ('當下：距一年高點 ≤10%', sd[px[sd] / hi252[sd] - 1 >= -0.10]),
           ('當下：距一年高點 >20%', sd[px[sd] / hi252[sd] - 1 < -0.20]),
           ('事後：一年後 QQQ 收高', sd[np.nan_to_num(fwd1y[sd], nan=-1) > 0]),
           ('事後：一年後 QQQ 收低', sd[np.nan_to_num(fwd1y[sd], nan=1) <= 0])]
for lab, ent in FILTERS:
    dfh, ph = build(ent, 252)
    summarize(dfh, lab)
print('--- 組合：每筆 5%，不設上限／上限 20%，2000-03-10→今：期末倍數／年化／最大回撤 ---')
for lab, ent in FILTERS[:5]:
    dfh, ph = build(ent, 252); line = f'{lab:<22}'
    for cap in (None, 0.20):
        m, c, d = stats(portfolio(ph, 0.05, '2000-03-10', cap=cap)); line += f'| {"不設上限" if cap is None else "上限 20%"} {m:7.1f}× {c*100:+6.1f}% {d*100:5.0f}% '
    print(line)
m, c, d = stats(adj_s['2000-03-10':]); print(f'QQQ 買進持有            | {m:7.1f}× {c*100:+6.1f}% {d*100:5.0f}%')
print('--- 200 日線濾網在 2010 之後（上限 20%）---')
for lab, ent in FILTERS[:3]:
    dfh, ph = build(ent, 252); m, c, d = stats(portfolio(ph, 0.05, '2010-01-04', cap=0.20))
    print(f'{lab:<22}| {m:6.1f}× {c*100:+6.1f}% {d*100:5.0f}%')

print('\n=== I. 用 QQQ 200 日線／400 日線當多空開關（訊號看前一日收盤，當日收盤執行；起點 2000-11-01，400 日線暖機後）===')
START_I = '2000-11-01'
MA = {200: px_s.rolling(200).mean().values, 400: px_s.rolling(400).mean().values}
on = {k: np.concatenate([[False], (px > v)[:-1]]) for k, v in MA.items()}       # on[t] = 前一日收盤在線上
sdI = sig_days[sig_days >= 401]
print('--- I-1 逐筆（1 年到期）---')
for k in (200, 400):
    up = sdI[px[sdI] > MA[k][sdI]]; dn = sdI[px[sdI] <= MA[k][sdI]]
    summarize(build(up, 252)[0], f'收盤 > {k} 日線才買'); summarize(build(dn, 252)[0], f'收盤 < {k} 日線才買')

def portfolio_sw(paths, f, start, cap, reg, exit_off):
    """同 portfolio，但只在 reg[t] 為真時進場；exit_off=True 時轉空當日把在手 call 全部按估值賣掉。"""
    i0 = np.searchsorted(dates, pd.Timestamp(start)); cash = 1.0; pos = []; eq = np.empty(n - i0); nexit = 0
    for t in range(i0, n):
        if t > i0: cash *= 1 + rf[t - 1] / 252
        mtm = 0.0; keep = []; basis = 0.0
        for (e, qty) in pos:
            buy, idx, vals, status = paths[e]; k = t - e - 1
            if k >= len(vals) - 1 and status != 'open': cash += qty * vals[-1]
            elif exit_off and not reg[t]: cash += qty * vals[min(k, len(vals) - 1)]; nexit += 1
            else: mtm += qty * vals[min(k, len(vals) - 1)]; keep.append((e, qty)); basis += qty * buy
        pos = keep; equity = cash + mtm
        if t in paths and reg[t]:
            alloc = min(f * equity, cash)
            if cap is not None: alloc = min(alloc, max(cap * equity - basis, 0.0))
            if alloc > 1e-9: pos.append((t, alloc / paths[t][0])); cash -= alloc
        eq[t - i0] = equity
    return pd.Series(eq, index=dates[i0:])

dfI, pI = build(sdI, 252)
always = np.ones(n, bool)
print('--- I-2 LEAPS 組合（每筆 5%）：期末倍數／年化／最大回撤 ---')
for st in (START_I, '2010-01-04'):
    print(f'[{st}→今]')
    for lab, reg, ex in [('不用開關', always, False), ('200 日線：只擋進場', on[200], False), ('200 日線：擋進場＋轉空全賣', on[200], True),
                         ('400 日線：只擋進場', on[400], False), ('400 日線：擋進場＋轉空全賣', on[400], True)]:
        line = f'  {lab:<20}'
        for cap in (None, 0.20, 0.30):
            m, c, d = stats(portfolio_sw(pI, 0.05, st, cap, reg, ex)); line += f'| {"不設上限" if cap is None else f"上限 {cap*100:.0f}%"} {m:7.1f}× {c*100:+6.1f}% {d*100:5.0f}% '
        print(line)
    m, c, d = stats(adj_s[st:]); print(f'  QQQ 買進持有          | {m:7.1f}× {c*100:+6.1f}% {d*100:5.0f}%')

def switch_hold(asset, reg, start, end=None, cost=0.001):
    a = asset[start:end].dropna(); r = a.pct_change().fillna(0).values; ix = [dates.get_loc(d) for d in a.index]
    g = np.array([reg[i] for i in ix]); held = np.concatenate([[g[0]], g[:-1]])   # reg 已是前一日訊號 → 當日收盤換，隔日起算報酬
    daily = np.where(held, r, rf[ix] / 252); sw = np.abs(np.diff(held.astype(int))); daily[1:] -= sw * cost
    s = pd.Series(np.cumprod(1 + daily), index=a.index); return s, sw.sum() / (len(a) / 252), held.mean()

print('--- I-3 直接拿開關持有 QQQ／QLD（線上持有、線下放 T-bill，每次切換 10bp）---')
for nm, asset, wins in [('QQQ', adj_s, [(START_I, None), (START_I, '2009-12-31'), ('2010-01-04', None)]),
                        ('QLD', qld_s, [('2006-07-03', None), ('2006-07-03', '2009-12-31'), ('2010-01-04', None)])]:
    for a, b in wins:
        m, c, d = stats(asset[a:b].dropna()); line = f'{nm} {a}→{b or "今"}：買進持有 {m:6.1f}× {c*100:+5.1f}% {d*100:4.0f}% '
        for k in (200, 400):
            s, per_yr, frac = switch_hold(asset, on[k], a, b); m, c, d = stats(s)
            line += f'| {k} 日線 {m:6.1f}× {c*100:+5.1f}% {d*100:4.0f}%（年切換 {per_yr:.1f} 次、在場 {frac*100:.0f}%）'
        print(line)
