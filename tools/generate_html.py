#!/usr/bin/env python3
"""
generate_html.py — Convert Markdown reports to self-contained HTML and optionally
push to the private fadacai-reports repo for Cloudflare Pages hosting.

Usage (push 預設開啟；加 --no-push 只存本地不上線):
  python3 tools/generate_html.py briefing 2026-06-10 [--no-push]
  python3 tools/generate_html.py portfolio-review briefing-out/portfolio-review-2026-06-07.md [--no-push]
  python3 tools/generate_html.py stock-analysis briefing-out/stock-analysis-NVDA-2026-06-10.md [--no-push]
  python3 tools/generate_html.py options-strategy briefing-out/options-strategy-NVDA-2026-06-10.md [--no-push]

Environment (.env):
  REPORT_SITE_TOKEN      — 32-hex token used as URL directory (security by obscurity)
  REPORT_SITE_URL        — base URL e.g. https://fadacai-reports.pages.dev
  REPORTS_REPO_PATH      — absolute path to local fadacai-reports clone

Returns exit code:
  0 — success
  1 — source file not found or conversion error
  2 — push failed (non-fatal for caller)
"""

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import markdown
from markdown.extensions.toc import TocExtension

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
BRIEFING_OUT = ROOT / "briefing-out"
LOCAL_HTML_DIR = BRIEFING_OUT / "html"


# ── .env loader ───────────────────────────────────────────────────────────────
def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                v = v.split("#")[0].strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                    v = v[1:-1]
                os.environ.setdefault(k.strip(), v)


