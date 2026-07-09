#!/usr/bin/env python3
"""
pmcc_scan.py — Poor Man's Covered Call 候選發現引擎。

對每個候選 ticker 跑 5 因子計分卡（規則見 feedback/pmcc-candidate-discipline.md）：
  1. 方向 range-bound（GATE）：trend 非 strong_up/strong_down；revision 非加速；target upside 適中
  2. IV 肥：ATR% / vol_regime（high 才收得到肉）
  3. 期權流動性：短腿 OI + bid/ask spread + underlying avg vol（能 roll）
  4. LEAPS 經濟性：12-18 月 deep-ITM（δ≈0.80-0.88）存在 + 時間價值可接受
  5. 桶別相容：revision 加速 / target 噴 = 反 pattern（讓 run，別封頂）→ 機械排除

資料源（沿用 event_vol_scan.py 慣例）：
  - yfinance 本地庫：價格歷史（trend/mom/ATR%/RSI）+ 期權鏈（LEAPS + 短腿）
  - EODHD REST（.env token）：revision（up/dn 30d）、WallStreetTargetPrice、beta；cache 優先
  - 快取 briefing-out/cache/fundamentals-snapshot.json（含 21 檔組合/觀察名）、earnings-dates.json

Strike 選擇用 Black-Scholes delta（math.erf，無 scipy）：LEAPS 挑 δ≈0.82、短腿挑 δ≈0.30 且
strike ≥ LEAPS breakeven（strike+debit）。機械計 cycle yield / max profit / 成本基礎降幅。
判斷層（thesis、口數、實際掛單、桶別歸屬）留給 /options-strategy skill。

用法：
  python3 tools/pmcc_scan.py                       # 無參數 → 掃 fundamentals 快取全部 21 檔（不忘記）
  python3 tools/pmcc_scan.py --tickers TSLA,GOOGL  # ad-hoc 指定
  python3 tools/pmcc_scan.py --only-candidates      # 只印 PMCC_CANDIDATE
  python3 tools/pmcc_scan.py --json briefing-out/cache/pmcc-scan.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    print("ERROR: 本機 python 缺 yfinance（pip install yfinance）", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "briefing-out" / "cache"
EODHD_BASE = "https://eodhd.com/api"

# ── 5 因子計分卡門檻（源 feedback/pmcc-candidate-discipline.md）────────────────
# 因子 1 — 方向 range-bound
TARGET_UPSIDE_MAX = 0.30       # target > +30% = 火箭，讓 run 別封頂
TARGET_UPSIDE_SWEET_LO = 0.05  # 甜蜜區下緣
TARGET_UPSIDE_FLOOR = -0.08    # < -8% = street 投降，LEAPS 論點存疑 → WATCH
REV_ACCEL_MIN_UP = 15          # revision 加速判定：up ≥ 15
REV_ACCEL_RATIO = 4.0          # 且 up ≥ 4× down → 加速（反 pattern）
MOM_STRONG = 12.0              # |20d 動能| > 12% → strong trend
MOM_MILD = 3.0                 # |20d 動能| > 3% → mild trend
# 因子 2 — IV 肥
ATR_HIGH = 3.5                 # ATR% ≥ 3.5 → vol_regime high
ATR_MED = 2.0                  # ATR% ≥ 2.0 → medium
IV_RICH_MIN = 0.40             # 短腿到期 ATM IV ≥ 40% 也算 premium 肥（ATR% 的補充）
# 因子 3 — 期權流動性
SHORT_DTE_LO, SHORT_DTE_HI, SHORT_DTE_TGT = 25, 50, 38
MIN_SHORT_OI = 200             # 短腿 strike OI 門檻
MAX_SPREAD_PCT = 0.15          # 短腿 bid-ask/mid 上限
MIN_AVG_VOL = 800_000          # underlying 20d 均量門檻（能 roll）
# 因子 4 — LEAPS 經濟性
LEAPS_DTE_LO, LEAPS_DTE_HI, LEAPS_DTE_TGT = 300, 560, 450
LEAPS_DELTA_TGT = 0.82
LEAPS_DELTA_LO, LEAPS_DELTA_HI = 0.72, 0.90
MAX_LEAPS_TV_PCT = 0.18        # LEAPS 時間價值/spot 上限（付太多 debit 不划算）
# 短腿目標 delta
SHORT_DELTA_TGT = 0.30


def _load_env_token() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("EODHD_API_TOKEN="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("EODHD_API_TOKEN", "")


def _load_cache(name: str) -> dict:
    p = CACHE_DIR / name
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def _eodhd_get(endpoint: str, params: dict, token: str):
    p = dict(params)
    p["api_token"] = token
    p["fmt"] = "json"
    resp = requests.get(f"{EODHD_BASE}/{endpoint}", params=p, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Black-Scholes call delta（r≈0、無股利近似；strike 選擇用，非定價）──────────
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_call_delta(spot: float, strike: float, t_years: float, iv: float) -> float | None:
    if spot <= 0 or strike <= 0 or t_years <= 0 or iv <= 0:
        return None
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t_years) / (iv * math.sqrt(t_years))
    return _norm_cdf(d1)


def _iv_est_from_atr(atr_pct: float | None) -> float:
    """從 ATR% 推年化波動當 IV fallback（盤前 yfinance IV 壞掉時用）。
    daily_std ≈ ATR/1.4；年化 ×√252；clamp [0.15, 1.5]。"""
    if not atr_pct:
        return 0.45
    return max(0.15, min(1.5, (atr_pct / 100.0 / 1.4) * math.sqrt(252)))


def _sane_iv(row_iv, iv_est: float) -> float:
    """鏈上 IV 合理（10%–250%）就用，否則用 ATR 推估（盤前 IV 常是 0.2% 之類 artifact）。"""
    try:
        v = float(row_iv or 0)
    except (TypeError, ValueError):
        v = 0.0
    return v if 0.10 <= v <= 2.5 else iv_est


def _safe_int(v) -> int:
    """NaN / None / 非數 → 0（盤前 yfinance OI/volume 常是 NaN）。"""
    try:
        f = float(v)
        return 0 if math.isnan(f) else int(f)
    except (TypeError, ValueError):
        return 0


def _to_float(v):
    """字串/None/NaN → float 或 None（EODHD REST 常回字串數字）。"""
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _mid(row) -> float | None:
    bid, ask, last = float(row.get("bid") or 0), float(row.get("ask") or 0), float(row.get("lastPrice") or 0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    return last if last > 0 else None


# ── 技術面（從 yfinance 收盤自算，取代 technical MCP）──────────────────────────
def _rsi(closes, n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    delta = closes.diff().dropna()
    up = delta.clip(lower=0).rolling(n).mean().iloc[-1]
    dn = (-delta.clip(upper=0)).rolling(n).mean().iloc[-1]
    if dn == 0:
        return 100.0
    rs = up / dn
    return round(100 - 100 / (1 + rs), 1)


def _atr_pct(hist, n: int = 14) -> float | None:
    if len(hist) < n + 1:
        return None
    h, l, c = hist["High"], hist["Low"], hist["Close"]
    pc = c.shift(1)
    tr = (h - l).combine((h - pc).abs(), max).combine((l - pc).abs(), max)
    atr = tr.rolling(n).mean().iloc[-1]
    price = float(c.iloc[-1])
    return round(float(atr) / price * 100, 2) if price else None


def _classify_trend(price, sma50, sma200, mom_pct) -> str:
    above50 = sma50 is not None and price > sma50
    above200 = sma200 is not None and price > sma200
    if above50 and (above200 or sma200 is None) and mom_pct > MOM_STRONG:
        return "strong_uptrend"
    if (not above50) and (not above200 if sma200 is not None else True) and mom_pct < -MOM_STRONG:
        return "strong_downtrend"
    if above50 and mom_pct > MOM_MILD:
        return "mild_uptrend"
    if (not above50) and mom_pct < -MOM_MILD:
        return "weak_downtrend"
    return "consolidation"


def _vol_regime(atr_pct: float | None) -> str:
    if atr_pct is None:
        return "unknown"
    if atr_pct >= ATR_HIGH:
        return "high"
    if atr_pct >= ATR_MED:
        return "medium"
    return "low"


# ── 基本面（cache 優先 → EODHD fallback）──────────────────────────────────────
def _fundamentals(ticker: str, fund_cache: dict, token: str) -> dict:
    """回 {target, rev_up, rev_dn, eps_growth, beta}；cache 先，miss 打 EODHD。"""
    ent = (fund_cache.get("tickers") or {}).get(ticker)
    if ent:
        snap = ent.get("snapshot") or {}
        hl = snap.get("highlights") or {}
        tech = snap.get("technicals") or {}
        cf = (snap.get("forward_estimates") or {}).get("curr_fy") or {}
        return {
            "target": hl.get("wall_street_target"),
            "rev_up": cf.get("revisions_up_30d"),
            "rev_dn": cf.get("revisions_down_30d"),
            "eps_growth": cf.get("eps_growth"),
            "beta": tech.get("beta"),
            "src": "cache",
        }
    if not token:
        return {"src": "none"}
    try:
        data = _eodhd_get(f"fundamentals/{ticker}.US",
                          {"filter": "Highlights,Technicals,Earnings::Trend"}, token)
        if not isinstance(data, dict):
            return {"src": "none"}
        hl = data.get("Highlights") or {}
        tech = data.get("Technicals") or {}
        trend = data.get("Earnings::Trend") or {}
        # 取 period=="0y"（curr_fy）最新日期那筆
        best = None
        for dk, e in trend.items() if isinstance(trend, dict) else []:
            if isinstance(e, dict) and e.get("period") == "0y":
                if best is None or dk > best[0]:
                    best = (dk, e)
        cf = best[1] if best else {}
        return {
            "target": hl.get("WallStreetTargetPrice"),
            "rev_up": cf.get("epsRevisionsUpLast30days"),
            "rev_dn": cf.get("epsRevisionsDownLast30days"),
            "eps_growth": cf.get("earningsEstimateGrowth"),
            "beta": tech.get("Beta"),
            "src": "eodhd",
        }
    except Exception as e:
        return {"src": f"error:{e}"}


def _next_earnings(ticker: str, today: date, dates_cache: dict) -> str | None:
    ent = (dates_cache.get("tickers") or {}).get(ticker)
    if ent and ent.get("next_date"):
        return ent["next_date"]
    return None


def _pick_expiry(expiries: list[str], today: date, lo: int, hi: int, tgt: int) -> str | None:
    cand = []
    for e in expiries:
        try:
            dte = (date.fromisoformat(e) - today).days
        except ValueError:
            continue
        if lo <= dte <= hi:
            cand.append((abs(dte - tgt), e))
    if not cand:
        return None
    return sorted(cand)[0][1]


def scan_one(ticker: str, today: date, fund_cache: dict, dates_cache: dict, token: str) -> dict:
    out: dict = {"ticker": ticker}
    tk = yf.Ticker(ticker)
    hist = tk.history(period="1y", auto_adjust=True)
    if hist is None or len(hist) < 60:
        out["error"] = "價格歷史不足"
        return out
    closes = hist["Close"]
    spot = float(closes.iloc[-1])
    sma20 = float(closes.iloc[-20:].mean())
    sma50 = float(closes.iloc[-50:].mean()) if len(closes) >= 50 else None
    sma200 = float(closes.iloc[-200:].mean()) if len(closes) >= 200 else None
    mom = round(float(closes.iloc[-1] / closes.iloc[-21] - 1) * 100, 1) if len(closes) >= 21 else 0.0
    _v = hist["Volume"].iloc[-20:].mean()
    avg_vol = 0.0 if (_v is None or math.isnan(_v)) else float(_v)
    atrp = _atr_pct(hist)
    trend = _classify_trend(spot, sma50, sma200, mom)
    regime = _vol_regime(atrp)
    out.update({"spot": round(spot, 2), "mom_20d": mom, "atr_pct": atrp,
                "trend": trend, "vol_regime": regime, "avg_vol": _safe_int(avg_vol),
                "rsi": _rsi(closes)})

    f = _fundamentals(ticker, fund_cache, token)
    target = _to_float(f.get("target"))            # EODHD fallback 可能回字串 → 統一轉型
    rev_up, rev_dn = _safe_int(f.get("rev_up")), _safe_int(f.get("rev_dn"))
    upside = round(target / spot - 1, 4) if target else None
    out.update({"target": target, "target_upside": upside, "rev_up": rev_up, "rev_dn": rev_dn,
                "beta": f.get("beta"), "fund_src": f.get("src")})
    out["next_earnings"] = _next_earnings(ticker, today, dates_cache)

    # ── 因子 1（方向 GATE）+ 因子 5（反 pattern）機械判定 ──
    rev_accel = rev_up >= REV_ACCEL_MIN_UP and rev_up >= REV_ACCEL_RATIO * max(rev_dn, 1)
    out["rev_accel"] = rev_accel
    if trend == "strong_downtrend":
        out["verdict"] = "EXCLUDE_FALLING_KNIFE"
        out["reason"] = f"strong_downtrend mom {mom:+.0f}% → LEAPS 會流血，砍不是收租"
        return out
    if rev_accel or (upside is not None and upside > TARGET_UPSIDE_MAX) or trend == "strong_uptrend":
        bits = []
        if rev_accel:
            bits.append(f"revision 加速 {rev_up:.0f}:{rev_dn:.0f}")
        if upside is not None and upside > TARGET_UPSIDE_MAX:
            bits.append(f"target +{upside:.0%}")
        if trend == "strong_uptrend":
            bits.append("strong_uptrend")
        out["verdict"] = "EXCLUDE_LET_RUN"
        out["reason"] = "反 pattern（讓它 run，封頂=機會成本）：" + "、".join(bits)
        return out
    if regime == "low" and (atrp or 0) < ATR_MED:
        out["verdict"] = "EXCLUDE_LOW_IV"
        out["reason"] = f"vol_regime low（ATR% {atrp}）→ premium 太薄，不如裸持 LEAPS"
        return out

    # ── 通過方向+IV GATE → 拉期權鏈驗因子 3/4 ──
    try:
        expiries = list(tk.options or [])
    except Exception as e:
        out["verdict"] = "ERROR"
        out["reason"] = f"期權鏈讀取失敗：{e}"
        return out
    leaps_exp = _pick_expiry(expiries, today, LEAPS_DTE_LO, LEAPS_DTE_HI, LEAPS_DTE_TGT)
    short_exp = _pick_expiry(expiries, today, SHORT_DTE_LO, SHORT_DTE_HI, SHORT_DTE_TGT)
    if not leaps_exp:
        out["verdict"] = "EXCLUDE_NO_LEAPS"
        out["reason"] = "無 12-18 月 LEAPS 到期"
        return out
    if not short_exp:
        out["verdict"] = "EXCLUDE_NO_SHORT"
        out["reason"] = "無 30-45 DTE 短腿到期"
        return out

    # 因子 4：LEAPS 挑 δ≈0.82（IV 壞掉用 ATR 推估，盤前也不壞）
    iv_est = _iv_est_from_atr(atrp)
    lt = (date.fromisoformat(leaps_exp) - today).days / 365.0
    lcalls = tk.option_chain(leaps_exp).calls
    best_leaps = None
    for _, r in lcalls.iterrows():
        k = float(r["strike"])
        d = _bs_call_delta(spot, k, lt, _sane_iv(r.get("impliedVolatility"), iv_est))
        if d is None or not (LEAPS_DELTA_LO <= d <= LEAPS_DELTA_HI):
            continue
        mid = _mid(r)
        if not mid:
            continue
        score = abs(d - LEAPS_DELTA_TGT)
        if best_leaps is None or score < best_leaps["score"]:
            best_leaps = {"strike": k, "mid": round(mid, 2), "delta": round(d, 3),
                          "tv": round(mid - max(spot - k, 0), 2), "dte": (date.fromisoformat(leaps_exp) - today).days,
                          "score": score}
    if best_leaps is None:
        out["verdict"] = "EXCLUDE_NO_LEAPS"
        out["reason"] = f"LEAPS 到期 {leaps_exp} 無 δ∈[{LEAPS_DELTA_LO},{LEAPS_DELTA_HI}] 有效報價"
        return out
    debit = best_leaps["mid"]
    breakeven = best_leaps["strike"] + debit
    tv_pct = best_leaps["tv"] / spot if spot else 0
    out["leaps"] = {**{k: v for k, v in best_leaps.items() if k != "score"},
                    "breakeven": round(breakeven, 2), "tv_pct": round(tv_pct, 3), "expiry": leaps_exp}
    if tv_pct > MAX_LEAPS_TV_PCT:
        out["verdict"] = "WATCH"
        out["reason"] = f"LEAPS 時間價值 {tv_pct:.0%} > {MAX_LEAPS_TV_PCT:.0%}（debit 太貴）"
        return out

    # 因子 3：短腿挑 δ≈0.30 且 strike ≥ breakeven
    st = (date.fromisoformat(short_exp) - today).days / 365.0
    short_dte = (date.fromisoformat(short_exp) - today).days
    scalls = tk.option_chain(short_exp).calls
    best_short = None
    for _, r in scalls.iterrows():
        k = float(r["strike"])
        if k < breakeven:
            continue
        iv = _sane_iv(r.get("impliedVolatility"), iv_est)
        d = _bs_call_delta(spot, k, st, iv)
        mid = _mid(r)
        if mid is None:
            continue
        # 目標 δ≈0.30；若鏈上 breakeven 以上的最低 strike delta 仍 <0.30，取最接近者
        dd = abs((d if d is not None else 0) - SHORT_DELTA_TGT)
        cand = {"strike": k, "mid": round(mid, 2), "delta": round(d, 3) if d else None,
                "oi": _safe_int(r.get("openInterest")), "iv": round(iv, 3),
                "spread_pct": (round(float(r["ask"] - r["bid"]) / mid, 3)
                               if r.get("bid") and r.get("ask") and mid else None),
                "score": dd}
        if best_short is None or cand["score"] < best_short["score"]:
            best_short = cand
    if best_short is None:
        out["verdict"] = "EXCLUDE_NO_SHORT"
        out["reason"] = f"短腿到期 {short_exp} 無 strike ≥ breakeven ${breakeven:.0f} 的有效報價"
        return out
    credit = best_short["mid"]
    out["short"] = {**{k: v for k, v in best_short.items() if k != "score"},
                    "dte": short_dte, "expiry": short_exp}

    # 流動性 GATE（OI==0 視為盤前不可靠，改依均量；均量仍能擋真 illiquid 如 DIOD）
    liq_fail, liq_note = [], []
    if best_short["oi"] == 0:
        liq_note.append("OI 盤前不可靠→依均量")
    elif best_short["oi"] < MIN_SHORT_OI:
        liq_fail.append(f"短腿 OI {best_short['oi']}<{MIN_SHORT_OI}")
    if best_short["spread_pct"] is not None and best_short["spread_pct"] > MAX_SPREAD_PCT:
        liq_fail.append(f"spread {best_short['spread_pct']:.0%}>{MAX_SPREAD_PCT:.0%}")
    if avg_vol < MIN_AVG_VOL:
        liq_fail.append(f"均量 {avg_vol/1e6:.1f}M<{MIN_AVG_VOL/1e6:.1f}M")
    if liq_fail:
        out["verdict"] = "EXCLUDE_ILLIQUID"
        out["reason"] = "；".join(liq_fail)
        return out

    # ── PMCC 經濟性（機械計算）──
    width = best_short["strike"] - best_leaps["strike"]
    basis_after = debit - credit
    max_profit = width - basis_after
    cycle_yield = credit / debit if debit else None
    ann_yield = cycle_yield * 365 / short_dte if cycle_yield and short_dte else None
    out["econ"] = {
        "debit": debit, "credit": credit, "basis_after": round(basis_after, 2),
        "width": round(width, 2), "max_profit": round(max_profit, 2),
        "cycle_yield": round(cycle_yield, 3) if cycle_yield else None,
        "ann_yield": round(ann_yield, 3) if ann_yield else None,
    }
    out["verdict"] = "PMCC_CANDIDATE"
    notes = list(liq_note) + [f"短腿 δ{best_short['delta']} ≥BE ${breakeven:.0f}",
             f"單輪收 {cycle_yield:.0%}／年化 ~{ann_yield:.0%}"]
    if upside is not None and upside < TARGET_UPSIDE_FLOOR:
        notes.append(f"⚠️target {upside:+.0%} street 投降，LEAPS 論點自查")
    if out["next_earnings"]:
        try:
            days_to_er = (date.fromisoformat(out["next_earnings"]) - today).days
            if 0 <= days_to_er <= short_dte:
                notes.append(f"⚠️短腿跨財報 {out['next_earnings']}（±48h 開倉禁令 + timing 決策）")
        except ValueError:
            pass
    out["notes"] = notes
    return out


def _fmt_pct(x, signed=False):
    if x is None:
        return "—"
    return f"{x:+.0%}" if signed else f"{x:.0%}"


def main() -> int:
    ap = argparse.ArgumentParser(description="PMCC 候選 5 因子掃描")
    ap.add_argument("--tickers", default="", help="逗號分隔；空 → 掃 fundamentals 快取全部")
    ap.add_argument("--exclude", default="", help="逗號分隔排除清單")
    ap.add_argument("--only-candidates", action="store_true", help="只印 PMCC_CANDIDATE")
    ap.add_argument("--json", default=None, help="輸出完整 JSON 到此路徑")
    args = ap.parse_args()

    today = date.today()
    token = _load_env_token()
    fund_cache = _load_cache("fundamentals-snapshot.json")
    dates_cache = _load_cache("earnings-dates.json")

    if args.tickers.strip():
        universe = [x.strip().upper() for x in args.tickers.split(",") if x.strip()]
    else:
        universe = sorted((fund_cache.get("tickers") or {}).keys())
    excl = {x.strip().upper() for x in args.exclude.split(",") if x.strip()}
    universe = [t for t in universe if t not in excl]
    if not universe:
        print("ERROR: 無 ticker 可掃（--tickers 或先跑 fetch_fundamentals.py 填快取）", file=sys.stderr)
        return 1

    results = []
    for t in universe:
        try:
            results.append(scan_one(t, today, fund_cache, dates_cache, token))
        except Exception as e:
            results.append({"ticker": t, "verdict": "ERROR", "reason": str(e)})

    order = {"PMCC_CANDIDATE": 0, "WATCH": 1, "EXCLUDE_LOW_IV": 2, "EXCLUDE_ILLIQUID": 3,
             "EXCLUDE_NO_LEAPS": 4, "EXCLUDE_NO_SHORT": 4, "EXCLUDE_LET_RUN": 5,
             "EXCLUDE_FALLING_KNIFE": 6, "ERROR": 9}
    results.sort(key=lambda r: (order.get(r.get("verdict"), 8), r.get("ticker")))

    cand = [r for r in results if r.get("verdict") == "PMCC_CANDIDATE"]
    print(f"# PMCC 候選掃描（{today.isoformat()}，universe {len(universe)} 檔，候選 {len(cand)}）")
    print(f"> 5 因子計分卡 | 規則 feedback/pmcc-candidate-discipline.md | 判斷層留給 /options-strategy\n")
    print("| Ticker | 現價 | Trend/Mom | IV(ATR%) | Rev(up:dn) | Target | 裁決 | LEAPS(δ/BE) | 短腿(δ/credit/DTE) | 單輪/年化 | 備註 |")
    print("|--------|-----:|-----------|---------|-----------|-------:|------|-------------|--------------------|----------|------|")
    for r in results:
        if args.only_candidates and r.get("verdict") != "PMCC_CANDIDATE":
            continue
        if r.get("error"):
            print(f"| {r['ticker']} | — | — | — | — | — | ERROR | — | — | — | {r['error']} |")
            continue
        lp = r.get("leaps") or {}
        sh = r.get("short") or {}
        ec = r.get("econ") or {}
        leaps_s = f"${lp['strike']:.0f}C δ{lp['delta']}/BE ${lp['breakeven']:.0f}" if lp else "—"
        short_s = (f"${sh['strike']:.0f}C δ{sh.get('delta')}/${sh['mid']}/{sh['dte']}d" if sh else "—")
        yld = (f"{ec['cycle_yield']:.0%}/{ec['ann_yield']:.0%}" if ec.get("cycle_yield") else "—")
        note = "；".join(r.get("notes") or ([r.get("reason")] if r.get("reason") else []))
        print(f"| {r['ticker']} | {r.get('spot','—')} | {r.get('trend','—')} {r.get('mom_20d',0):+.0f}% "
              f"| {r.get('vol_regime','—')}({r.get('atr_pct','—')}) | {_safe_int(r.get('rev_up'))}:{_safe_int(r.get('rev_dn'))} "
              f"| {_fmt_pct(r.get('target_upside'), signed=True)} | **{r.get('verdict','—')}** "
              f"| {leaps_s} | {short_s} | {yld} | {note} |")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"generated_at": datetime.now().isoformat(), "universe": universe, "results": results},
            ensure_ascii=False, indent=2))
        print(f"\nJSON → {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
