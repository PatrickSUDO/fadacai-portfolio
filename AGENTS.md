# 台股基本面配置研究 - Project Instructions

## Project Overview
This is an investment research and portfolio management workspace for the **Taiwan stock market (台股)**. The user actively trades 台股（上市/上櫃）現股 and 台指期/選擇權 / 個股期貨, with live positions connected via the `shioaji-server` MCP (永豐金 Shioaji as the reference broker integration).

## Language & Format
- **All output in Traditional Chinese (繁體中文)**
- 個股一律用「代號 + 簡稱」格式（如 `2330 台積電`、`2454 聯發科`）
- Thread/social media posts: plain text only, NO markdown, NO tables
- Reports and analysis: markdown tables are fine
- 金額單位：新台幣（NT$ / 元）；張（1 張 = 1,000 股）、零股、口數（期/選）需明確標示

## Workflow
1. `/briefing` — quick daily check (~1 min); `/briefing full` (~3 min); `/briefing deep` (~5 min)
   - `/briefing telegram` — Telegram push tier (~2-3 min)：收盤推送專用，產出 briefing-out/ 兩個檔案
   - `--send` 旗標（任何 tier 可加）：執行完後推送 Telegram + email 副本
   - 例：`/briefing telegram --send`、`/briefing full --send`
   - launchd 每個 TWSE 交易日台灣時間 14:00 自動執行 `/briefing telegram --send`（週五加 `--codex`）
   - Setup 文件：`docs/briefing-auto-send.md`
2. `/portfolio-review` — full deep report with live data via MCP
3. `/stock-analysis 代號` — individual stock deep dive
4. `/options-strategy 標的 STRATEGY` — 台指期/選擇權計算 (supports multi-ticker comparison)
5. `/trade-journal log|review|summary|auto` — trade records
6. `/mcp-health` — test all MCP server connections

### Codex 第二意見（opt-in `--codex` / `--2nd`）

Add `--codex` to any of the above (except `/mcp-health`, `/trade-journal`) to append a Codex second-opinion section:

- **B1. 獨立第一性分析（預設）** — Codex 在**不知道 Claude 結論**的情況下，獨立執行 Step 0e（thesis / 證偽條件 / 機率分布 / EV / Verdict），只給它 raw data。然後 Claude 與 Codex 兩個獨立輸出**並排比較**，找出真實共識 vs 真實分歧。所有 5 個 skill 適用。
- **B2. 機會掃描** (`/codex:rescue`) — surface hot themes/tickers not in current portfolio. `/briefing full/deep`, `/portfolio-review`, `/todo` only.
- **B3. 輪動分析** (`/codex:rescue`) — sector + stock rotation (leading/lagging vs 加權指數 TAIEX, 法人資金流, 3 actionable rotation moves). Same 3 skills.

#### 為什麼預設用「獨立第一性」而不是「對立面審查」

舊版 B1 是 `/codex:adversarial-review`（攻擊 thesis），這是 **confirmation bias by design**：要它找 bug 它一定找出 bug，即使 thesis 完全成立。結果是兩邊「分歧」很多但大部分由 framing 製造，不是真實見解衝突。

獨立第一性分析讓 Claude 和 Codex 從同樣 raw data 出發、各自跑 Step 0e、不知道對方結論。**真實共識 = 高信心**；**真實分歧 = 值得深入的學習點**。

#### 進階：`--codex-adversarial`（opt-in 壓力測試）

若需要對「兩邊已對齊的結論」做進一步壓力測試（例如重大資金決策前），可改用 `--codex-adversarial`（或 `--codex-adv`）觸發舊版對立面審查。**僅在有意識需要 attacker mode 時使用**，預設 `--codex` 不跑 adversarial。

**Prerequisite:** Install plugin once with `/plugin marketplace add openai/codex-plugin-cc` → `/plugin install codex@openai-codex` → `/reload-plugins` → `/codex:setup`.

## Key Files
- `plan.md` — 投資計畫（板塊目標、策略佇列、觀察清單、策略原則）— 只在用戶要求時更新
- `journal/` — 每日交易日誌（YYYY-MM-DD.md），含完整倉位快照
- `feedback/` — 交易風格偏好，所有 skills 每次必讀
- `research/` — 投資論文與研究筆記

## Step 0 統一規範（所有 skills 共用）

### 0a. 每次必做
- 讀取 `plan.md` — 了解策略佇列與板塊目標
- 讀取 `feedback/*.md` — 套用交易風格偏好

