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
  max-width: 760px;
  margin: 0 auto;
  font-feature-settings: "tnum";   /* tabular numbers for financial data */
}

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
td { padding: 9px 14px; border-bottom: 1px solid var(--border); font-size: 0.88rem; }
tbody tr:last-child td { border-bottom: none; }

/* ── Up / Down ── */
.up   { color: var(--up); font-weight: 550; }
.down { color: var(--down); font-weight: 550; }
.warn { color: var(--warn); }

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

/* ── TOC ── */
.toc {
  background: var(--surface);
  border-radius: var(--radius);
  padding: 16px 22px;
  margin-bottom: 32px;
  box-shadow: var(--shadow);
}
.toc ul { margin: 0 0 0 18px; }
.toc li { margin: 4px 0; font-size: 0.86rem; }
.toc a { color: var(--text-muted); text-decoration: none; }
.toc a:hover { color: var(--accent); }
.toc-header {
  font-size: 0.72rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--text-muted); margin-bottom: 10px;
}

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
<div class="meta-bar">
  <span class="tag">{report_type}</span>
  <span>{date_label}</span>
  <span style="margin-left:auto">fadacai-portfolio</span>
</div>
{toc_html}
{body_html}
<footer>
  <a href="{md_filename}">📄 Markdown 原檔</a>
  <span>生成時間：{generated_at}</span>
  <a href="../index.html">← 報告列表</a>
</footer>
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
               "GIT_AUTHOR_EMAIL": "patricksuph@gmail.com",
               "GIT_COMMITTER_NAME": "PatrickSUDO",
               "GIT_COMMITTER_EMAIL": "patricksuph@gmail.com"}
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
    body_html = wrap_tables(body_html)
    body_html = colorize_pct(body_html)

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
