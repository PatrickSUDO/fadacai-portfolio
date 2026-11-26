"""第二組 PF：把 pf_run.py 的結果寫成 summary.md 與 rule-proposal.md。

本檔不含任何帳戶資料：所有數字在執行時才從 gitignore 的結果目錄讀進來。
規則原文也是執行時從 feedback/ 的規則檔擷取，不改動規則檔。

用法：python -B pf_report.py     （要先跑過 pf_run.py）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger_common as C  # noqa: E402

PRIMARY = "primary_ledger_fifo_price_implied_splits"
SEEDED = "robust_seeded_pre_ledger_inventory"
TABLE = "robust_ledger_split_table"
ALT_NAME = {"SPY": "改放 SPY", "SMH": "改放 SMH", "CASH": "放現金"}
HOLDING_RULE = C.REPO / "feedback" / "holding-period-discipline.md"
HURDLE_RULE = C.REPO / "feedback" / "new-position-benchmark-hurdle.md"


# ── formatting ────────────────────────────────────────────────────────────
def usd(x, sign=True) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x:+,.0f}" if sign else f"{x:,.0f}"


def wan(x) -> str:
    """絕對值，以「萬美元」表示。"""
    return f"{abs(x) / 1e4:.1f} 萬美元"


def pp(x) -> str:
    return "—" if x is None or pd.isna(x) else f"{x * 100:+.1f}"


def pct(x) -> str:
    return "—" if x is None or pd.isna(x) else f"{x * 100:.0f}%"


def ci(lo, hi, f=usd) -> str:
    if lo is None or pd.isna(lo):
        return "[—]"
    return f"[{f(lo)}, {f(hi)}]"


def crosses(lo, hi) -> bool:
    return not (lo > 0 or hi < 0)


def verdict_word(lo, hi, tot) -> str:
    if crosses(lo, hi):
        return "分不出正負"
    return "明顯為正" if tot > 0 else "明顯為負"


def same_word(lo, hi, tot) -> str:
    """和實際相比有沒有差別。"""
    if crosses(lo, hi):
        return "和實際分不出差別"
    return "會明顯比較好" if tot > 0 else "會明顯比較差"


def md_table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c).replace("|", "、") for c in r) + " |" for r in rows]
    return "\n".join(out)


def rule_text(path: Path, start_pat: str, n_lines: int = 1) -> str:
    """從規則檔擷取以 start_pat 起頭的那一行（與其後 n_lines−1 行），原樣回傳。"""
    try:
        lines = path.read_text(encoding="utf-8").split("\n")
    except OSError:
        return "（讀不到規則檔，請人工核對原文）"
    for i, line in enumerate(lines):
        if re.search(start_pat, line):
            return "\n".join(lines[i:i + n_lines]).strip()
    return "（在規則檔裡找不到對應段落，請人工核對原文）"


# ── main ──────────────────────────────────────────────────────────────────
def build() -> None:
    v = json.loads((C.OUT / "verdict.json").read_text(encoding="utf-8"))
    s2 = pd.read_csv(C.OUT / "min_hold_counterfactual.csv", dtype={"cut_value": str})
    h = pd.read_csv(C.OUT / "hurdle.csv")
    r14 = pd.read_csv(C.OUT / "r14_compliance.csv").fillna("")
    sv = pd.read_csv(C.OUT / "split_validation.csv").fillna("")

    def row(N, alt, version="no_stop", variant=PRIMARY, cut_type="all", cut_value="all"):
        d = s2[(s2.fifo_variant == variant) & (s2.version == version) & (s2.N == N) & (s2.alt == alt)
               & (s2.cut_type == cut_type) & (s2.cut_value == cut_value)]
        return d.iloc[0]

    def hrow(period, group, H, bench):
        return h[(h.period == period) & (h.group == group) & (h.H == H) & (h.benchmark == bench)].iloc[0]

    L, PR, SP = v["ledger"], v["prices"], v["splits"]
    P1, P2, P3 = v["PF1"], v["PF2"], v["PF3"]
    rd = P2["prewritten_reading_primary"]
    supported = rd["extend_r14_to_63_supported"]
    conc = P2["concentration_N63_primary_no_stop"]
    r21s, r63s, r63m, r126m = row(21, "SPY"), row(63, "SPY"), row(63, "SMH"), row(126, "SMH")
    semi63, oth63 = hrow("全部", "半導體／AI 硬體", 63, "SMH"), hrow("全部", "其他", 63, "SMH")
    semi126, oth126 = hrow("全部", "半導體／AI 硬體", 126, "SMH"), hrow("全部", "其他", 126, "SMH")
    oth63q = hrow("全部", "其他", 63, "QQQ")
    all63m, all63q = hrow("全部", "全部", 63, "SMH"), hrow("全部", "全部", 63, "QQQ")
    r35 = P3["r35"]
    n_complete, n_breach = P1["n_stock_window_complete"], P1["n_breach_stock_positions"]
    cats = P1.get("exception_category_stock", {})
    n_allowed = sum(n for k, n in cats.items() if k.startswith("exception_"))
    n_unrec, n_bypass = cats.get("unrecorded", 0), cats.get("bypass", 0)
    first63 = r35["earliest_evaluable"]["63"]["approx_first_evaluable_date_ignoring_holidays"]
    first126 = r35["earliest_evaluable"]["126"]["approx_first_evaluable_date_ignoring_holidays"]
    win = lambda x: "贏" if x > 0 else "輸"  # noqa: E731

    # ══ summary.md ══
    S: list[str] = []
    A = S.append
    A("# 第二組 PF：帳本與持有期規則（隔夜研究 2026-11-19）")
    A("")
    A("本檔含由個人帳本算出的數字與個別交易，只能留在 gitignore 的路徑，不得搬到會被 git 追蹤的地方。")
    A(f"產生時間：{v['generated']}。預註冊：`research/overnight-study-2026-11-19.md` 的「第二組 PF」。")
    A("")
    A("## 0. 結論（先讀這段）")
    A("")
    if supported:
        A("- 你問「不做一個月以內的交易」能不能再加強：把最短持有期拉長到 63 個交易日，這次的資料符合事前寫定的四個條件。")
    else:
        A("- 你問「不做一個月以內的交易」能不能再加強：把最短持有期從 30 天拉長到 63 個交易日，這次的資料不支持。")
    A(f"- 太早賣掉的買進如果硬抱滿 63 個交易日，會比「賣掉後改放 SMH」"
      f"{'多' if r63m.diff_total > 0 else '少'} {wan(r63m.diff_total)}。SMH 是追蹤半導體類股的指數基金。")
    A(f"- 一個月內就賣的交易確實賠錢。但硬抱滿 21 個交易日，結果{same_word(r21s.ci_lo, r21s.ci_hi, r21s.diff_total)}"
      + ("，所以問題出在買了什麼，不是賣太早。" if crosses(r21s.ci_lo, r21s.ci_hi) else "。"))
    A(f"- 現有的最短持有規則沒有被好好遵守：上線後已滿期的 {n_complete} 個新個股部位裡，有 {n_breach} 個提前清倉。"
      f"這幾個裡只有 {n_allowed} 個對得上規則允許的例外。")
    A(f"- 選股方面：半導體與 AI 硬體的買進抱 63 個交易日，平均{win(semi63.excess_mean_ew)} SMH "
      f"{abs(semi63.excess_mean_ew) * 100:.1f} 個百分點。其他類股的買進平均{win(oth63.excess_mean_ew)} SMH "
      f"{abs(oth63.excess_mean_ew) * 100:.1f} 個百分點。")
    A("- 以上全部是描述性的整理，只能用來提名想法，不是驗證過的策略。"
      f"新倉門檻規則（R35）上線後的買進還沒有任何一筆滿 63 個交易日，現在無法評估。")
    A("")
    A("## 1. 這份研究在回答什麼")
    A("")
    A("- 你的要求是「不要做一個月以內的交易，看這個能不能在現有 fadacai-portfolio 上優化」。")
    A("- 這一組是診斷，沒有及格線。它只描述帳本裡已經發生的事，結論只能拿來提名，不能當成驗證過的規則。")
    A("- 四個問題：現有規則有沒有被遵守（PF-1）、把最短持有期拉長會怎樣（PF-2）、買進有沒有贏基準（PF-3）、規則該怎麼改（PF-4）。")
    A("")
    A("名詞：")
    A("")
    A("- **R14**：新建的部位在 30 個日曆日內不得清倉或減碼過半的規則，2026-07-29 生效。規則只允許三種例外。")
    A("- **R35**：新名字要預期贏過對應的基準 ETF 才能買的規則，2026-10-20 採用。")
    A("- **交易日**：股市有開盤的日子。21 個交易日大約一個月。63 個交易日大約三個月。126 個交易日大約半年。")
    A("- **先進先出配對**：把每一筆賣出，對回同一檔股票最早買進、還沒賣掉的那一批。配出來的一段叫「配對段」。")
    A("- **反事實**：假設當時照另一條規則做，結果會差多少。它不是真的發生過。")
    A("- **SPY、QQQ、SMH**：分別追蹤美股大盤、那斯達克 100、半導體類股的 ETF（指數型基金）。")
    A("- **bootstrap 95% 區間**：把買進月份整月重複抽樣一萬次，看總數會落在哪個範圍。區間跨過 0，表示分不出正負。")
    A("- **超額**：這筆買進的報酬，減掉同一段期間基準 ETF 的報酬。**百分點**：兩個百分比相減的單位。")
    A("- **硬停損**：收盤價比成本低 25% 就無條件賣出。")
    A("- **還原收盤價**：把拆股與配息的影響調整回去的收盤價，用來算跨日的報酬。")
    A("- **journal**：專案裡每天的交易日誌。**guard**：每天檢查持倉有沒有違反規則的程式（`tools/position_guard.py`）。")
    A("- **roster**：專案的持倉名冊，記錄每個部位屬於哪一類。**thesis**：當初買進的理由與它的失效條件。")
    A("- **bypass**：明知違反規則仍然照做，也就是推翻規則。")
    A("- **ranker**：另一個研究專案，這裡只借用它整理好的美股日線價格。")
    A("")
    A("## 2. 資料與做法")
    A("")
    A(f"- 帳本共有 {L['n_rows_in_file']:,} 列成交。")
    A(f"- 依預註冊排除 {L['n_option_rows']} 列選擇權與 {L['n_void_rows']} 列作廢記錄。")
    A(f"- 剩下 {L['n_stock_etf_rows_used']:,} 列股票與 ETF 成交，共 {L['n_symbols']} 個代號。")
    A(f"- 其中買進 {L['n_buys']} 筆、賣出 {L['n_sells']} 筆。")
    A(f"- 期間從 {L['first_fill']} 到 {L['last_fill']}。")
    A(f"- 價格沿用 2026-11-18 研究的來源與優先序，最後一個有價格的交易日是 {PR['calendar_last_priced_session']}。")
    A("- 一筆報酬只用同一個來源的價格，不同來源不拼接。")
    A(f"- ranker 的價格只讀到 {PR['silver_max_date']}，實際只補上 {PR['n_symbols_only_in_silver']} 個其他來源沒有的代號。")
    A("- 這一組依預註冊用到帳本最後一筆成交，所以會用到 2026 年的價格。")
    A("- 沒有讀任何前瞻驗證或保留樣本的路徑。")
    A("")
    A("### 2.1 拆股處理的驗證")
    A("")
    A("拆股會讓「買 1 股、賣 10 股」看起來對不上，配對前必須換算成同一種股數。")
    A("")
    A(f"- 用「成交價 ÷ 當天還原收盤價」比對，有 {SP['n_symbols_with_price_implied_split']} 個交易過的代號出現拆股痕跡。")
    A(f"- 專案的拆股表（`tools/trade_ledger.py` 的 SPLITS）只列了 {SP['n_symbols_in_ledger_split_table']} 個；"
      f"這 {SP['n_table_symbols_confirmed_by_price']} 個的倍數與日期都和價格吻合。")
    A(f"- 缺的 {SP['n_symbols_missing_from_table']} 個裡，有 {SP['n_missing_symbols_whose_fills_straddle_the_split']} 個"
      "的成交橫跨拆股日，會讓配對出錯。")
    A(f"- 受影響的成交共 {SP['n_fills_where_table_disagrees_with_price']} 列。")
    A("- 本研究的做法：每一列成交的拆股倍數都由價格推定，不用專案的拆股表。這是主要版本。")
    sil_rows = sv[sv.silver_events != ""]
    sil_ok = all(str(x) in ("True", "") for x in sil_rows.silver_event_dates_consistent_with_fills)
    A(f"- 其中 {len(sil_rows)} 個代號另外有 ranker 的原始收盤價可以核對拆股日期，"
      + ("結果全部一致。" if sil_ok else "結果有不一致的地方，見下表。"))
    rec_i, rec_t = SP["reconciliation_vs_broker"]["price_implied_splits"], SP["reconciliation_vs_broker"]["ledger_split_table"]
    if rec_i.get("available"):
        same = rec_i["n_symbols_only_in_ledger"] == 0 and rec_i["n_symbols_only_at_broker"] == 0
        A(f"- 旁證：用價格推定的版本，帳本推出的未平倉代號與券商目前的 {rec_i['n_broker_positions']} 檔持股"
          + ("代號完全一致。" if same else "代號不完全一致。"))
        A(f"- 其中 {rec_i['n_symbols_qty_diff_over_1_share']} 檔的股數差超過 1 股，推測是帳本起點之前的庫存或配股。")
        A(f"- 用專案拆股表的版本會多出 {rec_t['n_symbols_only_in_ledger']} 檔其實已經賣光的「幽靈部位」。")
    A(f"- 兩種做法算出的已實現損益差很多：價格推定版是 {usd(SP['realised_pnl_price_implied'])} 美元，"
      f"拆股表版是 {usd(SP['realised_pnl_ledger_table'])} 美元。")
    A("")
    A("拆股比對明細（代號是公開資訊，但這張表透露了交易過哪些代號，所以仍留在這裡）：")
    A("")
    A(md_table(["代號", "成交列數", "在專案拆股表裡", "價格推定的倍數（出現過的值）", "成交橫跨拆股日", "拆股表與價格不合的列數", "ranker 原始價的拆股事件"],
               [[r.symbol, r.n_fills, "是" if r.in_ledger_split_table else "否", r.price_implied_factors_seen,
                 "是" if r.fills_straddle_a_split else "否", r.n_fills_where_table_disagrees_with_price,
                 r.silver_events or "（沒有資料）"] for r in sv.itertuples()]))
    A("")
    A("### 2.2 配對的限制")
    A("")
    fi = SP["fifo_price_implied"]
    A(f"- 配對只用帳本裡的成交，與專案慣例相同。共配出 {SP['n_pieces_price_implied']} 段。")
    A(f"- 有 {fi['n_sells_fully_unmatched']} 筆賣出完全找不到對應的買進，另有 {fi['n_sells_partially_unmatched']} 筆只配到一部分。")
    A(f"- 這些沒配到的賣出金額合計 {usd(fi['unmatched_sell_proceeds'], False)} 美元，多半是帳本起點之前就持有的股票。")
    A(f"- 有 {SP['n_symbols_with_pre_ledger_inventory_over_half_share']} 個代號在帳本起點之前就有庫存。"
      "對這些代號，本研究的配對會把「賣舊股」算成「賣新買的」，持有天數會偏短。")
    A("- 為此另跑一個對照版：先替這些代號補上一批「帳本之前的庫存」再配對。結論不變（見 4.5）。")
    A("- 2023 到 2025 年的成交沒有時間戳記，同一天的買賣順序只能照帳本的列順序。")
    A("")

    # ── PF-1 ──
    A("## 3. PF-1：R14 有沒有被遵守")
    A("")
    A("做法：找出 2026-07-29 之後「從零建倉」的部位，看建倉後 30 個日曆日內有沒有清倉，或累計賣掉超過一半。")
    A("「30 天內」的算法和現行的 guard 一樣：賣出日減建倉日小於 30 天。")
    A("類別依 roster 區分：現金等價物是短期公債基金，基準停泊 ETF 是暫時不買個股時停放資金的大盤基金。")
    A("")
    cls = P1["n_new_positions_by_class"]
    rows = []
    for k in ["個股部位", "避險部位", "基準停泊 ETF", "現金等價物"]:
        d = r14[r14["class"] == k]
        if len(d):
            rows.append([k, len(d), int((d.window_complete.astype(str) == "True").sum()), int((d.breach != "無").sum())])
    rows.append(["合計", len(r14), P1["n_window_complete"], P1["n_breach_all"]])
    A(md_table(["類別", "新建部位數", "30 天窗已結束", "窗內清倉或減碼過半"], rows))
    A("")
    A(f"- R14 管的是個股部位，共 {P1['n_stock_positions']} 個，其中 {n_complete} 個的最短持有窗已經結束。")
    n_half = P1["breach_type_stock"].get("減碼過半", 0)
    A(f"- 這 {n_complete} 個裡有 {n_breach} 個在窗內違反。")
    A(f"- 違反的型態：「減碼過半但沒清倉」的有 {n_half} 個，其餘都是清倉。")
    A(f"- 這幾個提前清倉的已實現損益合計 {usd(P1['breach_realised_pnl_stock'])} 美元，"
      f"其中 {P1['breach_n_losing_stock']} 個是賠錢出場。")
    A(f"- 例外的判讀：{n_allowed} 個對得上規則允許的例外。")
    A(f"- 另外 {n_bypass} 個在 journal 明寫是推翻規則，{n_unrec} 個沒有記錄用了哪一種例外。")
    A(f"- 另有 {P1['n_stock_closed_exactly_on_day_30']} 個部位剛好在第 30 天、鎖一解開就清倉；照現行算法不算違反。")
    A(f"- 另有 {P1['n_stock_trim_in_window_not_breach']} 個部位在窗內小幅減碼，沒有超過一半，不算違反。")
    if P1["n_breach_non_stock"]:
        A(f"- 個股以外另有 {P1['n_breach_non_stock']} 筆（現金等價物）是資金停泊的進出，不是 R14 要管的對象，表中單獨列出。")
    A(f"- 帳本裡有 {L['n_void_rows']} 列作廢記錄依預註冊排除。它們是一次系統誤觸的賣出與隔天的補回，發生在某個新倉的 30 天窗內。")
    A("")
    A("窗內清倉或減碼過半的部位（逐筆）：")
    A("")
    br = r14[r14.breach != "無"]
    A(md_table(["代號", "類別", "建倉日", "違反類型", "第幾天", "窗內賣出金額", "已實現損益", "判讀", "判讀依據"],
               [[r.symbol, r["class"], r.established, r.breach, int(float(r.breach_days_after_entry)),
                 usd(r.window_sell_proceeds, False), usd(r.window_sell_realised_pnl), r.exception_reading,
                 r.exception_reading_reason] for _, r in br.iterrows()]))
    A("")
    A("- 「判讀」是人工讀帳本的來源註記欄（origin_evidence）與 journal 之後寫的，存在 `r14_exception_reading.json`。")
    A(f"- 程式另外用關鍵字自動貼了一個初步標籤；兩者歸類不同的有 {P1.get('n_reading_category_differs_from_auto_label', 0)} 個。")
    if n_allowed:
        A("- 被判成例外 1 的部位，依據是建倉當天寫定的「收盤跌破某個價位就賣」。")
        A("- 這是價格條件，而 R14 原文說價格下跌不是例外；它算不算例外，規則本身沒有講清楚。")
    A("")

    # ── PF-2 ──
    A("## 4. PF-2：最短持有的反事實")
    A("")
    A("### 4.1 怎麼算")
    A("")
    A("- 對象是每一段「實際持有不到 N 個交易日就賣掉」的配對段。")
    A("- 實際情況：賣出拿回的錢，改放 SPY、SMH 或現金，一直放到「買進後第 N 個交易日」。現金以零報酬計。")
    A("- 反事實：不賣，抱到買進後第 N 個交易日收盤。")
    A("- 差額 = 反事實的價值 − 實際情況的價值。正數表示「規定抱滿 N 日」會比較好。")
    A("- 股票從賣出日到第 N 日的漲跌，用還原收盤價計算（與 2026-11-18 研究相同的收盤價慣例）。")
    A("- 買進後第 N 個交易日超過價格資料終點的配對段，無法計算，剔除並列出筆數。")
    A("")
    A("### 4.2 主要結果（不帶停損）")
    A("")

    def pf2_rows(version):
        out = []
        for N in C.N_LIST:
            a = row(N, "SPY", version)
            cells = [N, a.n_pieces_held_under_N, a.n_pieces,
                     f"{a.n_excluded_horizon_past_data_end}／{a.n_excluded_no_price_cover}",
                     usd(a.proceeds_sum, False), usd(a.realised_pnl_sum)]
            for alt in C.ALTS:
                r = row(N, alt, version)
                cells.append(f"{usd(r.diff_total)} {ci(r.ci_lo, r.ci_hi)}")
            if version != "no_stop":
                cells.append(f"{a.n_stop_triggered}（{a.n_stop_before_actual_sale}）")
            out.append(cells)
        return out

    head = ["N", "不滿 N 日就賣的段數", "可計算段數", "剔除：未滿 N 日／價格蓋不到", "賣出金額合計", "這些段的實際已實現損益",
            "差額：改放 SPY", "差額：改放 SMH", "差額：放現金"]
    A(md_table(head, pf2_rows("no_stop")))
    A("")
    A("金額單位是美元。方括號是按買進月份整月重抽的 bootstrap 95% 區間。")
    A("")
    A(f"- 硬抱滿 21 個交易日，對「改放 SPY」的差額是 {usd(r21s.diff_total)} 美元，{verdict_word(r21s.ci_lo, r21s.ci_hi, r21s.diff_total)}。")
    A(f"- 這些不滿 21 日就賣的配對段，實際已實現損益合計 {usd(r21s.realised_pnl_sum)} 美元；所以「一個月內的交易賠錢」是事實。")
    if crosses(r21s.ci_lo, r21s.ci_hi):
        A("- 但賠的錢不是因為賣太早：多抱到滿一個月，平均並沒有比較好。")
    A(f"- N = 63：對「改放 SPY」是 {usd(r63s.diff_total)} 美元，{verdict_word(r63s.ci_lo, r63s.ci_hi, r63s.diff_total)}。")
    A(f"- N = 63：對「改放 SMH」是 {usd(r63m.diff_total)} 美元，{verdict_word(r63m.ci_lo, r63m.ci_hi, r63m.diff_total)}。")
    A(f"- N = 126：對「改放 SMH」是 {usd(r126m.diff_total)} 美元，{verdict_word(r126m.ci_lo, r126m.ci_hi, r126m.diff_total)}。")
    cash_cross = [N for N in C.N_LIST if crosses(row(N, "CASH").ci_lo, row(N, "CASH").ci_hi)]
    A("- 「放現金」那一欄偏正，主要是因為這段期間股市整體上漲。"
      + ("三個 N 的區間都跨過 0。" if len(cash_cross) == len(C.N_LIST)
         else f"區間跨過 0 的有 {len(cash_cross)} 個 N。"))
    A("")
    A("### 4.3 帶硬停損的版本")
    A("")
    A("「不准賣」可能放大虧損，所以另算一版：抱的過程中，只要收盤價比成本低 25% 就出場，之後的錢同樣改放 SPY、SMH 或現金。")
    A("")
    A(md_table(head + ["觸發停損的段數（其中比實際賣出還早）"], pf2_rows("hard_stop_25pct")))
    A("")
    hs63s, hs63m = row(63, "SPY", "hard_stop_25pct"), row(63, "SMH", "hard_stop_25pct")
    A(f"- 加上硬停損後，抱滿 63 日對 SPY 的差額變成 {usd(hs63s.diff_total)} 美元。")
    if hs63s.diff_total < r63s.diff_total:
        A("- 停損砍掉的不只是虧損，也砍掉了之後反彈的部分，所以加了停損反而比較差。")
    else:
        A("- 加了停損之後差額變大，表示停損擋掉的虧損多過錯過的反彈。")
    A(f"- 對 SMH 仍然{verdict_word(hs63m.ci_lo, hs63m.ci_hi, hs63m.diff_total)}（{usd(hs63m.diff_total)} 美元）。")
    A("")
    A("### 4.4 分年度、分來源（N = 63，不帶停損）")
    A("")
    yrs = sorted(s2[(s2.fifo_variant == PRIMARY) & (s2.cut_type == "buy_year")].cut_value.unique())
    rows = []
    for y in yrs:
        a = row(63, "SPY", cut_type="buy_year", cut_value=y)
        b = row(63, "SMH", cut_type="buy_year", cut_value=y)
        c = row(63, "CASH", cut_type="buy_year", cut_value=y)
        rows.append([y, a.n_pieces, a.n_buy_months, usd(a.proceeds_sum, False),
                     f"{usd(a.diff_total)} {ci(a.ci_lo, a.ci_hi)}", f"{usd(b.diff_total)} {ci(b.ci_lo, b.ci_hi)}",
                     f"{usd(c.diff_total)} {ci(c.ci_lo, c.ci_hi)}"])
    A(md_table(["買進年度", "段數", "買進月份數", "賣出金額合計", "差額：改放 SPY", "差額：改放 SMH", "差額：放現金"], rows))
    A("")
    rows = []
    for o, name in (("system", "system（系統依計畫下的單）"), ("user", "user（使用者臨時下的單）"), ("unknown", "unknown（無法判定）")):
        a = row(63, "SPY", cut_type="buy_origin", cut_value=o)
        b = row(63, "SMH", cut_type="buy_origin", cut_value=o)
        c = row(63, "CASH", cut_type="buy_origin", cut_value=o)
        rows.append([name, a.n_pieces, a.n_buy_months, usd(a.proceeds_sum, False),
                     f"{usd(a.diff_total)} {ci(a.ci_lo, a.ci_hi)}", f"{usd(b.diff_total)} {ci(b.ci_lo, b.ci_hi)}",
                     f"{usd(c.diff_total)} {ci(c.ci_lo, c.ci_hi)}"])
    A(md_table(["買進的來源", "段數", "買進月份數", "賣出金額合計", "差額：改放 SPY", "差額：改放 SMH", "差額：放現金"], rows))
    A("")
    cs, cm = rd["checks"]["SPY"], rd["checks"]["SMH"]
    A(f"- 2025 年買進的批次對 SPY 是 {usd(cs['diff_2025'])} 美元。")
    A(f"- 2026 年買進的批次對 SPY 是 {usd(cs['diff_2026'])} 美元，和前一年方向{'相同' if cs['years_same_sign'] else '相反'}。")
    A(f"- 2025 年買進的批次對 SMH 是 {usd(cm['diff_2025'])} 美元。")
    A(f"- 2026 年買進的批次對 SMH 是 {usd(cm['diff_2026'])} 美元，和前一年方向{'相同' if cm['years_same_sign'] else '相反'}。")
    un = row(63, "SPY", cut_type="buy_origin", cut_value="unknown")
    A(f"- 來源欄有 {un.n_pieces} 段是 unknown，system 與 user 的樣本太少，分來源的數字只能當參考。")
    A("- N = 21 與 N = 126 的分年度、分來源數字在 `min_hold_counterfactual.csv`。該檔另有「按賣出的來源分」的補充切法。")
    A("")
    A("### 4.5 事前寫定的讀法")
    A("")
    A("預註冊寫明：「把 R14 拉長到 63 個交易日」只有在下面四個條件都成立時才算有支持。")
    A("")
    yn = lambda b: "成立" if b else "不成立"  # noqa: E731
    A(md_table(["條件（N = 63，不帶停損）", "改放 SPY", "改放 SMH"], [
        ["差額為正", f"{yn(cs['positive'])}（{usd(cs['diff_total'])}）", f"{yn(cm['positive'])}（{usd(cm['diff_total'])}）"],
        ["區間不含 0", f"{yn(cs['ci_excludes_zero'])} {ci(cs['ci_lo'], cs['ci_hi'])}",
         f"{yn(cm['ci_excludes_zero'])} {ci(cm['ci_lo'], cm['ci_hi'])}"],
        ["2025 與 2026 兩個子樣本同向且為正", yn(cs["years_both_positive"]), yn(cm["years_both_positive"])],
        ["這個假設下全部成立", yn(cs["all_conditions"]), yn(cm["all_conditions"])],
    ]))
    A("")
    A(f"**判定：{'有支持' if supported else '沒有支持'}。**（條件要求對 SPY 與 SMH 兩種假設都成立。）")
    A("")
    if cm["ci_excludes_zero"] and not cm["positive"]:
        A("- 對 SMH 的區間雖然不含 0，但方向是負的：抱滿 63 日明顯比換成 SMH 差。")
    allv = P2["prewritten_reading_all_variants"]
    n_sup = sum(1 for x in allv.values() if x["extend_r14_to_63_supported"])
    A(f"- 換成帶硬停損的版本、補上帳本之前庫存的對照版、或改用專案拆股表的對照版，共 {len(allv)} 種組合，判定為「有支持」的有 {n_sup} 種。")
    sd = row(63, "SPY", variant=SEEDED)
    sdm = row(63, "SMH", variant=SEEDED)
    A(f"- 補上帳本之前庫存的對照版，抱滿 63 日對 SPY 是 {usd(sd.diff_total)} 美元。")
    A(f"- 同一個對照版對 SMH 是 {usd(sdm.diff_total)} 美元。")
    A("")
    A("### 4.6 這個數字有多集中")
    A("")
    c1, c2 = conc["SPY"], conc["SMH"]
    A("- 抱滿 63 日對 SPY 的差額很集中在少數月份。")
    A(f"- 拿掉貢獻最大的三個買進月份，總數就從 {usd(c1['total'])} 變成 {usd(c1['total_without_top3_months'])} 美元。")
    A(f"- 按代號看，{c1['n_symbols']} 個代號裡只有 {c1['n_symbols_positive']} 個的差額是正的。")
    A(f"- 對 SMH 的差額拿掉最好的三個月份後是 {usd(c2['total_without_top3_months'])} 美元，"
      + ("仍然是負的，所以負的結論不靠少數月份。" if c2["total_without_top3_months"] < 0 and c2["total"] < 0 else "方向會改變。"))
    pr = conc["post_r14_pieces_by_N"]
    A(f"- R14 生效後買進、又提早賣掉的配對段有 {pr['63']['n_held_under_N']} 段。")
    A(f"- 其中只有 {pr['63']['n_ok']} 段已經滿 63 個交易日、算得出來。")
    A("- 所以這一節幾乎全是 R14 生效之前的交易；它回答不了「R14 生效後」的行為有沒有變好。")
    A("")

    # ── PF-3 ──
    A("## 5. PF-3：買進有沒有贏基準")
    A("")
    A("做法：每一筆買進都假設固定抱 63 或 126 個交易日，進場價用買進當天的還原收盤價，再減掉同期間 SMH 或 QQQ 的報酬。")
    A("「半導體／AI 硬體」的分組用專案現成的名單（`tools/trade_ledger.py` 的 SEMI_AI），其餘歸「其他」（含 ETF）。")
    A("")
    for bench in C.HURDLE_BENCH:
        rows = []
        for g in ["全部", "半導體／AI 硬體", "其他"]:
            for H in C.H_LIST:
                r = hrow("全部", g, H, bench)
                rows.append([g, H, r.n_ok, r.n_symbols, r.n_months,
                             f"{r.n_dropped_horizon_past_data_end}／{r.n_dropped_no_price_cover}",
                             f"{pp(r.excess_mean_ew)} {ci(r.excess_ew_ci_lo, r.excess_ew_ci_hi, pp)}",
                             f"{pp(r.excess_mean_nw)} {ci(r.excess_nw_ci_lo, r.excess_nw_ci_hi, pp)}",
                             pp(r.excess_median), pct(r.hit_rate)])
        A(f"**對 {bench} 的超額（百分點）**")
        A("")
        A(md_table(["分組", "抱幾個交易日", "可計算筆數", "代號數", "買進月份數", "剔除：未滿／價格蓋不到",
                    "等權平均", "金額加權平均", "中位數", "勝率"], rows))
        A("")
    A("「等權平均」把每筆買進看成一樣重；「金額加權平均」依買進金額加權；「勝率」是超額大於零的筆數比例。")
    A("")
    A(f"- 全部買進抱 63 個交易日，對 SMH 平均{win(all63m.excess_mean_ew)} {abs(all63m.excess_mean_ew) * 100:.1f} 個百分點。")
    A(f"- 對 QQQ 則是 {pp(all63q.excess_mean_ew)} 個百分點，{verdict_word(all63q.excess_ew_ci_lo, all63q.excess_ew_ci_hi, all63q.excess_mean_ew)}。")
    def both_clear(a, b):
        return not crosses(a.excess_ew_ci_lo, a.excess_ew_ci_hi) and not crosses(b.excess_ew_ci_lo, b.excess_ew_ci_hi)

    A(f"- 半導體／AI 硬體組抱 63 個交易日，對 SMH 是 {pp(semi63.excess_mean_ew)} 個百分點。")
    A(f"- 同一組抱 126 個交易日是 {pp(semi126.excess_mean_ew)} 個百分點。"
      + ("兩個區間都不含 0。" if both_clear(semi63, semi126) else "區間有跨過 0 的。"))
    A(f"- 但這一組 63 日的中位數是 {pp(semi63.excess_median)} 個百分點。")
    A(f"- 勝率是 {pct(semi63.hit_rate)}，大約一半。" if 0.4 <= semi63.hit_rate <= 0.6 else f"- 勝率是 {pct(semi63.hit_rate)}。")
    if semi63.excess_median < semi63.excess_mean_ew:
        A("- 中位數比平均低很多，表示平均是被少數大贏家拉上去的。")
    A(f"- 其他組抱 63 個交易日，對 SMH 是 {pp(oth63.excess_mean_ew)} 個百分點。")
    A(f"- 同一組抱 126 個交易日是 {pp(oth126.excess_mean_ew)} 個百分點。"
      + ("兩個區間都不含 0。" if both_clear(oth63, oth126) else "區間有跨過 0 的。"))
    A(f"- 其他組 63 日對 QQQ 是 {pp(oth63q.excess_mean_ew)} 個百分點，"
      f"{verdict_word(oth63q.excess_ew_ci_lo, oth63q.excess_ew_ci_hi, oth63q.excess_mean_ew)}。")
    if semi63.excess_mean_ew > 0 > oth63.excess_mean_ew:
        A("- 白話：你在半導體與 AI 硬體裡選股有加分；在這個圈子以外的買進，平均不如直接買 SMH。")
    A("")
    A("### 5.1 R35 上線後有沒有改善")
    A("")
    A(f"- R35 在 {r35['r35_effective']} 採用。之後的買進有 {r35['n_buys_after_r35']} 筆，其中從零建倉的新部位有 {r35['n_new_position_buys_after_r35']} 筆。")
    A(f"- 這些買進到資料終點最多只過了 {r35['max_sessions_elapsed_since_r35']} 個交易日。")
    A(f"- 滿 63 個交易日的有 {r35['n_after_r35_with_63_sessions']} 筆。")
    A("- **樣本是零，現在完全無法判斷 R35 有沒有改善。** 預註冊沒有列更短的週期，所以這裡不另外算。")
    A(f"- 第一筆滿 63 個交易日最早大約在 {first63}。")
    A(f"- 第一筆滿 126 個交易日最早大約在 {first126}。這兩個日期沒有扣掉假日，實際會再晚幾天。")
    A("- 上表「全部」那幾列實際上就是 R35 之前的基準線，之後可以拿來比。")
    A("")

    # ── PF-4 pointer ──
    A("## 6. PF-4：規則建議")
    A("")
    A("三條建議的原文與建議文並列在 `rule-proposal.md`。規則檔本身沒有被改動。重點：")
    A("")
    A("1. R14 的窗長維持 30 個日曆日，不延長到 63 個交易日；把規則理由那一段改寫成和這次的數字一致。")
    A("2. R14 的例外要逐筆寫上編號；寫不出編號的一律記成推翻規則，並計入失效次數。")
    A("3. R35 的計分加上「買進後 63、126 個交易日對 SMH 與 QQQ 的超額」，分兩組記錄，並寫明現在的基準線。")
    A("")

    # ── interpretation choices ──
    A("## 7. 解讀上的選擇（預註冊沒有寫死的地方）")
    A("")
    choices = [
        "配對只用帳本內的成交（專案慣例、與 2026-11-18 研究相同）。帳本之前的庫存另跑對照版，不取代主要版本。",
        "拆股倍數由價格推定，不用專案的拆股表；因為價格與券商持股都顯示拆股表不完整。用拆股表的版本列為對照。",
        "反事實的差額以「賣出拿回的實際金額」為基礎，乘上還原收盤價從賣出日到第 N 日的變動。也就是把賣出視為發生在當天收盤。",
        "「現金」以零報酬計，不加利息。",
        "硬停損從買進日起逐日檢查收盤價；觸發後的錢和實際情況一樣，改放 SPY、SMH 或現金到第 N 日。停損有可能比實際賣出還早。",
        "「收盤 ÷ 成本」用（賣出金額 ÷ 成本）乘上還原價的變動來還原，成本含手續費。",
        "分年度用「買進日」的年度；分來源用「買進那一筆」的來源。按賣出來源的切法只當補充。",
        "bootstrap 的統計量是差額的總和，按買進月份整月重抽 10,000 次，亂數種子固定。",
        "「2025 與 2026 同向」採保守讀法：兩年都要是正的才算成立。",
        "事前寫定的讀法只用「不帶停損、主要配對版本」判定；其他版本只列出來當穩健性對照。",
        "R14 的「30 天內」沿用現行 guard 的算法（賣出日減建倉日小於 30 天）。剛好第 30 天清倉不算違反，但另外列出筆數。",
        "「從零建倉」沿用現行 guard 的口徑：只看帳本、持股不低於 0。另外核對過這些新部位在帳本之前都沒有庫存。",
        "「減碼過半」定義為：窗內累計賣出超過「截至該筆的累計買進」的一半。",
        "PF-1 涵蓋所有新建的股票與 ETF 部位，但依 roster 把現金等價物、基準停泊、避險部位分開列；結論以個股部位為準。",
        "例外的判讀以人工讀帳本與 journal 為準，存在結果目錄的 JSON 檔；程式的關鍵字標籤只當初篩。",
        "PF-3 的分組用專案現成的 SEMI_AI 名單；ETF 一律歸「其他」。進場價用買進日還原收盤（與 2026-11-18 研究相同）。",
        "PF-3 只算預註冊列的 63 與 126 個交易日；R35 之後沒有樣本，不另外加更短的週期。",
        "ranker 的價格排在來源優先序的最後，而且只讀到 2025-12-31。",
        "價格日曆以 SPY 有價格的日子為準；之後到最後一筆成交之間的兩天只用來數交易日，沒有價格。",
        "多出的輸出（不影響任何判定）：split_validation.csv、min_hold_pieces.csv、hurdle_fills.csv、r14_exception_reading.json。",
    ]
    for i, c in enumerate(choices, 1):
        A(f"{i}. {c}")
    A("")

    # ── weaknesses ──
    A("## 8. 弱點與可疑之處")
    A("")
    weak = [
        "這不是帳戶層級的模擬。同一筆錢賣掉再買、再賣，會在不同配對段裡各算一次；總金額不能解讀成「帳戶會多賺或少賺這麼多」。",
        "反事實沒有考慮：錢被鎖住之後，後面那些交易就不會發生。它只回答「這一段如果多抱幾天」這個局部問題。",
        f"樣本偏近期：N = 63 的配對段裡，有 {row(63, 'SPY', cut_type='buy_year', cut_value='2026').n_pieces} 段是今年買進的，超過一半。",
        f"獨立資訊遠少於段數：只有 {r63s.n_buy_months} 個買進月份，而且持有期間彼此重疊。",
        "N = 63 對 SPY 的正差額靠少數幾個月份撐起來（見 4.6），不能當成穩定的現象。",
        "R14 生效後的交易幾乎都還沒滿 63 個交易日，所以 PF-2 主要在描述 R14 之前的行為。",
        f"PF-1 的樣本很小：只有 {n_complete} 個已滿期的新個股部位。{n_breach} 個違反是個案，不是統計結論。",
        "例外的判讀含人工判斷，尤其「建倉時寫定的價格線算不算例外 1」可以有不同看法。",
        "帳本之前的庫存會讓部分配對的持有天數偏短；對照版顯示結論不變，但金額會差幾千美元。",
        "同一天內的買賣順序在 2025 年以前無法確定，極少數當日買賣的配對可能配錯。",
        "賣出價以當天收盤代替實際成交價來推算之後的走勢；盤中賣在高點或低點的差異沒有算進去。",
        f"N = 126 有 {row(126, 'SPY').n_excluded_no_price_cover} 段因為價格序列蓋不到而剔除，多半是今年春天買的小型股；這會讓半年那一列的數字略有偏差。",
        f"價格有 {PR['pf2_share_from_eod_cache'] * 100:.0f}% 來自簡報用的快取檔，不同批次抓的還原基準可能不同；本研究用「一筆報酬只用同一批抓取的資料」避開，但沒有逐一核對原始資料。",
        "PF-3 沒有做 beta 調整（beta 是對大盤漲跌的敏感度）。半導體組贏 SMH，有一部分可能只是持股波動比 SMH 大、又剛好遇到上漲期。",
        "PF-3 的「其他」組混了個股、避險 ETF 與現金停泊 ETF；拿它們去比 SMH 本來就不公平，數字偏負有一部分是分類造成的。",
        "R35 之後的樣本是零，任何「R35 有沒有用」的說法現在都沒有根據。",
        f"帳本有 {fi['n_sells_fully_unmatched'] + fi['n_sells_partially_unmatched']} 筆賣出沒有完全配到買進；這些不在任何一張表裡。",
        f"專案的拆股表缺 {SP['n_symbols_missing_from_table']} 個代號。這不影響本研究（已改用價格推定），但會影響專案裡其他用到拆股表的工具算出的已實現損益。",
        "來源欄大多是 unknown，「系統單」與「使用者單」的比較沒有足夠樣本。",
    ]
    for w in weak:
        A(f"- {w}")
    A("")
    A("## 9. 檔案")
    A("")
    A("- 程式：`tools/backtests/overnight_2026-11-19/ledger/` 的 `ledger_common.py`、`pf_run.py`、`pf_report.py`、`test_ledger.py`。")
    A("- 結果（本目錄，全部在 gitignore 路徑）：")
    A("  - `r14_compliance.csv`：PF-1，每個新建部位一列。`r14_exception_reading.json`：人工判讀。")
    A("  - `min_hold_counterfactual.csv`：PF-2 的彙總（三種配對版本 × 兩種停損版本 × N × 改放標的 × 切法）。")
    A("  - `min_hold_pieces.csv`：PF-2 逐段明細（主要版本）。")
    A("  - `hurdle.csv`：PF-3 的彙總。`hurdle_fills.csv`：逐筆明細。")
    A("  - `split_validation.csv`：拆股比對。")
    A("  - `rule-proposal.md`：PF-4 規則建議。`verdict.json`：機器可讀的全部數字。")
    A(f"- 執行時間：計算約 {v['runtime_sec']} 秒。")
    (C.OUT / "summary.md").write_text("\n".join(S) + "\n", encoding="utf-8")

    # ══ rule-proposal.md ══
    why_orig = rule_text(HOLDING_RULE, r"^\*\*Why：\*\* 短於一個月", 2)
    r14_orig = rule_text(HOLDING_RULE, r"^新建倉（該標的從零建倉）", 1)
    r35_orig = rule_text(HURDLE_RULE, r"^命中 = 被擋的名字 90 日", 1)
    hs21 = row(21, "SPY", "hard_stop_25pct")
    R: list[str] = []
    B = R.append
    B("# PF-4：規則修改建議（隔夜研究 2026-11-19）")
    B("")
    B("本檔含由個人帳本算出的數字，只能留在 gitignore 的路徑。")
    B("這些只是建議。規則檔沒有被改動，要不要採用由你決定。")
    B("所有數字都是描述性的，只能用來提名想法，不是驗證過的結論。")
    B("")
    B("名詞：**R14** 是新倉 30 個日曆日最短持有的規則。**R35** 是新名字要預期贏過基準 ETF 才能買的規則。"
      "**交易日**是股市有開盤的日子。**SPY、QQQ、SMH** 是追蹤大盤、那斯達克 100、半導體類股的 ETF。"
      "**區間**指按買進月份重抽的 bootstrap 95% 區間，跨過 0 表示分不出正負。"
      "規則原文裡的 **pp** 是百分點，**α** 是超額報酬，**PASS** 是通過門檻，**thesis** 是買進理由與它的失效條件，"
      "**bypass** 是推翻規則，**journal** 是每天的交易日誌。")
    B("")
    B("## 建議 1：R14 的窗長不延長；改寫理由那一段")
    B("")
    B("檔案：`feedback/holding-period-discipline.md`，「規則 1（R14）」的 Why 段。")
    B("")
    B("**原文**")
    B("")
    B("> " + why_orig.replace("\n", "\n> "))
    B("")
    B("**建議文**")
    B("")
    B("> **Why：** 一個月內就賣掉的交易，已實現損益合計為負（上表）。"
      "但 2026-11-19 的反事實檢查顯示，把這些交易硬抱滿 21 個交易日，結果與實際分不出差別。"
      "拉長到 63 個交易日，對「賣掉改放 SPY」仍分不出正負，對「賣掉改放 SMH」則明顯更差。"
      "所以短線賠錢主要出在買進本身，不是賣得太早。"
      "這條閘的作用是擋掉情緒性的換手，不是提高報酬；窗長維持 30 個日曆日，不延長。")
    B("")
    B("**支持的數字**")
    B("")
    B(md_table(["項目", "數字", "樣本"], [
        ["不滿 21 個交易日就賣的配對段，實際已實現損益", f"{usd(r21s.realised_pnl_sum)} 美元", f"{r21s.n_pieces} 段、{r21s.n_buy_months} 個買進月份"],
        ["硬抱滿 21 日 vs 賣掉改放 SPY", f"{usd(r21s.diff_total)} 美元 {ci(r21s.ci_lo, r21s.ci_hi)}", f"{r21s.n_pieces} 段"],
        ["硬抱滿 63 日 vs 賣掉改放 SPY", f"{usd(r63s.diff_total)} 美元 {ci(r63s.ci_lo, r63s.ci_hi)}", f"{r63s.n_pieces} 段、{r63s.n_buy_months} 個買進月份"],
        ["硬抱滿 63 日 vs 賣掉改放 SMH", f"{usd(r63m.diff_total)} 美元 {ci(r63m.ci_lo, r63m.ci_hi)}", f"{r63m.n_pieces} 段"],
        ["同上，2025 年買進／2026 年買進（對 SPY）", f"{usd(cs['diff_2025'])}／{usd(cs['diff_2026'])} 美元", "兩年方向" + ("相同" if cs["years_same_sign"] else "相反")],
        ["加上「自成本跌 25% 出場」的硬停損，63 日對 SPY", f"{usd(hs63s.diff_total)} 美元 {ci(hs63s.ci_lo, hs63s.ci_hi)}", f"{hs63s.n_stop_triggered} 段觸發停損"],
        ["加上硬停損，21 日對 SPY", f"{usd(hs21.diff_total)} 美元 {ci(hs21.ci_lo, hs21.ci_hi)}", f"{hs21.n_stop_triggered} 段觸發停損"],
    ]))
    B("")
    B(f"- 事前寫定的四個條件{'全部成立' if supported else '沒有全部成立'}，所以「拉長到 63 個交易日」{'有' if supported else '沒有'}支持。")
    B(f"- 換成帶硬停損或兩種對照配對的版本，共 {len(allv)} 種組合，判定為「有支持」的有 {n_sup} 種。")
    B("- 限制：這些配對段幾乎都發生在 R14 生效之前；金額是逐段加總，不是帳戶層級的模擬。")
    B("")
    B("## 建議 2：R14 的例外要逐筆寫上編號")
    B("")
    B("檔案：`feedback/holding-period-discipline.md`，「規則 1（R14）」的第一句與例外清單之後。")
    B("")
    B("**原文**")
    B("")
    B("> " + r14_orig.replace("\n", "\n> "))
    B("")
    B("**建議文**")
    B("")
    B("> " + r14_orig)
    B(">")
    B("> （這一句與後面三種例外的清單都不變。在清單之後加一段：）")
    B(">")
    B("> **記錄方式：** 每一筆窗內清倉或減碼過半的賣出，都要在帳本該筆成交的備註寫上它是第幾種例外，以及引用的條目。"
      "寫不出編號的一律記成 `bypass`，並計入 R14 的失效次數。"
      "建倉時寫定的收盤價線如果要算例外 1，必須在建倉當天就登錄成 thesis 條目；事後補寫的不算。")
    B("")
    B("**支持的數字**")
    B("")
    B(md_table(["項目", "數字"], [
        ["R14 生效後從零建倉的個股部位", f"{P1['n_stock_positions']} 個"],
        ["其中 30 天窗已結束", f"{n_complete} 個"],
        ["窗內清倉", f"{n_breach} 個"],
        ["判讀：對得上允許的例外", f"{n_allowed} 個（依據是建倉時寫定的收盤價線）"],
        ["判讀：journal 明寫推翻規則", f"{n_bypass} 個"],
        ["判讀：沒有記錄用了哪一種例外", f"{n_unrec} 個"],
        ["這幾個提前清倉的已實現損益合計", f"{usd(P1['breach_realised_pnl_stock'])} 美元"],
        ["剛好在第 30 天、鎖一解開就清倉", f"{P1['n_stock_closed_exactly_on_day_30']} 個"],
    ]))
    B("")
    B(f"- 樣本只有 {n_complete} 個部位，這是個案整理，不是統計結論。")
    B("- 這條建議不改變能不能賣，只要求留下記錄，讓之後算得出規則到底被推翻了幾次。")
    B("")
    B("## 建議 3：R35 的計分加上固定週期的超額")
    B("")
    B("檔案：`feedback/new-position-benchmark-hurdle.md`，「計分（RULES-LEDGER R35）」。")
    B("")
    B("**原文**")
    B("")
    B("> " + r35_orig.replace("\n", "\n> "))
    B("")
    B("**建議文**")
    B("")
    B("> " + r35_orig + " "
      "PASS 進場者另外固定記錄買進後 63 與 126 個交易日對 SMH、QQQ 的超額，"
      "分「半導體／AI 硬體」與「其他」兩組，和 R35 之前的基準線比較。"
      f"基準線：抱 63 個交易日對 SMH，半導體組是 {pp(semi63.excess_mean_ew)} 個百分點。"
      f"其他組是 {pp(oth63.excess_mean_ew)} 個百分點。"
      f"第一筆滿 63 個交易日最早約在 {first63}；筆數太少時只列數字，不下結論。")
    B("")
    B("**支持的數字**")
    B("")
    rows = []
    for g in ["半導體／AI 硬體", "其他", "全部"]:
        for H in C.H_LIST:
            a, b = hrow("全部", g, H, "SMH"), hrow("全部", g, H, "QQQ")
            rows.append([g, H, f"{a.n_ok} 筆、{a.n_symbols} 個代號",
                         f"{pp(a.excess_mean_ew)} {ci(a.excess_ew_ci_lo, a.excess_ew_ci_hi, pp)}",
                         f"{pp(b.excess_mean_ew)} {ci(b.excess_ew_ci_lo, b.excess_ew_ci_hi, pp)}", pct(a.hit_rate)])
    B(md_table(["分組", "抱幾個交易日", "樣本", "對 SMH 的超額（百分點，等權）", "對 QQQ 的超額（百分點，等權）", "對 SMH 的勝率"], rows))
    B("")
    B(f"- R35 採用後的買進有 {r35['n_buys_after_r35']} 筆。")
    B(f"- 其中滿 63 個交易日的有 {r35['n_after_r35_with_63_sessions']} 筆，所以現在無法評估 R35。")
    B("- 上表全部是 R35 之前的買進，可以當成之後比較用的基準線。")
    B("- 限制：沒有做 beta 調整（beta 是對大盤漲跌的敏感度）；「其他」組混了避險與停泊用的 ETF。")
    B("")
    B("## 不屬於規則的工具修正（順帶提出）")
    B("")
    B(f"- `tools/trade_ledger.py` 的拆股表只列了 {SP['n_symbols_in_ledger_split_table']} 個代號，"
      f"價格資料顯示交易過的代號裡有 {SP['n_symbols_with_price_implied_split']} 個拆過股。")
    B(f"- 缺的代號裡有 {SP['n_missing_symbols_whose_fills_straddle_the_split']} 個的成交橫跨拆股日，會讓先進先出配對與已實現損益算錯。")
    B(f"- 兩種做法的已實現損益合計相差 {usd(abs(SP['realised_pnl_ledger_table'] - SP['realised_pnl_price_implied']), False)} 美元。")
    B("- 缺哪些代號、倍數多少，見 `split_validation.csv`。這是程式修正，不是規則修改。")
    (C.OUT / "rule-proposal.md").write_text("\n".join(R) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
    print("wrote", C.OUT / "summary.md")
    print("wrote", C.OUT / "rule-proposal.md")
