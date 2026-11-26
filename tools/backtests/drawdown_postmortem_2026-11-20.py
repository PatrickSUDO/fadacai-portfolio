"""drawdown_postmortem_2026-11-20.py — 2026 年帳戶從 +43% 回到 +0.6%：有沒有什麼事先做好就能避免？
（2026-11-20 用戶「今天又大跌今年基本沒賺了，在反思有沒有什麼事情先做好就能避免」）

資料：research/equity-marks.json（淨值標記）、research/trade-ledger.jsonl（成交）、journal 6/22 與 10/30 的倉位快照、
Firstrade 2026-11-20 14:17 ET 即時部位（寫死在 LIVE／LIVE_SH，重跑前要更新）、yfinance 還原價。

首跑結論（2026-11-20，帳戶 $199,575）：
- 今年帳戶 +0.6%、QQQ +0.6%、VOO +2.9%、SMH +12.9%。帳戶與 SMH 同一天（6/22）見頂：帳戶 +43.0%（$283,810）、SMH +85.7%；
  之後 SMH −39.2%、帳戶 −29.7%（−$84k）。
- 凍結對照（那天之後完全不動）：1/1 起凍結 → 6/22 當天 +46.5%、今天 +5.0%，實際 +43.0%／+0.6% → 全年操作少賺約 4pp（多數在上半年）；
  6/22 起凍結 → $197.4k vs 實際 $199.6k（峰後 252 筆成交淨效果約零）；10/29 起凍結 → $193.3k vs 實際 $199.6k（多留約 $6k）。
  今年 738 筆成交，買進 $117 萬、賣出 $117 萬，約淨值的 5 倍。
- 6/22 帳本對 SMH 的 β 0.75（LEAPS 以 delta 名目計）× SMH −39.2% = −29.4%，實際 −29.7% → 回撤全部可由曝險解釋。今日帳本 β 0.47。
- 分散沒有作用：6/22 帳本個股兩兩相關中位 0.30 → 峰後 0.53；MYRG／STRL（標成工業基建）對 SMH 相關 0.51 → 0.73，各跌 48%／73%。
- 6/22 SMH 高於 200 日線 62%。費半指數 1994→ 超過 50% 只有 1995、1999、2000 三次，之後 250 日內最深回檔中位 −29%（任意日 −14%），
  但 60／120 日報酬仍為正 → 是風險加倍的狀態，不是賣出訊號，n=3 無法驗成規則。
- 梯級停利（R8，7/1 建立）若 6/22 當天就套用：不含信念桶多留約 $6k、含信念桶約 $13k，對 −$84k 是小數。
- SMH 200 日線 11/2 才跌破（距峰 −24%），之後再跌 20%；長期代價見 trend_switch_ema_macd_2026-11-16.py。
- 停泊 VOO（R33，10/20 起）至今 −$4.3k；帳本多頭曝險仍 93%。
裁決（待用戶）：不為這次下跌加進出場規則；候選只有「對 SMH 的 β 上限」（配置決定）與「板塊過熱時停利不豁免信念桶」（事前承諾，非驗證過的規則）。

用法：python3 tools/backtests/drawdown_postmortem_2026-11-20.py
"""
import json, re, collections, numpy as np, pandas as pd, yfinance as yf, warnings
warnings.filterwarnings("ignore")
LIVE_TOTAL = 199575
LIVE = {'AMAT': 4619.25, 'ANET': 8771.88, 'AVGO': 9286.43, 'CRDO': 2155.86, 'CRM': 11960.78, 'CRWD': 19890.94, 'DIOD': 7429 - 400,
        'MU': 13356.24, 'NET': 4146.9, 'NVDA': 11307.34, 'PLTR': 13883.3, 'SNPS': 11253.48, 'TWLO': 6476.85, 'VOO': 54578.5, 'XLE': 7022.27}
LIVE_SH = {'AMAT': 15, 'ANET': 52, 'AVGO': 30.33493, 'CRDO': 21, 'CRM': 65.04313, 'CRWD': 86, 'DIOD': 100, 'MU': 22.00985, 'NET': 15,
           'NVDA': 85.13919, 'PLTR': 95, 'SNPS': 28, 'TWLO': 37, 'VOO': 85, 'XLE': 114.7429}
PEAK, PEAK_TOTAL, PEAK_CASH = '2026-06-22', 283810, 67868.58
Y0_TOTAL, Y0_CASH = 198411.65, 13362

