"""把 XM 的結果檔排成 summary.md（繁體中文、結論先行）。

所有數字都在執行時從結果檔讀出來；程式碼裡不內嵌任何由帳本算出的數字。
文字敘述對應 2026-11-19 那次執行的結果；開頭的檢查若不成立就停下來，避免文字與數字對不上。

跑法：先跑 run_xm.py 與 ledger_timing.py，再跑 python -B write_summary.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

O = C.OUT_DIR
WINS = ["Wa", "Wb", "Wc"]
PRED_NAME = {"0050": "0050", "2330": "2330", "TAIEX_TR": "TAIEX_TR（加權報酬指數）", "SEMI4": "四大半導體等權"}


def pct(x: float, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%".replace("-", "−")


def num(x: float, d: int = 1) -> str:
    out = f"{x:.{d}f}"
    if float(out) == 0:
        out = out.lstrip("-")
    return out.replace("-", "−")


def cheaper_or_dearer(lo: float, hi: float) -> str:
    if hi < 0:
        return f"平均貴 {-hi:.0f} 到 {-lo:.0f} bp"
    if lo > 0:
        return f"平均便宜 {lo:.0f} 到 {hi:.0f} bp"
    return f"平均落在 {num(lo, 0)} 到 {num(hi, 0)} bp 之間（正數代表較便宜）"


def main() -> None:
    cells = pd.read_csv(O / "cells.csv", dtype={"predictor": str})
    regs = pd.read_csv(O / "regressions.csv", dtype={"predictor": str})
    tim = pd.read_csv(O / "timing.csv", dtype={"predictor": str})
    rev = pd.read_csv(O / "reverse.csv")
    al = pd.read_csv(O / "alignment.csv")
    led = pd.read_csv(O / "ledger_timing.csv", dtype={"predictor": str})
    ledj = json.loads((O / "ledger_timing.json").read_text())
    sens = pd.read_csv(O / "sens_smh_cells.csv", dtype={"predictor": str})
    verdict = json.loads((O / "verdict.json").read_text())

    main2 = cells[(cells["alignment"] == "same_date") & (cells["cost_bp"] == 2)]
    full2 = main2[main2["window"] == "full"]
    stale2 = cells[(cells["alignment"] == "stale_latest") & (cells["cost_bp"] == 2) & (cells["window"] == "full")]
    sens2 = sens[(sens["alignment"] == "same_date") & (sens["cost_bp"] == 2) & (sens["window"] == "full")]
    tmain = tim[tim["alignment"] == "same_date"]
    tfull = tmain[tmain["window"] == "full"]
    twin = tmain[tmain["window"].isin(WINS)]
    prim = regs[(regs["alignment"] == "same_date") & (regs["tw_ret_type"] == "cc") & regs["window"].isin(WINS)]
    oc = prim[prim["spec"] == "oc~z+gap"]
    oo5 = prim[prim["spec"] == "oo5~z+gap"]
    gapz = prim[prim["spec"] == "gap~z"]

    # ── 文字敘述成立的前提（不成立就停）──
    q_cells = full2[full2["q_bh"] < 0.10]
    exq = full2[full2["pass_ex_q"]]
    checks = {
        "XM-2 沒有任何一格過及格線": int(full2["pass"].sum()) == 0,
        "XM-3 沒有任何一格過及格線（嚴格與字面）": int(tfull["pass"].sum()) == 0 and int(tfull["pass_literal"].sum()) == 0,
        "另報版本也沒有": int(stale2["pass"].sum()) == 0,
        "q<0.10 的格都是 TSM 的 R1": len(q_cells) > 0 and set(q_cells["target"]) == {"TSM"} and set(q_cells["rule"]) == {"R1"},
        "報酬條件都過的格都是 SMH 的 R1": len(exq) > 0 and set(exq["target"]) == {"SMH"} and set(exq["rule"]) == {"R1"},
        "跳空對 z 全部顯著為正": bool((gapz["t_z"] > 1.96).all()),
        "開盤到收盤迴歸在 Wc 沒有顯著": int((oc[oc["window"] == "Wc"]["t_z"].abs() > 1.96).sum()) == 0,
        "顯著的開盤到收盤迴歸只出現在 TSM、NVDA、AMD": set(oc[oc["t_z"].abs() > 1.96]["target"]) <= {"TSM", "NVDA", "AMD"},
        "所有格都輸買進持有": bool((full2["cagr_strat"] < full2["cagr_buyhold"]).all()),
        "等待對第一天買全部為負": bool((tfull["wait_vs_first_bp"] < 0).all()),
        "沒有任何窗顯示等待明顯較便宜": int((twin["wait_vs_first_lo"] > 0).sum()) == 0 and int((twin["wait_vs_avg_lo"] > 0).sum()) == 0,
        "SMH 敏感度沒有任何一格過": int(sens2["pass"].sum()) == 0,
        "R3 沒有一格三窗都贏無條件": int((full2[full2["rule"] == "R3"]["win_beats_uncond"] == 3).sum()) == 0,
    }
    bad = [k for k, v in checks.items() if not v]
    if bad:
        raise SystemExit("summary 的文字敘述與結果不符，需要重寫：" + "；".join(bad))

    L: list[str] = []
    A = L.append
    n_cells, n_tcells = len(full2), len(tfull)
    A("# XM：看台股做美股（隔夜研究 2026-11-19，第一組）")
    A("")
    A("## 0. 結論（先讀這段）")
    A("")
    A("1. 對你的意思：看完台股再決定當天要不要買美股，這次測不出可以用的優勢，不需要為此改任何操作。")
    A(f"2. 台股的消息在美股開盤那一跳就反映完了：{n_cells} 格交易規則沒有一格過及格線，進場時點的 {n_tcells} 格也沒有。")
    A("3. 唯一看起來有東西的是台積電 ADR（在美國掛牌的台積電存託憑證），但效果集中在較早的年份，2020 年後扣掉成本變成負的或輸現金。")
    A("4. 「等台股轉弱那天再買」比「第一天就買」平均買得更貴，因為多等的那一兩天股價平均在漲。")
    A("5. 反方向很清楚但賺不到：美股前一晚的漲跌大約一半會直接出現在 0050 隔天的開盤價，開盤之後沒有可用的後續。")
    A("6. 以上全部是描述性結果，只能用來提名想法，不是驗證過的策略。")
    A("")
    A("## 1. 這個研究在問什麼")
    A("")
    A("台股收盤比美股開盤早大約八到九個小時。")
    A("所以美股開盤前，當天台股的漲跌已經是已知的。")
    A("問題是：美股開盤價已經反映過一次之後，台股的漲跌還剩不剩資訊。")
    A("事前預期是「剩很少」。")
    A("結果符合事前預期。")
    A("")
    A("## 2. 名詞")
    A("")
    A("- **跳空**：今天開盤價相對昨天收盤價的變動。")
    A("- **bp**：萬分之一，100 bp 等於百分之一。")
    A("- **β（貝他）**：台股報酬平均跟著美股前一天報酬動多少，用過去 252 個交易日估計。")
    A("- **台股意外**：台股當天報酬減掉「β 乘以美股前一天報酬」，也就是台股自己多出來的那一段。")
    A("- **z 分數**：把台股意外除以它過去一年的波動，z 等於 1 代表「比平常大一個標準差」。")
    A("- **t 值**：估計值除以它的誤差，絕對值大約超過 2 才算不像巧合；這裡用 Newey-West 修正（考慮前後幾天互相關聯的算法）。")
    A("- **圓形位移對照**：把訊號整串往後挪至少 21 天再重算，重複 1,000 次，看真的訊號有沒有比亂挪的好。")
    A("- **p 值**：亂挪的訊號裡有多少比例不輸真的訊號，越小越不像巧合。")
    A("- **q 值**：同時檢定很多格時，用 BH 方法（控制「誤報比例」的算法）修正後的 p 值，及格線是小於 0.10。")
    A("- **淨年化**：扣掉交易成本後換算成一年的複利報酬。")
    A("- **無條件**：不看訊號、每天都做同一個動作，用來當對照。")
    A("- **買進持有**：一開始買了就一直抱著。")
    A("- **三個窗**：把整段期間切成三段分開看，三段都成立才算數。")
    A("  - Wa 是 2005 到 2012。")
    A("  - Wb 是 2013 到 2019。")
    A("  - Wc 是 2020 到 2025。")
    A("- **還原價**：把配息與拆股調整回去的價格，這裡所有報酬都用還原價算。")
    A("")
    A("## 3. 日期對齊（最容易出錯的地方）")
    A("")
    A("規則：美股交易日 D 只用「日期等於 D、而且台股當天有開盤」的台股資料。")
    A("台股日期晚於 D 的資料，程式結構上拿不到。")
    A("計算 β 時，台股某日只配「日期嚴格早於該日」的最後一個美股交易日。")
    A("這些規則都寫成單元測試（`test_align.py`），全部通過。")
    A("其中一個測試把 D 之後的台股資料全部改掉，確認 D 當天的 z 完全不變。")
    A("另外用最笨的逐日迴圈重算了兩格，結果和主程式一致。")
    A("")
    A("美股有開、台股同一天休市的日子（主分析不計）：")
    A("")
    A("| 窗 | 美股交易日 | 台股同日休市 | 佔比 | 另報版本的平均過期天數 | 最長過期天數 |")
    A("|---|---|---|---|---|---|")
    for _, r in al.iterrows():
        name = "全期" if r["window"] == "full" else r["window"]
        A(f"| {name} | {int(r['us_sessions']):,} | {int(r['us_no_same_date_tw'])} | {pct(r['share_no_same_date_tw'])} "
          f"| {num(r['stale_mean_days'])} | {int(r['stale_max_days'])} |")
    A("")
    A("「另報版本」是指台股休市時改用最近一個台股交易日的資料。")
    A("它的結論和主分析相同，沒有任何一格過及格線。")
    A("")
    A("## 4. XM-1 預測力")
    A("")
    A("**台股意外確實和美股有關，但關聯都在開盤那一跳。**")
    A(f"把美股跳空對 z 做迴歸，三個窗、{gapz.groupby(['target', 'predictor']).ngroups} 組配對全部顯著為正。")
    A(f"z 每高 1，美股跳空的中位數大約高 {gapz['b_z_bp'].median():.0f} bp。")
    A("")
    A("**開盤之後就幾乎沒有了。**")
    A("下面是「美股開盤到收盤報酬對 z 的迴歸、控制當天跳空」的結果。")
    A("每個美股標的有 12 條迴歸。")
    A("也就是 4 個台股預測變數各跑 3 個窗。")
    A("")
    A("| 美股標的 | 12 條裡 t 值絕對值超過 1.96 的條數 | 出現在哪個窗 |")
    A("|---|---|---|")
    for tgt in C.TARGETS:
        x = oc[(oc["target"] == tgt) & (oc["t_z"].abs() > 1.96)]
        where = "、".join(f"{w} {int((x['window'] == w).sum())} 條" for w in WINS if (x["window"] == w).any()) or "無"
        label = "TSM（台積電 ADR）" if tgt == "TSM" else tgt
        A(f"| {label} | {len(x)} | {where} |")
    A("")
    n_sig = int((oc["t_z"].abs() > 1.96).sum())
    A(f"{len(oc)} 條裡有 {n_sig} 條顯著。")
    A(f"純巧合預期大約 {0.05 * len(oc):.1f} 條。")
    A("但這些顯著的迴歸高度重疊，因為四個台股預測變數彼此很像。")
    A("沒有任何一組配對在三個窗都顯著。")
    A("最近的窗（Wc）沒有一條顯著。")
    A("")
    A("台積電 ADR 對 2330 的那一組最強，但一路變弱：")
    A("")
    A("| 窗 | z 每高 1，ADR 開盤到收盤多幾 bp | t 值 |")
    A("|---|---|---|")
    for w in WINS:
        r = oc[(oc["target"] == "TSM") & (oc["predictor"] == "2330") & (oc["window"] == w)].iloc[0]
        A(f"| {w} | {num(r['b_z_bp'])} | {num(r['t_z'])} |")
    A("")
    A("5 日版本（從開盤起算抱 5 個交易日）更弱。")
    A(f"{len(oo5)} 條裡只有 {int((oo5['t_z'].abs() > 1.96).sum())} 條顯著，沒有超過純巧合預期的條數。")
    A("")
    A("## 5. XM-2 交易規則")
    A("")
    A("三條凍結的規則：")
    A("- **R1**：z 大於 0.5 的日子，美股開盤買、收盤賣，其餘日子放現金。")
    A("- **R2**：z 小於負 0.5 的日子做同樣的事。")
    A("- **R3**：z 大於 1 的日子開盤買，抱 5 個交易日。")
    A("")
    A("每邊成本 2 bp、全期的結果（每條規則 24 格）：")
    A("")
    A("| 規則 | 過及格線 | 淨年化中位數 | 無條件對照中位數 | 現金中位數 | 三窗都贏現金的格數 | 三窗都贏無條件的格數 | q 小於 0.10 的格數 |")
    A("|---|---|---|---|---|---|---|---|")
    for rule, g in full2.groupby("rule"):
        A(f"| {rule} | {int(g['pass'].sum())} | {pct(g['cagr_strat'].median())} | {pct(g['cagr_uncond'].median())} "
          f"| {pct(g['cagr_cash'].median())} | {int((g['win_beats_cash'] == 3).sum())} "
          f"| {int((g['win_beats_uncond'] == 3).sum())} | {int((g['q_bh'] < 0.10).sum())} |")
    A("")
    A("**怎麼讀這張表：**")
    A("- R1 的中位數連現金都沒贏。")
    A("- R2 是負的，代表台股偏弱的日子去買美股當沖沒有好處。")
    A("- R3 有賺，但遠輸「一直抱著」，沒有一格在三個窗都贏無條件對照。")
    A(f"- {n_cells} 格的淨年化全部輸給買進持有。")
    A("")
    A("**差一點的格子：**")
    A(f"- q 小於 0.10 的 {len(q_cells)} 格都是台積電 ADR 的 R1。")
    A("- 它們沒過，是因為 Wc 的淨年化是負的。")
    A(f"- 另有 {len(exq)} 格 SMH 的 R1 報酬條件都過，但 q 值最低也有 {exq['q_bh'].min():.2f}，分不出是不是巧合。")
    A("")
    A("台積電 ADR 的 R1 淨年化（每邊 2 bp）：")
    A("")
    A("| 台股預測變數 | Wa | Wb | Wc | Wc 的現金 | q 值 |")
    A("|---|---|---|---|---|---|")
    tsm = main2[(main2["target"] == "TSM") & (main2["rule"] == "R1")]
    for pred in C.PREDICTORS:
        g = tsm[tsm["predictor"] == pred].set_index("window")
        A(f"| {PRED_NAME[pred]} | {pct(g.loc['Wa', 'cagr_strat'])} | {pct(g.loc['Wb', 'cagr_strat'])} "
          f"| {pct(g.loc['Wc', 'cagr_strat'])} | {pct(g.loc['Wc', 'cagr_cash'])} | {g.loc['full', 'q_bh']:.3f} |")
    A("")
    A("這個效果對成本很敏感。")
    by_cost = {}
    for cb in (1, 5):
        m = cells[(cells["alignment"] == "same_date") & (cells["cost_bp"] == cb) & cells["window"].isin(WINS)]
        ok = ((m["cagr_strat"] > m["cagr_cash"]) & (m["cagr_strat"] > m["cagr_uncond"]) & (m["cagr_strat"] > 0))
        by_cost[cb] = int((ok.groupby([m["target"], m["predictor"], m["rule"]]).sum() == 3).sum())
    A(f"「三個窗的報酬條件都過」的格數，每邊 1 bp 時是 {by_cost[1]} 格。")
    A(f"每邊 5 bp 時是 {by_cost[5]} 格。")
    A("")
    A("## 6. XM-3 進場時點")
    A("")
    A("假設本來就要買，可以在 3 個交易日內挑一天開盤買。")
    A("比較三種：第一天就買、等到 z 小於 0 的那天買、三天各買三分之一。")
    A("下表是全期平均，單位 bp，正數代表買得比較便宜。")
    A("每列是四個台股預測變數的平均。")
    A("")
    A("| 美股標的 | 等 z 轉負 對 第一天買 | 三天平均 對 第一天買 | 等 z 轉負 對 三天平均 |")
    A("|---|---|---|---|")
    for tgt in C.TARGETS:
        g = tfull[tfull["target"] == tgt]
        A(f"| {tgt} | {num(g['wait_vs_first_bp'].mean())} | {num(g['avg_vs_first_bp'].mean())} | {num(g['wait_vs_avg_bp'].mean())} |")
    A("")
    A(f"**結論：{n_tcells} 格沒有一格過及格線。**")
    A("等待本身就比較貴，因為這些標的長期在漲。")
    A(f"在 {len(twin)} 個「格乘窗」裡，有 {int((twin['wait_vs_first_hi'] < 0).sum())} 個顯示等待明顯比第一天買更貴。")
    A("沒有任何一個顯示等待明顯更便宜。")
    A(f"拿「等 z 轉負」跟「三天平均」比，全期差距落在 {num(tfull['wait_vs_avg_bp'].min())} 到 {num(tfull['wait_vs_avg_bp'].max())} bp 之間。")
    A("這些差距的區間沒有一個落在明顯為正的一側。")
    A("也就是說，台股訊號沒有幫你挑到比較好的那一天。")
    A("")
    A("**套在帳本的實際買進日（由帳本算出，只寫在這個不進版控的資料夾）：**")
    pooled = led[(led["target"] == "POOLED") & (led["alignment"] == "same_date")]
    for variant, title in (("A_ticker_matched", "讀法 A"), ("B_all_buy_dates", "讀法 B")):
        g = pooled[pooled["variant"] == variant]
        if g.empty:
            A(f"- {title}：沒有可算的樣本。")
            continue
        n = int(g["n"].iloc[0])
        if variant == "A_ticker_matched":
            syms = sorted(set(led[(led["variant"] == variant) & (led["target"] != "POOLED")]["target"]))
            A(f"- 讀法 A：帳本裡買的剛好是六個標的之一，只有 {' 與 '.join(syms)}，共 {n} 筆。")
        else:
            A(f"- 讀法 B：把帳本每一個買進日當起始日，套在六個標的上，共 {n:,} 筆。")
        A(f"- {title}，等 z 轉負對第一天買：{cheaper_or_dearer(g['wait_vs_first_bp'].min(), g['wait_vs_first_bp'].max())}。")
        inc0 = int(((g["wait_vs_first_lo"] <= 0) & (g["wait_vs_first_hi"] >= 0)).sum())
        A(f"- {title} 這一項的四個區間裡有 {inc0} 個包含 0。")
        A(f"- {title}，等 z 轉負對三天平均：{cheaper_or_dearer(g['wait_vs_avg_bp'].min(), g['wait_vs_avg_bp'].max())}。")
        inc0 = int(((g["wait_vs_avg_lo"] <= 0) & (g["wait_vs_avg_hi"] >= 0)).sum())
        A(f"- {title} 這一項的四個區間裡有 {inc0} 個包含 0。")
    cov = ledj["coverage"]
    A("- 帳本期間大致是一段多頭，所以「等」的代價比長期平均更高。")
    A(f"- 個股價格資料只到 {cov['price_last_date']['NVDA']}，之後買的個股沒算進讀法 A。")
    A(f"- ETF 價格資料只到 {cov['price_last_date']['SPY']}，之後的買進日沒算進讀法 B。")
    A("")
    A("## 7. XM-4 反方向（只報告）")
    A("")
    A("美股前一個交易日的報酬，對 0050 隔天的跳空與開盤到收盤（全期）：")
    A("")
    A("| 美股標的 | 0050 跳空的係數 | 解釋力（R 平方） | 控制跳空後，0050 開盤到收盤的係數 | 該係數的 t 值 |")
    A("|---|---|---|---|---|")
    rf = rev[(rev["alignment"] == "fresh_us_session") & (rev["window"] == "full")].set_index(["us_symbol", "spec"])
    for sym in C.TARGETS:
        a, b = rf.loc[(sym, "gap~us")], rf.loc[(sym, "oc~us+gap")]
        A(f"| {sym} | {num(a['b_us'], 2)} | {num(a['r2'], 2)} | {num(b['b_us'], 2)} | {num(b['t_us'])} |")
    A("")
    spy_gap = rf.loc[("SPY", "gap~us"), "b_us"]
    spy_oc = rf.loc[("SPY", "oc~us"), "b_us"]
    A(f"怎麼讀：SPY 前一晚漲 1%，0050 隔天開盤平均高 {spy_gap:.2f}%。")
    A("開盤之後有一點點回吐，但很小。")
    A(f"不控制跳空時，SPY 漲 1% 對應 0050 盤中大約變動 {num(spy_oc * 100, 0)} bp。")
    rw = rev[(rev["alignment"] == "fresh_us_session") & (rev["us_symbol"] == "SPY") & (rev["spec"] == "oc~us")
             & rev["window"].isin(WINS)]
    A(f"這個回吐在三個窗裡只有 {int((rw['t_us'].abs() > 1.96).sum())} 個窗顯著，不穩定。")
    A("這一段只是報告，沒有及格線，也沒有扣成本。")
    A("")
    A("## 8. 弱點與可疑之處")
    A("")
    dq = verdict["data_quality"]
    r1 = full2[full2["rule"] == "R1"]
    tsm_wa = main2[(main2["target"] == "TSM") & (main2["rule"] == "R1") & (main2["window"] == "Wa")]
    A("- **台積電 ADR 的開盤價可能不是真的買得到的價格。** 資料商的開盤價有時是第一筆零星成交，會讓「開盤買」看起來比實際好。這正好是唯一有訊號的地方，所以要特別保留。")
    A(f"- **SMH 有兩天的還原因子不合理**（{' 與 '.join(dq['SMH_suspect_adjustment_days'])}），當天的還原報酬被灌大。主結果原樣保留；拿掉這兩天重跑後，SMH 仍然沒有任何一格過及格線。")
    A(f"- **個股的 Wa 不完整。** TSM、NVDA、AMD 的價格從 2007 年才有，加上暖身期，z 要到 {tsm_wa['first_date'].min()} 才開始。這三個標的的 Wa 只有 {int(tsm_wa['n_elig'].max())} 個有效日。")
    A(f"- **2330 與四大半導體的 z 較晚開始**（{dq['first_valid_z_date']['SPY|2330']}），因為台股個股資料從 2005 年起。")
    A("- **四大半導體在 2018-04-30 之前只有三檔**，因為 3711 當時還沒有資料。")
    A("- **TAIEX_TR 沒有開盤價**，所以它沒有「開盤對收盤」版本的預測變數。")
    A(f"- **R1 與 R2 的無條件對照很好贏。** 每天當沖一次要付 4 bp，一年大約吃掉一成，所以「贏無條件」這一條的鑑別力很低。24 格 R1 裡只有 {int((r1['win_beats_uncond_gross'] == 3).sum())} 格三窗都贏「零成本的無條件版本」。")
    A("- **迴歸的 t 值沒有做多重檢定修正。** 顯著的那幾條其實只是「TSM 在 Wa 與 Wb」加「NVDA、AMD 在 Wa」這幾件事重複出現。")
    A("- **圓形位移只做 1,000 次**，所以 p 值最小只能到 0.001。")
    A("- **進場時點的比較沒有算等待期間的現金利息**，影響不到 1 bp。")
    A("- **台股休市被剔除的日子**，在 Newey-West 計算裡被當成相鄰的兩天，影響很小。")
    A("")
    A("## 9. 預註冊沒寫死、取保守讀法的地方")
    A("")
    plain = [
        "「對應美股標的」讀成該格要預測的那個美股標的，每一對各算自己的 β 與 z。",
        "交易規則與進場時點只用「收盤對收盤」版本的 z。「開盤對收盤」版本只放在迴歸表裡當參考。",
        "β 與 z 都只用當天以前的 252 個台股交易日，不含當天。",
        "「美股前一天」照字面，只取台股該日之前最後一個美股交易日。台股連休後不累加。",
        "四大半導體在 3711 有資料之前，用其餘三檔等權。",
        "R2 的「反向版」讀成條件反過來、但一樣是做多，不放空。",
        "R3 在第 5 個交易日的開盤賣出，資金分成 5 批錯開。",
        "沒持倉的日子領國庫券利率。「贏現金」是指淨年化高於同期間的現金年化。",
        "「無條件」對照付同樣的成本。另外多報一個更嚴格的版本，要求也贏零成本的無條件對照。",
        "及格線取嚴格讀法：三個窗各自都要贏無條件、贏現金、淨年化為正，全期也要為正，而且 q 小於 0.10。",
        "圓形位移用全期、每邊 2 bp 的總報酬當比較標準。",
        "進場時點的及格線取嚴格讀法：要同時比「第一天買」和「三天平均」都好超過 5 bp。只比第一天的字面讀法也沒有任何一格通過。",
        "帳本那一段兩種讀法都報（見第 6 節）。",
        "反方向只用「上一個台股收盤之後確實有新的美股交易日」的台股日。",
        "Newey-West 的落後期數用慣例公式。",
        "SMH 的兩個可疑日在主結果裡原樣保留，另跑一個拿掉它們的版本當參考。",
        "迴歸表另外附了「跳空對 z」與「隔日開盤對 z」兩種，只當描述，不進任何及格線。",
    ]
    for i, line in enumerate(plain, 1):
        A(f"{i}. {line}")
    A(f"{len(plain) + 1}. 精確的寫法在 `verdict.json` 的 `interpretation_choices`，共 {len(verdict['interpretation_choices'])} 條。")
    A("")
    A("## 10. 檔案")
    A("")
    A("| 檔案 | 內容 |")
    A("|---|---|")
    A("| `cells.csv` | XM-2 每一格、每個窗、每種成本的結果；`alignment` 欄區分主分析與另報版本 |")
    A("| `regressions.csv` | XM-1 迴歸；`role` 欄標明哪些是預註冊指定、哪些只是描述 |")
    A("| `timing.csv` | XM-3 進場時點 |")
    A("| `reverse.csv` | XM-4 反方向 |")
    A("| `alignment.csv` | 每個窗的對齊統計 |")
    A("| `ledger_timing.csv`、`ledger_timing.json` | XM-3 套在帳本買進日的結果（由帳本算出，不可移出這個資料夾） |")
    A("| `sens_smh_cells.csv`、`sens_smh_regressions.csv` | 拿掉 SMH 兩個可疑日的敏感度 |")
    A("| `verdict.json` | 及格線計數、對齊統計、解讀選擇、資料品質 |")
    A("")
    A("程式在 `tools/backtests/overnight_2026-11-19/xm/`：`align.py`（對齊）、`common.py`（讀檔與模擬）、`run_xm.py`（主程式）、`ledger_timing.py`（帳本段）、`write_summary.py`（本檔的產生器）、`test_align.py`（測試）。")
    text = "\n".join(L) + "\n"
    assert "§" not in text
    (O / "summary.md").write_text(text, encoding="utf-8")
    print(f"wrote {O / 'summary.md'} ({len(text)} chars)")


if __name__ == "__main__":
    main()
