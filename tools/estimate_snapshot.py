#!/usr/bin/env python3
"""
estimate_snapshot.py — 每天把分析師預估存一份，累積成「當時看得到什麼」的歷史。

Why（2026-11-22 用戶「幫我開始先存快照」）：選股核心是「分析師上修」，但免費來源只給
「現在的預估」，不給「某一天當時的預估」。沒有這份歷史，上修選股永遠無法回測。
唯一的路是自己每天存；少存一天就永遠少一天。

每檔一次請求抓齊（Yahoo quoteSummary，經 yfinance）：
  earningsTrend          本季/下季/今年/明年：EPS 與營收的平均、高、低、分析師人數；
                         EPS 預估 7/30/60/90 天前的值；7/30 天內上修、下修家數
  financialData          目標價（平均/中位/高/低）、評等平均、覆蓋家數、現價
  recommendationTrend    強買/買/持有/賣/強賣 家數（本月與前三個月）
  defaultKeyStatistics   放空股數、放空回補天數、流通股數、預估 EPS
  calendarEvents         下次財報日
  upgradeDowngradeHistory 只留最近 45 天的升降評與目標價調整
  price                  現價、市值、報價時間

名單：briefing-out/cache/universe.json（發現層約 600 檔）＋ roster 持倉 ＋ SA 兩張清單
      ＋「曾經存過的代號」（掉出名單的照樣繼續存，避免只剩活下來的）。

Output（全在 git-ignored 的 research/ 底下）：
  research/estimate-snapshots/YYYY-MM-DD.jsonl.gz   一行一檔（日期用美東）
  research/estimate-snapshots/manifest.jsonl        每次執行一行（成功/失敗檔數）
  research/estimate-snapshots/tickers-seen.json     曾經存過的代號

排程：launchd 每小時叫一次（tools/launchd/com.fadacai.estimate-snapshot.plist）。
      美東 06:00 以後當天第一次機會就存；當天已存夠就立刻退出；失敗的檔下個小時補。
      連續兩天沒有完整快照 → 推一則 Telegram（每天最多一則）。

Usage:
  python3 tools/estimate_snapshot.py                 # 排程入口（有時間門檻、可重入）
  python3 tools/estimate_snapshot.py --force         # 不管時間門檻，現在就存/補
  python3 tools/estimate_snapshot.py --tickers NVDA,AMD --dry-run   # 試抓、只印不寫
  python3 tools/estimate_snapshot.py status          # 列出已存天數與每日涵蓋率
  python3 tools/estimate_snapshot.py panel           # 攤平成一張表（panel.csv.gz）

注意：
  - 「7/30/60/90 天前的 EPS 預估」是 Yahoo 自己回推的；本檔存的是每天親眼看到的值，兩者之後可互相核對。
  - 資料只記錄，不 gate 任何動作。要拿來選股，先寫好規則再看資料（預先登記），不要邊看邊調。
"""

import argparse
import gzip
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "research" / "estimate-snapshots"
MANIFEST = OUT / "manifest.jsonl"
SEEN = OUT / "tickers-seen.json"
ALERT_MARK = OUT / ".alert-sent"
UNIVERSE = ROOT / "briefing-out" / "cache" / "universe.json"
ROSTER = ROOT / "research" / "roster.json"
SA_SLUGS = ROOT / "research" / "sa-quant-scans" / "slugs.json"

ET = ZoneInfo("America/New_York")
GATE_HOUR_ET = 6          # 美東 06:00 以後才存（開盤前的狀態；歐洲時間約中午）
MODULES = ["earningsTrend", "financialData", "recommendationTrend",
           "defaultKeyStatistics", "calendarEvents", "upgradeDowngradeHistory", "price"]
PRICE_KEEP = ("regularMarketPrice", "regularMarketTime", "marketCap", "currency",
              "exchangeName", "quoteType", "shortName", "regularMarketPreviousClose")
GRADE_KEEP_DAYS = 45
COMPLETE_FRAC = 0.95      # 當天成功檔數 ≥ 95% 視為存夠
MAX_RUNS_PER_DAY = 4      # 一天最多補抓幾輪（避免永遠抓不到的代號每小時重敲）
SLEEP_S = 0.12
ABORT_CONSEC_FAIL = 25    # 連續失敗這麼多檔 → 多半被限流，收手等下一輪
STALE_ALERT_DAYS = 2


def now_et() -> datetime:
    return datetime.now(ET)


