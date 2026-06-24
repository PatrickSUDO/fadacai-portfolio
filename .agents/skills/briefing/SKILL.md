---
name: briefing
description: "Daily portfolio briefing with 3 tiers: /briefing (quick ~1min), /briefing full (~3min), /briefing deep (~5min). Replaces daily-briefing."
user_invocable: true
model: claude-sonnet-4-6
---

# Portfolio Briefing

三層結構的每日投資組合簡報，取代原 `/daily-briefing`。

## Arguments
- `/briefing` → Quick（~1 分鐘）
- `/briefing full` → Quick + Full（~3 分鐘）
- `/briefing deep` → Quick + Full + Deep（~5 分鐘）
- `/briefing telegram` → Telegram Push Tier（~2-3 分鐘）— 收盤後推送專用，不跑 Phase 1-3

### --send 旗標
任何 tier 加上 `--send` 會在 tier 執行完後：
1. 把完整 briefing markdown 寫到 `briefing-out/YYYY-MM-DD-full.md`（Write tool）
2. 把 Telegram 格式純文字寫到 `briefing-out/YYYY-MM-DD-telegram.txt`（Write tool）
3. 呼叫 `python3 tools/send_briefing.py YYYY-MM-DD`（Bash tool）推送至 Telegram + Email

`briefing telegram` 沒有 `--send` 時：只寫 `briefing-out/` 兩個檔案，不發送。

### 執行模型建議
- `/briefing`（quick）→ Sonnet 4.6（純彙整；session 已長則先 `/compact`）
- `/briefing telegram` → Sonnet 4.6（每日 launchd 自動推送，成本敏感，固定 Sonnet；週五 `--codex` 另走 gpt-5.5）
- `/briefing full` → Opus 4.8（中等綜合 + Verdict；Phase 2 subagent 已外包 Haiku）
- `/briefing deep` → Fable 5（最強旗艦：深度合成 + Codex 整合 + 機率/EV，一律 Fable）

切換方式：`/model sonnet`、`/model opus` 或 `/model fable` 後執行 skill。

---

## Step 0: 配置同步 & 倉位偵測

執行 AGENTS.md 的 Step 0 統一規範（0a → 0b → 0c → 0d → **0e**）。
- 讀 `plan.md` + `feedback/*.md`（必做）
- 呼叫 `get_account_position` 取即時持倉
- 今日 journal 不存在 → 執行 gap-fill + 變動偵測 + 自動建立 journal
- 若偵測到的變動對應 plan.md 待辦項 → 在 Phase 1 Step 1 標記
- **0e 第一性原理紀律**：在 Quick Take 之前必須完成「市場主題 thesis / 證偽條件 / 機率分布」三題（見 AGENTS.md 0e）

## Step 0.5: Macro Snapshot Load（所有 Phase / Tier 共用）

讀 cache（不打 API，所有數據由 `tools/fetch_macro.py` 預載到 `briefing-out/cache/macro-snapshot.json`）：

```
Read briefing-out/cache/macro-snapshot.json
```

判定：
- `status == "ok"` 或 `"partial"` 且 cache mtime < 36h → **使用**，在 Quick Take 區前顯示 1 行：
  ```
  📊 Macro: Fed {fed_funds}% | 2s10s {value} ({regime}) | HY OAS {value} ({regime}, pct {pct_1y}%) | VIX {value} ({regime}) | regime: {regime_tag}
  ```
- `status == "skipped"`（台灣總經(FinMind) key 缺失）→ 顯示 `⚠️ Macro snapshot unavailable (台灣總經(FinMind)_API_KEY not set)` 並跳過
- mtime > 36h → 顯示 `⚠️ Macro snapshot stale ({mtime_hours}h old)` 仍使用但標記

將 5 個 series + regime_tag 內容餵給 **Step 0e** 與後續呼叫的 `probability-honesty-checker` agent（其 Step 1i 必須收到此資料）。

## Step 0.6: Earnings History Load（所有 Phase / Tier 共用）

讀 cache（由 `tools/earnings_history.py` 預載）：

```
Read briefing-out/cache/earnings-history.json
Read briefing-out/cache/earnings-dates.json
```

判定：
- `status == "ok"` → 使用，後續 Section 4.5 與 Telegram tier earnings 區直接引用
- `status == "skipped"` / mtime stale → 標記 `⚠️ Earnings cache stale` 但仍使用最後一份

這兩份資料用於：
- Section 4.5 財報/月營收行事曆 表格的 `Trailing 8Q beat` / `avg surprise` 欄位
- Telegram tier `📅 本週重大事件（法說/月營收/除權息）` 加 beat rate 標註
- `probability-honesty-checker` Step 1d「Base rate」強制欄位

---

