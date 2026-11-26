"""account_target_rebalance_sim_2026-11-20.py — 用帳戶實際的個股部位，試算「目標比例＋再平衡帶＋每跌 10% 補回」
（2026-11-20 用戶點「試算」；承 bias_overheat／ladder_below_ma60 兩支回測的結論）

做法：
1. 從今日即時部位（LIVE_SH，重跑前要更新）往回套成交帳，還原 2026 年每天收盤的現股部位（現單位股數）。
2. 「個股格」= 全部個股（不含 ETF、不含選擇權）。個股格每日報酬 =（今日市值 − 今日淨買進）÷ 昨日市值 − 1，
   也就是「你實際選的股票、實際的進出」的報酬，跟放多少比例無關。
3. 規則只管比例：個股格目標 T，其餘放 VOO。可選的動作——
   上緣帶：個股格比重 ≥ T＋帶寬 → 減回 T；
   補回梯：SMH 自一年高點每多跌 10%（且收盤在季線下）→ 個股格若低於 T，補回 T；
   月初再平衡：每月第一個交易日調回 T（對照）。
   收盤判定、隔日收盤執行、每次 10bp。
4. 兩個起點：2026-01-01（整年照做）與 2026-06-22（帳戶峰值）。對照：實際帳戶、同樣起始比例但完全不調整。
限制：選擇權不在個股格裡（上半年 LEAPS 的損益沒算進來）；1/1 部位由成交帳反推（約 3% 誤差）；股息只算 VOO。

首跑結論（2026-11-20，帳戶 $199,575）：
- 個股格實際報酬（含所有進出、不含選擇權）：1/1→6/22 +46.3%、6/22→今 −31.3%、全年 +0.5%（SMH +85.7%／−39.6%，VOO +9.7%／−6.5%）。
- 實際的個股比重是跟著行情反著走的：6/19 重整後 67%（剛好在頂）→ 四週內 SMH 跌 17% 時加回到 90% → 7 月到 10 月中都在 80–89% →
  11 月跌 30–40% 之後降到 62%。高點附近最低、下跌途中最高、跌深之後又減。
- 從峰值照做（6/22 起，$283,810）：個股格固定 70%、其餘 VOO、完全不調整 → 今 $216,024（−23.9%），實際 $199,575（−29.7%），差 $16k；
  其餘放現金是 $221,579。差距來自 LEAPS 疊在上面（約 $10k）與下跌途中把比重加到 80–90%。補回梯（7/17、7/29、11/6 三次共 $14.7k）到今天反而少 $1.6k。
- 整年照做（1/1 起）：不管目標 50%～93%，今天都落在 +0.7% 到 +3.0%——個股格本身全年 +0.5%，目標比例鎖不住 6 月的獲利，只按比例縮小擺幅
  （6/22 當天 +28% 到 +44%、年內最大回撤 −23% 到 −32%）。上緣帶 ±10 整年沒觸發；±5 在 6/1–6/3 減一次 $14k。再平衡全年多 $2–3k。
- 現況：個股格 62.4%、VOO 27.3%、XLE 3.5%、現金 6.9%；SMH 第 3 梯已到（11/5）、第 4 梯在 401。目標 65% → 這一梯換 $5.2k、目標 70% → $15.2k、目標 60% → 不動。

用法：python3 tools/backtests/account_target_rebalance_sim_2026-11-20.py
"""
import json, collections, numpy as np, pandas as pd, yfinance as yf, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent; DATA = HERE / "data"
LIVE_TOTAL, LIVE_CASH = 199575, 13841
LIVE_SH = {'AMAT': 15, 'ANET': 52, 'AVGO': 30.33493, 'CRDO': 21, 'CRM': 65.04313, 'CRWD': 86, 'DIOD': 100, 'MU': 22.00985, 'NET': 15,
           'NVDA': 85.13919, 'PLTR': 95, 'SNPS': 28, 'TWLO': 37, 'VOO': 85, 'XLE': 114.7429}
