"""半導體景氣指標能不能預測 SMH 的報酬（絕對、相對 QQQ、相對 SPY）——預先登記的檢定（2026-11-22）。

【這段 docstring 是預先登記】寫完這段之後才第一次下載任何股價／報酬資料。
寫之前只做過「指標資料拿不拿得到」的探測（FRED、WSTS、FinMind、本機 MOPS 公開月營收的欄位與起迄月），沒有看過任何報酬。
之後若有任何新增的指標、轉換、門檻、樣本切法，一律放在輸出最後的「事後探索」，不算入門檻判定。
本檔執行時會印出這段文字的 sha256，首跑前的雜湊另存在 data/semi_cycle_smh_2026-11-22/prereg_sha256.txt。

背景
  投資人限制：不開槓桿、持有期不短於一個月、低周轉、零手續費、無資本利得稅。
  半導體集中度不能比 SMH 更高，所以實際用法只有一種：「平常抱 SMH，景氣指標差的時候把部位換到 QQQ 或現金」。
  本專案之前大量挖過 2018–2025，所以歷史回測通過只算「提名」，不算證實。回測一律止於 2025-12-31（2026 年資料完全不讀，留作日後的乾淨樣本）。

樣本
  主樣本：決策月底 2011-12 … 2025-11（報酬月 2012-01 … 2025-12），SMH／QQQ／SPY 用 yfinance 還原收盤的月底值。
    SMH 在 2011 年底改組，2012 以前的序列不可靠，一律不用。
  長樣本（穩健性）：^SOX（費半價格指數，不含股息）對 ^NDX、^GSPC（也都是價格指數），1995-01 起，止於 2025-12。
    另外單獨報「2011 以前」那一段，因為那段沒被本專案挖過。
  對半切：前半＝報酬月 2012–2018，後半＝2019–2025。另報「去掉 2023–2025」（報酬月 2012–2022）。

指標（6 個有免費且夠長的資料；每個都照真實公布時差往後推，值在「可用月底」之後才能用）
  A  台積電月營收年增率。來源 FinMind 免費 API（等同公開資訊觀測站 MOPS），2002-01 起。
     公布：次月 10 日前（本機資料的公告日中位數是月底後 10 天、最晚 15 天）→ 資料月 M 在 M+1 月底可用（時差 1 個月）。
     營收年增率用「近三個月營收合計」對「去年同期三個月合計」算（三個月平均年增率）。
     理由：一、二月受農曆年落點干擾，單月年增率會亂跳；而且 WSTS 的標準口徑也是三個月移動平均。
     2013 年起改報合併營收：2013 之後的去年同期值改用 MOPS 當月公布的「去年同月營收」（同口徑），2012 以前用母公司口徑對母公司口徑。
     公司自行申報、極少修正，視為接近即時資料。
  B  台灣半導體大型股（不含台積電）合計月營收年增率。固定名單事先定死、不看績效：
     晶圓代工 2303 聯電、5347 世界；封測 2449 京元電、6239 力成；IC 設計 2454 聯發科、3034 聯詠、2379 瑞昱；記憶體 2408 南亞科、2344 華邦電、2337 旺宏。
     不含台積電，因為台積電佔合計一半以上，放進去就等於重複 A。日月光（3711／2311／2325）因免費來源 2013-01 到 2018-04 缺資料而排除。
     名單是「現在看得到的大公司」，有倖存者偏誤。算法、時差同 A（配對樣本：同時有今年與去年值的公司才加總）。
  C  WSTS 全球半導體銷售額（三個月移動平均）年增率。來源 wsts.org Historical Billings Report（2026-09 版 xlsx），1986 起。
     公布：月底後約 5 週 → 時差 2 個月。只有最新版本，歷史值可能修正過 → 結果偏樂觀。
  D1 美國半導體工業生產指數 IPG3344S 年增率（FRED）。G.17 於次月中公布 → 時差 1 個月。每年大幅修正，只有最新版本 → 偏樂觀。
  D2 美國「電腦及電子產品」製造業存貨／出貨比 A34SIS（FRED，M3 調查）。用「比值年變動率取負號」，數字越高＝庫存越輕＝越好。
     M3 完整報告於月底後約 5 週公布 → 時差 2 個月。會修正 → 偏樂觀。半導體專屬的 M3 序列（A34GVS）已在 2010 年停編，只能用大類。
  D3 美國「電腦及電子產品」製造業新訂單 A34SNO 年增率（FRED，M3）。時差 2 個月。會修正。注意：普查局的新訂單不含半導體本身。
  E  南韓半導體出口年增率、台灣外銷訂單（電子產品）年增率：資料拿不到（細節寫在輸出與報告），不納入。
  F  價格對照組（不算候選指標）：半導體自身 12-1 動能（12 個月前到 1 個月前的漲幅）、半導體相對那斯達克 100 的 12-1 相對強弱。
     兩者都用 ^SOX 與 ^NDX 算（SMH 2012 以前不可靠，算不出 2012 年的動能）。

轉換（每個指標剛好兩種）
  T1 水準：年增率本身。回歸用連續值；規則用「年增率 > 0」＝好。
  T2 加速度：年增率減三個月前的年增率。回歸用連續值；規則用「加速度 > 0」＝好。
  候選訊號共 6 × 2 = 12 個。不設其他門檻、不做最佳化。

檢定 1：預測回歸
  y ＝ 決策月底之後 1 個月、3 個月的報酬：SMH、SMH 減 QQQ、SMH 減 SPY（累積報酬相減）。x ＝ 訊號（樣本內標準化）。
  Newey–West 標準誤（修正重疊樣本造成的自我相關）：1 個月用 3 階、3 個月用 6 階。
  主樣本 12 訊號 × 2 期間 × 3 目標 = 72 條。報係數正負號、t、R²、樣本數、獨立樣本數（樣本數 ÷ 期間）。
  預期方向：正（指標好 → 之後 SMH 較強）。
  敏感度（事先登記、只 2 條）：A 改用「單月」年增率，T1／T2 → 3 個月 SMH 減 QQQ。
  長樣本：同樣 72 條（^SOX、^SOX 減 ^NDX、^SOX 減 ^GSPC），全段與「2011 以前」各報一次。
  加入價格對照組：y 對 [訊號、12-1 動能、相對強弱] 一起回歸，看訊號的 t 還剩多少。

檢定 2：「二階導數」說法（股價在年增率見底時落底，不是在營收水準見底時）
  只用過去資料的轉折定義（在資料月 t 判定）：
    年增率谷底：y[t] > y[t-1] > y[t-2]，且 y[t-2] 是過去 13 個值的最低，且 y[t-2] < y[t-8]。
    年增率峰頂：對稱。同類事件 12 個月內只算一次。事件在 t 加公布時差的月底才可用。
  事件後 6、12 個月報酬：SMH（主樣本）與 ^SOX（長樣本），谷底對峰頂對全部月份平均，附事件數。6 指標 × 2 期間 × 2 標的 = 24 組。
  「水準見底」對照：C 與 A 的三個月營收水準用同一套規則找谷底，^SOX 6、12 個月（4 組）。
  描述性（用到事後資訊，只供閱讀）：^SOX 月收盤在年增率真實谷底月前後 12 個月內的最低點，落在谷底月的前或後幾個月。

檢定 3：簡單規則
  每月底決策一次：訊號＝好 → 下個月抱 SMH，否則抱 QQQ（變體：否則抱國庫券，報酬用 FRED TB3MS）。最短持有一個月。
  12 訊號 × 2 種避風港 = 24 條；對照組 2 個價格訊號 × 2 = 4 條。
  報 CAGR（年化報酬）、最大回撤（用月底值，會低估月中回撤）、Calmar（年化報酬 ÷ 最大回撤）、切換次數、抱 SMH 的月份比例。
  比較對象：買進持有 SMH、買進持有 QQQ、SMH／QQQ 各半（每月再平衡）、SPY。分段：全段、前半、後半、去掉 2023–2025。
  長樣本另跑 12 條（^SOX 對 ^NDX）。

檢定 4：反方向（股價是不是領先指標）
  交叉相關：^SOX 12 個月漲幅（月 t）對指標年增率（資料月 t+k），k = -12…+12，報相關最高的 k。k > 0 ＝股價領先。
  對稱回歸（都不加公布時差，對指標最有利）：
    正向：^SOX 未來 6 個月報酬 對 指標年增率過去 6 個月的變化。
    反向：指標年增率未來 6 個月的變化 對 ^SOX 過去 6 個月報酬。Newey–West 12 階。

過關門檻（事先定死；三項全過才算「過門檻」，而且即使過也只是提名）
  主規格 ＝ A 的 T2（台積電營收年增率的加速度）→ 之後 3 個月 SMH 減 QQQ，主樣本。
  (1) 全段 |t| ≥ 3.0，且前半、後半係數與全段同號。
  (2) 切換規則（A-T2，好抱 SMH、否則抱 QQQ）的 CAGR 在前半、後半都高於買進持有 SMH，且全段平均每年切換 ≤ 3 次。
  (3) 加入兩個價格對照變數後，訊號的 |t| 仍 ≥ 2.0。
  任一項不過 ＝「未過門檻」。不為了過關而調整任何設定。
  運氣線：把所有變體數 N 代入 Bonferroni（5% 雙尾 ÷ N）算出的 t，以及 N 個獨立檢定下「最大 |t|」的期望值，一併印出。
  提醒：14 年只有 3–4 個半導體循環，有效樣本極小。

Run（首跑需要讀本機 MOPS parquet，用 fadacai-tw 的環境；之後有快取，系統 python3 即可）:
  /Users/supatrick/laptop/project/fadacai-tw/.venv/bin/python tools/backtests/semi_cycle_smh_2026-11-22.py
Output: tools/backtests/data/semi_cycle_smh_2026-11-22.out.txt
"""
# 首跑結論（2026-11-22；寫在 docstring 之外，預先登記的文字與雜湊不動）：未過門檻。
#   主規格 t = -0.66（方向相反；前半 +0.17、後半 -1.00；加價格對照 -0.36），n=166、約 55 個獨立的三個月。
#   主規則（好抱 SMH、否則 QQQ）CAGR 23.0% 對買進持有 SMH 26.8%；前半 -1.8、後半 -6.2 個百分點；每年切換 2.3 次。
#   主樣本 72 條回歸 |t| 最大 1.86、沒有一條 ≥2；24 條規則沒有一條前後半都贏 SMH。
#   反方向成立：^SOX 12 個月漲幅領先 WSTS 年增率 3–5 個月；反向回歸 t +3.8 到 +4.0，正向 -0.5 到 +1.0。
#   首跑後加了「事後探索」一節（P1–P3），並把價格快取由 pkl 改成 csv（系統 python3 沒有 pyarrow 讀不了 pkl）；其餘未動。
#   報告：research/semi-cycle-smh-2026-11-22.md
import hashlib
import io
import json
import os
import re
import time
import warnings
import zipfile
import xml.etree.ElementTree as ET
from statistics import NormalDist

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import requests
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "semi_cycle_smh_2026-11-22.out.txt")
CACHE = os.path.join(HERE, "data", "semi_cycle_smh_2026-11-22")
os.makedirs(CACHE, exist_ok=True)
MOPS_PARQUET = "/Users/supatrick/laptop/project/fadacai-tw/data/raw/mops/mops_revenue.parquet"
WSTS_URL = "https://www.wsts.org/esraCMS/extension/media/f/WST/7849/WSTS-Historical-Billings-Report-Sep_2026.xlsx"
END = pd.Period("2025-12", "M")
P0 = pd.Period("2011-12", "M")          # 主樣本第一個決策月底
SPLIT = pd.Period("2018-12", "M")       # 前半最後一個報酬月
EX_END = pd.Period("2022-12", "M")      # 「去掉 2023–2025」的最後報酬月
LONG0 = pd.Period("1994-12", "M")       # 長樣本第一個決策月底
TW_LIST = ["2303", "5347", "2449", "6239", "2454", "3034", "2379", "2408", "2344", "2337"]
NW_LAGS = {1: 3, 3: 6}
_lines = []
N_VARIANTS = {}


