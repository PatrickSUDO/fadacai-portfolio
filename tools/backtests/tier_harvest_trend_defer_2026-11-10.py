"""U4 梯級停利在趨勢中延後 — 2026-11-10

問題：認列桶梯級停利（未實現 +30%／+60%／+100% 各賣 15%／15%／20%，`feedback/tiered-profit-taking.md`）是到價就賣。
若到價當天股價仍在上升趨勢（收盤 > SMA50 且 > EMA200），改成「等第一次收盤跌破 SMA50 才賣」（最多等 120 個交易日），會賣得比較好嗎？

設計（事先寫定，不調參）：
- 宇宙：`vix_spike_timing_2026-11-07.py` 的 HOLD + CAND 30 檔，價格 2018-01→（均線暖身），建倉 2019→
- 建倉：每檔在每年第一個交易日收盤建一個 lot（另做每季第一個交易日版增加樣本）；建倉日該檔須已有 ≥200 個交易日歷史（EMA200 才算得出）
- 級距事件：未實現（收盤 ÷ 建倉價 − 1）首次 ≥ +30%／+60%／+100% 的那天
    (a) 當日收盤賣該級距比例
    (b) 當日收盤 > SMA50 且 > EMA200 → 延後到之後第一次收盤 < SMA50 的那天收盤賣；滿 120 個交易日仍未跌破 → 第 120 日收盤賣；
        當日不在趨勢中 → 與 (a) 相同（價差 0）
- 比較：(b) 成交價 ÷ (a) 成交價 − 1。報平均、中位、(b) 較好比例、最差 10%（第 10 百分位與最差十分之一的平均）、按級距分開、按觸發年份分開
- 防偷看：SMA50／EMA200 只用到當日收盤；(b) 的賣出日由當日收盤判定。另列「(b) 判定後隔日收盤才成交」版（t 收盤判定 → t+1 執行）
- 公平對照：(a) 賣出的錢不會躺著——同一段延後期間 SPY／SMH 的報酬一併列出，「(b) − SPY」「(b) − SMH」才是延後的淨好處
- 資料尾端未走完（未跌破且未滿 120 日）的事件剔除並報數量

已知缺陷（重要）：
1. **倖存者偏差**：30 檔是 2026 年的持倉與候補，事後看都是贏家；贏家的特徵就是「到價後繼續漲」，會系統性高估延後的好處。
2. 同一檔不同年份／季度的 lot 共用同一條價格路徑，事件高度相關；有效樣本遠小於事件數（另列「以股票為單位」的平均與 t 值）。
3. 實際梯級單是 GTC 限價（盤中觸價成交），這裡用收盤近似；未計交易成本。
4. 樣本期 2019→ 幾乎是單一多頭（中間夾 2022）；無 2000／2008 型長空頭。

首跑結論（2026-11-10，年初建倉版 198 個 lot／544 個級距事件；季初版 786 個 lot／2,122 個事件，兩版數字幾乎相同）：
- 到價當天 99% 都在趨勢中 → 規則 (b) 實際上等於「一律延後到跌破 SMA50」。延後天數中位 39 日；96% 以跌破 SMA50 結束、4% 滿 120 日。
- 典型結果是賣得比較差：(b) 相對 (a) 的成交價差 中位 −1.5%、(b) 較好只有 44–45%、較差 55%；第 10 百分位 −13.8%、最差一成平均 −18.4%。
- 平均卻是 +12.7%，全靠右尾：最好一成平均 +127.5%。滿 120 日才賣的 19 筆平均 +242%，其中 14 筆是同一檔 LITE 的 2025-08→2026-04 同一段行情
  （不同年份的 lot 重複計）；跌破 SMA50 才賣的 520 筆平均 +4.5%、中位 −2.0%、較好 42%。
- 按級距：+30% 級 平均 +9.3%／中位 −1.9%／較好 41%；+60% 級 +13.7%／−2.6%／45%；+100% 級 +15.7%／−0.3%／48%。沒有哪一級明顯不同。
- 公平對照（賣出的錢同期放指數）：延後期間 SPY 平均 +1.7%、SMH +5.5%；(b) − SMH 平均 +7.3%、中位 −3.2%、為正 40%。
  以股票為單位（30 檔）：延後價差平均 +10.7%（t +1.82）、扣 SMH +4.3%（t +0.79）、扣 SMH 為正 14/30 檔。
  拿掉最好的三檔（LITE／MU／PLTR）：平均 +3.9%、中位 −2.5%、扣 SMH −0.5%。
- 按觸發年份：2020 中位 +6.3%／較好 62%；2021 −5.4%／33%；2022 −7.0%／31%；2024 −2.4%／39%；2025 平均 +54.7% 但中位 −4.2%（LITE）；2026 −1.8%／43%。
- 隔日收盤成交版（t 判定 → t+1 執行）：平均 +13.8%、中位 −1.1%、較好 47%——結論不變。
- 判讀：**證據不足，偏不成立**。延後是「六成機率少賣 2–14%，換一個小機率的大贏」；平均為正完全來自少數幾檔的單一行情，
  而宇宙本身是事後挑的贏家（倖存者偏差方向 = 高估延後）。扣掉指數與前三檔後是 0。右尾已經由梯級規則的 30% runner 保底在吃，
  不需要再用延後停利去買第二張同樣的彩券。梯級停利維持到價即賣。
"""
import numpy as np, pandas as pd, yfinance as yf, warnings
warnings.filterwarnings("ignore")

