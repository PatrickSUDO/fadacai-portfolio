# Fundamental Allocation Study - Project Instructions

## Project Overview
This is an investment research and portfolio management workspace. The user actively trades US stocks and options on a Level 2 options margin brokerage account (connected via the `firstrade-server` MCP as the reference broker integration).

## Language & Format
- **All output in Traditional Chinese (繁體中文)**
- Thread/social media posts: plain text only, NO markdown, NO tables
- Reports and analysis: markdown tables are fine

## Workflow
1. `/briefing` — quick daily check (~1 min); `/briefing full` (~3 min); `/briefing deep` (~5 min)
   - `/briefing telegram` — Telegram push tier (~2-3 min)：盤中推送專用，產出 briefing-out/ 兩個檔案
   - `--send` 旗標（任何 tier 可加）：執行完後推送 Telegram + email 副本
   - 例：`/briefing telegram --send`、`/briefing full --send`
   - launchd 每個交易日 CEST 17:00 自動執行 `/briefing telegram --send`（週五加 `--codex`）；runner 固定 `--model sonnet`（`BRIEFING_MODEL` 覆寫）、重試 5 次（2026-08-05 五修：API mid-stream 斷流連殺對策）。三次以上全滅 → 互動 session 手動 `/briefing telegram --send` 補發（dedup 防重複）
   - Setup 文件：`docs/briefing-auto-send.md`
2. `/portfolio-review` — full deep report with live data via MCP
3. `/stock-analysis TICKER` — individual stock deep dive
4. `/options-strategy TICKER STRATEGY` — options calculation (supports multi-ticker comparison)
5. `/trade-journal log|review|summary|auto` — trade records
6. `/mcp-health` — test all MCP server connections
7. `/event-vol-scan [days] [TICKER ...]` — 財報/CPI/FOMC 前末日 buy call / 雙買 straddle 機會掃描（引擎 `tools/event_vol_scan.py`；賣方策略不適用、仍守財報 ±48h 禁令）
8. `/trade-review [2w|4w|since YYYY-MM-DD]` — **每兩週交易檢討（自我進化引擎）**：歸因每筆成交是「系統決策」還是「脫離 plan 的自主決策」，算**三個並列指標**、驗影子訊號、更新 `feedback/RULES-LEDGER.md` 規則命中率，輸出「本期該改哪一條規則」。引擎 `tools/trade_ledger.py`；briefing 距上次 >14 天會提醒。**每期加跑帳戶級四指標**（期間報酬/CAGR/MDD/Sharpe + profit factor）：`tools/account_metrics.py scan && report --live <即時總值>`（淨值標記刮自 journal/briefing 快照，2026-06-01 起；FIFO 已實現含選擇權）
   - **交易 α**（`score`）：進出對不對。β 對**實際使用的基準回歸**算（半導體對 SMH、其餘對 SPY）——用券商 β（對大盤測）套 SMH 會嚴重過度調整，結論會反過來
   - **持有 α**（`holding-alpha`）：該不該繼續抱。滾動窗 + 建倉至今。**沒有這項，純交易指標會獎勵頻繁進出、把「抱對」記為零貢獻**；首測持有 α 量級大於交易 α
   - **beta capture**（`beta-capture`）：行情好的時候吃到沒有。拆基準上漲/下跌日各自回歸 β；**up-β < down-β = 漲不上跌得凶**。梯級停利 + 買梯會機械性壓低 up-capture，這是純 α 看不見的成本
8. PMCC 收租候選掃描 — `python3 tools/pmcc_scan.py`（5 因子計分卡機械化，規則 `feedback/pmcc-candidate-discipline.md`；每次 `/portfolio-review` Section I.6 自動跑，找「想留但不看好大漲」的名字轉 poor man's covered call；判斷層留給 `/options-strategy`）

### Codex 第二意見（opt-in `--codex` / `--2nd`）

Add `--codex` to any of the above (except `/mcp-health`, `/trade-journal`) to append a Codex second-opinion section:

- **B1. 獨立第一性分析（預設）** — Codex 在**不知道 Claude 結論**的情況下，獨立執行 Step 0e（thesis / 證偽條件 / 機率分布 / EV / Verdict），只給它 raw data。然後 Claude 與 Codex 兩個獨立輸出**並排比較**，找出真實共識 vs 真實分歧。所有 5 個 skill 適用。
- **B2. 機會掃描** (`/codex:rescue`) — surface hot themes/tickers not in current portfolio. `/briefing full/deep`, `/portfolio-review`, `/todo` only.
- **B3. 輪動分析** (`/codex:rescue`) — sector + stock rotation (leading/lagging vs SPY, money flow, 3 actionable rotation moves). Same 3 skills.

獨立第一性（而非對立面審查）是預設，因為 attacker mode 是 confirmation bias by design——要它找 bug 它一定找出 bug，分歧多半是 framing 製造的。兩邊盲跑同樣 raw data：真實共識 = 高信心，真實分歧 = 學習點。

#### 進階：`--codex-adversarial`（opt-in 壓力測試）

