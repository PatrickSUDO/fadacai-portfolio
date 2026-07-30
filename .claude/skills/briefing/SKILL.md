---
name: briefing
description: "Daily portfolio briefing with 3 tiers: /briefing (quick ~1min), /briefing full (~3min), /briefing deep (~5min). Replaces daily-briefing."
user_invocable: true
model: claude-opus-4-8
---

# Portfolio Briefing

三層結構的每日投資組合簡報，取代原 `/daily-briefing`。

## Arguments
- `/briefing` → Quick（~1 分鐘）
- `/briefing full` → Quick + Full（~3 分鐘）
- `/briefing deep` → Quick + Full + Deep（~5 分鐘）
- `/briefing telegram` → Telegram Push Tier（~2-3 分鐘）— 盤中推送專用，不跑 Phase 1-3

### --send 旗標
任何 tier 加上 `--send` 會在 tier 執行完後：
1. 把完整 briefing markdown 寫到 `briefing-out/YYYY-MM-DD-full.md`（Write tool）
2. 把 Telegram 格式純文字寫到 `briefing-out/YYYY-MM-DD-telegram.txt`（Write tool）
3. 呼叫 `python3 tools/send_briefing.py YYYY-MM-DD`（Bash tool）推送至 Telegram + Email
   - send_briefing.py 內部自動呼叫 `generate_html.py`，push HTML 到 reports repo，並在 Telegram 訊息末加上網頁連結

`briefing telegram` 沒有 `--send` 時：只寫 `briefing-out/` 兩個檔案，不發送。
若需手動生成 HTML（不發送）：`python3 tools/generate_html.py briefing YYYY-MM-DD [--push]`

### 執行模型建議
- `/briefing`（quick）→ Sonnet 4.6（純彙整；session 已長則先 `/compact`）
- `/briefing telegram` → Sonnet 4.6（每日 launchd 自動推送，成本敏感，固定 Sonnet；週五 `--codex` 另走 gpt-5.5）
- `/briefing full` → Opus 4.8（中等綜合 + Verdict；Phase 2 subagent 已外包 Sonnet 4.6）
- `/briefing deep` → Opus 4.8（深度合成 + Codex 整合 + 機率/EV）

切換方式：`/model sonnet`、`/model opus` 或 `/model fable` 後執行 skill。

---

## Step 0: 配置同步 & 倉位偵測

執行 CLAUDE.md 的 Step 0 統一規範（0a → 0b → 0c → 0d → **0e**）。
- 讀 `plan.md` + `feedback/*.md`（必做）
- 呼叫 `get_account_position` 取即時持倉
- 今日 journal 不存在 → 執行 gap-fill + 變動偵測 + 自動建立 journal
- 若偵測到的變動對應 plan.md 待辦項 → 在 Phase 1 Step 1 標記
- **0e 第一性原理紀律**：在 Quick Take 之前必須完成「市場主題 thesis / 證偽條件 / 機率分布」三題（見 CLAUDE.md 0e）

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
- `status == "skipped"`（FRED key 缺失）→ 顯示 `⚠️ Macro snapshot unavailable (FRED_API_KEY not set)` 並跳過
- mtime > 36h → 顯示 `⚠️ Macro snapshot stale ({mtime_hours}h old)` 仍使用但標記

將 5 個 series + regime_tag 內容餵給 **Step 0e** 與後續呼叫的 `probability-honesty-checker` agent（其 Step 1i 必須收到此資料）。

## Step 0.55: Leading Indicators Load（所有 Phase / Tier 共用）

讀 cache（不打 API，由 `tools/fetch_leading.py` 預載，TTL 20h；配置 `research/leading-config.json`）：

```
Read briefing-out/cache/leading-indicators.json
```

判定（**逐 block，不整檔否決**）：
- 頂層 `status == "ok"` 或 `"partial"` 且 mtime < 36h → **使用**；`partial` 時只跳過 `status ∉ {"ok","partial","warming_up"}` 的 block，各標 `⚠️ {block} unavailable`
- block `status == "carried_forward"` → 使用但標 `(前日值 {data_as_of})`
- 頂層 `status == "skipped"` / 檔案缺失 → 顯示 `⚠️ Leading indicators unavailable`，跳過所有相關段落；**Deep tier** 強制刷新：`uv run --directory tools python3 tools/fetch_leading.py --force` 後重讀；Quick/Full/Telegram 標旗即續
- `blocks.revision_delta` 某 archive 窗 `available == false` → 顯示 `⏳ archive-diff {窗} warming up（{available_from} 起可用）`，該窗不產生 archive decel 旗標。**vendor 7d 曲線法（Fundamentals Data Feed 的 `vendor_*` 欄位）自首日可用**：`decel_tickers` 為兩法 union，`decel_tickers_archive` / `decel_tickers_vendor` 分列（/trade-review 各驗命中率）；`vendor_book` 給 7d vs 30d 上修寬度對比
- `blocks.tw_monthly` 各檔 `history_months < 2` → accel/轉負 flags 為 null 不判定，僅列數字

在 📊 Macro 行下方顯示 1 行 🚦 儀表（所有 tier 一致，欄位缺失以 `—` 填）：
```
🚦 先行: HY {delta_5d_bps:+}bp/5d ({velocity_flag}) | VIX期限 {ratio} ({term_flag}) | 半導體寬度 {pct_above_50dma}%>50DMA ({breadth_flag}) | 記憶體報價 {memory.n_hits}則/功率 {power.n_hits}則 | 台股月營收 {data_month} {最強檔 YoY%或 —}
```

`gauges` 另帶兩個 FMP 免費層儀表（不進一行 banner，供 full/deep 段落與 Key Alerts 引用）：
- `treasury`（10Y/2Y/3M/30Y + 2s10s/3m10y spread）— plan「10Y <4.35 再加滿」類閘門的即時對照
- `semis_industry_pe`（半導體行業 PE 日頻 + Δ5d/Δ20d + 100 日分位）— **估值溫度計**：與 revision 寬度並讀可分離「估值壓縮 vs 基本面惡化」（PE 大跌 + revision 寬度不動 = 純 de-rating）

**紀律（同影子訊號 A4，記錄不阻擋）：** 本 cache 所有旗標為 **display-only + Key Alerts 標旗**，不得單獨觸發任何加減碼/harvest/否決；由 `/trade-review` 跑滿 ≥2 期驗命中率後才可討論升級硬閘門。

這份 cache 用於：
- 本步 🚦 儀表行（所有 tier）
- **Section 4.6** 財報 Cross-Read 排序（leaders → followers 讀序）
- **Section 5** 強訊號對稱分類 `🟠 decel` 標註與 **Section 12.5** 飛輪檢查 revision 轉折佐證
- **Section 6** Key Alerts 的 regime-break / pricing 反轉 / 台股轉負 / book_decel 旗標
- **§9.5**（Deep）訊號擷取的 pricing_watch 預過濾新聞（excerpt 即 raw_quote 候選）
- **Telegram** T1 `↳ read-through` 子行、T5 🚦 alerts、T8a/T8b 🚦 區塊

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
- Section 4.5 Earnings Calendar 表格的 `Trailing 8Q beat` / `avg surprise` 欄位
- Telegram tier `📅 Earnings This Week` 加 beat rate 標註
- `probability-honesty-checker` Step 1d「Base rate」備選來源（EODHD fundamentals-snapshot 為首選）

---

## Step 0.65: Fundamentals Snapshot Load（所有 Tier 共用，cache-only）

讀 cache（由 `tools/fetch_fundamentals.py` 預載，TTL 24h）：

```
Read briefing-out/cache/fundamentals-snapshot.json
```

判定：
- `status == "ok"` 且 mtime < 30h → **使用**，供估值區塊、probability-honesty-checker 1d/1h 使用
- `status == "skipped"` / mtime > 30h / 缺失 → 標記 `⚠️ Fundamentals cache stale/missing`；Deep tier 強制派 subagent 刷新，Quick/Telegram 標旗但繼續

**EODHD 資料缺口處理（必守）：**
- `highlights.pe_ratio == 0.0` 或 `peg_ratio == 0.0` → 丟棄該三錨點錨，標 `(anchor unavailable)`，不進 Fair PE 計算
- `avg_surprise_pct` 對低基期股（EPS estimate ≤$0.10）可能失真 → beat 次數可信，avg% 在機率計算中標 `(unreliable-low-base)` 並拉寬區間

**Cache-miss fallback / Deep 強制刷新：**
```
Agent(subagent_type="data-collector",
  prompt: "對以下全部持倉（TICKER.US 格式）呼叫 mcp__eodhd-mcp__get_fundamentals_snapshot 與
           mcp__eodhd-mcp__get_earnings_history，回傳 dict {ticker: {snapshot:{...}, base_rate:{...}}}，
           不分析不合成。")
```
Deep tier 每次必跑（強制刷新）；Quick/Full 僅在 cache miss 時派。

