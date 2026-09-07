---
name: trade-review
description: 每兩週交易檢討：歸因每筆成交是「系統決策」還是「你自己決策」、算基準校正 α、驗影子訊號、更新規則命中率帳本，輸出「本期該改哪一條規則」。Usage - /trade-review [2w|4w|since YYYY-MM-DD]
user_invocable: true
model: claude-opus-4-8
---

# Trade Review — 兩週交易檢討

**這是系統自我進化的引擎。** 其他 skill 產生決策，這個 skill 檢查決策對不對，並把結果回饋到規則層。

**Why：** 2026-07-25 首次歸因調查發現，系統決策的 α 是 **+6.1%**（賣方 +13.0% / 71% 勝率），脫離 plan 的用戶決策是 **−14.0%**（12 次對 2 次）。但當時可歸因覆蓋率只有 49%，且沒有任何機制持續計分——規則寫死後永不重測。這個 skill 補上那個迴路。

## Arguments

- `/trade-review` → 上次檢討至今（若無紀錄則近 14 天）
- `/trade-review 4w` → 近 28 天
- `/trade-review since 2026-06-04` → 指定起日

## Step 0（沿用 CLAUDE.md 統一規範）

- 0a 讀 `plan.md` + `feedback/*.md`（**含 `feedback/RULES-LEDGER.md`**）
- 0b `mcp__firstrade-server__get_account_position`
- 0c/0d journal 確認與 gap-fill
- **不需要 0e 第一性檢查**——本 skill 不輸出 Verdict / 投資建議，只做事後歸因與規則計分

---

## Step 1 — 交易帳 ingest 與歸因

```bash
python3 tools/trade_ledger.py snapshot-orders
python3 tools/trade_ledger.py ingest --range 2m
python3 tools/trade_ledger.py backfill-origin --since <期初>
python3 tools/trade_ledger.py stats
```

**必報三個數字**（覆蓋率是本迴路的健康指標，要逐期往上走）：
- 本期新增成交筆數
- `attribution_coverage_journaled_pct`（有 journal 期間的 origin 覆蓋率）
- `order_registry.snapshot_days`（快照天數；越多，往後歸因越接近 100%）

⚠️ **覆蓋率不會靠自己變好。** 對 `unknown_sample` 列出的每一筆，翻當日 journal / plan.md 判斷來源，然後：

```bash
python3 tools/trade_ledger.py annotate --id <fill_id> \
  --origin system|user --evidence "<判定依據原文>" [--bucket 信念|認列|hedge|樂透]
```

補正時**一併記模型**（`--model claude-opus-4-8 --effort high`），這樣 `score --by model` 之後能用數據回答兩件事：貴的模型層級值不值那個成本，以及更新的模型不同意舊決策時，該不該相信它。**模型版本是排覆審順序的依據，不是推翻已驗證結論的依據**（同 `RULES-LEDGER` 的鐵則）。

判定準則（`origin` = **誰決定**，與 `exec_via` **誰按按鈕** 無關）：
- **system** — plan.md 有 ref／plan #N／規則執行（梯級停利、停損鐵律、harvest 訊號）／plan v2 砍單
- **user** — 未列於 plan／偏離 plan 階梯／違反既有指令／無 plan 依據的自主判斷
- 判不出來就留 unknown，**不要猜**

> 2026-06-18 是必記的反例：九檔在 App 手動出清，但砍因來自 plan v2 → **系統決策、手動執行**。若用執行方式推論決策來源，會把全帳最大 alpha 事件（+$8,997）誤記成用戶自主交易。

## Step 2 — 三個指標，缺一不可

三者答不同問題，只看任一個都會誤導：**交易 α**（進出對不對）、**持有 α**（該不該繼續抱）、**beta capture**（行情好的時候吃到沒有）。

```bash
python3 tools/trade_ledger.py score --by origin-side --since <期初>
python3 tools/trade_ledger.py score --by bucket --since <期初>
python3 tools/trade_ledger.py holding-alpha --window 90
python3 tools/trade_ledger.py beta-capture --window 180 --bench SMH
```

### 2d. 帳戶級四指標（每期必跑，2026-07-29 起）

```bash
python3 tools/account_metrics.py scan && python3 tools/account_metrics.py report --live <Step 0b 即時帳戶總值>
```

