"""「大跌之後買雙買（ATM straddle）搶反彈」好不好——事件研究。
標的 SPY（IV＝VIX，1993→）、QQQ（IV＝VXN，2001→）、SMH（無 IV 指數，用 VXN × 60 日已實現波動比代理）。
沒有免費的歷史選擇權報價，所以進場權利金用 Black-Scholes 以當日 IV 指數 × K_IV 估（ATM IV 通常低於 VIX，
VIX 含價外 put 的偏斜）；持有到期的損益只靠進場 IV 假設，提前出場另需出場日 IV（同一來源）。
事件去叢集 20 個交易日。對照：只買 call、只買 put、買現股、以及「任意日買雙買」基準。
用法：python3 straddle_after_drop_2026-11-10.py [K_IV=0.92]

首跑結論（2026-11-10，輸出在 data/straddle_after_drop_2026-11-10.k*.out.txt）：
- 大跌後雙買是負期望值，而且比「任意日買雙買」更差。VIX 首次站上 30 後 SPY 21 日雙買（n=64）：
  損平 ±7.6%、實際平均 |漲跌| 5.5%，平均 −27% 權利金、勝率 30%、PF 0.29、t −4.3；任意日 −17%、勝率 35%。
- 提前賣更糟：第 5 日賣出勝率 16%、PF 0.22（反彈時 IV 回落，兩腿一起縮）。
- 賠的是 put 腿（−57%）；call 腿約打平；現股 +2.2%、勝率 72%。
- 只買 call 在 63 日到期才有正期望：VIX ≥30 後 SPY +18%（PF 1.6）、≥40 後 +38%／勝率 62%／PF 2.35（n=21）、
  QQQ +77%（n=19）；但每百元名目 call +2.9 vs 現股 +8.0，是 cf-vix-spike 的槓桿版不是新訊號。
- 穩健性：K_IV 0.85 雙買仍負（−21%），約 0.66 才打平；今日實價／VIX 全額模型 = 0.81；1993–2009 與 2010→ 同向。
- 限制：權利金是 BS 估值、沒有偏斜；SMH IV 是代理；個股沒測（無免費歷史 IV）。

只買 call 專段（同日追問，`python3 本檔 0.92 call`，輸出 data/…call_k*.out.txt）：
- 一個月內到期沒有優勢：VIX ≥30 後 SPY 21 日價平 call 平均 +0%、價外 5% −43%（66% 歸零）。
- 到期日拉到 6 個月才像樣，而且只在 VIX ≥40：SPY 126 日價平 +80%／勝率 67%（n=21，10 個年份），
  價內 10% +77%／勝率 90%／歸零 5%；VIX ≥30 的 +35% 與任意日 +29% 沒有差別。
- 每百元名目永遠輸現股：VIX ≥40 後 126 日，價內 10% call +12.3、價平 +8.4、現股 +17.4。
  不開槓桿（delta 名目 ≤ 現金）之下，call 換到的是「最多賠權利金」的地板，不是更高報酬。
- 尾部：2008-09→12 連四次歸零（現股同期 −8% 到 −21%，之後漲回；call 沒有之後）。
- K_IV 1.0：SPY 126 日價內 10% 在 VIX ≥40 後仍 +69%／勝率 76%；結論不變。
- 252 日那幾列：^VIX1Y 抓不到，用 VIX 當一年期 IV——大跌時高估成本（保守）、平時低估（基準列偏樂觀），不引用。
- 價內 call 的真實 IV 因偏斜高於價平，模型略低估其成本。

價外一、兩檔（同日追問，`python3 本檔 0.92 call 1.0,1.01,1.02,1.03,1.05`，輸出 data/…call_otm_k*.out.txt）：
- 實際間距（2026-11-10 鏈）：SPY 每檔 $1 = 0.13%（一兩檔等於價平）；QQQ／SMH 六個月每檔 $5 = 0.7–1.0%；
  個股 NVDA／AVGO 每檔 1.6–3.1%。所以「一、兩檔」≈ ETF 價外 0.1–2%、個股 3–6%。
- 六個月到期：價外 1–3% 與價平幾乎一樣。SPY VIX ≥40 後 +80%（價平）→ +79%／+78%／+76%，勝率都 67%；
  QQQ 反而略高（+150% → +152%／+155%／+157%，勝率 74–79%）。
- 三個月：每往外一檔掉一點。SPY VIX ≥40 後 +38% → +35%／+32%／+28%，勝率 62% → 57%／52%／52%。
- 一個月：每往外一檔都更差。SPY VIX ≥30 後 0% → −7%／−15%／−24%，歸零 28% → 30%／41%／50%。
- 價外 call 的真實 IV 低於價平（偏斜），模型對價外是略偏保守。
- 結論：往外一兩檔不改變任何判斷——長天期無差別（挑流動性好的履約價即可），短天期只會更糟。"""
import sys, warnings
from math import erf, sqrt, log, exp
import numpy as np, pandas as pd, yfinance as yf
warnings.filterwarnings("ignore")
K_IV = float(sys.argv[1]) if len(sys.argv) > 1 else 0.92
COST = 0.01          # 進場權利金 1%（指數 ETF 價差；個股遠高於此）
N = lambda x: 0.5 * (1 + erf(x / sqrt(2)))

