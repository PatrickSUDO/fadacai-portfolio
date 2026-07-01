---
name: portfolio-review
description: Fetch live brokerage positions and generate a comprehensive portfolio report with sector allocation, P&L analysis, options summary, and risk assessment. Use when user asks for portfolio review.
user_invocable: true
model: claude-opus-4-8
---

# Portfolio Review

Generate a comprehensive portfolio report from the user's live brokerage positions (via the `firstrade-server` MCP).

## Step 0: 配置同步 & 倉位偵測

執行 CLAUDE.md 的 Step 0 統一規範（0a → 0b → 0c → 0d → **0e**）。
- 讀 `plan.md` + `feedback/*.md`（必做）；在後續分析中引用板塊目標與策略佇列
- 呼叫 `get_account_position` 取即時持倉
- 今日 journal 不存在 → 執行 gap-fill + 變動偵測 + 自動建立 journal
- **0e 第一性原理紀律**：在「下一步建議」之前必須完成「組合層級 thesis / 證偽條件 / 機率分布」三題（見 CLAUDE.md 0e）

## Step 0.5: Macro + Earnings + Fundamentals Cache Load

讀以下四份 cache（由各預載腳本維護）：
- `briefing-out/cache/macro-snapshot.json` — 供 Step 0e 與 probability-honesty-checker Step 1i
- `briefing-out/cache/earnings-history.json` — 供 Section F Key Alerts、Section G 個股 thesis、及 probability-honesty-checker Step 1d base rate
- `briefing-out/cache/earnings-dates.json` — 供 Section F earnings window 警示
- `briefing-out/cache/fundamentals-snapshot.json`（TTL 24h，`tools/fetch_fundamentals.py` 預載）— 供 Section G3.5 三錨點估值、probability-honesty-checker Step 1d/1h

判定 fundamentals cache：
- `status == "ok"` 且 mtime < 30h → **使用**（Section G3.5 三錨點計算直接取 highlights）
- `status == "skipped"` / mtime > 30h / 缺失 → 標 `⚠️ Fundamentals cache stale/missing`，派 Agent 即時補抓（同 briefing Deep 模式）：
  ```
  Agent(subagent_type="data-collector"):
    呼叫 mcp__eodhd-mcp__get_fundamentals_snapshot 對所有 >3% 持倉 (TICKER.US)
    回傳 dict {ticker: {snapshot:{...}, base_rate:{...}}}
  ```
- `pe_ratio == 0.0 / null` → 丟棄 A1 錨；`peg_ratio == 0.0 / null` → 丟棄 A2 錨；不猜測

若 macro `status == "skipped"` → Section K 第一性檢查標記 `Macro: unavailable`，probability-honesty-checker 1i 填 unavailable。
若 earnings cache 過期 > 36h → 加註 `⚠️ cache stale (X h)`。
若 cache 缺某 ticker → Section F 該 ticker earnings 列 `(unavailable)`，prompt 提示手動 `python3 tools/earnings_history.py --force`。

---

## Step 0.6: Thesis Ledger 驗收 & 逾期掃描

與 briefing 共用同一套引擎（`tools/thesis_ledger.py`，帳本 `research/thesis-ledger.json`）。portfolio-review 也自動驗收，確保未跑 briefing 的日子不漏驗收。

```
python3 tools/thesis_ledger.py due      # 取到期清單 + 自動 expire sweep
```
對每筆 `due`：讀 `trigger.metric` → 用 MCP 抓實際數字 → 對照 `thesis`+`falsification` 判 passed/failed/partial → `resolve --next-action`；抓不到新數 → `reschedule` 維持 pending，不猜 verdict。流程細節與規則同 briefing Step 0.7。

在 **Section F Key Alerts 前**輸出「📋 thesis 驗收」表：

```
## 📋 thesis 驗收
| thesis | 命題 | 實際 | verdict | 公允價 before→after | 價格影響 | → actionable |
|--------|------|------|---------|---------------------|---------|-------------|
```

`公允價 before→after` 與 `價格影響` 欄：有 resolve 且帶 impact 旗標時填入，reschedule 留空。D2 三桶分解（passed/failed/partial）同 briefing Step 0.7 邏輯：
- **passed** → D1 三錨點用新數字重算 `fair_value_after`；`price_impact_pct = (after−before)/before`
- **failed** → 同上但用惡化輸入（成長減速/砍 guide）
- **partial** → `impact_decomp = "thesis +X%(基本面)/multiple −Z%(re-rate)=net −W%"`

並列出 expired 歸檔清單。驗收結果（含公允價影響）直接餵「下一步建議」。

---

## Workflow

1. **Fetch live positions**
   - Call `mcp__firstrade-server__get_account_position` to get real-time positions
   - Also call `mcp__firstrade-server__get_account_balance` for total account value
   - Parse the Stocks section and Options section separately
   - Extract: Symbol, Quantity, Last Price, Market Value, Unit Cost, Total Cost, Gain/Loss($), Gain/Loss(%)

