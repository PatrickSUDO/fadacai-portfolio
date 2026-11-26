#!/usr/bin/env python3
"""日頻趨勢開關（EMA100／MACD 線 24,52／兩者「或」「且」）搬到美股有沒有幫助 — 2026-11-16

來源：台股專案 fadacai-tw 同日測出「日頻檢查 + 連續 3 日確認 + 次日執行」的 EMA100、MACD 線 (24,52) 與兩者合併
在 00631L／00878／現金三資產組合上 Calmar 高於年再平衡（增益幾乎全在回撤）。問題是同一套開關對本專案三層結構有沒有用。
既有裁決（不重做）：`parking_exit_rules_2026-11-10.py` SMA200 月頻退場 2010 後少賺 4.5pp／年 → 不加；
`hmm_regime_timing_2026-11-09.py` SMA200 日頻對照；`feedback/ma-filter-evidence.md` 個股層 MACD 任何用法 ≈ 基準。

══ 事先寫定（跑之前寫完，跑完不加變體）══

指標（收盤後算，全用含息調整收盤）：
  ema_100          = 價 / EMA100 − 1 > 0
  macd_line_24_52  = (EMA24 − EMA52) / 價 > 0
  ema100 或 macd   = 兩者任一 > 0 就持有（兩者都轉空才出場）
  ema100 且 macd   = 兩者都 > 0 才持有
節奏：每日收盤判定；合併後的原始狀態與現行狀態連續 3 個交易日不同才翻；翻的那天收盤後決定、次一交易日收盤執行
  → 新部位從再下一日的報酬開始算（shift 2，比 parking_exit 的 shift 1 保守一天）。
出場期間放 T-bill（^IRX/252，下限 0）。不加槓桿，曝險只在 {1, 出場值} 之間。

三層：
  1 指數層（停泊池／基準格）：SPY（代 VOO）、QQQ、SMH、IGV 各自用自己的訊號，持有或全退 T-bill。4 規則 × 4 標的 = 16 個候選。
    QQQ 上市前（1999-03）用 ^NDX、SMH 上市前（2000-05）用 ^SOX 的價格報酬接上，只為了讓 2000 年有暖身完的訊號。
  2 組合層：P0 = 52% SMH + 33% IGV + 15% SPY 月底再平衡（`structure_alternatives_2026-10-23/portfolio_fit`）。
    訊號來源兩種：SPY（台股「看大盤切組合」的對應）、P0 自己的淨值；出場深度兩種：全退（0%）、減半（50%）。
    4 規則 × 2 來源 × 2 深度 = 16 個候選。
  3 個股層（描述性，不進判定）：30 檔宇宙（同 `trendline_regression_2026-11-07.py`：14 持倉 + 12 候補 + 4 曾持有），
    各股自己的訊號全退 T-bill。這份名單是今天看得到的名單 → 倖存者偏差，買進持有那一邊被灌水，只當方向參考。
  候選合計 32 個（第 1、2 層）；多重檢定校正的分母 = 32。

對照（不算候選）：買進持有；SMA200 月底判定次日生效（= parking_exit 的 A，照原語意 shift 1）；
  SMA200 日頻 + 同一個 3 日確認節奏（分離「節奏」與「指標種類」）。

窗：W1 = 2000-01-03 → 2009-12-31；W2 = 2010-01-04 → 2026-11-13；全期 = 兩者相連。
  IGV 2001-07 才上市，IGV 與 P0 的 W1 從上市滿 252 個交易日（約 2002-07）起算，沒有 2000–2002 的主跌段，照實標示。
  個股層 S1 = 2021-09-01 → 2023-12-29、S2 = 2024-01-02 → 2026-11-13。

成本與稅：ETF 每次完整切換扣 10bp（ETF 一腿 5bp 滑價 + SGOV 一腿，零手續費）；個股每次 20bp。
  NRA 帳戶無資本利得稅 → 不扣賣出稅。股息與 T-bill 利息的預扣未建模（對買進持有略有利，量級 <0.4pp／年）；
  另對各層最佳候選報穩健性：成本 0／30bp、T-bill 報酬 ×0.7（當作利息被預扣 30%）、執行早一天（shift 1）。

報：CAGR、MaxDD、Sharpe（對 T-bill 超額）、Calmar、在市比例、每年切換次數、10 個交易日內反覆比例
  （完整持有段落中短於 10 日的比例）；對買進持有的 ΔCAGR（少賺／多賺）與 ΔMDD（少掉的回撤）分開列；
  出場段落數、躲對幾段（出場期間標的下跌）、出場期間標的平均報酬。

置換檢定：把「已含 3 日確認與執行延遲的曝險序列」在該窗內圓形位移 k 日，k 取 252 … n−252 的每一個值（不抽樣），
  統計量 = Calmar − 買進持有 Calmar（主）、Sharpe 差（副）；單尾 p = (1 + 位移後 ≥ 實測的個數) / (位移數 + 1)。
  位移保留在市比例、切換次數與段落長度，只打掉「時點」。32 個候選各窗都算，Benjamini-Hochberg q 與 Bonferroni 都報。

判定（預先寫死）：
  「過線」= 兩窗都滿足〔CAGR ≥ 買進持有 − 2pp 且 MaxDD 淺 ≥ 5pp〕，且全期置換 q_BH < 0.10。
  「只有回撤保護」= 兩窗 MaxDD 都淺 ≥ 5pp，但任一窗 CAGR 少賺 > 2pp 或置換沒過。
  其餘 =「沒有幫助」。只在一窗成立不算。
  對 parking_exit 裁決是否翻盤的判準：SPY 2010→ 的候選 CAGR 是否 ≥ 買進持有 − 2pp。

已知缺陷：2000→ 只有三次長空頭（2000–02、2008、2022）+ 2020 急跌，W1 的好處靠前兩次；接上的 ^NDX／^SOX 是價格指數
  （不含息，該年代股息 <0.5%）；個股層單一多頭 regime 且倖存者偏差；P0 權重是代表組合不是帳戶實際持倉。

用法：python3 tools/backtests/trend_switch_ema_macd_2026-11-16.py [--refresh]
  價格快取 data/<同名>.px.pkl（首跑下載，--refresh 重抓）；輸出同時寫 data/<同名>.out.txt。

══ 首跑結論（2026-11-16，資料至 2026-11-13）══
判定：32 個候選「過線」0 個、「只有回撤保護」27 個、「沒有幫助」5 個。**不加。與 parking_exit 裁決一致，沒有翻盤。**
- 指數層 2010→ 全部少賺 5–10pp／年：SPY 買進持有 14.0%／MDD −33.7%；ema_100 8.7%／−19.7%、macd 6.9%／−25.7%、
  「或」8.7%／−24.9%、「且」7.3%／−21.7%；對照 SMA200 月頻 9.3%／−24.5%（= parking_exit 的 9.5% 扣成本）、SMA200 日頻＋3 日 9.7%／−18.9%。
  QQQ 18.4% → 9.7–11.2%；SMH 24.7% → 15.2–16.2%；IGV 15.4% → 7.8–10.1%。回撤淺 4–16pp，Calmar 只有 SPY ema_100（0.44 vs 0.42）勉強持平，其餘都低於買進持有。
- 指數層 2000–2009 才是好處所在：SPY −1.0%／−55.2% → 2.2–4.1%／−24 到 −28%；QQQ −6.4%／−83.0% → 3.9–5.4%／−36 到 −44%；
  SMH −7.4%／−87.1% → −1.8 到 +4.8%／−62 到 −69%（半導體連日頻開關也擋不住六成回撤）。IGV 的 W1 沒有 2000–02，連 W1 都少賺 2–8pp。
- 組合層 P0：2002-07→2009 買進持有 5.2%／−56.0% → 全退 4.8–10.3%／−23.5 到 −27%；2010→ 20.5%／−41.3% → 全退 10.3–15.3%、減半 15.6–18.3%。
  最接近過線的是「ema_100｜訊號 P0 自身淨值｜減半」：2010→ 少賺 2.3pp、回撤淺 12.3pp、Calmar 0.63 vs 0.50，但置換 p 0.024 校正後 q_BH 0.35 → 沒過。
  用 SPY 當訊號（台股「看大盤切組合」的對應）在 2010→ 最差：「或｜全退」出場 26 段 0 段躲對、MDD 反而深 0.7pp。
- 置換檢定（圓形位移，Calmar 增益）：W1 有 17／32 個 q_BH < 0.10；**W2 是 0／32**（最小 p 0.024、q 0.35、Bonferroni 0.75）；
  全期 20／32 過 q 0.10 但全靠 W1，Bonferroni 只剩 QQQ ema_100（0.046）。Sharpe 差：W2 沒有任何一個 p < 0.05，全期 0 個過 q 0.10。
  → 有統計訊號的只有「2000–02 與 2008 兩次長空頭躲得掉」，不是可重複的時點能力；只在一窗成立，照預先寫的規則不算。
- 出場段落 2010→：SPY ema_100 出場 34 段躲對 5 段、「或」26 段躲對 3 段，出場期間 SPY 平均 +2.4 到 +4.1%（每次出場平均買回更貴）。
- 台股的兩個發現都沒有複製：①「或」不是最好——SPY 2010→ Calmar 0.35 低於 ema_100 的 0.44，P0 自身訊號反而「且」（0.56）高於「或」（0.48）；
  ②「日頻＋3 日確認」不是關鍵——SMA200 換成這個節奏，2010→ 略好（9.7%／−18.9% vs 9.3%／−24.5%）、2000–2009 較差（5.7%／−18.1% vs 7.8%／−11.4%）。
  切換次數：ema_100 每年 4–6 次、10 日內反覆 21–37%；macd 每年 3–4 次、反覆 0–18%。
- 個股層（描述性、倖存者偏差）：等權籃子 2021-09→2023 買進持有 11.7%／−43.5% → 開關 7.3–11.1%／−19 到 −24%；2024→ 55.7%／−32.0% → 35–41%／−16 到 −17%；
  逐檔 CAGR 中位少 2.3–5.3pp（S1）、8.5–17.8pp（S2）。轉空事件之後 20 日：ema_100 +3.78%、macd +1.47% vs 任意日 +2.83%，60 日全部 ≈ 任意日 +9.2%
  → 轉空不是賣出訊號（同 ma-filter-evidence「狀態有資訊、觸發沒有」）。狀態差 +1.2–1.3pp ≈ 既有「>SMA50 且 >EMA200」的 +1.0pp，無新資訊。
- 穩健性：成本 30bp 再少約 1pp；T-bill 利息打七折再少 0.1–0.4pp；執行早一天方向不一致。結論不依賴這些設定。
- 沒測的：2 倍槓桿 ETF（QLD／USD）——台股結果是在 2 倍的 00631L 上測的，波動拖累讓趨勢開關在槓桿 ETF 上較有利，
  本帳戶不持有槓桿 ETF（CLAUDE.md 不開槓桿硬線），不在本次範圍。 → 見下方加考。

══ 加考：2 倍 ETF（2026-11-16 用戶點單「加測 2 倍 ETF」「要列出 Sharpe、Calmar 差異」；`--lev2x`）══
事先寫定（跑之前寫完，跑完不加變體）。對象是家戶另一個定期定額帳戶的 QLD／USD／VO，不是 Firstrade 帳戶（不開槓桿硬線不變）。
載具：QLD（2× QQQ，2006-06 起實價）、USD（2× 半導體，2007-02 起實價）；上市前用 2× 日再平衡合成
  （r = 2×標的日報酬 − T-bill 日報酬 − c/252，c 用實價重疊期校準，同 `vix_leveraged_etf_2026-11-07.py`；USD 標的以 SMH 代）。
訊號：一律看 1× 標的（QQQ／SMH，同主測的四條規則與同一個 3 日確認、次日執行節奏）——台股也是看大盤指數切 2 倍 ETF。
出場動作兩種：退 T-bill（每次切換 10bp）、換成 1× 標的（去槓桿不離場，每次 15bp）。
三組：QLD 單檔、USD 單檔、定期定額籃子（QLD／USD／VO 各 1/3 每日等權；兩條 2 倍腿各看自己的標的，VO 不動；VO 2004 前接 MDY）。
  4 規則 × 2 出場動作 × 3 組 = 24 個候選（多重檢定分母 24，與主測的 32 分開算）。
對照（不算候選）：2 倍買進持有（判定基準）、1× 買進持有（= 直接去槓桿）、SMA200 月底判定、SMA200 日頻＋3 日確認（皆退 T-bill）。
窗同主測：W1 2000-01-03 → 2009-12-31、W2 2010-01-04 → 2026-11-13、全期。
報：CAGR、MaxDD、Sharpe、Calmar 與各自對 2 倍買進持有的差；另列每個候選對 1× 買進持有的四個差。
置換檢定同主測（曝險序列圓形位移，籃子兩條腿同步位移），統計量 Calmar 差（主）與 Sharpe 差（副）都報 p 與 q_BH。
判定同主測三分類（基準 = 2 倍買進持有）。另一個預先寫定的問題：「2 倍 + 開關」有沒有在兩窗都贏「直接換 1×」
  （Sharpe 與 Calmar 都較高才算贏）。
已知缺陷：2006 前是合成序列（2000–02 的 2 倍 QQQ 幾乎歸零，W1 的買進持有基準極差，任何出場規則都會顯得很好）；
  單筆投入不是定期定額（定期定額在低點多買，對買進持有較有利）；籃子每日等權未計再平衡成本。
輸出：data/<同名>.lev2x.out.txt；價格快取 data/<同名>.lev2x.px.pkl。

══ 加考首跑結論（2026-11-16，資料至 2026-11-13）══
判定：24 個候選「過線」0 個、「只有回撤保護」20 個、「沒有幫助」4 個；兩窗都贏「直接換 1×」的 0／24。**結論與主測相同，槓桿沒有讓開關過線。**
合成校準：QLD 額外成本 1.7%／年、重疊期殘差 +0.10pp、日相關 0.996；USD 0.7%／年、殘差 −1.48pp、相關 0.967（USD 的標的不是 SMH，W1 的 USD 只當量級看）。
- 2010→（對 2 倍買進持有；ΔSharpe／ΔCalmar 為絕對差）：
  QLD 30.4%／−63.7%／Sharpe 0.81／Calmar 0.48 → 退 T-bill 14.8–17.6%／−45 到 −52%，ΔSharpe −0.26 到 −0.19、ΔCalmar −0.18 到 −0.10；
    換 1× 23.3–24.5%／−46 到 −56%，ΔSharpe −0.07 到 −0.04、ΔCalmar −0.04 到 +0.04。
  USD 35.6%／−77.9%／0.78／0.46 → 退 T-bill 20.6–24.1%，ΔSharpe −0.18 到 −0.11、ΔCalmar −0.17 到 −0.06；換 1× 29.9–32.7%，ΔSharpe −0.05 到 +0.01、ΔCalmar −0.03 到 +0.04。
  籃子 28.8%／−59.0%／0.81／0.49 → 退 T-bill 19.2–19.4%／−33 到 −51%，ΔSharpe −0.12 到 −0.08、ΔCalmar −0.11 到 +0.11；
    換 1× 24.3–24.7%／−44 到 −52%，ΔSharpe −0.03 到 0.00、ΔCalmar −0.02 到 +0.07。
  → 2010 後 Sharpe 沒有一個候選明顯高於抱著不動（最好 +0.01）；Calmar 最好的是「且」（籃子退 T-bill +0.11、換 1× +0.07），置換 p 0.041／0.073、校正後 q 0.70。
- 2000–2009：2 倍買進持有幾乎歸零（QLD −25.8%／年、MDD −98.9%；USD −30.6%／−99.8%；籃子 −13.5%／−95.1%），所以任何出場規則都大勝：
  籃子退 T-bill 2.1–5.9%／−69 到 −70%，ΔSharpe +0.15 到 +0.27、ΔCalmar +0.17 到 +0.23；換 1× ΔSharpe +0.06 到 +0.10、ΔCalmar +0.09 到 +0.11。
  但回撤仍有七成（USD 九成）——開關把「歸零」變成「腰斬再腰斬」，不是保護。
- 全期（2000→）：籃子 2 倍買進持有 11.1%／−95.1%／Sharpe 0.42／Calmar 0.12 → 退 T-bill 12.7–14.0%／−69 到 −70%，ΔSharpe +0.07 到 +0.11、ΔCalmar +0.06 到 +0.09。
  全期置換 Calmar 差 22／24 過 q 0.10、Sharpe 差 18／24 過 q 0.10（q 皆 0.06），但 W2 是 0／24（Calmar 最小 p 0.041 → q 0.70；Sharpe 最小 p 0.25）——全靠 2000–02 與 2008。
- 對「直接換 1×」（QQQ／SMH／VO 買進持有：2010→ 籃子 18.8%／−35.7%／Sharpe 0.84／Calmar 0.53）：
  2010→ 所有候選 Sharpe 都低於 1×（−0.30 到 −0.02）；退 T-bill 版報酬與 1× 差不多（籃子 +0.3 到 +0.6pp）但回撤深 6–15pp（只有「且」淺 3pp）；
  換 1× 版多賺 5.5–5.9pp、回撤深 8–16pp。2000–2009 退 T-bill 版贏 1×（籃子 ΔSharpe +0.11 到 +0.23）。兩窗都贏的 0 個。
- 指標與節奏：對照的 SMA200 月底判定在 2 倍上仍是全期最好的一列（籃子 15.1%／−60.3%／Sharpe 0.54／Calmar 0.25）；EMA／MACD／日頻節奏沒有比它好。「或」在 2010→ 仍是四條裡偏差的。
- 讀法：趨勢開關在 2 倍 ETF 上的價值 = 一張「2000／2008 型長空頭」的保險，保費是多頭年代每年 4–16pp（退 T-bill）或 3–7pp（換 1×）。
  要風險調整後報酬，直接降槓桿（1×）在 2010 後比任何開關都好、也不用每年切換 4 次；要保留 2 倍又怕歸零，最便宜的版本是「轉空時換 1×」而不是退現金。
  這是家戶定期定額帳戶的數學，不是 Firstrade 的規則；不建議為此立規則或影子。
"""
import os, sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(HERE, "data")
NAME = "trend_switch_ema_macd_2026-11-16"
CACHE = os.path.join(DATA, NAME + ".px.pkl"); OUT = os.path.join(DATA, NAME + ".out.txt")
END = "2026-11-13"
W1 = ("2000-01-03", "2009-12-31"); W2 = ("2010-01-04", END)
S1 = ("2021-09-01", "2023-12-29"); S2 = ("2024-01-02", END)
COST_ETF, COST_STK = 0.0010, 0.0020
CONFIRM, WARM = 3, 252
ETFS = ["SPY", "QQQ", "SMH", "IGV"]
SPLICE = {"QQQ": "^NDX", "SMH": "^SOX"}
P0W = {"SMH": 0.52, "IGV": 0.33, "SPY": 0.15}
HOLD = ['AMAT', 'ANET', 'AVGO', 'CLS', 'CRM', 'CRWD', 'DIOD', 'MU', 'NET', 'NVDA', 'PLTR', 'PWR', 'SNPS', 'TWLO']
CAND = ['HWM', 'ATI', 'FN', 'GEV', 'COHR', 'VRT', 'PAYC', 'WDAY', 'DOCU', 'ZS', 'OKTA', 'AMZN']
EXTRA = ['LITE', 'MRVL', 'ONTO', 'STRL']
STOCKS = HOLD + CAND + EXTRA
RULES = ["ema_100", "macd_line_24_52", "ema100 或 macd", "ema100 且 macd"]


