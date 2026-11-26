"""台灣供應鏈月營收，能不能領先美國客戶股價？（2026-11-22，原創、事前登記的檢定）

==================================================================================================
事前登記（PRE-REGISTRATION）——這一段與下方的 LINKS 對照表，寫於下載任何美股價格、
計算任何報酬之前。寫的時候只看過：營收檔的欄位、每家供應商的資料起訖月、公告日分布。
之後若加任何東西，一律標「事後探索」，分開報告，並計入嘗試次數。
==================================================================================================

問題
  台灣上市櫃公司每月 10 日前公告上月營收。這是全球少見的高頻基本面資料。
  美國客戶（Apple、Nvidia、雲端大廠…）一季才報一次。
  假說：供應商營收「加速」時，美國客戶接下來一個月的股價會贏過大盤。
  先驗看法：市場很可能早就知道。所以這是一個預期會失敗、但值得用乾淨方法確認的檢定。

資料
  營收：TEJ month_revenue（第一版公告值 version=1，含公告日 annd）。2013-01 起才完整。
        年增率用 TEJ 的 yoy_pct（公司當時公告的口徑）；缺值時依序改用
        MOPS 彙總表的（當月 ÷ 去年同月 − 1）、TEJ 自己 12 個月前的營收。
  美股：yfinance 還原收盤（auto_adjust）。回測報酬最晚到 2025-12-31。2026 年資料完全不碰。
  台股：TEJ prices 的 adj_close，只用來做「供應商自己股價」這個控制變數。

時間對齊（避免偷看）
  營收月 M 的「成形日」F_M ＝ M+1 月 10 日當天或之後的第一個台股交易日（春節順延就自動往後）。
  供應商那一筆的公告日 annd 必須 ≤ F_M 才算進訊號；晚交的當月直接不算。
  進場日 E_M ＝ F_M 之後（嚴格大於）的第一個美股收盤。多等一天，保守。
  1 個月報酬＝E_M 收盤 → E_{M+1} 收盤。3 個月報酬＝E_M → E_{M+3}（月頻重疊）。
  持有期最短就是 1 個月，符合投資人限制。

供應商 → 客戶對照表（見下方 LINKS）
  手工建立，只收長期、廣為人知的關係。每條連結有「起始年」：
  起始年＝該關係在那一年年初就已經是公開常識（保守取整年）。
  AI 伺服器相關連結（鴻海、緯創、廣達、台達電、台光電、奇鋐、雙鴻 → NVDA）一律從 2024 起算，
  因為要到 2023 年中才成為常識。
  誠實聲明：這張表是用 2026 年的知識寫的，有後見之明風險
  （知道哪些客戶後來變重要、哪些供應商後來出名）。
  穩健性版本：只用 core=True 的連結（2015 年時就已是教科書等級的關係）。
  查不到公開佐證而刪掉的：川湖→雲端大廠、勤誠→AMZN、智邦→HPE、南茂→MU。
  刻意不收：CSCO（只有鴻海一家，訊號等同 Apple）、華碩（品牌廠，顯卡占比低）。
  DELL 只從 2019 起用（2013–2018 下市；yfinance 2016–2018 是追蹤股，不是本業）。
  HPE 2016 起（2015-11 分拆）。日月光：2311（到 2018-04）接 3711（2018-05 起）。
  矽品 2325 於 2018-04 下市，之前照用（避免存活者偏誤）。

訊號（每家供應商、每個營收月 M；只有這三個）
  先處理春節：2 月的年增率改用「1+2 月合計」年增率；1 月維持原值（承認有雜訊）。
  年增率截尾在 [−90%, +300%]。
  (a) YOY   ＝ 年增率。
  (b) ACCEL ＝ 年增率 − 前三個月年增率的平均。（加速度；主要規格）
  (c) SURP  ＝ 實際營收 ÷（去年同月 ×（1＋前三個月合計年增率））− 1。（對季節性天真預測的驚喜）
  客戶層級訊號＝該客戶當時有效的供應商的等權平均（主要）；營收加權（近 12 個月營收）為次要。
  時間序列／合併追蹤資料迴歸用 z 分數：每個客戶用「自己過去」的訊號算平均與標準差
  （擴張窗口、至少 12 個月、截尾 ±3），不偷看未來。
  橫斷面排序用原始訊號直接排名。

檢定
  (i)  合併追蹤資料（panel）：下期超額報酬 ＝ a + b·z。超額＝客戶報酬 − QQQ 報酬。
       半導體客戶（NVDA AMD QCOM AVGO MRVL INTC MU AMAT）另做一版對 SMH。
       標準誤：1 個月用「按月份分群」；3 個月用 Driscoll–Kraay（Bartlett 核，落後 3 期），
       處理重疊報酬與同月相關。
       另列每個客戶各自的時間序列迴歸（1 個月 White；3 個月 Newey–West 落後 3 期）。
  (ii) 橫斷面：每月依訊號排名，前三分之一 vs 後三分之一、前三分之一 vs 全體等權。
       持有 1 個月，以及 3 個月（三批錯開）。當月有效客戶 < 6 家就跳過。
       報：年化平均差（算術，月平均 ×12）、t、勝率、最大回撤、換手率。
  (iii) 控制變數：加上客戶自己的 12-1 動能（對 QQQ 的超額）、
       供應商自己同期的台股報酬（上一個進場日到這一個進場日之間；看資訊是否已進價格）、
       客戶自己前一個月的超額報酬。
  (iv) 領先落後：同一個訊號對「公告前」第 1、2 個月與「公告後」第 1、2、3 個月的單月超額報酬。
       如果相關只出現在公告前，代表市場早就知道。
  (v)  分段：前半 vs 後半；2023–2025（AI 伺服器熱潮）vs 之前。
  穩健性（事前登記）：core-2015 對照表；營收加權；進場日改成 F_M 當天的美股收盤。

主要規格（只有一個）
  ACCEL、等權、完整對照表、1 個月、對 QQQ、合併追蹤資料、按月分群。

事前設定的過關門檻（三條都要過，少一條就是「未過門檻」）
  1. 主要規格的 t ≥ 3.0（且方向為正）。
  2. 前半、後半兩段方向相同，且各自 t ≥ 1.5。
  3. ACCEL 排名前三分之一（持有 1 個月）比全體等權客戶籃子每年多 ≥ 3 個百分點
     （算術：月平均差 ×12）。
  即使三條全過，也只是「提名去做前瞻測試」，不是可以下單。
  本專案先前已在 2018–2025 的歷史上試過約 1,000 種設定，所以另外報告
  「以本次嘗試次數校正」與「連同先前 1,000 次校正」的運氣線。

白話描述（投資人要的答案）
  六組最重要的配對，用 SURP（等權）對下個月、下一季的客戶超額報酬算相關係數與樣本數：
  A 台積電 → 大型無廠半導體籃子（NVDA AMD QCOM AVGO MRVL，對 SMH）
  B 台積電 → AAPL（對 QQQ，2014 起）
  C 伺服器代工籃子（廣達 緯創 英業達 緯穎 鴻海）→ NVDA（對 SMH）
  D 伺服器代工籃子（廣達 緯創 英業達 緯穎）→ 雲端四大（MSFT GOOGL AMZN META，對 QQQ）
  E 蘋果鏈籃子 → AAPL（對 QQQ）
  F 顯卡板卡廠（技嘉 微星）→ NVDA＋AMD（對 SMH）

嘗試次數
  程式每算一個「訊號對報酬」的統計量就登記一次，最後印總數。不挑好看的報。

登記後的更動紀錄（全部列出）
  1. 看到任何報酬結果之前的修正：日月光 2018-05 換代號（併矽品）後，年增率的第三順位備援
     （自己 12 個月前的營收）不可跨代號接，否則會把合併造成的營收跳升當成成長。
     改成那 12 個月沒有年增率（與 TEJ 原始口徑一致）。屬資料錯誤修正，不是調參數。
  2. 事後探索（看過結果之後才加，只有這一項）：【9】管線檢查。
     用供應商自己的訊號對供應商自己的台股報酬，確認訊號算法與時間對齊抓得到「應該存在」的關係。
     它不檢定本假說，不影響判定，另計次數。
==================================================================================================

首跑結論（2026-11-22；寫於結果出來之後）：未過門檻。
  主要規格 t=+0.71（142 個月、2,181 個客戶-月），門檻是 3.0。前半 +0.26、後半 +0.71，都不到 1.5。
  前三分之一每年贏等權籃子 +3.04pp，剛好碰到第三條，但 t 只有 0.91，持有 3 個月就變成 −1.85pp。
  僅有的一點相關落在公告之前（蘋果鏈對 AAPL：公告前一個月 r=+0.20，公告後 r=+0.01）。
  2023–2025 沒有撐起任何正結果（1 個月 t=−0.19；3 個月 t=−3.13，方向相反）。
  管線沒壞：同一批訊號對供應商自己的台股，公告當月 t=+9.4。
  共算 169 個統計量（事前 163、事後 6），運氣線 |t|≥3.62；沒有任何一個本假說的統計量超過。
  寫作：research/tw-revenue-us-customers-2026-11-22.md

Run:  /Users/supatrick/laptop/project/fadacai-tw/.venv/bin/python tools/backtests/tw_revenue_us_customers_2026-11-22.py
      （系統 python3 沒有 pyarrow，所以借用 fadacai-tw 的 venv；不安裝任何東西）
Output: tools/backtests/data/tw_revenue_us_customers_2026-11-22.out.txt
"""
import os
import sys
import warnings
from collections import Counter

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
OUT = os.path.join(DATA_DIR, "tw_revenue_us_customers_2026-11-22.out.txt")
PX_CACHE = os.path.join(DATA_DIR, "tw_revenue_us_customers_2026-11-22_uspx.csv")
TW = "/Users/supatrick/laptop/project/fadacai-tw/data"
TEJ_REV = f"{TW}/curated/tej/month_revenue.parquet"
TEJ_PX = f"{TW}/curated/tej/prices.parquet"
MOPS_REV = f"{TW}/raw/mops/mops_revenue.parquet"
END = "2025-12-31"

