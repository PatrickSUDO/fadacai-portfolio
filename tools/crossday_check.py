#!/usr/bin/env python3
"""crossday_check.py — T5.5 跨日一致性檢查（2026-09-14 由散文改為 code）

比對「昨日 telegram.txt」與「今日 telegram.txt」中每個 ticker 的方向詞，找出**無新數據卻反轉**的條目：
  昨日 賣方/警示（減碼、清倉、降桶、停損、勿加碼、旗標…）→ 今日 買方（加碼、買進、起手、補滿…）  或反向
反轉本身不代表錯，但依 T5.5 規則：命中者**當日不得由 T6.5 自動執行**，且 Key Alerts 需一行說明依據。

Usage:
  python3 tools/crossday_check.py briefing-out/2026-09-14-telegram.txt      # 自動找前一份 telegram.txt
  python3 tools/crossday_check.py --hook                                    # PostToolUse（stdin JSON；非 *-telegram.txt 直接 exit 0）
exit 2 = 有反轉（訊息印到 stderr，讓 hook 擋下並要求補說明）；0 = 無。
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "briefing-out"
TICKER = re.compile(r"\b([A-Z]{2,5})\b")
BUY = ("加碼", "買進", "買入", "起手", "補滿", "補倉", "建倉", "進場", "掛買", "second-leg", "補至")
SELL = ("減碼", "賣出", "清倉", "降桶", "停損", "平倉", "砍位", "汰弱", "出清", "減 1/3", "減半")
WARN = ("勿加碼", "禁加碼", "禁向下加碼", "thesis 蒙塵", "降桶候選", "待覆判", "旗標")
IGNORE = {"GTC", "EPS", "ETF", "SMA", "RSI", "MACD", "ATR", "SPY", "SMH", "VIX", "CPI", "FED", "AI", "HBM", "TPE", "ET",
          "PE", "PEG", "EV", "DTE", "OI", "IV", "USD", "BPS", "BCS", "CC", "CSP", "ITM", "OTM", "ATM", "YTD", "MDD",
          "OK", "TODO", "AMC", "BMO", "QQQ", "IGV", "XLK", "XLE", "GLD", "SGOV", "BIL", "URA", "GDX", "XLF", "XLV"}


def stances(path: Path) -> dict:
    """{ticker: {'buy','sell','warn'}} 依行掃描；同一行內 ticker 與方向詞共現即計。"""
    out: dict[str, set] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        tks = [t for t in TICKER.findall(line) if t not in IGNORE]
        if not tks:
            continue
        s = set()
        if any(w in line for w in BUY):
            s.add("buy")
        if any(w in line for w in SELL):
            s.add("sell")
        if any(w in line for w in WARN):
            s.add("warn")
        if not s:
            continue
        for t in tks:
            out.setdefault(t, set()).update(s)
    return out


def prev_file(today_path: Path) -> Path | None:
    files = sorted(OUT_DIR.glob("*-telegram.txt"))
    files = [f for f in files if f.name < today_path.name]
    return files[-1] if files else None


def check(today_path: Path) -> list[str]:
    prev = prev_file(today_path)
    if prev is None:
        return []
    y, t = stances(prev), stances(today_path)
    flags = []
    for tk, ts in t.items():
        ys = y.get(tk)
        if not ys:
            continue
        if "buy" in ts and ({"sell", "warn"} & ys) and "buy" not in ys:
            flags.append(f"⚠️ 跨日反轉：{tk} 昨日{'/'.join(sorted(ys))} → 今日 buy（{prev.name} → {today_path.name}）")
        if "sell" in ts and "buy" in ys and not ({"sell", "warn"} & ys):
            flags.append(f"⚠️ 跨日反轉：{tk} 昨日 buy → 今日 sell（{prev.name} → {today_path.name}）")
    return flags


def report(flags: list[str], stream=sys.stdout) -> int:
    if not flags:
        print("✅ T5.5 跨日一致性：無反轉", file=stream)
        return 0
    print("❌ T5.5 跨日反轉（今日待辦中這些 ticker 不得 T6.5 自動執行；Key Alerts 需一行寫明新依據）：", file=stream)
    for f in flags:
        print("  " + f, file=stream)
    return 2


def hook_main() -> int:
    try:
        d = json.load(sys.stdin)
    except Exception:
        return 0
    f = ((d.get("tool_input") or {}).get("file_path") or "")
    if not f.endswith("-telegram.txt"):
        return 0
    return report(check(Path(f)), stream=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--hook":
        sys.exit(hook_main())
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(report(check(Path(sys.argv[1]))))
