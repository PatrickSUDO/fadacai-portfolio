#!/usr/bin/env python3
"""
source_credit.py — Score claims made by external information sources (X/Twitter,
Substack, RSS trackers, podcasts, manual notes) against what actually happened,
and let a source's own hit rate — not its follow count — decide how much weight
its future claims get.

Two claim kinds:
  fact  — a quantified, falsifiable claim about a specific ticker (e.g. "ON SiC
          lead times stretching to 26 weeks"), scored by magnitude_check() once a
          human supplies the confirmed actual number.
  view  — a directional call on a ticker (e.g. a podcast naming a stock + a
          direction), scored automatically against price + benchmark alpha,
          the same mechanism as shadow_signals.py's cmd_score.

Nothing here blocks a trade. A source's tier (probation/trusted/core) is
display-only until it has survived >=2 /trade-review cycles (CLAUDE.md 0e's
shadow-signal discipline — same rule already applied to the A4 self-valuation
flag and the R18 earnings-window block in shadow_signals.py).

Storage
  research/source-config.json    private whitelist of sources (hand-edited; this
                                  tool only ever rewrites tier/tier_since/tier_history)
  research/source-credit.jsonl   one claim per line, JSONL, atomic rewrite

Scoring formulas (verbatim from the design doc — treat this as the spec):

  fact magnitude_check：
    方向錯 → miss；方向對且 |actual−value|/|value| ≤ 0.5 → hit；
    方向對但超幅 → partial；缺數字 → null
    （verdict 以 --actual 證據為準，與 check 不符只警告不擋）

  lead time：
    lead_time_days = (first_news_date or confirm_date) − posted_date
    ≤0 → timeliness_credit = 0（準確度照計，不因領先時間非正而扣分）

  view (identical to shadow_signals.py's cmd_score)：
    bench = benchmark_for(ticker)[:-3]
    alpha = (p1/p0 - 1) - (b1/b0 - 1)
    verdict = hit if (alpha > 0) == (direction == "up") else miss
    target_date_used = min(target_date, asof)

  Beta posterior (90d half-life recency weighting, DISPLAY ONLY — tier uses the
  unweighted hit_rate below)：
    s = 1 / 0.5 / 0             for hit / partial / miss
    w = 0.5 ** (age_days / half_life_days)
    α = 1 + Σ w·s,  β = 1 + Σ w·(1−s)
    posterior_mean = α / (α+β);  effective_n = Σw

  hit_rate (unweighted, used for TIER) = (hits + 0.5·partial) / n_scored

  vague_ratio = (unscorable + expired) / n_total
  noise = n_total >= 5 and vague_ratio > 0.7

  tier evaluation order — first match wins; tier_lock freezes the current tier：
    ① demote  → probation  if misses_in_last_5 >= 2
                            or (n_scored >= 4 and hit_rate < 0.5)
    ② core                 if hits >= 6 and hit_rate >= 0.75
                            and distinct_tickers_hit >= 2
    ③ trusted              if hits >= 3 and hit_rate >= 0.65
    ④ else                 → probation

  stats per-source fields: n_total n_pending n_scored hits partial misses
    unscorable expired hit_rate posterior_mean effective_n distinct_tickers_hit
    misses_in_last_5 mean_lead_time_days vague_ratio noise mean_excess_alpha_pct
    backtest_share proposed_tier  (+ by_kind / overall / promotion_rule)

Exit codes: 0 ok · 1 validation/usage error · 2 collision (claim id already
decided — same semantics as thesis_ledger.py's EXIT_COLLISION) · 3 not found
(unknown source-id, or unknown claim id). `resolve-due` always exits 0 — it
must never block the briefing pipeline.

See docs/source-credit.md for the full design writeup and CLI reference.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = ROOT / "research" / "source-credit.jsonl"
DEFAULT_CONFIG = ROOT / "research" / "source-config.json"

VALID_PLATFORMS = {"x", "substack", "rss", "podcast", "manual"}
VALID_KINDS = {"fact", "view"}
VALID_TIERS = {"probation", "trusted", "core"}
VALID_STATUSES = {"pending", "resolved", "unscorable", "expired"}
VALID_FACT_VERDICTS = {"hit", "miss", "partial"}

EXIT_OK, EXIT_GENERIC, EXIT_COLLISION, EXIT_NOT_FOUND = 0, 1, 2, 3


def today():
    return date.today().isoformat()


def _emit(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _fail(code, msg, **extra):
    _emit({"error": msg, **extra})
    return code


# ── storage: config (JSON, private whitelist) ───────────────────────────────
def load_config(path):
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"source config not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def save_config(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".source-config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(p))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def find_source(config, source_id):
    for s in config.get("sources", []):
        if s["id"] == source_id:
            return s
    return None


# ── storage: claims ledger (JSONL, one claim per line) ──────────────────────
def load_claims(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def save_claims(path, claims):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".source-credit-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for c in claims:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        os.replace(tmp, str(p))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ── id / slug helpers ────────────────────────────────────────────────────────
def _slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", str(s).strip().lower())
    return s.strip("-") or "x"


def make_claim_id(source_id, kind, posted_date, ticker, *, metric=None, direction=None,
                   horizon_days=None, slug=None):
    """fact: source:date:TICKER:metric ; view: source:date:TICKER:up-h30"""
    if slug:
        return f"{source_id}:{posted_date}:{_slugify(slug)}"
    t = ticker or "NONE"
    if kind == "fact":
        m = _slugify(metric) if metric else "claim"
        return f"{source_id}:{posted_date}:{t}:{m}"
    return f"{source_id}:{posted_date}:{t}:{direction}-h{horizon_days}"


# ── scoring primitives ───────────────────────────────────────────────────────
def magnitude_check(direction, value, actual_num, tolerance=0.5):
    """方向錯 → miss；方向對且 |actual-value|/|value| <= tolerance → hit；
    方向對但超幅 → partial；缺數字（value 或 actual_num 任一為 None）→ null(None)."""
    if actual_num is None or value is None:
        return None
    if direction == "up":
        dir_ok = actual_num > 0
    elif direction == "down":
        dir_ok = actual_num < 0
    else:  # flat — direction-agnostic, only the magnitude question applies
        dir_ok = True
    if not dir_ok:
        return "miss"
    if value == 0:
        return "partial"  # direction right but no relative magnitude is computable
    rel_err = abs(actual_num - value) / abs(value)
    return "hit" if rel_err <= tolerance else "partial"


def lead_time_days(posted_date, confirm_date, first_news_date=None):
    ref = first_news_date or confirm_date
    return (date.fromisoformat(ref) - date.fromisoformat(posted_date)).days


def timeliness_credit(lead_days):
    return lead_days if lead_days > 0 else 0


def weight(age_days, half_life_days=90):
    return 0.5 ** (age_days / half_life_days)


def beta_posterior(scored, asof, half_life_days=90):
    """scored: iterable of (verdict, resolved_at_date_str). Beta(1,1) prior +
    time-decayed evidence. Display-only estimate — tier decisions use the plain
    unweighted hit_rate, not this posterior."""
    a, b, total_w = 1.0, 1.0, 0.0
    asof_d = date.fromisoformat(asof)
    for verdict, resolved_at in scored:
        s = {"hit": 1.0, "partial": 0.5, "miss": 0.0}.get(verdict, 0.0)
        try:
            age = max((asof_d - date.fromisoformat(resolved_at)).days, 0)
        except (TypeError, ValueError):
            age = 0
        w = weight(age, half_life_days)
        a += w * s
        b += w * (1 - s)
        total_w += w
    return {"alpha": a, "beta": b, "posterior_mean": a / (a + b), "effective_n": total_w}


def is_noise(n_total, vague_ratio, thresholds):
    cfg = thresholds.get("noise", {})
    return n_total >= cfg.get("min_total", 5) and vague_ratio > cfg.get("max_vague_ratio", 0.7)


def propose_tier(*, n_scored, hits, partial, misses, hit_rate, distinct_tickers_hit,
                  misses_in_last_n, thresholds, tier_lock=False, current_tier="probation"):
    """Evaluation order: demote overrides core/trusted; tier_lock freezes current_tier."""
    if tier_lock:
        return current_tier
    demote_cfg = thresholds["demote"]
    demote = (misses_in_last_n >= demote_cfg["misses_in_last_n"]) or (
        n_scored >= demote_cfg["min_n_for_rate"] and hit_rate < demote_cfg["max_hit_rate"]
    )
    if demote:
        return "probation"
    core_cfg = thresholds["core"]
    if (hits >= core_cfg["min_hits"] and hit_rate >= core_cfg["min_hit_rate"]
            and distinct_tickers_hit >= core_cfg["min_distinct_tickers"]):
        return "core"
    trusted_cfg = thresholds["trusted"]
    if hits >= trusted_cfg["min_hits"] and hit_rate >= trusted_cfg["min_hit_rate"]:
        return "trusted"
    return "probation"


def score_view(claim, asof):
    """Resolve a view claim by comparing ticker excess return vs its benchmark.
    Identical formula to shadow_signals.py's cmd_score:
        bench = benchmark_for(ticker)[:-3]
        alpha = (p1/p0 - 1) - (b1/b0 - 1)
        verdict = hit if (alpha > 0) == (direction == "up") else miss
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from trade_ledger import benchmark_for, eod_series, load_env, _asof_close  # noqa: PLC0415

    load_env()
    ticker = claim.get("ticker")
    if not ticker:
        raise RuntimeError(f"claim {claim.get('id')} has no ticker — unscorable")
    bench = benchmark_for(ticker)[:-3]
    p0_date = claim["posted_date"]
    target_date_used = min(claim["target_date"], asof)
    series_t = eod_series(f"{ticker}.US", p0_date, asof)
    series_b = eod_series(f"{bench}.US", p0_date, asof)
    p0 = _asof_close(series_t, p0_date)
    p1 = _asof_close(series_t, target_date_used)
    b0 = _asof_close(series_b, p0_date)
    b1 = _asof_close(series_b, target_date_used)
    if not (p0 and p1 and b0 and b1):
        raise RuntimeError(f"missing price data for {ticker}/{bench} around {p0_date}..{target_date_used}")
    alpha = (p1 / p0 - 1) - (b1 / b0 - 1)
    verdict = "hit" if (alpha > 0) == (claim["direction"] == "up") else "miss"
    return {
        "resolved_at": asof, "method": "price", "benchmark": bench,
        "p0": p0, "p1": p1, "b0": b0, "b1": b1,
        "excess_alpha_pct": round(alpha * 100, 2),
        "verdict": verdict, "target_date_used": target_date_used,
    }


