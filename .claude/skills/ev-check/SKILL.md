---
name: ev-check
description: 強制 first-principles 機率分布 + EV 計算。用於檢查當前組合在指定時間窗的預期報酬，禁止用 default bell shape 或質性語言。Usage - /ev-check [30d|7d|14d] [optional scenario theme]
user_invocable: true
model: claude-opus-4-8
---

# EV / Probability Distribution Honesty Check

對當前持倉執行嚴謹的機率分布與 expected value 計算。**強制 first-principles**，不接受偷懶輸出。

此 skill 可獨立呼叫做 ad-hoc check，或被其他 skill（briefing / portfolio-review / stock-analysis / todo）在輸出 Verdict / 機率分布前 mandatory 呼叫。

## Arguments

- `/ev-check` → 預設 30 天 horizon
- `/ev-check 7d` / `/ev-check 14d` / `/ev-check 30d` → 自選時間窗
- `/ev-check 30d nvda-bear` → 用戶指定情境主題（agent 會以此為主要 catalyst 反推）

## Workflow

### Step 1: 收集 raw 輸入

呼叫以下 MCP 取數據（可平行）：

1. `mcp__firstrade-server__get_account_position` — 持倉
2. `mcp__firstrade-server__get_account_balance` — 帳戶總值 + 現金
3. `mcp__technical-mcp__get_batch_indicators(所有持倉, period=3mo)` — RSI / momentum / trend
4. `mcp__technical-mcp__get_sector_rotation(period=3mo)` — leading / lagging
5. `mcp__yfinance-advanced__get_stock_info(top 11 by MV)` — 52w high/low、fundamentals
6. `mcp__fmp-mcp__getEarningsCalendar(today, today+horizon)` — binary catalysts in window
7. （平行 agent）`mcp__eodhd-mcp__get_sentiment_trend(top 8 by MV, days=30)` — 7d/30d sentiment
8. Read `briefing-out/cache/macro-snapshot.json` — macro state（fed_funds / 2s10s / HY OAS / VIX / CPI / regime_tag）；`status == "skipped"` 或缺失 → 1i 標 `unavailable` 並註明

### Step 2: 整理成 9 項 Input Enumeration

按 `probability-honesty-checker` agent 的 Step 1 contract，整理：

- 1a. RSI 分布（每個 bucket 檔數 + % of port）
- 1b. 距 52w 高位置（中位數、最大、最小）
- 1c. 已實現波動（5d / 2d / 最大單日）
- 1d. Binary catalysts table（catalyst / 日期 / 影響持倉 % / base rate）
- 1e. 集中度（top 1、top 5、最大板塊）
- 1f. 板塊輪動曝險（leading 持倉 % / lagging 持倉 %）
- 1g. Sentiment 健康度
- 1h. Thesis 健康度（從 plan.md + 近期新聞）
- 1i. Macro state（從 macro-snapshot.json：fed_funds + 30d change / 2s10s + regime / hy_oas + regime + pct_1y / vix + regime / cpi_yoy + trend / regime_tag；agent 缺 1i 會回 INVALID INPUT）

**不齊全 → 不能進下一步**，必須補齊。

### Step 3: 呼叫 probability-honesty-checker subagent

```
Agent(
  subagent_type: "probability-honesty-checker",
  description: "EV check for [horizon]",
  prompt: """
  執行 6 步強制流程計算當前組合 [horizon] 機率分布與 EV。

  時間窗: [horizon]
  情境主題（如有）: [user-specified]

  ## Step 1 輸入資料（8 項齊全）:
  [貼上 Step 2 整理好的資料]

  ## 額外 context:
  [plan.md 摘要 / 用戶提到的特定 catalyst / 最近 N 天的事件]

  請按你的 6 步流程輸出：
  1. Input Enumeration（confirm 我給的齊全）
  2. 形狀反推
  3. Conditional Probabilities
  4. Aggregated Scenario Probabilities
  5. EV Calculation
  6. Self-Audit Checklist
  + 給主 skill 的精簡輸出
  """
)
```

### Step 4: 顯示 agent 完整輸出

不刪減、不簡化、不重寫。直接呈現 agent 的 6 步流程 + 精簡輸出。

主 skill 看到的格式：
```
# EV Check — [horizon]

[Agent 完整 6 步輸出]

---

## ✅ 給用戶的精簡結論

機率分布：樂觀 X% / 基準 X% / 悲觀 X%
EV ([horizon]) = X.XX%
主導因素：[1 句]
```

### Step 5: 用戶 push back 處理

如果用戶質疑「你真的有算嗎」「這是 default 嗎」：
- **不要辯解、不要重組原數字**
- 重跑 Step 3（重新呼叫 agent，明確要求 audit checklist 全勾）
- 如果發現原本確實偷懶（例如 sum 沒到 100%、機率是 default mirror、EV 寫質性語言）→ 老實承認 + 顯示新算

---

## 何時被其他 skill 呼叫

以下 skill 在輸出 **Verdict / 機率分布 / EV / Quick Take** 之前 **必須** 呼叫此 skill（或直接 invoke probability-honesty-checker agent）：

- `/briefing`（任何 tier）→ Quick Take 前
- `/portfolio-review` → Section K 第一性檢查前
- `/stock-analysis` → 個股 Verdict 前
- `/todo` → 行動清單第一性檢查前

呼叫方式可選：
- 走 ev-check skill（完整流程，給用戶看的格式）
- 直接 invoke `probability-honesty-checker` agent（內部使用，省一層 wrapping）

## Output Format

繁體中文。所有數字 explicit。**絕不出現**：「略偏正」「略偏負」「中性偏多」「應該會」「不確定性高」等質性語言 — 全部換成數字區間或機率。

## 失敗模式與防呆

| Claude 主程序常見偷懶 | 此 skill 阻擋方式 |
|---------------------|----------------|
| 套 30/45/25 default | Agent Step 2 強制顯示「形狀規則應用」對照表，不對照不能進 Step 3 |
| 寫「略偏負」結論 | Agent Step 5 強制顯式 Σ 計算，數字必須出現 |
| 跳過 Step 1 直接給機率 | Agent 收到不完整 input 回「INVALID INPUT」拒絕計算 |
| Sum ≠ 100% | Agent Step 4 顯式 sum check |
| 中點手動偏移 | Agent Step 5 強制 (max+min)/2 算術平均 |
