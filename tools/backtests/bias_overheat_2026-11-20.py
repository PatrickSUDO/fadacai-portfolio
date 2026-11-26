"""bias_overheat_2026-11-20.py — 用乖離率看過熱，能不能事前收割？
（2026-11-20 用戶「那用乖離來看過熱呢？」；承 drawdown_postmortem_2026-11-20.py：6/22 帳戶見頂時 SMH 高於 200 日線 62%）

乖離率 = 收盤 ÷ N 日均線 − 1，N = 20（月線）／60（季線）／120（半年線）／240（年線）。
門檻用「擴張視窗百分位」：當天的乖離在「到當天為止的全部歷史」裡排第幾（≥95、≥99 分位），不偷看未來；暖機 756 日。
A. 指數層條件統計：^SOX 1994→、^NDX 1985→、^GSPC 1960→；乖離進入高分位之後 60／120／250 日報酬與 250 日內最深回檔，
   事件以「離開 60 日以上再進入」算新的一次。
B. 規則化：乖離 ≥ 門檻 → 減碼一半或全出（放 T-bill），乖離回到中位數或回到均線才買回；收盤判定、隔日生效、每次切換 10bp；
   32 組 × 3 個指數，分 2009 以前與 2010 以後兩窗，圓形位移置換檢定 + BH 校正。
C. 逐次事件表（^SOX 年線乖離 ≥99 分位）與 2026 年 SMH 個案：警報響了之後還漲多少、買回價比賣出價高還低。
D. 個股層：83 檔宇宙（今天看得到的名單，有倖存者偏差）2015→，年線乖離首次 ≥50%／≥100%、季線乖離首次 ≥30%／≥50% 之後
   對板塊 ETF 的超額與最深回檔；另列 6/22 帳本逐檔乖離與之後跌幅的排序相關。

E. 高點把半導體換成 VOO、落底換回（同日用戶追問「能不能在不太犧牲利潤的情況下減少回撤」）：半導體（SMH 含息，2000-06 前用費半）
   與 SPY 含息兩資產，1998-04→。E1 固定比例價目表；E2 過熱減碼 60 組；E3 落底加碼；E4 兩邊一起；E5 逐次事件；E6 套到 2026；
   E7 跌破長均線才換（事後確認版）；E8 再平衡 vs 不再平衡。每條規則都另外跟「同樣平均比例的固定配置」比，才分得出擇時有沒有用。

首跑結論（2026-11-20）：
- 乖離高通常是動能不是頂：費半季線乖離 ≥95 分位（14 次）之後 250 日 +50%（任意日 +21%）；NDX 年線乖離 ≥95 分位（12 次）+31%（任意日 +18%）。
  例外只有最極端那一格：費半年線乖離 ≥99 分位（約 +65%）史上兩次——2000-02 與 2026-05，之後都是崩盤，n=2。
- 警報響得早：兩次都在警報後 25–31 個交易日才見頂，期間再漲 53%／28%。SMH 2026 年 4/24 首次進 ≥99 分位，之後還漲 32%；6/22 年線乖離 +71% 是上市以來最高。
- 做成規則沒有用：換現金 96 組、換 VOO 60 組，「兩窗都少賺 ≤1pp 且回撤明顯變淺」0 組，贏「同比例固定配置」0 組，置換檢定 BH 校正後 0 組。
  原因是買回條件：乖離回到中位數時崩盤才走一半（2000-05 買回後再跌八成；2026-10-22 買回後再跌兩成）。套到 2026，換參數結果從 +6% 到 +21%（不動 +14%）。
- 個股層（83 檔，倖存者偏差）：年線乖離 ≥100% 之後 250 日超額 +98%（t 3.2）——高乖離的贏家繼續贏。但 6/22 帳本內乖離排序很準：
  年線乖離較高的一半之後 −53%、較低的一半 −10%（排序相關 −0.73，n=18，單一事件）→ 只能當「板塊過熱時先減誰」的排序。
- 落底訊號後半導體確實好（VIX 首次站上 30：250 日 +20%／勝 67%；年線乖離掉到歷史最低 5%：+41%／勝 75%／n=8），
  但做成「落底加碼」跟「平常就多抱一點」沒差別（對同比例固定配置 +0.2 到 +0.8pp，p 0.2–0.7）；真正的熊市裡這些訊號都來得太早（2000-04、2001、2008-01）。
- 固定比例價目表（年化／最大回撤）：全期 100% 半導體 +13.7%／−87%、70／30 +12.9%／−77%、50／50 +12.0%／−69%、全 VOO +8.5%／−55%；
  2010 後 +23.4%／−45%、+20.8%／−39%、+18.9%／−35%、+13.4%／−34%。Sharpe 幾乎不變（0.80–0.82）→ 少抱是線性交換，不是免費的。
- 接近免費的只有再平衡：70／30 每日再平衡 vs 讓它漂，全期 +12.9%／−77% vs +12.7%／−82%，2010 後 +20.8%／−39% vs +21.5%／−42%，2026 年 +11.6% vs +10.4%。
- 事後確認版（費半跌破 240 日線連 5 日才把一半換成 VOO）：全期 +0.75pp／回撤淺 6.6pp，2009 前 +3.7pp，2010 後 −1.7pp／淺 4.0pp；
  對同比例固定配置 2010 後 −0.3pp、全期 +1.1pp，置換 p 0.12 → 多頭十年的代價約等於固定放 15% VOO，多年空頭時多一層保護；未達顯著，400 日線版本更差。
裁決（待用戶）：乖離只做顯示與減碼排序，不做觸發；想少跌主要靠目標比例＋再平衡帶，長均線開關是可選的保險。

用法：python3 tools/backtests/bias_overheat_2026-11-20.py [--refresh]
"""
import sys, bisect, numpy as np, pandas as pd, yfinance as yf, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[1]; DATA = HERE / "data"; DATA.mkdir(exist_ok=True)
NS = (20, 60, 120, 240); LAB = {20: '月線', 60: '季線', 120: '半年線', 240: '年線', 200: '200 日線'}
RNG = np.random.default_rng(20261120)