# -------------------------------------------------------------------------------------------------
# 事前登記的對照表：(供應商實體, 美國客戶, 起始年, 結束年, core2015)
# -------------------------------------------------------------------------------------------------
ENTITY_IDS = {"ASE": [("2311", 0, 201804), ("3711", 201805, 999999)]}  # 其餘實體＝單一代號
SUP_NAME = {
    "2330": "台積電", "2303": "聯電", "ASE": "日月光(2311→3711)", "2325": "矽品", "2449": "京元電", "6239": "力成",
    "3037": "欣興", "8046": "南電", "3189": "景碩", "4958": "臻鼎", "6269": "台郡", "2313": "華通", "2368": "金像電",
    "2383": "台光電", "3653": "健策", "2317": "鴻海", "4938": "和碩", "3231": "緯創", "2382": "廣達", "2324": "仁寶",
    "2356": "英業達", "6669": "緯穎", "2376": "技嘉", "2377": "微星", "2301": "光寶科", "2308": "台達電", "2474": "可成",
    "3008": "大立光", "3406": "玉晶光", "2354": "鴻準", "6176": "瑞儀", "3673": "TPK", "2392": "正崴", "6121": "新普",
    "4966": "譜瑞", "6456": "GIS", "3017": "奇鋐", "3324": "雙鴻", "3533": "嘉澤", "5269": "祥碩", "3661": "世芯",
    "5274": "信驊", "2345": "智邦", "3105": "穩懋", "6515": "穎崴", "1536": "和大", "3665": "貿聯", "3413": "京鼎",
}
Y9 = 9999
LINKS = [
    # 晶圓代工
    ("2330", "AAPL", 2015, Y9, True), ("2330", "NVDA", 2010, Y9, True), ("2330", "AMD", 2010, Y9, True),
    ("2330", "QCOM", 2010, Y9, True), ("2330", "AVGO", 2010, Y9, True), ("2330", "MRVL", 2010, Y9, True),
    ("2303", "QCOM", 2013, Y9, False),
    # 封裝測試
    ("ASE", "QCOM", 2010, Y9, True), ("ASE", "AVGO", 2010, Y9, True), ("ASE", "NVDA", 2010, Y9, False),
    ("ASE", "AMD", 2010, Y9, False), ("ASE", "AAPL", 2016, Y9, False),
    ("2325", "QCOM", 2010, 2018, False), ("2325", "NVDA", 2010, 2018, False), ("2325", "AMD", 2010, 2018, False),
    ("2449", "NVDA", 2020, Y9, False),
    ("6239", "MU", 2013, 2023, True),
    # 載板 / PCB / 銅箔基板 / 散熱片
    ("3037", "INTC", 2010, Y9, True), ("3037", "AAPL", 2010, Y9, False), ("3037", "NVDA", 2019, Y9, False),
    ("3037", "AMD", 2019, Y9, False),
    ("8046", "INTC", 2010, Y9, True), ("8046", "AMD", 2019, Y9, False), ("8046", "NVDA", 2019, Y9, False),
    ("3189", "QCOM", 2010, Y9, True),
    ("4958", "AAPL", 2012, Y9, True), ("6269", "AAPL", 2012, Y9, True), ("2313", "AAPL", 2012, Y9, False),
    ("2368", "AMZN", 2021, Y9, False), ("2368", "MSFT", 2021, Y9, False), ("2368", "GOOGL", 2021, Y9, False),
    ("2368", "META", 2021, Y9, False),
    ("2383", "AAPL", 2013, Y9, False), ("2383", "NVDA", 2024, Y9, False),
    ("3653", "NVDA", 2021, Y9, False), ("3653", "AMD", 2021, Y9, False), ("3653", "INTC", 2021, Y9, False),
    # 組裝代工 / 伺服器代工
    ("2317", "AAPL", 2010, Y9, True), ("2317", "HPQ", 2010, Y9, False), ("2317", "DELL", 2010, Y9, False),
    ("2317", "AMZN", 2012, Y9, False), ("2317", "NVDA", 2024, Y9, False),
    ("4938", "AAPL", 2011, Y9, True), ("4938", "MSFT", 2013, Y9, False), ("4938", "TSLA", 2018, Y9, False),
    ("3231", "HPQ", 2010, Y9, True), ("3231", "DELL", 2010, Y9, False), ("3231", "AAPL", 2017, 2023, False),
    ("3231", "NVDA", 2024, Y9, False),
    ("2382", "AAPL", 2010, Y9, True), ("2382", "HPQ", 2010, Y9, True), ("2382", "DELL", 2010, Y9, False),
    ("2382", "AMZN", 2012, Y9, True), ("2382", "GOOGL", 2013, Y9, True), ("2382", "META", 2013, Y9, True),
    ("2382", "MSFT", 2015, Y9, False), ("2382", "TSLA", 2018, Y9, False), ("2382", "NVDA", 2024, Y9, False),
    ("2324", "HPQ", 2010, Y9, True), ("2324", "DELL", 2010, Y9, False),
    ("2356", "HPQ", 2010, Y9, True), ("2356", "HPE", 2016, Y9, False), ("2356", "AAPL", 2017, Y9, False),
    ("6669", "META", 2019, Y9, False), ("6669", "MSFT", 2019, Y9, False),
    # 顯卡板卡
    ("2376", "NVDA", 2010, Y9, True), ("2376", "AMD", 2010, Y9, True),
    ("2377", "NVDA", 2010, Y9, True), ("2377", "AMD", 2010, Y9, True),
    # 電源
    ("2301", "HPQ", 2010, Y9, False), ("2301", "DELL", 2010, Y9, False),
    ("2308", "AAPL", 2010, Y9, False), ("2308", "TSLA", 2016, Y9, False), ("2308", "NVDA", 2024, Y9, False),
    # 蘋果零組件
    ("2474", "AAPL", 2010, 2020, True), ("3008", "AAPL", 2010, Y9, True), ("3406", "AAPL", 2012, Y9, True),
    ("2354", "AAPL", 2010, Y9, True), ("6176", "AAPL", 2010, Y9, True), ("3673", "AAPL", 2010, 2016, True),
    ("2392", "AAPL", 2010, Y9, True), ("6121", "AAPL", 2010, Y9, True), ("6121", "HPQ", 2010, Y9, False),
    ("6121", "DELL", 2010, Y9, False), ("4966", "AAPL", 2013, Y9, False), ("6456", "AAPL", 2016, Y9, False),
    # 散熱 / 連接器 / 晶片
    ("3017", "NVDA", 2024, Y9, False), ("3324", "NVDA", 2024, Y9, False),
    ("3533", "INTC", 2019, Y9, False), ("3533", "AMD", 2019, Y9, False),
    ("5269", "AMD", 2017, Y9, False),
    ("3661", "AMZN", 2022, Y9, False),
    ("5274", "AMZN", 2017, Y9, False), ("5274", "MSFT", 2017, Y9, False), ("5274", "GOOGL", 2017, Y9, False),
    ("5274", "META", 2017, Y9, False),
    # 網通
    ("2345", "AMZN", 2018, Y9, False), ("2345", "META", 2016, Y9, False),
    # 化合物半導體 / 測試介面
    ("3105", "AVGO", 2013, Y9, True),
    ("6515", "NVDA", 2021, Y9, False), ("6515", "AMD", 2021, Y9, False),
    # 電動車
    ("1536", "TSLA", 2015, Y9, True), ("3665", "TSLA", 2016, Y9, False),
    # 半導體設備代工
    ("3413", "AMAT", 2016, Y9, False),
]
SEMI = ["NVDA", "AMD", "QCOM", "AVGO", "MRVL", "INTC", "MU", "AMAT"]
CUSTS = sorted({l[1] for l in LINKS})
CUST_START_YEAR = {"DELL": 2019, "HPE": 2016, "META": 2013}
BENCH = ["QQQ", "SMH", "VOO"]
SIGS = ["ACCEL", "YOY", "SURP"]
PAIRS = [  # 白話描述用（事前登記）
    ("A 台積電→無廠半導體籃子", ["2330"], ["NVDA", "AMD", "QCOM", "AVGO", "MRVL"], "SMH", 2013),
    ("B 台積電→AAPL", ["2330"], ["AAPL"], "QQQ", 2015),
    ("C 伺服器代工籃子→NVDA", ["2382", "3231", "2356", "6669", "2317"], ["NVDA"], "SMH", 2013),
    ("D 伺服器代工籃子→雲端四大", ["2382", "3231", "2356", "6669"], ["MSFT", "GOOGL", "AMZN", "META"], "QQQ", 2013),
    ("E 蘋果鏈籃子→AAPL", ["2317", "4938", "3008", "2474", "4958", "6269", "3406", "2392", "6176", "2354"],
     ["AAPL"], "QQQ", 2013),
    ("F 顯卡板卡廠→NVDA+AMD", ["2376", "2377"], ["NVDA", "AMD"], "SMH", 2013),
]
# =================================== 以上為事前登記內容 ============================================

