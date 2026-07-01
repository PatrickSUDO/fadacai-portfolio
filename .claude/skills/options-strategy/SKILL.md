---
name: options-strategy
description: Calculate and compare options strategies (sell put, covered call, LEAPS, naked call) for a given ticker. Usage - /options-strategy TICKER STRATEGY
user_invocable: true
model: claude-opus-4-8
---

# Options Strategy Calculator

Evaluate options strategies for a given ticker with risk/reward analysis.

## Step 0: 配置同步 & 倉位偵測

執行 CLAUDE.md 的 Step 0 統一規範（0a → 0b → 0c → 0d → **0e**）。
- 讀 `plan.md` + `feedback/*.md`（必做）；了解此標的在計畫中的進場策略與 strikes
- 呼叫 `get_account_position` 取即時持倉（確認現有部位與資金狀況）
- 今日 journal 不存在 → 執行 gap-fill + 變動偵測 + 自動建立 journal
- **0e 第一性原理紀律**：在 Recommendation 之前必須完成「方向 thesis / 證偽條件 / IV 機率分布」三題（見 CLAUDE.md 0e）

---

## Arguments
- `/options-strategy TEAM sell-put` — Sell put analysis
- `/options-strategy SSRM covered-call` — Covered call analysis
- `/options-strategy MU leaps` — LEAPS replacement analysis
- `/options-strategy FSLY naked-call` — Speculative call analysis
- `/options-strategy PLTR all` — Show all applicable strategies
- `/options-strategy PLTR AMD MU sell-put` — 多標的比較（平行）
- `/options-strategy MU sell-put --codex` — 加 Codex 第二意見（adversarial review of strike selection）

## Workflow

1. **Parse ticker and strategy** from arguments

### Multi-Ticker Parallel Mode

當偵測到多個 ticker（如 `/options-strategy PLTR AMD MU sell-put`）：

1. 為每個 ticker 派出獨立 Agent 子代理（subagent_type: "data-collector"，Sonnet 4.6），每個 Agent 執行：
   - `get_stock_info` — 現價 + 基本面
   - `get_option_chain` — 選擇權鏈
   - `get_technical_indicators` — 波動率 + RSI + 動量
   - `get_support_resistance` — S/R levels for strike selection
2. 每個 Agent 回傳 raw 選擇權數據，主 skill 計算所選策略 3-4 個 strike 的損益數據
3. 整合為比較表，依 E_adj 排序：

| Ticker | 現價 | Strategy | Best Strike(s) | Max Profit | Max Loss | 損益比 | ATR% | E_adj | 排名 |
|--------|------|----------|----------------|------------|----------|--------|------|-------|------|

若 Agent tool 不可用，依序處理各 ticker 亦可。

---

2. **Get Current Price & Technicals**
   - If Yahoo Finance MCP is available, fetch real-time quote
   - Otherwise use WebSearch: "[TICKER] stock price today"
   - 現有持倉從 Step 0 的 `get_account_position` 取（已淘汰 current-position.md）
   - Use `mcp__technical-mcp__get_technical_indicators` to get volatility regime, ATR, and RSI
   - Use `mcp__technical-mcp__get_support_resistance` to identify key levels for strike selection

3. **Get Options Data**
   - If Options Chain MCP or Yahoo Finance MCP is available, fetch actual options chain
   - Otherwise, estimate premiums based on:
     - Stock price and volatility
     - Days to expiry
     - Strike distance from current price
     - Historical IV if available via WebSearch

4. **Strategy Analysis**

### Sell Put
For 3-4 strike levels (near ATM to 15-20% OTM):
| Strike | OTM % | Expiry | Est. Premium | Breakeven | Annualized Return | P(assign) | Margin Est. |
- Margin estimate = 20-25% of (strike × 100) for margin account
- Annualized return = (premium / margin) × (365 / DTE)
- Show assignment scenario: what happens if assigned

