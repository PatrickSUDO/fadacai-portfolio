---
name: todo
description: "生成下一個交易日的優先行動清單。當用戶問「明天開盤要做什麼」、「今天要操作什麼」、「給我待辦」、「接下來要做什麼」、「有什麼需要處理」等問題時立刻使用此 skill。也適用於盤中（「現在有什麼要做」）和盤後（「今天還有什麼沒做」）場景。不要等用戶說 /todo 才觸發，只要問的是「下一步行動」的問題就應該用。"
user_invocable: true
model: claude-sonnet-4-6
---

# Portfolio Action Todo

根據當前持倉、投資計畫、選擇權狀態，生成有優先順序的行動清單。

## 資料讀取順序

### Step 0：AGENTS.md 統一規範（含 0e 第一性原理紀律）
執行 0a → 0b → 0c → 0d → **0e**。每個 🔴/🟡/🟢 行動項目都必須通過第一性檢查（thesis / 證偽條件 / 機率），否則該項應移到「⏸ 不動」並註明缺乏明確 thesis。

### Step 1：取得即時持倉（必做）
同時執行：
- `mcp__firstrade-server__get_account_position` — 即時持倉（股票 + 選擇權）
- 讀取 `plan.md` — 計畫中待辦事項

### Step 2：讀取 journal（快速掃描）
- 找今天的 `journal/YYYY-MM-DD.md`
- 若存在，掃描「已執行」事項，避免重複建議

### Step 3：技術面補充（選擇性，快速版跳過）
僅對「需要確認進場時機」的標的，呼叫：
- `mcp__technical-mcp__get_batch_indicators` — 快速取 RSI/動能
- 目的是確認「現在進場還是等」

---

## 分析框架

掃描以下六個維度，找出需要行動的項目：

### A. 選擇權急迫性（最優先）
- 剩餘天數 < 14 天的合約 → 🔴 急迫
- 剩餘天數 14-30 天的合約 → 🟡 注意
- PMCC 短腿距 strike < 5% → 🔴 急迫（可能被 call 走）
- BPS/BCS 已達 50-75% 最大利潤 → 🟡 考慮平倉

### B. 計畫中待執行策略
- 從 `plan.md` 找「⏳ 待執行」項目
- 對照當前市價，判斷觸發條件是否已達成

### C. 個股異常（日內 — 必過根因/revision 閘門，禁純價格反應）
- 今日單檔跌超 5% → 先跑根因分類（`feedback/weak-signal-root-cause.md`）：只有 thesis 破裂 (a) 才列減碼；earnings reaction / sector rotation / noise → 「⏸ 不動」。revision 仍上修的深跌 = 洗盤錯殺 → 列加碼候選
- 今日單檔漲超 8% → 查 revision 方向（`feedback/momentum-valuation-symmetry.md`）：**revision 上修中的加速領導者 → 讓 run，不列停利**（強者愈強，超買非賣出理由）；revision 轉折/flat + 高倍數 + 認列桶 → 列 harvest（GTC 賣階梯或開 CC）。**CC 只對認列循環桶開，信念桶不封頂**（>10% 紅線減碼除外）

### D. 待開新倉位
- 從對話或計畫中識別「討論過但尚未進場」的 Spread
- 確認市況是否符合進場條件
- 新倉必過機會成本閘門：優於最弱在倉名額才進；14–18 上緣 → 指名砍一進一

### E. 需設警報的監控項目
- 不需要立刻動，但需要盯的價位或事件

### F. 飛輪 / 停利再投入（每次必掃 — per `feedback/momentum-valuation-symmetry.md`）
- **梯級停利到價**：認列桶倉位觸及/逼近下一級（+30/+60/+100/每+50pp，per `feedback/tiered-profit-taking.md`）而無 GTC 掛單 → 列補掛行動（含級距價 + 股數）
- **今日該 Realize 什麼**：認列桶 Swing Risk 🔴（肥利潤 + 高β + revision 轉折）→ 列 harvest 行動（附 GTC 賣單/CC 結構，可提前下一級）
- **Harvest 配對去處**：每筆停利同時列 redeploy 目標（信念桶領導者 / L1 revision 最陡者 + 進場結構），或標 `dry powder + 觸發條件`
- **現金滯留**：現金 >15–20% 且無掛單覆蓋、無理由 → 🔴 列「部署決策」行動項