def compact(x):
    """Yahoo 的 {"raw":…, "fmt":…} 只留 raw；空 dict → None。"""
    if isinstance(x, dict):
        if "raw" in x:
            return x["raw"]
        if not x:
            return None
        return {k: compact(v) for k, v in x.items() if k != "maxAge"}
    if isinstance(x, list):
        return [compact(v) for v in x]
    return x


def _valid_ticker(t) -> bool:
    return isinstance(t, str) and 0 < len(t) <= 8 and t.replace(".", "").replace("-", "").isalnum()


def load_universe() -> list:
    names = set()
    try:
        names |= set(json.loads(UNIVERSE.read_text())["tickers"])
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ universe.json 讀不到（{type(e).__name__}）", file=sys.stderr)
    try:
        # roster.json: {"buckets": {"信念": [代號…], "認列": […], …}}
        for members in json.loads(ROSTER.read_text()).get("buckets", {}).values():
            names |= {str(t).upper() for t in members if isinstance(t, str)}
    except Exception:  # noqa: BLE001
        pass
    try:
        # slugs.json: {"bench": [slug…], "lists": {"alpha-pick": {"slugs": […]}, …}}
        s = json.loads(SA_SLUGS.read_text())
        names |= {str(t).upper() for t in s.get("bench", [])}
        for lst in s.get("lists", {}).values():
            names |= {str(t).upper() for t in lst.get("slugs", [])}
    except Exception:  # noqa: BLE001
        pass
    try:
        # 這些清單歷次掃描出現過的代號也收（SA 榜上名單每週換，掉榜後仍要追）
        for p in SA_SLUGS.parent.glob("api-*.json"):
            names |= {str(t).upper() for t in json.loads(p.read_text()).get("slugs", [])}
    except Exception:  # noqa: BLE001
        pass
    try:
        names |= set(json.loads(SEEN.read_text()))
    except Exception:  # noqa: BLE001
        pass
    return sorted(t for t in names if _valid_ticker(t))


def yahoo_symbol(t: str) -> str:
    return t.replace(".", "-")     # BRK.B → BRK-B


def fetch_one(ticker: str) -> dict:
    import yfinance as yf
    tk = yf.Ticker(yahoo_symbol(ticker))
    try:
        raw = tk._quote._fetch(modules=MODULES)  # noqa: SLF001
        if not raw or not (raw.get("quoteSummary") or {}).get("result"):
            raise LookupError("not found")       # 查無此檔（下市、改代號）→ 不重試
        res, src = raw["quoteSummary"]["result"][0], "quoteSummary"
    except AttributeError:
        # yfinance 內部介面改版時的備援：走公開屬性（欄位較少，但不會整個斷）
        res, src = {}, "yfinance-public"
        for key, attr in (("eps_trend", "eps_trend"), ("eps_revisions", "eps_revisions"),
                          ("earnings_estimate", "earnings_estimate"),
                          ("revenue_estimate", "revenue_estimate"),
                          ("recommendations_summary", "recommendations_summary")):
            df = getattr(tk, attr, None)
            if df is not None and hasattr(df, "to_dict"):
                res[key] = json.loads(df.to_json(orient="index"))
        res["analyst_price_targets"] = getattr(tk, "analyst_price_targets", None)
    row = {"ticker": ticker, "src": src}
    for m, v in res.items():
        v = compact(v)
        if m == "price" and isinstance(v, dict):
            v = {k: v.get(k) for k in PRICE_KEEP}
        elif m == "upgradeDowngradeHistory" and isinstance(v, dict):
            cut = time.time() - GRADE_KEEP_DAYS * 86400
            v = [h for h in (v.get("history") or []) if (h.get("epochGradeDate") or 0) >= cut]
        elif m == "earningsTrend" and isinstance(v, dict):
            v = v.get("trend")
        elif m == "recommendationTrend" and isinstance(v, dict):
            v = v.get("trend")
        row[m] = v
    return row


def day_file(d: str) -> Path:
    return OUT / f"{d}.jsonl.gz"


def read_day(d: str) -> dict:
    """回傳 {ticker: row}；同一天多輪補抓時後寫的蓋前面的。"""
    rows, p = {}, day_file(d)
    if not p.exists():
        return rows
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                rows[r["ticker"]] = r
            except Exception:  # noqa: BLE001
                continue
    return rows


def manifest_rows() -> list:
    if not MANIFEST.exists():
        return []
    out = []
    for line in MANIFEST.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            pass
    return out