2. **Sector Classification**
   Classify each ticker into a sector using this two-step approach:

   **Step 1: Use your knowledge of each company** to assign it to ONE of these sectors:
   - **AI/Semiconductor** — GPU, memory, chip design, semiconductor equipment
   - **AI Infrastructure** — optical networking, power/cooling, PCB/substrates, networking equipment
   - **Large Tech** — mega-cap platform companies (FAANG-level)
   - **AI Software/Platform** — AI-focused software, data analytics, autonomous systems
   - **SaaS/Enterprise Software** — cloud software, dev tools, enterprise apps
   - **Infrastructure/Construction** — electrical, utility, data center construction
   - **Aerospace/Defense** — defense contractors, aerospace materials, military tech
   - **Precious Metals/Mining** — gold, silver miners and royalty companies
   - **Nuclear/Uranium** — uranium miners, nuclear energy
   - **Transport/Logistics** — freight, shipping, logistics
   - **Healthcare/Biotech** — pharma, biotech, medical devices
   - **Energy** — oil, gas, traditional energy
   - **Real Assets** — land rights, water rights, mineral rights, REITs
   - **Materials/Metals** — aluminum, steel, rare earth, specialty metals
   - **Other** — anything that doesn't fit above

   **Step 2: For any ticker you're unsure about**, use `mcp__yfinance-advanced__get_stock_info` to check its `sector`, `industry`, and `longBusinessSummary` fields to classify accurately.

   **Grouping rule**: Combine sectors with < 3% allocation into an "Other/Small" bucket to keep the table clean.

3. **Generate Report** with these sections:

### A. Portfolio Summary
```
Total Stock Value: $XXX,XXX
Total Options Value: $XX,XXX
Total Portfolio: $XXX,XXX
Day Change: +/- $X,XXX (+/- X.XX%)
Total Gain/Loss: +/- $X,XXX (+/- X.XX%)
Number of Positions: XX stocks + XX options
```

### B. Sector Allocation Table
| Sector | Market Value | % of Portfolio | Holdings |
Sort by percentage descending. Flag any sector > 20% as overweight.

### C. Top 5 Winners & Losers (by Gain/Loss %)
Show the best and worst performing positions.

### D. Position Sizing & 分桶對照（Portfolio as a Business）

**D1. Size flags：**
- Over 7% of portfolio → 預警（too concentrated）
- **Over 10% → 🔴 紅線強制標記**（信念桶也不豁免，per `feedback/position-concentration.md`）
- Under 1.5% of portfolio (too small to matter)

**D2. 分桶對照表（roster 權威來源 = `plan.md`「組合架構 v2」）：**

每個主動倉位標注所屬桶別，與 plan.md roster 比對：

| 標的 | 權重 | β | 桶別（🔵信念/🟢認列） | 桶規則狀態 |
|------|------|---|---------------------|-----------|

- 桶別與 plan.md 不一致 / 新倉未歸桶 → 標 `⚠️ 待歸桶`（疑問時預設認列桶）
- 🔵 信念桶：只檢查 ① thesis 破 ② >10%，其餘不 trim
- 🟢 認列桶：進入 Swing Risk 監測（Section E2）與飛輪檢查（Section 4.5）

**D3. 支數檢查：** 主動組合支數 = X 檔（目標 14–18，理想 14–16）。>18 → 標 `🔴 超編：新倉一律砍一進一，不淨增`；<14 → 標 `🟡 有空位：從 plan.md L1 On-Deck 補`。

