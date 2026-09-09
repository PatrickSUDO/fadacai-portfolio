# Portfolio — Claude Code 投資研究與組合管理框架

一套建構在 **Claude Code skills + MCP servers** 之上的美股投資研究與組合管理工作區。日報、組合檢視、個股深掘、選擇權策略、交易日誌、每兩週檢討，全部封裝成可重複執行的 slash command；每個投資結論都要過**第一性原理紀律**（可驗證 thesis → 證偽條件 → 機率分布 + EV），而且事後會被機械驗價、計分、回頭修規則。

它不是「叫 LLM 給意見」的工具，是一套**讓 LLM 的意見可以被打分數、讓規則用實測存廢、讓偷懶被程式抓到**的框架。

- **使用對象**：自行操作美股/選擇權、想用 LLM 輔助但要求紀律與可驗證性的個人投資人 / quant
- **輸出語言**：全繁體中文
- **券商整合**：透過 `firstrade-server` MCP 取即時持倉（以 Firstrade 為參考整合，可替換成你自己的券商 MCP）

> ⚠️ **非投資建議。** 本專案是分析與紀律工具，所有輸出僅供研究參考；你需自行承擔所有交易決策與風險，並自備所有 API key / 券商憑證。詳見文末免責聲明。

> 📦 自寫的兩個 MCP server（`technical` 技術指標、`eodhd` 情緒）已獨立開源於 **[fadacai-mcp-servers](https://github.com/PatrickSUDO/fadacai-mcp-servers)**。

---

## 架構

[![架構總覽](docs/architecture.svg)](docs/architecture.svg)

> 點圖可看放大版（GitHub 會開圖片檢視器，可縮放）；完整頁面版見下方「架構」小節連結。

---

## 跟一般 LLM 選股工具不一樣的地方

1. **每個結論都事前登錄、到期機械驗價。** Thesis、EV 分布、消息來源主張、影子訊號四本帳：先寫下機率與三情境公允價，到期由程式抓收盤判定，校準是算出來的，不是感覺。
2. **規則有自己的命中率，存廢由分數裁決。** 每條交易規則帶命中 / 失效 / **巧合機率**（純擲硬幣達成該紀錄的機率 ≤5% 才算已驗證），原始案例不計分、每筆附市場 regime 標籤；模型換代不會把累積實證清零。
3. **運氣和技能分開記。** 結果落在事前分布外算「模型漏分支」不算運氣；thesis 對但沒賺記「對但沒用」不記命中；連放棄條件都事前寫死（兩年後 Brier skill score 與持有 α 不過就轉被動）。
4. **不靠模型自律，靠程式擋。** 工具在寫入點拒收不完整登錄；每日排程跑帳本一致性檢查，失敗直接推 Telegram；Claude Code hook 對每份檢討報告跑 lint。判斷層的規則能變工具就變工具。
5. **警示必須進資料層。** 「降桶候選」「勿再加碼」這類旗標一寫就登記附期限，延後計次、第三次強制減碼；持倉守門每日掃持有天數、自峰回撤線、停利掛單缺口、集中度、財報窗。實測這是回撤最貴的漏口。
6. **決策輸入每日凍結，第二意見盲跑。** 當日 raw data 快照保留 120 天，供無 hindsight 的重推導與模型換代盲測；Codex 在不知道 Claude 結論的情況下獨立分析，只比對真實共識與真實分歧。
7. **新想法先回測再進系統。** 例：13F 與國會議員抄單，用官方申報 PDF 與實盤 ETF 回測後 α 的 t 值全 <2，不加入（[`tools/backtests/`](tools/backtests/README.md)）。

---

## 機制一覽

| 機制 | 工具 / 入口 | 說明 |
|---|---|---|
| 第一性紀律 + 機率誠實 agent | 所有 skill 的 Step 0e、`probability-honesty-checker` | thesis / 證偽條件 / 機率分布 + EV，禁 default bell shape 與質性語言；thesis-driven 分支必做 priced-in 檢查 |
| 三錨點估值 + A4 影子錨 | `tools/fetch_fundamentals.py` | 市場隱含 PE / PEG / 分析師 PT 三角定位；自建盈利觀 vs Street 分歧旗標（display-only） |
| 四本自我驗證帳 | `thesis_ledger.py`、`ev_ledger.py`、`source_credit.py`、`shadow_signals.py` | 事前登錄、到期機械驗收；`ev_ledger.py stats` 出 Brier skill score、獨立 n、in_range、thesis × 定價 2×2 |
| 規則命中率帳 + 統計判讀 | `tools/rule_stats.py`、`/trade-review` | 巧合機率欄機械寫回、`--check` 抓漏；每兩週歸因每筆成交（系統 vs 自主），交易 α / 持有 α / beta capture 三並列指標 |
| 持倉守門 + 旗標紀律 | `tools/position_guard.py`、`trade_ledger.py flag` | 每日掃 R14 / R23 / R8 / >10% / 財報窗 / 桶別缺口；旗標延後計次、第 3 次強制 |
| 發現層先行指標 | `tools/fetch_leading.py` | 信用利差速度、VIX 期限結構、半導體寬度、revision 二階導、台股月營收；display-only |
| 每日快取 + 凍結 | `tools/briefing_runner.sh`、`archive_cache.py` | 排程預載總經 / 基本面 / 新聞 / 先行指標，當日決策輸入凍結 120 天 |
| 推送 + 警報 + 手掛單 | `send_briefing.py`、`price_alerts.py`、`tg_send.py` | Telegram 摘要層 / Email 詳細層；15 分鐘價格警報；做不到的單一句話一單推 Telegram |
| 產出檢查 | `tools/review_lint.py`（hook）、`rule_stats.py ledger-audit --check` | 缺段 / 多結論 / 收尾未做 / 帳本矛盾 → exit 2 |

細節見 [`docs/methodology.md`](docs/methodology.md)。

---

## 快速開始

```bash
# 前置需求：Claude Code CLI、Python 3.10+、uv（建議）
git clone <this-repo-url> portfolio && cd portfolio

pip3 install -r tools/requirements.txt
cp .env.example .env      # 依註解填入你自己的 key（純互動分析可略過）

claude
> /mcp-health             # 先確認 7 個 MCP server 連線
> /briefing               # 跑第一份日報
```

MCP 安裝與環境變數完整說明見 [`docs/setup.md`](docs/setup.md)。個人規則（`feedback/`）、帳本（`research/`）、日誌（`journal/`）、產出（`briefing-out/`）皆為本機檔案，已 gitignore，clone 後從空白開始累積。

---

## 指令一覽

| 指令 | 用途 | 模型 | 預估時間 |
|------|------|------|---------|
| `/briefing` | 快速日報（技術面 + 警示 + 計畫進度） | Sonnet | ~1 min |
| `/briefing full` | + 情緒面 + 市場動態 + 預測市場 | Sonnet | ~3 min |
| `/briefing deep` | + SEC + FMP + 個股深度分析 | Opus | ~5 min |
| `/briefing telegram` | Telegram 推送格式（emoji 純文字，寫出 briefing-out/ 兩個檔案） | Sonnet | ~2-3 min |
| `/briefing telegram --send` | 同上，並實際推送至 Telegram + 寄送 email | Sonnet | ~2-3 min |
| `/portfolio-review` | 完整組合報告（板塊配置 + 個股分析） | Opus | ~3-5 min |
| `/stock-analysis TICKER` | 個股深度研究（支援多股比較） | Sonnet / Opus | ~2 min |
| `/options-strategy TICKER STRATEGY` | 選擇權策略計算（E_adj 排序） | Sonnet | ~1-2 min |
| `/todo` | 下一交易日 / 盤中 / 盤後優先行動清單 | Sonnet | ~1 min |
| `/ev-check [7d\|14d\|30d]` | 強制第一性機率分布 + 組合 EV 計算 | — | ~1 min |
| `/trade-journal log\|review\|summary\|auto` | 交易記錄與回顧 | — | ~1 min |
| `/trade-review [2w\|4w]` | 每兩週交易檢討：成交歸因 + 三並列指標 + 規則命中率帳本 + 運氣/技能判讀 | Opus | ~3-5 min |
| `/event-vol-scan [days] [TICKER ...]` | 財報/CPI/FOMC 前末日 buy call / 雙買 straddle 機會掃描 | Opus | ~2 min |
| `/mcp-health` | 測試所有 MCP server 連線狀態 | — | ~30 sec |

**`--send` 旗標：** 可加在任何 tier 後，執行完自動推送 Telegram + email。例：`/briefing full --send`

**`--codex` 旗標：** 任何分析 skill 後加，觸發 Codex 獨立第一性分析（B1）+ 機會掃描（B2）+ 輪動分析（B3）；`--codex-adversarial` 觸發壓力測試模式。

**模型切換：** 若 harness 未自動套用 frontmatter model，手動 `/model sonnet` / `/model opus` 後再執行；session context > 100k 建議先 `/compact`。

---

## 近期更新（2026-09）

- **R23–R25 持倉守門**：認列桶自峰回撤線、閒置現金機械停泊、避險 sleeve 結構性持有；`position_guard.py` 每日掃描並自動掛撤警報
- **R26 運氣 vs 技能統計紀律**：規則帳本改巧合機率制、regime 標籤、thesis × 定價 2×2、事前放棄條件；`rule_stats.py` / `review_lint.py` / PostToolUse hook 三層機械執行
- **推送分層**：Telegram 摘要層、Email/網頁詳細層；`tg_send.py` 把做不到的單一句話一單推給人手掛
- **`tools/backtests/`**：13F / 國會議員抄單回測，結論不加入

---

## 文件

- [`docs/setup.md`](docs/setup.md) — 安裝步驟、7 個 MCP server 設定與註冊指令、環境變數表、關鍵本地檔案、常見問題
- [`docs/setup-troubleshooting.md`](docs/setup-troubleshooting.md) — 從零安裝實際會卡住的 7 個踩坑速查
- [`docs/briefing-auto-send.md`](docs/briefing-auto-send.md) — Telegram/Email 自動推送完整設定、pipeline 架構、疑難排解
- [`docs/fmp-containerization.md`](docs/fmp-containerization.md) — fmp-mcp 容器化架構、watchdog、日常操作與回滾
- [`docs/methodology.md`](docs/methodology.md) — 方法論細節：第一性紀律、三錨點估值、各帳本、統計紀律、機械執行層、如何擴展
- [`docs/thesis-ledger.md`](docs/thesis-ledger.md) — Thesis Ledger 資料模型、去重機制、CLI、驗收流程
- [`docs/leading-indicators.md`](docs/leading-indicators.md) — 發現層先行指標五 block 架構與防假訊號設計
- [`docs/source-credit.md`](docs/source-credit.md) — 來源信用系統：計分公式、tier 升降規則、X API 成本控管
- [`tools/backtests/README.md`](tools/backtests/README.md) — 回測腳本與結論（13F / 國會議員抄單）
- [`docs/architecture.html`](docs/architecture.html) — 系統架構圖完整頁面版（`docs/architecture.svg` 為 README 用）

完整規範（Step 0 統一規範、MCP 政策、模型分工、旗標紀律）見 [`CLAUDE.md`](CLAUDE.md)。

---

## 授權

[MIT License](LICENSE) — 自由使用、修改、商用，保留版權聲明即可。

## 免責聲明

本專案為**投資研究與紀律輔助工具**，所有輸出（含 Verdict、EV、機率、選擇權建議）**僅供研究與教育參考，不構成投資建議、要約或保證**。美股與選擇權交易具高度風險，可能導致本金全部損失。你需自行評估並承擔一切交易決策與後果，並自備所有 API key 與券商憑證；作者與貢獻者不對任何使用本專案所致之損失負責。
