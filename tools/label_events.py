#!/usr/bin/env python3
"""label_events.py — 新聞 → 結構化事件帳（2026-09-21，JEV 評估後的第一步）

為什麼：portfolio 每天流過 ~136 篇有內文的新聞，但判斷只在 briefing 裡即興讀幾篇，
沒有一條線是「每天對全部樣本用同一套尺量」，所以永遠累積不出能算命中率的 n。
EODHD 情緒分數無用（H7）是因為它只給正負不給事件類型。這支工具把每篇標成固定 schema，
寫進 research/event-ledger.jsonl，20/60 日後機械算條件報酬，briefing 只陳列（display-only，同 A4/R18 紀律）。

標註器可換（--labeler）：
  claude-haiku（預設）：`claude -p --model haiku`，30 篇一批。用戶為 Max 訂閱 → 邊際成本 0，只佔 5 小時窗額度；批次是為了省額度與時間，CLI 回報的 total_cost_usd 為名目值
  jev：TypeSafe System One（POST /v1/systemone，TYPESAFE_API_KEY），早期存取，adapter 待 key 到後補實作
兩者輸出同 schema，可用 `compare` 對同一批文章算一致率。

Usage:
  uv run --directory tools python3 tools/label_events.py run [--date YYYY-MM-DD] [--labeler claude-haiku|jev] [--limit N]
  uv run --directory tools python3 tools/label_events.py score        # 到期事件補 r20/r60（yfinance）
  python3 tools/label_events.py stats [--min-n 8]                     # 事件類型 × 方向的條件報酬
  python3 tools/label_events.py compare --date YYYY-MM-DD             # 同批文章 claude-haiku vs jev 一致率（需兩邊都跑過）
"""
import glob, hashlib, json, os, re, subprocess, sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "briefing-out" / "cache" / "news-articles.json"
ARCH = ROOT / "briefing-out" / "cache" / "archive"
LEDGER = ROOT / "research" / "event-ledger.jsonl"
BATCH = 30

EVENT_TYPES = ["guidance_raise", "guidance_cut", "earnings_beat", "earnings_miss", "capacity_expansion", "capex_cut",
               "pricing_up", "pricing_down", "demand_accel", "demand_decel", "supply_constraint", "inventory_correction",
               "new_customer_or_contract", "customer_loss_or_share_loss", "product_launch", "regulatory_or_policy",
               "geopolitical", "m_and_a", "financing_or_dilution", "insider_or_buyback", "analyst_rating_change",
               "macro_rates_fed", "management_change", "legal_or_investigation", "commentary_only"]

SCHEMA = {
    "id": "文章 id（照抄）",
    "event_type": "one of: " + ", ".join(EVENT_TYPES),
    "direction": "對主要相關標的的方向：1 利多 / 0 中性 / -1 利空",
    "horizon": "near(≤1 季) | mid(1-4 季) | structural(>1 年) | none",
    "quant_statement": "文中最關鍵的一句『帶數字』的陳述，逐字 ≤120 字；沒有數字就 null",
    "affected": "受影響的 ticker 陣列（僅限文章 symbols 內）",
    "is_commentary": "true 若文章只是評論/選股名單/無新事實",
    "confidence": "0-1，你對 event_type 分類正確的信心",
}


def _load_day(day: str | None):
    p = LIVE if not day or day == date.today().isoformat() else ARCH / day / "news-articles.json"
    if not p.exists():
        return {}, p
    return json.loads(p.read_text()), p


def _articles(doc):
    out = []
    for tk, v in (doc.get("tickers") or {}).items():
        arts = v.get("articles", v) if isinstance(v, dict) else v
        for a in arts or []:
            aid = hashlib.sha1((a.get("link") or a.get("title") or "").encode()).hexdigest()[:12]
            out.append({"id": aid, "ticker": tk.replace(".US", ""), "title": a.get("title"), "date": (a.get("date") or "")[:10],
                        "link": a.get("link"), "source": a.get("source"), "body": a.get("content_excerpt") or "",
                        "symbols": [s.replace(".US", "") for s in _as_list(a.get("symbols"))], "tags": _as_list(a.get("tags"))})
    # 同一篇文章掛多檔 → 只標一次，affected 由標註器決定
    seen, uniq = set(), []
    for a in out:
        if a["id"] in seen:
            continue
        seen.add(a["id"]); uniq.append(a)
    return uniq


def _as_list(x):
    if isinstance(x, list):
        return x
    if isinstance(x, str):
        try:
            return json.loads(x.replace("'", '"'))
        except Exception:  # noqa: BLE001
            return []
    return []