### Covered Call
Requires existing shares（從 `get_account_position` 確認）:
| Strike | OTM % | Expiry | Est. Premium | Max Profit | Annualized Yield | P(called away) |
- Flag if user has enough shares for round lot (100)

### LEAPS (Stock Replacement)
For 2-3 strike levels (10-25% ITM):
| Strike | ITM % | Expiry | Est. Cost | Delta | Equiv. Shares | vs. Holding Stock |
- Compare capital required: LEAPS vs equivalent shares
- Calculate capital freed
- Time value at risk
- Note: if the user's broker is Level 2 only (no spreads), PMCC is unavailable

### Bull Put Spread
For 2-3 strike combinations (short strike near support, long strike $10-20 below):
| Short Strike | Long Strike | Width | Max Profit | Max Loss | Breakeven | P(profit) | Margin |
- Max profit = net premium received
- Max loss = width × 100 - premium
- Margin requirement = width × 100
- 引用配置計畫中建議的 strike levels（如有）

### Bear Call Spread
For stocks with **revision 下修/flat + 現價已超分析師 PT**（不以 RSI 過高為條件）:
| Short Strike | Long Strike | Width | Max Profit | Max Loss | Breakeven | P(profit) |
- Suitable for: **revision 下修/flat + 已超分析師 PT** 的標的（RSI 過高不是開 BCS 的理由 — 不對 revision 上修中的強者反向封頂）

### Naked Call (Speculative)
| Strike | OTM % | Expiry | Est. Cost | Breakeven | Max Loss |
- Flag this as high risk
- Only for small speculative positions

5. **Broker Constraints（內部參考，不輸出）**
   分析時遵守以下限制，但不在輸出中顯示此區塊：
   - Options Level 2 + Spread 已開通（2026/03/03 起）
   - 可做 Bull/Bear Put/Call Spread、PMCC
   - Sell Put 使用 Margin（非 cash-secured 全額）
   - 不能做裸賣 Call（需 Level 3+）
   - 配置計畫原則：不再開裸 Sell Put，全部用 Spread
   - **財報 ±48h 不開新選擇權部位**（IV 扭曲定價失準，per `feedback/options-leaps-playbook.md`）；既有部位管理不受限

5.5 **策略角色對映（飛輪定位 — 每次 Recommendation 前先確認本次操作在飛輪哪一環）**

   | 策略 | 飛輪角色 | 適用桶/情境 | 紀律 |
   |------|---------|-----------|------|
   | Covered Call | **harvest 端**：肥利潤落袋替代直接賣股 | 🟢 認列桶 ≥100 股 + revision 轉折/題材降溫 | **信念桶不開 CC 封頂**（>10% 紅線減碼除外）；strike 近 R1/分析師 PT，30-45 DTE |
   | Bull Call Spread | **redeploy 端**：加速領導者貼高/超買的定義風險參與 | revision 上修中 + 貼 52W 高（「超買」不是不追的理由，是換結構的理由） | max loss = net debit，凸性參與強者恆強 |
   | Bull Put Spread | **redeploy 端**：支撐區進場替代限價單 | 回檔至支撐 + thesis 完好 | short strike 貼支撐，寬 $10-20 |
   | LEAPS deep ITM | **信念端**：股票替代，釋放資金給飛輪 | 🔵 信念桶多年 thesis | delta 0.80–0.88、12-18 個月、<90 DTE 評估 roll |
   | Bear Call Spread | 對沖/超目標價 harvest 輔助 | revision 下修 + 超分析師 PT 的認列桶 | 不對 revision 上修中的持倉開（會反向封頂強者） |
   | 短 DTE OTM Call 樂透 | 衛星倉 | binary catalyst 30d 內 + 具體論述 | 總成本 ≤2% 帳戶，IV Rank >80 不做 |

