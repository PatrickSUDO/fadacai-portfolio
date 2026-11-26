"""strategy_leaderboard_2026-11-20.py — 測過的做法與現行系統放同一張表，比 Sharpe 與 Calmar
（2026-11-20 用戶「所以目前這麼多方式哪個 calmar ratio, sharpe ratio 最好」「你也得看看之前測過還有現在有在用的方式」）

Sharpe =（年化報酬 − 國庫券）÷ 年化波動；Calmar = 年化報酬 ÷ 最大回撤。
A 組（半導體＋VOO 或國庫券，訊號看費半；半導體報酬用 SMH 含息、2000-06 前用費半；VOO 以 SPY 含息代替）：1998-04→、另列 2009 前與 2010 後。
   含當日測的（固定比例、再平衡、乖離減碼、落底加碼、長均線換 VOO、每跌 10% 加碼梯）與 2026-10-19 測過的波動目標／200 日線半倉（tools/backtest_vol_target.py 的做法原樣搬來）。
   每個做法另跟「同樣平均曝險、同樣停泊資產的固定配置」比——差值才是擇時本身的價值；Sharpe 差附區塊重抽 95% 區間（60 日一塊 × 400 次）。
B 組（QQQ）：買進持有、200／400 日線開關、波動目標、跌 1% 買 LEAPS（Black-Scholes 估值，不是實際報價）：2000-11→、另列 2010 後。
C 組（現行系統實際績效）：個股格（實際選股與進出，每日）與整個帳戶（淨值標記）對 SMH／QQQ／VOO，同樣的日子。
其餘既有研究（核心衛星、結構替代、選擇權覆蓋、VIX、持有期間、隔夜、ETF 留強）的數字見各自報告，這裡不重跑。

首跑結論（2026-11-20，納入波動目標與現行系統之後）：
- Calmar 明顯拉開的只有一族：波動目標（其餘放國庫券）。半導體全期 Calmar 0.26（加 200 日線半倉 0.30），一直抱是 0.16；2010 後 0.71 vs 0.51；2009 前 0.09–0.15 vs 0.01。
  QQQ 也一樣：2000-11→ 0.23–0.35 vs 0.12、2010 後 0.61–0.70 vs 0.50。換參數、換標的的穩健性見 vol_target_robustness_2026-11-20.py。
- Sharpe 也是它排前面（半導體全期 0.56–0.60 vs 0.47、2010 後 0.82–0.85 vs 0.80；QQQ 2010 後 0.85–0.88 vs 0.81），但對同曝險固定配置的差 95% 區間含 0。
- 同一套波動目標把閒置部位放 VOO，好處消失（Sharpe 0.49、Calmar 0.17，與固定 70／30 相同）——現行 R33 正是放 VOO。
- 當日其他做法（固定比例、再平衡、乖離減碼、落底加碼、每跌 10% 加碼梯）扣掉同曝險固定配置後 Sharpe 差都在 ±0.02 內、Calmar 差 ±0.02 內。
- 長均線全出場：全期 Sharpe 略高（+0.02 到 +0.05）但 2010 後低於一直抱（0.74–0.75 vs 0.80）；QQQ 400 日線 Calmar 0.43／0.58，同一條線放半導體全表最差。
- 跌 1% 買 LEAPS 加上限：2010 後 Sharpe 0.87 名義並列最高，為模型估值；2000-11→ Calmar 0.18–0.20；不設上限歸零。
- 現行系統實際績效期間太短無法評比：個股格今年 Sharpe +0.13／Calmar 0.00（SMH +0.41／+0.31、QQQ −0.08／−0.03）；峰值後全部為負。
裁決（待用戶）：若目標是 Calmar，值得重開 2026-10-23 對波動目標的「不採用」；前提是閒置部位改放現金類，且要處理與 R15、R33 的衝突。

用法：python3 tools/backtests/strategy_leaderboard_2026-11-20.py
"""
import io, bisect, runpy, contextlib, numpy as np, pandas as pd, yfinance as yf, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(20261120)