def exp_pct(x, minp=756):
    """擴張視窗百分位：x[t] 在 x[:t+1] 裡的排名（%），只用當下以前的資料。"""
    out = np.full(len(x), np.nan); srt = []
    for i, v in enumerate(x):
        if np.isnan(v): continue
        bisect.insort(srt, v)
        if len(srt) >= minp: out[i] = bisect.bisect_right(srt, v) / len(srt) * 100
    return out

def episodes(mask, gap=60):
    ks = []; last = -10 ** 9
    for k in np.where(mask)[0]:
        if k - last > gap: ks.append(k)
        last = k
    return ks

def fwd(v, ks, H): return np.array([v[k + H] / v[k] - 1 for k in ks if k + H < len(v)])
def fdd(v, ks, H=250): return np.array([v[k:k + H + 1].min() / v[k] - 1 for k in ks if k + H < len(v)])

raw = yf.download(['^SOX', '^NDX', '^GSPC', 'SMH', '^IRX'], period='max', progress=False, auto_adjust=True)['Close']
RF = (raw['^IRX'] / 100).ffill()
SER = {'^SOX': raw['^SOX'].dropna(), '^NDX': raw['^NDX'].dropna(), '^GSPC': raw['^GSPC'].dropna()['1960':]}
BIAS = {}; PCT = {}
for nm, s in list(SER.items()) + [('SMH', raw['SMH'].dropna())]:
    for N in NS + (200,):
        b = (s / s.rolling(N).mean() - 1).values; BIAS[nm, N] = b; PCT[nm, N] = exp_pct(b)
SER['SMH'] = raw['SMH'].dropna()

print('=== A. 乖離進入高分位之後（事件：離開 60 日以上再進入才算新的一次）===')
for nm in ('^SOX', '^NDX', '^GSPC'):
    s = SER[nm]; v = s.values; ok = np.where(~np.isnan(PCT[nm, 240]))[0]
    base = {H: fwd(v, ok, H).mean() for H in (60, 120, 250)}; bdd = np.median(fdd(v, ok[::5]))
    print(f'{nm}（統計起點 {s.index[ok[0]].date()}）任意日：60 日 {base[60]*100:+.1f}%、120 日 {base[120]*100:+.1f}%、250 日 {base[250]*100:+.1f}%；250 日內最深回檔中位 {bdd*100:.0f}%')
    for N in NS:
        for th in (95, 99):
            m = np.zeros(len(v), bool); m[ok] = PCT[nm, N][ok] >= th; ks = episodes(m)
            lvl = np.nanpercentile(BIAS[nm, N], th)
            line = f'  {LAB[N]}乖離 ≥{th} 分位（現在約 ≥{lvl*100:+.0f}%）：{m[ok].mean()*100:4.1f}% 的日子、{len(ks):>2} 次'
            for H in (60, 120, 250):
                r = fwd(v, ks, H)
                if len(r): line += f'｜{H} 日 {r.mean()*100:+5.1f}%（勝 {np.mean(r>0)*100:3.0f}%）'
            d = fdd(v, ks)
            if len(d): line += f'｜最深回檔中位 {np.median(d)*100:.0f}%'
            print(line)

def perf(ret, rfd):
    eq = np.cumprod(1 + ret); yrs = len(ret) / 252
    ex = ret - rfd
    return eq[-1] ** (1 / yrs) - 1, (eq / np.maximum.accumulate(eq) - 1).min(), ex.mean() / ex.std() * np.sqrt(252)

def rule_pos(bias, pct, p_hi, cut, re):
    pos = np.ones(len(bias)); cur = 1.0
    for t in range(len(bias)):
        if not np.isnan(pct[t]):
            if cur == 1.0 and pct[t] >= p_hi: cur = 1 - cut
            elif cur < 1.0 and ((re == 'p50' and pct[t] <= 50) or (re == 'ma' and bias[t] <= 0)): cur = 1.0
        pos[t] = cur
    return np.concatenate([[1.0], pos[:-1]])           # 收盤判定、隔日生效

def strat(r, rfd, pos, cost=0.001):
    out = pos * r + (1 - pos) * rfd; out[1:] -= np.abs(np.diff(pos)) * cost; return out