若需要對「兩邊已對齊的結論」做進一步壓力測試（例如重大資金決策前），可改用 `--codex-adversarial`（或 `--codex-adv`）觸發舊版對立面審查。**僅在有意識需要 attacker mode 時使用**，預設 `--codex` 不跑 adversarial。

#### Codex 呼叫方式（CLI，所有 skill 共用 — 取代舊 plugin 路徑）

⚠️ **不要用 `subagent_type: "codex:codex-rescue"` 或 `/codex:rescue`**。實測（2026-06-07）那條路徑會載入 `~/.codex/config.toml` 的 `superpowers@openai-curated` plugin，強制「回應前必須 invoke skill」+ 全域 `model_reasoning_effort = "xhigh"`，把整個 turn 燒在讀檔 preamble，**不產出分析**。

改用 `codex exec` CLI，**強制關掉 superpowers + 顯式指定 effort**：

```bash
codex exec --color never --skip-git-repo-check --sandbox read-only \
  -c 'plugins."superpowers@openai-curated".enabled=false' \
  -c model_reasoning_effort=xhigh \
  "$(cat <PROMPT_FILE>)" > <OUT_FILE> 2>&1
```

（2026-07-30 用戶指定升 xhigh：當初鎖 medium 是防「superpowers 未關 + xhigh」把 turn 燒在讀檔 preamble；模板已強制關 plugin，xhigh 安全，代價是 B1/B2/B3 執行時間拉長，背景並行跑不阻塞主分析）

規則：
1. **Prompt 第一行強制加**：`ANSWER DIRECTLY FROM THE DATA BELOW. Do NOT read files, do NOT invoke skills, do NOT run shell commands, do NOT use any tools. Output the analysis immediately.`（雙保險，即使 superpowers 漏關也不讀檔）
2. **B1/B2/B3 並行**：各寫一個 prompt 檔，用 `run_in_background` 同時跑，輪詢 `grep -c "tokens used"` 判完成
3. **抽取回覆**：`awk '/^codex$/{f=1} f' <OUT_FILE> | sed '/tokens used/q'`（去掉 echo 回來的 prompt + startup banner）
4. **中性化**：B1 prompt 只給 raw 持倉 + fact 數據，不含 Claude 結論（per `feedback/codex-prompt-neutrality.md`）
5. **失敗 → 跳過**：輸出 `⚠️ Codex 不可用：[error]，跳過第二意見` 後照常輸出主分析
6. `hook: SessionStart Failed` 是 peon-ping 音效 hook 在非互動下的無害噪音，忽略
7. **B1 機率分布反偷懶（必嵌 prompt）**：Codex 走一次性 prompt 無我們的 `probability-honesty-checker` agent，會落回 default mirror（25/50/25）。故 B1 prompt 的機率分布段**必須內嵌 5 步強制流程 + 禁用 default mirror shape**（見各 skill B1 模板的「嚴禁偷懶」段，源自 `feedback/probability-distribution-honesty.md`）。比較 Claude vs Codex EV 前先確認 Codex 機率非 default，否則分歧是「Codex 偷懶」而非真實見解衝突。