這份 cache 用於：
- **Section 8.5（Full/Deep）** 三錨點估值表（A1 pe_ratio / A2 PEG / A3 分析師隱含 PE）
- **Quick Take 下方「💰 估值快訊」**（一行，最便宜/最貴持倉 vs 公允價）
- `probability-honesty-checker` **Step 1d**（beat base-rate 首選來源）與 **Step 1h**（quarterly growth → fundamental intact X/Y）
- **D2 thesis-impact 推理**：`fair_value_before/after` 重算從同一 cache 取三錨點輸入

---

## Step 0.67: News Articles Load（所有 Tier 共用，cache-only）

讀 cache（由 `tools/fetch_news.py` 預載，TTL 6h）：

```
Read briefing-out/cache/news-articles.json
```

判定：
- `status == "ok"` 且 mtime < 8h 且 `"content" in fields_available` → **使用**，P3 信號擷取（Deep tier §9.5）可讀 body
- `status == "ok"` 但 `"content" not in fields_available` → **有限使用**（只有 headline+sentiment，P3 只能做 headline 掃描，標 `⚠️ news body 不可用`）
- `status == "skipped"` / mtime > 8h / 缺失 → 標記 `⚠️ News cache stale/missing`，Quick/Full/Telegram 略過 P3 信號擷取，Deep tier 繼續（P3 降級為僅 SEC/逐字稿）
- Quick / Full / Telegram tier：**不讀 body，不做信號擷取**；news cache 僅供 Deep tier §9.5 使用

---

## Step 0.7: Thesis Ledger 驗收 & 逾期掃描（所有 Tier 共用）

帳本 = `research/thesis-ledger.json`，工具 = `tools/thesis_ledger.py`（去重/碰撞/到期/過期/統計全在程式層，**Claude 不手改 JSON**）。

**1. 取得今日到期清單（同時自動 expire sweep）：**
```
python3 tools/thesis_ledger.py due
```
回傳 `{due:[...], expired:[...]}`。`expired` 是工具自動把「逾期 >30 天未驗收」轉掉的，當作無結果。

**2. 對每筆 `due` thesis 驗收：**
- 讀該筆 `trigger.metric` → 知道要抓什麼（財報營收/ASP/毛利率、板塊 ETF、價格…）
- 用既有 MCP（yfinance / `earnings_history.py` cache / technical 等）抓**實際數字**
- 對照 `thesis` + `falsification` 判定 `passed` / `failed` / `partial`
- **抓不到新數**（event 觸發但財報還沒出）→ 用 `reschedule` 把觸發日往後推、維持 pending，**絕不猜 verdict**：
  ```
  python3 tools/thesis_ledger.py reschedule --id <id> --to YYYY-MM-DD --reason "財報未出"
  ```
- 有結論 → 先做 **D2 三桶股價影響分解**，再呼叫 `resolve` 帶結構化旗標：
  - **passed**：用財報後新數字重算 D1 三錨點（`pe_ratio × fwd_eps` 各情境） → `fair_value_after`；`price_impact_pct = (after−before)/before`
  - **failed**：同上但用惡化輸入（成長減速/砍 guide） → `fair_value_after` 下修
  - **partial**：拆分 thesis 成分 vs 倍數/價格成分 → `impact_decomp = "thesis +X%(基本面)/multiple −Z%(re-rate)=net −W%"`
  ```
  python3 tools/thesis_ledger.py resolve --id <id> --verdict passed|failed|partial \
    --actual "實際數字" --note "判讀" --next-action "由此推出的操作" \
    --fair-value-before <float> --fair-value-after <float> \
    --price-impact-pct <float> --impact-decomp "thesis +X%/multiple −Z%=net −W%"
  ```
  `fair_value_before/after` 取自 Step 0.65 fundamentals cache 的三錨點計算；全部選填，有數就帶。

**3.（已除役 2026-07-30）** 舊 naked-call-watchlist 3 閘門檢查已移除 —— 該清單為 6/5 反應式閘門時代產物（方法論 6/13 已被預掛 GTC 買梯取代），檔案歸檔至 `research/archive/`。樂透機會由 Section 11.5 掃描 + 價格警報器承接，不再每日讀舊清單。

**4. 輸出「📋 thesis 驗收」區塊**（接在 Key Alerts 後 / Quick Take 前）：
```
## 📋 thesis 驗收
| thesis | 命題 | 實際 | verdict | 公允價 before→after | 價格影響 | → actionable |
|--------|------|------|---------|---------------------|---------|-------------|
| MU:memory-cycle | DRAM 漲價毛利率>40% | ASP +8%、毛利率42% | ✅ passed | $320→$370 | +15.6% | HOLD，加碼門檻 $XXX |
（無到期項則略過此區塊；「公允價 before→after」和「價格影響」欄只在 resolve 時填，reschedule 留空）
⏳ 逾期未驗收已歸檔：[expired 清單，若有]
```

**驗收結果直接餵 actionable**：passed → 強化/HOLD/加碼（含新公允價上修幅度）；failed → 汰弱/減碼（含公允價下修多少）；partial → 分解 thesis vs multiple 成分後決定操作。`resolve --next-action` 寫的就是下一步行動，併入 Key Alerts / 行動項。

**5. SA 量化榜整合（2026-07-25 用戶指定）**：
- 到期提醒：ledger 有 `MARKET:sa-quant-scan-*` due（或 `research/sa-quant-scans/` 最新快照 >35 天）→ Key Alerts 加一行 `📋 SA 量化榜掃描到期：請貼最新 screener（條件凍結），與 {最新快照日期} 基準 diff`；未到期不輸出。
- 輔助訊號引用：判讀持倉/bench 名字時**可**引用最新快照的 quant 排名/verdict（標註快照日期，如「SA quant #1 @07-24」）；快照 **>35 天視為 stale 不引用**。
- 管線與鐵則見 plan.md「SA 量化榜掃描機制」：榜單是儀表板非方向盤——掉榜 = revision 覆查警報（最高價值），quant 高分 ≠ 買進（必過 headroom/coverage/mandate/結構四濾網）。

---

## Step 0.75: 影子訊號 & 交易檢討到期（所有 Tier 共用）

launchd 路徑下 `tools/briefing_runner.sh` 已預取此兩項；**手動執行 briefing 時才需自己跑**（重跑安全，有去重）：

```bash
python3 tools/shadow_signals.py flag          # A4 高估旗標，記錄不阻擋
python3 tools/trade_ledger.py snapshot-orders # 在掛單快照（歸因 ground truth）
python3 tools/trade_ledger.py orders          # 讀回：死單 + 不在 plan 的在掛單
```

**1. A4 高估旗標（🟣 影子模式）**

`flag` 回傳 `A4vsA3 ≤ −35%` 且 `self_valuation.confidence == ok` 的持倉。在 Key Alerts 加一行：

```
🟣 A4 高估旗標（影子，不阻擋）：{ticker} A4vsA3 −X%｜{ticker} −Y% — 記錄中，滿 30 天由 /trade-review 計分
```

**這一行只做記錄，不得據此改變任何建議。** A4 依 CLAUDE.md 0e 仍不進 median、不進 EV。跑滿 2 期檢討才決定是否升為硬閘門（見 `feedback/RULES-LEDGER.md` R3）。
無旗標則整段省略。

**2. 在掛單快照 + 死單偵測**

`snapshot-orders` **每個交易日都必須跑**，累積訂單登記表——這是往後把成交歸因到「系統決策 vs 自主決策」的唯一可靠來源。券商 `order_status` 只回在掛單，成交/取消後即消失，**斷一天就有一天的成交永久無法歸因**。

掛單 >30 天未成交 → Key Alerts 加一行：
```
⚠️ 死單：{order_id} {買/賣} {ticker} {N}股 @${price}（掛 D 天）→ 重新定價或撤單
```
`python3 tools/trade_ledger.py orders` 另會標出**不在 plan.md 的在掛單**（plan 與券商實況脫節），一併列出。

**3. 未結旗標（🔴 本書最貴的漏口，優先於其他所有 alert）**

```bash
python3 tools/trade_ledger.py flags
```

**量測結論（2026-07-25）：吃掉最多回撤的機制是「已標記惡化但沒有強制出場」，自警示以來 −$6,333。** 成因是旗標只活在 briefing 散文裡：TSLA 與 ON 的 thesis-ledger `history` 都是 **0 筆**，沒有任何東西在數延後次數，所以每天把同一個警示當新的重述一次。

輸出規則：
- `forced_action_required` 非空 → **Key Alerts 第一行**，格式：
  `🔴 強制決定：{id} 已延後 {n} 次｜自警示 {days} 天累積 −$X → 減碼 1/3 或明文撤旗（附理由）`
- `overdue` 非空 → `⚠️ 旗標逾期：{id}（deadline {date}，逾 {n} 天）`
- `post_flag_fills.buys > 0` → `⚠️ {ticker} 在警示後仍加碼 {n} 股（{dates}），損益 $X`

**開旗紀律（強制，這是修好漏口的關鍵）：**
凡在 briefing / journal 寫下 ⚠️ / 降桶候選 / 勿再向下加碼 / thesis 蒙塵 / 待覆判 的部位，**同一次必須開旗**：

```bash
python3 tools/trade_ledger.py flag --ticker <T> --slug <kebab> \
  --reason "<警示內容>" --deadline <YYYY-MM-DD 決定到期日>
```

