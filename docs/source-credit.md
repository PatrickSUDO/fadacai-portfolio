# 來源信用系統 — X/Substack/RSS 早期資訊層 + 每來源信用帳

見報的消息多半已 price-in；少數供應鏈記者/分析師/KOL 的貼文有數小時到數週的 lead time。但「小道消息」本身不可驗證，與本系統既有的證據紀律（`raw_quote` 閘門、影子驗證、命中率帳本）相衝。

解法：把「來源」本身當成一個要驗證的資訊層——每則可計分主張入帳、到期機械驗、來源按命中率自動升降級，**驗滿 ≥2 期 `/trade-review` 前 display-only**（同 A4 自建錨影子 / R18 財報窗 / 先行指標三者的既有紀律）。

- **私有帳本**：`research/source-config.json`（來源白名單+配置）、`research/source-credit.jsonl`（每則主張的登錄與驗收）— 整個 `research/` 已 gitignore，個人選號（信哪個帳號）不入庫
- **公開範例**：`docs/source-config.example.json`（同 schema，只放 2 個佔位來源，不放真實選號）
- **工具**：`tools/source_credit.py`（帳本 CLI，純 stdlib）、`tools/fetch_twitter.py`（X API v2 抓取，`requests`）
- **測試**：`tools/test_source_credit.py`

## 動機與紀律

1. **來源無關**：X/Substack/RSS/podcast 皆可登錄，機制不綁死平台
2. **官方 X API 按量計費**：讀取有成本，抓取閘門必須有預算上限（見下方「X API 成本」）
3. **Tier 完全機械化**：`probation` → `trusted` → `core` 的升降由 `source_credit.py tiers` 依命中率算出，**Claude 不得手動升降**
4. **Display-only，直到跑滿 ≥2 期 `/trade-review`**：任何 tier 的來源訊號都不得單獨改變 Verdict / 加減碼建議，只作背景與記錄（同 CLAUDE.md 0e 對 A4 自建錨、R18、先行指標旗標的既有紀律）
5. **引用即 add-claim**：凡在任何 skill 輸出中引用某則貼文的主張支持判斷，同一次必須 `add-claim` 登錄，否則不算已驗證過的引用（同旗標紀律「講了要記」）
6. **KOL（view 型來源）用價格計分，無標的者只當背景**：例如財經 podcast/YouTuber 在節目中明確點名標的+方向時可登 `view` claim；若只談總經敘事、不點名標的（`--tickers none`），該筆 `unscorable`，只能作背景，不計分

## 架構

```
research/source-config.json     ← 私有：來源白名單 + X 抓取配置 + 計分門檻（gitignore）
research/source-credit.jsonl    ← 私有：每則主張的登錄與驗收記錄（gitignore）
docs/source-config.example.json ← 公開：schema 範例，只放 2 個佔位來源

tools/source_credit.py          ← 帳本 CLI：add-source / add-claim / due / resolve / resolve-due / stats / tiers / list
tools/fetch_twitter.py          ← X API v2 抓取器，寫 briefing-out/cache/twitter-signals.json（TTL 20h）
tools/test_source_credit.py     ← unittest

tools/briefing_runner.sh        ← 每日自動：fetch_twitter.py（抓取）+ source_credit.py resolve-due（驗收）
tools/archive_cache.py          ← twitter-signals.json 併入每日凍結快照
```

消費端（Claude skill 讀取，全部 cache-only，不在 skill 執行時直接打 X API）：

| Skill | 消費點 |
|---|---|
| `/briefing` | Step 0.68（Load cache）、Step 0.7 2b（facts_due 驗收）、§9.5 3c（訊號擷取管道）、Section 6 Key Alerts 🐦 行、§9.6（Deep tier 陳列表，僅此處可見 Probation）、Telegram T3.5/T8a/T8b |
| `/trade-review` | 4d（`resolve-due && stats && tiers --dry-run`，判讀信用帳 + R21 升級門檻） |
| `/stock-analysis` | §4b 訊號擷取來源管道第 5 項 |

## 資料模型

### `source-config.json`（私有，示意 schema）