## Key Files
- `plan.md` — **狀態版（2026-09-02 重建）**：三條硬線 + 持倉表生成區（`tools/position_guard.py --render-plan` 自動寫入，禁手改）+ 唯一一張候補表 + R19 pair 追蹤。手改只限候補表與硬線，且只在用戶要求時。歷史決策全文 `research/plan-history.md`（凍結）
- `research/roster.json` — **桶別唯一資料源**（信念/認列/sleeve/樂透）；每檔持倉必須登記，否則 guard 報缺口；改桶別改這裡不改散文
- `tools/position_guard.py` — **持倉守門**（briefing Step 0.75 / trade-review 5.5 每次跑）：Firstrade live 持倉 → R14 天數、R23 arm/線/警報自動掛撤、R8 GTC 缺口、>10% 硬線、檔數上限、財報窗、桶別缺口、旗標逾期 → `research/position-state.json` + plan.md 標記區；exit 2 = 有缺口，逐條進 Key Alerts
- `journal/` — 每日交易日誌（YYYY-MM-DD.md），含完整倉位快照
- `feedback/` — 交易風格偏好，所有 skills 每次必讀
- `feedback/RULES-LEDGER.md` — **規則自己的命中率帳本**（失效 ≥2 次 → 強制覆審）；由 `/trade-review` 每兩週更新；巧合欄與一致性檢查 `tools/rule_stats.py ledger-audit [--write|--check]`，產出檢查 `tools/review_lint.py`，判準 `feedback/skill-vs-luck.md`（R26 放棄條件 2028-09-06 裁決）
- `research/` — 投資論文與研究筆記
- `research/trade-ledger.jsonl` — 結構化成交帳（含 `origin` 誰決定 / `exec_via` 怎麼下單）；工具 `tools/trade_ledger.py`
- `research/order-registry.json` — 在掛單快照累積（券商只回在掛單，斷天補不回來 → briefing 每次 `snapshot-orders`）
- `research/shadow-signals.jsonl` — 影子訊號旗標（記錄不阻擋）；工具 `tools/shadow_signals.py`。兩類 signal：A4 高估旗標（`flag` 自動掃）+ **R18 財報窗被擋加碼**（`block --ticker X --price Y --size Z --note "..."` 手動登錄——凡財報窗禁令實際擋下一個想做的加碼，同一次必登錄；`score` 30 天熟成後驗「被擋的買進是否跑輸基準」，見 `feedback/earnings-reaction-window.md` C 段）
- `research/ev-ledger.jsonl` — **EV 分布事前登錄帳（機率校準自驗）**；工具 `tools/ev_ledger.py add/resolve-due/stats`。stock-analysis / ev-check 收尾 `add`（機率+三情境公允價+EV 原樣入帳），briefing 到期 `resolve-due` 機械驗價（個股 yfinance / PORTFOLIO 對 equity-marks，零判斷），/trade-review 每期讀 `stats`（EV 誤差 by horizon/model、Brier、校準表）。**修正只進 prompt/規則層（RULES-LEDGER 帶命中率），不建 ML 模型 — n>150 筆獨立已解決樣本前不重評**（2026-08-03 設計裁決：小 n + 高相關標的 + Goodhart 風險）
- `research/last-trade-review.txt` — 上次交易檻討日期（briefing 據此算 >14 天到期提醒）
- `research/position-flags.json` — **未結旗標登記（欠一個決定的部位）**。工具 `tools/trade_ledger.py flag/defer/resolve-flag/flags`
- `briefing-out/cache/archive/YYYY-MM-DD/` — **每日決策輸入凍結快照**（fundamentals/macro/news/earnings/pmcc/leading）。工具 `tools/archive_cache.py`，briefing_runner 自動跑，保留 120 天日快照 + 之後每月首日
- `research/leading-config.json` — **發現層先行指標配置**（cross-read 鏈、pricing 關鍵字/symbols、SMH 寬度成分、台股月營收清單、decel 閾值）；改持倉/鏈/閾值時手動編輯，`tools/fetch_leading.py` 讀取
- `briefing-out/cache/leading-indicators.json` — **先行指標快照**（三儀表 + 財報 cross-read + 報價新聞 + revision 二階導 + 台股月營收）。工具 `tools/fetch_leading.py`（TTL 20h），briefing_runner 每日預載、archive_cache 凍結。**所有旗標 display-only（記錄不阻擋，同 A4）**，/trade-review 驗過命中率才可升閘門。細部方法（revision 兩法、SMH 成分、quarterly_trends）見工具內註釋與 `research/leading-config.json`
- `research/price-alerts.json` — **自動價格警報**（launchd `com.fadacai.price-alerts` 每 15 分輪詢，盤中 ET 09:25–16:10 生效 → Telegram）。工具 `tools/price_alerts.py add/list/remove/test`；Firstrade 非官方 lib 無警報 endpoint 故以 yfinance 自建。凡 briefing/review 產出「價格觸發待辦」（收租觸發、撿回條件、短腿破位）應同步 `add` 進來，Mac 睡眠期間不輪詢。**Note 格式（2026-08-19 強制，動作優先）**：note 開頭必為 `→ 動作：<收到訊息當下該做/不該做什麼>`，接前置閘門（名額/確認條件/否決條件）；觀察型觸發（到價 ≠ 進場）必須明寫「這不是買進訊號」——收訊人不需任何上下文就知道下一步。條件已失效的警報（如價格跌穿整個觸發帶）要撤舊換新，不留殭屍警報每日重複發。**R23 自峰回撤線（2026-09-02，`feedback/peak-drawdown-line.md`）**：認列桶部位未實現一旦達 +20%（armed），briefing 同次必掛 `--peak-dd 20` 與 `--peak-dd 30 --since <建倉日>` 兩支警報（id `SYM-R23-peakdd20/30`）；觸發 → 收盤確認 → 隔日執行 → `flag`/`resolve-flag --action trimmed`
- `research/source-config.json` — **來源信用系統：私有來源白名單 + X 抓取配置 + 計分門檻**（gitignore，schema 範例見 `docs/source-config.example.json`）。`platform ∈ x|substack|rss|podcast|manual`；`kind ∈ fact|view`；`tier` 只由 `tools/source_credit.py tiers` 機械寫回，不手改
- `research/source-credit.jsonl` — **來源信用帳**：每則可計分主張的登錄與驗收記錄（gitignore）。工具 `tools/source_credit.py add-claim/due/resolve/resolve-due/stats/tiers/list`；fact 型主張只列不猜、人工核對官方數字；view 型到期自動用價格驗價（同 `shadow_signals.py` 邏輯）。**所有 tier display-only**，驗滿 ≥2 期 `/trade-review` 且 Trusted+ hit_rate≥65%/mean lead>0 才可升硬閘門（R21，見 `feedback/RULES-LEDGER.md`）。細節見 `docs/source-credit.md`
- `briefing-out/cache/twitter-signals.json` — **來源訊號快照**（TTL 20h）。工具 `tools/fetch_twitter.py`（X API v2，按量計費，`max_reads_per_run` 硬上限，成本估算見 `docs/source-credit.md`），briefing_runner 每日預載、archive_cache 凍結。Probation tier 僅 briefing §9.6 陳列，Trusted+ 才可進 Key Alerts / Telegram

