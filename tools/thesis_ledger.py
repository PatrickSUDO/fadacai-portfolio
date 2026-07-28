#!/usr/bin/env python3
"""
thesis_ledger.py — Track investment theses with falsifiable triggers, verify on
due date, and report hit rate.

Deterministic by design: dedup, collision guard, due/expiry detection, status
transitions, date arithmetic, and schema validation all live here. The calling
skill (briefing / portfolio-review) only supplies the reasoning judgment
("given the actual numbers, did the thesis pass?").

Storage: research/thesis-ledger.json  ({"theses": [ ... ]})

See docs/thesis-ledger.md for the full design and CLI reference.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = ROOT / "research" / "thesis-ledger.json"

SIMILARITY_THRESHOLD = 0.3   # >= → same thesis (update); < → collision
EXPIRE_AFTER_DAYS = 30       # pending past trigger by this many days → expired

VALID_STATUSES = {
    "pending", "passed", "failed", "partial", "expired", "stale", "superseded",
    "untested",
}
VALID_VERDICTS = {"passed", "failed", "partial"}
# `untested` = the position was exited before the trigger could fire, so the claim was
# never put to the test. Recording it as passed/failed/partial would be inventing a
# verdict; leaving it pending lets it resolve later against a position that no longer
# exists (ARM's thesis fires on the 07-29 print for a position closed 07-20 at -20.8%,
# and a beat would have booked a `passed` on a realised loss). It is excluded from
# hit_rate AND from follow_through_rate — it is neither a hit, a miss, nor a failure
# to verify on time.
VALID_POSITION_STATUS = {"held", "exited", "never_entered"}
VALID_PRICE_VERDICTS = {"met", "missed"}

# Market / portfolio-level theses have no single ticker to hold, so they can never
# be orphaned by an exit.
PORTFOLIO_TICKERS = {"MARKET", "PORTFOLIO", "_PORTFOLIO", "MACRO"}


# ── slug / id helpers ───────────────────────────────────────────────────────
def normalize_slug(slug):
    """Lowercase, trim, collapse internal whitespace to single hyphens."""
    parts = str(slug).strip().lower().replace("_", "-").split()
    joined = "-".join(parts)
    # collapse repeated hyphens
    while "--" in joined:
        joined = joined.replace("--", "-")
    return joined.strip("-")


def make_id(ticker, slug):
    return f"{str(ticker).strip().upper()}:{normalize_slug(slug)}"


def _trigrams(text):
    s = "".join(str(text).split())  # drop all whitespace
    if len(s) < 3:
        return {s} if s else set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


def trigram_similarity(a, b):
    """Char-trigram Jaccard similarity in [0, 1]. Deterministic, dep-free."""
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union


# ── entry lookup ────────────────────────────────────────────────────────────
def _find(data, entry_id):
    for e in data["theses"]:
        if e["id"] == entry_id:
            return e
    return None


def _resolve_alias(data, entry_id):
    """If entry_id was merged into another entry, return the surviving id."""
    for e in data["theses"]:
        if entry_id == e["id"]:
            return e["id"]
        slug = entry_id.split(":", 1)[1] if ":" in entry_id else entry_id
        if slug in e.get("aliases", []) and entry_id.split(":", 1)[0] == e["ticker"]:
            return e["id"]
    return entry_id


# ── add (insert / update / collision / redirect) ────────────────────────────
def add_thesis(data, *, ticker, slug, thesis, falsification, trigger_type,
               trigger_date, event=None, metric=None, source="briefing",
               ev=None, asof=None):
    asof = asof or date.today().isoformat()
    entry_id = make_id(ticker, slug)

    # redirect through a merge alias if one exists
    resolved_id = _resolve_alias(data, entry_id)
    existing = _find(data, resolved_id)

    trigger = {"type": trigger_type, "date": trigger_date}
    if event is not None:
        trigger["event"] = event
    if metric is not None:
        trigger["metric"] = metric

    if existing is not None and existing["status"] not in ("superseded", "stale"):
        sim = trigram_similarity(existing["thesis"], thesis)
        if sim < SIMILARITY_THRESHOLD:
            return {
                "action": "collision",
                "id": existing["id"],
                "existing_thesis": existing["thesis"],
                "incoming_thesis": thesis,
                "similarity": round(sim, 3),
            }
        # update in place
        existing["thesis"] = thesis
        existing["falsification"] = list(falsification)
        existing["trigger"] = trigger
        existing["source"] = source
        if ev is not None:
            existing["ev_snapshot"] = ev
        existing["updated"] = asof
        action = "updated" if existing["id"] == entry_id else "redirected"
        return {"action": action, "id": existing["id"], "similarity": round(sim, 3)}

    entry = {
        "id": entry_id,
        "ticker": str(ticker).strip().upper(),
        "slug": normalize_slug(slug),
        "thesis": thesis,
        "falsification": list(falsification),
        "trigger": trigger,
        "status": "pending",
        "source": source,
        "created": asof,
        "updated": asof,
        "ev_snapshot": ev,
        "aliases": [],
        "superseded_by": None,
        "history": [],
    }
    data["theses"].append(entry)
    return {"action": "inserted", "id": entry_id}


# ── due / expiry sweep ──────────────────────────────────────────────────────
def _parse(d):
    return datetime.strptime(d, "%Y-%m-%d").date()


def due_theses(data, *, asof=None, expire_after_days=EXPIRE_AFTER_DAYS):
    """Return {due, expired}. Auto-expires pending entries whose trigger is more
    than expire_after_days behind asof (mutates them to status='expired')."""
    asof = asof or date.today().isoformat()
    today = _parse(asof)
    due, expired = [], []
    for e in data["theses"]:
        if e["status"] != "pending":
            continue
        trig = _parse(e["trigger"]["date"])
        if trig > today:
            continue
        if (today - trig).days > expire_after_days:
            e["status"] = "expired"
            e["updated"] = asof
            e["history"].append({
                "date": asof,
                "verdict": "expired",
                "actual": None,
                "note": f"逾期 {(today - trig).days} 天未驗收，當作無結果",
                "next_action": None,
            })
            expired.append(e)
        else:
            due.append(e)
    return {"due": due, "expired": expired}


# ── resolve / reschedule ────────────────────────────────────────────────────
DRIFT_WARN_DAYS = 45      # premise has had this long to break before the trigger fires


def recheck(data, *, asof=None, drift_warn=DRIFT_WARN_DAYS):
    """Pending theses whose premise has had time to break before the trigger fires.

    The falsification conditions are already written and specific — the gap is that
    they are only consulted on the trigger date. MRVL:fy28-ai-bookings-visibility has
    172 days between creation and trigger; a premise can be dead for five months with
    nobody looking. This surfaces them, newest-risk-first, and leaves the judgment
    ("is any of these observable as already met?") to the caller. No pre-classifying
    conditions into checkable/not — that is a migration, and the value is in putting
    them in front of a reader, not in tagging them.
    """
    today = _parse(asof) if asof else date.today()
    rows = []
    for e in data["theses"]:
        if e["status"] != "pending":
            continue
        trig = (e.get("trigger") or {}).get("date")
        if not trig:
            continue
        created = _parse(e["created"])
        elapsed = (today - created).days
        remaining = (_parse(trig) - today).days
        rows.append({
            "id": e["id"],
            "ticker": e["ticker"],
            "created": e["created"],
            "trigger_date": trig,
            "days_since_created": elapsed,
            "days_until_trigger": remaining,
            "total_drift_days": (_parse(trig) - created).days,
            "long_drift": (_parse(trig) - created).days >= drift_warn,
            "thesis": e.get("thesis"),
            "falsification": e.get("falsification") or [],
            "source": e.get("source"),
        })
    # longest already-elapsed exposure first: that is where a dead premise hides
    rows.sort(key=lambda r: (-r["days_since_created"], r["days_until_trigger"]))
    return rows


def close_untested(data, *, entry_id, exit_date, note, realized_pnl=None, asof=None):
    """Close an orphan: the position went away before the thesis could be tested."""
    asof = asof or date.today().isoformat()
    entry = _find(data, _resolve_alias(data, entry_id))
    if entry is None:
        return {"action": "not_found", "id": entry_id}
    if entry["status"] != "pending":
        return {"action": "not_pending", "id": entry_id, "status": entry["status"]}
    entry["status"] = "untested"
    entry["updated"] = asof
    entry["history"].append({
        "date": asof,
        "verdict": "untested",
        "actual": f"position exited {exit_date} before trigger "
                  f"{(entry.get('trigger') or {}).get('date')}",
        "note": note,
        "next_action": None,
        "position_status": "exited",
        "realized_pnl": realized_pnl,
        "price_verdict": None,
    })
    return {"action": "closed_untested", "id": entry["id"], "exit_date": exit_date}


def resolve_thesis(data, *, entry_id, verdict, actual, note, next_action,
                   asof=None,
                   fair_value_before=None, fair_value_after=None,
                   price_impact_pct=None, impact_decomp=None,
                   position_status=None, realized_pnl=None, price_verdict=None):
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"invalid verdict: {verdict} (use {VALID_VERDICTS})")
    if position_status is not None and position_status not in VALID_POSITION_STATUS:
        raise ValueError(f"invalid position_status: {position_status} "
                         f"(use {VALID_POSITION_STATUS})")
    if price_verdict is not None and price_verdict not in VALID_PRICE_VERDICTS:
        raise ValueError(f"invalid price_verdict: {price_verdict} "
                         f"(use {VALID_PRICE_VERDICTS})")
    # A "partial" with no price_verdict is where honest failures hide: AVGO raised
    # FY27 AI guidance yet fell 15%, NOK only held guide and stayed far below the
    # upgrade threshold, GEV showed record orders on a 20% EPS miss. Recording
    # whether the PRICE claim was met keeps those separable from operational wins.
    if verdict == "partial" and price_verdict is None:
        raise ValueError("verdict=partial requires price_verdict (met|missed): did the "
                         "thesis's price implication hold, independent of the operating data?")
    asof = asof or date.today().isoformat()
    entry = _find(data, _resolve_alias(data, entry_id))
    if entry is None:
        return {"action": "not_found", "id": entry_id}
    entry["status"] = verdict
    entry["updated"] = asof
    history_record = {
        "date": asof,
        "verdict": verdict,
        "actual": actual,
        "note": note,
        "next_action": next_action,
        # D2 估值影響欄位（選填，有數就存，無則 None）
        "fair_value_before": fair_value_before,
        "fair_value_after": fair_value_after,
        "price_impact_pct": price_impact_pct,
        "impact_decomp": impact_decomp,
        # P1 部位連結：thesis 命中 ≠ 賺錢（ARM 案例）
        "position_status": position_status,
        "realized_pnl": realized_pnl,
        "price_verdict": price_verdict,
    }
    entry["history"].append(history_record)
    return {"action": "resolved", "id": entry["id"], "status": verdict,
            "position_status": position_status, "realized_pnl": realized_pnl,
            "price_verdict": price_verdict}


# ── orphan detection ────────────────────────────────────────────────────────
def traded_symbols():
    """Tickers with at least one fill in the trade ledger (i.e. we owned them)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from trade_ledger import load_fills   # noqa: PLC0415  (optional dependency)
    except ImportError:
        return None
    out = set()
    for f in load_fills():
        out.add((f.get("underlying") if f.get("is_option") else f.get("symbol") or "").upper())
    return {s for s in out if s} or None


