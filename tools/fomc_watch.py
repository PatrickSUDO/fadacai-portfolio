#!/usr/bin/env python3
"""fomc_watch.py — FOMC 決議後的機械動作（2026-09-16，10Y 5% / 升息日用戶問「有動作該做嗎」）。

規則來源：feedback/hedge-sleeve.md 規則 1——「regime 加劇（CPI 熱 / Fed 實際升息 / 油 >$100）→ sleeve 加到 8–10%」。
原本這句只活在散文裡；本工具在決議公布後讀 EODHD economic-events 的 Fed Interest Rate Decision actual vs previous：
  actual > previous（實際升息）→ research/regime-overrides.json 寫 sleeve_target_pct=8（附理由/日期），guard 讀到就出 BUY_TO，
                                  pre-close / 收盤 pass 依 R25 規則 4 分兩批買（一半貼盤 day、一半 −4.5% GTC）
  actual < previous（降息）      → 不動（縮減條件是油 <$70 且 CPI 趨勢向下 ≥3 個月，另案）
  無決議 / 尚未公布              → 什麼都不做（每日 20:10 本地跑一次，非 FOMC 日零成本）
覆寫的解除：/trade-review 或用戶明文，工具不自動降回 6%（regime 判斷是人的事，執行是機器的事）。
"""
import json, os, sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
OVR = ROOT / "research" / "regime-overrides.json"
HIKE_TARGET = 8.0


def load_env():
    try:
        from send_briefing import load_env as _le  # noqa: WPS433
        _le()
    except Exception:  # noqa: BLE001
        pass


def fed_decision_today(token: str, day: str):
    q = urlencode({"api_token": token, "country": "US", "from": day, "to": day, "limit": 200, "fmt": "json"})
    with urlopen(Request(f"https://eodhd.com/api/economic-events?{q}", headers={"User-Agent": "fadacai"}), timeout=30) as r:
        events = json.loads(r.read())
    for e in events:
        t = (e.get("type") or "").lower()
        if "interest rate decision" in t and "fed" in t:
            return e
    return None


def main(argv):
    load_env()
    token = os.environ.get("EODHD_API_TOKEN", "").strip()
    day = next((a.split("=", 1)[1] for a in argv if a.startswith("--date=")), date.today().isoformat())
    if not token:
        print("⚠️ EODHD_API_TOKEN 未設，跳過"); return 0
    # 手動路徑：EODHD actual 常落後數小時（2026-09-16 決議後 1h+ 仍 None），可用已證實的新聞直接餵：
    #   --hike 3.75 4.00 --source "<url>"
    if "--hike" in argv:
        i = argv.index("--hike"); prev, actual = float(argv[i + 1]), float(argv[i + 2])
        src = argv[argv.index("--source") + 1] if "--source" in argv else "manual"
        ev = {"previous": prev, "actual": actual, "manual_source": src}
    else:
        ev = fed_decision_today(token, day)
        if not ev:
            print(f"{day}: 無 Fed 決議事件"); return 0
    actual, prev = ev.get("actual"), ev.get("previous")
    if actual is None:
        print(f"{day}: Fed 決議尚未公布（forecast {ev.get('forecast')}，previous {prev}）"); return 0
    ovr = json.loads(OVR.read_text()) if OVR.exists() else {}
    msg = None
    if prev is not None and float(actual) > float(prev):
        if ovr.get("sleeve_target_pct") != HIKE_TARGET or ovr.get("reason_date") != day:
            ovr.update({"sleeve_target_pct": HIKE_TARGET, "reason": f"Fed 升息 {prev}→{actual}（R25 規則 1：實際升息 → sleeve 8–10%）",
                        "reason_date": day, "set_by": "tools/fomc_watch.py", "set_at": datetime.now().isoformat(timespec="minutes"),
                        "evidence": ev.get("manual_source") or "EODHD economic-events actual",
                        "clear_how": "/trade-review 或用戶明文；油 <$70 且 CPI 趨勢向下 ≥3 個月才縮回 6%"})
            OVR.write_text(json.dumps(ovr, ensure_ascii=False, indent=2))
            msg = (f"🏛 FOMC {day}：升息 {prev}→{actual}。R25 規則 1 觸發 → 避險 sleeve 目標 6%→8%，"
                   f"今晚 pre-close/收盤 pass 依規則 4 分兩批補（GLD/XLE 各半：一半貼盤、一半 −4.5% GTC）。→ 動作：不用回 session。")
        else:
            print(f"{day}: 升息已記錄過，覆寫維持 {HIKE_TARGET}%")
    else:
        print(f"{day}: Fed {prev}→{actual}，非升息，sleeve 目標不變")
    if msg:
        print(msg)
        try:
            from send_briefing import send_telegram  # noqa: WPS433
            send_telegram(msg)
        except Exception as e:  # noqa: BLE001
            print(f"tg failed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
