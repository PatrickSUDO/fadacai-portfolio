"""ladder_below_ma60_2026-11-20.py — 季線以下每跌 10% 逐步加碼（拿 VOO 換回半導體）好不好？
（2026-11-20 用戶「那季線以下每跌 10% 逐步加碼？」；承 bias_overheat_2026-11-20.py 的兩資產框架）

資產：半導體（SMH 含息，2000-06 前用費半指數）與 SPY 含息（代替 VOO）；訊號看費半指數收盤，1995-05→。
「每跌 10%」有三種讀法，都測：
  A 乖離梯：收盤低於季線（60 日線）10%、20%、30%…各加一份
  C 破線價梯：跌破季線前一日收盤為基準，之後每再跌 10% 加一份（站回季線重置）
  D 高點回檔梯：自一年高點回檔滿 10%、20%、30%…且收盤在季線下，各加一份（回到高點 5% 內重置）
加碼的部位什麼時候賣回 VOO，測四種：站回季線／站回年線／回到一年高點 10% 內／抱 250 個交易日。
平時比例 50% 或 70%，每梯 +10 個百分點，最多加到 100%；收盤判定、隔日生效、每次切換 10bp。
每個組合都跟兩個對照比：平時比例不動、以及「同樣平均比例的固定配置」（分得出加碼時點有沒有用）；另做圓形位移置換檢定。

首跑結論（2026-11-20，1995-05→，31.5 年）：
- 每一梯買進之後的一年報酬跟任意日買差不多，路更顛：任意日 250 日 +21.6%／勝 67%／買完中位再跌 14%；
  乖離梯第 1／2／3 梯 +13.8%／+38.3%／+4.7%（43／13／4 次，勝 50–61%，買完中位再跌 23–31%）；
  高點回檔梯第 1–5 梯 +27%／+3%／+20%／+26%／+69%（49／16／12／6／4 次，勝 60–80%，買完中位再跌 13–23%、最慘 −45 到 −57%）。
  深梯（−40%、−50%）看起來最好，但只有 4–6 次，而且第 4 梯之後 60 日平均 −10.7%（勝 20%）——通常還要再跌兩三個月。
- 14 段跌超過 25% 的跌勢裡，五梯（−10 到 −50%）全買完的 4 段；最低點時加碼部位帳面中位 −22%、最慘 −77%（2000–02，16 年才回到均價；2008 是 −55%、2.7 年）。
- 做成組合（24 組）：對「同樣平均比例的固定配置」幾乎沒差，兩窗都贏的只有 2 組（都是「高點回檔梯＋站回季線就賣回」：年化 +0.3pp、回撤淺 1.7pp，
  置換 p 0.12／0.04），BH 校正後 0 組。加碼部位抱越久（抱一年、等回高點）回撤越深：加深 4–14pp 換 0–0.5pp。
  2010 後所有版本對平時不動都多賺 0.4–2.6pp，2009 前都少賺 0.2–2.8pp——跟「平常多抱一點」是同一件事。
- 逐步買 vs 一次買（−10%／−20%／−30%／−40% 一次加滿）：差距都在 ±1.2pp 內、方向不一致 → 分梯的好處是紀律（不會一次押錯梯），不是報酬。
- 現況（SMH 402.8）：自高點 −40%、季線乖離 −27%；乖離梯在第 2 梯（第 3 梯約 385）、破線價梯在第 3 梯（第 4 梯 353）、高點回檔梯剛碰第 4 梯（401，第 5 梯 334）。
裁決（待用戶）：可以做，但它是紀律工具不是優勢；要先定總共加多少（子彈）與 2000 年型跌法的承受度，並且用「補回目標比例」而不是「越跌目標越高」。

用法：python3 tools/backtests/ladder_below_ma60_2026-11-20.py
"""
import numpy as np, pandas as pd, yfinance as yf, warnings
warnings.filterwarnings("ignore")
RNG = np.random.default_rng(20261120)
raw = yf.download(['^SOX', 'SMH', 'SPY', '^IRX'], period='max', progress=False, auto_adjust=True)['Close']
sox = raw['^SOX'].dropna(); DA = sox.index
rs_a = raw['SMH'].pct_change().reindex(DA); rs_a = rs_a.where(rs_a.notna(), sox.pct_change())
i0 = 252
D = DA[i0:]; n = len(D); v = sox.values[i0:]
rs = rs_a.to_numpy(copy=True)[i0:]; rv = raw['SPY'].pct_change().reindex(DA).fillna(0).to_numpy(copy=True)[i0:]
rf = ((raw['^IRX'] / 100).reindex(DA).ffill().fillna(0.03) / 252).values[i0:]
b60 = (sox / sox.rolling(60).mean() - 1).values[i0:]; b240 = (sox / sox.rolling(240).mean() - 1).values[i0:]
dd = (sox / sox.rolling(252, min_periods=120).max() - 1).values[i0:]
cs = np.cumprod(1 + rs); cv = np.cumprod(1 + rv)