def orphans(data, held_symbols, ever_traded=None):
    """Pending theses for positions we held and have since exited.

    Why this matters: ARM:agentic-ai-cpu-royalty triggers on the 2026-07-29 earnings
    print, but the position was liquidated 2026-07-20 at −20.8%. Left alone the
    ledger records `passed` on a realised loss — exactly how hit_rate drifts away
    from P&L.

    Two categories are deliberately NOT orphans:
      · `reentry-*` slugs — meant to outlive the position per
        feedback/exit-reentry-discipline.md
      · theses on names never owned (L1/L2 bench candidates such as WELL, ALAB,
        KTOS) — pending is their correct state; they are waiting on a trigger to
        decide entry. `ever_traded` (from the trade ledger) is what separates
        "exited" from "never entered"; without it they cannot be told apart and
        every bench candidate reads as an orphan.
    """
    held = {s.strip().upper() for s in held_symbols if s and s.strip()}
    out, candidates = [], []
    for e in data["theses"]:
        if e["status"] != "pending":
            continue
        ticker = e["ticker"].upper()
        if ticker in held or ticker in PORTFOLIO_TICKERS:
            continue
        if e["slug"].startswith("reentry-"):
            continue
        row = {
            "id": e["id"],
            "ticker": ticker,
            "slug": e["slug"],
            "trigger_date": (e.get("trigger") or {}).get("date"),
            "created": e.get("created"),
            "thesis": (e.get("thesis") or "")[:140],
        }
        if ever_traded is not None and ticker not in ever_traded:
            candidates.append(row)
        else:
            out.append(row)
    key = lambda o: (o["trigger_date"] or "", o["ticker"])   # noqa: E731
    return sorted(out, key=key), sorted(candidates, key=key)