class Tee:
    def __init__(self, *fs): self.fs = fs
    def write(self, s):
        for f in self.fs: f.write(s)
    def flush(self):
        for f in self.fs: f.flush()


def load():
    if os.path.exists(CACHE) and "--refresh" not in sys.argv:
        return pd.read_pickle(CACHE)
    import yfinance as yf
    idxs = yf.download(ETFS + list(SPLICE.values()) + ["^IRX"], period="max", progress=False, auto_adjust=True)["Close"]
    stk = yf.download(STOCKS, start="2019-06-01", progress=False, auto_adjust=True)["Close"]
    d = {"idx": idxs, "stk": stk}
    os.makedirs(DATA, exist_ok=True); pd.to_pickle(d, CACHE)
    return d


def ema(s, n): return s.ewm(span=n, adjust=False).mean()


def raw_states(px):
    a = (px / ema(px, 100) - 1) > 0
    b = ((ema(px, 24) - ema(px, 52)) / px) > 0
    return {"ema_100": a, "macd_line_24_52": b, "ema100 或 macd": a | b, "ema100 且 macd": a & b}


def confirm(raw, n=CONFIRM):
    """原始狀態與現行狀態連續 n 日不同才翻。"""
    v = raw.values.astype(bool); out = np.empty(len(v), bool); cur = v[0]; run = 0
    for i, x in enumerate(v):
        if x != cur:
            run += 1
            if run >= n: cur = x; run = 0
        else:
            run = 0
        out[i] = cur
    return pd.Series(out, index=raw.index)