def trig_A(step=0.10, maxk=8):
    ev = []; kd = 0
    for t in range(n):
        if b60[t] >= 0: kd = 0; continue
        k = min(maxk, int(np.floor(-b60[t] / step + 1e-9)))
        while kd < k: kd += 1; ev.append((t, kd))
    return ev
def trig_C(step=0.10, maxk=8):
    ev = []; kd = 0; p0 = None
    for t in range(1, n):
        if b60[t] >= 0: kd = 0; p0 = None; continue
        if p0 is None: p0 = v[t - 1] if b60[t - 1] >= 0 else v[t]
        k = min(maxk, int(np.floor((1 - v[t] / p0) / step + 1e-9)))
        while kd < k: kd += 1; ev.append((t, kd))
    return ev
def trig_D(step=0.10, maxk=8):
    ev = []; kd = 0
    for t in range(n):
        if dd[t] > -0.05: kd = 0
        if b60[t] < 0:
            k = min(maxk, int(np.floor(-dd[t] / step + 1e-9)))
            while kd < k: kd += 1; ev.append((t, kd))
    return ev
TR = {'A 乖離梯': trig_A(), 'C 破線價梯': trig_C(), 'D 高點回檔梯': trig_D()}
UL = {'ma60': '站回季線賣回', 'ma240': '站回年線賣回', 'dd10': '回到高點 10% 內賣回', 'hold250': '抱 250 日賣回'}

def perf(ret, rfd):
    eq = np.cumprod(1 + ret); ex = ret - rfd
    return eq[-1] ** (252 / len(ret)) - 1, (eq / np.maximum.accumulate(eq) - 1).min(), ex.mean() / ex.std() * np.sqrt(252)
W = {'全期': np.ones(n, bool), '2009 前': np.asarray(D < '2010-01-01'), '2010 後': np.asarray(D >= '2010-01-01')}
def pf(w, cost=0.001):
    r = w * rs + (1 - w) * rv; r[1:] -= np.abs(np.diff(w)) * cost
    return {k: perf(r[m], rf[m]) for k, m in W.items()}, r
def dfm(a, b): return '｜'.join(f'{k} {(a[k][0]-b[k][0])*100:+5.2f}pp／{(a[k][1]-b[k][1])*100:+5.1f}pp' for k in W)

def run(ev, base, size_fn, unwind, hold=250):
    by = {}
    for t, k in ev: by.setdefault(t, []).append(k)
    held = []; w = np.empty(n); fired = miss = 0
    for t in range(n):
        if (unwind == 'ma60' and b60[t] >= 0) or (unwind == 'ma240' and b240[t] >= 0) or (unwind == 'dd10' and dd[t] >= -0.10): held = []
        elif unwind == 'hold250': held = [h for h in held if t - h[0] < hold]
        for k in by.get(t, []):
            sz = size_fn(k)
            if sz <= 0: continue
            fired += 1; room = 1 - base - sum(h[1] for h in held)
            if room > 1e-9: held.append((t, min(sz, room)))
            else: miss += 1
        w[t] = base + sum(h[1] for h in held)
    return np.concatenate([[base], w[:-1]]), fired, miss