# ── stats aggregation ────────────────────────────────────────────────────────
def compute_source_stats(claims, asof, thresholds, current_tier, tier_lock):
    n_total = len(claims)
    n_pending = sum(1 for c in claims if c.get("status") == "pending")
    unscorable = sum(1 for c in claims if c.get("status") == "unscorable")
    expired = sum(1 for c in claims if c.get("status") == "expired")
    resolved = [c for c in claims if c.get("status") == "resolved"]

    verdicted = [(c, (c.get("resolution") or {}).get("verdict")) for c in resolved]
    verdicted = [(c, v) for c, v in verdicted if v in ("hit", "miss", "partial")]

    hits = sum(1 for _, v in verdicted if v == "hit")
    partial = sum(1 for _, v in verdicted if v == "partial")
    misses = sum(1 for _, v in verdicted if v == "miss")
    n_scored = hits + partial + misses
    hit_rate = round((hits + 0.5 * partial) / n_scored, 4) if n_scored else None

    distinct_tickers_hit = len({c.get("ticker") for c, v in verdicted if v == "hit" and c.get("ticker")})

    last_n = thresholds["demote"]["last_n"]
    scored_sorted = sorted(
        verdicted,
        key=lambda cv: (cv[0].get("resolution") or {}).get("resolved_at") or cv[0].get("posted_date") or "",
        reverse=True,
    )
    misses_in_last_5 = sum(1 for c, v in scored_sorted[:last_n] if v == "miss")

    lead_times = [c["resolution"].get("lead_time_days") for c in resolved
                  if c.get("kind") == "fact" and (c.get("resolution") or {}).get("lead_time_days") is not None]
    mean_lead_time_days = round(sum(lead_times) / len(lead_times), 1) if lead_times else None

    alphas = [c["resolution"].get("excess_alpha_pct") for c in resolved
              if c.get("kind") == "view" and (c.get("resolution") or {}).get("excess_alpha_pct") is not None]
    mean_excess_alpha_pct = round(sum(alphas) / len(alphas), 2) if alphas else None

    vague_ratio = round((unscorable + expired) / n_total, 3) if n_total else 0.0
    noise = is_noise(n_total, vague_ratio, thresholds)

    backtest_n = sum(1 for c in claims if c.get("backtest"))
    backtest_share = round(backtest_n / n_total, 3) if n_total else None

    posterior = beta_posterior(
        [(v, (c.get("resolution") or {}).get("resolved_at") or asof) for c, v in verdicted],
        asof, thresholds.get("half_life_days", 90),
    )

    proposed = propose_tier(
        n_scored=n_scored, hits=hits, partial=partial, misses=misses,
        hit_rate=hit_rate or 0.0, distinct_tickers_hit=distinct_tickers_hit,
        misses_in_last_n=misses_in_last_5, thresholds=thresholds,
        tier_lock=tier_lock, current_tier=current_tier,
    )

    return {
        "n_total": n_total, "n_pending": n_pending, "n_scored": n_scored,
        "hits": hits, "partial": partial, "misses": misses,
        "unscorable": unscorable, "expired": expired,
        "hit_rate": hit_rate,
        "posterior_mean": round(posterior["posterior_mean"], 4),
        "effective_n": round(posterior["effective_n"], 3),
        "distinct_tickers_hit": distinct_tickers_hit,
        "misses_in_last_5": misses_in_last_5,
        "mean_lead_time_days": mean_lead_time_days,
        "vague_ratio": vague_ratio,
        "noise": noise,
        "mean_excess_alpha_pct": mean_excess_alpha_pct,
        "backtest_share": backtest_share,
        "proposed_tier": proposed,
    }


