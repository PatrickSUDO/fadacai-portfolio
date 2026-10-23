# backtests/ — 一次性回測腳本（可重跑）

研究用，不進 briefing / trade-review 管線。每支腳本 docstring 帶首跑結論；`data/` 為下載快取（gitignore）。

| 腳本 | 問題 | 首跑結論（2026-09-05） |
|---|---|---|
| `etf_copy_strategies.py` | 13F 抄單（GURU/GVIP）、國會抄單（NANC/KRUZ）ETF 實盤能不能贏大盤 | 四支年化 α t 值全 <2；GURU 14 年 α −2.7%/yr；NANC 對 QQQ β 0.79、α +1.1%（t 0.4）= 稀釋版 QQQ |
| `pelosi_ptr_event_study.py` | 從官方 PTR 申報日抄 Pelosi 買賣，21/63/126/252 天超額 vs SPY/QQQ | 申報延遲中位 23 天吃光短期資訊（交易日 21d +6.3% → 申報日 +0.3%）；126d 均值 +5.7% 但中位 −0.4%、勝率 49%，靠一筆 NVDA LEAPS；賣單反指標；全部 t <2 |

裁決：13F / 國會交易**不加入訊號層**（`feedback/skill-vs-luck.md`「不做」清單）。名單與現有 AI/半導體持倉重疊近 100%，邊際資訊量趨近零；若要當 L2 idea 源，每季手動翻集中型長線基金的**新建倉**即可，不建管線。

依賴：`yfinance`、`pandas`、`pypdf`（`pip install --user pypdf`）。

## 2026-10-23 選擇權多空／配對策略評估（`options_long_short_2026-10-23/`）

用戶問「加選擇權 based 多空策略會不會比較好、做空勝率會更高嗎、空個股多指數對 Sharpe/PF 如何」。五路證據 + 12 條主張 × 3 反駁者，報告在 `research/options-long-short-evaluation-2026-10-23.md`。

| 子目錄 | 問題 | 首跑結論 |
|---|---|---|
| `short_alpha/` | 帳戶 2026 賣出反手做空、83 檔宇宙 R36 型弱勢訊號做空（2015→），直接空與空個股多板塊 ETF 配對 | 配對 60 日勝率約五成（帳戶 54.8%、宇宙去漂移 50.6%），期望值為負、配對空方 Sharpe 九格全負、PF 0.56–0.79；右偏尾巴是宇宙屬性非訊號特徵 |
| `overlay_sim/` | 空指數 β 對沖 / 保護性 put / 賣權價差 / 空最弱 1/5 配對 / 波動目標，套帳戶標記（2026-06→10）與 SMH 2012→ | 實價成本下沒有覆蓋同時提高 Sharpe 與 PF；保護 put 0.93→0.75；賣權價差 0.91 只在 IV 26% 成立；空最弱 1/5 腿年化 −31%；波動目標 0.97 在噪音內 |
| `option_costs/` | Firstrade 鏈即時權利金、VRP、價差、對沖總帳 | SMH 10% 價外 60 天 put 年化 16.6%（10/19 11.5%）；全額對沖 $32k/年 = 總值 13.2%；個股 IV 1.2–2.1× SMH、價差 7–58% |
| `internal_audit/` | 帳本選擇權結構合成分組 | 看空結構 1/7 勝 −$3,981；<15 天買方 PF 0.11；CC PF 2.37 但 8 勝全在標的下跌窗 |

裁決：**不加做空腿、不加配對 sleeve、不加常態指數 put**；條件式半額賣權價差只在 SMH IV ≤ 28% 時由用戶裁決。副產品：`account_metrics.py` 年化波動 17.3% 錯（1/1→6/1 空窗攤進分母），重算約 33–39%，Sharpe 約 0.8 非 1.1。

## 2026-10-23 替代結構評估：槓桿 ETF／其他 ETF／選擇權結構（`structure_alternatives_2026-10-23/`）

用戶問「引進怎樣的選擇權或各種方式對我更好，也考慮槓桿 ETF 或其他 ETF」（前一句「那價差策略呢」）。五路證據 + 14 個候選 × 3 反駁者，報告在 `research/structure-alternatives-evaluation-2026-10-23.md`。

| 子目錄 | 問題 | 首跑結論 |
|---|---|---|
| `lev_etf/` | SOXL/USD/TQQQ/QLD/SSO/UPRO/TECL 單獨、β 配對（1/k 槓桿 ETF + T-bill）、停泊格、衛星、R15 互動 | 配對恆等於 1× 減成本（對自身指數每年 −2 到 −3.5pp），封頂與複製 β 互斥；衛星/停泊格是用更深 MDD 買 CAGR，Sharpe 不升；R15 觸發 17→20–21 次 |
| `other_etf/` | 40 檔 ETF 2015→/2020→ 對 QQQ/SMH 的 α/β、停泊格替換、R36 基準格、收租/緩衝 | 兩段都贏 QQQ 的只有 SMH/SOXX/VGT/XLK（全是半導體 β）；停泊格換 SPMO/QUAL/RSP 在噪音內；IGV 2020→ 對 QQQ α −4.7%；JEPQ/QYLD 稅前已輸、NRA 預扣再拖 3–4pp |
| `opt_structures/` | Firstrade 鏈實價：LEAPS 股票替代、credit/debit 價差、領口、CSP、PMCC | LEAPS 時間價值 = 融資成分 + 一張 −20% put（SMH/QQQ 每年 2–5%，含價差與 roll 約 6–7%），無折價；16 組 credit spread 在隱含機率下 EV ≤0；CSP 一口 = 帳戶 7–25%，與 R30 $3k 不相容 |
| `portfolio_fit/` | 候選套在 P0（52% SMH + 33% IGV + 15% SPY）2012→ | 只有波動目標與 IGV→QQQ 疊加在「CAGR ≥ −2pp 且 MDD 淺 ≥5pp」過線，但反駁者指出套到帳戶實際波動 32.7% 後 CAGR 代價 −3 到 −5pp、放 VOO 版好處大半消失、QQQ 會加重半導體集中 |
| `lit/` | 槓桿 ETF 衰減公式與實證、Frazzini-Pedersen 內嵌槓桿、動能 ETF 實盤、收租 ETF、NRA 稅務（含遺產稅 $60k 門檻）、PUT 指數 | 內嵌槓桿長期是付費買曝險；2× 只在漂移 > 1.5σ² 時贏 1×；PPUT/CLL Sharpe 低於 S&P；PUT 指數 Sharpe 持平 |

裁決：**不加槓桿 ETF（三種用法）、不加 credit/debit 價差、不加領口、不加 CSP 進場、不加收租 ETF、停泊維持 VOO、軟體基準格維持 IGV**；LEAPS 股票替代列為用戶裁決的「付 6–7%/年買 −20% 地板」選項，不是 Sharpe 改善。14 個候選中「建議採用／條件式」五個全被反駁，「不採用」九個中八個存活。
