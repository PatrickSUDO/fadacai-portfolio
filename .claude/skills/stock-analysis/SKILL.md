---
name: stock-analysis
description: Analyze a stock ticker with fundamentals, technicals, analyst ratings, and investment thesis. Usage - /stock-analysis TICKER or /stock-analysis TICKER1 TICKER2 for comparison.
user_invocable: true
model: claude-opus-4-8
---

# Stock Analysis

> 💡 模型指引：session context **< 100k** → `/model sonnet`；**> 100k** → 先 `/compact` 再 Sonnet，或直接 `/model opus`（長 context 推理品質 Opus 更穩定）。重大決策（>5% 倉位）一律用 Opus。

Generate a standardized research report for one or more stock tickers.

## Step 0: 分析前準備

### 預設模式（無 `--current`）— 純獨立分析
- **跳過** plan.md、feedback/*.md、持倉、journal 偵測
- 分析不考慮現有倉位或投資計畫，僅基於公開市場數據
- **保留 Step 0e**：Verdict 之前必須完成「核心 thesis / 證偽條件 / 機率分布」三題

### Step 0.5 (共用): Macro + Earnings + Fundamentals Cache Load

讀以下四份 cache：
- `briefing-out/cache/macro-snapshot.json` — 用於 Step 0e 第一性檢查的 macro ground state
- `briefing-out/cache/earnings-history.json` — 該 TICKER 的 trailing 8Q beat rate + surprise
- `briefing-out/cache/earnings-dates.json` — 該 TICKER 的下次 earnings 日期
- `briefing-out/cache/fundamentals-snapshot.json`（TTL 24h）— TICKER 的三錨點輸入（pe_ratio/peg_ratio/wall_street_target/growth/margins）+ `forward_estimates`（賣方共識 fwdEPS curr_fy/next_fy + EPS 修正動能）

若 TICKER **不在** earnings cache 中（如新標的）→ 跑一次 `python3 tools/earnings_history.py --force`；或標 `(earnings cache miss)`。

fundamentals cache 處理：
- TICKER 在 cache 且 mtime < 30h → **使用**，供三錨點估值 + probability agent 1d/1h
- TICKER 不在 cache 或 mtime > 30h → **先跑 `python3 tools/fetch_fundamentals.py --ticker TICKER`**（單票 fetch + merge 進 cache，含 A4 `self_valuation`），再讀 cache。**這樣 cache miss/stale 也能取得 A4**，不再直接標 `(self-val N/A)`。Agent 3 仍同批抓 `get_fundamentals_snapshot` + `get_earnings_history` 作即時三錨點交叉（fetch_fundamentals 失敗時的 fallback）。
- 只有 `fetch_fundamentals --ticker` **真的失敗**（EODHD 無資料/token 缺）才標 `(self-val N/A)`。
- `pe_ratio == 0.0 / null` → 丟棄 A1 錨；`peg_ratio == 0.0 / null` → 丟棄 A2 錨，標 `(anchor unavailable)`

這些 cache 資料用於：
- Section「Investment Thesis」: 引用 trailing 8Q beat rate 強化/弱化基本面論點
- Section「三錨點公允價」: A1/A2/A3 錨點計算 Fair PE + EV（取代手寫點估計）
- Section「Verdict」前呼叫 `probability-honesty-checker` 時，**強制**將 macro + base rate 帶入 prompt（Step 1d、1h、1i 必填）

### `--current` 模式 — 整合持倉與計畫
啟用後執行完整 CLAUDE.md Step 0 統一規範（0a → 0b → 0c → 0d → 0e）：
- 讀 `plan.md` + `feedback/*.md`；了解此標的在計畫中的角色
- 呼叫 `get_account_position` 取即時持倉
- 今日 journal 不存在 → 執行 gap-fill + 變動偵測 + 自動建立 journal
- 報告額外輸出「持倉確認」與「配置計畫定位」兩節

---

## Arguments
- Single ticker: `/stock-analysis PLTR`
- Multiple tickers for comparison: `/stock-analysis DCO AIR`
- With specific focus: `/stock-analysis TEAM options` (include options strategy suggestions)
- With portfolio context: `/stock-analysis MU --current` (activates plan.md + positions)
- With Codex second opinion: `/stock-analysis MU --codex` or `/stock-analysis MU --2nd`
- Combined: `/stock-analysis MU --current --codex`

## Workflow

1. **Parse the ticker(s)** from the arguments

2. **Gather Data** using MCP tools and WebSearch:

   **Primary: Yahoo Finance MCP**
   - `mcp__yfinance-advanced__get_stock_info` — fundamentals, analyst targets, margins, PE ratios
   - `mcp__yfinance-advanced__get_financial_statement` (income_stmt) — revenue, earnings trends
   - `mcp__yfinance-advanced__get_recommendations` (recommendations) — analyst consensus
   - `mcp__yfinance-advanced__get_yahoo_finance_news` — recent headlines
   - `mcp__yfinance-advanced__get_historical_stock_prices` (period=6mo) — price trend

   **Secondary: SEC EDGAR MCP** (for deeper analysis)
   - `mcp__sec-edgar-mcp__get_financials` (statement_type="all") — official SEC financial data
   - `mcp__sec-edgar-mcp__get_insider_transactions` (days=90) — insider buying/selling
   - `mcp__sec-edgar-mcp__get_recent_filings` (days=60) — recent 8-K, 10-K/Q filings
   - `mcp__sec-edgar-mcp__get_segment_data` — revenue breakdown by geography/product

   **Technical: Technical Indicators MCP**
   - `mcp__technical-mcp__get_technical_indicators` — RSI, MACD, Bollinger Bands, ATR, momentum score, trend
   - `mcp__technical-mcp__get_support_resistance` — support/resistance levels, 52-week range

   **Sentiment: EODHD MCP**
   - `mcp__eodhd-mcp__get_news_sentiment` — news with AI sentiment scores
   - `mcp__eodhd-mcp__get_sentiment_trend` — 30-day sentiment trajectory

   **Tertiary: FMP MCP** (free tier, supplementary)
   - `mcp__fmp-mcp__getStockPeers` — peer companies for comparison
   - `mcp__fmp-mcp__getCompanyProfile` — company profile (fallback if yfinance incomplete)

   **Supplementary: WebSearch** (if MCP data is insufficient)
   - Search: "[TICKER] stock analysis 2026"
   - Search: "[TICKER] earnings revenue growth"

   **平行數據收集（Agent 子代理 — subagent_type: "data-collector"）：**

   使用 Agent tool 平行派遣以下 3 組子代理（每組指定 subagent_type: "data-collector"，自動使用 Sonnet 4.6 純數據收集）：

   - **Agent 1 — Yahoo Finance**（subagent_type: "data-collector"）：`get_stock_info` + `get_financial_statement` + `get_recommendations` + `get_yahoo_finance_news` + `get_historical_stock_prices`
   - **Agent 2 — SEC EDGAR**（subagent_type: "data-collector"）：`get_financials`（all）+ `get_insider_transactions`（90d）+ `get_recent_filings`（60d）+ `get_segment_data`
   - **Agent 3 — Technical + Sentiment + EODHD Fundamentals**（subagent_type: "data-collector"）：`get_technical_indicators` + `get_support_resistance` + `get_sentiment_trend` + `get_news_sentiment`（ticker format: TICKER.US）；**若 fundamentals cache miss 或 mtime > 30h**，同批加抓 `mcp__eodhd-mcp__get_fundamentals_snapshot(TICKER.US)` + `mcp__eodhd-mcp__get_earnings_history(TICKER.US)`（不額外 round-trip）

   多股比較時，為每個 ticker 各派一組 Agent。若 Agent tool 不可用，依序呼叫亦可。

   ⚠️ **Agent 失敗 fallback**：若 Agent 3（Technical）回傳空結果或聲稱「沒有 MCP 權限」，主 Claude 直接呼叫 `mcp__technical-mcp__get_technical_indicators` + `mcp__technical-mcp__get_support_resistance` + `mcp__eodhd-mcp__get_sentiment_trend`，絕不跳過技術分析 section。

3. **Check Current Portfolio**（`--current` 模式才執行）
   - 呼叫 `get_account_position` 確認是否持有此標的
   - 若持有，在報告開頭輸出「持倉確認」段落（成本、口數、損益）

4a. **Thesis Ledger 雙向整合（`--current` 或有持倉時執行；新標的分析只做「寫」端）**

### 讀端（consumer）— 了解「上次的論點驗證了沒」

```
python3 tools/thesis_ledger.py list --ticker TICKER
```

輸出「📋 {TICKER} 既有 thesis 狀態」段落：
```
| thesis slug | 命題 | 建立 | 狀態 | 上次 resolve 結果 | 公允價 before→after | 價格影響 | 下一步 |
|------------|------|------|------|-----------------|---------------------|---------|------|
| memory-cycle | DRAM ASP上漲... | 2026-01-10 | pending | — | — | — | 等 Q2財報 |
| q1-guide-exec | Q1 guide確認... | 2026-02-01 | passed | AI revenue +6% | $460→$490 | +6.5% | HOLD |
```
若帳本無此 ticker → 輸出「📋 {TICKER} 帳本：無既有 thesis」

若有 **today-due** thesis（`due` 命令輸出中出現此 ticker）→ 在此段末尾標：
`⚠️ 今日到期 thesis：{slug} — 請在本次分析後執行 D2 三桶分解 + resolve`

**如果有到期需驗收的 thesis，執行 D2：**
- 從本次 Agent 數據抓實際指標（財報數字/分析師 PT/毛利率等）
- 照 briefing Step 0.7 邏輯做 passed/failed/partial 三桶分解
- 呼叫 `resolve` 帶結構化旗標（`--fair-value-before` 從上次登錄時的公允價基準取，或從 history 最後一筆取）

### 寫端（producer）— 本次分析的新 thesis 登錄（Verdict 後執行）

凡 Verdict 含**明確時間/事件觸發點**的論點，在輸出末尾登錄：
```
python3 tools/thesis_ledger.py list --ticker TICKER   # 先查既有 slug
python3 tools/thesis_ledger.py add --ticker TICKER --slug <slug> \
  --thesis "<可驗證命題>" --falsification "<條件1>" "<條件2>" \
  --trigger-type event|date --trigger-date YYYY-MM-DD \
  [--event earnings] [--metric "到期要比的指標"] --source stock-analysis \
  --ev "<EV snapshot: bull/base/bear 公允價>"
```
新增 `--ev` 時同時記錄當下基準公允價（= `fair_value_before` 的基準，日後 resolve 時用）

4b. **訊號擷取 & Thesis 候選（Signal Extraction，stock-analysis 預設開）**

> 目的：從 news body + SEC 8-K + 財報逐字稿抽**已量化陳述**，用以補強/修正 thesis 機率分布輸入（Step 0e）。

**反幻覺門檻（必守）：** 每個 signal 必須附 `raw_quote`（≤120 字逐字引用）；無 quote → 無 signal；只有 narrative → 明寫「無可量化信號（only narrative）」。

**資料管道優先順序：**
1. SEC 8-K（Agent 2 `analyze_8k` / `get_recent_filings` 14d 內）→ `confidence: high`
2. 財報逐字稿（`mcp__fmp-mcp__getEarningsTranscript` 最新一份，取 capex/ASP/wafer/utilization 句）→ `confidence: high`；僅財報後 30 天內
3. EODHD raw news body（`news-articles.json` Step 0.67，或 `mcp__eodhd-mcp__get_news` 即時抓）→ `confidence: medium`
4. FMP segment（`mcp__fmp-mcp__getRevenueProductSegmentation`）→ `confidence: medium`（有數字才算）

**訊號 record（Claude 輸出，不寫 JSON cache）：**
```
metric: wafer_starts / capex / ASP_QoQ / segment_revenue / utilization / ...
value: "+8% QoQ"（逐字含單位）
direction: up | down | flat
ticker, source_url_or_desc, source_type: sec_8k | transcript | news | fmp_segment
date, confidence: high | medium | low
raw_quote: "<逐字引用，≤120 字>"    ← 無此欄 = 不成立
```

**Signal → Thesis 轉換後登錄（`confidence ∈ {high, medium}` 且有明確前瞻 trigger）：**
```
python3 tools/thesis_ledger.py list --ticker <T>   # 先查重
python3 tools/thesis_ledger.py add --ticker <T> --slug <slug> \
  --thesis "<1句可驗證命題>" \
  --falsification "<條件1>" "<條件2>" "<條件3>" \
  --trigger-type event|date --trigger-date YYYY-MM-DD \
  --event earnings --metric "<到期要比的指標>" \
  --source signal-inference \
  --ev "signal: <metric> <value>, <source>, conf=<confidence>"
```
`confidence=low` 或純 paraphrase → 在報告文字呈現即可，**不入 ledger**。exit-code-2 碰撞 → 改 slug 或 supersede。

**輸出段落（報告末尾）：**
```
### §4b 訊號擷取
| metric | value | dir | source | confidence | raw_quote（首 80 字） |
|--------|-------|-----|--------|------------|----------------------|
| wafer_starts | +8% QoQ | up | Reuters/EODHD | medium | "...逐字引用..." |

THESIS 候選：[若有 high/medium conf 訊號]
- slug: wafer-starts-bit-growth → 已登錄 thesis_ledger
[若無]
- 無可量化信號（only narrative news，無 SEC 8-K / 逐字稿量化句）
```

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
| RSI (14) | XX.X | 數值列示（不標超買；<30 可標 Oversold） |
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

**Entry Timing（revision 閘門 — per `feedback/momentum-valuation-symmetry.md`；RSI 過高不進任何判定）：**
- **estimate 上修中**（`forward_estimates` revisions up ≫ down）的加速領導者：**不否決、不等回檔才給方向** — 強者愈強；starter 倉現在進 + 回檔 GTC ladder + bull call spread 定義風險參與
- **estimate 翻下修/flat + 高倍數**：唯一「不追」的正當情況（均值回歸 edge 只在此成立）
- 深跌至支撐 + **revision 未惡化**：洗盤錯殺，加碼機會（RSI < 30 可作超賣佐證）；revision 惡化中 → 受損 turnaround，等催化不接刀
- High ATR regime: wider stop-loss needed, consider smaller position
- 原則：**revision 定方向，估值只定下手結構與 size**；RSI 僅數值列示，過高側不觸發任何「不追/減碼」判定

### SEC EDGAR Insights
- Insider Trading (90 days): net buying/selling activity
- Recent Filings: any material 8-K events, 10-K/Q highlights
- Revenue Segments: geographic/product breakdown (if available)

### 市場情緒 (Sentiment)
Use `mcp__eodhd-mcp__get_sentiment_trend` and `mcp__eodhd-mcp__get_news_sentiment`.

- Sentiment trend: improving / declining / stable (30-day trajectory)
- 7-day vs 30-day average sentiment comparison
- Recent news headlines with sentiment polarity scores
- Flag strongly negative sentiment (< -0.3) as risk factor

### Peer Comparison (FMP)
- Top 5 peers by market cap similarity

### Investment Context（獨立分析）
- 所屬板塊 / 主題（AI、半導體、SaaS、基建…）
- 在同類股中的競爭定位（leader / challenger / niche）
- 一般性倉位建議（不參考個人帳戶）：進取型 / 穩健型各建議比例

### 配置計畫定位（`--current` 模式才輸出）
- 此標的是否在 plan.md 待建倉/加碼清單中？
- 與現有持倉是否重疊？
- 計畫建議的進場方式：現股 vs Bull Put Spread vs LEAPS（引用計畫原文）
- 建議倉位佔帳戶 %
- **桶別建議（必填）**：進場後歸 🔵 信念桶（中低 β + 多年結構 thesis → 讓 run）/ 🟢 認列循環桶（高 β >3 / 純週期 / 純波段 → 系統性 harvest）/ 🟡 L1 On-Deck（thesis 已驗證但等觸發）/ 🔵 L2 Research Pool（thesis 未驗證完）。疑問時歸認列桶
- **機會成本閘門（新倉必答）**：此標的是否**明顯優於目前最弱的在倉名額**？（列出最弱在倉 1-2 檔 revision/動能對比）。組合在 14–18 上緣 → 必須指名砍誰進場（砍一進一，不淨增）；相關 beta 門檻最高，去相關 hedge/填缺口門檻較低
- **進場結構（對稱性）**：貼高加速領導者 → starter + 回檔 ladder + bull call spread；支撐區 → GTC 限價階梯 / bull put spread；長期信念 → LEAPS deep ITM delta 0.80–0.88。結尾附可掛的 Firstrade 單（per `feedback/actionable-firstrade-orders.md`）

### 第一性檢查（必填，在 Verdict 之前）
- **核心 thesis：** [1 句可驗證命題，非 narrative]
- **證偽條件：** [2-3 個 falsifiable 觀察點 — 量化指標 / 事件 / 時程]

**三錨點 Fair PE 計算（D1，必做）：**

| 錨點 | 值 | 說明 |
|------|----|------|
| A1 市場 PE | EODHD `pe_ratio` | 0.0/null → N/A |
| A2 PEG 錨 | `peg_ratio × growth%`（AI龍頭 PEG基準=1.5，其餘=1.0） | 0.0/null → N/A |
| A3 分析師錨 | `wall_street_target ÷ fwdEPS`；fwdEPS 優先 `forward_estimates.curr_fy.eps_avg`（真實共識）→ `next_fy.eps_avg` → `eps_ttm×(1+growth)` 近似 | 任一缺 → N/A |
| **A4 自建錨（分歧）** | `self_valuation.own_target_price`（cache miss/stale 已由 `fetch_fundamentals.py --ticker` 補抓）| `unavailable`（真失敗才）→ `(self-val N/A)`；`low` → `⚠️低信心`；**A4 不進 median，不進 EV — 僅做分歧 flag** |

- **基準 Fair PE** = median(A1, A2, A3)（A4 排除在外）；**樂觀** = max × 1.25（上限 current_PE × 1.25）；**悲觀** = min × 0.70
- **FwdEPS 情境**：基準=analyst 共識 fwdEPS（`forward_estimates.curr_fy.eps_avg`，缺則 next_fy，再缺才用 `eps_ttm×(1+growth)` 近似；cache `self_valuation.a3_fwdeps_source` 已標來源）；樂觀=基準×(1+min(avg_surprise%,15%))；悲觀=基準×(1−5%/10%)
- **EPS 修正動能**：`forward_estimates` 另帶 `eps_revision_30d_pct` + `revisions_up/down_30d`，30 日共識上修=guidance 偏正領先訊號，供 thesis/P3 引用（非估值輸入）
- stock-analysis 單股深度**每次都做 DCF 交叉**，改用**自建 `tools/simple_dcf.py`**（FMP free tier 無 getDCFValuation）：把 Agent 1 yfinance 已抓的數字餵進去——
  ```bash
  python3 tools/simple_dcf.py --fcf <freeCashflow> --shares <sharesOutstanding> \
    --cash <totalCash> --debt <totalDebt> --growth <forward EPS/rev 成長小數> [--wacc 0.10] [--terminal 0.03]
  ```
  回 `intrinsic_value_per_share`。FCF≤0 → 工具自動回 N/A（標 `DCF 不適用（FCF 為負）`）。**DCF 僅 sanity flag，不進 EV**；高成長股 terminal 佔比常 >70%（工具會回 `terminal_pct_of_ev`），偏離大時註明「假設敏感、參考性低」。FMP getDCFValuation 僅作備援（通常 402）。

- **機率分布：**

  | 情境 | 機率 | FwdEPS | A1 | A2 | A3 | Fair PE | 公允價 |
  |------|------|--------|-----|-----|-----|---------|--------|
  | 樂觀 | XX% | $X | XX | XX | XX | XX（max×1.25） | $XXX |
  | 基準 | XX% | $X | — | — | — | XX（median） | $XXX |
  | 悲觀 | XX% | $X | XX | XX | XX | XX（min×0.70） | $XXX |

  Expected value = Σ(機率 × 公允價) = $XXX → vs 現價 $XXX：±X%

  DCF 交叉（`simple_dcf.py` 自建，必做）：`DCF: $XXX vs 基準公允 $XXX（差 ±X%）；terminal 佔 EV X%`（FCF<0 → `DCF 不適用`）

- **A4 自建分歧（必顯示）：**
  - A4 目標價：`$XXX`（信心：`ok` / `⚠️低信心` / `(self-val N/A)`）
  - A4 vs A3：`(A4 − A3) / A3 = ±X%`
  - 解讀（|分歧| > 20% 才說）：
    - A4 > A3 + 20%：「我的營收/利潤推估較 Street 樂觀 — 檢查是否有市場未定價的成長催化」
    - A4 < A3 − 20%：「我的推估較 Street 保守 — 分析師可能過樂觀，注意下修風險」
    - |分歧| ≤ 20%：「自建估值與 Street 大致吻合」
  - **Note**：A4vsA3 分歧隔離「EPS/盈利觀」差異（倍數相同），不混入估值倍數變動。

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

**核心原則：Codex 不看 Claude 的結論**，只給 raw data，讓它獨立跑 Step 0e。Claude 與 Codex 兩個獨立輸出並排比較，真實共識 = 高信心，真實分歧 = 值得深入。

**🔴 Prompt 中性化要求**（詳見 `feedback/codex-prompt-neutrality.md`）：

raw data 必須是 fact 數值，**不能** 是 derived label。技術面只給 RSI 純數字、MACD 三個 line/signal/histogram 數值、價格 vs SMA 百分比、6-12 週區間，**不寫**：
- trend 分類（strong_uptrend / weak_downtrend / consolidation）
- status 分類（overbought / oversold / neutral）
- momentum_score（這已是 derived score，改寫成「N 個交易日累計漲跌 X%」）
- 「弱勢」「強勢」「拋物線」「打底」等敘事標籤

讓 Codex 自己跑 indicator interpretation，從 raw 數值推導結論。**用戶 push back 後重做時，新 prompt 必須完全去除舊 framing**，不能寫「之前判斷 X，請重新評估」。

呼叫 Codex（**用 CLAUDE.md「Codex 呼叫方式」的 `codex exec` CLI；勿用 codex:codex-rescue subagent / `/codex:rescue`，會卡 superpowers preamble**），prompt 首行加強制 no-tool 指令，模板：

```
我是一名美股投資人，使用 Level 2 options + Spread 的 margin 帳戶。
請對 [TICKER] 個股，**完全獨立**執行 Step 0e 第一性分析 — 不要受任何先前結論或 framing 影響，這是一份獨立第二意見。

**Raw data（只給 fact 數值，無 derived label）：**

**估值（純數字 — 三錨點原始值，讓 Codex 自行推導 Fair PE）：**
- 現價：$XXX
- Trailing PE：XX / Forward PE：XX / PEG：X.X / P/S：X.X / EV/EBITDA：XX
- Forward EPS：$X.XX / FY 估算 EPS：$X.XX
- 分析師 median PT：$XXX
- EODHD earnings base rate：N/8 beat, avg_surprise X.X%（或 unreliable-low-base）
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

**內部人交易（90 天）：** [N] 筆 Form 4，[X 筆 buy / X 筆 sell]，金額摘要 — 不寫「警訊」「正常」分類

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

3. **機率分布表（三錨點 Fair PE，自行推導不依賴 Claude 的計算）：**

   先導出你自己的三錨點：
   - A1 = Trailing PE（市場隱含）
   - A2 = PEG × growth%（成長合理倍數；AI 龍頭 PEG=1.5，其餘=1.0）
   - A3 = 分析師 median PT ÷ fwdEPS（賣方共識隱含）
   - base = median(A1,A2,A3)；bull = max × 1.25（上限 current_PE × 1.25）；bear = min × 0.70

   | 情境 | 機率 | FwdEPS | Fair PE（推導方式） | 公允價 |
   |------|------|--------|-----------------|--------|
   | 樂觀 | XX% | $X | XX（A?錨 × 1.25） | $XXX |
   | 基準 | XX% | $X | XX（median） | $XXX |
   | 悲觀 | XX% | $X | XX（A?錨 × 0.70） | $XXX |

   Expected Value = Σ(機率 × 公允價) = $XXX → vs 現價 $XXX：±X%

4. **Verdict**（1 句）：Strong Buy / Buy / Hold / Sell / Avoid，並說明 conditional 在什麼前提。

5. **加分題：用戶持倉建議**（持有 / 加碼 / 減碼 / 出清？加碼/停損觸發點？）

**規則：**
- 機率分布必須 sum 到 100%
- Verdict 必須有可量化條件
- 不假設 Claude 已說過什麼
- 用客觀數據與你自己的 mental model 從 raw 數值自行 derive interpretation
- 若 ticker 在 ±48h earnings window，特別考慮「earnings sell-on-news」vs「thesis 破裂」的根因區分

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

### 並排比較：Claude vs Codex（獨立輸出）

| 維度 | Claude | Codex | 一致性 |
|------|--------|-------|--------|
| 核心 thesis | [Claude] | [Codex] | 一致 / 部分 / 顯著 |
| 證偽條件數 | N | N | — |
| 機率分布（樂/基/悲）| XX/XX/XX | XX/XX/XX | 差異 |
| Expected Value | $XXX | $XXX | 差 ±X% |
| 現價 vs EV | ±X% | ±X% | — |
| Verdict | [Claude] | [Codex] | 同 / 異 |

**真實共識**（兩邊獨立都認同）：[1-2 條 — 高信心結論]
**真實分歧**（兩邊獨立得出不同結論）：[1-3 條 — 值得深入]
**整合建議：** [基於真實共識給出最終行動，明示不確定性來源]
```

### 進階：`--codex-adversarial`（opt-in 壓力測試）

僅當 arguments 含 `--codex-adversarial` 或 `--codex-adv` 時，**追加**對立面審查段落（攻擊 thesis、找 bug）。預設 `--codex` 不執行。

```
[追加段落 — 只在 --codex-adversarial 時觸發]
請對 Claude 的 [TICKER] 結論進行對立面審查 — 攻擊 thesis、找最弱假設、提出 dissenting verdict。
[Claude 完整 thesis + verdict + technical analysis]
請以繁體中文回覆。
```

> 若 Codex 失敗 → 輸出 `⚠️ Codex 不可用：[error]，跳過第二意見`，繼續正常輸出。

---

## Output Language
Use Traditional Chinese (繁體中文) for all text output.

## 存檔 + HTML 生成
報告完成後：
1. 使用 Write tool 把完整 markdown 寫到 `briefing-out/stock-analysis-<TICKER>-YYYY-MM-DD.md`
2. 執行：
```bash
python3 tools/generate_html.py stock-analysis briefing-out/stock-analysis-<TICKER>-YYYY-MM-DD.md --push
```
成功時印出網頁連結，失敗（repo 尚未建立）時印警告並繼續。