延後**不是免費的**，必須走 `defer`（會計次）：
```bash
python3 tools/trade_ledger.py defer --id <id> --to <新日期> --reason "<為何還不決定>"
```
**第 3 次延後自動轉 forced** → 減碼 1/3 或明文撤旗。撤旗也要走 `resolve-flag --action withdrawn --note "<為何警示不成立>"`。

> 反例存證：TSLA 7/01 標降桶候選，7/08 再提、7/09「不砍改收租」（用 PMCC 取代決定）、7/13 ledger 記 on-track，最後 −52.7% / −$6,399。若當時有此機制，**7/13 就會被強制處理**（標的 $425 vs 現在 $313）。

**4. thesis 中途證偽掃描（不等觸發日）**

```bash
python3 tools/thesis_ledger.py recheck --long-drift-only --limit 5
```

Step 0.7 的 `due` 只在**觸發日**驗收；`recheck` 補的是中間那段。列出「已過天數」最長的 5 筆，各問一句：**證偽條件裡有沒有現在就看得到的已經成立？**

- 成立 → 立刻 `resolve --verdict failed`，不等觸發日，並進 Key Alerts actionable
- 前提完好 → 不輸出（避免每日噪音）

quick / telegram tier 只掃前 3 筆；full / deep 掃全部長飄移筆數。

**5. 交易檢討到期提醒**

讀 `research/last-trade-review.txt`（單行日期）。距今 >14 天（或檔案不存在）→ Key Alerts 加一行：

```
📋 交易檢討已到期（上次 YYYY-MM-DD，D 天前）→ 執行 /trade-review
```

未到期不輸出。**briefing 不代跑檢討**——歸因需要逐筆判斷決策來源，要用戶在場。

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
比對選擇權持倉的 underlying ticker vs 現股持倉。若 underlying 沒有對應現股（如 CRWD、DDOG、GOOGL、LRCX、TSLA、TEAM），
使用 `mcp__technical-mcp__get_batch_indicators` 或 `mcp__yfinance-advanced__get_stock_info` 取得該標的目前現股價格。
在 Options Status 表格中加入「標的現價」和「距 Strike %」欄位，方便判斷 ITM/OTM 狀態。

**4b. Options 總覽表：**

| 合約 | 方向 | 到期日 | 剩餘天數 | 標的現價 | 距Strike% | 損益% | 狀態 |

⚠️ 標記剩餘 <14 天的合約。

### 4.5 Earnings Calendar Check（Technical Snapshot 前必做）

**為何必要：** 持倉 ticker 在 ±48h 內若有財報，technical signal（trend / momentum / RSI）會被 earnings reaction 主導，不是結構性訊號。直接套「弱勢持續 → 減碼」會在 fundamental beat 後賣在低點（PLTR 5/5 案例）。

**資料來源**：Step 0.6 已預載 `briefing-out/cache/earnings-dates.json` + `earnings-history.json`，直接從 cache 取，**不再呼叫 MCP**（若 cache 缺失或 ticker 不在，才 fallback `mcp__fmp-mcp__getEarningsCalendar`）。

**執行步驟：**
1. 從 cache 列出未來 7 天內、或過去 48h 內有財報的持倉 ticker
2. 對 earnings window（±48h）內的 ticker，在 Step 5 Technical Snapshot 表格的「標的」欄位前綴 ⚠️
3. 對 earnings window 內的 ticker：
   - **不執行**「弱勢持續 → 減碼」等自動規則
   - actionable 改寫為「等 N+1 個交易日 settle 再判斷結構」
   - 若強行給建議，必須先 confirm fundamental 數字（revenue / EPS / guide）方向，不能只看 price action
4. **輸出格式（必須含 base rate）：**

   ```markdown
   | 標的 | 日期 | 時機 | 距 earnings | Trailing 8Q beat | Avg surprise % | 狀態 |
   |------|------|------|------------|-----------------|---------------|------|
   | NVDA | 2026-05-20 | AMC | 2d | 8/8 (100%) | +6.3% | 🔴 window 內 |
   | AVGO | 2026-06-03 | AMC | 16d | 7/8 (87.5%) | +3.4% | 觀察中 |
   ```

   `Trailing 8Q beat` 與 `Avg surprise %` 從 `earnings-history.json` 的 `beat_count/total` 與 `avg_surprise_pct` 直接讀。

5. 若 cache `status` ≠ `"ok"` 或 ticker 不在 cache → 該欄填 `(unavailable)`，並在輸出末尾加註 `⚠️ N tickers 缺 earnings cache（請手動 python3 tools/earnings_history.py --force）`

6. **財報叢集曝險（book 級檢查，必做）**：
   - 計算「未來 7 個日曆日內有財報的持倉」合計佔組合 %（權重從 Step 0b 持倉算）
   - 表格後固定輸出一行：`📊 財報叢集：未來 7 日窗內持倉合計 X%（N 檔）`
   - **> 20% → 🔴 叢集警示**（進 Key Alerts）：提示 ① 該窗內 Swing Risk 🔴 / 梯級到價的認列桶倉位**提前 harvest**（財報前落袋，不賭 binary）② 暫停對同窗 ticker 新增曝險（現股與選擇權皆是，選擇權本有 ±48h 禁令）③ 窗內合計曝險與各檔 beat rate 一併列出供判斷
   - 10–20% → 🟡 資訊性標註，不強制動作

> 詳見 `feedback/earnings-reaction-window.md` 與 `feedback/weak-signal-root-cause.md`

### 4.6 財報 Cross-Read（先行者 → 後行者讀序）

資料：Step 0.55 `earnings_crossread.chains`（鏈定義 `research/leading-config.json`，日期由 fetcher 解析，不打 API）。

規則：
1. 只展開 `active == true` 的鏈（leader 過去 10 日已發或未來 7 日將發、或 TSMC 月營收窗 8–12 日）；無 active 鏈 → 一行「本期無 active cross-read 鏈」
2. leader **已發**（`reported_within_10d`）：從 news cache（Step 0.67）/ pricing_watch 摘 1 句硬數字（capex guide / bit 出貨 / book-to-bill / backlog…），**須逐字 quote ≤120 字，無 quote → 標「已發，硬數字未見」**（同 §9.5 反幻覺門檻）；方向標 ↑/↓/→ 作為 followers 的 **prior**
3. `news_only` leader（SK海力士/三星/Infineon）：無排程日期，靠 pricing_watch 承接，有相符 item 才列，附 `recurrence` 提示
4. **禁**：leader 結果不得直接轉成 follower 買賣指令 — 只更新 prior；行動仍走各自 gate（earnings window ±48h 禁令、revision 閘門不變）

| 鏈 | Leader（日期/狀態）| 讀什麼 | Followers（財報日）| Leader 訊號（quote）|
|----|------------------|--------|------------------|-------------------|
| hyperscaler_capex | GOOGL 7/22 ✅ / META 7/29 | capex guide | NVDA 8/26, COHR 8/12… | capex ↑ "…"（來源）|

### 5. Technical Snapshot
使用 `mcp__technical-mcp__get_batch_indicators` 取得全持倉技術指標。

**欄位順序（依決策權重排列）：**

| 標的 | 現價 | 趨勢 | MACD | 量能比 | 動能分 | RSI |

- **趨勢**：strong_uptrend / mild_uptrend / consolidation / pullback / weak_downtrend / strong_downtrend
- **MACD**：顯示 crossover 狀態（golden_cross 🚀 / death_cross ⚠️ / none）
- **量能比**：volume_ratio（>1.5 爆量 / <0.7 縮量）
- **動能分**：momentum_score（-100 ~ +100）
- **RSI**：僅數值列示。**RSI 過高不觸發任何警示/標籤/動作**（2026-07-01 用戶定調：強者愈強，超買非賣出理由；反轉偵測交給 revision 閘門）。RSI < 30 可作超賣參考

**複合訊號標記規則（必須多指標同時觸發 + 無 earnings window）：**

| 標記 | 觸發條件 |
|------|---------|
| 🔴 弱勢持續 | downtrend + momentum_score < -30（不是機會，是落刀）|
| ⚠️ 動能背離 | uptrend + momentum_score 轉負 OR death_cross（趨勢未破但動能轉弱）|
| 🚀 強勢確認 | golden_cross + strong_uptrend + volume_ratio > 1.2 |
| ⚠️ earnings window | 過去/未來 48h 有財報 → **以上規則一律不套用**，標記 wait N+1d |

> 舊「🔴 拋物線警示（RSI>75）」「🟡 留意（RSI>70）」已於 2026-07-01 移除 — RSI 過高類標籤是飛輪/對稱性規則之前的遺留，一律不再產生。

**根因分類規則（看到弱勢/強勢訊號必做）：**

對任一 weak_down / strong_down / momentum < -20 訊號，先回答根因再行動：
1. 過去 48h 有財報？→ (b) earnings reaction → HOLD wait
2. 同板塊 ETF 也弱？→ (c) sector rotation → 評估板塊配置
3. fundamental 數據惡化？（revenue growth 連 2 季減速 / guide 下修）→ (a) thesis 破裂 → **可執行汰弱**
4. 以上皆否 → (d) noise → 忽略