HOLD = ['AMAT','ANET','AVGO','CLS','CRM','CRWD','DIOD','MU','NET','NVDA','PLTR','PWR','SNPS','TWLO']
CAND = ['HWM','ATI','FN','GEV','COHR','VRT','PAYC','WDAY','DOCU','ZS','OKTA','AMZN','LITE','MRVL','ONTO','STRL']
U = HOLD + CAND
TIERS = ((0.30, 0.15), (0.60, 0.15), (1.00, 0.20))
MAXDEF = 120
raw = yf.download(U + ["SPY", "SMH"], start="2017-01-01", progress=False, auto_adjust=True)["Close"]
cal = raw["SPY"].dropna().index
spy = raw["SPY"].reindex(cal); smh = raw["SMH"].reindex(cal)

def entry_days(freq):
    s = pd.Series(cal, index=cal); s = s[s.index >= "2019-01-01"]
    key = s.index.to_period("Y" if freq == "Y" else "Q")
    return list(s.groupby(key).first())

def simulate(freq):
    rows = []; skipped_open = 0; no_hist = 0
    for sym in U:
        px = raw[sym].dropna()
        if px.empty: continue
        sma = px.rolling(50).mean(); ema = px.ewm(span=200, adjust=False, min_periods=200).mean()
        v = px.to_numpy(); sm = sma.to_numpy(); em = ema.to_numpy(); ix = px.index
        for d in entry_days(freq):
            if d not in ix: continue
            i0 = ix.get_loc(d)
            if i0 < 200: no_hist += 1; continue
            e = v[i0]
            for tier, frac in TIERS:
                hit = np.nonzero(v[i0 + 1:] >= e * (1 + tier))[0]
                if len(hit) == 0: continue
                it = i0 + 1 + hit[0]
                in_trend = (v[it] > sm[it]) and (v[it] > em[it])
                if not in_trend:
                    ib = it; why = "未延後"
                else:
                    brk = np.nonzero(v[it + 1:it + 1 + MAXDEF] < sm[it + 1:it + 1 + MAXDEF])[0]
                    if len(brk):
                        ib = it + 1 + brk[0]; why = "跌破SMA50"
                    elif it + MAXDEF < len(v):
                        ib = it + MAXDEF; why = "滿120日"
                    else:
                        skipped_open += 1; continue
                ib1 = min(ib + 1, len(v) - 1) if why != "未延後" else ib          # 隔日收盤成交版
                da, db = ix[it], ix[ib]
                bs = spy.loc[db] / spy.loc[da] - 1; bm = smh.loc[db] / smh.loc[da] - 1
                rows.append(dict(sym=sym, entry=d, tier=tier, frac=frac, trig=da, sell_b=db, why=why, days=ib - it,
                                 diff=v[ib] / v[it] - 1, diff_next=v[ib1] / v[it] - 1, spy=bs, smh=bm,
                                 lot_gain=frac * (v[ib] - v[it]) / e))
    return pd.DataFrame(rows), skipped_open, no_hist

def tcl(x):
    x = x.dropna(); return x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 2 and x.std() > 0 else np.nan

def line(lab, d):
    x = d["diff"]; q10 = x.quantile(0.10); worst = x[x <= q10].mean()
    return (f"   {lab:<16} n={len(d):>4}  延後佔 {(d.why != '未延後').mean():>4.0%}  平均 {x.mean():>+6.1%}  中位 {x.median():>+6.1%}  "
            f"(b)較好 {(x > 0).mean():>4.0%}／相同 {(x == 0).mean():>4.0%}／較差 {(x < 0).mean():>4.0%}  "
            f"第10百分位 {q10:>+6.1%}  最差一成平均 {worst:>+6.1%}  最好一成平均 {x[x >= x.quantile(0.9)].mean():>+6.1%}")

