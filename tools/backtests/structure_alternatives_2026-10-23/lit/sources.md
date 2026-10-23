# 文獻與指數基準率：來源清單（2026-10-23）
## Q1 Cboe 指數
- Cboe BXM factsheet (as of 2026-09-30, pdfs/bxm_factsheet.txt): 1986-06-20 起 BXM 年化 8.6% / 波動 10.6% / MDD -35.8% / beta 0.62 / Sharpe 0.56；SPTR 11.2% / 15.2% / -50.9% / Sharpe 0.56。年度 2011–2025 表。1Y 18.2%。
- Cboe BXMD factsheet (同上, pdfs/BXMD_factsheet.txt): 10.6% / 12.9% / -42.7% / beta 0.8 / Sharpe 0.61；1Y 16.7%, 3Y 18.1%, 5Y 10.8%, 10Y 10.8%。
- Cboe PUT factsheet (同上, pdfs/put_factsheet.txt): 2007-01-03 起 7.2% / 10.7% / -32.7% / beta 0.6 / Sharpe 0.52；SPTR 11.0%/15.4%/-50.9%/0.61。1Y 15.2% 3Y 13.9% 5Y 9.8% 10Y 8.5%。2025 全年 9.2% vs 17.9%。
- Black & Szado 2016 (Cboe 委託, pdfs/black_szado_2016.txt): 1986-06→2015-12 BXMD 10.66%、PUT 10.13% 年化；PUT 年化標差 10.16%。
- cxoadvisory PPUT 頁 (1986-07→2016-05): PPUT 超額報酬 2.5%/yr vs SPTR 5.8%；波動 13.5%、beta 0.74、alpha -1.8%/yr。https://www.cxoadvisory.com/equity-options/do-protective-equity-index-puts-work-well/
- Cboe 2023 (WebSearch 摘要 cboe.com VPD/VPN 貼文): 1986-07→2023-06 PPUT MDD -38.9% vs S&P -51.0%。
- Cboe 2021 benchmark series (PPUT/CLL/CLLZ): 35 年 beta <0.75；S&P 35 次單月 ≤-6% vs PPUT 18 次。https://www.cboe.com/insights/posts/benchmark-indices-series-hedging-downside-exposure-with-pput-cll-and-cllz-indices
- Israelov & Klein 2016 via cxoadvisory (?p=27965): CLL 1986-07→2014-12 超額 3.2%/yr vs S&P 7.3%；波動 10.7% vs 15.7%；Sharpe 0.30 vs 0.47；beta 0.62。
- Israelov & Nielsen 2015 "Still Not Cheap" via ETF.com Swedroe: 2006-03→2014-06 買 put 拉低報酬 2.5pp/yr，Sharpe 0.37→0.21；最低 VIX 十分位實現 VRP 仍 +2.5。
## Q2 VRP
- Driessen-Maenhout-Vilkov 2009 JF (OptionMetrics 摘要): S&P100 隱含 24.7% vs 實現 20.8%（≈3.9 vol pts）；個股選擇權無顯著波動風險溢酬。
- Carr & Wu 2009 RFS: 5 指數 + 35 個股；指數 VRP 顯著負；個股 VRP 負但較小/較不顯著（二手）。
- Hollstein & Wese Simen 2020 JoE: 修正後個股亦有顯著負 VSP（二手摘要）。
- 自算 bench_stats.py: 2010-01→2026-10 VIX − 後 21 日 SPY 實現波動 均值 3.78 pts、中位 4.59、84.1% 日子為正（VIX 均 18.4 vs RV 14.65）。
## Q3 做空
- Boehmer-Jones-Zhang 2008 JF: 重空股 20 日風險調整落後 1.16%（年化 15.6%）；機構非程式空單 1.43%/月。
- Kelley-Tetlock 2017 RFS: 模仿散戶空單組合 年化風險調整 9%。
- D'Avolio 2002 JFE: 91% 股票借券費 <1%/yr（GC 均 17bp）；specials 均 4.3%/yr；最高 79%，>35% 僅 8 家。
- Schultz 2024 JFQA (evidenceinvestor 摘要): 2006-2019 借券費 中位 37.5bp、均 2.67%、95 分位 11.0%；利用率 ≥90% 股票次月超額 -1.29%、軋空成本 0.87–1.04% 吃掉 >2/3；最高費+最高利用率十分位 -2.67%/月；利用率 ≥90% 約每 11 天一次全市場軋空。
- Melvin Capital 2021-01 -53%（WSJ/Bloomberg/CNBC）。
- Daniel-Moskowitz Table 1: 輸家十分位 β 1.61、超額 -2.5%/yr、σ 36.5%。
## Q4 多空基金 / 配對
- HFR Media Reference Guide 2024-09-09 (pdfs/hfr_guide_2024.txt) 年度表：EH 2013 14.28, 2014 1.81, 2015 -0.97, 2016 5.47, 2017 13.29, 2018 -7.14, 2019 13.71, 2020 17.89, 2021 11.67, 2022 -10.13, 2023 11.37；EMN 6.46, 3.06, 4.27, 2.23, 4.88, -0.98, 2.33, -0.11, 7.05, 1.21, 5.97。2024 EH +12.3 (HFR 年終)；2025 EH +17.05 (Integrity Research)；2010 EH +10.4、2011 -8.0 (hedgeweek)。
- hfri_calc.py: 2013-2023 EH CAGR 6.09% / 年度標差 9.38%；EMN 3.28% / 2.67%；SPY 13.63% / 16.17%；QQQ 19.25% / 25.06%。
- UBS HF bulletin 2025-04: EH 10Y 年化 5.81%、10Y 波動 8.76% vs MSCI World 9.34% / 15.05%。
- AIMA 2014: EH 20 年 Sharpe 1.09 vs S&P 0.45；波動 9.18% vs 15.21%。
- Do & Faff 2010 FAJ: 前 20 對 月超額 0.86% (1962-88) → 0.37% (1989-2002) → 0.24% (2003-09)；Rad-Low-Faff 2015 計入買賣價差後 1980s 後不為正。
## Q5 動能多空
- Kenneth French Mom factor (ff/F-F_Momentum_Factor.CSV, mom_stats.py): 1927-01→2026-08 7.4%/yr、vol 16.3%、Sharpe 0.45、MDD -78.4%、月偏態 -3.02；2010→2026-08 3.0%/yr、vol 12.8%、Sharpe 0.23、MDD -25.4%；2009 全年 -52.8%、2009-03→05 -49.4%、1932-07/08 -74.2%；2025 -2.2%、2026 YTD +3.9%。
- Daniel & Moskowitz NBER w20439 (pdfs/dm_momcrash.txt): 1927-2013 WML 超額 17.9%/yr、σ 30%、Sharpe 0.60（文中 0.71）、月偏態 -4.70、β -0.58；最差月 1932-08 -74.36%、1932-07 -60.98%、2009-04 -45.52%、2009-03 -42.28%；2009-03→05 輸家 +163% vs 贏家 +8%；動態策略 Sharpe 1.18。
## Q6 散戶選擇權
- Bauer-Cosemans-Eichholtz 2009 JBF (cxoadvisory 摘要): 68,146 荷蘭投資人 2000-01→2006-03；選擇權交易者風險調整落後 1%/月（毛）、2.75%/月（淨）；動機賭博娛樂。
- de Silva-Smith-So 2025 RoF: 財報前買選擇權平均虧 5–9%，高預期波動 10–14%。
- Bryzgalova-Pavlova-Sikorskaya 2023 JF: 散戶偏好週選、均買賣價差 12.6%，平均虧損。
- SEBI FY2025-26: 87.7% 個人衍生品交易者虧損、選擇權占 92% 虧損。
## Q7 2026 YTD
- yfinance ^PUT: 2025-12-31 3336.14 → 2026-10-22 3698.47 = +10.86%；^SP500TR +12.98%；^GSPC 價格 +11.95%。
- BXM：Barchart 7 月快照 +167.95 (+7.30%) → 2025 年底 2300.68；10/22 2557.03 (yfinance) → YTD +11.14%（推導）。First Trust 3/24/26：至 3/20 S&P -4.70% vs BXM -1.87%。
- Cboe Index Insights 2026-09: 9 月 SPX -0.45%、BXM +0.9%、PUT +1.4%。
- PPUT/CLL 2026 YTD 未取得（Cboe dashboard 動態載入、factsheet 403）。
