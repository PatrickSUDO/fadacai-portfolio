#!/usr/bin/env python3
"""
rule_stats.py — 規則命中率的統計判讀（運氣 vs 技能的機械層；feedback/skill-vs-luck.md）

  coincidence --hits K --fails F      K/F 紀錄在 p=0.5 下的巧合機率 + Beta 後驗 + 建議狀態
  regime --date D [--bench SMH]       該日基準 regime：trailing 21 交易日報酬 ≥0 → up，否則 down
  regime-table --from A --to B        期間逐月 regime
  ledger-audit [--write | --check]    解析 RULES-LEDGER 帳本表：
        （無旗標）列印每列巧合機率與建議狀態
        --write   把「巧合」欄寫回帳本
        --check   一致性檢查，任一違規 exit 2（briefing 每日跑，缺口進 Key Alerts）：
                  ① 巧合欄過期（未跑 --write）
                  ② 狀態欄與數字矛盾（標 🟢 已驗證但巧合 >5%、標初步支持但 >25%、失效 ≥2 未標 🔴）
                  ③ 2026-09-06 起的新案例缺 [up]/[down] regime 標籤（只查有數字計分的規則）

門檻：失效 ≥2 🔴 強制覆審｜失效 1 🟡 待覆審｜失效 0：巧合 ≤5% 🟢 已驗證（獨立命中 ≥5）、
      ≤25% 🟡 初步支持（命中 2–4）、否則 ⚪ 未驗證。
「命中」只算規則建立日之後的獨立事件：原始案例不計；同批同段行情算 1。
"""

import argparse
import math
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "feedback" / "RULES-LEDGER.md"

VERIFIED_P = 0.05
SUPPORT_P = 0.25
REGIME_TAG_SINCE = date(2026, 9, 6)
TAG_RE = re.compile(r"\[(up|down)\]")
DATE_RE = re.compile(r"@\s*(\d{4})-(\d{2})(?:-(\d{2}))?")


# ── 統計 ─────────────────────────────────────────────────────────────────────
def binom_tail(k, n, p=0.5):
    if n == 0:
        return None
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def _betacf(a, b, x, max_iter=200, eps=3e-12):
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / d if abs(d) > 1e-300 else 1e300
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d; d = 1.0 / d if abs(d) > 1e-300 else 1e300
        c = 1.0 + aa / c if abs(c) > 1e-300 else 1e300
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d; d = 1.0 / d if abs(d) > 1e-300 else 1e300
        c = 1.0 + aa / c if abs(c) > 1e-300 else 1e300
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


def beta_cdf(x, a, b):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1 - x) / b


def beta_quantile(q, a, b):
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if beta_cdf(mid, a, b) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def judge(hits, fails):
    """→ (coincidence_p, posterior_mean, lower90, status_label)."""
    n = hits + fails
    if n == 0:
        return None, None, None, "— 無可計分事件"
    p = binom_tail(hits, n)
    post_mean = (hits + 1) / (n + 2)
    lower90 = beta_quantile(0.10, hits + 1, fails + 1)
    if fails >= 2:
        s = "🔴 強制覆審"
    elif fails == 1:
        s = "🟡 待覆審"
    elif p <= VERIFIED_P:
        s = "🟢 已驗證"
    elif p <= SUPPORT_P:
        s = "🟡 初步支持"
    else:
        s = "⚪ 未驗證"
    return p, post_mean, lower90, s


def fmt_p(p):
    return "—" if p is None else f"{p*100:.1f}%"


# ── regime ───────────────────────────────────────────────────────────────────
def _closes(bench, start, end):
    import yfinance as yf
    h = yf.Ticker(bench).history(start=start.isoformat(), end=end.isoformat(),
                                 interval="1d", auto_adjust=True)
    if h is None or h.empty:
        sys.exit(f"no price for {bench}")
    return h["Close"]


