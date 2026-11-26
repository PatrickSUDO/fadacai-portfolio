"""vol_target_robustness_2026-11-20.py — 波動目標（2026-10-19 測過、10-23 未採用）換參數、換標的、拉長歷史後還站不站得住
（2026-11-20 用戶「你也得看看之前測過還有現在有在用的方式哪個 calmar, sharpe 好」；排行見 strategy_leaderboard_2026-11-20.py）

規則同 tools/backtest_vol_target.py：曝險 = min(1, 目標 ÷ N 日實現波動)，週五收盤決定、變動 <10% 不動、隔日生效，其餘放國庫券，每次調整 10bp；
「趨勢」= 收盤在 200 日線下再減半。格子：目標 15／20／25／30% × 回看 20／60 日 × 有無趨勢 = 16 組；
標的：半導體（SMH，2000-06 前用費半）1998-04→、QQQ 2000-11→、SPY 1994→；三個時段（全期、2009 前、2010 後）。
每格另列「同樣平均曝險的固定配置」，分得出好處是來自「少抱」還是來自「什麼時候少抱」。輸出欄位：Sharpe／Calmar（年化、最大回撤）。

首跑結論（2026-11-20）：
- Calmar 幾乎每一格都贏：三個時段都高於買進持有的有 半導體 16／16、QQQ 14／16、SPY 16／16；三個時段都高於「同曝險固定配置」的有 13、14、16。
  這是當日所有做法裡唯一換參數、換標的、換時段都成立的（乖離減碼 0／60、每跌 10% 加碼 2／24、長均線換 VOO 兩窗方向相反）。
- Sharpe 只小贏：三個時段都高於買進持有的是 8、7、10 組，差距 +0.02 到 +0.15，區塊重抽的 95% 區間含 0（見排行腳本）。
- 代價是多頭年少賺：半導體 2010 後買進持有 +23.2%／−45%；目標 20% 是 +18.0%／−26%、25% 是 +20.5%／−31%、30% 是 +22.1%／−37%。
  含 2000 年崩盤的全期則不少賺（目標 25–30%：+13.8% 到 +14.2% vs +13.6%，回撤 −57% 到 −65% vs −87%）。
- 好處只在「其餘放現金／國庫券」時成立；其餘放 VOO 的版本 Sharpe、Calmar 與固定配置相同（排行腳本 A 組）。
- 2026 年：SMH 買進持有 +11.1%／−40%，波動目標 20% +17.1%／−19%；套到帳戶實際個股格是 +3.9% 到 +5.7%／回撤 −22% 到 −27%（不調整 −0.1%／−34%）。
- 10-23 未採用的理由仍在：與 R15（回檔期間信念桶禁減碼）、R33（閒置放 VOO）互咬；約六成的加回發生在減碼後 30 天內；對一週內的急跌沒有保護。

用法：python3 tools/backtests/vol_target_robustness_2026-11-20.py
"""
import numpy as np, pandas as pd, yfinance as yf, warnings
warnings.filterwarnings('ignore')
raw = yf.download(['^SOX','SMH','QQQ','SPY','^IRX'], period='max', progress=False, auto_adjust=True)['Close']
rfa = (raw['^IRX']/100/252).ffill()
def met(r, rf):
    eq = np.cumprod(1+r); c = eq[-1]**(252/len(r))-1; m = (eq/np.maximum.accumulate(eq)-1).min(); ex = r-rf
    return c, m, ex.mean()/ex.std()*np.sqrt(252), c/abs(m)
def expo(ret, price, target, lb, trend, thr=0.10):
    vol = ret.rolling(lb).std()*np.sqrt(252); rw = (target/vol).clip(upper=1.0).fillna(1.0)
    wk = rw.where(rw.index.weekday==4).ffill().fillna(1.0); held=[1.0]
    for v in wk.iloc[1:]: held.append(v if abs(v-held[-1])>=thr else held[-1])
    e = pd.Series(held, index=ret.index)
    if trend: e = e*(price > price.rolling(200).mean()).astype(float).replace(0.0,0.5)
    return e.shift(1).fillna(1.0)
sox = raw['^SOX'].dropna(); rs = raw['SMH'].pct_change().reindex(sox.index); rs = rs.where(rs.notna(), sox.pct_change()).fillna(0)
ASSETS = {'半導體（1998-04→）': (rs['1998-04-09':], sox, rs), 'QQQ（2000-11→）': (raw['QQQ'].pct_change().dropna()['2000-11-01':], raw['QQQ'].dropna(), raw['QQQ'].pct_change().fillna(0)),
          'SPY（1994→）': (raw['SPY'].pct_change().dropna()['1994-01-03':], raw['SPY'].dropna(), raw['SPY'].pct_change().fillna(0))}
for nm, (r, price, rfull) in ASSETS.items():
    rf = rfa.reindex(r.index).ffill().fillna(0.03/252); idx = r.index; rv_ = r.to_numpy(copy=True); rfv = rf.to_numpy(copy=True)
    wins = {'全期': np.asarray(idx >= idx[0]), '2009 前': np.asarray(idx < '2010-01-01'), '2010 後': np.asarray(idx >= '2010-01-01')}
    bh = {k: met(rv_[m], rfv[m]) for k, m in wins.items()}
    print(f'\n{nm} 買進持有：' + '｜'.join(f'{k} Sharpe {v[2]:.2f}／Calmar {v[3]:.2f}（{v[0]*100:+.1f}%、{v[1]*100:.0f}%）' for k, v in bh.items()))
    okS = okC = okST = okSS = tot = 0
    for tg in (0.15, 0.20, 0.25, 0.30):
        for lb in (20, 60):
            for tr in (False, True):
                e = expo(rfull, price, tg, lb, tr).reindex(idx).fillna(1.0).to_numpy(copy=True)
                x = e*rv_ + (1-e)*rfv; x[1:] -= np.abs(np.diff(e))*0.001
                ms = {k: met(x[m], rfv[m]) for k, m in wins.items()}
                st = {k: met(e[m].mean()*rv_[m] + (1-e[m].mean())*rfv[m], rfv[m]) for k, m in wins.items()}
                tot += 1; okS += all(ms[k][2] > bh[k][2] for k in wins); okC += all(ms[k][3] > bh[k][3] for k in wins)
                okST += all(ms[k][3] > st[k][3] for k in wins); okSS += all(ms[k][2] > st[k][2] for k in wins)
                print(f'T{tg*100:.0f} L{lb} {"趨勢" if tr else "    "} 曝險{e.mean()*100:3.0f}%：' + '｜'.join(f'{k} {ms[k][2]:.2f}／{ms[k][3]:.2f}（{ms[k][0]*100:+5.1f}%、{ms[k][1]*100:4.0f}%；同曝險 {st[k][2]:.2f}／{st[k][3]:.2f}）' for k in wins))
    print(f'→ {tot} 組裡：三時段 Sharpe 都高於買進持有 {okS}；三時段 Calmar 都高於買進持有 {okC}；三時段 Sharpe 都高於同曝險固定 {okSS}；三時段 Calmar 都高於同曝險固定 {okST}')