輸出期間報酬 / CAGR / MDD / Sharpe（淨值標記曲線）+ profit factor（FIFO 已實現、含選擇權與費用）。與上期 `archive/*/account-metrics.json` 對照列 Δ。**誠實標示照工具輸出**：MDD 基於離散標記屬低估、短窗年化僅供方向；淨值紀錄自 2026-06-01 起，用戶提供券商對帳單更早淨值時用 `add` 補錨。

### 2a. 交易 α（誰決定的比較好）

| 決策來源 | n | β調整 α | 勝率 | β調整 $ | β=1 的 $ | beta 汙染 | 均β |
|---|---|---|---|---|---|---|---|
| 系統決定 — 賣/買 | | | | | | | |
| 你自己決定 — 賣/買 | | | | | | | |
| 無記載 | | | | | | | |

**`alpha_beta` 才是結論依據**，`naive_alpha_dollars` 只用來看 beta 汙染有多大。β 是對**實際使用的基準**回歸算的（半導體對 SMH、其餘對 SPY）。

> 為什麼這件事關鍵：2026-07-25 首測時，賣方 β=1 算出 +$8,997，看似巨大選股技術；改用券商 β（對大盤測）套 SMH 又算出「全滅」。**兩者都錯。** 同基準回歸給出 +$6,846（76% 存活）—— 選股技術是真的，但有 24% 是 beta。用錯 β 會讓「該不該繼續這樣做」得到相反答案。

### 2b. 持有 α（交易 α 之外的另一半）

`holding-alpha` 給每檔的**滾動 90 天**（決策相關：現在還該不該抱）與**建倉至今**（歷史：進場對不對）。

**必列：正 α 與負 α 各自的檔數與金額。** 首測基準：滾動 90 天 +$8,219 但**勝率僅 25%**——集中在 MU/DDOG/CRWD/AMD 四檔（+$33,833），被其餘 15 檔（≈−$26,000）抵銷。

⚠️ **建倉至今不可加總**（僅 13/20 可測，且可測者偏向近期建倉、長抱贏家因 lots 早於帳戶歷史落選 = 選擇偏差）。只讀個股。

⚠️ **持有 α 存在的理由**：純交易指標會系統性獎勵頻繁進出、把「抱對一年」記為零貢獻。首測顯示持有 α 量級**大於**交易 α。

### 2c. beta capture（行情好的時候吃到沒有）

`beta-capture` 拆基準上漲日/下跌日各自回歸 β：

| | β | 日 α (bps) | 累積 α | 天數 |
|---|---|---|---|---|
| 全期 / 上漲日 / 下跌日 | | | | |

**判讀：up-β > down-β = 想要的曝險輪廓；up-β < down-β = 漲不上跌得凶。**

首測基準（180 天 vs SMH）：**up-β 0.79 < down-β 0.90，capture 比 0.88**。成因結構性——梯級停利在強勢中賣、買梯在弱勢中買，兩者機械性壓低 up-capture。這是純 α 指標看不見的成本（見 `RULES-LEDGER` R8）。

### 解讀紀律
- 買方 α 全負不代表買錯 —— 先確認基準也在跌；`alpha_beta` 已扣 beta，負才是真的差
- n < 10 的分組**必須標註樣本不足**，不得單獨下結論
- 與上期比較趨勢，而非只看本期絕對值
- **三個指標若互相矛盾，那本身就是本期最重要的發現**（例：交易 α 正但 up-capture < 1 = 進出做得好但曝險輪廓錯）

## Step 3 — 最佳/最差各 5 筆，逐筆追問

`score` 已回傳 `best` / `worst`。對每一筆翻出當日 journal 的決策理由，回答：

1. **當下有沒有訊號被忽略？**（revision、情緒、A4 旗標、集中度、Codex 反對意見）
2. **這筆的 origin 判定可靠嗎？**（evidence 是不是真的指向這筆交易）
3. **是規則問題還是執行問題？** 規則對但沒執行 → 執行力缺口；規則本身導致 → 進 Step 5 計分

歷史對照（首次調查已確立的模式，用來檢查本期是否重演）：
- **MRVL 型**：不在 plan 的名字連續加碼，每次都被 journal 標記卻沒被阻止（3 次共 −$1,884 α）
- **NVDA $205 型**：plan 內領導者、價格高於買梯，偏離是**對的**（+7.9%；MU $844.81 +3.6%）
- **ICHR 型**：小倉「汰弱」賣出，事後標的大漲（−32.3%）
- **hygiene 型**：為湊支數/清尾倉砍小倉（LITE −11.2%、CEG −14.3%、SNOW −21.8%）

