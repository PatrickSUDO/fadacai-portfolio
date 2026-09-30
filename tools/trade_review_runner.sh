#!/bin/bash
# trade_review_runner.sh — 每兩週交易檢討的無人值守執行器（2026-09-29 用戶指定自動化）
#
# 為什麼：/trade-review 的到期提醒 9/14 起已由 review_due.py 直推 Telegram，但「提醒 → 有人開 session 跑」
# 這一步仍靠人；9/29 是第 15 天才由用戶手動跑。這支把最後一步也交給 launchd：
#   到期（review_due.py trade-review 狀態 due/red）→ claude -p "/trade-review" --model fable
#   → 報告轉 HTML 推報告站 → Telegram 一則（§6 本期結論 + 網頁連結）
# 失敗（登入失效 / 逾時 / 沒產出）也推 Telegram——這是兩週一次的工作，靜默失敗的代價是整期規則沒被計分。
#
# launchd：com.fadacai.trade-review（每日 09:30 本地 = 21:30 ET 前一日收盤後）；不到期直接退出，零成本。
# 手動：bash tools/trade_review_runner.sh --force   （忽略到期判定）
#       bash tools/trade_review_runner.sh --notify-only <report.md>   （只做 HTML + Telegram，報告已在）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$REPO_ROOT/tools"
LOG_DIR="$REPO_ROOT/briefing-out"
LOG="$LOG_DIR/trade-review-runner.log"
export PATH="/Users/supatrick/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TZ=America/New_York   # 美東日期為準（2026-09-30）
cd "$REPO_ROOT" || exit 1
mkdir -p "$LOG_DIR"
log() { printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG"; }

# .env：CLAUDE_CODE_OAUTH_TOKEN（長效 token，9/28 互動 OAuth 過期案）、REPORT_SITE_*、Telegram
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
  local md="$1" stem lint_line url=""
  stem="$(basename "$md" .md)"
  if python3 "$SCRIPT_DIR/review_lint.py" "$md" >> "$LOG" 2>&1; then lint_line="產出檢查：通過"; else lint_line="⚠️ 產出檢查未通過（缺段或收尾沒做，看 briefing-out/trade-review-runner.log）"; fi
  # generate_html 預設 push 到 reports repo（Netlify）；exit 2 = HTML 有但 push 失敗
  python3 "$SCRIPT_DIR/generate_html.py" trade-review "$md" >> "$LOG" 2>&1
  local rc=$?
  if [[ $rc -eq 0 && -n "${REPORT_SITE_URL:-}" && -n "${REPORT_SITE_TOKEN:-}" ]]; then
    url="${REPORT_SITE_URL}/r/${REPORT_SITE_TOKEN}/trade-review/${stem}.html"
  else
    log "generate_html rc=$rc（連結不附）"
  fi
  # Telegram：標題 + §6 結論（去 markdown）+ 連結；≤3000 字元（telegram tier 同上限）
  python3 - "$md" "$lint_line" "$url" <<'PY' | python3 "$SCRIPT_DIR/tg_send.py" - >> "$LOG" 2>&1 || log "tg_send failed (report)"
import re, sys
md, lint_line, url = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(md, encoding="utf-8").read()
title = text.splitlines()[0].lstrip("# ").strip()
m = re.search(r"## 6\..*?(?=\n---|\n## |\Z)", text, re.S)
sec6 = m.group(0) if m else "（找不到 §6 結論段）"
sec6 = re.sub(r"^## 6\.\s*", "", sec6.strip())
sec6 = re.sub(r"\*\*(.+?)\*\*", r"\1", sec6)
sec6 = re.sub(r"`([^`]*)`", r"\1", sec6)
sec6 = re.sub(r"^#+\s*", "", sec6, flags=re.M)
body = f"📋 {title}\n\n本期結論：\n{sec6}\n\n{lint_line}"
if url:
    body += f"\n\n🔗 完整報告：{url}"
print(body[:3000])
PY
}

