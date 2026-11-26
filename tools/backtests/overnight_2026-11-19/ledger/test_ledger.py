"""PF 的單元測試：全部用人造資料（不含任何帳戶資料）。

用法：python -B test_ledger.py
最後一項 test_no_trade_data_in_code 會讀帳本的代號清單，只用來確認程式碼裡沒有寫死任何交易過的代號。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ledger_common as C  # noqa: E402
import pf_run as P  # noqa: E402


def _fill(row, date, sym, side, qty, price, origin="unknown", **kw):
    amt = qty * price * (-1 if side == "BOUGHT" else 1)
    return {"row": row, "date": date, "symbol": sym, "side": side, "qty": float(qty),
            "price": float(price), "amount": amt, "notional": qty * price, "origin": origin, **kw}


def test_implied_split_factor():
    assert C.implied_split_factor(1000.0, 100.0) == (10.0, True)
    assert C.implied_split_factor(100.0, 98.0) == (1.0, True)
    k, ok = C.implied_split_factor(5.5, 50.0)           # 反向拆股 1:10，還原價含股息所以比值偏高
    assert ok and abs(k - 0.1) < 1e-12
    k, ok = C.implied_split_factor(226.0, 100.0)        # 2:1 加上累積股息
    assert ok and k == 2.0
    assert C.implied_split_factor(170.0, 100.0) == (1.0, False)   # 判不出來
    assert C.implied_split_factor(np.nan, 100.0) == (1.0, False)


def test_implied_split_factors_borrow():
    cal = pd.bdate_range("2024-01-01", periods=10)
    arr = np.array([10.0] * 10)
    arr[3] = np.nan
    book = {"ZZA": [("s", arr)]}
    fills = [_fill(0, str(cal[0].date()), "ZZA", "BOUGHT", 1, 100.0),     # 10:1
             _fill(1, str(cal[3].date()), "ZZA", "BOUGHT", 1, 100.0),     # 當天沒價 -> 借最近一筆
             _fill(2, str(cal[8].date()), "ZZA", "SOLD", 20, 10.0)]
    fac, info = C.implied_split_factors(fills, cal, book)
    assert fac == {0: 10.0, 1: 10.0, 2: 1.0}
    assert info["n_fills_factor_borrowed_from_nearest_fill"] == 1


def test_fifo_basic_and_split():
    fills = [_fill(0, "2024-01-02", "ZZA", "BOUGHT", 1, 1000.0),          # 之後 10:1 拆股
             _fill(1, "2024-02-01", "ZZA", "BOUGHT", 10, 110.0),
             _fill(2, "2024-03-01", "ZZA", "SOLD", 15, 120.0),
             _fill(3, "2024-03-05", "ZZA", "SOLD", 10, 130.0)]             # 其中 5 股沒有對應買進
    fac = {0: 10.0, 1: 1.0, 2: 1.0, 3: 1.0}
    pc, info, lots = C.fifo_pieces(fills, lambda f: fac[f["row"]])
    assert len(pc) == 3
    assert list(pc.buy_row) == [0, 1, 1] and list(pc.sell_row) == [2, 2, 3]
    assert np.allclose(pc.qty, [10, 5, 5])
    assert np.allclose(pc.cost, [1000.0, 550.0, 550.0])
    assert np.allclose(pc.proceeds, [1200.0, 600.0, 650.0])
    assert np.allclose(pc.pnl, [200.0, 50.0, 100.0])
    assert info["n_sells_partially_unmatched"] == 1 and info["n_sells_fully_unmatched"] == 0
    assert abs(info["unmatched_sell_proceeds"] - 650.0) < 1e-9
    # 不做拆股調整時，同一批成交會配錯
    pc2, _, _ = C.fifo_pieces(fills, lambda f: 1.0)
    assert not np.allclose(pc2.pnl.sum(), pc.pnl.sum())


def test_seeded_fifo():
    fills = [_fill(0, "2024-01-02", "ZZA", "SOLD", 5, 10.0),               # 賣的是帳本之前的庫存
             _fill(1, "2024-01-03", "ZZA", "BOUGHT", 5, 10.0),
             _fill(2, "2024-01-10", "ZZA", "SOLD", 5, 12.0)]
    fac = {0: 1.0, 1: 1.0, 2: 1.0}
    seeds, before = P.pre_ledger_seeds(fills, fac)
    assert seeds == {"ZZA": 5.0} and before == {1: 0.0}
    sf = P.seeded_fills(fills, seeds)
    pc, info, _ = C.fifo_pieces(sf, lambda f: f.get("_factor") if "_factor" in f else fac[f["row"]])
    assert list(pc.buy_row) == [-1, 1] and info["n_sells_fully_unmatched"] == 0
    pc0, info0, _ = C.fifo_pieces(fills, lambda f: 1.0)
    assert info0["n_sells_fully_unmatched"] == 1 and list(pc0.buy_row) == [1]


def test_counterfactual_no_stop():
    #            0     1     2     3     4     5
    arr = np.array([100., 102., 104., 110., 120., 130.])
    spy = np.array([100., 100., 100., 101., 102., 103.])
    alt = {"SPY": spy, "CASH": None}
    # 成本 1000（10 股 @100），第 2 天以 104 賣出，T = 第 5 天
    r = P.counterfactual_piece(1040.0, 1000.0, arr, 0, 2, 5, alt)
    assert abs(r["hold_ratio"] - 130 / 104) < 1e-12
    assert abs(r["diff_CASH"] - (1300.0 - 1040.0)) < 1e-9
    assert abs(r["diff_SPY"] - (1300.0 - 1040.0 * 1.03)) < 1e-9
    assert r["stop_triggered"] is False and r["diffstop_SPY"] == r["diff_SPY"]


def test_counterfactual_with_stop():
    arr = np.array([100., 95., 90., 74., 60., 120.])
    spy = np.array([100., 100., 100., 100., 110., 121.])
    alt = {"SPY": spy, "CASH": None}
    # 第 1 天以 95 賣出（賠 5%）。不賣的話第 3 天收 74 <= 75 觸發停損，之後放 SPY。
    r = P.counterfactual_piece(950.0, 1000.0, arr, 0, 1, 5, alt)
    assert r["stop_triggered"] and not r["stop_before_actual_sale"]
    assert abs(r["diff_CASH"] - (1200.0 - 950.0)) < 1e-9
    assert abs(r["diffstop_CASH"] - (740.0 - 950.0)) < 1e-9
    assert abs(r["diffstop_SPY"] - (740.0 * 1.21 - 950.0 * 1.21)) < 1e-9
    # 實際賣得比停損還晚：第 4 天以 60 賣出，停損在第 3 天就該出場
    r2 = P.counterfactual_piece(600.0, 1000.0, arr, 0, 4, 5, alt)
    assert r2["stop_triggered"] and r2["stop_before_actual_sale"]
    assert abs(r2["diffstop_CASH"] - (740.0 - 600.0)) < 1e-9
    assert abs(r2["diffstop_SPY"] - (740.0 * 1.21 - 600.0 * 1.10)) < 1e-9


def test_pf2_status():
    cal = pd.bdate_range("2024-01-01", periods=200)
    arr = np.linspace(100, 200, 200)
    short = arr.copy()
    short[150:] = np.nan
    book = {"ZZA": [("s", arr)], "ZZB": [("s", short)]}
    d = lambda i: str(cal[i].date())  # noqa: E731
    pieces = pd.DataFrame([
        {"symbol": "ZZA", "buy_row": 0, "sell_row": 1, "buy_date": d(0), "sell_date": d(10),
         "qty": 1, "cost": 100.0, "proceeds": 105.0, "pnl": 5.0, "buy_origin": "user", "sell_origin": "user"},
        {"symbol": "ZZA", "buy_row": 2, "sell_row": 3, "buy_date": d(0), "sell_date": d(70),
         "qty": 1, "cost": 100.0, "proceeds": 105.0, "pnl": 5.0, "buy_origin": "user", "sell_origin": "user"},
        {"symbol": "ZZA", "buy_row": 4, "sell_row": 5, "buy_date": d(150), "sell_date": d(160),
         "qty": 1, "cost": 100.0, "proceeds": 105.0, "pnl": 5.0, "buy_origin": "user", "sell_origin": "user"},
        {"symbol": "ZZB", "buy_row": 6, "sell_row": 7, "buy_date": d(100), "sell_date": d(110),
         "qty": 1, "cost": 100.0, "proceeds": 105.0, "pnl": 5.0, "buy_origin": "user", "sell_origin": "user"},
    ], columns=C.PIECE_COLS)
    alt = {"SPY": np.full(200, 100.0), "SMH": np.full(200, 100.0), "CASH": None}
    pp = P.pf2_pieces(pieces, cal, 199, book, alt)
    st = {(r.buy_row, r.N): r.status for r in pp.itertuples()}
    assert st[(0, 21)] == "ok" and st[(0, 63)] == "ok" and st[(0, 126)] == "ok"
    assert st[(2, 21)] == "held_at_least_N" and st[(2, 63)] == "held_at_least_N" and st[(2, 126)] == "ok"
    assert st[(4, 21)] == "ok" and st[(4, 63)] == "horizon_past_data_end"
    assert st[(6, 21)] == "ok" and st[(6, 63)] == "no_price_cover"
    r = pp[(pp.buy_row == 0) & (pp.N == 21)].iloc[0]
    assert abs(r.diff_CASH - 105.0 * (arr[21] / arr[10] - 1)) < 1e-9
    s = P.pf2_summarise(pp, "t")
    a = s[(s.N == 21) & (s.cut_type == "all") & (s.alt == "CASH") & (s.version == "no_stop")].iloc[0]
    assert a.n_pieces == 3 and a.n_pieces_held_under_N == 3


def test_r14_episodes():
    fac = {i: 1.0 for i in range(20)}
    fills = [
        # A：建倉後 10 天清倉 -> 違反（清倉）
        _fill(0, "2026-08-03", "ZZA", "BOUGHT", 10, 10.0), _fill(1, "2026-08-13", "ZZA", "SOLD", 10, 9.0),
        # B：第 30 天才清倉 -> 不算（鎖是 days < 30）
        _fill(2, "2026-08-03", "ZZB", "BOUGHT", 10, 10.0), _fill(3, "2026-09-02", "ZZB", "SOLD", 10, 9.0),
        # C：窗內賣 4/10，再賣 2/10 -> 累計 60% > 一半（減碼過半）
        _fill(4, "2026-08-03", "ZZC", "BOUGHT", 10, 10.0), _fill(5, "2026-08-10", "ZZC", "SOLD", 4, 11.0),
        _fill(6, "2026-08-20", "ZZC", "SOLD", 2, 11.0),
        # D：加碼後賣掉不到累計買進的一半 -> 不算
        _fill(7, "2026-08-03", "ZZD", "BOUGHT", 10, 10.0), _fill(8, "2026-08-05", "ZZD", "BOUGHT", 10, 10.0),
        _fill(9, "2026-08-10", "ZZD", "SOLD", 10, 11.0),
        # E：生效日之前建倉 -> 不列入
        _fill(10, "2026-07-01", "ZZE", "BOUGHT", 10, 10.0), _fill(11, "2026-07-05", "ZZE", "SOLD", 10, 9.0),
        # F：舊倉加碼（不是由零建倉）-> 不列入
        _fill(12, "2026-06-01", "ZZF", "BOUGHT", 10, 10.0), _fill(13, "2026-08-03", "ZZF", "BOUGHT", 5, 10.0),
        _fill(14, "2026-08-04", "ZZF", "SOLD", 15, 9.0),
    ]
    fills = sorted(fills, key=lambda f: f["date"])
    for i, f in enumerate(fills):
        f["old"] = f["row"]
    eps = {e["symbol"]: e for e in P.r14_episodes(fills, fac)}
    assert set(eps) == {"ZZA", "ZZB", "ZZC", "ZZD"}
    assert eps["ZZA"]["breach"] == "清倉" and eps["ZZA"]["breach_days"] == 10
    assert eps["ZZB"]["breach"] == "" and eps["ZZB"]["closed_days"] == 30
    assert eps["ZZC"]["breach"] == "減碼過半" and eps["ZZC"]["breach_date"] == "2026-08-20"
    assert eps["ZZD"]["breach"] == "" and abs(eps["ZZD"]["max_sold_frac_in_window"] - 0.5) < 1e-12


def test_label_category():
    assert P.label_category("journal 明文記為 R14 bypass") == "bypass"
    assert P.label_category("例外 1：thesis 證偽條件") == "exception_1"
    assert P.label_category("例外 3：旗標 forced") == "exception_3"
    assert P.label_category("未記錄") == "unrecorded" and P.label_category(None) == "unrecorded"
    assert P.auto_label(["[2026-01-01] 這筆是 R14 bypass，由使用者推翻"]) == "journal 明文記為 R14 bypass"
    assert P.auto_label(["[2026-01-01] 只是一般的賣出記錄"]) == P.UNRECORDED


def test_bootstrap():
    x = np.array([1.0, 2.0, 3.0, 4.0, -1.0, 5.0])
    cl = np.array(["a", "a", "b", "b", "c", "c"])
    lo, hi, M = C.cluster_boot_total(x, cl, n_boot=4000, seed=1)
    assert M == 3 and lo <= x.sum() <= hi
    assert (lo, hi, M) == C.cluster_boot_total(x, cl, n_boot=4000, seed=1)       # 可重現
    lo1, hi1, M1 = C.cluster_boot_total(x, np.array(["a"] * 6))
    assert M1 == 1 and np.isnan(lo1)
    # 每個群的總和都一樣 -> 區間退化成一點
    lo2, hi2, _ = C.cluster_boot_total(np.array([1.0, 1.0, 2.0]), np.array(["a", "a", "b"]), n_boot=500)
    assert abs(lo2 - 4.0) < 1e-12 and abs(hi2 - 4.0) < 1e-12
    ci = C.cluster_boot_mean(x, np.ones(6), cl, n_boot=2000, seed=1)
    assert ci["ew_lo"] <= x.mean() <= ci["ew_hi"] and abs(ci["ew_lo"] - ci["nw_lo"]) < 1e-12


def _reading_frame(spy, smh, spy_years, smh_years):
    """spy／smh = (總差額, 區間下界, 區間上界)；*_years = (2025 的差額, 2026 的差額)。"""
    rows = []
    for alt, (tot, lo, hi), (a, b) in (("SPY", spy, spy_years), ("SMH", smh, smh_years)):
        rows.append({"fifo_variant": "v", "version": "no_stop", "N": 63, "alt": alt, "cut_type": "all",
                     "cut_value": "all", "n_pieces": 10, "diff_total": tot, "ci_lo": lo, "ci_hi": hi})
        for y, v in (("2025", a), ("2026", b)):
            rows.append({"fifo_variant": "v", "version": "no_stop", "N": 63, "alt": alt,
                         "cut_type": "buy_year", "cut_value": y, "n_pieces": 5, "diff_total": v,
                         "ci_lo": np.nan, "ci_hi": np.nan})
    return pd.DataFrame(rows)


def test_prewritten_reading():
    ok = P.prewritten_reading(_reading_frame((10, 1, 20), (10, 2, 30), (3, 7), (4, 6)), "v", "no_stop")
    assert ok["extend_r14_to_63_supported"] is True
    # 區間跨 0
    r = P.prewritten_reading(_reading_frame((10, -1, 20), (10, 2, 30), (3, 7), (4, 6)), "v", "no_stop")
    assert r["extend_r14_to_63_supported"] is False and r["checks"]["SPY"]["ci_excludes_zero"] is False
    # 對 SMH 為負（區間不含 0 但方向相反）
    r = P.prewritten_reading(_reading_frame((10, 1, 20), (-10, -30, -2), (3, 7), (-4, -6)), "v", "no_stop")
    assert r["extend_r14_to_63_supported"] is False and r["checks"]["SMH"]["ci_excludes_zero"] is True
    # 兩個年度不同向
    r = P.prewritten_reading(_reading_frame((10, 1, 20), (10, 2, 30), (-3, 13), (4, 6)), "v", "no_stop")
    assert r["extend_r14_to_63_supported"] is False and r["checks"]["SPY"]["years_same_sign"] is False


def test_pf3_table():
    cal = pd.bdate_range("2024-01-01", periods=200)
    arr = np.linspace(100, 200, 200)
    bench = {"SMH": np.linspace(100, 150, 200), "QQQ": np.full(200, 100.0)}
    fills = [_fill(0, str(cal[0].date()), "ZZA", "BOUGHT", 1, 100.0),
             _fill(1, str(cal[100].date()), "ZZB", "BOUGHT", 1, 100.0),
             _fill(2, str(cal[150].date()), "ZZA", "SOLD", 1, 100.0)]
    ft = P.pf3_table(fills, cal, 199, {"ZZA": [("s", arr)], "ZZB": [("s", arr)]}, bench, {"ZZA"}, {0, 1})
    assert len(ft) == 4
    a = ft[(ft.row == 0) & (ft.H == 63)].iloc[0]
    assert a.group == "半導體／AI 硬體" and abs(a.ret - (arr[63] / arr[0] - 1)) < 1e-12
    assert abs(a.ex_QQQ - a.ret) < 1e-12
    b = ft[(ft.row == 1) & (ft.H == 126)].iloc[0]
    assert b.status == "horizon_past_data_end" and b.group == "其他"
    s = P.pf3_summarise(ft)
    assert set(s.period) == {"全部", "R35 之前", "R35 之後"}


def test_silver_is_capped():
    assert C.SILVER_END == "2025-12-31"
    src = (HERE / "ledger_common.py").read_text(encoding="utf-8")
    assert 'pc.field("date") <= SILVER_END' in src


def test_no_forbidden_paths():
    for name in ("ledger_common.py", "pf_run.py", "pf_report.py"):
        path = HERE / name
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8").lower()
        code = "\n".join(line for line in src.split("\n") if "/" in line and ("path(" in line or "repo /" in line or "data /" in line))
        for bad in ("holdout", "forward", "sealed-input"):
            assert bad not in code, f"{name} references a forbidden path fragment: {bad}"


def test_no_trade_data_in_code():
    """程式碼裡不得寫死任何交易過的代號（三個基準 ETF 除外）、也不得出現委託單號。
    代號清單在測試時才從帳本讀出來，不寫在這裡。"""
    import json
    syms = set()
    for line in C.LEDGER.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            syms.add(str(r.get("symbol", "")))
            syms.add(str(r.get("underlying", "")))
    syms -= {"", "SPY", "SMH", "QQQ"}
    for name in ("ledger_common.py", "pf_run.py", "pf_report.py", "test_ledger.py"):
        path = HERE / name
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        bare = {s for s in syms if re.search(rf"(?<![A-Za-z_]){re.escape(s)}(?![A-Za-z_])", src)}
        assert not bare, f"{name} mentions {len(bare)} traded symbol(s)"
        assert not re.search(r"G\d{5}-\d{4}", src), f"{name} contains an order id"


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