```jsonc
{
  "version": "2026-08-26",
  "note": "display-only、tier 只由 source_credit.py tiers 機械更新",
  "sources": [
    {
      "id": "example_fact_source",
      "platform": "x",            // x | substack | rss | podcast | manual
      "handle": "example_handle",
      "url": "https://x.com/example_handle",
      "kind": "fact",             // fact | view
      "domains": ["semis", "memory"],
      "tier": "probation",        // probation | trusted | core（機器寫）
      "tier_since": "2026-08-26",
      "tier_lock": false,          // 手動鎖，鎖住時 tiers 不改此來源
      "tier_history": [],
      "x_user_id": null,           // fetch_twitter.py 解析後寫回
      "enabled": true,
      "added": "2026-08-26",
      "notes": "…"
    }
  ],
  "x_fetch": {
    "enabled": true,
    "max_reads_per_run": 60,
    "per_account_limit": 10,
    "lookback_hours": 48,
    "exclude": ["retweets", "replies"],
    "cost_per_read_usd": 0.005,
    "keywords": ["…"],
    "extra_tickers": ["…"],
    "aliases": {"…": "…"}
  },
  "credit_thresholds": {
    "half_life_days": 90,
    "stale_days": 14,
    "fact_magnitude_tolerance": 0.5,
    "view_horizons_allowed": [30, 60],
    "view_default_horizon_days": 30,
    "fact_expire_after_days": 30,
    "trusted": {"min_hits": 3, "min_hit_rate": 0.65},
    "core": {"min_hits": 6, "min_hit_rate": 0.75, "min_distinct_tickers": 2},
    "demote": {"misses_in_last_n": 2, "last_n": 5, "min_n_for_rate": 4, "max_hit_rate": 0.5},
    "noise": {"max_vague_ratio": 0.7, "min_total": 5}
  }
}
```

`platform ∈ {x, substack, rss, podcast, manual}`；`kind ∈ {fact, view}`；`tier ∈ {probation, trusted, core}`；`tier_lock` 為手動鎖。機器只寫 `tier` / `tier_since` / `tier_history` / `x_user_id` 四欄，其餘手編。

真實種子來源（實際信任哪些帳號）直接寫進這份私有 config，**不進本文件、不進任何入庫檔案**。

### `source-credit.jsonl`（私有，每行一則主張）

欄位：`id, source_id, platform, kind, tickers[], ticker, domain, claim, metric, value, value_num, direction, raw_quote(≤120字), url, posted_date, first_news_date, confirm_by(fact專屬), horizon_days/target_date(view專屬), backtest, status, created_at, resolution`

`status ∈ {pending, resolved, unscorable, expired}`

**fact resolution：**
```jsonc
{"resolved_at": "...", "method": "manual", "verdict": "hit|miss|partial",
 "actual": "...", "actual_num": null, "confirm_date": "...",
 "lead_time_days": 14, "timeliness_credit": 1, "magnitude_check": "..."}
```

**view resolution：**
```jsonc
{"resolved_at": "...", "method": "price", "benchmark": "SMH",
 "p0": 0, "p1": 0, "b0": 0, "b1": 0,
 "excess_alpha_pct": 0.0, "verdict": "hit|miss", "target_date_used": "..."}
```

**id 規則**：fact = `source:date:TICKER:metric`；view = `source:date:TICKER:up-h30`。同 id 若仍 `pending` → 重登為 upsert；已 `resolved` → 拒絕重登，exit code 2（碰撞，同 thesis_ledger 慣例）。

## 計分公式

（以下逐字對應 `tools/source_credit.py` module docstring，任何調整以程式碼為準）

- **fact magnitude_check**：方向錯 → miss；方向對且 `|actual−value|/|value| ≤ 0.5` → hit；方向對但超幅 → partial；缺數字 → null（verdict 以 `--actual` 證據為準，與 check 不符只警告不擋）
- **lead time**：`(first_news_date or confirm_date) − posted_date`；≤0 → `timeliness_credit=0`（準確度照計，不因領先時間非正而扣分）
- **view**：同 `shadow_signals.py` 既有邏輯：`bench = benchmark_for(t)[:-3]`，`eod_series(f"{s}.US", …)`，`alpha = (p1/p0-1) - (b1/b0-1)`，`verdict = hit if (alpha>0)==(direction=="up") else miss`；`target_date_used = min(target_date, asof)`
- **Beta 後驗（90 天半衰）**：`s = 1/0.5/0`（hit/partial/miss），`w = 0.5**(age/90)`，`α = 1+Σws`，`β = 1+Σw(1−s)`；`hit_rate = (hits + 0.5·partial) / n_scored`（**tier 判定用未加權** hit_rate，Beta 後驗只作展示用的貝式估計）
- **vague_ratio** = `(unscorable + expired) / n_total`；`noise` 成立條件 = `n_total ≥ 5` 且 `vague_ratio > 0.7`
- **tier 判定順序**（由上而下，前者蓋過後者）：
  1. **降級 probation**：最近 5 筆 `miss ≥ 2`，或 `n ≥ 4` 且 `hit_rate < 0.5`
  2. **core**：`hits ≥ 6`、`hit_rate ≥ 0.75`、`distinct_tickers_hit ≥ 2`
  3. **trusted**：`hits ≥ 3`、`hit_rate ≥ 0.65`
  4. 其餘 → **probation**