print(f'期間 {D[0].date()} → {D[-1].date()}（{n/252:.1f} 年）。半導體一直抱：' + '｜'.join(f'{k} {x[0]*100:+.1f}%／{x[1]*100:.0f}%' for k, x in pf(np.ones(n))[0].items()))
print('\n=== 1. 每一梯觸發之後（事件 = 該梯在一段跌勢裡第一次碰到）===')
allk = np.arange(0, n - 250)
print(f'任意日：60 日 {np.mean(cs[allk+60]/cs[allk]-1)*100:+.1f}%、250 日 {np.mean(cs[allk+250]/cs[allk]-1)*100:+.1f}%（勝 {np.mean(cs[allk+250]>cs[allk])*100:.0f}%）、比 VOO 多 {np.mean(cs[allk+250]/cs[allk]-cv[allk+250]/cv[allk])*100:+.1f}%；250 日內最多再跌 中位 {np.median([v[k:k+251].min()/v[k]-1 for k in allk[::5]])*100:.0f}%')
for nm, ev in TR.items():
    print(nm + '：')
    for k in range(1, 6):
        ks = [t for t, kk in ev if kk == k]; kf = [t for t in ks if t + 250 < n]
        if not kf: print(f'  第 {k} 梯：{len(ks)} 次（尚無滿一年的樣本）'); continue
        r60 = np.array([cs[t + 60] / cs[t] - 1 for t in kf]); r250 = np.array([cs[t + 250] / cs[t] - 1 for t in kf])
        x250 = np.array([cs[t + 250] / cs[t] - cv[t + 250] / cv[t] for t in kf]); more = np.array([v[t:t + 251].min() / v[t] - 1 for t in kf])
        yrs = len({D[t].year for t in ks})
        print(f'  第 {k} 梯（−{k*10}%）：{len(ks):>3} 次／{yrs:>2} 個年份｜60 日 {r60.mean()*100:+5.1f}%（勝 {np.mean(r60>0)*100:3.0f}%）｜250 日 {r250.mean()*100:+5.1f}%（中位 {np.median(r250)*100:+4.0f}%、勝 {np.mean(r250>0)*100:3.0f}%）｜比 VOO 多 {x250.mean()*100:+5.1f}%（贏 {np.mean(x250>0)*100:3.0f}%）｜之後最多再跌 中位 {np.median(more)*100:4.0f}%、最慘 {more.min()*100:4.0f}%')

print('\n=== 2. 每一段大跌：照「自高點每跌 10% 買一份，買到 −50% 共五份」會怎樣 ===')
eps = []; on = False
for t in range(n):
    if not on and dd[t] <= -0.10: on = True; a = t; pk = v[t] / (1 + dd[t]); lo = v[t]; lo_i = t
    elif on:
        if v[t] < lo: lo, lo_i = v[t], t
        if dd[t] > -0.05: eps.append((a, pk, lo, lo_i, t)); on = False
if on: eps.append((a, pk, lo, lo_i, None))
big = [e for e in eps if e[2] / e[1] - 1 <= -0.25]
print(f'自一年高點回檔 ≥10% 共 {len(eps)} 段，其中跌超過 25% 的 {len(big)} 段：')
worst = []; rungs_hit = []
for a, pk, lo, lo_i, end in big:
    depth = lo / pk - 1; hit = [k for k in range(1, 6) if depth <= -0.1 * k]; avg = np.mean([1 - 0.1 * k for k in hit]); wl = (lo / pk) / avg - 1
    worst.append(wl); rungs_hit.append(len(hit))
    be = next((t for t in range(lo_i, n) if v[t] >= avg * pk), None)
    first = next(t for t in range(a, n) if v[t] <= 0.9 * pk)
    print(f'  {D[a].date()} 起，最深 {depth*100:.0f}%（{D[lo_i].date()}）：買到第 {len(hit)} 梯、均價在高點的 {avg*100:.0f}%，最低點時加碼部位帳面 {wl*100:+.0f}%，'
          + (f'第一份買進後 {be-first} 個交易日回到均價' if be is not None else '至今未回到均價'))
print(f'  五份全買完的 {sum(r == 5 for r in rungs_hit)}/{len(big)} 段；最低點時加碼部位帳面虧損 中位 {np.median(worst)*100:.0f}%、最慘 {min(worst)*100:.0f}%')

print('\n=== 3. 做成組合：平時固定比例，每梯從 VOO 換 10 個百分點到半導體 ===')
FR = {wb: pf(np.full(n, wb))[0] for wb in (0.5, 0.7, 1.0)}
for wb in (0.5, 0.7): print(f'平時 {wb*100:.0f}% 不動：' + '｜'.join(f'{k} {x[0]*100:+.1f}%／{x[1]*100:.0f}%／{x[2]:.2f}' for k, x in FR[wb].items()))
res = []; pall = []
for wb in (0.5, 0.7):
    for nm, ev in TR.items():
        for un in UL:
            w, fired, miss = run(ev, wb, lambda k: 0.10, un); pr, _ = pf(w); st, _ = pf(np.full(n, w.mean()))
            rc = []; rm = []
            for _ in range(200):
                x = pf(np.roll(w, int(RNG.integers(60, n - 60))))[0]['全期']; rc.append(x[0]); rm.append(x[1])
            pc = float(np.mean(np.array(rc) >= pr['全期'][0])); pall.append(pc)
            res.append((wb, nm, un, w.mean(), fired, miss, pr, st, pc, float(np.mean(np.array(rm) >= pr['全期'][1]))))
for wb, nm, un, wbar, fired, miss, pr, st, pc, pm in res:
    print(f'  平時 {wb*100:.0f}%｜{nm}｜{UL[un]}（平均抱 {wbar*100:.0f}%、觸發 {fired} 次、子彈用完沒買到 {miss} 次）')
    print(f'      對平時比例不動：{dfm(pr, FR[wb])}')
    print(f'      對同比例固定配置：{dfm(pr, st)}｜置換 p（年化）{pc:.2f}、（回撤）{pm:.2f}')
