# 安裝與環境設定

從零安裝這套框架需要：Claude Code CLI、Python 3.10+、7 個 MCP server（各自取得資料）、以及（可選）`.env` 環境變數啟用自動推送與總經/基本面快取。本文件是完整安裝手冊；踩坑細節另見 [`setup-troubleshooting.md`](setup-troubleshooting.md)（7 個常見卡點）與 [`fmp-containerization.md`](fmp-containerization.md)（fmp-mcp 容器化細節）。

---

## 前置需求

- **[Claude Code](https://docs.claude.com/claude-code)** CLI（本框架的執行環境，skills / agents / MCP 都靠它）
- **Python 3.10+**（`tools/` 腳本與部分 MCP server）
- **[uv](https://github.com/astral-sh/uv)**（執行 Python MCP server，建議）
- macOS（`launchd` 自動推送為 macOS 專屬；其餘功能跨平台）

## 安裝

```bash
# 1. clone
git clone <this-repo-url> portfolio && cd portfolio

# 2. Python 依賴（tools/ 腳本用）
pip3 install -r tools/requirements.txt

# 3. 環境變數（自動推送 / 總經才需要；純互動分析可略過）
cp .env.example .env      # 再依註解填入你自己的 key

# 4. 啟動 Claude Code，輸入任一指令
claude
> /mcp-health             # 先確認 MCP 連線
> /briefing               # 跑第一份日報
```

## MCP servers 設定（核心）

本框架的數據來自 7 個 MCP server，需各自安裝並在 Claude Code 註冊（`claude mcp add ...` 或專案 `.mcp.json`）。**所有 API key / 券商憑證由你自備，本 repo 不含任何金鑰。**

| Server | 取得方式 | 需要 key？ |
|--------|----------|:---------:|
| `firstrade-server` | 第三方 [morristai/firstrade-mcp](https://github.com/morristai/firstrade-mcp) + 你自己的憑證 shim（**勿把券商帳密 commit 進任何 repo**） | ✅ 券商登入 |
| `yfinance-advanced` | PyPI 套件 [`yfinance-mcp`](https://pypi.org/project/yfinance-mcp/)，`uvx yfinance-mcp` 直接啟動，免 clone | ❌ |
| `sec-edgar-mcp` | PyPI 套件 [`sec-edgar-mcp`](https://pypi.org/project/sec-edgar-mcp/)，`uvx sec-edgar-mcp` 直接啟動，免 clone | ❌（需填 email 作 user-agent） |
| `fmp-mcp` | [Financial-Modeling-Prep-MCP-Server](https://github.com/imbenrabi/Financial-Modeling-Prep-MCP-Server)，**npm 無套件**，需 clone + build；建議放在 project 以外的獨立資料夾 | ✅ FMP token（free tier） |
| `technical-mcp` | 姊妹 repo [fadacai-mcp-servers `/technical`](https://github.com/PatrickSUDO/fadacai-mcp-servers/tree/main/technical) | ❌（用 yfinance） |
| `eodhd-mcp` | 姊妹 repo [fadacai-mcp-servers `/eodhd`](https://github.com/PatrickSUDO/fadacai-mcp-servers/tree/main/eodhd) | ✅ EODHD token |
| `polymarket-mcp` | PyPI 套件 [`polymarket-mcp`](https://pypi.org/project/polymarket-mcp/)，`uvx polymarket-mcp` 直接啟動，免 clone | ❌ |

**Claude Code 註冊指令（`/path/to/fadacai-mcp-servers` 替換成你自己的路徑）：**

```bash
# uvx 直接啟動（免 clone）
claude mcp add yfinance-advanced -- uvx yfinance-mcp
claude mcp add sec-edgar-mcp --env SEC_EDGAR_USER_AGENT="Your Name your@email.com" -- uvx sec-edgar-mcp
claude mcp add polymarket-mcp -- uvx polymarket-mcp

# fadacai-mcp-servers（clone 後 uv sync）
claude mcp add technical -- uv --directory /path/to/fadacai-mcp-servers/technical run server.py
claude mcp add eodhd-mcp --env EODHD_API_TOKEN=xxxx -- uv --directory /path/to/fadacai-mcp-servers/eodhd run server.py

# fmp-mcp（需 clone 到獨立資料夾，npm install && npm run build 後）
claude mcp add fmp-mcp --env FMP_API_KEY=xxxx -- node /path/to/fmp-mcp/dist/index.js
```

> 缺任一 server 不會讓整個框架失效——`/mcp-health` 會標出不可用者，skills 內建 retry → 健康檢查 → WebSearch fallback。
>
> macOS 上安裝 Python 套件別用 `pip3`（會撞 PEP 668），一律用 `uv`/`uvx`；`fmp-mcp` 建議跑成常駐 HTTP server 而非 stdio（見 `setup-troubleshooting.md` §2）；子代理拿不到 project-scope 的 MCP 時，改用專案根目錄的 `.mcp.json`（範本 `.mcp.json.example`）。

### MCP Servers 功能一覽

| Server | 功能 | 備註 |
|--------|------|------|
| **firstrade-server** | 即時持倉、帳戶餘額、交易歷史、報價 | 主要帳戶數據源 |
| **yfinance-advanced** | 即時報價、選擇權鏈、財報、新聞、分析師評級 | 主要市場數據源 |
| **sec-edgar-mcp** | SEC 財報、內部人 Form 4、8-K 事件、XBRL | 官方法規文件 |
| **fmp-mcp** | 同業比較、市場漲跌排行（Free tier） | 補充數據 |
| **technical-mcp** | RSI、MACD、布林通道、ATR、動量分數、S/R levels | 技術分析 |
| **eodhd-mcp** | `get_news`（新聞全文 body/symbols/tags，P3 訊號擷取用）+ AI 情緒分析 + 基本面快照（PE/PEG/分析師PT/盈餘 beat rate/毛利率/季度成長，7 工具，ticker 格式: AAPL.US） | 情緒分析 + 免費版估值 + 新聞全文 |
| **polymarket-mcp** | 預測市場事件概率（Demo mode，read-only） | 市場信念數據 |

**MCP Retry Policy：** 失敗 → 重試 3 次 → 健康檢查 → fallback WebSearch/WebFetch，輸出中標記 `⚠️ [server] MCP 不可用`。

## 環境變數（`.env`）

| 變數 | 用途 | 取得 |
|------|------|------|
| `FRED_API_KEY` | 總經快照（Fed Funds / CPI / 殖利率曲線 / HY OAS / VIX） | [FRED 免費申請](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `EODHD_API_TOKEN` | 基本面快取（`fetch_fundamentals.py`）：PE/PEG/分析師PT/盈餘 beat rate/季度成長 | [EODHD 申請](https://eodhd.com/financial-apis/)（All-In-One 含 Fundamentals）|
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 日報推送到 Telegram | `@BotFather` / `getUpdates` |
| `SMTP_*` / `EMAIL_*` | 日報 email 副本 | Gmail App Password |
| `BRIEFING_MODEL` / `FRIDAY_CODEX` / `RETRY_MAX` 等 | launchd 自動推送行為（headless 模型預設 `sonnet`、重試預設 5） | 見 `.env.example` 註解 |
| `REPORT_SITE_TOKEN` / `REPORT_SITE_URL` / `REPORTS_REPO_PATH` | 私有 HTML 報告站（Netlify，`generate_html.py --push`；Telegram 訊息末自動附連結） | 自建 private repo + Netlify |

以上**全部選用**——不設也能用所有互動式 slash command，只是少了自動推送、總經快照與三錨點估值快取。自動推送（Telegram + Email + launchd 排程）的完整步驟見 [`briefing-auto-send.md`](briefing-auto-send.md)。

## 關鍵本地檔案

| 檔案 / 目錄 | 用途 | 更新方式 |
|------------|------|---------|
| `plan.md` | 投資計畫：板塊目標、策略佇列、觀察清單 | 手動（僅在用戶要求時） |
| `journal/` | 每日交易日誌（YYYY-MM-DD.md），含完整倉位快照 | 自動（Step 0c/0d + hook） |
| `feedback/` | 交易風格規則，所有 skill 每次必讀 | 手動（學習後更新） |
| `research/` | 個股投資論文、thesis/ev/shadow-signal/source-credit 帳本 | 手動 + 工具自動 |
| `.env` | Telegram + SMTP 設定（**gitignored**，cp .env.example） | 手動 |
| `tools/` | Pipeline 腳本：`send_briefing.py`、`check_trading_day.py`、`briefing_runner.sh`（headless 生成，`--model sonnet` + retry 5）、`fetch_macro.py`、`fetch_fundamentals.py`（EODHD 基本面 + revision 曲線 + A4 自建估值快取）、`fetch_news.py`（EODHD 新聞全文快取）、`fetch_twitter.py`（X API v2 抓取）、`fetch_leading.py`（發現層先行指標）、`earnings_history.py`、`thesis_ledger.py`、`ev_ledger.py`、`source_credit.py`、`trade_ledger.py`（成交歸因 / 旗標紀律 / α 計分）、`account_metrics.py`（帳戶級四指標）、`shadow_signals.py`（影子訊號帳本）、`archive_cache.py`（每日決策輸入凍結）、`price_alerts.py`（價格警報）、`pmcc_scan.py`、`event_vol_scan.py`、`generate_html.py`（報告 → 私有 Netlify 報告站）、`fmp_query.py`（FMP session 過期旁路 helper）、`simple_dcf.py`、`sync_agents_skills.py`（`.claude` → `.agents` 鏡像生成）、`test_*.py`（單元測試） | git tracked |
| `briefing-out/` | 每日 briefing 輸出 + 發送 log（**gitignored**） | 自動生成 |
| `briefing-out/cache/` | 預載快取層：macro / earnings / fundamentals / news / leading-indicators / twitter-signals（各自 TTL），`archive/YYYY-MM-DD/` 每日凍結全部決策輸入（120 天） | 自動（runner + launchd） |
| `CLAUDE.md` | 完整專案指令手冊（Step 0 規範、MCP 政策、模型分工） | 手動 |

## 常見問題

**MCP 掛了怎麼辦？**
執行 `/mcp-health` 診斷，通常重開 Claude Code session 即可。三次重試後自動 fallback WebSearch。

**倉位資料從哪來？**
`mcp__firstrade-server__get_account_position` 取即時數據（Step 0b 自動執行）。

**交易記錄在哪？**
`journal/` 目錄，每日一檔（YYYY-MM-DD.md），每次 skill 執行都會建立或更新。

**配置計畫在哪？**
`plan.md` — 含板塊目標（%）、策略佇列（⏳/✅/🔄）、觀察清單、策略原則。

**第一性原理紀律是什麼？**
每個 Verdict / Recommendation 前強制填寫：核心 thesis（可驗證命題）+ 證偽條件（2-3 個 falsifiable 觀察點）+ 機率分布（EV 計算）。確保結論有 ground truth 依據，不是 narrative。詳見 [`methodology.md`](methodology.md)。

**Telegram 每天幾點收到？**
由你在 plist `StartCalendarInterval` 自訂（系統本地時區解讀，NYSE 交易日才跑）。沒收到 = 該發送窗失敗，除錯路徑見 [`briefing-auto-send.md`](briefing-auto-send.md) 疑難排解。

更多安裝踩坑（firstrade-server 自建細節、headless `claude -p` 兩大坑、Mac 睡眠導致 launchd 不觸發等）見 [`setup-troubleshooting.md`](setup-troubleshooting.md)。