- **`stats` 每來源輸出欄**：`n_total n_pending n_scored hits partial misses unscorable expired hit_rate posterior_mean effective_n distinct_tickers_hit misses_in_last_5 mean_lead_time_days vague_ratio noise mean_excess_alpha_pct backtest_share proposed_tier`，另加 `by_kind` / `overall` / `promotion_rule` 三個彙總欄

## Tier 語意（skill 消費時的許可範圍）

| Tier | 可出現位置 | 可作用途 |
|---|---|---|
| **Probation** | 僅 briefing §9.6（Deep tier 陳列表） | 不得作任何 prior、不得進 Key Alerts / Telegram |
| **Trusted** | Key Alerts 🐦 行、Telegram T3.5/T8a/T8b、§9.5 3c 訊號擷取 | medium confidence prior |
| **Core** | 同 Trusted，額外可提試單候選背景 | 仍須過 R14 持有期閘 / R15 回檔熔斷 / R18 財報窗禁令等既有硬閘門，不繞過 |

**升級為可作硬閘門輸入的條件（R21，見 `feedback/RULES-LEDGER.md`）**：連續 **2 期** `/trade-review` 內，Trusted+ 來源 `hit_rate ≥ 0.65` 且 `mean_lead_time_days > 0`（真的有領先，不是巧合追認）。未達標前，所有 tier 皆維持 display-only。

## CLI 速查

### `tools/source_credit.py`

全域旗標：`--ledger --config --asof`（`--asof` 固定日期供測試用，預設 `date.today()`）

```bash
# 登錄來源（一般手動編輯私有 config 即可；此指令供程式化流程用）
python3 tools/source_credit.py add-source --id <id> --platform x|substack|rss|podcast|manual \
  --handle <handle> [--url <url>] --kind fact|view --domains a,b [--tier probation] [--notes "..."]

# 登錄主張
python3 tools/source_credit.py add-claim --source-id <id> --kind fact|view \
  --tickers T1[,T2]|none --claim "..." --raw-quote "<≤120字逐字>" --url <url> --posted-date YYYY-MM-DD \
  [--metric "..." --value "..." --value-num <float>] --direction up|down|flat \
  # fact 專屬：
  --confirm-by YYYY-MM-DD [--first-news-date YYYY-MM-DD] \
  # view 專屬：
  [--horizon-days 30|60] \
  [--domain semis] [--backtest] [--slug <slug>] [--note "..."]

# 到期掃描（同時 expire fact 超過 confirm_by+30 天者）
python3 tools/source_credit.py due
# → {facts_due:[...], views_due:[...], expired:[...]}

# 驗收
python3 tools/source_credit.py resolve --id <id> \
  --verdict hit|partial|miss --actual "..." [--actual-num <float>] \
  [--confirm-date YYYY-MM-DD] [--first-news-date YYYY-MM-DD]   # fact
python3 tools/source_credit.py resolve --id <id> [--force]      # view（一般改走 resolve-due）

# 到期自動驗（view 全自動抓價；fact 只列不猜，exit code 永遠 0）
python3 tools/source_credit.py resolve-due

# 統計 / 命中率
python3 tools/source_credit.py stats [--source <id>] [--kind fact|view] [--since YYYY-MM-DD]
python3 tools/source_credit.py score [--source <id>] [--kind fact|view] [--since YYYY-MM-DD]

# Tier 重算（寫回私有 config，尊重 tier_lock）
python3 tools/source_credit.py tiers [--dry-run]

# 列表
python3 tools/source_credit.py list [--source <id>] [--status pending|resolved|unscorable|expired] [--kind fact|view] [--sources]
```

**驗證規則**：`raw_quote` 必填且 ≤120 字，否則 exit 1；來源不存在 → exit 3；fact 必帶 `--confirm-by` + `--direction`；view 必帶 `up|down` 且 `--horizon-days` 須在 `view_horizons_allowed` 內；`--tickers none` 只允許 `kind=view`，資格為 `unscorable`（背景用，不計分）。

### `tools/fetch_twitter.py`