def num(s):
    s = s.replace('−', '-').replace('$', '').replace(',', '').replace('*', '').strip()
    m = re.search(r'-?\d+(\.\d+)?', s); return float(m.group()) if m else None
def rows_of(path):
    for ln in open(path):
        if ln.startswith('|') and '標的' not in ln and '---' not in ln:
            c = [x.strip() for x in ln.strip().strip('|').split('|')]
            if len(c) >= 6: yield c
peak_raw = {c[0].replace('*', ''): num(c[4]) for c in rows_of('journal/2026-06-22.md') if num(c[4]) is not None}
peak_pct = {c[0].replace('*', '').split()[0]: num(c[6]) for c in rows_of('journal/2026-06-22.md') if num(c[4]) is not None and len(c) > 6}
peak_stk = {k.split()[0]: v for k, v in peak_raw.items() if '270115' not in k and 'bull put' not in k}
oct_pos = {}
for c in rows_of('journal/2026-10-30.md'):
    try: oct_pos[c[0]] = float(c[2]) * float(c[4])
    except ValueError: pass
fills = [json.loads(l) for l in open('research/trade-ledger.jsonl')]
f26 = [f for f in fills if f['date'] >= '2026-01-01']

# 1/1 部位反推（現單位股數）
pos0 = collections.defaultdict(float); pos0.update(LIVE_SH)
for f in f26:
    if f['is_option']: continue
    sp = f.get('split_adj_price') or f['price']; q = f['notional'] / sp if sp else f['qty']
    pos0[f['symbol']] += -q if f['side'].upper().startswith('B') else q
pos0 = {k: v for k, v in pos0.items() if abs(v) > 0.05}

tk = sorted(set(peak_stk) | set(oct_pos) | set(LIVE) | set(pos0) | {'TSLA', 'GOOGL', 'SMH', 'QQQ', 'VOO', 'SPY', 'IGV', 'SPCX'})
adj = yf.download(tk, start='2025-01-01', progress=False, auto_adjust=True)['Close']
raw = yf.download(tk, start='2025-12-20', progress=False, auto_adjust=False)['Close']
last = adj.ffill().iloc[-1]
at = lambda d: adj.loc[:d].ffill().iloc[-1]

print('=== 1. 帳戶 vs 基準 ===')
m = json.load(open('research/equity-marks.json'))
s = pd.Series({x['date']: x['value'] for x in m['manual'] + [y for y in m['marks'] if not y.get('excluded') and y.get('kind') == 'total']}).sort_index()
s.index = pd.to_datetime(s.index); s.loc[pd.Timestamp('2026-11-20')] = LIVE_TOTAL
b0 = at('2025-12-31')
print('今年：帳戶 %+.1f%%' % ((LIVE_TOTAL / Y0_TOTAL - 1) * 100), {c: f'{(last[c]/b0[c]-1)*100:+.1f}%' for c in ('SMH', 'QQQ', 'VOO', 'IGV')})
for a, b in [('2026-01-01', PEAK), (PEAK, '2026-07-31'), ('2026-07-31', '2026-09-30'), ('2026-09-30', '2026-10-30'), ('2026-10-30', '2026-11-20'), (PEAK, '2026-11-20')]:
    va, vb, pa, pb = s[:a].iloc[-1], s[:b].iloc[-1], at(a), at(b)
    print(f'{a}→{b}：帳戶 {(vb/va-1)*100:+6.1f}%（${vb-va:+,.0f}）｜SMH {(pb["SMH"]/pa["SMH"]-1)*100:+6.1f}%｜QQQ {(pb["QQQ"]/pa["QQQ"]-1)*100:+6.1f}%｜VOO {(pb["VOO"]/pa["VOO"]-1)*100:+6.1f}%')

print('\n=== 2. 峰值至今逐檔損益（期末市值 − 期初市值 + 期間賣出 − 期間買進）===')
cf = collections.defaultdict(float); nf = 0
for f in fills:
    if PEAK < f['date'] <= '2026-11-20': cf[f.get('underlying') or f['symbol']] += f['amount']; nf += 1