---

## 輸出格式

用繁體中文輸出，結構固定如下：

```
## 今日/明日開盤行動清單
📅 [日期] | 組合市值 $XXX,XXX

### 🔴 立即處理（開盤優先）
[條件達成或到期風險高的項目]

### 🟡 盤中監控（設好警報）
[需要觀察價格再決定的項目]

### 🟢 計畫進場（條件確認後執行）
[待開的 Spread/倉位，附條件]

### ⏸ 不動（持有觀察）
[今日下跌但無需操作的持倉，簡短說明為何不動]

### 📋 開盤時間軸
09:30 — ...
09:45 — ...
10:00 — ...
```

**每個行動項目要包含（第一性原理紀律）：**
- 標的 + 具體操作（例：「平倉 DDOG BPS 85/95」）
- **核心 thesis（1 句可驗證命題）**（例：「DDOG SaaS estimate 已 reset，Q2 beat 機率 60%」）
- **觸發條件 = 證偽條件之一**（例：「若 DDOG > $95，thesis 已 partially 兌現」）
- 口數 / 股數
- 最大風險金額（若是新倉）
- **Conditional 機率**（例：「此操作在 thesis 成立的 60% 條件下 expected +$XXX」）

> 若一個行動項目寫不出 thesis 或證偽條件，這項應改放「⏸ 不動（缺乏 thesis）」。寧可少做也不要做 narrative-driven 操作。

---

## 精簡原則

- 只列出「需要人做決定或操作」的項目
- 純持有觀察的倉位，簡短帶過即可
- 若同一標的有多個操作，合併為一個項目
- 時間軸只列出真正有時序要求的操作

---

## Phase 2: Codex 第二意見（opt-in）

**僅當 arguments 含 `--codex` 或 `--2nd` 時執行（例：`/todo --codex`）。**

三個子 block 依序執行（可並行派 Agent）：

### B1. 獨立第一性分析（預設，independent first-principles）

**核心原則：Codex 不看 Claude 的行動清單**（不給 🔴/🟡/🟢 分級與排序），只給 raw 持倉 + 計畫 ⏳ 項目 + 市場數據，讓它獨立排今日 priorities。Claude 與 Codex 兩個獨立輸出並排比較。

呼叫 Codex（**用 AGENTS.md「Codex 呼叫方式」的 `codex exec` CLI；勿用 codex:codex-rescue subagent / `/codex:rescue`，會卡 superpowers preamble**），prompt 首行加強制 no-tool 指令，模板：

```
我是一名美股投資人，使用 Level 2 options + Spread 的 margin 帳戶。
請對今日待辦清單，**完全獨立**排出 priorities — 不要看任何先前的優先序，這是獨立第二意見。

**Raw data（只給事實）：**
- 帳戶總值 / 現金
- 今日持倉清單（標的 / 股數 / 損益% / 占比%）
- plan.md ⏳ 待執行/待評估清單（原文）
- 主要持倉 RSI/趨勢
- 近期催化（4 天內財報日、產業事件）
- 投資風格：AI/半導體主軸、汰弱留強、信念持倉 [TSLA/MU/AVGO]

**請輸出（獨立判斷）：**

1. **今日 priorities thesis**（1 句：今日資金最該做什麼？理由？）

2. **獨立排出的行動清單**（最多 5 項，按優先序）：

   | 優先 | 操作 | 觸發條件 | 口數/股數 | 最大風險 | 為什麼 |
   |-----|------|---------|----------|---------|-------|
   | 🔴 | ... |

3. **最大風險判斷**（1 條：哪個操作如果做錯損失最大？）

4. **不該做的事**（2 條：明確排除的操作）

5. **Verdict**（1 句）：今日整體該進攻 / 防守 / 觀望？

**規則：**
- 必須講股數/口數
- 觸發條件必須 falsifiable
- 不假設 Claude 已說過什麼

請以繁體中文回覆，控制在 700 字內。

--effort high --fresh
```

### B2. 機會掃描（opportunity scout）

