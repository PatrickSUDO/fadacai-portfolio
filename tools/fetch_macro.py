#!/usr/bin/env python3
"""
fetch_macro.py — Fetch 台灣總經 indicators (FinMind) with TTL cache.

以 FinMind v4 data API 抓台灣總經序列，組成 briefing 的 zero-latency macro 層。
逐序列容錯：任一 dataset 抓不到只標 partial，不影響其他序列。

Series（FinMind dataset → 內部 name）:
  TaiwanExchangeRate (USD)        usd_twd        新台幣對美元匯率（外資動向 / 出口）
  InterestRate (CBC)              cbc_rate       央行重貼現率
  TaiwanCPI                       cpi_yoy        消費者物價指數 YoY（主計總處）
  TaiwanGovBondYield (10Y)        bond_10y       10 年期公債殖利率（殖利率曲線/利率環境）
  外資買賣超 + 台指 VIX 由 chip-server / 其他來源補（見 briefing skill），非本檔職責。

註：FinMind 部分總經 dataset 命名會調整，本檔以「逐序列 try + partial 容錯」設計，
    某 dataset 名稱失效時該序列降級為 unavailable，不致整體失敗。

Output: briefing-out/cache/macro-snapshot.json
TTL:    24h (skip refresh if cache fresher)

Usage:
  python3 tools/fetch_macro.py              # refresh if cache stale
  python3 tools/fetch_macro.py --force      # force refresh

Env:
  FINMIND_TOKEN   required (free at https://finmindtrade.com/)
  DRY_RUN=1       print what would be fetched, don't write
"""

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Use certifi CA bundle when available (fixes SSL in launchd environments)
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()

# ── Path setup ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "briefing-out" / "cache"
CACHE_FILE = CACHE_DIR / "macro-snapshot.json"

# ── Config ─────────────────────────────────────────────────────────────────
# (dataset, data_id, internal_name)；data_id 為空字串代表該 dataset 不需 data_id。
FINMIND_SERIES = [
    ("TaiwanExchangeRate", "USD", "usd_twd"),
    ("InterestRate", "CBC", "cbc_rate"),
    ("TaiwanCPI", "", "cpi_yoy"),
    ("TaiwanGovBondYield", "10Y", "bond_10y"),
]
CACHE_TTL_HOURS = 24
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"


# ── .env loader (stdlib only) ───────────────────────────────────────────────
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


# ── Retry wrapper ───────────────────────────────────────────────────────────
def with_retry(fn, label: str, max_retries: int = 3):
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as e:
            print(f"[{label}] attempt {attempt}/{max_retries} failed: {e}",
                  file=sys.stderr)
            if attempt < max_retries:
                time.sleep(3 * attempt)
    return None


# ── FinMind fetch ──────────────────────────────────────────────────────────
def fetch_series(dataset: str, data_id: str, token: str, days: int = 800) -> list:
    """Return FinMind data rows (list of dicts), oldest→newest as API returns."""
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {"dataset": dataset, "start_date": start, "token": token}
    if data_id:
        params["data_id"] = data_id
    url = f"{FINMIND_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=25, context=_SSL_CTX) as resp:
        payload = json.loads(resp.read())
    if payload.get("status") != 200:
        raise RuntimeError(payload.get("msg", "FinMind error"))
    return payload.get("data", [])


def _num(row: dict, *keys):
    """Pick first present numeric field from candidate keys."""
    for k in keys:
        if k in row and row[k] not in (None, "", "."):
            try:
                return float(row[k])
            except (TypeError, ValueError):
                continue
    return None


# ── Regime computation（台灣訊號）─────────────────────────────────────────
def classify_twvix(v: float) -> str:
    if v < 15:
        return "low"
    if v < 25:
        return "mid"
    return "high"


def classify_bond_curve(short_rate, long_yield) -> str:
    """以重貼現率(短) vs 10Y 公債殖利率(長)近似殖利率曲線。"""
    if short_rate is None or long_yield is None:
        return "unknown"
    spread = long_yield - short_rate
    if spread < 0:
        return "inverted"
    if spread < 0.3:
        return "flat"
    return "normal"


def classify_twd(change_30d_pct) -> str:
    if change_30d_pct is None:
        return "stable"
    if change_30d_pct > 1.5:
        return "twd_weak"      # 貶值（USD/TWD 上升），外資匯出壓力
    if change_30d_pct < -1.5:
        return "twd_strong"    # 升值，利出口/外資流入
    return "stable"


def compute_regime_tag(series: dict) -> str:
    parts = []
    curve = series.get("bond_curve_regime")
    if curve == "inverted":
        parts.append("recession_signal")
    elif curve == "flat":
        parts.append("late_cycle")
    elif curve == "normal":
        parts.append("normal_cycle")

    twd = series.get("usd_twd", {}).get("regime")
    if twd == "twd_weak":
        parts.append("foreign_outflow_risk")
    elif twd == "twd_strong":
        parts.append("risk_on")

    cpi_trend = series.get("cpi_yoy", {}).get("trend")
    if cpi_trend == "down":
        parts.append("disinflation")
    elif cpi_trend == "up":
        parts.append("reflation")

    return "/".join(parts) if parts else "neutral"