def bs(S, K, T, r, sig):
    """回傳 (call, put)。T 以年計。"""
    if T <= 0 or sig <= 0:
        return max(S - K, 0.0), max(K - S, 0.0)
    d1 = (log(S / K) + (r + sig * sig / 2) * T) / (sig * sqrt(T)); d2 = d1 - sig * sqrt(T)
    c = S * N(d1) - K * exp(-r * T) * N(d2)
    return c, c - S + K * exp(-r * T)

raw = yf.download(['SPY', 'QQQ', 'SMH', '^VIX', '^VXN', '^VIX9D', '^VIX3M', '^IRX'], period='max', progress=False, auto_adjust=True)['Close']
vix = raw['^VIX'].dropna(); vxn = raw['^VXN']; v9 = raw['^VIX9D']; v3 = raw['^VIX3M']
rf = (raw['^IRX'] / 100).reindex(vix.index).ffill().fillna(0.03)
P = {s: raw[s].dropna() for s in ('SPY', 'QQQ', 'SMH')}
rv = {s: np.log(P[s]).diff().rolling(60).std() * sqrt(252) for s in P}
# 期限結構：短天期用 VIX9D/VIX、長天期用 VIX3M/VIX（沒資料的年代當 1）
term = {5: (v9 / vix).reindex(vix.index).fillna(1.0), 21: pd.Series(1.0, index=vix.index), 63: (v3 / vix).reindex(vix.index).fillna(1.0)}

def iv30(sym):
    if sym == 'SPY': return vix / 100
    if sym == 'QQQ': return vxn.reindex(vix.index) / 100
    ratio = (rv['SMH'] / rv['QQQ']).clip(1.0, 2.0)
    return (vxn.reindex(vix.index) / 100) * ratio.reindex(vix.index)

def iv(sym, d, tenor):
    x = iv30(sym).get(d, np.nan)
    return x * term[tenor].get(d, 1.0) * K_IV if pd.notna(x) else np.nan

def events(cond, gap=20):
    cond = cond.fillna(False); pos = np.flatnonzero(cond.values); keep = []; last = -10**9
    for i in pos:
        if i - last > gap: keep.append(cond.index[i]); last = i
    return keep

def trade(sym, d, tenor, exit_at=None):
    """d 收盤買 ATM 雙買，tenor 個交易日到期；exit_at=None 抱到期，否則第 exit_at 日以 BS 估值賣出。
    回傳 dict（皆以進場標的價為 1 的比例）。"""
    s = P[sym]
    if d not in s.index: return None
    i = s.index.get_loc(d); h = tenor if exit_at is None else exit_at
    if i + h >= len(s): return None
    S0 = s.iloc[i]; sig = iv(sym, d, tenor)
    if pd.isna(sig): return None
    r = rf.get(d, 0.03); c0, p0 = bs(S0, S0, tenor / 252, r, sig)
    c0 *= 1 + COST; p0 *= 1 + COST
    d1 = s.index[i + h]; S1 = s.iloc[i + h]
    if exit_at is None:
        c1, p1 = max(S1 - S0, 0), max(S0 - S1, 0)
    else:
        sig1 = iv(sym, d1, tenor)
        if pd.isna(sig1): return None
        c1, p1 = bs(S1, S0, (tenor - exit_at) / 252, rf.get(d1, 0.03), sig1)
        c1 *= 1 - COST; p1 *= 1 - COST
    return dict(be=(c0 + p0) / S0, move=abs(S1 / S0 - 1), stk=S1 / S0 - 1,
                strd=(c1 + p1) / (c0 + p0) - 1, call=c1 / c0 - 1, put=p1 / p0 - 1,
                strd_n=(c1 + p1 - c0 - p0) / S0, call_n=(c1 - c0) / S0, iv=sig)

def pf(x):
    x = np.asarray(x); g = x[x > 0].sum(); l = -x[x < 0].sum()
    return g / l if l > 0 else np.inf

