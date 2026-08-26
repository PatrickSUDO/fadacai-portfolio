# Briefing Auto-Send Setup

每個 NYSE 交易日在你設定的 launchd 排程時間自動跑 `/briefing telegram`，推送精簡摘要到 Telegram，同時 email 副本（精簡版 + 完整 briefing markdown）到你的信箱。週五自動加 Codex 第二意見。

**架構特色：**
- **睡眠免疫**：排程前 `pmset` 喚醒 + `caffeinate` 保清醒，闔蓋/睡眠中的 Mac 也能準時發
- **失敗安靜、補發冪等**：失敗只記 log 不推錯誤訊息（Telegram 只收正式報告）；手動補發 `/briefing telegram --send`，`send_briefing.py` dedup 保證不重複推送
- **headless 韌性**：生成固定用 Sonnet（`BRIEFING_MODEL` 可覆寫）縮短單次 run 曝險、單窗內最多重試 5 次（遞增 backoff）
- 週五自動加 `--codex` 第二意見

---

## 訊息格式範例

```
📊 5/12 盤中 13:00 ET

📰 News & Catalysts
  • ICHR: Q1 beat，Q2 guide $290-310M，GAAP EPS 轉正

📅 Earnings This Week
  • NVDA 5/20 AMC — HBM demand，data-center 指引

📊 Sentiment Pulse (EODHD 7d)
  📈 改善: ONTO 1.00, STRL 0.90, AVGO 0.90
  ⚠️ 注意: MU 急降 0.97→0.51

💰 估值 & Thesis
  📉 最低估: MU vs 公允價 −22%（三錨點中位 $375）
  📈 最高估: ARM vs 公允價 +38%
  📋 今日 thesis: AVBO:q2-guide → partial 公允價 $460→$415（−9.8%）

🔄 Sector Rotation
  💪 leading: 半導體 SMH (+34.9% vs SPY)
  📈 improving: 工業 XLI
  💀 lagging: 能源 XLE

🚨 Alerts
  • ICHR ⚠️ 財報 reaction window，技術訊號暫停

🎯 今日待辦
  • ICHR: 等 reaction settle 後評估加碼至 100 股

📋 明日待辦
  • 確認 5/20 cluster 倉位（QCOM/ON/ANET/NVDA）

⚡ Quick Take
  全面回調但 SMH 仍 leading，sentiment 全面正面。
  本週核心：ICHR reaction + 5/20 四檔財報前倉位確認。
```

---

## 快速起步（6 步驟）

### 1. 申請 Telegram Bot

1. 開 Telegram，搜尋 **@BotFather**，點 Start
2. 輸入 `/newbot`，跟著提示取名（例：`my_briefing_bot`）
3. BotFather 會給你一個 token，格式：`123456789:AAFxxxxxxxxxxxxxxxx`
4. 開 **@userinfobot**，點 Start → 它會回傳你的 **numeric chat ID**（例：`987654321`）

### 2. 取得 Gmail App Password

1. Google Account → **Security** → **2-Step Verification**（需已開啟）
2. 往下找 **App passwords**
3. Select app: Mail / Select device: Mac → **Generate**
4. 記下 16 字元的 app password（不含空格）

### 3. 建立 .env 設定檔

```bash
cd /path/to/portfolio
cp .env.example .env
```

編輯 `.env`，填入：
```
TELEGRAM_BOT_TOKEN=123456789:AAFxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=987654321
SMTP_USER=your-email@gmail.com
SMTP_PASS=abcd efgh ijkl mnop    # 16 字元 app password（可帶空格，需加引號）
EMAIL_FROM=your-email@gmail.com
EMAIL_TO=your-email@gmail.com
```

> ⚠️ `SMTP_PASS` 如果有空格**必須**加引號（`SMTP_PASS="xxxx xxxx xxxx xxxx"`），否則 bash 會解析錯誤。

其他欄位保留預設值即可，完整變數說明見 [`setup.md`](setup.md)。

### 4. 安裝 Python 依賴

```bash
pip3 install -r tools/requirements.txt
# 或用 uv：
uv pip install -r tools/requirements.txt
```

### 5. 安裝 launchd 排程