def p(s=""):
    print(s)
    _lines.append(s)


def count(key, n=1):
    N_VARIANTS[key] = N_VARIANTS.get(key, 0) + n


# ── 資料 ────────────────────────────────────────────────────────────────────
def cached_bytes(name, fetch):
    path = os.path.join(CACHE, name)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as f:
            return f.read()
    b = fetch()
    with open(path, "wb") as f:
        f.write(b)
    return b


def http_get(url):
    def go():
        # FRED 會擋瀏覽器樣式的 User-Agent（讀取逾時），WSTS 則需要；兩種輪流試
        for i, ua in enumerate(("curl/8.7.1", "Mozilla/5.0", "curl/8.7.1")):
            try:
                r = requests.get(url, timeout=45, headers={"User-Agent": ua})
                if r.status_code == 200 and len(r.content) > 100:
                    return r.content
            except requests.RequestException:
                pass
            time.sleep(2 + 2 * i)
        raise RuntimeError(f"download failed: {url}")
    return go


def fred(sid):
    b = cached_bytes(f"fred_{sid}.csv", http_get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"))
    df = pd.read_csv(io.BytesIO(b))
    df.columns = ["date", "v"]
    s = pd.to_numeric(df["v"], errors="coerce")
    s.index = pd.PeriodIndex(pd.to_datetime(df["date"]), freq="M")
    return s.dropna()


def finmind_rev(sid):
    url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue&data_id={sid}&start_date=1998-01-01"
    b = cached_bytes(f"finmind_rev_{sid}.json", http_get(url))
    d = pd.DataFrame(json.loads(b)["data"])
    idx = pd.PeriodIndex([pd.Period(year=int(y), month=int(m), freq="M") for y, m in zip(d.revenue_year, d.revenue_month)])
    s = pd.Series(d.revenue.astype(float).values, index=idx)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.where(s > 0)


def mops_last_year():
    """2013 起 MOPS 公布的『當月營收／去年同月營收』（公開資料），只取本檔用到的 11 檔，快取成 csv。"""
    path = os.path.join(CACHE, "mops_last_year_2013plus.csv")
    if not os.path.exists(path):
        m = pd.read_parquet(MOPS_PARQUET)
        m = m[m.stock_id.isin(["2330"] + TW_LIST)][["stock_id", "revenue_year", "revenue_month", "revenue", "revenue_last_year"]]
        m.to_csv(path, index=False)
    m = pd.read_csv(path, dtype={"stock_id": str})
    m["ym"] = pd.PeriodIndex([pd.Period(year=int(y), month=int(mo), freq="M") for y, mo in zip(m.revenue_year, m.revenue_month)])
    return m.drop_duplicates(["stock_id", "ym"], keep="last")


def rev_cur_prior(ids, mops):
    cur, prior, chk = {}, {}, []
    for i in ids:
        s = finmind_rev(i)
        pr = s.copy()
        pr.index = pr.index + 12
        mm = mops[mops.stock_id == i].set_index("ym")
        ly = mm.revenue_last_year.astype(float)
        ly = ly[ly > 0]
        pr = pr.reindex(pr.index.union(ly.index))
        pr.loc[ly.index] = ly.values
        cur[i], prior[i] = s, pr
        j = pd.concat([s.rename("fm"), mm.revenue.astype(float).rename("mops")], axis=1).dropna()
        chk.append((i, len(j), float((j.fm / j.mops - 1).abs().max()) if len(j) else np.nan))
    return pd.DataFrame(cur), pd.DataFrame(prior), chk


def group_yoy(cur, prior, window=3):
    c = cur.rolling(window).sum() if window > 1 else cur
    q = prior.reindex(cur.index)
    q = q.rolling(window).sum() if window > 1 else q
    ok = c.notna() & q.notna()
    num, den = c.where(ok).sum(axis=1, min_count=1), q.where(ok).sum(axis=1, min_count=1)
    return (num / den - 1).dropna() * 100, ok.sum(axis=1)


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def wsts_worldwide(sheet):
    """sheet 1＝單月銷售額、sheet 2＝三個月移動平均。回傳 Worldwide 月序列（千美元）。"""
    b = cached_bytes("wsts_historical_billings_2026-09.xlsx", http_get(WSTS_URL))
    z = zipfile.ZipFile(io.BytesIO(b))
    ss = ["".join(t.text or "" for t in si.iter("{%s}t" % NS["m"]))
          for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)]
    root = ET.fromstring(z.read(f"xl/worksheets/sheet{sheet}.xml"))
    out, year = {}, None
    for r in root.iter("{%s}row" % NS["m"]):
        d = {}
        for c in r.findall("m:c", NS):
            col = re.match(r"[A-Z]+", c.get("r")).group(0)
            v = c.find("m:v", NS)
            if v is not None:
                d[col] = ss[int(v.text)] if c.get("t") == "s" else v.text
        a = str(d.get("A", "")).strip()
        if re.fullmatch(r"(19|20)\d\d(\.0)?", a) and len(d) == 1:
            year = int(float(a))
        elif a == "Worldwide" and year:
            for k, col in enumerate("BCDEFGHIJKLM"):
                if col in d:
                    v = float(d[col])
                    if v > 0:
                        out[pd.Period(year=year, month=k + 1, freq="M")] = v
    return pd.Series(out).sort_index()


