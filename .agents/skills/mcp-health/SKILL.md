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
| 1 | shioaji-server | `get_account_balance` | `()` |
| 2 | finmind-server | `get_stock_info` | `("2330")` |
| 3 | mops-server | `get_company_info` | `("2330")` |
| 4 | twse-server | `get_industry_list` | `()` |
| 5 | technical-mcp | `get_technical_indicators` | `("2330")` |
| 6 | cnyes-news | `get_sentiment_trend` | `("2330", 7)` |
| 7 | chip-server | `get_institutional_netbuy` | `("2330", 5)` |

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
| shioaji-server | ✅ Healthy | ~Xs | 即時持倉來源 |
| finmind-server | ✅ Healthy | ~Xs | — |
| mops-server | ✅ Healthy | ~Xs | — |
| twse-server | ✅ Healthy | ~Xs | 證交所/櫃買開放 API |
| technical-mcp | ✅ Healthy | ~Xs | — |
| cnyes-news | ❌ Failed | — | 連線失敗 |
| chip-server | ✅ Healthy | ~Xs | 三大法人/籌碼 |

健康: X/7 | 異常: X/7
```

### 4. 失敗時的處理

對於 ❌ Failed 的 server，顯示：
- 錯誤訊息摘要
- 手動重啟指令（僅顯示，**不自動執行**）：

```
# 手動重啟指令（請在終端機執行）：
# finmind-server:
cd /path/to/finmind-server && uv run server.py

# mops-server:
cd /path/to/mops-server && uv run server.py

# twse-server:
cd /path/to/twse-server && uv run server.py
```

### 5. 建議

- 若 1-2 個 server 失敗 → 建議重啟該 server，其他 skill 可正常使用（會 fallback）
- 若 3+ 個 server 失敗 → 建議重啟 Claude Code session
- 提醒：MCP server 由 Claude Code 自動管理，通常重開 session 即可恢復

## Output Format
- 繁體中文輸出
- 簡潔表格格式
- 預估執行時間：~30 秒
