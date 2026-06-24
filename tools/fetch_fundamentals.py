#!/usr/bin/env python3
"""
fetch_fundamentals.py — Cache per-holding 台股 fundamentals snapshot + earnings base-rate.

Source: FinMind v4 data API（TaiwanStockInfo / TaiwanStockFinancialStatement /
        TaiwanStockPER / TaiwanStockMonthRevenue / 分析師目標價 等）。
Output:
  briefing-out/cache/fundamentals-snapshot.json
    {status, generated_at, tickers: {代號: {snapshot: {...}, base_rate: {...}}}, errors: []}
TTL:
  24 hours (基本面 / 分析師目標價 / 技術面 盤中相對穩定)

⚠️ 整合接縫：下方 `fetch_*` 與欄位 mapping 原型沿用三方 REST 的 section 命名
   （Highlights / Valuation / AnalystRatings…），實際接 FinMind 時需把這些 section
   對應到 FinMind dataset 回應欄位（如 本益比→TaiwanStockPER.PER、季成長→
   TaiwanStockFinancialStatement、月營收→TaiwanStockMonthRevenue）。A4 自建估值數學
   （own_fwdEPS / CAGR / decel / margin）與 cache schema 為市場無關，原封保留。

Ticker source priority:
  1. ROOT/journal/<latest>.md  (parse holdings table — same logic as earnings_history.py)
  2. FUNDAMENTALS_TICKERS env var (comma-separated 4 碼代號)
  3. abort with warning if both empty

Usage:
  python3 tools/fetch_fundamentals.py              # refresh if stale
  python3 tools/fetch_fundamentals.py --force      # force refresh
"""

import json
import os
import re
import sys
import time
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

warnings.filterwarnings("ignore")

# ── Path setup ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "briefing-out" / "cache"
SNAP_FILE = CACHE_DIR / "fundamentals-snapshot.json"
JOURNAL_DIR = ROOT / "journal"

# ── Config ─────────────────────────────────────────────────────────────────
CACHE_TTL_HOURS = 24
TICKERS_DELAY = 0.4          # polite delay between FinMind API calls
FINMIND_BASE = "https://api.finmindtrade.com/api/v4"

# 概念性 fundamentals sections（接 FinMind 時對應到各 dataset，見 module docstring 整合接縫）
FUNDAMENTALS_FILTER = ",".join([
    "General::Name", "General::Sector", "General::Industry",
    "Highlights", "Valuation", "AnalystRatings", "Technicals",
    # 年度損益表（營收/淨利 時間序列 → CAGR）
    "Financials::Income_Statement::yearly",
    # 流通在外股數（own_fwdEPS = rev × margin ÷ shares）
    "SharesStats::SharesOutstanding",
    # 賣方前瞻共識（A3 錨 fwdEPS + EPS 修正動能）+ 月營收
    "Earnings::Trend", "MonthlyRevenue",
])

# 低 EPS 基期股：avg_surprise_pct 不可靠（see README / CLAUDE.md），改用 beat 次數
LOW_EPS_BASE_TICKERS = {"3661", "6488", "3035", "8299"}

# A4 自建錨：AI/半導體龍頭目標 PEG 1.5，其餘 1.0
# (mirrors the rule in briefing/SKILL.md Section 8.5 and stock-analysis three-anchor table)
AI_LEADERS = {"2330", "2454", "3661", "3017", "3037"}

# ── A4 self-valuation projection constants ──────────────────────────────────
TERMINAL_GROWTH = 0.08       # long-term terminal growth rate (fade target)
GROWTH_CAP = 0.40            # hard cap — never project >40% perpetually
DECEL_FACTOR = 0.30          # each year, 30% of the gap to terminal growth fades
GROWTH_STDEV_THRESHOLD = 0.30  # stdev of YoY growth rates → "low" confidence flag
USE_MARGIN_TREND = True      # if last 2 yearly net margins both rising and |Δ|<3pp,
                              # use avg(last2) instead of trailing (smoother for cyclicals)


# ── .env loader (same as earnings_history.py) ────────────────────────────────
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