### 0b. 取得即時持倉
- 呼叫 `mcp__shioaji-server__get_account_position`

### 0c. 今日 journal 確認
- 若 `journal/YYYY-MM-DD.md`（今日）已存在 → 跳過偵測
- 若不存在 → 執行 gap-fill + 變動偵測（見下方）

### 0d. Gap-fill 邏輯
- 讀取 `journal/` 最新檔案作為「前」
- 若距上次 journal > 3 個交易日：先建立銜接條目（標記 `⚠️ gap-fill`，列出時間範圍）
- 比較「前」vs 即時持倉，輸出差異（🆕新建倉/🔴清倉/📈加碼/📉減碼）
- 自動建立今日 journal，含完整倉位快照

### 0e. 第一性原理紀律（Verdict / Recommendation / Action 前必做）

在輸出任何投資結論之前，**強制**回答三個第一性問題（First-Principles Discipline）：

1. **核心 thesis 是什麼？**
   - 用 1 句可驗證的陳述句（**非 narrative，非 adjective**）
   - ❌ 反例：「AI 帶動需求」「股票超買」「題材熱絡」
   - ✅ 範例：「CoWoS 先進封裝產能 2024→2026 從 ~15k 增至 ~70k wpm，台積電 capex 指引上修，先進封裝營收占比 2026 上看雙位數」

2. **這個 thesis 在什麼條件下會被證偽？**
   - 列出 2-3 個 **falsifiable 觀察點**（可量化的指標、事件、時程）
   - ❌ 反例：「市況不好就錯」
   - ✅ 範例：「下次法說 CoWoS 產能指引下修、月營收連 2 月 YoY 轉負、北美雲端資本支出下修 >10%」

3. **目前 Verdict 在多大機率上 conditional 在 thesis 成立？**
   - 給**機率分布而非單點**（不寫「可能會漲」而是 60% 看多 / 25% 中性 / 15% 看空）
   - 算 expected value：Σ(機率 × 各情境公允價)，與現價比較
   - **強制呼叫 `probability-honesty-checker` agent**（見下方）— 不可手動套機率

**為什麼這條重要：**
- Claude 的分析、Codex 的 adversarial review 都會帶 framing 偏差
- narrative 層的辯論（「該買 vs 該避」）永遠分歧，第一性是繞開兩者的 ground truth
- 連續做不到這三題 = Verdict 是 narrative + heuristic + framing 的產物，不可靠

**⚠️ 機率分布強制流程（briefing / portfolio-review / stock-analysis / todo 適用）：**

凡輸出機率分布或 EV，必須先呼叫：

```
Agent(subagent_type: "probability-honesty-checker", prompt: "...")
```

或對組合整體用 `/ev-check [horizon]`。Agent 會強制執行 6 步流程：
1. Input Enumeration（8 項齊全才能進下一步）
2. 形狀反推（從事實 mapping，禁止 default bell shape）
3. 各 catalyst 的 conditional 機率（顯式 base rate）
4. Aggregated 三情境合成（sum check = 100%）
5. EV 顯式 Σ 計算（中點 = 區間算術平均）
6. Self-audit checklist 全勾

**禁止偷懶寫法**（Agent 與主 skill 都不可寫）：
- ❌ 30/45/25、35/45/20、20/45/35、25/50/25（default mirror shape，無依據時禁用）
- ❌ 「略偏多」「略偏空」「中性偏多」「應該會」「不確定性高」（質性語言）
- ❌ 跳過 Input Enumeration 直接給機率
- ❌ EV 寫成文字而非顯式 Σ 數字

**輸出格式（所有 Verdict 前置）：**
```
### 第一性檢查
- **核心 thesis：** [1 句可驗證命題]
- **證偽條件：** [2-3 個 falsifiable 觀察點]
- **機率分布：** [由 probability-honesty-checker agent 算出，含 8 項輸入 + 形狀反推 + EV Σ]
```

用戶 push back「你真的有算嗎」時的處理：
- 不辯解、不重組原數字
- 重跑 agent，明確要求 audit checklist 全勾
- 發現原本確實偷懶 → 老實承認 + 顯示新算（見 feedback/probability-distribution-honesty.md）