def has_estimates(r: dict) -> bool:
    return bool(r.get("earningsTrend") or r.get("eps_trend") or r.get("financialData"))


def last_complete_day():
    best = None
    for m in manifest_rows():
        if m.get("complete") and (best is None or m["date"] > best):
            best = m["date"]
    return best


def maybe_alert(today: str) -> None:
    """連續 STALE_ALERT_DAYS 天沒有完整快照 → Telegram 一則（每天最多一則）。"""
    days = sorted(p.name[:10] for p in OUT.glob("20??-??-??.jsonl.gz"))
    if not days:
        return                       # 第一次執行前不吵
    last = last_complete_day() or "（無）"
    ref = last if last[:2] == "20" else days[0]
    gap = (datetime.fromisoformat(today) - datetime.fromisoformat(ref)).days
    if gap < STALE_ALERT_DAYS:
        return
    if ALERT_MARK.exists() and ALERT_MARK.read_text().strip() == today:
        return
    msg = (f"⚠️ 分析師預估快照已 {gap} 天沒有存完整（最後完整日 {last}）。"
           f"少存的日子補不回來。檢查：python3 tools/estimate_snapshot.py status")
    try:
        subprocess.run([sys.executable, str(ROOT / "tools" / "tg_send.py"), msg],
                       timeout=60, check=False, capture_output=True)
        ALERT_MARK.write_text(today)
    except Exception:  # noqa: BLE001
        pass


