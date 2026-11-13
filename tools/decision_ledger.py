#!/usr/bin/env python3
"""decision_ledger.py — 待用戶決定的事項登記（2026-11-05 用戶「所有要我決定的可不可也都弄按鈕」）

briefing / review 產出「你的判斷，我沒改」「要不要…」這類待辦時，散文會被下一個 context 忘掉，用戶在手機上
也無從回答（11/5：「PWR 賣單要不要改貼盤價——你的判斷，我沒改」）。凡要用戶決定的事，同一次登記成一筆
decision（2–4 個選項）：`tg_flag_decisions.py ask` 送 Telegram 按鈕，`poll` 把回答寫回這裡；下一個有券商連線的
執行點（briefing Step 0 / 互動 session）讀 `list --status answered`，照選項執行後 `done`。
旗標的「defer 與否」另走 trade_ledger rule-flag / defer（同一組按鈕機制），不登記在這裡。

按鈕只記錄決定，不下單。選項文字要讓用戶不看上下文就知道按下去會發生什麼、何時發生。

資料：research/decisions.json
  add     --id <kebab> --question "…" --option key=按鈕文字[=選了之後會怎樣] ×2–4
          [--ticker T] [--detail "…"] [--expires YYYY-MM-DD]（預設 3 天後）
  list    [--status open|answered|done|expired|all]（預設 open + answered = 還沒了結的）
  answer  --id <id> --key <key> [--via telegram|session]   冪等：已回答 → 回既有答案、不覆寫
  done    --id <id> --note "<做了什麼／單號>"                answered → done（執行完才標）
  expire                                                    open 且過 expires → expired（ask 每次先跑）
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "research" / "decisions.json"
ET = ZoneInfo("America/New_York")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{2,39}$")
KEY_RE = re.compile(r"^[a-z0-9-]{1,12}$")
MAX_LABEL = 40
DEFAULT_EXPIRE_DAYS = 3
EXIT_OK, EXIT_GENERIC = 0, 1


def _now() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


def _today() -> date:
    return datetime.now(ET).date()


def load(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"decisions": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save(data: dict, path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def parse_option(raw: str) -> dict:
    parts = raw.split("=", 2)
    if len(parts) < 2:
        raise ValueError(f"選項格式是 key=按鈕文字[=效果]：{raw!r}")
    key, label = parts[0].strip(), parts[1].strip()
    effect = parts[2].strip() if len(parts) == 3 else ""
    if not KEY_RE.match(key):
        raise ValueError(f"選項 key 只能是 a-z0-9-、最長 12 字：{key!r}")
    if not label or len(label) > MAX_LABEL:
        raise ValueError(f"按鈕文字 1–{MAX_LABEL} 字：{label!r}")
    return {"key": key, "label": label, "effect": effect}


def add(data, *, id_, question, options, ticker=None, detail=None, expires=None) -> dict:
    if not ID_RE.match(id_):
        return {"action": "bad_id", "id": id_, "rule": "3–40 字，英數與 : _ -"}
    if not 2 <= len(options) <= 4:
        return {"action": "bad_options", "rule": "2–4 個選項"}
    if len({o["key"] for o in options}) != len(options):
        return {"action": "bad_options", "rule": "選項 key 不可重複"}
    for d in data["decisions"]:
        if d["id"] == id_ and d["status"] in ("open", "answered"):
            return {"action": "already_open", "id": id_, "status": d["status"]}
    today = _today()
    data["decisions"].append({
        "id": id_, "ticker": (ticker or "").upper() or None, "question": question, "detail": detail,
        "options": options, "opened": today.isoformat(),
        "expires": expires or (today + timedelta(days=DEFAULT_EXPIRE_DAYS)).isoformat(),
        "status": "open", "answer": None,
        "history": [{"at": _now(), "event": "opened"}],
    })
    return {"action": "opened", "id": id_}


def answer(data, *, id_, key, via="session") -> dict:
    d = next((x for x in data["decisions"] if x["id"] == id_), None)
    if d is None:
        return {"action": "not_found", "id": id_}
    if d["status"] != "open":                       # 冪等：連按、重複回答都不覆寫第一次的答案
        return {"action": "already_closed", "id": id_, "status": d["status"], "answer": d.get("answer")}
    opt = next((o for o in d["options"] if o["key"] == key), None)
    if opt is None:
        return {"action": "bad_key", "id": id_, "allowed": [o["key"] for o in d["options"]]}
    d["status"] = "answered"
    d["answer"] = {"key": key, "label": opt["label"], "effect": opt.get("effect"), "at": _now(), "via": via}
    d["history"].append({"at": _now(), "event": "answered", "key": key, "via": via})
    return {"action": "answered", "id": id_, "answer": d["answer"]}


def done(data, *, id_, note) -> dict:
    d = next((x for x in data["decisions"] if x["id"] == id_), None)
    if d is None:
        return {"action": "not_found", "id": id_}
    if d["status"] != "answered":
        return {"action": "not_answered", "id": id_, "status": d["status"]}
    d["status"] = "done"
    d["history"].append({"at": _now(), "event": "done", "note": note})
    return {"action": "done", "id": id_}


def withdraw(data, *, id_, note) -> dict:
    """還沒回答的卡片在別處已有決定（例：用戶在 session 裡說自己手動處理）→ 直接結案，不假裝選了哪個選項。"""
    d = next((x for x in data["decisions"] if x["id"] == id_), None)
    if d is None:
        return {"action": "not_found", "id": id_}
    if d["status"] != "open":
        return {"action": "already_closed", "id": id_, "status": d["status"]}
    d["status"] = "done"
    d["history"].append({"at": _now(), "event": "withdrawn", "note": note})
    return {"action": "withdrawn", "id": id_}


def expire(data) -> dict:
    today = _today().isoformat()
    hit = []
    for d in data["decisions"]:
        if d["status"] == "open" and (d.get("expires") or "9999") < today:
            d["status"] = "expired"
            d["history"].append({"at": _now(), "event": "expired"})
            hit.append(d["id"])
    return {"action": "expired", "ids": hit}


def main() -> int:
    p = argparse.ArgumentParser(description="待用戶決定事項登記（Telegram 按鈕的資料層）")
    p.add_argument("--path", default=str(DEFAULT_PATH))
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="登記一筆要用戶決定的事（2–4 個選項）")
    a.add_argument("--id", dest="id_", required=True, help="3–40 字 kebab，例：20261105-pwr-reprice")
    a.add_argument("--question", required=True, help="一句話問題，不看上下文也懂")
    a.add_argument("--option", action="append", required=True, help="key=按鈕文字[=選了之後會怎樣、何時]；重複 2–4 次")
    a.add_argument("--ticker", default=None)
    a.add_argument("--detail", default=None, help="補充一兩句（價位、理由）")
    a.add_argument("--expires", default=None, help="YYYY-MM-DD；預設 3 天後")

    ls = sub.add_parser("list", help="列出決定事項")
    ls.add_argument("--status", default="pending", choices=["pending", "open", "answered", "done", "expired", "all"])

    an = sub.add_parser("answer", help="寫入回答（冪等）")
    an.add_argument("--id", dest="id_", required=True)
    an.add_argument("--key", required=True)
    an.add_argument("--via", default="session", choices=["telegram", "session"])

    dn = sub.add_parser("done", help="回答已執行完 → 結案")
    dn.add_argument("--id", dest="id_", required=True)
    dn.add_argument("--note", required=True)

    wd = sub.add_parser("withdraw", help="未回答的卡片已在別處決定 → 結案（不記成任何選項）")
    wd.add_argument("--id", dest="id_", required=True)
    wd.add_argument("--note", required=True)
    sub.add_parser("expire", help="過期未答 → expired")

    args = p.parse_args()
    data = load(args.path)
    try:
        if args.cmd == "add":
            res = add(data, id_=args.id_, question=args.question,
                      options=[parse_option(o) for o in args.option],
                      ticker=args.ticker, detail=args.detail, expires=args.expires)
            ok = res["action"] == "opened"
        elif args.cmd == "list":
            want = {"pending": ("open", "answered"), "all": None}.get(args.status, (args.status,))
            rows = [d for d in data["decisions"] if want is None or d["status"] in want]
            _emit({"count": len(rows), "decisions": rows})
            return EXIT_OK
        elif args.cmd == "answer":
            res = answer(data, id_=args.id_, key=args.key, via=args.via)
            ok = res["action"] == "answered"
        elif args.cmd == "done":
            res = done(data, id_=args.id_, note=args.note)
            ok = res["action"] == "done"
        elif args.cmd == "withdraw":
            res = withdraw(data, id_=args.id_, note=args.note)
            ok = res["action"] == "withdrawn"
        else:
            res = expire(data)
            ok = True
    except ValueError as e:
        _emit({"action": "error", "error": str(e)})
        return EXIT_GENERIC
    save(data, args.path)
    _emit(res)
    return EXIT_OK if ok else EXIT_GENERIC


if __name__ == "__main__":
    sys.exit(main())