def yoy(s):
    return (s / s.shift(12) - 1) * 100


def load_prices():
    path = os.path.join(CACHE, "px_monthly.csv")
    if not os.path.exists(path):
        raw = yf.download(["SMH", "QQQ", "SPY", "^SOX", "^NDX", "^GSPC"], start="1990-01-01", end="2026-01-01",
                          progress=False, auto_adjust=True)["Close"]
        raw = raw[raw.index <= "2025-12-31"]
        m = raw.groupby(raw.index.to_period("M")).last()
        m.columns = [c.replace("^", "") for c in m.columns]
        m.loc[m.index < P0, "SMH"] = np.nan     # 2012 以前的 SMH 不用
        m.index = m.index.astype(str)
        m.index.name = "month"
        m.to_csv(path)
    m = pd.read_csv(path, index_col=0)
    m.index = pd.PeriodIndex(m.index, freq="M")
    return m.astype(float)


# ── 統計工具 ────────────────────────────────────────────────────────────────
def nw_ols(y, X, lags):
    n, k = X.shape
    xtx_inv = np.linalg.inv(X.T @ X)
    b = xtx_inv @ X.T @ y
    e = y - X @ b
    xe = X * e[:, None]
    s = xe.T @ xe
    for l in range(1, lags + 1):
        g = xe[l:].T @ xe[:-l]
        s += (1 - l / (lags + 1)) * (g + g.T)
    v = xtx_inv @ s @ xtx_inv * n / (n - k)
    se = np.sqrt(np.diag(v))
    r2 = 1 - (e @ e) / ((y - y.mean()) @ (y - y.mean()))
    return b, b / se, r2, n