# ── CSS template ──────────────────────────────────────────────────────────────
CSS = """
/* ── Mediterranean warm — soft light theme (default) ── */
:root {
  --bg: #faf7f2;            /* warm paper */
  --surface: #f2ece2;       /* sand */
  --surface2: #eae2d4;      /* deeper sand */
  --border: #e3dacb;        /* soft linen border */
  --border-strong: #d4c7b2;
  --text: #433a30;          /* soft espresso (not black) */
  --text-muted: #8c7f6e;    /* driftwood */
  --heading: #35302a;
  --accent: #b06f43;        /* muted terracotta */
  --accent-soft: #b06f4318; /* terracotta wash */
  --up: #57824f;            /* muted olive */
  --down: #b65c43;          /* soft brick */
  --warn: #a3812f;          /* quiet ochre */
  --radius: 10px;
  --shadow: 0 1px 3px rgba(67, 58, 48, 0.06);
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans TC",
          "PingFang TC", "Microsoft JhengHei", sans-serif;
  --mono: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace;
}

/* ── Soft warm dark (auto, follows system) ── */
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #211d18;
    --surface: #2a251f;
    --surface2: #332d26;
    --border: #3b342b;
    --border-strong: #4a4136;
    --text: #ddd3c4;
    --text-muted: #998c7b;
    --heading: #e8dfd2;
    --accent: #cf9468;
    --accent-soft: #cf946818;
    --up: #8caf85;
    --down: #cf8a72;
    --warn: #c2a560;
    --shadow: none;
  }
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html { -webkit-text-size-adjust: 100%; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  font-size: clamp(0.95rem, 0.9rem + 0.25vw, 1.0625rem);
  line-height: 1.75;
  padding: clamp(16px, 4vw, 40px) clamp(16px, 5vw, 32px);
  max-width: 980px;
  margin: 0 auto;
  font-feature-settings: "tnum";   /* tabular numbers for financial data */
}
.page { max-width: 760px; margin: 0 auto; }          /* 散文欄寬；表格可溢出到 980 */
@media (min-width: 1060px) { .page .table-wrap { width: 980px; margin-left: -110px; } }

/* ── Typography ── */
h1 {
  font-size: clamp(1.3rem, 1.1rem + 1vw, 1.6rem);
  font-weight: 650;
  color: var(--heading);
  letter-spacing: -0.01em;
  line-height: 1.3;
  margin: 28px 0 16px;
}
h2 {
  font-size: clamp(1.05rem, 1rem + 0.4vw, 1.2rem);
  font-weight: 600;
  color: var(--heading);
  letter-spacing: -0.005em;
  margin: 40px 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-strong);
}
h2:first-child { margin-top: 0; }
h3 {
  font-size: 1rem;
  font-weight: 600;
  color: var(--accent);
  margin: 26px 0 8px;
}
h4 { font-size: 0.92rem; font-weight: 600; color: var(--text-muted); margin: 18px 0 6px; }
p  { margin: 10px 0; }
ul, ol { margin: 10px 0 10px 22px; }
li { margin: 5px 0; }
li::marker { color: var(--text-muted); }
strong { font-weight: 650; color: var(--heading); }
em { color: var(--text-muted); }
a  { color: var(--accent); text-decoration: underline; text-decoration-color: transparent; text-underline-offset: 3px; transition: text-decoration-color .15s; }
a:hover { text-decoration-color: currentColor; }
code {
  font-family: var(--mono);
  font-size: 0.85em;
  background: var(--surface);
  border-radius: 5px;
  padding: 2px 6px;
}
pre {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  overflow-x: auto;
  margin: 14px 0;
  font-size: 0.85rem;
  line-height: 1.6;
}
pre code { background: none; padding: 0; }
blockquote {
  border-left: 3px solid var(--border-strong);
  color: var(--text-muted);
  margin: 14px 0;
  padding: 6px 16px;
}
hr { border: none; border-top: 1px solid var(--border); margin: 28px 0; }

/* ── Tables ── */
.table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin: 16px 0;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--bg);
  box-shadow: var(--shadow);
}
table { border-collapse: collapse; width: 100%; }
th {
  text-align: left;
  padding: 10px 14px;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border-bottom: 1px solid var(--border-strong);
  background: var(--surface);
  white-space: nowrap;
}
td { padding: 8px 12px; border-bottom: 1px solid var(--border); font-size: 0.86rem; vertical-align: top; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:nth-child(even) td { background: color-mix(in srgb, var(--surface) 45%, transparent); }
tbody tr:hover td { background: var(--surface2); }
thead th { position: sticky; top: 0; z-index: 1; }
td.nw, th.nw { white-space: nowrap; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td:first-child { font-weight: 600; color: var(--heading); }
td.ticker { font-family: var(--mono); font-size: 0.84rem; letter-spacing: .02em; }
td > code, .flag { font-family: var(--mono); font-size: 0.78em; }
.flag { display:inline-block; background: var(--surface2); border-radius: 5px; padding: 1px 6px; white-space: nowrap; }
.flag .fdate { color: var(--text-muted); margin-left: 4px; font-family: var(--font); }
.badge { display:inline-block; font-size: .72rem; font-weight: 600; border-radius: 999px; padding: 1px 8px;
         line-height: 1.5; white-space: nowrap; border: 1px solid transparent; }
.b-conv { color:#2d5f8a; background:#2d5f8a1a; border-color:#2d5f8a33; }
.b-harv { color:var(--up); background:#57824f1a; border-color:#57824f33; }
.b-park { color:var(--text-muted); background:var(--surface2); border-color:var(--border-strong); }
.b-lotto { color:var(--warn); background:#a3812f1a; border-color:#a3812f33; }
@media (prefers-color-scheme: dark) { .b-conv { color:#8fb8dc; } }

/* ── Up / Down ── */
.up   { color: var(--up); font-weight: 550; }
.down { color: var(--down); font-weight: 550; }
/* 命中率條（2026-10-29 用戶「影子訊號很難讀」）：表頭含「命中」的欄，k/n 或 NN% 自動畫條 */
.hitbar { display:inline-block; width:56px; height:8px; border-radius:4px; background:var(--surface2);
          vertical-align:middle; margin-right:6px; overflow:hidden; }
.hitbar > span { display:block; height:100%; border-radius:4px; }
.hb-good > span { background:var(--up); }
.hb-mid  > span { background:var(--accent); }
.hb-bad  > span { background:var(--down); }
.hitpct { opacity:.65; font-size:.85em; margin-left:3px; white-space:nowrap; }
td .hitcell { white-space:nowrap; }
.warn { color: var(--warn); }

/* ── Header / lead / kv strip / callout ── */
.report-head { margin: 8px 0 20px; }
.report-head h1 { margin: 0 0 10px; }
.lead {
  background: var(--surface); border-left: 4px solid var(--accent);
  border-radius: 0 var(--radius) var(--radius) 0;
  padding: 14px 18px; margin: 0 0 18px; font-size: 1.02em; line-height: 1.8;
}
.lead p { margin: 0; }
.kv-strip { display: flex; flex-direction: column; gap: 6px; margin: 0 0 24px; }
.kv-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: .82rem; }
.kv-label { font-weight: 650; color: var(--heading); margin-right: 4px; white-space: nowrap; }
.kv-item { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 2px 9px; white-space: nowrap; color: var(--text); }
.callout { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 4px 20px 12px; margin: 8px 0 24px; }
.callout h2 { border-bottom: none; margin-top: 14px; }
.callout ul { margin-left: 18px; }

/* ── Meta bar ── */
.meta-bar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  font-size: 0.8rem; color: var(--text-muted);
  margin-bottom: 28px;
}
.meta-bar .tag {
  background: var(--accent-soft);
  color: var(--accent);
  border-radius: 999px;
  padding: 3px 12px;
  font-size: 0.75rem;
  font-weight: 600;
}

/* ── Footer ── */
footer {
  margin-top: 56px; padding-top: 20px;
  border-top: 1px solid var(--border);
  font-size: 0.8rem; color: var(--text-muted);
  display: flex; gap: 20px; flex-wrap: wrap;
}
footer a { color: var(--text-muted); }
footer a:hover { color: var(--accent); }

/* ── TOC：橫向 chip 導覽（只取 h2） ── */
.toc { margin: 0 0 28px; }
.toc ul { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
.toc ul ul { display: none; }
.toc li { margin: 0; font-size: 0.8rem; }
.toc a { display: inline-block; color: var(--text-muted); text-decoration: none;
         background: var(--surface); border: 1px solid var(--border); border-radius: 999px; padding: 3px 11px; }
.toc a:hover { color: var(--accent); border-color: var(--accent); }
.toc-header { display: none; }

/* ── Mobile ── */
@media (max-width: 600px) {
  body { line-height: 1.7; }
  h2 { margin-top: 32px; }
  th, td { padding: 8px 10px; }
  td { font-size: 0.84rem; }
  .toc { padding: 14px 16px; }
}
"""