## Step 0.7: Thesis Ledger 驗收 & 逾期掃描（所有 Tier 共用）

帳本 = `research/thesis-ledger.json`，工具 = `tools/thesis_ledger.py`（去重/碰撞/到期/過期/統計全在程式層，**Codex 不手改 JSON**）。

**1. 取得今日到期清單（同時自動 expire sweep）：**
```
python3 tools/thesis_ledger.py due
```
回傳 `{due:[...], expired:[...]}`。`expired` 是工具自動把「逾期 >30 天未驗收」轉掉的，當作無結果。

**2. 對每筆 `due` thesis 驗收：**
- 讀該筆 `trigger.metric` → 知道要抓什麼（財報營收/ASP/毛利率、板塊 ETF、價格…）
- 用既有 MCP（FinMind / `earnings_history.py` cache / technical 等）抓**實際數字**
- 對照 `thesis` + `falsification` 判定 `passed` / `failed` / `partial`
- **抓不到新數**（event 觸發但財報還沒出）→ 用 `reschedule` 把觸發日往後推、維持 pending，**絕不猜 verdict**：
  ```
  python3 tools/thesis_ledger.py reschedule --id <id> --to YYYY-MM-DD --reason "財報未出"
  ```
- 有結論 → `resolve`：
  ```
  python3 tools/thesis_ledger.py resolve --id <id> --verdict passed|failed|partial \
    --actual "實際數字" --note "判讀" --next-action "由此推出的操作"
  ```

**3. 輸出「📋 thesis 驗收」區塊**（接在 Key Alerts 後 / Quick Take 前）：
```
## 📋 thesis 驗收
| thesis | 命題 | 實際 | verdict | → actionable |
|--------|------|------|---------|-------------|
| 3661 世芯-KW:memory-cycle | DRAM 漲價毛利率>40% | ASP +8%、毛利率42% | ✅ passed | HOLD，加碼門檻 $XXX |
（無到期項則略過此區塊，僅在有 due/expired 時輸出）
⏳ 逾期未驗收已歸檔：[expired 清單，若有]
```

**驗收結果直接餵 actionable**：passed → 強化/HOLD/加碼；failed → 汰弱/減碼；partial → 續觀察。`resolve --next-action` 寫的就是下一步行動，併入 Key Alerts / 行動項。

---

## Phase 1: Quick（永遠執行）

### 1. Trade Journal Auto
若 Step 0b 偵測到倉位變化，輸出差異表：

```
## ⚡ 倉位變動（vs 上次快照 YYYY-MM-DD）
| 類型 | 操作 | 標的 | 變化 | 計畫對應 |
```

無變動則顯示「倉位無變化」。

### 2. Daily Snapshot

```
日期: YYYY-MM-DD
組合市值: $XXX,XXX (日變動: +/- $X,XXX / +/- X.XX%)
總損益: +/- $X,XXX (+/- X.XX%)
持倉: XX 檔股票 + XX 個選擇權合約
```

### 3. Today's Movers
全持倉依日漲跌%排序：

| 標的 | 股數 | 現價 | 日漲跌% | 市值 | 總損益% |

> +2% 或 -2% 標記。

### 4. Options Status

**4a. 無現股標的價格確認：**
比對選擇權持倉的 underlying ticker vs 現股持倉。若 underlying 沒有對應現股（如 2379 瑞昱、DDOG、2454 聯發科、LRCX、2330 台積電、2454 聯發科），
使用 `mcp__technical-mcp__get_batch_indicators` 或 `mcp__finmind-server__get_stock_info` 取得該標的目前現股價格。
在 Options Status 表格中加入「標的現價」和「距 Strike %」欄位，方便判斷 ITM/OTM 狀態。

**4b. Options 總覽表：**

| 合約 | 方向 | 到期日 | 剩餘天數 | 標的現價 | 距Strike% | 損益% | 狀態 |

⚠️ 標記剩餘 <14 天的合約。

### 4.5 財報/月營收行事曆 Check（Technical Snapshot 前必做）

**為何必要：** 持倉 ticker 在 ±48h 內若有財報，technical signal（trend / momentum / RSI）會被 財報反應 主導，不是結構性訊號。直接套「弱勢持續 → 減碼」會在 fundamental beat 後賣在低點（3661 世芯-KW 5/5 案例）。

**資料來源**：Step 0.6 已預載 `briefing-out/cache/earnings-dates.json` + `earnings-history.json`，直接從 cache 取，**不再呼叫 MCP**（若 cache 缺失或 ticker 不在，才 fallback `mcp__twse-server__getEarningsCalendar`）。