def _existing_ids():
    if not LEDGER.exists():
        return set()
    ids = set()
    for line in LEDGER.read_text().splitlines():
        try:
            ids.add((json.loads(line)["id"], json.loads(line)["labeler"]))
        except Exception:  # noqa: BLE001
            continue
    return ids


# ── labelers ────────────────────────────────────────────────────────────────
def label_claude_haiku(batch):
    prompt = ("你是財經新聞事件標註器。對下列每篇文章輸出一個 JSON 物件，全部放在一個 JSON 陣列裡，**只輸出 JSON，不要任何解釋**。\n"
              f"Schema：{json.dumps(SCHEMA, ensure_ascii=False)}\n"
              "規則：event_type 只能用列表內的值；quant_statement 必須逐字引用原文（不可改寫、不可翻譯），沒有數字就 null；"
              "純評論/選股清單/榜單文章 is_commentary=true 且 event_type=commentary_only；direction 以文章主要標的為準。\n\n文章：\n")
    for a in batch:
        prompt += f"\n---\nid: {a['id']}\nticker: {a['ticker']} | symbols: {a['symbols']}\ntitle: {a['title']}\nbody: {a['body'][:2500]}\n"
    r = subprocess.run(["claude", "-p", "--model", "haiku", "--output-format", "json"], input=prompt,
                       capture_output=True, text=True, timeout=300)
    try:
        d = json.loads(r.stdout)
        txt = d.get("result") or ""
        cost = d.get("total_cost_usd")
    except Exception:  # noqa: BLE001
        txt, cost = r.stdout, None
    m = re.search(r"\[.*\]", txt, re.S)
    if not m:
        raise RuntimeError(f"labeler returned no JSON array: {txt[:200]}")
    items = json.loads(m.group(0))
    return items, cost


def label_jev(batch):
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY 未設（.env）；Jev 為早期存取，key 到後補 adapter")
    # TODO(jev): POST https://api.typesafe.ai/v1/systemone，每篇一個 request：questions = event_type(Choice) / direction(Choice) /
    #   horizon(Choice) / is_commentary(Noul) / confidence 由回傳 probability 取；quant_statement 由 Choice 無法產生 → 用 regex 抓帶數字句作 fallback。
    raise NotImplementedError("Jev adapter：等 early access key，實作見 TODO(jev)")


LABELERS = {"claude-haiku": label_claude_haiku, "jev": label_jev}


# ── run / score / stats / compare ───────────────────────────────────────────
def cmd_run(argv):
    day = _arg(argv, "--date") or date.today().isoformat()
    labeler = _arg(argv, "--labeler") or "claude-haiku"
    limit = int(_arg(argv, "--limit") or 0)
    doc, p = _load_day(day)
    arts = [a for a in _articles(doc) if a["body"]]
    if limit:
        arts = arts[:limit]
    done = _existing_ids()
    todo = [a for a in arts if (a["id"], labeler) not in done]
    print(f"📰 {day}: {len(arts)} 篇有內文，{len(todo)} 篇待標（labeler={labeler}）")
    if not todo:
        return 0
    px = _closes({a["ticker"] for a in todo} | {s for a in todo for s in a["symbols"]}, day)
    n_ok, total_cost = 0, 0.0
    with open(LEDGER, "a") as fh:
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            try:
                items, cost = LABELERS[labeler](batch)
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠️ batch {i//BATCH+1} 失敗：{str(e)[:160]}"); continue
            total_cost += cost or 0
            by_id = {it.get("id"): it for it in items if isinstance(it, dict)}
            for a in batch:
                it = by_id.get(a["id"])
                if not it:
                    continue
                affected = [s for s in (it.get("affected") or [a["ticker"]]) if s in a["symbols"] or s == a["ticker"]] or [a["ticker"]]
                rec = {"id": a["id"], "date": day, "article_date": a["date"], "labeler": labeler, "labeled_at": datetime.now().isoformat(timespec="minutes"),
                       "title": a["title"], "link": a["link"], "source": a["source"], "primary": a["ticker"], "affected": affected,
                       "event_type": it.get("event_type") if it.get("event_type") in EVENT_TYPES else "commentary_only",
                       "direction": int(it.get("direction") or 0), "horizon": it.get("horizon"), "quant_statement": it.get("quant_statement"),
                       "is_commentary": bool(it.get("is_commentary")), "confidence": float(it.get("confidence") or 0),
                       "price_t0": {s: px.get(s) for s in affected}, "r20": None, "r60": None, "scored_at": None}
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); n_ok += 1
            print(f"  ✓ batch {i//BATCH+1}: {len(batch)} 篇，累計成本 ${total_cost:.3f}")
    print(f"✅ 寫入 {n_ok} 筆 → {LEDGER.name}｜成本 ${total_cost:.3f}")
    return 0


