---
name: portfolio-review
description: Fetch live brokerage positions and generate a comprehensive portfolio report with sector allocation, P&L analysis, options summary, and risk assessment. Use when user asks for portfolio review.
user_invocable: true
model: claude-fable-5
---

# Portfolio Review

Generate a comprehensive portfolio report from the user's live brokerage positions (via the `shioaji-server` MCP).

## Step 0: 配置同步 & 倉位偵測

執行 AGENTS.md 的 Step 0 統一規範（0a → 0b → 0c → 0d → **0e**）。
- 讀 `plan.md` + `feedback/*.md`（必做）；在後續分析中引用板塊目標與策略佇列
- 呼叫 `get_account_position` 取即時持倉
- 今日 journal 不存在 → 執行 gap-fill + 變動偵測 + 自動建立 journal
- **0e 第一性原理紀律**：在「下一步建議」之前必須完成「組合層級 thesis / 證偽條件 / 機率分布」三題（見 AGENTS.md 0e）

## Step 0.5: Macro + Earnings Cache Load

讀以下三份 cache（由 `tools/fetch_macro.py` + `tools/earnings_history.py` 預載）：
- `briefing-out/cache/macro-snapshot.json` — 供 Step 0e 與 probability-honesty-checker Step 1i
- `briefing-out/cache/earnings-history.json` — 供 Section F Key Alerts、Section G 個股 thesis、及 probability-honesty-checker Step 1d base rate
- `briefing-out/cache/earnings-dates.json` — 供 Section F 財報/月營收窗口 警示

若 macro `status == "skipped"` → Section K 第一性檢查標記 `Macro: unavailable`，probability-honesty-checker 1i 填 unavailable。
若 cache 過期 > 36h → 加註 `⚠️ cache stale (X h)`。
若 cache 缺某 ticker → Section F 該 ticker earnings 列 `(unavailable)`，prompt 提示手動 `python3 tools/earnings_history.py --force`。

---

## Step 0.6: Thesis Ledger 驗收 & 逾期掃描

與 briefing 共用同一套引擎（`tools/thesis_ledger.py`，帳本 `research/thesis-ledger.json`）。portfolio-review 也自動驗收，確保未跑 briefing 的日子不漏驗收。

```
python3 tools/thesis_ledger.py due      # 取到期清單 + 自動 expire sweep
```
對每筆 `due`：讀 `trigger.metric` → 用 MCP 抓實際數字 → 對照 `thesis`+`falsification` 判 passed/failed/partial → `resolve --next-action`；抓不到新數 → `reschedule` 維持 pending，不猜 verdict。流程細節與規則同 briefing Step 0.7。

在 **Section F Key Alerts 前**輸出「📋 thesis 驗收」表（命題 → 實際 → verdict → actionable），並列出 expired 歸檔清單。驗收結果直接餵「下一步建議」。

---

## Workflow

1. **Fetch live positions**
   - Call `mcp__shioaji-server__get_account_position` to get real-time positions
   - Also call `mcp__shioaji-server__get_account_balance` for total account value
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

   **Step 2: For any ticker you're unsure about**, use `mcp__finmind-server__get_stock_info` to check its `sector`, `industry`, and `longBusinessSummary` fields to classify accurately.

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

### D. Position Sizing
Flag positions that are:
- Over 7% of portfolio (too concentrated)
- Under 1.5% of portfolio (too small to matter)

