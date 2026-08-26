#!/usr/bin/env python3
"""
fetch_twitter.py — Cache raw X/Twitter posts from source-credit tracked accounts
for briefing consumption and source_credit.py claim scoring.

Source: X API v2 (https://api.x.com/2), official REST — bearer token auth.
Output:
  briefing-out/cache/twitter-signals.json
    {status, reason, generated_at, reads_used, est_cost_usd, budget{...},
     sources: {source_id: {platform, handle, kind, tier, tier_since, domains,
                            posts: [{id, date, text, url, tickers_mentioned,
                                     keywords_hit, has_number, metrics}]}},
     errors: [...]}
  briefing-out/cache/twitter-state.json
    {source_id: since_id}   — pagination cursor per tracked account
TTL:
  20 hours (mirrors briefing cadence — one real refresh per day; --force bypasses).

Source config (private, gitignored, may not exist yet):
  research/source-config.json
    sources[]: {id, platform, handle, kind, tier, tier_since, domains, enabled, x_user_id}
    x_fetch: {enabled, max_reads_per_run, per_account_limit, lookback_hours,
              exclude, cost_per_read_usd, keywords, extra_tickers, aliases}
  Missing/invalid config, x_fetch disabled, or no bearer token → this script is a
  well-behaved no-op: it writes {"status":"skipped", ...} and exits 0 so the
  briefing pipeline never fails on it.

Cost guard (billing caveat):
  X API v2 bills per Post/User object returned in the response body, not per
  request — a single "GET tweets" call can consume anywhere from 0 to
  max_results reads. We treat every user-lookup response and every tweet
  returned as one "read" against x_fetch.max_reads_per_run (overridable with
  --max-reads) and shrink max_results to whatever budget remains so a single
  call can never blow through the daily cap. If remaining budget drops below
  5 (X's own minimum for max_results) we stop the run entirely rather than
  attempt an out-of-spec request. HTTP 429 (rate limited) or 402 (payment
  required) also stop the run immediately with no retries — those are billing
  signals, not transient errors worth retrying into more spend.

Source order: core → trusted → probation (higher-credit sources get first
claim on a shrinking budget when many accounts are tracked).

Tagging (per post):
  tickers_mentioned = entities.cashtags ∪ whole-word holdings match ∪
                       whole-word extra_tickers match ∪ alias-phrase match
  keywords_hit      = whole-word match against x_fetch.keywords
  has_number        = tweet text (URLs stripped) contains a digit
  Whole-word matching mirrors fetch_leading.py's _kw_pattern: case-sensitive
  when the term is ALL-CAPS (tickers/acronyms), case-insensitive otherwise.

Usage:
  python3 tools/fetch_twitter.py                       # refresh if stale (TTL 20h)
  python3 tools/fetch_twitter.py --force                # force refresh
  python3 tools/fetch_twitter.py --only semi_daily,convertbond   # restrict to these source ids
  python3 tools/fetch_twitter.py --max-reads 20          # override x_fetch.max_reads_per_run
  DRY_RUN=1 python3 tools/fetch_twitter.py --force       # print the plan, make no API calls, write nothing
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ── Path setup ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "briefing-out" / "cache"
TWITTER_FILE = CACHE_DIR / "twitter-signals.json"
STATE_FILE = CACHE_DIR / "twitter-state.json"
CONFIG_FILE = ROOT / "research" / "source-config.json"

# Reuse holdings-ticker discovery from fetch_news.py instead of duplicating the
# journal-parsing logic (per implementation plan — same directory, sibling module).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_news import get_tickers  # noqa: E402

# ── Config ─────────────────────────────────────────────────────────────────
CACHE_TTL_HOURS = 20            # ~one real refresh per daily briefing cycle
X_API_BASE = "https://api.x.com/2"
REQUEST_TIMEOUT = 20

DEFAULT_MAX_READS_PER_RUN = 60
DEFAULT_PER_ACCOUNT_LIMIT = 10
DEFAULT_LOOKBACK_HOURS = 48
DEFAULT_COST_PER_READ_USD = 0.005
DEFAULT_EXCLUDE = ["retweets", "replies"]

MIN_MAX_RESULTS = 5             # X API v2 floor for max_results
MAX_MAX_RESULTS = 100           # X API v2 ceiling for max_results
MIN_REMAINING_TO_CONTINUE = 5   # below this, a valid request can't be built — stop the run

TIER_RANK = {"core": 0, "trusted": 1, "probation": 2}
FATAL_STATUS_CODES = {429, 402}  # rate-limited / payment-required — stop, don't retry


# ── .env loader (identical to fetch_news.py) ────────────────────────────────
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


# ── Cache helpers (identical to fetch_news.py) ──────────────────────────────
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


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def rfc3339(dt: datetime) -> str:
    """X API start_time wants RFC3339 with a literal 'Z', no microseconds."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(n, hi))


