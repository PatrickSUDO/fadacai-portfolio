"""五條件抄底清單與各種進場方式——回測（2026-11-10 用戶貼的清單）。
條件（訊號一律看 SPY／VIX，收盤判定）：
  1 VIX > 25　2 SPY 自 252 日高回檔 ≥ 10%　3 週線 RSI(14) < 40
  4 成交量激增：4a SPY 日量 > 1 億股（絕對值，年代不可比——2008–2011 幾乎天天超過、1990 年代從未）；4b 日量 > 1.5× 前 50 日均量（主用）
  5 止穩：t−10..t−3 曾創 20 日收盤新低、近 3 日未再破、收盤 > 5 日線且 > 前 3 日最高收盤；
    5s 另要求近 10 日低點落在 200 日線或前 126 日低點的 −5%～+2% 內且收盤守住（「下探支撐後企穩」）
三個視角：
  (一) 事件研究：各條件／組合觸發後 20/60/120/250 日報酬 vs 任意日（去叢集 20 日；買 SPY/QQQ/SMH）
  (二) 逐次修正：SPY 自歷史新高回檔 ≥10% 的每一段，各進場方式買在離最低點多遠、之後賺多少（含價格梯、時間梯）
  (三) 存錢等訊號 vs 每月直接買：每月存 1 元，等訊號才一次投入 vs 定期定額
用法：python3 dip_buy_conditions_2026-11-10.py

首跑結論（2026-11-10，輸出 data/dip_buy_conditions_2026-11-10.out.txt）：
- 五條裡只有 VIX 水位有資訊量，而且要 ≥30 才明顯：SPY 之後 250 日 +17.0%（≥30）／+29.7%（≥40）vs 任意日 +12.1%。
  VIX>25 只在 60 日有一點（+4.4% vs +2.8%，t 2.0），250 日 +12.3% 與任意日相同。
- 回檔 ≥10%、週 RSI<40、量增、止穩、支撐止穩：單獨看全部 ≈ 任意日（|t| < 1.5）；回檔 ≥10% 的 250 日反而較低（+9.0%）。
- 條件疊越多越差：1+2+3 同日 250 日 +13.1%（t 0.3）；五條到齊 +8.3%（t −0.7），事件只剩 21 次、分布在 10 個年份。
- 逐次修正（12 段）：五條到齊在 5 段完全沒觸發（1997×2、1999、2016、2018-02 這種淺修正）；有觸發時買在離低點 13.6%（中位），
  不比「跌破 −10% 當天直接買」的 10.5% 好。等止穩同樣沒有買得更低（17.2%）。
- 兩次大熊市（2000、2008）所有方式都買在離最低點 58–105% 之上，沒有任何條件組合躲得掉。
- 價格梯（−10/−15/−20）買進均價最好（離低點 5.5%），但淺修正只成交 1/3，平均只投入 64%，整筆錢 250 日報酬反而較低（+9.2% vs +14.3%）。
- 存錢等訊號 vs 每月直接買：所有等法都輸，期末資產是定期定額的 0.72–0.97 倍；五條到齊最長連續 87 個月沒訊號。
- 參考列：VIX 高於歷史第 80 百分位比 ≥30 弱（250 日 +13.6%，t 0.9）；VIX 倒掛本身無資訊，倒掛結束後 QQQ 120 日 +12.9%（t 2.6，n=33）但 SPY 不顯著。
- 限制：條件 4、5 的量化定義是我訂的；修正只有 12 段；訊號只看 SPY。"""
import warnings
import numpy as np, pandas as pd, yfinance as yf
warnings.filterwarnings("ignore")
raw = yf.download(['SPY', 'QQQ', 'SMH', '^VIX', '^VIX3M', '^IRX'], period='max', progress=False, auto_adjust=True)
C = raw['Close']; LO = raw['Low']; V = raw['Volume']
spy = C['SPY'].dropna(); idx = spy.index; lo = LO['SPY'].reindex(idx)
vix_full = C['^VIX'].dropna(); vix = vix_full.reindex(idx).ffill(); v3 = C['^VIX3M'].reindex(idx)
rf = C['^IRX'].reindex(idx).ffill().fillna(3.0) / 100 / 252
HZ = (20, 60, 120, 250)

def rsi_wilder(s, n=14):
    d = s.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean(); ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + au / ad)

