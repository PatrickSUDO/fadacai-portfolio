#!/usr/bin/env python3
"""Write summary.md (Traditional Chinese, conclusion first) for study ETF-C from the
files produced by run_etfc.py. Every number is read from those files.
Run:  python -B write_summary.py     (after run_etfc.py; same ETFC_OUT_DIR)"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

import etfc_common as C

O = C.OUT_DIR
BASE, STRESS = C.BASE, C.STRESS
CAND = ["S1", "S2", "S3", "R1", "R2", "V1", "V2", "V3", "T1", "C1"]
TIMED = ["R2", "V1", "V2", "V3", "T1", "C1"]
DESC = {
    "SPY": "基準：SPY（代表 VOO）", "QQQ": "基準：QQQ", "SMH": "基準：SMH",
    "B6040": "基準：SPY 六成、IEF 四成",
    "S1": "SPY 四成、QQQ 四成、SMH 兩成", "S2": "合成 2 倍 QQQ、合成 2 倍 SMH、MDY 各三分之一",
    "S3": "QQQ、SMH、MDY 各三分之一", "R1": "QQQ／TLT／GLD 風險平衡",
    "R2": "R1 加波動目標 15%", "V1": "QQQ 波動目標 18%", "V2": "SPY 波動目標 15%",
    "V3": "S1 整體波動目標 18%", "T1": "QQQ 站上 200 日均線抱 2 倍 QQQ，否則 BIL",
    "C1": "七成 V1 加三成 R1",
}


def pc(x, d=1):
    if x is None or not np.isfinite(x):
        return "—"
    return ("%.*f%%" % (d, x * 100)).replace("-", "−")


def pp(x, d=1):
    if x is None or not np.isfinite(x):
        return "—"
    return ("%+.*fpp" % (d, x * 100)).replace("-", "−")


def pa(x, d=1):
    """absolute size in percentage points"""
    if x is None or not np.isfinite(x):
        return "—"
    return "%.*fpp" % (d, abs(x) * 100)


def nm(x, d=2):
    if x is None or not np.isfinite(x):
        return "—"
    return ("%.*f" % (d, x)).replace("-", "−")


def sg(x, d=2):
    if x is None or not np.isfinite(x):
        return "—"
    return ("%+.*f" % (d, x)).replace("-", "−")


def yn(v):
    return "不適用" if v is None else ("過" if v else "不過")


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def main():
    ports = pd.read_csv(os.path.join(O, "portfolios.csv"))
    wins = pd.read_csv(os.path.join(O, "windows.csv"))
    dds = pd.read_csv(os.path.join(O, "drawdowns.csv"))
    sens = pd.read_csv(os.path.join(O, "sensitivity.csv"))
    boot = pd.read_csv(os.path.join(O, "bootstrap.csv"))
    val = pd.read_csv(os.path.join(O, "synthetic_validation.csv")).set_index("period")
    with open(os.path.join(O, "verdict.json")) as fh:
        V = json.load(fh)
    P = ports.loc[ports["cost"] == BASE].set_index("portfolio")
    PS = ports.loc[ports["cost"] == STRESS].set_index("portfolio")
    W = wins.loc[(wins["cost"] == BASE) & (wins["window_type"] == "window")]
    Wc = W.pivot(index="portfolio", columns="window", values="cagr")
    Wg = W.pivot(index="portfolio", columns="window", values="cagr_minus_spy")
    Wm = W.pivot(index="portfolio", columns="window", values="mdd")
    Y = wins.loc[(wins["cost"] == BASE) & (wins["window_type"] == "year")].pivot(
        index="window", columns="portfolio", values="total_return")
    E = dds.loc[dds["episode"] != "FULL_MDD"]
    Er = E.pivot(index="portfolio", columns="episode", values="span_return")
    Em = E.pivot(index="portfolio", columns="episode", values="mdd_in_span")
    FM = dds.loc[dds["episode"] == "FULL_MDD"].set_index("portfolio")
    Bt = boot.set_index(["portfolio", "benchmark"])
    cells = V["cells"]
    sv = V["synthetic_validation"]
    nt = V["null_test"]
    dca = {k.split("@")[0]: v for k, v in V["monthly_investing"].items() if k.endswith(BASE)}
    yrs10 = ["Y%d" % y for y in range(2010, 2026)]
    s2_2010 = float(np.prod(1 + Y.loc[yrs10, "S2"]) ** (1 / len(yrs10)) - 1)
    s3_2010 = float(np.prod(1 + Y.loc[yrs10, "S3"]) ** (1 / len(yrs10)) - 1)
    n_pass_calmar = nt["information_only_n_q_lt_0p10"]["calmar"]
    n_pass_cagr = nt["information_only_n_q_lt_0p10"]["cagr"]
    passed = V["passed"]
    L = []
    A = L.append

    A("# ETF-C：ETF 組合方式（2005–2025）結果摘要")
    A("")
    A("日期 2026-11-19｜預註冊：`research/overnight-study-2026-11-19.md` 的「第三組 ETF-C」｜回測終點 2025-12-31。")
    A("**全部是描述性結果，只能提名，不是已驗證的策略，也不是下單建議。**")
    A("")
    A("## 0. 結論（先讀這段）")
    A("")
    A("1. 這一組沒有找到值得你改變現有做法的組合方式；所有結果都是描述性的，只能提名。")
    A("2. 定期定額帳戶的槓桿是風險選擇，不是被驗證過的優勢：帶槓桿的配置年化報酬 %s、不帶槓桿 %s。"
      "最大跌幅則是 %s 對 %s。" % (pc(P.cagr.S2), pc(P.cagr.S3), pc(P.mdd.S2), pc(P.mdd.S3)))
    A("3. 個股帳戶「不設核心」的裁決不用改：固定混合贏大盤，只是因為裝了比較多科技股與半導體。")
    A("4. 波動目標（市場晃得兇就少放、平靜就多放）確實讓跌幅變淺，但沒有多賺；"
      "六個會依訊號調整部位大小的組合，照事前寫定的檢定（和「時間點打亂」的版本比）沒有一個過關。")
    A("5. 「2 倍 Nasdaq ETF 加 200 日均線開關」沒過，和 11 月 16 日的結論一致。")
    A("6. 風險平衡（股、長債、黃金各貢獻差不多的波動）跌得最淺，但年化報酬輸大盤，最差的一年正是股債同跌的 2022 年。")
    A("")
    A("## 1. 這對你的兩個帳戶代表什麼")
    A("")
    A("先講代號。SPY 是追蹤 S&P 500 的 ETF（這裡代表 VOO）。QQQ 追蹤 Nasdaq-100。SMH 是半導體 ETF。MDY 是中型股 ETF。"
      "TLT 是長天期美國公債 ETF，IEF 是中天期公債 ETF，GLD 是黃金 ETF，BIL 是短期國庫券 ETF（等於現金）。")
    A("「pp」是百分點。「年化報酬」在表格裡寫成 CAGR。「最大跌幅」在表格裡寫成 MDD，是從高點到低點最多跌掉多少。")
    A("")
    A("### 1.1 個股帳戶（不設核心）")
    A("")
    b = Bt.loc[("S1", "QQQ")]
    A("- S1（SPY、QQQ、SMH 的固定混合）通過了它適用的四條及格線。")
    A("- 但這只說明 2005 年以來 QQQ 與半導體贏 SPY，不代表「混合」這個動作本身有好處。")
    A("- S1 和單抱 QQQ 分不出高下：年化報酬差 %s。" % pp(b.cagr_diff))
    A("- 這個差距的 95%% 區間是 %s 到 %s，跨過 0。" % (pp(b.cagr_diff_lo), pp(b.cagr_diff_hi)))
    A("- 所以這一組沒有提供「個股帳戶該加一個核心」的新理由，和 2026-10-30 的裁決（核心比例只是波動旋鈕）一致。")
    A("- V1、V3、C1 是「報酬接近 QQQ、跌幅淺很多」的三個組合。以 V1（QQQ 波動目標）為例：年化 %s，QQQ 是 %s。"
      % (pc(P.cagr.V1), pc(P.cagr.QQQ)))
    A("- V1 的最大跌幅是 %s，QQQ 是 %s。" % (pc(P.mdd.V1), pc(P.mdd.QQQ)))
    A("- 但它們都沒有通過擇時檢定。")
    A("- 而且 V1 有 %s 的月份要用到 2 倍 ETF，這和 2026-10-23「不用槓桿 ETF」的裁決有張力。"
      % pc(P.share_decisions_above_1.V1, 0))
    A("- 建議：個股帳戶的規則不動。")
    A("")
    A("### 1.2 定期定額帳戶（2 倍 Nasdaq、2 倍半導體、中型股各三分之一）")
    A("")
    A("這裡用的是代理：2 倍 Nasdaq 用合成的 2 倍 QQQ，USD（2 倍半導體）用合成的 2 倍 SMH，VO（中型股）用 MDY。"
      "「合成」是指用預註冊的公式由 1 倍 ETF 的日報酬算出每天重設的 2 倍基金，所以每天重設造成的耗損已經算在結果裡。")
    A("")
    A("- 一次投入、每年再平衡：帶槓桿（S2）年化 %s，不帶槓桿（S3）%s。" % (pc(P.cagr.S2), pc(P.cagr.S3)))
    A("- 最大跌幅：S2 是 %s，S3 是 %s。" % (pc(P.mdd.S2), pc(P.mdd.S3)))
    A("- 每月定額投入：S2 的內部報酬率（把每筆投入的時間算進去的年化報酬）是 %s，S3 是 %s。"
      % (pc(dca["S2_DCA"]["dca_irr"]), pc(dca["S3_DCA"]["dca_irr"])))
    A("- 每月定額最難熬的一天是 %s：S2 的帳戶市值比累計投入少 %s。"
      % (dca["S2_DCA"]["dca_worst_value_vs_paid_in_date"], pc(-dca["S2_DCA"]["dca_worst_value_vs_paid_in"])))
    A("- 同樣的現金流放在 S3，最低點是比累計投入少 %s。" % pc(-dca["S3_DCA"]["dca_worst_value_vs_paid_in"]))
    A("- 槓桿不是每一段都贏：2005–2012 年 S2 年化 %s，S3 是 %s。" % (pc(Wc.loc["S2", "Wa"]), pc(Wc.loc["S3", "Wa"])))
    A("- 2013–2019 年 S2 年化 %s，S3 是 %s。" % (pc(Wc.loc["S2", "Wb"]), pc(Wc.loc["S3", "Wb"])))
    A("- 2020–2025 年 S2 年化 %s，S3 是 %s。" % (pc(Wc.loc["S2", "Wc"]), pc(Wc.loc["S3", "Wc"])))
    A("- 每承擔一單位波動賺到的報酬（Sharpe）沒有變多：S2 是 %s，S3 是 %s。" % (nm(P.sharpe.S2), nm(P.sharpe.S3)))
    A("- 也就是說，槓桿把報酬和風險一起放大，沒有改善兩者的比例。")
    A("- 這個樣本從 2005 年開始，沒有包含 2000–2002 年的科技股崩盤；先前研究裡同類的 2 倍籃子在 2000–2009 年最大跌幅是 −95%。")
    A("- 用均線開關或波動目標來「管理」槓桿，這次都沒有通過檢定，不建議為此加規則。")
    A("- 意思：留不留槓桿是你對「帳面可能少掉四分之三」承受度的選擇，回測沒辦法替你證明哪一邊是對的。"
      "家戶穩定度主要由這個帳戶的槓桿決定（2026-10-30 的結論），這次的數字沒有推翻它。")
    A("")
    A("## 2. 先驗證合成槓桿 ETF 可不可信")
    A("")
    A("公式：每日報酬 = L × 標的日報酬 −（L − 1）×（國庫券利率 + 0.5%）÷ 252 − 0.95% ÷ 252。L 是槓桿倍數。")
    A("做法：用同一條公式做 3 倍 QQQ，和真實的 TQQQ（3 倍 Nasdaq-100 基金）從 %s 比到 %s。" % (sv["period"][0], sv["period"][1]))
    A("")
    A("- 全期年化報酬：真實 %s，合成 %s。" % (pc(sv["cagr_real_tqqq"], 2), pc(sv["cagr_synth_3x"], 2)))
    A("- 兩者的年化差距是 %s；追蹤誤差（兩者每日報酬差的年化波動）是 %s。"
      % (pp(sv["cagr_gap_synth_minus_real"], 2), pc(sv["tracking_error_ann"])))
    A("- 全期幾乎沒有差距，是前後兩段互相抵銷的結果：2010–2012 年合成每年比真實少 %s，2020–2025 年每年多 %s。"
      % (pa(val.loc["2010-2012", "cagr_gap_synth_minus_real"], 2), pa(val.loc["Wc_2020-2025", "cagr_gap_synth_minus_real"], 2)))
    A("- 單一年度的差距落在 %s 到 %s 之間。" % (pp(sv["worst_year_gap"]), pp(sv["best_year_gap"])))
    A("- 讀法：公式在 3 倍 QQQ 上夠準，可以拿來做 2 倍；但利率高的年份合成會略為高估。")
    A("- 沒有驗證到的部分：2010 年以前（包含 2008 年）、以及 2 倍的 SPY、SMH、TLT、GLD，這些只是套用同一條公式。")
    A("")
    rows = []
    for k, lab in (("FULL_2010-02-11_2025", "全期"), ("2010-2012", "2010–2012"),
                   ("Wb_2013-2019", "2013–2019"), ("Wc_2020-2025", "2020–2025")):
        r = val.loc[k]
        rows.append([lab, pc(r.cagr_real_tqqq), pc(r.cagr_synth_3x), pp(r.cagr_gap_synth_minus_real, 2),
                     pc(r.tracking_error_ann), pc(r.mdd_real), pc(r.mdd_synth)])
    A(table(["期間", "真實 TQQQ 年化", "合成 3 倍年化", "差距", "追蹤誤差", "真實 MDD", "合成 MDD"], rows))
    A("")
    A("## 3. 全期成績（2005-01-03 → 2025-12-31，成本每邊 5 bp）")
    A("")
    A("「bp」是萬分之一。「Sharpe」是每單位波動賺多少；「扣現金 Sharpe」先扣掉放現金也拿得到的利息。"
      "「Calmar」是年化報酬除以最大跌幅。「對 SPY」「對 QQQ」是同一段日子裡的年化報酬差。")
    A("R1、C1 從 %s 才開始，R2 從 %s 才開始，因為 GLD 在 2004 年 11 月才上市、湊不滿一年的波動資料；它們都只和同一段日子的 SPY 比。"
      % (V["live_start"]["R1"], V["live_start"]["R2"]))
    A("")
    rows = []
    for n in ["SPY", "QQQ", "SMH", "B6040"] + CAND:
        r = P.loc[n]
        rows.append([n, DESC[n], pc(r.cagr), nm(r.sharpe), nm(r.sharpe_ex), pc(r.mdd), nm(r.calmar),
                     "%d（%s）" % (r.worst_year, pc(r.worst_year_ret)), pp(r.cagr_minus_spy), pp(r.cagr_minus_qqq),
                     pc(r.te_vs_SPY), pc(r.te_vs_QQQ)])
    A(table(["代號", "內容", "CAGR", "Sharpe", "扣現金 Sharpe", "MDD", "Calmar", "最差年度", "對 SPY", "對 QQQ",
             "對 SPY 追蹤誤差", "對 QQQ 追蹤誤差"], rows))
    A("")
    A("贏不贏 QQQ、SMH（照實報告，不列入及格條件）：")
    beat_q = [n for n in CAND if P.cagr_minus_qqq[n] > 0]
    beat_s = [n for n in CAND if P.cagr_minus_smh[n] > 0]
    A("- 同一段日子裡年化報酬高過 QQQ 的有：%s。"
      % ("、".join("%s（%s）" % (n, pp(P.cagr_minus_qqq[n])) for n in beat_q) if beat_q else "沒有"))
    A("- 年化報酬高過 SMH 的有：%s。"
      % ("、".join("%s（%s）" % (n, pp(P.cagr_minus_smh[n])) for n in beat_s) if beat_s else "沒有"))
    sig_q = [n for n in CAND if Bt.loc[(n, "QQQ"), "cagr_diff_lo"] > 0]
    A("- 但對 QQQ 的差距在重抽檢定下站得住的有：%s（見第 8 節）。" % ("、".join(sig_q) if sig_q else "沒有"))
    A("- 贏 QQQ 比較多的幾個都帶 2 倍槓桿；不帶槓桿的組合沒有一個在報酬上明顯贏 QQQ。")
    A("")
    A("## 4. 兩類組合要分開讀")
    A("")
    A("### 4.1 「這是風險選擇」：S1、S2、S3、R1")
    A("")
    A("這四個是固定配置，沒有進出場判斷，所以沒有對照組可以檢定。它們贏或輸只反映「承擔了哪一種風險」，不能寫成驗證過的策略。")
    A("")
    A("- S1 與 S3 通過適用的四條線，原因是多裝了 QQQ 與半導體；這是押科技股的風險。")
    A("- S2 的年化報酬最高，但最大跌幅比 SPY 深 %s，沒過第 3 條。" % pa(cells["S2"]["mdd_gap_vs_spy"]))
    A("- R1 的最大跌幅只有 %s，是所有組合裡最淺的。" % pc(P.mdd.R1))
    A("- 但 R1 的年化報酬比同期 SPY 低 %s，沒過第 1 條。" % pa(P.cagr_minus_spy.R1))
    A("- R1 在 2013–2019 年每年落後 SPY %s，在 2020–2025 年每年落後 %s，沒過第 2 條。"
      % (pa(Wg.loc["R1", "Wb"]), pa(Wg.loc["R1", "Wc"])))
    A("- 事前預期「2022 年是風險平衡的弱點」成立：R1 最差的年度是 2022 年，跌 %s。" % pc(-P.worst_year_ret.R1))
    A("")
    A("### 4.2 「有擇時成分、可以檢定」：R2、V1、V2、V3、T1、C1")
    A("")
    A("「曝險」是實際放在市場上的比例：1 是全部投入，2 是兩倍，0 是全放現金。")
    A("檢定方法：把每個組合的曝險時間表整段往後挪一個隨機天數（至少 %d 個交易日），做 %d 次，當作「同樣的曝險、但時間點是亂的」對照組。"
      % (nt["min_shift_sessions"], nt["n_shifts"]))
    A("p 值是對照組裡不輸真實結果的比例。q 值是同時檢定六個組合後修正過的 p 值，及格線是 q 小於 0.10。")
    A("事前定的讀法比較嚴：年化報酬和 Calmar 兩項都要贏過對照組（取兩個 p 值較大的那個）。")
    A("")
    rows = []
    for n in TIMED:
        z = cells[n]["null"]
        rows.append([n, pc(z["obs_cagr"]), pc(z["null_median_cagr"]), nm(z["null_p_cagr"], 3),
                     pc(z["obs_mdd"]), pc(z["null_median_mdd"]), nm(z["null_p_calmar"], 3),
                     nm(z["null_q"], 2), nm(nt["information_only_q_if_single_metric"]["calmar"][n], 3)])
    A(table(["代號", "真實 CAGR", "對照組中位 CAGR", "p（CAGR）", "真實 MDD", "對照組中位 MDD", "p（Calmar）",
             "q（事前讀法）", "q（只看 Calmar，僅供參考）"], rows))
    A("")
    A("- 結果：照事前讀法，六個裡 %s 個過關。" % V["pass_line_counts"]["line6"].split(" ")[0])
    A("- 原因很清楚：真實的年化報酬和對照組的中位數幾乎一樣，擇時沒有多賺。")
    A("- 但真實的最大跌幅明顯比對照組淺，例如 V1 是 %s，對照組中位數是 %s。"
      % (pc(cells["V1"]["null"]["obs_mdd"]), pc(cells["V1"]["null"]["null_median_mdd"])))
    A("- 所以波動目標是「把跌幅變淺的工具」，不是「多賺的來源」。")
    A("- **這一條對讀法很敏感，請注意**：如果檢定只看 Calmar，六個裡會有 %d 個的 q 小於 0.10；如果只看年化報酬，是 %d 個。"
      % (n_pass_calmar, n_pass_cagr))
    A("- 預註冊沒有寫明用哪個統計量；這裡沿用 2026-11-18 研究的做法（兩項都要過），屬於保守的那一邊。")
    five = [n for n in TIMED if all(cells[n][k] for k in (
        "line1_cagr_ge_spy_and_calmar_gt_spy", "line2_each_window_within_2pp_of_spy",
        "line3_mdd_within_5pp_of_spy", "line4_lines_1_to_3_hold_at_10bp", "line5_sensitivity"))]
    alt = [n for n in five if nt["information_only_q_if_single_metric"]["calmar"][n] < 0.10]
    A("- 若改成只看 Calmar，%s 會六條全過；要不要採用那個讀法需要你裁決，程式沒有替你決定，前瞻追蹤的設定也沒有動。"
      % ("、".join(alt) if alt else "仍然沒有組合"))
    A("")
    A("## 5. 及格線逐條")
    A("")
    A("六條線：(1) 全期年化報酬不低於 SPY，且 Calmar 高於 SPY。(2) 三個窗各自的年化報酬不比 SPY 低超過 2pp。"
      "(3) 全期最大跌幅不比 SPY 深超過 5pp。(4) 成本加倍到每邊 10 bp，前三條仍成立。"
      "(5) 敏感度版本裡至少四分之三的 Calmar 仍高於 SPY。(6) 有擇時成分的組合，對照組檢定 q 小於 0.10。")
    A("")
    rows = []
    for n in CAND:
        c = cells[n]
        l5 = "不適用" if c["line5_sensitivity"] is None else "%s（%d／%d）" % (
            yn(c["line5_sensitivity"]), round(c["line5_share_of_variants_calmar_gt_spy"] * c["line5_n_variants"]),
            c["line5_n_variants"])
        rows.append([n, yn(c["line1_cagr_ge_spy_and_calmar_gt_spy"]), yn(c["line2_each_window_within_2pp_of_spy"]),
                     yn(c["line3_mdd_within_5pp_of_spy"]), yn(c["line4_lines_1_to_3_hold_at_10bp"]), l5,
                     yn(c["line6_null_q_lt_0p10"]), "%d／%d" % (c["n_lines_passed"], c["n_lines_applicable"]),
                     "是" if c["passes_all_applicable_lines"] else "否"])
    A(table(["代號", "線 1", "線 2", "線 3", "線 4", "線 5", "線 6", "通過／適用", "適用的線全過"], rows))
    A("")
    pc_ = V["pass_line_counts"]
    A("- 十個候選裡，線 1 過 %d 個，線 2 過 %d 個。" % (pc_["line1"], pc_["line2"]))
    A("- 線 3 過 %d 個，線 4 過 %d 個。" % (pc_["line3"], pc_["line4"]))
    A("- 線 5：七個有敏感度版本的組合裡過 %s 個。線 6：六個有擇時成分的組合裡過 %s 個。"
      % (pc_["line5"].split(" ")[0], pc_["line6"].split(" ")[0]))
    A("- 適用的線全過的只有：%s。它們都是固定配置（風險選擇），沒有經過對照組檢定。" % "、".join(passed))
    A("- %s 過了前五條，只卡在線 6。" % "、".join(five))
    A("- 依預註冊，沒有任何帶擇時成分的組合取得「值得前瞻追蹤」的資格。")
    A("")
    A("## 6. 三個窗與三次大跌")
    A("")
    A("三個窗：Wa 是 2005–2012 年，Wb 是 2013–2019 年，Wc 是 2020–2025 年。表內是年化報酬，括號是和同一段日子的 SPY 的差。")
    A("")
    rows = []
    for n in ["SPY", "QQQ", "SMH", "B6040"] + CAND:
        rows.append([n] + ["%s（%s）" % (pc(Wc.loc[n, w]), pp(Wg.loc[n, w])) for w in ("Wa", "Wb", "Wc")]
                    + [pc(Wm.loc[n, w]) for w in ("Wa", "Wb", "Wc")])
    A(table(["代號", "Wa CAGR", "Wb CAGR", "Wc CAGR", "Wa MDD", "Wb MDD", "Wc MDD"], rows))
    A("")
    A("三次大跌用固定的日期區間，表內是區間頭尾的報酬，括號是區間內最深的跌幅。")
    A("")
    for ep in ("2008", "2020", "2022"):
        A("- %s 年那一次：%s 到 %s。" % ((ep,) + C.EPISODES[ep]))
    A("")
    rows = []
    for n in ["SPY", "QQQ", "SMH", "B6040"] + CAND:
        rows.append([n] + ["%s（%s）" % (pc(Er.loc[n, e]), pc(Em.loc[n, e])) for e in ("2008", "2020", "2022")]
                    + [pc(FM.loc[n, "mdd_in_span"]), "%s → %s" % (FM.loc[n, "peak_date"], FM.loc[n, "trough_date"])])
    A(table(["代號", "2008", "2020", "2022", "全期 MDD", "全期 MDD 的高點 → 低點"], rows))
    A("")
    A("- 波動目標在 2008 年有幫助：V1 區間內最深跌 %s，QQQ 是 %s。" % (pc(Em.loc["V1", "2008"]), pc(Em.loc["QQQ", "2008"])))
    A("- 在 2020 年反而比較糟：V1 最深跌 %s，QQQ 是 %s。" % (pc(Em.loc["V1", "2020"]), pc(Em.loc["QQQ", "2020"])))
    A("- 原因是 2020 年 1 月底市場很平靜，波動目標把 V1 的曝險加到 1 以上，然後急跌來得比每月調整還快。")
    A("- T1 的全期最大跌幅 %s 也發生在 2020 年 3 月，同樣是每月才檢查一次來不及。" % pc(P.mdd.T1))
    A("- 2022 年股債同跌：R1 區間內最深跌 %s，比 SPY 的 %s 還深。" % (pc(Em.loc["R1", "2022"]), pc(Em.loc["SPY", "2022"])))
    A("")
    A("## 7. 敏感度（只報告，用來看結論是不是只靠某一個參數）")
    A("")
    A("版本：波動目標加減 3pp、回看天數改成 21 或 126 個交易日、改成每週調整。每次只改一項，成本每邊 5 bp。")
    A("")
    rows = []
    for n in ["R1", "R2", "V1", "V2", "V3", "T1", "C1"]:
        g = sens.loc[sens["portfolio"] == n]
        rows.append([n, "%d／%d" % (g.calmar_above_spy.sum(), len(g)),
                     "%s 到 %s" % (pc(g.cagr.min()), pc(g.cagr.max())),
                     "%s 到 %s" % (pc(g.mdd.min()), pc(g.mdd.max())),
                     "%s 到 %s" % (nm(g.calmar.min()), nm(g.calmar.max())),
                     "%d／%d" % ((g.line1 & g.line2 & g.line3).sum(), len(g))])
    A(table(["代號", "Calmar 高於 SPY 的版本數", "CAGR 範圍", "MDD 範圍", "Calmar 範圍", "線 1–3 全過的版本數"], rows))
    A("")
    vt = sens.loc[sens.portfolio.isin(["R2", "V1", "V2", "V3", "C1"])]
    assert vt.calmar_above_spy.all()
    A("- 波動目標這一類（R2、V1、V2、V3、C1）的 Calmar 在每個版本都高於 SPY，「跌幅變淺」這件事不靠單一參數。")
    A("- 但 V2 的年化報酬在五個版本裡有 %d 個低於 SPY，SPY 上做波動目標沒有多賺。"
      % int((sens.loc[sens.portfolio == "V2", "cagr_minus_spy"] < 0).sum()))
    t21 = sens.loc[(sens.portfolio == "T1") & (sens.variant == "lookback_21")].iloc[0]
    A("- T1 對均線長度很敏感：改成 21 日均線後年化報酬掉到 %s，最大跌幅 %s。" % (pc(t21.cagr), pc(t21.mdd)))
    assert cells["T1"]["line5_narrow_reading"] and not cells["T1"]["line2_each_window_within_2pp_of_spy"]
    assert not cells["T1"]["line4_lines_1_to_3_hold_at_10bp"] and not cells["T1"]["line6_null_q_lt_0p10"]
    A("- T1 的回看版本是把 200 日均線換成 21 日與 126 日；若只算「每週調整」這一個版本，T1 的線 5 會過，但它仍然不過線 2、線 4、線 6。")
    A("")
    A("## 8. 和 SPY、QQQ 的差距有多確定（區塊 bootstrap）")
    A("")
    A("做法：把每日報酬切成 %d 個交易日一段，整段重抽 %d 次，看差距會晃多大。區間跨過 0 表示分不出高下。"
      % (V["bootstrap"]["block_sessions"], V["bootstrap"]["n_boot"]))
    A("")
    rows = []
    for n in ["QQQ", "SMH", "B6040"] + CAND:
        r = []
        for b in ("SPY", "QQQ"):
            if (n, b) in Bt.index:
                z = Bt.loc[(n, b)]
                r += ["%s［%s，%s］" % (sg(z.sharpe_diff), sg(z.sharpe_diff_lo), sg(z.sharpe_diff_hi)),
                      "%s［%s，%s］" % (pp(z.cagr_diff), pp(z.cagr_diff_lo), pp(z.cagr_diff_hi))]
            else:
                r += ["—", "—"]
        rows.append([n] + r)
    A(table(["代號", "對 SPY 的 Sharpe 差", "對 SPY 的 CAGR 差", "對 QQQ 的 Sharpe 差", "對 QQQ 的 CAGR 差"], rows))
    A("")
    def excl(b, k):
        return [n for n in CAND if Bt.loc[(n, b), k + "_lo"] > 0 or Bt.loc[(n, b), k + "_hi"] < 0]
    lst = lambda v: "、".join(v) if v else "沒有"
    A("- 對 QQQ：Sharpe 差的區間不含 0 的候選有：%s。年化報酬差的區間不含 0 的有：%s。"
      % (lst(excl("QQQ", "sharpe_diff")), lst(excl("QQQ", "cagr_diff"))))
    A("- 對 SPY：年化報酬差的區間不含 0 的有：%s；這三個都是固定配置，贏在多裝科技股或槓桿。" % lst(excl("SPY", "cagr_diff")))
    A("- 對 SPY：Sharpe 差的區間不含 0 的有：%s，而且下緣只有 %s，很勉強。"
      % (lst(excl("SPY", "sharpe_diff")), sg(Bt.loc[("C1", "SPY"), "sharpe_diff_lo"], 3)))
    A("- 21 年只有一條歷史路徑，這些區間都很寬，請不要把第 3 節的排名當成確定的高下。")
    A("")
    A("## 9. 每月定額投入的版本（S2）")
    A("")
    A("做法：每個月第一個交易日開盤投入一單位，按目標比例買；每年第一個交易日把整個帳戶調回目標比例。共 %d 筆投入。"
      % dca["S2_DCA"]["dca_n_contributions"])
    A("S3、SPY、QQQ 三列是同樣現金流的對照，方便看內部報酬率的高低，不是另外的策略。")
    A("「單位淨值 MDD」是把新投入的錢排除之後算的最大跌幅。")
    A("")
    rows = []
    for k, lab in (("S2_DCA", "S2（帶槓桿）"), ("S3_DCA", "S3（不帶槓桿）"), ("SPY_DCA", "SPY"), ("QQQ_DCA", "QQQ")):
        d = dca[k]
        rows.append([lab, pc(d["dca_irr"]), nm(d["dca_multiple"], 1), pc(d["dca_worst_value_vs_paid_in"]),
                     d["dca_worst_value_vs_paid_in_date"], pc(d["mdd"])])
    A(table(["配置", "內部報酬率", "期末市值 ÷ 累計投入", "市值相對累計投入的最低點", "發生日", "單位淨值 MDD"], rows))
    A("")
    A("## 10. 和既有結論重疊或衝突的地方（逐項）")
    A("")
    A("1. **V2（SPY 波動目標 15%%）對 `hmm_regime_timing_2026-11-09.py` 的同一格**：舊結果是年化 8.2%%、最大跌幅 −44%%，窗從 1998 年起、不帶槓桿。"
      "這次是年化 %s、最大跌幅 %s，窗從 2005 年起、曝險上限 2 倍。方向一致：報酬和買進持有差不多，跌幅淺一些，沒有衝突。"
      % (pc(P.cagr.V2), pc(P.mdd.V2)))
    A("2. **V1（QQQ 波動目標）對 `tools/backtest_vol_target.py` 與 portfolio_fit**：前者沒有留下結果數字。"
      "後者把波動目標套在舊組合 P0（以半導體為主的舊配置）上，過了「年化報酬少不到 2pp、跌幅淺 5pp 以上」那條線。"
      "這次 V1 對 QQQ 的年化差是 %s，跌幅淺 %s，一致。舊的反駁（套到帳戶實際波動後代價變大）這次沒有測。"
      % (pp(P.cagr_minus_qqq.V1), pa(P.mdd.V1 - P.mdd.QQQ)))
    A("3. **T1 對 `feedback/ma-filter-evidence.md` G 節的 2 倍 ETF 加考**：舊結論是 24 個候選 0 個過，2 倍加開關輸 2 倍買進持有。"
      "這次 T1 年化 %s，合成 2 倍 QQQ 買進持有是 %s，仍然 0 個過，一致。" % (pc(P.cagr.T1), pc(P.cagr.QQQ2X)))
    A("4. **T1 的分段表現和舊結論「均線的好處集中在 2009 年以前」表面上不同**：這次 T1 在 2005–2012 年反而最差，年化只有 %s。"
      "原因是 2005 年與 2010–2011 年被來回洗。它在 2020–2025 年略贏 2 倍買進持有（%s 對 %s）。"
      "兩邊的窗不一樣（這次沒有 2000–2004 年），不算直接衝突，也不改變「沒過」的結論。"
      % (pc(Wc.loc["T1", "Wa"]), pc(Wc.loc["T1", "Wc"]), pc(Wc.loc["QQQ2X", "Wc"])))
    A("5. **S2 對 G 節與 `research/core-satellite-proposal-2026-10-30.md` 的 QLD／USD／VO 籃子**（QLD 是 2 倍 Nasdaq-100 的 ETF）：舊結果是 2010 年起年化 28.8%%、最大跌幅 −59%%。"
      "這次代理籃子 2010–2025 年年化 %s，2022 年區間內最深跌 %s。報酬相近（不帶槓桿版這次是 %s，舊數字是 18.8%%）。"
      "跌幅比舊數字淺約 %s，可能是 2 倍 SMH 代理 USD 造成的低估，請把這次的 S2 跌幅當成偏樂觀。"
      % (pc(s2_2010), pc(Em.loc["S2", "2022"]), pc(s3_2010), pa(-0.59 - Em.loc["S2", "2022"], 0)))
    A("6. **槓桿 ETF 裁決（2026-10-23：三種用途都不用）**：S2 的 Sharpe（%s）沒有高過 S3（%s），和「用更深的跌幅買報酬、Sharpe 不升」一致。"
      % (nm(P.sharpe.S2), nm(P.sharpe.S3)))
    A("7. **同一裁決的張力**：V1、V3、C1 的報酬能貼近 QQQ，是因為平靜時用 2 倍 ETF 把曝險加到 1 以上；"
      "不帶槓桿的波動目標在舊研究裡要付出報酬。這次的結果沒有推翻舊裁決，只是把代價換了一個地方付。")
    A("8. **核心／衛星（2026-10-30：核心比例是波動旋鈕、不是超額報酬來源）**：S1、S3、60/40 的結果都符合這句話，沒有衝突。")
    A("9. **家戶兩帳戶（去槓桿對 2022 型回撤的改善最大）**：這次 2022 年區間 S2 最深跌 %s、S3 是 %s，方向與量級都一致。"
      % (pc(Em.loc["S2", "2022"]), pc(Em.loc["S3", "2022"])))
    A("10. **R1、R2（風險平衡）**：既有檔案沒有測過 TLT，也沒有「按波動倒數分配資產權重」的回測，這兩格是新的，沒有可以比對的舊結果。"
       "`feedback/hedge-sleeve.md` 的黃金對沖部位是政策不是回測，這次沒有檢驗它。")
    A("11. **2026-11-18 的 ETF 研究（輪動與進出場都輸買進持有）**：這次的擇時檢定在報酬上同樣是 0 個過，一致；"
       "新增的資訊是「波動目標對跌幅有可檢定的效果」。")
    A("")
    A("## 11. 規格沒寫清楚、由我選定的讀法")
    A("")
    for s in INTERP_ZH:
        A("- " + s)
    A("")
    A("## 12. 看起來弱或可疑的地方")
    A("")
    bd = V["diagnostics"]["bil_traded_at_close_equivalent"]
    weak = [
        "線 6 的結論取決於統計量的讀法：兩項都要過是 0 個，只看 Calmar 是 %d 個。這是整份結果裡最需要人來裁決的一點。" % n_pass_calmar,
        "合成槓桿在全期的零差距是前後抵銷出來的；利率高的 2023–2025 年，合成的 3 倍每年高估 %s 到 %s。"
        "2005–2007 年利率也高，但那一段沒有真實資料可以驗證。"
        % (pa(min(val.loc["Y%d" % y, "cagr_gap_synth_minus_real"] for y in (2023, 2024, 2025))),
           pa(max(val.loc["Y%d" % y, "cagr_gap_synth_minus_real"] for y in (2023, 2024, 2025)))),
        "2 倍的 SPY、SMH、TLT、GLD 沒有真實基金可以對，只是套用同一條公式。",
        "USD 用 2 倍 SMH 代理；和舊研究的真實 ETF 數字比，2022 年的跌幅這次淺了約 %s，S2 的風險可能被低估。"
        % pa(-0.59 - Em.loc["S2", "2022"], 0),
        "樣本從 2005 年開始，沒有 2000–2002 年。凡是多裝科技股的組合，在這段期間對 SPY 的三條線幾乎一定會過，這不是組合方式的功勞。",
        "R1、C1 晚約十個月上線，R2 晚約十四個月；它們的 Wa 窗比較短，只和同一段日子的 SPY 比。",
        "S1、S2、S3 沒有敏感度版本，線 5 對它們是「不適用」而不是「通過」。",
        "BIL 的開盤價有雜訊（有 %d 個交易日的開盤跳動超過 25 bp）；改用收盤等值價成交，各組合的年化報酬變動最多 %s，不影響結論。"
        % (bd["n_sessions_bil_open_gap_gt_25bp"], pa(max(abs(bd[n]["cagr_change"]) for n in TIMED), 2)),
        "波動目標在 2020 年 3 月比買進持有跌得更深，這是每月調整的結構性弱點，不是資料問題。",
        "bootstrap 的區間都很寬；沒有任何候選和 QQQ 的差距分得出來，對 SPY 分得出來的也只有固定配置的報酬差與 C1 很勉強的 Sharpe 差。",
        "全部只有一條歷史路徑、十個候選，沒有樣本外資料；這就是為什麼結果只能提名。",
    ]
    for s in weak:
        A("- " + s)
    A("")
    A("## 13. 檔案")
    A("")
    A("- 程式：`tools/backtests/overnight_2026-11-19/etf/`（`etfc_common.py`、`run_etfc.py`、`write_summary.py`、`test_etfc.py`）。")
    A("- 結果：`tools/backtests/data/overnight_2026-11-19/etf/`（`portfolios.csv`、`windows.csv`、`drawdowns.csv`、`sensitivity.csv`、"
      "`bootstrap.csv`、`synthetic_validation.csv`、`verdict.json`、`summary.md`）。")
    A("- 這一組只用 ETF 價格，沒有讀帳本。沒有改任何規則檔，沒有 commit。")
    A("")
    with open(os.path.join(O, "summary.md"), "w") as fh:
        fh.write("\n".join(L))
    print("summary.md written:", len(L), "lines")


INTERP_ZH = [
    "窗的算法：窗內每個交易日的報酬都算進去，起點是窗前一個交易日的收盤；Wa 與全期的起點是 2005-01-03 收盤。",
    "進場：2005-01-03 收盤做第一次決定，2005-01-04 開盤成交，之前是現金。規格沒有持有天數，所以沒有用分批（tranche）。",
    "基準 SPY、QQQ、SMH 用收盤對收盤、不扣成本；60/40 每年再平衡、照樣扣成本。",
    "R1 要等 QQQ、TLT、GLD 都有 252 個日報酬才上線（2005-11-17）；R2 再等 R1 自己有 63 個日報酬（2006-02-21）；C1 跟 R1 同時上線。"
    "比較一律用組合自己上線後的同一段日子。",
    "「每月調整」是每月最後一個交易日收盤決定、下一個交易日開盤成交；「每年」是年底最後一個交易日；「每週」是每週最後一個交易日。",
    "沒有設不交易的緩衝帶，每次調整都完全調到目標。",
    "成本每邊 5 bp（壓力 10 bp）算在所有成交金額上，包含 BIL 與 1 倍、2 倍之間的互換，首次買進也算。",
    "波動 = 過去 63 個收盤對收盤日報酬的標準差乘以根號 252，用還原價（把配息與分割調整回去的價格）；200 日均線也用還原收盤價。",
    "R2 與 V3 的「組合波動」是底層組合（R1、S1）自己過去 63 日實際日報酬的波動。R2 的權重是當下 R1 的目標權重；"
    "V3 的權重是 S1 當下漂移後的權重（年底那次用四成、四成、兩成）。",
    "曝險超過 1 的做法：每個資產把（曝險 − 1）的比例放在它的合成 2 倍、（2 − 曝險）放在 1 倍；曝險不到 1 時其餘放 BIL。沒有融資。",
    "合成 2 倍的開盤價 = 前一日合成收盤 ×（1 + 2 × 標的隔夜報酬）；當天的融資與管理費在收盤扣。國庫券利率用當天之前最後一筆 13 週利率。",
    "BIL 上市前（2007-05-31 以前）用 13 週國庫券利率除以 252，隔夜計息。扣現金 Sharpe 也用這個利率。",
    "C1：每次每月調整都把目標設回七成 V1 的目標加三成 R1 的目標。",
    "對照組檢定：只挪動曝險時間表，底層權重、調整日、成本都不變；位移量在 252 個交易日到（總天數 − 252）之間抽 1,000 個不重複的值；"
    "統計量是年化報酬與 Calmar 兩個 p 值取大者（p 值只算對照組不輸真實結果的那一邊）；"
    "六個組合一起做 BH 修正（同時檢定多個組合時控制誤判比例的方法）。C1 只挪動 V1 那一部分的曝險。",
    "敏感度：「回看 21／126 日」對 R2、V1、V2、V3、C1 是改 63 日的波動回看；對 R1 是改 252 日；對 T1 是改 200 日均線。"
    "R2 與 C1 裡 R1 的 252 日權重不動。S1、S2、S3 沒有可改的參數，線 5 記為不適用。",
    "線 1 到線 3 都是和同一段日子的 SPY 比；線 4 是把成本換成 10 bp 後重算線 1 到線 3。",
    "bootstrap（重抽）：組合與基準的日報酬成對、每段 63 個交易日、頭尾相接地重抽 2,000 次，取中間 95% 的範圍；年化報酬用幾何平均、一年 252 個交易日。",
    "三次大跌用固定日期區間（見第 6 節），報區間頭尾報酬與區間內最深跌幅。最差年度只算整年都在線上的年度。",
    "每月定額：新錢按目標比例買進，不拿來做再平衡；每年第一個交易日全帳戶調回目標。S3、SPY、QQQ 的同現金流版本是我加的對照列。",
    "另外加了單一標的的參考列（合成 2 倍 QQQ、合成 2 倍 SMH、MDY、TLT、GLD、IEF、BIL），只供對照，不是候選。",
]


if __name__ == "__main__":
    main()