ETFS = {'VOO', 'SGOV', 'BIL', 'GLD', 'XLE', 'SMH', 'IGV', 'SPY', 'QQQ', 'SOXX', 'QLD', 'USD'}
Y0, PEAK = '2026-01-01', '2026-06-22'
E_Y0, E_PEAK = 198411.65, 283810

fills = [json.loads(l) for l in open('research/trade-ledger.jsonl')]
f26 = sorted([f for f in fills if f['date'] >= Y0 and not f['is_option']], key=lambda f: f['date'])
def sq(f):
    sp = f.get('split_adj_price') or f['price']; q = f['notional'] / sp if sp else f['qty']
    return q if f['side'].upper().startswith('B') else -q
pos0 = collections.defaultdict(float); pos0.update(LIVE_SH)
for f in f26: pos0[f['symbol']] -= sq(f)
syms = sorted(set(pos0) | {f['symbol'] for f in f26}); ym = {s: s.replace('.', '-') for s in syms}
px = yf.download(sorted(set(ym.values())), start='2025-12-26', progress=False, auto_adjust=False)['Close']
adj = yf.download(['VOO', 'SMH'], start='2024-06-01', progress=False, auto_adjust=True)['Close']
days = px.index[px.index >= '2025-12-31']
nopx = [s for s in syms if ym[s] not in px.columns or px[ym[s]].loc[days].isna().all()]
by_day = collections.defaultdict(list)
for f in f26:
    d = days[days.searchsorted(pd.Timestamp(f['date']))] if days.searchsorted(pd.Timestamp(f['date'])) < len(days) else days[-1]
    by_day[d].append(f)
cur = {s: q for s, q in pos0.items()}; rows = []
for d in days:
    nb = 0.0
    for f in by_day.get(d, []):
        s = f['symbol']; cur[s] = cur.get(s, 0.0) + sq(f)
        if s not in ETFS and s not in nopx: nb += -f['amount']
    ms = me = 0.0
    for s, q in cur.items():
        if abs(q) < 1e-6 or s in nopx: continue
        p = px.at[d, ym[s]]
        if np.isnan(p): p = px[ym[s]].loc[:d].ffill().iloc[-1]
        if np.isnan(p): continue
        if s in ETFS: me += q * p
        else: ms += q * p
    rows.append((d, ms, me, nb))
S = pd.DataFrame(rows, columns=['date', 'mv_s', 'mv_e', 'nb']).set_index('date')
S['rs'] = (S.mv_s - S.nb) / S.mv_s.shift(1) - 1; S['rs'] = S['rs'].fillna(0)
S['rv'] = adj['VOO'].pct_change().reindex(S.index).fillna(0)
m = json.load(open('research/equity-marks.json'))
marks = pd.Series({x['date']: x['value'] for x in m['manual'] + [y for y in m['marks'] if not y.get('excluded') and y.get('kind') == 'total']}).sort_index()
marks.index = pd.to_datetime(marks.index); marks.loc[S.index[-1]] = LIVE_TOTAL
at = lambda d: S.index[min(S.index.searchsorted(pd.Timestamp(d)), len(S) - 1)]

print('=== 0. 還原檢查 ===')
if nopx: print('  無報價、不計入個股格：', nopx)
print(f'  個股格市值：1/1 ${S.mv_s.iloc[0]:,.0f}（成交帳反推）、6/22 ${S.mv_s[at(PEAK)]:,.0f}（當日日誌盤中 $197,441）、11/19 ${S.mv_s[at("2026-11-19")]:,.0f}（日誌反推約 $134,100）、最新 ${S.mv_s.iloc[-1]:,.0f}')
tw = lambda a, b: (1 + S.rs[(S.index > at(a)) & (S.index <= at(b))]).prod() - 1
vo = lambda a, b: adj['VOO'][at(b)] / adj['VOO'][at(a)] - 1
sm = lambda a, b: adj['SMH'][at(b)] / adj['SMH'][at(a)] - 1
print(f'  個股格實際報酬（含你所有進出、不含選擇權）：1/1→6/22 {tw("2025-12-31", PEAK)*100:+.1f}%（SMH {sm("2025-12-31", PEAK)*100:+.1f}%、VOO {vo("2025-12-31", PEAK)*100:+.1f}%）；'
      f'6/22→今 {tw(PEAK, S.index[-1])*100:+.1f}%（SMH {sm(PEAK, S.index[-1])*100:+.1f}%、VOO {vo(PEAK, S.index[-1])*100:+.1f}%）；全年 {tw("2025-12-31", S.index[-1])*100:+.1f}%')

