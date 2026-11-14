#!/bin/bash
# reentry_ev_runner.sh — 撿回名單的收盤後評估（2026-11-12 用戶「這環節能否自動化，我看數據決定即可」）
#
# 為什麼：撿回候選到價、修正方向也過了之後，還缺一個 365 日 EV 才能對 R35 門檻判定；原本要用戶手動叫 /stock-analysis
# （11/9–11/12 四檔連卡三天）。這支由 evening_pass.sh 收盤後那一輪結尾同步呼叫：
#   reentry_gate.py scan（順便把每檔的修正數字、財報日、併購申報存好）→ 缺 EV 的（每天最多 6 檔，已到價的優先，
#   其次是離觸發線最近的——還沒到價也先算）跑 /stock-analysis T --reentry → 再 scan 一次
#   → tg_flag_decisions.py ask 把決定卡（只剩併購類特殊情況）送成 Telegram 按鈕。
# 2026-11-13 用戶「改」：過門檻的不再送卡，由隔天早上 briefing 拿即時價跑 reentry_gate.py live、直接掛起手倉。
# 不過門檻的安靜登影子。分析失敗只推一則 Telegram，隔 3 天再試。
# 2026-11-13 用戶「所有要跑 stock analysis 的警報都自動」：佇列也含觀察警報的名字（未持有個股的到價警報，
#   reentry_gate.py candidates 的 source=watch）；這類過門檻一律送決定卡，不自動買。
#
# 權限（不用 --dangerously-skip-permissions）：分析用的 claude 走一般權限模式。
#   券商的下單／撤單／預覽工具不在任何允許清單，下面再明列禁止（禁止優先於允許）；
#   會下單、發訊息、改警報或改決定帳的本 repo 腳本也明列禁止。
#   注意：專案 .claude/settings.json 本來就允許所有 shell 指令，所以這裡擋的是「列名的危險動作」，不是整個 shell。
#   買單只由早上的 briefing 照 reentry_gate.py live 的輸出掛（T6.5，≤ $3,000）；本腳本與它叫起來的分析都不下單。
#
# 一天一次（marker），時窗 ET 16:15–21:00；手動：bash tools/reentry_ev_runner.sh --force
# REENTRY_EV_ANALYZE=0 → 只跑閘門與送卡，不跑分析。
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$REPO_ROOT/tools"
LOG_DIR="$REPO_ROOT/briefing-out"
LOG="$LOG_DIR/reentry-ev-runner.log"
export PATH="/Users/supatrick/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TZ=America/New_York
cd "$REPO_ROOT" || exit 1
mkdir -p "$LOG_DIR/cache"
log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }
tg() { printf '%s\n' "$1" | python3 "$SCRIPT_DIR/tg_send.py" - >> "$LOG" 2>&1 || log "tg_send failed"; }
ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then set -a; source "$ENV_FILE"; set +a; fi

