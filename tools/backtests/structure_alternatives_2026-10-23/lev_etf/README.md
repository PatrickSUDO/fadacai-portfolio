# 槓桿 ETF 量化評估（2026-10-23）
重跑順序：python3 download.py → t1_standalone.py → t2_beta_pair.py → t3_parking.py → t4_satellite.py → t5_r15.py → t6_extra.py → t7_ytd.py；cat out_t*.md > ALL_TABLES.md
資料：yfinance auto_adjust 收盤，→2026-10-22；T-bill 日報酬 = ^IRX/100/252（前值補）。
Sharpe = (CAGR − 期間平均 rf) / 年化波動（與 repo account_metrics 同口徑）。
費用率為記憶中的發行商數字（SOXL 0.75 / TQQQ 0.84 / QLD 0.95 / SSO 0.89 / SPXL、UPRO 0.91 / TECL 0.94 / USD 0.95），未即時查證。