print('\n=== 1. 你實際的個股格比重（個股市值 ÷ 帳戶淨值；6 月有 LEAPS 另計）===')
for d in ['2026-01-01', '2026-06-22', '2026-07-31', '2026-08-31', '2026-09-30', '2026-10-06', '2026-10-16', '2026-10-29', '2026-11-04', '2026-11-06', '2026-11-12', '2026-11-19', '2026-11-20']:
    t = at(d); mk = marks[:t]
    if not len(mk): continue
    print(f'  {d}：個股 {S.mv_s[t]/mk.iloc[-1]*100:5.1f}%、ETF（VOO／SGOV／GLD／XLE）{S.mv_e[t]/mk.iloc[-1]*100:5.1f}%、其餘（現金與選擇權）{(1-(S.mv_s[t]+S.mv_e[t])/mk.iloc[-1])*100:5.1f}%｜淨值 ${mk.iloc[-1]:,.0f}｜SMH 距一年高點 {(adj["SMH"][t]/adj["SMH"][:t].tail(252).max()-1)*100:+.0f}%')

# SMH 高點回檔梯：自一年高點每多跌 10% 且收盤在季線下 → 新的一梯；回到高點 5% 內重置
smh = adj['SMH'].dropna(); hi = smh.rolling(252, min_periods=120).max(); ddv = (smh / hi - 1); m60 = smh.rolling(60).mean()
kd = 0; rung = {}
for d in smh.index:
    if np.isnan(ddv[d]): continue
    if ddv[d] > -0.05: kd = 0
    if smh[d] < m60[d]:
        k = int(np.floor(-ddv[d] / 0.10 + 1e-9))
        if k > kd: kd = k; rung[d] = k
print('\n2026 年 SMH 補回梯觸發日：' + '、'.join(f'{d.date()} 第 {k} 梯（SMH {smh[d]:.0f}）' for d, k in rung.items() if d >= pd.Timestamp(Y0)))

def simulate(start, E0, T, mode, band=0.10, rest='VOO', cost=0.001):
    idx = S.index[S.index >= at(start)]; Vs = E0 * T; Vr = E0 * (1 - T); pend = None; log = []; path = [E0]
    for i in range(1, len(idx)):
        d = idx[i]; Vs *= 1 + S.rs[d]; Vr *= 1 + (S.rv[d] if rest == 'VOO' else 0)
        if pend:
            tot = Vs + Vr; amt = T * tot - Vs; c = abs(amt) * cost; log.append((d, pend, amt, Vs / tot)); Vs += amt; Vr -= amt + c; pend = None
        w = Vs / (Vs + Vr)
        if 'band' in mode and w >= T + band: pend = '上緣減回'
        elif 'ladder' in mode and d in rung and w < T - 0.005: pend = f'第 {rung[d]} 梯補回'
        elif mode == 'monthly' and i + 1 < len(idx) and idx[i + 1].month != d.month and abs(w - T) > 0.01: pend = '月初調回'
        path.append(Vs + Vr)
    p = pd.Series(path, index=idx)
    return p, log, Vs / (Vs + Vr)
