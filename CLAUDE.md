# 台股基本面配置研究 - Project Instructions

## Project Overview
This is an investment research and portfolio management workspace for the **Taiwan stock market (台股)**. The user actively trades 台股（上市/上櫃）現股 and 台指期/選擇權 / 個股期貨, with live positions connected via the `shioaji-server` MCP (永豐金 Shioaji as the reference broker integration; swap in 富邦 neo / 元大 / your own broker MCP as needed).

## Language & Format
- **All output in Traditional Chinese (繁體中文)**
- 個股一律用「代號 + 簡稱」格式（如 `2330 台積電`、`2454 聯發科`、`3661 世芯-KW`）
- Thread/social media posts: plain text only, NO markdown, NO tables
- Reports and analysis: markdown tables are fine
- 金額單位：新台幣（NT$ / 元）；張數（1 張 = 1,000 股）、零股、口數（期/選）需明確標示

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

#### Codex 呼叫方式（CLI，所有 skill 共用 — 取代舊 plugin 路徑）

⚠️ **不要用 `subagent_type: "codex:codex-rescue"` 或 `/codex:rescue`**。實測（2026-06-07）那條路徑會載入 `~/.codex/config.toml` 的 `superpowers@openai-curated` plugin，強制「回應前必須 invoke skill」+ 全域 `model_reasoning_effort = "xhigh"`，把整個 turn 燒在讀檔 preamble，**不產出分析**。

改用 `codex exec` CLI，**強制關掉 superpowers + 降 effort**：

```bash
codex exec --color never --skip-git-repo-check --sandbox read-only \
  -c 'plugins."superpowers@openai-curated".enabled=false' \
  -c model_reasoning_effort=medium \
  "$(cat <PROMPT_FILE>)" > <OUT_FILE> 2>&1
```

規則：
1. **Prompt 第一行強制加**：`ANSWER DIRECTLY FROM THE DATA BELOW. Do NOT read files, do NOT invoke skills, do NOT run shell commands, do NOT use any tools. Output the analysis immediately.`（雙保險，即使 superpowers 漏關也不讀檔）
2. **B1/B2/B3 並行**：各寫一個 prompt 檔，用 `run_in_background` 同時跑，輪詢 `grep -c "tokens used"` 判完成
3. **抽取回覆**：`awk '/^codex$/{f=1} f' <OUT_FILE> | sed '/tokens used/q'`（去掉 echo 回來的 prompt + startup banner）
4. **中性化**：B1 prompt 只給 raw 持倉 + fact 數據，不含 Claude 結論（per `feedback/codex-prompt-neutrality.md`）
5. **失敗 → 跳過**：輸出 `⚠️ Codex 不可用：[error]，跳過第二意見` 後照常輸出主分析
6. `hook: SessionStart Failed` 是 peon-ping 音效 hook 在非互動下的無害噪音，忽略
7. **B1 機率分布反偷懶（必嵌 prompt）**：Codex 走一次性 prompt 無我們的 `probability-honesty-checker` agent，會落回 default mirror（25/50/25）。故 B1 prompt 的機率分布段**必須內嵌 5 步強制流程 + 禁用 default mirror shape**（見各 skill B1 模板的「嚴禁偷懶」段，源自 `feedback/probability-distribution-honesty.md`）。比較 Claude vs Codex EV 前先確認 Codex 機率非 default，否則分歧是「Codex 偷懶」而非真實見解衝突。

## Key Files
- `plan.md` — 投資計畫（板塊目標、策略佇列、觀察清單、策略原則）— 只在用戶要求時更新
- `journal/` — 每日交易日誌（YYYY-MM-DD.md），含完整倉位快照
- `feedback/` — 交易風格偏好，所有 skills 每次必讀
- `research/` — 投資論文與研究筆記

## HTML 報告站工作流

每份報告輸出 markdown（source of truth）後自動轉為 HTML，push 到獨立 private repo 部署為 Netlify 靜態網站。

### 工具
```bash
python3 tools/generate_html.py briefing 2026-06-10 [--push]
python3 tools/generate_html.py portfolio-review briefing-out/portfolio-review-2026-06-07.md [--push]
python3 tools/generate_html.py stock-analysis briefing-out/stock-analysis-2330-2026-06-10.md [--push]
python3 tools/generate_html.py options-strategy briefing-out/options-strategy-TXO-2026-06-10.md [--push]
```
- 無 `--push`：只在 `briefing-out/html/` 存一份本地 HTML
- 有 `--push`：同步到 `$REPORTS_REPO_PATH` 並 git push（Netlify 自動部署）
- `send_briefing.py` 在 `--send` 流程中自動呼叫 `generate_html briefing --push`，Telegram 訊息末自動附連結

