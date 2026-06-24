---
name: stock-analysis
description: Analyze a stock ticker with fundamentals, technicals, analyst ratings, and investment thesis. Usage - /stock-analysis TICKER or /stock-analysis TICKER1 TICKER2 for comparison.
user_invocable: true
model: claude-fable-5
---

# Stock Analysis

> 💡 模型指引：session context **< 100k** → `/model sonnet`；**> 100k** → 先 `/compact` 再 Sonnet，或直接 `/model opus`（長 context 推理品質 Opus 更穩定）。重大決策（>5% 倉位）一律用 Opus。

Generate a standardized research report for one or more stock tickers.

## Step 0: 分析前準備

### 預設模式（無 `--current`）— 純獨立分析
- **跳過** plan.md、feedback/*.md、持倉、journal 偵測
- 分析不考慮現有倉位或投資計畫，僅基於公開市場數據
- **保留 Step 0e**：Verdict 之前必須完成「核心 thesis / 證偽條件 / 機率分布」三題

### Step 0.5 (共用): Macro + Earnings Cache Load

讀以下三份 cache（由 `tools/fetch_macro.py` 與 `tools/earnings_history.py` 預載）：
- `briefing-out/cache/macro-snapshot.json` — 用於 Step 0e 第一性檢查的 macro ground state
- `briefing-out/cache/earnings-history.json` — 該 TICKER 的 trailing 8Q beat rate + surprise
- `briefing-out/cache/earnings-dates.json` — 該 TICKER 的下次 earnings 日期

若 TICKER **不在** earnings cache 中（如新標的）→ 跑一次 `python3 tools/earnings_history.py --force`（會包含當前 ticker 因為 SKILL 會把它加進 `EARNINGS_TICKERS` env 暫時 override）；或標 `(earnings cache miss)`。

這些 cache 資料用於：
- Section「Investment Thesis」: 引用 trailing 8Q beat rate 強化/弱化基本面論點
- Section「Verdict」前呼叫 `probability-honesty-checker` 時，**強制**將 macro + base rate 帶入 prompt（Step 1d、1i 必填）

### `--current` 模式 — 整合持倉與計畫
啟用後執行完整 AGENTS.md Step 0 統一規範（0a → 0b → 0c → 0d → 0e）：
- 讀 `plan.md` + `feedback/*.md`；了解此標的在計畫中的角色
- 呼叫 `get_account_position` 取即時持倉
- 今日 journal 不存在 → 執行 gap-fill + 變動偵測 + 自動建立 journal
- 報告額外輸出「持倉確認」與「配置計畫定位」兩節

---

## Arguments
- Single ticker: `/stock-analysis 3661 世芯-KW`
- Multiple tickers for comparison: `/stock-analysis 3034 聯詠 3661 世芯-KW`
- With specific focus: `/stock-analysis 2454 聯發科 options` (include options strategy suggestions)
- With portfolio context: `/stock-analysis 3661 世芯-KW --current` (activates plan.md + positions)
- With Codex second opinion: `/stock-analysis 3661 世芯-KW --codex` or `/stock-analysis 3661 世芯-KW --2nd`
- Combined: `/stock-analysis 3661 世芯-KW --current --codex`

## Workflow

1. **Parse the ticker(s)** from the arguments

2. **Gather Data** using MCP tools and WebSearch:

   **Primary: FinMind MCP**
   - `mcp__finmind-server__get_stock_info` — fundamentals, analyst targets, margins, PE ratios
   - `mcp__finmind-server__get_financial_statement` (income_stmt) — revenue, earnings trends
   - `mcp__finmind-server__get_recommendations` (recommendations) — analyst consensus
   - `mcp__finmind-server__get_finmind_finance_news` — recent headlines
   - `mcp__finmind-server__get_historical_stock_prices` (period=6mo) — price trend

   **Secondary: 公開資訊觀測站 MOPS MCP** (for deeper analysis)
   - `mcp__mops-server__get_financials` (statement_type="all") — official MOPS financial data
   - `mcp__mops-server__get_insider_transactions` (days=90) — insider buying/selling
   - `mcp__mops-server__get_recent_filings` (days=60) — recent 重訊, 季報/年報
   - `mcp__mops-server__get_segment_data` — revenue breakdown by geography/product

   **Technical: Technical Indicators MCP**
   - `mcp__technical-mcp__get_technical_indicators` — RSI, MACD, Bollinger Bands, ATR, momentum score, trend
   - `mcp__technical-mcp__get_support_resistance` — support/resistance levels, 52-week range

   **Sentiment: FinMind MCP**
   - `mcp__cnyes-news__get_news_sentiment` — news with AI sentiment scores
   - `mcp__cnyes-news__get_sentiment_trend` — 30-day sentiment trajectory

   **Tertiary: twse MCP** (free tier, supplementary)
   - `mcp__twse-server__getStockPeers` — peer companies for comparison
   - `mcp__twse-server__getCompanyProfile` — company profile (fallback if FinMind incomplete)

   **Supplementary: WebSearch** (if MCP data is insufficient)
   - Search: "[TICKER] stock analysis 2026"
   - Search: "[TICKER] earnings revenue growth"

   **平行數據收集（Agent 子代理 — subagent_type: "data-collector"）：**

   使用 Agent tool 平行派遣以下 3 組子代理（每組指定 subagent_type: "data-collector"，自動使用 Haiku 4.5 純數據收集）：

   - **Agent 1 — FinMind**（subagent_type: "data-collector"）：`get_stock_info` + `get_financial_statement` + `get_recommendations` + `get_finmind_finance_news` + `get_historical_stock_prices`
   - **Agent 2 — 公開資訊觀測站 MOPS**（subagent_type: "data-collector"）：`get_financials`（all）+ `get_insider_transactions`（90d）+ `get_recent_filings`（60d）+ `get_segment_data`
   - **Agent 3 — Technical + Sentiment**（subagent_type: "data-collector"）：`get_technical_indicators` + `get_support_resistance` + `get_sentiment_trend` + `get_news_sentiment`

   多股比較時，為每個 ticker 各派一組 Agent。若 Agent tool 不可用，依序呼叫亦可。

3. **Check Current Portfolio**（`--current` 模式才執行）
   - 呼叫 `get_account_position` 確認是否持有此標的
   - 若持有，在報告開頭輸出「持倉確認」段落（成本、口數、損益）

4. **Generate Report** for each ticker:

### Standard Report Format

```markdown
## [TICKER] - [Company Name] ($XX.XX)
**Sector:** [sector] | **Market Cap:** $XXB | **Forward PE:** XX.X

### Key Metrics
| Metric | Value |
|--------|-------|
| Revenue (TTM) | $X.XB |
| Revenue Growth (YoY) | XX% |
| EPS (TTM) | $X.XX |
| EPS Growth | XX% |
| Forward PE | XX.X |
| PEG Ratio | X.XX |
| Gross Margin | XX% |
| Free Cash Flow | $XM |
| Debt/Equity | X.XX |

### Investment Thesis
- Bull case (2-3 points)
- Bear case (2-3 points)

### Analyst Consensus
- Rating: Buy/Hold/Sell
- Price Target Range: $XX - $XX
- Median Target: $XX (upside/downside %)

### Technical Analysis
Use `mcp__technical-mcp__get_technical_indicators` and `mcp__technical-mcp__get_support_resistance`.

| Indicator | Value | Signal |
|-----------|-------|--------|
| RSI (14) | XX.X | Overbought/Neutral/Oversold |
| MACD | line/signal/histogram | Golden Cross/Death Cross/None |
| Bollinger %B | X.XX | Upper/Middle/Lower band |
| ATR (normalized) | X.X% | Low/Medium/High volatility |
| Momentum Score | XX | -100 to +100 |
| Trend | description | |
| Volume Ratio | X.XX | Above/Below average |

**Support & Resistance:**
| Level Type | Price | Distance % |
|------------|-------|-----------|
| Resistance 1 | $XX.XX | +X.X% |
| Support 1 | $XX.XX | -X.X% |
| 52W High | $XX.XX | -X.X% |
| 52W Low | $XX.XX | +X.X% |

**Entry Timing:**
- RSI > 70: avoid chasing, wait for pullback
- RSI < 30 + near support: potential entry opportunity
- High ATR regime: wider stop-loss needed, consider smaller position

### 公開資訊觀測站 MOPS Insights
- Insider Trading (90 days): net buying/selling activity
- Recent Filings: any material 重訊 events, 10-K/Q highlights
- Revenue Segments: geographic/product breakdown (if available)

### 市場情緒 (Sentiment)
Use `mcp__cnyes-news__get_sentiment_trend` and `mcp__cnyes-news__get_news_sentiment`.

- Sentiment trend: improving / declining / stable (30-day trajectory)
- 7-day vs 30-day average sentiment comparison
- Recent news headlines with sentiment polarity scores
- Flag strongly negative sentiment (< -0.3) as risk factor

### Peer Comparison (twse)
- Top 5 peers by market cap similarity

### Investment Context（獨立分析）
- 所屬板塊 / 主題（AI、半導體、SaaS、基建…）
- 在同類股中的競爭定位（leader / challenger / niche）
- 一般性倉位建議（不參考個人帳戶）：進取型 / 穩健型各建議比例

### 配置計畫定位（`--current` 模式才輸出）
- 此標的是否在 plan.md 待建倉/加碼清單中？
- 與現有持倉是否重疊？
- 計畫建議的進場方式：現股 vs Bull Put Spread vs 個股期貨（引用計畫原文）
- 建議倉位佔帳戶 %

### 第一性檢查（必填，在 Verdict 之前）
- **核心 thesis：** [1 句可驗證命題，非 narrative]
- **證偽條件：** [2-3 個 falsifiable 觀察點 — 量化指標 / 事件 / 時程]
- **機率分布：**

  | 情境 | 機率 | Forward EPS | Fair PE | 公允價 |
  |------|------|------------|--------|--------|
  | 樂觀 | XX% | $X | XX | $XXX |
  | 基準 | XX% | $X | XX | $XXX |
  | 悲觀 | XX% | $X | XX | $XXX |

  Expected value = Σ(機率 × 公允價) = $XXX  → vs 現價 $XXX：±X%

### Verdict
One of: Strong Buy / Buy / Hold / Sell / Avoid
With 1-2 sentence rationale，明確說 Verdict conditional on thesis 成立的機率。
```

5. **If comparing multiple tickers**, add a comparison table at the end:

| Metric | TICKER1 | TICKER2 |
|--------|---------|---------|

With a clear recommendation on which to prefer.

---

## Step 6: Codex 第二意見（opt-in）

**僅當 arguments 含 `--codex` 或 `--2nd` 時執行。**

### B1. 獨立第一性分析（預設，independent first-principles）

**核心原則：Codex 不看 Codex 的結論**，只給 raw data，讓它獨立跑 Step 0e。Codex 與 Codex 兩個獨立輸出並排比較，真實共識 = 高信心，真實分歧 = 值得深入。

**🔴 Prompt 中性化要求**（詳見 `feedback/codex-prompt-neutrality.md`）：

raw data 必須是 fact 數值，**不能** 是 derived label。技術面只給 RSI 純數字、MACD 三個 line/signal/histogram 數值、價格 vs SMA 百分比、6-12 週區間，**不寫**：
- trend 分類（strong_uptrend / weak_downtrend / consolidation）
- status 分類（overbought / oversold / neutral）
- momentum_score（這已是 derived score，改寫成「N 個交易日累計漲跌 X%」）
- 「弱勢」「強勢」「拋物線」「打底」等敘事標籤

讓 Codex 自己跑 indicator interpretation，從 raw 數值推導結論。**用戶 push back 後重做時，新 prompt 必須完全去除舊 framing**，不能寫「之前判斷 X，請重新評估」。

呼叫 Codex（`subagent_type: "codex:codex-rescue"`），prompt 模板：

```
我是一名美股投資人，使用 Level 2 options + Spread 的 margin 帳戶。
請對 [TICKER] 個股，**完全獨立**執行 Step 0e 第一性分析 — 不要受任何先前結論或 framing 影響，這是一份獨立第二意見。

**Raw data（只給 fact 數值，無 derived label）：**

**估值（純數字）：**
- 現價：$XXX
- PE：XX / Forward PE：XX / P/S：X.X / EV/EBITDA：XX / PEG：X.X
- Forward EPS：$X.XX / FY 估算 EPS：$X.XX
- Market Cap：$XXB

**最近財報（fact，含日期）：**
- 報告日：YYYY-MM-DD（[已過 X 天 / 即將公佈]）
- Revenue：$XXX M（YoY +X.X%，QoQ +X.X%）
- EPS：$X.XX（YoY +X.X%）
- 公司 guide / 分析師 estimate revision

**Quarterly 軌跡（最近 4-6 季 raw 數字）：**
- Q[N] [date]：Revenue $XXX M / EPS $X.XX
- ...

**Margins（最近一季 vs 前一季）：**
- Gross：XX.X% / Operating：XX.X% / Net：XX.X% / FCF：XX.X%

**資產負債：** Cash $XB / Debt $XB / Net cash position $XB / Quick ratio X.X

**分析師共識：** [N] strong buy / [N] buy / [N] hold / [N] sell / [N] strong sell；median PT $XXX；high $XXX / low $XXX

**內部人交易（90 天）：** [N] 筆 內部人持股申報，[X 筆 buy / X 筆 sell]，金額摘要 — 不寫「警訊」「正常」分類

**技術面（fact only，不分類）：**
- RSI(14)：XX.X（純數字，不標 OB/oversold）
- MACD：line X.XX / signal X.XX / histogram X.XX（不標 bullish/bearish）
- 價 vs SMA20：X.X% / 價 vs SMA50：X.X% / 價 vs SMA200：X.X%
- ATR normalized：X.X%
- 6 週價格區間：低 $XXX → 高 $XXX → 現 $XXX
- 距 52W 高：X.X% / 距 52W 低：X.X%
- 主要 supports：$XXX / $XXX / $XXX
- 主要 resistances：$XXX / $XXX

**Sentiment（30 天 raw）：** 平均 X.XX / 7d 平均 X.XX / 今日 X.XX（新聞量 N 篇）

**近期催化（事實 timeline）：** 財報日、產業事件、guidance update 等（不寫評語）

**配置上下文：**（`--current` 模式才填入）已持有 X 股 @ avg $X / 未持有；若無 --current 則省略此行

**請輸出：**

1. **核心 thesis**（1 句可驗證命題，falsifiable，非 narrative）

2. **證偽條件**（2-3 個 falsifiable 觀察點 — 量化指標 / 事件 / 時程）

3. **機率分布表：**

   | 情境 | 機率 | FY EPS | Fair PE | 公允價 |
   |------|------|-------|---------|--------|
   | 樂觀 | XX% | $X | XX | $XXX |
   | 基準 | XX% | $X | XX | $XXX |
   | 悲觀 | XX% | $X | XX | $XXX |

   Expected Value = Σ(機率 × 公允價) = $XXX → vs 現價 $XXX：±X%

4. **Verdict**（1 句）：Strong Buy / Buy / Hold / Sell / Avoid，並說明 conditional 在什麼前提。

5. **加分題：用戶持倉建議**（持有 / 加碼 / 減碼 / 出清？加碼/停損觸發點？）

**規則：**
- 機率分布必須 sum 到 100%
- Verdict 必須有可量化條件
- 不假設 Codex 已說過什麼
- 用客觀數據與你自己的 mental model 從 raw 數值自行 derive interpretation
- 若 ticker 在 ±48h 財報/月營收窗口，特別考慮「earnings sell-on-news」vs「thesis 破裂」的根因區分

請以繁體中文回覆，控制在 700 字內。

--effort high --fresh
```

### 輸出整合

```
## 🤖 Codex 第二意見（獨立第一性分析）

### Codex 獨立輸出

**核心 thesis：** [Codex 的 thesis]
**證偽條件：** [Codex 列的條件]
**機率分布：**

| 情境 | 機率 | EPS | PE | 公允價 |
|------|------|-----|-----|--------|
| 樂觀 | XX% | ... | ... | $XXX |
| 基準 | XX% | ... | ... | $XXX |
| 悲觀 | XX% | ... | ... | $XXX |

**Codex EV：** $XXX vs 現價 $XXX → ±X%
**Codex Verdict：** [...]

---

### 並排比較：Codex vs Codex（獨立輸出）

| 維度 | Codex | Codex | 一致性 |
|------|--------|-------|--------|
| 核心 thesis | [Codex] | [Codex] | 一致 / 部分 / 顯著 |
| 證偽條件數 | N | N | — |
| 機率分布（樂/基/悲）| XX/XX/XX | XX/XX/XX | 差異 |
| Expected Value | $XXX | $XXX | 差 ±X% |
| 現價 vs EV | ±X% | ±X% | — |
| Verdict | [Codex] | [Codex] | 同 / 異 |

**真實共識**（兩邊獨立都認同）：[1-2 條 — 高信心結論]
**真實分歧**（兩邊獨立得出不同結論）：[1-3 條 — 值得深入]
**整合建議：** [基於真實共識給出最終行動，明示不確定性來源]
```

### 進階：`--codex-adversarial`（opt-in 壓力測試）

僅當 arguments 含 `--codex-adversarial` 或 `--codex-adv` 時，**追加**對立面審查段落（攻擊 thesis、找 bug）。預設 `--codex` 不執行。

```
[追加段落 — 只在 --codex-adversarial 時觸發]
請對 Codex 的 [TICKER] 結論進行對立面審查 — 攻擊 thesis、找最弱假設、提出 dissenting verdict。
[Codex 完整 thesis + verdict + technical analysis]
請以繁體中文回覆。
```

> 若 Codex 失敗 → 輸出 `⚠️ Codex 不可用：[error]，跳過第二意見`，繼續正常輸出。

---

## Output Language
Use Traditional Chinese (繁體中文) for all text output.
