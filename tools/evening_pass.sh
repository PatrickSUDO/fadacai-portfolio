#!/bin/bash
# evening_pass.sh <preclose|close> — 機械執行 pass（2026-09-15，MYRG 手動案）
#
# 為什麼：原本 auto_exec 早上 11:00 ET 才由 briefing 執行前一收盤的判定，中間隔一夜 + 開盤 90 分鐘；
# 防守線警報又在盤中每天一發。MYRG $274 線 8/27–9/15 來回觸價、用戶收一堆通知、最後自己手動賣。
#
#   preclose（21:45 本地 = 15:45 ET）：即時價當準收盤、線多破 0.5% 才算 → day 限價貼盤，收盤前成交，沒成交自動失效
#   close   （22:20 本地 = 16:20 ET）：真正收盤重算 → 補網：15:45 沒抓到/沒成交的掛 gt90 隔日生效；ingest 今日成交讓 R23 峰值重置
# 兩支都：guard --sync-alerts → auto_exec --execute（AUTO_EXEC_LIVE=1）→ 有動作才發一則 Telegram。
# launchd：com.fadacai.auto-exec-preclose（21:45）、com.fadacai.auto-exec-evening（22:20）。
set -uo pipefail
PASS="${1:-close}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$REPO_ROOT/tools"
LOG_DIR="$REPO_ROOT/briefing-out"
LOG="$LOG_DIR/evening-pass.log"
export PATH="/Users/supatrick/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd "$REPO_ROOT" || exit 1
log() { printf '[%s] [%s] %s\n' "$(date '+%F %T')" "$PASS" "$*" >> "$LOG"; }

# 交易日檢查（借 price_alerts 的日曆）
if ! python3 - <<'PY'
import sys; sys.path.insert(0, "tools")
from datetime import datetime
from zoneinfo import ZoneInfo
import price_alerts as pa
sys.exit(0 if pa.is_trading_day(datetime.now(ZoneInfo("America/New_York")).date()) else 1)
PY
then log "non-trading day, skip"; exit 0; fi

if [[ "$PASS" == "close" ]]; then
  log "ingest today's fills + snapshot orders（讓 guard 看到 pre-close 的成交 → R23 峰值重置）"
  python3 "$SCRIPT_DIR/trade_ledger.py" snapshot-orders >> "$LOG" 2>&1 || log "snapshot failed (continuing)"
  python3 "$SCRIPT_DIR/trade_ledger.py" ingest --range today >> "$LOG" 2>&1 || log "ingest failed (continuing)"
fi

log "guard --sync-alerts"
uv run --directory "$SCRIPT_DIR" python3 "$SCRIPT_DIR/position_guard.py" --sync-alerts --render-plan >> "$LOG" 2>&1 || log "guard exit $? (continuing)"

FLAG=""; [[ "$PASS" == "preclose" ]] && FLAG="--preclose"
log "auto_exec --execute $FLAG"
AUTO_EXEC_LIVE=1 uv run --directory "$SCRIPT_DIR" python3 "$SCRIPT_DIR/auto_exec.py" --execute $FLAG >> "$LOG" 2>&1
RC=$?
log "auto_exec rc=$RC（5 = state 非 live 拒絕執行）"

# Telegram 一則摘要（只在有動作 / 有錯 / 被拒時發）
python3 - "$RC" "$PASS" <<'PY' | python3 "$SCRIPT_DIR/tg_send.py" - >> "$LOG" 2>&1 || log "tg_send failed"
import json, sys
rc, pas = sys.argv[1], sys.argv[2]
d = json.load(open("briefing-out/cache/auto-exec-plan.json"))
if d.get("mode") == "aborted":
    print(f"⛔ 機械執行被拒（{pas}）：{d.get('reason')}\n→ 動作：Firstrade session 掉了，開 session 跑 /mcp-health 或等下一次 pass；本次無任何單送出")
    sys.exit(0)
ex = d.get("executed") or []
placed = [e for e in ex if e.get("status") == "placed"]
cancelled = [e for e in ex if e.get("status") == "cancelled"]
errors = [e for e in ex if e.get("status") == "error"]
manual = [p for p in d.get("plan", []) if p.get("action") == "CLOSE_SPREAD"]
if not (placed or cancelled or errors or manual):
    sys.exit(0)  # 無事不發
# 口吻：講人話。一行一件事，寫「做了什麼、為什麼、你要不要動」，不寫規則代號和內部欄位（用戶 9/16：「很難懂，簡潔直白一點」）
WHY = {"R23": "跌破自峰回撤線，減碼", "user": "跌破你定的收盤線，減碼", "R25": "Fed 升息，避險部位補到 8%",
       "R30": "強勢股回檔，加碼", "R24": "現金停泊", "R8": "梯級停利", "options": "選擇權管理線"}
def why(rule):
    return WHY.get((rule or "").split("-")[0], rule)
act_zh = {"BUY": "買", "SELL": "賣"}
when = "收盤前" if pas == "preclose" else "收盤後"
lines = [f"{when}自動下單（{d.get('asof')}）"]
for e in placed:
    kind = "今天收盤前成交" if e.get("duration") == "day" else "明天開盤生效"
    lines.append(f"已{act_zh.get(e['action'], e['action'])} {e['symbol']} {e.get('qty')} 股 @{e.get('limit')}，{why(e['rule'])}，{kind}。單號 {e.get('order_id')}")
for e in cancelled:
    lines.append(f"已撤 {e['symbol']} 的舊單，{why(e['rule'])}條件已變。")
for e in errors:
    lines.append(f"失敗：{e['symbol']} {act_zh.get(e['action'], e['action'])} {e.get('qty')} 股（{why(e['rule'])}）沒送出。原因：{(e.get('error') or str(e.get('broker') or ''))[:80]}。我會修，修好補下。")
for p in manual:
    lines.append(f"要你手動掛：{p['symbol']} 複式單，{p.get('basis','')[:60]}")
if not (placed or cancelled or errors or manual):
    sys.exit(0)
lines.append("你不用做任何事。" if not (errors or manual) else "只有上面標「要你手動掛」的需要你。")
print("\n".join(lines))
PY
exit 0
