#!/usr/bin/env python3
"""tg_flag_decisions.py — Telegram 旗標決定按鈕（2026-11-04 用戶「有沒有在手機上能快速下決定的方式…按過就不見」「我是說決定 defer 與否」）

briefing 的判斷類待辦過去寫「要照做請回一聲；沒回明天 defer 一次」，但沒有任何程式在收回覆，
用戶在手機上也沒有一鍵回答的辦法（LITE:r28b-loser-runner 11/4 案）。本工具把那個決定變成兩顆按鈕：

  ask   對 deadline ≤ 下一個交易日、status=open、尚無 ruling 的旗標，各送一則 Telegram 短訊息，附 inline keyboard：
          ✅ 清倉／減碼（不 defer）→ trade_ledger.py rule-flag --action exit|trim（動作由旗標 reason 推：含「減碼」且無「清倉」→ trim，否則 exit）
          ⏭ defer 一次 → MM/DD      → trade_ledger.py defer --to <原 deadline 後第一個交易日>
        同一旗標同一天只送一次（briefing-out/cache/tg-decisions-pending.json）。forced 旗標不送（那是減 1/3 或撤旗，不是 defer 與否）。
  poll  getUpdates long poll（timeout 50 秒），只收本人 chat 的 callback_query → 寫裁決 → answerCallbackQuery（手機跳一行提示）
        → editMessageText 把原訊息改成「✅ 已裁決：…」且不帶鍵盤（按鈕消失）。每筆記 research/tg-decisions.jsonl。
        offset 存 briefing-out/cache/tg-offset.json；處理失敗也前進 offset（寧可漏一次、不重複寫兩次 defer）。

2026-11-05 擴充（用戶「所有要我決定的可不可也都弄按鈕」）：旗標以外的判斷類待辦由 briefing 用
tools/decision_ledger.py add 登記（2–4 個選項）；ask 每題送一則、一個選項一顆按鈕（callback `dc:<id>:<key>`），
poll 把回答寫成 answered。連按只認第一次（旗標與一般事項皆同）——輪詢器沒在跑時按壓會排隊，11/5 AMD 連按 9 次。

2026-11-05 再擴充（用戶「我不能在手機指導 mac 弄 launchctl」）：自動執行（tools/evening_pass.sh，會下真單）的手機開關。
  notice  送一則「收盤前自動執行預告」：跑一次 auto_exec --preclose 乾跑（不下單）列出屆時會下的單，附一顆
          「⏸ 今天不要跑」（callback `ax:<美東日期>:skip`）。按了 → 寫 briefing-out/cache/auto-exec-skip-<日期>，
          evening_pass.sh 看到就當天兩輪都不跑；訊息改成已跳過並換成「↩️ 恢復今天的自動執行」（`ax:<日期>:run`，刪檔）。
          只擋當天、隔天自動恢復；不按 = 照跑（預設行為不變）。
          poll 在美東 15:00–15:38 的交易日自動送（乾跑有單才送，沒單每 10 分鐘再看一次，一天最多一則）；
          手動 `notice --force` 隨時送。

launchd `com.fadacai.tg-decisions` 每 60 秒跑一次 poll（Mac mini 不睡，等於常駐監聽）。
硬規則：
  - 一個 bot 同時只能有一個 getUpdates 消費者（第二個會收到 409 Conflict）：手動跑 poll 前先 launchctl bootout。
  - 若 bot 設了 webhook，getUpdates 會失敗：啟動先 getWebhookInfo，有 url 就報錯退出，不自動 deleteWebhook。
  - 只寫裁決，絕不下任何券商單——下單仍走 briefing T6.5 / evening pass。
  - callback_data ≤ 64 bytes；超過改用短 token（t:<hex>）查 pending 檔。

測試（不碰真檔、不連 Telegram）：
  python3 tools/tg_flag_decisions.py --flags /tmp/flags.json --state-dir /tmp/tgtest ask --dry-run --no-cost
  python3 tools/tg_flag_decisions.py --flags /tmp/flags.json --state-dir /tmp/tgtest poll --fake-updates /tmp/updates.json
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import send_briefing as sb  # noqa: E402
from check_trading_day import is_trading_day  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
DEFAULT_FLAGS = ROOT / "research" / "position-flags.json"
DEFAULT_STATE_DIR = ROOT / "briefing-out" / "cache"
DEFAULT_LOG = ROOT / "research" / "tg-decisions.jsonl"
DEFAULT_DECISIONS = ROOT / "research" / "decisions.json"   # 旗標以外的待決事項（tools/decision_ledger.py）
ET = ZoneInfo("America/New_York")
CB_MAX_BYTES = 64
POLL_TIMEOUT = 50


# ── 小工具 ───────────────────────────────────────────────────────────────────
def now_et() -> datetime:
    return datetime.now(ET)


def stamp() -> str:
    return now_et().strftime("%m/%d %H:%M")


def load_json(p: Path, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def save_json(p: Path, data) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_log(p: Path, entry: dict) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": now_et().isoformat(timespec="seconds"), **entry}, ensure_ascii=False) + "\n")


def next_trading_day(d: date) -> date:
    n = d + timedelta(days=1)
    for _ in range(12):
        if is_trading_day(n):
            return n
        n += timedelta(days=1)
    return n


def run_ledger(flags_path: Path, args: list[str], timeout: int = 180) -> tuple[int, dict]:
    """呼叫 trade_ledger.py（裁決邏輯只住在那裡），回 (exit code, 它印的 JSON)。"""
    cmd = [sys.executable, str(TOOLS / "trade_ledger.py"), "--flags", str(flags_path), *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return 124, {"error": f"trade_ledger {args[0]} timeout {timeout}s"}
    out = r.stdout.strip()
    try:
        res = json.loads(out)
    except Exception:  # noqa: BLE001
        i = out.find("{")
        try:
            res = json.loads(out[i:]) if i >= 0 else {}
        except Exception:  # noqa: BLE001
            res = {"raw": out[-400:], "stderr": r.stderr[-400:]}
    return r.returncode, res


def run_decisions(dec_path: Path, args: list[str], timeout: int = 60) -> tuple[int, dict]:
    """呼叫 decision_ledger.py（一般待決事項的資料層），回 (exit code, 它印的 JSON)。"""
    cmd = [sys.executable, str(TOOLS / "decision_ledger.py"), "--path", str(dec_path), *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return 124, {"action": "error", "error": f"decision_ledger {args[0]} timeout"}
    try:
        res = json.loads(r.stdout)
    except Exception:  # noqa: BLE001
        res = {"action": "error", "raw": r.stdout[-400:], "stderr": r.stderr[-400:]}
    return r.returncode, res


def flag_action(f: dict) -> str:
    """旗標到期「執行」是清倉還是減碼：reason 含「減碼」且不含「清倉」→ trim，其餘 exit（R28b/R29a 都寫清倉）。"""
    reason = f.get("reason") or ""
    return "trim" if ("減碼" in reason and "清倉" not in reason) else "exit"


def action_zh(action: str) -> str:
    return {"exit": "清倉", "trim": "減碼", "hold": "留倉"}.get(action, action)


STATUS_MARKS = ("\n\n✅ 已裁決", "\n\n✅ 已選", "\n\n⏭ 已 defer", "\n\n⛔ ", "\n\n⚠️ 寫入失敗",
                "\n\n⏸ ", "\n\n✅ 已恢復")


def base_text(text: str) -> str:
    """訊息原文（去掉先前附加的狀態行）。callback 帶的是「按下當時」的訊息快照，重複按時狀態行不得疊加或互相覆寫。"""
    cuts = [i for i in (text.find(m) for m in STATUS_MARKS) if i >= 0]
    return text[:min(cuts)] if cuts else text


# ── callback_data 編碼（≤ 64 bytes，否則用 token） ─────────────────────────
def encode_cb(full: str, tokens: dict) -> str:
    if len(full.encode()) <= CB_MAX_BYTES:
        return full
    tok = "t:" + hashlib.sha1(full.encode()).hexdigest()[:12]
    tokens[tok] = full
    return tok


def decode_cb(cb: str, pending: dict) -> str:
    if not cb.startswith("t:"):
        return cb
    for entry in pending.values():
        full = (entry.get("tokens") or {}).get(cb)
        if full:
            return full
    return ""


def parse_cb(full: str) -> tuple[str, str, str]:
    """'rf:<flag_id>:<exit|trim>' / 'df:<flag_id>:<YYYY-MM-DD>' → (kind, flag_id, arg)。flag_id 本身含冒號（TICKER:slug）。"""
    if ":" not in full:
        return "", "", ""
    kind, rest = full.split(":", 1)       # 另有 'dc:<decision_id>:<option key>'（一般待決事項）、'ax:<美東日期>:<skip|run>'（自動執行開關）
    if kind not in ("rf", "df", "dc", "ax") or ":" not in rest:
        return "", "", ""
    flag_id, arg = rest.rsplit(":", 1)
    return kind, flag_id, arg


# ── ask ───────────────────────────────────────────────────────────────────────
def build_text(f: dict, cost: dict | None, today: date, defer_to: date, action: str) -> str:
    dl = date.fromisoformat(f["deadline"])
    when = "今天" if dl == today else ("明天" if dl == next_trading_day(today) else "")
    when = f"（{when}）" if when else ("（已逾期）" if dl < today else "")
    reason = (f.get("reason") or "").replace("\n", " ")
    if len(reason) > 90:
        reason = reason[:90] + "…"
    lines = [f"🗳 旗標決定：{f['ticker']}",
             f"{f['id']}｜到期 {dl.strftime('%m/%d')}{when}｜已延 {f.get('deferrals', 0)} 次",
             reason]
    if cost:
        mv = cost.get("underlying_move_pct")
        c = cost.get("cost_since_flag")
        bits = []
        if mv is not None:
            bits.append(f"自警示 {mv:+.1f}%")
        if c is not None:
            bits.append(f"累積 {'−' if c < 0 else '+'}${abs(c):,.0f}")
        if bits:
            lines.append("、".join(bits))
    n = f.get("deferrals", 0) + 1
    lines.append(f"按「{action_zh(action)}」= 不 defer，明早 briefing 直接執行（成交後自動結案）；"
                 f"按「defer 一次」= 延到 {defer_to.strftime('%m/%d')}（第 {n} 次{'，即轉 forced' if n >= 3 else '，第 3 次強制'}）。"
                 f"不按 = 明早 briefing 照規則 defer 並記次。")
    return "\n".join(lines)


def cmd_ask(a) -> int:
    today = now_et().date()
    cutoff = next_trading_day(today)
    data = load_json(a.flags, {"flags": []})
    pending_path = Path(a.state_dir) / "tg-decisions-pending.json"
    pending = load_json(pending_path, {})
    open_ids = {f["id"] for f in data.get("flags", []) if f.get("status") in ("open", "forced")}
    if not a.dry_run:
        run_decisions(a.decisions, ["expire"])                        # 過期未答的一般決定 → expired
    dec_data = load_json(a.decisions, {"decisions": []})
    live_dec = {"dc:" + d["id"] for d in dec_data.get("decisions", []) if d.get("status") in ("open", "answered")}
    pending = {k: v for k, v in pending.items() if k in open_ids or k in live_dec}   # 已結案的 pending 丟掉

    cost = {}
    if not a.no_cost:
        rc, rep = run_ledger(a.flags, ["flags"])
        if rc == 0 and isinstance(rep, dict):
            cost = {r["id"]: r for r in rep.get("flags", [])}
        else:
            print(f"[ask] flags report unavailable ({rc}) — 訊息不帶損益", file=sys.stderr)

    asked, skipped = [], []
    for f in data.get("flags", []):
        fid = f["id"]
        if f.get("status") != "open" or f.get("ruling"):
            continue
        dl = date.fromisoformat(f["deadline"])
        if dl > cutoff:
            continue
        p = pending.get(fid)
        if p and p.get("asked") == today.isoformat():
            skipped.append(fid)
            continue
        action = flag_action(f)
        defer_to = next_trading_day(max(dl, today))
        tokens: dict = {}
        cb_exec = encode_cb(f"rf:{fid}:{action}", tokens)
        cb_defer = encode_cb(f"df:{fid}:{defer_to.isoformat()}", tokens)
        kb = {"inline_keyboard": [[
            {"text": f"✅ {action_zh(action)}（不 defer）", "callback_data": cb_exec},
            {"text": f"⏭ defer 一次 → {defer_to.strftime('%m/%d')}", "callback_data": cb_defer},
        ]]}
        text = build_text(f, cost.get(fid), today, defer_to, action)
        mid = sb.send_telegram_message(text, reply_markup=kb, dry_run=a.dry_run)
        pending[fid] = {"asked": today.isoformat(), "status": "asked", "message_id": mid,
                        "deadline": f["deadline"], "defer_to": defer_to.isoformat(),
                        "action": action, "tokens": tokens}
        asked.append(fid)
        append_log(a.log, {"event": "asked", "flag_id": fid, "message_id": mid, "dry_run": a.dry_run})
    # 一般待決事項（decision_ledger）：每題只問一次，一個選項一顆按鈕（各佔一列，文字長也放得下）
    dec_asked = []
    for d in dec_data.get("decisions", []):
        if d.get("status") != "open":
            continue
        pk = "dc:" + d["id"]
        if pk in pending:
            continue
        tokens = {}
        rows = [[{"text": o["label"], "callback_data": encode_cb(f"dc:{d['id']}:{o['key']}", tokens)}]
                for o in d["options"]]
        mid = sb.send_telegram_message(build_decision_text(d), reply_markup={"inline_keyboard": rows},
                                       dry_run=a.dry_run)
        pending[pk] = {"asked": today.isoformat(), "status": "asked", "message_id": mid, "tokens": tokens}
        dec_asked.append(d["id"])
        append_log(a.log, {"event": "asked", "decision_id": d["id"], "message_id": mid, "dry_run": a.dry_run})

    if not a.dry_run:
        save_json(pending_path, pending)
    print(json.dumps({"today": today.isoformat(), "cutoff": cutoff.isoformat(),
                      "asked": asked, "already_asked_today": skipped,
                      "decisions_asked": dec_asked, "dry_run": a.dry_run},
                     ensure_ascii=False))
    return 0


# ── poll ──────────────────────────────────────────────────────────────────────
class TG:
    """answer / edit 兩個動作；--fake-updates 時只印不送（測試不連網）。"""
    def __init__(self, offline: bool):
        self.offline = offline

    def answer(self, cq_id: str, text: str) -> None:
        if self.offline:
            print(f"[answerCallbackQuery] {text}")
            return
        try:
            sb.tg_api("answerCallbackQuery", {"callback_query_id": cq_id, "text": text[:200]})
        except RuntimeError as e:   # 「query is too old」= 按下去超過 Telegram 容許時間；訊息編輯仍會把按鈕拿掉
            print(f"[answerCallbackQuery] {e}", file=sys.stderr)

    def edit(self, chat_id: str, message_id: int, text: str, keep_keyboard: dict | None = None) -> None:
        if self.offline:
            print(f"[editMessageText mid={message_id}] {text}\n[keyboard] {'kept' if keep_keyboard else 'removed'}")
            return
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text[:sb.MAX_TG_CHARS]}
        if keep_keyboard:
            payload["reply_markup"] = keep_keyboard
        try:
            sb.tg_api("editMessageText", payload)
        except RuntimeError as e:
            if "message is not modified" in str(e):   # 已經是這個內容（重複按）→ 不是錯誤
                return
            print(f"[editMessageText] {e}", file=sys.stderr)
            if not keep_keyboard:   # 文字改不了至少把鍵盤拿掉
                try:
                    sb.tg_api("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id})
                except RuntimeError as e2:
                    print(f"[editMessageReplyMarkup] {e2}", file=sys.stderr)


def build_decision_text(d: dict) -> str:
    lines = [f"🗳 待你決定：{d['ticker']}" if d.get("ticker") else "🗳 待你決定", d["question"]]
    if d.get("detail"):
        lines.append(d["detail"])
    for o in d["options"]:
        if o.get("effect"):
            lines.append(f"• {o['label']} → {o['effect']}")
    exp = date.fromisoformat(d["expires"]).strftime("%m/%d") if d.get("expires") else None
    lines.append("按了只記錄你的決定，不會立刻下單；執行在下一次 briefing（美東 11:00）或你開 session 時。"
                 + (f"{exp} 前沒按 = 維持現狀。" if exp else ""))
    return "\n".join(lines)


def handle_decision(cq_id: str, chat_id: str, mid, dec_id: str, key: str, orig: str,
                    keyboard, a, tg: "TG") -> None:
    """一般待決事項的按鈕：寫 decision_ledger answer（冪等——連按只認第一次），訊息改成所選答案。"""
    rc, res = run_decisions(a.decisions, ["answer", "--id", dec_id, "--key", key, "--via", "telegram"])
    act = res.get("action")
    ans = res.get("answer") or {}
    keep = None
    if act == "answered":
        toast = f"已記錄：{ans.get('label')}"
        line = f"✅ 已選（{stamp()} ET）：{ans.get('label')}。{ans.get('effect') or ''}"
    elif act == "already_closed" and ans:
        when = (ans.get("at") or "")[5:16].replace("T", " ").replace("-", "/")
        toast = f"已選過：{ans.get('label')}（這一下不算）"
        line = f"✅ 已選（{when} ET）：{ans.get('label')}。{ans.get('effect') or ''}"
    elif act in ("already_closed", "not_found"):
        why = "找不到這題" if act == "not_found" else f"狀態 {res.get('status')}"
        toast = f"這題已結案（{why}）"
        line = f"⛔ 已結案（{why}，{stamp()} ET），按鈕作廢。"
    else:
        toast = f"寫入失敗：{act or rc}"
        line = f"⚠️ 寫入失敗（{stamp()} ET）：{act or rc}。可再按一次。"
        keep = keyboard
    append_log(a.log, {"event": "dc", "decision_id": dec_id, "key": key, "ok": act == "answered", "result": res})
    tg.answer(cq_id, toast)
    tg.edit(chat_id, mid, f"{orig}\n\n{line}", keep_keyboard=keep)


# ── 自動執行（evening_pass.sh）的手機開關 ─────────────────────────────────────
PLAN_JSON = ROOT / "briefing-out" / "cache" / "auto-exec-plan.json"
NOTICE_WINDOW = ((15, 0), (15, 38))     # 美東；收盤前那輪 15:40 開始
NOTICE_RECHECK_MIN = 10                 # 乾跑沒單 → 隔這麼久再看一次
ACT_ZH = {"BUY": "買", "SELL": "賣", "CANCEL": "撤單", "CLOSE_SPREAD": "複式單（要你手動掛，不會自動下）"}


def skip_path(state_dir, day: str) -> Path:
    """evening_pass.sh 讀的就是這個檔名（$LOG_DIR/cache/auto-exec-skip-<美東日期>）——兩邊要一起改。"""
    return Path(state_dir) / f"auto-exec-skip-{day}"


def ax_keyboard(day: str, skipped: bool) -> dict:
    btn = ({"text": "↩️ 恢復今天的自動執行", "callback_data": f"ax:{day}:run"} if skipped
           else {"text": "⏸ 今天不要跑", "callback_data": f"ax:{day}:skip"})
    return {"inline_keyboard": [[btn]]}


def preview_orders(day: str) -> tuple[list[str] | None, str]:
    """跑一次 auto_exec --preclose 乾跑（沒有 --execute，不下單），回 (屆時會下的單, 價格時間)。失敗回 (None, 原因)。"""
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    try:
        r = subprocess.run([uv, "run", "--directory", str(TOOLS), "python3", str(TOOLS / "auto_exec.py"), "--preclose"],
                           capture_output=True, text=True, timeout=180)
    except (subprocess.TimeoutExpired, OSError) as e:
        return None, f"乾跑沒跑起來（{str(e)[:60]}）"
    d = load_json(PLAN_JSON, {})
    if r.returncode != 0 or d.get("mode") != "dry-run" or d.get("asof") != day:
        return None, f"乾跑結果不可用（rc={r.returncode}、mode={d.get('mode')}）"
    m = re.search(r"T(\d\d:\d\d)", str(d.get("close_asof") or ""))
    lines = []
    for p in d.get("plan", []):
        act = p.get("action")
        if act not in ACT_ZH:       # SHADOW 等不下單的項目不列
            continue
        basis = re.sub(r"（[A-Za-z0-9_-]+）\s*$", "", str(p.get("basis") or "")).replace("前收", "現價")
        qty = f" {p['qty']} 股" if p.get("qty") else ""
        lines.append(f"• {ACT_ZH[act]} {p.get('symbol', '')}{qty}" + (f"（{basis[:90]}）" if basis else ""))
    return lines, (m.group(1) if m else stamp()[-5:])


def build_notice_text(day: str, orders: list[str] | None, when: str) -> str:
    md = date.fromisoformat(day).strftime("%m/%d")
    out = [f"⏰ 今天（{md}）自動執行預告"]
    if orders is None:
        out.append(f"預覽失敗：{when}。自動執行仍會照規則跑（收盤前 15:40、收盤後 16:15 ET）。")
    elif orders:
        out.append(f"依 {when} ET 的價格，收盤前那一輪（15:40 ET）會自動下這些單：")
        out += orders
        out.append("屆時價格回到線上就不會下。")
    else:
        out.append(f"依 {when} ET 的價格，目前沒有要下的單；到 15:40 ET 若有部位跌破線仍會下。")
    out.append("不用回覆 = 照跑。不想讓它今天動就按下面按鈕：收盤前、收盤後兩輪都跳過，明天自動恢復。")
    return "\n".join(out)


def send_notice(a, force: bool = False, dry_run: bool = False, no_preview: bool = False) -> dict:
    now = now_et()
    day = now.date().isoformat()
    sd = Path(a.state_dir)
    if not is_trading_day(now.date()):
        return {"sent": False, "why": "非交易日"}
    if (sd / f"evening-pass-close-{day}.done").exists():
        return {"sent": False, "why": "今天兩輪都跑完了"}
    mark = sd / f"auto-exec-notice-{day}.json"
    st = load_json(mark, {})
    skipped = skip_path(sd, day).exists()
    if not force:
        if st.get("sent") or skipped:
            return {"sent": False, "why": "今天已送過／已跳過"}
        last = st.get("last_check")
        if last and (now - datetime.fromisoformat(last)).total_seconds() < NOTICE_RECHECK_MIN * 60:
            return {"sent": False, "why": "剛看過，還沒到下一次"}
    orders, when = (None, "沒有跑預覽") if no_preview else preview_orders(day)
    if not force and orders == []:      # 無事不發
        save_json(mark, {"sent": False, "last_check": now.isoformat(timespec="seconds")})
        return {"sent": False, "why": "乾跑沒有要下的單"}
    text = build_notice_text(day, orders, when)
    if skipped:
        text += "\n\n⏸ 目前狀態：今天已設成跳過。"
    mid = sb.send_telegram_message(text, ax_keyboard(day, skipped), dry_run=dry_run)
    if not dry_run:
        save_json(mark, {"sent": True, "message_id": mid, "at": now.isoformat(timespec="seconds"),
                         "orders": len(orders or [])})
        append_log(a.log, {"event": "ax_notice", "date": day, "message_id": mid, "orders": orders})
    return {"sent": not dry_run, "message_id": mid, "orders": orders, "dry_run": dry_run}


def cmd_notice(a) -> int:
    print(json.dumps(send_notice(a, force=a.force, dry_run=a.dry_run, no_preview=a.no_preview), ensure_ascii=False))
    return 0


def maybe_auto_notice(a) -> None:
    """poll 每分鐘順便看：美東 15:00–15:38 才動作；任何失敗都不得拖垮收按鈕。"""
    n = now_et()
    if not (NOTICE_WINDOW[0] <= (n.hour, n.minute) <= NOTICE_WINDOW[1]):
        return
    try:
        res = send_notice(a)
        if res.get("sent"):
            print(json.dumps({"auto_notice": res}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(f"[auto notice] {e}", file=sys.stderr)


def handle_auto_exec(cq_id: str, chat_id: str, mid, day: str, arg: str, orig: str, a, tg: "TG") -> None:
    """⏸ 今天不要跑／↩️ 恢復：只動 skip 檔（evening_pass.sh 讀），不碰任何券商單、不撤已送出的單。"""
    sd = Path(a.state_dir)
    today = now_et().date().isoformat()
    ts = stamp()
    sp = skip_path(sd, day)
    pre_done = (sd / f"evening-pass-preclose-{day}.done").exists()
    close_done = (sd / f"evening-pass-close-{day}.done").exists()
    keep = None
    if day != today or arg not in ("skip", "run"):
        toast = "這顆按鈕已過期"
        line = f"⛔ 已過期：這是 {day[5:].replace('-', '/')} 的開關，按鈕作廢。"
    elif close_done:
        toast = "今天兩輪都跑完了"
        line = f"⛔ 今天收盤前、收盤後兩輪都已跑完（{ts} ET），沒有可以跳過的了。已送出的單要撤請到券商 App。"
    elif arg == "skip":
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(f"skip via telegram {now_et().isoformat(timespec='seconds')}\n", encoding="utf-8")
        toast = "已跳過今天的自動執行"
        line = (f"⏸ 已跳過收盤後那一輪（{ts} ET）。收盤前那輪已經跑完，已送出的單不受影響。明天自動恢復。" if pre_done
                else f"⏸ 今天的自動執行已跳過（{ts} ET）：收盤前、收盤後兩輪都不跑，不會下任何單。明天自動恢復。")
        keep = ax_keyboard(day, True)
    else:
        sp.unlink(missing_ok=True)
        hm = now_et().strftime("%H%M")
        toast = "已恢復今天的自動執行"
        if pre_done or hm > "1558":
            line = f"✅ 已恢復（{ts} ET）：收盤前那輪已過，收盤後那一輪（16:15–19:00 ET）照跑。"
        else:
            line = f"✅ 已恢復（{ts} ET）：照原訂時間跑（收盤前 15:40、收盤後 16:15 ET）。"
        keep = ax_keyboard(day, False)
    append_log(a.log, {"event": "ax", "date": day, "arg": arg, "skip_file_exists": sp.exists()})
    tg.answer(cq_id, toast)
    tg.edit(chat_id, mid, f"{orig}\n\n{line}", keep_keyboard=keep)


def handle_callback(cq: dict, chat_id: str, a, tg: TG) -> None:
    cq_id = cq.get("id", "")
    msg = cq.get("message") or {}
    mid = msg.get("message_id")
    from_id = str((cq.get("from") or {}).get("id", ""))
    msg_chat = str((msg.get("chat") or {}).get("id", ""))
    if from_id != chat_id or msg_chat != chat_id:
        append_log(a.log, {"event": "rejected", "why": "not owner", "from": from_id, "chat": msg_chat})
        tg.answer(cq_id, "不是本人，忽略")
        return

    pending_path = Path(a.state_dir) / "tg-decisions-pending.json"
    pending = load_json(pending_path, {})
    full = decode_cb(cq.get("data") or "", pending)
    kind, flag_id, arg = parse_cb(full)
    if not kind:
        append_log(a.log, {"event": "rejected", "why": "bad callback", "data": cq.get("data")})
        tg.answer(cq_id, "看不懂這顆按鈕，忽略")
        return
    if kind == "dc":
        handle_decision(cq_id, chat_id, mid, flag_id, arg,
                        base_text(msg.get("text") or f"🗳 待你決定：{flag_id}"),
                        msg.get("reply_markup"), a, tg)
        return
    if kind == "ax":
        handle_auto_exec(cq_id, chat_id, mid, flag_id, arg,
                         base_text(msg.get("text") or "⏰ 自動執行開關"), a, tg)
        return

    data = load_json(a.flags, {"flags": []})
    f = next((x for x in data.get("flags", []) if x.get("id") == flag_id), None)
    orig = base_text(msg.get("text") or f"🗳 旗標決定：{flag_id}")
    ts = stamp()
    p = pending.get(flag_id) or {}

    # 冪等：同一則訊息連按多次只認第一次（輪詢器沒在跑時按壓會排隊——2026-11-05 AMD 連按 9 次：
    # 第 1 下寫入並改成「✅ 已裁決」，第 2 下卻把訊息覆寫成「⛔ 已結案」；若按的是 defer 會被記成 9 次直接 forced）。
    # 已有裁決／這則訊息已 defer 過／defer 目標日已達成 → 不再寫帳，只把訊息改成現況。
    if f is not None and f.get("ruling"):
        r = f["ruling"]
        append_log(a.log, {"event": "repeat", "flag_id": flag_id, "why": "已有裁決"})
        tg.answer(cq_id, f"已裁決過：{action_zh(r.get('action'))}，不 defer")
        tg.edit(chat_id, mid, f"{orig}\n\n✅ 已裁決（{r.get('date')}）：{action_zh(r.get('action'))}，不 defer。"
                              "明早 briefing 直接執行，成交後自動結案。")
        return
    if f is not None and f.get("status") in ("open", "forced") and (
            (p.get("status") == "deferred" and p.get("message_id") == mid)
            or (kind == "df" and (f.get("deadline") or "") >= arg)):
        to_zh = date.fromisoformat(f["deadline"]).strftime("%m/%d")
        append_log(a.log, {"event": "repeat", "flag_id": flag_id, "why": "已 defer"})
        tg.answer(cq_id, f"已 defer 到 {to_zh}（第 {f.get('deferrals')} 次），這一下不再計次")
        tg.edit(chat_id, mid, f"{orig}\n\n⏭ 已 defer 到 {to_zh}（第 {f.get('deferrals')} 次）。"
                + ("🔴 已達 3 次 → forced：減碼 1/3 或明文撤旗。" if f.get("status") == "forced"
                   else "第 3 次自動轉 forced。"))
        return
    if f is None or f.get("status") != "open":
        why = "找不到旗標" if f is None else f"狀態 {f.get('status')}"
        append_log(a.log, {"event": "stale", "flag_id": flag_id, "why": why})
        tg.answer(cq_id, f"這個旗標已結案（{why}）")
        tg.edit(chat_id, mid, f"{orig}\n\n⛔ 已結案（{why}，{ts} ET），按鈕作廢。")
        pending.pop(flag_id, None)
        save_json(pending_path, pending)
        return

    if kind == "rf":
        action = arg if arg in ("exit", "trim") else "exit"
        note = f"Telegram 按鈕 {ts} ET：不 defer，到期日{action_zh(action)}（依旗標 reason 既定動作）"
        rc, res = run_ledger(a.flags, ["rule-flag", "--id", flag_id, "--action", action, "--note", note])
        ok = rc == 0 and res.get("action") == "ruled"
        toast = f"已記錄：{action_zh(action)}，不 defer" if ok else f"寫入失敗：{res.get('action') or res.get('error') or rc}"
        done = f"✅ 已裁決（{ts} ET）：{action_zh(action)}，不 defer。明早 briefing 直接執行，成交後自動結案。"
        status = "ruled"
    else:
        rc, res = run_ledger(a.flags, ["defer", "--id", flag_id, "--to", arg,
                                       "--reason", f"Telegram 按鈕 {ts} ET defer 一次"])
        ok = rc == 0 and res.get("action") == "deferred"
        n = res.get("deferrals")
        forced = res.get("forced")
        to_zh = date.fromisoformat(arg).strftime("%m/%d")
        toast = (f"已 defer 到 {to_zh}（第 {n} 次{'，已轉 forced' if forced else ''}）" if ok
                 else f"defer 失敗：{res.get('action') or res.get('error') or rc}")
        done = (f"⏭ 已 defer 到 {to_zh}（{ts} ET，第 {n} 次）。"
                + ("🔴 已達 3 次 → forced：減碼 1/3 或明文撤旗。" if forced else "第 3 次自動轉 forced。"))
        status = "deferred"

    append_log(a.log, {"event": kind, "flag_id": flag_id, "arg": arg, "ok": ok, "result": res})
    tg.answer(cq_id, toast)
    if ok:
        tg.edit(chat_id, mid, f"{orig}\n\n{done}")
        if flag_id in pending:
            pending[flag_id]["status"] = status
            pending[flag_id]["decided"] = now_et().isoformat(timespec="seconds")
            save_json(pending_path, pending)
    elif res.get("action") in ("refused_ruled", "not_found"):
        tg.edit(chat_id, mid, f"{orig}\n\n⛔ 無法寫入：{res.get('rule') or res.get('action')}（{ts} ET），按鈕作廢。")
    else:
        # 其他失敗（例如 trade_ledger 例外）：留著鍵盤讓用戶再按一次
        tg.edit(chat_id, mid, f"{orig}\n\n⚠️ 寫入失敗（{ts} ET）：{toast}。可再按一次。",
                keep_keyboard=msg.get("reply_markup"))


def cmd_poll(a) -> int:
    chat_id = sb.require("TELEGRAM_CHAT_ID")
    offset_path = Path(a.state_dir) / "tg-offset.json"
    if a.fake_updates:
        updates = load_json(a.fake_updates, [])
        tg = TG(offline=True)
    else:
        info = sb.tg_api("getWebhookInfo", {})
        if info.get("url"):
            print(f"⛔ bot 設有 webhook（{info['url']}），getUpdates 不可用；請先手動 deleteWebhook 再跑", file=sys.stderr)
            return 2
        maybe_auto_notice(a)        # 美東 15:00–15:38：收盤前自動執行預告（有單才送，一天最多一則）
        off = load_json(offset_path, {}).get("offset", 0)
        try:
            updates = sb.tg_api("getUpdates", {"offset": off, "timeout": a.timeout,
                                               "allowed_updates": ["callback_query"]},
                                timeout=a.timeout + 15)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            # 網路瞬斷（11/5 12:20 ET「Connection reset by peer」）：60 秒後 launchd 會再跑，不印整段 traceback
            print(f"[poll] {now_et().isoformat(timespec='seconds')} 網路錯誤，下一輪重試：{e}", file=sys.stderr)
            return 0
        except RuntimeError as e:
            if "Conflict" in str(e) or "409" in str(e):
                print("⛔ 另一個 getUpdates 消費者在跑（409 Conflict）——同一 bot 只能一個；手動跑 poll 前先 launchctl bootout",
                      file=sys.stderr)
                return 3
            raise
        tg = TG(offline=False)

    handled = 0
    new_off = load_json(offset_path, {}).get("offset", 0)
    for u in updates or []:
        new_off = max(new_off, int(u.get("update_id", 0)) + 1)
        cq = u.get("callback_query")
        if not cq:
            continue
        try:
            handle_callback(cq, chat_id, a, tg)
            handled += 1
        except Exception as e:  # noqa: BLE001  處理失敗也前進 offset：寧可漏一次、不重複寫兩次 defer
            append_log(a.log, {"event": "error", "data": cq.get("data"), "error": str(e)})
            print(f"[poll] handler error: {e}", file=sys.stderr)
            try:
                tg.answer(cq.get("id", ""), f"處理失敗：{str(e)[:120]}")
            except Exception:  # noqa: BLE001
                pass
    if not a.fake_updates:
        save_json(offset_path, {"offset": new_off, "at": now_et().isoformat(timespec="seconds")})
    if handled or a.fake_updates:
        print(json.dumps({"handled": handled, "updates": len(updates or []), "offset": new_off}))
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────
def main() -> int:
    sb.load_env()
    p = argparse.ArgumentParser(description="Telegram 旗標決定按鈕：ask 送按鈕、poll 收回答寫進旗標檔")
    p.add_argument("--flags", default=str(DEFAULT_FLAGS), help="旗標檔（測試用副本）")
    p.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR), help="pending / offset 存放目錄（測試時指到暫存）")
    p.add_argument("--log", default=None, help="決定帳 jsonl（預設 research/tg-decisions.jsonl；--state-dir 非預設時跟著進該目錄）")
    p.add_argument("--decisions", default=str(DEFAULT_DECISIONS), help="一般待決事項檔（decision_ledger；測試用副本）")
    sub = p.add_subparsers(dest="cmd", required=True)

    ask = sub.add_parser("ask", help="對到期未裁決的旗標、以及 open 的一般待決事項送決定按鈕")
    ask.add_argument("--dry-run", action="store_true", help="只印不送、不寫 pending")
    ask.add_argument("--no-cost", action="store_true", help="不跑 trade_ledger flags（不連券商、訊息不帶損益）")

    poll = sub.add_parser("poll", help="收 Telegram 按鈕回答（getUpdates long poll 一次）")
    poll.add_argument("--timeout", type=int, default=POLL_TIMEOUT, help="long poll 秒數（launchd 每 60 秒一跑，預設 50）")
    poll.add_argument("--fake-updates", default=None, help="測試：讀這個 JSON 當 getUpdates 結果，不連 Telegram")

    notice = sub.add_parser("notice", help="送「收盤前自動執行預告」＋「⏸ 今天不要跑」按鈕（poll 在美東 15:00–15:38 會自動送）")
    notice.add_argument("--force", action="store_true", help="不管時間、今天送過沒、有沒有單，現在就送")
    notice.add_argument("--dry-run", action="store_true", help="只印不送")
    notice.add_argument("--no-preview", action="store_true", help="不跑 auto_exec 乾跑（測試用）")

    a = p.parse_args()
    if a.log is None:
        a.log = str(DEFAULT_LOG if Path(a.state_dir) == DEFAULT_STATE_DIR else Path(a.state_dir) / "tg-decisions.jsonl")
    Path(a.state_dir).mkdir(parents=True, exist_ok=True)
    return {"ask": cmd_ask, "poll": cmd_poll, "notice": cmd_notice}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