## Step 3.5 — 旗標稽核（本書最貴的漏口）

```bash
python3 tools/trade_ledger.py flags
```

**2026-07-25 量測：「已標記惡化但沒有強制出場」是吃掉最多回撤的單一機制，自警示以來 −$6,333。** 排第二的是「下跌中深檔買梯建新倉」（−$5,700）。

本期必答：
1. **forced 清單處理了嗎？** 每筆 forced 必須有 `resolve-flag`（減碼/出場/撤旗），不得再 `defer`
2. **本期新開的旗標，有沒有該開卻沒開的？** 掃本期 briefing/journal 的 ⚠️ / 降桶候選 / 勿加碼 / thesis 蒙塵 字樣，比對 flags 清單。**漏開就是漏口重現**
3. **`post_flag_fills` 有值的 → 警示後仍加碼**，逐筆檢討為什麼禁令沒有阻力（ON 6/26 下禁令、7/06 加碼 32 股，−$206）
4. **`total_cost_since_flag` 與上期比較** —— 這個數字往下走才算修好

同時查 thesis 增生（合理化的指紋）：同一標的累積 ≥2 筆 pending thesis 而部位在虧 → 逐筆問是不是為了繞過既有警示而新登錄。
> ON 在 4 週內累積 3 筆 pending thesis（6/26 `cyclical-recovery-q2`、7/04 `power-shortage-early-position`、7/23 `800vdc-power-tree-validation`），全部觸發 8/03；而 7/06 的加碼引用的正是 7/04 那筆新 thesis。

## Step 4 — 影子訊號驗收

```bash
python3 tools/thesis_ledger.py orphans
python3 tools/thesis_ledger.py stats
python3 tools/ev_ledger.py resolve-due && python3 tools/ev_ledger.py stats
```

**4-0. EV 分布校準（機率誠實的結果端驗證）**

`ev_ledger.py stats` 輸出 EV 誤差（by horizon/model）+ Brier + 校準表（給的機率 vs 實際落桶頻率）。判讀紀律：
- **n<30 的分組只記錄方向，不改規則**；相關樣本（同跨一段行情的多筆）算一筆證據，不按筆數計
- 系統性偏差確立（如「30-60d 一致過度樂觀」連兩期同向）→ 修正對象是 **probability-honesty-checker 的形狀規則表 / 各 skill prompt**，寫入 `RULES-LEDGER` 帶命中率追蹤 — **不建 ML 模型**（n>150 獨立已解決樣本前不重評，見 CLAUDE.md）
- Goodhart 警戒：校準變好但分布變窄（永遠給 hedged 分布）= 假改善，對照分布寬度一起看
- `stats` 的四項——獨立 n、Brier skill score（>0 才是技能）、`in_range`（分布外 = 漏分支非運氣）、thesis × 定價 2×2（「對但沒用」= priced-in 候選）——原樣抄進報告 §4，`review_lint.py` 會查

**4a. A4 高估旗標（影子模式，Phase 1 只記錄不阻擋）**

讀 `research/shadow-signals.jsonl`，對**已滿 30 天**的旗標算實際超額 α，累計命中率：

| 旗標日 | 標的 | A4vsA3 | 30d 後超額 α | 命中 |
|---|---|---|---|---|

判定條件（`briefing` / `portfolio-review` 產生旗標時已套用）：`A4vsA3 ≤ −35%` 且 `confidence == "ok"` 且 `pe_ratio < 200`。

> `pe_ratio < 200` 的排除條件來自 DDOG：A4 給 −71% 但 PE 553、表中自註「我極保守」，事後 **+19.0% α**。這是唯一反例且成因已知。

**跑滿 2 期後**才決定是否升硬閘門（Phase 2）。基準線：首次前瞻檢驗 n=12、Spearman +0.45、高估組 4/4 落後平均 −15.9% α。

**4b. thesis 中途證偽（不是等觸發日才看）**

```bash
python3 tools/thesis_ledger.py recheck --long-drift-only
```

證偽條件已經寫好且具體，缺的是**只在觸發日被讀**。首測時 23/23 pending thesis 的建立→觸發相隔 ≥45 天，`MRVL:fy28-ai-bookings-visibility` **172 天**——半年前提可以壞掉而沒人看。

