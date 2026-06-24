#!/usr/bin/env python3
"""
fetch_news.py — Cache per-holding 中文新聞(鉅亨/cnyes) raw news articles (body + signals) for briefing.

Source: 中文新聞（鉅亨網 cnyes / 經濟日報）REST 抓取 + LLM 中文情緒（cnyes-news MCP 的快取版）
⚠️ 整合接縫：`NEWS_BASE` 與 `_news_get` 為占位原型；實際接時換成你選用的中文新聞來源
   端點（鉅亨/經濟日報/工商）並把回應 mapping 到 {title, body, link, symbols, tags}。
Output:
  briefing-out/cache/news-articles.json
    {status, generated_at, fields_available, tickers: {TICKER: {articles: [...]}}, errors: []}
TTL:
  6 hours (news is time-sensitive; same-day re-runs reuse cache, next-day always refreshes)

Ticker source priority:
  1. ROOT/journal/<latest>.md  (parse holdings table — same logic as fetch_fundamentals.py)
  2. NEWS_TICKERS env var (comma-separated)
  3. abort with warning if both empty

Content control:
  - Fetch up to NEWS_LIMIT_FETCH articles/ticker; deduplicate by title+link; keep top NEWS_KEEP.
  - article.content truncated to BODY_CHARS chars (600) as content_excerpt.
  - Preserves: title, date, link, source, content_excerpt, symbols, tags, sentiment.
  - fields_available in payload: P3 signal-inference gate (check "content" in fields_available).

Usage:
  python3 tools/fetch_news.py              # refresh if stale (TTL 6h)
  python3 tools/fetch_news.py --force      # force refresh
"""

import json
import os
import re
import sys
import time
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

warnings.filterwarnings("ignore")

# ── Path setup ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "briefing-out" / "cache"
NEWS_FILE = CACHE_DIR / "news-articles.json"
JOURNAL_DIR = ROOT / "journal"

# ── Config ─────────────────────────────────────────────────────────────────
CACHE_TTL_HOURS = 6        # news is time-sensitive; 6h = same-day reuse, next-day refresh
NEWS_DAYS = 7              # lookback window (matches get_news_sentiment default)
NEWS_LIMIT_FETCH = 20      # articles to fetch per ticker (before dedup)
NEWS_KEEP = 8              # articles to keep per ticker (after dedup, newest-first)
BODY_CHARS = 600           # content truncation — lede + first quant sentence fits here
TICKERS_DELAY = 0.4        # polite delay between 中文新聞(鉅亨/cnyes) API calls
NEWS_BASE = "https://cnyes.com/api"


# ── .env loader (identical to fetch_fundamentals.py) ────────────────────────
def load_env() -> None:
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


# ── Ticker discovery (identical to fetch_fundamentals.py) ────────────────────
TICKER_RE = re.compile(r"^\|\s*(\d{4})\b")


def journals_newest_first() -> list[Path]:
    if not JOURNAL_DIR.exists():
        return []
    return sorted(JOURNAL_DIR.glob("[0-9]*-[0-9]*-[0-9]*.md"), reverse=True)


def parse_journal_tickers(path: Path) -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()
    in_holdings_table = False
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if "持倉快照" in line or "倉位快照" in line or "持倉清單" in line:
            in_holdings_table = True
            continue
        if in_holdings_table and line.startswith("##"):
            in_holdings_table = False
        if not in_holdings_table:
            continue
        m = TICKER_RE.match(raw)
        if m:
            sym = m.group(1)
            if sym in ("LEAPS",):
                continue
            if sym not in seen:
                tickers.append(sym)
                seen.add(sym)
    return tickers


def get_tickers() -> list[str]:
    # Walk journals newest→oldest until one yields a holdings snapshot.
    # /briefing's auto-created journals are often delta-only (no 持倉快照
    # table), so the newest file frequently parses to zero tickers — fall back
    # to the most recent journal that actually has the snapshot instead of
    # dropping straight to the env/empty path.
    journals = journals_newest_first()
    for idx, journal in enumerate(journals):
        ts = parse_journal_tickers(journal)
        if ts:
            note = "" if idx == 0 else f" (skipped {idx} newer journal(s) w/o snapshot)"
            print(f"📋 tickers from {journal.name}: {len(ts)} found{note}")
            return ts
    if journals:
        print(f"⚠️  no snapshot table in any of {len(journals)} journal(s)")
    env_tickers = os.environ.get("NEWS_TICKERS", "").strip()
    if env_tickers:
        ts = [s.strip().upper() for s in env_tickers.split(",") if s.strip()]
        print(f"📋 tickers from NEWS_TICKERS env: {len(ts)} found")
        return ts
    print("⚠️  no tickers found (journals had no snapshot + NEWS_TICKERS unset)")
    return []


# ── Cache helpers (identical to fetch_fundamentals.py) ──────────────────────
def is_cache_fresh(path: Path, ttl_hours: int) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < ttl_hours * 3600


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