只有 (a) 才執行「汰弱留強」減碼。詳見 `feedback/weak-signal-root-cause.md`

**強訊號對稱分類（看到貼高/大漲訊號必做 — per `feedback/momentum-valuation-symmetry.md`；RSI 過高不是輸入）：**

對任一貼 52W 高 / 單日大漲 / 已漲多訊號，先查 **revision 方向**再行動：
1. estimate 上修中（revisions up ≫ down / eps_revision_30d_pct > 0）+ 成長加速？→ **加速領導者**：在倉**讓它 run、不 trim**（強者愈強；認列桶仍按梯級停利級距走）；新資金不否決，改 starter + 回檔 ladder + bull call spread 定義風險

> ⚠️ revision 引用必附 coverage：**分析師數 N≥15 全權重；8–14 半權重（須與 trend/季成長印證）；<8 不單獨觸發加減碼**；上次財報後 >45 天的 revision 標 stale 降權（per `feedback/momentum-valuation-symmetry.md` 規則 6）

> 🟠 **revision decel（Step 0.55 cache 旗標，影子驗證中）**：該股在 `revision_delta.decel_tickers` 中（上修仍為正但 7d/30d 動能顯著縮減）→ 在該股行尾標 `🟠 decel`。**只標記不改結論**：不因此提前 harvest、不否決加碼、不進 EV；連同 `book_decel` 記入 Section 6 Key Alerts，由 /trade-review 驗命中率。`warming_up` → 本標註完全不出現。
2. estimate 翻下修/flat + 高倍數？→ **峰值 harvest 候選**：認列桶列入 harvest 清單（這才是「賣強」的正當時機）
3. weak_downtrend 反彈 + momentum 低 + 無 revision 支撐？→ **受損 turnaround**：等催化驗收，不接刀（今天綠 ≠ 領導力）

**禁**：把「超買/太貴/已漲多/RSI 高」單獨當在倉 trim 或新倉否決理由 — 只影響**下手結構**（分批/spread），永不影響**方向**。賣出仍須過 (a)/(b)/(c) trim 閘門（`feedback/position-concentration.md`）。

### 6. Key Alerts
只在觸發時顯示（無則跳過整個 section）：
- 單日跌 > 5%
- 總虧 > 15%
- 單一持倉 > 8% 組合（過度集中；>10% 🔴 紅線）
- 財報 < 3 天（用已知財報日歷）
- 選擇權 < 14 天到期
- **Swing Risk**：認列桶肥利潤（>+40%）+ 高 β + revision 轉折/題材降溫，且無對應落袋掛單 → `🔴 Swing Risk 未處理`（附建議可掛單）
- **梯級停利到價/缺口**：認列桶倉位觸及下一梯級（+30/+60/+100/每+50pp）而無對應 GTC 掛單，或存量累計減碼低於級距應達比例 → `🟡 梯級缺口`（附補掛單，per `feedback/tiered-profit-taking.md`）
- **財報叢集**：未來 7 日財報窗內持倉合計 >20% → `🔴 叢集曝險 X%`（見 Section 4.5 step 6）
- **現金滯留**：現金 >15–20% 且無 GTC 掛單覆蓋、無 dry powder 理由 → `🔴 飛輪滲漏`
- **🚦 Regime break（Step 0.55，display-only）**：credit `widening_fast`（HY OAS Δ5d ≥ +25bp 或 Δ20d ≥ +50bp）/ VIX 期限 `inverted`（^VIX/^VIX3M ≥ 1.0）/ 半導體寬度 `divergence_flag`（SMH 距 52w 高 <5% 且寬度 <50%）→ 各 1 行附數字，不觸發自動動作
- **記憶體/功率報價反轉**：pricing_watch 出現合約價轉跌 / lead time 縮短 / 砍單類 quote → `🚦 pricing 反轉候選`（附逐字 excerpt + 對應 thesis slug，如 MU:memory-supply-response-2027）
- **台股月營收轉負**：tw_monthly 任一檔 `turned_negative == true` → `🔴 需求證偽候選：{名} 月營收 YoY 轉負 → 提前檢討 ON/DIOD，不等財報`
- **Revision book decel**：`book_decel == true` → `🟠 revision 動能減速（寬度 {breadth_pos_pct}%，7d {momentum_7d_pp}pp）`；`book_rollover == true` → 升 `🔴 revision 寬度跌破 50%`
- **🔴 回檔行為熔斷（R15）**：讀 `briefing-out/cache/account-metrics.json` → `equity.circuit_breaker_active == true`（帳戶自峰回落 >10%）→ 固定顯示 `🔴 回檔熔斷生效中（峰 {peak_date} −{current_drawdown_pct}%）：信念桶禁淨減碼；清倉/降桶決定強制隔夜（寫理由過根因分類，次日確認）；僅機械單（梯級 harvest/旗標 forced/既掛 GTC）照常`（規則 `feedback/holding-period-discipline.md`；cache 缺失 → 跳過不猜）

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
  1d. Binary catalysts (window 7d): [從 Section 4.5 Earnings Calendar Check 摘出，
      **必須含 trailing 8Q beat rate + avg surprise %**。
      資料來源優先順序：
      (1) fundamentals-snapshot.json → tickers.TICKER.base_rate（EODHD，首選）
      (2) earnings-history.json → tickers.TICKER（yfinance，備選）
      格式：「N/8 beat, +X.X% avg」。⚠️ 低基期股（AMD/CRDO/ONTO 等 avg_surprise_unreliable=true）→ 只用 beat N/8，avg% 標 (unreliable-low-base) 不進 Step 3。cache 缺 → (unavailable)]
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

**💰 估值快訊（Quick tier 僅一行，cache 算）：**
```
💰 估值：{最被低估標的} vs 公允價 −X%（三錨點中位） | {最被高估標的} vs 公允價 +X% | 今日 thesis 影響：{ticker} {verdict}→ $FV_before→$FV_after（±X%） | 自建分歧最大：{ticker} A4 vs A3 {±X%}
```
規則：
- 從 Step 0.65 fundamentals cache 算三錨點 Fair PE（A1 PE / A2 PEG×growth / A3 PT÷FwdEPS），各持倉公允價 = 中位錨 × analyst fwdEPS
- 最被低估 = min(現價/公允價)；最被高估 = max(現價/公允價)；≥3% 持倉優先
- 今日 thesis 影響：從 Step 0.7 resolve 結果取，無 resolve 或 cache missing 則省略
- **自建分歧**：從 `self_valuation.own_target_price` vs A3 `wall_street_target` 計算 `A4vsA3 = (own_target − A3_target)/A3_target`；取 ≥3% 持倉中絕對分歧最大者；`confidence==unavailable` 的 ticker 跳過；整段在所有 ≥3% ticker 都是 unavailable 時省略

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

### 8.5 個股估值（三錨點公允價）

**資料來源：** Step 0.65 fundamentals-snapshot.json（cache-first；Deep tier 強制已刷新）

**執行範圍：**
- Full tier：≥3% 持倉全部（純股票持倉；選擇權部位只列 underlying 若持有現股）
- Deep tier：全持倉（含 <3% 小倉）+ 每檔加 DCF 交叉檢核行

**三錨點 Fair PE 計算規則（每檔必守）：**

| 錨點 | 來源欄位 | 規則 |
|------|---------|------|
| A1（市場隱含）| `highlights.pe_ratio` | `== null / 0.0` → 丟棄，標 `(N/A)` |
| A2（成長合理）| `highlights.peg_ratio × (quarterly_revenue_growth_yoy × 4 或 fwdEPS_growth%)`；AI 龍頭（NVDA/AVGO/CRWD/AMD）目標 PEG 1.5，其餘 1.0 | `== null / 0.0` → 丟棄 |
| A3（分析師隱含）| `highlights.wall_street_target ÷ fwdEPS`。**fwdEPS 來源優先序：** ① `snapshot.forward_estimates.curr_fy.eps_avg`（EODHD 真實賣方共識，當前 FY）→ ② `forward_estimates.next_fy.eps_avg`（次年 FY）→ ③ 保底 `eps_ttm × (1 + growth%)` 近似。cache 已在 `self_valuation.a3_fwdeps_source` 標來源（`consensus_curr_fy`/`consensus_next_fy`/`approx`），直接讀勿重推 | 任一缺 → 丟棄 |

情境指派規則（可重複）：
- **基準 Fair PE** = median(有效錨點)
- **樂觀 Fair PE** = max(有效錨點) × 1.25，**上限：current_PE × 1.25**（不得無限擴張）
- **悲觀 Fair PE** = min(有效錨點) × 0.70，**下限：current_PE × 0.70**
- 僅 1 個有效錨 → 用該錨 ×1.10 / ×0.90，並在備註標 `⚠️ 單錨低信心`

