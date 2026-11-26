#!/usr/bin/env python3
"""Write summary.md (Traditional Chinese) from the CSV outputs of run.py."""
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D

o = D.OUT_DIR
c = pd.read_csv(os.path.join(o, "cells.csv")); w = pd.read_csv(os.path.join(o, "windows.csv"))
b = pd.read_csv(os.path.join(o, "benchmarks.csv")); n = pd.read_csv(os.path.join(o, "null.csv"))
v = json.load(open(os.path.join(o, "verdict.json"))); sc = json.load(open(os.path.join(o, "selfcheck.json")))
ZH = {"keep": "留強", "cull": "汰弱", "stay": "續抱"}
LB = {"L126": "126日", "L252": "252日", "L252s21": "252日跳21"}
pc = lambda x: f"{x*100:.1f}%"
pp = lambda x: f"{x*100:+.1f}"
def lab(r): return f"{r['list']}｜{LB[r['lookback']]}｜H{r['H']}｜{ZH[r['form']]}"
def num(x): return [int(t[0]) for t in x.split(";") if t]

L = []
A = L.append
nom = v["nominated"]
two = c[(c.ex_qqq > 0)]
A("# ETF 汰弱留強（keep-the-strong）回測結果")
A("")
A("日期：2026-11-19。對應預註冊文件：`research/etf-keep-strong-study-2026-11-19.md`。資料到 2025-12-31 為止。這是描述性結果，不是上線建議。")
A("")
A("## 0. 結論（先讀這段）")
A("")
A(f"- 36 格裡通過及格線的有 {len(nom)} 格，所以沒有任何提名。")
A(f"- 只有 {len(two)} 格的年化報酬贏過 QQQ，而且都是 G7 名單的「留強」；它們在某個窗輸給 QQQ 太多，也沒通過隨機對照。")
A("- 36 格全部輸給 SMH 買進持有，輸的幅度是每年 4 到 7 個百分點。")
A("- G3 的 18 格全部輸給三檔平均分配。G7 的 18 格比七檔平均分配多賺的，最多約 2 個百分點，也過不了隨機對照。")
A("- 這跟事前預期一致：輸 SMH，跟 QQQ 與平均分配打平。")
A("")
A("名詞：**年化報酬（CAGR）** = 每年複利平均賺多少。**pp** = 百分點。**MDD** = 最大回撤，從高點跌到低點的最大幅度。**IR** = 比 QQQ 多賺的部分除以它的波動。**BH q 值** = 一次測 36 格時，扣掉「多試幾次總會有一格好看」的運氣後的顯著程度。")
A("")
A("## 1. 做了什麼")
A("")
m3, m7 = v["meta"]["G3"], v["meta"]["G7"]
A(f"- G3 = QQQ、SMH、IGV。G7 = QQQ、SMH、IGV、XLK、XLY、VOX、IBB。七檔都有資料，沒有剔除任何一檔。")
A(f"- 規則完全照預註冊：回看 126 日、252 日、252 日跳過最近 21 日；每 63 或 126 個交易日檢查；三種形式（留強、汰弱、續抱）。")
A("- 檢查日收盤算訊號，隔一個交易日收盤成交，每邊 5bp（0.05%），永遠滿倉。")
A("- 起始日敏感度：每個檢查週期用 H 除以 21 批、各差 21 個交易日的分批，把每天的報酬平均。")
A(f"- G3 評估期從 {m3['eval_start']} 到 {m3['eval_end']}。G7 從 {m7['eval_start']} 到 {m7['eval_end']}（VOX 2004-09 才上市，所以較晚）。")
A("- 評估期比「起算日」晚約 107 個交易日，因為要等所有分批都已持倉才開始算（見第 8 節）。")
A("")
A("## 2. 買進持有與平均分配（同期）")
A("")
A("| 名單 | 對象 | 年化 | MDD | 波動 |")
A("|---|---|---|---|---|")
for _, r in b[b.window == "FULL"].iterrows():
    nm = {"EW_H63": "平均分配（每63日拉回）", "EW_H126": "平均分配（每126日拉回）"}.get(r["name"], r["name"] + " 買進持有")
    A(f"| {r['list']} | {nm} | {pc(r['cagr'])} | {pc(r['mdd'])} | {pc(r['vol'])} |")
A("")
A("VOO 在 2010-09 上市前，用 SPY 的報酬接上。G3 與 G7 起點不同，所以同一檔的數字不同。")
A("")
A("## 3. 36 格總表")
A("")
A("欄位「對 QQQ／SMH／平均」是年化差（pp）。「SMH 占比」是持有 SMH 的時間比例。「未過」是沒過的及格線編號（1 年化贏 QQQ 與平均；2 三窗各自不輸 QQQ 超過 0.5pp；3 IR 至少 0.30；4 BH q 小於 0.10；5 成本 20bp 仍贏 QQQ；6 回撤不深過 QQQ 5pp）。")
A("")
A("| 格（名單｜回看｜H｜形式） | 年化 | 對QQQ | 對SMH | 對平均 | MDD | 換檔/年 | SMH占比 | p | q | 結果 | 未過 |")
A("|---|---|---|---|---|---|---|---|---|---|---|---|")
for _, r in c.iterrows():
    A(f"| {lab(r)} | {pc(r.cagr)} | {pp(r.ex_qqq)} | {pp(r.ex_smh)} | {pp(r.ex_ew)} | {pc(r.mdd)} | {r.switches_per_year:.1f} | {r.smh_time_share*100:.0f}% | {r.null_p:.3f} | {r.bh_q:.2f} | {'過' if r['pass'] else '不過'} | {','.join(map(str, num(r.failing_lines))) or '-'} |")