for freq, name in (("Y", "每年第一個交易日建倉"), ("Q", "每季第一個交易日建倉")):
    df, sk, nh = simulate(freq)
    lots = df.groupby(["sym", "entry"]).ngroups
    print(f"\n================ {name} ================")
    print(f"資料 {cal[0].date()} → {cal[-1].date()}；建倉 2019→；有級距事件的 lot {lots} 個（{df.sym.nunique()} 檔）；級距事件 {len(df)}；"
          f"尾端未走完剔除 {sk}；建倉日歷史不足 200 日跳過 {nh}")
    print("[全部事件：(b) 成交價 ÷ (a) 成交價 − 1]")
    print(line("全部級距", df))
    for tier, _ in TIERS:
        print(line(f"+{tier:.0%} 級", df[df.tier == tier]))
    de = df[df.why != "未延後"]
    print("[只看有延後的事件]")
    print(line("全部級距", de))
    for tier, _ in TIERS:
        print(line(f"+{tier:.0%} 級", de[de.tier == tier]))
    print(f"   延後天數：平均 {de.days.mean():.0f}、中位 {de.days.median():.0f}；結束原因 跌破SMA50 {(de.why == '跌破SMA50').mean():.0%}／滿120日 {(de.why == '滿120日').mean():.0%}")
    print(f"   滿 120 日才賣的 {int((de.why == '滿120日').sum())} 筆平均 {de[de.why == '滿120日']['diff'].mean():+.1%}；跌破 SMA50 才賣的 {int((de.why == '跌破SMA50').sum())} 筆平均 {de[de.why == '跌破SMA50']['diff'].mean():+.1%}、中位 {de[de.why == '跌破SMA50']['diff'].median():+.1%}、較好比例 {(de[de.why == '跌破SMA50']['diff'] > 0).mean():.0%}")
    print(f"[隔日收盤成交版（t 判定 → t+1 執行）] 有延後事件 平均 {de.diff_next.mean():+.1%}、中位 {de.diff_next.median():+.1%}、(b)較好 {(de.diff_next > 0).mean():.0%}")
    print("[公平對照：同一段延後期間把 (a) 賣出的錢放指數]（只看有延後的事件）")
    print(f"   個股延後 平均 {de['diff'].mean():+.1%}／中位 {de['diff'].median():+.1%}；同期 SPY 平均 {de.spy.mean():+.1%}／中位 {de.spy.median():+.1%}；同期 SMH 平均 {de.smh.mean():+.1%}／中位 {de.smh.median():+.1%}")
    for b in ("spy", "smh"):
        x = de["diff"] - de[b]
        print(f"   (b) − {b.upper()}：平均 {x.mean():+.1%}、中位 {x.median():+.1%}、為正比例 {(x > 0).mean():.0%}、事件層 t={tcl(x):+.2f}（事件相關、高估）")
    bysym = de.groupby("sym").agg(n=("diff", "size"), diff=("diff", "mean"), x_spy=("diff", lambda s: (s - de.loc[s.index, "spy"]).mean()),
                                  x_smh=("diff", lambda s: (s - de.loc[s.index, "smh"]).mean()))
    print(f"[以股票為單位（{len(bysym)} 檔，每檔先取平均）] 延後價差 平均 {bysym['diff'].mean():+.1%}、中位 {bysym['diff'].median():+.1%}、為正 {(bysym['diff'] > 0).sum()}/{len(bysym)} 檔、t={tcl(bysym['diff']):+.2f}；"
          f"扣 SPY 平均 {bysym.x_spy.mean():+.1%}（t={tcl(bysym.x_spy):+.2f}，為正 {(bysym.x_spy > 0).sum()} 檔）；扣 SMH 平均 {bysym.x_smh.mean():+.1%}（t={tcl(bysym.x_smh):+.2f}，為正 {(bysym.x_smh > 0).sum()} 檔）")
    top = bysym.sort_values("diff", ascending=False)
    print("   最好 5 檔：" + "、".join(f"{s} {r['diff']:+.0%}(n={int(r['n'])})" for s, r in top.head(5).iterrows())
          + "；最差 5 檔：" + "、".join(f"{s} {r['diff']:+.0%}(n={int(r['n'])})" for s, r in top.tail(5).iterrows()))
    ex = de[~de.sym.isin(list(top.head(3).index))]
    print(f"   拿掉最好 3 檔後（有延後事件 n={len(ex)}）：平均 {ex['diff'].mean():+.1%}、中位 {ex['diff'].median():+.1%}、較好 {(ex['diff'] > 0).mean():.0%}、扣 SMH 平均 {(ex['diff'] - ex.smh).mean():+.1%}")
    print("[按觸發年份（有延後的事件）]")
    for y, g in de.groupby(de.trig.dt.year):
        print(f"   {y}  n={len(g):>3}  平均 {g['diff'].mean():>+6.1%}  中位 {g['diff'].median():>+6.1%}  較好 {(g['diff'] > 0).mean():>4.0%}  同期 SPY {g.spy.mean():>+6.1%}  SMH {g.smh.mean():>+6.1%}  扣 SMH {(g['diff'] - g.smh).mean():>+6.1%}")
    lot = df.groupby(["sym", "entry"]).lot_gain.sum()
    print(f"[每個 lot 的合計影響（Σ 級距比例 × 價差 ÷ 建倉價）] 平均 {lot.mean():+.1%} 的建倉成本、中位 {lot.median():+.1%}、為正 {(lot > 0).mean():.0%}、第10百分位 {lot.quantile(0.1):+.1%}")