**執行步驟：**
1. 從 cache 列出未來 7 天內、或過去 48h 內有財報的持倉 ticker
2. 對 財報/月營收窗口（±48h）內的 ticker，在 Step 5 Technical Snapshot 表格的「標的」欄位前綴 ⚠️
3. 對 財報/月營收窗口 內的 ticker：
   - **不執行**「弱勢持續 → 減碼」「拋物線警示 → 出清」自動規則
   - actionable 改寫為「等 N+1 個交易日 settle 再判斷結構」
   - 若強行給建議，必須先 confirm fundamental 數字（revenue / EPS / guide）方向，不能只看 price action
4. **輸出格式（必須含 base rate）：**

   ```markdown
   | 標的 | 日期 | 時機 | 距 earnings | Trailing 8Q beat | Avg surprise % | 狀態 |
   |------|------|------|------------|-----------------|---------------|------|
   | 2330 台積電 | 2026-05-20 | 盤後 | 2d | 8/8 (100%) | +6.3% | 🔴 window 內 |
   | 2454 聯發科 | 2026-06-03 | 盤後 | 16d | 7/8 (87.5%) | +3.4% | 觀察中 |
   ```

   `Trailing 8Q beat` 與 `Avg surprise %` 從 `earnings-history.json` 的 `beat_count/total` 與 `avg_surprise_pct` 直接讀。

5. 若 cache `status` ≠ `"ok"` 或 ticker 不在 cache → 該欄填 `(unavailable)`，並在輸出末尾加註 `⚠️ N tickers 缺 earnings cache（請手動 python3 tools/earnings_history.py --force）`

> 詳見 `feedback/earnings-reaction-window.md` 與 `feedback/weak-signal-root-cause.md`

### 5. Technical Snapshot
使用 `mcp__technical-mcp__get_batch_indicators` 取得全持倉技術指標。

**欄位順序（依決策權重排列）：**

| 標的 | 現價 | 趨勢 | MACD | 量能比 | 動能分 | RSI |

- **趨勢**：strong_uptrend / mild_uptrend / consolidation / pullback / weak_downtrend / strong_downtrend
- **MACD**：顯示 crossover 狀態（golden_cross 🚀 / death_cross ⚠️ / none）
- **量能比**：volume_ratio（>1.5 爆量 / <0.7 縮量）
- **動能分**：momentum_score（-100 ~ +100）
- **RSI**：最後參考，不單獨作為買賣訊號

**複合訊號標記規則（必須多指標同時觸發 + 無 財報/月營收窗口）：**

| 標記 | 觸發條件 |
|------|---------|
| 🔴 拋物線警示 | strong_uptrend + RSI > 75 + volume_ratio < 0.8（創高但量縮，背離）|
| 🔴 弱勢持續 | downtrend + momentum_score < -30（不是機會，是落刀）|
| ⚠️ 動能背離 | uptrend + momentum_score 轉負 OR death_cross（趨勢未破但動能轉弱）|
| 🚀 強勢確認 | golden_cross + strong_uptrend + volume_ratio > 1.2 |
| 🟡 留意 | RSI > 70 但無以上複合條件 → 只標數字，不加警示標籤 |
| ⚠️ 財報/月營收窗口 | 過去/未來 48h 有財報 → **以上規則一律不套用**，標記 wait N+1d |

**根因分類規則（看到弱勢/強勢訊號必做）：**

對任一 weak_down / strong_down / momentum < -20 訊號，先回答根因再行動：
1. 過去 48h 有財報？→ (b) 財報反應 → HOLD wait
2. 同板塊 ETF 也弱？→ (c) sector rotation → 評估板塊配置
3. fundamental 數據惡化？（revenue growth 連 2 季減速 / guide 下修）→ (a) thesis 破裂 → **可執行汰弱**
4. 以上皆否 → (d) noise → 忽略

只有 (a) 才執行「汰弱留強」減碼。詳見 `feedback/weak-signal-root-cause.md`

### 6. Key Alerts
只在觸發時顯示（無則跳過整個 section）：
- 單日跌 > 5%
- 總虧 > 15%
- 單一持倉 > 8% 組合（過度集中）
- 財報 < 3 天（用已知財報日歷）
- 選擇權 < 14 天到期

### 7. 計畫進度 Quick
- 近期待辦狀態（✅🔄⏳）
- 今日是否有計畫中的觸發條件被滿足（RSI 破 30、MACD 金叉等）
- 即將到期的選擇權 vs 計畫中的關鍵日期

### 8. Quick Take

**🔒 強制：機率分布必須呼叫 `probability-honesty-checker` agent**

寫出機率分布 / EV **之前**必須執行：