**⚠️ Agent 註冊限制（重要）：**
- Claude Code session 啟動時載入 `.claude/agents/` 目錄，**session 內新增的 agent 檔案不會被動態 picked up**
- 若呼叫返回 `Agent type 'X' not found`：(1) 確認檔案在 `.claude/agents/X.md`，(2) 該 session 暫時用 workaround，(3) 下次 session 自動載入

**Workaround：當 probability-honesty-checker agent 不可用時**
直接呼叫 `general-purpose` agent，並把 `.claude/agents/probability-honesty-checker.md` 的內容當 prompt 前綴傳入：

```
Agent(
  subagent_type: "general-purpose",
  prompt: "<貼上 probability-honesty-checker.md 從 '# Probability Honesty Checker' 開始的全部內容>

  ---

  以下是本次任務的輸入：

  [Step 1 九項輸入...]
  [額外 context...]

  請按 6 步流程執行。"
)
```

紀律不打折 — 6 步 + audit checklist 全勾的要求對 general-purpose agent 同樣適用。

### 0f. Thesis Ledger（thesis 追蹤與到期驗收）

第一性檢查產出的可驗證 thesis 不是寫完就忘 — 凡帶**明確時間/事件觸發點**的 thesis（「請在法說/月營收公布/N 日後檢視 X」）都登錄到帳本 `research/thesis-ledger.json`，到期自動回頭抓實際數字驗收（passed/failed/partial），結果驅動下一步 actionable。

- 工具：`tools/thesis_ledger.py`（去重、碰撞攔截、到期/過期掃描、狀態轉換、統計全在程式層，**Claude 不手改 JSON**）
- 去重 key = `ticker:slug`；同 key 但 thesis 差太多 → exit code 2 碰撞，改 slug 或 `supersede`
- 逾期 >30 天未驗收 → 自動 `expired`（當作無結果，不算命中率分母）
- **驗收（每次 briefing / portfolio-review 自動跑）**：`thesis_ledger.py due` → 對到期項抓數判定 → `resolve`；抓不到新數 → `reschedule` 不猜 verdict
- **登錄（briefing / portfolio-review 收尾）**：`list` 看既有 slug → `add`
- **台股特有觸發點**：月營收公布（每月 10 日前）、季報截止（Q1 5/15、Q2 8/14、Q3 11/14、年報 3/31）、法人說明會、除權息日
- 詳見 `docs/thesis-ledger.md`

## Auto Journal Detection（SessionStart Hook）
每次對話開始時，hook 會輸出今日 journal 狀態：
- `⚡ 今日尚無 journal，自動執行倉位偵測` → 執行 Step 0c/0d，建立 journal，完成後以 1 行通知用戶，繼續處理原始請求
- `✅ 今日 journal 已存在` → 略過偵測

## Investment Style
- 主軸：AI/半導體供應鏈（晶圓代工、IC 設計、CoWoS/先進封裝、ABF 載板、散熱、PCB、伺服器代工、光通訊、記憶體）、高成長科技（無板塊上限，單一個股 > 10% 才提醒）
- 避險/平衡：高股息（金融、電信）、傳產龍頭、原物料/航運（小比例平衡）
- Strategies: 台指期/小台（TX/MTX）多空與避險、台指選擇權（TXO）賣方價外 put/call、Bull Put Spread、Bull Call Spread、Covered Calls、個股期貨（替代現股）
- Risk: 單一持倉 > 10% flagged as over-concentrated；留意漲跌幅 10% 限制、處置股/注意股

## MCP Tools Available
- `mcp__shioaji-server__*` — live 永豐金 Shioaji account data (positions, balance, settlements, quotes, watchlists)
  - `get_account_position` — real-time 現股 + 期貨/選擇權 positions (replaces current-position.md)
  - `get_account_balance` — account equity and cash（含交割款）
  - `get_account_history` — 成交/委託 history
  - `get_single_quote` / `get_watchlist_quote` — real-time quotes（含五檔、漲跌幅）
- `mcp__finmind-server__*` — 台股報價、財報、月營收、法人買賣超、分點籌碼 (primary; stock_id 純 4 碼如 "2330")
- `mcp__mops-server__*` — 公開資訊觀測站 MOPS：重大訊息、法說會、月營收公告、IFRS 財報、內部人持股申報、庫藏股
- `mcp__twse-server__*` — 證交所/櫃買開放 API：同類股、漲跌幅排行、產業分類、三大法人買賣超總表、融資融券餘額
- `mcp__technical-mcp__*` — technical indicators (RSI, MACD, Bollinger Bands, ATR, momentum score, support/resistance)
  - `get_technical_indicators(ticker, period)` — full single-ticker analysis
  - `get_support_resistance(ticker, period)` — S/R levels + 52W range
  - `get_batch_indicators(tickers, period)` — compact multi-ticker summary