wk = spy.resample('W-FRI').last().dropna()
rsiw = rsi_wilder(wk).reindex(idx, method='ffill')          # 週五收盤才更新，無偷看
vol = V['SPY'].reindex(idx)
dd = spy / spy.rolling(252, min_periods=60).max() - 1
c1 = vix > 25; c2 = dd <= -0.10; c3 = rsiw < 40
c4a = vol > 100e6; c4b = vol > 1.5 * vol.rolling(50).mean().shift(1)
sma5 = spy.rolling(5).mean(); sma200 = spy.rolling(200).mean()
is_low = (spy <= spy.rolling(20).min()).astype(float)
c5 = (is_low.shift(3).rolling(8).max() == 1) & (is_low.rolling(3).max() == 0) & (spy > sma5) & (spy > spy.shift(1).rolling(3).max())
low10 = lo.rolling(10).min(); prior_low = lo.shift(11).rolling(126).min()
near = lambda S: (low10 <= S * 1.02) & (low10 >= S * 0.95) & (spy >= S * 0.98)
c5s = c5 & (near(sma200) | near(prior_low))
r10 = lambda c: c.astype(float).rolling(10).max() == 1      # 近 10 日內曾成立
ksame = c1.astype(int) + c2.astype(int) + c3.astype(int) + c4b.astype(int) + c5.astype(int)
all5 = c2 & c3 & r10(c1) & r10(c4b) & c5
p80 = vix_full.expanding(min_periods=500).quantile(0.8).shift(1).reindex(idx).ffill()
inv = (vix / v3) > 1
inv_end = (inv.astype(float).shift(1).rolling(3).min() == 1) & (~inv) & v3.notna()

SIG = {
    '1 VIX>25': c1, '2 回檔≥10%': c2, '3 週RSI<40': c3, '4a 量>1億股': c4a, '4b 量>1.5×均量': c4b,
    '5 止穩': c5, '5s 支撐+止穩': c5s,
    '1+2': c1 & c2, '1+2+3': c1 & c2 & c3, '1+2+3+4b 同日': c1 & c2 & c3 & c4b,
    '2+5 回檔後止穩': c2 & c5, '2+3+5': c2 & c3 & c5,
    '五條到齊（1、4 近10日；2、3、5 當日）': all5,
    '五條到齊（5 改 5s）': c2 & c3 & r10(c1) & r10(c4b) & c5s,
    '同日成立 ≥3 條': ksame >= 3, '同日成立 ≥4 條': ksame >= 4,
    '參考 VIX≥30': vix >= 30, '參考 VIX≥40': vix >= 40,
    '參考 VIX>歷史第80百分位': vix > p80,
    '參考 VIX 倒掛（VIX>VIX3M，2007→）': inv, '參考 倒掛結束（連3日倒掛後轉正）': inv_end,
}

def events(cond, gap=20):
    pos = np.flatnonzero(cond.fillna(False).values); keep = []; last = -10**9
    for i in pos:
        if i - last > gap: keep.append(cond.index[i]); last = i
    return keep

def study(sym, days, start):
    s = C[sym].dropna(); s = s[s.index >= start]; l = LO[sym].reindex(s.index); out = []
    ii = [s.index.get_loc(d) for d in days if d in s.index]
    for h in HZ:
        r = np.array([s.iloc[i + h] / s.iloc[i] - 1 for i in ii if i + h < len(s)])
        b = (s.shift(-h) / s - 1).dropna()
        t = (r.mean() - b.mean()) / (r.std(ddof=1) / np.sqrt(len(r))) if len(r) > 2 else np.nan
        out.append((r.mean() if len(r) else np.nan, (r > 0).mean() if len(r) else np.nan, b.mean(), t, len(r)))
    ddv = [l.iloc[i + 1:i + 61].min() / s.iloc[i] - 1 for i in ii if i + 60 < len(s)]
    return out, (np.median(ddv) if ddv else np.nan)

def part1():
    print('=== (一) 事件研究：觸發日收盤買，之後 N 日報酬（括號＝勝率；t＝對任意日基準）；去叢集 20 日 ===')
    for sym, start in (('SPY', '1993-06-01'), ('QQQ', '1999-06-01'), ('SMH', '2000-09-01')):
        s = C[sym].dropna(); s = s[s.index >= start]
        base = ' | '.join(f'{h}日 {(s.shift(-h)/s-1).mean()*100:+5.1f}%({((s.shift(-h)/s-1).dropna()>0).mean()*100:3.0f}%)' for h in HZ)
        print(f'\n## 買 {sym}（{start[:4]}→）　任意日基準：{base}')
        for k, cond in SIG.items():
            days = [d for d in events(cond) if d >= pd.Timestamp(start)]
            if len(days) < 5: print(f'  {k:<30} 事件 {len(days)}（太少）'); continue
            st, mdd = study(sym, days, start); yrs = len({d.year for d in days})
            print(f'  {k:<30} 事件{len(days):>4} 年份{yrs:>3} | ' + ' | '.join(f'{h}日 {m*100:+5.1f}%({w*100:3.0f}%) t{t:+4.1f}' for h, (m, w, b, t, n) in zip(HZ, st)) + f' | 60日內最深 中位{mdd*100:+5.1f}%')

