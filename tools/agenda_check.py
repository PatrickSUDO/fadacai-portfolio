#!/usr/bin/env python3
"""agenda_check.py — 「講話的人手上有沒有部位」檢查（2026-09-16，用戶對 Bill Ackman 的觀察）。

來源白名單裡 `bias == "talks-book"` 的人（目前 Pershing Square / @BillAckman），公開講「很可怕」的總經觀點時
通常已持有相關部位——觀點方向 ≈ 部位方向，不是預測。本工具把最新 13F-HR 前 N 大持倉抓下來快取，
briefing / source_credit 引用其主張時附一句「13F 同向 / 無關」，命中率分兩組看：同向命中不算預測力，算 agenda 揭露。

資料：SEC EDGAR submissions JSON（CIK）→ 最新 13F-HR → infotable XML → 依市值排序。TTL 7 天（13F 季更，45 天延遲）。
Usage:
  python3 tools/agenda_check.py                    # 刷新所有 talks-book 來源的 13F 快取（TTL 內跳過）
  python3 tools/agenda_check.py --force
  python3 tools/agenda_check.py --claim "rates will stay higher, long bonds are dangerous" --source billackman
                                                   # 回傳該主張是否與持倉同向（關鍵字/ticker 粗配，display-only）
輸出：briefing-out/cache/agenda-13f.json  {source_id: {cik, period, filed, top: [{issuer, ticker?, value_usd, pct}], asof}}
"""
import json, re, sys, time
from datetime import date, datetime
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "research" / "source-config.json"
OUT = ROOT / "briefing-out" / "cache" / "agenda-13f.json"
UA = {"User-Agent": "fadacai-portfolio research (contact: patricksuph@gmail.com)"}
TTL_DAYS, TOP_N = 7, 12


def _get(url, retries=3):
    for i in range(retries):
        try:
            with urlopen(Request(url, headers=UA), timeout=30) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def latest_13f(cik: str):
    cik10 = cik.zfill(10)
    subs = json.loads(_get(f"https://data.sec.gov/submissions/CIK{cik10}.json"))
    rec = subs["filings"]["recent"]
    # 13F-NT = 該季申請保密處理（confidential treatment），持倉表會落後一季、且幾乎一定有新建部位不想被看到——本身就是訊號
    nt = next(({"filed": fd, "period": rd} for f, fd, rd in zip(rec["form"], rec["filingDate"], rec["reportDate"]) if f == "13F-NT"), None)
    for form, acc, filed, rdate, doc in zip(rec["form"], rec["accessionNumber"], rec["filingDate"], rec["reportDate"], rec["primaryDocument"]):
        if form in ("13F-HR", "13F-HR/A"):
            if nt and nt["period"] > rdate:
                confidential = nt
            else:
                confidential = None
            acc_nodash = acc.replace("-", "")
            base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}/"
            idx = _get(base).decode("utf-8", "ignore")
            xmls = re.findall(r'href="([^"]+\.xml)"', idx)
            info = next((x for x in xmls if "infotable" in x.lower() or "form13f" in x.lower() and "primary" not in x.lower()), None)
            if not info:
                info = next((x for x in xmls if "primary_doc" not in x.lower()), None)
            if not info:
                continue
            url = info if info.startswith("http") else ("https://www.sec.gov" + info if info.startswith("/") else base + info)
            return {"accession": acc, "filed": filed, "period": rdate, "infotable_url": url, "xml": _get(url), "confidential_nt": confidential}
    return None