def reg(y, xs, lags, lo=None, hi=None):
    """y: Series（決策月為索引）；xs: list of Series。樣本內把 x 標準化。回傳 (b_x1, t 向量[不含常數], r2, n)。"""
    df = pd.concat([y.rename("y")] + [x.rename(f"x{i}") for i, x in enumerate(xs)], axis=1).dropna()
    if lo is not None:
        df = df[df.index >= lo]
    if hi is not None:
        df = df[df.index <= hi]
    if len(df) < 24:
        return np.nan, [np.nan] * len(xs), np.nan, len(df)
    xm = df.iloc[:, 1:]
    xm = (xm - xm.mean()) / xm.std()
    X = np.column_stack([np.ones(len(df)), xm.values])
    b, t, r2, n = nw_ols(df["y"].values, X, lags)
    return b[1], list(t[1:]), r2, n


def fwd(px, h):
    return (px.shift(-h) / px - 1) * 100


def perf(r):
    r = r.dropna()
    eq = (1 + r).cumprod()
    yrs = len(r) / 12
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    peak = eq.cummax().clip(lower=1.0)
    mdd = (eq / peak - 1).min()
    return cagr * 100, mdd * 100, (cagr / abs(mdd) if mdd < 0 else np.nan)


def turning_points(y, kind):
    """只用過去資料的轉折判定。回傳判定月 t 的清單（真實極值月＝t-2）。"""
    v = y.dropna()
    if kind == "peak":
        v = -v
    ev, last = [], None
    idx = v.index
    for k in range(14, len(v)):
        a, b_, c = v.iloc[k], v.iloc[k - 1], v.iloc[k - 2]
        if a > b_ > c and c <= v.iloc[k - 14:k - 1].min() and c < v.iloc[k - 8]:
            t = idx[k]
            if last is None or (t - last).n > 12:
                ev.append(t)
                last = t
    return ev