# ── HTML page template ─────────────────────────────────────────────────────────
PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta name="briefing-tier" content="{tier}">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="page">
<div class="meta-bar">
  <span class="tag">{report_type}</span>
  <span>{date_label}</span>
  <span style="margin-left:auto">fadacai-portfolio</span>
</div>
{head_html}
{toc_html}
{body_html}
<footer>
  <a href="{md_filename}">📄 Markdown 原檔</a>
  <span>生成時間：{generated_at}</span>
  <a href="../index.html">← 報告列表</a>
</footer>
</div>
</body>
</html>
"""

# ── Index page template ────────────────────────────────────────────────────────
INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Reports — fadacai-portfolio</title>
<style>{css}
.section-title {{ font-size:1rem; color:var(--text-muted); text-transform:uppercase;
  letter-spacing:.06em; margin: 28px 0 10px; border-bottom:1px solid var(--border); padding-bottom:4px; }}
.report-list {{ list-style:none; margin:0; padding:0; }}
.report-list li {{ padding:10px 14px; border-bottom:1px solid var(--border); display:flex; gap:12px; align-items:center; }}
.report-list li:last-child {{ border-bottom:none; }}
.report-list li:hover {{ background:var(--surface2); }}
.report-list .date {{ font-size:.8rem; color:var(--text-muted); white-space:nowrap; }}
.report-list a {{ flex:1; }}
.card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); overflow:hidden; margin-bottom:24px; }}
</style>
</head>
<body>
<h1 style="margin-bottom:4px">📊 fadacai-portfolio 報告</h1>
<p style="color:var(--text-muted);font-size:.85rem;margin-bottom:24px">
  更新於 {generated_at}・共 {total} 份報告
</p>
{sections}
<footer style="margin-top:40px;padding-top:16px;border-top:1px solid var(--border);font-size:.8rem;color:var(--text-muted)">
  fadacai-portfolio private report site
</footer>
</body>
</html>
"""