# ── Cache helpers ──────────────────────────────────────────────────────────
def is_cache_fresh(path: Path, ttl_hours: int) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < ttl_hours * 3600


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_skipped(reason: str) -> None:
    snapshot = {
        "status": "skipped",
        "reason": reason,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "series": {},
        "regime_tag": None,
    }
    atomic_write(CACHE_FILE, snapshot)


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    load_env()
    force = "--force" in sys.argv
    dry_run = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")

    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if not token:
        print("⚠️  FINMIND_TOKEN missing, writing skipped status to cache")
        if not dry_run:
            write_skipped("no_api_key")
        return 0

    if not force and is_cache_fresh(CACHE_FILE, CACHE_TTL_HOURS):
        print(f"✅ macro cache fresh (< {CACHE_TTL_HOURS}h), skipping")
        return 0

    print(f"🔄 fetching {len(FINMIND_SERIES)} FinMind 台灣總經 series...")
    raw: dict = {}
    errors: list = []
    for dataset, data_id, name in FINMIND_SERIES:
        if dry_run:
            print(f"[DRY-RUN] would fetch FinMind {dataset}/{data_id or '-'} → {name}")
            continue
        rows = with_retry(lambda d=dataset, i=data_id: fetch_series(d, i, token),
                          f"FinMind {dataset}", max_retries=3)
        if not rows:
            errors.append(name)
            continue
        raw[name] = rows

    if dry_run:
        print("[DRY-RUN] complete, no write")
        return 0

    series_data: dict = {}

    # usd_twd: 取 spot 賣出近值 + 30d 變動
    if "usd_twd" in raw:
        rows = raw["usd_twd"]
        latest = rows[-1]
        rate = _num(latest, "spot_sell", "spot_buy", "cash_sell", "close")
        prev_30 = rows[max(0, len(rows) - 22)]
        prev_rate = _num(prev_30, "spot_sell", "spot_buy", "cash_sell", "close")
        chg = round((rate - prev_rate) / prev_rate * 100, 2) if (rate and prev_rate) else None
        series_data["usd_twd"] = {
            "value": round(rate, 3) if rate else None,
            "date": latest.get("date"),
            "change_30d_pct": chg,
            "regime": classify_twd(chg),
        }

    # cbc_rate: 央行重貼現率
    short_rate = None
    if "cbc_rate" in raw:
        rows = raw["cbc_rate"]
        latest = rows[-1]
        short_rate = _num(latest, "interest_rate", "value", "rediscount_rate")
        series_data["cbc_rate"] = {
            "value": round(short_rate, 3) if short_rate else None,
            "date": latest.get("date"),
        }

    # cpi_yoy: 取最新 YoY + 趨勢（FinMind 若直接給 YoY 用之，否則由 index 推算）
    if "cpi_yoy" in raw:
        rows = raw["cpi_yoy"]
        latest = rows[-1]
        cur = _num(latest, "YoY", "yoy", "cpi_yoy")
        if cur is None:  # 由指數推 YoY
            idx_now = _num(latest, "value", "cpi", "index")
            idx_prev = _num(rows[max(0, len(rows) - 13)], "value", "cpi", "index")
            cur = round((idx_now - idx_prev) / idx_prev * 100, 2) if (idx_now and idx_prev) else None
        prev = _num(rows[max(0, len(rows) - 2)], "YoY", "yoy", "cpi_yoy")
        trend = "stable"
        if cur is not None and prev is not None:
            if cur - prev > 0.2:
                trend = "up"
            elif cur - prev < -0.2:
                trend = "down"
        series_data["cpi_yoy"] = {"value": cur, "date": latest.get("date"), "trend": trend}

    # bond_10y: 10 年期公債殖利率
    long_yield = None
    if "bond_10y" in raw:
        rows = raw["bond_10y"]
        latest = rows[-1]
        long_yield = _num(latest, "yield", "value", "interest_rate")
        series_data["bond_10y"] = {
            "value": round(long_yield, 3) if long_yield else None,
            "date": latest.get("date"),
        }

    series_data["bond_curve_regime"] = classify_bond_curve(short_rate, long_yield)

    regime_tag = compute_regime_tag(series_data)
    status = "ok" if not errors else "partial"

    snapshot = {
        "status": status,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "series": series_data,
        "regime_tag": regime_tag,
        "errors": errors,
        "note": "台指 VIX 與外資買賣超由 chip-server / briefing skill 另補",
    }
    atomic_write(CACHE_FILE, snapshot)
    print(f"✅ macro cache refreshed ({len(series_data)} fields, regime={regime_tag})")
    if errors:
        print(f"⚠️  errors on: {', '.join(errors)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
