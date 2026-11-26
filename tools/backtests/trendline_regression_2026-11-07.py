"""趨勢線 / 線性回歸 當進出場輔助的實證——同 feedback/ma-filter-evidence.md 的宇宙與 horizon。
30 檔（14 檔持倉 + 12 檔候補 + 補 4 檔曾持有）× 2021-09→今，指標 = 之後 20 日報酬。"""
import numpy as np, pandas as pd, yfinance as yf, warnings, sys
warnings.filterwarnings("ignore")
HOLD = ['AMAT','ANET','AVGO','CLS','CRM','CRWD','DIOD','MU','NET','NVDA','PLTR','PWR','SNPS','TWLO']
CAND = ['HWM','ATI','FN','GEV','COHR','VRT','PAYC','WDAY','DOCU','ZS','OKTA','AMZN']
EXTRA = ['LITE','MRVL','ONTO','STRL']
U = HOLD + CAND + EXTRA
H = 20
raw = yf.download(U, start='2021-06-01', progress=False, auto_adjust=True)
C, L, Hi = raw['Close'], raw['Low'], raw['High']
rows, trend_events = [], []

def regstats(y, w):
    """rolling OLS on log price: slope(%/day), z of last point vs line (resid σ), R²"""
    n = len(y); out = np.full((n, 3), np.nan)
    if n < w: return out
    sw = np.lib.stride_tricks.sliding_window_view(y, w)
    t = np.arange(w); tm = t.mean(); tt = ((t - tm) ** 2).sum()
    ym = sw.mean(1, keepdims=True)
    slope = ((t - tm) * (sw - ym)).sum(1) / tt
    fit = ym + slope[:, None] * (t - tm)
    res = sw - fit
    sd = res.std(1); sst = ((sw - ym) ** 2).sum(1)
    r2 = 1 - (res ** 2).sum(1) / np.where(sst == 0, np.nan, sst)
    z = res[:, -1] / np.where(sd == 0, np.nan, sd)
    out[w - 1:] = np.c_[slope * 100, z, r2]
    return out

def pivots(a, k, kind):
    idx = []
    for i in range(k, len(a) - k):
        win = a[i - k:i + k + 1]
        if (kind == 'low' and a[i] == win.min()) or (kind == 'high' and a[i] == win.max()):
            idx.append(i)
    return idx

for s in U:
    c = C[s].dropna(); lo = L[s].reindex(c.index); hi = Hi[s].reindex(c.index)
    if len(c) < 300: continue
    y = np.log(c.values); n = len(y)
    fwd = np.full(n, np.nan); fwd[:-H] = c.values[H:] / c.values[:-H] - 1
    fwd5 = np.full(n, np.nan); fwd5[:-5] = c.values[5:] / c.values[:-5] - 1
    fwd60 = np.full(n, np.nan); fwd60[:-60] = c.values[60:] / c.values[:-60] - 1
    df = pd.DataFrame({'sym': s, 'fwd': fwd, 'fwd5': fwd5, 'fwd60': fwd60}, index=c.index)
    for w in (20, 50, 100):
        st = regstats(y, w)
        df[f'slope{w}'], df[f'z{w}'], df[f'r2{w}'] = st[:, 0], st[:, 1], st[:, 2]
    df['sma50'] = c.rolling(50).mean().values; df['ema200'] = c.ewm(span=200).mean().values
    df['filt'] = (c.values > df['sma50']) & (c.values > df['ema200'])
    # ── 趨勢線：最近兩個已確認 pivot low（第二個較高）連線；pivot high 同理 ──
    k = 5
    pl = pivots(lo.values, k, 'low'); ph = pivots(hi.values, k, 'high')
    up_line = np.full(n, np.nan); dn_line = np.full(n, np.nan)
    for d in range(n):
        cl = [p for p in pl if p + k <= d]           # 已確認（d 已過 p+k）
        if len(cl) >= 2:
            p1, p2 = cl[-2], cl[-1]
            if lo.values[p2] > lo.values[p1] and d - p2 <= 120:
                up_line[d] = lo.values[p1] + (lo.values[p2] - lo.values[p1]) / (p2 - p1) * (d - p1)
        ch = [p for p in ph if p + k <= d]
        if len(ch) >= 2:
            p1, p2 = ch[-2], ch[-1]
            if hi.values[p2] < hi.values[p1] and d - p2 <= 120:
                dn_line[d] = hi.values[p1] + (hi.values[p2] - hi.values[p1]) / (p2 - p1) * (d - p1)
    cv = c.values
    above_up = cv >= up_line; below_dn = cv <= dn_line
    df['up_break'] = np.r_[False, (above_up[:-1] & ~above_up[1:] & ~np.isnan(up_line[1:]) & ~np.isnan(up_line[:-1]))]
    df['dn_break'] = np.r_[False, (below_dn[:-1] & ~below_dn[1:] & ~np.isnan(dn_line[1:]) & ~np.isnan(dn_line[:-1]))]
    df['up_touch'] = above_up & (cv / up_line - 1 <= 0.02)      # 貼著上升趨勢線（±2% 內）未破
    df['up_intact'] = above_up & ~np.isnan(up_line)
    rows.append(df)