def compute_tier_changes(sources, claims, thresholds, asof):
    changes = []
    for src in sources:
        if src.get("tier_lock"):
            continue
        group = [c for c in claims if c.get("source_id") == src["id"]]
        stats = compute_source_stats(group, asof, thresholds, src.get("tier", "probation"),
                                      src.get("tier_lock", False))
        proposed = stats["proposed_tier"]
        if proposed != src.get("tier"):
            changes.append({"id": src["id"], "from": src.get("tier"), "to": proposed,
                             "n_scored": stats["n_scored"], "hit_rate": stats["hit_rate"]})
    return changes


def apply_tier_changes(sources, changes, asof):
    by_id = {c["id"]: c for c in changes}
    for src in sources:
        ch = by_id.get(src["id"])
        if not ch:
            continue
        src.setdefault("tier_history", []).append({
            "date": asof, "from": ch["from"], "to": ch["to"],
            "reason": f"n_scored={ch['n_scored']}, hit_rate={ch['hit_rate']}",
        })
        src["tier"] = ch["to"]
        src["tier_since"] = asof


# ── commands: sources / claims lifecycle ────────────────────────────────────
def cmd_add_source(args):
    config = load_config(args.config)
    if find_source(config, args.id) is not None:
        return _fail(EXIT_GENERIC,
                     f"source already exists: {args.id}（其餘欄位請直接編輯 {args.config}）")
    asof = args.asof or today()
    entry = {
        "id": args.id, "platform": args.platform, "handle": args.handle,
        "url": args.url, "kind": args.kind,
        "domains": [d.strip() for d in args.domains.split(",") if d.strip()],
        "tier": args.tier, "tier_since": asof, "tier_lock": False, "tier_history": [],
        "x_user_id": None, "enabled": True, "added": asof, "notes": args.notes or "",
    }
    config.setdefault("sources", []).append(entry)
    save_config(args.config, config)
    _emit({"action": "inserted", "id": args.id})
    return EXIT_OK