def show(lab, p, log, wend, ref=None):
    mdd = (p / p.cummax() - 1).min(); pk = p[:at(PEAK)].iloc[-1] if p.index[0] < at(PEAK) else p.iloc[0]
    line = f'  {lab:<34} 今 ${p.iloc[-1]:>9,.0f}（{(p.iloc[-1]/p.iloc[0]-1)*100:+6.1f}%）'
    if p.index[0] < at(PEAK): line += f'｜6/22 ${pk:>9,.0f}（{(pk/p.iloc[0]-1)*100:+5.1f}%）'
    line += f'｜期間最大回撤 {mdd*100:5.1f}%｜期末個股格 {wend*100:.0f}%｜調整 {len(log)} 次'
    if ref is not None: line += f'｜比不調整 {p.iloc[-1]-ref:+,.0f}'
    print(line)
    for d, what, amt, wb in log: print(f'        {d.date()} {what}：{"買" if amt > 0 else "賣"}個股格 ${abs(amt):,.0f}（調整前比重 {wb*100:.0f}%）')
MODES = [('完全不調整', 'drift', 0.10), ('只做補回梯', 'ladder', 0.10), ('上緣帶 ±10 ＋補回梯', 'band+ladder', 0.10), ('上緣帶 ±5 ＋補回梯', 'band+ladder', 0.05), ('每月初調回', 'monthly', 0.10)]

print('\n=== 2. 整年照做（1/1 起，淨值 $198,412；實際帳戶今 $199,575 ＝ +0.6%，6/22 $283,810 ＝ +43.0%）===')
mk = marks[marks.index >= Y0]; acct_mdd = (mk / mk.cummax() - 1).min()
print(f'  實際帳戶：期間最大回撤 {acct_mdd*100:.1f}%')
for T in (0.93, 0.80, 0.70, 0.60, 0.50):
    ref = None
    for lab, mode, band in (MODES if T < 0.9 else MODES[:1]):
        p, log, wend = simulate('2025-12-31', E_Y0, T, mode, band)
        show(f'個股格 {T*100:.0f}%｜{lab}', p, log, wend, ref)
        if mode == 'drift': ref = p.iloc[-1]

print('\n=== 3. 從峰值照做（6/22 起，淨值 $283,810；實際帳戶今 $199,575 ＝ −29.7%）===')
p, log, wend = simulate(PEAK, E_PEAK, 0.70, 'drift', rest='cash'); show('個股格 70%｜其餘放現金不調整（最接近你當時）', p, log, wend)
for T in (0.80, 0.70, 0.60, 0.50):
    ref = None
    for lab, mode, band in (MODES[0], MODES[1], MODES[4]):
        p, log, wend = simulate(PEAK, E_PEAK, T, mode, band)
        show(f'個股格 {T*100:.0f}%｜{lab}', p, log, wend, ref)
        if mode == 'drift': ref = p.iloc[-1]

print('\n=== 4. 現在照規則要做什麼（即時部位：淨值 $199,575）===')
voo = 54578.5; xle = 7022.27; stk = LIVE_TOTAL - voo - xle - LIVE_CASH + 400
print(f'  個股格 ${stk:,.0f}（{stk/LIVE_TOTAL*100:.1f}%）、VOO ${voo:,.0f}（{voo/LIVE_TOTAL*100:.1f}%）、XLE ${xle:,.0f}（{xle/LIVE_TOTAL*100:.1f}%）、現金 ${LIVE_CASH:,.0f}（{LIVE_CASH/LIVE_TOTAL*100:.1f}%）')
t = smh.index[-1]; nk = int(np.floor(-ddv[t] / 0.10 + 1e-9)) + 1
print(f'  SMH {smh[t]:.1f}，距一年高點 {ddv[t]*100:.0f}%；已觸發到第 {kd} 梯，下一梯（第 {nk} 梯）在 {hi[t]*(1-0.1*nk):.0f}')
for T in (0.60, 0.65, 0.70, 0.75):
    gap = T * LIVE_TOTAL - stk
    print(f'  目標 {T*100:.0f}%：' + (f'個股格低於目標 ${gap:,.0f} → 這一梯把 ${gap:,.0f} 從 VOO 換過去（VOO 剩 ${voo-gap:,.0f}）' if gap > 0.005 * LIVE_TOTAL else f'個股格已在目標附近（差 ${gap:,.0f}），這一梯不動'))
