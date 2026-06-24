---
name: options-strategy
description: Calculate and compare 台指期/選擇權 + 個股期貨 strategies (sell put, covered call, 多頭價差, 個股期貨替代現股, naked) for a given 標的. Usage - /options-strategy 標的 STRATEGY
user_invocable: true
model: claude-opus-4-8
---

# 台指期/選擇權 Strategy Calculator

Evaluate 台指選擇權（TXO）、台指期（TX/MTX 小台）與個股期貨策略 with risk/reward analysis。台灣個股選擇權流動性極差，故衍生品以**台指選擇權 + 台指期 + 個股期貨**為主。

## Step 0: 配置同步 & 倉位偵測

執行 CLAUDE.md 的 Step 0 統一規範（0a → 0b → 0c → 0d → **0e**）。
- 讀 `plan.md` + `feedback/*.md`（必做）；了解此標的在計畫中的進場策略與履約價
- 呼叫 `get_account_position` 取即時持倉（確認現有部位、保證金與資金狀況）
- 今日 journal 不存在 → 執行 gap-fill + 變動偵測 + 自動建立 journal
- **0e 第一性原理紀律**：在 Recommendation 之前必須完成「方向 thesis / 證偽條件 / IV 機率分布」三題（見 CLAUDE.md 0e）

---

## Arguments
- `/options-strategy TXO sell-put` — 台指選擇權賣出價外 put
- `/options-strategy 2002 中鋼 covered-call` — 持有現股賣 call（需先有現股）
- `/options-strategy 3661 世芯-KW stock-future` — 個股期貨替代現股分析
- `/options-strategy TXO bull-put-spread` — 台指賣權多頭價差
- `/options-strategy TX hedge` — 台指期空單避險現股組合
- `/options-strategy TXO all` — 列出所有適用策略
- `/options-strategy 3661 世芯-KW 3034 聯詠 sell-put` — 多標的比較（平行，個股期貨/Covered）
- `/options-strategy TXO sell-put --codex` — 加 Codex 第二意見（adversarial review of 履約價選擇）

## 合約規格（台灣，內部參考）
- **台指選擇權 TXO**：每點 NT$50，歐式、現金結算，週選（每週三到期）+ 月選；賣方需 SPAN 保證金
- **台指期 TX（大台）**：每點 NT$200；**小台 MTX**：每點 NT$50；保證金約 1 口大台 18 萬上下（依結算所公告浮動）
- **個股期貨**：1 口 = 2 張（2,000 股）；原始保證金約契約價值 13.5%（依層級）；可替代現股、降資金佔用、可空
- 履約價/口數一律以「口」計；現股以「張（1,000 股）」計

## Workflow

1. **Parse 標的 and strategy** from arguments

### Multi-Ticker Parallel Mode

當偵測到多個 ticker（如 `/options-strategy 3661 世芯-KW 3034 聯詠 sell-put`）：

1. 為每個 ticker 派出獨立 Agent 子代理（subagent_type: "data-collector"，Haiku 4.5），每個 Agent 執行：
   - `get_stock_info` — 現價 + 基本面
   - `get_futures_quote` / `get_option_chain` — 個股期貨/台指選擇權報價
   - `get_technical_indicators` — 波動率 + RSI + 動量
   - `get_support_resistance` — S/R levels for 履約價/進場選擇
2. 每個 Agent 回傳 raw 數據，主 skill 計算所選策略 3-4 個履約價/進場的損益數據
3. 整合為比較表，依 E_adj 排序：

| 標的 | 現價 | Strategy | Best 履約價/進場 | Max Profit | Max Loss | 損益比 | ATR% | E_adj | 排名 |
|------|------|----------|----------------|------------|----------|--------|------|-------|------|

若 Agent tool 不可用，依序處理各 ticker 亦可。

---