_lines = []
TRIED = []  # 每個「訊號對報酬」統計量登記一次


def p(s=""):
    print(s)
    _lines.append(str(s))


def reg(family, label):
    TRIED.append((family, label))


def mi_of(y, m):
    return int(y) * 12 + int(m) - 1


def ym_of(mi):
    mi = int(mi)
    return f"{mi // 12}-{mi % 12 + 1:02d}"


# -------------------------------------------------------------------------------------------------
# 1. 營收 → 供應商層級訊號
# -------------------------------------------------------------------------------------------------
def load_supplier_signals():
    ents = sorted({l[0] for l in LINKS} | {s for pr in PAIRS for s in pr[1]})
    ids = sorted({i for e in ents for i in ([x[0] for x in ENTITY_IDS[e]] if e in ENTITY_IDS else [e])})
    tej = pd.read_parquet(TEJ_REV, filters=[("stock_id", "in", ids)])
    tej["ym"] = tej.revenue_year * 100 + tej.revenue_month
    tej = tej.sort_values(["stock_id", "ym", "version"]).drop_duplicates(["stock_id", "ym"], keep="first")
    n_notv1 = int((tej.version != 1).sum())
    mops = pd.read_parquet(MOPS_REV, filters=[("stock_id", "in", ids)])
    mops["ym"] = mops.revenue_year * 100 + mops.revenue_month
    mops["yoy_mops"] = np.where((mops.revenue_last_year > 0) & (mops.revenue > 0),
                                mops.revenue / mops.revenue_last_year - 1, np.nan)
    tej = tej.merge(mops[["stock_id", "ym", "yoy_mops"]], on=["stock_id", "ym"], how="left")
    stats = Counter()
    out = {}
    for e in ents:
        parts = ENTITY_IDS.get(e, [(e, 0, 999999)])
        d = pd.concat([tej[(tej.stock_id == sid) & (tej.ym >= a) & (tej.ym <= b)] for sid, a, b in parts])
        if d.empty:
            continue
        d = d.assign(mi=[mi_of(y, m) for y, m in zip(d.revenue_year, d.revenue_month)]).set_index("mi").sort_index()
        idx = range(d.index.min(), d.index.max() + 1)
        d = d.reindex(idx)
        rev = d.revenue.astype(float)
        yoy = d.yoy_pct / 100.0
        fb1 = yoy.isna() & d.yoy_mops.notna()
        yoy = yoy.where(~fb1, d.yoy_mops)
        own = (rev / rev.shift(12) - 1).where(d.stock_id == d.stock_id.shift(12))  # 換代號（合併）不跨接
        fb2 = yoy.isna() & own.notna() & rev.notna()
        yoy = yoy.where(~fb2, own)
        stats["rows"] += int(rev.notna().sum())
        stats["yoy_from_mops"] += int(fb1.sum())
        stats["yoy_from_own_lag12"] += int(fb2.sum())
        stats["yoy_missing"] += int((yoy.isna() & rev.notna()).sum())
        yoy = yoy.where(yoy > -1)
        base = rev / (1 + yoy)
        month = pd.Series([i % 12 + 1 for i in d.index], index=d.index)
        comb = (rev + rev.shift(1)) / (base + base.shift(1)) - 1  # 1+2 月合計年增率
        yadj = yoy.where(~((month == 2) & comb.notna()), comb).clip(-0.9, 3.0)
        prior3 = pd.concat([yadj.shift(k) for k in (1, 2, 3)], axis=1)
        accel = yadj - prior3.mean(axis=1, skipna=False)
        g3 = sum(rev.shift(k) for k in (1, 2, 3)) / sum(base.shift(k) for k in (1, 2, 3)) - 1
        surp = ((1 + yadj) / (1 + g3) - 1).clip(-0.9, 3.0)
        w12 = rev.rolling(12, min_periods=6).sum()
        out[e] = pd.DataFrame({"YOY": yadj, "ACCEL": accel, "SURP": surp, "w12": w12,
                               "annd": pd.to_datetime(d.annd), "rev_ok": rev.notna()})
    stats["rows_not_version1"] = n_notv1
    return out, stats