情境 FwdEPS：
- 基準 = analyst 共識 fwdEPS（`forward_estimates.curr_fy.eps_avg`；缺則 next_fy；再缺才用 `eps_ttm×(1+growth)` 近似）
- 樂觀 = 基準 × (1 + min(avg_surprise_pct, 15%))；avg_surprise_unreliable=true → 直接用 +5%
- 悲觀 = 基準 × (1 − 5%) [beat_pct≥75%] 否則 × (1 − 10%)
- **EPS 修正動能（P3 訊號）**：`forward_estimates.{curr_fy,next_fy}` 另帶 `eps_revision_30d_pct` 與 `revisions_up_30d / down_30d`——共識 30 日內上修（up≫down 或 pct>0）= guidance 偏正領先訊號，可在備註或 P3 訊號推導引用（非估值輸入）
- **修正曲線（Fundamentals Data Feed，2026-07-28 起）**：每期另帶 `eps_revision_7d_pct / revisions_up_7d / revisions_down_7d / eps_revision_60d_pct / eps_revision_90d_pct` — 90d→60d→30d→7d 斜率遞減 = 上修波退潮中（Step 0.55 revision_delta 的 vendor 法直接吃這組）
- **季度趨勢（Fundamentals Data Feed）**：`snapshot.quarterly_trends[]`（最近 6 季 `revenue_yoy_pct / gm_pct / inventory_days / inventory_days_qoq`）— 缺貨 thesis 證偽指標（ON/DIOD/MCHP/MU 的 GM QoQ 與庫存天數方向），thesis 驗收與 §9.5 可直接引用

**Full tier 輸出表（每持倉一行）：**
```
| 標的 | 現價 | A1 PE | A2 PEG錨 | A3 PT錨 | Fair PE(基/牛/熊) | FwdEPS | 公允價(基/牛/熊) | A4自建目標 | A4vsA3分歧% | 現價/公允基% | 備註 |
|------|------|-------|---------|---------|-----------------|--------|----------------|----------|------------|------------|------|
| MU | $XXX | 40.8 | 35.2 | 44.1 | 40.8/55.1/28.6 | $9.2 | $375/507/263 | $987 ⚠️低信心 | +33% | −8% | beat 8/8 |
| CRWD | $XXX | N/A | 62.1 | 71.3 | 66.7/89.1/46.7 | $3.8 | $253/339/177 | (self-val N/A) | — | +5% | A1 anchor N/A |
```

欄位說明：
- **現價/公允基%** = (現價 − 基準公允價) / 基準公允價；負 = 被低估；正 = 被高估
- 若 abs > 30% → 在備註標 `⚠️ 大幅偏離`；若 abs > 50% → 標 `⚠️⚠️ 異常大偏離，錨點可能失效`
- **A4自建目標**：從 `self_valuation.own_target_price`（cache 已算，**不重算**）；`confidence=="unavailable"` → 標 `(self-val N/A)`；`confidence=="low"` → 標 `⚠️低信心`
- **A4vsA3分歧%** = `(A4目標 − A3 wall_street_target) / A3 wall_street_target`；A4 不進 median(A1,A2,A3)，不進 EV（與 DCF 同為 sanity/divergence flag）
- A4vsA3 > +20% → 我較 Street 樂觀：檢查是否有 Street 未定價的成長 driver；A4vsA3 < −20% → 我較 Street 保守：Street 可能過度樂觀，留意下修風險

**DCF 交叉檢核（Deep tier 每檔追加一行）：**
```python
mcp__fmp-mcp__getDCFValuation(ticker)
```
- 有值 → 追加：`  DCF 交叉: $XXX (vs 基準公允 $XXX, 差 ±X%)　[⚠️ 乖離>30% → 錨點存疑]`
- 402 / empty / 免費版限制 → 標 `DCF 不可用 (FMP free tier)` 靜默略過
- DCF 結果**僅為 sanity flag，不進 EV 計算**

**資料缺口標準處理（不得猜測）：**
- pe_ratio = 0.0 → `A1: N/A` （CRWD 已知缺口）
- peg_ratio = 0.0 → `A2: N/A`（CRDO 已知缺口）
- wall_street_target 缺 → `A3: N/A`
- fwdEPS 三來源（consensus curr_fy / next_fy / approx）皆缺 → 整欄標 `(fwdEPS unavailable)`，不輸出公允價

### 9. Sentiment Analysis
使用 Agent 子代理（subagent_type: "data-collector"）取 top 5 持倉的情緒數據：

- **Agent: EODHD Sentiment**（subagent_type: "data-collector"）→ `get_sentiment_trend`（ticker format: "TICKER.US"）

| 標的 | 7日情緒 | 30日情緒 | 趨勢 | 備註 |

情緒 < -0.3 的標的額外調用 `get_news_sentiment` 顯示負面新聞。

### 9.5 訊號擷取 & Thesis 候選（**僅 Deep tier**）

**目的：** 從 news body + SEC 8-K + 宏觀 calendar 抽**已量化陳述**，推導可驗證 thesis 候選，補上財報間隙的高頻 thesis-health 信號。

**反幻覺門檻（必守）：** 每個 signal 必須附 `raw_quote`（≤120 字逐字引用）；無 quote → 無 signal；只有 narrative → 明寫「無可量化信號（only narrative news）」，不捏造數字。

**資料管道優先順序（可靠度由高到低）：**
1. SEC 8-K 硬數字（`mcp__sec-edgar-mcp__analyze_8k`）→ `confidence: high`；僅針對 ≥3% 持倉在過去 14 天有新 8-K 者
2. 財報硬數字（財報後 30 天內）→ `confidence: high`。⚠️ **FMP `getEarningsTranscript` 已實測 402（2026-07-28，免費層無逐字稿）**，改走：SEC 8-K 財報 exhibit（`mcp__sec-edgar-mcp__analyze_8k` / `get_filing_content`，Item 2.02 附 earnings PR 全數字）或 EODHD news body 財報報導
3. EODHD raw news body（Step 0.67 `news-articles.json`，需 `"content" in fields_available`）→ `confidence: medium`（一般新聞常缺晶圓級細節）
3b. Leading cache pricing_watch（Step 0.55 `pricing_watch.memory/power[].excerpt` — 關鍵字預過濾 + 逐字 excerpt ≤240 字）→ `confidence: medium`；excerpt 可直接作 raw_quote 來源（仍須裁剪為 ≤120 字逐字引用），涵蓋非持倉訊號源（TSM/SNDK/STM/TXN 報價與 SK hynix/Samsung/Infineon 發布）
4. 宏觀 calendar（`macro-snapshot.json` regime_tag + `get_economic_calendar(high_impact_only=True)`）→ 宏觀主題 thesis 輸入

**訊號 record shape（Claude 輸出，不寫 JSON 到 cache）：**
```
metric: wafer_starts / capex / ASP_QoQ / segment_revenue / utilization / Fed_rate / CPI
value: "+8% QoQ"（逐字含單位）
direction: up | down | flat
ticker/theme, source_url_or_desc, source_type: news|sec_8k|transcript|macro, date
confidence: high | medium | low
raw_quote: "<逐字引用，≤120 字>"    ← 無此欄 = 不成立
```

**訊號 → thesis 轉換（Step 0e 紀律）：**
signal 需轉成 1 句可驗證命題 + 2-3 量化證偽點 + 觸發點才算完整 thesis：
```
SIGNAL: MU 投片量 +8% QoQ (source: EODHD/Reuters, conf medium)
→ THESIS: "MU 投片量 +8% QoQ 預示 FY27 bit 出貨 YoY >25% 且 DRAM ASP 不跌破 −5% QoQ"
→ FALSIFY: ["下季 bit shipment YoY <25%","DRAM ASP QoQ <−5%","guide 下修 >10%"]
→ TRIGGER: event, <next_earnings from earnings-dates.json>, metric="bit shipment YoY + DRAM ASP QoQ"
```

**Thesis 登錄規則：** 僅 `confidence ∈ {high, medium}` 且有明確前瞻 trigger → 登錄 ledger（`--source signal-inference`，`--ev` 存 signal provenance）；`confidence=low` 只在 briefing 文字呈現，不入 ledger；exit-code-2 碰撞 → 改 slug 或 supersede。
```
python3 tools/thesis_ledger.py list --ticker <T>         # check existing first
python3 tools/thesis_ledger.py add --ticker <T> --slug <slug> \
  --thesis "..." --falsification "..." "..." \
  --trigger-type event|date --trigger-date YYYY-MM-DD \
  --event earnings --metric "..." \
  --source signal-inference \
  --ev "signal: <metric> <value>, <source>, conf=<confidence>"
```

**誠實退化（必守）：** 若此 tier 的 ≥3% 持倉全部回傳「只有 narrative，無量化數字」→ 整段輸出：
```
§9.5 訊號擷取：本期無可量化信號（只有 narrative news，無 SEC 8-K / 逐字稿量化句）
```
不輸出任何推測數字，不改寫 qualitative 為 quantitative。

### 10. Market Dynamics
- `mcp__fmp-mcp__getBiggestGainers` + `getBiggestLosers`
- 檢查持倉是否出現在極端波動名單
- 市場主題掃描（板塊輪動、避險情緒等）

### 11. Prediction Markets
- `mcp__polymarket-mcp__search_markets` 搜尋與持倉板塊相關事件
- 搜尋關鍵字：AI regulation, tariffs, Fed rate, semiconductor
- 顯示相關事件及概率

### 11.5 樂透機會掃描（Lottery Opportunity Scan）