def reschedule(data, *, entry_id, to, reason, asof=None):
    asof = asof or date.today().isoformat()
    entry = _find(data, _resolve_alias(data, entry_id))
    if entry is None:
        return {"action": "not_found", "id": entry_id}
    old = entry["trigger"]["date"]
    entry["trigger"]["date"] = to
    entry["status"] = "pending"
    entry["updated"] = asof
    entry["history"].append({
        "date": asof,
        "verdict": "rescheduled",
        "actual": None,
        "note": f"{old} → {to}：{reason}",
        "next_action": None,
    })
    return {"action": "rescheduled", "id": entry["id"], "to": to}


# ── merge / supersede ───────────────────────────────────────────────────────
def merge(data, *, from_id, into_id, asof=None):
    asof = asof or date.today().isoformat()
    src = _find(data, from_id)
    dst = _find(data, into_id)
    if src is None or dst is None:
        return {"action": "not_found", "from": from_id, "into": into_id}
    dst["history"].extend(src["history"])
    dst["history"].sort(key=lambda h: h["date"])
    dst.setdefault("aliases", [])
    if src["slug"] not in dst["aliases"]:
        dst["aliases"].append(src["slug"])
    for a in src.get("aliases", []):
        if a not in dst["aliases"]:
            dst["aliases"].append(a)
    dst["updated"] = asof
    data["theses"] = [e for e in data["theses"] if e["id"] != from_id]
    return {"action": "merged", "id": into_id, "absorbed": from_id}