def exp_pct(x, minp=756):
    out = np.full(len(x), np.nan); srt = []
    for i, v in enumerate(x):
        if np.isnan(v): continue
        bisect.insort(srt, v)
        if len(srt) >= minp: out[i] = bisect.bisect_right(srt, v) / len(srt) * 100
    return out
def metrics(ret, rfd):
    ret = np.asarray(ret, float); rfd = np.asarray(rfd, float)
    eq = np.cumprod(1 + ret); cagr = eq[-1] ** (252 / len(ret)) - 1; mdd = (eq / np.maximum.accumulate(eq) - 1).min()
    ex = ret - rfd; sh = ex.mean() / ex.std() * np.sqrt(252)
    return cagr, mdd, sh, (cagr / abs(mdd) if mdd < 0 else float('nan'))

raw = yf.download(['^SOX', 'SMH', 'SPY', '^VIX', '^IRX'], period='max', progress=False, auto_adjust=True)['Close']
sox = raw['^SOX'].dropna(); DI = sox.index
B240 = (sox / sox.rolling(240).mean() - 1).values; P240 = exp_pct(B240); e0 = int(np.where(~np.isnan(P240))[0][0])
rs_a = raw['SMH'].pct_change().reindex(DI); rs_a = rs_a.where(rs_a.notna(), sox.pct_change()).fillna(0)
D = DI[e0:]; n = len(D)
rs = rs_a.to_numpy(copy=True)[e0:]; rv = raw['SPY'].pct_change().reindex(DI).fillna(0).to_numpy(copy=True)[e0:]; rs[0] = rv[0] = 0
rf = ((raw['^IRX'] / 100).reindex(DI).ffill().fillna(0.03) / 252).values[e0:]
vix = raw['^VIX'].reindex(DI).ffill().values
p240 = P240[e0:]; b60 = (sox / sox.rolling(60).mean() - 1).values[e0:]; dd = (sox / sox.rolling(252, min_periods=120).max() - 1).values[e0:]
def first_cross(cond, look=20):
    c = pd.Series(np.asarray(cond, bool)); prev = c.shift(1).rolling(look).max().fillna(0).astype(bool); return (c & ~prev).values
vix30 = first_cross(vix >= 30)[e0:]
sh1 = lambda w, base: np.concatenate([[base], w[:-1]])

def w_overheat(p_hi, cut, re):
    w = np.empty(n); on = False
    for t in range(n):
        if not on and p240[t] >= p_hi: on = True
        elif on and ((re == 'p50' and p240[t] <= 50) or (re == 'vix30' and vix30[t])): on = False
        w[t] = 1 - cut if on else 1.0
    return sh1(w, 1.0)
def w_tilt(base, hold=250):
    w = np.empty(n); tb = -10 ** 9
    for t in range(n):
        if vix30[t]: tb = t
        w[t] = 1.0 if t - tb < hold else base
    return sh1(w, base)
def w_ma(N, confirm, lo):
    above = ((sox / sox.rolling(N).mean() - 1).values[e0:]) > 0; w = np.empty(n); cur = 1.0; run = 0
    for t in range(n):
        want = 1.0 if above[t] else lo
        if want != cur:
            run += 1
            if run >= confirm: cur = want; run = 0
        else: run = 0
        w[t] = cur
    return sh1(w, 1.0)
def w_ladder(base, unwind):
    w = np.empty(n); kd = 0; held = 0; slots = int(round((1 - base) / 0.10))
    for t in range(n):
        if (unwind == 'ma60' and b60[t] >= 0) or (unwind == 'dd10' and dd[t] >= -0.10): held = 0
        if dd[t] > -0.05: kd = 0
        if b60[t] < 0:
            k = int(np.floor(-dd[t] / 0.10 + 1e-9))
            while kd < k: kd += 1; held = min(slots, held + 1)
        w[t] = base + 0.10 * held
    return sh1(w, base)