ok1 = sum(all(r[6][k][0] - r[7][k][0] > 0 and r[6][k][1] - r[7][k][1] >= 0 for k in ('2009 前', '2010 後')) for r in res)
ok2 = sum(all(r[6][k][0] - r[7][k][0] > 0 for k in ('2009 前', '2010 後')) for r in res)
ok3 = sum(all(r[6][k][0] - FR[r[0]][k][0] >= 0.005 and r[6][k][1] - FR[r[0]][k][1] >= -0.05 for k in ('2009 前', '2010 後')) for r in res)
ps = np.sort(np.array(pall)); bq = [ps[i] * len(ps) / (i + 1) for i in range(len(ps))]
print(f'24 組裡：兩窗都贏同比例固定配置（年化更高且回撤不更深）{ok1} 組；兩窗年化都贏同比例固定配置 {ok2} 組；兩窗都「比平時不動多賺 ≥0.5pp 且回撤加深 ≤5pp」{ok3} 組')
print(f'置換檢定（年化，24 組）：最小 p {ps[0]:.3f}；BH 校正後 q<0.10 的 {int(sum(q < 0.10 for q in bq))} 組')

print('\n=== 4. 逐步買 vs 一次買（平時 50%，D 高點回檔梯，回到高點 10% 內賣回）===')
for lab, fn in (('每梯 10 個百分點，分五梯', lambda k: 0.10), ('第一梯（−10%）一次加滿', lambda k: 0.5 if k == 1 else 0), ('等第二梯（−20%）一次加滿', lambda k: 0.5 if k == 2 else 0),
                ('等第三梯（−30%）一次加滿', lambda k: 0.5 if k == 3 else 0), ('等第四梯（−40%）一次加滿', lambda k: 0.5 if k == 4 else 0)):
    w, fired, miss = run(TR['D 高點回檔梯'], 0.5, fn, 'dd10'); pr, _ = pf(w); st, _ = pf(np.full(n, w.mean()))
    print(f'  {lab}（平均抱 {w.mean()*100:.0f}%、加碼中 {np.mean(w > 0.5)*100:.0f}% 的日子）：對 50% 不動 {dfm(pr, FR[0.5])}')
    print(f'      對同比例固定配置：{dfm(pr, st)}')

print('\n=== 5. 現在在第幾梯（用 SMH 實際價格）===')
smh = raw['SMH'].dropna(); sv = smh.values; m60 = smh.rolling(60).mean().values; h252 = smh.rolling(252).max().values
t = len(sv) - 1; pk_i = int(np.argmax(sv[-252:])) + len(sv) - 252
print(f'SMH 收 {sv[t]:.1f}；一年高點 {h252[t]:.1f}（{smh.index[pk_i].date()}），回檔 {(sv[t]/h252[t]-1)*100:.0f}%；季線 {m60[t]:.1f}，乖離 {(sv[t]/m60[t]-1)*100:.0f}%')
k = t
while k > 0 and sv[k] < m60[k]: k -= 1
p0 = sv[k]; print(f'本次跌破季線：{smh.index[k+1].date()}（破線前一日收盤 {p0:.1f}）')
def hits(levels, series_fn):
    out = []
    for kk, lv in levels:
        d_ = next((smh.index[j].date() for j in range(pk_i, t + 1) if series_fn(j) <= lv), None)
        out.append(f'第 {kk} 梯 {d_ if d_ else "未到"}')
    return '、'.join(out)
print('  A 乖離梯（低於季線 10／20／30／40%）：' + hits([(i, -0.1 * i) for i in range(1, 5)], lambda j: sv[j] / m60[j] - 1) + f'；下一梯價位約 {m60[t]*(1-0.1*(int(-(sv[t]/m60[t]-1)/0.1)+1)):.0f}（季線每天在降）')
print('  C 破線價梯（破線價每再跌 10%）：' + '、'.join(f'第 {i} 梯 {p0*(1-0.1*i):.0f}' + ('（已到）' if sv[k+1:t+1].min() <= p0*(1-0.1*i) else '') for i in range(1, 5)))
print('  D 高點回檔梯（自高點 −10／−20／−30／−40／−50%）：' + '、'.join(f'第 {i} 梯 {h252[t]*(1-0.1*i):.0f}' + ('（已到）' if sv[pk_i:t+1].min() <= h252[t]*(1-0.1*i) else '') for i in range(1, 6)))