print('\n=== B. 規則化：乖離 ≥ 門檻減碼、回到中位數（或均線）買回；對買進持有的差（年化／最大回撤／Sharpe）===')
GRID = [(N, p, c, re) for N in NS for p in (95, 99) for c in (0.5, 1.0) for re in ('p50', 'ma')]
allp = []; store = {}
for nm in ('^SOX', '^NDX', '^GSPC'):
    s = SER[nm]; i0 = np.where(~np.isnan(PCT[nm, 240]))[0][0]
    d = s.index[i0:]; r = s.pct_change().to_numpy(copy=True)[i0:]; r[0] = 0; rfd = RF.reindex(d).ffill().fillna(0.03).values / 252
    w1 = d < '2010-01-01'; w2 = ~w1
    bh = {k: perf(r[m], rfd[m]) for k, m in (('all', np.ones(len(d), bool)), ('w1', w1), ('w2', w2))}
    print(f'{nm} 買進持有：全期 {bh["all"][0]*100:+.1f}%／{bh["all"][1]*100:.0f}%／{bh["all"][2]:.2f}；2009 前 {bh["w1"][0]*100:+.1f}%／{bh["w1"][1]*100:.0f}%；2010 後 {bh["w2"][0]*100:+.1f}%／{bh["w2"][1]*100:.0f}%／{bh["w2"][2]:.2f}')
    cnt = dict(w2_cagr=0, both_sharpe=0, both_good=0)
    for g in GRID:
        N, p, c, re = g; pos = rule_pos(BIAS[nm, N][i0:], PCT[nm, N][i0:], p, c, re); sr = strat(r, rfd, pos)
        res = {k: perf(sr[m], rfd[m]) for k, m in (('all', np.ones(len(d), bool)), ('w1', w1), ('w2', w2))}
        dif = {k: tuple(res[k][j] - bh[k][j] for j in range(3)) for k in res}
        sh = []
        for _ in range(200):
            ps = np.roll(pos, int(RNG.integers(60, len(pos) - 60))); sh.append(perf(strat(r, rfd, ps), rfd)[2] - bh['all'][2])
        pv = float(np.mean(np.array(sh) >= dif['all'][2])); allp.append(pv)
        store[nm, g] = (dif, (pos < 1).mean(), int((np.diff(pos) != 0).sum()), pv)
        cnt['w2_cagr'] += dif['w2'][0] >= 0; cnt['both_sharpe'] += (dif['w1'][2] > 0 and dif['w2'][2] > 0)
        cnt['both_good'] += all(dif[k][1] >= 0.05 and dif[k][0] >= -0.01 for k in ('w1', 'w2'))
    print(f'  32 組裡：2010 後年化不輸買進持有 {cnt["w2_cagr"]} 組；兩窗 Sharpe 都更高 {cnt["both_sharpe"]} 組；兩窗都「回撤淺 ≥5pp 且年化代價 ≤1pp」{cnt["both_good"]} 組')
    for g in [(N, p, 0.5, 'p50') for N in NS for p in (95, 99)]:
        dif, out, ntr, pv = store[nm, g]
        print(f'    {LAB[g[0]]} ≥{g[1]} 減半（減碼中 {out*100:4.1f}% 的日子、切換 {ntr:>3} 次）：全期 {dif["all"][0]*100:+5.2f}pp／{dif["all"][1]*100:+5.1f}pp／{dif["all"][2]:+.2f}'
              f'｜2009 前 {dif["w1"][0]*100:+5.2f}pp／{dif["w1"][1]*100:+5.1f}pp｜2010 後 {dif["w2"][0]*100:+5.2f}pp／{dif["w2"][1]*100:+5.1f}pp／{dif["w2"][2]:+.2f}｜置換 p {pv:.2f}')
ps = np.sort(np.array(allp)); m_ = len(ps); bhq = [ps[i] * m_ / (i + 1) for i in range(m_)]
print(f'置換檢定（全期 Sharpe 差，96 組）：最小 p {ps[0]:.3f}；BH 校正後 q<0.10 的有 {int(sum(q < 0.10 for q in bhq))} 組')

print('\n=== C. 逐次事件：^SOX 年線乖離 ≥99 分位（買回 = 乖離回到歷史中位數）===')
def episode_table(nm, N, th=99):
    s = SER[nm]; v = s.values; b = BIAS[nm, N]; p = PCT[nm, N]; t = 0; rows = []
    while t < len(v):
        if not np.isnan(p[t]) and p[t] >= th:
            e = t; x = t + 1
            while x < len(v) and not (p[x] <= 50): x += 1
            seg = v[e:min(x, len(v) - 1) + 1]; pk = int(np.argmax(seg))
            rows.append((s.index[e].date(), b[e], seg[pk] / v[e] - 1, pk, s.index[min(x, len(v) - 1)].date() if x < len(v) else None,
                         (v[x] / v[e] - 1) if x < len(v) else v[-1] / v[e] - 1, seg.min() / seg[pk] - 1 if pk < len(seg) - 1 else 0.0))
            t = x + 1
        else: t += 1
    return rows
