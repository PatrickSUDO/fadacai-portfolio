"""vix_leveraged_etf_2026-11-07.py — 「VIX 飆高買 QLD/USD（2× ETF），反彈後把超額拿去買個股」能不能用？
（2026-11-07 用戶「仔細幫我研究下目前最適合的 vix 運用方式」）

事件：VIX 收盤首次站上 30（前 20 個交易日沒站過）；另列 40 檔次。載具：QQQ / SMH 現貨、QLD / USD 實際 ETF
（2006-06 / 2007-01 起），更早用「2× 日再平衡合成序列」補到 1999/2000（以實際 ETF 重疊期校準成本）。
出場：固定 60 / 120 / 250 日；或「VIX 收盤 <20 平靜出場」（最少持 20 日、最多 250 日）。
另模擬「停泊池」：平時全放 SPY，事件日把池子的一段換成 2× ETF，平靜後換回 SPY——跟「一直放 SPY」比 CAGR / MDD。
"""
import numpy as np, pandas as pd, yfinance as yf, warnings
warnings.filterwarnings("ignore")
raw = yf.download(['^VIX','^IRX','SPY','QQQ','SMH','QLD','USD','TQQQ','SOXL'], period='max', progress=False, auto_adjust=True)
C = raw['Close']; L = raw['Low']
vix = C['^VIX'].dropna()
rf = (C['^IRX'] / 100).reindex(C.index).ffill().fillna(0.02)   # 年化 T-bill

def synth2x(idx_sym, etf_sym):
    """2× 日再平衡合成：r = 2r_idx − (rf + c)/252，c 用實際 ETF 重疊期校準。"""
    r = C[idx_sym].pct_change()
    ov = pd.concat([r, C[etf_sym].pct_change(), rf], axis=1).dropna(); ov.columns = ['r','e','rf']
    c = float(((2*ov['r'] - ov['e']) * 252 - ov['rf']).mean())           # 年化額外成本（費用+融資價差+追蹤）
    lev = (2*r - (rf + c)/252).fillna(0)
    s = (1 + lev).cumprod(); s = s / s.loc[C[etf_sym].first_valid_index()] * C[etf_sym].loc[C[etf_sym].first_valid_index()]
    full = C[etf_sym].copy(); full[full.index < C[etf_sym].first_valid_index()] = s[s.index < C[etf_sym].first_valid_index()]
    # 校準品質：重疊期年化差
    ov_s = (1+ov['e']).cumprod(); ov_m = (1 + (2*ov['r'] - (ov['rf']+c)/252)).cumprod()
    yrs = len(ov)/252; gap = (ov_s.iloc[-1]**(1/yrs) - ov_m.iloc[-1]**(1/yrs))
    return full.dropna(), c, gap

QLDx, cQ, gQ = synth2x('QQQ','QLD'); USDx, cU, gU = synth2x('SMH','USD')
print(f'合成校準：QLD 額外成本 {cQ*100:.1f}%/年（重疊期年化殘差 {gQ*100:+.2f}pp）；USD 額外成本 {cU*100:.1f}%/年（殘差 {gU*100:+.2f}pp）')
V = {'QQQ': C['QQQ'].dropna(), 'QLD(2×,合成補)': QLDx, 'SMH': C['SMH'].dropna(), 'USD(2×,合成補)': USDx, 'SPY': C['SPY'].dropna()}

def events(level, gap=20):
    cond = vix >= level; days = []; last = None
    for d in cond[cond].index:
        i = vix.index.get_loc(d)
        if last is None or i - last > gap: days.append(d); last = i
    return days

def trade(s, d, exit_rule):
    """回傳 (報酬, 持有日數, 交易內最深回撤)"""
    if d not in s.index: return None
    i = s.index.get_loc(d); n = len(s)
    if isinstance(exit_rule, int):
        j = i + exit_rule
        if j >= n: return None
    else:  # 'calm'：VIX 收 <20，最少 20 日、最多 250 日
        j = None
        for k in range(i + 20, min(i + 250, n - 1) + 1):
            dk = s.index[k]
            if dk in vix.index and vix.loc[dk] < 20: j = k; break
        if j is None: j = min(i + 250, n - 1)
        if j <= i: return None
    path = s.iloc[i:j + 1]
    return (path.iloc[-1] / path.iloc[0] - 1, j - i, path.min() / path.iloc[0] - 1)

