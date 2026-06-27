# FMP MCP 容器化說明

> 2026-06-28 實作。此文件說明 FMP MCP server 的容器架構、日常操作、以及必要時回滾到 launchd 的步驟。

## 架構概覽

| 元件 | 位置 |
|------|------|
| Source + Dockerfile | `/Users/supatrick/laptop/mcp-servers/fmp-mcp/` |
| compose.yaml | 同上 |
| .env（token）| 同上，gitignored |
| Claude Code 設定 | `.mcp.json → {"type":"http","url":"http://localhost:8081/mcp"}` — **不動** |
| curl 旁路 helper | `tools/fmp_query.py` |
| watchdog script | `tools/mcp_watchdog.sh` |
| watchdog plist | `~/Library/LaunchAgents/com.fadacai.mcp-watchdog.plist` |
| 歸檔舊 plist | `~/Library/LaunchAgents/com.fadacai.fmp-mcp.plist.bak` |

**重點：Claude Code 的 `fmp-mcp` 設定 URL 不變（`http://localhost:8081/mcp`），容器化對 skill 完全透明。**

## 為什麼容器化不能直接修好 session expired？

FMP 是 stateful HTTP server（每個 `initialize` 建立一個 session）。Claude Code client 快取它拿到的 `Mcp-Session-Id`；server 端把閒置 session 淘汰後，client 仍用舊 id → `Session not found or expired`。容器重啟只是清空 server 端 session store，client 的 stale id 問題不解。

**根本解是 `tools/fmp_query.py` helper**：它每次做全新 handshake，建完即棄，永遠不持有 stale session。

## 日常操作

### 確認狀態
```bash
docker compose -f /Users/supatrick/laptop/mcp-servers/fmp-mcp/compose.yaml ps
curl http://localhost:8081/healthcheck
```

### 重啟容器（session 卡死或 wedged）
```bash
docker compose -f /Users/supatrick/laptop/mcp-servers/fmp-mcp/compose.yaml restart
# 再 /mcp → reconnect fmp-mcp 讓 Claude Code client 拿新 session
```

### 查看 log
```bash
docker compose -f /Users/supatrick/laptop/mcp-servers/fmp-mcp/compose.yaml logs --tail 50
```

### 重建映像（更新程式碼後）
```bash
cd /Users/supatrick/laptop/mcp-servers/fmp-mcp
git pull    # 或 git fetch + 手動 merge
docker compose up -d --build
```

### FMP session expired → 用 helper 旁路（不需 reconnect）
```bash
python3 tools/fmp_query.py getBiggestGainers
python3 tools/fmp_query.py getStockPeers --args '{"symbol":"NVDA"}'
python3 tools/fmp_query.py getEarningsCalendar --args '{"from":"2026-06-28","to":"2026-07-28"}'
python3 tools/fmp_query.py getCompanyProfile --args '{"symbol":"AAPL"}'
python3 tools/fmp_query.py getMostActiveStocks
```

## Watchdog

`com.fadacai.mcp-watchdog.plist` 每 5 分鐘探一次 `GET /healthcheck`：
- 正常 → 靜默不記 log（避免噪音）
- Docker daemon 未啟動 → `open -a Docker` 等 20s
- FMP 無回應 → `docker compose restart` + 記 log

watchdog log：`/Users/supatrick/laptop/mcp-servers/fmp-mcp/watchdog.log`（自動輪替 1MB）

```bash
# 手動測 watchdog
bash /Users/supatrick/laptop/project/fadacai-portfolio/tools/mcp_watchdog.sh

# 查看 watchdog log
tail -30 /Users/supatrick/laptop/mcp-servers/fmp-mcp/watchdog.log
```

## 重要前提

**Docker Desktop 必須設為登入自啟：**
Settings → General → ☑️ Start Docker Desktop when you sign in

若 Docker Desktop 未開 → FMP 容器不跑 → MCP + helper 都無法使用。

## 回滾到 launchd（如需要）

```bash
# 1. 停止容器並停 watchdog
docker compose -f /Users/supatrick/laptop/mcp-servers/fmp-mcp/compose.yaml down
launchctl bootout gui/$(id -u)/com.fadacai.mcp-watchdog

# 2. 還原舊 plist
cp ~/Library/LaunchAgents/com.fadacai.fmp-mcp.plist.bak \
   ~/Library/LaunchAgents/com.fadacai.fmp-mcp.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.fadacai.fmp-mcp.plist
launchctl start com.fadacai.fmp-mcp

# 3. 驗證
curl http://localhost:8081/healthcheck
```

## Token 管理

`FMP_ACCESS_TOKEN` 存在 `/Users/supatrick/laptop/mcp-servers/fmp-mcp/.env`（gitignored）。

舊 plist 有 token 明文 → 已歸檔為 `.bak`。若需更換 token：
1. 編輯 `.env`
2. `docker compose up -d`（環境變數在啟動時注入）
