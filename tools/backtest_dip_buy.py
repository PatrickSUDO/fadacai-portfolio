"""backtest_dip_buy.py — 「SMH/QQQ 兩日大跌後買現股」回測（2026-10-30 用戶「先不管規則你回測一下」）
觸發：SMH 兩日 ≤ −6%/−8% 或 QQQ ≤ −4%（可加 VIX ≥20），同一波去叢集 10 天；標的：用戶點名的 8 檔。
量測：觸發日收盤買／隔日開盤買 持有 20/45 日報酬 vs 隨便哪天買的基準；持有期最深回撤；−5%/−10% 回檔梯成交率與成交者報酬；對 SMH 超額。
用法：python3 tools/backtest_dip_buy.py
"""
import yfinance as yf, pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
NAMES=["MU","GOOGL","MSFT","AMZN","META","NVDA","AVGO","AMD"]
raw=yf.download(NAMES+["SMH","QQQ","^VIX"],period="max",auto_adjust=True,progress=False)
C=raw["Close"]; O=raw["Open"]; L=raw["Low"]
C=C[(C.index>="2010-01-01")&(C.index.date<=pd.Timestamp("2026-10-29").date())]; O=O.loc[C.index]; L=L.loc[C.index]
def triggers(idx,thr,vixmin):
    r2=C[idx]/C[idx].shift(2)-1
    cond=(r2<=thr)&(C["^VIX"]>=vixmin); days=list(C.index[cond.fillna(False)])
    keep=[];last=None
    for d in days:
        if last is None or (d-last).days>10: keep.append(d); last=d
    return keep
def fwd(s,i,n): return s.iloc[i+n]/s.iloc[i]-1 if i+n<len(s) else np.nan
def study(label,days,hold=45):
    rows=[]
    for d in days:
        i=C.index.get_loc(d)
        for n in NAMES:
            s=C[n]; 
            if np.isnan(s.iloc[i]) or i+hold>=len(s): continue
            buy_close=s.iloc[i]; buy_open=O[n].iloc[i+1]
            r_close=s.iloc[i+hold]/buy_close-1; r_open=s.iloc[i+hold]/buy_open-1
            path=s.iloc[i:i+hold+1]; mdd=path.min()/buy_close-1
            # ladder: limits at -5%/-10% from trigger close, valid 20d, exit at i+hold
            lows=L[n].iloc[i+1:i+21]
            f5=(lows<=buy_close*0.95).any(); f10=(lows<=buy_close*0.90).any()
            r5=s.iloc[i+hold]/(buy_close*0.95)-1 if f5 else np.nan
            r10=s.iloc[i+hold]/(buy_close*0.90)-1 if f10 else np.nan
            rows.append(dict(date=d,name=n,r_close=r_close,r_open=r_open,mdd=mdd,f5=f5,f10=f10,r5=r5,r10=r10,
                             smh=C["SMH"].iloc[i+hold]/C["SMH"].iloc[i]-1))
    df=pd.DataFrame(rows)
    # unconditional baseline per name: median hold-day return over all days
    base={n:(C[n].shift(-hold)/C[n]-1).dropna() for n in NAMES}
    base_med=np.median(np.concatenate([b.values for b in base.values()])); base_win=np.mean(np.concatenate([(b>0).values for b in base.values()]))
    print(f"\n=== {label}：觸發 {len(days)} 次，{hold} 個交易日持有，8 檔合計 {len(df)} 筆 ===")
    print(f"觸發日收盤買： 中位 {df.r_close.median():+.1%}  均 {df.r_close.mean():+.1%}  勝率 {(df.r_close>0).mean():.0%} ｜ 隨便哪天買的基準：中位 {base_med:+.1%} 勝率 {base_win:.0%}")
    print(f"隔日開盤買：   中位 {df.r_open.median():+.1%}  均 {df.r_open.mean():+.1%}  勝率 {(df.r_open>0).mean():.0%}")
    print(f"持有期間最深回撤（相對買價）：中位 {df.mdd.median():+.1%}；20 日內再跌 ≥10% 的比例 {(df.mdd<=-0.10).mean():.0%}；≥20% {(df.mdd<=-0.20).mean():.0%}")
    print(f"回檔梯：−5% 單成交率 {df.f5.mean():.0%}，成交者 {hold} 日報酬中位 {df.r5.median():+.1%} 成交者勝率 {(df.r5.dropna()>0).mean():.0%}；−10% 單成交率 {df.f10.mean():.0%}，中位 {df.r10.median():+.1%} 成交者勝率 {(df.r10.dropna()>0).mean():.0%}")
    print(f"同期 SMH 中位 {df.smh.median():+.1%}（個股對 SMH 超額中位 {(df.r_close-df.smh).median():+.1%}）")
    per=df.groupby("name").agg(n=("r_close","size"),med=("r_close","median"),win=("r_close",lambda x:(x>0).mean()),mdd=("mdd","median"))
    print(per.assign(med=lambda t:(t.med*100).round(1),win=lambda t:(t.win*100).round(0),mdd=lambda t:(t.mdd*100).round(1)).to_string())
    yr=df.assign(y=df.date.dt.year).groupby("y").agg(n=("r_close","size"),med=("r_close","median"),win=("r_close",lambda x:(x>0).mean()))
    print("依年份：", {int(y):f"n{int(r.n)} 中位{r.med:+.0%} 勝{r.win:.0%}" for y,r in yr.iterrows()})
    return df
d1=triggers("SMH",-0.06,20); study("SMH 兩日跌 ≥6% 且 VIX ≥20",d1,45)
study("同上，持有 20 日",d1,20)
d2=triggers("SMH",-0.08,0);  study("SMH 兩日跌 ≥8%（不看 VIX）",d2,45)
d3=triggers("QQQ",-0.04,20); study("QQQ 兩日跌 ≥4% 且 VIX ≥20",d3,45)