for nm, N in (('^SOX', 240), ('^SOX', 60), ('^NDX', 240)):
    rows = episode_table(nm, N); rb = [r[5] for r in rows if r[4]]
    print(f'{nm} {LAB[N]}乖離 ≥99 分位：{len(rows)} 次；買回價比警報價低的 {sum(x < 0 for x in rb)}/{len(rb)} 次，買回價相對警報價中位 {np.median(rb)*100:+.0f}%；警報後到最高點中位再漲 {np.median([r[2] for r in rows])*100:+.0f}%、中位 {np.median([r[3] for r in rows]):.0f} 個交易日')
    for r in rows:
        print(f'    {r[0]} 乖離 {r[1]*100:+.0f}% → 之後最高再漲 {r[2]*100:+.0f}%（{r[3]} 日後）→ ' + (f'{r[4]} 買回，價格比警報價 {r[5]*100:+.0f}%' if r[4] else f'尚未買回，現價比警報價 {r[5]*100:+.0f}%'))
smh = SER['SMH']; v = smh.values; i26 = smh.index.get_loc(smh['2026':].index[0]); ipk = smh.index.get_loc(pd.Timestamp('2026-06-22'))
print('SMH 2026 個案（6/22 見頂）：')
for N in (20, 60, 120, 200, 240):
    b = BIAS['SMH', N]; p = PCT['SMH', N]
    hit = [k for k in range(i26, ipk + 1) if p[k] >= 99]
    line = f'    {LAB[N]}：6/22 乖離 {b[ipk]*100:+.0f}%（歷史 {p[ipk]:.1f} 分位）'
    if hit:
        k = hit[0]; line += f'；今年首次 ≥99 分位在 {smh.index[k].date()}（乖離 {b[k]*100:+.0f}%），之後到 6/22 還漲 {(v[ipk]/v[k]-1)*100:+.0f}%，現價比當時 {(v[-1]/v[k]-1)*100:+.0f}%；今年到峰值共 {len(hit)} 天在 ≥99 分位'
    else: line += '；今年到峰值沒有進過 ≥99 分位'
    print(line)

print('\n=== D. 個股層（83 檔宇宙 2015→，對板塊 ETF 超額；t 值以事件月份為單位）===')
sys.path.insert(0, str(HERE / "options_long_short_2026-10-23" / "short_alpha"))
import universe as UNI  # noqa: E402
UNI.LEDGER = str(ROOT / "research/trade-ledger.jsonl"); UNI.TL_PY = str(ROOT / "tools/trade_ledger.py"); UNI.BENCH_JSON = str(ROOT / "research/bench.json")
SYMS = [s for s in UNI.test2_universe() if s not in UNI.ETFS]; ETF = {s: UNI.sector_etf(s) for s in SYMS}
BOOK = ['MU', 'MYRG', 'CRWD', 'AVGO', 'STRL', 'AMD', 'DDOG', 'ONTO', 'PLTR', 'NVDA', 'CRDO', 'ARM', 'LITE', 'ON', 'AU', 'ANET', 'GOOGL', 'TSLA']
PXF = DATA / 'bias_overheat_px_2026-11-20.csv'
if PXF.exists() and '--refresh' not in sys.argv: C = pd.read_csv(PXF, index_col=0, parse_dates=True)
else:
    C = yf.download(sorted(set(SYMS) | set(ETF.values()) | set(BOOK) | {'SMH', 'IGV', 'SPY'}), start='2013-06-01', progress=False, auto_adjust=True)['Close']; C.to_csv(PXF)
i15 = C.index.searchsorted(pd.Timestamp('2015-01-01'))
def stock_events(N, th, gap=120):
    ev = []; base = {60: [], 120: [], 250: []}; bdd = []
    for sy in SYMS:
        if sy not in C or ETF[sy] not in C: continue
        s = C[sy].dropna()
        if len(s) < N + 300: continue
        v = s.values; e = C[ETF[sy]].reindex(s.index).ffill().values; b = v / pd.Series(v).rolling(N).mean().values - 1
        st = max(N, s.index.searchsorted(pd.Timestamp('2015-01-01')))
        for k in range(st, len(v) - 250, 5):
            for H in base: base[H].append(v[k + H] / v[k] - e[k + H] / e[k])
            bdd.append(v[k:k + 251].min() / v[k] - 1)
        m = np.zeros(len(v), bool); m[st:] = b[st:] >= th
        for k in episodes(m, gap):
            if k + 60 < len(v):
                ev.append(dict(sym=sy, ym=str(s.index[k])[:7], bias=b[k],
                               **{f'x{H}': (v[k + H] / v[k] - e[k + H] / e[k]) if k + H < len(v) else np.nan for H in (60, 120, 250)},
                               **{f'r{H}': (v[k + H] / v[k] - 1) if k + H < len(v) else np.nan for H in (60, 120, 250)},
                               dd=(v[k:k + 251].min() / v[k] - 1) if k + 250 < len(v) else np.nan))
    return pd.DataFrame(ev), {H: np.mean(x) for H, x in base.items()}, np.median(bdd)