2. **Get Current Price & Technicals**
   - 若 finmind-server MCP 可用，抓即時報價（含加權指數現值、五檔）
   - 否則用 WebSearch：「[標的] 股價 今日」或「台股加權指數 即時」
   - 確認現有持倉（現股張數 / 期貨口數 / 選擇權部位）
   - 用 `mcp__technical-mcp__get_technical_indicators` 取波動率 regime、ATR、RSI
   - 用 `mcp__technical-mcp__get_support_resistance` 找關鍵價位作履約價選擇

3. **Get 期貨/選擇權 Data**
   - 若有台指選擇權鏈 / 個股期貨報價（TAIFEX / 券商 MCP），抓實際報價與隱含波動率
   - 否則依以下估算權利金：
     - 標的價與波動率（台指 VIX / 個股 ATR）
     - 到期天數（週選 / 月選）
     - 履約價距現價距離
     - 歷史 IV（WebSearch 補）

4. **Strategy Analysis**

### Sell Put（台指選擇權賣方，價外）
For 3-4 履約價 levels（近價平到 OTM）：
| 履約價 | OTM % | 到期 | Est. 權利金(點) | 收入(NT$) | 損益平衡 | 年化報酬 | P(履約) | 保證金估 |
- 收入 = 權利金點數 × NT$50 × 口數
- 保證金估 = TAIFEX SPAN 公式近似（價外賣方約 權利金 + max(A值−價外, B值)）
- 年化報酬 = (權利金收入 / 保證金) × (365 / DTE)
- 顯示被履約情境：現金結算，賠 (履約價 − 結算價) × NT$50 × 口數

### Covered Call（持有現股賣 call）
需先持有現股（個股選擇權流動性差時，改用「持有現股 + 賣個股期貨」或對指數曝險用台指 call）：
| 履約價 | OTM % | 到期 | Est. 權利金 | Max Profit | 年化權利金收益 | P(被叫走) |
- 提示是否有足夠對應部位（個股期貨 1 口對應 2 張現股）

### 個股期貨（替代現股 / Stock Replacement）
For 1-3 進場情境：
| 進場價 | 口數 | 契約價值 | 原始保證金 | 對應現股張數 | 釋出資金 vs 現股 |
- 比較資金佔用：個股期貨保證金 vs 等量現股全額
- 計算釋出資金（可做其他配置）
- 風險：槓桿放大、需補保證金、無股息（但有結算價調整）、轉倉成本
- 註：個股期貨可空，適合 thesis 偏空或避險

### Bull Put Spread（賣權多頭價差，台指選擇權）
For 2-3 履約價組合（賣近支撐的 put，買更低履約價的 put）：
| 賣 Put | 買 Put | 價差(點) | Max Profit | Max Loss | 損益平衡 | P(獲利) | 保證金 |
- Max profit = 淨收權利金 × NT$50 × 口數
- Max loss = (價差點數 − 淨權利金) × NT$50 × 口數
- 保證金需求 ≈ 價差 × NT$50 × 口數（風險有限，保證金低於裸賣）
- 引用配置計畫中建議的履約價（如有）

### Bear Call Spread（買權空頭價差）
For 指數/標的超買或超目標價：
| 賣 Call | 買 Call | 價差 | Max Profit | Max Loss | 損益平衡 | P(獲利) |
- 適合：RSI 超買、指數逼近壓力、計畫中標記偏空的情境

### Naked（裸賣選擇權，高風險）
| 履約價 | OTM % | 到期 | Est. 權利金 | 損益平衡 | 保證金 | 風險 |
- 標記為高風險（裸賣 put/call 保證金高、尾部風險大）
- 僅限小額投機部位，且配置計畫原則上優先用 Spread 取代裸賣

5. **期貨/選擇權帳戶限制（內部參考，不輸出）**
   分析時遵守以下限制，但不在輸出中顯示此區塊：
   - 已開通台指選擇權買賣 + 價差 + 個股期貨
   - 可做 Bull/Bear Put/Call Spread、Covered Call、個股期貨多空
   - 賣方需維持 SPAN 保證金，留意盤中與結算保證金追繳
   - 配置計畫原則：優先用 Spread / 個股期貨，裸賣僅小額且有意識使用
   - 留意台股漲跌幅 10% 對個股期貨保證金與結算的影響