```bash
# 複製 plist，並替換 YOUR_USERNAME 和路徑
cp tools/launchd/com.fadacai.briefing.plist ~/Library/LaunchAgents/

# 編輯 plist 換成你的實際路徑
nano ~/Library/LaunchAgents/com.fadacai.briefing.plist
# 把所有 YOUR_USERNAME 和 /path/to/portfolio 換成實際值

# 載入排程
launchctl load ~/Library/LaunchAgents/com.fadacai.briefing.plist

# 確認已載入
launchctl list | grep fadacai
```

### 6. macOS TCC 權限（必做）

launchd 背景程序需要存取專案目錄裡的腳本：

1. **System Settings** → **Privacy & Security** → **Full Disk Access**
2. 點 **+** → 按 `Shift+Cmd+G` → 輸入 `/bin` → 選 **bash** → Open
3. 確認開關為 **ON**

首次執行也可能跳一次性的「取用」彈窗，按允許即可，之後不需每天按。

---

## 測試

### 手動發送一次（推薦先測）

在 Claude Code session 內：
```
/briefing telegram --send
```

或直接用腳本重發最新一份：
```bash
python3 tools/send_briefing.py latest
```

### Dry-run（不實際發送，只印出內容）

```bash
DRY_RUN=1 python3 tools/send_briefing.py latest
```

### 立刻觸發 launchd（不等排程時間）

```bash
launchctl start com.fadacai.briefing
tail -f briefing-out/launchd.log
```

### 測試非交易日跳過

```bash
FAKE_DATE=2026-05-16 python3 tools/check_trading_day.py
# 預期：exit 1，印出 "2026-05-16 is NOT a NYSE trading day"
```

### 測試 Telegram 連線

```bash
# 臨時 token 測試（用壞 token 看 retry 行為）
TELEGRAM_BOT_TOKEN=bad RETRY_MAX=1 python3 tools/send_briefing.py latest
# 預期：retry 1 次失敗，send-log.jsonl 記 failed，email 獨立發送
```

---

## 手動使用方式

| 指令 | 說明 |
|------|------|
| `/briefing telegram` | 跑 telegram tier，寫 briefing-out/ 兩個檔案，**不**發送 |
| `/briefing telegram --send` | 跑 + 發送到 Telegram + Email |
| `/briefing full --send` | 完整 full briefing + 發送（telegram 格式從 full 內容提取）|
| `python3 tools/send_briefing.py latest` | 重發最新一份（不重新跑 briefing）|
| `python3 tools/send_briefing.py 2026-05-12` | 重發特定日期 |

---

## 每週行為

| 日期 | 行為 |
|------|------|
| 週一至週四 | `/briefing telegram --send`（無 Codex）|
| 週五 | `/briefing telegram --send --codex`（加 Codex 第二意見）|
| 週六、週日 | 跳過（不執行）|
| NYSE 休市日 | 跳過（exchange_calendars 判斷）|

---

## 架構說明

實際執行順序照 `tools/briefing_runner.sh`：