- `mcp__chip-server__*` — 籌碼面 / 聰明錢部位 (TWSE/TAIFEX 開放資料, read-only)
  - `get_institutional_netbuy(ticker, days)` — 三大法人（外資/投信/自營）買賣超
  - `get_futures_oi()` — 台指期未平倉（三大法人 + 大額交易人多空）
- `mcp__cnyes-news__*` — 中文財經新聞 + LLM 情緒 (stock_id format: "2330")
  - `get_news_sentiment(ticker, days, limit)` — news with 中文 sentiment scores
  - `get_sentiment_trend(ticker, days)` — aggregated daily sentiment trajectory (-1 to +1)
- Use parallel agent dispatch for batch data fetching across multiple tickers

## MCP Retry & Fallback Policy
- Any MCP tool call that fails → retry up to **3 times**
- 3 次都失敗 → call that server's health test (single simple tool) to diagnose:
  - shioaji-server: `get_account_balance()`
  - finmind-server: `get_stock_info("2330")`
  - mops-server: `get_company_info("2330")`
  - twse-server: `get_industry_list()`
  - technical-mcp: `get_technical_indicators("2330")`
  - cnyes-news: `get_sentiment_trend("2330", 7)`
  - chip-server: `get_institutional_netbuy("2330", 5)`
- Health test also fails → fallback to WebSearch/WebFetch for equivalent data
- 在輸出中標記 "⚠️ [server] MCP 不可用，使用替代數據源"

## Research Boundaries
- 不主動研究用戶未要求的付費 API/服務
- FinMind free tier 請求上限已記錄，不嘗試超量輪詢

## Permission Protection
- 不覆蓋/刪除 `.claude.json` 中現有 allow rules
- 只 append 新權限，並向用戶展示新增內容

## Skill 模型分工（2026-05-05）

### 數據收集 subagent — Haiku 4.5
所有 skill 的平行數據收集 Agent 都指定 `subagent_type: "data-collector"`（見 `.claude/agents/data-collector.md`）。
Data-collector 每次啟動是全新 context（無歷史），Haiku 完全勝任純 MCP 抓資料工作。

### 主 skill 執行模型（2026-06-13 更新：全面回歸 Opus 4.8）

模型階梯：**Opus 4.8**（`claude-opus-4-8`，$15/$75，旗艦推理）> **Sonnet 4.6**（中堅）> **Haiku 4.5**（純機械）。

| Skill / 任務 | 模型 | 理由 |
|---|---|---|
| `/ev-check` | **Opus 4.8** | 純第一性機率分布 + EV，反偷懶紀律最吃推理 |
| `/portfolio-review` | **Opus 4.8** | 跨全組合綜合 + 風險 + EV，驅動資金決策 |
| `/briefing deep` | **Opus 4.8** | 深度合成 + Codex 整合 + 機率/EV |
| `/stock-analysis` | **Opus 4.8** | 單標的深掘，旗艦推理 |
| `/options-strategy` | **Opus 4.8** | Greeks / 價差計算 + 多腿比較 |
| `/briefing full` | **Opus 4.8** | 中等綜合 + Verdict |
| `/briefing`（quick）| **Sonnet 4.6** | ~1min 彙整 |
| `/briefing telegram` | **Sonnet 4.6** | 每日 launchd 自動推送，成本敏感 |
| `/todo` | **Sonnet 4.6** | 行動清單 |
| `/trade-journal` review/summary | **Sonnet 4.6** | 帶輕度分析 |
| `/trade-journal` log | **Haiku 4.5** | 純記錄/格式化（frontmatter 預設 Sonnet，log 可降 Haiku）|
| `/mcp-health` | **Haiku 4.5** | 純連線測試 |
| data-collector subagent | **Haiku 4.5** | 純 MCP 抓資料 |
| probability-honesty-checker subagent | **Opus 4.8** | 機率紀律執法者，用旗艦 |

**長 context：** session > 100k 時先 `/compact`，再繼續執行。換主題先 `/clear`。

**手動切換：** skill frontmatter `model:` 已聲明；若 harness 未自動套用，用 `/model opus`、`/model sonnet`、`/model haiku` 切換後再呼叫。
