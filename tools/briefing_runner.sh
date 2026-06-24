#!/usr/bin/env bash
# briefing_runner.sh — launchd entry point for daily briefing push.
#
# Called by com.fadacai.briefing.plist at 14:00 台灣時間 (Asia/Taipei) on
# weekdays — one attempt per day, no backup windows. 台股 13:30 收盤後、盤後
# 三大法人買賣超約 14:00 前公布。
# Checks TWSE calendar, adds --codex on Fridays, then invokes Claude CLI.

set -euo pipefail

# Report/log/trading-day timestamps stay on Taiwan market time (Asia/Taipei).
# NOTE: TZ lives here, NOT in the plist's EnvironmentVariables — keeping it out
# of the plist means launchd's StartCalendarInterval is evaluated in the system
# local timezone, so the job fires at the wall-clock time we set.
: "${TZ:=Asia/Taipei}"
export TZ

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$REPO_ROOT/briefing-out"

mkdir -p "$LOG_DIR"

# ── Load .env ──────────────────────────────────────────────────────────────
ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

RETRY_MAX="${RETRY_MAX:-3}"
FRIDAY_CODEX="${FRIDAY_CODEX:-true}"
SKIP_NON_TRADING="${SKIP_NON_TRADING_DAYS:-true}"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# ── TWSE calendar check ────────────────────────────────────────────────────
if [[ "$SKIP_NON_TRADING" == "true" ]]; then
  if ! python3 "$SCRIPT_DIR/check_trading_day.py"; then
    log "Non-trading day — exiting without briefing"
    exit 0
  fi
fi

# ── Friday → add --codex ───────────────────────────────────────────────────
DOW=$(python3 -c "from datetime import date; print(date.today().weekday())")  # 4 = Friday
CODEX_FLAG=""
if [[ "$FRIDAY_CODEX" == "true" && "$DOW" == "4" ]]; then
  CODEX_FLAG="--codex"
  log "Friday detected — appending --codex"
fi

# ── Pre-load data caches (non-fatal) ──────────────────────────────────────
log "Refreshing macro cache (FinMind 台灣總經)..."
uv run --directory "$SCRIPT_DIR" python3 "$SCRIPT_DIR/fetch_macro.py" \
  >> "$LOG_DIR/launchd.log" 2>> "$LOG_DIR/launchd.err" \
  || log "macro refresh failed (non-fatal, briefing continues with stale/missing cache)"

log "Refreshing earnings cache (FinMind 財報/月營收)..."
uv run --directory "$SCRIPT_DIR" python3 "$SCRIPT_DIR/earnings_history.py" \
  >> "$LOG_DIR/launchd.log" 2>> "$LOG_DIR/launchd.err" \
  || log "earnings refresh failed (non-fatal, briefing continues with stale/missing cache)"

log "Refreshing fundamentals cache (FinMind)..."
uv run --directory "$SCRIPT_DIR" python3 "$SCRIPT_DIR/fetch_fundamentals.py" \
  >> "$LOG_DIR/launchd.log" 2>> "$LOG_DIR/launchd.err" \
  || log "fundamentals refresh failed (non-fatal, briefing continues with stale/missing cache)"

log "Refreshing news cache (中文新聞 raw articles)..."
uv run --directory "$SCRIPT_DIR" python3 "$SCRIPT_DIR/fetch_news.py" \
  >> "$LOG_DIR/launchd.log" 2>> "$LOG_DIR/launchd.err" \
  || log "news refresh failed (non-fatal, briefing continues without news cache)"

# ── Invoke Claude CLI ──────────────────────────────────────────────────────
# Must cd to REPO_ROOT so Claude Code finds .claude/skills/ and project settings
cd "$REPO_ROOT"

PROMPT="/briefing telegram --send $CODEX_FLAG"
log "Running: claude -p \"$PROMPT\" (cwd: $REPO_ROOT)"


attempt=0
success=false
while [[ $attempt -lt $RETRY_MAX ]]; do
  attempt=$((attempt + 1))
  log "Attempt $attempt/$RETRY_MAX"

  # Wrap in a hard timeout (default 900s) so a hung headless claude -p
  # can't block for hours — alarm kills it and the retry loop takes over.
  # macOS has no `timeout`; perl's alarm is built-in and portable.
  CLAUDE_TIMEOUT="${CLAUDE_TIMEOUT:-900}"
  # --dangerously-skip-permissions: this is an unattended trusted run on the
  # user's own repo; without it, any Claude Code tool-permission prompt has no
  # way to be answered headless and the job hangs until the alarm timeout.
  # (NOTE: this does NOT bypass macOS TCC file-access dialogs — those need
  #  Full Disk Access granted to /bin/bash. See docs/briefing-auto-send.md.)
  if perl -e 'alarm shift; exec @ARGV' "$CLAUDE_TIMEOUT" claude -p "$PROMPT" --dangerously-skip-permissions >> "$LOG_DIR/launchd.log" 2>> "$LOG_DIR/launchd.err"; then
    log "Claude briefing completed successfully"
    success=true
    break
  else
    EXIT_CODE=$?
    if [[ $EXIT_CODE -eq 142 ]]; then
      log "Claude TIMED OUT after ${CLAUDE_TIMEOUT}s (alarm) — treating as failure"
    fi
    log "Claude exited with code $EXIT_CODE"
    if [[ $attempt -lt $RETRY_MAX ]]; then
      log "Retrying in $((attempt * 30))s…"
      sleep $((attempt * 30))
    fi
  fi
done

if [[ "$success" != "true" ]]; then
  # 失敗只記 log，不推 Telegram 錯誤訊息（用戶偏好：Telegram 只收正式 briefing）
  log "All $RETRY_MAX attempts failed — see briefing-out/launchd.err (no Telegram error notify by design)"
  exit 1
fi
