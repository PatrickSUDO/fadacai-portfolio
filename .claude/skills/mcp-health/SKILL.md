---
name: mcp-health
description: Test all MCP server connections and report health status. Usage - /mcp-health
user_invocable: true
model: claude-haiku-4-5-20251001
---

# MCP Health Check

測試所有 MCP server 的連線狀態，快速診斷問題。

## Workflow

### 1. 平行測試所有 MCP Server

盡可能同時呼叫以下 7 個測試，使用最簡單的工具確認連線：

| # | Server | 測試工具 | 測試呼叫 |
|---|--------|---------|---------|
| 1 | firstrade-server | `get_account_balance` | `()` |
| 2 | yfinance-advanced | `get_stock_info` | `("AAPL")` |
| 3 | sec-edgar-mcp | `get_company_info` | `("AAPL")` |
| 4 | fmp-mcp | `getCompanyProfile` | `("AAPL")` |
| 5 | technical-mcp | `get_technical_indicators` | `("AAPL")` |
| 6 | eodhd-mcp | `get_sentiment_trend` | `("AAPL.US", 7)` |
| 7 | polymarket-mcp | `get_trending_markets` | `()` |

### 2. 判定狀態

對每個 server 的回應判定：
- **✅ Healthy** — 正常返回數據
- **⚠️ Degraded** — 返回但數據不完整或響應異常慢
- **❌ Failed** — 呼叫失敗或超時

### 3. 輸出狀態表

```
## MCP Server 健康檢查

| Server | 狀態 | 延遲 | 備註 |
|--------|------|------|------|
| firstrade-server | ✅ Healthy | ~Xs | 即時持倉來源 |
| yfinance-advanced | ✅ Healthy | ~Xs | — |
| sec-edgar-mcp | ✅ Healthy | ~Xs | — |
| fmp-mcp | ✅ Healthy | ~Xs | Free tier |
| technical-mcp | ✅ Healthy | ~Xs | — |
| eodhd-mcp | ❌ Failed | — | 連線失敗 |
| polymarket-mcp | ✅ Healthy | ~Xs | Demo mode |

健康: X/7 | 異常: X/7
```

### 4. 失敗時的處理

對於 ❌ Failed 的 server，顯示：
- 錯誤訊息摘要
- 手動重啟指令（僅顯示，**不自動執行**）：

```
# 手動重啟指令（請在終端機執行）：

# yfinance-advanced（uvx @0.1.2，由 Claude Code 自管 stdio subprocess）：
# → 通常重開 Claude Code session 即恢復；若需驗證版本：
#   uvx yfinance-mcp@0.1.2 --help

# sec-edgar-mcp（uvx @1.0.8，由 Claude Code 自管）：
# → 重開 Claude Code session 即恢復

# fmp-mcp（Docker 容器，非 stdio，不由 Claude Code 管）：
docker compose -f /Users/supatrick/laptop/mcp-servers/fmp-mcp/compose.yaml restart

# fmp-mcp 旁路驗證（不需 /mcp reconnect，直接測 helper）：
python3 /Users/supatrick/laptop/project/fadacai-portfolio/tools/fmp_query.py getCompanyProfile --args '{"symbol":"AAPL"}'

# fmp-mcp session expired（常見）→ 用 helper 取資料，不用 reconnect：
python3 /Users/supatrick/laptop/project/fadacai-portfolio/tools/fmp_query.py getBiggestGainers
```

### 5. 建議

- 若 1-2 個 server 失敗 → 建議重啟該 server，其他 skill 可正常使用（會 fallback）
- 若 3+ 個 server 失敗 → 建議重啟 Claude Code session
- 提醒：MCP server 由 Claude Code 自動管理，通常重開 session 即可恢復

## Output Format
- 繁體中文輸出
- 簡潔表格格式
- 預估執行時間：~30 秒