6. **Volatility-Adjusted Guidance**
   Based on `mcp__technical-mcp__get_technical_indicators` volatility regime:
   - **High volatility regime** → sell premium strategies more attractive (higher premiums), wider strikes
   - **Low volatility regime** → buying options cheaper, tighter strikes for sell strategies
   - **RSI oversold (<30)** → sell put premiums attractive, consider buying calls
   - **RSI 過高不作任何指引**（2026-07-01 移除舊「overbought → avoid buying calls」— revision 上修中的強者照樣可用 bull call spread 參與，方向由 revision 定）
   - Use support levels from `get_support_resistance` to suggest sell put strikes near support

7. **倉位管理 & 波動率標準化**

   **Quarter-Kelly 倉位上限：**
   單筆 Spread 最大配置 = min(總資產 5%, Spread 最大損失)。
   同方向 Spread 合計 ≤ 總資產 15%。
   （總資產從 Step 0 的 `get_account_balance` 即時取得）

   **Swing Risk / Adjusted Risk 框架（per `feedback/realized-pnl-business-model.md`）：**
   - 既有選擇權部位的 **Swing Risk = Premium 成本 + 當前未實現利潤**（以歸零為最壞情境 = Expiry Risk）；肥利潤未落袋 → 主動建議部分平倉/roll 鎖利
   - **Roll 決策用 Adjusted Risk 視角**：同標的累積已認列獲利後，新倉真實風險 = `新倉成本 − 該標的累積已認列`；累積認列 ≥ 起始投入 = Risk-Free State。建議 roll/落袋時用此框架呈現，**不寫「賣了就少賺」**
   - BPS/BCS 達 50–75% 最大利潤 → 建議平倉認列（theta 後段風險報酬比惡化），釋放 margin 回飛輪

   **波動率標準化比較 (E_adj)：**
   當同時評估多個 Spread 機會時，計算：
   ```
   E_adj = 損益比 / ATR%
   損益比 = Max Profit / Max Loss
   ATR%  = ATR / 現價 × 100（從 get_technical_indicators 取得）
   ```
   E_adj 越高 = 風險調整報酬越好，應優先開倉。
   在 Recommendation 中顯示 E_adj 排序。

8. **第一性檢查（Recommendation 前必填）**

   ```
   ### 第一性檢查（Options 層級）
   - **方向 thesis：** [1 句可驗證命題，例：「MU FY26 EPS forward $XX 隱含 PE XX，週期高點未到」]
   - **證偽條件：** [2-3 個 falsifiable — 例：「下季 ASP 連續下跌」「庫存週數超 X 週」「DRAM spot price -10%」]
   - **IV / 機率分布：**

     | 情境 | 機率 | 標的 12 個月價 | Strategy P/L |
     |------|------|--------------|--------------|
     | 樂觀 | XX% | $XXX | +$XXX |
     | 基準 | XX% | $XXX | +$XXX |
     | 悲觀 | XX% | $XXX | -$XXX |

     Expected P/L = Σ(機率 × 損益) = $XXX
     對比單純買現股的 expected return：哪個更優？
   ```

9. **Recommendation**
   - Which strike/expiry combination is best for this ticker
   - How it fits with existing portfolio
   - **飛輪定位**（引用 5.5 對映表：本操作是 harvest / redeploy / 信念端哪一環；若是 harvest，同時給盈餘配對去處或標 dry powder）
   - Position sizing（根據 Quarter-Kelly 上限）
   - E_adj 分數（如有比較對象）
   - **明確說 Recommendation conditional on 哪個情境 + 機率**
   - **結尾附可掛的單（per `feedback/actionable-firstrade-orders.md`）**：結構 + 買賣別 + 履約價 + 到期 + limit credit/debit + 口數 + 效期，照抄可下；複式單無法 GTC → 給價格警報價位 + 預定結構（觸發後 2 分鐘執行）

---

## Step 9: Codex 第二意見（opt-in）

**僅當 arguments 含 `--codex` 或 `--2nd` 時執行。**

### B1. 獨立第一性分析（預設，independent first-principles）

**核心原則：Codex 不看 Claude 的 strike 選擇與 Recommendation**，只給 raw market data，讓它獨立挑 strike + 計 E_adj。Claude 與 Codex 兩個獨立輸出並排比較。