def main():
    doc_hash = hashlib.sha256(__doc__.encode("utf-8")).hexdigest()
    p(f"預先登記 docstring sha256 = {doc_hash}")
    p("=" * 110)
    p("0. 資料")
    mops = mops_last_year()
    cur_a, pri_a, chk_a = rev_cur_prior(["2330"], mops)
    cur_b, pri_b, chk_b = rev_cur_prior(TW_LIST, mops)
    yoy_a, _ = group_yoy(cur_a, pri_a, 3)
    yoy_a1, _ = group_yoy(cur_a, pri_a, 1)
    yoy_b, nb = group_yoy(cur_b, pri_b, 3)
    lvl_a = cur_a["2330"].rolling(3).sum()
    w3 = wsts_worldwide(2)
    yoy_c = yoy(w3).dropna()
    ip, isr, no, tb = fred("IPG3344S"), fred("A34SIS"), fred("A34SNO"), fred("TB3MS")
    IND = {
        "A 台積電營收": dict(yoy=yoy_a, lag=1),
        "B 台半導體不含台積": dict(yoy=yoy_b, lag=1),
        "C WSTS全球銷售": dict(yoy=yoy_c, lag=2),
        "D1 美半導體工業生產": dict(yoy=yoy(ip).dropna(), lag=1),
        "D2 美電子存貨出貨比(反向)": dict(yoy=-yoy(isr).dropna(), lag=2),
        "D3 美電子新訂單": dict(yoy=yoy(no).dropna(), lag=2),
    }
    p("FinMind 對本機 MOPS 的月營收核對（2013 起重疊月數／最大相對差）：")
    for i, n, d in chk_a + chk_b:
        p(f"  {i}: 重疊 {n} 個月, 最大差 {d:.4%}")
    p(f"B 名單每月納入公司數：最少 {int(nb[nb.index >= pd.Period('2003-03', 'M')].min())}、最多 {int(nb.max())}")
    for k, v in IND.items():
        y = v["yoy"]
        y = y[y.index <= END]
        p(f"  {k:<24} 資料月 {y.index.min()} … {y.index.max()}（{len(y)} 個月）公布時差 {v['lag']} 個月；"
          f"2012–2025 年增率>0 的月份比例 {100 * (y[y.index >= pd.Period('2011-11', 'M')] > 0).mean():.0f}%")
    p("  E 南韓半導體出口、台灣外銷訂單（電子產品）：資料拿不到，不納入。")

    SIG = {}
    for k, v in IND.items():
        lv = v["yoy"].copy()
        ac = (v["yoy"] - v["yoy"].shift(3)).dropna()
        for nm, s in (("T1水準", lv), ("T2加速", ac)):
            s = s.copy()
            s.index = s.index + v["lag"]
            SIG[f"{k}|{nm}"] = s[s.index <= END]
    PRIMARY = "A 台積電營收|T2加速"

    # ── 以下才第一次讀價格 ──
    px = load_prices()
    px = px[px.index <= END]
    ret = px.pct_change()
    p(f"價格月底值：SMH {px.SMH.dropna().index.min()}…{px.SMH.dropna().index.max()}，SOX {px.SOX.dropna().index.min()}…，"
      f"NDX {px.NDX.dropna().index.min()}…")
    both = ret[["SMH", "SOX"]].dropna()
    p(f"SMH 與 ^SOX 月報酬相關（2012–2025）：{both.corr().iloc[0, 1]:.3f}；月報酬平均差（SMH 減 SOX，含股息差）{100 * (both.SMH - both.SOX).mean():.2f}%")
    mom = (px.SOX.shift(1) / px.SOX.shift(12) - 1) * 100
    rel = px.SOX / px.NDX
    rs = (rel.shift(1) / rel.shift(12) - 1) * 100
    CTRL = {"F1 SOX 12-1動能": mom, "F2 SOX/NDX 12-1相對強弱": rs}

    def targets(sample):
        if sample == "main":
            return {"SMH": lambda h: fwd(px.SMH, h), "SMH-QQQ": lambda h: fwd(px.SMH, h) - fwd(px.QQQ, h),
                    "SMH-SPY": lambda h: fwd(px.SMH, h) - fwd(px.SPY, h)}
        return {"SOX": lambda h: fwd(px.SOX, h), "SOX-NDX": lambda h: fwd(px.SOX, h) - fwd(px.NDX, h),
                "SOX-GSPC": lambda h: fwd(px.SOX, h) - fwd(px.GSPC, h)}

    # ── 1. 預測回歸 ──
    p()
    p("=" * 110)
    p("1. 預測回歸（主樣本：決策月 2011-12…；x 樣本內標準化，b＝x 每高一個標準差，之後報酬多幾 %；t 為 Newey–West）")
    p("   欄位：全段 b / t / R² / n(獨立樣本數) ｜ 前半 t ｜ 後半 t ｜ 去掉2023–25 t ｜ 加價格對照後的 t")
    all_t, primary = [], {}
    tg = targets("main")
    for h in (1, 3):
        for tn, f in tg.items():
            y = f(h)
            p(f"-- 目標 {tn}，之後 {h} 個月")
            for sn, s in SIG.items():
                lo, hi = P0, END - h
                b, t, r2, n = reg(y, [s], NW_LAGS[h], lo, hi)
                _, t1, _, n1 = reg(y, [s], NW_LAGS[h], lo, SPLIT - h)
                b2, t2, _, n2 = reg(y, [s], NW_LAGS[h], SPLIT, hi)
                _, tx, _, _ = reg(y, [s], NW_LAGS[h], lo, EX_END - h)
                _, tc, _, _ = reg(y, [s, mom, rs], NW_LAGS[h], lo, hi)
                count("主樣本回歸")
                all_t.append(abs(t[0]))
                star = " ←主規格" if (sn == PRIMARY and tn == "SMH-QQQ" and h == 3) else ""
                p(f"   {sn:<34} b {b:+6.2f}  t {t[0]:+5.2f}  R² {100 * r2:4.1f}%  n {n}({n // h}) ｜ {t1[0]:+5.2f} ｜ {t2[0]:+5.2f} ｜ {tx[0]:+5.2f} ｜ {tc[0]:+5.2f}{star}")
                if star:
                    primary = dict(b=b, t=t[0], t1=t1[0], t2=t2[0], tx=tx[0], tc=tc[0], r2=r2, n=n, n1=n1, n2=n2)
            for cn, c in CTRL.items():
                b, t, r2, n = reg(y, [c], NW_LAGS[h], P0, END - h)
                _, t1, _, _ = reg(y, [c], NW_LAGS[h], P0, SPLIT - h)
                _, t2, _, _ = reg(y, [c], NW_LAGS[h], SPLIT, END - h)
                p(f"   [對照] {cn:<27} b {b:+6.2f}  t {t[0]:+5.2f}  R² {100 * r2:4.1f}%  n {n}({n // h}) ｜ {t1[0]:+5.2f} ｜ {t2[0]:+5.2f}")
    p(f"主樣本 72 條回歸：|t| 最大 {max(all_t):.2f}，|t|≥2 的有 {sum(t >= 2 for t in all_t)} 條，|t|≥3 的有 {sum(t >= 3 for t in all_t)} 條"
      f"（純運氣下 72 條約有 {72 * 0.0455:.1f} 條 |t|≥2）")

    p()
    p("1b. 敏感度（事先登記）：A 改用單月年增率 → 之後 3 個月 SMH 減 QQQ")
    y = tg["SMH-QQQ"](3)
    for nm, s0 in (("T1水準", yoy_a1), ("T2加速", (yoy_a1 - yoy_a1.shift(3)).dropna())):
        s = s0.copy()
        s.index = s.index + 1
        b, t, r2, n = reg(y, [s], 6, P0, END - 3)
        _, t1, _, _ = reg(y, [s], 6, P0, SPLIT - 3)
        _, t2, _, _ = reg(y, [s], 6, SPLIT, END - 3)
        count("單月年增率敏感度")
        p(f"   A 單月|{nm}  b {b:+6.2f}  t {t[0]:+5.2f}  R² {100 * r2:4.1f}%  n {n} ｜ 前半 {t1[0]:+5.2f} ｜ 後半 {t2[0]:+5.2f}")

    p()
    p("1c. 長樣本（^SOX 價格指數；決策月 1994-12 起或指標起始月；欄位：全段 t (n) ｜ 2011 以前 t (n) ｜ 2012 以後 t）")
    tgl = targets("long")
    long_t, pre_t = [], []
    for h in (1, 3):
        for tn, f in tgl.items():
            y = f(h)
            p(f"-- 目標 {tn}，之後 {h} 個月")
            for sn, s in SIG.items():
                b, t, r2, n = reg(y, [s], NW_LAGS[h], LONG0, END - h)
                _, tp, _, npre = reg(y, [s], NW_LAGS[h], LONG0, P0 - h)
                _, tq, _, _ = reg(y, [s], NW_LAGS[h], P0, END - h)
                count("長樣本回歸")
                long_t.append(abs(t[0]))
                pre_t.append(abs(tp[0]))
                p(f"   {sn:<34} b {b:+6.2f}  t {t[0]:+5.2f} ({n}) ｜ {tp[0]:+5.2f} ({npre}) ｜ {tq[0]:+5.2f}")
    p(f"長樣本 72 條：全段 |t|≥2 有 {sum(t >= 2 for t in long_t)} 條、≥3 有 {sum(t >= 3 for t in long_t)} 條；"
      f"2011 以前 |t|≥2 有 {sum(t >= 2 for t in pre_t)} 條、≥3 有 {sum(t >= 3 for t in pre_t)} 條")

    # ── 2. 二階導數 ──
    p()
    p("=" * 110)
    p("2. 二階導數說法：年增率谷底／峰頂之後 6、12 個月報酬（事件在公布後的月底才進場；平均% / 中位% / 上漲比例 / 事件數）")

    def ev_stats(events, lag, col, h, lo):
        f = fwd(px[col], h)
        dts = [t + lag for t in events]
        vals = [f.get(d, np.nan) for d in dts if d >= lo]
        vals = [v for v in vals if not np.isnan(v)]
        if not vals:
            return "  無事件", 0, np.nan
        return f"{np.mean(vals):+6.1f} / {np.median(vals):+6.1f} / {100 * np.mean(np.array(vals) > 0):3.0f}% / n={len(vals)}", len(vals), np.mean(vals)

    def uncond(col, h, lo):
        f = fwd(px[col], h)
        f = f[f.index >= lo].dropna()
        return f"{f.mean():+6.1f} / {f.median():+6.1f} / {100 * (f > 0).mean():3.0f}% / n={len(f)}"

    EV = {}
    for k, v in IND.items():
        y = v["yoy"][v["yoy"].index <= END]
        EV[k] = dict(trough=turning_points(y, "trough"), peak=turning_points(y, "peak"), lag=v["lag"])
    for col, lo, lab in (("SMH", P0, "SMH 主樣本（2011-12 起）"), ("SOX", pd.Period("1994-05", "M"), "^SOX 長樣本（1994-05 起，不含股息）")):
        for h in (6, 12):
            p(f"-- {lab}，之後 {h} 個月；全部月份：{uncond(col, h, lo)}")
            for k, e in EV.items():
                a, _, _ = ev_stats(e["trough"], e["lag"], col, h, lo)
                b_, _, _ = ev_stats(e["peak"], e["lag"], col, h, lo)
                count("轉折事件比較")
                p(f"   {k:<24} 谷底後 {a:<34} ｜ 峰頂後 {b_}")
    p("-- 事件判定月（資料月；真實極值月＝再往前 2 個月）")
    for k, e in EV.items():
        p(f"   {k:<24} 谷底: {' '.join(str(t) for t in e['trough'])}")
        p(f"   {'':<24} 峰頂: {' '.join(str(t) for t in e['peak'])}")
    p("-- 對照：營收『水準』見底（同一套規則，用三個月水準）之後 ^SOX 報酬")
    w3c = w3[w3.index <= END]
    for nm, lv, lag in (("C WSTS 3MMA 水準", w3c, 2), ("A 台積電三個月營收水準", lvl_a[lvl_a.index <= END], 1)):
        tl = turning_points(lv, "trough")
        for h in (6, 12):
            a, _, _ = ev_stats(tl, lag, "SOX", h, pd.Period("1994-05", "M"))
            count("水準見底對照")
            p(f"   {nm:<24} 之後 {h:>2} 個月 {a}")
        p(f"   {'':<24} 水準谷底判定月: {' '.join(str(t) for t in tl)}")
    p("-- 描述（用到事後資訊）：^SOX 月收盤在『年增率真實谷底月』前後 12 個月內的最低點，相對谷底月的位置（負＝股價先落底）")
    for k in ("C WSTS全球銷售", "A 台積電營收"):
        offs = []
        for t in EV[k]["trough"]:
            t0 = t - 2
            w = px.SOX[(px.SOX.index >= t0 - 12) & (px.SOX.index <= t0 + 12)].dropna()
            if len(w) >= 20:
                offs.append((str(t0), (w.idxmin() - t0).n))
        p(f"   {k:<18} " + "  ".join(f"{a}:{o:+d}" for a, o in offs)
          + (f"   → 中位 {np.median([o for _, o in offs]):+.0f} 個月, 股價先落底 {sum(o < 0 for _, o in offs)}/{len(offs)}" if offs else ""))

    # ── 3. 規則 ──
    p()
    p("=" * 110)
    p("3. 簡單規則（每月底決策；訊號>0 → 下月抱 SMH，否則抱避風港）")
    rm = ret[(ret.index > P0) & (ret.index <= END)]
    tbr = (tb / 1200).reindex(rm.index).ffill()
    SEG = {"全段2012–25": (P0 + 1, END), "前半2012–18": (P0 + 1, SPLIT), "後半2019–25": (SPLIT + 1, END), "去掉2023–25": (P0 + 1, EX_END)}

    def seg_line(r):
        out = []
        for a, b_ in SEG.values():
            c, d, cal = perf(r[(r.index >= a) & (r.index <= b_)])
            out.append(f"{c:5.1f}/{d:6.1f}/{cal:4.2f}")
        return " ｜ ".join(out)

    p("   每段欄位：CAGR% / 最大回撤% / Calmar。分段：" + " ｜ ".join(SEG.keys()))
    BH = {"買進持有 SMH": rm.SMH, "買進持有 QQQ": rm.QQQ, "SMH/QQQ 各半(月平衡)": 0.5 * rm.SMH + 0.5 * rm.QQQ, "買進持有 SPY": rm.SPY, "國庫券": tbr}
    for k, r in BH.items():
        p(f"   {k:<40} {seg_line(r)}")
    bh_smh = {sg: perf(rm.SMH[(rm.index >= a) & (rm.index <= b_)])[0] for sg, (a, b_) in SEG.items()}
    rule_res = {}

    def run_rule(name, s, alt_name, alt, tag):
        st = (s.reindex(rm.index - 1) > 0).astype(float)
        st[s.reindex(rm.index - 1).isna().values] = 1.0   # 缺值＝維持抱 SMH（主樣本內不應發生）
        st.index = rm.index
        r = st * rm.SMH + (1 - st) * alt
        sw = int((st.diff().abs() > 0).sum())
        yrs = len(rm) / 12
        beats = []
        for sg, (a, b_) in SEG.items():
            beats.append(perf(r[(r.index >= a) & (r.index <= b_)])[0] - bh_smh[sg])
        sw1 = int((st[st.index <= SPLIT].diff().abs() > 0).sum())
        sw2 = sw - sw1
        count(tag)
        p(f"   {name + '→' + alt_name:<40} {seg_line(r)} ｜ 切換 {sw:>3} 次({sw / yrs:.1f}/年; 前半 {sw1} 後半 {sw2}) 抱SMH {100 * st.mean():3.0f}% ｜ 對SMH的CAGR差 "
          + " ".join(f"{x:+5.1f}" for x in beats))
        rule_res[(name, alt_name)] = dict(beats=beats, sw_per_yr=sw / yrs, st=st, r=r)

    for alt_name, alt in (("QQQ", rm.QQQ), ("國庫券", tbr)):
        p(f"-- 避風港＝{alt_name}")
        for sn, s in SIG.items():
            run_rule(sn, s, alt_name, alt, "主樣本規則")
        for cn, c in CTRL.items():
            run_rule("[對照] " + cn, c, alt_name, alt, "價格對照規則")
    nbeat = sum(1 for (n_, a_), v in rule_res.items() if not n_.startswith("[對照]") and v["beats"][1] > 0 and v["beats"][2] > 0)
    p(f"24 條候選規則中，前半、後半 CAGR 都贏買進持有 SMH 的有 {nbeat} 條")

    p()
    p("3b. 長樣本規則（^SOX 對 ^NDX，價格指數；決策月 1994-12 起或指標起始；CAGR%/最大回撤%/Calmar ｜ 同期買進持有 SOX ｜ 2011 以前兩者 CAGR）")
    rl = ret[(ret.index > LONG0) & (ret.index <= END)]
    for sn, s in SIG.items():
        x = s.reindex(rl.index - 1)
        x.index = rl.index
        ok = x.notna()
        ok = ok & (ok.cumsum() > 0)
        rr = rl[ok.values]
        st = (x[ok.values] > 0).astype(float)
        r = st * rr.SOX + (1 - st) * rr.NDX
        c, d, cal = perf(r)
        c0, d0, cal0 = perf(rr.SOX)
        pre = r.index <= P0
        cp = perf(r[pre])[0] if pre.sum() > 24 else np.nan
        cp0 = perf(rr.SOX[pre])[0] if pre.sum() > 24 else np.nan
        sw = int((st.diff().abs() > 0).sum())
        count("長樣本規則")
        p(f"   {sn:<34} {rr.index.min()}起 {c:5.1f}/{d:6.1f}/{cal:4.2f} ｜ SOX {c0:5.1f}/{d0:6.1f}/{cal0:4.2f} ｜ 2011前 {cp:5.1f} vs {cp0:5.1f} ｜ 切換 {sw / (len(rr) / 12):.1f}/年")

    # ── 4. 反方向 ──
    p()
    p("=" * 110)
    p("4. 反方向：股價是否領先指標")
    p("   交叉相關：^SOX 12 個月漲幅(月 t) 對 指標年增率(資料月 t+k)。k*>0＝股價領先 k* 個月。欄位：長樣本 k*/相關/k=0 相關 ｜ 2012 起 k*/相關/k=0 相關")
    sox_yoy = yoy(px.SOX).dropna()
    for k, v in IND.items():
        y = v["yoy"][v["yoy"].index <= END]
        outs = []
        for lo in (pd.Period("1995-05", "M"), pd.Period("2012-01", "M")):
            cs = {}
            for kk in range(-12, 13):
                yy = y.copy()
                yy.index = yy.index - kk
                j = pd.concat([sox_yoy[sox_yoy.index >= lo], yy], axis=1).dropna()
                cs[kk] = j.corr().iloc[0, 1] if len(j) > 36 else np.nan
            ks = max(cs, key=lambda q: -9 if np.isnan(cs[q]) else cs[q])
            outs.append(f"k*={ks:+d} / {cs[ks]:.2f} / {cs[0]:.2f}")
        count("反方向交叉相關")
        p(f"   {k:<24} {outs[0]} ｜ {outs[1]}")
    p("   對稱回歸（不加公布時差；NW 12 階）：正向＝SOX 未來6月報酬 對 指標年增率過去6月變化；反向＝指標年增率未來6月變化 對 SOX 過去6月報酬")
    sox_f6, sox_p6 = fwd(px.SOX, 6), (px.SOX / px.SOX.shift(6) - 1) * 100
    for k, v in IND.items():
        y = v["yoy"][v["yoy"].index <= END]
        d_past, d_fut = y - y.shift(6), y.shift(-6) - y
        res = []
        for lo in (pd.Period("1995-01", "M"), pd.Period("2012-01", "M")):
            _, tf, r2f, nf = reg(sox_f6, [d_past], 12, lo, END - 6)
            _, tr_, r2r, nr = reg(d_fut, [sox_p6], 12, lo, END - 6)
            res.append(f"正向 t {tf[0]:+5.2f} R² {100 * r2f:4.1f}% ／ 反向 t {tr_[0]:+5.2f} R² {100 * r2r:4.1f}% (n={nf})")
        count("反方向回歸", 2)
        p(f"   {k:<24} 長樣本 {res[0]} ｜ 2012起 {res[1]}")

    # ── 事後探索（首跑看過結果之後才加；不算入門檻判定）──
    p()
    p("=" * 110)
    p("事後探索（首跑之後才加的三個補充數字；不算入門檻、不拿來提名）")
    p("P1. 谷底後對峰頂後的報酬差，Welch t（兩組樣本數都很小，只看量級）")

    def ev_vals(events, lag, col, h, lo):
        f = fwd(px[col], h)
        v = [f.get(t + lag, np.nan) for t in events if t + lag >= lo]
        return np.array([x for x in v if not np.isnan(x)])

    for k in ("A 台積電營收", "C WSTS全球銷售"):
        for col, lo in (("SMH", P0), ("SOX", pd.Period("1994-05", "M"))):
            for h in (6, 12):
                a, b_ = ev_vals(EV[k]["trough"], EV[k]["lag"], col, h, lo), ev_vals(EV[k]["peak"], EV[k]["lag"], col, h, lo)
                if len(a) > 1 and len(b_) > 1:
                    wt = (a.mean() - b_.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b_.var(ddof=1) / len(b_))
                    count("事後探索")
                    p(f"   {k:<16} {col} {h:>2} 個月：谷底後 {a.mean():+6.1f}% (n={len(a)}) 減 峰頂後 {b_.mean():+6.1f}% (n={len(b_)}) = {a.mean() - b_.mean():+6.1f}，t {wt:+.2f}")
    p("P2. 只看 2023–2025：主規則與買進持有（CAGR% / 最大回撤%）")
    w = (rm.index >= pd.Period("2023-01", "M"))
    prr = rule_res[(PRIMARY, "QQQ")]
    for nm, r in (("主規則 A-T2→QQQ", prr["r"]), ("買進持有 SMH", rm.SMH), ("買進持有 QQQ", rm.QQQ)):
        c, d, _ = perf(r[w])
        p(f"   {nm:<18} {c:5.1f} / {d:6.1f}")
    p(f"   主規則在 2023–2025 抱 SMH 的月份比例 {100 * prr['st'][w].mean():.0f}%")
    count("事後探索")
    p("P3. 避風港＝國庫券時 Calmar 看起來較高的兩條，對照『固定比例、同樣平均持股』的組合（每月再平衡）")
    for sn in ("B 台半導體不含台積|T2加速", "C WSTS全球銷售|T2加速"):
        rr_ = rule_res[(sn, "國庫券")]
        wgt = rr_["st"].mean()
        static = wgt * rm.SMH + (1 - wgt) * tbr
        c, d, cal = perf(rr_["r"])
        c0, d0, cal0 = perf(static)
        count("事後探索")
        p(f"   {sn:<28} 規則 {c:5.1f}/{d:6.1f}/{cal:4.2f} ｜ 固定 {100 * wgt:.0f}% SMH＋國庫券 {c0:5.1f}/{d0:6.1f}/{cal0:4.2f}")
    p("   （24 條裡事後挑 2 條，本身就是挑櫻桃；只為了回答『回撤變小是不是只因為持股少』。）")

    # ── 5. 判定 ──
    p()
    p("=" * 110)
    p("5. 對照事先定死的門檻（主規格：A 台積電營收 T2 加速 → 之後 3 個月 SMH 減 QQQ）")
    c1 = abs(primary["t"]) >= 3.0 and np.sign(primary["t1"]) == np.sign(primary["t"]) == np.sign(primary["t2"])
    pr = rule_res[(PRIMARY, "QQQ")]
    c2 = pr["beats"][1] > 0 and pr["beats"][2] > 0 and pr["sw_per_yr"] <= 3.0
    c3 = abs(primary["tc"]) >= 2.0
    p(f"   (1) 全段 t = {primary['t']:+.2f}（需 |t|≥3.0），前半 t {primary['t1']:+.2f}、後半 t {primary['t2']:+.2f}（需同號）；"
      f"n={primary['n']}、獨立樣本約 {primary['n'] // 3}、R² {100 * primary['r2']:.1f}% → {'過' if c1 else '不過'}")
    p(f"   (2) 規則對買進持有 SMH 的 CAGR 差：前半 {pr['beats'][1]:+.1f}、後半 {pr['beats'][2]:+.1f} 個百分點（需都 >0）；"
      f"每年切換 {pr['sw_per_yr']:.1f} 次（需 ≤3）→ {'過' if c2 else '不過'}")
    p(f"   (3) 加入價格對照後 t = {primary['tc']:+.2f}（需 |t|≥2.0）→ {'過' if c3 else '不過'}")
    p(f"   判定：{'過門檻（僅為提名，不是證實）' if (c1 and c2 and c3) else '未過門檻'}")
    total = sum(N_VARIANTS.values())
    p()
    p("   變體數：" + "、".join(f"{k} {v}" for k, v in N_VARIANTS.items()) + f" → 合計 {total}")
    rng = np.random.default_rng(20261122)
    for n in (12, 72, total - N_VARIANTS.get("事後探索", 0), total):
        bonf = NormalDist().inv_cdf(1 - 0.025 / n)
        emax = np.abs(rng.standard_normal((20000, n))).max(axis=1)
        p(f"   運氣線 N={n:>3}：Bonferroni 5% 雙尾 t ≥ {bonf:.2f}；N 個獨立檢定下最大 |t| 的期望值 {emax.mean():.2f}、95 百分位 {np.quantile(emax, 0.95):.2f}")
    p("   （各變體彼此高度相關，獨立檢定數比 N 少，上面的運氣線偏嚴；但 14 年只有 3–4 個循環，有效樣本本來就很小。）")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write("\n".join(_lines) + "\n")


if __name__ == "__main__":
    main()
