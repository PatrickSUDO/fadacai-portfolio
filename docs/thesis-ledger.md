# Thesis Ledger — 投資論點追蹤與到期驗收

第一性檢查產出的可驗證 thesis 不該寫完就忘。Thesis Ledger 把每個帶**明確時間/事件觸發點**的論點登錄下來，到期自動回頭抓實際數字驗收（過關 / 破裂 / 部分），驗收結果直接驅動下一步 actionable，並累積歷史命中率。

- **帳本**：`research/thesis-ledger.json`
- **工具**：`tools/thesis_ledger.py`（純 stdlib，零外部相依）
- **測試**：`tools/test_thesis_ledger.py`（`python3 -m unittest test_thesis_ledger`）

## 設計原則

凡屬 **deterministic** 的邏輯——去重、碰撞攔截、到期偵測、過期掃描、狀態轉換、日期算術、schema 驗證、JSON 讀寫——全部在 Python 工具裡，**Claude 不手改 JSON**。Claude 只負責需要推理的部分：「拿到實際數字後，thesis 有沒有過關」。

## 資料模型

```jsonc
{
  "id": "3661:memory-cycle",        // 去重 key = ticker:slug
  "ticker": "3661",                  // 個股 / "MARKET"(市場題材) / "PORTFOLIO"
  "slug": "memory-cycle",
  "thesis": "DRAM 進入漲價週期，FY26 毛利率 > 40%",  // 1 句可驗證命題
  "falsification": ["次季 ASP 不再漲", "HBM3E 指引下修>10%"],  // 證偽觀察點
  "trigger": {
    "type": "event",              // "date" 或 "event"
    "date": "2026-06-25",          // date型=絕對日；event型=預期財報日
    "event": "earnings",           // event型才有
    "metric": "DRAM ASP QoQ + 毛利率 vs 40%"  // 到期要抓來比的東西
  },
  "status": "pending",            // 見下方狀態表
  "source": "briefing",           // briefing / portfolio-review
  "created": "2026-05-31",
  "updated": "2026-05-31",
  "ev_snapshot": "+1.0% (7d)",    // 登錄當下的 EV（選填，事後回顧）
  "aliases": ["dram-pricing"],    // merge 後的舊 slug，redirect 用
  "superseded_by": null,          // 被 supersede 取代時指向新 id
  "history": [                     // 每次驗收 append，不覆蓋
    {"date": "2026-06-26", "verdict": "passed",
     "actual": "ASP +8% QoQ，毛利率 42%", "note": "右峰兌現",
     "next_action": "HOLD，加碼門檻 $XXX"}
  ]
}
```

### 狀態

| status | 意義 | 計入命中率? |
|--------|------|:-----------:|
| `pending` | 待驗收 | — |
| `passed` | thesis 過關 | ✅ 分子+分母 |
| `failed` | thesis 破裂 | 分母 |
| `partial` | 部分成立 | 另計（不灌水命中率）|
| `expired` | 逾期 >30 天未驗收，當作無結果 | ❌（只進 follow-through 分母）|
| `stale` | 手動歸檔（thesis 已不相關）| ❌ |
| `superseded` | 被新論點取代 | ❌ |

## 去重機制

key = `ticker:slug`。`add` 時：

1. **key 不存在** → insert
2. **key 存在、新 thesis 文字相似度 ≥ 0.3**（char-trigram Jaccard）→ 視為同論點演進，**update**（刷新 trigger / falsification / EV）
3. **key 存在、相似度 < 0.3** → **碰撞**：拒絕寫入，回傳既有 thesis，**exit code 2**。Claude 必須二選一：取區隔 slug，或確定舊論點被推翻 → `supersede`
4. 登錄前先 `list --ticker <T>` 看既有 slug，降低 slug 飄移

事後若不慎開了兩筆同義 thesis → `merge` 合併（history 併入、舊 slug 留 alias 墓碑，之後用舊 slug `add` 會 redirect）。

## CLI 速查

```bash
# 登錄/更新（upsert by ticker:slug）
python3 tools/thesis_ledger.py add --ticker 3661 --slug memory-cycle \
  --thesis "DRAM 漲價毛利率>40%" --falsification "ASP 不再漲" "HBM 指引下修" \
  --trigger-type event --trigger-date 2026-06-25 --event earnings \
  --metric "ASP QoQ + 毛利率" --source briefing --ev "+1.0% (7d)"

python3 tools/thesis_ledger.py list [--ticker 3661] [--status pending]
python3 tools/thesis_ledger.py due [--asof YYYY-MM-DD] [--expire-after-days 30]
python3 tools/thesis_ledger.py resolve --id 3661:memory-cycle --verdict passed|failed|partial \
  --actual "..." --note "..." --next-action "..."
python3 tools/thesis_ledger.py reschedule --id 3661:memory-cycle --to YYYY-MM-DD --reason "財報未出"
python3 tools/thesis_ledger.py merge --from 3661:dram-pricing --into 3661:memory-cycle
python3 tools/thesis_ledger.py supersede --id 3661:memory-cycle --new-slug hbm-capacity \
  --thesis "..." --falsification "..." --trigger-type date --trigger-date YYYY-MM-DD
python3 tools/thesis_ledger.py stats [--ticker 3661] [--source briefing] [--since YYYY-MM-DD]
```