```
Agent(
  subagent_type: "probability-honesty-checker",
  description: "Briefing quick take EV check",
  prompt: """
  計算當前組合 7 日 horizon 機率分布與 EV。

  ## Step 1 九項輸入（已備齊）:
  1a. RSI 分布: [從 Section 5 Technical Snapshot 摘出，每 bucket 檔數 + % of port]
  1b. 距 52w 高: [從 get_stock_info 摘出，中位數/最大/最小]
  1c. 已實現波動: 過去 5d/2d 累積，最大單日
  1d. Binary catalysts (window 7d): [從 Section 4.5 財報/月營收行事曆 Check 摘出，
      **必須含 trailing 8Q beat rate + avg surprise %** 來自 earnings-history.json
      cache。格式：「N/8 beat, +X.X% avg」。cache 缺 → (unavailable)]
  1e. 集中度: top 1 / top 5 / 最大板塊（從 Section 1 倉位 + B 板塊配置）
  1f. 板塊輪動曝險: leading 持倉 % / lagging 持倉 %（從 sector rotation）
  1g. Sentiment: 7d/30d 對比（如 quick tier 無 sentiment 數據則標 N/A）
  1h. Thesis 健康度: 持倉 fundamental 是否 intact
  1i. Macro state: [從 Step 0.5 載入的 macro-snapshot.json 完整貼入：
      fed_funds + 30d change / yield_2s10s + regime / hy_oas + regime + pct_1y /
      vix + regime / cpi_yoy + trend / regime_tag]

  ## 額外 context:
  [plan.md 摘要 + 最近 N 天事件]

  請執行你的 6 步流程並回傳完整輸出 + 精簡結論。
  """
)
```

收到 agent 結果後 verbatim 顯示精簡結論（含 EV 數字）。**不可手動改機率或寫質性結論。**

**第一性檢查（Quick Take 前必填）：**
```
### 第一性檢查（市場主題）
- **核心 thesis：** [1 句可驗證命題]
- **證偽條件：** [2-3 個 falsifiable]
- **機率分布：** [由 probability-honesty-checker agent 算出，引用其精簡輸出]
  - 樂觀 X% / 基準 X% / 悲觀 X%
  - EV (7d) = X.XX%
```

2-3 句總結（明確 conditional 在 thesis 機率）：
- 今日市場主題（從持倉漲跌推斷，**事實非 narrative**）
- 是否需立即行動？（明確說 conditional 在哪個情境）
- 明天關注重點（對應到證偽條件）

**禁止偷懶**（直接由 agent self-audit 攔截，主 skill 絕不可寫）：
- ❌ 30/45/25、35/45/20 default mirror shape
- ❌ 「略偏正」「略偏負」「中性偏多」
- ❌ EV 寫成「整體 EV 略偏正」而非數字

**第一性檢查產出後 → 登錄 Thesis Ledger（收尾步驟）：**

只登錄**有明確時間/事件觸發點**的 thesis（當日核心市場 thesis + 行動項裡帶「請在財報後/N 日後檢視」的個股 micro thesis）；**沒有觸發點的泛泛評論不登錄**。

每筆登錄前先看既有，避免 slug 飄移：
```
python3 tools/thesis_ledger.py list --ticker <T>
```
- 同論點 → 沿用既有 slug（變 update）；新論點 → 取區隔 slug
```
python3 tools/thesis_ledger.py add --ticker <T> --slug <slug> \
  --thesis "<可驗證命題>" --falsification "<證偽點1>" "<證偽點2>" \
  --trigger-type event|date --trigger-date YYYY-MM-DD \
  [--event earnings] [--metric "到期要比的指標"] --source briefing --ev "<EV snapshot>"
```
- **exit code 2 = 碰撞**（同 slug 但 thesis 差很多）：改取區隔 slug，或確定舊論點被推翻 → 改用 `supersede`
- market-level thesis 用 `--ticker MARKET`

---

## Phase 2: Full（`/briefing full` 或 `/briefing deep` 時執行）

### 9. Sentiment Analysis
使用 Agent 子代理（subagent_type: "data-collector"）取 top 5 持倉的情緒數據：

- **Agent: FinMind Sentiment**（subagent_type: "data-collector"）→ `get_sentiment_trend`（ticker format: "TICKER"）

| 標的 | 7日情緒 | 30日情緒 | 趨勢 | 備註 |

情緒 < -0.3 的標的額外調用 `get_news_sentiment` 顯示負面新聞。

### 10. Market Dynamics
- `mcp__twse-server__getBiggestGainers` + `getBiggestLosers`
- 檢查持倉是否出現在極端波動名單
- 市場主題掃描（板塊輪動、避險情緒等）

### 11. Prediction Markets
- `mcp__chip-server__search_markets` 搜尋與持倉板塊相關事件
- 搜尋關鍵字：AI regulation, tariffs, Fed rate, semiconductor
- 顯示相關事件及概率

