#!/usr/bin/env python3
"""fetch_feeds.py — 追蹤作者的新文章（RSS／Atom；免費、不用 API key、只用標準函式庫）

2026-11-20 用戶「幫我定期追蹤這個作者，還有其他類似的分析師作者」（Beth Kindig 的 AMD 文章）。

為什麼：`research/source-config.json` 裡的 Seeking Alpha／Substack 作者從 8 月起就在名單上，但 platform 是 manual 或
沒有對應的抓取器，X 抓取又在 2026-10-30 停用——實際上沒有任何程式在追。這支只讀每個來源的 `feed` 欄位（RSS 網址），
把近幾天的新文章寫進 cache，briefing 當「閱讀清單」陳列。

紀律（訊號層凍結 2026-10-30 仍有效）：display-only。這裡只有標題、連結、代號，不抽主張、不進任何 gate、不單獨觸發加減碼。
要計分的主張仍走 `source_credit.py add-claim`（讀完文章的人或 briefing 登）。

輸出 briefing-out/cache/source-feeds.json：
  items[] = {source_id, handle, tier, kind, title, url, published, first_seen, tickers[], mine, summary, summary_points[], has_body}
  mine = 文章提到持倉／撿回與觀察名單裡的代號。first_seen = 本工具第一次看到這篇的日期（美東），briefing 用它判「新」。

Seeking Alpha 全文（2026-11-20 用戶「我不是讓你能登入 seeking alpha…我有付費帳號」）：用戶的付費帳號登入（.env SA_COOKIE，
  與 fetch_sa_quant.py 同一套）可從文章 API 取全文。只替「今天第一次看到、且 mine」的 SA 文章抓，一次最多 5 篇，
  全文存 briefing-out/cache/source-articles.json（私有、不進 repo、不上報告站，留 30 天），item 標 has_body 並附作者自寫摘要。
  沒有 cookie 就略過；被回 403 就停、不重試、不繞過機器人防護。全文只供自己讀與摘要，任何輸出不得貼原文段落。

Usage:
  python3 tools/fetch_feeds.py                 # 抓（6 小時內抓過就跳過）
  python3 tools/fetch_feeds.py --force
  python3 tools/fetch_feeds.py list [--days 3] [--mine]
  python3 tools/fetch_feeds.py read <Seeking Alpha 文章網址或編號>   # 單篇全文存進 source-articles.json（互動時「幫我看這篇」）
  python3 tools/fetch_feeds.py digest [--done]   # 週報：每週第一個交易日 due=true，給本週與持倉／候補有關的文章（依代號分組）

陳列節奏（2026-11-20 用戶「我沒那麼多時間天天看」）：每天默默收，平日 briefing 不提；每週只講一次，而且只講例外
  （同一檔 ≥2 位作者同方向、或作者方向與我們對持倉的處置相反），沒有就一行帶過。判斷在 briefing 技能，這裡只給 due 與分組。
  python3 tools/fetch_feeds.py selftest
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
CONFIG = ROOT / "research" / "source-config.json"
SEEN = ROOT / "research" / "source-feeds-seen.json"
POS_STATE = ROOT / "research" / "position-state.json"
ALERTS = ROOT / "research" / "price-alerts.json"
OUT = ROOT / "briefing-out" / "cache" / "source-feeds.json"
ARTICLES = ROOT / "briefing-out" / "cache" / "source-articles.json"
ET_TZ = ZoneInfo("America/New_York")

TTL_HOURS = 6
LOOKBACK_DAYS = 10
MAX_PER_SOURCE = 8
SEEN_KEEP_DAYS = 120
TIMEOUT = 20
MAX_SA_ARTICLES = 5
ARTICLE_KEEP_DAYS = 30
ARTICLE_MAX_CHARS = 24000
SA_ARTICLE_RE = re.compile(r"seekingalpha\.com/article/(\d+)")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
# 標題裡常用公司名而不是代號；只收持倉／候補常見的名字，其餘靠 feed 自帶的代號標籤
ALIASES = {
    "nvidia": "NVDA", "amd": "AMD", "advanced micro": "AMD", "broadcom": "AVGO", "micron": "MU", "palantir": "PLTR",
    "crowdstrike": "CRWD", "arista": "ANET", "applied materials": "AMAT", "celestica": "CLS", "cloudflare": "NET",
    "synopsys": "SNPS", "twilio": "TWLO", "salesforce": "CRM", "credo": "CRDO", "anthropic": "ANT", "lam research": "LRCX",
    "lumentum": "LITE", "datadog": "DDOG", "fastly": "FSLY", "microsoft": "MSFT", "amazon": "AMZN", "alphabet": "GOOGL",
    "google": "GOOGL", "meta platforms": "META", "tsmc": "TSM", "taiwan semiconductor": "TSM", "spacex": "SPCX",
    "asml": "ASML", "marvell": "MRVL", "oracle": "ORCL", "sandisk": "SNDK", "bloom energy": "BE", "mongodb": "MDB",
}
TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
TAG_RE = re.compile(r"<[^>]+>")


def jload(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def now_et() -> datetime:
    return datetime.now(ET_TZ)


def watch_universe() -> set:
    """持倉 ∪ 價格警報上的代號（撿回與觀察名單都在警報裡）。"""
    out = set()
    pos = jload(POS_STATE, {}).get("positions", [])
    out |= {p.get("symbol") for p in pos} if isinstance(pos, list) else set(pos)
    out |= {a.get("symbol") for a in jload(ALERTS, {}).get("alerts", [])}
    return {t for t in out if t and TICKER_RE.match(t)}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def clean(s: str | None, n: int = 400) -> str:
    t = html.unescape(TAG_RE.sub(" ", s or ""))
    return " ".join(t.split())[:n]


def tickers_of(title: str, symbols: list[str], universe: set) -> list[str]:
    found = [s for s in symbols if TICKER_RE.match(s)]           # feed 自帶的代號標籤（SA）；NVDA:CA 這類不收
    found += re.findall(r"\$([A-Z]{1,5})\b", title)
    found += [t for t in re.findall(r"\b[A-Z]{2,5}\b", title) if t in universe]
    low = title.lower()
    found += [tk for name, tk in ALIASES.items() if re.search(rf"\b{re.escape(name)}\b", low)]
    return sorted(set(found))


def parse_feed(xml_text: str) -> list[dict]:
    """RSS 2.0（channel/item）與 Atom（entry）都吃。回 [{title, url, published(datetime|None), symbols[], summary, guid}]"""
    root = ET.fromstring(xml_text)
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        d = {"title": "", "url": "", "published": None, "symbols": [], "summary": "", "guid": ""}
        for c in el:
            name = local(c.tag)
            if name == "title":
                d["title"] = clean(c.text, 200)
            elif name == "link":
                d["url"] = d["url"] or (c.get("href") or (c.text or "")).strip()
            elif name in ("pubDate", "published", "updated", "date"):
                d["published"] = d["published"] or parse_date(c.text)
            elif name in ("guid", "id"):
                d["guid"] = (c.text or "").strip()
            elif name == "category" and c.get("type") == "symbol":
                d["symbols"].append((c.text or "").strip().upper())
            elif name in ("description", "summary") and not d["summary"]:
                d["summary"] = clean(c.text)
        d["url"] = d["url"].split("?source=")[0]
        if d["title"] and d["url"]:
            items.append(d)
    return items


def http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", errors="replace")


class SABlocked(Exception):
    pass


def sa_article(article_id: str) -> dict | None:
    """用戶付費帳號登入取 Seeking Alpha 單篇全文。沒有 cookie → None；403 → SABlocked（呼叫端停止，不重試）。"""
    import os
    import urllib.error
    import fetch_sa_quant as sa
    sa.load_env()
    cookie = os.environ.get("SA_COOKIE", "").strip()
    if not cookie:
        return None
    try:
        a = sa.sa_get(f"articles/{article_id}", cookie)["data"]["attributes"]
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise SABlocked(f"Seeking Alpha 回 403（文章 {article_id}）") from e
        return None
    text = clean(a.get("content"), ARTICLE_MAX_CHARS)
    return {"id": article_id, "title": clean(a.get("title"), 200), "summary_points": [clean(x, 220) for x in (a.get("summary") or []) if x][:5],
            "text": text, "locked": bool(a.get("isMpwLocked") or a.get("isPaywalled")) or len(text) < 1500}


def save_article(url: str, art: dict, source_id: str | None, published: str | None) -> None:
    store = jload(ARTICLES, {})
    store[url] = {**art, "source_id": source_id, "published": published, "fetched": now_et().date().isoformat()}
    old = (now_et().date() - timedelta(days=ARTICLE_KEEP_DAYS)).isoformat()
    store = {k: v for k, v in store.items() if (v.get("fetched") or "") >= old}
    ARTICLES.parent.mkdir(parents=True, exist_ok=True)
    ARTICLES.write_text(json.dumps(store, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def cmd_read(ref: str) -> int:
    m = SA_ARTICLE_RE.search(ref) or re.fullmatch(r"(\d{5,9})", ref.strip())
    if not m:
        print("只支援 Seeking Alpha 文章網址或編號")
        return 1
    try:
        art = sa_article(m.group(1))
    except SABlocked as e:
        print(f"⚠️ {e}——不重試。請改用瀏覽器登入狀態讀，或把全文貼上來")
        return 2
    if not art:
        print("沒有 SA_COOKIE 或讀不到這篇")
        return 1
    url = ref.split("?")[0] if ref.startswith("http") else f"https://seekingalpha.com/article/{m.group(1)}"
    save_article(url, art, None, None)
    print(json.dumps({"saved": str(ARTICLES.relative_to(ROOT)), "key": url, "title": art["title"], "chars": len(art["text"]),
                      "locked": art["locked"], "summary_points": art["summary_points"]}, ensure_ascii=False, indent=1))
    return 0


def fetch(force: bool) -> int:
    if not force and OUT.exists() and time.time() - OUT.stat().st_mtime < TTL_HOURS * 3600:
        print(json.dumps({"action": "skipped", "why": f"cache 在 {TTL_HOURS} 小時內"}, ensure_ascii=False))
        return 0
    sources = [s for s in jload(CONFIG, {}).get("sources", []) if s.get("enabled", True) and s.get("feed")]
    universe, today = watch_universe(), now_et().date().isoformat()
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    seen = jload(SEEN, {})
    first_run = not seen                        # 第一次跑：既有文章不算「新」，只有今天發的才算
    items, errors, ok = [], [], 0
    for s in sources:
        try:
            parsed = parse_feed(http_get(s["feed"]))
            ok += 1
        except Exception as e:  # noqa: BLE001
            errors.append({"id": s["id"], "error": str(e)[:120]})
            continue
        kept = 0
        for it in sorted(parsed, key=lambda x: x["published"] or cutoff, reverse=True):
            if kept >= MAX_PER_SOURCE or (it["published"] and it["published"] < cutoff):
                continue
            key = f"{s['id']}|{it['guid'] or it['url']}"
            pub = it["published"].astimezone(ET_TZ).date().isoformat() if it["published"] else None
            if key not in seen:
                seen[key] = pub if (first_run and pub and pub < today) else today
            tks = tickers_of(it["title"], it["symbols"], universe)
            items.append({"source_id": s["id"], "handle": s.get("handle"), "tier": s.get("tier"), "kind": s.get("kind"),
                          "title": it["title"], "url": it["url"], "published": pub, "first_seen": seen[key],
                          "tickers": tks, "mine": bool(set(tks) & universe), "summary": it["summary"]})
            kept += 1
    have = jload(ARTICLES, {})
    n_sa = 0
    for it in items:
        m = SA_ARTICLE_RE.search(it["url"])
        if not m:
            continue
        if it["url"] in have:
            it.update(has_body=not have[it["url"]].get("locked"), summary_points=have[it["url"]].get("summary_points") or [])
            continue
        if not (it["mine"] and it["first_seen"] == today and n_sa < MAX_SA_ARTICLES):
            continue
        try:
            art = sa_article(m.group(1))
        except SABlocked as e:
            errors.append({"id": "seekingalpha-fulltext", "error": f"{e}；本輪停止抓全文，不重試"})
            break
        n_sa += 1
        if art:
            save_article(it["url"], art, it["source_id"], it["published"])
            it.update(has_body=not art["locked"], summary_points=art["summary_points"])
        time.sleep(2)
    old = (now_et().date() - timedelta(days=SEEN_KEEP_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if (v or today) >= old}
    items.sort(key=lambda x: (x["first_seen"] or "", x["published"] or ""), reverse=True)
    out = {"generated_at": now_et().isoformat(timespec="seconds"), "status": "ok" if not errors else ("partial" if ok else "failed"),
           "lookback_days": LOOKBACK_DAYS, "sources_total": len(sources), "sources_ok": ok, "errors": errors,
           "new_today": sum(1 for i in items if i["first_seen"] == today),
           "new_today_mine": sum(1 for i in items if i["first_seen"] == today and i["mine"]),
           "bodies_today": sum(1 for i in items if i["first_seen"] == today and i.get("has_body")),
           "note": "display-only 閱讀清單，不是訊號。has_body 的全文在 source-articles.json（私有）；引用主張要 source_credit.py add-claim；輸出不得貼原文段落",
           "items": items}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    SEEN.write_text(json.dumps(seen, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("status", "sources_total", "sources_ok", "new_today", "new_today_mine", "bodies_today", "errors")}, ensure_ascii=False))
    return 0


def cmd_list(days: int, mine: bool) -> int:
    d = jload(OUT, None)
    if not d:
        print("尚無 cache，先跑 python3 tools/fetch_feeds.py")
        return 1
    since = (now_et().date() - timedelta(days=days)).isoformat()
    rows = [i for i in d["items"] if (i["first_seen"] or "") >= since and (i["mine"] or not mine)]
    print(f"追蹤作者新文章（{d['generated_at']}；近 {days} 天；{d['sources_ok']}/{d['sources_total']} 個來源讀到）")
    for i in rows:
        tk = "、".join(i["tickers"]) or "—"
        print(f"  {i['first_seen']} {'★' if i['mine'] else ' '}{'📄' if i.get('has_body') else '  '} [{i['handle']}] {i['title']}（{tk}）\n      {i['url']}")
        for pt in i.get("summary_points") or []:
            print(f"        · {pt}")
    for e in d.get("errors", []):
        print(f"  ⚠️ {e['id']} 讀取失敗：{e['error']}")
    return 0


def cmd_digest(done: bool) -> int:
    seen, today = jload(SEEN, {}), now_et().date()
    if done:
        seen["__last_digest__"] = today.isoformat()
        SEEN.write_text(json.dumps(seen, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
        print(json.dumps({"action": "marked", "last_digest": today.isoformat()}, ensure_ascii=False))
        return 0
    last = seen.get("__last_digest__")
    monday = (today - timedelta(days=today.weekday())).isoformat()
    if today.weekday() >= 5 or (last and last >= monday):       # 週末不出；本週出過就不再出
        print(json.dumps({"due": False, "last_digest": last}, ensure_ascii=False))
        return 0
    since = max(last or "", (today - timedelta(days=LOOKBACK_DAYS)).isoformat())
    pos = jload(POS_STATE, {}).get("positions", [])
    held = {p.get("symbol") for p in pos} if isinstance(pos, list) else set(pos)
    universe = watch_universe()
    rows = [i for i in (jload(OUT, {}) or {}).get("items", []) if i.get("mine") and (i.get("first_seen") or "") >= since]
    by: dict[str, list] = {}
    for i in rows:
        for t in i["tickers"]:
            if t in universe:
                by.setdefault(t, []).append({"author": i["handle"], "source_id": i["source_id"], "title": i["title"], "url": i["url"],
                                             "date": i["first_seen"], "has_body": bool(i.get("has_body")),
                                             "summary_points": i.get("summary_points") or []})
    order = sorted(by, key=lambda t: (t not in held, -len({a["source_id"] for a in by[t]}), t))
    print(json.dumps({"due": True, "since": since, "n_articles": len(rows), "n_with_body": sum(1 for i in rows if i.get("has_body")),
                      "held": sorted(t for t in by if t in held),
                      "multi_author": [t for t in order if len({a["source_id"] for a in by[t]}) >= 2],
                      "by_ticker": {t: by[t] for t in order},
                      "after": "寫完週報後跑 python3 tools/fetch_feeds.py digest --done"}, ensure_ascii=False, indent=1))
    return 0


def selftest() -> int:
    rss = """<rss><channel><item><title>AMD Stock: Two-Catalyst Punch</title>
      <link>https://seekingalpha.com/article/1-amd?source=feed_author_x</link><guid isPermaLink="false">1</guid>
      <pubDate>Fri, 20 Nov 2026 09:00:42 -0500</pubDate>
      <category type="symbol">NVDA</category><category type="symbol">NVDA:CA</category><category type="symbol">AMD</category>
      <category type="author">Beth Kindig</category></item></channel></rss>"""
    it = parse_feed(rss)[0]
    assert it["url"] == "https://seekingalpha.com/article/1-amd" and it["guid"] == "1", it
    assert it["published"].astimezone(ET_TZ).date().isoformat() == "2026-11-20", it
    assert tickers_of(it["title"], it["symbols"], {"AMD"}) == ["AMD", "NVDA"], tickers_of(it["title"], it["symbols"], {"AMD"})
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Why Micron and $SNDK matter</title>
      <link href="https://example.com/p/1"/><id>tag:1</id><updated>2026-11-19T12:00:00Z</updated>
      <summary>&lt;p&gt;HBM &amp;amp; NAND&lt;/p&gt;</summary></entry></feed>"""
    it = parse_feed(atom)[0]
    assert it["url"] == "https://example.com/p/1" and it["summary"] == "HBM & NAND", it
    assert tickers_of(it["title"], it["symbols"], {"MU"}) == ["MU", "SNDK"], tickers_of(it["title"], it["symbols"], {"MU"})
    assert tickers_of("The AI trade is NOT over", [], {"NVDA"}) == []        # 全大寫的普通字不當代號
    print("selftest ok")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="追蹤作者的新文章（RSS）")
    p.add_argument("cmd", nargs="?", default="fetch", choices=["fetch", "list", "read", "digest", "selftest"])
    p.add_argument("--done", action="store_true", help="digest 用：標記本週週報已出")
    p.add_argument("ref", nargs="?", default=None, help="read 用：Seeking Alpha 文章網址或編號")
    p.add_argument("--force", action="store_true")
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--mine", action="store_true", help="只列提到持倉／候補代號的")
    a = p.parse_args()
    if a.cmd == "selftest":
        return selftest()
    if a.cmd == "list":
        return cmd_list(a.days, a.mine)
    if a.cmd == "read":
        return cmd_read(a.ref or "")
    if a.cmd == "digest":
        return cmd_digest(a.done)
    return fetch(a.force)


if __name__ == "__main__":
    sys.exit(main())
