# 方法論亮點

這套框架的核心不是「叫 LLM 給意見」，而是用多層紀律強迫每個結論落在可驗證的 ground truth 上。以下逐項展開 [README「核心設計」](../README.md#核心設計) 列出的機制。

- **第一性原理紀律（Step 0e）** — 任何 Verdict 前強制回答三題：① 核心 thesis（1 句**可驗證命題**，非 narrative）② 證偽條件（2-3 個 falsifiable 觀察點）③ 機率分布 + EV（由 `probability-honesty-checker` agent 強制計算，禁用 default bell shape 與「略偏正」這類質性語言）。
- **三錨點 Fair PE 估值（Section 8.5 / G3.5）** — 不手寫 PE 倍數猜想；用三個獨立錨點做三角定位：A1 市場隱含 PE（EODHD）/ A2 PEG 成長合理倍數 / A3 分析師 PT 隱含 PE。Base = median；Bull = max × 1.25；Bear = min × 0.70。`pe_ratio == 0.0` / `peg_ratio == 0.0` → 自動丟棄該錨，標 `(anchor unavailable)`。
- **Thesis Ledger（`tools/thesis_ledger.py`）** — 把帶觸發點的 thesis 登錄進帳本，到期（如財報日）自動回頭抓實際數字驗收 passed/failed，累積命中率。詳見 [`thesis-ledger.md`](thesis-ledger.md)。
- **Thesis 驗證 → 股價影響（D2 三桶分解）** — thesis verdict 不只是分類；`resolve` 時帶結構化旗標：`fair_value_before/after`（三錨點重算）+ `price_impact_pct` + `impact_decomp`（thesis 成分 vs 倍數重估成分分解）。實例：AVBO partial → `thesis +6%(FY27 AI guide 確認)/multiple −16%(GM 壓縮 re-rate)=net −9.8%`。
- **全持倉基本面快取（`briefing-out/cache/fundamentals-snapshot.json`）** — `fetch_fundamentals.py` 每交易日 launchd 預載，TTL 24h。Quick/Telegram tier 直接讀快取（zero-latency，不等 MCP）；Deep tier 強制刷新。
- **A4 自建估值錨（sanity / divergence flag）** — `fetch_fundamentals.py` 同次 API call 計算：`own_fwdEPS = 歷史 CAGR（幾何，40% cap → fade 向 8% terminal）× 淨利率 ÷ 股數`（完全不看分析師 estimate）。`own_target_price = own_fwdEPS × base_FairPE(median A1,A2,A3)`。`A4vsA3% = (own_target − wall_street_target) / wall_street_target` 乾淨隔離「我的盈利觀 vs Street 盈利觀」（倍數固定）。**A4 不進 EV**，僅做分歧 flag：`confidence=unavailable`（虧損股 / <3年資料）→ `(self-val N/A)`；`low`（營收 stdev>30%）→ `⚠️低信心`；`ok` → 正常顯示。34 單元測試（`test_self_valuation.py`）覆蓋 CAGR、cap、decel、macro clamp、guardrails。
- **新聞全文快取 + P3 訊號擷取（`briefing-out/cache/news-articles.json`）** — `fetch_news.py` TTL 6h，top 8 篇/ticker，600-char body excerpt。`mcp__eodhd-mcp__get_news` 工具提供即時全文（1500 char）。Deep tier §9.5 / stock-analysis Step 4b 從 news body + SEC 8-K + 財報逐字稿抽**已量化陳述**（wafer starts / capex / ASP 等），強制附 raw_quote（≤120 字逐字引用），signal → thesis 轉換後以 `--source signal-inference` 登錄 thesis_ledger，閉環追蹤 P3 命中率。反幻覺鎖：**無 raw_quote = 無 signal = 不登錄。**
- **來源信用系統（`tools/source_credit.py`）** — 把 X/Substack/RSS/podcast 這類「見報前」資訊層也當成要驗證的證據：每則可計分主張（fact 用官方數字驗、view 用價格驗）登錄入帳，到期機械驗收，來源按命中率機械升降 `probation → trusted → core`，**Claude 不得手動升降 tier**。同 A4/R18/先行指標一樣，跑滿 ≥2 期 `/trade-review` 前純 display-only，不得單獨改變 Verdict。詳見 [`source-credit.md`](source-credit.md)。
- **發現層先行指標（`tools/fetch_leading.py`）** — 財報 gate 是裁決層（慢而準），發現層另設五組比財報更早的硬數字前哨：三儀表（HY OAS 速度 / VIX 期限結構 / 半導體寬度）+ 行業 PE 溫度計與國債曲線、財報季 cross-read 排序（早報者 → 晚報持倉的讀序 prior）、記憶體/功率報價新聞監測、**revision 二階導雙法**（archive-diff × vendor 7d 曲線互驗）、台股功率元件月營收（TWSE/TPEx 免金鑰）。全部 **display-only（記錄不阻擋）**，命中率由 `/trade-review` 驗證後才可升閘門。詳見 [`leading-indicators.md`](leading-indicators.md)。
- **交易檢討自我進化引擎（`/trade-review` + `tools/trade_ledger.py`）** — 每兩週歸因每筆成交是「系統決策」還是「脫離 plan 的自主決策」，計算三並列指標：交易 α（對實際使用的基準回歸，半導體對 SMH）、持有 α（沒有它，純交易指標會獎勵頻繁進出）、up/down beta capture（漲不上跌得凶的量化）。**旗標紀律**：欠決定的部位必須 `flag` 登記附 deadline，延後計次、第 3 次強制執行 — 修的是「警示只活在散文裡而永不執行」這個實測最貴的漏口。規則命中率帳本（`feedback/RULES-LEDGER.md`）讓每條 feedback 規則用實測存廢，不由模型換代裁決。
- **自動價格警報（`tools/price_alerts.py`）** — 券商 lib 無警報 endpoint，自建：launchd 15 分鐘盤中輪詢 yfinance，跌破/突破/N 日新高三型條件 → Telegram（複用日報同一 bot），`once_per_day` 防洗版；警報定義與觸發狀態存 `research/price-alerts.json`。
- **EV 事前登錄帳（`tools/ev_ledger.py`）** — 每次 stock-analysis / ev-check 收尾把「機率分布 + 三情境公允價 + EV」**原樣**登錄（pre-registration），到期由日報機械驗價（個股抓收盤、組合對淨值標記，零判斷）；`/trade-review` 讀 `stats`（EV 誤差 by horizon、Brier、校準表）——讓「機率有沒有算準」自己留下可計分的痕跡。修正只進 prompt/規則層，n>150 筆前不建 ML 模型（防 Goodhart）。
- **規則也要被計分：財報窗禁令 A/B/C 拆分（2026-08-04）** — 掛帳 0 命中 0 失效 60 天的「±48h 禁令」被拆成三條各自計分：A 技術訊號停用（保留 + 補「財報後預登錄基本面 gate 行動」豁免）、B 選擇權不開新倉（維持保守）、C 財報前不加碼（**R18 影子計分**：每次實際擋下加碼就 `shadow_signals.py block` 登錄，30 天熟成後驗「被擋的買進是否跑輸基準」，兩期後由命中率裁決升閘門或廢除）。廢除跟保留一樣需要數據。

- **運氣 vs 技能的統計紀律（`tools/rule_stats.py`，2026-09）** — 舊門檻「命中 ≥2 = 已驗證」純擲硬幣達成率 25%，25 條規則同測預期 6 條假驗證。改為**巧合機率制**：失效 0 且巧合 ≤5%（獨立命中 ≥5）才算已驗證，5–25% 為初步支持；命中只算規則建立日後的獨立事件（原始案例不計、同批算 1），每筆附 `[up]/[down]` regime 標籤，單一 regime 的命中在另一 regime 視同未驗證。每筆結案分四格：結果落在事前分布外 = **模型漏了一支分支，不是運氣**；證偽條件觸發未動 = 決策錯；thesis 對但 realized < EV = 「對但沒用」（priced-in 候選，`ev_ledger.py stats` 自動列出）；thesis 錯但賺 = 運氣好，不計命中。帳戶級 α 要 t≥2 需要 資訊比率 × √年 ≥ 2，所以檢討重心放在兩週就能累積 n 的過程指標（規則遵循率、旗標紀律、Brier skill score），並**事前寫死放棄條件**（R26：24 個月後 Brier skill ≤0 且持有 α 對 SMH ≤0 → 轉被動，不辯解不延期）。
- **機械執行層：不信任模型的自律** — 判斷層規則跳過不留痕跡，所以能變工具的都變工具，分三層：① 工具在寫入點就擋（`ev_ledger.py add` 帶 thesis 必填 `--p-up-given-thesis`，缺就拒寫）；② 每日排程跑 `rule_stats.py ledger-audit --check`（巧合欄過期 / 狀態與數字矛盾 / 新案例缺 regime 標籤），失敗直接推 Telegram，不經模型；③ Claude Code PostToolUse hook 對每份 `trade-review-*.md` 跑 `review_lint.py`（缺段 / 結論 >2 條 / 收尾未做 → exit 2 回進對話）。檢查邏輯 100% 程式；剩下的邊界是「lint 查段落有沒有，不查數字對不對」。
- **持倉守門與資金紀律（`tools/position_guard.py`，R23–R25）** — 每日把「寫在規則裡靠人記」的機制跑成檢查：R14 新倉 30 天閘、R23 認列桶自峰回撤線（+20% 啟動，自峰 −20%/−30% 各減 1/3，警報自動掛撤）、R8 梯級停利 GTC 缺口、>10% 單倉硬線、檔數上限、財報 ±48h 窗、桶別缺口、旗標逾期；exit 2 = 缺口逐條進 Key Alerts。R24 閒置現金機械停泊 SGOV（券商現金不計息）；R25 避險 sleeve（GLD/XLE）結構性持有、不套動能規則。做不到的單（收盤確認單、選擇權）用 `tg_send.py` 一句話一單推 Telegram 讓人手掛。
- **新想法先回測再進系統（`tools/backtests/`）** — 例：13F 與國會議員抄單，用 House Clerk 官方申報 PDF 做申報日事件回測、用 GURU/GVIP/NANC/KRUZ 實盤 ETF 做代理，α 的 t 值全 <2、申報延遲吃光短期資訊、賣單反指標 → 不加入。結論與腳本留底，可重跑。

## 如何擴展

- **新增 skill**：在 `.claude/skills/<name>/SKILL.md` 建立，frontmatter 設 `user_invocable: true` + `description`，內文遵循 `CLAUDE.md` 的 Step 0 統一規範。
- **新增資料 agent**：純抓資料的子代理用 `data-collector`（Sonnet 4.6）；需要紀律推理的用既有 pattern。
- **新增工具**：放 `tools/`，純標準函式庫優先（如 `thesis_ledger.py` 即零相依），方便他人免裝依賴執行。
- **調整交易風格**：`feedback/*.md`（本機個人檔，已 gitignored）每次 skill 必讀，是把你的偏好餵給框架的地方。

完整規範與設計細節見 [`CLAUDE.md`](../CLAUDE.md)。