仿 `fetch_news.py` 慣例：`X_BEARER_TOKEN` 讀自 `.env`；`CACHE=briefing-out/cache/twitter-signals.json`；`STATE=briefing-out/cache/twitter-state.json`（存 `since_id` 避免重複讀取）；TTL 20h；支援 `--force` `--only id,id` `--max-reads N`；`DRY_RUN=1` 只印計畫不打 API。

```bash
DRY_RUN=1 python3 tools/fetch_twitter.py --force            # 只印計畫，不消耗額度
python3 tools/fetch_twitter.py --force                       # 正常抓取（尊重 TTL/預算）
python3 tools/fetch_twitter.py --only <source_id> --max-reads 10   # 單一來源測試
```

無 `X_BEARER_TOKEN` 或私有 config 的 `x_fetch.enabled=false` → 輸出 `status:"skipped"`，exit 0（非致命，briefing 照常，只是沒有這份 cache）。

輸出 schema（`briefing-out/cache/twitter-signals.json`）：
```jsonc
{
  "status": "ok|partial|skipped",
  "reason": "...",
  "generated_at": "...",
  "reads_used": 0,
  "est_cost_usd": 0.0,
  "budget": {"...": "..."},
  "sources": {
    "<source_id>": {
      "platform": "x", "handle": "...", "kind": "fact",
      "tier": "trusted", "tier_since": "...", "domains": ["..."],
      "posts": [
        {"id": "...", "date": "...", "text": "...", "url": "...",
         "tickers_mentioned": ["..."], "keywords_hit": ["..."],
         "has_number": true, "metrics": {}}
      ]
    }
  },
  "errors": []
}
```

`tier` 直接抄自私有 config，skill 端不需讀私有 config 即可判斷顯示權限。

## X API 成本

`cost_per_read_usd = 0.005`（官方 X API v2 按量計費，實際帳單依請求量非回傳量，見下方已知限制）；`max_reads_per_run = 60` 為每次執行硬上限。

- 單次執行上限：`60 reads × $0.005 = $0.30`
- launchd 只在交易日跑（`SKIP_NON_TRADING_DAYS=true`），以 ~23 個交易日/月估：`$0.30 × 23 ≈ $7/月`
- 剩餘額度不足 5 reads 時停止讀取，標記 `budget_exhausted:true`，`status` 降為 `partial`；429/402 錯誤 → 記錄後即停，不重試（避免計費雪球）

## Bootstrap 回測協定

實作完成後，先用歷史已知的公開事件回測，建立首批 tier 分布，避免上線即空手。**由 Claude 使用 Chrome，在用戶已登入的 X 帳號上執行**（不走官方 API，省額度；X 搜尋介面公開可讀歷史推文）。

### 事件表（先做 8 件 + 1 負對照，其餘視時間）

| 標的 | 事件 | 確認日 |
|---|---|---|
| ON | SiC 通路缺貨 | 2026-08-03 |
| DIOD | 通路庫存 | 2026-08-06 |
| COHR | NVDA $2B / 800G | 2026-08-12 |
| MU | $22B take-or-pay | 2026-06-24 |
| BE | Oracle 2.8GW | 2026-07-28 |
| MRVL | Google ASIC + $12.2B | 2026-08-18 |
| GEV | 機組排到 2030 | 2026-07-22 |
| STM | 資料中心營收 >$1B | 2026-07-23 |
| **SNDK**（負對照） | NAND guide miss | 2026-08-06 |

備用（視時間追加）：KTOS / STRL / ONTO / LRCX / AAPL。

### 搜尋 query 模板

對每件事件，在 X 搜尋以下 query，由早到晚讀，記最多 5 個有量化方向主張的貼文（handle / URL / 日期 / 逐字 ≤120 字 / 數字）：

```
x.com/search?q=("kw1" OR "kw2") <公司> since:<確認日−45天> until:<確認日−1天> min_faves:20 -filter:replies&f=live
```

### 執行步驟

1. 不在私有 config 的來源 → `add-source` 先登錄
2. 對每則挑出的貼文 → `add-claim --backtest ... --confirm-by <確認日>`
3. 立即用官方數字（財報/8-K/公司公告）`resolve --verdict hit|partial|miss --actual "<官方數字+出處>" --confirm-date <確認日>`；負對照講錯者記 `miss`（這正是負對照存在的目的——驗證計分機制不會無腦全給 hit）
4. 完成後 `stats` → `tiers --dry-run` → **用戶抽查 3 筆** → 確認無誤才 `tiers`（不帶 `--dry-run`）套用