```
launchd（排程時間自訂，NYSE 交易日才跑）
    │
    ▼
tools/briefing_runner.sh                  ← TCC-safe wrapper
    ├── check_trading_day.py              ← NYSE 休市日 exit 0
    ├── 週五 → CODEX_FLAG="--codex"
    ├── [non-fatal] fetch_macro.py        ← FRED 總經快取（TTL 36h）
    ├── [non-fatal] earnings_history.py   ← yfinance 盈餘快取（TTL 24h）
    ├── [non-fatal] fetch_fundamentals.py ← EODHD 基本面快取（TTL 24h）；含 A4 自建估值
    ├── [non-fatal] fetch_news.py         ← EODHD 新聞全文快取（TTL 6h）；P3 訊號擷取的 body 來源
    ├── [non-fatal] fetch_twitter.py      ← X API v2 來源信用訊號抓取（按量計費，成本封頂）
    ├── [non-fatal] fetch_leading.py      ← 先行指標五 block（TTL 20h）
    ├── [non-fatal] trade_ledger.py snapshot-orders   ← 在掛單快照（歸因 ground truth，斷天補不回來）
    ├── [optional]  briefing_local_hooks.sh           ← 機器本地 hooks（untracked，非致命）
    ├── [non-fatal] account_metrics.py scan && report ← 帳戶級四指標（R15 回檔熔斷輸入）
    ├── [non-fatal] shadow_signals.py flag            ← A4 高估旗標記錄
    ├── [non-fatal] source_credit.py resolve-due      ← 來源信用帳到期驗收（view 自動抓價，fact 只列）
    ├── [non-fatal] archive_cache.py                  ← 每日決策輸入凍結快照（120 天，需在快取刷新後執行）
    └── claude -p "/briefing telegram --send $CODEX_FLAG" --model sonnet   ← RETRY_MAX 5、backoff 60s 遞增
            │
            ▼
        .claude/skills/briefing/SKILL.md (telegram tier)
            ├── Step 0.65: 讀 fundamentals cache（三錨點估值輸入）
            ├── Step 0.68: 讀 twitter/source-credit cache（Trusted+ 來源訊號）
            ├── T1: Earnings Window（from cache）
            ├── T2: Sentiment Pulse（EODHD sentiment_trend）
            ├── T2.5: 💰 估值 & Thesis Pulse（cache 算，signal-only）
            ├── T3: News & Catalysts
            ├── T4: Sector Rotation
            ├── T5-T7: Alerts / 待辦 / QuickTake
            ├── T8a: 寫 briefing-out/YYYY-MM-DD-full.md
            ├── T8b: 寫 briefing-out/YYYY-MM-DD-telegram.txt
            └── tools/send_briefing.py YYYY-MM-DD
                    ├── POST Telegram Bot API（> 4096 字自動切段）
                    ├── SMTP send email（精簡版 + 完整 markdown）
                    └── 寫 briefing-out/send-log.jsonl
```

---

## 輸出檔案

| 檔案 | 說明 |
|------|------|
| `briefing-out/YYYY-MM-DD-full.md` | 完整 briefing markdown（email 附件） |
| `briefing-out/YYYY-MM-DD-telegram.txt` | Telegram 純文字格式 |
| `briefing-out/send-log.jsonl` | 每次發送記錄（時間、狀態、dry_run） |
| `briefing-out/launchd.log` | launchd 排程執行 log |
| `briefing-out/launchd.err` | launchd 錯誤 log |

> `briefing-out/` 已加入 `.gitignore`（含個人帳戶數據，不 commit）。

---

## 疑難排解

| 問題 | 排查 |
|------|------|
| `launchd` 沒跑 | `launchctl list \| grep fadacai`；無輸出 → 沒有 load，重新 `launchctl load ~/Library/LaunchAgents/com.fadacai.briefing.plist` |
| `Operation not permitted`（TCC） | 見上方「快速起步 Step 6」；仍反覆跳彈窗 → 系統設定→隱私權與安全性→完整磁碟取用 加入 `/bin/bash` |
| `SMTP_PASS: command not found` | App Password 有空格但沒加引號，`.env` 需 `SMTP_PASS="xxxx xxxx xxxx xxxx"` |
| `Unknown command: /briefing` | runner 需先 `cd $REPO_ROOT` 再呼叫 claude（已內建於 `briefing_runner.sh`）|
| Telegram 收不到訊息 | 確認 bot token 正確（BotFather `/mybots`）；確認你已先對 bot 傳過訊息（bot 需用戶先 initiate）；確認 `TELEGRAM_CHAT_ID` 是你自己的個人 ID，不是群組 ID 或 bot ID |
| Gmail 認證失敗 | 確認使用 App Password，不是 Gmail 登入密碼；確認 2-Step Verification 已啟用；`SMTP_PASS` 可帶空格 |
| `exchange_calendars` 找不到 | `pip3 install exchange_calendars`（或 `uv pip install exchange_calendars`；有 fallback，非致命） |
| `claude` CLI 找不到（exit 127） | plist 的 `PATH` 需包含 `claude` 安裝路徑，`which claude` 查詢後加入 |
| launchd.log 空白 | job 還在跑（claude 需要 2-5 分鐘），等待後再看 |
| `.env: line N: syntax error` + 三／五窗全滅 | `.env` 有未加引號的特殊字元值（cookie/JSON）→ 包單引號後 `bash -c 'set -a; source ./.env'` 驗證，詳見下方「故障排除」 |
| `API Error: ... mid-stream` 連續殺掉 headless run | Anthropic 端串流不穩，非本機問題；確認 runner 有 `--model sonnet`，詳見下方「故障排除」 |