### 模型版本記錄（因應模型換代）
新規則寫入 `feedback/RULES-LEDGER.md` 時填 `作者` 欄；`/trade-review` 補正歸因時帶 `--model` / `--effort`。
**用途是排覆審順序，不是推翻依據** —— 更新的模型不同意一條已驗證規則（失效 0、巧合 ≤5%）時，除非有新硬數據否則模型輸。否則每次換代就把累積實證清零，那是「無腦 follow」的反面，同樣不靠證據運作。
**要比較新舊模型只有一種乾淨作法：盲測重推導** —— 餵 `cache/archive/` 的當日資料切點、**不給結果**，讓新模型獨立推導，再把兩者一起對照實際結果。用新模型「重審」舊決策不具資訊量（它已知道結果）。

### ⚠️ 旗標紀律（修 2026-07-25 量測出的最大回撤漏口）
凡在 briefing / journal 寫下 **⚠️ / 降桶候選 / 勿再向下加碼 / thesis 蒙塵 / 待覆判** 的部位，**同一次必須 `trade_ledger.py flag`**（附 `--deadline`）。**deadline ≤ 15 個交易日，或必須同時掛價格觸發線（2026-09-02 R11 修訂：MYRG 8/27 旗標排兩個月 deadline 期間續跌是本修訂案例）。**延後必須走 `defer`（**會計次**），**第 3 次自動 forced → 減碼 1/3 或明文 `resolve-flag --action withdrawn` 附理由**。

**Why：** 旗標只活在散文裡時，每天被當新的重述而永不執行。TSLA 7/01 標降桶候選、延後 3 次（其中一次用「改收租」取代決定）→ **−52.7% / −$6,399**；ON 6/26 明文「勿再向下加碼」→ 7/06 仍加碼 32 股。兩者的 thesis-ledger `history` 都是 **0 筆** —— 沒有任何東西在數延後。自警示起算累積代價 **−$6,333**，是全書最貴的單一機制。`flags` 會顯示 `post_flag_fills`（警示後才加的碼）與 `total_cost_since_flag`（該數字逐期往下走才算修好）。

### 鏡像規則（.agents 樹為生成檔，禁手改）
`AGENTS.md` 與 `.agents/skills/` 由 `python3 tools/sync_agents_skills.py` 從 `.claude/` 樹自動生成（唯一轉換：內文 CLAUDE→AGENTS 檔名引用）。**任何 skill / 本檔改動後必須重跑一次 sync**；`--check` 可驗證是否 drift。禁止直接編輯 `.agents/` 下的檔案，也禁止做「Claude→Codex」之類全文置換（2026-07-01 前的鏡像壞損即由此而來）。

## HTML 報告站工作流

每份報告輸出 markdown（source of truth）後自動轉為 HTML，push 到獨立 private repo 部署為 Netlify 靜態網站。