def episodes():
    vals = spy.values; ath = spy.cummax().values; eps = []; i = 0; n = len(vals)
    while i < n:
        if vals[i] / ath[i] - 1 <= -0.10:
            pk = np.flatnonzero(vals[:i + 1] == ath[i])[-1]
            later = np.flatnonzero(vals[i:] >= ath[i]); end = i + later[0] if len(later) else n - 1
            tr = pk + int(np.argmin(vals[pk:end + 1])); eps.append((pk, i, tr, end, bool(len(later)))); i = end + 1
        else: i += 1
    return eps

def first(cond, a, b):
    pos = np.flatnonzero(cond.fillna(False).values[a:b + 1])
    return a + pos[0] if len(pos) else None

def fills_for(name, pk, st, end):
    """回傳 [(index, 權重)]；權重合計 ≤ 1，沒成交的部分留現金。"""
    P = spy.values; peak = P[pk]
    one = lambda c: [(i, 1.0)] if (i := first(c, pk, end)) is not None else []
    if name == 'A 回檔−10% 當天一次買': return [(st, 1.0)]
    if name == 'B VIX>25 首日': return one(c1)
    if name == 'C 週RSI<40 首日': return one(c3)
    if name == 'D 條件1+2+3 同日': return one(c1 & c2 & c3)
    if name == 'E 條件1+2+3+4b 同日': return one(c1 & c2 & c3 & c4b)
    if name == 'F 回檔後等止穩（2+5）': return one(c2 & c5)
    if name == 'G 回檔後等支撐止穩（2+5s）': return one(c2 & c5s)
    if name == 'H 五條到齊': return one(all5)
    if name == 'I VIX≥30 首日': return one(vix >= 30)
    if name == 'J VIX≥40 首日': return one(vix >= 40)
    if name.startswith('K 價格梯') or name.startswith('L 價格梯'):
        lv = (0.90, 0.85, 0.80) if name.startswith('K') else (0.90, 0.80, 0.70); out = []
        for x in lv:
            i = first(pd.Series(P <= peak * x, index=idx), pk, end)
            if i is not None: out.append((i, 1 / 3))
        return out
    if name == 'M 時間梯：−10% 當天、+20、+40 日各 1/3': return [(min(st + k, len(P) - 1), 1 / 3) for k in (0, 20, 40)]
    if name == 'N 一半在 1+2+3、一半等之後止穩':
        i = first(c1 & c2 & c3, pk, end)
        if i is None: return []
        j = first(c5, i + 1, end); return [(i, 0.5)] + ([(j, 0.5)] if j is not None else [])
    if name == 'O 一半在 −10% 當天、一半等 VIX≥30':
        j = first(vix >= 30, pk, end); return [(st, 0.5)] + ([(j, 0.5)] if j is not None else [])
    raise ValueError(name)

METHODS = ['A 回檔−10% 當天一次買', 'B VIX>25 首日', 'C 週RSI<40 首日', 'D 條件1+2+3 同日', 'E 條件1+2+3+4b 同日',
           'F 回檔後等止穩（2+5）', 'G 回檔後等支撐止穩（2+5s）', 'H 五條到齊', 'I VIX≥30 首日', 'J VIX≥40 首日',
           'K 價格梯 −10/−15/−20 各 1/3', 'L 價格梯 −10/−20/−30 各 1/3', 'M 時間梯：−10% 當天、+20、+40 日各 1/3',
           'N 一半在 1+2+3、一半等之後止穩', 'O 一半在 −10% 當天、一半等 VIX≥30']

