#!/bin/bash
# portfolio_review_runner.sh — 每月全書檢視的無人值守執行器（2026-10-06 用戶：「定期的 portfolio review 可不可以自動化」）
#
# 為什麼：review_due.py 9/14 起已在 30 天到期時直推 Telegram，但「提醒 → 有人開 session 跑」仍靠人；
# 9/3 之後第 33 天才在 10/6 由用戶手動觸發。這支把最後一步交給 launchd，做法同 trade_review_runner.sh：
#   到期（review_due.py portfolio-review 狀態 due/red）→ 美東盤中時窗 → claude -p "/portfolio-review" --model opus
#   → 報告轉 HTML 推報告站 → Telegram 一則（第 0 節 本期結論 + 網頁連結）
# 失敗（登入失效 / 逾時 / 沒產出）也推 Telegram。
#
# 時間以美東為準（memory: feedback-schedule-us-eastern-time）：launchd 每 15 分鐘叫一次，本腳本自判
#   ET 平日 11:30–15:00（盤中：PMCC 掃描與選擇權鏈 OI 要盤中才準）+ 當日 marker（一天只試一次，失敗隔天重試）。
# 手動：bash tools/portfolio_review_runner.sh --force          （忽略到期與時窗）
#       bash tools/portfolio_review_runner.sh --notify-only <md> （只做 HTML + Telegram）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$REPO_ROOT/tools"
LOG_DIR="$REPO_ROOT/briefing-out"
LOG="$LOG_DIR/portfolio-review-runner.log"
export PATH="/Users/supatrick/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TZ=America/New_York
cd "$REPO_ROOT" || exit 1
mkdir -p "$LOG_DIR/cache"
log() { printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG"; }

ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then set -a; source "$ENV_FILE"; set +a; fi

FORCE=false; NOTIFY_ONLY=""
for a in "$@"; do
  case "$a" in
    --force) FORCE=true ;;
    --notify-only) NOTIFY_ONLY="pending" ;;
    *) [[ "$NOTIFY_ONLY" == "pending" ]] && NOTIFY_ONLY="$a" ;;
  esac
done

tg() { printf '%s\n' "$1" | python3 "$SCRIPT_DIR/tg_send.py" - >> "$LOG" 2>&1 || log "tg_send failed"; }

notify_report() {   # $1 = report md path
  local md="$1" stem url=""
  stem="$(basename "$md" .md)"
  # 同一份報告只推一次（2026-10-29：無人值守時 session 內模型跑 --notify-only、runner 收尾又推一次 → Telegram 重複兩則）
  local mark="$LOG_DIR/cache/portfolio-review-notified-${stem}"
  if [[ -f "$mark" && "$mark" -nt "$md" ]]; then log "already notified for ${stem}，跳過重複推送"; return 0; fi
  python3 "$SCRIPT_DIR/generate_html.py" portfolio-review "$md" >> "$LOG" 2>&1
  local rc=$?
  if [[ $rc -eq 0 && -n "${REPORT_SITE_URL:-}" && -n "${REPORT_SITE_TOKEN:-}" ]]; then
    url="${REPORT_SITE_URL}/r/${REPORT_SITE_TOKEN}/portfolio-review/${stem}.html"
  else
    log "generate_html rc=$rc（連結不附）"
  fi
  python3 - "$md" "$url" <<'PY' | python3 "$SCRIPT_DIR/tg_send.py" - >> "$LOG" 2>&1 || log "tg_send failed (report)"
import re, sys
md, url = sys.argv[1], sys.argv[2]
text = open(md, encoding="utf-8").read()
title = text.splitlines()[0].lstrip("# ").strip()
# 優先抽「## 0. 本期結論」；沒有就抽第一個 ## 段
m = re.search(r"## 0\..*?(?=\n## |\n---|\Z)", text, re.S) or re.search(r"\n## .*?(?=\n## |\Z)", text, re.S)
sec = m.group(0).strip() if m else text[:1500]
sec = re.sub(r"^## 0\.\s*", "", sec)
sec = re.sub(r"\*\*(.+?)\*\*", r"\1", sec)
sec = re.sub(r"`([^`]*)`", r"\1", sec)
sec = re.sub(r"^#+\s*", "", sec, flags=re.M)
body = f"📊 {title}\n\n{sec}"
if url:
    body += f"\n\n🔗 完整報告：{url}"
print(body[:3000])
PY
  mkdir -p "$LOG_DIR/cache"; touch "$mark"
}