def daily_pos(raw, lag=2):
    return confirm(raw).astype(float).shift(lag)


def strat_ret(r, rf, e, cost):
    return e * r + (1 - e) * rf - cost * e.diff().abs().fillna(0)


def spells(e):
    """回傳完整段落（兩端都有切換）的長度陣列與切換次數。"""
    v = e.values; ch = np.flatnonzero(np.abs(np.diff(v)) > 1e-12) + 1
    lens = np.diff(ch) if len(ch) > 1 else np.array([])
    return lens, len(ch)


def metrics(ret, rf, e=None):
    n = len(ret); yrs = n / 252
    lr = np.log1p(ret.values); eq = np.exp(np.cumsum(lr))
    cagr = eq[-1] ** (1 / yrs) - 1
    mdd = (eq / np.maximum.accumulate(eq) - 1).min()
    sh = (ret.values - rf.values).mean() / ret.values.std() * np.sqrt(252)
    out = dict(cagr=cagr, mdd=mdd, sharpe=sh, calmar=cagr / abs(mdd) if mdd < 0 else np.nan)
    if e is not None:
        lens, nsw = spells(e)
        out.update(inmkt=float(e.mean()), sw=nsw / yrs, whip=float((lens < 10).mean()) if len(lens) else np.nan)
    return out


def _stat(ret, rf):
    n = len(ret); eq = np.exp(np.cumsum(np.log1p(ret)))
    cagr = eq[-1] ** (252 / n) - 1; mdd = (eq / np.maximum.accumulate(eq) - 1).min()
    return cagr / abs(mdd), (ret - rf).mean() / ret.std() * np.sqrt(252)