# -------------------------------------------------------------------------------------------------
# 2. 日曆與價格
# -------------------------------------------------------------------------------------------------
def load_tw_prices():
    import pyarrow.dataset as ds
    ids = sorted({i for e in SUP_NAME for i in ([x[0] for x in ENTITY_IDS[e]] if e in ENTITY_IDS else [e])})
    t = ds.dataset(TEJ_PX).to_table(columns=["date", "stock_id", "adj_close"],
                                    filter=ds.field("stock_id").isin(ids)).to_pandas()
    t["date"] = pd.to_datetime(t["date"])
    px = t.pivot(index="date", columns="stock_id", values="adj_close").sort_index()
    cal = px["2330"].dropna().index
    return px, cal


def load_us_prices():
    syms = CUSTS + BENCH
    if os.path.exists(PX_CACHE):
        c = pd.read_csv(PX_CACHE, index_col=0, parse_dates=True)
        if set(syms) <= set(c.columns):
            return c[syms]
    import yfinance as yf
    c = yf.download(syms, start="2012-01-01", end="2026-01-01", progress=False, auto_adjust=True)["Close"]
    c = c[c.index <= END]
    os.makedirs(DATA_DIR, exist_ok=True)
    c.to_csv(PX_CACHE)
    return c[syms]


def build_calendar(tw_cal, us_days, mi_lo, mi_hi):
    rows = []
    for mi in range(mi_lo, mi_hi + 1):
        y, m = mi // 12, mi % 12 + 1
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        tenth = pd.Timestamp(ny, nm, 10)
        k = tw_cal.searchsorted(tenth, side="left")
        if k >= len(tw_cal):
            continue
        F = tw_cal[k]
        j = us_days.searchsorted(F, side="right")  # 嚴格大於 F
        j0 = us_days.searchsorted(F, side="left")  # F 當天或之後
        rows.append({"mi": mi, "F": F, "E": us_days[j] if j < len(us_days) else pd.NaT,
                     "E0": us_days[j0] if j0 < len(us_days) else pd.NaT})
    return pd.DataFrame(rows).set_index("mi")


# -------------------------------------------------------------------------------------------------
# 3. 客戶層級訊號與報酬面板
# -------------------------------------------------------------------------------------------------
def link_active(l, year):
    return l[2] <= year <= l[3] and year >= CUST_START_YEAR.get(l[1], 0)


def customer_signals(sup, cal, links, weight):
    rows = []
    late = Counter()
    for mi, F in cal.F.items():
        for c in CUSTS:
            vals = {s: [] for s in SIGS}
            wts = {s: [] for s in SIGS}
            sups = []
            for l in links:
                if l[1] != c or not link_active(l, F.year):
                    continue
                d = sup.get(l[0])
                if d is None or mi not in d.index or not d.rev_ok.get(mi, False):
                    continue
                r = d.loc[mi]
                if pd.isna(r.annd) or r.annd > F:
                    late[(l[0], mi)] += 1
                    continue
                sups.append(l[0])
                for s in SIGS:
                    if pd.notna(r[s]):
                        vals[s].append(r[s])
                        wts[s].append(r.w12 if (weight == "rw" and pd.notna(r.w12)) else 1.0)
            row = {"mi": mi, "cust": c, "nsup": len(sups), "sups": tuple(sups)}
            for s in SIGS:
                row[s] = float(np.average(vals[s], weights=wts[s])) if vals[s] else np.nan
            rows.append(row)
    return pd.DataFrame(rows), late


def expanding_z(x, minp=12):
    m = x.shift(1).expanding(min_periods=minp).mean()
    sd = x.shift(1).expanding(min_periods=minp).std()
    return ((x - m) / sd).clip(-3, 3)