### 11.5 樂透機會掃描（Lottery Opportunity Scan）

**目的：** 從市場掃出**至多 3 個**適合短 DTE OTM Call 樂透的候選（per memory feedback：樂透用近期 OTM Call 不用 個股期貨，避免 vega 干擾凸性）。

**篩選步驟（重用 Section 10 movers + active list 數據，不額外抓取）：**
1. 候選池：`getBiggestGainers` + `getMostActiveStocks`
2. **排除遲到派對：** 過去 5 日累計漲幅 > 30% → 凸性已被消耗
3. **排除既有持倉同題材：** 與 portfolio 重複曝險的標的跳過
4. **必要條件（3 項全符合才入選）：**
   - 30 天內有 binary catalyst（財報 / FDA / 政策 / 公告）
   - 有具體論述（不是純技術突破或迷因）
   - 短 DTE OTM Call 流動性合理（OI > 500 估算）

**輸出格式（限 1-3 筆，無符合則輸出「⏳ 本次無符合凸性條件的樂透機會」）：**

| Ticker | 題材 / Binary 催化 | 建議結構 | 預估成本 | 凸性備註 |
|--------|----------------|---------|---------|---------|

**規則：**
- 預設 1-2 口，**總成本 ≤ 2% 帳戶價值**（Quarter-Kelly 樂透上限）
- **不推 個股期貨 OTM 當樂透**（vega 干擾，違反 feedback_options_vega_playbook.md）
- 「上行 +XXX% / 下行 max loss = premium」必寫
- 若候選 IV Rank > 80：警告「IV 過高，後續 IV crush 風險」

### 12. 計畫 Full Alignment
完整進度表：

| # | 計畫操作 | 狀態 | 觸發條件 | 當前數據 | 備註 |
|---|---------|------|---------|---------|------|
| 1 | 加碼 2330 台積電 | ⏳ 待觸發 | RSI<35 | RSI=42 | 接近 |
| 2 | DDOG BCS | ✅ 已完成 | — | — | 3/5 建倉 |

---

## Phase 3: Deep（`/briefing deep` 時執行）

### 13. 平行 Agent 派遣

同時派出 3 組 Agent 子代理（全部 subagent_type: "data-collector"，自動使用 Haiku 4.5）：

- **Agent 1 — 公開資訊觀測站 MOPS**（subagent_type: "data-collector"，top 5）：`get_insider_transactions`（90d）+ `get_recent_filings`（30d）
- **Agent 2 — FinMind**（subagent_type: "data-collector"，top 5）：`get_stock_info` + `get_financial_statement` — 基本面摘要
- **Agent 3 — twse**（subagent_type: "data-collector"）：`getStockPeers`（top 3）+ `getBiggestGainers` / `getBiggestLosers`

若 Agent tool 不可用，依序呼叫亦可。

### 14. 個股深度分析
對 Key Alerts 中標記異常的股票（跌>5%、虧>15%），執行 stock-analysis 級別的分析：
- 技術面詳細指標（BB、ATR、SMA）
- 基本面快照（PE、Revenue Growth、Margins）
- 內部人交易摘要
- 投資論點重新評估

### 15. 完整計畫對照
portfolio-review 式的計畫執行進度表：
- 板塊佔比 vs 計畫目標的偏差分析
- 所有待辦項目的執行狀態
- 風險監控項目的當前狀態
- 下一步建議（基於計畫優先級 + 當前市場條件）

---

---

## Telegram Tier（`/briefing telegram`）

**目的：** 每日收盤後（台灣時間 14:00）推送至 Telegram + Email 的精簡決策摘要。不跑 Phase 1-3 的完整分析，只抓推送所需的 7 個資料點，直接產出 emoji 純文字格式。

### 執行模型
Sonnet 4.6（資料抓取為主，無深度合成需要）

### Step 0
同標準規範（0a-0e）：讀 `plan.md` + `feedback/*.md` → `get_account_position` → journal 確認。

### 資料步驟（依序，可部分並行）

**T1. 財報/月營收窗口（next 7 days）**
**改從 cache 讀：** Step 0.6 已預載 `briefing-out/cache/earnings-dates.json` + `earnings-history.json`，直接 Read 兩份 JSON。
列出所有持倉 ticker 的：
- 財報日 + 盤前/盤後（`next_date`, `timing`）
- 過去 ±48h 已發財報的 ticker 也標出
- **Trailing 8Q beat rate + avg surprise %**（從 `earnings-history.json`）
- focus 重點：可從 FinMind news / sentiment 摘要推斷

若 cache `status` ≠ `"ok"` → fallback `mcp__twse-server__getEarningsCalendar`，並加註 `⚠️ earnings cache unavailable`。

