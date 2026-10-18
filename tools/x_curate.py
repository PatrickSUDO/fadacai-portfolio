#!/usr/bin/env python3
"""
x_curate.py — X (Twitter) 追蹤名單整理：API 拉名單 / 驗證帳號 / 備份 / 執行進度。

X API 自 2026-04 起不再對自助方案開放 follow / unfollow 寫入端點（僅 Enterprise），
所以本工具只負責「讀」與「記帳」；實際退追 / 追蹤由 Claude 透過已登入的 Chrome 操作，
每做一筆呼叫 `progress` 記錄，跨日可續跑。

資料目錄：research/x-curation/（整個 research/ 已 gitignore，追蹤圖屬私有資料）
  following-<handle>-<date>.json      某帳號的追蹤名單快照（含 description / metrics）
  candidates-resolved.json            候選帳號經 API 驗證後的原始資料
  plan.json                           keep / unfollow / follow 三張表（Claude 產出）
  progress.jsonl                      每筆已執行動作（append-only）

API 計費（pay-per-use，2026-10）：User read $0.010 / 每個回傳 user；following read 同價。
`--max-users` 是硬上限，超過就停，不會無限翻頁。

Usage:
  python3 tools/x_curate.py pull-following --handle mengkunghsieh [--max-users 1500]
  python3 tools/x_curate.py resolve @a @b ... [--out research/x-curation/candidates-resolved.json]
  python3 tools/x_curate.py progress --action unfollow|follow --handle foo [--note ...]
  python3 tools/x_curate.py recent @a @b -n 5   # 最近 5 則原創貼文（活躍度/內容驗證，$0.005/post）
  python3 tools/x_curate.py reconcile       # 以最新 API 快照重寫 progress（UI 回報不可信）
  python3 tools/x_curate.py report          # plan + 快照 → research/x-curation/report-<date>.md
  python3 tools/x_curate.py status          # plan vs progress 對帳
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "research" / "x-curation"
CONFIG_FILE = ROOT / "research" / "source-config.json"
X_API_BASE = "https://api.x.com/2"
TIMEOUT = 30
USER_FIELDS = ("id,name,username,description,created_at,location,url,verified,"
               "verified_type,protected,public_metrics,profile_image_url")
COST_PER_USER = 0.010

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_twitter import load_env  # noqa: E402


def _token() -> str:
    load_env()
    tok = os.environ.get("X_BEARER_TOKEN")
    if not tok:
        sys.exit("X_BEARER_TOKEN missing in .env")
    return tok


def _get(path: str, params: dict) -> dict:
    r = requests.get(f"{X_API_BASE}{path}", params=params,
                     headers={"Authorization": f"Bearer {_token()}"}, timeout=TIMEOUT)
    if r.status_code in (402, 429):
        sys.exit(f"HTTP {r.status_code} (billing/rate signal) — stop. body={r.text[:300]}")
    if r.status_code >= 400:
        sys.exit(f"HTTP {r.status_code}: {r.text[:500]}")
    return r.json()


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def _slim(u: dict) -> dict:
    pm = u.get("public_metrics") or {}
    return {
        "id": u.get("id"), "username": u.get("username"), "name": u.get("name"),
        "description": (u.get("description") or "").replace("\n", " ").strip(),
        "followers": pm.get("followers_count"), "following": pm.get("following_count"),
        "tweets": pm.get("tweet_count"), "created_at": (u.get("created_at") or "")[:10],
        "location": u.get("location"), "url": u.get("url"), "verified": u.get("verified"),
        "verified_type": u.get("verified_type"), "protected": u.get("protected"),
    }


def resolve_handle(handle: str) -> dict:
    body = _get(f"/users/by/username/{handle.lstrip('@')}", {"user.fields": USER_FIELDS})
    if not body.get("data"):
        sys.exit(f"user lookup failed: {body}")
    return body["data"]


def cmd_pull_following(a):
    handle = a.handle.lstrip("@")
    uid = a.user_id
    if not uid and CONFIG_FILE.exists():
        for s in json.loads(CONFIG_FILE.read_text()).get("sources", []):
            if (s.get("handle") or "").lower() == handle.lower() and s.get("x_user_id"):
                uid = s["x_user_id"]
    if not uid:
        uid = resolve_handle(handle)["id"]
    users, token, pages = [], None, 0
    while True:
        remaining = a.max_users - len(users)
        if remaining <= 0:
            print(f"⚠️ hit --max-users {a.max_users}; list truncated", file=sys.stderr)
            break
        params = {"max_results": max(1, min(1000, remaining)), "user.fields": USER_FIELDS}
        if token:
            params["pagination_token"] = token
        body = _get(f"/users/{uid}/{a.edge}", params)
        pages += 1
        users.extend(_slim(u) for u in body.get("data", []))
        token = (body.get("meta") or {}).get("next_token")
        print(f"page {pages}: +{len(body.get('data', []))} (total {len(users)})", file=sys.stderr)
        if not token:
            break
        time.sleep(1)
    out = a.out or OUT_DIR / f"{a.edge}-{handle}-{datetime.now().date()}.json"
    _write(Path(out), {"source_handle": handle, "source_user_id": uid, "edge": a.edge,
                       "pulled_at": datetime.now(tz=timezone.utc).isoformat(),
                       "count": len(users), "est_cost_usd": round(len(users) * COST_PER_USER, 2),
                       "users": users})
    print(f"wrote {out}: {len(users)} users, est ${len(users) * COST_PER_USER:.2f}")


def cmd_resolve(a):
    handles = [h.lstrip("@").strip() for h in a.handles if h.strip()]
    handles = list(dict.fromkeys(h.lower() for h in handles))
    found, errors = {}, []
    for i in range(0, len(handles), 100):
        chunk = handles[i:i + 100]
        body = _get("/users/by", {"usernames": ",".join(chunk), "user.fields": USER_FIELDS})
        for u in body.get("data", []):
            found[u["username"].lower()] = _slim(u)
        for e in body.get("errors", []):
            errors.append({"handle": e.get("value"), "title": e.get("title"), "detail": e.get("detail")})
        time.sleep(1)
    out = Path(a.out) if a.out else OUT_DIR / "candidates-resolved.json"
    prev = json.loads(out.read_text()).get("users", {}) if out.exists() and a.merge else {}
    prev.update(found)
    _write(out, {"resolved_at": datetime.now(tz=timezone.utc).isoformat(), "users": prev,
                 "errors": errors})
    print(f"resolved {len(found)}/{len(handles)}; {len(errors)} not found → {out}")
    for e in errors:
        print(f"  ✗ {e['handle']}: {e['title']}")


def cmd_progress(a):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now(tz=timezone.utc).isoformat(), "action": a.action,
           "handle": a.handle.lstrip("@"), "ok": not a.failed, "note": a.note}
    with (OUT_DIR / "progress.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False))


def _load_progress() -> list:
    p = OUT_DIR / "progress.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def cmd_status(a):
    plan_p = OUT_DIR / "plan.json"
    if not plan_p.exists():
        sys.exit("no plan.json yet")
    plan = json.loads(plan_p.read_text())
    done = {(r["action"], r["handle"].lower()) for r in _load_progress() if r.get("ok")}
    for action in ("unfollow", "follow"):
        queue = [x["username"] for x in plan.get(action, [])]
        left = [h for h in queue if (action, h.lower()) not in done]
        print(f"{action}: {len(queue) - len(left)}/{len(queue)} done; next: {left[:15]}")
    if a.json:
        print(json.dumps({act: [x["username"] for x in plan.get(act, [])
                                if (act, x["username"].lower()) not in done]
                          for act in ("unfollow", "follow")}))


def cmd_recent(a):
    """最近 N 則原創貼文（排除轉推/回覆）→ 驗活躍度與內容；$0.005/post。"""
    res_p = OUT_DIR / "candidates-resolved.json"
    ids = {}
    if res_p.exists():
        ids = {k: v["id"] for k, v in json.loads(res_p.read_text()).get("users", {}).items()}
    out = {}
    for h in a.handles:
        h = h.lstrip("@").lower()
        uid = ids.get(h) or resolve_handle(h)["id"]
        body = _get(f"/users/{uid}/tweets", {"max_results": max(5, min(100, a.n)), "exclude": "retweets,replies",
                                               "tweet.fields": "created_at,public_metrics,lang"})
        posts = [{"date": (t.get("created_at") or "")[:10], "lang": t.get("lang"),
                  "likes": (t.get("public_metrics") or {}).get("like_count"),
                  "text": (t.get("text") or "").replace("\n", " ")[:280]} for t in (body.get("data") or [])][: a.n]
        out[h] = {"posts": posts, "newest": posts[0]["date"] if posts else None,
                  "error": (body.get("errors") or [{}])[0].get("detail") if not posts else None}
        time.sleep(0.5)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def _latest_snapshot(handle: str) -> dict:
    files = sorted(OUT_DIR.glob(f"following-{handle}-*.json"), key=lambda f: f.stat().st_mtime)
    if not files:
        sys.exit(f"no following snapshot for {handle}; run pull-following first")
    return json.loads(files[-1].read_text())


def cmd_reconcile(a):
    """以最新 API 快照為準重寫 progress.jsonl（UI 點了沒生效的追蹤會被 X 限速吞掉，不能信 UI 回報）。"""
    plan = json.loads((OUT_DIR / "plan.json").read_text())
    snap = _latest_snapshot(a.handle)
    now = {u["username"].lower() for u in snap["users"]}
    base_p = OUT_DIR / f"following-{a.handle}-{plan['generated']}.json"
    base = {u["username"].lower() for u in json.loads(base_p.read_text())["users"]} if base_p.exists() else set()
    recs = []
    ts = snap.get("pulled_at")
    for x in plan.get("unfollow", []):
        h = x["username"].lower()
        recs.append({"ts": ts, "action": "unfollow", "handle": x["username"], "ok": h not in now,
                     "note": "reconciled vs API snapshot"})
    for key in ("follow_whitelist", "follow"):
        for x in plan.get(key, []):
            h = x["username"].lower()
            recs.append({"ts": ts, "action": "follow", "handle": x["username"], "ok": h in now,
                         "note": f"reconciled vs API snapshot ({key})"})
    (OUT_DIR / "progress.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    unexpected = sorted(now - base - {x["username"].lower() for k in ("follow_whitelist", "follow") for x in plan.get(k, [])})
    print(f"reconciled: following={len(now)} (base {len(base)}); "
          f"follow ok={sum(1 for r in recs if r['action']=='follow' and r['ok'])}/"
          f"{sum(1 for r in recs if r['action']=='follow')}, "
          f"unfollow ok={sum(1 for r in recs if r['action']=='unfollow' and r['ok'])}/"
          f"{sum(1 for r in recs if r['action']=='unfollow')}; not-in-plan follows={unexpected}")


def cmd_report(a):
    """plan.json + 最新快照 → 繁中 markdown 報告。"""
    plan = json.loads((OUT_DIR / "plan.json").read_text())
    snap = _latest_snapshot(a.handle)
    now = {u["username"].lower(): u for u in snap["users"]}
    L = [f"# X 追蹤名單整理報告（@{a.handle}，{plan['generated']}）", "",
         f"- 目前追蹤：{len(now)} 個帳號（快照 {snap.get('pulled_at','')[:16]} UTC）",
         f"- 退追 {sum(1 for x in plan['unfollow'] if x['username'].lower() not in now)}/{len(plan['unfollow'])}；"
         f"白名單補追 {sum(1 for x in plan['follow_whitelist'] if x['username'].lower() in now)}/{len(plan['follow_whitelist'])}；"
         f"新追蹤 {sum(1 for x in plan['follow'] if x['username'].lower() in now)}/{len(plan['follow'])}", ""]
    L += ["## 已退追", "", "| 帳號 | 原因 | 狀態 |", "|---|---|---|"]
    L += [f"| @{x['username']} | {x['reason']} | {'✅' if x['username'].lower() not in now else '❌ 仍在追蹤'} |" for x in plan["unfollow"]]
    L += ["", "## 白名單來源（source-config，原本一個都沒追）", "", "| 帳號 | 狀態 |", "|---|---|"]
    L += [f"| @{x['username']} | {'✅' if x['username'].lower() in now else '⏳ 待補（限速）'} |" for x in plan["follow_whitelist"]]
    L += ["", "## 新追蹤（評審 + 最近貼文查核通過）", "", "| 桶 | 帳號 | 級 | 日均貼文 | 為什麼 | 狀態 |", "|---|---|---|---|---|---|"]
    for x in plan["follow"]:
        st = "✅" if x["username"].lower() in now else "⏳ 待補（限速）"
        L.append(f"| {x['bucket']} | @{x['username']} | {x['tier']} | {x.get('posts_per_day')} | {(x.get('judge') or x.get('why') or '').replace('|','/')} | {st} |")
    L += ["", "## 評審選入但最近貼文查核不過（可自行加回）", "", "| 桶 | 帳號 | 最新貼文 | 查核意見 |", "|---|---|---|---|"]
    L += [f"| {x['bucket']} | @{x['username']} | {x['newest_post']} | {x['reason'].replace('|','/')} |" for x in plan["refuted"]]
    L += ["", "## 評審直接排除（節錄原因）", "", "| 桶 | 帳號 | 原因 |", "|---|---|---|"]
    L += [f"| {x['bucket']} | @{x['username']} | {x['reason'].replace('|','/')} |" for x in plan["excluded_by_judge"]]
    out = OUT_DIR / f"report-{plan['generated']}.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {out}")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("pull-following"); p.add_argument("--handle", required=True)
    p.add_argument("--user-id"); p.add_argument("--max-users", type=int, default=1500)
    p.add_argument("--edge", choices=["following", "followers"], default="following")
    p.add_argument("--out"); p.set_defaults(fn=cmd_pull_following)
    p = sp.add_parser("resolve"); p.add_argument("handles", nargs="+"); p.add_argument("--out")
    p.add_argument("--merge", action="store_true"); p.set_defaults(fn=cmd_resolve)
    p = sp.add_parser("progress"); p.add_argument("--action", required=True, choices=["unfollow", "follow"])
    p.add_argument("--handle", required=True); p.add_argument("--note", default="")
    p.add_argument("--failed", action="store_true"); p.set_defaults(fn=cmd_progress)
    p = sp.add_parser("recent"); p.add_argument("handles", nargs="+"); p.add_argument("-n", type=int, default=5)
    p.set_defaults(fn=cmd_recent)
    p = sp.add_parser("reconcile"); p.add_argument("--handle", default="patricksudo"); p.set_defaults(fn=cmd_reconcile)
    p = sp.add_parser("report"); p.add_argument("--handle", default="patricksudo"); p.set_defaults(fn=cmd_report)
    p = sp.add_parser("status"); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_status)
    a = ap.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