def table(level, rules=(60, 120, 250, 'calm')):
    ev = events(level)
    print(f'\n=== VIX 首次站上 {level}（{len(ev)} 次，1999/2000→）===')
    print(f'{"載具":<16}' + ''.join(f'| {str(r)+"日" if isinstance(r,int) else "平靜出場":^52}' for r in rules))
    for name, s in V.items():
        if name == 'SPY': continue
        cells = []
        for r in rules:
            res = [t for d in ev for t in [trade(s, d, r)] if t]
            if not res: cells.append(f'| {"—":^30}'); continue
            ret = np.array([x[0] for x in res]); dd = np.array([x[2] for x in res])
            cells.append(f'| 均{ret.mean()*100:+6.1f}% 中{np.median(ret)*100:+6.1f}% 勝{(ret>0).mean()*100:3.0f}% 最差{ret.min()*100:+5.0f}% 途中回撤中{np.median(dd)*100:+4.0f}%/最深{dd.min()*100:+4.0f}% ')
        print(f'{name:<16}' + ''.join(cells))
    # 平靜出場的平均持有日
    res = [t for d in ev for t in [trade(V['QQQ'], d, 'calm')] if t]
    print(f'平靜出場平均持有 {np.mean([x[1] for x in res]):.0f} 日（中位 {np.median([x[1] for x in res]):.0f}）')

table(30); table(40)

# ── 逐事件表（2020→，看每一次到底發生什麼）──
print('\n=== 逐事件（2020→）：買進後 60 / 250 日報酬，括號 = 平靜出場（VIX<20）報酬與持有日 ===')
print(f'{"事件日":<12}{"VIX":>5} ' + ''.join(f'{n:>22}' for n in ['QQQ','QLD(2×,合成補)','SMH','USD(2×,合成補)']))
for d in events(30):
    if d < pd.Timestamp('2020-01-01'): continue
    cells = []
    for n in ['QQQ','QLD(2×,合成補)','SMH','USD(2×,合成補)']:
        t60 = trade(V[n], d, 60); t250 = trade(V[n], d, 250); tc = trade(V[n], d, 'calm')
        f = lambda t: f'{t[0]*100:+5.0f}%' if t else '  n/a'
        cells.append(f'{f(t60)}/{f(t250)} ({f(tc)},{tc[1] if tc else 0:>3}d)')
    print(f'{d.date()}  {vix.loc[d]:5.1f} ' + ''.join(f'{c:>22}' for c in cells))

# ── 停泊池模擬：平時 SPY；事件日把池子 share 換成 2× ETF，平靜出場換回 ──
def pool_sim(lev_sym, start, end=None, share=0.5, level=30, tiers=None, exit_rule='calm'):
    s_spy = V['SPY']; s_lev = V[lev_sym]; excess = []
    idx = s_spy.index[(s_spy.index >= start) & (s_spy.index <= (end or s_spy.index[-1]))]
    idx = idx.intersection(s_lev.index)
    spy_units, lev_units = 1.0 / s_spy.loc[idx[0]], 0.0
    ev = set(events(level)); ev40 = set(events(40)); in_trade = None; hist = []
    for d in idx:
        if in_trade is not None:
            held = idx.get_loc(d) - in_trade
            done = ((held >= 20 and vix.get(d, 99) < 20) or held >= 250) if exit_rule == 'calm' else held >= exit_rule
            if done:
                d0 = idx[in_trade]
                excess.append((s_lev.loc[d]/s_lev.loc[d0] - 1) - (s_spy.loc[d]/s_spy.loc[d0] - 1))
                spy_units += lev_units * s_lev.loc[d] / s_spy.loc[d]; lev_units = 0.0; in_trade = None
        if d in ev and in_trade is None:
            sh = share * (2 if (tiers and d in ev40) else 1); sh = min(sh, 1.0)
            move = spy_units * sh; spy_units -= move
            lev_units += move * s_spy.loc[d] / s_lev.loc[d]; in_trade = idx.get_loc(d)
        elif d in ev40 and in_trade is not None and tiers:     # 已在場內又升到 40 → 再加一段
            move = spy_units * share; spy_units -= move; lev_units += move * s_spy.loc[d] / s_lev.loc[d]
        hist.append(spy_units * s_spy.loc[d] + lev_units * s_lev.loc[d])
    v = pd.Series(hist, index=idx); b = s_spy.loc[idx] / s_spy.loc[idx[0]]
    def m(x):
        yrs = len(x) / 252; cagr = x.iloc[-1] ** (1 / yrs) - 1; mdd = (x / x.cummax() - 1).min()
        r = x.pct_change().dropna(); sh = r.mean() / r.std() * np.sqrt(252)
        return cagr, mdd, sh
    return m(v), m(b), excess