**目的：** 從市場掃出**至多 3 個**適合短 DTE OTM Call 樂透的候選（per memory feedback：樂透用近期 OTM Call 不用 LEAPS，避免 vega 干擾凸性）。

**篩選步驟（重用 Section 10 movers + active list 數據，不額外抓取）：**
1. 候選池：`getBiggestGainers` + `getMostActiveStocks`
1b. **槓桿 ETF 先映射本尊再判斷（2026-07-30 BE 案）**：榜上槓桿/反向 ETF（名稱含 2x/3x/Long/Short Daily）不得直接當雜訊丟棄 —— 先映射 underlying（BEG→BE、MUZ→MU…），本尊若 mandate 內且有 binary catalyst → 以本尊進入後續篩選
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
- 本節選擇權樂透 = 權利金即最大損失（defined risk，不掛停損）；若建議**現股**樂透/事件倉 → 依 R16 建倉單必附 GTC 普通停損（技術失效位、≥2× ATR，`feedback/holding-period-discipline.md` 規則 3）
- **不推 LEAPS OTM 當樂透**（vega 干擾，違反 feedback_options_vega_playbook.md）
- 「上行 +XXX% / 下行 max loss = premium」必寫
- 若候選 IV Rank > 80：警告「IV 過高，後續 IV crush 風險」

### 12. 計畫 Full Alignment
完整進度表：

| # | 計畫操作 | 狀態 | 觸發條件 | 當前數據 | 備註 |
|---|---------|------|---------|---------|------|
| 1 | 加碼 NVDA | ⏳ 待觸發 | RSI<35 | RSI=42 | 接近 |
| 2 | DDOG BCS | ✅ 已完成 | — | — | 3/5 建倉 |

### 12.5 飛輪檢查（Full/Deep 收尾必跑 — per `feedback/momentum-valuation-symmetry.md` 定期節奏）

精簡三問（完整版在 /portfolio-review 4.5；briefing 只掃描 + 給可掛單，不展開全表）：

1. **該 harvest 誰？** 認列桶（roster 見 plan.md 組合架構 v2）中 ① **梯級停利到價/缺口**（+30/+60/+100 級距，per `feedback/tiered-profit-taking.md`）② revision 轉折/題材降溫/Swing Risk 🔴（可提前下一級；revision 轉折的機械佐證可引 Step 0.55 `revision_delta` 的 `decel_flag`/`book_decel`，仍屬 prior 非強制 harvest）→ 每筆附 GTC 賣限價或 covered call 結構。**revision 仍上修的領導者只按級距走，不提前**（超買/新高不是 harvest 理由）
2. **現金滯留了嗎？** 現金 % vs 既有 GTC 買單覆蓋 → 閒置 >15–20% 無計畫 → 🔴 flag
3. **盈餘該去哪？** L1 On-Deck + 信念桶中 revision 最陡的領漲者 1–2 檔 → 附進場結構（GTC 階梯 / bull put spread / bull call spread 貼高參與 / LEAPS）

```
### 🔄 飛輪檢查
Harvest：[標的 + 觸發依據 + 可掛單]（無則「本期無 harvest 觸發」）
現金：X%（✅ 有部署計畫 / 🔴 閒置）
Redeploy 首選：[標的 + revision 依據 + 結構]
配對狀態：每筆 harvest 已配對去處 or 標 dry powder + 觸發
```

---

## Phase 3: Deep（`/briefing deep` 時執行）

### 13. 平行 Agent 派遣

同時派出 3 組 Agent 子代理（全部 subagent_type: "data-collector"，自動使用 Sonnet 4.6）：

- **Agent 1 — SEC EDGAR**（subagent_type: "data-collector"，top 5）：`get_insider_transactions`（90d）+ `get_recent_filings`（30d）
- **Agent 2 — Yahoo Finance**（subagent_type: "data-collector"，top 5）：`get_stock_info` + `get_financial_statement` — 基本面摘要
- **Agent 3 — FMP**（subagent_type: "data-collector"）：`getStockPeers`（top 3）+ `getBiggestGainers` / `getBiggestLosers`

若 Agent tool 不可用，依序呼叫亦可。

### 14. 個股深度分析
對 Key Alerts 中標記異常的股票（跌>5%、虧>15%），執行 stock-analysis 級別的分析：
- 技術面詳細指標（BB、ATR、SMA）
- 基本面快照（PE、Revenue Growth、Margins）
- 內部人交易摘要
- 投資論點重新評估

### 14.5 Thesis 目標達成度 Scorecard

**目的：** 顯示「公司目標/thesis 有無達成」，讓用戶一眼看出哪些論點正在驗證、哪些可能破裂，**不 resolve**（只讀取、對照、標狀態）。

**資料來源：**
- `thesis_ledger.py list --status pending`（取得所有待驗收 thesis）
- Step 0.65 fundamentals-snapshot cache（quarterly_revenue_growth_yoy / quarterly_earnings_growth_yoy / pe_ratio 等）
- Step 0.6 earnings cache（beat rate, next_earnings date）

**Scorecard 邏輯（每筆 pending thesis 做一行）：**

對每筆 pending thesis，取其 `trigger.metric` 欄位（或從 thesis 命題推斷），與 fundamentals cache 的實際指標對照，判定當前狀態：

| 狀態 | 標記 | 條件 |
|------|------|------|
| 進行中 / 符合目標 | ✅ on-track | 核心指標與 thesis 方向一致（例：quarterly_revenue_growth_yoy > 0 且加速） |
| 待財報驗收 | ⏳ 待 event | trigger_type=event 且 trigger_date 尚未到（不能從 cache 判斷，等財報） |
| 有風險 / 指標轉弱 | ⚠️ at-risk | quarterly growth decel 連 2Q 或 guide 下修方向；技術面 death_cross；或 Step 0.55 `revision_delta` 該股 `decel_flag`（7d 上修動能縮減，影子驗證中）|
| 已接近證偽條件 | 🔴 warning | falsification 條件中有 1+ 個已出現（精確比對 thesis 列的證偽點） |
| 無法判定 | ❓ unknown | cache 缺相關指標，無法自動比對 |

**輸出格式：**
```
### 14.5 📋 Thesis 目標達成度
| ticker | thesis slug | 核心命題（摘要）| 到期/觸發 | cache 指標現況 | 狀態 |
|--------|------------|----------------|---------|--------------|------|
| MU | memory-cycle-asm | DRAM ASP持續上漲 + 毛利>40% | 2026-06-15 財報 | revenue growth +21% YoY；PE 40.8 | ⏳ 待 event |
| NVDA | datacenter-demand | DC revenue連4Q加速 | 2026-05-28 財報 | revenue growth +78% YoY | ✅ on-track |
| CIEN | margin-recovery | 毛利率50%以上連2Q | 2026-06-10 財報 | beat 1/8（⚠️最弱）| 🔴 warning |
```

**附加：thesis 到期日程（未來 30 天）**
```
📅 近期 thesis 到期：
  6/10 MU:memory-cycle（財報前） → 屆時需抓實際 ASP + 毛利率驗收
  6/15 AVGO:ai-revenue-accl（財報後） → AI revenue YoY + guide 驗收
```

**規則：**
- 本 section **只讀不寫**（不執行 `resolve` 或 `add`，那是 Step 0.7 的工作）
- 若 pending thesis 為空 → 輸出「📋 無待驗收 thesis（帳本為空或全已 resolve）」
- 每筆最多 1 行，不展開全文；詳細論點讓用戶自行查帳本

### 15. 完整計畫對照
portfolio-review 式的計畫執行進度表：
- 板塊佔比 vs 計畫目標的偏差分析
- 所有待辦項目的執行狀態
- 風險監控項目的當前狀態
- 下一步建議（基於計畫優先級 + 當前市場條件）

---

---

## Telegram Tier（`/briefing telegram`）

**目的：** 每日盤中推送至 Telegram + Email 的精簡決策摘要。不跑 Phase 1-3 的完整分析，只抓推送所需的 7 個資料點，直接產出 emoji 純文字格式。

### 執行模型
Sonnet 4.6（資料抓取為主，無深度合成需要）

### Step 0
同標準規範（0a-0e）：讀 `plan.md` + `feedback/*.md` → `get_account_position` → journal 確認。

### 資料步驟（依序，可部分並行）

**T1. Earnings Window（next 7 days）**
**改從 cache 讀：** Step 0.6 已預載 `briefing-out/cache/earnings-dates.json` + `earnings-history.json`，直接 Read 兩份 JSON。
列出所有持倉 ticker 的：
- 財報日 + 盤前/盤後（`next_date`, `timing`）
- 過去 ±48h 已發財報的 ticker 也標出
- **Trailing 8Q beat rate + avg surprise %**（從 `earnings-history.json`）
- focus 重點：可從 yfinance news / sentiment 摘要推斷
- **Cross-read 子行**：該 ticker 為 Step 0.55 active 鏈 leader → 行下加 `  ↳ read-through: {followers（≤4 檔）}`（全訊息至多 1 行）

若 cache `status` ≠ `"ok"` → fallback `mcp__fmp-mcp__getEarningsCalendar`，並加註 `⚠️ earnings cache unavailable`。