def cmd_add_claim(args):
    config = load_config(args.config)
    src = find_source(config, args.source_id)
    if src is None:
        return _fail(EXIT_NOT_FOUND, f"unknown source: {args.source_id}")
    if len(args.raw_quote) > 120:
        return _fail(EXIT_GENERIC, f"raw_quote too long: {len(args.raw_quote)} chars (max 120)")

    tickers_raw = args.tickers.strip()
    if tickers_raw.lower() == "none":
        if args.kind != "view":
            return _fail(EXIT_GENERIC, "--tickers none is only valid for kind=view")
        tickers, ticker = [], None
    else:
        tickers = [t.strip().upper() for t in tickers_raw.split(",") if t.strip()]
        if not tickers:
            return _fail(EXIT_GENERIC, "no tickers provided")
        ticker = tickers[0]

    horizon_days, target_date = None, None
    if args.kind == "fact":
        if not args.confirm_by:
            return _fail(EXIT_GENERIC, "fact claims require --confirm-by")
    else:  # view
        if args.direction not in ("up", "down"):
            return _fail(EXIT_GENERIC, "view claims require --direction up|down (not flat)")
        allowed = config["credit_thresholds"].get("view_horizons_allowed", [30, 60])
        horizon_days = args.horizon_days or config["credit_thresholds"].get("view_default_horizon_days", 30)
        if horizon_days not in allowed:
            return _fail(EXIT_GENERIC, f"--horizon-days {horizon_days} not in allowed set {allowed}")
        target_date = (date.fromisoformat(args.posted_date) + timedelta(days=horizon_days)).isoformat()

    asof = args.asof or today()
    claim_id = make_claim_id(args.source_id, args.kind, args.posted_date, ticker,
                              metric=args.metric, direction=args.direction,
                              horizon_days=horizon_days, slug=args.slug)

    claims = load_claims(args.ledger)
    existing_idx = next((i for i, c in enumerate(claims) if c["id"] == claim_id), None)
    status = "unscorable" if (args.kind == "view" and ticker is None) else "pending"

    entry = {
        "id": claim_id, "source_id": args.source_id, "platform": src.get("platform"),
        "kind": args.kind, "tickers": tickers, "ticker": ticker, "domain": args.domain,
        "claim": args.claim, "metric": args.metric, "value": args.value, "value_num": args.value_num,
        "direction": args.direction, "raw_quote": args.raw_quote, "url": args.url,
        "posted_date": args.posted_date, "first_news_date": args.first_news_date,
        "confirm_by": args.confirm_by, "horizon_days": horizon_days, "target_date": target_date,
        "backtest": bool(args.backtest), "status": status, "created_at": asof,
        "note": args.note, "resolution": None,
    }

    if existing_idx is None:
        claims.append(entry)
        action = "inserted"
    else:
        if claims[existing_idx]["status"] != "pending":
            return _fail(EXIT_COLLISION,
                         f"{claim_id} already {claims[existing_idx]['status']} — refusing to overwrite")
        entry["created_at"] = claims[existing_idx]["created_at"]
        claims[existing_idx] = entry
        action = "updated"

    save_claims(args.ledger, claims)
    _emit({"action": action, "id": claim_id, "status": status, "target_date": target_date})
    return EXIT_OK