def parse_infotable(xml_bytes):
    root = ET.fromstring(xml_bytes)
    ns = {"n": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    def f(el, name):
        x = el.find(f"n:{name}", ns) if ns else el.find(name)
        return (x.text or "").strip() if x is not None else ""
    rows = []
    for it in (root.findall("n:infoTable", ns) if ns else root.findall("infoTable")):
        try:
            val = float(f(it, "value").replace(",", "") or 0)
        except ValueError:
            val = 0.0
        rows.append({"issuer": f(it, "nameOfIssuer"), "class": f(it, "titleOfClass"), "cusip": f(it, "cusip"),
                     "put_call": (it.find("n:putCall", ns).text if (ns and it.find("n:putCall", ns) is not None) else ""),
                     "value_usd": val})
    # 13F value 單位：2023 起為美元（舊檔為千元）；用總額量級判斷
    tot = sum(r["value_usd"] for r in rows) or 1.0
    if tot < 5e8:  # 太小 → 千元單位
        for r in rows:
            r["value_usd"] *= 1000
        tot *= 1000
    agg = {}
    for r in rows:
        k = (r["issuer"], r["put_call"])
        agg.setdefault(k, {"issuer": r["issuer"], "put_call": r["put_call"], "value_usd": 0.0})
        agg[k]["value_usd"] += r["value_usd"]
    top = sorted(agg.values(), key=lambda r: -r["value_usd"])[:TOP_N]
    for r in top:
        r["pct"] = round(r["value_usd"] / tot * 100, 1)
        r["value_usd"] = round(r["value_usd"])
    return {"total_usd": round(tot), "n_positions": len(agg), "top": top}


def refresh(force=False):
    cfg = json.loads(CFG.read_text()) if CFG.exists() else {"sources": []}
    cache = json.loads(OUT.read_text()) if OUT.exists() else {}
    today = date.today().isoformat()
    for s in cfg.get("sources", []):
        if s.get("bias") != "talks-book" or not (s.get("agenda_check") or {}).get("sec_cik"):
            continue
        sid, cik = s["id"], s["agenda_check"]["sec_cik"]
        prev = cache.get(sid)
        if prev and not force and (date.today() - date.fromisoformat(prev.get("asof", "2000-01-01"))).days < TTL_DAYS:
            continue
        try:
            f13 = latest_13f(cik)
            if not f13:
                cache[sid] = {"cik": cik, "asof": today, "error": "no 13F-HR found"}; continue
            parsed = parse_infotable(f13["xml"])
            cache[sid] = {"cik": cik, "handle": s.get("handle"), "asof": today, "filed": f13["filed"], "period": f13["period"],
                          "accession": f13["accession"], "confidential_nt": f13.get("confidential_nt"), **parsed}
        except Exception as e:  # noqa: BLE001
            cache[sid] = {"cik": cik, "asof": today, "error": str(e)[:200]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    return cache


# 粗配：主張文字裡的方向詞 × 持倉類型（display-only；細判交給 briefing 的人話）
BEAR_WORDS = ("crash", "collapse", "crisis", "dangerous", "bubble", "recession", "崩", "危機", "泡沫", "衰退", "可怕")
BULL_WORDS = ("buy", "opportunity", "cheap", "undervalued", "long", "買", "低估", "機會")


def match_claim(text: str, source_id: str, cache: dict):
    c = cache.get(source_id) or {}
    top = c.get("top") or []
    t = text.lower()
    names = [r["issuer"] for r in top if any(w in t for w in re.findall(r"[a-z]{4,}", r["issuer"].lower()))]
    direction = "bear" if any(w in t for w in BEAR_WORDS) else ("bull" if any(w in t for w in BULL_WORDS) else "n/a")
    puts = [r["issuer"] for r in top if r.get("put_call")]
    return {"source": source_id, "13f_period": c.get("period"), "filed": c.get("filed"), "direction_words": direction,
            "mentions_holding": names, "has_puts_or_hedges": puts,
            "verdict": ("同向：點名的就是持倉" if names else ("可能同向：看空且 13F 有 put/避險部位" if (direction == "bear" and puts) else "無關/未點名")),
            "rule": "同向 ≠ 預測力；引用時標 agenda，不當獨立訊號（source-config bias=talks-book）"}


def main(argv):
    force = "--force" in argv
    cache = refresh(force=force)
    if "--claim" in argv:
        i = argv.index("--claim"); text = argv[i + 1]
        sid = argv[argv.index("--source") + 1] if "--source" in argv else "billackman"
        print(json.dumps(match_claim(text, sid, cache), ensure_ascii=False, indent=1)); return 0
    for sid, c in cache.items():
        if c.get("error"):
            print(f"⚠️ {sid}: {c['error']}"); continue
        print(f"📄 {sid} (@{c.get('handle')}) 13F {c['period']} filed {c['filed']}｜{c['n_positions']} 檔 ${c['total_usd']/1e9:.1f}B")
        if c.get("confidential_nt"):
            nt = c["confidential_nt"]
            print(f"   🔒 最新一季 {nt['period']} 只交 13F-NT（{nt['filed']} 申請保密）→ 上表落後一季，且幾乎確定有新建部位不想被看到；他這段期間的公開言論更該對照")
        for r in c["top"][:10]:
            print(f"   {r['pct']:5.1f}%  {r['issuer']}{'  [' + r['put_call'] + ']' if r.get('put_call') else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