# ── Decoy root index ───────────────────────────────────────────────────────────
DECOY_INDEX = "<!DOCTYPE html><html><head><meta name=\"robots\" content=\"noindex,nofollow\"></head><body></body></html>\n"

# ── CF Pages _headers ─────────────────────────────────────────────────────────
CF_HEADERS = """\
/*
  X-Robots-Tag: noindex, nofollow
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
"""


# ── Markdown conversion ────────────────────────────────────────────────────────
def _ensure_blank_before_tables(md_text: str) -> str:
    """Python-Markdown 的 tables extension 要求表格前有空行，否則整塊當段落
    （raw pipes + <br>）。報告常見 `**標題:**` 緊接表格 → 渲染跑掉。
    這裡在「非空白、非表格行」之後緊接的表格首行前自動插入空行。跳過 fenced code。"""
    lines = md_text.split("\n")
    out: list[str] = []
    in_fence = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if (not in_fence and stripped.startswith("|") and out
                and out[-1].strip() != "" and not out[-1].lstrip().startswith("|")):
            out.append("")  # 插入空行讓 tables extension 認得
        out.append(line)
    return "\n".join(out)


def md_to_html(md_text: str) -> tuple[str, str]:
    """Return (toc_html, body_html)."""
    md_text = _ensure_blank_before_tables(md_text)
    md = markdown.Markdown(
        extensions=[
            "tables",
            "fenced_code",
            "sane_lists",
            "nl2br",
            TocExtension(title="", toc_depth="2-3"),
        ]
    )
    body = md.convert(md_text)
    toc = md.toc  # type: ignore[attr-defined]
    return toc, body


def wrap_tables(html: str) -> str:
    """Wrap <table> in a scrollable div."""
    return re.sub(r"<table>", '<div class="table-wrap"><table>', html).replace(
        "</table>", "</table></div>"
    )


_KN_RE = re.compile(r"(?<![\d/.])(\d{1,3})\s*/\s*(\d{1,3})(?![\d/])")
_PCT_RE = re.compile(r"(?<![\d.+\-−])(\d{1,3}(?:\.\d+)?)%")