for N, th in ((240, 0.50), (240, 1.00), (60, 0.30), (60, 0.50)):
    df, base, bdd = stock_events(N, th)
    if not len(df): print(f'{LAB[N]}乖離 ≥{th*100:.0f}%：無事件'); continue
    line = f'{LAB[N]}乖離首次 ≥{th*100:.0f}%：{len(df)} 次／{df.sym.nunique()} 檔'
    for H in (60, 120, 250):
        x = df[f'x{H}'].dropna(); co = df.dropna(subset=[f'x{H}']).groupby('ym')[f'x{H}'].mean()
        t = co.mean() / (co.std() / np.sqrt(len(co))) if len(co) > 2 else float('nan')
        line += f'｜{H} 日超額 {x.mean()*100:+.1f}%（任意日 {base[H]*100:+.1f}%，t {t:+.1f}，原始報酬 {df[f"r{H}"].mean()*100:+.0f}%、勝 {np.mean(df[f"r{H}"].dropna()>0)*100:.0f}%）'
    line += f'｜250 日內最深回檔中位 {df.dd.median()*100:.0f}%（任意日 {bdd*100:.0f}%）'
    print(line)
pk = C.index[C.index.searchsorted(pd.Timestamp('2026-06-22'))]; rows = []
for sy in BOOK:
    if sy not in C: continue
    s = C[sy].dropna()
    if pk not in s.index or len(s[:pk]) < 240: continue
    rows.append((sy, s[:pk].iloc[-1] / s[:pk].tail(240).mean() - 1, s[:pk].iloc[-1] / s[:pk].tail(60).mean() - 1, s.iloc[-1] / s[:pk].iloc[-1] - 1))
bk = pd.DataFrame(rows, columns=['sym', 'b240', 'b60', 'after']).sort_values('b240', ascending=False)
print('6/22 帳本逐檔（年線乖離／季線乖離 → 之後至今）：' + '、'.join(f'{r.sym} {r.b240*100:+.0f}%／{r.b60*100:+.0f}% → {r.after*100:+.0f}%' for r in bk.itertuples()))
print(f'  排序相關（乖離越大、之後跌越多 = 負值）：年線 {bk.b240.rank().corr(bk.after.rank()):+.2f}、季線 {bk.b60.rank().corr(bk.after.rank()):+.2f}（n={len(bk)}，單一事件）')
half = len(bk) // 2
print(f'  年線乖離較高的一半之後平均 {bk.after.iloc[:half].mean()*100:+.0f}%、較低的一半 {bk.after.iloc[half:].mean()*100:+.0f}%')

print('\n=== E. 高點把半導體換成 VOO、落底換回（半導體：SMH 含息，2000-06 前用費半指數；VOO 以 SPY 含息代替；訊號看費半乖離）===')
ex = yf.download(['SMH', 'SPY', '^VIX'], period='max', progress=False, auto_adjust=True)['Close']
sox = SER['^SOX']; DI = sox.index; e0 = int(np.where(~np.isnan(PCT['^SOX', 240]))[0][0])
rs_all = ex['SMH'].pct_change().reindex(DI); rs_all = rs_all.where(rs_all.notna(), sox.pct_change())
E_D = DI[e0:]; E_n = len(E_D)
E_rs = rs_all.to_numpy(copy=True)[e0:]; E_rv = ex['SPY'].pct_change().reindex(DI).fillna(0).to_numpy(copy=True)[e0:]; E_rs[0] = 0; E_rv[0] = 0
E_rf = RF.reindex(E_D).ffill().fillna(0.03).values / 252
E_vix = ex['^VIX'].reindex(DI).ffill().values
E_pct = {N: PCT['^SOX', N][e0:] for N in NS}; E_bias = {N: BIAS['^SOX', N][e0:] for N in NS}
soxv = sox.values; ddv = soxv / pd.Series(soxv).rolling(252).max().values - 1
def first_cross(cond, look=20):
    c = pd.Series(np.asarray(cond, bool)); prev = c.shift(1).rolling(look).max().fillna(0).astype(bool)
    return (c & ~prev).values
SIG = {'vix30': first_cross(E_vix >= 30)[e0:], 'os5': first_cross(PCT['^SOX', 240] <= 5)[e0:], 'dd30': first_cross(ddv <= -0.30)[e0:]}
SL = {'p50': '乖離回到中位數', 'ma': '跌回均線', 'vix30': 'VIX 首次站上 30', 'os5': '年線乖離掉到歷史最低 5%', 'dd30': '費半自一年高點跌 30%'}

def e_weights(base, H=None, L=None, hold=250):
    """H=(N, 分位, 減碼比例, 買回條件)：過熱 → 半導體權重 × (1−減碼)。L=(落底訊號, 加到多少)：訊號後抱 hold 日。隔日生效。"""
    w = np.empty(E_n); st = 'base'; t_bt = -1
    for t in range(E_n):
        if st == 'base':
            if H and E_pct[H[0]][t] >= H[1]: st = 'oh'
            elif L and SIG[L[0]][t]: st = 'bt'; t_bt = t
        elif st == 'oh':
            N, p_hi, cut, re = H
            if L and SIG[L[0]][t]: st = 'bt'; t_bt = t
            elif re == 'p50' and E_pct[N][t] <= 50: st = 'base'
            elif re == 'ma' and E_bias[N][t] <= 0: st = 'base'
            elif re in SIG and SIG[re][t]: st = 'base'
        else:
            if L and SIG[L[0]][t]: t_bt = t
            elif t - t_bt >= hold: st = 'base'
        w[t] = base * (1 - H[2]) if st == 'oh' else (L[1] if st == 'bt' else base)
    return np.concatenate([[base], w[:-1]])
def e_ret(w, cost=0.001):
    out = w * E_rs + (1 - w) * E_rv; out[1:] -= np.abs(np.diff(w)) * cost; return out