def perm_test(r, rf, e, cost, bh_calmar, bh_sharpe):
    """圓形位移 null：k = 252 … n−252 全取。回傳 (p_calmar, p_sharpe, 位移數)。"""
    r, rf, e = r.values, rf.values, e.values; n = len(r)
    if n < 3 * 252: return np.nan, np.nan, 0
    tc0 = cost * np.abs(np.diff(e, prepend=e[0]))
    oc, os_ = _stat(e * r + (1 - e) * rf - tc0, rf)
    oc -= bh_calmar; os_ -= bh_sharpe
    gc = gs = 0; ks = range(252, n - 251)
    for k in ks:
        ek = np.roll(e, k); tc = cost * np.abs(ek - np.roll(ek, 1))
        c, s = _stat(ek * r + (1 - ek) * rf - tc, rf)
        gc += (c - bh_calmar) >= oc; gs += (s - bh_sharpe) >= os_
    m = len(ks)
    return (1 + gc) / (m + 1), (1 + gs) / (m + 1), m


def bh_q(p):
    p = np.asarray(p, float); ok = ~np.isnan(p); q = np.full(len(p), np.nan)
    pv = p[ok]; m = len(pv); o = np.argsort(pv); ranked = pv[o] * m / (np.arange(m) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]; qq = np.empty(m); qq[o] = np.minimum(ranked, 1)
    q[ok] = qq
    return q


def out_segments(e, r):
    o = (e == 0); g = (o != o.shift()).cumsum(); rets = []
    for _, s in o[o].groupby(g[o]):
        rets.append((1 + r.loc[s.index[0]:s.index[-1]]).prod() - 1)
    rets = np.array(rets)
    return len(rets), int((rets < 0).sum()), (rets.mean() if len(rets) else np.nan)


def win_slice(s, a, b, valid_from):
    a = max(pd.Timestamp(a), valid_from)
    return s.loc[a:b]


def fmt(m, bh, p=None, q=None):
    s = (f"{m['cagr']:>7.1%}{(m['cagr'] - bh['cagr']) * 100:>+7.1f}{m['mdd']:>8.1%}{(m['mdd'] - bh['mdd']) * 100:>+7.1f}"
         f"{m['sharpe']:>7.2f}{m['calmar']:>7.2f}")
    if 'inmkt' in m:
        w = f"{m['whip']:>6.0%}" if not np.isnan(m['whip']) else f"{'–':>6}"
        s += f"{m['inmkt']:>6.0%}{m['sw']:>6.1f}{w}"
    else:
        s += f"{'':>18}"
    if p is not None and not np.isnan(p): s += f"{p:>8.3f}{q:>7.3f}"
    return s


HDR = (f"{'CAGR':>7}{'Δpp':>7}{'MDD':>8}{'Δpp':>7}{'Sharpe':>7}{'Calmar':>7}{'在市':>5}{'切/年':>5}{'<10日':>5}"
       f"{'p置換':>7}{'q_BH':>7}")


