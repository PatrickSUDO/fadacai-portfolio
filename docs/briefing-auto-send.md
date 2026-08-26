# Briefing Auto-Send Setup

每個 NYSE 交易日 ET 13:00 自動跑 `/briefing telegram`，推送精簡摘要到 Telegram，同時 email 副本（精簡版 + 完整 briefing markdown）到你的信箱。週五自動加 Codex 第二意見。

---

## 快速起步（5 步驟）

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
SMTP_PASS=abcd efgh ijkl mnop    # 16 字元 app password（可帶空格）
EMAIL_FROM=your-email@gmail.com
EMAIL_TO=your-email@gmail.com
```

其他欄位保留預設值即可。

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

### 立刻觸發 launchd（不等 13:00）

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

## 輸出檔案

```
briefing-out/
├── YYYY-MM-DD-full.md        # 完整 briefing markdown（email 用）
├── YYYY-MM-DD-telegram.txt   # Telegram 精簡純文字
├── send-log.jsonl            # 每次發送記錄（日期、狀態、Telegram/Email OK 或 failed）
├── launchd.log               # launchd stdout
└── launchd.err               # launchd stderr
```

---

## 疑難排解

**launchd 沒跑**
```bash
launchctl list | grep fadacai
# 若無輸出 → 沒有 load
launchctl load ~/Library/LaunchAgents/com.fadacai.briefing.plist
```

**Telegram 收不到訊息**
- 確認 bot token 正確（BotFather `/mybots`）
- 確認你有先傳訊息給 bot（Telegram bot 需要用戶先 initiate）
- 確認 TELEGRAM_CHAT_ID 是你自己的 ID 而非 bot ID

**Gmail 認證失敗**
- 確認使用 App Password，不是你的 Gmail 登入密碼
- 確認 2-Step Verification 已啟用
- SMTP_PASS 可帶空格（16 字元 app password 通常每 4 字元有空格）

**`exchange_calendars` 找不到**
```bash
pip3 install exchange_calendars
# 或
uv pip install exchange_calendars
```

**claude CLI 找不到**
plist 的 `PATH` 需包含 `claude` 的安裝路徑。查詢：
```bash
which claude
# 把那個目錄加到 plist EnvironmentVariables → PATH
```

---

## 開源配置說明

若要在別的機器或分享給他人：

1. `.env` 不 commit（已 gitignore），每個人自己填 token/密碼
2. plist 路徑需對應各自的 home 目錄，依 README 步驟替換 `YOUR_USERNAME`
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
- **`Operation not permitted`（TCC）**：repo 在 `~/Desktop`（受保護）。launchd job 第一次存取會跳「取用桌面」彈窗，按一次「允許」後就持續有效（不需每天按）。若真的反覆跳，把 `/bin/bash` 加進 系統設定→隱私權→完整取用磁碟。
- **`runs` 不增加 / 今天沒跑**：dark-wake 沒撐住 → 見上方 caffeinate。
- **`.env` 語法錯誤殺死 runner（2026-08-03 四修）**：往 `.env` 加含 `;` `(` `)` 空格的原始字串（cookie/UA/JSON）**必須包單引號**——bash `source` 會直接 syntax error、exit 2，連 launchd.log 都不寫（log mtime 停格是指紋）。互動 session 正常（Python loader 容忍）但自動排程全滅。指紋：`launchctl print … | grep "last exit"` 非 0 + `launchd.err` 出現 `.env: line N: syntax error`。修完用 `bash -c 'set -a; source ./.env'` 驗證。
- **API mid-stream 斷流連殺（2026-08-04/05 五修）**：`launchd.log` 出現 `API Error: Response stalled mid-stream` / `Connection closed mid-response`，每次 run 跑 50-70 分鐘後死 = Anthropic 端串流中斷，非本機問題。**根因放大器 = runner 未指定模型繼承大模型**，run 時間遠超 telegram tier 規定的 Sonnet。已修（`tools/briefing_runner.sh`）：① `claude -p` 加 `--model "$BRIEFING_MODEL"`（預設 `sonnet`，env 可覆寫）② `RETRY_MAX` 預設 3→**5** ③ backoff 改 60s 遞增（60/120/180/240s）。
- **三／五次全滅後手動補發 SOP**：先殺殘留程序（`pkill -f "claude -p /briefing"` 再殺 runner PID），然後在互動 session 直接跑 `/briefing telegram --send` —— `send_briefing.py` 的 dedup 保證與稍後任何自動重跑不重複推送。
- **手動補發**：`launchctl kickstart -k gui/$(id -u)/com.fadacai.briefing`（會真的推一封）。