### 退出碼

| code | 意義 |
|:----:|------|
| 0 | 成功 |
| 2 | 碰撞（同 slug 不同 thesis）— 改 slug 或 supersede |
| 3 | 找不到 id |
| 1 | 用法/其他錯誤 |

`--asof` 讓所有日期邏輯可固定（測試用），預設 `date.today()`。

## skill 整合

- **briefing**：`Step 0.7` 驗收（`due` → 抓數 → `resolve`）+ 收尾登錄（`list` → `add`）
- **portfolio-review**：`Step 0.6` 驗收 + 收尾登錄
- 兩者共用同一帳本與工具；briefing 是保證每日的驗收引擎

## Source 分類 + `signal-inference` 慣例

`--source` 欄位記錄 thesis 來自哪個 skill / 流程：

| source | 說明 |
|--------|------|
| `briefing` | 由每日 briefing skill 登錄（Section 8 / Step 0.7） |
| `portfolio-review` | 由組合審查登錄（Step 0.6） |
| `stock-analysis` | 由個股深度分析登錄（Step 4a writer） |
| `signal-inference` | **由訊號推導登錄**（news body / 重大訊息 / 逐字稿量化信號 → thesis 轉換） |

### `signal-inference` 流程 + 反幻覺規則

這是 P3 新增的來源，用於從高頻資料（新聞全文、重訊、逐字稿）推導 thesis 候選，補上財報間隙的訊號。

**必要欄位：**
- `--source signal-inference`
- `--ev "signal: <metric> <value>, <source>, conf=<confidence>"` — 暫存訊號來源 provenance
  - 例：`--ev "signal: wafer_starts +8% QoQ, Reuters/FinMind 2026-06-04, conf=medium"`

**反幻覺鎖（不可繞過）：**
- 每個訊號必須有 `raw_quote`（≤120 字逐字原文引用）存在**源文件**中，才成立
- 無 raw_quote → 無 signal → 不登錄（在 briefing/stock-analysis 文字呈現即可）
- 僅 `confidence ∈ {high, medium}` 且有明確前瞻 trigger 才登錄；`low` 不登錄

**Signal → Thesis 轉換模板：**
```
SIGNAL: {ticker} {metric} {value} ({direction})
  來源: {source_url/desc}, source_type={sec_8k|transcript|news}, 日期={date}
  confidence: {high|medium|low}
  raw_quote: "<逐字 ≤120字>"

→ THESIS (1句可驗證命題):
  "{ticker} {metric} {value} 預示 {forward_condition}"

→ FALSIFY (2-3個):
  1. "{量化觀察點}"
  2. "{量化觀察點}"
  3. "{量化觀察點}"（選填）

→ TRIGGER: type=event|date, date=YYYY-MM-DD, metric="{到期要比的指標}"
```

**CLI 範例（signal-inference 登錄）：**
```bash
# 先查既有 slug 避免碰撞
python3 tools/thesis_ledger.py list --ticker 3661

python3 tools/thesis_ledger.py add --ticker 3661 --slug wafer-starts-bit-growth \
  --thesis "3661 世芯-KW 投片量 +8% QoQ 預示 FY27 bit 出貨 YoY >25% 且 DRAM ASP 不跌破 -5% QoQ" \
  --falsification "下季 bit shipment YoY <25%" "DRAM ASP QoQ <-5%" "guide 下修 >10%" \
  --trigger-type event --trigger-date 2026-09-25 --event earnings \
  --metric "bit shipment YoY + DRAM ASP QoQ" \
  --source signal-inference \
  --ev "signal: wafer_starts +8% QoQ, Reuters/FinMind 2026-06-04, conf=medium"
```

**命中率追蹤（閉環驗證 P3 是否真有價值）：**
```bash
# 查 signal-inference 來源的所有 thesis + 命中率
python3 tools/thesis_ledger.py stats --source signal-inference

# 查特定 ticker 的 signal-inference thesis
python3 tools/thesis_ledger.py list --ticker 3661 --status pending
```

## 驗收流程（Claude 端）

1. `due` 取今日到期清單（工具同時自動把逾期 >30 天的轉 `expired`）
2. 每筆讀 `trigger.metric` → 用 MCP（FinMind / earnings cache / technical）抓**實際數字**
3. 對照 `thesis` + `falsification` 判 `passed` / `failed` / `partial`
4. 抓不到新數（財報還沒出）→ `reschedule` 維持 pending，**絕不猜 verdict**
5. `resolve --next-action` 寫下一步操作 → 併入日報 actionable