**T2. Sentiment Pulse（平行 Agent）**
派出 data-collector subagent，取所有持倉的 FinMind 7d sentiment_trend（格式：TICKER.US）：
```
Agent(subagent_type="data-collector"):
  呼叫 mcp__cnyes-news__get_sentiment_trend 對每個 ticker
  回傳 dict: {ticker: {score: float, trend: str}}
```
分類：score 7日變動 > +0.1 → 改善；< -0.1 → 轉弱；急降（從 > +0.3 → < +0.1）→ ⚠️ 注意

**T3. News & Catalysts（past 24h）**
`mcp__finmind-server__get_finmind_finance_news` 取 top 5 持倉的新聞，各取 1-2 篇 24h 內最重要的。篩選標準：有具體事件（財報、合約、產品發布、監管）優先，無實質 catalyst 跳過。**最多 3 條進入 Telegram 輸出。**

**T4. Sector Rotation**
`mcp__technical-mcp__get_sector_rotation()` → 取全 sector ETF 相對 加權指數 的 leading / improving / weakening / lagging 分類。只顯示各分類各 1-2 個代表 sector。

**T5. Alerts（閾值觸發）**
根據 T1 + T2 + Step 0b 持倉數據生成 alerts（無則跳過整個 section）：
- Earnings window ±48h 的 ticker → 標記「技術訊號暫停」
- Sentiment 急降（T2 注意類）→ 標記「情緒惡化」
- 任一持倉距 52w 低點 < 5%（需 `get_stock_info`）→ 標記「逼近 52w 低」
- plan.md 中有明確 stop-loss 且接近觸發的 ticker

**T6. 今日 / 明日待辦**
從 `plan.md` 的策略佇列 + 觀察清單（⏳ 待評估）+ Step 0e 第一性分析，生成：
- **今日待辦**：有明確觸發條件且條件「已接近或已達」的項目（最多 3 條）
- **明日待辦**：即將到來的 catalyst（財報 next day、FOMC、plan.md 明天到期的條件）（最多 3 條）
- 過濾純 HOLD-only、無 actionable 的項目
- 每條格式：`• {action}（{trigger / catalyst}）`

**T7. Quick Take（第一性）**
2 行以內，情緒/敘事走向。不講 RSI/MACD。句子格式：
- 今日整體 sentiment 方向（用 T2 + T4 支撐）
- 本週重點 / 核心注意事項（1 句）

---

### 檔案輸出（每次執行均寫出，無論有無 --send）

**T8a. 完整 Markdown → `briefing-out/YYYY-MM-DD-full.md`**

使用 Write tool 寫入，格式：
```markdown
# Briefing Telegram YYYY-MM-DD

## 財報/月營收窗口
...

## Sentiment Pulse
...

## News & Catalysts
...

## Sector Rotation
...

## Alerts
...

## 今日待辦
...

## 明日待辦
...

## Quick Take
...
```

**T8b. Telegram 純文字 → `briefing-out/YYYY-MM-DD-telegram.txt`**

使用 Write tool 寫入，格式嚴格遵守（純文字 + emoji，無 markdown，無表格，無 bold/italic/link）：

```
📊 M/D HH:MM（發送時間，本地時區）

📰 News & Catalysts
  • {ticker}: {一句話} ({source})
  （無 catalyst 則略過整個 section）

📅 本週重大事件（法說/月營收/除權息）
  • {ticker} {M/D} {盤前/盤後} ({beat_count}/{total} beat, +{avg_surprise}%) — {focus 重點}
  （Trailing beat rate 從 earnings-history.json 讀；cache 缺則省略括弧）

📊 Sentiment Pulse (FinMind 7d)
  📈 改善: {ticker} +{delta}, {ticker} +{delta}
  📉 轉弱: {ticker} -{delta}
  ⚠️ 注意: {ticker} {一句說明}
  （無變化的 ticker 不列出）

🔄 Sector Rotation
  💪 leading: {sector}, {sector}
  📈 improving: {sector}
  📉 weakening: {sector}
  💀 lagging: {sector}

🚨 Alerts
  • {alert}
  （無 alert 則略過整個 section）

🎯 今日待辦
  • {action}（{trigger}）

📋 明日待辦
  • {action}（{catalyst}）

⚡ Quick Take
  {第一行：今日情緒/敘事方向}
  {第二行：本週核心注意事項}
```

**格式規則：**
- 純文字，emoji 作區塊分隔
- 無 `**`、`_`、`[text](url)` 等 markdown 語法
- 數字：K（千）、M（百萬）、% 縮寫
- 無 catalyst 或無 alert 的 section 完整省略（不要顯示空 section）
- 目標長度 < 1500 字元（一則 Telegram 訊息），最長不超過 4096
- `briefing-out/` 目錄不存在時先用 Bash `mkdir -p briefing-out` 建立