def cmd_regime(a):
    d = datetime.strptime(a.date, "%Y-%m-%d").date()
    s = _closes(a.bench, d - timedelta(days=a.window * 3), d + timedelta(days=1))
    s = s[s.index.date <= d]
    if len(s) < a.window + 1:
        sys.exit(f"not enough history for {a.bench} before {d}")
    r = s.iloc[-1] / s.iloc[-1 - a.window] - 1
    print(f"{a.bench} @ {d}: [{'up' if r >= 0 else 'down'}] (trailing {a.window}d {r*100:+.1f}%)")


def cmd_regime_table(a):
    d0 = datetime.strptime(a.frm, "%Y-%m-%d").date()
    d1 = datetime.strptime(a.to, "%Y-%m-%d").date()
    s = _closes(a.bench, d0 - timedelta(days=45), d1 + timedelta(days=1))
    print(f"{a.bench} 月 regime（月內報酬正負）")
    for (y, m), grp in s.groupby([s.index.year, s.index.month]):
        first = date(y, m, 1)
        if first < date(d0.year, d0.month, 1) or first > d1:
            continue
        r = grp.iloc[-1] / grp.iloc[0] - 1
        print(f"  {y}-{m:02d}: [{'up' if r >= 0 else 'down'}] {r*100:+.1f}%")


# ── ledger audit ─────────────────────────────────────────────────────────────
def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _leading_int(cell):
    m = re.match(r"\s*(\d+)", cell)
    return int(m.group(1)) if m else None


def parse_ledger(text):
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("|") and "命中" in ln and "失效" in ln and "#" in ln:
            cols = _cells(ln)
            return lines, i, {c: j for j, c in enumerate(cols)}
    sys.exit("帳本表頭（含 # / 命中 / 失效）未找到")


def audit_rows(lines, hdr, cm):
    out = []
    i = hdr + 2
    while i < len(lines) and lines[i].startswith("|"):
        cells = _cells(lines[i])
        if len(cells) >= len(cm):
            h, f = _leading_int(cells[cm["命中"]]), _leading_int(cells[cm["失效"]])
            if h is None and f is None:
                p = pm = lo = None; sug = "— 無可計分事件"
            else:
                p, pm, lo, sug = judge(h or 0, f or 0)
            out.append(dict(line=i, id=cells[cm["#"]], hits=h, fails=f, p=p, post=pm, lower90=lo,
                            suggest=sug, status=cells[cm["狀態"]] if "狀態" in cm else "",
                            case=cells[cm["結構化原始案例"]] if "結構化原始案例" in cm else "",
                            written=cells[cm["巧合"]] if "巧合" in cm else None))
        i += 1
    return out


def violations(rows):
    """--check rules ①②③ → list of strings."""
    v = []
    for r in rows:
        st = re.sub(r"\*", "", r["status"])
        # ① stale coincidence column
        if r["written"] is not None and r["written"] != fmt_p(r["p"]):
            v.append(f"{r['id']}: 巧合欄 {r['written']} ≠ 計算值 {fmt_p(r['p'])}（跑 ledger-audit --write）")
        if r["p"] is None:
            continue
        # ② status contradicts numbers
        if re.match(r"^\s*🟢\s*已驗證", st) and "已驗證" not in r["suggest"]:
            v.append(f"{r['id']}: 標 🟢 已驗證，但巧合 {fmt_p(r['p'])} → 應為 {r['suggest']}")
        if "初步支持" in st[:8] and r["p"] > SUPPORT_P:
            v.append(f"{r['id']}: 標初步支持，但巧合 {fmt_p(r['p'])} > 25% → 應為 {r['suggest']}")
        if (r["fails"] or 0) >= 2 and not st.startswith("🔴"):
            v.append(f"{r['id']}: 失效 {r['fails']} 未標 🔴 強制覆審")
        # ③ regime tag on new case entries (only rules being scored)
        for seg in re.split(r"[；;]", r["case"]):
            dates = [date(int(y), int(m), int(d or 1)) for y, m, d in DATE_RE.findall(seg)]
            if dates and max(dates) >= REGIME_TAG_SINCE and not TAG_RE.search(seg):
                v.append(f"{r['id']}: 案例「{seg.strip()[:40]}…」缺 [up]/[down] regime 標籤")
    return v


