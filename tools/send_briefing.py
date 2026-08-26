#!/usr/bin/env python3
"""
send_briefing.py — Push daily briefing to Telegram + email via SMTP.

Usage:
  python3 tools/send_briefing.py YYYY-MM-DD   # send specific date
  python3 tools/send_briefing.py latest        # send most recent files

Environment (from .env or shell):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_FROM, EMAIL_TO
  DRY_RUN=1        # print what would be sent, don't actually send
  RETRY_MAX=3      # retry count on send failure (default 3)
"""

import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
BRIEFING_OUT = ROOT / "briefing-out"
LOG_FILE = BRIEFING_OUT / "send-log.jsonl"


# ── .env loader (stdlib only) ───────────────────────────────────────────────
def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                # strip inline comments (e.g. VALUE=foo  # comment)
                v = v.split("#")[0].strip()
                # strip surrounding quotes (single or double)
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                    v = v[1:-1]
                os.environ.setdefault(k.strip(), v)


def require(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


# ── File resolution ─────────────────────────────────────────────────────────
def resolve_date(arg: str) -> str:
    if arg == "latest":
        files = sorted(BRIEFING_OUT.glob("*-telegram.txt"))
        if not files:
            raise FileNotFoundError("No telegram files found in briefing-out/")
        return files[-1].name.replace("-telegram.txt", "")
    # validate YYYY-MM-DD
    datetime.strptime(arg, "%Y-%m-%d")
    return arg


def read_files(date_str: str) -> tuple[str, str]:
    tg_path = BRIEFING_OUT / f"{date_str}-telegram.txt"
    full_path = BRIEFING_OUT / f"{date_str}-full.md"
    if not tg_path.exists():
        raise FileNotFoundError(f"Not found: {tg_path}")
    if not full_path.exists():
        raise FileNotFoundError(f"Not found: {full_path}")
    return tg_path.read_text(encoding="utf-8"), full_path.read_text(encoding="utf-8")


# ── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_TG_CHARS = 4096


def split_message(text: str, limit: int = MAX_TG_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        # split at last newline before limit
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts


def send_telegram(text: str, dry_run: bool = False) -> None:
    token = require("TELEGRAM_BOT_TOKEN")
    chat_id = require("TELEGRAM_CHAT_ID")
    url = TELEGRAM_API.format(token=token)

    for i, part in enumerate(split_message(text)):
        if dry_run:
            print(f"[DRY-RUN] Telegram → chat_id={chat_id} part {i+1}/{len(split_message(text))}")
            print(part[:200] + ("…" if len(part) > 200 else ""))
            continue
        payload = json.dumps({"chat_id": chat_id, "text": part}).encode()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                raise RuntimeError(f"Telegram API error: {result}")


# ── Markdown → plain text ────────────────────────────────────────────────────
def md_to_plain(text: str) -> str:
    """Strip markdown syntax so plain-text email clients (Gmail) read cleanly."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()

        # Table separator row  |---|---|  → skip entirely
        if re.match(r'^\|[\s\-|:]+\|?\s*$', stripped):
            continue

        # Table data row  |col1|col2|  → cells joined by two spaces
        if stripped.startswith('|') and stripped.endswith('|'):
            cells = [c.strip() for c in stripped[1:-1].split('|')]
            out.append('  '.join(cells))
            continue

        # ATX headers  ## Title
        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if m:
            level, title = len(m.group(1)), m.group(2)
            # strip inline markers inside the title
            title = re.sub(r'\*+([^*]+)\*+', r'\1', title)
            title = re.sub(r'_([^_]+)_', r'\1', title)
            if level == 1:
                out.append(title.upper())
                out.append('=' * len(title))
            elif level == 2:
                out.append(f'\n{title}')
                out.append('─' * len(title))
            else:
                out.append(title)
            continue

        # Horizontal rule  ---  ***
        if re.match(r'^[-*_]{3,}\s*$', stripped):
            out.append('─' * 40)
            continue

        # Blockquote  > text  → strip leading >
        line = re.sub(r'^>\s?', '', line)

        # Bold / italic  **x**, *x*, _x_
        line = re.sub(r'\*{2,3}([^*\n]+)\*{2,3}', r'\1', line)
        line = re.sub(r'\*([^*\n]+)\*', r'\1', line)
        line = re.sub(r'_([^_\n]+)_', r'\1', line)

        # Inline code  `x`
        line = re.sub(r'`([^`]+)`', r'\1', line)

        # Links  [text](url)  → text
        line = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', line)

        # Unordered list markers  - / *
        line = re.sub(r'^(\s*)[-*]\s+', r'\1• ', line)

        out.append(line)

    return '\n'.join(out)


# ── Email (SMTP) ─────────────────────────────────────────────────────────────
def send_email(telegram_text: str, full_md: str, date_str: str,
               dry_run: bool = False) -> None:
    smtp_host = require("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = require("SMTP_USER")
    smtp_pass = require("SMTP_PASS")
    email_from = os.environ.get("EMAIL_FROM", smtp_user)
    email_to = require("EMAIL_TO")

    subject = f"📊 Daily Briefing {date_str}"
    body_plain = f"{telegram_text}\n\n{'─' * 40}\n\n{md_to_plain(full_md)}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    msg.attach(MIMEText(body_plain, "plain", "utf-8"))

    if dry_run:
        print(f"[DRY-RUN] Email → {email_to}  subject: {subject}")
        print(telegram_text[:200] + "…")
        return

    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(email_from, [email_to], msg.as_string())


# ── Logging ───────────────────────────────────────────────────────────────────
def already_sent_today(date_str: str) -> bool:
    """Return True if send-log already has a fully successful (non-dry-run) entry for date_str."""
    if not LOG_FILE.exists():
        return False
    for line in LOG_FILE.read_text().splitlines():
        try:
            entry = json.loads(line)
            if (entry.get("date") == date_str
                    and not entry.get("dry_run")
                    and entry.get("telegram") == "ok"
                    and entry.get("email") == "ok"):
                return True
        except json.JSONDecodeError:
            continue
    return False


def write_log(entry: dict) -> None:
    BRIEFING_OUT.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Retry wrapper ─────────────────────────────────────────────────────────────
def with_retry(fn, label: str, max_retries: int) -> bool:
    for attempt in range(1, max_retries + 1):
        try:
            fn()
            return True
        except Exception as e:
            print(f"[{label}] attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                time.sleep(3 * attempt)
    return False


# ── HTML generation helper ─────────────────────────────────────────────────────
def _generate_html(date_str: str, dry_run: bool) -> str | None:
    """Call generate_html.py and return the public URL on success, or None on failure.

    Returns empty string if site URL/token not configured (skip silently).
    """
    token = os.environ.get("REPORT_SITE_TOKEN", "")
    site_url = os.environ.get("REPORT_SITE_URL", "")
    repo_path = os.environ.get("REPORTS_REPO_PATH", "")
    if not (token and site_url and repo_path):
        return ""  # not configured, skip

    script = ROOT / "tools" / "generate_html.py"
    cmd = [sys.executable, str(script), "briefing", date_str, "--push"]
    if dry_run:
        print(f"[DRY-RUN] HTML 生成 + push → {site_url}/r/{token}/briefing/{date_str}.html")
        return f"{site_url}/r/{token}/briefing/{date_str}.html"
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode in (0, 2):  # 0=ok, 2=push failed (repo not ready) but HTML written
            url = f"{site_url}/r/{token}/briefing/{date_str}.html"
            if result.returncode == 2:
                print(f"[send_briefing] ⚠️ HTML 已生成但 push 失敗，連結暫不附加")
                return None
            return url
        print(f"[send_briefing] ⚠️ generate_html 失敗 (exit {result.returncode})")
        if result.stderr:
            print(result.stderr[:300])
        return None
    except subprocess.TimeoutExpired:
        print("[send_briefing] ⚠️ generate_html 逾時（60s）")
        return None
    except Exception as e:
        print(f"[send_briefing] ⚠️ generate_html 例外：{e}")
        return None


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> int:
    load_env()

    dry_run = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")
    max_retries = int(os.environ.get("RETRY_MAX", "3"))

    if len(sys.argv) < 2:
        print("Usage: send_briefing.py YYYY-MM-DD | latest")
        return 1

    try:
        date_str = resolve_date(sys.argv[1])
        tg_text, full_md = read_files(date_str)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        return 1

    # Guard: skip if already fully sent today (prevents duplicate from runner retry)
    # FORCE_RESEND=1 bypasses the guard for intentional manual re-sends (updated content)
    force_resend = os.environ.get("FORCE_RESEND", "").strip() in ("1", "true", "yes")
    if not dry_run and not force_resend and already_sent_today(date_str):
        print(f"⏭️  {date_str} 已成功發送過，跳過重複發送")
        return 0

    log_entry: dict = {
        "date": date_str,
        "sent_at": datetime.now(tz=timezone.utc).isoformat(),
        "dry_run": dry_run,
        "telegram": None,
        "email": None,
        "html": None,
    }

    # ── HTML generation (best-effort, runs before send so link can be appended)
    html_url = _generate_html(date_str, dry_run)
    if html_url:
        tg_text = tg_text.rstrip() + f"\n\n🔗 網頁版：{html_url}"
        log_entry["html"] = "ok"
    else:
        log_entry["html"] = "failed" if html_url is None else "skipped"

    # ── Telegram
    tg_ok = with_retry(
        lambda: send_telegram(tg_text, dry_run),
        "Telegram", max_retries
    )
    log_entry["telegram"] = "ok" if tg_ok else "failed"
    if not tg_ok:
        # 失敗只記 log，不推 Telegram 錯誤訊息（用戶偏好：Telegram 只收正式 briefing）
        print(f"[send_briefing] {date_str} Telegram 推送失敗（已重試 {max_retries} 次），詳見 send-log.jsonl")

    # ── Email (independent of Telegram success)
    email_ok = with_retry(
        lambda: send_email(tg_text, full_md, date_str, dry_run),
        "Email", max_retries
    )
    log_entry["email"] = "ok" if email_ok else "failed"

    write_log(log_entry)

    if tg_ok and email_ok:
        print(f"✅ {date_str} Telegram 已發送 / Email 已寄出")
        return 0
    elif tg_ok or email_ok:
        print(f"⚠️ {date_str} 部分成功 — "
              f"Telegram: {'ok' if tg_ok else 'failed'}, "
              f"Email: {'ok' if email_ok else 'failed'}")
        return 1
    else:
        print(f"❌ {date_str} Telegram + Email 均失敗")
        return 2


if __name__ == "__main__":
    sys.exit(main())