---

### --send 旗標處理

寫完兩個檔案後，若 arguments 含 `--send`：

```bash
python3 tools/send_briefing.py YYYY-MM-DD
```

成功時輸出「✅ Telegram 已發送 / Email 已寄出」，失敗時輸出錯誤訊息（sender 自帶 retry + error notification）。

---

## Phase 4: Codex 第二意見（opt-in — 僅 `full` 或 `deep` 層）

**僅當 arguments 含 `--codex` 或 `--2nd` 時執行。Quick 層完全跳過本 Phase。**

三個子 block 依序執行（可並行派 Agent）：

---

### B1. 獨立第一性分析（預設，independent first-principles）

**核心原則：Codex 不看 Codex 的 Phase 1–3 結論**（不給 Quick Take / Key Alerts / 建議），只給 raw 持倉變動 + 市場數據，讓它獨立評估今日 priorities。Codex 與 Codex 兩個獨立輸出並排比較。

**🔴 Prompt 中性化要求**（詳見 `feedback/codex-prompt-neutrality.md`）：

raw data 區只能放 fact 數值，**不能放** derived label：

| ❌ 不能寫 | ✅ 改寫為 |
|----------|----------|
| `3661 世芯-KW strong_uptrend / 49 / 量縮` | `3661 世芯-KW $635.80 (+10.30%) / RSI 81.7 / vol_ratio 0.49 / 6w range $XXX-$XXX` |
| `3661 世芯-KW weak_downtrend / momentum -24` | `3661 世芯-KW $138.30 (-5.29%) / RSI 46.2 / 6w range $122-$146 / Q1 earnings 5/4（昨日）` |
| `BE 拋物線警示` | `BE $291 (+0.9%) / RSI 77.6 / 5d 區間 $275-$303` |

**禁止的 label：** strong_uptrend / weak_downtrend / consolidation / overbought / oversold / 拋物線 / 打底 / 弱勢持續 / 強勢確認 / momentum_score（這已是 -100~+100 derived score，改寫成「X 個交易日累計漲跌 X%」）。

讓 Codex 自己跑 indicator interpretation，從 raw 數值推導結論。

呼叫 Codex（`subagent_type: "codex:codex-rescue"`），prompt 模板：

```
我是一名美股投資人，使用 Level 2 options + Spread 的 margin 帳戶。
請對今日 briefing，**完全獨立**評估 — 不要看任何先前結論。

**Raw data（只給 fact 數值，無 derived label）：**

帳戶：總值 $XXX / 現金 $XXX / 今日帳戶變動 +X.XX%

**今日 movers（價格 + % + 量能比 + 6 週區間）：**
- [ticker] $XXX (+/-X.XX%) / RSI XX.X / vol_ratio X.XX / 6w range $XXX-$XXX
- ...

**財報/月營收窗口 標記（過去/未來 48h 有財報的 ticker）：**
- [ticker] — 財報日 X/X（[已過 X 天 / 還剩 X 天]）

**主要持倉技術面（fact only）：**
- [ticker]：價 $XXX / RSI XX / MACD line/signal/histogram / vs SMA20 X% / vs SMA50 X%
- ...

**板塊輪動（vs 加權指數 3mo，純數值）：**
- 費半/IC設計 +X.XX% / 1w +X.XX% / RSI XX.X
- ...

**待執行/觀察的計畫項目**（從 plan.md 摘出 ⏳，不寫評語）：
- ...

**近期重大事件（fact）：** 財報日列表、台灣央行理監事會 / 美國 FOMC、產業催化

**投資風格：** AI/半導體主軸、汰弱留強、信念持倉 [2330 台積電/3661 世芯-KW/2454 聯發科]

**請輸出（獨立判斷）：**

1. **今日組合 thesis**（1 句：今日是「進攻」「防守」「觀望」？理由？）

2. **3 個今日最重要的訊號**（具體 — 自己解讀 raw data，不依賴 Codex 標籤）

3. **未來 5 個交易日機率分布（組合表現）：**

   | 情境 | 機率 | 條件 | 預期 % |
   |------|------|------|--------|
   | 樂觀 | XX% | [...] | +X% |
   | 基準 | XX% | [...] | ±X% |
   | 悲觀 | XX% | [...] | -X% |

4. **3 個 actionable 建議**（含口數 / 觸發條件）— 對 財報/月營收窗口 內的 ticker 預設「等 settle」

5. **Verdict**（1 句）：今日整體該做什麼？

**規則：**
- 機率分布必須 sum 到 100%
- 不假設 Codex 已說過什麼
- 保持獨立判斷
- 財報/月營收窗口 內的 ticker 不直接套「汰弱留強」

請以繁體中文回覆，控制在 700 字內。

--effort high --fresh
```