對清單上每一筆問一句：**這些條件裡，有沒有現在就看得到的已經成立了？**
- 成立 → 立刻 `resolve --verdict failed`，**不等觸發日**
- 前提完好 → 說一句「完好」帶過
- 判不出來（需要下次財報）→ 明確說「須待 <事件>」

有些條件本來就不必等財報，例如「Google 公開宣佈減少 AVGO 採購份額」「主要 hyperscaler 公開削減 XPU capex >10%」「毛利率跌破 38%」。

**4c. thesis 帳本兩個比率**

`stats` 現在同時回 `hit_rate`（thesis 對不對）與 `pnl_hit_rate`（有沒有賺錢）。**兩者的差距就是「在虧損部位上驗證 thesis」的程度。**

`orphans` 列出「曾持有→已出場但 thesis 仍 pending」者（`reentry-*` 與從未持有的候補已排除）。每一筆必須處理：

```bash
python3 tools/thesis_ledger.py resolve --id <id> --verdict passed|failed|partial \
  --actual "..." --note "..." --next-action "..." \
  --position-status exited --realized-pnl <±金額> [--price-verdict met|missed]
```

`partial` 強制 `--price-verdict`：營運達標但市場不認 → `missed`。

**4d. 來源信用帳（來源信用 tier 閘，R21 影子計分中）**

```bash
python3 tools/source_credit.py resolve-due
python3 tools/source_credit.py stats
python3 tools/source_credit.py tiers --dry-run
```

輸出每來源一行：

| 來源 | tier | n_scored | hit_rate | mean_lead_time_days | vague_ratio | backtest_share | proposed_tier |
|---|---|---|---|---|---|---|---|

判讀紀律：
- **n_scored < 3** → 只記錄不下結論（樣本太小）
- **backtest_share > 0.8** → 標「僅回測」，實盤期樣本不足前不當已驗證命中率
- **noise**（`vague_ratio > 0.7` 且 `n_total ≥ 5`）→ 建議該來源 `disable`（連續講不可驗證的模糊主張）
- **tier 只抄 `tiers --dry-run` 輸出**，不手改 `research/source-config.json`；抽查認可後才拿掉 `--dry-run` 套用
- **R21 升級條件**（display-only → 可作硬閘門輸入）：連續 **2 期** `/trade-review` 內，Trusted+ 來源 `hit_rate ≥ 0.65` 且 `mean_lead_time_days > 0`（真的有領先，不是巧合追認）才討論升級；未達標維持 §9.6 display-only

## Step 5 — 更新規則命中率帳本

編輯 `feedback/RULES-LEDGER.md`（判準 `feedback/skill-vs-luck.md`）：

1. 更新命中/失效：只算建立日後的獨立事件（原始案例不計、同批算 1）；每筆附證據 + `[up]/[down]`（`python3 tools/rule_stats.py regime --date <日> --bench SMH|SPY`）
2. `python3 tools/rule_stats.py ledger-audit --write` → 狀態欄照輸出改；再跑 `--check` 必須 exit 0
3. 結案分類：分布外 = 模型錯；證偽條件觸發未動 = 決策錯；thesis 沒兌現但賺 = 運氣（不計命中）
4. 新規則 → 登錄一列；新假設 → 對照追蹤表
5. R26：報 Brier skill score（獨立 n）與 `holding-alpha` 對 SMH 走向，不裁決

## Step 5.5 — 注意力預算稽核（每期必跑，2026-07-30 起）

登記機制只進不出會稀釋注意力。每期掃四類，列清理清單並執行：

1. **Thesis 殭屍**：`thesis_ledger.py stats` + pending 全列 →
   - 已清倉標的的殘留 thesis（re-entry 條目已另存者）→ `close-untested --exit-date <清倉日>`
   - pending 齡 >60 天且 due 還在 30 天外、期間無任何 signpost 移動 → 覆審：還值得等嗎？不值得 → close