# ── Source config I/O ────────────────────────────────────────────────────────
def load_config() -> tuple[dict | None, str | None]:
    """Returns (config, error_reason). Missing/invalid config is not fatal —
    the caller writes a {"status":"skipped"} cache and exits 0."""
    if not CONFIG_FILE.exists():
        return None, "source_config_missing"
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8")), None
    except (json.JSONDecodeError, OSError):
        return None, "source_config_invalid"


def write_x_user_id(source_id: str, user_id: str) -> None:
    """Persist a resolved x_user_id back to the private config. Reloads from
    disk immediately before writing and touches only this one field on this
    one source, per the "machine writes tier/tier_since/tier_history/x_user_id
    only, everything else is hand-edited" contract."""
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    for s in cfg.get("sources", []):
        if s.get("id") == source_id:
            s["x_user_id"] = user_id
            break
    atomic_write(CONFIG_FILE, cfg)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# ── X API v2 client ──────────────────────────────────────────────────────────
def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def resolve_user_id(handle: str, token: str) -> str:
    """GET /2/users/by/username/{handle}. Costs 1 read (one User object)."""
    resp = requests.get(
        f"{X_API_BASE}/users/by/username/{handle}",
        headers=_headers(token),
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data")
    if not data or not data.get("id"):
        raise ValueError(f"user lookup returned no id: {body.get('errors', body)}")
    return data["id"]


def fetch_user_tweets(user_id: str, max_results: int, start_time: str,
                       since_id: str | None, exclude: list[str], token: str) -> tuple[list[dict], dict]:
    """GET /2/users/{id}/tweets. Costs 1 read per Post object returned."""
    params = {
        "max_results": max_results,
        "start_time": start_time,
        "exclude": ",".join(exclude),
        "tweet.fields": "created_at,public_metrics,entities",
    }
    if since_id:
        params["since_id"] = since_id
    resp = requests.get(
        f"{X_API_BASE}/users/{user_id}/tweets",
        headers=_headers(token),
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    return body.get("data") or [], body.get("meta") or {}


# ── Tagging helpers ──────────────────────────────────────────────────────────
URL_RE = re.compile(r"https?://\S+")
DIGIT_RE = re.compile(r"\d")


def _wb_pattern(term: str) -> re.Pattern:
    """Whole-word/whole-phrase match. Case-sensitive when the term is
    ALL-CAPS (tickers, acronyms) to avoid false hits like "ON" matching the
    word "on"; case-insensitive otherwise. Mirrors fetch_leading.py's
    _kw_pattern so ticker/keyword matching is consistent across the pipeline."""
    pat = r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
    flags = 0 if term.isupper() else re.IGNORECASE
    return re.compile(pat, flags)


def has_number(text: str) -> bool:
    """True if the tweet text contains a digit outside of any URL — shortened
    t.co links are base62 and can contain digits that aren't a quantified claim."""
    return bool(DIGIT_RE.search(URL_RE.sub("", text or "")))


def extract_cashtags(entities: dict | None) -> list[str]:
    tags = (entities or {}).get("cashtags") or []
    return sorted({t.get("tag", "").upper() for t in tags if t.get("tag")})


def tag_tickers(text: str, entities: dict | None, holdings: list[str],
                 extra_tickers: list[str], aliases: dict) -> list[str]:
    hits = set(extract_cashtags(entities))
    for tk in dict.fromkeys([*holdings, *extra_tickers]):  # de-dup, keep order
        if tk and _wb_pattern(tk).search(text):
            hits.add(tk.upper())
    for alias, ticker in (aliases or {}).items():
        if alias and ticker and _wb_pattern(alias).search(text):
            hits.add(ticker.upper())
    return sorted(hits)


def tag_keywords(text: str, keywords: list[str]) -> list[str]:
    return sorted({kw for kw in (keywords or []) if _wb_pattern(kw).search(text)})


# ── Skip payload (config missing / disabled / no token / no sources) ───────
def _skip_payload(reason: str, max_reads: int = 0) -> dict:
    return {
        "status": "skipped",
        "reason": reason,
        "generated_at": now_iso(),
        "reads_used": 0,
        "est_cost_usd": 0.0,
        "budget": {
            "max_reads_per_run": max_reads,
            "reads_used": 0,
            "remaining": max_reads,
            "budget_exhausted": False,
        },
        "sources": {},
        "errors": [],
    }


# ── Main ────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch X posts for source-credit tracked accounts.")
    p.add_argument("--force", action="store_true", help="ignore cache TTL and refetch")
    p.add_argument("--only", default="", help="comma-separated source ids to restrict this run to")
    p.add_argument("--max-reads", type=int, default=None,
                   help="override x_fetch.max_reads_per_run for this run")
    return p.parse_args()


def main() -> int:
    load_env()
    args = parse_args()
    dry_run = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")
    only_ids = {s.strip() for s in args.only.split(",") if s.strip()} or None

    if not args.force and is_cache_fresh(TWITTER_FILE, CACHE_TTL_HOURS):
        print("✅ twitter-signals.json fresh, skipping")
        return 0

    config, cfg_err = load_config()
    if cfg_err:
        print(f"⚠️  {cfg_err} — skipping twitter cache")
        if not dry_run:
            atomic_write(TWITTER_FILE, _skip_payload(cfg_err))
        return 0

    x_fetch = config.get("x_fetch") or {}
    if not x_fetch.get("enabled", False):
        print("⚠️  x_fetch disabled in source-config.json — skipping twitter cache")
        if not dry_run:
            atomic_write(TWITTER_FILE, _skip_payload("x_fetch_disabled"))
        return 0

    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token:
        print("⚠️  X_BEARER_TOKEN not set — skipping twitter cache")
        if not dry_run:
            atomic_write(TWITTER_FILE, _skip_payload("X_BEARER_TOKEN_missing"))
        return 0

    max_reads = args.max_reads if args.max_reads is not None else x_fetch.get(
        "max_reads_per_run", DEFAULT_MAX_READS_PER_RUN)
    per_account_limit = x_fetch.get("per_account_limit", DEFAULT_PER_ACCOUNT_LIMIT)
    lookback_hours = x_fetch.get("lookback_hours", DEFAULT_LOOKBACK_HOURS)
    cost_per_read = x_fetch.get("cost_per_read_usd", DEFAULT_COST_PER_READ_USD)
    exclude = x_fetch.get("exclude") or DEFAULT_EXCLUDE
    keywords = x_fetch.get("keywords") or []
    extra_tickers = x_fetch.get("extra_tickers") or []
    aliases = x_fetch.get("aliases") or {}

    sources_cfg = [s for s in (config.get("sources") or [])
                   if s.get("platform") == "x" and s.get("enabled", True)]
    if only_ids:
        missing = only_ids - {s.get("id") for s in sources_cfg}
        if missing:
            print(f"⚠️  --only ids not found among enabled x sources: {sorted(missing)}")
        sources_cfg = [s for s in sources_cfg if s.get("id") in only_ids]
    sources_cfg.sort(key=lambda s: TIER_RANK.get(s.get("tier", ""), 99))

    if not sources_cfg:
        print("⚠️  no enabled X sources in source-config.json — skipping twitter cache")
        if not dry_run:
            atomic_write(TWITTER_FILE, _skip_payload("no_enabled_sources", max_reads))
        return 0

    holdings = get_tickers()
    state = load_state()
    start_time = rfc3339(datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours))

    print(f"🔄 fetching X posts for {len(sources_cfg)} sources "
          f"(budget {max_reads} reads, {lookback_hours}h lookback)...")

    reads_used = 0
    budget_exhausted = False
    fatal_reason: str | None = None
    errors: list[dict] = []
    sources_out: dict = {}

    for src in sources_cfg:
        source_id = src.get("id", "")
        handle = src.get("handle", "")

        remaining = max_reads - reads_used
        if remaining < MIN_REMAINING_TO_CONTINUE:
            budget_exhausted = True
            print(f"⚠️  budget exhausted ({remaining} reads left) — stopping before {source_id}")
            break

        if dry_run:
            print(f"[DRY-RUN] would fetch @{handle} ({source_id}), "
                  f"remaining budget {remaining}, x_user_id="
                  f"{src.get('x_user_id') or 'unresolved (would +1 read)'}")
            continue

        user_id = src.get("x_user_id")
        if not user_id:
            try:
                user_id = resolve_user_id(handle, token)
                reads_used += 1  # 1 User object returned = 1 read
                write_x_user_id(source_id, user_id)
                src["x_user_id"] = user_id
                print(f"  ↳ resolved {handle} → x_user_id={user_id}")
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else 0
                errors.append({"source": source_id, "error": f"HTTP {code} (user lookup): {e}"})
                if code in FATAL_STATUS_CODES:
                    fatal_reason = "rate_limited" if code == 429 else "payment_required"
                    print(f"⛔ HTTP {code} on user lookup for {source_id} — stopping run (no retries)")
                    break
                print(f"  ✗ {source_id}: HTTP {code} on user lookup")
                continue
            except Exception as e:
                errors.append({"source": source_id, "error": f"user lookup {type(e).__name__}: {e}"})
                print(f"  ✗ {source_id}: user lookup {type(e).__name__}: {e}")
                continue

        remaining = max_reads - reads_used
        if remaining < MIN_REMAINING_TO_CONTINUE:
            budget_exhausted = True
            print(f"⚠️  budget exhausted ({remaining} reads left) — stopping before {source_id} tweets")
            break

        max_results = clamp(min(per_account_limit, remaining), MIN_MAX_RESULTS, MAX_MAX_RESULTS)
        since_id = state.get(source_id)

        try:
            tweets, _meta = fetch_user_tweets(user_id, max_results, start_time, since_id, exclude, token)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            errors.append({"source": source_id, "error": f"HTTP {code} (tweets): {e}"})
            if code in FATAL_STATUS_CODES:
                fatal_reason = "rate_limited" if code == 429 else "payment_required"
                print(f"⛔ HTTP {code} on tweets for {source_id} — stopping run (no retries)")
                break
            print(f"  ✗ {source_id}: HTTP {code} on tweets")
            continue
        except Exception as e:
            errors.append({"source": source_id, "error": f"tweets {type(e).__name__}: {e}"})
            print(f"  ✗ {source_id}: {type(e).__name__}: {e}")
            continue

        reads_used += len(tweets)  # billed per Post object returned

        posts = []
        for t in tweets:
            text = t.get("text", "") or ""
            posts.append({
                "id": t.get("id", ""),
                "date": t.get("created_at", ""),
                "text": text,
                "url": f"https://x.com/{handle}/status/{t.get('id', '')}",
                "tickers_mentioned": tag_tickers(text, t.get("entities"), holdings, extra_tickers, aliases),
                "keywords_hit": tag_keywords(text, keywords),
                "has_number": has_number(text),
                "metrics": t.get("public_metrics") or {},
            })

        if tweets:
            state[source_id] = max((t.get("id", "0") for t in tweets), key=lambda x: int(x))

        sources_out[source_id] = {
            "platform": src.get("platform", "x"),
            "handle": handle,
            "kind": src.get("kind"),
            "tier": src.get("tier"),
            "tier_since": src.get("tier_since"),
            "domains": src.get("domains") or [],
            "posts": posts,
        }
        print(f"  ✓ {source_id} (@{handle}): {len(posts)} posts, reads_used={reads_used}")

    if dry_run:
        print("[DRY-RUN] complete, no write")
        return 0

    if fatal_reason:
        status = "partial"
        reason = fatal_reason
    elif budget_exhausted:
        status = "partial"
        reason = "budget_exhausted"
    elif errors:
        status = "partial"
        reason = "partial_errors"
    else:
        status = "ok"
        reason = None

    payload = {
        "status": status,
        "reason": reason,
        "generated_at": now_iso(),
        "reads_used": reads_used,
        "est_cost_usd": round(reads_used * cost_per_read, 4),
        "budget": {
            "max_reads_per_run": max_reads,
            "reads_used": reads_used,
            "remaining": max(max_reads - reads_used, 0),
            "budget_exhausted": budget_exhausted,
        },
        "sources": sources_out,
        "errors": errors,
    }
    atomic_write(TWITTER_FILE, payload)
    atomic_write(STATE_FILE, state)

    total_posts = sum(len(s["posts"]) for s in sources_out.values())
    est_cost = payload["est_cost_usd"]
    print(f"✅ twitter-signals.json: {len(sources_out)} sources, {total_posts} posts, "
          f"reads_used {reads_used} (~${est_cost})")
    if errors:
        for err in errors:
            print(f"   ⚠️  {err['source']}: {err['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