FORCE=false; [[ "${1:-}" == "--force" ]] && FORCE=true
ET_DATE="$(date +%F)"; ET_HM=$(date +%H%M)
MARK="$LOG_DIR/cache/reentry-ev-${ET_DATE}.done"
if [[ "$FORCE" != "true" ]]; then
  (( 10#$ET_HM < 1615 || 10#$ET_HM > 2100 )) && exit 0
  [[ -f "$MARK" ]] && exit 0
fi
touch "$MARK"

gate() { perl -e 'alarm shift; exec @ARGV' 900 uv run --directory "$SCRIPT_DIR" python3 "$SCRIPT_DIR/reentry_gate.py" "$@" >> "$LOG" 2>> "$LOG_DIR/reentry-ev-runner.err"; }

log "scan #1"
gate scan || { log "scan #1 failed rc=$?"; tg "⚠️ 撿回閘門沒跑成（${ET_DATE}）：reentry_gate.py scan 失敗
→ 動作：不用處理，明天收盤後會再跑；連兩天失敗再開 session 看 briefing-out/reentry-ev-runner.log"; exit 1; }

QUEUE=""
[[ "${REENTRY_EV_ANALYZE:-1}" == "1" ]] && QUEUE=$(python3 "$SCRIPT_DIR/reentry_gate.py" queue)
CLAUDE_TIMEOUT="${REENTRY_EV_TIMEOUT:-2400}"
# 允許清單：分析會用到的資料工具（專案設定未列的 MCP 工具在無人值守模式下預設被拒，所以要明列）。
ALLOW=(
  Read Glob Grep Write Edit Skill Agent ToolSearch
  "mcp__yfinance-advanced__*" "mcp__sec-edgar-mcp__*" "mcp__technical__*" "mcp__eodhd-mcp__*" "mcp__fmp-mcp__*"
  mcp__firstrade-server__get_single_quote mcp__firstrade-server__get_watchlist_quote
)
# 禁止清單：下單、撤單、發訊息、改警報、改決定帳、改成交帳與旗標。
DENY=(
  mcp__firstrade-server__place_stock_order mcp__firstrade-server__place_option_order mcp__firstrade-server__place_option_spread
  mcp__firstrade-server__cancel_order mcp__firstrade-server__preview_stock_order mcp__firstrade-server__preview_option_order
  mcp__firstrade-server__preview_option_spread
  "Bash(python3 tools/auto_exec.py:*)" "Bash(python3 tools/tg_send.py:*)" "Bash(python3 tools/send_briefing.py:*)"
  "Bash(python3 tools/price_alerts.py:*)" "Bash(python3 tools/decision_ledger.py:*)" "Bash(python3 tools/tg_flag_decisions.py:*)"
  "Bash(python3 tools/trade_ledger.py:*)" "Bash(python3 tools/reentry_gate.py:*)"
  "Bash(bash tools/evening_pass.sh:*)" "Bash(bash tools/briefing_runner.sh:*)"
)
for T in $QUEUE; do
  [[ "$T" =~ ^[A-Z.]{1,6}$ ]] || { log "skip bad ticker: $T"; continue; }
  log "Running: /stock-analysis $T --reentry（opus，允許清單模式，timeout ${CLAUDE_TIMEOUT}s）"
  LINES_BEFORE=$(wc -l < "$LOG")
  perl -e 'alarm shift; exec @ARGV' "$CLAUDE_TIMEOUT" \
    claude -p "/stock-analysis $T --reentry" --model opus \
      --allowedTools "${ALLOW[@]}" --disallowedTools "${DENY[@]}" >> "$LOG" 2>&1
  RC=$?
  if tail -n +"$((LINES_BEFORE + 1))" "$LOG" | grep -qiE "Failed to authenticate|OAuth session expired|OAuth token has expired|Invalid API key|authentication_error"; then
    log "auth failure"
    python3 "$SCRIPT_DIR/reentry_gate.py" mark-run "$T" fail
    tg "⚠️ 撿回評估沒跑：Claude CLI 登入失效（${ET_DATE}）
→ 動作：終端機跑 claude setup-token，把新 token 以 CLAUDE_CODE_OAUTH_TOKEN= 寫進 fadacai-portfolio/.env；之後 bash tools/reentry_ev_runner.sh --force 補跑。"
    exit 1
  fi
  # 成功的定義：預測帳裡出現今天的 365 日 EV（不看 exit code——跑完但沒登帳也算失敗）
  if python3 "$SCRIPT_DIR/reentry_gate.py" has-ev "$T" "$ET_DATE"; then
    log "$T ok (rc=$RC)"
    python3 "$SCRIPT_DIR/reentry_gate.py" mark-run "$T" ok
  else
    [[ $RC -eq 142 ]] && WHY="逾時 ${CLAUDE_TIMEOUT} 秒" || WHY="跑完但預測帳沒有今天的 365 日 EV（exit $RC）"
    log "$T failed: $WHY"
    python3 "$SCRIPT_DIR/reentry_gate.py" mark-run "$T" fail
    tg "⚠️ 撿回評估失敗：${T}（${ET_DATE}）——${WHY}
→ 動作：不用處理，3 天後自動重試；要馬上看就開 session 跑 /stock-analysis ${T} --reentry"
  fi
done

if [[ -n "$QUEUE" ]]; then
  log "scan #2"
  gate scan || log "scan #2 failed rc=$?"
fi
python3 "$SCRIPT_DIR/reentry_gate.py" status >> "$LOG" 2>&1
log "ask（決定卡 → Telegram 按鈕）"
python3 "$SCRIPT_DIR/tg_flag_decisions.py" ask >> "$LOG" 2>> "$LOG_DIR/reentry-ev-runner.err" || log "tg_flag_decisions ask failed (non-fatal)"
exit 0