**篩選規則（2026-08-26 首輪回測實測後追加）**：
- 確認日前 **<3 天**的貼文一律不登錄——那是財報預覽/堆疊，不是提前資訊（首輪 MU/BE/MRVL/GEV 搜到的全是印前 1 天堆疊，全部跳過）
- 自動化帳號（標示 Automated by …）不登錄
- `$TICKER` cashtag 撞幣圈（如 `$ON` = Orochi Network）→ query 改用公司名純字
- X 搜尋對利基供應鏈主張的召回率低：首輪 9 事件只找到 5 則可計分的提前主張（ON 24 天、DIOD 13 天、COHR/STM 4 天、SNDK 對照待驗）；**回測只能當種子，tier 真正要靠實盤期累積**

**預期結果**：少數來源達 Trusted，**目前不會有 Core**（Core 門檻需 6 命中且跨 ≥2 檔，設計上要靠實盤期累積，不是回測能單獨衝到的）。

### 中文來源（2026-08-26 實測）

- **X 的中文關鍵字搜尋幾乎無效**（CJK 斷詞鬆散，`缺貨/交期/急單` 撈到體育、政治與垃圾連結；`lang:zh` + `min_faves` 只能稍減）。**中文走帳號制**：從英文/中文搜尋結果中發現有實質供應鏈內容的帳號 → `add-source` 進每日抓取，靠 tier 計分篩選，不靠關鍵字搜尋發現主張
- 台灣供應鏈的價值在**第一手重訊/月營收/法說轉述**（例：聯亞 3081 長約重訊、ASML 日媒財報整理、CCL/PTFE 材料鏈）——確認點明確（每月 10 號營收、法說會），是 NVDA/AVGO/MU/LITE 的上游估算來源
- `fetch_twitter.py` 的邊界比對 `(?<![A-Za-z0-9])…(?![A-Za-z0-9])` 對 CJK 有效，**中文 alias（輝達→NVDA、聯亞→3081.TW…）與關鍵字（投片、急單、交期、能見度…）只需加進私有 config**，不改程式

### KOL（view 型來源）處理慣例

- 財經 podcast/YouTuber 只在節目**明確點名標的+方向**時登 `view` claim（用價格計分）
- 只談總經敘事、不點名個別標的者 → `--tickers none`，僅作背景，`unscorable` 不計分

## 消費點（各 skill 的引用位置）

- `/briefing` Step 0.68（cache 讀取與紀律）、Step 0.7 `2b`（facts_due 人工驗收）、§9.5 `3c`（訊號擷取管道，含 `--ev` provenance 格式 `src=<source_id>@<tier>, claim=<id>`）、Section 6 Key Alerts 🐦 行（Trusted+ only）、§9.6（Deep tier，唯一可見 Probation 的陳列位置）、Telegram T3.5/T8a/T8b
- `/trade-review` 4d（`resolve-due && stats && tiers --dry-run`，判讀 n<3/backtest_share/noise，R21 升級門檻檢查）
- `/stock-analysis` §4b 訊號擷取來源管道第 5 項

## 已知限制

- **X 計費模型不確定**：官方文件對「按請求量」vs「按回傳量」計費界線不總是清楚；`max_reads_per_run` 是硬上限，最壞情況成本仍受其夾住，但實際帳單可能與 `est_cost_usd` 估算有落差，需對照官方帳單校正 `cost_per_read_usd`
- **view 只計方向，不計幅度**：`alpha=(p1/p0-1)-(b1/b0-1)` 只判斷方向對錯，不像 fact 的 `magnitude_check` 有 partial 分級；影子期可接受，若 `/trade-review` 發現 mean excess alpha 長期 ≈0（方向對但幅度小到無意義）則需要細化計分
- **Core tier 需要實盤期**：回測無法單獨衝到 Core（見上），代表上線初期所有來源最多到 Trusted，這是設計上刻意的門檻，不是 bug
- **小樣本統計謹慎**：`n_scored < 3` 的來源一律只記錄不下結論；`backtest_share > 0.8` 的來源標「僅回測」，不當已在實盤驗證的命中率
- **`tiers` 寫入私有 config 的欄位受限**：只改 `tier` / `tier_since` / `tier_history` / `x_user_id` 四欄，且用原子寫（`tempfile.mkstemp` + `os.replace`），不動其餘手編欄位
- **個人選號不入庫**：真實信任的帳號清單只存在私有 `research/source-config.json`，本文件與 `docs/source-config.example.json` 一律只用佔位範例
