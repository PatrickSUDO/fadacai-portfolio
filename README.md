# Portfolio — Claude Code 台股投資研究與組合管理框架

一套建構在 **Claude Code skills + MCP servers** 之上的台股投資研究與組合管理工作區。把日報、組合檢視、個股深度分析、台指期/選擇權策略、交易日誌等流程，全部封裝成可重複執行的 slash command，並用一套**第一性原理紀律**（可驗證 thesis → 證偽條件 → 機率分布 + EV）約束每一個投資結論，避免淪為 narrative。

- **使用對象**：自行操作台股（上市/上櫃）與台指期/選擇權、想用 LLM 輔助但要求紀律與可驗證性的個人投資人 / quant
- **輸出語言**：全繁體中文
- **券商整合**：透過 `shioaji-server` MCP 取即時持倉（以永豐金 Shioaji 為參考整合，可替換成富邦 neo / 元大 / 你自己的券商 MCP）
- **資料來源**：7 個 MCP server（即時報價、公開資訊觀測站 MOPS、技術指標、新聞情緒、籌碼面等）+ 台灣總經 + FinMind 基本面 REST 快取
- **可選自動化**：launchd 每個 TWSE 交易日定時產生並推送日報到 Telegram + Email

> ⚠️ **非投資建議。** 本專案是分析與紀律工具，所有輸出僅供研究參考；你需自行承擔所有交易決策與風險，並自備所有 API key / 券商憑證。詳見文末免責聲明。