---

### B2. 機會掃描（opportunity scout）

呼叫 `/codex:rescue`：

```
我目前的台股持倉（含市值占比）：
[插入 Step 0b get_account_position 取得的持倉表]

我的投資風格：
- 主軸：AI/半導體供應鏈、高成長科技；汰弱留強，集中持倉
- 信念持倉（不換）：2330 台積電, 3661 世芯-KW, 2454 聯發科 多年期 thesis
- 板塊偏好：[從 plan.md 摘出 3-5 行板塊目標]

請以獨立分析師視角：
1. 掃描今日市場有哪些當紅題材/個股，是我目前持倉沒覆蓋到的
2. 對每個候選列出：題材、代表 ticker、為何此刻有機會、建議切入方式（現股/Spread/個股期貨）
3. 要追這些新機會，最該砍掉哪一檔現有持倉？為什麼？
4. 提供 2-3 個具體 actionable 建議（含目標 entry zone）

請以繁體中文回覆。輸出限 600 字。
```

---

### B3. 輪動分析（rotation scan）

**Step 1 — Codex 預先收集數據：**
- `mcp__technical-mcp__get_sector_rotation()` → 全板塊 ETF 相對強度 vs 加權指數（leading / improving / weakening / lagging）
- `mcp__technical-mcp__get_batch_indicators(tickers=[所有持倉])` → 個股動能分數 + 趨勢

**Step 2 — 呼叫 `/codex:rescue`：**

```
我的台股持倉（含市值占比 + 板塊歸屬）：
[持倉表]

當前板塊輪動數據（vs 加權指數）：
[get_sector_rotation 完整輸出]

當前個股動能：
[get_batch_indicators 摘要]

請以輪動專家視角：
1. 板塊輪動：哪些板塊 leading，哪些 weakening？我的持倉是否站在 leading 板塊？
2. 個股輪動：在我已持有的板塊內，有更強的 leader 我沒拿到？有持倉已被同板塊其他名字超越？
3. 資金流向：從 weakening 輪到 leading 的訊號是否明確？建議調倉路徑
4. 具體建議：3 條 actionable 輪動操作（從哪檔減 → 加到哪檔，附理由）

請以繁體中文回覆。輸出限 700 字。
```

---

### B4. 輸出整合

```
## 🤖 Codex 第二意見

### B1. 獨立第一性分析（Codex 獨立輸出）

**Codex 今日 thesis：** [...]
**Codex 列的 3 個重要訊號：** [...]
**Codex 機率分布：**

| 情境 | 機率 | 條件 | 預期 % |
|------|------|------|--------|
| ... |

**Codex 3 個建議：** [...]
**Codex Verdict：** [...]

#### 並排比較：Codex vs Codex（獨立輸出）

| 維度 | Codex | Codex | 一致性 |
|------|--------|-------|--------|
| 今日 thesis | [Codex] | [Codex] | 同 / 異 |
| 機率分布偏向 | 偏多 / 中性 / 偏空 | 偏多 / 中性 / 偏空 | — |
| 主要建議 | [Codex] | [Codex] | 同 / 異 |
| Verdict | [Codex] | [Codex] | 同 / 異 |

**真實共識：** [1-2 條]
**真實分歧：** [1-3 條]

### 機會掃描（vs 現有持倉）
[B2 Codex 完整回覆]

### 輪動分析（板塊 + 個股）
[B3 Codex 完整回覆]

---
**值得追蹤的新機會：** [從 B2 挑 1-2 個 Codex 也認同的]
**輪動 actionable：** [從 B3 挑 1-2 條 Codex 也認同的調倉操作]
```

### 進階：`--codex-adversarial`（opt-in 壓力測試）

僅當 arguments 含 `--codex-adversarial` 時，**追加**對立面審查段落（攻擊 Codex 結論、找 bug）。預設 `--codex` 不執行。

> 若 Codex 失敗 → 輸出 `⚠️ Codex 不可用：[error]，跳過第二意見`，繼續正常輸出。

---

## Output Format
- 繁體中文
- 簡潔 markdown 表格
- 所有金額為 USD
- Quick 版應在一個畫面內完成
- Full/Deep 版可較長但需結構清晰
- **Telegram Tier**：對話輸出一份簡要摘要（確認執行完畢）；真正的輸出在 `briefing-out/` 的兩個檔案

## briefing-out/ 目錄
- `briefing-out/` 已加入 `.gitignore`（個人化數據，不 commit）
- 每日執行會覆蓋同日期的檔案（不保留版本）
- 手動重發：`python3 tools/send_briefing.py YYYY-MM-DD` 或 `python3 tools/send_briefing.py latest`