呼叫 Codex（**用 CLAUDE.md「Codex 呼叫方式」的 `codex exec` CLI；勿用 codex:codex-rescue subagent / `/codex:rescue`，會卡 superpowers preamble**），prompt 首行加強制 no-tool 指令，模板：

```
我是一名美股投資人，使用 Level 2 options + Spread 的 margin 帳戶。
請對 [TICKER] 在策略 [STRATEGY] 下，**完全獨立**選 strike + 計算 E_adj — 不要看任何先前推薦，這是獨立第二意見。

**Raw market data（只給事實）：**
- 現價：$XXX
- ATR / IV / IV Rank：[數據]
- 分析師中位 PT：$XXX
- 技術面：RSI / 趨勢 / 距 52W 高 / R1 / S1 / SMA50
- 近期催化：[財報日、產業事件]
- 配置上下文：用戶帳戶 ~$XXX，Quarter-Kelly 單筆上限 5%（~$XX,XXX）
- 用戶持倉：[已持有 X 股 / 未持有]

**可選 strike 範圍：**
[列出該策略下合理的 3-5 個 strike + DTE 組合，不標註哪個是 Claude 選]
- Strike $X DTE Y → 權利金 $X / 損益比 X.X / breakeven $X
- Strike $X DTE Y → ...

**請輸出：**

1. **核心 thesis**（1 句可驗證命題：為何此標的此時適合此策略？）

2. **證偽條件**（2-3 個 falsifiable — 例如：IV 跌破某值、現價跌破 SMA50、財報 miss）

3. **strike 選擇 + E_adj 計算：**

   | Strike | DTE | 權利金 | 損益比 | ATR% | E_adj | 機率盈利 |
   |--------|-----|-------|--------|------|-------|---------|
   | ... |

   推薦 strike：[$X DTE Y] / 開 [N] 口 / 總收入 $X / 鎖定資本 $X / 最大損失 $X

4. **Verdict**（1 句）：建議執行 / 暫緩 / 換策略，並說明 conditional 在什麼前提。

**規則：**
- E_adj = 損益比 / ATR%（越高越優先）
- 必須講口數（CLAUDE.md feedback 規定）
- 不假設 Claude 選哪個 strike
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
**Codex 推薦 strike：** $X DTE Y，開 N 口
- 總收入：$X
- 鎖定資本：$X
- E_adj：X.X

**Codex Verdict：** [...]

---

### 並排比較：Claude vs Codex（獨立輸出）

| 維度 | Claude | Codex | 一致性 |
|------|--------|-------|--------|
| 推薦 strike | $X DTE Y | $X DTE Y | 同 / 異 |
| 口數 | N | N | — |
| 總收入 | $X | $X | 差異 |
| E_adj | X.X | X.X | — |
| Verdict | 執行 / 暫緩 | 執行 / 暫緩 | 同 / 異 |

**真實共識**（兩邊獨立都認同）：[1-2 條 — 高信心結論]
**真實分歧**（兩邊獨立得出不同結論）：[1-3 條 — 值得深入]
**整合建議：** [基於真實共識的最終 strike + 口數，或建議再等資料]
```

### 進階：`--codex-adversarial`（opt-in 壓力測試）

僅當 arguments 含 `--codex-adversarial` 時，**追加**對立面審查段落（攻擊 strike 選擇、找最弱假設）。預設 `--codex` 不執行。

> 若 Codex 失敗 → 輸出 `⚠️ Codex 不可用：[error]，跳過第二意見`，繼續正常輸出。

---

## Output Language
Use Traditional Chinese (繁體中文) for all text output.

## 存檔 + HTML 生成
報告完成後：
1. 使用 Write tool 把完整 markdown 寫到 `briefing-out/options-strategy-<TICKER>-YYYY-MM-DD.md`
2. 執行：
```bash
python3 tools/generate_html.py options-strategy briefing-out/options-strategy-<TICKER>-YYYY-MM-DD.md --push
```
成功時印出網頁連結，失敗時印警告並繼續。