def cmd_due(args):
    claims = load_claims(args.ledger)
    config = load_config(args.config)
    asof = args.asof or today()
    expire_after = config["credit_thresholds"].get("fact_expire_after_days", 30)
    facts_due, views_due, expired = [], [], []
    changed = False
    for c in claims:
        if c.get("status") != "pending":
            continue
        if c["kind"] == "fact":
            cb = c.get("confirm_by")
            if not cb or cb > asof:
                continue
            days_over = (date.fromisoformat(asof) - date.fromisoformat(cb)).days
            if days_over > expire_after:
                c["status"] = "expired"
                c["resolution"] = {
                    "resolved_at": asof, "method": "auto-expire", "verdict": None,
                    "note": f"逾期 {days_over} 天未驗收（confirm_by {cb}），當作無結果",
                }
                expired.append(c)
                changed = True
            else:
                facts_due.append(c)
        else:  # view — resolve-due auto-scores these; `due` only reports them
            td = c.get("target_date")
            if td and td <= asof:
                views_due.append(c)
    if changed:
        save_claims(args.ledger, claims)
    _emit({
        "asof": asof,
        "facts_due": [{"id": c["id"], "source_id": c["source_id"], "ticker": c.get("ticker"),
                        "claim": c.get("claim"), "confirm_by": c.get("confirm_by")} for c in facts_due],
        "views_due": [{"id": c["id"], "source_id": c["source_id"], "ticker": c.get("ticker"),
                        "target_date": c.get("target_date")} for c in views_due],
        "expired": [{"id": c["id"], "source_id": c["source_id"]} for c in expired],
        "facts_due_count": len(facts_due), "views_due_count": len(views_due),
        "expired_count": len(expired),
    })
    return EXIT_OK