def vt_exposure(ret, price, target=0.20, trend=False, vt=True):
    """tools/backtest_vol_target.py 的規則：曝險 = min(1, 目標 ÷ 20 日實現波動)，週五收盤決定、變動 <10% 不動；trend = 200 日線下減半；隔日生效。"""
    exp = pd.Series(1.0, index=ret.index)
    if vt:
        vol = ret.rolling(20).std() * np.sqrt(252); raw_ = (target / vol).clip(upper=1.0).fillna(1.0)
        wk = raw_.where(raw_.index.weekday == 4).ffill().fillna(1.0); held = [1.0]
        for v_ in wk.iloc[1:]: held.append(v_ if abs(v_ - held[-1]) >= 0.10 else held[-1])
        exp = pd.Series(held, index=ret.index)
    if trend: exp = exp * (price > price.rolling(200).mean()).astype(float).replace(0.0, 0.5)
    return exp.shift(1).fillna(1.0)
def ret_of(w, rest='voo', cost=0.001):
    r = w * rs + (1 - w) * (rv if rest == 'voo' else rf); r[1:] -= np.abs(np.diff(w)) * cost; return r
def ret_drift(base, mask):
    a = np.cumprod(1 + rs[mask]); b = np.cumprod(1 + rv[mask]); v = base * a + (1 - base) * b
    return np.diff(np.concatenate([[1.0], v])) / np.concatenate([[1.0], v[:-1]])

VT = lambda **k: vt_exposure(rs_a, sox, **k).values[e0:]
STR = {
    '半導體 100%（一直抱）': (np.ones(n), 'voo'), 'VOO 100%': (np.zeros(n), 'voo'),
    '固定 70／30（每日再平衡）': (np.full(n, 0.7), 'voo'), '固定 50／50': (np.full(n, 0.5), 'voo'), '固定 30／70': (np.full(n, 0.3), 'voo'),
    '年線乖離 ≥99 分位減半，回中位買回': (w_overheat(99, 0.5, 'p50'), 'voo'), '年線乖離 ≥95 分位減半，VIX≥30 買回': (w_overheat(95, 0.5, 'vix30'), 'voo'),
    '平時 70%，VIX 首次站上 30 加滿抱一年': (w_tilt(0.7), 'voo'), '平時 50%，VIX 首次站上 30 加滿抱一年': (w_tilt(0.5), 'voo'),
    '跌破 200 日線全換 VOO': (w_ma(200, 1, 0.0), 'voo'), '跌破 240 日線（連 5 日）全換 VOO': (w_ma(240, 5, 0.0), 'voo'), '跌破 240 日線（連 5 日）換一半到 VOO': (w_ma(240, 5, 0.5), 'voo'),
    '跌破 400 日線（連 5 日）全換 VOO': (w_ma(400, 5, 0.0), 'voo'),
    '平時 50%＋每跌 10% 加一梯，站回季線賣回': (w_ladder(0.5, 'ma60'), 'voo'), '平時 70%＋每跌 10% 加一梯，站回季線賣回': (w_ladder(0.7, 'ma60'), 'voo'),
    '平時 50%＋每跌 10% 加一梯，回高點才賣回': (w_ladder(0.5, 'dd10'), 'voo'),
    '波動目標 20%（其餘國庫券）': (VT(), 'bill'), '波動目標 20%（其餘 VOO）': (VT(), 'voo'),
    '200 日線下半倉（其餘國庫券）': (VT(vt=False, trend=True), 'bill'), '波動目標 20%＋200 日線下半倉（其餘國庫券）': (VT(trend=True), 'bill'),
    '波動目標 20%＋200 日線下半倉（其餘 VOO）': (VT(trend=True), 'voo'),
}
WIN = {'全期（1998-04→）': np.ones(n, bool), '2009 前': np.asarray(D < '2010-01-01'), '2010 後': np.asarray(D >= '2010-01-01')}
RET = {k: ret_of(w, rest) for k, (w, rest) in STR.items()}
MA_ = {nm: {wn: metrics(r[m], rf[m]) for wn, m in WIN.items()} for nm, r in RET.items()}
AVG = {nm: w.mean() for nm, (w, rest) in STR.items()}
for base in (0.7, 0.5):
    nm = f'起始 {base*100:.0f}／{100-base*100:.0f} 不再平衡（讓它漂）'; MA_[nm] = {wn: metrics(ret_drift(base, m), rf[m]) for wn, m in WIN.items()}; AVG[nm] = float('nan')