E_W = {'全期': np.ones(E_n, bool), '2009 前': np.asarray(E_D < '2010-01-01'), '2010 後': np.asarray(E_D >= '2010-01-01')}
def e_perf(ret): return {k: perf(ret[m], E_rf[m]) for k, m in E_W.items()}
def fmt(pr): return '｜'.join(f'{k} {pr[k][0]*100:+5.1f}%／{pr[k][1]*100:4.0f}%／{pr[k][2]:.2f}' for k in E_W)
def dfm(a, b): return '｜'.join(f'{k} {(a[k][0]-b[k][0])*100:+5.2f}pp／{(a[k][1]-b[k][1])*100:+5.1f}pp' for k in E_W)

print(f'統計期間 {E_D[0].date()} → {E_D[-1].date()}。欄位：年化／最大回撤／Sharpe')
print('--- E1 固定比例（每日再平衡）的價目表：少抱半導體，回撤淺多少、少賺多少 ---')
FR = {}
for wb in (1.0, 0.85, 0.70, 0.50, 0.30, 0.0):
    FR[wb] = e_perf(e_ret(np.full(E_n, wb))); print(f'  半導體 {wb*100:3.0f}%／VOO {100-wb*100:3.0f}%：{fmt(FR[wb])}')
bh = FR[1.0]

print('--- E2 高點減碼（基準 100% 半導體；過熱時把一半或全部換成 VOO）---')
HG = [(N, p, c, re) for N in (60, 120, 240) for p in (95, 99) for c in (0.5, 1.0) for re in ('p50', 'ma', 'vix30', 'os5', 'dd30')]
HR = {}; pc = []
for H in HG:
    w = e_weights(1.0, H); rr = e_ret(w); pr = e_perf(rr); st_ = e_perf(e_ret(np.full(E_n, w.mean())))
    rc = []; rm = []
    for _ in range(200):
        x = perf(e_ret(np.roll(w, int(RNG.integers(60, E_n - 60)))), E_rf); rc.append(x[0]); rm.append(x[1])
    HR[H] = dict(pr=pr, st=st_, wbar=w.mean(), sw=int((np.diff(w) != 0).sum()), p_c=float(np.mean(np.array(rc) >= pr['全期'][0])), p_m=float(np.mean(np.array(rm) >= pr['全期'][1])))
    pc.append(HR[H]['p_c'])
p1 = [H for H in HG if all(HR[H]['pr'][k][0] - bh[k][0] >= -0.01 and HR[H]['pr'][k][1] - bh[k][1] >= 0.10 for k in ('2009 前', '2010 後'))]
p2 = [H for H in HG if all(HR[H]['pr'][k][0] - HR[H]['st'][k][0] > 0 and HR[H]['pr'][k][1] - HR[H]['st'][k][1] >= 0 for k in ('2009 前', '2010 後'))]
p3 = [H for H in HG if HR[H]['pr']['2010 後'][0] >= bh['2010 後'][0]]
pcs = np.sort(np.array(pc)); bq = [pcs[i] * len(pcs) / (i + 1) for i in range(len(pcs))]
print(f'  60 組裡：兩窗都「年化少 ≤1pp 且回撤淺 ≥10pp」{len(p1)} 組；兩窗都贏「同樣平均比例的固定配置」{len(p2)} 組；2010 後年化不輸一直抱半導體 {len(p3)} 組')
print(f'  置換檢定（同樣的減碼天數隨機挪到別的時間，比年化）：最小 p {pcs[0]:.3f}，BH 校正後 q<0.10 的 {int(sum(q < 0.10 for q in bq))} 組')
if p1: print('  過第一關的：' + '；'.join(f'{LAB[H[0]]}≥{H[1]} 減{H[2]*100:.0f}% 買回＝{SL[H[3]]}' for H in p1[:8]))
if p2: print('  過第二關的：' + '；'.join(f'{LAB[H[0]]}≥{H[1]} 減{H[2]*100:.0f}% 買回＝{SL[H[3]]}' for H in p2[:8]))
for H in [(N, p, 0.5, re) for (N, p) in ((240, 95), (240, 99), (120, 99), (60, 99)) for re in ('p50', 'vix30', 'dd30')]:
    x = HR[H]
    print(f'  {LAB[H[0]]}乖離 ≥{H[1]} 分位減半、買回＝{SL[H[3]]}（平均抱 {x["wbar"]*100:.0f}%、切換 {x["sw"]} 次）')
    print(f'      對一直抱半導體：{dfm(x["pr"], bh)}')
    print(f'      對同比例固定配置：{dfm(x["pr"], x["st"])}｜置換 p（年化）{x["p_c"]:.2f}、（回撤）{x["p_m"]:.2f}')

print('--- E3 落底加碼（平時固定比例；落底訊號後把半導體加到 100%，抱 250 個交易日）---')
for wb in (0.70, 0.50):
    for sg in ('vix30', 'os5', 'dd30'):
        w = e_weights(wb, None, (sg, 1.0)); pr = e_perf(e_ret(w)); st_ = e_perf(e_ret(np.full(E_n, w.mean())))
        rc = [perf(e_ret(np.roll(w, int(RNG.integers(60, E_n - 60)))), E_rf)[0] for _ in range(200)]
        print(f'  平時 {wb*100:.0f}%，{SL[sg]}→100%（{int(SIG[sg].sum())} 次訊號、平均抱 {w.mean()*100:.0f}%）')
        print(f'      對平時比例不動：{dfm(pr, FR[wb])}')
        print(f'      對同比例固定配置：{dfm(pr, st_)}｜置換 p（年化）{float(np.mean(np.array(rc) >= pr["全期"][0])):.2f}')