def main():
    os.makedirs(DATA, exist_ok=True)
    fo = open(OUT, "w"); sys.stdout = Tee(sys.__stdout__, fo)
    d = load()
    raw = d["idx"].loc[:END]
    rf_all = (raw["^IRX"] / 100 / 252).clip(lower=0)

    # ── 價格序列（必要時接上指數）
    PX, VALID = {}, {}
    for t in ETFS:
        p = raw[t].dropna()
        if t in SPLICE:
            ix = raw[SPLICE[t]].dropna(); pre = ix.loc[:p.index[0]]
            pre = pre / pre.iloc[-1] * p.iloc[0]
            p = pd.concat([pre.iloc[:-1], p])
        PX[t] = p; VALID[t] = p.index[min(WARM, len(p) - 1)]
    # P0 月底再平衡日報酬
    cidx = PX["IGV"].index.intersection(PX["SMH"].index).intersection(PX["SPY"].index)
    R3 = pd.DataFrame({k: PX[k].reindex(cidx).pct_change() for k in P0W}).iloc[1:]
    ym = R3.index.to_period("M"); w = np.array([P0W[k] for k in R3.columns]); cur = w.copy(); pr = []
    for i in range(len(R3)):
        x = R3.values[i]; g = float((cur * x).sum()); pr.append(g)
        cur = cur * (1 + x) / (1 + g)
        if i + 1 < len(R3) and ym[i + 1] != ym[i]: cur = w.copy()
    p0r = pd.Series(pr, index=R3.index); PX["P0"] = (1 + p0r).cumprod()
    VALID["P0"] = PX["P0"].index[WARM]

    print(f"日頻趨勢開關（EMA100／MACD 24,52／或／且）— 資料至 {END}")
    print(f"節奏：收盤判定、連續 {CONFIRM} 日確認、次一交易日收盤執行；出場放 T-bill；ETF 每次切換 {COST_ETF * 1e4:.0f}bp、個股 {COST_STK * 1e4:.0f}bp")
    for t in ETFS + ["P0"]:
        print(f"  {t:<4} 資料 {PX[t].index[0].date()} →，統計自 {max(VALID[t], pd.Timestamp(W1[0])).date()}"
              + (f"（{SPLICE[t]} 接到上市前）" if t in SPLICE else ""))
    a_, b_ = raw_states(PX["SPY"])["ema_100"], raw_states(PX["SPY"])["macd_line_24_52"]
    print(f"  SPY 兩條線每日原始狀態相同比例（2000→）：{(a_ == b_).loc['2000':].mean():.0%}；"
          f"SMH {(raw_states(PX['SMH'])['ema_100'] == raw_states(PX['SMH'])['macd_line_24_52']).loc['2000':].mean():.0%}\n")

    # ── 建案例
    cases = []   # dict(layer, asset, rule, r, e, cand, cost)

    def add(layer, asset, rule, r, e, cand):
        cases.append(dict(layer=layer, asset=asset, rule=rule, r=r, e=e.reindex(r.index), cand=cand, cost=COST_ETF))

    def controls(px):
        sma = px.rolling(200).mean(); tr = (px > sma).where(sma.notna())
        ymx = pd.Series(px.index.to_period("M"), index=px.index); is_me = (ymx != ymx.shift(-1)); is_me.iloc[-1] = False
        me = px.index[is_me.values]
        mon = tr[me].astype(float).reindex(px.index).ffill().shift(1)
        day = daily_pos((px > sma).fillna(False))
        return {"買進持有": pd.Series(1.0, index=px.index), "SMA200 月底判定（parking_exit A）": mon, "SMA200 日頻＋3 日確認": day}

    for t in ETFS:
        px = PX[t]; r = px.pct_change()
        for k, e in controls(px).items(): add(1, t, k, r, e, False)
        for k, s in raw_states(px).items(): add(1, t, k, r, daily_pos(s), True)
    r0 = PX["P0"].pct_change()
    for k, e in controls(PX["P0"]).items(): add(2, "P0", k, r0, e, False)
    for src in ("SPY", "P0"):
        for k, s in raw_states(PX[src]).items():
            pos = daily_pos(s).reindex(r0.index)
            add(2, "P0", f"{k}｜訊號 {src}｜全退", r0, pos, True)
            add(2, "P0", f"{k}｜訊號 {src}｜減半", r0, 0.5 + 0.5 * pos, True)
    ncand = sum(c["cand"] for c in cases)
    print(f"候選數（多重檢定分母）：{ncand}\n")

    # ── 各窗計算
    WINS = [("W1 2000–2009", W1[0], W1[1]), ("W2 2010→", W2[0], W2[1]), ("全期", W1[0], W2[1])]
    res = {}   # (case_i, win) -> dict
    for wn, a, b in WINS:
        for i, c in enumerate(cases):
            vf = VALID[c["asset"]]
            r = win_slice(c["r"], a, b, vf).dropna(); e = c["e"].reindex(r.index).fillna(1.0)
            rf = rf_all.reindex(r.index).ffill().fillna(0)
            ret = strat_ret(r, rf, e, c["cost"])
            m = metrics(ret, rf, e if c["rule"] != "買進持有" else None)
            m.update(r=r, rf=rf, e=e, start=r.index[0])
            res[(i, wn)] = m
        for i, c in enumerate(cases):
            if not c["cand"]: continue
            bh = next(res[(j, wn)] for j, cc in enumerate(cases) if cc["asset"] == c["asset"] and cc["rule"] == "買進持有")
            m = res[(i, wn)]
            m["p_c"], m["p_s"], m["nperm"] = perm_test(m["r"], m["rf"], m["e"], c["cost"], bh["calmar"], bh["sharpe"])
        ci = [i for i, c in enumerate(cases) if c["cand"]]
        for i, q in zip(ci, bh_q([res[(i, wn)]["p_c"] for i in ci])): res[(i, wn)]["q_c"] = q
        for i, q in zip(ci, bh_q([res[(i, wn)]["p_s"] for i in ci])): res[(i, wn)]["q_s"] = q

    def bh_of(asset, wn):
        return next(res[(j, wn)] for j, cc in enumerate(cases) if cc["asset"] == asset and cc["rule"] == "買進持有")

    # ── 輸出：第 1、2 層
    for layer, title in ((1, "第 1 層 指數層（各自訊號，持有或全退 T-bill）"), (2, "第 2 層 組合層 P0 = 52% SMH + 33% IGV + 15% SPY")):
        print("=" * 110); print(title); print("Δpp = 對買進持有的差（CAGR：負 = 少賺；MDD：正 = 回撤變淺）；p置換／q_BH = Calmar 增益的圓形位移檢定")
        for asset in [a for a in ETFS + ["P0"] if any(c["layer"] == layer and c["asset"] == a for c in cases)]:
            for wn, a, b in WINS:
                bh = bh_of(asset, wn)
                print(f"\n[{asset}｜{wn}｜自 {bh['start'].date()}]")
                print(f"  {'規則':<34}{HDR}")
                for i, c in enumerate(cases):
                    if c["layer"] != layer or c["asset"] != asset: continue
                    m = res[(i, wn)]
                    print(f"  {c['rule']:<34}" + fmt(m, bh, m.get("p_c"), m.get("q_c")))
        print()

    # ── 出場段落
    print("=" * 110); print("出場段落（全退版）：段數／躲對（出場期間標的下跌）／出場期間標的平均報酬")
    for wn, a, b in WINS[:2]:
        print(f"\n[{wn}]")
        for i, c in enumerate(cases):
            if c["rule"] == "買進持有" or "減半" in c["rule"]: continue
            m = res[(i, wn)]; n, good, avg = out_segments(m["e"], m["r"])
            print(f"  {c['asset']:<4}{c['rule']:<34} 出場 {n:>3} 段｜躲對 {good:>3}｜賣錯 {n - good:>3}｜出場期間標的平均 {avg:>+6.1%}" if n else
                  f"  {c['asset']:<4}{c['rule']:<34} 出場   0 段")

    # ── 判定
    print("\n" + "=" * 110); print("判定（預先寫死的三分類）與多重檢定")
    print(f"  {'層':<3}{'標的':<5}{'規則':<32}{'W1 ΔCAGR':>9}{'W1 ΔMDD':>8}{'W2 ΔCAGR':>9}{'W2 ΔMDD':>8}{'全期 p':>8}{'q_BH':>7}{'Bonf':>7}  判定")
    tally = {"過線": 0, "只有回撤保護": 0, "沒有幫助": 0}; rows = []
    for i, c in enumerate(cases):
        if not c["cand"]: continue
        v = []
        for wn in ("W1 2000–2009", "W2 2010→"):
            bh = bh_of(c["asset"], wn); m = res[(i, wn)]
            v.append(((m["cagr"] - bh["cagr"]) * 100, (m["mdd"] - bh["mdd"]) * 100))
        mf = res[(i, "全期")]
        dd_ok = all(x[1] >= 5 for x in v); cg_ok = all(x[0] >= -2 for x in v); sig = mf["q_c"] < 0.10
        verdict = "過線" if (dd_ok and cg_ok and sig) else ("只有回撤保護" if dd_ok else "沒有幫助")
        tally[verdict] += 1
        rows.append((mf["p_c"], i, c, v, mf, verdict))
        print(f"  {c['layer']:<3}{c['asset']:<5}{c['rule']:<32}{v[0][0]:>+9.1f}{v[0][1]:>+8.1f}{v[1][0]:>+9.1f}{v[1][1]:>+8.1f}"
              f"{mf['p_c']:>8.3f}{mf['q_c']:>7.3f}{min(1, mf['p_c'] * ncand):>7.3f}  {verdict}")
    print(f"\n  彙總：{tally}（候選 {ncand} 個）")
    for wn, _, _ in WINS:
        ps = [(res[(i, wn)]["p_c"], res[(i, wn)]["q_c"], cases[i]) for i, c in enumerate(cases) if c["cand"]]
        ps = [x for x in ps if not np.isnan(x[0])]; ps.sort(key=lambda x: x[0])
        print(f"  [{wn}] Calmar 增益置換 p 最小：{ps[0][2]['asset']} {ps[0][2]['rule']} p={ps[0][0]:.3f}、q_BH={ps[0][1]:.3f}、"
              f"Bonferroni={min(1, ps[0][0] * ncand):.3f}；p<0.05 的候選 {sum(p < 0.05 for p, _, _ in ps)}／{len(ps)}，q_BH<0.10 的 {sum(q < 0.10 for _, q, _ in ps)}")
        ss = [(res[(i, wn)]["p_s"], res[(i, wn)]["q_s"]) for i, c in enumerate(cases) if c["cand"] and not np.isnan(res[(i, wn)]["p_s"])]
        print(f"  {'':<{len(wn) + 3}}Sharpe 差（副）：p<0.05 的 {sum(p < 0.05 for p, _ in ss)}／{len(ss)}，q_BH<0.10 的 {sum(q < 0.10 for _, q in ss)}")
    spy2 = [(c["rule"], (res[(i, "W2 2010→")]["cagr"] - bh_of("SPY", "W2 2010→")["cagr"]) * 100)
            for i, c in enumerate(cases) if c["asset"] == "SPY" and c["layer"] == 1 and c["rule"] != "買進持有"]
    print("\n  對 parking_exit 裁決（SPY 2010→ 對買進持有的 CAGR 差，門檻 −2pp）：")
    for k, v in spy2: print(f"    {k:<34}{v:>+6.1f}pp  {'未翻盤' if v < -2 else '在門檻內'}")

    # ── 穩健性：各層全期 Calmar 增益最大的候選
    print("\n" + "=" * 110); print("穩健性（各層全期 Calmar 增益最大的候選；不是新變體）")
    for layer in (1, 2):
        best = max((i for i, c in enumerate(cases) if c["cand"] and c["layer"] == layer),
                   key=lambda i: res[(i, "全期")]["calmar"] - bh_of(cases[i]["asset"], "全期")["calmar"])
        c = cases[best]; print(f"\n  第 {layer} 層：{c['asset']} {c['rule']}")
        print(f"    {'設定':<26}" + "".join(f"{wn + ' CAGR/MDD/Calmar':>30}" for wn, _, _ in WINS))
        src = c["rule"].split("｜")[1].replace("訊號 ", "") if "｜" in c["rule"] else c["asset"]
        rule = c["rule"].split("｜")[0]; half = "減半" in c["rule"]
        pos1 = daily_pos(raw_states(PX[src])[rule], lag=1).reindex(c["r"].index)
        e1 = 0.5 + 0.5 * pos1 if half else pos1
        for lab, e, cost, rfm in (("基準（10bp、shift 2）", c["e"], COST_ETF, 1.0), ("成本 0", c["e"], 0.0, 1.0),
                                  ("成本 30bp", c["e"], 0.0030, 1.0), ("T-bill ×0.7（利息預扣）", c["e"], COST_ETF, 0.7),
                                  ("執行早一天（shift 1）", e1, COST_ETF, 1.0)):
            line = f"    {lab:<26}"
            for wn, a, b in WINS:
                r = win_slice(c["r"], a, b, VALID[c["asset"]]).dropna(); ee = e.reindex(r.index).fillna(1.0)
                rf = rf_all.reindex(r.index).ffill().fillna(0)
                m = metrics(strat_ret(r, rf * rfm, ee, cost), rf)
                line += f"{m['cagr']:>13.1%} /{m['mdd']:>7.1%} /{m['calmar']:>5.2f}"
            print(line)
        line = f"    {'買進持有':<26}"
        for wn, _, _ in WINS:
            m = bh_of(c["asset"], wn); line += f"{m['cagr']:>13.1%} /{m['mdd']:>7.1%} /{m['calmar']:>5.2f}"
        print(line)

    # ── 第 3 層 個股（描述性）
    print("\n" + "=" * 110)
    print("第 3 層 個股層（描述性；30 檔是今天的名單 = 倖存者偏差，買進持有被灌水；不進判定、無置換檢定）")
    stk = d["stk"].loc[:END]
    SR = {}   # rule -> DataFrame of strategy returns
    ctrl = "對照：>SMA50 且 >EMA200（同節奏）"
    ev = {k: [] for k in RULES}; st_fwd = {k: {"on": [], "off": []} for k in RULES + [ctrl]}; allf = {20: [], 60: []}
    per = {}
    for s in STOCKS:
        if s not in stk: continue
        px = stk[s].dropna()
        if len(px) < WARM + 250: continue
        r = px.pct_change(); rf = rf_all.reindex(px.index).ffill().fillna(0); vf = px.index[WARM]
        states = raw_states(px)
        states[ctrl] = (px > px.rolling(50).mean()) & (px > ema(px, 200))
        f20 = px.shift(-21) / px.shift(-1) - 1; f60 = px.shift(-61) / px.shift(-1) - 1
        inwin = (px.index >= max(vf, pd.Timestamp(S1[0])))
        allf[20].append(f20[inwin].dropna()); allf[60].append(f60[inwin].dropna())
        SR.setdefault("買進持有", {})[s] = r.where(inwin)
        for k, raw_s in states.items():
            cs = confirm(raw_s); e = cs.astype(float).shift(2)
            SR.setdefault(k, {})[s] = strat_ret(r, rf, e, COST_STK).where(inwin)
            st_fwd[k]["on"].append(f20[inwin & cs.values].dropna()); st_fwd[k]["off"].append(f20[inwin & ~cs.values].dropna())
            if k in ev:
                flip = (cs.astype(int).diff() == -1) & inwin
                ev[k].append(pd.DataFrame({"f20": f20[flip], "f60": f60[flip]}))
            for wn, (a, b) in (("S1", S1), ("S2", S2)):
                rr = r.loc[max(pd.Timestamp(a), vf):b].dropna()
                if len(rr) < 250: continue
                rfw = rf.reindex(rr.index); ee = e.reindex(rr.index).fillna(1.0)
                per[(s, k, wn)] = (metrics(strat_ret(rr, rfw, ee, COST_STK), rfw, ee), metrics(rr, rfw))
    rfS = rf_all.reindex(stk.index).ffill().fillna(0)
    for wn, (a, b) in (("S1 2021-09→2023", S1), ("S2 2024→", S2)):
        key = wn[:2]
        print(f"\n[{wn}]  等權籃子（每日等權、未計再平衡成本）與逐檔中位數")
        print(f"  {'規則':<30}{'籃子CAGR':>9}{'MDD':>8}{'Sharpe':>7}{'Calmar':>7}｜{'逐檔 ΔCAGR 中位':>14}{'ΔMDD 中位':>10}{'Calmar 較好比例':>14}{'切/年':>6}{'<10日':>6}{'檔數':>5}")
        for k in ["買進持有"] + RULES + [ctrl]:
            bas = pd.DataFrame(SR[k]).loc[a:b].mean(axis=1).dropna()
            m = metrics(bas, rfS.reindex(bas.index))
            line = f"  {k:<30}{m['cagr']:>9.1%}{m['mdd']:>8.1%}{m['sharpe']:>7.2f}{m['calmar']:>7.2f}｜"
            if k != "買進持有":
                xs = [(v[0], v[1]) for (s, kk, w_), v in per.items() if kk == k and w_ == key]
                dc = np.median([(x["cagr"] - y["cagr"]) * 100 for x, y in xs]); dm = np.median([(x["mdd"] - y["mdd"]) * 100 for x, y in xs])
                better = np.mean([x["calmar"] > y["calmar"] for x, y in xs])
                line += (f"{dc:>+14.1f}{dm:>+10.1f}{better:>14.0%}{np.mean([x['sw'] for x, _ in xs]):>6.1f}"
                         f"{np.nanmean([x['whip'] for x, _ in xs]):>6.0%}{len(xs):>5}")
            print(line)
    print("\n[轉空事件之後的報酬（2021-09→，執行日收盤起算）vs 任意日]")
    A20 = pd.concat(allf[20]); A60 = pd.concat(allf[60])
    print(f"  {'任意日':<22} n={len(A20):>6}  20 日 {A20.mean():>+6.2%}／勝率 {(A20 > 0).mean():.1%}   60 日 {A60.mean():>+6.2%}／勝率 {(A60 > 0).mean():.1%}")
    for k in RULES:
        E = pd.concat(ev[k]); a20 = E["f20"].dropna(); a60 = E["f60"].dropna()
        print(f"  {k + ' 轉空':<22} n={len(a20):>6}  20 日 {a20.mean():>+6.2%}／勝率 {(a20 > 0).mean():.1%}   60 日 {a60.mean():>+6.2%}／勝率 {(a60 > 0).mean():.1%}"
              f"   20 日跌 >10% 比例 {(a20 < -0.10).mean():.1%}（任意日 {(A20 < -0.10).mean():.1%}）")
    print("\n[狀態（確認後）之後 20 日報酬：多方狀態 vs 空方狀態]")
    for k in RULES + [ctrl]:
        on = pd.concat(st_fwd[k]["on"]); off = pd.concat(st_fwd[k]["off"])
        print(f"  {k:<30} 多方 {on.mean():>+6.2%}／{(on > 0).mean():.1%}（{len(on) / (len(on) + len(off)):.0%} 時間）  空方 {off.mean():>+6.2%}／{(off > 0).mean():.1%}  差 {(on.mean() - off.mean()) * 100:>+5.2f}pp")
    fo.flush()