def row(label, rs):
    if len(rs) < 5: print(f'  {label:<34} n={len(rs)}（樣本太少）'); return
    df = pd.DataFrame(rs); n = len(df); t = df.strd.mean() / (df.strd.std() / sqrt(n))
    print(f'  {label:<34} n={n:>4} IV {df.iv.mean()*100:4.0f}% 損平±{df.be.mean()*100:4.1f}% 實際|動|{df.move.mean()*100:4.1f}% | '
          f'雙買 均{df.strd.mean()*100:+6.1f}% 中{df.strd.median()*100:+6.1f}% 勝{(df.strd>0).mean()*100:3.0f}% PF{pf(df.strd):4.2f} t{t:+4.1f} | '
          f'call 均{df.call.mean()*100:+6.1f}% 中{df.call.median()*100:+6.1f}% 勝{(df.call>0).mean()*100:3.0f}% PF{pf(df.call):4.2f} | '
          f'put 均{df.put.mean()*100:+6.1f}% | 現股 均{df.stk.mean()*100:+5.1f}% 勝{(df.stk>0).mean()*100:3.0f}% | '
          f'每百元名目 雙買{df.strd_n.mean()*100:+5.2f} call{df.call_n.mean()*100:+5.2f}')

spy = P['SPY']; r1 = spy.pct_change(); r5 = spy / spy.shift(5) - 1; dd20 = spy / spy.rolling(20).max() - 1
EV = {
    'E1 SPY 單日 ≤ −2%': events(r1 <= -0.02),
    'E2 SPY 單日 ≤ −3%': events(r1 <= -0.03),
    'E3 SPY 5 日 ≤ −5%': events(r5 <= -0.05),
    'E4 SPY 自 20 日高 ≤ −7%': events(dd20 <= -0.07),
    'E5 SPY 自 20 日高 ≤ −10%': events(dd20 <= -0.10),
    'E6 VIX 首次站上 30': events(vix >= 30),
    'E7 VIX 首次站上 40': events(vix >= 40),
    'E8 SPY 收 5 日新低且距 10 日高 ≤ −2%': events((spy <= spy.rolling(5).min()) & (spy / spy.rolling(10).max() - 1 <= -0.02)),
}
OWN = {s: {f'自身自 20 日高 ≤ −{int(th*100)}%': events(P[s] / P[s].rolling(20).max() - 1 <= -th) for th in ths}
       for s, ths in (('QQQ', (0.10, 0.15)), ('SMH', (0.15, 0.20)))}
START = {'SPY': '1993-02-01', 'QQQ': '2001-02-01', 'SMH': '2001-02-01'}

def run(sym, tenor, exit_at=None, since=None, until=None):
    st = pd.Timestamp(since or START[sym]); en = pd.Timestamp(until or '2100-01-01')
    allev = dict(EV); allev.update(OWN.get(sym, {}))
    for k, days in allev.items():
        rs = [t for d in days if st <= d <= en for t in [trade(sym, d, tenor, exit_at)] if t]
        row(k, rs)
    base = [t for d in P[sym].index[::5] if st <= d <= en for t in [trade(sym, d, tenor, exit_at)] if t]
    row('基準：任意日（每 5 日取樣）', base)

if __name__ == '__main__' and len(sys.argv) <= 2:
    print(f'K_IV={K_IV}（ATM IV = IV 指數 × {K_IV}）；報酬率 = 相對權利金；每百元名目 = 損益 ÷ 標的價 × 100；進場成本 {COST*100:.0f}%')
    # 校準點：今天 SPY 最接近 30 天的 ATM 雙買實價 vs 模型
    try:
        tk = yf.Ticker('SPY'); S = float(P['SPY'].iloc[-1]); today = P['SPY'].index[-1]
        exps = [e for e in tk.options if 20 <= (pd.Timestamp(e) - today).days <= 45]
        e = min(exps, key=lambda x: abs((pd.Timestamp(x) - today).days - 30)); ch = tk.option_chain(e)
        K = min(ch.calls.strike, key=lambda k: abs(k - S))
        def mid(df):
            r = df[df.strike == K].iloc[0]; m = (r.bid + r.ask) / 2
            return float(m if m > 0 else r.lastPrice)   # 盤外 bid/ask 為 0 → 用最後成交價
        T = (pd.Timestamp(e) - today).days / 365; mkt = mid(ch.calls) + mid(ch.puts)
        c, p = bs(S, K, T, float(rf.iloc[-1]), float(vix.iloc[-1]) / 100)
        print(f'校準：SPY {S:.1f} 到期 {e} K={K} 實價雙買 {mkt:.2f}；VIX {vix.iloc[-1]:.1f} 全額代入模型 {c+p:.2f} → 實價/模型 = {mkt/(c+p):.2f}')
    except Exception as ex:
        print('校準略過：', ex)
    for sym in ('SPY', 'QQQ', 'SMH'):
        for tenor in (5, 21, 63):
            print(f'\n### {sym} ATM 雙買 {tenor} 交易日到期，抱到期' + ('（IV 為代理值）' if sym == 'SMH' else ''))
            run(sym, tenor)
    for sym in ('SPY', 'QQQ'):
        for ex_at in (5, 10):
            print(f'\n### {sym} 買 21 日到期雙買，第 {ex_at} 日賣出（BS 估值，吃 IV 回落）')
            run(sym, 21, ex_at)
        print(f'\n### {sym} 買 63 日到期雙買，第 21 日賣出')
        run(sym, 63, 21)
    print('\n\n== 分段穩健性：SPY 21 日抱到期 ==')
    for a, b in (('1993-02-01', '2009-12-31'), ('2010-01-01', '2100-01-01')):
        print(f'-- {a[:4]}→{b[:4]}'); run('SPY', 21, None, a, b)