def table(title, rows, wins, avg=None):
    if title: print(title)
    for wn in wins:
        r_ = sorted(((nm, *m_[wn]) for nm, m_ in rows.items()), key=lambda x: -(x[3] if x[3] == x[3] else -9)); cal = sorted(r_, key=lambda x: -x[4]); crank = {x[0]: i + 1 for i, x in enumerate(cal)}
        print(f'  【{wn}】依 Sharpe 排序：年化／最大回撤／Sharpe／Calmar（Calmar 名次）' + ('／平均半導體曝險' if avg else ''))
        for i, (nm, c, m_, s, ca) in enumerate(r_):
            print(f'   {i+1:>2}. {nm:<34} {c*100:+6.1f}% {m_*100:6.0f}% {s:6.2f} {ca:6.2f}（{crank[nm]}）' + (f' {avg[nm]*100:4.0f}%' if avg and avg[nm] == avg[nm] else ''))
table('=== A 組：半導體＋VOO／國庫券 ===', MA_, list(WIN), AVG)

print('\n--- A 組：扣掉「同樣平均曝險、同樣停泊資產的固定配置」之後還剩多少（＝擇時本身的價值）---')
nb = n // 60 + 1
def boot(r, ref):
    out = []
    for _ in range(400):
        st = RNG.integers(0, n - 60, nb); idx = (st[:, None] + np.arange(60)[None, :]).ravel()[:n]
        a = r[idx] - rf[idx]; b = ref[idx] - rf[idx]; out.append(a.mean() / a.std() * np.sqrt(252) - b.mean() / b.std() * np.sqrt(252))
    return np.percentile(out, [2.5, 97.5])
s70 = MA_['固定 70／30（每日再平衡）']['全期（1998-04→）'][2]
print(f'  單一做法 Sharpe 的標準誤：全期約 ±{np.sqrt((1 + s70**2 / 2) / (n / 252)):.2f}、2010 後約 ±{np.sqrt((1 + 0.8**2 / 2) / (WIN["2010 後"].sum() / 252)):.2f}')
print('  做法　　　　　　　　　　　　　　　　　｜全期 Sharpe 差（95% 區間）｜全期 Calmar 差｜2010 後 Sharpe 差／Calmar 差')
for nm, (w, rest) in STR.items():
    if w.std() < 1e-9: continue
    ref = ret_of(np.full(n, w.mean()), rest); lo, hi = boot(RET[nm], ref); out = []
    for wn in ('全期（1998-04→）', '2010 後'):
        m_ = WIN[wn]; a = metrics(RET[nm][m_], rf[m_]); b = metrics(ret_of(np.full(n, w[m_].mean()), rest)[m_], rf[m_]); out.append((a[2] - b[2], a[3] - b[3]))
    print(f'  {nm:<34}｜{out[0][0]:+.2f}（{lo:+.2f} ～ {hi:+.2f}）{"＊" if lo > 0 or hi < 0 else "　"}｜{out[0][1]:+.2f}｜{out[1][0]:+.2f}／{out[1][1]:+.2f}')
print('  ＊＝區間不含 0')

print('\n=== B 組：QQQ ===')
with contextlib.redirect_stdout(io.StringIO()):
    g = runpy.run_path(str(HERE / 'qqq_leaps_dip_2026-11-20.py'))
qq = g['adj_s'].dropna(); rfq = pd.Series(g['rf'], index=g['dates']).reindex(qq.index).ffill().fillna(0.03) / 252
def m_of(s):
    r = s.pct_change().dropna(); return metrics(r.values, rfq.reindex(r.index).fillna(0).values)