def _bar(ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    cls = "hb-good" if ratio >= 0.6 else ("hb-bad" if ratio < 0.4 else "hb-mid")
    return f'<span class="hitbar {cls}"><span style="width:{ratio * 100:.0f}%"></span></span>'


def _hit_cell(inner: str) -> str:
    if "hitbar" in inner:
        return inner
    def kn(m):
        k, n = int(m.group(1)), int(m.group(2))
        if n == 0 or k > n:
            return m.group(0)
        return f'<span class="hitcell">{_bar(k / n)}{m.group(0)}<span class="hitpct">{k / n:.0%}</span></span>'
    out, cnt = _KN_RE.subn(kn, inner)
    if cnt:
        return out
    m = _PCT_RE.search(inner)
    if m and float(m.group(1)) <= 100:
        return inner[:m.start()] + f'<span class="hitcell">{_bar(float(m.group(1)) / 100)}{m.group(0)}</span>' + inner[m.end():]
    return inner


def hit_bars(html: str) -> str:
    """表頭含「命中」的欄：k/n 或無正負號的 NN% 畫成命中率條（綠 ≥60%、紅 <40%、其餘強調色）。
    其他欄不動，所以報酬率的 ±% 仍走 colorize_pct。"""
    def per_table(tm):
        tbl = tm.group(0)
        head = re.search(r"<thead>(.*?)</thead>", tbl, re.S)
        if not head:
            return tbl
        ths = [re.sub(r"<[^>]+>", "", h) for h in re.findall(r"<th[^>]*>(.*?)</th>", head.group(1), re.S)]
        cols = {i for i, h in enumerate(ths) if "命中" in h}
        if not cols:
            return tbl
        def per_row(rm):
            cells = list(re.finditer(r"<td([^>]*)>(.*?)</td>", rm.group(0), re.S))
            row = rm.group(0)
            for i in sorted(cols, reverse=True):
                if i < len(cells):
                    c = cells[i]
                    row = row[:c.start()] + f"<td{c.group(1)}>{_hit_cell(c.group(2))}</td>" + row[c.end():]
            return row
        body = re.search(r"<tbody>(.*?)</tbody>", tbl, re.S)
        if not body:
            return tbl
        new_body = re.sub(r"<tr>.*?</tr>", per_row, body.group(1), flags=re.S)
        return tbl[:body.start(1)] + new_body + tbl[body.end(1):]
    return re.sub(r"<table>.*?</table>", per_table, html, flags=re.S)


def colorize_pct(html: str) -> str:
    """Wrap percentage changes with up/down spans (text nodes only, skips tag content)."""
    result: list[str] = []
    pos = 0
    for m in re.finditer(r"<[^>]+>", html):
        text = html[pos : m.start()]
        text = re.sub(r"(\+\d+\.?\d*%)", r'<span class="up">\1</span>', text)
        text = re.sub(r"([−\-]\d+\.?\d*%)", r'<span class="down">\1</span>', text)
        result.append(text)
        result.append(m.group())  # keep tag unchanged
        pos = m.end()
    tail = html[pos:]
    tail = re.sub(r"(\+\d+\.?\d*%)", r'<span class="up">\1</span>', tail)
    tail = re.sub(r"([−\-]\d+\.?\d*%)", r'<span class="down">\1</span>', tail)
    result.append(tail)
    return "".join(result)



# ── 版面後處理（2026-10-31 用戶「美化產出 html」） ─────────────────────────
_BUCKET_CLS = {"信念": "b-conv", "認列": "b-harv", "停泊": "b-park", "sleeve": "b-park",
               "現金": "b-park", "樂透": "b-lotto", "基準": "b-park"}
_FLAG_RE = re.compile(r"([A-Z]{1,6}:[a-z0-9][a-z0-9-]*)(（[^）]*）)?")
_NUM_RE = re.compile(r"^[+\-−$]?[\d,]+(\.\d+)?%?$")


def split_head(body: str) -> tuple[str, str]:
    """抽出第一個 <h1> 與緊接的首段（白話結論）→ 頁首卡；其餘回傳為 body。"""
    m = re.match(r"\s*<h1[^>]*>.*?</h1>\s*", body, re.S)
    if not m:
        return "", body
    h1 = m.group(0).strip()
    rest = body[m.end():]
    lead = ""
    pm = re.match(r"\s*<p>(?!📊|🚦|🔁)(.*?)</p>\s*", rest, re.S)
    if pm and "<br" not in pm.group(1):
        lead = f'<div class="lead"><p>{pm.group(1)}</p></div>'
        rest = rest[pm.end():]
    return f'<div class="report-head">{h1}{lead}</div>', rest


def kv_strips(html: str) -> str:
    """以 📊/🚦/🔁 開頭、用「｜」分隔的段落 → 鍵值 chip 列。"""
    def per_p(m):
        inner = m.group(1)
        lines = [l.strip() for l in re.split(r"<br\s*/?>\s*", inner) if l.strip()]
        if not lines or not all(l[:1] in "📊🚦🔁📈📉🧭" for l in lines):
            return m.group(0)
        rows = []
        for l in lines:
            parts = [x.strip() for x in l.split("｜") if x.strip()]
            label, items = parts[0], parts[1:]
            if "：" in label:
                label, first = label.split("：", 1)
                items = [first] + items
            rows.append('<div class="kv-row"><span class="kv-label">' + label + "</span>"
                        + "".join(f'<span class="kv-item">{x}</span>' for x in items) + "</div>")
        return '<div class="kv-strip">' + "".join(rows) + "</div>"
    return re.sub(r"<p>(.*?)</p>", per_p, html, flags=re.S)


def decorate_cells(html: str) -> str:
    """表格儲存格：桶別→badge、旗標 id→mono 標籤、短文字/數字→不折行、數字靠右。"""
    def per_td(m):
        attrs, inner = m.group(1), m.group(2)
        plain = re.sub(r"<[^>]+>", "", inner).strip()
        cls = []
        if plain in _BUCKET_CLS:
            inner = f'<span class="badge {_BUCKET_CLS[plain]}">{plain}</span>'
            cls.append("nw")
        elif _FLAG_RE.search(plain) and "<a" not in inner:
            inner = _FLAG_RE.sub(lambda f: f'<span class="flag">{f.group(1)}'
                                 + (f'<span class="fdate">{f.group(2)}</span>' if f.group(2) else "")
                                 + "</span>", inner)
        elif _NUM_RE.match(plain):
            cls += ["num", "nw"]
        elif re.fullmatch(r"[A-Z]{1,6}(\.[A-Z]{1,2})?", plain):
            cls += ["ticker", "nw"]
        elif len(plain) <= 14:
            cls.append("nw")
        if cls:
            attrs = re.sub(r'class="([^"]*)"', lambda c: f'class="{c.group(1)} {" ".join(cls)}"', attrs) \
                if 'class="' in attrs else attrs + f' class="{" ".join(cls)}"'
        return f"<td{attrs}>{inner}</td>"
    return re.sub(r"<td([^>]*)>(.*?)</td>", per_td, html, flags=re.S)


_CALLOUT_H2 = ("今日待辦", "明日待辦", "Quick Take", "本期結論", "先讀這段", "Key Alerts", "結論")


def callout_sections(html: str) -> str:
    """待辦／結論類 h2 連同內容包成卡片。"""
    parts = re.split(r"(?=<h2)", html)
    out = []
    for part in parts:
        hm = re.match(r"<h2[^>]*>(.*?)</h2>", part, re.S)
        if hm and any(k in re.sub(r"<[^>]+>", "", hm.group(1)) for k in _CALLOUT_H2):
            out.append(f'<div class="callout">{part}</div>')
        else:
            out.append(part)
    return "".join(out)


# ── Tier ranking (briefing only) ──────────────────────────────────────────────
TIER_RANK: dict[str, int] = {"quick": 1, "telegram": 2, "full": 3, "deep": 4}


def read_tier_from_html(html_path: Path) -> int:
    """Read briefing-tier meta tag from an existing HTML file. Returns 0 if absent."""
    if not html_path.exists():
        return 0
    m = re.search(r'<meta name="briefing-tier" content="(\w+)"', html_path.read_text(encoding="utf-8"))
    return TIER_RANK.get(m.group(1), 0) if m else 0


def read_tier_from_txt(date_str: str) -> str:
    """Read tier from YYYY-MM-DD-tier.txt written by the skill. Falls back to 'full'."""
    tier_file = BRIEFING_OUT / f"{date_str}-tier.txt"
    if tier_file.exists():
        return tier_file.read_text().strip().lower()
    return "full"


# ── Report type helpers ────────────────────────────────────────────────────────
TYPE_LABELS = {
    "briefing": "每日報告",
    "portfolio-review": "組合審查",
    "stock-analysis": "個股分析",
    "options-strategy": "選擇權策略",
    "trade-review": "交易檢討",
}


def infer_type_and_name(report_type: str, src_path: Path, date_str: str = "") -> tuple[str, str]:
    """Return (type_key, output_stem)."""
    if report_type == "briefing":
        # Use the clean date string, not the "-full" stem
        return "briefing", date_str or src_path.stem.replace("-full", "")
    return report_type, src_path.stem


# ── Index builder ─────────────────────────────────────────────────────────────
def build_index(token_dir: Path) -> None:
    sections: dict[str, list[tuple[str, str, str]]] = {
        "briefing": [],
        "portfolio-review": [],
        "stock-analysis": [],
        "options-strategy": [],
        "trade-review": [],
    }
    total = 0
    for sub in sections:
        sub_dir = token_dir / sub
        if not sub_dir.exists():
            continue
        for f in sorted(sub_dir.glob("*.html"), reverse=True):
            label = f.stem
            sections[sub].append((label, f"{sub}/{f.name}", f.stat().st_mtime))
            total += 1

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html_sections = ""
    for key, label in TYPE_LABELS.items():
        items = sections[key]
        if not items:
            continue
        lis = "\n".join(
            f'<li><span class="date">{name}</span>'
            f'<a href="{path}">{TYPE_LABELS[key]} {name}</a></li>'
            for name, path, _ in items
        )
        html_sections += f"""
<div class="card">
  <h2 style="margin:0;padding:12px 16px;border-bottom:1px solid var(--border)">{label}</h2>
  <ul class="report-list">{lis}</ul>
</div>"""

    (token_dir / "index.html").write_text(
        INDEX_TEMPLATE.format(
            css=CSS,
            generated_at=now,
            total=total,
            sections=html_sections or "<p style='color:var(--text-muted)'>尚無報告</p>",
        ),
        encoding="utf-8",
    )


# ── Push to reports repo ───────────────────────────────────────────────────────
def push_to_repo(repo_path: Path, date_label: str, report_type: str) -> bool:
    try:
        env = {**os.environ, "GIT_AUTHOR_NAME": "PatrickSUDO",
               "GIT_AUTHOR_EMAIL": "48519645+PatrickSUDO@users.noreply.github.com",
               "GIT_COMMITTER_NAME": "PatrickSUDO",
               "GIT_COMMITTER_EMAIL": "48519645+PatrickSUDO@users.noreply.github.com"}
        subprocess.run(["git", "-C", str(repo_path), "add", "-A"], check=True, env=env)
        result = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain"],
            capture_output=True, text=True
        )
        if not result.stdout.strip():
            print(f"[generate_html] repo 無變更，跳過 commit")
            return True
        msg = f"chore(reports): {report_type} {date_label}"
        subprocess.run(
            ["git", "-C", str(repo_path), "commit", "-m", msg],
            check=True, env=env,
        )
        subprocess.run(
            ["git", "-C", str(repo_path), "push"],
            check=True, timeout=30,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"[generate_html] push 失敗：{e}", file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print("[generate_html] push 逾時（30s）", file=sys.stderr)
        return False


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    load_env()

    # Parse args
    # push 預設開啟（2026-06-13，Netlify 升級 1,000 credits 後）；--no-push 可關閉。
    # --push 仍可顯式指定（向後相容，無作用差異）。
    push = "--no-push" not in sys.argv
    clean_args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(clean_args) < 2:
        print("Usage: generate_html.py <type> <date-or-path> [--no-push]")
        print("  type: briefing | portfolio-review | stock-analysis | options-strategy"
              " | trade-review")
        print("  （預設自動 push 到 reports repo；加 --no-push 只存本地）")
        return 1

    report_type, arg2 = clean_args[0], clean_args[1]

    # Resolve source markdown path
    if report_type == "briefing":
        date_str = arg2  # e.g. 2026-06-10
        src = BRIEFING_OUT / f"{date_str}-full.md"
        date_label = date_str
    else:
        src = Path(arg2) if Path(arg2).is_absolute() else ROOT / arg2
        if not src.exists():
            src = BRIEFING_OUT / arg2
        date_label = src.stem  # full filename stem as label

    if not src.exists():
        print(f"[generate_html] 找不到來源：{src}", file=sys.stderr)
        return 1

    md_text = src.read_text(encoding="utf-8")
    type_key, out_stem = infer_type_and_name(
        report_type, src, date_str if report_type == "briefing" else ""
    )
    label = TYPE_LABELS.get(type_key, report_type)

    # First line as title candidate
    first_line = md_text.splitlines()[0].lstrip("# ").strip() if md_text else out_stem
    title = first_line if first_line else f"{label} {date_label}"

    # Convert
    toc_html, body_html = md_to_html(md_text)
    body_html = hit_bars(body_html)
    body_html = decorate_cells(body_html)
    body_html = wrap_tables(body_html)
    body_html = kv_strips(body_html)
    body_html = colorize_pct(body_html)
    head_html, body_html = split_head(body_html)
    body_html = callout_sections(body_html)

    toc_block = ""
    if toc_html.strip() and "<li>" in toc_html:
        toc_block = f'<div class="toc"><div class="toc-header">目錄</div>{toc_html}</div>'

    # Determine tier (briefing only; others always push)
    tier = read_tier_from_txt(date_str) if report_type == "briefing" else "full"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = PAGE_TEMPLATE.format(
        title=title,
        css=CSS,
        report_type=label,
        date_label=date_label,
        head_html=head_html,
        toc_html=toc_block,
        body_html=body_html,
        md_filename=f"{out_stem}.md",
        generated_at=now_str,
        tier=tier,
    )

    # Always write local copy
    LOCAL_HTML_DIR.mkdir(parents=True, exist_ok=True)
    local_out = LOCAL_HTML_DIR / f"{out_stem}.html"
    local_out.write_text(html, encoding="utf-8")
    print(f"[generate_html] 本地 HTML → {local_out}")

    # Write to reports repo if configured
    token = os.environ.get("REPORT_SITE_TOKEN", "")
    repo_path_str = os.environ.get("REPORTS_REPO_PATH", "")
    site_url = os.environ.get("REPORT_SITE_URL", "")

    if not token or not repo_path_str:
        print("[generate_html] REPORT_SITE_TOKEN / REPORTS_REPO_PATH 未設定，跳過部署")
        return 0

    repo_path = Path(repo_path_str)
    if not repo_path.exists():
        print(f"[generate_html] ⚠️ REPORTS_REPO_PATH 不存在：{repo_path}", file=sys.stderr)
        print("[generate_html]    請先建立 fadacai-reports repo 並 clone 到該路徑")
        return 2

    # Ensure directory structure
    token_dir = repo_path / "r" / token
    report_dir = token_dir / type_key
    report_dir.mkdir(parents=True, exist_ok=True)

    # Tier gate: only push if new tier >= existing (briefing only)
    if report_type == "briefing":
        existing_tier = read_tier_from_html(report_dir / f"{out_stem}.html")
        new_tier = TIER_RANK.get(tier, 2)
        if push and existing_tier > new_tier:
            print(
                f"[generate_html] ⏭️  網站已有 tier={list(TIER_RANK.keys())[existing_tier-1]} "
                f"({existing_tier}) > 本次 {tier} ({new_tier})，跳過 push（本地 HTML 已更新）"
            )
            push = False  # write files to repo dir but don't git push

    # Write HTML + MD to repo
    (report_dir / f"{out_stem}.html").write_text(html, encoding="utf-8")
    shutil.copy2(src, report_dir / f"{out_stem}.md")

    # Decoy root index
    root_decoy = repo_path / "index.html"
    if not root_decoy.exists():
        root_decoy.write_text(DECOY_INDEX, encoding="utf-8")

    # CF Pages _headers
    headers_file = repo_path / "_headers"
    if not headers_file.exists():
        headers_file.write_text(CF_HEADERS, encoding="utf-8")

    # Rebuild index page
    build_index(token_dir)

    page_url = f"{site_url}/r/{token}/{type_key}/{out_stem}.html"
    print(f"[generate_html] 報告網址：{page_url}")

    if push:
        ok = push_to_repo(repo_path, date_label, type_key)
        if not ok:
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