def _closes(syms, day):
    try:
        import yfinance as yf
        syms = sorted(s for s in syms if s and re.match(r"^[A-Z.\-]{1,6}$", s))
        end = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        px = yf.download(syms, start=(date.fromisoformat(day) - timedelta(days=6)).isoformat(), end=end, auto_adjust=True, progress=False)["Close"]
        if hasattr(px, "columns"):
            last = px.dropna(how="all").iloc[-1]
            return {s: round(float(last[s]), 2) for s in syms if s in last and last[s] == last[s]}
        return {}
    except Exception:  # noqa: BLE001
        return {}


def cmd_score(argv):
    if not LEDGER.exists():
        print("no ledger"); return 0
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    today = date.today()
    need = [r for r in rows if (r.get("r20") is None and (today - date.fromisoformat(r["date"])).days >= 30)
            or (r.get("r60") is None and (today - date.fromisoformat(r["date"])).days >= 88)]
    if not need:
        print("nothing due"); return 0
    import yfinance as yf
    syms = sorted({s for r in need for s in r["affected"]} | {"SPY"})
    start = min(r["date"] for r in need)
    px = yf.download(syms, start=start, auto_adjust=True, progress=False)["Close"].dropna(how="all")
    def ret(s, d0, n):
        c = px[s].dropna() if s in px else None
        if c is None or c.empty:
            return None
        i = c.index.searchsorted(d0)
        if i + n >= len(c):
            return None
        return round(float(c.iloc[i + n] / c.iloc[i] - 1) * 100, 2)
    for r in need:
        d0 = r["date"]
        for key, n in (("r20", 20), ("r60", 60)):
            if r.get(key) is None and (today - date.fromisoformat(d0)).days >= (30 if n == 20 else 88):
                vals = {s: ret(s, d0, n) for s in r["affected"]}
                spy = ret("SPY", d0, n)
                r[key] = {"raw": vals, "spy": spy, "alpha": {s: (round(v - spy, 2) if (v is not None and spy is not None) else None) for s, v in vals.items()}}
                r["scored_at"] = today.isoformat()
    LEDGER.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    print(f"scored {len(need)} rows")
    return 0


def cmd_stats(argv):
    min_n = int(_arg(argv, "--min-n") or 8)
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()] if LEDGER.exists() else []
    print(f"事件帳：{len(rows)} 筆｜已 score r20：{sum(1 for r in rows if r.get('r20'))}｜commentary 佔比 {sum(1 for r in rows if r.get('is_commentary'))/max(len(rows),1):.0%}")
    from collections import defaultdict
    g = defaultdict(list)
    for r in rows:
        if not r.get("r20") or r.get("is_commentary"):
            continue
        for s, a in (r["r20"].get("alpha") or {}).items():
            if a is not None:
                g[(r["event_type"], r["direction"])].append(a)
    print(f"\n{'event_type':28} {'dir':>3} {'n':>4} {'20日α均':>8} {'中位':>7} {'正%':>5}")
    for (et, d), v in sorted(g.items(), key=lambda kv: -len(kv[1])):
        if len(v) < min_n:
            continue
        v2 = sorted(v); print(f"{et:28} {d:>3} {len(v):>4} {sum(v)/len(v):>8.2f} {v2[len(v2)//2]:>7.2f} {sum(1 for x in v if x>0)/len(v):>5.0%}")
    return 0


def cmd_compare(argv):
    day = _arg(argv, "--date")
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()] if LEDGER.exists() else []
    by = {}
    for r in rows:
        if day and r["date"] != day:
            continue
        by.setdefault(r["id"], {})[r["labeler"]] = r
    both = [v for v in by.values() if "claude-haiku" in v and "jev" in v]
    if not both:
        print("尚無同一批文章的兩種標註"); return 0
    agree_et = sum(1 for v in both if v["claude-haiku"]["event_type"] == v["jev"]["event_type"])
    agree_dir = sum(1 for v in both if v["claude-haiku"]["direction"] == v["jev"]["direction"])
    print(f"n={len(both)}｜event_type 一致 {agree_et/len(both):.0%}｜direction 一致 {agree_dir/len(both):.0%}")
    return 0


def _arg(argv, k):
    return argv[argv.index(k) + 1] if k in argv and argv.index(k) + 1 < len(argv) else None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    sys.exit({"run": cmd_run, "score": cmd_score, "stats": cmd_stats, "compare": cmd_compare}.get(cmd, cmd_run)(sys.argv[2:]))