def vt_eq(st, **k):
    r = qq.pct_change().fillna(0); e = vt_exposure(r, qq, **k); x = (e * r + (1 - e) * rfq)[st:]; return (1 + x).cumprod()
MB = {}
for wn, st in (('2000-11→', '2000-11-01'), ('2010 後', '2010-01-04')):
    cands = {'QQQ 買進持有': qq[st:], 'QQQ 200 日線開關（線下全放國庫券）': g['switch_hold'](g['adj_s'], g['on'][200], st)[0], 'QQQ 400 日線開關（線下全放國庫券）': g['switch_hold'](g['adj_s'], g['on'][400], st)[0],
             'QQQ 波動目標 20%': vt_eq(st), 'QQQ 200 日線下半倉': vt_eq(st, vt=False, trend=True), 'QQQ 波動目標 20%＋200 日線下半倉': vt_eq(st, trend=True),
             '跌 1% 買 LEAPS，權利金上限 20%（模型估值）': g['portfolio'](g['paths1'], 0.05, st, cap=0.20), '跌 1% 買 LEAPS，權利金上限 30%（模型估值）': g['portfolio'](g['paths1'], 0.05, st, cap=0.30),
             '跌 1% 買 LEAPS，不設上限（模型估值）': g['portfolio'](g['paths1'], 0.05, st)}
    for nm, s in cands.items(): MB.setdefault(nm, {})[wn] = m_of(s) if s.min() > 1e-6 else (-1.0, -1.0, float('nan'), -1.0)
table('', MB, ['2000-11→', '2010 後'])

print('\n=== C 組：現行系統的實際績效（期間太短，Sharpe 的標準誤 ±1 到 ±2，只能當紀錄）===')
with contextlib.redirect_stdout(io.StringIO()):
    a_ = runpy.run_path(str(HERE / 'account_target_rebalance_sim_2026-11-20.py'))
S = a_['S']; marks = a_['marks']
px = yf.download(['SMH', 'QQQ', 'VOO'], start='2025-12-26', progress=False, auto_adjust=True)['Close']; rfx = (raw['^IRX'] / 100 / 252).ffill()
def line(lab, r, rfd_):
    c, m_, s, ca = metrics(r, rfd_); tot = np.prod(1 + np.asarray(r)) - 1
    print(f'    {lab:<22} 期間 {tot*100:+6.1f}%｜最大回撤 {m_*100:6.1f}%｜Sharpe {s:+5.2f}｜Calmar {ca:+5.2f}')
for lab, a, b in (('今年 1/1→今', '2025-12-31', None), ('上半年 1/1→6/22', '2025-12-31', '2026-06-22'), ('峰值後 6/22→今', '2026-06-22', None)):
    idx = S.index[(S.index > pd.Timestamp(a)) & ((S.index <= pd.Timestamp(b)) if b else True)]; rr = rfx.reindex(idx).fillna(0)
    print(f'  {lab}（每日）：'); line('個股格（實際選股與進出）', S.rs[idx], rr)
    for b_ in ('SMH', 'QQQ', 'VOO'): line(b_ + ' 買進持有', px[b_].pct_change().reindex(idx).fillna(0), rr)
mk = marks[marks.index >= '2026-06-01']; mk = mk[~mk.index.duplicated()]; gaps = mk.index.to_series().diff().dt.days
r = mk.pct_change().dropna(); r = r[gaps.reindex(r.index) <= 5]; rr = rfx.reindex(r.index).fillna(0)
print('  整個帳戶 6/2→今（淨值標記日對標記日，含現金、VOO、選擇權）：'); line('帳戶（實際）', r, rr)
for b_ in ('SMH', 'QQQ', 'VOO'): line(b_ + '（同樣的標記日）', px[b_].reindex(mk.index, method='ffill').pct_change().reindex(r.index).fillna(0), rr)