def supersede(data, *, entry_id, new_slug, thesis, falsification, trigger_type,
              trigger_date, event=None, metric=None, source="briefing",
              ev=None, asof=None):
    asof = asof or date.today().isoformat()
    old = _find(data, _resolve_alias(data, entry_id))
    if old is None:
        return {"action": "not_found", "id": entry_id}
    res = add_thesis(
        data, ticker=old["ticker"], slug=new_slug, thesis=thesis,
        falsification=falsification, trigger_type=trigger_type,
        trigger_date=trigger_date, event=event, metric=metric, source=source,
        ev=ev, asof=asof,
    )
    if res["action"] == "collision":
        return res
    old["status"] = "superseded"
    old["superseded_by"] = res["id"]
    old["updated"] = asof
    old["history"].append({
        "date": asof,
        "verdict": "superseded",
        "actual": None,
        "note": f"被 {res['id']} 取代",
        "next_action": None,
    })
    return {"action": "superseded", "id": old["id"], "new_id": res["id"]}


# ── stats ───────────────────────────────────────────────────────────────────
def stats(data, *, ticker=None, source=None, since=None):
    counts = {s: 0 for s in VALID_STATUSES}
    resolve_days = []
    for e in data["theses"]:
        if ticker and e["ticker"] != str(ticker).upper():
            continue
        if source and e.get("source") != source:
            continue
        if since and e["created"] < since:
            continue
        counts[e["status"]] = counts.get(e["status"], 0) + 1
        if e["status"] in VALID_VERDICTS and e["history"]:
            resolve_days.append(
                (_parse(e["history"][-1]["date"]) - _parse(e["created"])).days
            )

    passed, failed = counts["passed"], counts["failed"]
    partial, expired = counts["partial"], counts["expired"]
    untested = counts.get("untested", 0)
    decided = passed + failed
    resolved = passed + failed + partial

    # A thesis being right and the position making money are different questions.
    # Reporting only hit_rate lets a `passed` on a liquidated loser (ARM) read as a
    # win, so surface the price/P&L view alongside it.
    price_met = price_missed = 0
    pnl_pos = pnl_neg = 0
    pnl_total = 0.0
    for e in data["theses"]:
        if ticker and e["ticker"] != str(ticker).upper():
            continue
        if source and e.get("source") != source:
            continue
        if since and e["created"] < since:
            continue
        for h in e.get("history", []):
            if h.get("price_verdict") == "met":
                price_met += 1
            elif h.get("price_verdict") == "missed":
                price_missed += 1
            pnl = h.get("realized_pnl")
            if isinstance(pnl, (int, float)):
                pnl_total += pnl
                if pnl > 0:
                    pnl_pos += 1
                elif pnl < 0:
                    pnl_neg += 1
    price_decided = price_met + price_missed
    pnl_decided = pnl_pos + pnl_neg
    return {
        "counts": counts,
        "hit_rate": (passed / decided) if decided else None,
        "price_hit_rate": (price_met / price_decided) if price_decided else None,
        "pnl_hit_rate": (pnl_pos / pnl_decided) if pnl_decided else None,
        "realized_pnl_total": round(pnl_total, 2) if pnl_decided else None,
        "coverage": {
            "verdicts_recorded": resolved,
            "with_price_verdict": price_decided,
            "with_realized_pnl": pnl_decided,
            "untested_excluded": untested,
        },
        "follow_through_rate": (resolved / (resolved + expired))
        if (resolved + expired) else None,
        "avg_days_to_resolve": (sum(resolve_days) / len(resolve_days))
        if resolve_days else None,
        "total": sum(counts.values()),
        "note": ("hit_rate counts theses; pnl_hit_rate counts money. A gap between "
                 "them means theses are being validated on positions that lost."),
    }