# ── 中文新聞(鉅亨/cnyes) REST client (inline — no cross-repo import) ──────────────────────
def _news_get(endpoint: str, params: dict | None = None, token: str = "") -> dict | list:
    """Simple 中文新聞(鉅亨/cnyes) REST call with raise_for_status."""
    p = params or {}
    p["api_token"] = token
    p["fmt"] = "json"
    resp = requests.get(f"{NEWS_BASE}/{endpoint}", params=p, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Deduplication ───────────────────────────────────────────────────────────
def _normalise_title(title: str) -> str:
    """Lowercase + collapse whitespace for dedup comparison."""
    return re.sub(r"\s+", " ", title.lower().strip())


def dedup_articles(articles: list[dict]) -> list[dict]:
    """Remove syndication reprints (same title or link). Preserves order (newest-first)."""
    seen_titles: set[str] = set()
    seen_links: set[str] = set()
    out = []
    for a in articles:
        t = _normalise_title(a.get("title", ""))
        lnk = (a.get("link") or "").strip()
        if t and t in seen_titles:
            continue
        if lnk and lnk in seen_links:
            continue
        if t:
            seen_titles.add(t)
        if lnk:
            seen_links.add(lnk)
        out.append(a)
    return out


# ── News fetch for one ticker ───────────────────────────────────────────────
def fetch_news_articles(sym_us: str, token: str) -> tuple[list[dict], list[str]]:
    """Fetch, dedup, and truncate raw 中文新聞(鉅亨/cnyes) news articles for one ticker.

    Returns:
        (articles_list, fields_detected)
        fields_detected records which raw fields were present in the API response
        — the P3 body-mining gate checks 'content' in fields_available.
    """
    date_from = (date.today() - timedelta(days=NEWS_DAYS)).isoformat()
    raw_data = _news_get("news", params={
        "s": sym_us,
        "from": date_from,
        "limit": NEWS_LIMIT_FETCH,
    }, token=token)

    if not isinstance(raw_data, list):
        return [], []

    # Detect which fields the API returned (check first article)
    fields_detected: list[str] = []
    if raw_data:
        first = raw_data[0]
        for f in ("title", "date", "link", "source", "content", "symbols", "tags", "sentiment"):
            if f in first:
                fields_detected.append(f)

    articles = []
    for a in raw_data:
        content_raw = a.get("content") or ""
        sentiment = a.get("sentiment") or {}
        # 中文新聞(鉅亨/cnyes) /news has no "source" field — derive from link hostname
        link = a.get("link", "")
        source = a.get("source", "") or urlparse(link).netloc.removeprefix("www.")
        articles.append({
            "title": a.get("title", ""),
            "date": a.get("date", ""),
            "link": link,
            "source": source,
            "content_excerpt": content_raw[:BODY_CHARS] if content_raw else "",
            "symbols": a.get("symbols") or [],
            "tags": a.get("tags") or [],
            "sentiment": {
                "polarity": sentiment.get("polarity", 0),
                "neg": sentiment.get("neg", 0),
                "neu": sentiment.get("neu", 0),
                "pos": sentiment.get("pos", 0),
            },
        })

    # Dedup by title + link, then keep top NEWS_KEEP newest
    articles = dedup_articles(articles)[:NEWS_KEEP]
    return articles, fields_detected


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    load_env()
    force = "--force" in sys.argv
    dry_run = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")

    if not force and is_cache_fresh(NEWS_FILE, CACHE_TTL_HOURS):
        print("✅ news-articles.json fresh, skipping")
        return 0

    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if not token:
        print("⚠️  FINMIND_TOKEN not set — skipping news cache")
        empty = {
            "status": "skipped",
            "reason": "FINMIND_TOKEN_missing",
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "fields_available": [],
            "tickers": {},
            "errors": [],
        }
        if not dry_run:
            atomic_write(NEWS_FILE, empty)
        return 0

    tickers = get_tickers()
    if not tickers:
        empty = {
            "status": "skipped",
            "reason": "no_tickers",
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "fields_available": [],
            "tickers": {},
            "errors": [],
        }
        if not dry_run:
            atomic_write(NEWS_FILE, empty)
        return 0

    print(
        f"🔄 fetching 中文新聞(鉅亨/cnyes) news for {len(tickers)} tickers "
        f"(7d lookback, up to {NEWS_KEEP}/ticker after dedup)..."
    )

    result: dict = {}
    errors: list = []
    all_fields: set[str] = set()

    for i, sym in enumerate(tickers):
        sym_us = sym  # 台股 4 碼代號，無後綴
        if dry_run:
            print(f"[DRY-RUN] would fetch news for {sym_us}")
            continue
        try:
            articles, fields = fetch_news_articles(sym_us, token)
            all_fields.update(fields)
            result[sym] = {"articles": articles}
            body_flag = "body✓" if "content" in fields else "no-body"
            print(f"  ✓ {sym}: {len(articles)} articles ({body_flag})")
        except requests.HTTPError as e:
            errors.append({"ticker": sym, "error": f"HTTP {e.response.status_code}: {e}"})
            print(f"  ✗ {sym}: HTTP {e.response.status_code}")
        except Exception as e:
            errors.append({"ticker": sym, "error": f"{type(e).__name__}: {e}"})
            print(f"  ✗ {sym}: {type(e).__name__}: {e}")

        if i < len(tickers) - 1:
            time.sleep(TICKERS_DELAY)

    if dry_run:
        print("[DRY-RUN] complete, no write")
        return 0

    fields_sorted = sorted(all_fields)
    payload = {
        "status": "ok" if result else "empty",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        # P3 gate: check "content" in fields_available before body-mining
        "fields_available": fields_sorted,
        # article body lives under this per-article key (NOT "content")
        "body_field": "content_excerpt",
        "tickers": result,
        "errors": errors,
    }
    atomic_write(NEWS_FILE, payload)
    body_ok = "content" in all_fields
    print(
        f"✅ news-articles.json: {len(result)} tickers, {len(errors)} errors "
        f"({'body available — P3 signal mining enabled' if body_ok else '⚠️ no body field — P3 limited to headlines'})"
    )
    if errors:
        for err in errors:
            print(f"   ⚠️  {err['ticker']}: {err['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