### E. Options Summary
For each option position:
- Type (Call/Put, Long/Short)
- Strike, Expiry date
- Days to expiry (calculate from today's date)
- Current P&L
- Status (ITM/OTM/ATM based on last stock price if available)
- For 個股期貨: delta equivalent shares estimate
- For Sell Puts: potential assignment cost and margin estimate

### F. Key Alerts
- Upcoming expiries within 30 days
- Positions with > 20% loss
- Sector concentration warnings
- Sell put margin utilization estimate

### G. 個股趨勢與分析

**平行數據收集（第一組 Agent 子代理 — subagent_type: "data-collector"）：**

使用 Agent tool 平行派遣以下 3 組子代理（每組 subagent_type: "data-collector"，自動使用 Haiku 4.5）：

- **Agent 1 — FinMind**（subagent_type: "data-collector"，所有主要持倉 >3%）：`get_stock_info` + `get_finmind_finance_news` + `get_historical_stock_prices`
- **Agent 2 — Technical**（subagent_type: "data-collector"，所有持倉）：`get_batch_indicators` + `get_technical_indicators`（top 5 個別分析）
- **Agent 3 — Sentiment**（subagent_type: "data-collector"，top 5）：`get_sentiment_trend`（ticker format: "TICKER"）

若 Agent tool 不可用，依序呼叫亦可。

Split holdings into two tiers:
- **主要持倉 (> 3% of portfolio):** Full analysis
- **小型持倉 (< 3%):** Summary row only

#### For major holdings (> 3%), fetch and display:

**G1. 股價趨勢 (Price Trends)**
Use `mcp__finmind-server__get_historical_stock_prices` with different periods.
Show for each stock:

| 標的 | 現價 | 1週 | 1月 | 3月 | YTD | 52W高/低 | 距52W高 |

Calculate % change from period start to current price.

**G2. 技術分析摘要 (Technical Summary)**
Use `mcp__technical-mcp__get_batch_indicators` for all major holdings at once, then `mcp__technical-mcp__get_technical_indicators` for top 5 holdings.

**Batch overview table (all major holdings):**

| 標的 | 現價 | RSI | RSI狀態 | MACD交叉 | 動量分數 | 趨勢 | 波動率 | 量能比 |

**Detailed view (top 5 holdings only):**
Use `mcp__technical-mcp__get_technical_indicators` for full data including Bollinger Bands and ATR.

| 標的 | BB %B | ATR% | SMA20 | SMA50 | SMA200 | vs50MA% | vs200MA% |

Flag:
- RSI > 70 → ⚠️ 超買
- RSI < 30 → 💡 超賣 (可能買入機會)
- momentum_score > 50 → 強勢
- momentum_score < -50 → 嚴重弱勢
- vol_regime = "high" → 高波動注意

**G3. 基本面摘要 (Fundamentals)**
Use `mcp__finmind-server__get_stock_info` for financial data.

| 標的 | Forward PE | P/S | Revenue Growth | Gross Margin | FCF | Analyst Rating | Target Price | Upside |

**G4. 近期新聞 (Recent News)**
Use `mcp__finmind-server__get_finmind_finance_news` for each major holding.
Show top 2 headlines per stock:

| 標的 | 日期 | 標題 | 情緒判斷 |

Sentiment: 利好/利空/中性 based on headline content.

#### For minor holdings (< 3%), show condensed row:

| 標的 | 市值 | 佔比 | 趨勢 | 1月% | Analyst |

**NOTE: 平行數據收集已在 Section G 開頭的 Agent 子代理指令中統一處理。**

#### G5. 情緒面分析 (Sentiment Analysis)
Use `mcp__cnyes-news__get_sentiment_trend` for top 5 holdings by market value.

| 標的 | 7日情緒 | 30日情緒 | 趨勢 |

For any stock with strongly negative sentiment (< -0.3), also call `mcp__cnyes-news__get_news_sentiment` to show recent negative headlines.

Flag stocks with rapidly deteriorating sentiment (7-day avg significantly below 30-day avg).

Note: FinMind tickers use exchange suffix format (e.g. "2330", "2330 台積電").

**平行數據收集（第二組 Agent 子代理 — subagent_type: "data-collector"）：**

在 Section G 數據到齊後，派遣第二組（subagent_type: "data-collector"，自動使用 Haiku 4.5）：

- **Agent 4 — 公開資訊觀測站 MOPS**（subagent_type: "data-collector"，top 5）：`get_insider_transactions` + `get_recent_filings`
- **Agent 5 — twse**（subagent_type: "data-collector"）：`getStockPeers`（top 3）+ `getBiggestGainers` / `getBiggestLosers`

若 Agent tool 不可用，依序呼叫亦可。

### H. 公開資訊觀測站 MOPS 深度數據

**Uses 公開資訊觀測站 MOPS MCP tools.**

Only run this section for the **top 5 holdings by market value**. Skip if user says "快速報告".

**H1. 內部人交易 (Insider Trading)**
Use `mcp__mops-server__get_insider_transactions` (days=90) for each top holding.

| 標的 | 90天內部人交易 | 買入/賣出 | 重要交易摘要 |

Flag any significant insider buying (bullish signal) or heavy selling (watch).

**H2. MOPS 財報數據 (MOPS Financials)**
Use `mcp__mops-server__get_financials` with `statement_type="income"` for top holdings.
Cross-reference with FinMind data — highlight any discrepancies.

| 標的 | MOPS Revenue | MOPS Net Income | MOPS EPS | 與FinMind差異 |

**H3. 近期 MOPS Filing (Recent Filings)**
Use `mcp__mops-server__get_recent_filings` (days=30) for top holdings.

| 標的 | Filing類型 | 日期 | 重點摘要 |

Flag any 重訊 (material events), 10-K/10-Q (earnings), or 內部人持股申報 (insider) filings.

**Note:** 公開資訊觀測站 MOPS data comes directly from official 公開資訊觀測站文件 and may lag real-time market data by days/weeks. Use it for verification and deep analysis, not for real-time trading decisions.

### I. twse 市場動態與同業比較

**This section uses twse MCP tools (free tier). Run in parallel with other sections.**

Skip if user says "快速報告".

**I1. 同業比較 (Peer Comparison)**
Use `mcp__twse-server__getStockPeers` for top 3 holdings.

| 標的 | 同業代碼 | 同業股價 | 備註 |

Highlight any peers that overlap with existing portfolio holdings.

**I2. 市場動態掃描 (Market Movers)**
Use `mcp__twse-server__getBiggestGainers` and `mcp__twse-server__getBiggestLosers`.
Check if any portfolio holdings appear in today's extreme movers.

**I3. 公司概覽補充 (Company Profile)**
Use `mcp__twse-server__getCompanyProfile` only for tickers where FinMind data is incomplete or unavailable.

**Note:** twse free tier is limited. Tools like getQuote, getIncomeStatement, getAnalystEstimates, getEarningsTranscript return 402. Only use the free endpoints listed above.

### I.5 樂透機會掃描（Lottery Opportunity Scan）

**目的：** 從市場掃出**至多 3 個**適合短 DTE OTM Call 樂透的候選（per memory feedback：樂透用近期 OTM Call 不用 個股期貨，避免 vega 干擾凸性）。

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
- **不推 個股期貨 OTM 當樂透**（vega 干擾，違反 feedback_options_vega_playbook.md）
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
     1c. 已實現波動: 過去 5d/2d/最大單日（從 journal/shioaji）
     1d. Binary catalysts (30d window): [從 earnings-dates.json + earnings-history.json
         摘出，**必須含 trailing 8Q beat rate + avg surprise %**，格式
         「N/8 beat, +X.X% avg」，cache 缺 → 標 (unavailable)]
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

**核心原則：Codex 不看 Codex 的 Sections A–I 結論**，只給 raw portfolio data，讓它獨立評估組合健康度與調倉優先序。Codex 與 Codex 兩個獨立輸出並排比較。

呼叫 Codex（`subagent_type: "codex:codex-rescue"`），prompt 模板：

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

3. **機率分布表（未來 30 天組合表現）：**

   | 情境 | 機率 | 觸發條件 | 組合預期 % |
   |------|------|---------|-----------|
   | 樂觀 | XX% | [條件] | +X% |
   | 基準 | XX% | [條件] | ±X% |
   | 悲觀 | XX% | [條件] | -X% |

   Expected Value = Σ(機率 × %) = ±X%

4. **3 個 actionable 調倉建議**（含口數 / 理由 / conditional）：
   - 操作 1：[減 / 加 / 換] 多少股 [標的]，理由 [...]
   - 操作 2：...
   - 操作 3：...

5. **Verdict**（1 句）：組合需要 重大調整 / 微調 / 維持，conditional 在什麼前提。

**規則：**
- 不假設 Codex 已說過什麼
- 用客觀數據與你自己的 mental model
- 機率分布必須 sum 到 100%
- 調倉建議必須講股數/口數

請以繁體中文回覆，控制在 800 字內。

--effort high --fresh
```

### B2. 機會掃描（opportunity scout）

呼叫 `/codex:rescue`：

```
我目前的美股持倉（含市值占比）：
[插入 Section B 板塊分配表]

我的投資風格：
- 主軸：AI/半導體、高成長科技；汰弱留強，集中持倉
- 信念持倉（不換）：2330 台積電, 3661 世芯-KW, 2454 聯發科 多年期 thesis
- 板塊偏好：[從 plan.md 摘出 3-5 行板塊目標]

請以獨立分析師視角：
1. 掃描今日市場有哪些當紅題材/個股，是我目前持倉沒覆蓋到的
2. 對每個候選列出：題材、代表 ticker、為何此刻有機會、建議切入方式（現股/Spread/個股期貨）
3. 要追這些新機會，最該砍掉哪一檔現有持倉？為什麼？
4. 提供 2-3 個具體 actionable 建議（含目標 entry zone）

請以繁體中文回覆。輸出限 600 字。
```

### B3. 輪動分析（rotation scan）

**Step 1 — Codex 預先收集數據：**
- `mcp__technical-mcp__get_sector_rotation()` → 全板塊 ETF 相對強度 vs 加權指數（leading / improving / weakening / lagging）
- `mcp__technical-mcp__get_batch_indicators(tickers=[所有持倉])` → 個股動能分數 + 趨勢

**Step 2 — 呼叫 `/codex:rescue`：**

```
我的美股持倉（含市值占比 + 板塊歸屬）：
[持倉表]

當前板塊輪動數據（vs 加權指數）：
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

#### 並排比較：Codex vs Codex（獨立輸出）

| 維度 | Codex | Codex | 一致性 |
|------|--------|-------|--------|
| 健康度 thesis | [Codex] | [Codex] | 一致 / 部分 / 顯著 |
| 最大風險 #1 | [Codex] | [Codex] | 同 / 異 |
| EV (30d) | ±X% | ±X% | 差 X% |
| 主要調倉建議 | [Codex] | [Codex] | 同 / 異 |
| Verdict | [Codex] | [Codex] | 同 / 異 |

**真實共識**（兩邊都認同）：[1-2 條 — 高信心]
**真實分歧**（兩邊得出不同結論）：[1-3 條 — 值得深入]

### 機會掃描（vs 現有持倉）
[B2 Codex 完整回覆]

### 輪動分析（板塊 + 個股）
[B3 Codex 完整回覆]

---
**值得追蹤的新機會：** [從 B2 挑 1-2 個 Codex 也認同的]
**輪動 actionable：** [從 B3 挑 1-2 條 Codex 也認同的調倉操作]
```

### 進階：`--codex-adversarial`（opt-in 壓力測試）

僅當 arguments 含 `--codex-adversarial` 時，**追加**對立面審查段落（攻擊組合論點、找弱點）。預設 `--codex` 不執行。

> 若 Codex 失敗 → 輸出 `⚠️ Codex 不可用：[error]，跳過第二意見`，繼續正常輸出。

---

## Output Format
Use clean markdown tables. Keep it concise but comprehensive. All dollar amounts in USD.
Use Traditional Chinese (繁體中文) for all text output to match the user's preference.

## Performance Notes
- The full report with G section will make many MCP calls. Expect 2-3 minutes for a 20-stock portfolio.
- If the user wants a quick report, they can say "快速報告" to skip section G.
- Fetch stock_info once per ticker and reuse data across G2 and G3 sections.