呼叫 Codex（用 AGENTS.md「Codex 呼叫方式」的 `codex exec` CLI）：

```
我目前的美股持倉（含市值占比）：
[插入持倉表，由 Step 1 的 get_account_position 取得]

我的投資風格：
- 主軸：AI/半導體、高成長科技；汰弱留強，集中持倉
- 信念持倉（不換）：TSLA, MU, AVGO 多年期 thesis
- 板塊偏好：[從 plan.md 摘出 3-5 行板塊目標]

請以獨立分析師視角：
1. 掃描今日市場有哪些當紅題材/個股，是我目前持倉沒覆蓋到的
2. 對每個候選列出：題材、代表 ticker、為何此刻有機會、建議切入方式（現股/Spread/LEAPS）
3. 要追這些新機會，最該砍掉哪一檔現有持倉？為什麼？
4. 2-3 個具體 actionable 建議（含目標 entry zone），可加進明日待辦

請以繁體中文回覆。輸出限 600 字。
```

### B3. 輪動分析（rotation scan）

**Step 1 — Claude 預先收集數據：**
- `mcp__technical-mcp__get_sector_rotation()` → 全板塊 ETF 相對強度 vs SPY（leading / improving / weakening / lagging）
- `mcp__technical-mcp__get_batch_indicators(tickers=[所有持倉])` → 個股動能分數 + 趨勢

**Step 2 — 呼叫 Codex（用 AGENTS.md「Codex 呼叫方式」的 `codex exec` CLI）：**

```
我的美股持倉（含市值占比 + 板塊歸屬）：
[持倉表]

當前板塊輪動數據（vs SPY）：
[get_sector_rotation 完整輸出]

當前個股動能：
[get_batch_indicators 摘要]

請以輪動專家視角：
1. 板塊輪動：哪些板塊 leading，哪些 weakening？我的持倉是否站在 leading 板塊？
2. 個股輪動：在我已持有的板塊內，有更強的 leader 我沒拿到？有持倉已被同板塊其他名字超越？
3. 資金流向：從 weakening 輪到 leading 的訊號是否明確？建議調倉路徑
4. 具體建議：3 條 actionable 輪動操作（從哪檔減 → 加到哪檔，附理由），可直接加入今日待辦

請以繁體中文回覆。輸出限 700 字。
```

### 輸出整合

```
## 🤖 Codex 第二意見

### B1. 獨立第一性分析（Codex 獨立排序）

**Codex priorities thesis：** [...]
**Codex 行動清單（獨立排序）：**

| 優先 | 操作 | 觸發條件 | 口數 | 最大風險 |
|-----|------|---------|------|---------|
| ... |

**Codex 最大風險判斷：** [...]
**Codex 不該做：** [...]
**Codex Verdict：** [...]

#### 並排比較：Claude vs Codex（獨立排序）

| 項目 | Claude 排序 | Codex 排序 | 一致性 |
|------|------------|-----------|--------|
| #1 操作 | [Claude] | [Codex] | 同 / 異 |
| #2 操作 | [Claude] | [Codex] | 同 / 異 |
| #3 操作 | [Claude] | [Codex] | 同 / 異 |
| Verdict | [Claude] | [Codex] | 同 / 異 |

**真實共識 priorities**（兩邊都排前 3 的）：[1-3 條 — 高信心今天做]
**真實分歧**（排序差很多的）：[1-3 條 — 值得深入]

### 機會掃描（vs 現有持倉）
[B2 Codex 完整回覆]

### 輪動分析（板塊 + 個股）
[B3 Codex 完整回覆]

---
**值得追蹤的新機會：** [從 B2 挑 1-2 個 Claude 也認同的]
**輪動 actionable：** [從 B3 挑 1-2 條 Claude 也認同的調倉操作]
```

### 進階：`--codex-adversarial`（opt-in 壓力測試）

僅當 arguments 含 `--codex-adversarial` 時，**追加**對立面審查段落（攻擊行動清單、找最弱判斷）。預設 `--codex` 不執行。

> 若 Codex 失敗 → 輸出 `⚠️ Codex 不可用：[error]，跳過第二意見`，繼續正常輸出。

---

## Output Language
繁體中文