# ════════════════════════════════════════════════════════════════════════════════════════
# 加考：2 倍 ETF（--lev2x）
# ════════════════════════════════════════════════════════════════════════════════════════
def _m(ret, rf):
    return metrics(pd.Series(ret), pd.Series(rf))


def perm_multi(sl, fixed, rf, bh_c, bh_s):
    """sl = [(w, r_on, r_off, e, cost)]（numpy）；各腿曝險同步圓形位移。回傳 (p_calmar, p_sharpe)。"""
    n = len(rf)

    def tot(shift):
        t = fixed.copy()
        for w, ron, roff, e, c in sl:
            ek = np.roll(e, shift) if shift else e
            d_ = np.abs(ek - np.roll(ek, 1)) if shift else np.abs(np.diff(e, prepend=e[0]))
            t += w * (ek * ron + (1 - ek) * roff - c * d_)
        return t
    oc, os_ = _stat(tot(0), rf); oc -= bh_c; os_ -= bh_s
    gc = gs = 0; ks = range(252, n - 251)
    for k in ks:
        c, s_ = _stat(tot(k), rf); gc += (c - bh_c) >= oc; gs += (s_ - bh_s) >= os_
    return (1 + gc) / (len(ks) + 1), (1 + gs) / (len(ks) + 1)


