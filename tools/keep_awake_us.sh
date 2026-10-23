#!/bin/bash
# keep_awake_us.sh — 美股盤中防 Mac 睡眠（2026-09-30）
# 為什麼：Mac 在台北時區時，美股盤中是本地 21:30–04:00；9/30 05:55 pmset log 顯示 Mac 進入睡眠，
# 睡著時 price_alerts 不輪詢、15:45/16:20 ET 的機械 pass 不跑（launchd 醒來才補，錯過時窗 = 當天沒 pass）。
# launchd 每 20 分鐘叫一次；ET 09:15–19:05 的平日 → caffeinate -i 25 分鐘（重疊銜接）。時區無關。
ET_HM=$(TZ=America/New_York date +%H%M); ET_DOW=$(TZ=America/New_York date +%u)
(( ET_DOW >= 6 )) && exit 0
(( 10#$ET_HM < 915 || 10#$ET_HM > 1905 )) && exit 0   # 2026-10-23：延到 19:05，覆蓋收盤 pass 時窗（10/22 close pass 跑到一半 Mac 睡著）
exec /usr/bin/caffeinate -i -t 1500
