# backtests/ — 一次性回測腳本（可重跑）

研究用，不進 briefing / trade-review 管線。每支腳本 docstring 帶首跑結論；`data/` 為下載快取（gitignore）。

| 腳本 | 問題 | 首跑結論（2026-09-05） |
|---|---|---|
| `etf_copy_strategies.py` | 13F 抄單（GURU/GVIP）、國會抄單（NANC/KRUZ）ETF 實盤能不能贏大盤 | 四支年化 α t 值全 <2；GURU 14 年 α −2.7%/yr；NANC 對 QQQ β 0.79、α +1.1%（t 0.4）= 稀釋版 QQQ |
| `pelosi_ptr_event_study.py` | 從官方 PTR 申報日抄 Pelosi 買賣，21/63/126/252 天超額 vs SPY/QQQ | 申報延遲中位 23 天吃光短期資訊（交易日 21d +6.3% → 申報日 +0.3%）；126d 均值 +5.7% 但中位 −0.4%、勝率 49%，靠一筆 NVDA LEAPS；賣單反指標；全部 t <2 |

裁決：13F / 國會交易**不加入訊號層**（`feedback/skill-vs-luck.md`「不做」清單）。名單與現有 AI/半導體持倉重疊近 100%，邊際資訊量趨近零；若要當 L2 idea 源，每季手動翻集中型長線基金的**新建倉**即可，不建管線。

依賴：`yfinance`、`pandas`、`pypdf`（`pip install --user pypdf`）。
