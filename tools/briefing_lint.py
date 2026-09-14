#!/usr/bin/env python3
"""
briefing_lint.py — R27 / H10 表述規則的機械檢查（2026-09-14，原本靠模型自律）。

  python3 tools/briefing_lint.py <檔案>        手動（briefing-out/*.md、*telegram.txt、journal/*.md）
  python3 tools/briefing_lint.py --hook         PostToolUse hook（stdin JSON；只對上述路徑觸發）

R27（認列桶只准機械線表述）：
  凡一行同時出現「認列桶 ticker」與「thesis 完好 / intact / 未破 / thesis 沒壞」，卻沒有任何機械線字樣
  （距 / 線 / 級距 / deadline / 減碼 / % / R23 / R8）→ 違規。信念桶不受限。
H10（新倉 starter ≤2%；priced_in_pct > +150% 者 ≤1.5%）：
  journal 檔：讀 position-state，找 open_since == 檔名日期 的現股新倉；權重超門檻而全文無「H10 bypass」→ 違規。
  是偏好不是硬線：標了 bypass 就過，只是要留痕給 /trade-review 分組計分。

exit 2 = 有違規（hook 走 stderr 提示，不擋寫入）。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROSTER = ROOT / "research" / "roster.json"
STATE = ROOT / "research" / "position-state.json"
FUND = ROOT / "briefing-out" / "cache" / "fundamentals-snapshot.json"
PATH_RE = re.compile(r"(briefing-out/[^/]+\.(md|txt)|journal/(\d{4}-\d{2}-\d{2})\.md)$")
INTACT_RE = re.compile(r"thesis\s*(完好|intact|未破|沒壞|無恙)|基本面完好", re.I)
MECH_RE = re.compile(r"距|線|級距|deadline|減碼|%|R23|R8|梯|旗標")
H10_CAP, H10_CAP_PRICEDIN, PRICEDIN_TH = 2.0, 1.5, 150.0


def _load(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:  # noqa: BLE001
        return default


def lint_r27(text, harvest_syms):
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if not INTACT_RE.search(line):
            continue
        syms = [s for s in harvest_syms if re.search(rf"\b{re.escape(s)}\b", line)]
        if syms and not MECH_RE.search(line):
            out.append(f"L{i} R27：認列桶 {','.join(syms)} 只寫「thesis 完好」無機械線距離（距線 ±X% / 累計減碼 vs 級距 / 旗標 deadline）")
    return out


def lint_h10(text, journal_date):
    st = _load(STATE, {})
    fund = _load(FUND, {})
    fund = fund.get("tickers", fund)
    out = []
    if "H10 bypass" in text:
        return out
    for p in st.get("positions", []):
        if p.get("open_since") != journal_date or p.get("weight_pct") is None:
            continue
        if p.get("bucket") in ("sleeve(ETF)",) or p["symbol"] in (st.get("cash_equivalents") or []):
            continue
        pin = ((fund.get(p["symbol"]) or {}).get("self_valuation") or {}).get("priced_in_pct")
        cap = H10_CAP_PRICEDIN if (pin is not None and pin > PRICEDIN_TH) else H10_CAP
        if p["weight_pct"] > cap:
            out.append(f"H10：新倉 {p['symbol']} 起手 {p['weight_pct']:.1f}% > {cap}%"
                       + (f"（priced_in {pin:+.0f}% > +150%）" if cap == H10_CAP_PRICEDIN else "")
                       + " 且 journal 無「⚠️ H10 bypass」標記 → 補標（偏好非硬線，但要留痕分組計分）")
    return out


def lint(path: Path):
    if not path.exists():
        return [f"not found: {path}"]
    text = path.read_text()
    roster = _load(ROSTER, {})
    harvest = list((roster.get("buckets") or {}).get("認列", []))
    problems = lint_r27(text, harvest)
    m = re.search(r"journal/(\d{4}-\d{2}-\d{2})\.md$", str(path))
    if m:
        problems += lint_h10(text, m.group(1))
    return problems


def report(problems, tag="", stream=sys.stdout):
    if problems:
        print(f"❌ briefing_lint{tag} {len(problems)} 項：", file=stream)
        for p in problems:
            print("  - " + p, file=stream)
        return 2
    print(f"✅ briefing_lint{tag} 通過", file=stream)
    return 0


def hook_main():
    try:
        d = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    f = ((d.get("tool_input") or {}).get("file_path") or (d.get("tool_response") or {}).get("filePath") or "")
    if not PATH_RE.search(f):
        return 0
    probs = lint(Path(f))
    if not probs:
        return 0
    return report(probs, tag="（hook，R27/H10 表述規則）", stream=sys.stderr)


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--hook":
        return hook_main()
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    return report(lint(Path(sys.argv[1])))


if __name__ == "__main__":
    sys.exit(main())