print('\n=== 停泊池模擬：平時全放 SPY；VIX 首次 ≥30 把池子的一段換成載具，VIX<20（最少 20 日）或 250 日換回；「分級」= ≥40 再換同一段 ===')
print('每次事件超額 = 該段載具報酬 − 同窗 SPY 報酬（池子裡那一段的超額，就是用戶說的「拿去買個股」的錢）')
V['QQQ(現貨)'] = V['QQQ']; V['SMH(現貨)'] = V['SMH']
for start in ('2000-01-01', '2010-01-01', '2020-01-01'):
    print(f'\n--- {start[:4]}→   一直放 SPY：', end='')
    (c0, d0, s0) = pool_sim('QQQ', start)[1]; print(f'CAGR {c0*100:.1f}% / MDD {d0*100:.1f}% / Sharpe {s0:.2f}')
    print(f'{"載具":<16}{"換出比例":>6}{"分級":>4}{"出場":>6}{"CAGR":>8}{"MDD":>8}{"Sharpe":>8}   事件超額 均/中位/最差   次數')
    for lev in ('QQQ(現貨)', 'SMH(現貨)', 'QLD(2×,合成補)', 'USD(2×,合成補)'):
        for share, tiers, ex in ((0.25, True, 'calm'), (0.5, False, 'calm'), (0.5, True, 'calm'), (0.5, True, 120), (1.0, False, 'calm')):
            (c1, d1, s1), _, exc = pool_sim(lev, start, share=share, tiers=tiers, exit_rule=ex)
            e = np.array(exc) * 100 if exc else np.array([np.nan])
            print(f'{lev:<16}{share*100:5.0f}%{"是" if tiers else "否":>4}{str(ex):>6}{c1*100:7.1f}%{d1*100:7.1f}%{s1:8.2f}   {e.mean():+6.1f}/{np.median(e):+6.1f}/{e.min():+6.1f}pp   {len(exc):>3}')

# ── 混合：tier 30 換現貨 SMH，tier 40 再加一段 2×（40 檔次歷史上最乾淨：QLD 平靜出場 21 次全勝、最差 +5%）──
def pool_hybrid(start, lev_sym, share=0.5, share40=0.5):
    s_spy = V['SPY']; s30 = V['SMH']; s40 = V[lev_sym]
    idx = s_spy.index[s_spy.index >= start].intersection(s30.index).intersection(s40.index)
    u_spy, u30, u40 = 1.0 / s_spy.loc[idx[0]], 0.0, 0.0
    ev30 = set(events(30)); ev40 = set(events(40)); t30 = t40 = None; hist = []
    for d in idx:
        i = idx.get_loc(d)
        for key in ('30', '40'):
            t = t30 if key == '30' else t40
            if t is not None and ((i - t >= 20 and vix.get(d, 99) < 20) or i - t >= 250):
                if key == '30': u_spy += u30 * s30.loc[d] / s_spy.loc[d]; u30 = 0.0; t30 = None
                else: u_spy += u40 * s40.loc[d] / s_spy.loc[d]; u40 = 0.0; t40 = None
        if d in ev30 and t30 is None:
            mv = u_spy * share; u_spy -= mv; u30 += mv * s_spy.loc[d] / s30.loc[d]; t30 = i
        if d in ev40 and t40 is None:
            mv = u_spy * share40; u_spy -= mv; u40 += mv * s_spy.loc[d] / s40.loc[d]; t40 = i
        hist.append(u_spy * s_spy.loc[d] + u30 * s30.loc[d] + u40 * s40.loc[d])
    x = pd.Series(hist, index=idx); yrs = len(x) / 252; r = x.pct_change().dropna()
    return x.iloc[-1] ** (1 / yrs) - 1, (x / x.cummax() - 1).min(), r.mean() / r.std() * np.sqrt(252)

print('\n=== 混合：VIX ≥30 池子 50% → SMH 現貨；≥40 再 50% → 2× ETF；各自 VIX<20 換回 ===')
for start in ('2000-01-01', '2010-01-01', '2020-01-01'):
    for lev in ('QLD(2×,合成補)', 'USD(2×,合成補)', 'SMH'):
        c, d, s = pool_hybrid(start, lev)
        print(f'{start[:4]}→  30→SMH / 40→{lev:<16} CAGR {c*100:5.1f}%  MDD {d*100:6.1f}%  Sharpe {s:.2f}')