### 工具
```bash
python3 tools/generate_html.py <briefing|portfolio-review|stock-analysis|options-strategy> <日期或 md 路徑> [--push]
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
- 讀取 `feedback/*.md` — 交易風格偏好。**但不是無腦套用**：先讀 `feedback/RULES-LEDGER.md`，每條規則都帶著自己的命中/失效紀錄，依下表判讀強度。

#### 規則判讀表（強制，取代舊的「套用 feedback」）

| 規則狀態 | 讀法 |
|---|---|
| 失效 0、巧合 ≤5%（獨立命中 ≥5） | **已驗證** → 遵循；要反對需硬證據 |
| 失效 0、巧合 5–25%（獨立命中 2–4） | 🟡 **初步支持** → 遵循，引用時附巧合機率；不得作為反對硬數據的依據 |
| 命中 ≤1 / 失效 0、且建立 >60 天 | **未驗證假設** → 可質疑；引用時標「該規則尚未被實測」，並主動設計檢核 |
| 失效 ≥1 | 待覆審 → 引用時**必須**說明已失效幾次 |
| 失效 ≥2 | 🔴 強制覆審 → **不得作為唯一依據** |
| 無結構化原始案例 | ⚠️ **不可驗證** → 降為「偏好」，不是「規則」 |

命中只算建立日後的獨立事件（原始案例不計），每筆案例附 `[up]/[down]` regime 標籤；巧合欄由 `tools/rule_stats.py ledger-audit` 維護（`--check` 每日抓漏）。細則 `feedback/skill-vs-luck.md`。

**兩條鐵則：**
1. **分數決定，不是模型決定。** 若你（或更新的模型）不同意一條已驗證（巧合 ≤5%）的規則 → 你輸，除非你有新的硬數據。不同意一條 0 命中放 >60 天的規則 → 你贏得推定。**規則存廢由實測命中率裁決，不由「哪個模型說的」裁決。** 否則每次模型換代就把累積實證清零，跟「無腦 follow」是同一枚硬幣的反面。
2. **要求原始案例可重測，本身就是篩子。** 一條規則若無法指出「哪些標的、哪一天、當時主張什麼」，它是意見不是規則，按上表降級。

（2026-07-25 建立時：10 條規則有 6 條屬「未驗證假設」，包含治了 66 次判定的 `weak-signal-root-cause.md` 門檻。誠實標示會讓 briefing 語氣變得比較不確定 —— 那是刻意的：**讓依據的強度可見，而不是所有結論聽起來一樣有信心。**）

### 0b. 取得即時持倉
- 呼叫 `mcp__firstrade-server__get_account_position`

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
   - ✅ 範例：「全球資料量 2024→2028 從 150ZB→290ZB，冷資料佔 80%+，HDD per TB 成本比 SSD 低 4-5x」

2. **這個 thesis 在什麼條件下會被證偽？**
   - 列出 2-3 個 **falsifiable 觀察點**（可量化的指標、事件、時程）
   - ❌ 反例：「市況不好就錯」
   - ✅ 範例：「下次財報 HDD ASP 不再上漲、HAMR 60TB 量產延後、Hyperscaler capex 下修 >10%」
   - **區分力優先（2026-07-29）**：觀察點優先選「在對立假說下出現機率差距大」的證據；與雙假說皆相容者（如「需求強勁」既相容週期高峰也相容結構改變）不得作為 thesis 支持，只能列背景。同源相關證據打折，不當多筆獨立樣本。詳 `feedback/voi-research-gate.md`

3. **目前 Verdict 在多大機率上 conditional 在 thesis 成立？**
   - 給**機率分布而非單點**（不寫「可能會漲」而是 60% 看多 / 25% 中性 / 15% 看空）
   - 算 expected value：Σ(機率 × 各情境公允價)，與現價比較
   - **強制呼叫 `probability-honesty-checker` agent**（見下方）— 不可手動套機率
   - **Fair PE 三錨點推導（不可手寫猜測）：** A1=EODHD `pe_ratio`（現行市場隱含）；A2=`peg_ratio×成長率`（成長合理倍數，AI龍頭目標PEG 1.5，其餘 1.0）；A3=`wall_street_target÷forward_EPS`（分析師隱含）。**A3 的 base forward_EPS 取真實賣方共識：`fundamentals-snapshot.json forward_estimates.curr_fy.eps_avg`（缺→next_fy.eps_avg，再缺→`eps_ttm×(1+growth)` 近似）；cache `self_valuation.a3_fwdeps_source` 已標來源，勿手推。** 任一錨回 0.0/null → 丟棄。基準Fair PE=median(A1,A2,A3)；樂觀=max 上限current_PE×1.25；悲觀=min 下限current_PE×0.70。Forward EPS：樂觀=base×(1+min(avg_surprise_pct,15%))；悲觀=base×(1−5%~10%)。
   - **A4 自建錨（divergence flag，不進 median、不進 EV）：** 從 `fundamentals-snapshot.json self_valuation` 直接讀（fetch_fundamentals.py 已算好，完全不看分析師 estimate；推導式在該工具內）。`A4vsA3%` 隔離「我的盈利觀 vs Street 盈利觀」（倍數固定）。⚠️ 影子驗證中（高估極端有預測力、低估無訊號，數據見 `RULES-LEDGER` R3）— 僅 shadow_signals 記錄 + briefing 標 `🟣`，**不得據此改變任何建議**，跑滿 2 期 /trade-review 才決定升閘門。顯示：`confidence=unavailable` → `(self-val N/A)`；`low` → `⚠️低信心`；`ok` → 正常。

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
- ❌ 「略偏正」「略偏負」「中性偏多」「應該會」「不確定性高」（質性語言）
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

**⚠️ Agent 註冊限制：** session 內新增的 `.claude/agents/` 檔案不會動態載入。回 `Agent type not found` 時 → 該 session 改呼叫 `general-purpose` agent，把 `probability-honesty-checker.md` 全文當 prompt 前綴傳入；6 步 + audit checklist 要求不打折。

### 0f. Thesis Ledger（thesis 追蹤與到期驗收）

第一性檢查產出的可驗證 thesis 不是寫完就忘 — 凡帶**明確時間/事件觸發點**的 thesis（「請在財報後/N 日後檢視 X」）都登錄到帳本 `research/thesis-ledger.json`，到期自動回頭抓實際數字驗收（passed/failed/partial），結果驅動下一步 actionable。

- 工具：`tools/thesis_ledger.py`（去重、碰撞攔截、到期/過期掃描、狀態轉換、統計全在程式層，**Claude 不手改 JSON**）
- 去重 key = `ticker:slug`；同 key 但 thesis 差太多 → exit code 2 碰撞，改 slug 或 `supersede`
- 逾期 >30 天未驗收 → 自動 `expired`（當作無結果，不算命中率分母）
- **驗收（每次 briefing / portfolio-review 自動跑）**：`thesis_ledger.py due` → 對到期項抓數判定 → `resolve`；抓不到新數 → `reschedule` 不猜 verdict
- **登錄（briefing / portfolio-review 收尾）**：`list` 看既有 slug → `add`
- **Signal-inference 來源**：從 news body / SEC 8-K / 逐字稿抽**已量化陳述**推導的 thesis，登錄時加 `--source signal-inference --ev "signal: <metric> <value>, <source>, conf=<confidence>"`。僅 `confidence ∈ {high, medium}` 且有明確前瞻 trigger + 強制 `raw_quote`（≤120 字逐字）才登錄；`low` 只在文字呈現。`stats --source signal-inference` 可量測新聞推導命中率（閉環驗證 P3 價值）。反幻覺鎖：無 raw_quote = 無 signal = 不登錄。
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
- 主軸：AI/半導體、高成長科技（無板塊上限；**單一個股 >10% = 硬線，強制減至 ≤10%**，2026-09-02 統一語意）
- 避險：基建、航太、貴金屬、核能（小比例平衡）
- Strategies: LEAPS (stock replacement, deep ITM delta 0.80-0.88), Bull Put Spread, Bull Call Spread, Covered Calls, PMCC
- Risk: 單一持倉 > 10% flagged as over-concentrated
- **避險 sleeve 結構性持有（R25，2026-09-04，`feedback/hedge-sleeve.md`）**：GLD 3% + XLE 3%（≤10%）被動 ETF，`roster.json passive_sleeve`，**不計 18 檔**、不套動能/R8/R23、不因落後汰；金融 ETF 不算避險；「VIX ≥25 才建 sleeve」已廢止
- **閒置現金停泊（R24，2026-09-04，`feedback/cash-parking.md`）**：Firstrade 現金不計息 → `閒置 = 現金 − 在掛買單 − 30 日部署需求 − 3% 緩衝` > $10k 或 >4% 時當次掛 **SGOV** GTC 買至 ≤ $5k；動用前一交易日賣（T+1）。SGOV/BIL 視同現金（`roster.json cash_equivalents`，guard 略過、不佔 18 檔、不進 α 計分；飛輪滯留檢查仍算現金）。不得用 XLF/XLE 等板塊 ETF 停泊

### 執行底層邏輯：Portfolio as a Business（強制濾鏡）
任何 Verdict / Action / 倉位建議都先過這套濾鏡（源 `research/新手開局.md`，操作規範 `feedback/realized-pnl-business-model.md`，Step 0a 已含必讀）：
- **績效看 Realized PnL，不看 Unrealized** — 只認列獲利、虧損掛庫存；目標 Realized ≈ 4× |未實現虧損|。反過來 = 爆倉訊號要 flag。
- **Swing Risk 首要監測**（= 帳上最高未實現利潤 + 潛在回吐；Options = Premium + 未實現利潤）；肥利潤未落袋要主動提示系統性落袋。
- **Offsetting 沖銷失誤而非利潤；禁「砍 loser 加碼 winner」**（四錯：認列虧損 / 過度暴險 / Beta 失衡 / 分散化打折）。
- **Rolling → Adjusted Risk → Risk-Free State**：落袋用 Adjusted Risk 視角（新倉真實風險 = size − 累積已認列），不是「賣了就少賺」。
- **Pre-emptive（非止損式）風險管理 + Scenario Planning**；慎用 Put/SPY 對沖（漲了變反向認列虧損 = Double-Kill）。
- **定位先行**；**主動組合支數 14–18（理想 14–16），>18 砍一進一不淨增**，>30 無益。
- **分桶**：每倉位歸 🔵信念桶（讓它 run、只在 thesis 破或 >10% 才動）或 🟢認列循環桶（高 β/週期/肥利潤 → 系統性 harvest）；疑問時歸認列。
- **兩層候補**：🟡L1 On-Deck（thesis 驗證+觸發明確，補空位只從 L1 拉）/ 🔵L2 Research Pool（需修復或擴 Universe）；砍倉依砍因歸層（組合理由→L1，thesis 破→L2）。
- **機會成本閘門（桶間升級/降級/部署皆強制）**：新倉須明顯優於最弱在倉名額才進 — 相關 beta 門檻最高（須擠掉弱倉、不淨增），無相關 hedge/填缺口門檻較低；14–18 上緣時砍一進一。**前置行業濾網（2026-08-19）**：名字對名字比較之前先問「該行業 TAM 是否 GROWING-STRUCTURAL（擴張中）」——衰退行業內的相對強者不進 bench（不做垃圾桶尋寶；行業比較前三名即可，不花時間分辨第一 vs 第二）。
- **停利再投入飛輪（汰弱留強的閉環，總原則）**：認列循環桶**系統性 harvest 峰值強度**（revision 轉折/題材降溫的肥利潤）+ **砍真弱**（thesis 破 OR 最弱動能無催化）→ **盈餘必配對 redeploy 決策，第一順位投入「加速中強度」**（信念桶領導者 / L1 中 revision 上修的領漲者），**不讓現金閒置滲漏**（每次 harvest 同一次 review 內要嘛 redeploy 上行、要嘛標明 dry powder 理由 + 觸發）。定義鎖死：**「弱」= fundamental 惡化或最弱動能無催化，非當日紅K**（per `feedback/weak-signal-root-cause.md`）；**「強」= estimate 上修/成長加速，非當日超買**（per `feedback/momentum-valuation-symmetry.md`）；funding 源用**已實現獲利 + 真弱倉，非砍虧損倉**（與上面「禁砍 loser 加碼 winner」相容——飛輪靠 realized gain 轉動，不靠認列虧損）。Guardrails（單倉>10%、14–18 支、相關度、去相關 hedge sleeve）是飛輪**護欄不是矛盾**：集中往強度跑、但不破紅線。詳 `feedback/momentum-valuation-symmetry.md`。
- **梯級停利（認列桶 harvest 的機械化觸發，2026-07-01）**：未實現 +30%/+60%/+100% 各賣 15%/15%/20%，之後每 +50pp 賣 10%；**保底 30% runner 永不因停利出場**（只因 thesis 破/汰弱換強/>10% 才動）。GTC 預掛下一級價、每次 full review 校正；revision 轉折 → 提前下一級；revision 上修中不提前。樂透 +100% 賣半；LEAPS >+80% 評估 roll-up 收本金留曝險。信念桶與 hedge sleeve 不適用。詳 `feedback/tiered-profit-taking.md`。
- **Revision 訊號 coverage 分級**：分析師數 N≥15 全權重；8–14 半權重（須與 trend/成長數據互相印證）；<8 不單獨觸發加減碼（改靠 P3 硬數字 + beat rate + guide）。上次財報後 >45 天的 revision 視為 stale。
- **Realized ≈ 4× 是診斷指標非 KPI**（Goodhart 防護）：汰弱認列的虧損屬策略性成本，**單獨列示、不進爆倉訊號判讀**——不可為了保比率而不砍真弱。
- **即時 roster（信念/認列/L1/L2 名單）權威來源 = `plan.md`「組合架構 v2」**；改動 roster 同步更新該節。

## MCP Tools Available
- `mcp__firstrade-server__*` — live Firstrade account data (positions, balance, history, quotes, watchlists)
  - `get_account_position` — real-time stock + options positions (replaces current-position.md)
  - `get_account_balance` — account equity and cash
  - `get_account_history(date_range, custom_from, custom_to)` — transaction history。`date_range`: today|1w|1m|2m|mtd|ytd|ly|cust；給 `custom_from`（+選填 `custom_to`）即自動走 cust 任意窗（2026-01-01 起 = 702 筆 vs `2m` 的 189 筆）
  - `get_orders(per_page=0)` — **在掛訂單清單含 order ID**（`G42621-1601`）→ 對上 plan.md ref = 歸因 ground truth；另可偵測死單。⚠️ **只回在掛單，成交/取消後即消失** → 必須每次 briefing 快照累積（`tools/trade_ledger.py snapshot-orders`）
  - `get_option_chain(symbol, exp_date="")` — 券商選擇權鏈；`exp_date` 空 → 回到期日清單（格式 `YYYYMMDD`，也吃 `YYYY-MM-DD`）
  - `get_option_greeks(symbol, exp_date)` — 券商計算的 delta/gamma/theta/vega/rho + IV（流動性差的履約價回 `--`）
  - `get_single_quote` / `get_watchlist_quote` — real-time quotes
  - ⚠️ **選擇權開倉不可用**（ref 1562）：底層 lib `OrderType` 只有 `BO`/`SO`，payload 無 open/close 判別欄位，API 端拒絕。選擇權一律 App 手掛；但 `get_orders` 快照會讓手掛單自動進交易帳，記錄缺口已補
- `mcp__yfinance-advanced__*` — real-time quotes, options chains, financials, news, recommendations (primary)
- `mcp__sec-edgar-mcp__*` — SEC filings, XBRL financials, insider trading (Form 4), 8-K events, segment data
- `mcp__fmp-mcp__*` — stock peers, market movers, company profiles (free tier; most endpoints need paid plan)
- `mcp__technical__*` / `mcp__polymarket-mcp__*` / `mcp__eodhd-mcp__*` — 工具清單與參數由各 server instructions 每 session 自動注入，此處只記 server 端沒有的實戰 caveat：
  - eodhd 改 server.py 後需重啟 session 才載入新工具
  - `get_fundamentals_snapshot` = 402-gated fmp ratios/PT 的免費層替代；`pe_ratio=0.0/peg=0.0` → 丟該錨
  - `get_earnings_history` = probability-checker Step 1d 首選；⚠️ 低 EPS 基期股 avg_surprise 不可靠（AMD +152% artifact — 用 beat 次數不用 avg%），與本地 earnings-history.json cache 交叉
  - `get_news` 每日快取 `tools/fetch_news.py` → `briefing-out/cache/news-articles.json`（TTL 6h）；P3 訊號抽取要 body 用它，不用 get_news_sentiment
  - `get_macro_indicator` 年頻滯後 — 只當 regime 背景，不當高頻訊號
- Use parallel agent dispatch for batch data fetching across multiple tickers

## MCP Retry & Fallback Policy
- Any MCP tool call that fails → retry up to **3 times**
- 3 次都失敗 → call that server's health test (single simple tool) to diagnose:
  - firstrade-server: `get_account_balance()`
  - yfinance-advanced: `get_stock_info("AAPL")`
  - sec-edgar-mcp: `get_company_info("AAPL")`
  - fmp-mcp: `getCompanyProfile("AAPL")`
  - technical-mcp: `get_technical_indicators("AAPL")`
  - eodhd-mcp: `get_sentiment_trend("AAPL.US", 7)`
  - polymarket-mcp: `get_trending_markets()`
- Health test also fails → fallback to WebSearch/WebFetch for equivalent data
- 在輸出中標記 "⚠️ [server] MCP 不可用，使用替代數據源"
- **fmp-mcp 專屬 fallback（session 過期無需 `/mcp` reconnect）**：`mcp__fmp-mcp__*` 回 `Session not found or expired` 時，**不需手動 reconnect**，直接跑旁路 helper（每次建全新 MCP session，永不過期）：
  ```bash
  python3 tools/fmp_query.py <toolName> [--args '<json>']
  ```
  例：`python3 tools/fmp_query.py getStockPeers --args '{"symbol":"NVDA"}'`（無參數工具省略 --args）。結果直接是 JSON。FMP 容器：`docker compose -f /Users/supatrick/laptop/mcp-servers/fmp-mcp/compose.yaml up -d`
- **FMP 免費層實測清單（2026-07-28 全面掃描）**：✅ 可用 — `getTreasuryRates`（全曲線）、`getHistoricalIndustryPE`/`getIndustryPESnapshot`（行業 PE 日頻，`fetch_leading.py` 半導體估值溫度計用）、`getSectorPESnapshot`、`getSectorPerformanceSnapshot`、`getAftermarketQuote`（盤前盤後報價）、`getShareFloat`、`getDividendsCalendar`、`getIndexQuote`（^VIX 可、^VIX3M 402）、加上原有 peers/movers/profile/earnings-calendar。❌ 402 — transcripts、COT、Senate/House trades、stock news、press releases、analyst estimates、grades、price targets、financial scores、economic calendar、SP500 constituents、insider stats（**§9.5 逐字稿改走 SEC 8-K exhibit**）

## Research Boundaries
- 不主動研究用戶未要求的付費 API/服務
- FMP free tier 限制已記錄，不嘗試付費端點（會返回 402）

## Permission Protection
- 不覆蓋/刪除 `.claude.json` 中現有 allow rules
- 只 append 新權限，並向用戶展示新增內容

## Skill 模型分工（2026-05-05）

### 數據收集 subagent — Sonnet 4.6
所有 skill 的平行數據收集 Agent 都指定 `subagent_type: "data-collector"`（見 `.claude/agents/data-collector.md`）。
Data-collector 每次啟動是全新 context（無歷史）。**Sonnet 4.6 + agent 內加反幻覺鐵則。** 主程仍須對權威價（Firstrade）交叉驗證，對不上即整批丟棄（見 `feedback/subagent-hallucination-guard.md`）。

### 主 skill 執行模型（2026-06-13 更新：全面回歸 Opus 4.8）

模型階梯：**Opus 4.8**（`claude-opus-4-8`，$15/$75，旗艦推理）> **Sonnet 4.6**（中堅/純機械）。

| Skill / 任務 | 模型 | 理由 |
|---|---|---|
| `/ev-check` | **Opus 4.8** | 純第一性機率分布 + EV，反偷懶紀律最吃推理 |
| `/portfolio-review` | **Opus 4.8** | 跨全組合綜合 + 風險 + EV，驅動資金決策 |
| `/briefing deep` | **Opus 4.8** | 深度合成 + Codex 整合 + 機率/EV |
| `/stock-analysis` | **Opus 4.8** | 單標的深掘，旗艦推理 |
| `/options-strategy` | **Opus 4.8** | Greeks / 價差計算 + 多腿比較 |
| `/event-vol-scan` | **Opus 4.8** | 事件買方掃描：VRP/base rate 判讀 + 末日/雙買結構 |
| `/briefing full` | **Opus 4.8** | 中等綜合 + Verdict |
| `/trade-review` | **Opus 4.8** | 決策歸因判讀 + 規則覆審，直接改規則層 |
| `/briefing`（quick）| **Sonnet 4.6** | ~1min 彙整 |
| `/briefing telegram` | **Sonnet 4.6** | 每日 launchd 自動推送，成本敏感 |
| `/todo` | **Sonnet 4.6** | 行動清單 |
| `/trade-journal` review/summary | **Sonnet 4.6** | 帶輕度分析 |
| `/trade-journal` log | **Sonnet 4.6** | 純記錄/格式化 |
| `/mcp-health` | **Sonnet 4.6** | 純連線測試 |
| data-collector subagent | **Sonnet 4.6** | 純 MCP 抓資料，反幻覺鐵則 |
| probability-honesty-checker subagent | **Opus 4.8** | 機率紀律執法者，用旗艦 |

**長 context：** session > 100k 時先 `/compact`，再繼續執行。換主題先 `/clear`。

**手動切換：** skill frontmatter `model:` 已聲明；若 harness 未自動套用，用 `/model opus` / `/model sonnet` 切換後再呼叫。