### 環境變數（.env，絕不 commit 到主 repo）
```
REPORT_SITE_TOKEN=<32-hex-token>          # URL 混淆用，等同隱私鎖
REPORT_SITE_URL=https://reports.patricksudo.com
REPORTS_REPO_PATH=/path/to/fadacai-reports  # private repo local clone
```

### 隱私原則
- Reports repo 必須是 **private**，token 只存在 .env 與 repo 目錄名
- 網站根目錄放空白 decoy index.html；所有頁面含 `noindex,nofollow` meta
- 安全標頭由 reports repo 的 `_headers` 設定（HSTS、`X-Robots-Tag: noindex`、`X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`），Netlify 部署時套用
- `cache/`、`send-log.jsonl`、`launchd.log`、codex prompt/out 等敏感快取**不上傳**到 reports repo

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
   - ❌ 反例：「AI 帶動需求」「股票超買」「題材熱絡」「外資回補」
   - ✅ 範例：「CoWoS 先進封裝產能 2024→2026 從 ~15k 增至 ~70k wpm，台積電 capex 指引上修，先進封裝營收占比 2026 上看雙位數」

2. **這個 thesis 在什麼條件下會被證偽？**
   - 列出 2-3 個 **falsifiable 觀察點**（可量化的指標、事件、時程）
   - ❌ 反例：「市況不好就錯」
   - ✅ 範例：「下次法說 CoWoS 產能指引下修、月營收連 2 月 YoY 轉負、北美雲端資本支出下修 >10%」

3. **目前 Verdict 在多大機率上 conditional 在 thesis 成立？**
   - 給**機率分布而非單點**（不寫「可能會漲」而是 60% 看多 / 25% 中性 / 15% 看空）
   - 算 expected value：Σ(機率 × 各情境公允價)，與現價比較
   - **強制呼叫 `probability-honesty-checker` agent**（見下方）— 不可手動套機率
   - **Fair PE 三錨點推導（不可手寫猜測）：** A1=FinMind `pe_ratio`（現行市場隱含本益比）；A2=`peg_ratio×成長率`（成長合理倍數，AI 半導體龍頭目標 PEG 1.5，其餘 1.0）；A3=`分析師目標價÷forward_EPS`（券商報告/FinMind 隱含）。**A3 的 base forward_EPS 取真實賣方共識：`fundamentals-snapshot.json forward_estimates.curr_fy.eps_avg`（缺→next_fy.eps_avg，再缺→`eps_ttm×(1+growth)` 近似）；cache `self_valuation.a3_fwdeps_source` 已標來源，勿手推。** 任一錨回 0.0/null → 丟棄。基準 Fair PE=median(A1,A2,A3)；樂觀=max 上限 current_PE×1.25；悲觀=min 下限 current_PE×0.70。Forward EPS：樂觀=base×(1+min(avg_surprise_pct,15%))；悲觀=base×(1−5%~10%)。
   - **台股殖利率錨（sanity check，不進 median）：** 台股重現金股利，對成熟/高息標的（金融、傳產、電信）加算 `現金殖利率 = 近 12 月現金股利 ÷ 股價`，對照個股歷史殖利率區間（如近 5 年 4%~6%）判斷貴賤；高成長股（IC 設計、CoWoS 概念）殖利率錨權重低、以成長錨為主。
   - **A4 自建錨（sanity/divergence flag，不進 median，不進 EV）：** 從 `fundamentals-snapshot.json self_valuation` 讀取（`tools/fetch_fundamentals.py` 已在 cache 計算）。`own_fwdEPS = projected_revenue × net_margin ÷ shares`，revenue 用歷史 CAGR 淡化向 8% terminal，**完全不看分析師 estimate**。`own_target_price = own_fwdEPS × base_FairPE(median(A1,A2,A3))`。`A4vsA3% = (own_target − 分析師目標價) / 分析師目標價`——隔離「我的盈利觀 vs 賣方盈利觀」（倍數固定）。`confidence=unavailable` → `(self-val N/A)`；`low` → `⚠️低信心（高波動）`；`ok` → 正常顯示。

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
- **台股特有觸發點**：月營收公布（每月 10 日前）、季報截止（Q1 5/15、Q2 8/14、Q3 11/14、年報 3/31）、法人說明會、除權息日、董監改選/減資
- **Signal-inference 來源**：從新聞 body / 重大訊息 / 法說逐字稿抽**已量化陳述**推導的 thesis，登錄時加 `--source signal-inference --ev "signal: <metric> <value>, <source>, conf=<confidence>"`。僅 `confidence ∈ {high, medium}` 且有明確前瞻 trigger + 強制 `raw_quote`（≤120 字逐字）才登錄；`low` 只在文字呈現。`stats --source signal-inference` 可量測新聞推導命中率（閉環驗證 P3 價值）。反幻覺鎖：無 raw_quote = 無 signal = 不登錄。
- **Resolve 附加估值影響欄位（選填，有數就帶）：**
  ```
  python3 tools/thesis_ledger.py resolve --id <id> --verdict passed|failed|partial \
    --actual "實際數字" --note "判讀" --next-action "操作" \
    --fair-value-before <float> --fair-value-after <float> \
    --price-impact-pct <float> --impact-decomp "thesis +X%/multiple −Z%=net −W%"
  ```
  passed→公允價上修（recompute D1 三錨點）；failed→下修；partial→拆分 thesis 成分 vs 倍數成分（impact_decomp）。數字存入 history[]，long-term queryable via stats。