### E. Options Summary
For each option position:
- Type (Call/Put, Long/Short)
- Strike, Expiry date
- Days to expiry (calculate from today's date)
- Current P&L
- Status (ITM/OTM/ATM based on last stock price if available)
- For LEAPS: delta equivalent shares estimate
- For Sell Puts: potential assignment cost and margin estimate

### E2. Swing Risk & Realized 健檢（必做，per `feedback/realized-pnl-business-model.md`）

**E2a. 每倉位 Swing Risk 標記（認列桶全列；信念桶僅 >10% 或肥利潤者）：**

| 標的 | 桶別 | 未實現利潤% | β | Swing Risk 判定 | 建議動作 |
|------|------|-----------|---|----------------|---------|

- 正股 Swing Risk = 帳上未實現利潤 + 潛在回吐（用 ATR% 估波動）；Options = Premium 成本 + 未實現利潤（歸零 = Expiry Risk）
- **判定門檻**：肥利潤（>+40%）+ 高 β（>2）+ revision 轉折/題材降溫 → `🔴 建議 harvest`；肥利潤但 revision 仍上修 → `🟡 監測`（結構領導者不純因新高 trim，per `feedback/momentum-valuation-symmetry.md` 規則 3）
- 建議動作必須具體：落袋 N 股 @ GTC $X / 開 covered call / 用價差替代 / Roll（附可掛單，per `feedback/actionable-firstrade-orders.md`）

**E2b. Realized vs Unrealized 比例健檢（組合層）：**
```
本月 Realized PnL: $X,XXX（從 get_account_history 或 journal 累計）
未實現虧損合計: −$X,XXX
比例: Realized ≈ X.X× |未實現虧損|（目標 ≈ 4×）
```
- 比例反轉（一直認列虧損、獲利全掛浮動）→ `🔴 爆倉訊號 flag`
- 落袋節奏檢查：認列循環桶日常 Rolling 落袋目標 0.5–1%/日，最近 5 個交易日實際認列 $X

### F. Key Alerts
- Upcoming expiries within 30 days
- Positions with > 20% loss
- Sector concentration warnings
- Sell put margin utilization estimate
- **Swing Risk 未處理**：E2a 標 🔴 的倉位若無對應掛單 → 列入 alerts
- **現金滯留**：現金 >15–20% 且無明確部署計畫（無 GTC 掛單、無 dry powder 理由）→ `🔴 飛輪滲漏 flag`

### G. 個股趨勢與分析

**平行數據收集（第一組 Agent 子代理 — subagent_type: "data-collector"）：**

使用 Agent tool 平行派遣以下 3 組子代理（每組 subagent_type: "data-collector"，自動使用 Sonnet 4.6）：

- **Agent 1 — Yahoo Finance**（subagent_type: "data-collector"，所有主要持倉 >3%）：`get_stock_info` + `get_yahoo_finance_news` + `get_historical_stock_prices`
- **Agent 2 — Technical**（subagent_type: "data-collector"，所有持倉）：`get_batch_indicators` + `get_technical_indicators`（top 5 個別分析）
- **Agent 3 — Sentiment**（subagent_type: "data-collector"，top 5）：`get_sentiment_trend`（ticker format: "TICKER.US"）

若 Agent tool 不可用，依序呼叫亦可。

⚠️ **Agent 失敗 fallback**：若任一 agent 回傳空結果或聲稱「沒有 MCP 權限」，主 Claude 直接自行呼叫對應工具：
- Agent 2（Technical）失敗 → 主 Claude 直接呼叫 `mcp__technical-mcp__get_batch_indicators` + `mcp__technical-mcp__get_technical_indicators`，繼續輸出 G2 技術分析
- Agent 1（Yahoo Finance）失敗 → 主 Claude 直接呼叫 `mcp__yfinance-advanced__get_stock_info`
- Agent 3（Sentiment）失敗 → 主 Claude 直接呼叫 `mcp__eodhd-mcp__get_sentiment_trend`
絕不因 agent 失敗而跳過整個 section。

Split holdings into two tiers:
- **主要持倉 (> 3% of portfolio):** Full analysis
- **小型持倉 (< 3%):** Summary row only

#### For major holdings (> 3%), fetch and display:

**G1. 股價趨勢 (Price Trends)**
Use `mcp__yfinance-advanced__get_historical_stock_prices` with different periods.
Show for each stock:

| 標的 | 現價 | 1週 | 1月 | 3月 | YTD | 52W高/低 | 距52W高 |

Calculate % change from period start to current price.

**G2. 技術分析摘要 (Technical Summary)**
Use `mcp__technical-mcp__get_batch_indicators` for all major holdings at once, then `mcp__technical-mcp__get_technical_indicators` for top 5 holdings.

**Batch overview table (all major holdings):**

| 標的 | 現價 | RSI | MACD交叉 | 動量分數 | 趨勢 | 波動率 | 量能比 |

**Detailed view (top 5 holdings only):**
Use `mcp__technical-mcp__get_technical_indicators` for full data including Bollinger Bands and ATR.

| 標的 | BB %B | ATR% | SMA20 | SMA50 | SMA200 | vs50MA% | vs200MA% |

Flag:
- RSI < 30 → 💡 超賣 (可能買入機會)
- **RSI 過高不標示、不觸發任何動作**（2026-07-01 移除舊「⚠️ 超買」flag — 強者愈強，反轉偵測交給 revision 閘門）
- momentum_score > 50 → 強勢
- momentum_score < -50 → 嚴重弱勢
- vol_regime = "high" → 高波動注意

**G3. 基本面摘要 (Fundamentals)**
Use `mcp__yfinance-advanced__get_stock_info` for financial data.

| 標的 | Forward PE | P/S | Revenue Growth | Gross Margin | FCF | Analyst Rating | Target Price | Upside |

**G3.5 三錨點公允價（D1 三角定位，全 >3% 持倉）**

資料：Step 0.5 fundamentals-snapshot.json cache（已預載）

三錨點計算規則（同 briefing Section 8.5，以下為簡化版）：

| 錨點 | 欄位 | 缺值處理 |
|------|------|---------|
| A1 市場 PE | `highlights.pe_ratio` | 0.0/null → 標 N/A |
| A2 PEG 錨 | `peg_ratio × growth%`；AI 龍頭 PEG=1.5，其餘=1.0 | 0.0/null → 標 N/A |
| A3 分析師錨 | `wall_street_target ÷ fwdEPS`；fwdEPS 來源優先序 `forward_estimates.curr_fy.eps_avg`（真實共識）→ `next_fy.eps_avg` → `eps_ttm×(1+growth)` 近似（cache `self_valuation.a3_fwdeps_source` 已標來源）| 任一缺 → 標 N/A |
| **A4 自建錨** | `self_valuation.own_target_price`（cache 已算） | `unavailable` → `(N/A)`；`low` → `⚠️`；**不進 median** |

情境 FairPE：base=median(A1,A2,A3)（A4 排除）；bull=max×1.25（上限 current_PE×1.25）；bear=min×0.70

輸出表（Full/Deep tier 才出 A4 欄）：
```
| 標的 | 現價 | A1 PE | A2 PEG錨 | A3 PT錨 | Fair PE(基/牛/熊) | FwdEPS | 公允價(基/牛/熊) | A4自建目標 | A4vsA3% | 偏離基準% | 備註 |
|------|------|-------|---------|---------|-----------------|--------|----------------|----------|---------|---------|------|
```

A4 欄規則：
- `unavailable` → `(N/A)`；`low` → 顯示數字 + `⚠️`；`ok` → 顯示數字
- `A4vsA3% = (own_target − wall_street_target) / wall_street_target`
- |A4vsA3%| > 20% → 備註欄加：「我較 Street 樂觀」/ 「我較 Street 保守」
- **EPS 修正動能（備註欄）**：讀 `forward_estimates.curr_fy`，`revisions_up_30d ≫ down_30d` 或 `eps_revision_30d_pct > 0` → 標 `共識上修↑`（guidance 偏正領先訊號）；反之 `共識下修↓`。僅 flag，非估值輸入

偏離 > ±30% → 標 `⚠️ 大幅偏離`；偏離 > ±50% → 標 `⚠️⚠️ 異常大偏離，錨點可能失效`

**G4. 近期新聞 (Recent News)**
Use `mcp__yfinance-advanced__get_yahoo_finance_news` for each major holding.
Show top 2 headlines per stock:

| 標的 | 日期 | 標題 | 情緒判斷 |

Sentiment: 利好/利空/中性 based on headline content.

#### For minor holdings (< 3%), show condensed row:

| 標的 | 市值 | 佔比 | 趨勢 | 1月% | Analyst |

**NOTE: 平行數據收集已在 Section G 開頭的 Agent 子代理指令中統一處理。**

#### G5. 情緒面分析 (Sentiment Analysis)
Use `mcp__eodhd-mcp__get_sentiment_trend` for top 5 holdings by market value.

| 標的 | 7日情緒 | 30日情緒 | 趨勢 |

For any stock with strongly negative sentiment (< -0.3), also call `mcp__eodhd-mcp__get_news_sentiment` to show recent negative headlines.

Flag stocks with rapidly deteriorating sentiment (7-day avg significantly below 30-day avg).

Note: EODHD tickers use exchange suffix format (e.g. "AAPL.US", "NVDA.US").

**平行數據收集（第二組 Agent 子代理 — subagent_type: "data-collector"）：**

在 Section G 數據到齊後，派遣第二組（subagent_type: "data-collector"，自動使用 Sonnet 4.6）：

- **Agent 4 — SEC EDGAR**（subagent_type: "data-collector"，top 5）：`get_insider_transactions` + `get_recent_filings`
- **Agent 5 — FMP**（subagent_type: "data-collector"）：`getStockPeers`（top 3）+ `getBiggestGainers` / `getBiggestLosers`

若 Agent tool 不可用，依序呼叫亦可。

### H. SEC EDGAR 深度數據

**Uses SEC EDGAR MCP tools.**

Only run this section for the **top 5 holdings by market value**. Skip if user says "快速報告".

**H1. 內部人交易 (Insider Trading)**
Use `mcp__sec-edgar-mcp__get_insider_transactions` (days=90) for each top holding.

| 標的 | 90天內部人交易 | 買入/賣出 | 重要交易摘要 |

Flag any significant insider buying (bullish signal) or heavy selling (watch).

**H2. SEC 財報數據 (SEC Financials)**
Use `mcp__sec-edgar-mcp__get_financials` with `statement_type="income"` for top holdings.
Cross-reference with yfinance data — highlight any discrepancies.

| 標的 | SEC Revenue | SEC Net Income | SEC EPS | 與Yahoo差異 |

**H3. 近期 SEC Filing (Recent Filings)**
Use `mcp__sec-edgar-mcp__get_recent_filings` (days=30) for top holdings.

| 標的 | Filing類型 | 日期 | 重點摘要 |

Flag any 8-K (material events), 10-K/10-Q (earnings), or Form 4 (insider) filings.

**Note:** SEC EDGAR data comes directly from official SEC filings and may lag real-time market data by days/weeks. Use it for verification and deep analysis, not for real-time trading decisions.

### I. FMP 市場動態與同業比較

**This section uses FMP MCP tools (free tier). Run in parallel with other sections.**

Skip if user says "快速報告".

**I1. 同業比較 (Peer Comparison)**
Use `mcp__fmp-mcp__getStockPeers` for top 3 holdings.

| 標的 | 同業代碼 | 同業股價 | 備註 |

Highlight any peers that overlap with existing portfolio holdings.

**I2. 市場動態掃描 (Market Movers)**
Use `mcp__fmp-mcp__getBiggestGainers` and `mcp__fmp-mcp__getBiggestLosers`.
Check if any portfolio holdings appear in today's extreme movers.

**I3. 公司概覽補充 (Company Profile)**
Use `mcp__fmp-mcp__getCompanyProfile` only for tickers where yfinance data is incomplete or unavailable.

**Note:** FMP free tier is limited. Tools like getQuote, getIncomeStatement, getAnalystEstimates, getEarningsTranscript return 402. Only use the free endpoints listed above.

### I.5 樂透機會掃描（Lottery Opportunity Scan）

**目的：** 從市場掃出**至多 3 個**適合短 DTE OTM Call 樂透的候選（per memory feedback：樂透用近期 OTM Call 不用 LEAPS，避免 vega 干擾凸性）。

**篩選步驟（重用 Section I.2 的 movers 數據，不額外抓取）：**
1. 候選池：`getBiggestGainers` + `getMostActiveStocks`
2. **排除遲到派對：** 過去 5 日累計漲幅 > 30% → 凸性已被消耗
3. **排除既有持倉同題材：** 與 portfolio 重複曝險的標的跳過
4. **必要條件（3 項全符合才入選）：**
   - 30 天內有 binary catalyst（財報 / FDA / 政策 / 公告）
   - 有具體論述（不是純技術突破或迷因）
   - 短 DTE OTM Call 流動性合理（OI > 500 估算）

**輸出格式（限 1-3 筆，無符合則輸出「⏳ 本次無符合凸性條件的樂透機會」）：**

| Ticker | 題材 / Binary 催化 | 建議結構 | 預估成本 | 凸性備註 |
|--------|----------------|---------|---------|---------|

**規則：**
- 預設 1-2 口，**總成本 ≤ 2% 帳戶價值**（Quarter-Kelly 樂透上限）
- **不推 LEAPS OTM 當樂透**（vega 干擾，違反 feedback_options_vega_playbook.md）
- 「上行 +XXX% / 下行 max loss = premium」必寫
- 若候選 IV Rank > 80：警告「IV 過高，後續 IV crush 風險」
- 若 portfolio 已有同板塊 binary 樂透（如 OKLO 待執行）：優先補強既有，不新開重複曝險

4. **配置計畫對照（必做）**
   - 對照 `plan.md` 中的目標配置
   - 顯示計畫執行進度表：

   | # | 計畫操作 | 狀態 | 備註 |

   - 標記已完成 ✅、進行中 🔄、待觸發 ⏳ 的項目
   - 板塊佔比 vs 計畫目標的偏差分析
   - 風險監控項目的當前狀態
   - 下一步建議（基於計畫優先級 + 當前市場條件）

4.5 **飛輪檢查（汰弱留強 → 停利 → 再投入；收尾必跑，per `feedback/momentum-valuation-symmetry.md`）**

   > 診斷基準 = **價格 vs revision 背離**：價弱但 revision↑ = 洗盤該加；價強但 revision↓/flat = 峰值該 harvest。「弱」= fundamental 惡化或最弱動能無催化（非當日紅K）；「強」= estimate 上修/成長加速（非當日超買）。

   **① Harvest 掃描（賣峰值強度）**：認列桶中 revision 轉折（up:down 惡化/翻 flat）/ 題材降溫 / Swing Risk 🔴 者 → 列 harvest 清單，附 GTC 賣限價階梯或 covered call 結構
   **② 砍真弱掃描（騰名額）**：僅在 14–18 上緣需要名額時。thesis 破（根因 (a)）OR 最弱動能且無催化者 → 列砍單，依砍因歸層（組合理由→L1 / thesis 破→L2）
   **③ 現金滯留檢查**：現金 % + 既有 GTC 掛單覆蓋額 → 若 >15–20% 閒置且無部署計畫 → 🔴 flag
   **④ Redeploy 配對（每筆 harvest/砍單必配一個去處）**：第一順位 = 信念桶領導者 / L1 中 revision 最陡的領漲者（列 plan.md L1 各標的 revision up:down 比較表）；要嘛部署（附 GTC 買單階梯 / spread 結構），要嘛標明 `dry powder + 觸發條件`。**禁 default 流向「便宜但 revision 平/下修」的落後者**
   **⑤ 選擇權工具對映（活用而非只現股進出）**：
   - harvest 端：≥100 股肥利潤認列桶 → covered call（30-45 DTE，strike 近 R1/分析師 PT）替代直接賣股；高 β 純週期 → 用價差鎖利潤
   - redeploy 端：加速中領導者貼高/超買 → **bull call spread 定義風險參與**（不是「太貴不追」）；支撐區進場 → bull put spread 替代限價單；長期信念 → LEAPS deep ITM（delta 0.80–0.88）
   - 每個建議附完整可掛規格（結構 + strike + 到期 + limit + 口數；複式單無法 GTC → 價格警報 + 預定結構）

   **輸出格式：**
   ```
   ### 🔄 飛輪檢查
   | 動作 | 標的 | 觸發依據（revision/Swing Risk） | 執行結構 | 可掛單 |
   |------|------|-------------------------------|---------|--------|
   | Harvest | ... | revision 19:12 惡化 + β3.78 | GTC 賣 N@$X 或 CC | ... |
   | Redeploy | ... | L1 最陡 revision 21:0↑ | GTC 階梯 / BCS | ... |
   現金滯留：X%（✅ 有部署計畫 / 🔴 閒置無理由）
   Harvest↔Redeploy 配對：X 筆 harvest / X 筆已配對（必須相等或標 dry powder 理由）
   ```

   Guardrails 不可破：單倉 >10%、14–18 支、相關度上限、去相關 hedge sleeve（AU 等避險倉不參與動能輪動、不因落後就汰）。

5. **第一性檢查（在「下一步建議」前必填）**

   **🔒 強制：機率分布 + EV 必須呼叫 `probability-honesty-checker` agent**

   寫出機率分布之前必須執行（Section A-I 數據已備齊，agent 不需重新抓）：

   ```
   Agent(
     subagent_type: "probability-honesty-checker",
     description: "Portfolio review 30d EV check",
     prompt: """
     計算當前組合 30 日 horizon 機率分布與 EV。

     ## Step 1 九項輸入（已備齊，從 Section A-I + cache 摘出）:
     1a. RSI 分布: [從 Section G1 / G2 摘出，每 bucket 檔數 + % of port]
     1b. 距 52w 高: [從 Section G3 / get_stock_info 摘出，中位數/最大/最小]
     1c. 已實現波動: 過去 5d/2d/最大單日（從 journal/firstrade）
     1d. Binary catalysts (30d window): [從 earnings-dates.json 摘出財報日期，
         **beat rate + avg surprise %** 來源優先順序：
         (1) fundamentals-snapshot.json → tickers.TICKER.base_rate（EODHD）
         (2) earnings-history.json → tickers.TICKER（yfinance 備選）
         格式：「N/8 beat, +X.X% avg」。avg_surprise_unreliable=true → 只用 beat N/8，avg% 標 (unreliable-low-base)；cache 缺 → 標 (unavailable)]
     1e. 集中度: top 1 / top 5 / 最大板塊（從 Section B 板塊分配）
     1f. 板塊輪動曝險: [從 sector_rotation + Section B 計算 leading/lagging 持倉 %]
     1g. Sentiment: 7d/30d 對比（從 Section G5）
     1h. Thesis 健康度: 各持倉 fundamental 是否 intact（從 Section G3 / G4）
     1i. Macro state: [從 briefing-out/cache/macro-snapshot.json 完整貼入]
         - fed_funds + 30d change
         - yield_2s10s + regime
         - hy_oas + regime + pct_1y
         - vix + regime
         - cpi_yoy + trend
         - regime_tag (overall)

     ## 額外 context:
     [plan.md 摘要 + 最近 N 天事件 + 用戶投資風格]

     請執行你的 6 步流程並回傳完整輸出 + 精簡結論。
     """
   )
   ```

   收到 agent 結果後 **verbatim 顯示**完整 6 步輸出（或至少顯示精簡結論 + Self-Audit checklist）。**主 skill 絕不可手動套機率或寫「EV 略偏正/略偏負」。**

   ```
   ### 第一性檢查（組合層級）
   - **核心 thesis：** [1 句可驗證命題]
   - **證偽條件：** [2-3 個 falsifiable 觀察點]
   - **組合機率分布：** [由 probability-honesty-checker agent 算出]

     [貼上 agent 的完整 Step 5 EV Calculation 表格]

     Expected return (30d) = X.XX%（agent 顯式 Σ 計算結果）

   - **Agent Self-Audit：** [貼上 agent 的 Step 6 checklist]
   ```

   下一步建議必須**明確 conditional 在 thesis 成立的機率**，且引用 agent 計算的數字（不可手動改寫）。

   **禁止偷懶**（user push back「你真的有算嗎」時的處理）：
   - 不辯解、不重組原數字
   - 重跑 agent，明確要求 audit checklist 全勾
   - 發現原本偷懶（套 default、寫質性）→ 老實承認 + 顯示新算

   **第一性檢查產出後 → 登錄 Thesis Ledger（收尾）：**
   只登錄有明確時間/事件觸發點的 thesis（組合層級 + 個股 micro thesis 帶「請在財報後/N 日後檢視」）。登錄前先 `list --ticker <T>` 看既有 slug，同論點沿用（update）、新論點取區隔 slug，再 `add`（exit code 2 = 碰撞 → 改 slug 或 `supersede`）。指令格式同 briefing Step 0.7。

---

## Section J: Codex 第二意見（opt-in）

**僅當 arguments 含 `--codex` 或 `--2nd` 時執行（例：`/portfolio-review --codex`）。**

三個子 block 依序執行（可並行派 Agent）：

### B1. 獨立第一性分析（預設，independent first-principles）

**核心原則：Codex 不看 Claude 的 Sections A–I 結論**，只給 raw portfolio data，讓它獨立評估組合健康度與調倉優先序。Claude 與 Codex 兩個獨立輸出並排比較。

呼叫 Codex（**用 CLAUDE.md「Codex 呼叫方式」的 `codex exec` CLI；勿用 codex:codex-rescue subagent / `/codex:rescue`，會卡 superpowers preamble**），prompt 首行加強制 no-tool 指令，模板：

```
我是一名美股投資人，使用 Level 2 options + Spread 的 margin 帳戶。
請對以下投資組合，**完全獨立**執行第一性分析 — 不要看任何先前結論，這是獨立第二意見。

**Raw 持倉數據（只給事實）：**
- 帳戶總值：$XXX，現金 $XXX
- 股票持倉清單（標的 / 股數 / 均價 / 現價 / 市值 / 損益% / 占比%）
- 選擇權清單（合約 / 方向 / 到期 / 損益%）
- 板塊歸屬（從持倉自然分類，不假設既定 framework）

**用戶設定（plan.md 摘要）：**
- 板塊配置目標：[從 plan.md 摘出板塊 % 目標]
- 投資主軸：AI/半導體、高成長科技；汰弱留強
- 信念持倉：[列出哪些是不換的長期論點]
- 風險原則：單一持倉 > 10% 警示；Quarter-Kelly 單筆 ≤ 5%

**請輸出（獨立判斷）：**

1. **組合健康度 thesis**（1 句可驗證命題：此組合目前處於什麼狀態？例如「過度集中 AI 半導體 + 現金不足」「板塊均衡但動能股偏多」）

2. **3 個最大結構性風險**（具體量化 — 例如「單一個股 X 占 12.5% 超過 10% 警戒」「板塊 Y 與 Z 高度相關，組合 beta 1.7」）

3. **機率分布表（未來 30 天組合表現）— ⚠️ 嚴禁偷懶，必照 5 步推導：**

   ❌ **禁用 default mirror shape**：25/50/25、30/45/25、35/45/20、20/45/35（無依據時一律禁止）
   ❌ 禁質性語言（「略偏正」「應該會」「中性偏多」）
   照以下 5 步，**每步都要寫出來**，不可直接跳到機率：
   (a) **Input Enumeration**：列 9 項 — RSI 分布 / 距 52w 高 / 已實現波動(5d,2d,單日) / binary catalysts + 各自 base rate / 集中度 / 板塊輪動 / sentiment / thesis 健康度 / macro。缺項不可進下一步。
   (b) **形狀反推**：起點 33/34/33，再依事實逐條 nudge（mean reversion 引力、binary catalyst → 雙峰非 bell、集中度、weakening 板塊、macro 左尾），每條調整寫 ±Xpp 與理由。不可直接寫結果。
   (c) **各情境 conditional 機率**：每個 catalyst 顯式 base rate（例：「MU 8/8 beat → blowout 機率 55%」）。
   (d) **三情境合成**：sum = 100%（顯式 check）。
   (e) **EV = Σ(機率 × 中點)**：中點 = 報酬區間算術平均（例 +10~+15% → +12.5%）。

   | 情境 | 機率 | 觸發條件(含 base rate) | 報酬區間 | 中點 | 機率×中點 |
   |------|------|---------|---------|------|----------|
   | 樂觀 | XX% | [條件] | +X~+Y% | +Z% | +A% |
   | 基準 | XX% | [條件] | ... | ... | ... |
   | 悲觀 | XX% | [條件] | -X~-Y% | -Z% | -A% |

   Expected Value = Σ(機率 × 中點) = **±X%**（顯式數字，非文字）

4. **3 個 actionable 調倉建議**（含口數 / 理由 / conditional）：
   - 操作 1：[減 / 加 / 換] 多少股 [標的]，理由 [...]
   - 操作 2：...
   - 操作 3：...

5. **Verdict**（1 句）：組合需要 重大調整 / 微調 / 維持，conditional 在什麼前提。

**規則：**
- 不假設 Claude 已說過什麼
- 用客觀數據與你自己的 mental model
- 機率分布必須 sum 到 100%
- 調倉建議必須講股數/口數

請以繁體中文回覆，控制在 800 字內。

--effort high --fresh
```

### B2. 機會掃描（opportunity scout）

呼叫 Codex（用 CLAUDE.md「Codex 呼叫方式」的 `codex exec` CLI）：

```
我目前的美股持倉（含市值占比）：
[插入 Section B 板塊分配表]

我的投資風格：
- 主軸：AI/半導體、高成長科技；汰弱留強，集中持倉
- 信念持倉（不換）：TSLA, MU, AVGO 多年期 thesis
- 板塊偏好：[從 plan.md 摘出 3-5 行板塊目標]

請以獨立分析師視角：
1. 掃描今日市場有哪些當紅題材/個股，是我目前持倉沒覆蓋到的
2. 對每個候選列出：題材、代表 ticker、為何此刻有機會、建議切入方式（現股/Spread/LEAPS）
3. 要追這些新機會，最該砍掉哪一檔現有持倉？為什麼？
4. 提供 2-3 個具體 actionable 建議（含目標 entry zone）

請以繁體中文回覆。輸出限 600 字。
```

### B3. 輪動分析（rotation scan）

**Step 1 — Claude 預先收集數據：**
- `mcp__technical-mcp__get_sector_rotation()` → 全板塊 ETF 相對強度 vs SPY（leading / improving / weakening / lagging）
- `mcp__technical-mcp__get_batch_indicators(tickers=[所有持倉])` → 個股動能分數 + 趨勢

**Step 2 — 呼叫 Codex（用 CLAUDE.md「Codex 呼叫方式」的 `codex exec` CLI）：**

```
我的美股持倉（含市值占比 + 板塊歸屬）：
[持倉表]

當前板塊輪動數據（vs SPY）：
[get_sector_rotation 完整輸出]

當前個股動能：
[get_batch_indicators 摘要]

請以輪動專家視角：
1. 板塊輪動：哪些板塊 leading，哪些 weakening？我的持倉是否站在 leading 板塊？
2. 個股輪動：在我已持有的板塊內，有更強的 leader 我沒拿到？有持倉已被同板塊其他名字超越？
3. 資金流向：從 weakening 輪到 leading 的訊號是否明確？建議調倉路徑
4. 具體建議：3 條 actionable 輪動操作（從哪檔減 → 加到哪檔，附理由）

請以繁體中文回覆。輸出限 700 字。
```

### 輸出整合

```
## 🤖 Codex 第二意見

### B1. 獨立第一性分析（Codex 獨立輸出）

**Codex 組合健康度 thesis：** [...]
**Codex 列的 3 大結構性風險：** [...]
**Codex 機率分布：**

| 情境 | 機率 | 條件 | 預期 % |
|------|------|------|--------|
| ... |

**Codex EV：** ±X%
**Codex 3 個調倉建議：** [...]
**Codex Verdict：** [...]

---

#### 並排比較：Claude vs Codex（獨立輸出）

| 維度 | Claude | Codex | 一致性 |
|------|--------|-------|--------|
| 健康度 thesis | [Claude] | [Codex] | 一致 / 部分 / 顯著 |
| 最大風險 #1 | [Claude] | [Codex] | 同 / 異 |
| EV (30d) | ±X% | ±X% | 差 X% |
| 主要調倉建議 | [Claude] | [Codex] | 同 / 異 |
| Verdict | [Claude] | [Codex] | 同 / 異 |

**真實共識**（兩邊都認同）：[1-2 條 — 高信心]
**真實分歧**（兩邊得出不同結論）：[1-3 條 — 值得深入]

### 機會掃描（vs 現有持倉）
[B2 Codex 完整回覆]

### 輪動分析（板塊 + 個股）
[B3 Codex 完整回覆]

---
**值得追蹤的新機會：** [從 B2 挑 1-2 個 Claude 也認同的]
**輪動 actionable：** [從 B3 挑 1-2 條 Claude 也認同的調倉操作]
```

### 進階：`--codex-adversarial`（opt-in 壓力測試）

僅當 arguments 含 `--codex-adversarial` 時，**追加**對立面審查段落（攻擊組合論點、找弱點）。預設 `--codex` 不執行。

> 若 Codex 失敗 → 輸出 `⚠️ Codex 不可用：[error]，跳過第二意見`，繼續正常輸出。

---

## Output Format
Use clean markdown tables. Keep it concise but comprehensive. All dollar amounts in USD.
Use Traditional Chinese (繁體中文) for all text output to match the user's preference.

## 存檔 + HTML 生成
報告完成後：
1. 使用 Write tool 把完整 markdown 寫到 `briefing-out/portfolio-review-YYYY-MM-DD.md`
2. 執行：
```bash
python3 tools/generate_html.py portfolio-review briefing-out/portfolio-review-YYYY-MM-DD.md --push
```
成功時印出網頁連結，失敗（repo 尚未建立）時印警告並繼續。若用戶未設定 reports repo，省略 --push。

## Performance Notes
- The full report with G section will make many MCP calls. Expect 2-3 minutes for a 20-stock portfolio.
- If the user wants a quick report, they can say "快速報告" to skip section G.
- Fetch stock_info once per ticker and reuse data across G2 and G3 sections.