out = pd.DataFrame({'actual_w': (S.mv_s / marks.reindex(S.index)).round(4), 'smh_dd': ddv.reindex(S.index).round(4)})
for T in (0.70, 0.60):
    idx = S.index[S.index >= at('2025-12-31')]; Vs = E_Y0 * T; Vr = E_Y0 * (1 - T); ws = [T]; pend = False
    for i in range(1, len(idx)):
        d = idx[i]; Vs *= 1 + S.rs[d]; Vr *= 1 + S.rv[d]
        if pend: tot = Vs + Vr; a = T * tot - Vs; Vs += a; Vr -= a; pend = False
        w = Vs / (Vs + Vr)
        if w >= T + 0.10 or (d in rung and w < T - 0.005): pend = True
        ws.append(w)
    out[f'rule_w_{int(T*100)}'] = pd.Series(ws, index=idx).round(4)
out.to_csv(DATA / 'account_target_rebalance_sim_2026-11-20.csv')

print('\n=== 5. 同一個個股格改用「波動目標」（2026-10-19 測過、10-23 未採用的做法；規則同 tools/backtest_vol_target.py）===')
rfd5 = (yf.download('^IRX', start='2025-12-01', progress=False, auto_adjust=True)['Close'].squeeze() / 100 / 252).reindex(S.index).ffill().fillna(0)
below5 = (smh < smh.rolling(200).mean()).reindex(S.index).fillna(False).values
def vt5(target, trend=False):
    vol = S.rs.rolling(20).std() * np.sqrt(252); raw_ = (target / vol).clip(upper=1.0).fillna(1.0)
    wk = raw_.where(raw_.index.weekday == 4).ffill().fillna(1.0); held = [1.0]
    for x in wk.iloc[1:]: held.append(x if abs(x - held[-1]) >= 0.10 else held[-1])
    e = pd.Series(held, index=S.index)
    if trend: e = e * np.where(below5, 0.5, 1.0)
    return e.shift(1).fillna(1.0)
def show5(lab, e, rest):
    r = e * S.rs + (1 - e) * (rfd5 if rest == 'bill' else S.rv); r.iloc[1:] -= e.diff().abs().iloc[1:] * 0.001
    eq = E_Y0 * (1 + r).cumprod(); pk = eq[:at(PEAK)].iloc[-1]
    print(f'  {lab:<36} 今 ${eq.iloc[-1]:>9,.0f}（{(eq.iloc[-1]/E_Y0-1)*100:+5.1f}%）｜6/22 {(pk/E_Y0-1)*100:+5.1f}%｜最大回撤 {(eq/eq.cummax()-1).min()*100:5.1f}%｜平均曝險 {e.mean()*100:.0f}%、6/22 {e[:at(PEAK)].iloc[-1]*100:.0f}%、現在 {e.iloc[-1]*100:.0f}%')
v5 = S.rs.rolling(20).std() * np.sqrt(252)
print(f'  個股格 20 日年化波動：今年中位 {v5.median()*100:.0f}%、6/22 {v5[:at(PEAK)].iloc[-1]*100:.0f}%、現在 {v5.iloc[-1]*100:.0f}%')
one5 = pd.Series(1.0, index=S.index)
show5('個股 100% 不調整', one5, 'bill'); show5('個股固定 70%，其餘國庫券', one5 * 0.7, 'bill'); show5('個股固定 70%，其餘 VOO', one5 * 0.7, 'voo')
for tg in (0.20, 0.25, 0.30): show5(f'波動目標 {tg*100:.0f}%，其餘國庫券', vt5(tg), 'bill')
show5('波動目標 25%，其餘 VOO', vt5(0.25), 'voo'); show5('波動目標 25%＋SMH 200 日線下半倉，其餘國庫券', vt5(0.25, True), 'bill')
