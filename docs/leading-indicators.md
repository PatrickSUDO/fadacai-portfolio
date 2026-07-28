# 發現層先行指標管線（Leading Indicators）

> 動機：財報 gate 是**裁決層**（慢而準），但發現層需要比財報更早的硬數字前哨。
> 設計原則：所有訊號 **display-only（記錄不阻擋）** — 不 gate 任何動作，命中率由 `/trade-review` 驗滿 ≥2 期後才可討論升級硬閘門（與 A4 影子訊號同路徑）。

## 架構

```
tools/fetch_leading.py（briefing_runner 每日預載，TTL 20h）
  ├─ 讀 research/leading-config.json（gitignored 私人配置，範例見下）
  ├─ 寫 briefing-out/cache/leading-indicators.json
  └─ archive_cache.py 每日凍結 → revision 二階導的歷史庫
```

五個 block，各自 try/except 隔離（單塊失敗 → `carried_forward` 沿用前值，不互殺）：

| Block | 內容 | 來源 |
|---|---|---|
| `gauges` | HY OAS Δ5d/Δ20d 速度、VIX/VIX3M 期限結構、半導體寬度（SMH 成分 %>50DMA，成分自動抓 ETF holdings）、**國債曲線**、**半導體行業 PE 溫度計**（Δ5d/Δ20d + 100 日分位）| FRED / yfinance / FMP 免費層 |
| `earnings_crossread` | 財報季 cross-read：早報者（hyperscaler capex、WFE、類比/功率、電力設備）當晚報持倉的讀序 prior | earnings-dates cache + yfinance |
| `pricing_watch` | 記憶體現貨/合約價、功率元件 lead time / 通路庫存 / book-to-bill 新聞關鍵字抽取（純機械、附逐字 excerpt，skill 端 quote-gate 判讀）| EODHD news |
| `revision_delta` | **revision 二階導雙法**：① archive-diff（今日 vs 7d/30d 前快照）② vendor 7d 曲線（EODHD `epsTrend7daysAgo` 等欄位，首日可用）。兩法分列驗命中率，union 供顯示 | fundamentals cache + archive |
| `tw_monthly` | 台股功率元件月營收先行指標（強茂/國巨/富鼎 + 上櫃台半/杰力/德微），YoY 連 2 月走升 = accel、轉負 = 需求證偽候選 | TWSE/TPEx OpenAPI（免金鑰）|

## 防假訊號設計（revision 二階導）

- 只比 `curr_fy` + `next_q`；**`curr_q` 刻意排除**（季度輪替機械性衰減 = 必然假 decel）；期別日期變動 → roll guard 跳過
- 分析師數兩側 ≥8 才合格；coverage 變動 >20% → 壓制旗標（覆蓋率變動 ≠ 估值變動）
- `decel` 定義 = 「上修仍為正但動能顯著縮減」（減速非翻轉）；全部閾值放 config 可調 → 可被 /trade-review 實測裁決

## config 範例（存為 `research/leading-config.json`）

```json
{
  "version": "YYYY-MM-DD",
  "crossread_chains": [
    {"id": "hyperscaler_capex", "label": "Hyperscaler capex → AI 供應鏈",
     "leaders": [{"sym": "GOOGL", "type": "us_earnings", "held": true},
                  {"sym": "META", "type": "us_earnings"}],
     "followers": ["AVGO", "NVDA"],
     "metric": "capex guide（絕對值 + YoY 方向）",
     "read": "capex 上修 → followers 需求 prior 上調"},
    {"id": "tsmc_monthly", "label": "台積電月營收 → AI 半導體全隊",
     "leaders": [{"sym": "TSM", "type": "monthly_rev", "day_of_month": 10, "window_days": [8, 12]}],
     "followers": ["NVDA", "AVGO"], "metric": "月營收 YoY/MoM", "read": "最高頻硬數據"},
    {"id": "memory_asia", "label": "亞洲記憶體 → 美系記憶體",
     "leaders": [{"sym": "SK_HYNIX", "type": "news_only", "news_kw": ["SK hynix"], "recurrence": "季報約 1/4/7/10 月下旬"}],
     "followers": ["MU"], "metric": "HBM/DRAM bit、ASP QoQ", "read": "供給紀律 prior"}
  ],
  "pricing_watch": {
    "lookback_days": 7,
    "memory": {"symbols": ["MU.US", "TSM.US"],
               "keywords": ["DRAM price", "NAND price", "TrendForce", "HBM price", "price hike"]},
    "power": {"symbols": ["ON.US", "DIOD.US"],
              "keywords": ["lead time", "book-to-bill", "channel inventory", "shortage", "ASP"]}
  },
  "breadth": {"universe_label": "SMH top-25（靜態 fallback）", "benchmark": "SMH",
              "tickers": ["NVDA", "TSM", "AVGO", "AMD", "ASML"]},
  "tw_monthly": {"twse": [{"code": "2481", "name": "強茂"}],
                 "tpex": [{"code": "5425", "name": "台半"}]},
  "revision_delta": {
    "windows": [{"days": 7, "tolerance": 3}, {"days": 30, "tolerance": 7}],
    "periods": ["curr_fy", "next_q"], "min_analysts": 8,
    "max_analyst_count_change_pct": 20,
    "decel_net_ratio_drop": 0.20, "decel_rev30_drop_pp": 3.0,
    "decel_net_ratio_drop_30d": 0.30, "decel_rev30_drop_pp_30d": 5.0,
    "book_decel_breadth_floor": 50, "book_decel_momentum_pp": -15,
    "vendor_decel_net30_min": 0.15, "vendor_decel_rev30_min_pct": 1.0,
    "vendor_book_decel_drop_pp": 25
  },
  "gauges_thresholds": {
    "credit": {"widening_fast_5d_bps": 25, "widening_fast_20d_bps": 50,
               "widening_5d_bps": 10, "tightening_5d_bps": -10},
    "vix_term": {"inverted": 1.0, "flattening": 0.95},
    "breadth": {"weak_pct": 40, "strong_pct": 80,
                "divergence_52w_pct": 5, "divergence_breadth_pct": 50}
  }
}
```

## CLI

```bash
python3 tools/fetch_leading.py                 # TTL 內跳過
python3 tools/fetch_leading.py --force         # 強制刷新
python3 tools/fetch_leading.py --force --only gauges,tw_monthly   # 只刷指定 block
DRY_RUN=1 python3 tools/fetch_leading.py --force                  # 只列計畫不寫檔
```

## 消費點

- briefing Step 0.55 載入 + 🚦 一行儀表（全 tier）；Section 4.6 財報 Cross-Read；Section 6 Key Alerts 的 regime-break / 台股轉負 / book_decel 旗標；§9.5 pricing excerpt 作 raw_quote 來源；Telegram T8a/T8b 🚦 區塊
- portfolio-review Step 0.5 + Section F

## 注意事項

- TPEx 憑證鏈在部分環境驗證失敗 → 僅該 host 用 unverified SSL context
- archive-diff 法需快照累積（7d 窗 ~1 週、30d 窗 ~1 月後可用）；vendor 法需 EODHD Fundamentals Data Feed（7d 欄位）
- 台股 accel/轉負旗標需 ≥2 個月度數據點，warm-up 期輸出 null 不猜
- FMP 免費層實測清單（可用 vs 402）見 CLAUDE.md「FMP 免費層實測清單」