---

## 開源配置說明

若要在別的機器或分享給他人：

1. `.env` 不 commit（已 gitignore），每個人自己填 token/密碼
2. plist 路徑需對應各自的 home 目錄，依步驟替換 `YOUR_USERNAME`
3. `briefing-out/` 不 commit（已 gitignore），純 local 輸出
4. 唯一需要 commit 的是 `.env.example`（模板）、`tools/`（scripts）、`tools/launchd/`（plist 模板）

## 喚醒排程 + 不睡著（單一發送時間）

發送時間（系統本地 CET/CEST）：**17:00，一天只試這一次**。無備援窗；失敗只記 log，**不**推 Telegram 錯誤訊息（2026-06-11 用戶決定：Telegram 只收正式 briefing）。

**喚醒（把 Mac 叫醒）**
- `pmset repeat wakepoweron … 16:59 weekdays` — 16:59 喚醒，涵蓋 17:00 發送窗。

**保持清醒（關鍵）** — 實測 16:59 scheduled wake 只是 dark-wake，2 秒後就釋放、可能在 17:00 前又睡回去，導致 launchd 推遲 17:00 job（症狀：`launchctl print` 顯示 `runs` 沒增加）。解法：
- **`com.fadacai.caffeinate` LaunchAgent**（`tools/launchd/com.fadacai.caffeinate.plist`）在 16:59 weekdays 跑 `caffeinate -u -t 5520`，把 Mac 從 16:59 撐到 18:31 — 涵蓋 runner 常態情況（Sonnet 單次 ~15-20 分 + 快取刷新）；極端多次重試會超出此窗，屆時依賴 AC `sleep 0` 保持清醒。
- 安裝：`cp tools/launchd/com.fadacai.caffeinate.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.fadacai.caffeinate.plist`

## 故障排除：自動推送失敗 / 卡死

- **`claude -p` 卡滿 timeout ×N**：headless 跑遇到 Claude 工具權限提示無法回答。runner 已加 `--dangerously-skip-permissions`（信任的自動化、跑自己的 repo）。注意此旗標**不**繞過 macOS TCC 檔案彈窗。
- **`Operation not permitted`（TCC）**：repo 在受保護目錄下。launchd job 第一次存取會跳「取用」彈窗，按一次「允許」後就持續有效（不需每天按）。若真的反覆跳，把 `/bin/bash` 加進 系統設定→隱私權→完整取用磁碟。
- **`runs` 不增加 / 今天沒跑**：dark-wake 沒撐住 → 見上方 caffeinate。
- **`.env` 語法錯誤殺死 runner（2026-08-03 四修）**：往 `.env` 加含 `;` `(` `)` 空格的原始字串（cookie/UA/JSON）**必須包單引號**——bash `source` 會直接 syntax error、exit 2，連 launchd.log 都不寫（log mtime 停格是指紋）。互動 session 正常（Python loader 容忍）但自動排程全滅。指紋：`launchctl print … | grep "last exit"` 非 0 + `launchd.err` 出現 `.env: line N: syntax error`。修完用 `bash -c 'set -a; source ./.env'` 驗證。
- **API mid-stream 斷流連殺（2026-08-04/05 五修）**：`launchd.log` 出現 `API Error: Response stalled mid-stream` / `Connection closed mid-response`，每次 run 跑 50-70 分鐘後死 = Anthropic 端串流中斷，非本機問題。**根因放大器 = runner 未指定模型繼承大模型**，run 時間遠超 telegram tier 規定的 Sonnet。已修（`tools/briefing_runner.sh`）：① `claude -p` 加 `--model "$BRIEFING_MODEL"`（預設 `sonnet`，env 可覆寫）② `RETRY_MAX` 預設 3→**5** ③ backoff 改 60s 遞增（60/120/180/240s）。
- **三／五次全滅後手動補發 SOP**：先殺殘留程序（`pkill -f "claude -p /briefing"` 再殺 runner PID），然後在互動 session 直接跑 `/briefing telegram --send` —— `send_briefing.py` 的 dedup 保證與稍後任何自動重跑不重複推送。
- **手動補發**：`launchctl kickstart -k gui/$(id -u)/com.fadacai.briefing`（會真的推一封）。