def part2():
    eps = episodes(); P = spy.values
    print('\n\n=== (二) 逐次修正：SPY 自歷史新高回檔 ≥10% 的每一段（1993→）===')
    for pk, st, tr, end, rec in eps:
        print(f'  高點 {idx[pk].date()} → 跌破−10% {idx[st].date()} → 最低 {idx[tr].date()}（{P[tr]/P[pk]-1:+.1%}）→ ' + (f'創新高 {idx[end].date()}' if rec else '尚未創新高'))
    print('\n  欄位：觸發段數／總段數｜投入比例（梯子沒成交的留現金）｜買進均價高於最低點 中位（最差）｜首筆進場相對最低點的交易日 中位（負＝早於低點）｜'
          '\n        之後 250 日整筆錢報酬 平均／中位／最差（未投入部分算 0）｜漲回前高時整筆錢報酬 平均')
    rows = {}
    for m in METHODS:
        ab, dt, r250, rath, fr = [], [], [], [], []
        for pk, st, tr, end, rec in eps:
            f = fills_for(m, pk, st, end)
            if not f: continue
            w = sum(x[1] for x in f); avg = w / sum(x[1] / P[x[0]] for x in f); f0 = f[0][0]
            ab.append(avg / P[tr] - 1); dt.append(f0 - tr); fr.append(w)
            if f0 + 250 < len(P): r250.append(sum(wt * (P[f0 + 250] / P[i] - 1) for i, wt in f if i <= f0 + 250))
            if rec: rath.append(sum(wt * (P[pk] / P[i] - 1) for i, wt in f))
        rows[m] = (len(ab), ab, dt, r250, rath, fr)
        if not ab: print(f'  {m:<34} 從未觸發'); continue
        print(f'  {m:<34} {len(ab):>2}/{len(eps)}｜投入 {np.mean(fr)*100:3.0f}%｜高於低點 中位 {np.median(ab)*100:5.1f}%（最差 {np.max(ab)*100:5.1f}%）｜相對低點 {np.median(dt):+5.0f} 日｜'
              f'250日 均 {np.mean(r250)*100:+5.1f}% 中 {np.median(r250)*100:+5.1f}% 最差 {np.min(r250)*100:+6.1f}%｜回前高 均 {np.mean(rath)*100:+5.1f}%')
    print('\n  逐段明細（買進均價高於最低點 %；— ＝該段沒觸發）')
    show = ['A 回檔−10% 當天一次買', 'D 條件1+2+3 同日', 'H 五條到齊', 'F 回檔後等止穩（2+5）', 'I VIX≥30 首日', 'K 價格梯 −10/−15/−20 各 1/3', 'M 時間梯：−10% 當天、+20、+40 日各 1/3']
    print('    最低點日     深度   ' + '  '.join(s.split(' ')[0] for s in show))
    for pk, st, tr, end, rec in eps:
        cells = []
        for m in show:
            f = fills_for(m, pk, st, end)
            if not f: cells.append('   —'); continue
            w = sum(x[1] for x in f); avg = w / sum(x[1] / P[x[0]] for x in f); cells.append(f'{(avg/P[tr]-1)*100:4.0f}')
        print(f'    {idx[tr].date()}  {P[tr]/P[pk]-1:+6.1%}  ' + ' '.join(cells))

def part3():
    print('\n\n=== (三) 每月存 1 元：等訊號才一次投入（等待期間放 T-bill）vs 每月直接買（定期定額）===')
    print('  欄位：期末資產 ÷ 總投入｜等訊號 ÷ 定期定額｜平均現金佔比｜最長連續沒訊號月數')
    conds = {'回檔≥10%（條件2）': c2, 'VIX>25（條件1）': c1, '條件1+2+3': c1 & c2 & c3, '同日 ≥3 條': ksame >= 3,
             '五條到齊': all5, '回檔後止穩（2+5）': c2 & c5, 'VIX≥30': vix >= 30, 'SPY 自 252 日高 −5%': dd <= -0.05}
    for sym, start in (('SPY', '1993-06-01'), ('SPY', '2010-01-01'), ('QQQ', '1999-06-01'), ('QQQ', '2010-01-01'), ('SMH', '2010-01-01')):
        s = C[sym].dropna(); s = s[s.index >= start]
        mf = set(pd.Series(s.index, index=s.index).groupby([s.index.year, s.index.month]).first().values)
        n_m = len(mf); dca = sum(1 / s[d] for d in s.index if d in mf) * s.iloc[-1]
        print(f'\n## {sym} {start[:4]}→　定期定額 期末 ÷ 投入 = {dca/n_m:.2f}')
        for k, cond in conds.items():
            cnd = cond.reindex(s.index).fillna(False).values; cash = 0.0; sh = 0.0; cs = []; gap = mx = 0
            for j, d in enumerate(s.index):
                cash *= 1 + rf.get(d, 0.0)
                if d in mf:
                    cash += 1; gap += 1; mx = max(mx, gap)
                if cnd[j] and cash > 0: sh += cash / s.iloc[j]; cash = 0.0; gap = 0
                if d in mf: cs.append(cash / (sh * s.iloc[j] + cash))
            fin = sh * s.iloc[-1] + cash
            print(f'  {k:<22} {fin/n_m:5.2f}｜{fin/dca:5.2f}×｜現金 {np.mean(cs)*100:3.0f}%｜最長 {mx:>3} 個月')

if __name__ == '__main__':
    print(f'資料到 {idx[-1].date()}；各條件成立天數佔比：' + '、'.join(f'{k} {v.fillna(False).mean()*100:.1f}%' for k, v in list(SIG.items())[:7]))
    print('4a 逐年代成立比例：' + '、'.join(f'{a}s {c4a[(idx.year>=a)&(idx.year<a+5)].mean()*100:.0f}%' for a in range(1995, 2030, 5) if ((idx.year >= a) & (idx.year < a + 5)).any()))
    part1(); part2(); part3()