print('--- E4 兩邊一起做（平時 70%；過熱減半、落底加到 100%）---')
for H, L in (((240, 95, 0.5, 'p50'), ('vix30', 1.0)), ((240, 99, 0.5, 'p50'), ('vix30', 1.0)), ((120, 99, 0.5, 'p50'), ('dd30', 1.0)), ((240, 95, 0.5, 'vix30'), ('vix30', 1.0))):
    w = e_weights(0.70, H, L); pr = e_perf(e_ret(w)); st_ = e_perf(e_ret(np.full(E_n, w.mean())))
    print(f'  {LAB[H[0]]}乖離 ≥{H[1]} 減半（買回＝{SL[H[3]]}）＋{SL[L[0]]}加滿（平均抱 {w.mean()*100:.0f}%）：{fmt(pr)}')
    print(f'      對 70% 不動：{dfm(pr, FR[0.70])}')
    print(f'      對同比例固定配置：{dfm(pr, st_)}')

print('--- E5 逐次事件：過熱時換成 VOO，到買回為止，半導體比 VOO 多賺（＋）或少賺（−）多少；負值 = 換對了 ---')
cs = np.cumprod(1 + E_rs); cv = np.cumprod(1 + E_rv)
def h_eps(N, p_hi, re):
    out = []; on = False; a = 0
    for t in range(E_n):
        if not on and E_pct[N][t] >= p_hi: on = True; a = t
        elif on and ((re == 'p50' and E_pct[N][t] <= 50) or (re == 'ma' and E_bias[N][t] <= 0) or (re in SIG and SIG[re][t])): out.append((a, t)); on = False
    if on: out.append((a, None))
    return out
for N, p_hi, re in ((240, 95, 'p50'), (240, 95, 'vix30'), (120, 99, 'p50'), (60, 99, 'p50')):
    eps = h_eps(N, p_hi, re); rel = []
    line = []
    for a, b in eps:
        b2 = b if b is not None else E_n - 1; x = cs[b2] / cs[a] - 1; y = cv[b2] / cv[a] - 1; rel.append(x - y)
        line.append(f'{E_D[a].date()}→{E_D[b2].date() if b is not None else "未買回"}（{b2-a} 日）半導體 {x*100:+.0f}%／VOO {y*100:+.0f}%')
    print(f'  {LAB[N]}乖離 ≥{p_hi} 分位、買回＝{SL[re]}：{len(eps)} 次，換對 {sum(v_ < 0 for v_ in rel)} 次，半導體相對 VOO 中位 {np.median(rel)*100:+.0f}%、平均 {np.mean(rel)*100:+.0f}%')
    for l_ in line: print('      ' + l_)
for sg in ('vix30', 'dd30', 'os5'):
    ks = np.where(SIG[sg])[0]; rel = [(cs[k + 250] / cs[k]) - (cv[k + 250] / cv[k]) for k in ks if k + 250 < E_n]
    raw_ = [cs[k + 250] / cs[k] - 1 for k in ks if k + 250 < E_n]
    print(f'  落底訊號 {SL[sg]}：{len(rel)} 次，之後 250 日半導體平均 {np.mean(raw_)*100:+.0f}%（勝 {np.mean(np.array(raw_)>0)*100:.0f}%），比 VOO 多 {np.mean(rel)*100:+.0f}%（中位 {np.median(rel)*100:+.0f}%、贏 VOO {np.mean(np.array(rel)>0)*100:.0f}%）')
    print('      ' + '、'.join(f'{E_D[k].date()} {((cs[k+250]/cs[k])-(cv[k+250]/cv[k]))*100:+.0f}%' for k in ks if k + 250 < E_n))

print('--- E6 套到 2026 年 ---')
y0 = int(np.searchsorted(E_D, pd.Timestamp('2026-01-01'))); ipk2 = int(np.searchsorted(E_D, pd.Timestamp('2026-06-22')))
print(f'  2026 半導體 {(cs[-1]/cs[y0-1]-1)*100:+.1f}%、VOO {(cv[-1]/cv[y0-1]-1)*100:+.1f}%；6/22 之後半導體 {(cs[-1]/cs[ipk2]-1)*100:+.1f}%、VOO {(cv[-1]/cv[ipk2]-1)*100:+.1f}%')
for sg in SIG: print(f'  {SL[sg]}：2026 年出現在 ' + ('、'.join(str(E_D[k].date()) for k in np.where(SIG[sg])[0] if k >= y0) or '（沒有）'))
for H, L in (((240, 95, 0.5, 'p50'), None), ((240, 99, 0.5, 'p50'), None), ((120, 99, 0.5, 'p50'), None), ((60, 99, 0.5, 'p50'), None), ((240, 95, 0.5, 'vix30'), None), ((240, 95, 0.5, 'p50'), ('vix30', 1.0))):
    for wb in ((1.0, 0.70) if L is None else (0.70,)):
        w = e_weights(wb, H, L); rr = e_ret(w)[y0:]; base_r = e_ret(np.full(E_n, wb))[y0:]
        eq = np.cumprod(1 + rr); eb = np.cumprod(1 + base_r)
        chg = [f'{E_D[k+1].date()} {w[k]*100:.0f}→{w[k+1]*100:.0f}%' for k in range(y0 - 1, E_n - 1) if w[k + 1] != w[k]]
        print(f'  平時 {wb*100:.0f}%，{LAB[H[0]]}乖離 ≥{H[1]} 減半、買回＝{SL[H[3]]}' + (f'＋{SL[L[0]]}加滿' if L else '') + f'：今年 {(eq[-1]-1)*100:+.1f}%（不動 {(eb[-1]-1)*100:+.1f}%）、年內最大回撤 {(eq/np.maximum.accumulate(eq)-1).min()*100:.0f}%（不動 {(eb/np.maximum.accumulate(eb)-1).min()*100:.0f}%）；調整：' + ('、'.join(chg) or '無'))

