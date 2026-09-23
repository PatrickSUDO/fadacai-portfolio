---
name: ev-check
description: 強制 first-principles 機率分布 + EV 計算。用於檢查當前組合在指定時間窗的預期報酬，禁止用 default bell shape 或質性語言。Usage - /ev-check [30d|7d|14d] [optional scenario theme]
user_invocable: true
model: opus
---

# EV / Probability Distribution Honesty Check

對當前持倉執行嚴謹的機率分布與 expected value 計算。**強制 first-principles**，不接受偷懶輸出。

此 skill 可獨立呼叫做 ad-hoc check，或被其他 skill（briefing / portfolio-review / stock-analysis / todo）在輸出 Verdict / 機率分布前 mandatory 呼叫。

## Arguments

- `/ev-check` → 預設 30 天 horizon
- `/ev-check 7d` / `/ev-check 14d` / `/ev-check 30d` → 自選時間窗
- `/ev-check 30d nvda-bear` → 用戶指定情境主題（agent 會以此為主要 catalyst 反推）
- `/ev-check 30d 比選 ...` → **名額比選模式**。比選集合不是 briefing 點名的那幾檔，而是 **plan.md 候補表整層 L1 全掃**（2026-09-21 用戶質問「選 HWM 不選 ATI 什麼理由」，當次只比了 briefing 框的 HWM/CRDO，ATI 漏掉）。作法：先列 L1 每一檔的「進場分支是否成立（價格線/走強線）、分析師覆蓋 N、與空名額同鏈的上下游關係」做一張淘汰表，明寫每檔為何進或不進 EV 計算；只對淘汰表存活者跑 agent。淘汰表要出現在輸出裡，用戶事後問任何一檔都要能指出被淘汰的那一行。**落選者同一次撤提名警報**（`shadow_signals.py record --kind cf-bench-loser` 已自動撤該標的 `price_above`/`rolling_high` 線；輸出列「已撤警報」欄，見 `feedback/alert-hygiene.md`）。

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
- 1g. Sentiment 健康度（display-only，不進機率；2026-09-11 影子測試無擇時訊號）
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

### Step 3.4: EV 怎麼用才不算濫用（2026-09-23 用戶 push back「跟 SGOV 比很不公平」，三條修正）

1. **基準看情境，不是永遠 SGOV。** 組合滿編（砍一進一）時，新倉的比較對象是**最弱在倉那檔的 EV**（機會成本閘門原文），SGOV 只在「另一個選擇真的是現金」（R24 閒置、名額空著）時才是基準。拿 SGOV 判換手決策 = 用錯閘門。
2. **EV 必附誤差帶，差距在帶內不得當裁決依據。** `ev_ledger.py stats` 2026-09-23：已驗收 15 筆，平均絕對誤差 **10.0pp**、平均偏差 −8.9pp（歷史偏樂觀）、Brier 技能分數 <0。輸出格式一律「EV −1.7%（±10pp）」；兩個選項 EV 差 <10pp 視為**無法區分**，裁決改看其他維度（相關度、thesis 成立機率、加權下行、載具）。n≥30 獨立樣本後依實測誤差重訂帶寬。
3. **有出場閘門的部位另算「規則管理版 EV」。** 365d 買抱不動的 EV 會把最壞 regime 整段吃進去；實際部位有 R23 線 / thesis gate / R14 後的機械出場，左尾被截斷。做法：對 thesis 破的 regime 把報酬改為「閘門觸發時的截斷損失」（財報 gate 通常 −15%~−20%）重算 Σ，兩版並列，標明哪一版對應用戶實際的持有方式。

**Why：** NET 9/23 案——報告以「365d EV −9.6% 輸 SGOV 13.5pp」判不建倉，但 ①當時 18/18 滿編、真正對手是 MYRG；②5.7pp（FSLY）的差距在 10pp 誤差內；③用戶的部位有 10/29 硬閘門，截斷後 EV 約 −5%。用戶「感覺就不成立」是對的：原則沒錯（風險資產期望值須高於無風險利率），錯在用錯基準與把 ±10pp 的數字當精準門檻。

### Step 3.5: EV ledger 事前登錄（強制，agent 輸出後執行）

```
python3 tools/ev_ledger.py add --ticker PORTFOLIO --slug <主題>-<horizon> \
  --horizon-days <N> --spot <帳戶即時總值> \
  --p-bull XX --p-base XX --p-bear XX --ev-pct <X.XX> \
  --source ev-check --model <本次模型>
```
機率/EV 直接抄 agent 輸出；spot 用帳戶即時總值（resolve 時對 `research/equity-marks.json` 最近標記）。到期由 briefing `resolve-due` 驗收，校準由 /trade-review 讀 `stats`。

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