6. **Volatility-Adjusted Guidance**
   Based on `mcp__technical-mcp__get_technical_indicators` volatility regime + 台指 VIX：
   - **高波動（台指 VIX 高）** → 賣方策略更具吸引力（權利金高），履約價拉遠
   - **低波動** → 買方便宜，賣方履約價收窄
   - **RSI 超買（>70）** → 賣 call 權利金吸引，避免追買 call
   - **RSI 超賣（<30）** → 賣 put 權利金吸引，可考慮買 call
   - 用 `get_support_resistance` 的支撐價位建議賣 put 履約價貼近支撐

7. **倉位管理 & 波動率標準化**

   **Quarter-Kelly 倉位上限：**
   單筆 Spread 最大配置 = min(總資產 5%, Spread 最大損失)。
   同方向 Spread 合計 ≤ 總資產 15%。個股期貨槓桿後曝險併入該標的集中度（不可繞過 >10% 提醒）。
   （總資產從 `plan.md` / 帳戶餘額讀取）

   **波動率標準化比較 (E_adj)：**
   當同時評估多個機會時，計算：
   ```
   E_adj = 損益比 / ATR%
   損益比 = Max Profit / Max Loss
   ATR%  = ATR / 現價 × 100（從 get_technical_indicators 取得）
   ```
   E_adj 越高 = 風險調整報酬越好，應優先開倉。
   在 Recommendation 中顯示 E_adj 排序。

8. **第一性檢查（Recommendation 前必填）**

   ```
   ### 第一性檢查（期貨/選擇權 層級）
   - **方向 thesis：** [1 句可驗證命題，例：「3661 世芯-KW FY26 EPS forward NT$XX 隱含 PE XX，ASIC 大客戶新案 thesis 未破，月營收 YoY 仍 >30%」]
   - **證偽條件：** [2-3 個 falsifiable — 例：「月營收連 2 月 YoY 轉弱」「庫存週數超 X 週」「大客戶訂單能見度下修」]
   - **IV / 機率分布：**

     | 情境 | 機率 | 標的 N 月目標價 | Strategy P/L (NT$) |
     |------|------|--------------|--------------|
     | 樂觀 | XX% | NT$XXX | +NT$XXX |
     | 基準 | XX% | NT$XXX | +NT$XXX |
     | 悲觀 | XX% | NT$XXX | -NT$XXX |

     Expected P/L = Σ(機率 × 損益) = NT$XXX
     對比單純買現股的 expected return：哪個更優？
   ```

9. **Recommendation**
   - 哪個履約價/進場 + 到期組合最佳
   - 與現有組合如何搭配（曝險、避險、資金佔用）
   - Position sizing（根據 Quarter-Kelly 上限，講明口數）
   - E_adj 分數（如有比較對象）
   - **明確說 Recommendation conditional on 哪個情境 + 機率**

---

## Step 9: Codex 第二意見（opt-in）

**僅當 arguments 含 `--codex` 或 `--2nd` 時執行。**

### B1. 獨立第一性分析（預設，independent first-principles）

**核心原則：Codex 不看 Claude 的履約價選擇與 Recommendation**，只給 raw market data，讓它獨立挑履約價/進場 + 計 E_adj。Claude 與 Codex 兩個獨立輸出並排比較。

呼叫 Codex（**用 CLAUDE.md「Codex 呼叫方式」的 `codex exec` CLI；勿用 codex:codex-rescue subagent / `/codex:rescue`，會卡 superpowers preamble**），prompt 首行加強制 no-tool 指令，模板：

