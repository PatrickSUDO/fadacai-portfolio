#!/usr/bin/env python3
"""
review_lint.py — /trade-review 產出檢查。缺段 / 多結論 / 收尾沒做 → exit 2。

  python3 tools/review_lint.py briefing-out/trade-review-YYYY-MM-DD.md   手動
  python3 tools/review_lint.py --hook                                     PostToolUse hook（stdin JSON，
                                                                          只對 briefing-out/trade-review-*.md 觸發）

存在理由：判斷層的規則（獨立 n、2×2、regime 標籤、R26 走向）跳過不留痕跡；
把「沒做」變成程式抓得到的東西，比要模型保證可靠。
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAST = ROOT / "research" / "last-trade-review.txt"
REPORT_RE = re.compile(r"briefing-out/trade-review-(\d{4}-\d{2}-\d{2})\.md$")

REQUIRED = [
    (r"獨立 n", "EV 校準：獨立 n"),
    (r"Brier skill|BSS", "EV 校準：Brier skill score"),
    (r"2×2|對但沒用", "thesis × 定價 2×2"),
    (r"in_range|分布外|分布內", "EV 校準：in_range"),
    (r"R26", "R26 兩指標走向（BSS / holding-α vs SMH）"),
    (r"ledger-audit|巧合", "RULES-LEDGER 巧合欄 / ledger-audit 已跑"),
    (r"## 6\.|該改哪一條規則", "§6 本期結論"),
]


def lint(path: Path) -> list[str]:
    if not path.exists():
        return [f"not found: {path}"]
    text = path.read_text()
    problems = [f"缺：{label}（pattern `{pat}`）" for pat, label in REQUIRED if not re.search(pat, text)]

    m = re.search(r"## 5\..*?(?=## 6\.|\Z)", text, re.S)
    if m:
        sec5 = m.group(0)
        scored = re.search(r"\+\s*命中|\+\s*失效|命中 \+|失效 \+", sec5)
        if scored and not re.search(r"\[(up|down)\]", sec5):
            problems.append("§5 有計分但無 [up]/[down] regime 標籤")
        if not scored and "本期無計分" not in sec5:
            problems.append("§5 無計分卻未寫「本期無計分」")

    m = re.search(r"## 6\..*", text, re.S)
    if m:
        n = len(re.findall(r"\*\*規則：\*\*", m.group(0)))
        if n == 0:
            problems.append("§6 沒有「**規則：**」結論")
        elif n > 2:
            problems.append(f"§6 有 {n} 條結論（最多 2）")

    dm = REPORT_RE.search(str(path))
    if dm:
        want = dm.group(1)
        have = LAST.read_text().strip() if LAST.exists() else ""
        if have != want:
            problems.append(f"research/last-trade-review.txt = '{have}'，應為 {want}")
    return problems


def report(problems, tag="", stream=sys.stdout) -> int:
    if problems:
        print(f"❌ review_lint{tag} {len(problems)} 項：", file=stream)
        for p in problems:
            print("  - " + p, file=stream)
        return 2
    print(f"✅ review_lint{tag} 通過", file=stream)
    return 0


def hook_main() -> int:
    try:
        d = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    f = ((d.get("tool_input") or {}).get("file_path")
         or (d.get("tool_response") or {}).get("filePath") or "")
    if not REPORT_RE.search(f):
        return 0
    return report(lint(Path(f)), tag="（hook，補齊再收尾）", stream=sys.stderr)


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--hook":
        return hook_main()
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    return report(lint(Path(sys.argv[1])))


if __name__ == "__main__":
    sys.exit(main())