def main_lev2x():
    out2 = os.path.join(DATA, NAME + ".lev2x.out.txt"); cache2 = os.path.join(DATA, NAME + ".lev2x.px.pkl")
    fo = open(out2, "w"); sys.stdout = Tee(sys.__stdout__, fo)
    raw = load()["idx"].loc[:END]
    if os.path.exists(cache2) and "--refresh" not in sys.argv:
        lv = pd.read_pickle(cache2)
    else:
        import yfinance as yf
        lv = yf.download(["QLD", "USD", "VO", "MDY"], period="max", progress=False, auto_adjust=True)["Close"]
        pd.to_pickle(lv, cache2)
    lv = lv.loc[:END]
    PX = {}
    for t in ("QQQ", "SMH"):
        p = raw[t].dropna(); ix = raw[SPLICE[t]].dropna(); pre = ix.loc[:p.index[0]]
        PX[t] = pd.concat([(pre / pre.iloc[-1] * p.iloc[0]).iloc[:-1], p])
    idx = PX["QQQ"].loc["1999-06-01":].index.intersection(PX["SMH"].index)
    rf = (raw["^IRX"] / 100 / 252).clip(lower=0).reindex(idx).ffill().fillna(0)
    R = pd.DataFrame({t: PX[t].pct_change().reindex(idx) for t in ("QQQ", "SMH")})
    print(f"加考：2 倍 ETF 版日頻趨勢開關 — 資料至 {END}")
    print("訊號看 1× 標的（QQQ／SMH）；出場動作：退 T-bill（10bp）或換 1× 標的（15bp）；節奏同主測")
    for etf, u in (("QLD", "QQQ"), ("USD", "SMH")):
        e = lv[etf].dropna().pct_change().dropna()
        ov = pd.concat([R[u], e, rf], axis=1).dropna(); ov.columns = ["r", "e", "rf"]
        c = float(((2 * ov["r"] - ov["rf"] - ov["e"]) * 252).mean())
        syn = 2 * R[u] - rf - c / 252
        yrs = len(ov) / 252
        gap = (1 + ov["e"]).prod() ** (1 / yrs) - (1 + 2 * ov["r"] - ov["rf"] - c / 252).prod() ** (1 / yrs)
        R[etf] = e.reindex(idx).where(idx >= e.index[0], syn)
        print(f"  {etf}：實價自 {e.index[0].date()}，之前合成；校準額外成本 {c * 100:.1f}%／年，重疊期年化殘差 {gap * 100:+.2f}pp，"
              f"日報酬相關 {ov['e'].corr(2 * ov['r']):.3f}")
    vo = lv["VO"].dropna().pct_change().dropna(); mdy = lv["MDY"].dropna().pct_change()
    R["VO"] = vo.reindex(idx).where(idx >= vo.index[0], mdy.reindex(idx))
    R = R.fillna(0.0)

    def sma_ctrl(px):
        sma = px.rolling(200).mean(); tr = (px > sma).where(sma.notna())
        ymx = pd.Series(px.index.to_period("M"), index=px.index); is_me = (ymx != ymx.shift(-1)); is_me.iloc[-1] = False
        return {"SMA200 月底判定｜退 T-bill": tr[px.index[is_me.values]].astype(float).reindex(px.index).ffill().shift(1),
                "SMA200 日頻＋3 日確認｜退 T-bill": daily_pos((px > sma).fillna(False))}
    POS = {u: {**{k: daily_pos(s) for k, s in raw_states(PX[u]).items()}, **sma_ctrl(PX[u])} for u in ("QQQ", "SMH")}
    one = pd.Series(1.0, index=idx); zero = pd.Series(0.0, index=idx)
    GROUPS = {"QLD": [("QLD", "QQQ", 1.0)], "USD": [("USD", "SMH", 1.0)], "籃子 QLD／USD／VO": [("QLD", "QQQ", 1 / 3), ("USD", "SMH", 1 / 3)]}
    cases = []   # dict(group, rule, sl=[(w, r_on, r_off, e, cost)], fixed, cand, kind)
    for g, legs in GROUPS.items():
        fixed = R["VO"] / 3 if len(legs) == 2 else zero
        def mk(rule, off, cand):
            sl = []
            for etf, u, w in legs:
                if rule == "2 倍買進持有": sl.append((w, R[etf], rf, one, 0.0))
                elif rule == "1× 買進持有": sl.append((w, R[u], rf, one, 0.0))
                else:
                    e = POS[u][rule].reindex(idx)
                    sl.append((w, R[etf], rf if off == "退 T-bill" else R[u], e, 0.0010 if off == "退 T-bill" else 0.0015))
            lab = rule if off is None else (rule if "｜" in rule else f"{rule}｜{off}")
            cases.append(dict(group=g, rule=lab, sl=sl, fixed=fixed, cand=cand, tb=(off == "退 T-bill")))
        mk("2 倍買進持有", None, False); mk("1× 買進持有", None, False)
        for k in ("SMA200 月底判定｜退 T-bill", "SMA200 日頻＋3 日確認｜退 T-bill"): mk(k, "退 T-bill", False)
        for off in ("退 T-bill", "換 1×"):
            for k in RULES: mk(k, off, True)
    ncand = sum(c["cand"] for c in cases); print(f"候選數（多重檢定分母）：{ncand}\n")

    WINS = [("W1 2000–2009", W1[0], W1[1]), ("W2 2010→", W2[0], W2[1]), ("全期", W1[0], W2[1])]
    res = {}
    for wn, a, b in WINS:
        wi = idx[(idx >= a) & (idx <= b)]; rfw = rf.reindex(wi).values
        for i, c in enumerate(cases):
            sl = [(w, ron.reindex(wi).values, roff.reindex(wi).values, e.reindex(wi).fillna(1.0).values, cost) for w, ron, roff, e, cost in c["sl"]]
            fx = c["fixed"].reindex(wi).values
            tot = fx.copy()
            for w, ron, roff, e, cost in sl: tot = tot + w * (e * ron + (1 - e) * roff - cost * np.abs(np.diff(e, prepend=e[0])))
            m = _m(tot, rfw); sw, wh, im = [], [], []
            for w, ron, roff, e, cost in sl:
                lens, nsw = spells(pd.Series(e)); sw.append(nsw / (len(wi) / 252)); im.append(e.mean())
                if len(lens): wh.append((lens < 10).mean())
            m.update(sw=np.mean(sw), whip=np.mean(wh) if wh else np.nan, inmkt=np.mean(im), sl=sl, fx=fx, rf=rfw, wi=wi)
            res[(i, wn)] = m
        for i, c in enumerate(cases):
            if not c["cand"]: continue
            bh = next(res[(j, wn)] for j, cc in enumerate(cases) if cc["group"] == c["group"] and cc["rule"] == "2 倍買進持有")
            m = res[(i, wn)]; m["p_c"], m["p_s"] = perm_multi(m["sl"], m["fx"], m["rf"], bh["calmar"], bh["sharpe"])
        ci = [i for i, c in enumerate(cases) if c["cand"]]
        for key, pk in (("q_c", "p_c"), ("q_s", "p_s")):
            for i, q in zip(ci, bh_q([res[(i, wn)][pk] for i in ci])): res[(i, wn)][key] = q

    def ref(g, wn, rule):
        return next(res[(j, wn)] for j, cc in enumerate(cases) if cc["group"] == g and cc["rule"] == rule)

    H = (f"{'CAGR':>7}{'Δpp':>7}{'MDD':>8}{'Δpp':>7}{'Sharpe':>7}{'Δ':>7}{'Calmar':>7}{'Δ':>7}{'在市':>5}{'切/年':>5}{'<10日':>5}"
         f"{'pCalmar':>8}{'q':>6}{'pSharpe':>8}{'q':>6}")
    print("=" * 130); print("Δ = 對 2 倍買進持有的差（CAGR、MDD 為百分點，MDD 正 = 回撤變淺；Sharpe、Calmar 為絕對差）；p／q = 圓形位移置換檢定與 BH 校正")
    for g in GROUPS:
        for wn, _, _ in WINS:
            bh = ref(g, wn, "2 倍買進持有"); print(f"\n[{g}｜{wn}]"); print(f"  {'規則':<34}{H}")
            for i, c in enumerate(cases):
                if c["group"] != g: continue
                m = res[(i, wn)]
                line = (f"  {c['rule']:<34}{m['cagr']:>7.1%}{(m['cagr'] - bh['cagr']) * 100:>+7.1f}{m['mdd']:>8.1%}{(m['mdd'] - bh['mdd']) * 100:>+7.1f}"
                        f"{m['sharpe']:>7.2f}{m['sharpe'] - bh['sharpe']:>+7.2f}{m['calmar']:>7.2f}{m['calmar'] - bh['calmar']:>+7.2f}")
                if "買進持有" not in c["rule"]:
                    line += f"{m['inmkt']:>6.0%}{m['sw']:>6.1f}" + (f"{m['whip']:>6.0%}" if not np.isnan(m["whip"]) else f"{'–':>6}")
                if c["cand"]: line += f"{m['p_c']:>8.3f}{m['q_c']:>6.3f}{m['p_s']:>8.3f}{m['q_s']:>6.3f}"
                print(line)

    print("\n" + "=" * 130); print("出場段落（退 T-bill 版，單檔）：段數／躲對（出場期間 2 倍 ETF 下跌）／出場期間 2 倍 ETF 平均報酬")
    for wn, _, _ in WINS[:2]:
        print(f"\n[{wn}]")
        for i, c in enumerate(cases):
            if not c["tb"] or len(c["sl"]) != 1: continue
            m = res[(i, wn)]; e = pd.Series(m["sl"][0][3], index=m["wi"]); r2 = pd.Series(m["sl"][0][1], index=m["wi"])
            n, good, avg = out_segments(e, r2)
            print(f"  {c['group']:<4}{c['rule']:<34} 出場 {n:>3} 段｜躲對 {good:>3}｜賣錯 {n - good:>3}｜出場期間 2 倍 ETF 平均 {avg:>+6.1%}")

    print("\n" + "=" * 130); print("判定（基準 = 2 倍買進持有；三分類同主測）＋ Sharpe／Calmar 差")
    print(f"  {'組':<16}{'規則':<28}｜{'W1 ΔCAGR':>8}{'ΔMDD':>7}{'ΔSharpe':>8}{'ΔCalmar':>8}｜{'W2 ΔCAGR':>8}{'ΔMDD':>7}{'ΔSharpe':>8}{'ΔCalmar':>8}｜{'全期 pC':>7}{'qC':>6}{'pS':>6}{'qS':>6}  判定")
    tally = {"過線": 0, "只有回撤保護": 0, "沒有幫助": 0}
    for i, c in enumerate(cases):
        if not c["cand"]: continue
        v = []
        for wn in ("W1 2000–2009", "W2 2010→"):
            bh = ref(c["group"], wn, "2 倍買進持有"); m = res[(i, wn)]
            v.append(((m["cagr"] - bh["cagr"]) * 100, (m["mdd"] - bh["mdd"]) * 100, m["sharpe"] - bh["sharpe"], m["calmar"] - bh["calmar"]))
        mf = res[(i, "全期")]
        dd_ok = all(x[1] >= 5 for x in v); cg_ok = all(x[0] >= -2 for x in v)
        verdict = "過線" if (dd_ok and cg_ok and mf["q_c"] < 0.10) else ("只有回撤保護" if dd_ok else "沒有幫助"); tally[verdict] += 1
        print(f"  {c['group']:<16}{c['rule']:<28}｜" + "｜".join(f"{x[0]:>+8.1f}{x[1]:>+7.1f}{x[2]:>+8.2f}{x[3]:>+8.2f}" for x in v)
              + f"｜{mf['p_c']:>7.3f}{mf['q_c']:>6.3f}{mf['p_s']:>6.3f}{mf['q_s']:>6.3f}  {verdict}")
    print(f"\n  彙總：{tally}（候選 {ncand} 個）")
    for wn, _, _ in WINS:
        pc = [(res[(i, wn)]["p_c"], res[(i, wn)]["q_c"], res[(i, wn)]["p_s"], res[(i, wn)]["q_s"], c) for i, c in enumerate(cases) if c["cand"]]
        b_ = min(pc, key=lambda x: x[0]); bs = min(pc, key=lambda x: x[2])
        print(f"  [{wn}] Calmar 差：p<0.05 {sum(x[0] < 0.05 for x in pc)}／{len(pc)}、q_BH<0.10 {sum(x[1] < 0.10 for x in pc)}，最小 {b_[4]['group']} {b_[4]['rule']} p={b_[0]:.3f} q={b_[1]:.3f} Bonf={min(1, b_[0] * ncand):.3f}"
              f"；Sharpe 差：p<0.05 {sum(x[2] < 0.05 for x in pc)}、q_BH<0.10 {sum(x[3] < 0.10 for x in pc)}，最小 p={bs[2]:.3f} q={bs[3]:.3f}")

    print("\n" + "=" * 130); print("對「直接換 1×」（1× 買進持有）的差：2 倍 + 開關有沒有在兩窗都贏（Sharpe 與 Calmar 都較高）")
    print(f"  {'組':<16}{'規則':<28}｜{'W1 ΔCAGR':>8}{'ΔMDD':>7}{'ΔSharpe':>8}{'ΔCalmar':>8}｜{'W2 ΔCAGR':>8}{'ΔMDD':>7}{'ΔSharpe':>8}{'ΔCalmar':>8}  兩窗都贏")
    nwin = 0
    for i, c in enumerate(cases):
        if c["rule"] in ("1× 買進持有",): continue
        v = []
        for wn in ("W1 2000–2009", "W2 2010→"):
            b1 = ref(c["group"], wn, "1× 買進持有"); m = res[(i, wn)]
            v.append(((m["cagr"] - b1["cagr"]) * 100, (m["mdd"] - b1["mdd"]) * 100, m["sharpe"] - b1["sharpe"], m["calmar"] - b1["calmar"]))
        win = all(x[2] > 0 and x[3] > 0 for x in v); nwin += win and c["cand"]
        print(f"  {c['group']:<16}{c['rule']:<28}｜" + "｜".join(f"{x[0]:>+8.1f}{x[1]:>+7.1f}{x[2]:>+8.2f}{x[3]:>+8.2f}" for x in v) + f"  {'是' if win else '否'}")
    print(f"\n  候選中兩窗都贏 1× 買進持有的：{nwin}／{ncand}")
    fo.flush()


if __name__ == "__main__":
    main_lev2x() if "--lev2x" in sys.argv else main()