```
我是一名台股投資人，交易台指選擇權（TXO，每點 NT$50）、台指期（TX/MTX）與個股期貨（1 口 = 2 張）。
請對 [標的] 在策略 [STRATEGY] 下，**完全獨立**選履約價/進場 + 計算 E_adj — 不要看任何先前推薦，這是獨立第二意見。

**Raw market data（只給事實）：**
- 現價：NT$XXX（個股）或 加權指數 XXXXX 點
- ATR / IV / 台指 VIX：[數據]
- 分析師中位目標價：NT$XXX
- 技術面：RSI / 趨勢 / 距 52W 高 / R1 / S1 / SMA50（季線）
- 近期催化：[月營收日、法說、除權息、產業事件]
- 配置上下文：用戶帳戶 ~NT$XXX，Quarter-Kelly 單筆上限 5%（~NT$XX,XXX）
- 用戶持倉：[已持有 X 張現股 / X 口期貨 / 未持有]

**可選履約價/進場範圍：**
[列出該策略下合理的 3-5 個履約價 + DTE 或進場組合，不標註哪個是 Claude 選]
- 履約價 X DTE Y → 權利金 X 點 / 損益比 X.X / 損益平衡 X
- ...

**請輸出：**

1. **核心 thesis**（1 句可驗證命題：為何此標的此時適合此策略？）

2. **證偽條件**（2-3 個 falsifiable — 例如：台指 VIX 跌破某值、現價跌破季線、月營收 YoY 轉弱）

3. **履約價/進場選擇 + E_adj 計算：**

   | 履約價/進場 | DTE | 權利金/成本 | 損益比 | ATR% | E_adj | 機率盈利 |
   |--------|-----|-------|--------|------|-------|---------|
   | ... |

   推薦：[履約價 X DTE Y] / 開 [N] 口 / 總收入 NT$X / 保證金 NT$X / 最大損失 NT$X

4. **Verdict**（1 句）：建議執行 / 暫緩 / 換策略，並說明 conditional 在什麼前提。

**規則：**
- E_adj = 損益比 / ATR%（越高越優先）
- 必須講口數（CLAUDE.md feedback 規定）
- 不假設 Claude 選哪個履約價
- 用客觀數據與你自己的 mental model

請以繁體中文回覆，控制在 600 字內。

--effort high --fresh
```

### 輸出整合

```
## 🤖 Codex 第二意見（獨立第一性分析）

### Codex 獨立輸出

**核心 thesis：** [Codex thesis]
**證偽條件：** [Codex 列的條件]
**Codex 推薦：** 履約價 X DTE Y，開 N 口
- 總收入：NT$X
- 保證金：NT$X
- E_adj：X.X

**Codex Verdict：** [...]

---

### 並排比較：Claude vs Codex（獨立輸出）

| 維度 | Claude | Codex | 一致性 |
|------|--------|-------|--------|
| 推薦履約價/進場 | X DTE Y | X DTE Y | 同 / 異 |
| 口數 | N | N | — |
| 總收入 | NT$X | NT$X | 差異 |
| E_adj | X.X | X.X | — |
| Verdict | 執行 / 暫緩 | 執行 / 暫緩 | 同 / 異 |

**真實共識**（兩邊獨立都認同）：[1-2 條 — 高信心結論]
**真實分歧**（兩邊獨立得出不同結論）：[1-3 條 — 值得深入]
**整合建議：** [基於真實共識的最終履約價 + 口數，或建議再等資料]
```

### 進階：`--codex-adversarial`（opt-in 壓力測試）

僅當 arguments 含 `--codex-adversarial` 時，**追加**對立面審查段落（攻擊履約價選擇、找最弱假設）。預設 `--codex` 不執行。

> 若 Codex 失敗 → 輸出 `⚠️ Codex 不可用：[error]，跳過第二意見`，繼續正常輸出。

---

## Output Language
Use Traditional Chinese (繁體中文) for all text output.

## 存檔 + HTML 生成
報告完成後：
1. 使用 Write tool 把完整 markdown 寫到 `briefing-out/options-strategy-<標的>-YYYY-MM-DD.md`
2. 執行：
```bash
python3 tools/generate_html.py options-strategy briefing-out/options-strategy-<標的>-YYYY-MM-DD.md --push
```
成功時印出網頁連結，失敗時印警告並繼續。