# ── Ticker discovery (identical to earnings_history.py) ─────────────────────
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
    env_tickers = os.environ.get("FUNDAMENTALS_TICKERS", "").strip()
    if env_tickers:
        ts = [s.strip().upper() for s in env_tickers.split(",") if s.strip()]
        print(f"📋 tickers from FUNDAMENTALS_TICKERS env: {len(ts)} found")
        return ts
    print("⚠️  no tickers found (journals had no snapshot + FUNDAMENTALS_TICKERS unset)")
    return []


# ── Cache helpers (identical to earnings_history.py) ────────────────────────
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


# ── FinMind REST client (inline — no cross-repo import) ───────────────────────
def _finmind_get(endpoint: str, params: dict | None = None, token: str = "") -> dict | list:
    """Simple FinMind REST call with raise_for_status."""
    p = params or {}
    p["api_token"] = token
    p["fmt"] = "json"
    resp = requests.get(f"{FINMIND_BASE}/{endpoint}", params=p, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f == 0.0 else f
    except (TypeError, ValueError):
        return None


def _num(v) -> float | None:
    """Convert to float WITHOUT collapsing 0.0 → None (for time-series values).

    Unlike _safe_float, this preserves zero — valid for revenue, netIncome, shares
    where 0.0 is a real number (not a data-gap sentinel). Zero revenue IS zero, not missing.
    """
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# Forward-looking Earnings::Trend period codes → friendly label.
# (0q = current quarter, +1q = next quarter, 0y = current FY, +1y = next FY)
_FORWARD_PERIOD_LABELS = {"0q": "curr_q", "+1q": "next_q", "0y": "curr_fy", "+1y": "next_fy"}


def _extract_forward_estimates(trend_raw: dict) -> dict:
    """Reshape FinMind Earnings::Trend → {next_q/curr_fy/next_fy/curr_q} consensus.

    The section is keyed by fiscal date and carries many historical 0q/0y rows;
    for each forward period code we keep only the entry with the latest date.
    Estimate magnitudes use _safe_float (0.0 = data gap → None); revision counts
    use _num (0 is a real count). eps_revision_30d_pct = consensus EPS now vs
    30 days ago — an upward drift leads post-guidance analyst upgrades.
    """
    if not isinstance(trend_raw, dict):
        return {}
    latest_by_period: dict = {}
    for date_key, entry in trend_raw.items():
        if not isinstance(entry, dict):
            continue
        period = entry.get("period")
        if period not in _FORWARD_PERIOD_LABELS:
            continue
        cur = latest_by_period.get(period)
        if cur is None or date_key > cur[0]:
            latest_by_period[period] = (date_key, entry)

    out: dict = {}
    for period, (date_key, e) in latest_by_period.items():
        eps_cur = _safe_float(e.get("epsTrendCurrent"))
        eps_30d = _safe_float(e.get("epsTrend30daysAgo"))
        rev_30d_pct = None
        if eps_cur is not None and eps_30d not in (None, 0):
            rev_30d_pct = round((eps_cur - eps_30d) / abs(eps_30d) * 100, 2)
        out[_FORWARD_PERIOD_LABELS[period]] = {
            "period": period,
            "date": date_key,
            "eps_avg": _safe_float(e.get("earningsEstimateAvg")),
            "eps_low": _safe_float(e.get("earningsEstimateLow")),
            "eps_high": _safe_float(e.get("earningsEstimateHigh")),
            "eps_num_analysts": _num(e.get("earningsEstimateNumberOfAnalysts")),
            "eps_growth": _safe_float(e.get("earningsEstimateGrowth")),
            "rev_avg": _safe_float(e.get("revenueEstimateAvg")),
            "rev_growth": _safe_float(e.get("revenueEstimateGrowth")),
            "eps_revision_30d_pct": rev_30d_pct,
            "revisions_up_30d": _num(e.get("epsRevisionsUpLast30days")),
            "revisions_down_30d": _num(e.get("epsRevisionsDownLast30days")),
        }
    return out


# ── Fundamentals snapshot ───────────────────────────────────────────────────
def fetch_snapshot(sym_us: str, token: str) -> dict:
    """Fetch compact fundamentals for one ticker (FinMind data_id, e.g. '2330')."""
    data = _finmind_get(f"fundamentals/{sym_us}", params={"filter": FUNDAMENTALS_FILTER}, token=token)
    if not isinstance(data, dict):
        return {"error": "unexpected response"}

    hl = data.get("Highlights") or {}
    tech = data.get("Technicals") or {}

    def _h(key):  # safe highlight getter → None if 0.0
        return _safe_float(hl.get(key))

    # ── P2: yearly income statement time series ──────────────────────────────
    # FinMind filter "Financials::Income_Statement::yearly" may come back as a
    # flat key OR nested; handle both shapes gracefully.
    yearly_raw = (
        data.get("Financials::Income_Statement::yearly")                         # flat-key path
        or (data.get("Financials") or {}).get("Income_Statement", {}).get("yearly", {})  # nested path
        or {}
    )
    # yearly_raw is a dict keyed by fiscal date ("2024-12-31"), newest dates sort last in alpha.
    rev_yearly: list[dict] = []
    ni_yearly: list[dict] = []
    for date_key in sorted(yearly_raw.keys(), reverse=True):  # newest-first
        entry = yearly_raw[date_key] if isinstance(yearly_raw[date_key], dict) else {}
        rv = _num(entry.get("totalRevenue"))
        ni = _num(entry.get("netIncome"))
        if rv is not None:
            rev_yearly.append({"date": date_key, "value": rv})
        if ni is not None:
            ni_yearly.append({"date": date_key, "value": ni})

    # SharesStats::SharesOutstanding — flat-key or nested
    shares_outstanding = (
        _num(data.get("SharesStats::SharesOutstanding"))
        or _num((data.get("SharesStats") or {}).get("SharesOutstanding"))
    )

    # P4: analyst forward consensus (A3 anchor fwdEPS + revision momentum) —
    # Earnings::Trend may come back flat-keyed or nested under Earnings.
    trend_raw = (
        data.get("Earnings::Trend")
        or (data.get("Earnings") or {}).get("Trend", {})
        or {}
    )
    forward_estimates = _extract_forward_estimates(trend_raw)

    return {
        "name": data.get("General::Name"),
        "sector": data.get("General::Sector"),
        "industry": data.get("General::Industry"),
        "highlights": {
            "market_cap": hl.get("MarketCapitalization"),
            "pe_ratio": _h("PERatio"),            # A1 anchor — None if 0/missing
            "peg_ratio": _h("PEGRatio"),           # A2 anchor — None if 0/missing
            "eps_ttm": _h("EarningsShare"),
            "profit_margin": _h("ProfitMargin"),
            "operating_margin_ttm": _h("OperatingMarginTTM"),
            "roe_ttm": _h("ReturnOnEquityTTM"),
            "revenue_ttm": hl.get("RevenueTTM"),
            "quarterly_revenue_growth_yoy": _h("QuarterlyRevenueGrowthYOY"),
            "quarterly_earnings_growth_yoy": _h("QuarterlyEarningsGrowthYOY"),
            "wall_street_target": _h("WallStreetTargetPrice"),  # A3 anchor (÷ fwdEPS)
            "dividend_yield": _h("DividendYield"),
        },
        "valuation": data.get("Valuation") or {},
        "analyst_ratings": data.get("AnalystRatings") or {},
        "technicals": {
            "beta": _safe_float(tech.get("Beta")),
            "52w_high": _safe_float(tech.get("52WeekHigh")),
            "52w_low": _safe_float(tech.get("52WeekLow")),
            "sma_50d": _safe_float(tech.get("50DayMA")),
            "sma_200d": _safe_float(tech.get("200DayMA")),
            "short_percent_float": _safe_float(tech.get("ShortPercent")),
        },
        # P4: analyst forward consensus (next_q/curr_fy/next_fy) for A3 fwdEPS + P3 signals
        "forward_estimates": forward_estimates,
        # P2: time series for A4 self-valuation (compute_self_valuation uses these)
        "financials": {
            "revenue_yearly": rev_yearly,         # [{date, value}] newest-first, up to 5y
            "net_income_yearly": ni_yearly,        # [{date, value}] newest-first
            "shares_outstanding": shares_outstanding,
        },
    }


# ── Earnings base-rate ──────────────────────────────────────────────────────
HIGH_IMPACT_QUARTERS = 8


def fetch_base_rate(sym_us: str, token: str, ticker_plain: str) -> dict:
    """Fetch trailing 8Q EPS beat base-rate from FinMind calendar/earnings."""
    from_date = (date.today() - timedelta(days=HIGH_IMPACT_QUARTERS * 100 + 120)).isoformat()
    to_date = (date.today() + timedelta(days=120)).isoformat()
    data = _finmind_get(
        "calendar/earnings",
        params={"symbols": sym_us, "from": from_date, "to": to_date},
        token=token,
    )
    rows = data.get("earnings", []) if isinstance(data, dict) else []

    reported, upcoming = [], []
    for r in rows:
        actual = r.get("actual")
        entry = {
            "report_date": r.get("report_date", ""),
            "estimate": r.get("estimate"),
            "actual": actual,
            "surprise_pct": r.get("percent"),
        }
        if actual is not None:
            reported.append(entry)
        else:
            upcoming.append(entry)

    reported.sort(key=lambda x: x["report_date"], reverse=True)
    upcoming.sort(key=lambda x: x["report_date"])
    reported = reported[:HIGH_IMPACT_QUARTERS]

    beats = misses = inline = 0
    surprises = []
    for e in reported:
        if e["actual"] is None or e["estimate"] is None:
            continue
        sp = e.get("surprise_pct")
        if sp is not None:
            surprises.append(sp)
        if e["actual"] > e["estimate"]:
            beats += 1
        elif e["actual"] < e["estimate"]:
            misses += 1
        else:
            inline += 1
    total = beats + misses + inline

    avg_sp = round(sum(surprises) / len(surprises), 2) if surprises else None
    low_base = ticker_plain.upper() in LOW_EPS_BASE_TICKERS

    return {
        "quarters_counted": total,
        "beats": beats,
        "misses": misses,
        "inline": inline,
        "beat_pct": round(beats / total * 100, 1) if total else None,
        "avg_surprise_pct": avg_sp,
        "avg_surprise_unreliable": low_base,  # True → skip avg% in probability calc
        "next_earnings": upcoming[0] if upcoming else None,
    }


# ── A4 self-built valuation anchor ─────────────────────────────────────────
def compute_self_valuation(
    sym: str, highlights: dict, financials: dict, forward_estimates: dict | None = None
) -> dict:
    """Compute the A4 self-built anchor: own_fwdEPS = projected_revenue × net_margin ÷ shares.

    Independence guarantee for A4: NO analyst estimate used in own_fwdEPS. Revenue from
    historical FinMind income statement; margin from trailing (or 2-year trend if steadily
    rising); growth projection = CAGR faded toward terminal with bounded macro nudge.

    own_target_price = own_fwdEPS × base_FairPE, where base_FairPE = median(A1,A2,A3).
    A3 ("analyst-implied" PE) = wall_street_target ÷ fwdEPS. The A3 fwdEPS now prefers
    real analyst consensus (forward_estimates next_fy → curr_fy eps_avg) and only falls
    back to the eps_ttm×(1+growth) approximation when consensus is missing. A4's own_fwdEPS
    stays fully independent of these analyst numbers.

    Args:
        sym: Plain 代號 string (e.g. "2330") — used for AI_LEADERS lookup.
        highlights: The highlights dict from fetch_snapshot() (same ticker).
        financials: The financials dict from fetch_snapshot() (revenue_yearly, etc.).
        forward_estimates: The forward_estimates dict from fetch_snapshot() (consensus
            eps_avg per next_q/curr_fy/next_fy). Used only for the A3 anchor's fwdEPS.

    Returns:
        self_valuation dict — confidence in {ok, low, unavailable}; carries
        a3_fwdeps_source in {consensus_next_fy, consensus_curr_fy, approx}.
        Consumers: check confidence=="unavailable" → skip A4 (show "(self-val N/A)").
    """
    def _unavail(notes: str) -> dict:
        return {
            "confidence": "unavailable",
            "own_target_price": None,
            "own_fwdEPS": None,
            "projected_revenue": None,
            "revenue_cagr": None,
            "g_next": None,
            "macro_adj": None,
            "g_adj": None,
            "net_margin": None,
            "shares_outstanding": None,
            "base_fair_pe_approx": None,
            "a3_fwdeps_source": None,
            "notes": notes,
        }

    # ── Data extraction ────────────────────────────────────────────────────
    rev_yearly = financials.get("revenue_yearly", [])
    ni_yearly = financials.get("net_income_yearly", [])
    rev_values = [r["value"] for r in rev_yearly if r.get("value") is not None and r["value"] > 0]
    shares = financials.get("shares_outstanding")

    # Guard: need ≥3 years of positive revenue
    if len(rev_values) < 3:
        return _unavail(f"<3 revenue years ({len(rev_values)} available)")
    if not shares or shares <= 0:
        return _unavail("shares_outstanding missing or zero")

    # Net margin: trailing from highlights, optionally updated to 2-year trend
    net_margin = highlights.get("profit_margin")
    if net_margin is None or net_margin <= 0:
        return _unavail(f"net_margin unavailable or ≤0 ({net_margin})")

    if USE_MARGIN_TREND and len(ni_yearly) >= 2 and len(rev_yearly) >= 2:
        ni_vals = [n["value"] for n in ni_yearly[:2] if n.get("value") is not None]
        rv_vals = [r["value"] for r in rev_yearly[:2] if r.get("value") is not None and r["value"] > 0]
        if len(ni_vals) == 2 and len(rv_vals) == 2:
            m0 = ni_vals[0] / rv_vals[0]  # most recent year margin
            m1 = ni_vals[1] / rv_vals[1]  # prior year margin
            # Use trend avg only when both positive, steadily rising, and change < 3pp
            if m0 > 0 and m1 > 0 and m0 > m1 and abs(m0 - m1) < 0.03:
                net_margin = (m0 + m1) / 2

    # ── Historical CAGR (geometric, newest-first) ──────────────────────────
    n = len(rev_values) - 1   # number of periods
    try:
        cagr = (rev_values[0] / rev_values[n]) ** (1.0 / n) - 1
    except (ZeroDivisionError, ValueError, OverflowError):
        return _unavail("CAGR computation error (zero/negative/overflow revenue)")

    # YoY volatility for confidence gate
    yoy_growths = []
    for i in range(n):
        if rev_values[i + 1] > 0:
            yoy_growths.append(rev_values[i] / rev_values[i + 1] - 1)
    stdev_growth = 0.0
    if len(yoy_growths) >= 2:
        mean_g = sum(yoy_growths) / len(yoy_growths)
        variance = sum((g - mean_g) ** 2 for g in yoy_growths) / len(yoy_growths)
        stdev_growth = variance ** 0.5

    # ── Growth projection: decelerate toward terminal ──────────────────────
    base_growth = min(cagr, GROWTH_CAP)
    g_next = TERMINAL_GROWTH + (base_growth - TERMINAL_GROWTH) * (1.0 - DECEL_FACTOR)

    # ── Macro adjustment (bounded nudge from macro-snapshot.json cache) ────
    macro_adj = 0.0
    macro_notes: list[str] = []
    try:
        macro_path = CACHE_DIR / "macro-snapshot.json"
        if macro_path.exists():
            macro_data = json.loads(macro_path.read_text(encoding="utf-8"))
            regime = (macro_data.get("regime_tag") or "").lower()
            series = macro_data.get("series") or {}

            if "recession_signal" in regime:
                macro_adj -= 0.03
                macro_notes.append("recession_signal −3pp")
            elif "late_cycle" in regime:
                macro_adj -= 0.01
                macro_notes.append("late_cycle −1pp")

            if "risk_on" in regime:
                macro_adj += 0.01
                macro_notes.append("risk_on +1pp")

            cpi_info = series.get("cpi_yoy") or {}
            if isinstance(cpi_info, dict) and cpi_info.get("trend") == "up":
                macro_adj -= 0.01
                macro_notes.append("CPI↑ −1pp")

            fed_info = series.get("fed_funds") or {}
            if isinstance(fed_info, dict):
                chg = fed_info.get("change_30d")
                if chg is not None and float(chg) > 0.25:
                    macro_adj -= 0.01
                    macro_notes.append("fed↑>25bp −1pp")
    except Exception:
        pass  # macro nudge is best-effort; failure is silent

    # Asymmetric clamp: macro can hurt (−4pp) more than it can help (+2pp)
    macro_adj = max(-0.04, min(0.02, macro_adj))
    g_adj = max(0.0, min(0.45, g_next + macro_adj))

    # ── Own forward EPS ────────────────────────────────────────────────────
    revenue_ttm = highlights.get("revenue_ttm")
    if not revenue_ttm or revenue_ttm <= 0:
        return _unavail("revenue_ttm missing or ≤0")
    projected_revenue = revenue_ttm * (1.0 + g_adj)
    own_fwdEPS = projected_revenue * net_margin / shares

    # ── Approx base_FairPE = median(A1, A2, A3) using cache-available data ─
    # Skills will refine own_target_price with a more accurate fwdEPS at render time.
    # This gives a reasonable cache-level approximation for the Quick tier "💰" line.
    a1 = highlights.get("pe_ratio")                          # None if 0.0 (from _safe_float)

    growth_yoy = highlights.get("quarterly_revenue_growth_yoy") or 0.0
    growth_annual_pct = growth_yoy * 4.0 * 100.0            # convert decimal YoY → percentage pts
    target_peg = 1.5 if sym.upper() in AI_LEADERS else 1.0
    a2 = (target_peg * growth_annual_pct) if growth_annual_pct > 0 else None

    eps_ttm = highlights.get("eps_ttm")
    wall_st_pt = highlights.get("wall_street_target")
    # A3 fwdEPS: prefer real analyst consensus. Use current-FY (0y) consensus first —
    # it's the near-term forward EPS the standard ForwardPE convention uses, so A3 stays
    # horizon-consistent with A1/current_PE (off-calendar fiscal years make next_fy 18-24mo
    # out and artificially cheapen A3). next_fy is the fallback, then the eps_ttm×(1+growth)
    # approximation only when no consensus is available.
    fe = forward_estimates or {}
    consensus_curr_fy = (fe.get("curr_fy") or {}).get("eps_avg")
    consensus_next_fy = (fe.get("next_fy") or {}).get("eps_avg")
    if consensus_curr_fy and consensus_curr_fy > 0:
        a3_fwdeps, a3_fwdeps_source = consensus_curr_fy, "consensus_curr_fy"
    elif consensus_next_fy and consensus_next_fy > 0:
        a3_fwdeps, a3_fwdeps_source = consensus_next_fy, "consensus_next_fy"
    elif eps_ttm and growth_yoy:
        a3_fwdeps, a3_fwdeps_source = eps_ttm * (1.0 + growth_yoy), "approx"
    else:
        a3_fwdeps, a3_fwdeps_source = None, "approx"
    a3 = None
    if wall_st_pt and a3_fwdeps and a3_fwdeps > 0:
        a3 = wall_st_pt / a3_fwdeps

    valid_anchors = [a for a in [a1, a2, a3] if a is not None and a > 0]
    if valid_anchors:
        sorted_a = sorted(valid_anchors)
        n_a = len(sorted_a)
        if n_a % 2 == 1:
            base_fair_pe = sorted_a[n_a // 2]
        else:
            base_fair_pe = (sorted_a[n_a // 2 - 1] + sorted_a[n_a // 2]) / 2.0
    else:
        base_fair_pe = None

    own_target_price = (own_fwdEPS * base_fair_pe) if (own_fwdEPS and base_fair_pe) else None

    # ── Confidence ─────────────────────────────────────────────────────────
    confidence = "low" if stdev_growth > GROWTH_STDEV_THRESHOLD else "ok"

    # ── Notes ──────────────────────────────────────────────────────────────
    notes_parts = [
        f"3y_CAGR={cagr:.1%}",
        f"g_adj={g_adj:.1%}",
        f"margin={'trend_avg' if USE_MARGIN_TREND and len(ni_yearly) >= 2 else 'trailing'}={net_margin:.1%}",
    ]
    if macro_notes:
        notes_parts.append("macro:" + ",".join(macro_notes))
    if confidence == "low":
        notes_parts.append(f"⚠️ rev_stdev={stdev_growth:.1%}>30%")
    notes_parts.append(f"A3_fwdEPS={a3_fwdeps_source}")

    return {
        "own_fwdEPS": round(own_fwdEPS, 4),
        "projected_revenue": int(round(projected_revenue)),
        "revenue_cagr": round(cagr, 4),
        "g_next": round(g_next, 4),
        "macro_adj": round(macro_adj, 4),
        "g_adj": round(g_adj, 4),
        "net_margin": round(net_margin, 4),
        "shares_outstanding": shares,
        "base_fair_pe_approx": round(base_fair_pe, 2) if base_fair_pe else None,
        "a3_fwdeps_source": a3_fwdeps_source,
        "own_target_price": round(own_target_price, 2) if own_target_price else None,
        "confidence": confidence,
        "notes": "; ".join(notes_parts),
    }


# ── Main ────────────────────────────────────────────────────────────────────
def _parse_cli_tickers() -> list[str]:
    """--ticker SYM 或 --ticker SYM1,SYM2（單/多票模式，fetch + merge 進現有 cache）。"""
    out: list[str] = []
    for i, a in enumerate(sys.argv):
        if a == "--ticker" and i + 1 < len(sys.argv):
            out += [s.strip().upper() for s in sys.argv[i + 1].split(",") if s.strip()]
        elif a.startswith("--ticker="):
            out += [s.strip().upper() for s in a.split("=", 1)[1].split(",") if s.strip()]
    return out


def main() -> int:
    load_env()
    force = "--force" in sys.argv
    dry_run = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")
    cli_tickers = _parse_cli_tickers()

    # --ticker 模式：強制抓指定票 + merge 進現有 cache（cache miss 時補單票 A4，不覆蓋其他）
    if cli_tickers:
        force = True
        print(f"🎯 單票模式：{', '.join(cli_tickers)}（fetch + merge）")
    elif not force and is_cache_fresh(SNAP_FILE, CACHE_TTL_HOURS):
        print("✅ fundamentals-snapshot.json fresh, skipping")
        return 0

    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if not token:
        print("⚠️  FINMIND_TOKEN not set — skipping fundamentals cache")
        empty = {
            "status": "skipped",
            "reason": "FINMIND_TOKEN_missing",
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "tickers": {},
            "errors": [],
        }
        if not dry_run:
            atomic_write(SNAP_FILE, empty)
        return 0

    tickers = cli_tickers if cli_tickers else get_tickers()
    if not tickers:
        empty = {
            "status": "skipped",
            "reason": "no_tickers",
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "tickers": {},
            "errors": [],
        }
        if not dry_run:
            atomic_write(SNAP_FILE, empty)
        return 0

    print(f"🔄 fetching FinMind fundamentals for {len(tickers)} tickers...")

    result: dict = {}
    errors: list = []

    for i, sym in enumerate(tickers):
        sym_us = sym  # 台股代號（FinMind data_id），無後綴
        if dry_run:
            print(f"[DRY-RUN] would fetch {sym_us}")
            continue
        try:
            snapshot = fetch_snapshot(sym_us, token)
            base_rate = fetch_base_rate(sym_us, token, sym)
            # P2: compute A4 self-built anchor from historical revenue series
            sv = compute_self_valuation(
                sym, snapshot["highlights"], snapshot["financials"],
                snapshot.get("forward_estimates"),
            )
            result[sym] = {"snapshot": snapshot, "base_rate": base_rate, "self_valuation": sv}
            sv_note = (
                f"A4_own_pt=${sv.get('own_target_price')} ({sv['confidence']})"
                if sv["confidence"] != "unavailable"
                else f"A4=N/A ({sv['notes'][:40]})"
            )
            print(f"  ✓ {sym}: PE={snapshot['highlights'].get('pe_ratio')} "
                  f"PEG={snapshot['highlights'].get('peg_ratio')} "
                  f"PT=NT${snapshot['highlights'].get('wall_street_target')} "
                  f"beat={base_rate['beats']}/{base_rate['quarters_counted']} "
                  f"| {sv_note}")
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

    # --ticker 模式：merge 進現有 cache（保留其他票 + 更新 generated_at 為現有，僅標 merged_at）
    merged = result
    if cli_tickers and SNAP_FILE.exists():
        try:
            existing = json.loads(SNAP_FILE.read_text())
            base = dict(existing.get("tickers", {}))
            base.update(result)  # 新抓的覆蓋同名舊的，其餘保留
            merged = base
            print(f"🔗 merge：現有 {len(existing.get('tickers', {}))} 票 + 本次 {len(result)} 票 → {len(merged)} 票")
        except Exception as e:
            print(f"⚠️  merge 讀取現有 cache 失敗（改為僅寫本次）：{e}")

    payload = {
        "status": "ok" if merged else "empty",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "tickers": merged,
        "errors": errors,
    }
    atomic_write(SNAP_FILE, payload)
    print(f"✅ fundamentals-snapshot.json: {len(merged)} tickers, {len(errors)} errors")
    if errors:
        for err in errors:
            print(f"   ⚠️  {err['ticker']}: {err['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