- 詳見 `docs/thesis-ledger.md`

## Auto Journal Detection（SessionStart Hook）
每次對話開始時，hook 會輸出今日 journal 狀態：
- `⚡ 今日尚無 journal，自動執行倉位偵測` → 執行 Step 0c/0d，建立 journal，完成後以 1 行通知用戶，繼續處理原始請求
- `✅ 今日 journal 已存在` → 略過偵測

## Investment Style
- 主軸：AI/半導體供應鏈（晶圓代工、IC 設計、CoWoS/先進封裝、ABF 載板、散熱、PCB、伺服器代工/組裝、光通訊、記憶體）、高成長科技（無板塊上限，單一個股 > 10% 才提醒）
- 避險/平衡：高股息（金融、電信）、傳產龍頭、原物料/航運（小比例平衡）
- 衍生品策略：台指期/小台（TX/MTX）多空與避險、台指選擇權（TXO）賣方價外 put/call、買權/賣權價差（Bull Put / Bull Call Spread）、Covered Call、個股期貨（替代現股、降資金佔用）
- Risk: 單一持倉 > 10% flagged as over-concentrated；留意台股漲跌幅 10% 限制、處置股（分盤交易）、注意股/警示股

### 執行底層邏輯：Portfolio as a Business（強制濾鏡）
任何 Verdict / Action / 倉位建議都先過這套濾鏡（源 `research/新手開局.md`，操作規範 `feedback/realized-pnl-business-model.md`，Step 0a 已含必讀）：
- **績效看 Realized PnL，不看 Unrealized** — 只認列獲利、虧損掛庫存；目標 Realized ≈ 4× |未實現虧損|。反過來 = 爆倉訊號要 flag。
- **Swing Risk 首要監測**（= 帳上最高未實現利潤 + 潛在回吐；選擇權 = 權利金 + 未實現利潤）；肥利潤未落袋要主動提示系統性落袋。
- **Offsetting 沖銷失誤而非利潤；禁「砍 loser 加碼 winner」**（四錯：認列虧損 / 過度暴險 / Beta 失衡 / 分散化打折）。
- **Rolling → Adjusted Risk → Risk-Free State**：落袋用 Adjusted Risk 視角（新倉真實風險 = size − 累積已認列），不是「賣了就少賺」。
- **Pre-emptive（非止損式）風險管理 + Scenario Planning**；慎用台指 Put / 期貨空單對沖（漲了變反向認列虧損 = Double-Kill）。
- **定位先行**；**主動組合支數 14–18（理想 14–16），>18 砍一進一不淨增**，>30 無益。
- **分桶**：每倉位歸 🔵信念桶（讓它 run、只在 thesis 破或 >10% 才動）或 🟢認列循環桶（高 β/週期/肥利潤 → 系統性 harvest）；疑問時歸認列。
- **兩層候補**：🟡L1 On-Deck（thesis 驗證+觸發明確，補空位只從 L1 拉）/ 🔵L2 Research Pool（需修復或擴 Universe）；砍倉依砍因歸層（組合理由→L1，thesis 破→L2）。
- **機會成本閘門（桶間升級/降級/部署皆強制）**：新倉須明顯優於最弱在倉名額才進 — 相關 beta 門檻最高（須擠掉弱倉、不淨增），無相關 hedge/填缺口門檻較低；14–18 上緣時砍一進一。
- **即時 roster（信念/認列/L1/L2 名單）權威來源 = `plan.md`「組合架構 v2」**；改動 roster 同步更新該節。