def build_panel(sup, cal, uspx, twpx, links, weight="ew", entry="E"):
    sig, late = customer_signals(sup, cal, links, weight)
    E = cal[entry]
    ok = E.notna()
    P = uspx.reindex(E[ok].values)
    P.index = E[ok].index  # mi → 進場日價格
    P = P.reindex(cal.index)

    def fwd(col, a, b):  # 報酬：mi+a → mi+b
        s = P[col]
        return s.shift(-b) / s.shift(-a) - 1

    R = {}
    for c in CUSTS + BENCH:
        R[c] = pd.DataFrame({"r1": fwd(c, 0, 1), "r3": fwd(c, 0, 3), "lead2": fwd(c, 1, 2), "lead3": fwd(c, 2, 3),
                             "pre1": fwd(c, -1, 0), "pre2": fwd(c, -2, -1), "m12_1": fwd(c, -12, -1)})
    # 供應商台股報酬：上一個進場日（含）以前最後一個台股收盤 → 這一個進場日以前最後一個台股收盤
    tw_at = {}
    for mi, d in E[ok].items():
        k = twpx.index.searchsorted(d, side="right") - 1
        tw_at[mi] = twpx.index[k] if k >= 0 else pd.NaT
    tw_at = pd.Series(tw_at).reindex(cal.index)
    ent_px = {}
    for e in SUP_NAME:
        if e in ENTITY_IDS:
            s = pd.concat([twpx[sid].dropna() for sid, _, _ in ENTITY_IDS[e] if sid in twpx], axis=0)
            # 不同代號之間不接報酬（換股比例不同）
            seg = pd.concat([pd.Series(k, index=twpx[sid].dropna().index)
                             for k, (sid, _, _) in enumerate(ENTITY_IDS[e]) if sid in twpx])
            ent_px[e] = (s, seg)
        elif e in twpx:
            s = twpx[e].dropna()
            ent_px[e] = (s, pd.Series(0, index=s.index))
    sup_ret = {}
    for e, (s, seg) in ent_px.items():
        a = s.reindex(tw_at.values)
        g = seg.reindex(tw_at.values)
        a.index = tw_at.index
        g.index = tw_at.index
        r = a / a.shift(1) - 1
        sup_ret[e] = r.where(g == g.shift(1))
    out = []
    for c, g in sig.groupby("cust"):
        g = g.set_index("mi").sort_index()
        df = pd.DataFrame(index=g.index)
        df["cust"] = c
        df["nsup"] = g.nsup
        for s in SIGS:
            df[s] = g[s]
            df["z" + s] = expanding_z(g[s])
        for k in ("r1", "r3", "lead2", "lead3", "pre1", "pre2"):
            df["x_" + k] = R[c][k] - R["QQQ"][k]
            df["s_" + k] = R[c][k] - R["SMH"][k]
            df["raw_" + k] = R[c][k]
        df["mom"] = R[c]["m12_1"] - R["QQQ"]["m12_1"]
        df["supret"] = [np.nanmean([sup_ret[e].get(mi, np.nan) for e in sp if e in sup_ret]) if sp else np.nan
                        for mi, sp in g.sups.items()]
        out.append(df.reset_index())
    pan = pd.concat(out, ignore_index=True)
    pan["F"] = pan.mi.map(cal.F)
    pan["E"] = pan.mi.map(E)
    bench = pd.DataFrame({b: R[b]["r1"] for b in BENCH})
    return pan, late, bench


# -------------------------------------------------------------------------------------------------
# 4. 統計工具（不依賴 statsmodels）
# -------------------------------------------------------------------------------------------------
def hac_ols(df, ycol, xcols, lags, tcol="mi"):
    """合併 OLS；標準誤＝Driscoll–Kraay（lags=0 即按時間分群）。回傳 dict。"""
    d = df[[ycol] + xcols + [tcol]].dropna()
    n, k = len(d), len(xcols) + 1
    if n < k + 8:
        return None
    X = np.column_stack([np.ones(n), d[xcols].values.astype(float)])
    y = d[ycol].values.astype(float)
    XtXi = np.linalg.pinv(X.T @ X)
    b = XtXi @ X.T @ y
    e = y - X @ b
    H = pd.DataFrame(X * e[:, None]).groupby(d[tcol].values).sum()
    T = len(H)
    H = H.reindex(range(int(H.index.min()), int(H.index.max()) + 1)).fillna(0.0).values
    S = H.T @ H
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1)
        G = H[l:].T @ H[:-l]
        S += w * (G + G.T)
    adj = (T / max(T - 1, 1)) * ((n - 1) / max(n - k, 1))
    V = XtXi @ S @ XtXi * adj
    se = np.sqrt(np.diag(V))
    return {"b": b, "se": se, "t": b / se, "n": n, "T": T, "names": ["const"] + xcols}


def fmt_reg(r, i=1):
    if r is None:
        return "樣本不足"
    return f"b={r['b'][i]*100:+.3f}%  t={r['t'][i]:+.2f}  (觀察值 {r['n']}，月數 {r['T']})"


def mdd(curve):
    curve = np.asarray(curve, float)
    return float((curve / np.maximum.accumulate(curve) - 1).min()) if len(curve) else np.nan


