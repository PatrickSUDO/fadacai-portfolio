# Setup 踩坑速查

從零安裝（7 個 MCP + Telegram 自動推送）實際會卡住的點。憑證放 `.env` / `.mcp.json`（皆 gitignored），本檔無金鑰。

## 1. MCP 安裝：能 uvx 就別 clone
能用 PyPI 套件或單檔 server 的就別 clone：
```bash
claude mcp add finmind-server --env FINMIND_TOKEN=xxx -- uv --directory /path/to/finmind-server run server.py
claude mcp add mops-server -- uv --directory /path/to/mops-server run server.py
claude mcp add chip-server -- uv --directory /path/to/fadacai-mcp-servers/chip run server.py
claude mcp add technical -- uv --directory /path/to/fadacai-mcp-servers/technical run server.py
claude mcp add cnyes-news -- uv --directory /path/to/cnyes-news run server.py
```
> macOS 別用 `pip3`（撞 PEP 668），一律 `uv` / `uvx`。

## 2. twse-server / mops-server：證交所 & 公開資訊觀測站開放 API
兩者用官方開放資料，**免 token**：
- 證交所 OpenAPI：<https://openapi.twse.com.tw/>
- 櫃買 OpenAPI：<https://www.tpex.org.tw/openapi/>
- 公開資訊觀測站 MOPS：<https://mops.twse.com.tw/>（重訊/法說/月營收/財報/內部人）

坑：開放 API 有流量限制，批量抓籌碼/法人時加 polite delay；月營收每月 10 日前才更新。

## 3. shioaji-server：自建 Python MCP（永豐金）
官方無現成 MCP，改用 PyPI `shioaji` 套件自寫 FastMCP（範例見 `shioaji-server-example/`）。重點：
- **以 `api_key`/`secret_key` 登入**（永豐個人首頁 → API 金鑰管理），查詢持倉/報價**不需憑證**。
- **下單才需 `activate_ca`（憑證 .pfx）**；純研究/查詢可不啟用，跑 `shioaji_setup.py login` 確認金鑰可登入即可。
- **金鑰從 server 自己的 `.env` 讀**，別用 `claude mcp add --env`（會明碼寫進 `~/.claude.json`）。
- 雜：登入失敗多為金鑰過期/IP 限制；憑證失敗檢查 `person_id` 與 .pfx 密碼。可替換成富邦 neo / 元大，只要對外提供相同 `get_account_*` 工具介面。

## 4. headless `claude -p` 兩大坑（會 exit 0 但沒產出）
- **PATH 找不到 claude**（exit 127）：plist 的 `PATH` 加 `/Users/YOU/.local/bin`。
- **MCP 權限非互動模式無法授予**：claude 拿不到持倉→拒絕捏造→空手而回。解法 `.claude/settings.json` 預授權：
- **claude -p 可能 hang 數小時**（尤其同機另有互動 claude session 時）：runner 用 `perl -e 'alarm shift; exec @ARGV' 900 claude -p ...` 加 900s 硬超時，超時 exit 142 走 retry，避免卡死。
```json
{ "enableAllProjectMcpServers": true,
  "permissions": { "defaultMode": "acceptEdits",
    "allow": ["mcp__shioaji-server","mcp__finmind-server","mcp__technical",
      "mcp__cnyes-news","mcp__mops-server","mcp__twse-server","mcp__chip-server",
      "Read","Edit","Write","Task","WebSearch","WebFetch","Bash(python3 *)"] } }
```

## 5. 子代理拿不到 MCP → 用 `.mcp.json`
`claude mcp add` 存的是 project scope，子代理/別的目錄載不到。專案根放 `.mcp.json`（含 token，務必 gitignore，範本見 `.mcp.json.example`）。

## 6. macOS TCC
launchd 跑 `/bin/bash` 存取專案目錄被擋（`Operation not permitted`）→ System Settings → Privacy & Security → Full Disk Access → 加 `/bin/bash`。

## 7. Mac 睡眠 → launchd 不觸發（筆電最大坑）
launchd 在睡眠不觸發，`pmset wake` 喚醒後筆電（尤其合蓋 clamshell）常立刻睡回去，到觸發那秒又睡著。單一固定時間極不可靠。

**解法 — 多觸發點 + dedup**（best for laptop）：plist 設多個 `StartCalendarInterval`（台灣時間 14:00 / 15:00 / 16:00），只要當天任一時段醒著就觸發；`briefing_runner.sh` 開頭檢查「今天發過沒」、`send_briefing.py` 再 dedup → 一天最多實際發一次。
```xml
<key>StartCalendarInterval</key>
<array>
  <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>0</integer></dict>
  <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
  <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
</array>
```
搭配 pmset 喚醒第一個時間點（需 sudo、接 AC）：
```bash
sudo pmset repeat wake MTWRF 13:50:00   # 台灣時間，14:00 前 10 分鐘
```
> 仍要求機器在某個觸發點是醒的。完全可靠需接 AC + 設定「接電源永不睡眠」，或合蓋接外接螢幕。

## 8. 雜項
- **`SMTP_PASS` 有空格要加引號**：`SMTP_PASS="xxxx xxxx xxxx xxxx"`。
- **dedup**：`send_briefing.py` 同日只發一次，重發要清 `send-log.jsonl` 當日記錄。
- `exchange_calendars`（XTAI 台股日曆）/ 台灣總經(FinMind) 429 皆非致命（有 fallback / cache）。

## 驗證
```bash
claude mcp list                  # 7 個 ✓ Connected
launchctl list | grep fadacai    # briefing + caffeinate
```
成功標誌：`claude -p "/briefing telegram --send"` 跑完，`briefing-out/` 出現當天兩檔 + `send-log.jsonl` 多一筆 `"telegram":"ok","email":"ok"`。