## MCP Tools Available
- `mcp__shioaji-server__*` — live 永豐金 Shioaji account data (positions, balance, settlements, quotes, watchlists)
  - `get_account_position` — real-time 現股 + 期貨/選擇權 positions (replaces current-position.md)
  - `get_account_balance` — account equity and cash（含交割款）
  - `get_account_history` — 成交/委託 history
  - `get_single_quote` / `get_watchlist_quote` — real-time quotes（含五檔、漲跌幅）
- `mcp__finmind-server__*` — 台股報價、財報、月營收、法人買賣超、分點籌碼 (primary market data; stock_id 純 4 碼如 "2330")
- `mcp__mops-server__*` — 公開資訊觀測站 MOPS：重大訊息(重訊)、法人說明會、月營收公告、IFRS 財報、內部人持股轉讓/股權異動申報、庫藏股
- `mcp__twse-server__*` — 證交所/櫃買開放 API：同類股、漲跌幅排行、產業分類、三大法人買賣超總表、融資融券餘額
- `mcp__technical-mcp__*` — technical indicators (RSI, MACD, Bollinger Bands, ATR, momentum score, support/resistance)；OHLC 來源改 FinMind / yfinance `.TW`(上市)/`.TWO`(上櫃)
  - `get_technical_indicators(ticker, period)` — full single-ticker analysis
  - `get_support_resistance(ticker, period)` — S/R levels + 52W range
  - `get_batch_indicators(tickers, period)` — compact multi-ticker summary
- `mcp__chip-server__*` — 籌碼面 / 聰明錢部位 (TWSE/TAIFEX 開放資料)
  - `get_institutional_netbuy(ticker, days)` — 三大法人（外資/投信/自營）買賣超
  - `get_margin_balance(ticker, days)` — 融資融券餘額 + 券資比
  - `get_futures_oi()` — 台指期未平倉（三大法人 + 大額交易人多空）
- `mcp__cnyes-news__*` — 中文財經新聞 (ticker format: "2330")
  - `get_news(ticker, days, limit)` — **raw news articles with full body** (鉅亨/經濟日報/工商), symbols[], tags[], sentiment. Use when you need article body for P3 signal extraction (晶圓投片/capex/ASP/月營收 data). Also cached daily by `tools/fetch_news.py` → `briefing-out/cache/news-articles.json` (TTL 6h, top 8 articles/ticker, 600-char excerpts).
  - `get_news_sentiment(ticker, days, limit)` — news with LLM 中文 sentiment scores
  - `get_sentiment_trend(ticker, days)` — aggregated daily sentiment trajectory (-1 to +1)
  - `get_fundamentals_snapshot(ticker)` — **one-call valuation bundle**: 本益比/PEG/淨利率/ROE/eps_ttm/revenue_ttm/月營收 YoY/季營收 YoY/分析師目標價/評等/52w/beta/SMA/現金殖利率。Known data gaps: pe_ratio=0.0/peg=0.0 → drop that anchor. stock_id format: "2330"
  - `get_earnings_history(ticker, quarters)` — trailing 8Q EPS 季增/年增 + beat base-rate（台股無正式 guidance，以財報達成 vs 賣方預估近似）: `{beat_pct, avg_surprise_pct, beats, quarters_counted}` + next_report_date。**Primary source for probability-honesty-checker Step 1d.** Caveat: avg_surprise_pct 對低 EPS 基期股可能失真 — use beat COUNT, not avg%; cross-check vs local earnings-history.json cache
  - `get_monthly_revenue(ticker, months)` — **台股特有**：每月 10 日前公布的月營收 YoY/MoM + 累計營收 YoY。最高頻 catalyst，feeds probability-honesty-checker Step 1d/1h
  - `get_macro_indicator(indicator, limit)` — 台灣總經時間序列（央行重貼現率、CPI YoY、10年公債殖利率、USD/TWD、外銷訂單、台指 VIX）。**Regime context only**
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
- FinMind free tier 有每日/每分鐘請求上限，已記錄，不嘗試超量輪詢

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
