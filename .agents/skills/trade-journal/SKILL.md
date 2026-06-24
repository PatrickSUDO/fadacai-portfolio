---
name: trade-journal
description: Record trades, track execution vs plan, and review trade history. Usage - /trade-journal [action] where action is log, review, or summary.
user_invocable: true
model: claude-sonnet-4-6
---

# Trade Journal

Track trades and compare execution against the investment plan.

## Arguments
- `/trade-journal log` — Record a new trade (manual or auto-detect from position changes)
- `/trade-journal review` — Show recent trades and compare to plan
- `/trade-journal summary` — Monthly P&L summary
- `/trade-journal auto` — 只做倉位變動偵測（不需手動輸入）

## Step 0: 配置同步 & 倉位偵測

### 0a. 每次必做
- 讀取 `plan.md` — 掌握計畫中的待辦操作，用於判斷交易是否「按計畫執行」
- 讀取 `feedback/*.md` — 套用交易風格偏好

### 0b. 倉位取得與 journal 判斷（auto 例外）
1. 若 action 是 `auto` → **無論今天是否已偵測，都重新執行完整偵測**（這是 auto 的主要功能）
2. 若 action 是 `log`/`review`/`summary`：
   - 呼叫 `mcp__shioaji-server__get_account_position` 取得即時持倉
   - 檢查 `journal/YYYY-MM-DD.md`（今天日期）是否已存在
   - **若已存在** → 跳過偵測，使用即時持倉進入主流程
   - **若不存在** → 執行完整偵測（見下方 Auto-Detect）

---

## Workflow

### Auto-Detect（完整偵測流程）

**倉位變動自動偵測（後減前）：**

1. 呼叫 `mcp__shioaji-server__get_account_position` 取得即時持倉（後 = 最新倉位）
2. 找到 `journal/` 目錄下**最新的** `.md` 檔案（前 = 上次快照）
3. 解析「前」檔案的倉位表格：
   - 現股：從「現股持倉」或 Stocks 表格提取 {ticker: quantity}
   - 選擇權：從「選擇權持倉」或 Options 表格提取 {contract: quantity}
4. 解析「後」（即時持倉）的倉位表格：同上
5. **比較差異**：

   **股票：**
   ```
   for each ticker in 後:
     if ticker not in 前 → 「🆕 新建倉：{ticker} {qty} 股」
     if ticker in 前 and qty changed → 「📈 加碼 / 📉 減碼：{ticker} {前qty} → {後qty}」
   for each ticker in 前:
     if ticker not in 後 → 「🔴 已清倉：{ticker} {前qty} 股」
   ```

   **選擇權：**
   ```
   比較合約名稱（Symbol + Strike + Expiry + Type）
   新合約 → 「🆕 新開倉」
   消失的合約 → 「🔴 已平倉/到期」
   數量變化 → 「加減倉」
   ```

6. **輸出偵測結果**給用戶確認：
   ```
   ## ⚡ 自動偵測到的倉位變動（vs 上次快照 YYYY-MM-DD）

   | 類型 | 操作 | 標的 | 變化 | 計畫對應 |
   |------|------|------|------|----------|
   | 股票 | 🆕 新建倉 | DDOG | 57 股 | ✅ SaaS建倉計畫 #1 |
   | 股票 | 🔴 清倉 | DY | 18 股 | ❓ 非計畫操作 |
   ```

7. **計畫對應**：比對 `plan.md` 的待辦清單
   - 如果交易匹配計畫中的操作 → 標記 ✅ 並引用計畫編號
   - 如果是計畫外操作 → 標記 ❓ 提醒用戶記錄原因

### Log a Trade

1. 如果 auto-detect 已偵測到變動 → 以偵測結果為基礎，詢問用戶補充：
   - 交易價格（auto-detect 無法得知）
   - 交易原因
   - 是否按計畫執行
2. 如果用戶手動提供交易資訊 → 直接記錄
3. 建立/更新檔案：`journal/YYYY-MM-DD.md`

**日記檔案格式：**

```markdown
# 交易日誌 — YYYY/MM/DD

## 帳戶總覽
| 項目 | 數值 |
|------|------|
| 股票市值 | $XXX,XXX |
| 選擇權市值 | $XX,XXX |
| 總資產 | ~$XXX,XXX |
| 今日變動 | +/- $X,XXX (+/- X.XX%) |
| 總損益 | +/- $X,XXX (+/- X.XX%) |

## 今日交易
| 時間 | 操作 | 代碼 | 合約 | 數量 | 價格 | 金額 | 計畫對應 |
|------|------|------|------|------|------|------|----------|
（若為自動偵測，時間欄填「—」，價格欄填「待確認」）

## 交易後倉位變化摘要
- TICKER: 前 → 後（描述）

## 現股持倉
| 代碼 | 股數 | 現價 | 成本 | 市值 | 損益 | 損益% |
|------|------|------|------|------|------|-------|
（從即時持倉取得，作為下次比較的快照）

## 選擇權持倉
| 代碼 | 合約 | 數量 | 現價 | 成本 | 市值 | 損益 | 損益% |
|------|------|------|------|------|------|------|-------|
（從即時持倉取得）

## 備註
- 用戶補充的交易原因和覆盤筆記
```

4. 記錄完成後，檢查是否需要更新配置計畫：
   - 提示用戶：「此交易是否需要更新 plan.md？」

### Review

1. 讀取 `journal/` 目錄下所有檔案
2. 讀取 `plan.md`
3. 生成：

```markdown
## Trade Review

### 計畫執行進度
| # | 計畫操作 | 狀態 | 執行日期 | 備註 |
（從配置計畫的「待執行操作」逐項對照）

### 計畫外交易
| 日期 | 操作 | 標的 | 原因 |

### 交易統計（本月）
- 總交易次數: XX
- 勝率: XX%
- 平均盈利: XX%
- 平均虧損: XX%
- 最佳交易: ...
- 最差交易: ...
```

### Summary

1. 計算月度 P&L
2. 選擇權收入統計（premium 收入 vs 到期損益）
3. 組合價值變化趨勢
4. 計畫執行率（完成 / 總待辦）

## File Structure
```
journal/
├── 2026-03-03.md    ← 每日一檔（含完整倉位快照）
├── 2026-03-04.md
└── ...
```

Create the trade-journal directory if it doesn't exist.

## 重要：倉位快照
**每個 journal 檔案都必須包含完整的「現股持倉」和「選擇權持倉」表格**，
這是下次「後減前」比較的數據來源。沒有快照就無法偵測變動。

## Output Language
Use Traditional Chinese (繁體中文) for all text output.
