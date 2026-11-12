#!/usr/bin/env python3
"""reentry_gate.py — 撿回名單的機械閘門（2026-11-12 用戶「這環節能否自動化，我看數據決定即可」）

為什麼：R20 撿回原本靠兩支價格警報每天響一次、早上的 briefing 臨場判斷修正方向，卡在「沒有 365 日 EV」就停住，
等用戶手動跑 /stock-analysis（11/9–11/12 四檔連卡三天；LRCX 低線警報重複響 22 次；LITE 被 Marvell 換股收購後
仍連兩天被標「走強確認」）。這支把整條鏈變成機械判定，只在「數據齊了、過門檻」時送一張 Telegram 決定卡。

每檔撿回候選（thesis-ledger 的 pending `*reentry*` 條目 ∪ 未過期的 `*-reentry-low/high` 警報）依序判：
  held          已在倉 → 不是撿回條目
  retired       用戶按過「不撿回」→ 不再追蹤
  snoozed       用戶按過「等事件」或卡片過期未按 → 到期前不問
  no-trigger    收盤在出場價 ±10% 之內
  revision-fail 到價但 30 日修正條件不過（回檔：下修 ≤ 上修；走強：上修 > 下修；分析師 <8 位不單獨成立）
  special       近 180 天有併購類申報（Form 425／DEFM14A／S-4…）→ 原撿回理由可能不適用，問要不要撤
  blocked       名額滿／財報 ±48 小時／走強分支遇板塊延伸（R31）
  needs-ev      以上都過但沒有新鮮的 365 日 EV → 排進無人值守 /stock-analysis（reentry_ev_runner.sh，每天最多 2 檔）
  ev-fail       EV（用今天收盤重算）< R35 門檻 → 安靜、登 cf-reentry 影子；股價跌到門檻價會自動轉 ready
  ready         過門檻 → decision_ledger 登記一題（買起手倉／等事件／不撿回），tg_flag_decisions ask 送按鈕

EV 不重跑也每天更新：EV% = 預測帳的 ev_price ÷ 今日收盤 − 1。EV 過期 = 預測日超過 30 天，或預測日之後公司又公布過財報。
「扣歷史偏差後」= 用預測帳已驗收樣本的（實際發生率 ÷ 預測機率）對樂觀／悲觀機率做半強度修正後重算，只顯示不裁決。

按鈕只記錄決定。「買」由下一次 briefing 照 T6.5 既有條件掛單（起手倉金額壓在 $3,000 無人值守上限內）；
「等」「不撿回」「撤條目」由本腳本 apply 機械處理。

Usage:
  python3 tools/reentry_gate.py scan [--dry-run] [--prices AMD=585.3,LRCX=233.78] [--no-network]
  python3 tools/reentry_gate.py apply            # 只處理已回答的按鈕（不抓價）
  python3 tools/reentry_gate.py status           # 印上次 scan 的表
  python3 tools/reentry_gate.py queue            # 印待跑 EV 的代號（一行一檔，runner 讀）
  python3 tools/reentry_gate.py mark-run TICKER ok|fail
  python3 tools/reentry_gate.py selftest
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

THESIS = ROOT / "research" / "thesis-ledger.json"
ALERTS = ROOT / "research" / "price-alerts.json"
EV_LEDGER = ROOT / "research" / "ev-ledger.jsonl"
DECISIONS = ROOT / "research" / "decisions.json"
POS_STATE = ROOT / "research" / "position-state.json"
HURDLES = ROOT / "research" / "benchmark-hurdles.json"
STATE = ROOT / "research" / "reentry-gate-state.json"
FUND = ROOT / "briefing-out" / "cache" / "fundamentals-snapshot.json"
OUT = ROOT / "briefing-out" / "cache" / "reentry-gate.json"
ET = ZoneInfo("America/New_York")

BAND_LOW, BAND_HIGH = 0.90, 1.10        # 與 trade_ledger.REENTRY_LOW/HIGH 一致
MIN_ANALYSTS = 8                         # H13：分析師 <8 位的修正不單獨觸發
REV_STALE_DAYS = 45                      # 距上次財報超過此天數的修正數字標過期（只標示，不擋）
EV_FRESH_DAYS = 30
EV_MIN_HORIZON = 300
EV_RUNS_PER_DAY = 2
EV_RETRY_DAYS = 3                        # 無人值守分析失敗後隔幾天再試
STARTER_PCT, STARTER_CAP_USD = 0.02, 3000.0   # H10 起手 ≤2%；$3,000 = T6.5 無人值守新增曝險上限
STARTER_PCT_RICH = 0.015                 # priced_in_pct > +150% 的名字
CASH_BUFFER = 8000.0                     # R24 固定緩衝
EARNINGS_BLACKOUT_DAYS = 2               # R18 財報 ±48 小時
ASK_EXPIRE_DAYS = 5
SNOOZE_DEFAULT_DAYS = 14
MERGER_FORMS = {"425", "DEFM14A", "PREM14A", "SC TO-T", "SC TO-T/A", "SC 14D9", "S-4", "S-4/A", "SC 13E3"}
MERGER_LOOKBACK_DAYS = 180
CALIB_MIN_N, CALIB_SHRINK = 5, 0.5


# ── io ────────────────────────────────────────────────────────────────────
def today_et() -> date:
    return datetime.now(ET).date()


def jload(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def jsave(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def run(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # noqa: BLE001
        return 124, str(e)


def tstate(state: dict, tk: str) -> dict:
    return state.setdefault("tickers", {}).setdefault(tk, {})


# ── 候選 ──────────────────────────────────────────────────────────────────
def exit_price_of(thesis: dict) -> float | None:
    for src, pat in ((thesis.get("ev_snapshot") or "", r"出場價\s*\$?([\d.]+)"), (thesis.get("thesis") or "", r"出場\s*@\s*\$?([\d.]+)")):
        m = re.search(pat, src)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None


def candidates(today: date) -> dict:
    """ticker → {exit, thesis_id, source, expires}。thesis 優先；thesis 已結但警報未過期者也算（CRDO 11/12 案）。"""
    out: dict[str, dict] = {}
    for t in jload(THESIS, {"theses": []}).get("theses", []):
        if t.get("status") != "pending" or "reentry" not in (t.get("slug") or ""):
            continue
        px = exit_price_of(t)
        if px:
            out[t["ticker"].upper()] = {"exit": px, "thesis_id": t["id"], "source": "thesis", "exit_date": t.get("created")}
    for a in jload(ALERTS, {"alerts": []}).get("alerts", []):
        m = re.match(r"^(.+)-reentry-(low|high)$", a.get("id", ""))
        if not m or not a.get("level"):
            continue
        tk = m.group(1).upper()
        if tk in out or (a.get("expires") and a["expires"] < today.isoformat()):
            continue
        px = a["level"] / (BAND_LOW if m.group(2) == "low" else BAND_HIGH)
        out[tk] = {"exit": round(px, 2), "thesis_id": None, "source": "alert", "exit_date": a.get("created"), "expires": a.get("expires")}
    return out


# ── 資料 ──────────────────────────────────────────────────────────────────
def fetch_closes(tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}
    import yfinance as yf
    out = {}
    df = yf.download(tickers, period="5d", interval="1d", auto_adjust=False, progress=False, group_by="ticker", threads=True)
    for tk in tickers:
        try:
            s = (df[tk]["Close"] if len(tickers) > 1 else df["Close"]).dropna()
            if hasattr(s, "columns"):
                s = s.iloc[:, 0]
            if len(s):
                out[tk] = round(float(s.iloc[-1]), 2)
        except Exception:  # noqa: BLE001
            continue
    return out


def earnings_dates(tk: str, today: date) -> tuple[str | None, str | None]:
    """(上次已公布財報日, 下次財報日)；抓不到回 None。"""
    try:
        import yfinance as yf
        df = yf.Ticker(tk).get_earnings_dates(limit=12)
        days = sorted({d.date() for d in df.index})
        past = [d for d in days if d <= today]
        fut = [d for d in days if d > today]
        return (past[-1].isoformat() if past else None, fut[0].isoformat() if fut else None)
    except Exception:  # noqa: BLE001
        return None, None


def revisions(tk: str, st: dict, today: date, network: bool) -> dict:
    """本財年 30 日 EPS 修正上修／下修家數；當天沒抓過就先補抓單票進 cache。"""
    if network and st.get("fund_fetched") != today.isoformat():
        rc, _ = run([sys.executable, str(TOOLS / "fetch_fundamentals.py"), "--ticker", tk], timeout=240)
        if rc == 0:
            st["fund_fetched"] = today.isoformat()
    f = jload(FUND, {})
    x = (f.get("tickers") or f).get(tk) or {}
    fe = (x.get("snapshot") or {}).get("forward_estimates") or x.get("forward_estimates") or {}
    cur = fe.get("curr_fy") or fe.get("next_fy") or {}
    up, dn, n = cur.get("revisions_up_30d"), cur.get("revisions_down_30d"), cur.get("eps_num_analysts")
    return {"up": int(up or 0), "down": int(dn or 0), "n": int(n or 0), "have": bool(cur),
            "priced_in_pct": (x.get("self_valuation") or {}).get("priced_in_pct")}


def merger_filing(tk: str, st: dict, today: date, network: bool) -> dict | None:
    """近 180 天有沒有併購類申報（Form 425／DEFM14A／S-4…）。一天查一次，結果記在 state。
    來源用 yfinance 的申報清單——本機直連 sec.gov 會回 403（2026-11-12 實測）。收購方自己也會有 425，同樣算特殊情況。"""
    if st.get("sec_checked") == today.isoformat() or not network:
        return st.get("special")
    try:
        import yfinance as yf
        cut = (today - timedelta(days=MERGER_LOOKBACK_DAYS)).isoformat()
        hits = sorted((str(f.get("date"))[:10], str(f.get("type"))) for f in (yf.Ticker(tk).get_sec_filings() or [])
                      if str(f.get("type")) in MERGER_FORMS and str(f.get("date"))[:10] >= cut)
        st["sec_checked"] = today.isoformat()
        st["special"] = {"kind": "merger", "form": hits[0][1], "first_filed": hits[0][0], "n": len(hits)} if hits else None
        st.pop("sec_error", None)
    except Exception as e:  # noqa: BLE001
        st["sec_error"] = str(e)[:120]
    return st.get("special")


def latest_ev(tk: str, today: date, last_earn: str | None) -> dict | None:
    best = None
    try:
        lines = EV_LEDGER.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if e.get("ticker") != tk or e.get("status") != "pending" or (e.get("horizon_days") or 0) < EV_MIN_HORIZON:
            continue
        if not e.get("ev_price") and e.get("ev_pct") is not None and e.get("spot"):
            e["ev_price"] = round(e["spot"] * (1 + e["ev_pct"] / 100), 2)
        if not e.get("ev_price"):
            continue
        if best is None or (e.get("forecast_date") or "") > (best.get("forecast_date") or ""):
            best = e
    if best is None:
        return None
    fd = best.get("forecast_date") or ""
    stale = None
    if fd < (today - timedelta(days=EV_FRESH_DAYS)).isoformat():
        stale = f"預測日 {fd} 超過 {EV_FRESH_DAYS} 天"
    elif last_earn and last_earn > fd:
        stale = f"預測日 {fd} 之後已公布財報（{last_earn}）"
    best["_stale"] = stale
    return best


def calibration() -> dict | None:
    """已驗收且有機率的樣本：樂觀／悲觀的（實際發生率 ÷ 平均預測機率），向 1 收一半。樣本不足回 None。"""
    rows = []
    try:
        for ln in EV_LEDGER.read_text(encoding="utf-8").splitlines():
            e = json.loads(ln)
            r = e.get("resolution") or {}
            if e.get("status") == "resolved" and r.get("bucket") and e.get("p_bull") is not None:
                rows.append(e)
    except Exception:  # noqa: BLE001
        return None
    n = len(rows)
    if n < CALIB_MIN_N:
        return None
    out = {"n": n}
    for cls, pk in (("bull", "p_bull"), ("bear", "p_bear")):
        pred = sum(e[pk] for e in rows) / n
        freq = 100.0 * sum(1 for e in rows if e["resolution"]["bucket"] == cls) / n
        ratio = freq / pred if pred else 1.0
        out[cls] = round(1 + (ratio - 1) * CALIB_SHRINK, 3)
    return out


def calibrated_ev_price(ev: dict, cal: dict | None) -> float | None:
    if not cal or any(ev.get(k) is None for k in ("p_bull", "p_base", "p_bear", "fv_bull", "fv_base", "fv_bear")):
        return None
    pb, pr = ev["p_bull"] * cal["bull"], ev["p_bear"] * cal["bear"]
    if pb + pr > 100:
        pb, pr = pb * 100 / (pb + pr), pr * 100 / (pb + pr)
    pm = 100 - pb - pr
    return round((pb * ev["fv_bull"] + pm * ev["fv_base"] + pr * ev["fv_bear"]) / 100, 2)


def required_ev(tk: str) -> tuple[str, float]:
    import bench_hurdle as bh
    cfg = jload(HURDLES, {"hurdle_12m_pct": {"VOO": 9.0}, "margin_pp": 10.0})
    b = bh.bench_for(tk)
    return b, cfg["hurdle_12m_pct"].get(b, cfg["hurdle_12m_pct"]["VOO"]) + cfg["margin_pp"]


# ── 判定 ──────────────────────────────────────────────────────────────────
def classify(tk: str, c: dict, close: float | None, *, pos: dict, st: dict, today: date, network: bool,
             cal: dict | None, live_decision: str | None) -> dict:
    row = {"ticker": tk, "exit": c["exit"], "exit_date": c.get("exit_date"), "close": close, "source": c["source"],
           "thesis_id": c.get("thesis_id"), "low": round(c["exit"] * BAND_LOW, 2), "high": round(c["exit"] * BAND_HIGH, 2),
           "decision_id": live_decision}

    def done(state: str, why: str) -> dict:
        row.update(state=state, why=why)
        return row

    held = {p.get("symbol") for p in pos.get("positions", [])} if isinstance(pos.get("positions"), list) else set(pos.get("positions", {}))
    if tk in held:
        return done("held", "已在倉，不是撿回條目")
    if st.get("retired"):
        return done("retired", f"{st['retired']} 已裁決不撿回")
    if close is None:
        return done("no-data", "抓不到收盤價")
    row["vs_exit_pct"] = round((close / c["exit"] - 1) * 100, 1)
    branch = "low" if close <= row["low"] else "high" if close >= row["high"] else None
    row["branch"] = branch
    if branch is None:
        return done("no-trigger", f"收盤 {close} 在 {row['low']}–{row['high']} 之內")
    if st.get("snooze_until") and st["snooze_until"] > today.isoformat():
        return done("snoozed", f"等到 {st['snooze_until']}（{st.get('snooze_why', '用戶裁決')}）")

    rv = revisions(tk, st, today, network)
    row.update(rev_up=rv["up"], rev_down=rv["down"], rev_n=rv["n"], priced_in_pct=rv["priced_in_pct"])
    if not rv["have"]:
        return done("no-data", "基本面快取沒有修正數字")
    ok = (rv["down"] <= rv["up"]) if branch == "low" else (rv["up"] > rv["down"])
    if rv["n"] < MIN_ANALYSTS:
        return done("revision-fail", f"分析師只有 {rv['n']} 位（<{MIN_ANALYSTS}），修正不單獨成立")
    if not ok:
        need = "下修 ≤ 上修" if branch == "low" else "上修 > 下修"
        return done("revision-fail", f"30 日修正 {rv['up']}↑:{rv['down']}↓，{'回檔' if branch == 'low' else '走強'}分支要 {need}")

    last_e, next_e = earnings_dates(tk, today) if network else (st.get("last_earnings"), st.get("next_earnings"))
    if network:
        st["last_earnings"], st["next_earnings"] = last_e, next_e
    row.update(last_earnings=last_e, next_earnings=next_e)
    if last_e:
        row["rev_age_days"] = (today - date.fromisoformat(last_e)).days
        row["rev_stale"] = row["rev_age_days"] > REV_STALE_DAYS

    sp = merger_filing(tk, st, today, network)
    if sp and not st.get("special_ack"):
        row["special"] = sp
        return done("special", f"{sp['first_filed']} 起有併購類申報（{sp['form']}，共 {sp['n']} 份）")

    n_pos, max_pos = pos.get("n_positions") or 0, pos.get("max_positions") or 18
    if n_pos >= max_pos:
        return done("blocked", f"名額滿（{n_pos}/{max_pos}），要先砍一檔")
    if next_e and 0 <= (date.fromisoformat(next_e) - today).days <= EARNINGS_BLACKOUT_DAYS:
        return done("blocked", f"財報 {next_e} 在 ±48 小時內")
    bench, req = required_ev(tk)
    row.update(bench=bench, required_ev_pct=req)
    sg = (pos.get("sector_gate") or {}).get(bench if bench in ("SMH", "IGV") else "SPY") or {}
    if branch == "high" and sg.get("extended"):
        return done("blocked", f"走強分支遇 {bench} 高於 50 日線 {sg.get('ext_sma50_pct')}%（R31），只准回檔買")

    ev = latest_ev(tk, today, last_e)
    if ev is None or ev["_stale"]:
        row["ev_stale_why"] = ev["_stale"] if ev else "沒有 365 日 EV"
        return done("needs-ev", row["ev_stale_why"])
    ev_pct = round((ev["ev_price"] / close - 1) * 100, 1)
    calp = calibrated_ev_price(ev, cal)
    row.update(ev_id=ev["id"], ev_forecast_date=ev.get("forecast_date"), ev_price=ev["ev_price"], ev_pct=ev_pct,
               ev_cal_pct=round((calp / close - 1) * 100, 1) if calp else None,
               scenarios=[[ev.get("p_bull"), ev.get("fv_bull")], [ev.get("p_base"), ev.get("fv_base")], [ev.get("p_bear"), ev.get("fv_bear")]],
               threshold_price=round(ev["ev_price"] / (1 + req / 100), 2))
    if ev_pct < req:
        return done("ev-fail", f"12 個月預期報酬 {ev_pct:+.1f}% < 門檻 {req:.0f}%（跌到 {row['threshold_price']} 以下才過）")
    return done("ready", f"12 個月預期報酬 {ev_pct:+.1f}% ≥ 門檻 {req:.0f}%")


# ── 決定卡 ────────────────────────────────────────────────────────────────
def starter(row: dict, pos: dict) -> dict:
    total = pos.get("total_account_value") or 0
    pct = STARTER_PCT_RICH if (row.get("priced_in_pct") or 0) > 150 else STARTER_PCT
    budget = min(total * pct, STARTER_CAP_USD)
    px = row["close"]
    sh = int(budget // px) if px else 0
    cost = round(sh * px, 2)
    head = (pos.get("cash") or 0) - (pos.get("pending_buy_notional") or 0) - CASH_BUFFER
    return {"shares": sh, "limit": px, "cost": cost, "weight_pct": round(cost / total * 100, 1) if total else None,
            "cash_headroom": round(head, 2), "cash_short": round(max(0.0, cost - head), 2)}


def md(d: str | None) -> str:
    return date.fromisoformat(d).strftime("%m/%d") if d else "—"


def card(row: dict, pos: dict, cal: dict | None, today: date) -> dict:
    tk, s = row["ticker"], starter(row, pos)
    br = "回檔分支" if row["branch"] == "low" else "走強分支"
    lines = [f"收盤 ${row['close']}｜出場價 ${row['exit']}（{row['vs_exit_pct']:+.1f}%）｜{br}",
             f"12 個月預期報酬 {row['ev_pct']:+.1f}%（門檻 {row['required_ev_pct']:.0f}%）"]
    if row.get("ev_cal_pct") is not None:
        warn = "，低於門檻" if row["ev_cal_pct"] < row["required_ev_pct"] else ""
        lines.append(f"扣歷史偏差後 {row['ev_cal_pct']:+.1f}%{warn}（已驗收 {cal['n']} 筆）")
    sc = row.get("scenarios") or []
    if sc and all(p is not None and v is not None for p, v in sc):
        lines.append("三情境：" + "／".join(f"{p:g}% ${v:g}" for p, v in sc))
    rev = f"30 日修正 {row['rev_up']}↑:{row['rev_down']}↓（{row['rev_n']} 位）"
    if row.get("rev_stale"):
        rev += f"，距上次財報 {row['rev_age_days']} 天、數字偏舊"
    lines.append(rev)
    if row.get("next_earnings"):
        lines.append(f"下次財報 {md(row['next_earnings'])}（{(date.fromisoformat(row['next_earnings']) - today).days} 天後）")
    lines.append(f"名額 {pos.get('n_positions')}/{pos.get('max_positions')}｜EV 預測日 {md(row.get('ev_forecast_date'))}")
    if s["cash_short"] > 0:
        lines.append(f"可動用現金 ${s['cash_headroom']:,.0f}，不夠 ${s['cash_short']:,.0f}，要先賣停泊的 VOO")
    wait_to = (date.fromisoformat(row["next_earnings"]) + timedelta(days=1)) if row.get("next_earnings") and \
        (date.fromisoformat(row["next_earnings"]) - today).days <= 45 else today + timedelta(days=SNOOZE_DEFAULT_DAYS)
    wait_label = f"等 {wait_to.strftime('%m/%d')}" + ("（財報後）再看" if row.get("next_earnings") and wait_to.isoformat() > row["next_earnings"] else " 再看")
    opts = [
        f"buy=買起手倉 {s['shares']} 股 @{s['limit']}=下一次簡報掛長效限價買單 {s['shares']} 股 @${s['limit']}，約 ${s['cost']:,.0f}（帳戶 {s['weight_pct']}%）",
        f"wait={wait_label}=到 {wait_to.strftime('%m/%d')} 前不再問，之後用新數字重算",
        "skip=不撿回，撤條目=撤掉撿回條目與警報，之後不再追蹤這檔",
    ]
    return {"id": f"reentry-{tk}-{today.strftime('%Y%m%d')}", "ticker": tk, "question": f"{tk} 過了新倉門檻，要撿回嗎？",
            "detail": "\n".join(lines), "options": opts, "expires": (today + timedelta(days=ASK_EXPIRE_DAYS)).isoformat(),
            "wait_to": wait_to.isoformat(), "starter": s}


def special_card(row: dict, today: date) -> dict:
    tk, sp = row["ticker"], row["special"]
    return {"id": f"reentry-{tk}-special", "ticker": tk,
            "question": f"{tk} 有併購類申報，撿回條目要撤嗎？",
            "detail": f"{md(sp['first_filed'])} 起有 {sp['n']} 份併購類申報（{sp['form']}）。被收購後股價由收購條件決定，原本的撿回理由可能不適用。\n"
                      f"收盤 ${row['close']}｜出場價 ${row['exit']}（{row['vs_exit_pct']:+.1f}%）",
            "options": ["retire=撤掉撿回條目=撤掉條目與警報，之後不再追蹤這檔",
                        "keep=保留，照一般流程評估=當成一般個股繼續跑預期報酬與門檻"],
            "expires": (today + timedelta(days=ASK_EXPIRE_DAYS)).isoformat()}


def add_decision(c: dict, dry: bool) -> str:
    if dry:
        return "dry-run"
    cmd = [sys.executable, str(TOOLS / "decision_ledger.py"), "add", "--id", c["id"], "--ticker", c["ticker"],
           "--question", c["question"], "--detail", c["detail"], "--expires", c["expires"]]
    for o in c["options"]:
        cmd += ["--option", o]
    rc, out = run(cmd, timeout=60)
    try:
        return json.loads(out).get("action", f"rc={rc}")
    except ValueError:
        return f"rc={rc} {out[:120]}"


# ── 副作用 ────────────────────────────────────────────────────────────────
def disable_reentry_alerts(dry: bool) -> list[str]:
    """撿回價格警報改由本腳本判定 → 關掉每日重複響（LRCX 低線響了 22 次）。警報條目保留當價位紀錄。"""
    data = jload(ALERTS, {"alerts": []})
    hit = []
    for a in data.get("alerts", []):
        if re.search(r"-reentry-(low|high)$", a.get("id", "")) and a.get("status") != "disabled":
            a["status"] = "disabled"
            a["disabled_reason"] = "reentry_gate.py 接手判定（2026-11-12）"
            hit.append(a["id"])
    if hit and not dry:
        jsave(ALERTS, data)
    return hit


def retire(tk: str, c: dict | None, st: dict, today: date, why: str) -> list[str]:
    done = []
    data = jload(ALERTS, {"alerts": []})
    keep = [a for a in data.get("alerts", []) if not re.match(rf"^{re.escape(tk)}-reentry-(low|high)$", a.get("id", ""))]
    if len(keep) != len(data.get("alerts", [])):
        data["alerts"] = keep
        jsave(ALERTS, data)
        done.append("警報已撤")
    tid = (c or {}).get("thesis_id") or f"{tk}:reentry-dual-branch"
    rc, out = run([sys.executable, str(TOOLS / "thesis_ledger.py"), "close-untested", "--id", tid,
                   "--exit-date", today.isoformat(), "--note", why], timeout=60)
    done.append("撿回條目已結" if rc == 0 else f"撿回條目未結（{out.strip()[:80]}）")
    st["retired"] = today.isoformat()
    st["retired_why"] = why
    return done


def shadow(tk: str, px: float, note: str) -> None:
    run([sys.executable, str(TOOLS / "shadow_signals.py"), "record", "--kind", "cf-reentry", "--ticker", tk,
         "--price", str(px), "--correct-if", "under", "--note", note], timeout=60)


def apply_answers(state: dict, cands: dict, today: date, dry: bool) -> list[dict]:
    """處理 reentry-* 決定：skip／retire → 撤；wait → 延後；keep → 記下不再問；buy 留給 briefing 掛單。過期未按 → 延後 14 天。"""
    out = []
    data = jload(DECISIONS, {"decisions": []})
    for d in data.get("decisions", []):
        if not d.get("id", "").startswith("reentry-") or not d.get("ticker"):
            continue
        tk, st = d["ticker"], tstate(state, d["ticker"])
        if d["status"] == "expired" and st.get("handled") != d["id"]:
            st.update(snooze_until=(today + timedelta(days=SNOOZE_DEFAULT_DAYS)).isoformat(), snooze_why="卡片過期未按", handled=d["id"])
            out.append({"id": d["id"], "result": "過期未按 → 14 天內不再問"})
            continue
        if d["status"] != "answered" or st.get("handled") == d["id"]:
            continue
        key, note = (d.get("answer") or {}).get("key"), None
        if dry:
            out.append({"id": d["id"], "key": key, "result": "dry-run"})
            continue
        if key in ("skip", "retire"):
            note = "；".join(retire(tk, cands.get(tk), st, today, f"用戶 Telegram 按鈕裁決不撿回（{d['id']}）"))
            px = st.get("last_close")
            if px:
                shadow(tk, px, f"reentry_gate：用戶裁決不撿回（{d['id']}）；30d 跑輸 = 不撿對")
        elif key == "wait":
            to = st.get("wait_to") or (today + timedelta(days=SNOOZE_DEFAULT_DAYS)).isoformat()
            st.update(snooze_until=to, snooze_why="用戶按「等」")
            note = f"延到 {to} 再評估"
        elif key == "keep":
            st["special_ack"] = True
            note = "保留條目，照一般流程評估"
        elif key == "buy":
            st["handled"] = d["id"]            # 掛單由 briefing 照 T6.5 條件執行並 done；這裡不動
            out.append({"id": d["id"], "key": key, "result": "留給 briefing 掛單"})
            continue
        if note:
            run([sys.executable, str(TOOLS / "decision_ledger.py"), "done", "--id", d["id"], "--note", f"reentry_gate：{note}"], timeout=60)
            st["handled"] = d["id"]
            out.append({"id": d["id"], "key": key, "result": note})
    return out


# ── 主流程 ────────────────────────────────────────────────────────────────
def scan(a) -> int:
    today = date.fromisoformat(a.asof) if a.asof else today_et()
    network, dry = not a.no_network, a.dry_run
    state = jload(STATE, {"tickers": {}})
    cands = candidates(today)
    applied = apply_answers(state, cands, today, dry)
    pos = jload(POS_STATE, {})
    manual = {}
    for kv in (a.prices or "").split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            manual[k.strip().upper()] = float(v)
    closes = dict(manual)
    need = [t for t in cands if t not in closes]
    if need and network:
        try:
            closes.update(fetch_closes(need))
        except Exception as e:  # noqa: BLE001
            print(f"warn: 抓收盤價失敗：{e}", file=sys.stderr)
    cal = calibration()
    live = {d["ticker"]: d["id"] for d in jload(DECISIONS, {"decisions": []}).get("decisions", [])
            if d.get("id", "").startswith("reentry-") and d.get("status") in ("open", "answered") and d.get("ticker")}
    rows, queue, asked = [], [], []
    for tk in sorted(cands):
        st = tstate(state, tk)
        if closes.get(tk):
            st["last_close"] = closes[tk]
        row = classify(tk, cands[tk], closes.get(tk), pos=pos, st=st, today=today, network=network, cal=cal, live_decision=live.get(tk))
        s = row["state"]
        if s == "needs-ev":
            last = st.get("last_ev_run")
            if not last or (today - date.fromisoformat(last)).days >= (EV_RETRY_DAYS if st.get("last_ev_result") == "fail" else 1):
                queue.append(tk)
            else:
                row["why"] += f"；{last} 已跑過（{st.get('last_ev_result')}），{EV_RETRY_DAYS} 天後再試"
        elif s == "ev-fail":
            key = f"{row['ev_id']}@{row['ev_forecast_date']}"
            if st.get("shadow_logged") != key and not dry:
                shadow(tk, row["close"], f"reentry_gate：R35 不過（EV {row['ev_pct']:+.1f}% < {row['required_ev_pct']:.0f}%），不撿回；30d 跑輸 = 不撿對")
                st["shadow_logged"] = key
        elif s in ("ready", "special") and not live.get(tk):
            c = card(row, pos, cal, today) if s == "ready" else special_card(row, today)
            ask_key = f"{s}:{row.get('ev_id')}@{row.get('ev_forecast_date')}"
            if st.get("asked_key") != ask_key or st.get("last_state") not in ("ready", "special"):
                res = add_decision(c, dry)
                row["decision_id"] = c["id"]
                asked.append({"id": c["id"], "result": res})
                if not dry and res == "opened":
                    st.update(asked_key=ask_key, last_asked=today.isoformat(), wait_to=c.get("wait_to"))
                if dry:
                    row["card_preview"] = c
        if not dry:
            st["last_state"] = s
        rows.append(row)
    queue = queue[:EV_RUNS_PER_DAY]
    disabled = disable_reentry_alerts(dry)
    out = {"asof": today.isoformat(), "generated_at": datetime.now(ET).isoformat(timespec="seconds"), "calibration": cal,
           "rows": rows, "queue": queue, "asked": asked, "applied": applied, "alerts_disabled": disabled, "dry_run": dry}
    if not dry:
        jsave(OUT, out)
        jsave(STATE, state)
    print(json.dumps(out if a.json else {"asof": out["asof"], "states": {r["ticker"]: f"{r['state']}｜{r['why']}" for r in rows},
                                         "queue": queue, "asked": asked, "applied": applied, "alerts_disabled": disabled},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_apply(a) -> int:
    state = jload(STATE, {"tickers": {}})
    today = today_et()
    res = apply_answers(state, candidates(today), today, a.dry_run)
    if not a.dry_run:
        jsave(STATE, state)
    print(json.dumps({"applied": res}, ensure_ascii=False, indent=2))
    return 0


def cmd_status(_a) -> int:
    d = jload(OUT, None)
    if not d:
        print("尚無 scan 結果")
        return 1
    print(f"撿回閘門 {d['asof']}（{d['generated_at']}）")
    for r in d["rows"]:
        ev = f"｜EV {r['ev_pct']:+.1f}%／門檻 {r['required_ev_pct']:.0f}%" if r.get("ev_pct") is not None else ""
        print(f"  {r['ticker']:5s} {r['state']:13s} 收 {r.get('close')}｜出場 {r['exit']}{ev}｜{r['why']}")
    if d.get("queue"):
        print("待跑 EV：" + "、".join(d["queue"]))
    return 0


def cmd_queue(_a) -> int:
    for t in (jload(OUT, {}) or {}).get("queue", []):
        print(t)
    return 0


def cmd_mark_run(a) -> int:
    state = jload(STATE, {"tickers": {}})
    st = tstate(state, a.ticker.upper())
    st.update(last_ev_run=today_et().isoformat(), last_ev_result=a.result)
    jsave(STATE, state)
    return 0


def cmd_has_ev(a) -> int:
    """runner 用：預測帳有沒有這檔在指定日期登的 365 日 EV。有 → exit 0。"""
    try:
        for ln in EV_LEDGER.read_text(encoding="utf-8").splitlines():
            e = json.loads(ln)
            if (e.get("ticker") == a.ticker.upper() and (e.get("horizon_days") or 0) >= EV_MIN_HORIZON
                    and e.get("forecast_date") == a.day and e.get("status") == "pending"):
                return 0
    except Exception:  # noqa: BLE001
        pass
    return 1


def selftest(_a) -> int:
    t = date(2026, 11, 12)
    ev = {"id": "X:e", "forecast_date": "2026-11-12", "ev_price": 185.13, "p_bull": 27, "p_base": 31, "p_bear": 42,
          "fv_bull": 315, "fv_base": 197.5, "fv_bear": 92.5}
    cal = {"n": 7, "bull": 0.725, "bear": 1.557}
    cp = calibrated_ev_price(ev, cal)
    assert abs(cp - 151.84) < 0.05, cp  # 27×0.725／42×1.557 重配後；11/12 人工四捨五入機率算的是 $152.75
    assert exit_price_of({"ev_snapshot": "出場價 537.41；flag X"}) == 537.41
    assert exit_price_of({"thesis": "2026-09-30 出場 @322.50（用戶…"}) == 322.5
    pos = {"positions": [{"symbol": "NVDA"}], "n_positions": 14, "max_positions": 18, "total_account_value": 227211.09,
           "cash": 13521.27, "pending_buy_notional": 0, "sector_gate": {"SMH": {"extended": False}}}
    base = {"exit": 100.0, "thesis_id": "X:reentry-dual-branch", "source": "thesis"}
    r = classify("X", base, 100.0, pos=pos, st={}, today=t, network=False, cal=cal, live_decision=None)
    assert r["state"] == "no-trigger", r
    r = classify("NVDA", base, 80.0, pos=pos, st={}, today=t, network=False, cal=cal, live_decision=None)
    assert r["state"] == "held", r
    r = classify("X", base, 80.0, pos=pos, st={"retired": "2026-11-01"}, today=t, network=False, cal=cal, live_decision=None)
    assert r["state"] == "retired", r
    r = classify("X", base, 80.0, pos=pos, st={"snooze_until": "2026-12-02"}, today=t, network=False, cal=cal, live_decision=None)
    assert r["state"] == "snoozed", r
    s = starter({"close": 139.81, "priced_in_pct": -61.6}, pos)
    assert s["shares"] == 21 and s["cash_short"] == 0, s  # $3,000 上限 → 21 股，現金夠
    s = starter({"close": 139.81, "priced_in_pct": -61.6}, {**pos, "cash": 9000})
    assert s["cash_short"] > 0, s
    print("selftest ok")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="撿回名單機械閘門")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--no-network", action="store_true")
    s.add_argument("--prices", default="")
    s.add_argument("--asof", default=None)
    s.add_argument("--json", action="store_true")
    ap = sub.add_parser("apply")
    ap.add_argument("--dry-run", action="store_true")
    sub.add_parser("status")
    sub.add_parser("queue")
    m = sub.add_parser("mark-run")
    m.add_argument("ticker")
    m.add_argument("result", choices=["ok", "fail"])
    h = sub.add_parser("has-ev")
    h.add_argument("ticker")
    h.add_argument("day")
    sub.add_parser("selftest")
    a = p.parse_args()
    return {"scan": scan, "has-ev": cmd_has_ev, "apply": cmd_apply, "status": cmd_status, "queue": cmd_queue, "mark-run": cmd_mark_run,
            "selftest": selftest}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