def tstat(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else np.nan


def xs_sort(pan, sig, hold, bench, min_n=6):
    """每月依原始訊號排名；回傳每月的 top / bottom / ew 報酬與統計。"""
    d = pan.dropna(subset=[sig, "raw_r1"])
    members = {}
    for mi, g in d.groupby("mi"):
        if len(g) < min_n:
            continue
        g = g.sort_values(sig, ascending=False)
        k = max(1, int(round(len(g) / 3)))
        members[mi] = (list(g.cust[:k]), list(g.cust[-k:]), list(g.cust))
    r1 = pan.pivot(index="mi", columns="cust", values="raw_r1")
    rows, prev_w, tos = [], None, []
    for mi in sorted(members):
        cohorts = [members[m] for m in range(mi - hold + 1, mi + 1) if m in members]
        tops, bots = [], []
        w = Counter()
        for top, bot, _ in cohorts:
            rt = r1.loc[mi, top].dropna()
            rb = r1.loc[mi, bot].dropna()
            if len(rt):
                tops.append(rt.mean())
                for c in rt.index:
                    w[c] += 1 / len(rt) / len(cohorts)
            if len(rb):
                bots.append(rb.mean())
        ew = r1.loc[mi, members[mi][2]].mean()
        if prev_w is not None:
            tos.append(0.5 * sum(abs(w.get(c, 0) - prev_w.get(c, 0)) for c in set(w) | set(prev_w)))
        prev_w = w
        rows.append({"mi": mi, "top": np.mean(tops), "bot": np.mean(bots), "ew": ew, "n": len(members[mi][2])})
    res = pd.DataFrame(rows).set_index("mi")
    res = res.join(bench)
    out = {"months": len(res), "avg_n": res.n.mean(), "turnover": float(np.mean(tos)) if tos else np.nan, "res": res}
    for name, a, b in (("top-ew", "top", "ew"), ("top-bot", "top", "bot"), ("top-QQQ", "top", "QQQ"),
                       ("ew-QQQ", "ew", "QQQ")):
        x = (res[a] - res[b]).dropna()
        rel = ((1 + res[a]) / (1 + res[b])).dropna().cumprod()
        out[name] = {"ann": x.mean() * 12, "t": tstat(x), "hit": float((x > 0).mean()), "mdd": mdd(rel.values)}
    yrs = len(res) / 12
    for a in ("top", "bot", "ew", "QQQ", "SMH", "VOO"):
        out["cagr_" + a] = float((1 + res[a].dropna()).prod() ** (1 / yrs) - 1)
        out["mdd_" + a] = mdd((1 + res[a].dropna()).cumprod().values)
    return out


def pr_xs(label, o):
    te, tb = o["top-ew"], o["top-bot"]
    p(f"  {label:<22} 月數 {o['months']:>3}  平均家數 {o['avg_n']:.1f}  月換手 {o['turnover']*100:4.0f}%")
    p(f"     前1/3 − 等權籃子：年化 {te['ann']*100:+5.2f}pp  t={te['t']:+.2f}  勝率 {te['hit']*100:.0f}%  相對回撤 {te['mdd']*100:.0f}%")
    p(f"     前1/3 − 後1/3  ：年化 {tb['ann']*100:+5.2f}pp  t={tb['t']:+.2f}  勝率 {tb['hit']*100:.0f}%  相對回撤 {tb['mdd']*100:.0f}%")
    p(f"     年化報酬（幾何）：前1/3 {o['cagr_top']*100:.1f}%  後1/3 {o['cagr_bot']*100:.1f}%  等權籃子 {o['cagr_ew']*100:.1f}%  "
      f"QQQ {o['cagr_QQQ']*100:.1f}%  SMH {o['cagr_SMH']*100:.1f}%  VOO {o['cagr_VOO']*100:.1f}%")
    p(f"     最大回撤：前1/3 {o['mdd_top']*100:.0f}%  等權籃子 {o['mdd_ew']*100:.0f}%  QQQ {o['mdd_QQQ']*100:.0f}%（月頻）")


def corr_n(x, y):
    d = pd.concat([x, y], axis=1).dropna()
    if len(d) < 12:
        return np.nan, np.nan, len(d)
    return float(d.iloc[:, 0].corr(d.iloc[:, 1])), float(d.iloc[:, 0].corr(d.iloc[:, 1], method="spearman")), len(d)


# -------------------------------------------------------------------------------------------------
# 5. 主流程
# -------------------------------------------------------------------------------------------------
def main():
    from scipy.stats import norm
    p("台灣供應鏈月營收 → 美國客戶股價：事前登記檢定（2026-11-22）")
    p("=" * 100)
    sup, st = load_supplier_signals()
    twpx, twcal = load_tw_prices()
    uspx = load_us_prices()
    us_days = uspx["QQQ"].dropna().index
    cal = build_calendar(twcal, us_days, mi_of(2013, 1), mi_of(2025, 12))

    # ---- 資料檢查 ----
    p("\n【0】資料檢查")
    p(f"  對照表：供應商實體 {len({l[0] for l in LINKS})} 家、美國客戶 {len(CUSTS)} 家、連結 {len(LINKS)} 條"
      f"（其中 core-2015 {sum(l[4] for l in LINKS)} 條）")
    p(f"  供應商營收列數 {st['rows']}；年增率取自 MOPS 的 {st['yoy_from_mops']} 列、"
      f"取自自己 12 個月前的 {st['yoy_from_own_lag12']} 列、仍缺 {st['yoy_missing']} 列；非第一版 {st['rows_not_version1']} 列")
    starts = {e: ym_of(d.index[d.rev_ok.values.astype(bool)].min()) for e, d in sup.items()}
    late_start = {SUP_NAME.get(e, e): s for e, s in starts.items() if s > "2013-01"}
    p(f"  營收資料 2013-01 之後才開始的供應商：{late_start}")
    gaps = {SUP_NAME.get(e, e): int(d.loc[d.rev_ok.fillna(False), 'YOY'].isna().sum()) for e, d in sup.items()}
    p(f"  有營收但沒有年增率的月數（>0 才列）：{ {k: v for k, v in gaps.items() if v} }")
    lag_days, n_late, n_all = [], 0, 0
    for e, d in sup.items():
        for mi, a in d.annd.dropna().items():
            if mi in cal.index:
                n_all += 1
                F = cal.F[mi]
                lag_days.append((a - F).days)
                n_late += a > F
    lag = pd.Series(lag_days)
    p(f"  公告日對成形日（M+1 月 10 日或之後第一個台股交易日）：{n_all} 筆中晚於成形日 {n_late} 筆（{n_late/n_all*100:.2f}%）；"
      f"公告日比成形日早的天數中位數 {-lag.median():.0f} 天，最早 {-lag.min():.0f} 天")
    p(f"  成形日不是 10 日的月份（假日順延）：{int((cal.F.dt.day != 10).sum())} / {len(cal)} 個月；最晚落在每月 {int(cal.F.dt.day.max())} 日")
    p(f"  美股價格起訖：{uspx.index.min().date()} → {uspx.index.max().date()}；各客戶第一筆價格："
      f"{ {c: str(uspx[c].first_valid_index().date()) for c in CUSTS if uspx[c].first_valid_index() > pd.Timestamp('2012-01-10')} }")

    pan, late, bench = build_panel(sup, cal, uspx, twpx, LINKS, "ew", "E")
    cov = pan.dropna(subset=["ACCEL"]).groupby("cust").agg(first=("mi", "min"), n=("mi", "count"), nsup=("nsup", "mean"))
    p("  各客戶 ACCEL 訊號涵蓋：" + "；".join(f"{c} {ym_of(r['first'])}起 {int(r['n'])}月 平均{r['nsup']:.1f}家" for c, r in cov.iterrows()))
    prim = pan.dropna(subset=["zACCEL", "x_r1"])
    months = sorted(prim.mi.unique())
    p(f"  主要規格樣本：{len(prim)} 個客戶-月，{len(months)} 個獨立月份（營收月 {ym_of(months[0])} → {ym_of(months[-1])}；"
      f"進場日 {prim.E.min().date()} → {prim.E.max().date()}；最後出場 ≤ {END}）")
    half_cut = months[len(months) // 2]

    # ---- (i) 合併追蹤資料 ----
    p("\n【1】合併追蹤資料迴歸：下期超額報酬 = a + b·z（b＝訊號高 1 個標準差，超額報酬多幾 %）")
    p("  主要規格 ★ = ACCEL / 等權 / 1 個月 / 對 QQQ")
    main_res = {}
    for s in SIGS:
        for h, lags in (("r1", 0), ("r3", 3)):
            r = hac_ols(pan, "x_" + h, ["z" + s], lags)
            reg("panel-QQQ", f"{s}-{h}")
            main_res[(s, h)] = r
            star = " ★" if (s, h) == ("ACCEL", "r1") else ""
            p(f"  對 QQQ  {s:<5} {'1個月' if h=='r1' else '3個月'}：{fmt_reg(r)}{star}")
    semi = pan[pan.cust.isin(SEMI)]
    for s in SIGS:
        for h, lags in (("r1", 0), ("r3", 3)):
            r = hac_ols(semi, "s_" + h, ["z" + s], lags)
            reg("panel-SMH", f"{s}-{h}")
            p(f"  半導體客戶對 SMH  {s:<5} {'1個月' if h=='r1' else '3個月'}：{fmt_reg(r)}")

    p("\n  每個客戶各自的時間序列（ACCEL；對 QQQ；半導體另列對 SMH）。17 家裡碰巧出現 1 家 |t|>2 屬正常。")
    for c in CUSTS:
        g = pan[pan.cust == c]
        r1 = hac_ols(g, "x_r1", ["zACCEL"], 0)
        r3 = hac_ols(g, "x_r3", ["zACCEL"], 3)
        reg("per-customer", f"{c}-r1")
        reg("per-customer", f"{c}-r3")
        extra = ""
        if c in SEMI:
            q = hac_ols(g, "s_r1", ["zACCEL"], 0)
            reg("per-customer", f"{c}-r1-SMH")
            extra = f" ｜對SMH 1個月 t={q['t'][1]:+.2f}" if q else ""
        if r1 is None:
            p(f"    {c:<5} 樣本不足")
            continue
        p(f"    {c:<5} 1個月 b={r1['b'][1]*100:+.2f}% t={r1['t'][1]:+.2f} n={r1['n']} ｜ 3個月 b={r3['b'][1]*100:+.2f}% t={r3['t'][1]:+.2f}{extra}")

    # ---- (ii) 橫斷面 ----
    p("\n【2】橫斷面排序：每月把客戶依訊號排名，買前三分之一")
    xs_main = {}
    for s in SIGS:
        for hold in (1, 3):
            o = xs_sort(pan, s, hold, bench)
            reg("xs", f"{s}-hold{hold}-top-ew")
            reg("xs", f"{s}-hold{hold}-top-bot")
            xs_main[(s, hold)] = o
            pr_xs(f"{s} 持有{hold}個月" + (" ★" if (s, hold) == ("ACCEL", 1) else ""), o)

    # ---- (iii) 控制變數 ----
    p("\n【3】控制變數（ACCEL；對 QQQ）。看 z 的係數在加入控制後還剩多少。")
    ctl = pan.dropna(subset=["zACCEL", "mom", "supret", "x_pre1"])
    for h, lags in (("r1", 0), ("r3", 3)):
        for name, xs in (("只有訊號（同樣本）", ["zACCEL"]), ("＋客戶 12-1 動能", ["zACCEL", "mom"]),
                         ("＋供應商自己同期股價", ["zACCEL", "supret"]),
                         ("＋動能＋供應商股價＋客戶前月報酬", ["zACCEL", "mom", "supret", "x_pre1"])):
            r = hac_ols(ctl, "x_" + h, xs, lags)
            reg("controls", f"{h}-{name}")
            others = "  ".join(f"{nm}: t={r['t'][i]:+.2f}" for i, nm in enumerate(r["names"]) if i >= 2)
            p(f"  {'1個月' if h=='r1' else '3個月'} {name:<22} {fmt_reg(r)}  {others}")
    r = hac_ols(pan, "supret", ["zACCEL"], 0)
    reg("controls", "supret-on-signal")
    p(f"  供應商自己的台股同期報酬對訊號：{fmt_reg(r)}  ←台股自己有沒有反應")

    # ---- (iv) 領先落後 ----
    p("\n【4】領先落後：訊號對各單月超額報酬（對 QQQ）。公告前 = 訊號成形以前的月份。")
    for s in SIGS:
        parts = []
        for k, lab in (("pre2", "公告前第2月"), ("pre1", "公告前第1月"), ("r1", "公告後第1月"), ("lead2", "公告後第2月"),
                       ("lead3", "公告後第3月")):
            r = hac_ols(pan, "x_" + k, ["z" + s], 0)
            if k != "r1":
                reg("lead-lag", f"{s}-{k}")
            parts.append(f"{lab} b={r['b'][1]*100:+.2f}% t={r['t'][1]:+.2f}")
        p(f"  {s:<5} " + " ｜ ".join(parts))

    # ---- (v) 分段 ----
    p("\n【5】分段（合併追蹤資料；對 QQQ）")
    segs = [("前半", pan[pan.mi < half_cut]), ("後半", pan[pan.mi >= half_cut]),
            ("2023 以前", pan[pan.F < "2023-01-01"]), ("2023–2025", pan[pan.F >= "2023-01-01"])]
    p(f"  前後半分界：營收月 {ym_of(half_cut)}")
    half_t = {}
    for s in SIGS:
        for h, lags in (("r1", 0), ("r3", 3)):
            parts = []
            for nm, d in segs:
                r = hac_ols(d, "x_" + h, ["z" + s], lags)
                reg("split", f"{s}-{h}-{nm}")
                parts.append(f"{nm} b={r['b'][1]*100:+.2f}% t={r['t'][1]:+.2f} (月數{r['T']})")
                if (s, h) == ("ACCEL", "r1"):
                    half_t[nm] = r["t"][1]
            p(f"  {s:<5} {'1個月' if h=='r1' else '3個月'}： " + " ｜ ".join(parts))
    p("  橫斷面 ACCEL 持有 1 個月，前1/3 − 等權籃子，分段：")
    res = xs_main[("ACCEL", 1)]["res"]
    dd = res.top - res.ew
    Fm = cal.F.reindex(res.index)
    for nm, mask in (("前半", res.index < half_cut), ("後半", res.index >= half_cut),
                     ("2023 以前", (Fm < "2023-01-01").values), ("2023–2025", (Fm >= "2023-01-01").values)):
        x = dd[mask]
        reg("split", f"xs-ACCEL-{nm}")
        p(f"    {nm:<9} 年化 {x.mean()*12*100:+5.2f}pp  t={tstat(x):+.2f}  月數 {len(x)}")

    # ---- 穩健性 ----
    p("\n【6】事前登記的穩健性")
    core = [l for l in LINKS if l[4]]
    pan_c, _, _ = build_panel(sup, cal, uspx, twpx, core, "ew", "E")
    p(f"  (a) 只用 2015 年就已是教科書等級的連結（{len(core)} 條，客戶 {pan_c.dropna(subset=['ACCEL']).cust.nunique()} 家）")
    for s in SIGS:
        for h, lags in (("r1", 0), ("r3", 3)):
            r = hac_ols(pan_c, "x_" + h, ["z" + s], lags)
            reg("robust-core2015", f"{s}-{h}")
            p(f"      {s:<5} {'1個月' if h=='r1' else '3個月'}：{fmt_reg(r)}")
    for hold in (1, 3):
        o = xs_sort(pan_c, "ACCEL", hold, bench)
        reg("robust-core2015", f"xs-ACCEL-{hold}")
        pr_xs(f"core ACCEL 持有{hold}個月", o)
    pan_w, _, _ = build_panel(sup, cal, uspx, twpx, LINKS, "rw", "E")
    p("  (b) 供應商改用營收加權")
    for s in SIGS:
        for h, lags in (("r1", 0), ("r3", 3)):
            r = hac_ols(pan_w, "x_" + h, ["z" + s], lags)
            reg("robust-revweight", f"{s}-{h}")
            p(f"      {s:<5} {'1個月' if h=='r1' else '3個月'}：{fmt_reg(r)}")
    for hold in (1, 3):
        o = xs_sort(pan_w, "ACCEL", hold, bench)
        reg("robust-revweight", f"xs-ACCEL-{hold}")
        pr_xs(f"營收加權 ACCEL 持有{hold}個月", o)
    pan_0, _, _ = build_panel(sup, cal, uspx, twpx, LINKS, "ew", "E0")
    r = hac_ols(pan_0, "x_r1", ["zACCEL"], 0)
    reg("robust-sameday", "ACCEL-r1")
    p(f"  (c) 進場日改成成形日當天的美股收盤：ACCEL 1個月 {fmt_reg(r)}")
    o = xs_sort(pan_0, "ACCEL", 1, bench)
    reg("robust-sameday", "xs-ACCEL-1")
    pr_xs("當天進場 ACCEL 持有1個月", o)

    # ---- 白話描述 ----
    p("\n【7】白話描述：供應商營收驚喜（SURP，等權）與客戶超額報酬的相關係數")
    p("  r＝皮爾森相關；ρ＝等級相關；n＝月數。3 個月報酬互相重疊，有效樣本約 n/3。")
    P_E = uspx.reindex(cal.E.dropna().values)
    P_E.index = cal.E.dropna().index
    P_E = P_E.reindex(cal.index)
    for name, sups_, custs_, bm, y0 in PAIRS:
        srs = []
        for e in sups_:
            d = sup.get(e)
            if d is None:
                continue
            x = d.SURP.reindex(cal.index)
            a = d.annd.reindex(cal.index)
            srs.append(x.where(a.notna() & (a <= cal.F)))
        sg = pd.concat(srs, axis=1).mean(axis=1)
        yrs = cal.F.dt.year
        sg = sg.where(yrs >= y0)
        cu = [c for c in custs_]

        def ex(a, b):
            rc = pd.concat([(P_E[c].shift(-b) / P_E[c].shift(-a) - 1) for c in cu], axis=1).mean(axis=1, skipna=False)
            return rc - (P_E[bm].shift(-b) / P_E[bm].shift(-a) - 1)

        outs = []
        for lab, a, b in (("公告前1月", -1, 0), ("下1月", 0, 1), ("下3月", 0, 3)):
            r_, rho, n = corr_n(sg, ex(a, b))
            reg("descriptive", f"{name}-{lab}")
            outs.append(f"{lab} r={r_:+.2f} ρ={rho:+.2f} n={n}")
        ai = sg.where(yrs >= 2023)
        r_, rho, n = corr_n(ai, ex(0, 1))
        reg("descriptive", f"{name}-下1月-2023起")
        pre = sg.where(yrs < 2023)
        r2, rho2, n2 = corr_n(pre, ex(0, 1))
        reg("descriptive", f"{name}-下1月-2023前")
        p(f"  {name}（對 {bm}，{y0} 起）")
        p("     " + " ｜ ".join(outs))
        p(f"     下1月分段：2023 以前 r={r2:+.2f} n={n2} ｜ 2023–2025 r={r_:+.2f} n={n}")

    # ---- 事後探索：管線檢查 ----
    p("\n【9】事後探索（看過結果後才加）：管線檢查——供應商自己的訊號 vs 供應商自己的台股報酬")
    p("  目的：確認訊號算法與日期對齊沒壞。台股月營收對自家股價有反應是已知現象，這裡應該看得到。")
    p("  報酬與訊號都先減掉當月全部對照表供應商的平均（去掉大盤）。按月分群。不計入本假說的判定。")
    E = cal["E"]
    tw_at = pd.Series({mi: (twpx.index[twpx.index.searchsorted(d, side="right") - 1]) for mi, d in E.dropna().items()}
                      ).reindex(cal.index)
    rows = []
    for e, d in sup.items():
        if e in ENTITY_IDS:
            parts = [(sid, twpx[sid].dropna()) for sid, _, _ in ENTITY_IDS[e] if sid in twpx]
        else:
            parts = [(e, twpx[e].dropna())] if e in twpx else []
        if not parts:
            continue
        s_ = pd.concat([x for _, x in parts])
        seg = pd.concat([pd.Series(k, index=x.index) for k, (_, x) in enumerate(parts)])
        a_ = s_.reindex(tw_at.values)
        g_ = seg.reindex(tw_at.values)
        a_.index = tw_at.index
        g_.index = tw_at.index
        r_ = (a_ / a_.shift(1) - 1).where(g_ == g_.shift(1))
        okd = d.annd.reindex(cal.index)
        okm = okd.notna() & (okd <= cal.F)
        df_ = pd.DataFrame({"mi": cal.index, "ent": e, "pre": r_.values, "post": r_.shift(-1).values})
        for s in SIGS:
            df_[s] = d[s].reindex(cal.index).where(okm).values
        rows.append(df_)
    sp = pd.concat(rows, ignore_index=True)
    for col in ["pre", "post"] + SIGS:
        sp[col] = sp[col] - sp.groupby("mi")[col].transform("mean")
    for s in SIGS:
        sd = sp[s].std()
        sp["u"] = sp[s] / sd
        a1 = hac_ols(sp, "pre", ["u"], 0)
        a2 = hac_ols(sp, "post", ["u"], 0)
        reg("posthoc-pipeline", f"{s}-pre")
        reg("posthoc-pipeline", f"{s}-post")
        p(f"  {s:<5} 公告所在的那個月（上個進場日→這個進場日）：{fmt_reg(a1)}")
        p(f"        公告後下一個月：{fmt_reg(a2)}")

    # ---- 判定 ----
    p("\n【8】對照事前門檻的判定")
    pr_ = main_res[("ACCEL", "r1")]
    t_main = float(pr_["t"][1])
    te = xs_main[("ACCEL", 1)]["top-ew"]
    c1 = t_main >= 3.0
    c2 = (half_t["前半"] >= 1.5 and half_t["後半"] >= 1.5 and t_main > 0)
    c3 = te["ann"] >= 0.03
    p(f"  條件 1  主要規格 t ≥ 3.0：t = {t_main:+.2f}  → {'過' if c1 else '未過'}")
    p(f"  條件 2  前後半同向且各 t ≥ 1.5：前半 {half_t['前半']:+.2f}、後半 {half_t['後半']:+.2f}  → {'過' if c2 else '未過'}")
    p(f"  條件 3  前1/3 每年贏等權籃子 ≥ 3pp：{te['ann']*100:+.2f}pp（t={te['t']:+.2f}）  → {'過' if c3 else '未過'}")
    p(f"  結論：{'三條全過 → 只算提名去做前瞻測試' if (c1 and c2 and c3) else '未過門檻'}")
    fam = Counter(f for f, _ in TRIED)
    K = len(TRIED)
    p(f"\n  本次共計算 {K} 個「訊號對報酬」統計量（事前登記 {K - fam['posthoc-pipeline']}、事後探索 {fam['posthoc-pipeline']}）：{dict(fam)}")
    p(f"  獨立月份 {len(months)} 個。單一檢定的 5% 線是 |t| ≥ 1.96。")
    p(f"  以本次 {K} 次校正（Bonferroni）：|t| ≥ {norm.ppf(1 - 0.025 / K):.2f} 才不算運氣。")
    p(f"  連同專案先前約 1,000 次：|t| ≥ {norm.ppf(1 - 0.025 / (K + 1000)):.2f}。")
    ts = []
    for (s, h), r in main_res.items():
        ts.append(abs(r["t"][1]))
    p(f"  本次 6 個對 QQQ 的合併迴歸中，最大 |t| = {max(ts):.2f}。")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT, "w") as f:
        f.write("\n".join(_lines) + "\n")
    return pan, sup, cal, uspx, twpx, bench


if __name__ == "__main__":
    main()