**T2. Sentiment Pulse + Fundamentals Cache 預讀（平行 Agent）**
派出 data-collector subagent，取所有持倉的 EODHD 7d sentiment_trend（格式：TICKER.US）：
```
Agent(subagent_type="data-collector"):
  呼叫 mcp__eodhd-mcp__get_sentiment_trend 對每個 ticker
  回傳 dict: {ticker: {score: float, trend: str}}
```
分類：score 7日變動 > +0.1 → 改善；< -0.1 → 轉弱；急降（從 > +0.3 → < +0.1）→ ⚠️ 注意

**同時讀取（不額外 MCP round-trip）：**
`briefing-out/cache/fundamentals-snapshot.json`（Step 0.65 已預載）→ 供下方 T2.5 💰 計算

**T2.5 💰 估值 & Thesis Pulse（cache 算，signal-only）**

資料：fundamentals-snapshot.json + Step 0.7 resolve 結果

計算邏輯（同 Section 8.5 三錨點精簡版）：
1. 對所有 ≥3% 持倉，算各自 `現價/基準公允價` 比值（基準公允 = median錨 × fwdEPS）
2. 最被低估 = ratio 最低者（ratio < 0.90 才顯示，否則「無明顯低估」）
3. 最被高估 = ratio 最高者（ratio > 1.10 才顯示）
4. 今日 thesis 影響 = Step 0.7 resolve 結果（若有）

**省略整段的條件（全部滿足則 T8a/T8b 不輸出此段）：**
- fundamentals cache status ≠ "ok"，OR
- 無任何持倉的 `|現價/公允基 − 1|` > 10%，AND
- 今日 Step 0.7 無 resolve（無新 verdict）

→ signal-only：無訊號不推送（比照現有「無 alert 則略過整個 section」慣例）

**T3. News & Catalysts（past 24h）**
`mcp__yfinance-advanced__get_yahoo_finance_news` 取 top 5 持倉的新聞，各取 1-2 篇 24h 內最重要的。篩選標準：有具體事件（財報、合約、產品發布、監管）優先，無實質 catalyst 跳過。**最多 3 條進入 Telegram 輸出。**

**T4. Sector Rotation**
`mcp__technical-mcp__get_sector_rotation()` → 取全 sector ETF 相對 SPY 的 leading / improving / weakening / lagging 分類。只顯示各分類各 1-2 個代表 sector。

**T5. Alerts（閾值觸發）**
根據 T1 + T2 + Step 0b 持倉數據生成 alerts（無則跳過整個 section）：
- Earnings window ±48h 的 ticker → 標記「技術訊號暫停」
- Sentiment 急降（T2 注意類）→ 標記「情緒惡化」
- 任一持倉距 52w 低點 < 5%（需 `get_stock_info`）→ 標記「逼近 52w 低」
- plan.md 中有明確 stop-loss 且接近觸發的 ticker
- Step 0.55 🚦 旗標（credit `widening_fast` / VIX 期限 `inverted` / 寬度 `divergence_flag` / 台股月營收 `turned_negative` / `book_decel`）→ 每項 1 行前綴 🚦（無則不出，display-only）

**T6. 今日 / 明日待辦**
從 `plan.md` 的策略佇列 + 觀察清單（⏳ 待評估）+ Step 0e 第一性分析，生成：
- **今日待辦**：有明確觸發條件且條件「已接近或已達」的項目（最多 3 條）
- **明日待辦**：即將到來的 catalyst（財報 next day、FOMC、plan.md 明天到期的條件）（最多 3 條）
- 過濾純 HOLD-only、無 actionable 的項目
- 每條格式：`• {action}（{trigger / catalyst}）`

**T7. Quick Take（第一性）**
一小段人話（3-5 句，per `feedback/briefing-voice-style.md`），情緒/敘事走向。不講 RSI/MACD。內容不變：
- 今日整體 sentiment 方向（用 T2 + T4 支撐）
- 本週重點 / 核心注意事項
- 收尾帶一句「明天看什麼」（游庭皓式 wrap-up）

---

### 檔案輸出（每次執行均寫出，無論有無 --send）

**T8a. 完整 Markdown → `briefing-out/YYYY-MM-DD-full.md`**

使用 Write tool 寫入。**敘事段落全部走 `feedback/briefing-voice-style.md` 口吻**（section 骨架與數據點照下方模板一項不漏；開場加 2-4 句 big picture 導言、每區內容寫成完整句子帶解讀）。格式：
```markdown
# Briefing Telegram YYYY-MM-DD

## Earnings Window
...

## Sentiment Pulse
...

## 🚦 Leading Indicators
- 儀表: HY {Δ5d:+}bp/5d ({flag}) | VIX期限 {ratio} ({flag}) | 半導體寬度 {pct}%>50DMA ({flag})
- Cross-read: {active 鏈：leader（日期/狀態）→ followers}（無 active 鏈則省略）
- Pricing: {memory/power 最重要 1-2 條 — "{excerpt 節錄}" ({source})}（無 hit 則省略）
- 台股月營收: {名 YoY ±X%…}（僅 is_new_month 或有 flag 時列出）
- Revision Δ: 寬度 {breadth_pos_pct}%（7d {±X}pp）{；🟠 decel: T1, T2}（warming_up → ⏳ warming up (archive {N}d)）

## News & Catalysts
...

## 💰 估值 & Thesis（signal-only，無訊號則省略整段）
### 估值偏離
- 最被低估：{ticker} 現價 $X vs 公允基準 $X（−X%，三錨點中位）；A1 PE={X}/A2 PEG錨={X}/A3 PT錨={X}
- 最被高估：{ticker} 現價 $X vs 公允基準 $X（+X%）
（|偏離| < 10% 則省略該行）

### 今日 Thesis 驗收影響
- {ticker}:{slug} → {verdict} | 公允價 $FV_before → $FV_after（±X%） | 影響：{impact_decomp}
（無今日 resolve 則省略此小節）

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

📅 Earnings This Week
  • {ticker} {M/D} {盤前/盤後} ({beat_count}/{total} beat, +{avg_surprise}%) — {focus 重點}
  ↳ read-through: {followers}（僅當該 ticker 為 active 鏈 leader；全訊息至多 1 行）
  （Trailing beat rate 從 earnings-history.json 讀；cache 缺則省略括弧）

🚦 先行指標
  HY {+X}bp/5d | VIX期限 {ratio} | 寬度 {pct}% | 記憶體 {n}則 | 台股 {摘要或—}
  ⚠️ {觸發中的 regime-break / 台股轉負 / book_decel，合併一行}（無觸發則省略此行）

📊 Sentiment Pulse (EODHD 7d)
  📈 改善: {ticker} +{delta}, {ticker} +{delta}
  📉 轉弱: {ticker} -{delta}
  ⚠️ 注意: {ticker} {一句說明}
  （無變化的 ticker 不列出）

💰 估值 & Thesis
  📉 最低估: {ticker} vs 公允價 −X%（三錨點中位）
  📈 最高估: {ticker} vs 公允價 +X%
  📋 今日 thesis: {ticker} {verdict} 公允價 $FV_before→$FV_after（±X%）
  （整段省略條件：無 >10% 偏離 且 今日無 thesis resolve）

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
- **口吻（2026-07-28 起）**：每區 1-3 句**完整句子**取代電報碎片，同區數據點全保留（`feedback/briefing-voice-style.md` 內容不變定律 + before/after 範例）；先講結論、數字帶解讀
- 數字：K（千）、M（百萬）、% 縮寫
- 無 catalyst 或無 alert 的 section 完整省略（不要顯示空 section）
- 🚦 先行指標區儀表行維持緊湊 1 行（數據面板不句子化），觸發說明行用人話；`↳ read-through` 全訊息至多 1 行
- 目標長度 **≤3000 字元**（2026-07-28 用戶放寬，換可讀性），硬上限 4096（超過由 send_briefing 自動分則）
- `briefing-out/` 目錄不存在時先用 Bash `mkdir -p briefing-out` 建立

---

### HTML 生成 + Tier 標記（所有 tier 共用）

寫完 `briefing-out/YYYY-MM-DD-full.md` 後，**先寫 tier 標記**再生成 HTML：

```bash
# 1. 寫 tier 標記（讓 generate_html.py 知道這次是哪個 tier）
echo "<tier>" > briefing-out/YYYY-MM-DD-tier.txt
# <tier> 填入：quick | telegram | full | deep