def cmd_resolve(args):
    claims = load_claims(args.ledger)
    config = load_config(args.config)
    idx = next((i for i, c in enumerate(claims) if c["id"] == args.id), None)
    if idx is None:
        return _fail(EXIT_NOT_FOUND, f"claim not found: {args.id}")
    c = claims[idx]
    if c.get("status") != "pending":
        return _fail(EXIT_GENERIC, f"{args.id} already {c['status']} — nothing to resolve")
    asof = args.asof or today()

    if c["kind"] == "fact":
        if not args.verdict or not args.actual:
            return _fail(EXIT_GENERIC, "fact resolve requires --verdict and --actual")
        if args.verdict not in VALID_FACT_VERDICTS:
            return _fail(EXIT_GENERIC, f"invalid --verdict: {args.verdict} (use hit|miss|partial)")
        confirm_date = args.confirm_date or asof
        first_news_date = args.first_news_date or c.get("first_news_date")
        lead = lead_time_days(c["posted_date"], confirm_date, first_news_date)
        credit = timeliness_credit(lead)
        tol = config["credit_thresholds"].get("fact_magnitude_tolerance", 0.5)
        mcheck = magnitude_check(c.get("direction"), c.get("value_num"), args.actual_num, tolerance=tol)
        resolution = {
            "resolved_at": asof, "method": "manual", "verdict": args.verdict,
            "actual": args.actual, "actual_num": args.actual_num,
            "confirm_date": confirm_date, "lead_time_days": lead,
            "timeliness_credit": credit, "magnitude_check": mcheck,
        }
        if mcheck is not None and mcheck != args.verdict:
            resolution["warning"] = (f"magnitude_check={mcheck} 與 --verdict={args.verdict} 不一致，"
                                      f"以 --verdict 為準（{args.actual}）")
        c["status"] = "resolved"
        c["resolution"] = resolution
    else:  # view
        td = c.get("target_date")
        if td and td > asof and not args.force:
            return _fail(EXIT_GENERIC, f"{args.id} not due until {td} (--force to resolve early)")
        if not c.get("ticker"):
            return _fail(EXIT_GENERIC, f"{args.id} has no ticker — unscorable, cannot resolve via price")
        try:
            resolution = score_view(c, asof)
        except Exception as exc:  # noqa: BLE001
            return _fail(EXIT_GENERIC, f"price resolution failed: {exc}")
        c["status"] = "resolved"
        c["resolution"] = resolution

    save_claims(args.ledger, claims)
    _emit(c["resolution"])
    return EXIT_OK


def cmd_resolve_due(args):
    """View claims are auto-resolved by price; fact claims are only listed, never
    guessed. Always exits 0 — must never block the daily briefing pipeline."""
    claims = load_claims(args.ledger)
    asof = args.asof or today()
    done, failed, facts_listed = [], [], []
    changed = False
    for c in claims:
        if c.get("status") != "pending":
            continue
        if c["kind"] == "view":
            td = c.get("target_date")
            if td and td <= asof:
                try:
                    res = score_view(c, asof)
                    c["status"] = "resolved"
                    c["resolution"] = res
                    changed = True
                    done.append(c)
                except Exception as exc:  # noqa: BLE001
                    failed.append({"id": c["id"], "error": str(exc)})
        elif c["kind"] == "fact":
            cb = c.get("confirm_by")
            if cb and cb <= asof:
                facts_listed.append(c)

    if changed:
        save_claims(args.ledger, claims)
    for c in done:
        r = c["resolution"]
        print(f"✅ {c['id']}: view {c.get('direction')} h{c.get('horizon_days')} → "
              f"alpha {r['excess_alpha_pct']:+.2f}% vs {r['benchmark']} (verdict={r['verdict']})")
    for f in failed:
        print(f"⚠️ {f['id']}: {f['error']}")
    for c in facts_listed:
        print(f"📋 {c['id']}: fact 待人工驗收（confirm_by {c.get('confirm_by')}）— "
              f"用 `resolve --id {c['id']} --verdict ... --actual ...`")
    if not done and not failed and not facts_listed:
        print("nothing due")
    _emit({"resolved_views": len(done), "failed_views": len(failed),
           "facts_pending_manual": len(facts_listed)})
    return EXIT_OK  # resolve-due always exits 0