start = collections.defaultdict(float)
for k, v in peak_raw.items(): start[k.split()[0]] += v
rows = sorted(((n, LIVE.get(n, 0) - start.get(n, 0) + cf.get(n, 0), start.get(n, 0)) for n in set(start) | set(LIVE) | set(cf)), key=lambda r: r[1])
print(f'峰後成交 {nf} 筆；逐檔合計 ${sum(r[1] for r in rows):,.0f}（淨值變化 ${LIVE_TOTAL-PEAK_TOTAL:,.0f}）；'
      f'峰值時已持有的名字 ${sum(r[1] for r in rows if r[2]):,.0f}、之後才買的名字 ${sum(r[1] for r in rows if not r[2]):,.0f}')
print('最賠：' + '、'.join(f'{r[0]} {r[1]:,.0f}' for r in rows[:10]) + '；最賺：' + '、'.join(f'{r[0]} {r[1]:+,.0f}' for r in rows[-3:]))

print('\n=== 3. 凍結對照：那天之後完全不動，今天剩多少 ===')
p = at(PEAK); tot = PEAK_CASH; det = []
for k, v in peak_stk.items(): tot += v * last[k] / p[k]; det.append((k, last[k] / p[k] - 1))
tot += max(last['TSLA'] - 300, 0) * 100 + max(last['GOOGL'] - 260, 0) * 100       # 兩張 LEAPS 只算內含價值
sp821 = adj['SPCX'].loc[:'2026-08-21'].dropna()
tot += -600 * (max(150 - sp821.iloc[-1], 0) - max(130 - sp821.iloc[-1], 0)) if len(sp821) else -4380 - 1116
print(f'6/22 起凍結：${tot:,.0f}（實際 ${LIVE_TOTAL:,}）；個股 ' + '、'.join(f'{k} {v*100:+.0f}%' for k, v in sorted(det, key=lambda x: x[1])))
r8 = {True: 0.0, False: 0.0}
for k, v in peak_stk.items():
    g = peak_pct.get(k) or 0; frac = 0.5 if g >= 100 else 0.3 if g >= 60 else 0.15 if g >= 30 else 0
    save = frac * v * (1 - last[k] / p[k]); r8[True] += save
    if k not in ('MU', 'CRWD', 'AVGO', 'PLTR', 'NVDA'): r8[False] += save
print(f'  若 6/22 當天就套梯級停利（+30/+60/+100% 各賣 15/15/20%，款項留現金）：不含信念桶多留 ${r8[False]:,.0f}、含信念桶 ${r8[True]:,.0f}')
p = at('2026-10-29'); mv = sum(oct_pos.values()); cash = 246512 - mv
print(f'10/29 起凍結：${cash + sum(v*last[k]/p[k] for k, v in oct_pos.items()):,.0f}（實際 ${LIVE_TOTAL:,}；當時部位 ${mv:,.0f}、現金 ${cash:,.0f}）')
r0 = raw.loc[:'2025-12-31'].ffill().iloc[-1]; a0 = at('2025-12-31'); a622 = at(PEAK)
v0 = {k: q * r0[k.replace('.', '-')] for k, q in pos0.items() if k.replace('.', '-') in r0 and not np.isnan(r0[k.replace('.', '-')])}
g_now = sum(v * last[k.replace('.', '-')] / a0[k.replace('.', '-')] for k, v in v0.items()) / sum(v0.values())
g_pk = sum(v * a622[k.replace('.', '-')] / a0[k.replace('.', '-')] for k, v in v0.items()) / sum(v0.values())
for lab, base in [('反推部位原值', sum(v0.values())), ('縮到標記值', Y0_TOTAL - Y0_CASH)]:
    print(f'1/1 起凍結（{lab} ${base:,.0f}）：6/22 {((base*g_pk+Y0_CASH)/(base+Y0_CASH)-1)*100:+.1f}%（實際 +43.0%）、今天 {((base*g_now+Y0_CASH)/(base+Y0_CASH)-1)*100:+.1f}%（實際 {(LIVE_TOTAL/Y0_TOTAL-1)*100:+.1f}%）')
tb = sum(-f['amount'] for f in f26 if f['amount'] < 0); ts = sum(f['amount'] for f in f26 if f['amount'] > 0)
print(f'今年成交 {len(f26)} 筆：買進 ${tb:,.0f}、賣出 ${ts:,.0f}')