2. **L1/L2 板凳除名**（plan.md）：L2 名字 90 天無 gate 觸發且 revision 靜止/轉負 → 除名（一句理由）；L1 觸發價失效 >60 天 → 降 L2 或除名；已進場者移出板凳。**除名 ≠ 永久淘汰**（質地理由才可判永久淘汰，per `exit-reentry-discipline.md` 分層鐵則）
3. **價格警報覆核**：`price_alerts.py list` → 觸發多次無人行動 / 條件已過時（財報已過、thesis 已結案）→ remove
4. **一次性清單**：research/ 下的行動清單（抄底清單類）過期 → 移 `research/archive/`，並拔掉 skill 引用
5. **守門工具 + roster 一致性（2026-09-02 起）**：跑 `python3 tools/position_guard.py --sync-alerts --render-plan`，缺口全數處理（桶別缺口 → 更新 `research/roster.json`；已出場標的自 roster 移除；R8 GTC 缺口 → 掛單；R23 旗標 → 執行/resolve）。同時掃 R23 計分：本期每筆 `resolve-flag --action trimmed` 的 R23 旗標，+30 天價 vs 減碼價 → 命中/失效寫入 RULES-LEDGER R23。
6. **規則本身**（用戶 2026-08-29 提議，首次大裁決後生效）：連兩期零觸發零資訊量的規則 → 標「歸檔候選」；建立滿 60 天仍 `—` 的規則 → 轉「未驗證假設」

輸出：`🧹 本期清理：thesis −N / 板凳 −N / 警報 −N`（零清理也要列，證明有跑）。

## Step 6 — 輸出

寫 `briefing-out/trade-review-YYYY-MM-DD.md`，然後：

```bash
python3 tools/generate_html.py trade-review briefing-out/trade-review-YYYY-MM-DD.md
```

報告結構：

```markdown
# 交易檢討 YYYY-MM-DD（期間 YYYY-MM-DD ~ YYYY-MM-DD）

## 1. 帳本健康
新增成交 N 筆｜歸因覆蓋率 X%（上期 Y%）｜快照天數 D｜本期人工補正 M 筆

## 2. 誰決定的比較好（基準校正 α）
[核心表，全部 + 僅高信心兩組]
[與上期趨勢比較]

## 3. 最佳/最差各 5 筆
[逐筆附當時 journal 理由 + 「當下有沒有訊號」的答案]

## 4. 影子訊號
[A4 旗標命中率表 + 是否建議升閘門]
[thesis hit_rate vs pnl_hit_rate + orphan 處理結果]
[來源信用帳 tier 表 + 是否達 R21 升級門檻]
[EV 校準：獨立 n / Brier skill score / in_range / 2×2；R26 走向]

## 5. 規則計分變動
[本期哪幾條 +命中 / +失效，附證據與 [up]/[down]；無計分寫「本期無計分」]
[ledger-audit 結果 + 🔴 強制覆審清單]

## 6. 本期結論：該改哪一條規則
**規則：** [具體到檔名與條號]
**為什麼：** [一句話 + 數字]
**改法：** [具體修改，或「證據不足，繼續觀察 N 期」]
```

**最後一節只准寫一條**（最多兩條）。列十條等於沒有結論。

## 收尾

1. 更新 `research/last-trade-review.txt` 為今日日期（briefing 讀它算到期提醒）
2. `python3 tools/review_lint.py briefing-out/trade-review-YYYY-MM-DD.md` **必 exit 0**（缺段 / 結論 >2 條 / 收尾沒做都會擋；擋了就補，不改 lint。寫入報告時 PostToolUse hook 會自動先跑一次，這裡再跑是確認 last-trade-review 已更新）
3. 若改動了任何 `.claude/skills/` 或 CLAUDE.md → `python3 tools/sync_agents_skills.py`

## 已知限制（每期都要讀，避免過度推論）

- **首次歸因的「你自己決定」樣本 n=12、兩個月、單一 regime（半導體殺盤）。** 效果量大且買賣方向一致，但不足以當定論。把樣本推大並回頭驗證，是這個 skill 存在的主要目的。
- **與 plan 一致的用戶判斷在紀錄上無法與系統區分**，會被計入 system。所以「你自己決定」實際是「你**脫離 plan** 的決策」，不是你全部的判斷。
- **`get_orders` 只回在掛單**，已成交/已取消會從券商端消失 → order_id 歸因只能前瞻。快照斷天會產生無法歸因的缺口。
- **2026-06 之前的成交沒有 journal 理由欄**，origin 永久 unknown，不必嘗試補。
- **選擇權已可經 MCP**（2026-09-07）：單腿 `order_type` 用 `buy_to_open` / `sell_to_close` 等四碼（平倉必用 `*_to_close`）；兩腿 spread 用 `preview_option_spread` / `place_option_spread`（day only、ET 7AM–4PM）。三腿以上或 GTC 複式單仍 App 手掛（`tg_send.py`）。