def cmd_stats(args):
    claims = load_claims(args.ledger)
    config = load_config(args.config)
    asof = args.asof or today()
    thresholds = config["credit_thresholds"]

    if args.source:
        claims = [c for c in claims if c.get("source_id") == args.source]
    if args.kind:
        claims = [c for c in claims if c.get("kind") == args.kind]
    if args.since:
        claims = [c for c in claims if (c.get("posted_date") or "") >= args.since]

    sources_by_id = {s["id"]: s for s in config.get("sources", [])}
    ids = sorted({c["source_id"] for c in claims} | ({args.source} if args.source else set()))
    by_source = {}
    for sid in ids:
        group = [c for c in claims if c.get("source_id") == sid]
        src = sources_by_id.get(sid, {})
        s_stats = compute_source_stats(group, asof, thresholds,
                                        src.get("tier", "probation"), src.get("tier_lock", False))
        s_stats["current_tier"] = src.get("tier", "probation")
        s_stats["tier_lock"] = src.get("tier_lock", False)
        s_stats["platform"] = src.get("platform")
        s_stats["kind"] = src.get("kind")
        by_source[sid] = s_stats

    overall = compute_source_stats(claims, asof, thresholds, "probation", False)
    by_kind = {
        k: compute_source_stats([c for c in claims if c.get("kind") == k], asof, thresholds, "probation", False)
        for k in ("fact", "view")
    }
    trusted_cfg, core_cfg, demote_cfg = thresholds["trusted"], thresholds["core"], thresholds["demote"]
    _emit({
        "asof": asof,
        "by_source": by_source,
        "overall": overall,
        "by_kind": by_kind,
        "promotion_rule": (
            f"trusted: hits>={trusted_cfg['min_hits']} & hit_rate>={trusted_cfg['min_hit_rate']} | "
            f"core: hits>={core_cfg['min_hits']} & hit_rate>={core_cfg['min_hit_rate']} & "
            f"distinct_tickers_hit>={core_cfg['min_distinct_tickers']} | "
            f"demote(overrides both): misses_in_last_{demote_cfg['last_n']}>={demote_cfg['misses_in_last_n']} "
            f"or (n_scored>={demote_cfg['min_n_for_rate']} & hit_rate<{demote_cfg['max_hit_rate']})"
        ),
    })
    return EXIT_OK


def cmd_tiers(args):
    config = load_config(args.config)
    claims = load_claims(args.ledger)
    asof = args.asof or today()
    thresholds = config["credit_thresholds"]
    changes = compute_tier_changes(config.get("sources", []), claims, thresholds, asof)
    applied = False
    if not args.dry_run and changes:
        apply_tier_changes(config["sources"], changes, asof)
        save_config(args.config, config)
        applied = True
    _emit({"asof": asof, "dry_run": bool(args.dry_run), "changes": changes, "applied": applied})
    return EXIT_OK


def cmd_list(args):
    if args.sources:
        config = load_config(args.config)
        items = config.get("sources", [])
        if args.kind:
            items = [s for s in items if s.get("kind") == args.kind]
        _emit({"count": len(items), "sources": items})
        return EXIT_OK
    claims = load_claims(args.ledger)
    if args.source:
        claims = [c for c in claims if c.get("source_id") == args.source]
    if args.status:
        claims = [c for c in claims if c.get("status") == args.status]
    if args.kind:
        claims = [c for c in claims if c.get("kind") == args.kind]
    _emit({"count": len(claims), "claims": claims})
    return EXIT_OK