# ---------- 只買 call 專段（2026-11-10 用戶追問「那只買 call？」）：python3 本檔 0.92 call ----------
def call_study():
    lt = yf.download(['^VIX6M', '^VIX1Y'], period='max', progress=False, auto_adjust=True)['Close']
    term[126] = (lt['^VIX6M'] / vix).reindex(vix.index).fillna(1.0)
    term[252] = (lt['^VIX1Y'] / vix).reindex(vix.index).fillna(1.0)

    def ct(sym, d, tenor, m):
        s = P[sym]
        if d not in s.index: return None
        i = s.index.get_loc(d)
        if i + tenor >= len(s): return None
        S0 = s.iloc[i]; sig = iv(sym, d, tenor)
        if pd.isna(sig): return None
        c0 = bs(S0, S0 * m, tenor / 252, rf.get(d, 0.03), sig)[0] * (1 + COST)
        S1 = s.iloc[i + tenor]; c1 = max(S1 - S0 * m, 0)
        return dict(roi=c1 / c0 - 1, prem=c0 / S0, pn=(c1 - c0) / S0, stk=S1 / S0 - 1, yr=d.year)

    def line(label, rs):
        if len(rs) < 5: print(f'    {label:<18} n={len(rs)}（太少）'); return
        df = pd.DataFrame(rs); n = len(df); t = df.roi.mean() / (df.roi.std() / sqrt(n))
        # 同一筆預算：把買 call 的權利金改買現股，賺多少（比較「同樣賠得起的錢」）
        print(f'    {label:<18} n={n:>4} 年份{df.yr.nunique():>3} 權利金佔標的{df.prem.mean()*100:5.1f}% | call 均{df.roi.mean()*100:+7.1f}% 中{df.roi.median()*100:+7.1f}% '
              f'勝{(df.roi>0).mean()*100:3.0f}% 歸零{(df.roi<=-0.999).mean()*100:3.0f}% PF{pf(df.roi):5.2f} t{t:+5.1f} | '
              f'每百元名目 call{df.pn.mean()*100:+6.2f} 現股{df.stk.mean()*100:+6.2f}（現股勝{(df.stk>0).mean()*100:3.0f}%）')

    # 第三個參數可給履約價倍數清單，例：python3 本檔 0.92 call 1.0,1.01,1.02
    if len(sys.argv) > 3:
        MS = [(float(x), '價平' if float(x) == 1 else f'價{"外" if float(x) > 1 else "內"}{abs(float(x) - 1) * 100:.1f}%') for x in sys.argv[3].split(',')]
    else:
        MS = [(0.90, '價內10%'), (1.00, '價平'), (1.05, '價外5%')]
    evs = {k: EV[k] for k in ('E2 SPY 單日 ≤ −3%', 'E3 SPY 5 日 ≤ −5%', 'E5 SPY 自 20 日高 ≤ −10%', 'E6 VIX 首次站上 30', 'E7 VIX 首次站上 40')}
    for sym in ('SPY', 'QQQ', 'SMH'):
        st = pd.Timestamp(START[sym])
        for tenor in (21, 63, 126, 252):
            for m, mn in MS:
                print(f'\n  ## {sym} call {tenor} 日到期 {mn}' + ('（IV 代理）' if sym == 'SMH' else ''))
                for k, days in evs.items():
                    line(k[:16], [t for d in days if d >= st for t in [ct(sym, d, tenor, m)] if t])
                line('基準：任意日', [t for d in P[sym].index[::5] if d >= st for t in [ct(sym, d, tenor, m)] if t])
    print('\n  ## VIX 首次站上 40 逐筆（SPY 63 日價平 call）')
    for d in EV['E7 VIX 首次站上 40']:
        t = ct('SPY', d, 63, 1.0)
        if t: print(f'    {d.date()} VIX {vix[d]:5.1f} call {t["roi"]*100:+7.1f}%  現股 {t["stk"]*100:+6.1f}%')

if __name__ == '__main__' and len(sys.argv) > 2 and sys.argv[2] == 'call':
    call_study()