print('\n=== 4. 帳本對基準的 β（個股各自對基準回歸，前 120 日，按權重加總；LEAPS 以 delta 名目計）===')
r = adj.pct_change()
def book_beta(book, total, end):
    w = r.loc[:end].tail(120); out = {}
    for b in ('SMH', 'QQQ', 'SPY'):
        out[b] = sum(mv / total * np.cov(*w[[k, b]].dropna().values.T)[0, 1] / w[b].var() for k, mv in book.items())
    return out
pk = dict(peak_stk); pk['GOOGL'] = pk.get('GOOGL', 0) + 100 * 349.5 * 0.9; pk['TSLA'] = 100 * 405 * 0.85
bp = book_beta(pk, PEAK_TOTAL, PEAK); bn = book_beta(LIVE, LIVE_TOTAL, '2026-11-19')
pa, pb = at(PEAK), last
print(f'6/22 帳本：SMH {bp["SMH"]:.2f}、QQQ {bp["QQQ"]:.2f}、SPY {bp["SPY"]:.2f} → β×SMH 跌幅 = {bp["SMH"]*(pb["SMH"]/pa["SMH"]-1)*100:+.1f}%（實際 {(LIVE_TOTAL/PEAK_TOTAL-1)*100:+.1f}%）')
print(f'今日帳本：SMH {bn["SMH"]:.2f}、QQQ {bn["QQQ"]:.2f}、SPY {bn["SPY"]:.2f}')
names = [k for k in peak_stk if k != 'AU']; iu = np.triu_indices(len(names), 1)
c1 = r.loc[:PEAK, names].tail(120).corr().values[iu]; c2 = r.loc['2026-06-23':, names].corr().values[iu]
print(f'6/22 帳本個股兩兩相關中位：峰前 {np.median(c1):.2f} → 峰後 {np.median(c2):.2f}')
for lab, ns in [('MYRG／STRL 對 SMH', ['MYRG', 'STRL']), ('CRWD／DDOG／PLTR 對 SMH', ['CRWD', 'DDOG', 'PLTR'])]:
    print(f'  {lab}：峰前 {np.mean([r.loc[:PEAK, [k, "SMH"]].tail(120).corr().iloc[0, 1] for k in ns]):.2f} → 峰後 {np.mean([r.loc["2026-06-23":, [k, "SMH"]].corr().iloc[0, 1] for k in ns]):.2f}')

print('\n=== 5. 板塊過熱（收盤高於 200 日線 X%）之後 ===')
h = yf.download(['SMH', '^SOX', '^NDX'], period='max', progress=False, auto_adjust=True)['Close']
smh = h['SMH'].dropna(); ma = smh.rolling(200).mean(); ext = smh / ma - 1
print(f'SMH 6/22 高於 200 日線 {ext.loc[:PEAK].iloc[-1]*100:+.0f}%；今 {ext.iloc[-1]*100:+.0f}%')
y = smh[PEAK:]; below = y[y < ma[PEAK:]]
if len(below): print(f'SMH 峰後首次收破 200 日線：{below.index[0].date()}，距峰 {(below.iloc[0]/y.iloc[0]-1)*100:+.0f}%，之後至今 {(smh.iloc[-1]/below.iloc[0]-1)*100:+.0f}%')
for nm in ('^SOX', 'SMH', '^NDX'):
    q = h[nm].dropna(); v = q.values; e = (q / q.rolling(200).mean() - 1).values
    dd_all = np.median([v[k:k + 251].min() / v[k] - 1 for k in range(200, len(v) - 250, 5)])
    print(f'{nm}（{q.index[0].date()}→）任意日 250 日內最深回檔中位 {dd_all*100:.0f}%')
    for th in (0.30, 0.40, 0.50):
        ks = []; lastk = -10 ** 9
        for k in np.where(e >= th)[0]:
            if k - lastk > 120: ks.append(k)
            lastk = k
        line = f'  ≥{th*100:.0f}%：{len(ks)} 次（{"、".join(str(q.index[k].date())[:7] for k in ks)}）'
        for H in (60, 120, 250):
            rr = [v[k + H] / v[k] - 1 for k in ks if k + H < len(v)]
            if rr: line += f'｜{H} 日中位 {np.median(rr)*100:+.0f}%（n={len(rr)}）'
        dd = [v[k:k + 251].min() / v[k] - 1 for k in ks if k + 250 < len(v)]
        if dd: line += f'｜250 日內最深中位 {np.median(dd)*100:.0f}%'
        print(line)
