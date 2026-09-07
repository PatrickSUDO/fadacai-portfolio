#!/usr/bin/env python3
"""
tg_send.py — 把一段純文字直接推到 Telegram（動作清單 / 手掛單指令用）。

用途（2026-09-03 用戶指定）：凡 Claude 無法自己執行的單子——收盤確認→隔日執行的
機械單、選擇權開倉（MCP 不支援）——不要等用戶回 session，直接寫成「一句話一單」推
Telegram，讓用戶在 App 手掛。

用法：
  python3 tools/tg_send.py "文字"            # 直接送
  python3 tools/tg_send.py --file path.txt   # 讀檔送
  echo "文字" | python3 tools/tg_send.py -   # stdin
  加 --dry-run 只印不送。

格式規範：純文字、無 markdown；每一單一行，含 標的/方向/股數/限價規則/前提/理由代號；
結尾寫「掛完不用回」——成交由 briefing 自動對帳。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import send_briefing as sb  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help='文字，或 "-" 讀 stdin')
    ap.add_argument("--file", help="從檔案讀文字")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.file:
        text = Path(a.file).read_text(encoding="utf-8")
    elif a.text == "-" or a.text is None:
        text = sys.stdin.read()
    else:
        text = a.text
    text = text.strip()
    if not text:
        print("empty text", file=sys.stderr)
        return 1

    sb.load_env()
    sb.send_telegram(text, dry_run=a.dry_run)
    print(f"telegram {'dry-run' if a.dry_run else 'sent'}: {len(text)} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