if [[ -n "$NOTIFY_ONLY" && "$NOTIFY_ONLY" != "pending" ]]; then
  log "notify-only: $NOTIFY_ONLY"; notify_report "$NOTIFY_ONLY"; exit 0
fi

ET_DATE=$(date +%F)
if [[ "$FORCE" != "true" ]]; then
  ET_HM=$(date +%H%M); ET_DOW=$(date +%u)
  (( ET_DOW >= 6 )) && exit 0
  (( 10#$ET_HM < 1130 || 10#$ET_HM > 1500 )) && exit 0
  MARK="$LOG_DIR/cache/portfolio-review-attempt-${ET_DATE}"
  [[ -f "$MARK" ]] && exit 0
  # 假日（借 price_alerts 日曆）
  python3 - <<'PY' || exit 0
import sys; sys.path.insert(0, "tools")
from datetime import datetime
from zoneinfo import ZoneInfo
import price_alerts as pa
sys.exit(0 if pa.is_trading_day(datetime.now(ZoneInfo("America/New_York")).date()) else 1)
PY
  DUE=$(python3 - <<'PY'
import json, subprocess, sys
out = subprocess.run([sys.executable, "tools/review_due.py", "--json"], capture_output=True, text=True).stdout
try:
    d = json.loads(out)
    it = next(i for i in d["items"] if i["key"] == "portfolio-review")
    print(f'{it["status"]} last={it["last"]} days={it["days"]}')
except Exception as e:  # noqa: BLE001
    print(f"unknown err={e}")
PY
)
  case "$DUE" in
    due*|red*|unknown*) log "portfolio-review $DUE → run" ;;
    *) exit 0 ;;
  esac
  touch "$MARK"
fi

REPORT="$LOG_DIR/portfolio-review-${ET_DATE}.md"
CLAUDE_TIMEOUT="${PORTFOLIO_REVIEW_TIMEOUT:-3600}"
log "Running: claude -p \"/portfolio-review\" --model opus (timeout ${CLAUDE_TIMEOUT}s)"
LINES_BEFORE=$(wc -l < "$LOG")
perl -e 'alarm shift; exec @ARGV' "$CLAUDE_TIMEOUT" \
  claude -p "/portfolio-review" --model opus --dangerously-skip-permissions >> "$LOG" 2>&1
RC=$?
if tail -n +"$((LINES_BEFORE + 1))" "$LOG" | grep -qiE "Failed to authenticate|OAuth session expired|OAuth token has expired|Invalid API key|authentication_error"; then
  log "auth failure"
  tg "⚠️ 全書檢視（/portfolio-review）沒跑：Claude CLI 登入失效（${ET_DATE}）
→ 動作：終端機跑 claude setup-token，把新 token 以 CLAUDE_CODE_OAUTH_TOKEN= 寫進 fadacai-portfolio/.env；之後 bash tools/portfolio_review_runner.sh --force 補跑。"
  exit 1
fi
if [[ $RC -ne 0 ]]; then
  log "claude exited rc=$RC"
  [[ $RC -eq 142 ]] && WHY="逾時 ${CLAUDE_TIMEOUT}s" || WHY="exit $RC"
  tg "⚠️ 全書檢視（/portfolio-review）執行失敗：${WHY}（${ET_DATE}）
→ 動作：不用管，明天盤中會自動重試；要立刻補就 bash tools/portfolio_review_runner.sh --force。log 在 briefing-out/portfolio-review-runner.log"
  exit 1
fi
if [[ ! -f "$REPORT" ]]; then
  REPORT="$(ls -t "$LOG_DIR"/portfolio-review-*.md 2>/dev/null | head -1)"
  if [[ -z "$REPORT" || $(( $(date +%s) - $(stat -f %m "$REPORT") )) -gt 7200 ]]; then
    log "no fresh report"
    tg "⚠️ 全書檢視跑完但沒有產出報告檔（${ET_DATE}）
→ 動作：明天盤中會自動重試；log 在 briefing-out/portfolio-review-runner.log"
    exit 1
  fi
fi
log "report: $REPORT"

if [[ -n "$(git status --porcelain)" ]]; then
  git add -A >> "$LOG" 2>&1
  git -c user.name=PatrickSUDO -c user.email=patricksuph@gmail.com commit -q -m "chore(portfolio-review): ${ET_DATE} 自動全書檢視產出（runner 補 commit）" >> "$LOG" 2>&1 \
    && git push -q >> "$LOG" 2>&1 || log "git commit/push failed (non-fatal)"
fi

notify_report "$REPORT"
log "done"
exit 0
