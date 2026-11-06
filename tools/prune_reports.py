#!/usr/bin/env python3
"""prune_reports.py — 舊的每日 briefing 收進封存（2026-11-06 用戶「報告越來越多…太老的 briefing 清掉」）

只動每日 briefing（一天一份、看完就過期）：
  本機    briefing-out/DATE-full.md / DATE-telegram.txt / DATE-tier.txt、briefing-out/html/DATE.html
          超過保留天數 → 搬到 briefing-out/archive/YYYY-MM/（搬，不刪；account_metrics scan 會讀封存，淨值標記不會少）
  報告站  <reports repo>/r/<token>/briefing/DATE.html 超過保留天數 → 用 git rm 移出網站、重建列表、push
          （檔案仍在 reports repo 的 git 歷史裡，救得回來；有未提交修改的檔案 git rm 會拒絕，不硬刪）

不動：trade-review / portfolio-review / stock-analysis / options-strategy（數量少、要長期回頭看，
      review_due.py 也靠 portfolio-review 檔名算到期）、cache/（archive_cache.py 自己管 120 天）、log。

用法：
  python3 tools/prune_reports.py                 乾跑，只列出會動什麼
  python3 tools/prune_reports.py --apply         真的搬／移出
  選項：--keep-days N（預設 60，或環境變數 PRUNE_KEEP_DAYS）、--no-site、--no-local、--no-push

排程：briefing_runner.sh 每週一跑一次 --apply。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIEFING_OUT = ROOT / "briefing-out"
ARCHIVE = BRIEFING_OUT / "archive"
LOCAL_PAT = re.compile(r"^(\d{4}-\d{2}-\d{2})-(?:full\.md|telegram\.txt|tier\.txt)$")
HTML_PAT = re.compile(r"^(\d{4}-\d{2}-\d{2})\.html$")
DEFAULT_KEEP = 60


def _old(name: str, pat: re.Pattern, cutoff: date):
    m = pat.match(name)
    if not m:
        return None
    try:
        d = date.fromisoformat(m.group(1))
    except ValueError:
        return None
    return d if d < cutoff else None


def local_targets(cutoff: date):
    """[(src, dest)]：本機每日 briefing 檔與其 HTML 副本。"""
    out = []
    if BRIEFING_OUT.exists():
        for f in sorted(BRIEFING_OUT.iterdir()):
            d = _old(f.name, LOCAL_PAT, cutoff) if f.is_file() else None
            if d:
                out.append((f, ARCHIVE / d.strftime("%Y-%m") / f.name))
    html_dir = BRIEFING_OUT / "html"
    if html_dir.exists():
        for f in sorted(html_dir.iterdir()):
            d = _old(f.name, HTML_PAT, cutoff) if f.is_file() else None
            if d:
                out.append((f, ARCHIVE / d.strftime("%Y-%m") / "html" / f.name))
    return out


def site_targets(cutoff: date):
    """(repo_path, token_dir, [files])；沒設定報告站 → (None, None, [])。"""
    sys.path.insert(0, str(ROOT / "tools"))
    import generate_html as gh  # noqa: E402  共用 .env 載入、列表重建、push
    gh.load_env()
    token = os.environ.get("REPORT_SITE_TOKEN", "")
    repo = os.environ.get("REPORTS_REPO_PATH", "")
    if not token or not repo or not Path(repo).exists():
        return None, None, [], gh
    token_dir = Path(repo) / "r" / token
    bdir = token_dir / "briefing"
    files = [f for f in sorted(bdir.glob("*.html")) if _old(f.name, HTML_PAT, cutoff)] if bdir.exists() else []
    return Path(repo), token_dir, files, gh


def _span(names):
    ds = sorted(re.search(r"\d{4}-\d{2}-\d{2}", n).group(0) for n in names)
    return f"{ds[0]} ~ {ds[-1]}" if ds else "—"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="真的動（預設乾跑）")
    ap.add_argument("--keep-days", type=int, default=int(os.environ.get("PRUNE_KEEP_DAYS", DEFAULT_KEEP)))
    ap.add_argument("--no-site", action="store_true")
    ap.add_argument("--no-local", action="store_true")
    ap.add_argument("--no-push", action="store_true", help="報告站只 git rm + 重建列表，不 commit/push")
    a = ap.parse_args()
    if a.keep_days < 14:
        print("keep-days 不得小於 14（交易檢討與跨日比對要回頭讀兩週內的 briefing）", file=sys.stderr)
        return 1
    cutoff = date.today() - timedelta(days=a.keep_days)
    mode = "執行" if a.apply else "乾跑"
    rc = 0

    if not a.no_local:
        targets = local_targets(cutoff)
        print(f"[{mode}] 本機：{len(targets)} 個檔（{_span([s.name for s, _ in targets])}）→ briefing-out/archive/YYYY-MM/")
        if a.apply:
            moved = skipped = 0
            for src, dest in targets:
                if dest.exists():
                    skipped += 1  # 封存已有同名檔：不覆蓋、不刪來源，留給人看
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
                moved += 1
            print(f"  已搬 {moved}" + (f"，略過 {skipped}（封存已有同名檔）" if skipped else ""))

    if not a.no_site:
        repo, token_dir, files, gh = site_targets(cutoff)
        if repo is None:
            print(f"[{mode}] 報告站：未設定或找不到 reports repo，跳過")
        else:
            print(f"[{mode}] 報告站：{len(files)} 頁每日報告（{_span([f.name for f in files])}）移出網站（留在 git 歷史）")
            if a.apply and files:
                rel = [str(f.relative_to(repo)) for f in files]
                r = subprocess.run(["git", "-C", str(repo), "rm", "-q", "--"] + rel, capture_output=True, text=True)
                if r.returncode != 0:
                    err = r.stderr.strip().replace(os.environ.get("REPORT_SITE_TOKEN", "\0"), "<token>")
                    print(f"  git rm 失敗，報告站未動：{err[:300]}", file=sys.stderr)
                    rc = 2
                else:
                    gh.build_index(token_dir)
                    if a.no_push:
                        print(f"  已移出 {len(files)} 頁、列表已重建（未 push）")
                    else:
                        ok = gh.push_to_repo(repo, f"收掉 {len(files)} 頁 {a.keep_days} 天前的每日報告", "prune")
                        print(f"  已移出 {len(files)} 頁，push {'成功' if ok else '失敗（下次 briefing push 會一併帶上）'}")
    if not a.apply:
        print("（乾跑，沒動任何檔案；加 --apply 才執行）")
    return rc


if __name__ == "__main__":
    sys.exit(main())
