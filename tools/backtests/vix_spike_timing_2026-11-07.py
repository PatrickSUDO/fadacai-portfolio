"""「VIX 飆升時加碼」是不是好的擇時——事件研究。
指數：SPY 1993→、QQQ 1999→、SMH 2000→（VIX 1990→）；本書宇宙 30 檔 2021-09→。
事件去叢集：同一條件 20 個交易日內只算第一次。報 20/60/120/250 日之後報酬 vs 基準（任意日），
另報「之後 60 日內最深回撤」（加碼後要忍多深）。"""
import numpy as np, pandas as pd, yfinance as yf, warnings
warnings.filterwarnings("ignore")
HOLD = ['AMAT','ANET','AVGO','CLS','CRM','CRWD','DIOD','MU','NET','NVDA','PLTR','PWR','SNPS','TWLO']
CAND = ['HWM','ATI','FN','GEV','COHR','VRT','PAYC','WDAY','DOCU','ZS','OKTA','AMZN','LITE','MRVL','ONTO','STRL']
U = HOLD + CAND
raw = yf.download(['^VIX','SPY','QQQ','SMH'] + U, period='max', progress=False, auto_adjust=True)
C = raw['Close']; L = raw['Low']
vix = C['^VIX'].dropna()
HZ = (20, 60, 120, 250)

def events(cond, gap=20):
    days = list(cond[cond.fillna(False)].index); keep = []; last = None
    for d in days:
        if last is None or (cond.index.get_loc(d) - cond.index.get_loc(last)) > gap:
            keep.append(d); last = d
    return keep

def stats(sym, days, start):
    s = C[sym].dropna(); s = s[s.index >= start]; lo = L[sym].reindex(s.index)
    idx = s.index; out = {}
    base = {h: (s.shift(-h) / s - 1).dropna() for h in HZ}
    for h in HZ:
        r = [s.iloc[i + h] / s.iloc[i] - 1 for d in days if d in idx for i in [idx.get_loc(d)] if i + h < len(s)]
        out[h] = (np.mean(r) if r else np.nan, np.mean(np.array(r) > 0) if r else np.nan, len(r), base[h].mean(), (base[h] > 0).mean())
    # 之後 60 日內最深回撤（相對事件日收盤）
    dd = [lo.iloc[i + 1:i + 61].min() / s.iloc[i] - 1 for d in days if d in idx for i in [idx.get_loc(d)] if i + 60 < len(s)]
    bdd = (lo.rolling(60).min().shift(-60) / s - 1).dropna()
    out['dd'] = (np.median(dd) if dd else np.nan, bdd.median())
    return out

def show(label, days, syms=('SPY','QQQ','SMH'), start='1993-01-01'):
    print(f'\n### {label}   事件數 {len([d for d in days if d >= pd.Timestamp(start)])}')
    for sym in syms:
        st = stats(sym, days, start)
        parts = []
        for h in HZ:
            m, w, n, bm, bw = st[h]
            parts.append(f'{h:>3}日 {m*100:+5.1f}%({w*100:3.0f}%) vs {bm*100:+4.1f}%({bw*100:3.0f}%)')
        print(f'  {sym:<4} ' + ' | '.join(parts) + f' | 60日內最深回撤 中位 {st["dd"][0]*100:+5.1f}% vs {st["dd"][1]*100:+5.1f}%  n={st[60][2]}')

v = vix
ratio20 = v / v.rolling(20).mean()
chg1 = v.pct_change(); chg5 = v / v.shift(5) - 1
print('基準 = 同一標的任意日起算（括號 = 勝率）')
show('A1 VIX 收盤首次站上 25（之前 20 日內沒站過）', events(v >= 25))
show('A2 VIX 首次站上 30', events(v >= 30))
show('A3 VIX 首次站上 40', events(v >= 40))
show('B1 VIX 單日飆升 ≥ +25%', events(chg1 >= 0.25))
show('B2 VIX 5 日飆升 ≥ +50%', events(chg5 >= 0.5))
show('B3 VIX ≥ 1.5× 其 20 日均值', events(ratio20 >= 1.5))
# 等「飆升後回落」的確認版：曾 ≥25 且自 10 日高點回落 ≥20%
hi10 = v.rolling(10).max()
show('C1 確認版：VIX 曾 ≥25 且自 10 日高回落 ≥20%', events((hi10 >= 25) & (v <= hi10 * 0.8)))
show('C2 確認版：VIX 曾 ≥30 且自 10 日高回落 ≥20%', events((hi10 >= 30) & (v <= hi10 * 0.8)))
# 反面：VIX 低檔（<15）加碼
show('D 對照：VIX 收盤 < 15（去叢集）', events(v < 15))

print('\n\n== 本書宇宙 30 檔（2021-09→），之後 20/60 日平均報酬，事件 = 上面各條件 ==')
ev = {'A1 首次≥25': events(v >= 25), 'A2 首次≥30': events(v >= 30), 'B1 單日+25%': events(chg1 >= 0.25),
      'B3 ≥1.5×20日均': events(ratio20 >= 1.5), 'C1 確認版≥25回落20%': events((hi10 >= 25) & (v <= hi10 * 0.8)),
      'D 對照 VIX<15': events(v < 15)}
start = pd.Timestamp('2021-09-01')
for k, days in ev.items():
    days = [d for d in days if d >= start]
    r20, r60, dd = [], [], []
    for sym in U:
        s = C[sym].dropna(); s = s[s.index >= start]; lo = L[sym].reindex(s.index)
        for d in days:
            if d not in s.index: continue
            i = s.index.get_loc(d)
            if i + 60 < len(s):
                r20.append(s.iloc[i+20]/s.iloc[i]-1); r60.append(s.iloc[i+60]/s.iloc[i]-1); dd.append(lo.iloc[i+1:i+61].min()/s.iloc[i]-1)
    print(f'  {k:<22} 事件 {len(days):>2}  20日 {np.mean(r20)*100:+5.1f}%({np.mean(np.array(r20)>0)*100:3.0f}%)  60日 {np.mean(r60)*100:+5.1f}%({np.mean(np.array(r60)>0)*100:3.0f}%)  60日內最深回撤中位 {np.median(dd)*100:+5.1f}%  n={len(r60)}')
b20, b60, bdd = [], [], []
for sym in U:
    s = C[sym].dropna(); s = s[s.index >= start]; lo = L[sym].reindex(s.index)
    b20 += list((s.shift(-20)/s-1).dropna()); b60 += list((s.shift(-60)/s-1).dropna()); bdd += list((lo.rolling(60).min().shift(-60)/s-1).dropna())
print(f'  {"基準（任意日）":<22}          20日 {np.mean(b20)*100:+5.1f}%({np.mean(np.array(b20)>0)*100:3.0f}%)  60日 {np.mean(b60)*100:+5.1f}%({np.mean(np.array(b60)>0)*100:3.0f}%)  60日內最深回撤中位 {np.median(bdd)*100:+5.1f}%')
# 事件日期列給人看（A2）
print('\nA2 VIX 首次站上 30 的日期：', ', '.join(d.strftime('%Y-%m-%d') for d in events(v >= 30)))