def live_held_symbols():
    """Tickers currently held, via the trade_ledger Firstrade bridge.

    Options are folded onto their underlying: holding a TSLA LEAPS still means the
    TSLA thesis has a live position behind it.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from trade_ledger import _ft_call            # noqa: PLC0415  (optional dependency)

    payload = _ft_call("print(json.dumps(data.get_positions(acct)))")
    out = set()
    for item in payload.get("items", []):
        sym = (item.get("symbol") or "").strip().upper()
        if not sym:
            continue
        if item.get("sec_type") == 2:            # option → OCC symbol, take the root
            root = re.match(r"^([A-Z]+)\d{6}[CP]\d+$", sym)
            sym = root.group(1) if root else sym
        out.add(sym)
    return sorted(out)


# ── file IO + validation ────────────────────────────────────────────────────
def validate(data):
    if not isinstance(data, dict) or not isinstance(data.get("theses"), list):
        raise ValueError("ledger must be an object with a 'theses' list")
    for e in data["theses"]:
        if e.get("status") not in VALID_STATUSES:
            raise ValueError(f"invalid status: {e.get('status')!r} on {e.get('id')!r}")
    return data


def load_ledger(path):
    p = Path(path)
    if not p.exists():
        return {"theses": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt ledger {path}: {exc}") from exc
    return validate(data)


def save_ledger(path, data):
    validate(data)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".thesis-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(p))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ── CLI ─────────────────────────────────────────────────────────────────────
# Exit codes: 0 ok · 2 collision (skill must pick new slug / supersede)
#             3 not_found · 1 usage/other error
EXIT_OK, EXIT_GENERIC, EXIT_COLLISION, EXIT_NOT_FOUND = 0, 1, 2, 3


def _emit(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _build_parser():
    p = argparse.ArgumentParser(description="Thesis ledger — track & verify investment theses")
    p.add_argument("--ledger", default=str(DEFAULT_LEDGER), help="path to ledger JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="register/update a thesis (upsert by ticker:slug)")
    a.add_argument("--ticker", required=True)
    a.add_argument("--slug", required=True)
    a.add_argument("--thesis", required=True)
    a.add_argument("--falsification", nargs="*", default=[])
    a.add_argument("--trigger-type", required=True, choices=["date", "event"])
    a.add_argument("--trigger-date", required=True, help="YYYY-MM-DD")
    a.add_argument("--event", default=None)
    a.add_argument("--metric", default=None)
    a.add_argument("--source", default="briefing")
    a.add_argument("--ev", default=None)
    a.add_argument("--asof", default=None)

    li = sub.add_parser("list", help="list theses")
    li.add_argument("--ticker", default=None)
    li.add_argument("--status", default=None, choices=sorted(VALID_STATUSES))

    d = sub.add_parser("due", help="list theses due for verification (auto-expires stale)")
    d.add_argument("--asof", default=None)
    d.add_argument("--expire-after-days", type=int, default=EXPIRE_AFTER_DAYS)

    r = sub.add_parser("resolve", help="record a verification result")
    r.add_argument("--id", required=True, dest="entry_id")
    r.add_argument("--verdict", required=True, choices=sorted(VALID_VERDICTS))
    r.add_argument("--actual", required=True)
    r.add_argument("--note", default="")
    r.add_argument("--next-action", default="", dest="next_action")
    r.add_argument("--asof", default=None)
    # Optional valuation-impact fields (D2 三錨點公允價影響)
    r.add_argument("--fair-value-before", type=float, default=None, dest="fair_value_before",
                   help="三錨點公允價（resolve 前，EV 快照）")
    r.add_argument("--fair-value-after", type=float, default=None, dest="fair_value_after",
                   help="三錨點公允價（resolve 後，thesis 成分已調整）")
    r.add_argument("--price-impact-pct", type=float, default=None, dest="price_impact_pct",
                   help="(fair_value_after - fair_value_before) / fair_value_before × 100")
    r.add_argument("--impact-decomp", default=None, dest="impact_decomp",
                   help="partial 專用：thesis +X%%/multiple −Z%%=net −W%%")
    # P1 部位連結：thesis 命中 ≠ 賺錢
    r.add_argument("--position-status", default=None, dest="position_status",
                   choices=sorted(VALID_POSITION_STATUS),
                   help="部位在驗收時的狀態；exited 代表 verdict 不等於損益")
    r.add_argument("--realized-pnl", type=float, default=None, dest="realized_pnl",
                   help="該部位已實現損益（美元，虧損為負）")
    r.add_argument("--price-verdict", default=None, dest="price_verdict",
                   choices=sorted(VALID_PRICE_VERDICTS),
                   help="價格含意是否成立（partial 必填）；營運達標但市場不認 → missed")

    rc = sub.add_parser("recheck",
                        help="pending theses whose premise may have broken before the trigger")
    rc.add_argument("--asof", default=None)
    rc.add_argument("--drift-warn-days", type=int, default=DRIFT_WARN_DAYS)
    rc.add_argument("--limit", type=int, default=0, help="0 = all")
    rc.add_argument("--long-drift-only", action="store_true")

    orp = sub.add_parser("orphans",
                         help="pending theses whose position is already gone (excl. reentry-*)")
    orp.add_argument("--held", default=None,
                     help="comma-separated held tickers; omit to read live positions")
    orp.add_argument("--include-never-held", action="store_true",
                     help="also count bench candidates never owned (noisy; off by default)")

    cu = sub.add_parser("close-untested",
                        help="close an orphan: position exited before the trigger could fire")
    cu.add_argument("--id", required=True, dest="entry_id")
    cu.add_argument("--exit-date", required=True, dest="exit_date")
    cu.add_argument("--note", required=True)
    cu.add_argument("--realized-pnl", type=float, default=None, dest="realized_pnl")
    cu.add_argument("--asof", default=None)

    rs = sub.add_parser("reschedule", help="push a pending thesis's trigger date out")
    rs.add_argument("--id", required=True, dest="entry_id")
    rs.add_argument("--to", required=True)
    rs.add_argument("--reason", default="")
    rs.add_argument("--asof", default=None)

    m = sub.add_parser("merge", help="merge a duplicate thesis into another")
    m.add_argument("--from", required=True, dest="from_id")
    m.add_argument("--into", required=True, dest="into_id")
    m.add_argument("--asof", default=None)

    sp = sub.add_parser("supersede", help="archive a thesis and create a replacement")
    sp.add_argument("--id", required=True, dest="entry_id")
    sp.add_argument("--new-slug", required=True)
    sp.add_argument("--thesis", required=True)
    sp.add_argument("--falsification", nargs="*", default=[])
    sp.add_argument("--trigger-type", required=True, choices=["date", "event"])
    sp.add_argument("--trigger-date", required=True)
    sp.add_argument("--event", default=None)
    sp.add_argument("--metric", default=None)
    sp.add_argument("--source", default="briefing")
    sp.add_argument("--ev", default=None)
    sp.add_argument("--asof", default=None)

    st = sub.add_parser("stats", help="hit rate & follow-through stats")
    st.add_argument("--ticker", default=None)
    st.add_argument("--source", default=None)
    st.add_argument("--since", default=None)

    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)
    path = args.ledger
    data = load_ledger(path)
    mutated = True

    if args.cmd == "add":
        res = add_thesis(
            data, ticker=args.ticker, slug=args.slug, thesis=args.thesis,
            falsification=args.falsification, trigger_type=args.trigger_type,
            trigger_date=args.trigger_date, event=args.event, metric=args.metric,
            source=args.source, ev=args.ev, asof=args.asof)
        if res["action"] == "collision":
            _emit(res)
            return EXIT_COLLISION
    elif args.cmd == "list":
        mutated = False
        items = [e for e in data["theses"]
                 if (not args.ticker or e["ticker"] == args.ticker.upper())
                 and (not args.status or e["status"] == args.status)]
        _emit({"count": len(items), "theses": items})
        return EXIT_OK
    elif args.cmd == "due":
        res = due_theses(data, asof=args.asof, expire_after_days=args.expire_after_days)
        _emit({"due": res["due"], "expired": res["expired"],
               "due_count": len(res["due"]), "expired_count": len(res["expired"])})
        save_ledger(path, data)
        return EXIT_OK
    elif args.cmd == "resolve":
        res = resolve_thesis(
            data, entry_id=args.entry_id, verdict=args.verdict,
            actual=args.actual, note=args.note, next_action=args.next_action,
            asof=args.asof,
            fair_value_before=args.fair_value_before,
            fair_value_after=args.fair_value_after,
            price_impact_pct=args.price_impact_pct,
            impact_decomp=args.impact_decomp,
            position_status=args.position_status,
            realized_pnl=args.realized_pnl,
            price_verdict=args.price_verdict)
        if res["action"] == "not_found":
            _emit(res)
            return EXIT_NOT_FOUND
    elif args.cmd == "close-untested":
        res = close_untested(data, entry_id=args.entry_id, exit_date=args.exit_date,
                             note=args.note, realized_pnl=args.realized_pnl, asof=args.asof)
        if res["action"] == "not_found":
            _emit(res)
            return EXIT_NOT_FOUND
    elif args.cmd == "recheck":
        mutated = False
        rows = recheck(data, asof=args.asof, drift_warn=args.drift_warn_days)
        if args.long_drift_only:
            rows = [r for r in rows if r["long_drift"]]
        shown = rows[: args.limit] if args.limit else rows
        _emit({
            "pending": len(rows),
            "long_drift": sum(1 for r in rows if r["long_drift"]),
            "drift_warn_days": args.drift_warn_days,
            "ask": ("for each: is any falsification condition ALREADY observable as met? "
                    "If yes → resolve --verdict failed now, do not wait for the trigger. "
                    "If the premise is intact, say so and move on — this is the step that "
                    "replaces blindly following a two-month-old thesis."),
            "theses": shown,
        })
        return EXIT_OK
    elif args.cmd == "orphans":
        mutated = False
        held = args.held.split(",") if args.held else live_held_symbols()
        ever = None if args.include_never_held else traded_symbols()
        found, candidates = orphans(data, held, ever_traded=ever)
        _emit({
            "orphan_count": len(found),
            "held_symbols": sorted({s.strip().upper() for s in held if s and s.strip()}),
            "orphans": found,
            "action_required": ("resolve each with --position-status exited (+ "
                                "--realized-pnl), or supersede into a reentry-* thesis "
                                "per feedback/exit-reentry-discipline.md")
            if found else None,
            "bench_candidates_not_orphans": candidates,
            "bench_note": ("never held per the trade ledger → pending is correct; "
                           "they are L1/L2 candidates awaiting an entry trigger"),
            "traded_symbol_source": "trade-ledger" if ever else "unavailable (all treated as exited)",
        })
        return EXIT_OK
    elif args.cmd == "reschedule":
        res = reschedule(data, entry_id=args.entry_id, to=args.to,
                         reason=args.reason, asof=args.asof)
        if res["action"] == "not_found":
            _emit(res)
            return EXIT_NOT_FOUND
    elif args.cmd == "merge":
        res = merge(data, from_id=args.from_id, into_id=args.into_id, asof=args.asof)
        if res["action"] == "not_found":
            _emit(res)
            return EXIT_NOT_FOUND
    elif args.cmd == "supersede":
        res = supersede(
            data, entry_id=args.entry_id, new_slug=args.new_slug,
            thesis=args.thesis, falsification=args.falsification,
            trigger_type=args.trigger_type, trigger_date=args.trigger_date,
            event=args.event, metric=args.metric, source=args.source,
            ev=args.ev, asof=args.asof)
        if res["action"] == "collision":
            _emit(res)
            return EXIT_COLLISION
        if res["action"] == "not_found":
            _emit(res)
            return EXIT_NOT_FOUND
    elif args.cmd == "stats":
        mutated = False
        _emit(stats(data, ticker=args.ticker, source=args.source, since=args.since))
        return EXIT_OK
    else:  # pragma: no cover
        return EXIT_GENERIC

    if mutated:
        save_ledger(path, data)
    _emit(res)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