> 📦 自寫的兩個 MCP server（`technical` 技術指標、`chip` 籌碼面）已獨立開源於 **[fadacai-mcp-servers](https://github.com/PatrickSUDO/fadacai-mcp-servers)**。

---

## 系統架構

```mermaid
flowchart TD
    User(["👤 User<br/>台股 + 台指期/選擇權"])

    Hook["🔔 SessionStart Hook<br/>journal/YYYY-MM-DD.md 存在？<br/>✅ 已存在 → 略過 ｜ ⚡ 不存在 → gap-fill"]

    User -->|session 開始| Hook
    User -->|slash commands| Skills

    subgraph Skills ["⚡ Skills — Slash Commands"]
        direction LR
        B["/briefing<br/>quick · full · deep · telegram"]
        PR["/portfolio-review"]
        SA["/stock-analysis 代號"]
        OS["/options-strategy"]
        TJ["/trade-journal"]
        MH["/mcp-health"]
    end

    Skills -->|共同執行| Step0

    subgraph Step0 ["📋 Step 0 統一規範（所有 skill 必跑）"]
        direction LR
        s0a["0a<br/>plan.md<br/>feedback/*.md"] --> s0b["0b<br/>get_account_position<br/>live broker"] --> s0c["0c/0d<br/>journal gap-fill<br/>今日快照"] --> s0e["0e<br/>第一性原理紀律<br/>thesis · 證偽 · EV"]
    end

    subgraph Models ["🤖 AI Model 分流（Cost Optimization）"]
        HAIKU["🟡 Haiku 4.5<br/>data-collector subagent<br/>mcp-health · trade-journal log<br/>純機械 · no synthesis"]
        SONNET["🔵 Sonnet 4.6<br/>日常分析合成<br/>briefing quick+telegram<br/>todo · journal review"]
        OPUS["🟠 Opus 4.8<br/>旗艦推理 · 重綜合<br/>portfolio-review · ev-check<br/>briefing deep/full · stock-analysis<br/>options-strategy · 機率/EV"]
    end

    s0e --> SONNET & OPUS
    Skills -->|"subagent_type: data-collector"| HAIKU

    subgraph MCP ["🔌 7 MCP Servers — 外部即時數據"]
        direction LR
        FT["🏦 shioaji-server<br/>持倉 · 餘額 · 成交 · 報價"]
        YF["📈 finmind-server<br/>報價 · 法人 · 財報 · 月營收"]
        SEC["📋 mops-server<br/>重訊 · 法說 · 月營收 · 內部人"]
        FMP["💹 twse-server<br/>同類股 · 漲跌排行 · 產業"]
        TECH["📊 technical-mcp<br/>RSI · MACD · ATR · S/R levels"]
        NEWS["💬 cnyes-news<br/>中文新聞全文 + 情緒 −1→+1"]
        CHIP["🎲 chip-server<br/>三大法人 · 融資券 · 期貨未平倉"]
    end

    HAIKU -->|平行呼叫（Retry 3x）| MCP
    s0b --> FT
    Hook -->|讀寫| JRL

    subgraph KB ["📁 Knowledge Base — 本地檔案"]
        direction LR
        PL[("plan.md<br/>板塊目標 · 策略佇列")]
        FB[("feedback/<br/>交易風格規則")]
        JRL[("journal/<br/>每日倉位快照")]
        RES[("research/<br/>投資論文")]
    end

    s0a -->|讀取| PL & FB
    s0c <-->|讀寫| JRL

    CODEX["🤖 Codex（opt-in）<br/>--codex flag<br/>B1 獨立第一性分析<br/>B2 機會掃描 · B3 輪動"]
    SONNET & OPUS -->|opt-in| CODEX

    subgraph AutoSend ["📲 每日自動推送（台灣時間 14:00 收盤後）"]
        direction LR
        LAUNCHD["⏰ launchd<br/>com.fadacai.briefing<br/>TWSE 交易日才跑<br/>週五加 --codex"]
        RUNNER["🔧 briefing_runner.sh<br/>~/.local/bin/<br/>TCC-safe wrapper"]
        OUT_FILES["📄 briefing-out/<br/>YYYY-MM-DD-full.md<br/>YYYY-MM-DD-telegram.txt"]
        TG["📱 Telegram Bot<br/>emoji 純文字 < 1500 字"]
        EMAIL["📧 Gmail SMTP<br/>精簡版 + 完整 markdown"]
        SENDLOG["📋 send-log.jsonl"]
    end

    LAUNCHD --> RUNNER --> SONNET
    SONNET -->|--send flag| OUT_FILES
    OUT_FILES --> TG & EMAIL
    TG & EMAIL --> SENDLOG

    OUT["📊 繁體中文報告<br/>Verdict · EV · 口數/張數 · 觸發條件"]
    SONNET --> OUT
    OPUS --> OUT
```

---

## 快速開始

### 前置需求

- **[Claude Code](https://docs.claude.com/claude-code)** CLI（本框架的執行環境，skills / agents / MCP 都靠它）
- **Python 3.10+**（`tools/` 腳本與部分 MCP server）
- **[uv](https://github.com/astral-sh/uv)**（執行 Python MCP server，建議）
- macOS（`launchd` 自動推送為 macOS 專屬；其餘功能跨平台）

### 安裝

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

### MCP servers 設定（核心）

本框架的數據來自 7 個 MCP server，需各自安裝並在 Claude Code 註冊（`claude mcp add ...` 或專案 `.mcp.json`）。**所有 API key / 券商憑證由你自備，本 repo 不含任何金鑰。**

| Server | 取得方式 | 需要 key？ |
|--------|----------|:---------:|
| `shioaji-server` | 永豐金 [Shioaji API](https://sinotrade.github.io/) 包成 MCP（**勿把券商帳密 / API Key commit 進任何 repo**），或替換成你自己券商的 MCP | ✅ 券商 API Key/Secret |
| `finmind-server` | [FinMind](https://finmindtrade.com/) 台股資料 API 包成 MCP（`pip install FinMind`）；報價/法人/財報/月營收 | ⭕ 免費 token（高頻需付費） |
| `mops-server` | 公開資訊觀測站 [MOPS](https://mops.twse.com.tw/) 爬取/開放 API 包成 MCP；重訊、法說會、月營收、財報、內部人持股 | ❌ |
| `twse-server` | [證交所](https://openapi.twse.com.tw/) + [櫃買](https://www.tpex.org.tw/openapi/) 開放 API 包成 MCP；同類股、漲跌排行、產業分類 | ❌ |
| `technical-mcp` | 姊妹 repo [fadacai-mcp-servers `/technical`](https://github.com/PatrickSUDO/fadacai-mcp-servers/tree/main/technical)（OHLC 來源改 FinMind/yfinance `.TW`） | ❌ |
| `cnyes-news` | [鉅亨網](https://news.cnyes.com/) / 經濟日報新聞抓取 + LLM 中文情緒包成 MCP | ⭕ 視來源 |
| `chip-server` | 姊妹 repo [fadacai-mcp-servers `/chip`](https://github.com/PatrickSUDO/fadacai-mcp-servers/tree/main/chip)；三大法人買賣超、融資融券、期貨未平倉（大額交易人）、借券 | ❌（用 TWSE/TAIFEX 開放資料） |

**Claude Code 註冊指令（`/path/to/...` 替換成你自己的路徑）：**

```bash
# FinMind（clone 後 uv sync，或 pip install FinMind 後自寫 server）
claude mcp add finmind-server --env FINMIND_TOKEN=xxxx -- uv --directory /path/to/finmind-server run server.py

# 公開資訊觀測站 MOPS / 證交所開放 API
claude mcp add mops-server -- uv --directory /path/to/mops-server run server.py
claude mcp add twse-server -- uv --directory /path/to/twse-server run server.py

# fadacai-mcp-servers（clone 後 uv sync）
claude mcp add technical -- uv --directory /path/to/fadacai-mcp-servers/technical run server.py
claude mcp add chip-server -- uv --directory /path/to/fadacai-mcp-servers/chip run server.py

# 新聞情緒
claude mcp add cnyes-news -- uv --directory /path/to/cnyes-news run server.py

# 券商（永豐金 Shioaji 範例；API Key/Secret 勿 commit）
claude mcp add shioaji-server --env SHIOAJI_API_KEY=xxxx --env SHIOAJI_SECRET_KEY=xxxx -- uv --directory /path/to/shioaji-server run server.py
```

> 缺任一 server 不會讓整個框架失效——`/mcp-health` 會標出不可用者，skills 內建 retry → 健康檢查 → WebSearch fallback。

### 環境變數（`.env`）

| 變數 | 用途 | 取得 |
|------|------|------|
| `FINMIND_TOKEN` | 基本面 / 月營收 / 法人快取（`fetch_fundamentals.py`）：本益比/PEG/殖利率/法人買賣超/季度成長 | [FinMind 申請](https://finmindtrade.com/analysis/#/account/login) |
| `TWVIX_SOURCE` / 總經 | 總經快照（央行重貼現率 / CPI / 10年公債殖利率 / USD-TWD / 台指 VIX） | FinMind 總經 / 央行 / 主計總處開放資料 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 日報推送到 Telegram | `@BotFather` / `getUpdates` |
| `SMTP_*` / `EMAIL_*` | 日報 email 副本 | Gmail App Password |
| `BRIEFING_*` / `FRIDAY_CODEX` / `RETRY_MAX` 等 | launchd 自動推送行為 | 見 `.env.example` 註解 |

以上**全部選用**——不設也能用所有互動式 slash command，只是少了自動推送、總經快照與三錨點估值快取。

---

## 指令一覽

| 指令 | 用途 | 模型 | 預估時間 |
|------|------|------|---------|
| `/briefing` | 快速日報（技術面 + 警示 + 計畫進度） | Sonnet | ~1 min |
| `/briefing full` | + 情緒面 + 籌碼動態 + 法人買賣超 | Opus | ~3 min |
| `/briefing deep` | + 重訊/法說 + 同類股 + 個股深度分析 | Opus | ~5 min |
| `/briefing telegram` | Telegram 推送格式（emoji 純文字，寫出 briefing-out/ 兩個檔案） | Sonnet | ~2-3 min |
| `/briefing telegram --send` | 同上，並實際推送至 Telegram + 寄送 email | Sonnet | ~2-3 min |
| `/portfolio-review` | 完整組合報告（板塊配置 + 個股分析） | Opus | ~3-5 min |
| `/stock-analysis 代號` | 個股深度研究（支援多股比較，如 `2330` `2454`） | Sonnet / Opus | ~2 min |
| `/options-strategy 標的 STRATEGY` | 台指期/選擇權策略計算（E_adj 排序） | Opus | ~1-2 min |
| `/todo` | 下一交易日 / 盤中 / 盤後優先行動清單 | Sonnet | ~1 min |
| `/ev-check [7d\|14d\|30d]` | 強制第一性機率分布 + 組合 EV 計算 | — | ~1 min |
| `/trade-journal log\|review\|summary\|auto` | 交易記錄與回顧 | — | ~1 min |
| `/mcp-health` | 測試所有 MCP server 連線狀態 | — | ~30 sec |

**`--send` 旗標：** 可加在任何 tier 後，執行完自動推送 Telegram + email。例：`/briefing full --send`

**`--codex` 旗標：** 任何分析 skill 後加，觸發 Codex 獨立第一性分析（B1）+ 機會掃描（B2）+ 輪動分析（B3）。`--codex-adversarial` 觸發壓力測試模式。

**模型切換：** 若 harness 未自動套用 frontmatter model，手動 `/model sonnet` 或 `/model opus` 後再執行 skill。Session context > 100k 時建議先 `/compact`。

---

## 使用範例

### 每日例行

```
/briefing                        ← 快速掃描（Sonnet，~1min）
/briefing full                   ← + 情緒面、法人籌碼
/briefing deep                   ← 完整版含重訊/法說 + 個股分析（Opus）
/briefing telegram               ← 生成 Telegram 推送格式（寫出檔案，不發送）
/briefing telegram --send        ← 生成並推送至 Telegram + email
/briefing full --send --codex    ← 完整版 + Codex + 推送
```

### 個股研究

```
/stock-analysis 2330             ← 台積電
/stock-analysis 2454 3034        ← 聯發科 vs 聯詠，依 EV 排序
/stock-analysis 3661 --codex     ← + Codex 獨立第二意見
```

### 台指期 / 選擇權分析

```
/options-strategy TXO sell-put            ← 台指選擇權賣方價外 put
/options-strategy TXO bull-put-spread     ← 台指買權/賣權價差
/options-strategy 2330 stock-future       ← 個股期貨
/options-strategy TX hedge                ← 台指期空單避險現股
```

### 交易記錄

```
/trade-journal auto              ← 自動偵測倉位變動
/trade-journal log               ← 手動記錄交易
/trade-journal review            ← 檢視計畫執行進度
/trade-journal summary           ← 月度損益摘要
```

### 手動重發 Briefing

```bash
python3 tools/send_briefing.py latest        # 重發最新一份
python3 tools/send_briefing.py 2026-05-12    # 重發特定日期
DRY_RUN=1 python3 tools/send_briefing.py latest   # Dry-run（不實際發送）
```

---

## Telegram 自動推送

每個 TWSE 交易日 **台灣時間 14:00**（收盤後 30 分鐘，盤後籌碼/法人買賣超已公布）自動推送收盤決策摘要。週五加 `--codex` 第二意見。

### Telegram 訊息格式

```
📊 5/12 收盤 14:00

📰 News & Catalysts
  • 3661 世芯-KW: 法說會釋出 ASIC 大客戶新案，Q2 guide 上修

📅 本週重大事件
  • 2330 台積電 4/17 法說 — 先進製程 capex / HPC 需求指引
  • 月營收公布日 5/10 前（全持倉）

📊 Sentiment Pulse (中文新聞 7d)
  📈 改善: 3034 聯詠 +0.80, 2308 台達電 +0.75
  ⚠️ 注意: 3008 大立光 急降 +0.60→−0.20

💰 估值 & Thesis
  📉 最低估: 2454 聯發科 vs 公允價 −18%（三錨點中位 1,450）
  📈 最高估: 3661 世芯 vs 公允價 +35%
  📋 今日 thesis: 2330:法說capex指引 → partial 公允價 1,180→1,120（−5.1%）

🔄 Sector Rotation
  💪 leading: IC 設計（vs 加權指數 +12%）
  📈 improving: 散熱/PCB
  💀 lagging: 面板、金融

📊 籌碼面（三大法人）
  💰 外資連 3 日買超：2330、2454
  ⚠️ 投信調節：3008 連 2 日賣超

🚨 Alerts
  • 3008 大立光 ⚠️ 月營收公布前，技術訊號暫停

🎯 今日待辦
  • 3661: 等法說 reaction settle 後評估加碼

📋 明日待辦
  • 確認 5/10 月營收 cluster 倉位（2330/2454/3034）

⚡ Quick Take
  指數量縮但 IC 設計仍 leading，外資回補權值。
  本週核心：台積法說 + 全持倉月營收公布。
```

### 快速設定

**Step 1 — Telegram Bot**

1. 開啟 Telegram → 搜尋 `@BotFather` → `/newbot`
2. 輸入 bot 名稱和 username，取得 `TELEGRAM_BOT_TOKEN`
3. 對你的 bot 傳一則訊息，然後在瀏覽器開啟：
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
4. 從回傳 JSON 找 `"chat": {"id": ...}` → 取得 `TELEGRAM_CHAT_ID`

**Step 2 — Gmail App Password**

1. Google 帳戶 → 安全性 → 兩步驟驗證（先開啟）→ 應用程式密碼
2. 選「其他（自訂名稱）」→ 輸入 `fadacai` → 產生 16 字元密碼

**Step 3 — 設定 `.env`**

```bash
cp .env.example .env
```

編輯 `.env`，填入以下欄位：

```bash
TELEGRAM_BOT_TOKEN=123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=1234567890

SMTP_USER=your-email@gmail.com
SMTP_PASS="xxxx xxxx xxxx xxxx"    # Gmail App Password，務必加引號
EMAIL_FROM=your-email@gmail.com
EMAIL_TO=your-email@gmail.com
```

> ⚠️ `SMTP_PASS` 如果有空格**必須**加引號，否則 bash 會解析錯誤。

**Step 4 — 安裝 Python 依賴**

```bash
pip3 install -r tools/requirements.txt
```

**Step 5 — 安裝 launchd 排程（macOS）**

```bash
cp tools/launchd/com.fadacai.briefing.plist ~/Library/LaunchAgents/
# 修改 plist 中的路徑（如果專案目錄不同）
launchctl load ~/Library/LaunchAgents/com.fadacai.briefing.plist
launchctl list | grep fadacai    # 確認已載入（PID 欄顯示 -）
```

**Step 6 — macOS TCC 權限（必做）**

launchd 背景程序需要存取專案目錄裡的腳本：

1. **System Settings** → **Privacy & Security** → **Full Disk Access**
2. 點 **+** → 按 `Shift+Cmd+G` → 輸入 `/bin` → 選 **bash** → Open
3. 確認開關為 **ON**

**Step 7 — 手動測試**

```bash
# 立刻觸發（不等 14:00）
launchctl start com.fadacai.briefing

# 觀察 log
tail -f briefing-out/launchd.log

# 確認發送成功
tail -1 briefing-out/send-log.jsonl
# → {"date": "...", "telegram": "ok", "email": "ok"}
```

### 架構說明

```
launchd (每日台灣時間 14:00，TWSE 交易日)
    │
    ▼
~/.local/bin/fadacai_briefing_runner.sh   ← TCC-safe wrapper
    ├── check_trading_day.py              ← TWSE 休市日 exit 0
    ├── 週五 → CODEX_FLAG="--codex"
    ├── [non-fatal] fetch_macro.py        ← 台灣總經快取（TTL 36h）
    ├── [non-fatal] earnings_history.py   ← FinMind 財報/月營收快取（TTL 24h）
    ├── [non-fatal] fetch_fundamentals.py ← FinMind 基本面快取（TTL 24h）；含 A4 自建估值（CAGR→own_fwdEPS→own_target）
    ├── [non-fatal] fetch_news.py         ← 中文新聞全文快取（TTL 6h）；P3 訊號擷取的 body 來源
    └── claude -p "/briefing telegram --send $CODEX_FLAG"
            │
            ▼
        .claude/skills/briefing/SKILL.md (telegram tier)
            ├── Step 0.65: 讀 fundamentals cache（三錨點估值輸入）
            ├── T1: 重大事件 Window（法說/月營收/除權息，from cache）
            ├── T2: Sentiment Pulse（中文新聞 sentiment_trend）
            ├── T2.5: 💰 估值 & Thesis Pulse（cache 算，signal-only）
            ├── T3: News & Catalysts
            ├── T4: Sector Rotation
            ├── T4.5: 籌碼面（三大法人買賣超）
            ├── T5-T7: Alerts / 待辦 / QuickTake
            ├── T8a: 寫 briefing-out/YYYY-MM-DD-full.md
            ├── T8b: 寫 briefing-out/YYYY-MM-DD-telegram.txt
            └── tools/send_briefing.py YYYY-MM-DD
                    ├── POST Telegram Bot API（> 4096 字自動切段）
                    ├── SMTP send email（精簡版 + 完整 markdown）
                    └── 寫 briefing-out/send-log.jsonl
```

### 輸出檔案

| 檔案 | 說明 |
|------|------|
| `briefing-out/YYYY-MM-DD-full.md` | 完整 briefing markdown（email 附件） |
| `briefing-out/YYYY-MM-DD-telegram.txt` | Telegram 純文字格式 |
| `briefing-out/send-log.jsonl` | 每次發送記錄（時間、狀態、dry_run） |
| `briefing-out/launchd.log` | launchd 排程執行 log |
| `briefing-out/launchd.err` | launchd 錯誤 log |

> `briefing-out/` 已加入 `.gitignore`（含個人帳戶數據，不 commit）。

### 常見問題排解

| 問題 | 排查 |
|------|------|
| `Operation not permitted` | FDA 未授予 `/bin/bash`（見 Step 6） |
| `SMTP_PASS: command not found` | App Password 有空格但沒加引號（`.env` 需加 `"`） |
| `Unknown command: /briefing` | runner 需 `cd $REPO_ROOT` 後才呼叫 claude（已內建） |
| Telegram 沒收到 | 確認 `TELEGRAM_CHAT_ID` 是你的個人 chat id，不是群組 id |
| `exchange_calendars not installed` | `pip3 install exchange_calendars`（有 fallback，非致命） |
| launchd.log 空白 | job 還在跑（claude 需要 2-5 分鐘），等待後再看 |

---

## MCP Servers

| Server | 功能 | 備註 |
|--------|------|------|
| **shioaji-server** | 即時持倉、帳戶餘額、成交歷史、報價 | 主要帳戶數據源（永豐金 Shioaji 參考整合） |
| **finmind-server** | 即時報價、財報、月營收、法人買賣超、分點籌碼 | 主要市場數據源（FinMind） |
| **mops-server** | 公開資訊觀測站：重大訊息、法說會、月營收公告、財報、內部人持股 | 官方法規文件 |
| **twse-server** | 同類股比較、漲跌幅排行、產業分類（證交所/櫃買開放 API） | 補充數據 |
| **technical-mcp** | RSI、MACD、布林通道、ATR、動量分數、S/R levels | 技術分析 |
| **cnyes-news** | **`get_news`**（中文新聞全文 body/symbols/tags，P3 訊號擷取用）+ LLM 中文情緒分析 + **基本面快照**（本益比/PEG/殖利率/法人/季度成長）| 情緒分析 + 新聞全文 |
| **chip-server** | 三大法人買賣超、融資融券、台指期未平倉（大額交易人）、借券 | 籌碼面/聰明錢部位 |

**MCP Retry Policy：** 失敗 → 重試 3 次 → 健康檢查 → fallback WebSearch/WebFetch，輸出中標記 `⚠️ [server] MCP 不可用`。

---

## 關鍵本地檔案

| 檔案 / 目錄 | 用途 | 更新方式 |
|------------|------|---------|
| `plan.md` | 投資計畫：板塊目標、策略佇列、觀察清單 | 手動（僅在用戶要求時） |
| `journal/` | 每日交易日誌（YYYY-MM-DD.md），含完整倉位快照 | 自動（Step 0c/0d + hook） |
| `feedback/` | 交易風格規則，所有 skill 每次必讀 | 手動（學習後更新） |
| `research/` | 個股投資論文（半導體供應鏈、AI 伺服器、散熱等） | 手動 |
| `.env` | Telegram + SMTP 設定（**gitignored**，cp .env.example） | 手動 |
| `tools/` | Pipeline 腳本：`send_briefing.py`、`check_trading_day.py`、`briefing_runner.sh`、`fetch_macro.py`、`fetch_fundamentals.py`（FinMind 基本面 + A4 自建估值快取）、`fetch_news.py`（中文新聞全文快取，TTL 6h）、`earnings_history.py`、`thesis_ledger.py`、`test_self_valuation.py`（A4 單元測試） | git tracked |
| `briefing-out/` | 每日 briefing 輸出 + 發送 log（**gitignored**） | 自動生成 |
| `briefing-out/cache/` | 預載快取：`macro-snapshot.json` / `earnings-history.json` / `earnings-dates.json` / `fundamentals-snapshot.json`（含 A4 `self_valuation`，TTL 24h）/ `news-articles.json`（全文 600-char excerpts，TTL 6h）— **日報 zero-latency 數據層** | 自動（runner + launchd） |
| `docs/briefing-auto-send.md` | Telegram 設定完整教學 | git tracked |
| `CLAUDE.md` | 完整專案指令手冊（Step 0 規範、MCP 政策、模型分工） | 手動 |

---

## 常見問題

**MCP 掛了怎麼辦？**
執行 `/mcp-health` 診斷，通常重開 Claude Code session 即可。三次重試後自動 fallback WebSearch。

**倉位資料從哪來？**
`mcp__shioaji-server__get_account_position` 取即時數據（Step 0b 自動執行）。

**交易記錄在哪？**
`journal/` 目錄，每日一檔（YYYY-MM-DD.md），每次 skill 執行都會建立或更新。

**配置計畫在哪？**
`plan.md` — 含板塊目標（%）、策略佇列（⏳/✅/🔄）、觀察清單、策略原則。

**第一性原理紀律是什麼？**
每個 Verdict / Recommendation 前強制填寫：核心 thesis（可驗證命題）+ 證偽條件（2-3 個 falsifiable 觀察點）+ 機率分布（EV 計算）。確保結論有 ground truth 依據，不是 narrative。

**Telegram 每天幾點收到？**
台灣時間 14:00（TWSE 交易日，收盤後 30 分鐘，盤後三大法人買賣超已公布）。

---

## 方法論亮點

這套框架的核心不是「叫 LLM 給意見」，而是用多層紀律強迫每個結論落在可驗證的 ground truth 上：

- **第一性原理紀律（Step 0e）** — 任何 Verdict 前強制回答三題：① 核心 thesis（1 句**可驗證命題**，非 narrative）② 證偽條件（2-3 個 falsifiable 觀察點）③ 機率分布 + EV（由 `probability-honesty-checker` agent 強制計算，禁用 default bell shape 與「略偏多」這類質性語言）。
- **三錨點 Fair PE 估值（Section 8.5 / G3.5）** — 不手寫 PE 倍數猜想；用三個獨立錨點做三角定位：A1 市場隱含本益比（FinMind）/ A2 PEG 成長合理倍數 / A3 分析師目標價隱含 PE（券商報告/FinMind）。Base = median；Bull = max × 1.25；Bear = min × 0.70。`pe_ratio == 0.0` / `peg_ratio == 0.0` → 自動丟棄該錨，標 `(anchor unavailable)`。台股加做**殖利率錨**（現金股利 ÷ 股價 vs 歷史區間）作 sanity check。
- **Thesis Ledger（`tools/thesis_ledger.py`）** — 把帶觸發點的 thesis 登錄進帳本，到期（如法說會/月營收日）自動回頭抓實際數字驗收 passed/failed，累積命中率。詳見 [`docs/thesis-ledger.md`](docs/thesis-ledger.md)。
- **Thesis 驗證 → 股價影響（D2 三桶分解）** — thesis verdict 不只是分類；`resolve` 時帶結構化旗標：`fair_value_before/after`（三錨點重算）+ `price_impact_pct` + `impact_decomp`（thesis 成分 vs 倍數重估成分分解）。
- **全持倉基本面快取（`briefing-out/cache/fundamentals-snapshot.json`）** — `fetch_fundamentals.py` 每交易日 launchd 預載，TTL 24h。Quick/Telegram tier 直接讀快取（zero-latency，不等 MCP）；Deep tier 強制刷新。
- **A4 自建估值錨（sanity / divergence flag）** — `fetch_fundamentals.py` 同次 API call 計算：`own_fwdEPS = 歷史 CAGR (幾何，40% cap → fade 向 8% terminal) × 淨利率 ÷ 股數`（完全不看分析師 estimate）。`own_target_price = own_fwdEPS × base_FairPE(median A1,A2,A3)`。**A4 不進 EV**，僅做分歧 flag。34 單元測試（`test_self_valuation.py`）覆蓋 CAGR、cap、decel、macro clamp、guardrails。
- **新聞全文快取 + P3 訊號擷取（`briefing-out/cache/news-articles.json`）** — `fetch_news.py` TTL 6h，top 8 篇/標的，600-char body excerpt。Deep tier §9.5 / stock-analysis Step 4b 從新聞 body + 重訊 + 法說逐字稿抽**已量化陳述**（晶圓投片/capex/ASP/月營收 YoY 等），強制附 raw_quote（≤120 字逐字引用），signal → thesis 轉換後以 `--source signal-inference` 登錄 thesis_ledger，閉環追蹤 P3 命中率。反幻覺鎖：**無 raw_quote = 無 signal = 不登錄。**

## 如何擴展

- **新增 skill**：在 `.claude/skills/<name>/SKILL.md` 建立，frontmatter 設 `user_invocable: true` + `description`，內文遵循 `CLAUDE.md` 的 Step 0 統一規範。
- **新增資料 agent**：純抓資料的子代理用 `data-collector`（Haiku）；需要紀律推理的用既有 pattern。
- **新增工具**：放 `tools/`，純標準函式庫優先（如 `thesis_ledger.py` 即零相依），方便他人免裝依賴執行。
- **調整交易風格**：`feedback/*.md`（本機個人檔，已 gitignored）每次 skill 必讀，是把你的偏好餵給框架的地方。

完整規範與設計細節見 [`CLAUDE.md`](CLAUDE.md)。

## 授權

[MIT License](LICENSE) — 自由使用、修改、商用，保留版權聲明即可。

## 免責聲明

本專案為**投資研究與紀律輔助工具**，所有輸出（含 Verdict、EV、機率、台指期/選擇權建議）**僅供研究與教育參考，不構成投資建議、要約或保證**。台股、台指期與選擇權交易具高度風險，可能導致本金全部損失。你需自行評估並承擔一切交易決策與後果，並自備所有 API key 與券商憑證；作者與貢獻者不對任何使用本專案所致之損失負責。