D = pd.concat(rows).dropna(subset=['fwd'])
base = D['fwd']
def line(name, m, extra=''):
    sub = D.loc[m, 'fwd']
    if len(sub) == 0: print(f'{name:<44} n=0'); return
    print(f'{name:<44} n={len(sub):>6}  20日均 {sub.mean()*100:5.2f}%  勝率 {(sub>0).mean()*100:4.1f}%  中位 {sub.median()*100:5.2f}%{extra}')
print(f'基準（任意日買）                            n={len(base):>6}  20日均 {base.mean()*100:5.2f}%  勝率 {(base>0).mean()*100:4.1f}%  中位 {base.median()*100:5.2f}%')
print(f'（對照）> SMA50 且 > EMA200 濾網', end=' '); line('', D['filt'])

print('\n== A. 線性回歸斜率 五分位（Q1 最低→Q5 最高）==')
for w in (20, 50, 100):
    q = pd.qcut(D[f'slope{w}'], 5, labels=False)
    print(f'回歸 {w:>3} 日斜率: ' + '  '.join(f'Q{i+1} {D.loc[q==i,"fwd"].mean()*100:4.2f}%/{(D.loc[q==i,"fwd"]>0).mean()*100:4.1f}%' for i in range(5)))
print('\n== B. 回歸通道位置 z（價 vs 回歸線，殘差σ）五分位 ==')
for w in (20, 50, 100):
    q = pd.qcut(D[f'z{w}'], 5, labels=False)
    print(f'通道 {w:>3} 日 z: ' + '  '.join(f'Q{i+1} {D.loc[q==i,"fwd"].mean()*100:4.2f}%/{(D.loc[q==i,"fwd"]>0).mean()*100:4.1f}%' for i in range(5)))
    line(f'  z{w} < −2（跌出通道下軌）', D[f'z{w}'] < -2)
    line(f'  z{w} > +2（衝出通道上軌）', D[f'z{w}'] > 2)
    line(f'  斜率>0 且 z{w} < −1（上升通道回到下緣）', (D[f'slope{w}'] > 0) & (D[f'z{w}'] < -1))
    line(f'  斜率>0 且 z{w} > +1（上升通道上緣）', (D[f'slope{w}'] > 0) & (D[f'z{w}'] > 1))
print('\n== C. 回歸 R²（趨勢乾淨度）五分位 ==')
for w in (50, 100):
    q = pd.qcut(D[f'r2{w}'], 5, labels=False)
    print(f'R² {w:>3} 日: ' + '  '.join(f'Q{i+1} {D.loc[q==i,"fwd"].mean()*100:4.2f}%/{(D.loc[q==i,"fwd"]>0).mean()*100:4.1f}%' for i in range(5)))
    line(f'  斜率>0 且 R²{w} 最高分位（乾淨上升）', (D[f'slope{w}'] > 0) & (q == 4))
    line(f'  斜率<0 且 R²{w} 最高分位（乾淨下跌）', (D[f'slope{w}'] < 0) & (q == 4))

print('\n== D. 畫線派：兩個 pivot 連的趨勢線（k=5，線齡 ≤120 日）==')
line('上升趨勢線完好（價在線上）', D['up_intact'])
line('貼上升趨勢線 ≤2%（「回測趨勢線買」）', D['up_touch'])
line('跌破上升趨勢線當日（「破線賣」）', D['up_break'])
line('突破下降趨勢線當日（「突破買」）', D['dn_break'])
for col, nm in (('up_break', '跌破上升線'), ('dn_break', '突破下降線')):
    sub = D[D[col]]
    print(f'  {nm} 後 5 日 {sub["fwd5"].mean()*100:5.2f}%（基準 {D["fwd5"].mean()*100:4.2f}%）  60 日 {sub["fwd60"].mean()*100:5.2f}%（基準 {D["fwd60"].mean()*100:4.2f}%）  n={len(sub)}')
# 破線後再跌 vs 反彈：破線賣能不能躲掉？
sub = D[D['up_break']]
print(f'  跌破上升線後 20 日 跌幅 >5% 的比例 {(sub["fwd"]<-0.05).mean()*100:4.1f}%（基準 {(D["fwd"]<-0.05).mean()*100:4.1f}%）；漲幅 >5% 的比例 {(sub["fwd"]>0.05).mean()*100:4.1f}%（基準 {(D["fwd"]>0.05).mean()*100:4.1f}%）')
print('\n== E. 疊在既有濾網上（>SMA50 且 >EMA200）==')
F = D['filt']
line('濾網內・回歸100斜率 Q5', F & (pd.qcut(D['slope100'], 5, labels=False) == 4))
line('濾網內・通道100 z < −1（回到下緣）', F & (D['z100'] < -1))
line('濾網內・貼上升趨勢線 ≤2%', F & D['up_touch'])
line('濾網內・跌破上升趨勢線當日', F & D['up_break'])