def run(args) -> int:
    now = now_et()
    today = now.strftime("%Y-%m-%d")
    OUT.mkdir(parents=True, exist_ok=True)

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = load_universe()
    if not tickers:
        print("⚠️ 名單是空的，沒有存", file=sys.stderr)
        return 1

    if not args.force and not args.tickers:
        if now.hour < GATE_HOUR_ET:
            return 0
        runs_today = [m for m in manifest_rows() if m.get("date") == today]
        if any(m.get("complete") for m in runs_today):
            return 0
        if len(runs_today) >= MAX_RUNS_PER_DAY:
            maybe_alert(today)
            return 0

    have = {} if (args.dry_run or args.tickers) else read_day(today)
    todo = [t for t in tickers if t not in have or not has_estimates(have[t])]
    if args.limit:
        todo = todo[: args.limit]
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ok, fail, consec, aborted = [], [], 0, False
    fh = None if args.dry_run else gzip.open(day_file(today), "at", encoding="utf-8")
    try:
        for i, t in enumerate(todo):
            row, err = None, None
            for attempt in range(3):
                try:
                    row = fetch_one(t)
                    break
                except Exception as e:  # noqa: BLE001
                    err = f"{type(e).__name__}: {str(e)[:80]}"
                    if isinstance(e, LookupError):
                        break            # 查無此檔，不必重試
                    time.sleep((2, 6, 15)[attempt])
            if row is not None:
                row["date"] = today
                row["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                if args.dry_run:
                    print(json.dumps(row, ensure_ascii=False)[:600])
                else:
                    fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                ok.append(t)
                consec = 0
            else:
                fail.append([t, err])
                consec += 1
                if consec >= ABORT_CONSEC_FAIL:
                    aborted = True
                    break
            time.sleep(SLEEP_S)
    finally:
        if fh:
            fh.close()

    if args.dry_run or args.tickers:
        print(f"試抓：成功 {len(ok)}、失敗 {len(fail)} {fail[:5]}")
        return 0

    rows = read_day(today)
    n_have = len([t for t in tickers if t in rows])
    n_est = len([t for t in tickers if t in rows and has_estimates(rows[t])])
    runs_today = len([m for m in manifest_rows() if m.get("date") == today]) + 1
    complete = n_have >= COMPLETE_FRAC * len(tickers) and not aborted
    try:
        import yfinance as yf
        ver = yf.__version__
    except Exception:  # noqa: BLE001
        ver = "?"
    with MANIFEST.open("a") as f:
        f.write(json.dumps({
            "date": today, "run": runs_today, "started_utc": started,
            "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "requested": len(tickers), "fetched_this_run": len(ok), "failed_this_run": len(fail),
            "have": n_have, "with_estimates": n_est, "aborted": aborted, "complete": complete,
            "yfinance": ver, "fail_sample": fail[:15],
        }, ensure_ascii=False) + "\n")
    seen = set(tickers)
    try:
        seen |= set(json.loads(SEEN.read_text()))
    except Exception:  # noqa: BLE001
        pass
    SEEN.write_text(json.dumps(sorted(seen)))
    if complete and ALERT_MARK.exists():
        ALERT_MARK.unlink()
    if not complete:
        maybe_alert(today)
    print(f"{'✅' if complete else '⚠️'} {today} 快照：名單 {len(tickers)}、已存 {n_have}、"
          f"有預估 {n_est}、本輪失敗 {len(fail)}{'（連續失敗收手）' if aborted else ''}")
    return 0 if complete else 2


def status(_args) -> int:
    days = sorted(p.name[:10] for p in OUT.glob("20??-??-??.jsonl.gz"))
    if not days:
        print("還沒有任何快照")
        return 1
    last = {}
    for m in manifest_rows():
        last[m["date"]] = m
    size = sum(p.stat().st_size for p in OUT.glob("*.jsonl.gz")) / 1e6
    print(f"已存 {len(days)} 天（{days[0]} → {days[-1]}），共 {size:.1f} MB")
    gaps = []
    for a, b in zip(days, days[1:]):
        g = (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days
        if g > 1:
            gaps.append(f"{a}→{b}（缺 {g - 1} 天）")
    print("缺口：" + ("、".join(gaps) if gaps else "無"))
    print("日期        名單  已存  有預估  完整")
    for d in days[-10:]:
        m = last.get(d, {})
        print(f"{d}  {m.get('requested', '?'):>4}  {m.get('have', '?'):>4}  "
              f"{m.get('with_estimates', '?'):>5}   {'是' if m.get('complete') else '否'}")
    today = now_et().strftime("%Y-%m-%d")
    stale = (datetime.fromisoformat(today) - datetime.fromisoformat(days[-1])).days
    return 2 if stale >= STALE_ALERT_DAYS else 0


def panel(_args) -> int:
    """攤平成一張表：一列 = 日期 × 代號 × 期別。之後做上修訊號、前瞻測試用。"""
    import csv
    cols = ["date", "ticker", "period", "end_date", "eps_avg", "eps_low", "eps_high", "eps_n",
            "eps_7d_ago", "eps_30d_ago", "eps_60d_ago", "eps_90d_ago",
            "up_7d", "up_30d", "down_7d", "down_30d", "rev_avg", "rev_n",
            "target_mean", "target_median", "rec_mean", "n_opinions",
            "price", "market_cap", "short_ratio", "shares_short", "next_earnings"]
    out = OUT / "panel.csv.gz"
    n = 0
    with gzip.open(out, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in sorted(OUT.glob("20??-??-??.jsonl.gz")):
            for t, r in read_day(p.name[:10]).items():
                fd = r.get("financialData") or {}
                ks = r.get("defaultKeyStatistics") or {}
                pr = r.get("price") or {}
                ce = ((r.get("calendarEvents") or {}).get("earnings") or {}).get("earningsDate") or [None]
                for tr in r.get("earningsTrend") or []:
                    ee, re_ = tr.get("earningsEstimate") or {}, tr.get("revenueEstimate") or {}
                    et, er = tr.get("epsTrend") or {}, tr.get("epsRevisions") or {}
                    w.writerow([r.get("date"), t, tr.get("period"), tr.get("endDate"),
                                ee.get("avg"), ee.get("low"), ee.get("high"), ee.get("numberOfAnalysts"),
                                et.get("7daysAgo"), et.get("30daysAgo"), et.get("60daysAgo"), et.get("90daysAgo"),
                                er.get("upLast7days"), er.get("upLast30days"),
                                er.get("downLast7Days"), er.get("downLast30days"),
                                re_.get("avg"), re_.get("numberOfAnalysts"),
                                fd.get("targetMeanPrice"), fd.get("targetMedianPrice"),
                                fd.get("recommendationMean"), fd.get("numberOfAnalystOpinions"),
                                pr.get("regularMarketPrice"), pr.get("marketCap"),
                                ks.get("shortRatio"), ks.get("sharesShort"), ce[0]])
                    n += 1
    print(f"panel：{n} 列 → {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "status", "panel"])
    ap.add_argument("--force", action="store_true", help="不管時間門檻與每日輪數上限")
    ap.add_argument("--tickers", help="臨時清單（逗號分隔）；不寫入當日檔")
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 檔（測試用）")
    ap.add_argument("--dry-run", action="store_true", help="只印不寫")
    args = ap.parse_args()
    return {"run": run, "status": status, "panel": panel}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