A("")
A("## 4. 隨機對照組")
A("")
A("做法：同樣的檢查日、同樣的持有檔數，但隨機挑；續抱形式用同樣的換檔次數。每格抽 1,000 次，種子固定。")
A(f"36 格裡最小的 p 是 {c.null_p.min():.3f}，BH 校正後最小的 q 是 {c.bh_q.min():.2f}，所以沒有一格過 0.10。")
A(f"隨機組年化的平均，比同名單平均分配低 {abs(n.null_mean_minus_ew.mean())*100:.2f}pp（36 格平均），兩者很接近。")
A("")
A("## 5. 三個窗，各形式的中位數（對 QQQ 的年化差，pp）")
A("")
w2 = w.copy(); w2["form"] = w2.cell.str.split("_").str[-1]
t = w2.groupby(["list", "window", "form"]).ex_qqq.median().unstack()
A("| 名單 | 窗 | 留強 | 汰弱 | 續抱 |")
A("|---|---|---|---|---|")
for (lst, win), r in t.iterrows():
    A(f"| {lst} | {win.replace('W','').replace('_','–')} | {pp(r['keep'])} | {pp(r['cull'])} | {pp(r['stay'])} |")
A("")
A("同一個窗裡，QQQ 與 SMH 的年化見 `benchmarks.csv`。三種形式在 2005–2012 都輸 QQQ，在 2013–2019 大多贏，在 2020–2025 看名單而定。")
A("")
A("## 6. 起始日敏感度（各批單獨跑）")
A("")
sp = c.tranche_cagr_max - c.tranche_cagr_min
A(f"各格最高與最低批的年化差，中位數是 {sp.median()*100:.1f}pp，最大是 {sp.max()*100:.1f}pp（{lab(c.loc[sp.idxmax()])}）。")
A("所以同一個規則換個起始日，年化可以差好幾個百分點；單一路徑的結果不能當成穩定的數字。各格的最低與最高見 `cells.csv` 的 tranche_cagr_min、tranche_cagr_max。")
A("")
A("## 7. 最近 18 個月（2024-07-01 到 2025-12-31，累積報酬）")
A("")
l = c.iloc[0]
A(f"同期 QQQ 累積 {pc(l.l18_qqq)}，SMH 累積 {pc(l.l18_smh)}。")
A(f"36 格裡贏 QQQ 的有 {int((c.l18_ex_qqq>0).sum())} 格，贏 SMH 的有 {int((c.l18_ret>l.l18_smh).sum())} 格。")
A("")
A("| 格 | 累積 | 對 QQQ（pp） |")
A("|---|---|---|")
for _, r in c.iterrows():
    A(f"| {lab(r)} | {pc(r.l18_ret)} | {pp(r.l18_ex_qqq)} |")
A("")
A("## 8. 檢查與限制")
A("")
a = sc["A_study_data"]; bb = sc["B_diagnostic_old_cache_to_2026-11-09"]
A("- 核對一：2005-01-03 到 2025-12-31，本研究 QQQ、SMH、SPY 年化是 " + f"{a['2005-01-03->2025-12-31']['QQQ']}%、{a['2005-01-03->2025-12-31']['SMH']}%、{a['2005-01-03->2025-12-31']['SPY']}%，舊報告是 14.8%、19.8%、10.6%，差距在 0.1pp 以內。")
A("- 核對二（只作診斷、不進結果）：用舊腳本自己的價格快取算到 2026-11-09，2010-01-04 起 QQQ、SMH、SPY 是 " + f"{bb['2010-01-04->2026-11-09']['QQQ']}%、{bb['2010-01-04->2026-11-09']['SMH']}%、{bb['2010-01-04->2026-11-09']['SPY']}%，舊腳本印的是 18.4%、24.7%、14.0%（VOO）。")
A("- 同樣方法 2002-08-01 起是 " + f"{bb['2002-08-01->2026-11-09']['QQQ']}%、{bb['2002-08-01->2026-11-09']['SMH']}%、{bb['2002-08-01->2026-11-09']['SPY']}%，舊腳本是 15.6%、16.8%、11.1%；差距 0.3pp 以內，原因未查明，可能是兩次抓到的調整價格版本不同。")
A("- 隨機對照組平均接近平均分配，符合預期。")
A("- 評估期起點：預註冊的起算日是所有代號都有滿 273 個交易日的第一天；為了讓所有分批都已持倉，我把評估起點再往後延 107 個交易日，所有策略與對照用同一起點。")
A("- 成本：換檔時對買進與賣出的金額各收 5bp；汰弱形式每次檢查把權重拉回等權，這個再平衡的金額也收費。")
A("- 風險：只有 21 年、一段 Nasdaq 與半導體大贏的歷史；名單是依上市時間挑，但 QQQ、SMH 本身就是事後的贏家。")
A("")
open(os.path.join(o, "summary.md"), "w").write("\n".join(L) + "\n")