def cmd_ledger_audit(a):
    text = LEDGER.read_text()
    lines, hdr, cm = parse_ledger(text)
    rows = audit_rows(lines, hdr, cm)

    if a.check:
        v = violations(rows)
        if v:
            print(f"❌ RULES-LEDGER 一致性 {len(v)} 項違規：")
            for x in v:
                print("  - " + x)
            sys.exit(2)
        print(f"✅ RULES-LEDGER 一致（{len(rows)} 條）")
        return

    print(f"{'規則':5s} {'命中':>4s} {'失效':>4s} {'巧合':>7s} {'後驗均':>6s} {'90%下限':>7s}  建議狀態      現行狀態")
    for r in rows:
        print(f"{r['id']:5s} {str(r['hits'] if r['hits'] is not None else '—'):>4s} "
              f"{str(r['fails'] if r['fails'] is not None else '—'):>4s} {fmt_p(r['p']):>7s} "
              f"{fmt_p(r['post']):>6s} {fmt_p(r['lower90']):>7s}  {r['suggest']:12s}  "
              f"{re.sub(r'[*]', '', r['status'])[:22]}")
    print(f"\n門檻：已驗證 = 失效 0 且巧合 ≤{VERIFIED_P*100:.0f}%；初步支持 ≤{SUPPORT_P*100:.0f}%。"
          f"{len(rows)} 條同測，5% 門檻下預期假驗證 ≈ {len(rows)*VERIFIED_P:.1f} 條。")
    v = violations(rows)
    if v:
        print(f"⚠️ {len(v)} 項不一致（--check 會擋）：\n  - " + "\n  - ".join(v))

    if not a.write:
        return
    fcol = cm["失效"]
    has = "巧合" in cm
    ccol = cm["巧合"] if has else fcol + 1

    def put(cells, val):
        if has:
            cells[ccol] = val
        else:
            cells.insert(ccol, val)
        return "| " + " | ".join(cells) + " |"

    lines[hdr] = put(_cells(lines[hdr]), "巧合")
    lines[hdr + 1] = put(_cells(lines[hdr + 1]), "----:")
    for r in rows:
        lines[r["line"]] = put(_cells(lines[r["line"]]), fmt_p(r["p"]))
    LEDGER.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""))
    print(f"✍️ 已寫回 {LEDGER.relative_to(ROOT)}（巧合欄 {'更新' if has else '新增'}）")


# ── cli ──────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="規則命中率統計判讀（運氣 vs 技能）")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("coincidence")
    c.add_argument("--hits", type=int, required=True)
    c.add_argument("--fails", type=int, default=0)
    c.set_defaults(func=lambda a: print(
        f"命中 {a.hits} / 失效 {a.fails}: 巧合 {fmt_p(judge(a.hits, a.fails)[0])} | "
        f"後驗均值 {fmt_p(judge(a.hits, a.fails)[1])} | 90% 下限 {fmt_p(judge(a.hits, a.fails)[2])} "
        f"→ {judge(a.hits, a.fails)[3]}"))

    r = sub.add_parser("regime")
    r.add_argument("--date", required=True)
    r.add_argument("--bench", default="SMH")
    r.add_argument("--window", type=int, default=21)
    r.set_defaults(func=cmd_regime)

    rt = sub.add_parser("regime-table")
    rt.add_argument("--from", dest="frm", required=True)
    rt.add_argument("--to", required=True)
    rt.add_argument("--bench", default="SMH")
    rt.set_defaults(func=cmd_regime_table)

    la = sub.add_parser("ledger-audit")
    g = la.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="把巧合欄寫回帳本")
    g.add_argument("--check", action="store_true", help="一致性檢查，違規 exit 2")
    la.set_defaults(func=cmd_ledger_audit)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