# 2. 生成 HTML + push（tier gate 自動判斷：只有升級才推）
python3 tools/generate_html.py briefing YYYY-MM-DD --push
# 成功時印出網頁連結；若網站已有更高 tier 則跳過 push（本地 HTML 仍更新）
```

**Tier 升級規則：** `quick(1) < telegram(2) < full(3) < deep(4)`
- 網站有 telegram + 跑 deep → **push**（升級）
- 網站有 deep + 跑 telegram → **不 push**（降級，保留深版；本地留一份）
- 同級 → push（覆蓋更新）

### --send 旗標處理

寫完兩個檔案後，若 arguments 含 `--send`：

```bash
python3 tools/send_briefing.py YYYY-MM-DD
```

`send_briefing.py` 會自動：
1. 呼叫 `tools/generate_html.py briefing YYYY-MM-DD --push`（best-effort，失敗不擋發送）
2. HTML push 成功 → Telegram 訊息末自動附加「🔗 網頁版：...」連結
3. 發送 Telegram + Email

成功時輸出「✅ Telegram 已發送 / Email 已寄出」，失敗時輸出錯誤訊息（sender 自帶 retry + error notification）。

---

## Phase 4: Codex 第二意見（opt-in — 僅 `full` 或 `deep` 層）

**僅當 arguments 含 `--codex` 或 `--2nd` 時執行。Quick 層完全跳過本 Phase。**

三個子 block 依序執行（可並行派 Agent）：

---

### B1. 獨立第一性分析（預設，independent first-principles）

**核心原則：Codex 不看 Claude 的 Phase 1–3 結論**（不給 Quick Take / Key Alerts / 建議），只給 raw 持倉變動 + 市場數據，讓它獨立評估今日 priorities。Claude 與 Codex 兩個獨立輸出並排比較。

**🔴 Prompt 中性化要求**（詳見 `feedback/codex-prompt-neutrality.md`）：

raw data 區只能放 fact 數值，**不能放** derived label：

| ❌ 不能寫 | ✅ 改寫為 |
|----------|----------|
| `MU strong_uptrend / 49 / 量縮` | `MU $635.80 (+10.30%) / RSI 81.7 / vol_ratio 0.49 / 6w range $XXX-$XXX` |
| `PLTR weak_downtrend / momentum -24` | `PLTR $138.30 (-5.29%) / RSI 46.2 / 6w range $122-$146 / Q1 earnings 5/4（昨日）` |
| `BE 拋物線警示` | `BE $291 (+0.9%) / RSI 77.6 / 5d 區間 $275-$303` |

**禁止的 label：** strong_uptrend / weak_downtrend / consolidation / overbought / oversold / 拋物線 / 打底 / 弱勢持續 / 強勢確認 / momentum_score（這已是 -100~+100 derived score，改寫成「X 個交易日累計漲跌 X%」）。

讓 Codex 自己跑 indicator interpretation，從 raw 數值推導結論。

呼叫 Codex（**用 CLAUDE.md「Codex 呼叫方式」的 `codex exec` CLI；勿用 codex:codex-rescue subagent / `/codex:rescue`，會卡 superpowers preamble**），prompt 首行加強制 no-tool 指令，模板：

```
我是一名美股投資人，使用 Level 2 options + Spread 的 margin 帳戶。
請對今日 briefing，**完全獨立**評估 — 不要看任何先前結論。

**Raw data（只給 fact 數值，無 derived label）：**

帳戶：總值 $XXX / 現金 $XXX / 今日帳戶變動 +X.XX%

**今日 movers（價格 + % + 量能比 + 6 週區間）：**
- [ticker] $XXX (+/-X.XX%) / RSI XX.X / vol_ratio X.XX / 6w range $XXX-$XXX
- ...

**Earnings Window 標記（過去/未來 48h 有財報的 ticker）：**
- [ticker] — 財報日 X/X（[已過 X 天 / 還剩 X 天]）

**主要持倉技術面（fact only）：**
- [ticker]：價 $XXX / RSI XX / MACD line/signal/histogram / vs SMA20 X% / vs SMA50 X%
- ...

**板塊輪動（vs SPY 3mo，純數值）：**
- SMH +X.XX% / 1w +X.XX% / RSI XX.X
- ...

**待執行/觀察的計畫項目**（從 plan.md 摘出 ⏳，不寫評語）：
- ...

**近期重大事件（fact）：** 財報日列表、FOMC、產業催化

**投資風格：** AI/半導體主軸、汰弱留強、信念持倉 [TSLA/MU/AVGO]

**請輸出（獨立判斷）：**

1. **今日組合 thesis**（1 句：今日是「進攻」「防守」「觀望」？理由？）

2. **3 個今日最重要的訊號**（具體 — 自己解讀 raw data，不依賴 Claude 標籤）

3. **未來 5 個交易日機率分布（組合表現）：**

   | 情境 | 機率 | 條件 | 預期 % |
   |------|------|------|--------|
   | 樂觀 | XX% | [...] | +X% |
   | 基準 | XX% | [...] | ±X% |
   | 悲觀 | XX% | [...] | -X% |

4. **3 個 actionable 建議**（含口數 / 觸發條件）— 對 earnings window 內的 ticker 預設「等 settle」

5. **Verdict**（1 句）：今日整體該做什麼？

**規則：**
- 機率分布必須 sum 到 100%
- 不假設 Claude 已說過什麼
- 保持獨立判斷
- earnings window 內的 ticker 不直接套「汰弱留強」

請以繁體中文回覆，控制在 700 字內。

--effort high --fresh
```

---

### B2. 機會掃描（opportunity scout）

呼叫 Codex（用 CLAUDE.md「Codex 呼叫方式」的 `codex exec` CLI）：

```
我目前的美股持倉（含市值占比）：
[插入 Step 0b get_account_position 取得的持倉表]

我的投資風格：
- 主軸：AI/半導體、高成長科技；汰弱留強，集中持倉
- 信念持倉（不換）：TSLA, MU, AVGO 多年期 thesis
- 板塊偏好：[從 plan.md 摘出 3-5 行板塊目標]

請以獨立分析師視角：
1. 掃描今日市場有哪些當紅題材/個股，是我目前持倉沒覆蓋到的
2. 對每個候選列出：題材、代表 ticker、為何此刻有機會、建議切入方式（現股/Spread/LEAPS）
3. 要追這些新機會，最該砍掉哪一檔現有持倉？為什麼？
4. 提供 2-3 個具體 actionable 建議（含目標 entry zone）

請以繁體中文回覆。輸出限 600 字。
```

---

### B3. 輪動分析（rotation scan）

**Step 1 — Claude 預先收集數據：**
- `mcp__technical-mcp__get_sector_rotation()` → 全板塊 ETF 相對強度 vs SPY（leading / improving / weakening / lagging）
- `mcp__technical-mcp__get_batch_indicators(tickers=[所有持倉])` → 個股動能分數 + 趨勢

**Step 2 — 呼叫 Codex（用 CLAUDE.md「Codex 呼叫方式」的 `codex exec` CLI）：**

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

#### 並排比較：Claude vs Codex（獨立輸出）

| 維度 | Claude | Codex | 一致性 |
|------|--------|-------|--------|
| 今日 thesis | [Claude] | [Codex] | 同 / 異 |
| 機率分布偏向 | 偏多 / 中性 / 偏空 | 偏多 / 中性 / 偏空 | — |
| 主要建議 | [Claude] | [Codex] | 同 / 異 |
| Verdict | [Claude] | [Codex] | 同 / 異 |

**真實共識：** [1-2 條]
**真實分歧：** [1-3 條]

### 機會掃描（vs 現有持倉）
[B2 Codex 完整回覆]

### 輪動分析（板塊 + 個股）
[B3 Codex 完整回覆]

---
**值得追蹤的新機會：** [從 B2 挑 1-2 個 Claude 也認同的]
**輪動 actionable：** [從 B3 挑 1-2 條 Claude 也認同的調倉操作]
```

### 進階：`--codex-adversarial`（opt-in 壓力測試）

僅當 arguments 含 `--codex-adversarial` 時，**追加**對立面審查段落（攻擊 Claude 結論、找 bug）。預設 `--codex` 不執行。

> 若 Codex 失敗 → 輸出 `⚠️ Codex 不可用：[error]，跳過第二意見`，繼續正常輸出。

---

## Output Format
- 繁體中文
- **口吻（2026-07-28 起強制）**：所有敘事文字走「懂行朋友講盤」體，規範見 `feedback/briefing-voice-style.md`（股癌式直白 + 游庭皓式晨報導讀）。**鐵則：內容不變定律** — 每個 section/數字/旗標/待辦一項不漏，只改「怎麼說」；先講結論、數字帶解讀不裸列、術語首次給白話；開場 2-4 句 big picture、結尾一小段「明天看什麼」。機率/EV/旗標的數據結構照舊，禁止用語氣詞替代機率
- **禁裸參數名**：`curr_fy`、`decel_flag`、`pct_above_50dma` 這類內部欄位名不得直接出現在報告文字，一律翻完整名稱（本財年、上修減速旗標、站上 50 日線比例…完整對照表見 `feedback/briefing-voice-style.md` 規則 4b）；溯源需要時才括號附欄位名。市場慣用英文（EPS/PE/capex/guide/beat/IV/DTE/delta）不受限
- 簡潔 markdown 表格（表格是內容不是口吻，保留）
- 所有金額為 USD
- Quick 版應在一個畫面內完成
- Full/Deep 版可較長但需結構清晰
- **Telegram Tier**：對話輸出一份簡要摘要（確認執行完畢）；真正的輸出在 `briefing-out/` 的兩個檔案

## briefing-out/ 目錄
- `briefing-out/` 已加入 `.gitignore`（個人化數據，不 commit）
- 每日執行會覆蓋同日期的檔案（不保留版本）
- 手動重發：`python3 tools/send_briefing.py YYYY-MM-DD` 或 `python3 tools/send_briefing.py latest`