# ── CLI ──────────────────────────────────────────────────────────────────────
def _build_parser():
    p = argparse.ArgumentParser(
        description="Source credit ledger — score X/Substack/RSS/podcast claims, gate source tiers")
    p.add_argument("--ledger", default=str(DEFAULT_LEDGER), help="path to source-credit.jsonl")
    p.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to source-config.json")
    p.add_argument("--asof", default=None, help="override today (YYYY-MM-DD), for testing/backfill")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("add-source", help="register a new source in the config whitelist")
    s.add_argument("--id", required=True)
    s.add_argument("--platform", required=True, choices=sorted(VALID_PLATFORMS))
    s.add_argument("--handle", required=True)
    s.add_argument("--url", default=None)
    s.add_argument("--kind", required=True, choices=sorted(VALID_KINDS))
    s.add_argument("--domains", required=True, help="comma-separated")
    s.add_argument("--tier", default="probation", choices=sorted(VALID_TIERS))
    s.add_argument("--notes", default=None)
    s.set_defaults(func=cmd_add_source)

    c = sub.add_parser("add-claim", help="register a scoreable claim from a source")
    c.add_argument("--source-id", required=True, dest="source_id")
    c.add_argument("--kind", required=True, choices=sorted(VALID_KINDS))
    c.add_argument("--tickers", required=True, help="comma-separated, or literal 'none' (view only)")
    c.add_argument("--claim", required=True)
    c.add_argument("--raw-quote", required=True, dest="raw_quote", help="verbatim quote, <=120 chars")
    c.add_argument("--url", required=True)
    c.add_argument("--posted-date", required=True, dest="posted_date")
    c.add_argument("--metric", default=None)
    c.add_argument("--value", default=None)
    c.add_argument("--value-num", type=float, default=None, dest="value_num")
    c.add_argument("--direction", required=True, choices=["up", "down", "flat"])
    c.add_argument("--confirm-by", default=None, dest="confirm_by", help="fact only")
    c.add_argument("--first-news-date", default=None, dest="first_news_date")
    c.add_argument("--horizon-days", type=int, default=None, dest="horizon_days", help="view only")
    c.add_argument("--domain", default=None)
    c.add_argument("--backtest", action="store_true")
    c.add_argument("--slug", default=None, help="override the id's final segment")
    c.add_argument("--note", default=None)
    c.set_defaults(func=cmd_add_claim)

    d = sub.add_parser("due", help="list claims due for verification; auto-expires stale facts")
    d.set_defaults(func=cmd_due)

    r = sub.add_parser("resolve", help="manually resolve one claim (facts) or force-resolve a view early")
    r.add_argument("--id", required=True)
    r.add_argument("--verdict", default=None, choices=sorted(VALID_FACT_VERDICTS))
    r.add_argument("--actual", default=None)
    r.add_argument("--actual-num", type=float, default=None, dest="actual_num")
    r.add_argument("--confirm-date", default=None, dest="confirm_date")
    r.add_argument("--first-news-date", default=None, dest="first_news_date")
    r.add_argument("--force", action="store_true")
    r.set_defaults(func=cmd_resolve)

    rd = sub.add_parser("resolve-due", help="auto-resolve due views by price; list due facts (never fails)")
    rd.set_defaults(func=cmd_resolve_due)

    st = sub.add_parser("stats", aliases=["score"], help="per-source hit-rate / calibration stats")
    st.add_argument("--source", default=None)
    st.add_argument("--kind", default=None, choices=sorted(VALID_KINDS))
    st.add_argument("--since", default=None)
    st.set_defaults(func=cmd_stats)

    t = sub.add_parser("tiers", help="recompute and (unless --dry-run) write back source tiers")
    t.add_argument("--dry-run", action="store_true", dest="dry_run")
    t.set_defaults(func=cmd_tiers)

    li = sub.add_parser("list", help="list claims (default) or --sources to list the config whitelist")
    li.add_argument("--source", default=None)
    li.add_argument("--status", default=None, choices=sorted(VALID_STATUSES))
    li.add_argument("--kind", default=None, choices=sorted(VALID_KINDS))
    li.add_argument("--sources", action="store_true")
    li.set_defaults(func=cmd_list)

    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
