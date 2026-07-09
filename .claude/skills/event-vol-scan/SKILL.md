---
name: event-vol-scan
description: 財報/重大事件（CPI/FOMC）前的末日 buy call 與雙買 straddle 機會掃描。Usage - /event-vol-scan [days] [TICKER ...]（預設窗 14 天，掃持倉 + L1 候補 + SPY/QQQ 宏觀事件）
user_invocable: true
model: claude-opus-4-8
---

# Event Vol Scan — 事件前買方機會掃描

> 定位：把 portfolio-review I.5 樂透掃描升級為**事件驅動買方**掃描 — 在財報 / CPI / FOMC 前找兩類機會：
> **① 末日 buy call**（方向凸性：base rate + revision 一面倒，且隱含移動不貴）
> **② 雙買 straddle**（純波動：隱含移動 < 歷史實際移動，不賭方向賭幅度）

## 與既有規則的關係（必讀）

- **「財報 ±48h 不新開期權倉」（options-leaps-playbook）的例外聲明**：那條禁的是「方向性建倉被事件 IV 扭曲定價而不自知」。本 skill 是**有意識的事件波動買方**（吃 gamma / vol），屬明確 opt-in 例外。**賣方策略（BPS/BCS/CC）仍完全遵守 ±48h 禁令，本 skill 絕不輸出事件窗內的賣方單。**
- 沿用樂透鐵則（playbook + I.5）：總成本 ≤ **2% 帳戶**（Quarter-Kelly）、OI > 500、已漲 >30%（5日）排除、**不用 OTM LEAPS 當樂透**（vega 干擾凸性）。
- 機率語言紀律：不寫「應該會大漲」— 引擎輸出 VRP（隱含/歷史）與 base rate，判讀 conditional 在這兩個數字。

## Step 0

執行 CLAUDE.md Step 0 統一規範（0a 讀 plan.md + feedback、0b `get_account_position`、0c/0d journal 檢查）。本 skill 需要：持倉 ticker 清單、帳戶總值（算 2% 預算）、plan.md L1 On-Deck / 觀察清單。

## Workflow

### 1. Universe 組建

- **預設**：持倉全部 ticker + plan.md「L1 On-Deck」+「觀察清單」標的
- 用戶 args 指定 ticker → 只掃指定的
- **宏觀事件**：`mcp__eodhd-mcp__get_economic_calendar(from, to, country="US", high_impact_only=True)` 抓窗內 CPI / FOMC / NFP 日期 → 以 `SPY:<date>:<label>,QQQ:<date>:<label>` 注入（半導體集中事件可加 SMH）

### 2. 跑掃描引擎（機械層 — 不手算 chain）

```bash
python3 tools/event_vol_scan.py \
  --tickers <逗號清單> \
  --days <N，預設 14> \
  --extra-events "SPY:YYYY-MM-DD:CPI,QQQ:YYYY-MM-DD:FOMC" \
  --account-value <live 帳戶總值> \
  --json briefing-out/cache/event-vol-scan.json
```

引擎輸出（每 ticker×事件）：事件後首個到期、ATM straddle 隱含移動、過去 8Q 財報實際移動中位（earnings-history cache 日期 × 日線）、**VRP = 隱含/歷史**、beat rate + 30d revisions、5 日 run-up、OI/spread 流動性、1×IM 末日 call 候選報價，以及機械裁決：

| 裁決 | 條件 | 意義 |
|------|------|------|
| `BUY_CALL` | beat ≥ 7/8 且 rev up ≥ 5×dn 且 avg surprise ≥ +5%（非 unreliable）且 VRP ≤ 1.2 | 方向凸性候選 |
| `STRADDLE` | VRP < 0.85 且歷史中位移動 ≥ 4% | 雙買候選（隱含 < 歷史） |
| `STRADDLE_RV` | 無財報基準（ETF/新股），隱含 < 20d 實現波動×√T | 雙買候選（次級基準） |
| `SKIP_RICH` | VRP > 1.2 | 隱含太貴，IV crush 風險 |
| `EXCLUDE` | 5日漲幅 >30% 或 OI/spread 不及格 | 淘汰 |
| `WATCH` | 無明確 edge | 列示不建議 |

### 3. 判斷層（Claude — 引擎裁決之上，逐條檢核）

1. **`STRADDLE_RV` 的 rv 灌水檢查**：近 5 日若有 >3% 單日（崩盤週），rv20 被灌高 → VRP_rv 失真偏便宜。此時降級為 WATCH，除非隱含移動絕對值也低於長期常態。
2. **`BUY_CALL` 的 thesis 一致性**：對照 plan.md 桶別 / 候補層 — 與現有持倉**同題材 binary 不重複開**（已有同板塊事件樂透 → 優先補強既有）。
3. **末日進場時點**（重要 — 掃描日 ≠ 進場日）：
   - 雙買：**事件前 2–5 個交易日**進場（IV ramp 前段，theta 尚可控）
   - 純末日 call：**事件前 1 日或當日**（最大 gamma，premium = max loss 心態）
   - 今天距事件 >5 日 → 輸出「價格警報 + 預定結構」，不是現在就買（複式單無法 GTC）
4. **口數與預算**：總樂透預算 ≤2% 帳戶（引擎已算出金額）；單筆 1-2 口；每筆必寫「上行 +XXX% / max loss = premium $X」。
5. **出場紀律（開倉時就寫死）**：
   - 雙買：**事件後首個交易日內了結**（IV crush 前），不留倉「等第二波」
   - 末日 call：+100% 賣半回本（house-money runner），事件後歸零風險自負
6. 入選 0 筆 → 誠實輸出「⏳ 本次無符合凸性條件的事件買方機會」+ 最接近門檻的 1-2 筆與差多少。

### 4. 輸出格式

```
## 🎯 事件前買方掃描（YYYY-MM-DD，窗 N 天）
[引擎 markdown 表原樣]

### 入選（≤3 筆）
| # | 標的 | 事件 | 結構 | 成本/口 | max loss | 上行情境 | 進場窗 | 出場紀律 |
每筆附：價格警報價位 + 預定結構（觸發後 2 分鐘執行）；或當下可掛的單。

### 判斷層淘汰說明
[哪些引擎候選被判斷層砍掉、為什麼 — 1 行/筆]
```

### 5. 落地（executed only）

- 用戶決定執行 → `thesis_ledger.py add`（slug 格式 `<ticker>:event-vol-<label>-<YYYYMM>`，trigger = 事件日，證偽 = 移動 < 隱含成本）
- 本 skill 預設不存 HTML 報告；用戶要求時走 `generate_html.py`（type: options-strategy）

## 常數（調整處 = tools/event_vol_scan.py 頂部）

RUNUP_EXCLUDE 30% / VRP_CHEAP 0.85 / VRP_RICH 1.20 / MIN_OI 500 / MAX_SPREAD 15% / 預算 2% / BUY_CALL 門檻 beat 87.5% + surprise ≥5%（unreliable 不算）+ rev 5:1。

## Performance

引擎 ~5-8 秒/ticker（yfinance 鏈 + 2y 歷史）。10 檔 Universe 約 1 分鐘。盤中執行前記得引擎報價是快照 — 下單前用 `get_single_quote` 補即時價。