if [[ -n "$NOTIFY_ONLY" && "$NOTIFY_ONLY" != "pending" ]]; then
  log "notify-only: $NOTIFY_ONLY"; notify_report "$NOTIFY_ONLY"; exit 0
fi

# ── 到期判定（日期取檔名 research/last-trade-review.txt，不取 mtime）──
if [[ "$FORCE" != "true" ]]; then
  DUE=$(python3 - <<'PY'
import json, subprocess, sys
out = subprocess.run([sys.executable, "tools/review_due.py", "--json"], capture_output=True, text=True).stdout
try:
    d = json.loads(out)
    it = next(i for i in d["items"] if i["key"] == "trade-review")
    print(f'{it["status"]} last={it["last"]} days={it["days"]}')
except Exception as e:  # noqa: BLE001
    print(f"unknown err={e}")
PY
)
  case "$DUE" in
    due*|red*|unknown*) log "trade-review $DUE → run" ;;
    *) exit 0 ;;   # 不到期，靜默
  esac
fi

TODAY="$(date +%F)"
REPORT="$LOG_DIR/trade-review-${TODAY}.md"
CLAUDE_TIMEOUT="${TRADE_REVIEW_TIMEOUT:-3600}"
log "Running: claude -p \"/trade-review\" --model fable (timeout ${CLAUDE_TIMEOUT}s)"
LINES_BEFORE=$(wc -l < "$LOG")
perl -e 'alarm shift; exec @ARGV' "$CLAUDE_TIMEOUT" \
  claude -p "/trade-review" --model fable --dangerously-skip-permissions >> "$LOG" 2>&1
RC=$?
if tail -n +"$((LINES_BEFORE + 1))" "$LOG" | grep -qiE "Failed to authenticate|OAuth session expired|OAuth token has expired|Invalid API key|authentication_error"; then
  log "auth failure"
  tg "⚠️ 交易檢討（/trade-review）沒跑：Claude CLI 登入失效（${TODAY}）
→ 動作：終端機跑 claude setup-token，把新 token 以 CLAUDE_CODE_OAUTH_TOKEN= 寫進 fadacai-portfolio/.env；之後 bash tools/trade_review_runner.sh --force 補跑。"
  exit 1
fi
if [[ $RC -ne 0 ]]; then
  log "claude exited rc=$RC"
  [[ $RC -eq 142 ]] && WHY="逾時 ${CLAUDE_TIMEOUT}s" || WHY="exit $RC"
  tg "⚠️ 交易檢討（/trade-review）執行失敗：${WHY}（${TODAY}）
→ 動作：開 session 跑 /trade-review，或 bash tools/trade_review_runner.sh --force 重試；log 在 briefing-out/trade-review-runner.log"
  exit 1
fi
if [[ ! -f "$REPORT" ]]; then
  # 模型可能用美東日期命名；找最新一份
  REPORT="$(ls -t "$LOG_DIR"/trade-review-*.md 2>/dev/null | head -1)"
  if [[ -z "$REPORT" || $(( $(date +%s) - $(stat -f %m "$REPORT") )) -gt 7200 ]]; then
    log "no fresh report"
    tg "⚠️ 交易檢討跑完但沒有產出報告檔（${TODAY}）
→ 動作：開 session 跑 /trade-review 補；log 在 briefing-out/trade-review-runner.log"
    exit 1
  fi
fi
log "report: $REPORT"

# 產出留痕：規則帳本 / plan / skill 的改動由模型在 session 內 commit；沒 commit 的補一筆（非致命）
if [[ -n "$(git status --porcelain)" ]]; then
  git add -A >> "$LOG" 2>&1
  git -c user.name=PatrickSUDO -c user.email=patricksuph@gmail.com commit -q -m "chore(trade-review): ${TODAY} 自動檢討產出（runner 補 commit）" >> "$LOG" 2>&1 \
    && git push -q >> "$LOG" 2>&1 || log "git commit/push failed (non-fatal)"
fi

notify_report "$REPORT"
log "done"
exit 0