print('--- E7 事後確認版：費半跌破長均線才把半導體換成 VOO、站回換回（基準 100% 半導體；收盤判定、隔日生效）---')
def ma_weights(N, confirm=1, lo=0.0):
    above = ((sox / sox.rolling(N).mean() - 1).values[e0:]) > 0; w = np.empty(E_n); cur = 1.0; run = 0
    for t in range(E_n):
        want = 1.0 if above[t] else lo
        if want != cur:
            run += 1
            if run >= confirm: cur = want; run = 0
        else: run = 0
        w[t] = cur
    return np.concatenate([[1.0], w[:-1]])
yrs_all = E_n / 252
for N in (200, 240, 400):
    for cf in (1, 5):
        for lo in (0.0, 0.5):
            w = ma_weights(N, cf, lo); rr = e_ret(w); pr = e_perf(rr); st_ = e_perf(e_ret(np.full(E_n, w.mean())))
            rc = []; rm = []
            for _ in range(200):
                x = perf(e_ret(np.roll(w, int(RNG.integers(60, E_n - 60)))), E_rf); rc.append(x[0]); rm.append(x[1])
            eq = np.cumprod(1 + rr[y0:]); chg = [f'{E_D[k+1].date()} {w[k]*100:.0f}→{w[k+1]*100:.0f}%' for k in range(y0 - 1, E_n - 1) if w[k + 1] != w[k]]
            print(f'  {N} 日線{"、連 5 日確認" if cf == 5 else ""}，線下半導體留 {lo*100:.0f}%（平均抱 {w.mean()*100:.0f}%、每年切換 {(np.diff(w) != 0).sum()/yrs_all:.1f} 次）：{fmt(pr)}')
            print(f'      對一直抱半導體：{dfm(pr, bh)}')
            print(f'      對同比例固定配置：{dfm(pr, st_)}｜置換 p（年化）{float(np.mean(np.array(rc) >= pr["全期"][0])):.2f}、（回撤）{float(np.mean(np.array(rm) >= pr["全期"][1])):.2f}')
            print(f'      2026：今年 {(eq[-1]-1)*100:+.1f}%（一直抱 {(cs[-1]/cs[y0-1]-1)*100:+.1f}%）、年內最大回撤 {(eq/np.maximum.accumulate(eq)-1).min()*100:.0f}%；調整：' + ('、'.join(chg) or '無'))
print('--- E8 固定比例但不再平衡（讓它漂）vs 每日再平衡：再平衡本身就是「漲多賣一點、跌多買一點」---')
for wb in (0.70, 0.50):
    for lab_, m_ in E_W.items():
        rs_, rv_ = E_rs[m_], E_rv[m_]; a_ = np.cumprod(1 + rs_); b_ = np.cumprod(1 + rv_); drift = wb * a_ + (1 - wb) * b_
        dr = np.diff(np.concatenate([[1.0], drift])) / np.concatenate([[1.0], drift[:-1]]); pd_ = perf(dr, E_rf[m_]); pr_ = perf(wb * rs_ + (1 - wb) * rv_, E_rf[m_])
        print(f'  起始 {wb*100:.0f}／{100-wb*100:.0f}，{lab_}：再平衡 {pr_[0]*100:+.1f}%／{pr_[1]*100:.0f}%；不再平衡 {pd_[0]*100:+.1f}%／{pd_[1]*100:.0f}%（期末半導體佔 {wb*a_[-1]/drift[-1]*100:.0f}%）')
a26 = cs[y0:] / cs[y0 - 1]; b26 = cv[y0:] / cv[y0 - 1]
for wb in (0.70, 0.50):
    reb = np.cumprod(1 + wb * E_rs[y0:] + (1 - wb) * E_rv[y0:]); drf = wb * a26 + (1 - wb) * b26
    print(f'  2026 年 {wb*100:.0f}／{100-wb*100:.0f}：每日再平衡 {(reb[-1]-1)*100:+.1f}%、不再平衡 {(drf[-1]-1)*100:+.1f}%；6/22 當天半導體比重會漂到 {wb*a26[ipk2-y0]/drf[ipk2-y0]*100:.0f}%')
