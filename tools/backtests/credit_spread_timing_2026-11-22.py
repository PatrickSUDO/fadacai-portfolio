"""credit_spread_timing_2026-11-22.py — 信用利差（公司債比公債多付的利息）能不能拿來做美股指數的擇時或調整部位

起因（2026-11-22）：儀表板早就有「信用利差快速擴大」燈號（tools/fetch_leading.py 的 credit_velocity，
FRED BAMLH0A0HYM2；5 日 +25bp 或 20 日 +50bp 亮「widening_fast」，門檻在 research/leading-config.json），但從沒回測過。
投資人條件：不開槓桿、持有期不短於一個月、討厭頻繁進出、零手續費零資本利得稅、目標是贏過買進持有 VOO／QQQ／SMH。

================ 事前登記（跑任何數字之前寫定；之後不加規則，要加就標「事後探索」另列） ================

資料
- 高收益債利差 BAMLH0A0HYM2：先查 FRED 今天實際給多長；若只有約三年，燈號本身無法用自己的資料驗證，改用長歷史替代品。
- 主替代品 = BAA10Y（穆迪 Baa 級公司債殖利率 − 10 年公債，日資料 1986→）。Baa 是投資級最低一階，對壞消息的反應比高收益債鈍。
  副替代品 = Baa−Aaa（BAA10Y − AAA10Y），只在「鄰近參數檢查」當穩健性對照，不當候選規則。
- 門檻換算（寫死的做法）：在兩者重疊期（到 2025-12-31），算高收益債 5 日變化 < 25bp 的天數比例 q5、20 日變化 < 50bp 的比例 q20；
  替代品門檻 a = 替代品 5 日變化的 q5 分位數、b = 20 日變化的 q20 分位數，四捨五入到 1bp，最低 1bp（＝讓亮燈頻率在重疊期相同）。
  另印「標準差比例換算」當對照，但不用它。
- 價格：yfinance 還原收盤。SPY 1994-01-03→、QQQ 2000-01-03→、SMH 2013-01-02→（SMH 只用 2012 以後的價；2012 當暖機）。全部結束於 2025-12-31。
- 現金那一腿拿 3 個月國庫券利率（FRED DTB3 ÷ 100 ÷ 252）。交易成本 0（零手續費；買賣價差沒算，用來回次數自己衡量）。
- 時間差：FRED 的利差晚一個營業日公布（d 日的值 d+1 日才知道）；t 日收盤知道的訊號在 t+1 日收盤成交，t+2 日起的報酬才受影響。
  所以利差 d 日的值最早影響 d+3 日的報酬。價格類條件（200 日線、VIX）沒有公布延遲，只有「隔日收盤成交」那一天。對照組也用同一個成交延遲。
- 最短停留：任何一次切換之後 21 個交易日內不再切換（進、出兩邊都算），對應「持有期不短於一個月」。

訊號定義（k = 當天已公布的替代利差，單位 bp）
- 快速擴大 W：k − k[5 日前] ≥ a 或 k − k[20 日前] ≥ b（照儀表板程式的寫法）。
- 收斂中 N：k < 自己的 20 日平均。
- 位階 P：k 在過去 252 個交易日（含當天）的百分位排名。
- 價格條件用「被交易的那檔」自己的價：200 日線；離 252 日最高收盤 ≤5%（近高點）或 ≥10%（已跌一段）；VIX 期限結構倒掛 = ^VIX > ^VIX3M（2007-01-03→）。

候選規則（共 14 條交易規則 + 1 個事件研究 = 15 個變體；上限 24）
 第 1 組 儀表板原規則（全出／全進）
  R1a  W 亮 → 出場；滿 21 日且 W 已熄 → 回場
  R1b  W 亮 → 出場；滿 63 日且 W 已熄 → 回場
  R1c  W 亮 → 出場；滿 21 日且利差跌回 20 日平均之下（N）→ 回場
 第 2 組 位階規則（全出／全進）
  R2a  P > 80% → 出場；P ≤ 80% → 回場
  R2b  P > 90% → 出場；P ≤ 90% → 回場
 第 3 組 壓低假警報（全出／全進；回場條件一律同 R1c）
  R3a  W 亮「而且」價格在 200 日線下 → 出場
  R3b  W 亮「而且」VIX 期限結構倒掛 → 出場（視窗 2007-01-03→）
  R3c  W 亮「而且」價格離一年高點不到 5%（提早警告版）→ 出場
  R3d  W 亮「而且」價格已從一年高點跌 10% 以上（晚到版）→ 出場
 第 4 組 只調部位（訊號亮時 100% → 50%，其餘放國庫券；永不超過 100%）
  S1c（R1c 的訊號）、S2a（R2a）、S2b（R2b）、S3a（R3a）
 第 5 組 反向讀法
  R5a  P > 90%「而且」還沒開始收斂 → 出場；一開始收斂（N）→ 回場（＝高利差但已回頭時抱滿）
  R5b  事件研究（不是交易規則）：P > 90% 且當天利差剛跌破 20 日平均（21 日內第一次）之後 63／126／252 日報酬 vs 任意日；
       同視窗對照「VIX 收盤首次站上 30」。

對照組（不算變體）：買進持有；200 日線（收盤在線下出場，每日檢查）；200 日線加 21 日最短停留；
 波動目標（目標 20%、20 日實現波動、週五決定、變動 <10% 不動、不開槓桿；同 vol_target_robustness_2026-11-20.py 但成本 0、成交延遲同上）。

每條規則 × SPY／QQQ／SMH 報：年化報酬、最大回撤、Calmar（年化 ÷ 最大回撤）、不在場（或減碼）時間比例、來回次數、對買進持有的差。
前後半：各標的視窗依交易日數對半切；策略全期連續跑，再把日報酬切兩半各算一次。

過關線（寫死）
 甲（全出／全進規則）：SPY 與 QQQ 的前半、後半，年化報酬「全部」高於買進持有，且兩檔每年來回 ≤ 2 次。
 乙（只調部位規則）：SPY 與 QQQ 的前半、後半，Calmar「全部」≥ 買進持有的 1.2 倍，且年化報酬「全部」少賺不超過 1 個百分點。
 SMH 只報不計入過關線。全出／全進規則也會順手印乙的欄位，但只當參考，判定只看甲。

警報本身的事件表（W 首次亮起 = 當天亮、前 21 個交易日都沒亮）
 真警報 = 警報日收盤之後 63 個交易日內，指數最低收盤比警報日收盤再低 ≥10%；否則是假警報。
 報：警報數、真／假數、任意日的同一機率（基準率）、真警報離谷底的交易日數中位、警報當下離一年高點多遠（看是領先還是同步）、
 假警報之後 21／63 日指數平均報酬（＝出場會少賺的）。另按第 3 組的四個過濾條件各列一次。
 高收益債自己的短歷史也用儀表板原門檻列一次（樣本極小，只當描述）。

最佳規則的檢查（選法寫死）
 最佳全出／全進 = R1a–R3d、R5a 之中「SPY 與 QQQ 全期年化報酬差的平均」最高者；最佳只調部位 = S 組之中「SPY 與 QQQ 全期 Calmar 倍數的平均」最高者。
 鄰近參數：W 類規則 = 門檻 ×0.5／×0.75／×1／×1.5／×2 × 最短出場 21／63 日；位階類規則 = 百分位 70／80／90／95 × 最短出場 21／63 日。
 另用副替代品 Baa−Aaa（門檻同法重算）各跑一次。這些格子只看穩不穩，不當候選、不計入 15 個變體。
 再報：最佳規則不在場的日子裡，200 日線規則同時也不在場的比例（看信用利差有沒有說出價格沒說的事）。

用法：python3 tools/backtests/credit_spread_timing_2026-11-22.py > tools/backtests/data/credit_spread_timing_2026-11-22.out.txt
（FRED 與價格會快取在 tools/backtests/data/credit_spread_timing_2026-11-22/；刪掉資料夾即重抓。FRED 免金鑰 CSV 連不上時改走 API，金鑰讀環境變數或 .env，不會印出。）

================ 首跑之後的更動（2026-11-22；上面的登記一字未改） ================
- 顯示修正（不影響任何判定）：QQQ 前半（2000→2012）買進持有年化為負，Calmar 也是負的，「幾倍」沒有意義。
  買進持有 Calmar ≤ 0 時改印兩邊的原值；乙線在這種格子改成「規則的 Calmar 高於買進持有就算過」（比原式寬，判定仍是 0 條過）。
- 事後探索（看過結果才加，另列在【九】，不計入過關判定、不計入 15 個變體）：
  主測試的弱點是替代品不夠像（重疊期 7 次高收益債警報只有 3 次在 BAA10Y 上也出現）。
  所以另用高收益債 ETF 的價格反推一個利差代理：HYG 與 IEI（3–7 年公債）的還原報酬差，N 日累計取負號（＝高收益債輸給公債多少，單位 bp）。
  門檻同樣用重疊期亮燈頻率對齊法換算；ETF 價格當天收盤就知道，所以只有「隔日收盤成交」一天延遲。視窗 2007-07-02→2025-12-31。
  只重跑 3 條：R1c（儀表板原規則）、R3a、S3a（首跑選出的兩條最佳），外加同一張事件表。
- 首跑後補了一列對照「200 日線下減半（含 21 日最短停留）」放在【八】，只為了回答「利差比價格多說了什麼」；它不是候選。
- 首跑結論：14 條交易規則過關 0 條；鄰近參數 20 格 + 換副替代品 2 次也是 0；事後探索 3 條同樣不過。
  警報命中率與任意日相同（SPY 13% 對 14.5%）；加上「價格在 200 日線下」命中率升到 29%，但那時指數中位數已離高點約 10%。
  FRED 的高收益債利差只剩 2023-11-21 之後，儀表板燈號本身無法驗證。細節見 research/credit-spread-timing-2026-11-22.md（不入庫）。
"""
import io, json, os, sys, urllib.parse, urllib.request, warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'tools' / 'backtests' / 'data' / 'credit_spread_timing_2026-11-22'
DATA.mkdir(parents=True, exist_ok=True)
END = '2025-12-31'
WINDOW = {'SPY': '1994-01-03', 'QQQ': '2000-01-03', 'SMH': '2013-01-02'}
VIXTERM_START = '2007-01-03'
HY_FAST_5D, HY_FAST_20D = 25, 50          # research/leading-config.json gauges_thresholds.credit
MINHOLD = 21


# ── 資料 ─────────────────────────────────────────────────────────────────────
def _fred_key():
    k = os.environ.get('FRED_API_KEY', '').strip()
    if k:
        return k
    env = ROOT / '.env'
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith('FRED_API_KEY') and '=' in line:
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    return ''


def fred(sid):
    f = DATA / f'fred_{sid}.csv'
    if f.exists():
        return pd.read_csv(f, index_col=0, parse_dates=True).iloc[:, 0]
    s = None
    try:
        req = urllib.request.Request(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = pd.read_csv(io.StringIO(r.read().decode()), index_col=0, parse_dates=True)
        s = pd.to_numeric(d.iloc[:, 0], errors='coerce').dropna()
    except Exception:
        s = None
    if s is None or s.empty:
        key = _fred_key()
        if not key:
            raise RuntimeError(f'FRED {sid}：CSV 端點連不上，也沒有 FRED_API_KEY')
        q = urllib.parse.urlencode({'series_id': sid, 'api_key': key, 'file_type': 'json', 'observation_start': '1980-01-01'})
        try:
            with urllib.request.urlopen(f'https://api.stlouisfed.org/fred/series/observations?{q}', timeout=45) as r:
                obs = json.load(r)['observations']
        except Exception as e:  # 不把含金鑰的網址帶進錯誤訊息
            raise RuntimeError(f'FRED {sid} 取不到（{type(e).__name__}）') from None
        s = pd.Series({pd.Timestamp(o['date']): float(o['value']) for o in obs if o['value'] not in ('.', '')})
    s.name = sid
    s.index.name = 'date'
    s.to_csv(f)
    return s


def prices():
    f = DATA / 'px.csv'
    if f.exists():
        return pd.read_csv(f, index_col=0, parse_dates=True)
    import yfinance as yf
    raw = yf.download(['SPY', 'QQQ', 'SMH', '^VIX', '^VIX3M'], period='max', progress=False, auto_adjust=True)['Close']
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    raw.to_csv(f)
    return raw


HY_ALL = fred('BAMLH0A0HYM2')
BAA = fred('BAA10Y').loc[:END]
AAA = fred('AAA10Y').loc[:END]
DTB3 = fred('DTB3').loc[:END]
HY = HY_ALL.loc[:END]
PX = prices().loc[:END]
PX.loc[:'2011-12-31', 'SMH'] = np.nan            # SMH 只用 2012 以後
CAL = PX['SPY'].dropna().index
RF = (DTB3 / 100 / 252).reindex(DTB3.index.union(CAL)).ffill().reindex(CAL).fillna(0.0)
BAA_AAA = (BAA - AAA).dropna()


def known(s):
    """換到股市交易日曆，再延後一天（FRED 晚一個營業日公布）。單位 bp。"""
    return (s.reindex(s.index.union(CAL)).ffill().reindex(CAL).shift(1) * 100).round(1)


def match_thresholds(sub):
    """重疊期內讓替代品亮燈頻率等於高收益債原門檻的亮燈頻率。"""
    j = pd.concat([HY, sub], axis=1, keys=['hy', 'sub']).dropna()
    out = {}
    for n, th in ((5, HY_FAST_5D), (20, HY_FAST_20D)):
        dh = ((j['hy'] - j['hy'].shift(n)) * 100).dropna()
        ds = ((j['sub'] - j['sub'].shift(n)) * 100).dropna()
        q = float((dh < th).mean())
        out[n] = dict(q=q, thr=max(1.0, float(np.round(np.quantile(ds, q)))), sd_ratio=float(dh.std() / ds.std()),
                      corr=float(dh.corr(ds)), beta=float(np.polyfit(ds.reindex(dh.index).to_numpy(), dh.to_numpy(), 1)[0]))
    out['level_corr'] = float(j['hy'].corr(j['sub']))
    out['n'] = len(j)
    out['span'] = (j.index[0].date(), j.index[-1].date())
    return out


def wf(k, a, b):
    d5 = (k - k.shift(5)).round(1)
    d20 = (k - k.shift(20)).round(1)
    return ((d5 >= a) | (d20 >= b)) & d20.notna()


# ── 規則引擎 ─────────────────────────────────────────────────────────────────
def machine(out_c, in_c, min_out=MINHOLD, min_in=MINHOLD):
    o = out_c.fillna(False).to_numpy(dtype=bool)
    i = in_c.fillna(False).to_numpy(dtype=bool)
    pos = np.ones(len(o))
    st, since = 1, 10 ** 9
    for t in range(len(o)):
        if st == 1 and o[t] and since >= min_in:
            st, since = 0, 0
        elif st == 0 and i[t] and since >= min_out:
            st, since = 1, 0
        else:
            since += 1
        pos[t] = st
    return pd.Series(pos, index=out_c.index)


class Cond:
    """某檔標的在自己交易日上的全部條件。scale 縮放 W 的門檻；series 選利差來源。"""

    def __init__(self, sym, k_cal, a, b, scale=1.0):
        p = PX[sym].dropna()
        self.p = p
        self.idx = p.index
        k = k_cal
        self.W = wf(k, a * scale, b * scale).reindex(p.index)
        self.N = (k < k.rolling(20).mean()).reindex(p.index)
        self.P = k.rolling(252).rank(pct=True).reindex(p.index)
        self.below = p < p.rolling(200).mean()
        hi = p.rolling(252, min_periods=200).max()
        self.near = p >= 0.95 * hi
        self.late = p <= 0.90 * hi
        self.dd_hi = p / hi - 1
        self.inv = (PX['^VIX'] > PX['^VIX3M']).reindex(p.index)


RULES = [  # (代號, 說明, 類型 io=全出全進 / sz=減半, 百分位預設)
    ('R1a', 'W→出；滿21日且W熄→回', 'io', None),
    ('R1b', 'W→出；滿63日且W熄→回', 'io', None),
    ('R1c', 'W→出；滿21日且利差<20日均→回', 'io', None),
    ('R2a', '位階>80%→出', 'io', 0.80),
    ('R2b', '位階>90%→出', 'io', 0.90),
    ('R3a', 'W且價<200日線→出', 'io', None),
    ('R3b', 'W且VIX期限倒掛→出（2007→）', 'io', None),
    ('R3c', 'W且離高點<5%→出（早）', 'io', None),
    ('R3d', 'W且已跌≥10%→出（晚）', 'io', None),
    ('S1c', 'R1c 訊號→減半', 'sz', None),
    ('S2a', 'R2a 訊號→減半', 'sz', 0.80),
    ('S2b', 'R2b 訊號→減半', 'sz', 0.90),
    ('S3a', 'R3a 訊號→減半', 'sz', None),
    ('R5a', '位階>90%且未收斂→出；收斂→回', 'io', 0.90),
]
BASE = {'S1c': 'R1c', 'S2a': 'R2a', 'S2b': 'R2b', 'S3a': 'R3a'}
KIND = {r[0]: r[2] for r in RULES}
PCT0 = {r[0]: r[3] for r in RULES}
LEVEL_RULES = {'R2a', 'R2b', 'S2a', 'S2b', 'R5a'}


def rule_pos(name, c, pct=None, min_out=None):
    base = BASE.get(name, name)
    pct = PCT0[name] if pct is None else pct
    mo = min_out if min_out is not None else (63 if base == 'R1b' else MINHOLD)
    if base in ('R1a', 'R1b'):
        return machine(c.W, ~c.W.fillna(True), mo)
    if base == 'R1c':
        return machine(c.W, c.N, mo)
    if base in ('R2a', 'R2b'):
        return machine(c.P > pct, c.P <= pct, mo)
    if base == 'R3a':
        return machine(c.W & c.below, c.N, mo)
    if base == 'R3b':
        return machine(c.W & c.inv, c.N, mo)
    if base == 'R3c':
        return machine(c.W & c.near, c.N, mo)
    if base == 'R3d':
        return machine(c.W & c.late, c.N, mo)
    if base == 'R5a':
        return machine((c.P > pct) & ~c.N.fillna(False), c.N, mo)
    raise KeyError(name)


def met(x):
    eq = np.cumprod(1 + x)
    c = eq[-1] ** (252 / len(x)) - 1
    m = (eq / np.maximum.accumulate(eq) - 1).min()
    return c, m, (c / abs(m) if m < 0 else np.nan)


def evaluate(sym, pos, floor, start, lag=2):
    """pos = t 日收盤的決定（1 在場／0 訊號亮）；lag=2 → t+1 收盤成交、t+2 起生效。"""
    r = PX[sym].dropna().pct_change()
    held = pos.shift(lag).fillna(1.0)
    e = 1.0 - (1.0 - floor) * (1.0 - held)
    w = r.index >= pd.Timestamp(start)
    r_, e_, rf_ = r[w].to_numpy(), e.reindex(r.index)[w].to_numpy(), RF.reindex(r.index)[w].to_numpy()
    x = e_ * r_ + (1 - e_) * rf_
    n = len(x)
    h = n // 2
    full, h1, h2 = met(x), met(x[:h]), met(x[h:])
    b, b1, b2 = met(r_), met(r_[:h]), met(r_[h:])
    ebar = e_.mean()
    fx = met(ebar * r_ + (1 - ebar) * rf_)
    trips = int(((e_[1:] < e_[:-1] - 1e-9) & (e_[:-1] > 1 - 1e-9)).sum()) if floor is not None else 0
    return dict(full=full, h1=h1, h2=h2, bh=b, bh1=b1, bh2=b2, out=float((e_ < 1 - 1e-9).mean()), ebar=float(ebar), trips=trips,
                tpy=trips / (n / 252), fixed=fx, n=n, split=r.index[w][h].date(), start=r.index[w][0].date(), e=pd.Series(e_, index=r.index[w]))


def vol_target(sym, target=0.20, lb=20, thr=0.10):
    p = PX[sym].dropna()
    ret = p.pct_change().fillna(0)
    vol = ret.rolling(lb).std() * np.sqrt(252)
    rw = (target / vol).clip(upper=1.0).fillna(1.0)
    wk = rw.where(rw.index.weekday == 4).ffill().fillna(1.0)
    held = [1.0]
    for v in wk.iloc[1:]:
        held.append(v if abs(v - held[-1]) >= thr else held[-1])
    return pd.Series(held, index=ret.index)


def evaluate_expo(sym, e_dec, start, lag=2):
    """給連續曝險（波動目標）用的版本。"""
    r = PX[sym].dropna().pct_change()
    e = e_dec.shift(lag).fillna(1.0)
    w = r.index >= pd.Timestamp(start)
    r_, e_, rf_ = r[w].to_numpy(), e.reindex(r.index)[w].to_numpy(), RF.reindex(r.index)[w].to_numpy()
    x = e_ * r_ + (1 - e_) * rf_
    n = len(x)
    h = n // 2
    ebar = e_.mean()
    return dict(full=met(x), h1=met(x[:h]), h2=met(x[h:]), bh=met(r_), bh1=met(r_[:h]), bh2=met(r_[h:]), out=float((e_ < 1 - 1e-9).mean()),
                ebar=float(ebar), trips=int((np.abs(np.diff(e_)) > 1e-9).sum()), tpy=float((np.abs(np.diff(e_)) > 1e-9).sum() / (n / 252)),
                fixed=met(ebar * r_ + (1 - ebar) * rf_), n=n, e=pd.Series(e_, index=r.index[w]))


def pass_a(rs, rq):
    ok = all(v[h][0] > v['bh' + h[-1]][0] for v in (rs, rq) for h in ('h1', 'h2'))
    return ok and rs['tpy'] <= 2 and rq['tpy'] <= 2


def _cal_ok(c, b):
    return c >= 1.2 * b if b > 0 else c > b      # 買進持有 Calmar ≤ 0 時：比它高就算過（首跑後補的澄清）


def cx(c, b):
    return f'×{c / b:.2f}' if b > 0 else f'{c:+.2f}對{b:+.2f}'


def pass_b(rs, rq):
    cal = all(_cal_ok(v[h][2], v['bh' + h[-1]][2]) for v in (rs, rq) for h in ('h1', 'h2'))
    ret = all(v[h][0] >= v['bh' + h[-1]][0] - 0.01 for v in (rs, rq) for h in ('h1', 'h2'))
    return cal and ret


def row(tag, v):
    f, b = v['full'], v['bh']
    return (f'{tag:<6} 年化 {f[0]*100:+6.1f}%（{(f[0]-b[0])*100:+5.1f}）回撤 {f[1]*100:5.0f}% Calmar {f[2]:.2f}（×{f[2]/b[2]:.2f}；同曝險固定 {v["fixed"][2]:.2f}）'
            f' 離場/減碼 {v["out"]*100:3.0f}% 來回 {v["trips"]:>3}（{v["tpy"]:.1f}/年）'
            f'｜前半 {v["h1"][0]*100:+5.1f}%（{(v["h1"][0]-v["bh1"][0])*100:+5.1f}）C{cx(v["h1"][2], v["bh1"][2])}'
            f'｜後半 {v["h2"][0]*100:+5.1f}%（{(v["h2"][0]-v["bh2"][0])*100:+5.1f}）C{cx(v["h2"][2], v["bh2"][2])}')


def start_of(name, sym):
    s = WINDOW[sym]
    return max(s, VIXTERM_START) if BASE.get(name, name) == 'R3b' else s


# ── 事件表 ───────────────────────────────────────────────────────────────────
def first_fire(flag, gap=21):
    f = flag.fillna(False).astype(bool)
    prev = f.shift(1).rolling(gap).sum()
    return f & (prev == 0)


def alarm_table(label, ev_flag, sym, start, horizon=63, drop=0.10, list_dates=False):
    p = PX[sym].dropna()
    p = p[p.index >= pd.Timestamp(start)]
    v = p.to_numpy()
    hi = PX[sym].dropna().rolling(252, min_periods=200).max().reindex(p.index).to_numpy()
    n = len(v)
    fmin = np.array([v[i + 1:i + 1 + horizon].min() / v[i] - 1 if i + horizon < n else np.nan for i in range(n)])
    base = np.nanmean(fmin <= -drop)
    days = [d for d in ev_flag[ev_flag].index if d in p.index]
    T, F, lead, ddhi, f21, f63, t63, rows = 0, 0, [], [], [], [], [], []
    for d in days:
        i = p.index.get_loc(d)
        if i + horizon >= n:
            continue
        seg = v[i + 1:i + 1 + horizon]
        mn = seg.min() / v[i] - 1
        true = mn <= -drop
        ddhi.append(v[i] / hi[i] - 1 if hi[i] == hi[i] else np.nan)
        if true:
            T += 1
            lead.append(int(seg.argmin()) + 1)
            t63.append(v[i + 63] / v[i] - 1)
        else:
            F += 1
            f21.append(v[i + 21] / v[i] - 1)
            f63.append(v[i + 63] / v[i] - 1)
        rows.append(f'{d.date()}{"真" if true else "假"}({mn*100:+.0f}%)')
    tot = T + F
    md = lambda a: (np.nanmedian(a) if len(a) else np.nan)
    mu = lambda a: (np.mean(a) if len(a) else np.nan)
    print(f'  {label:<26}{sym:<4} 警報 {tot:>3}｜真 {T:>2} 假 {F:>3}｜命中率 {((T/tot) if tot else np.nan)*100:4.0f}% vs 任意日 {base*100:4.1f}%'
          f'｜真警報離谷底 中位 {md(lead):4.0f} 日｜警報時離一年高 中位 {md(ddhi)*100:+5.1f}%'
          f'｜假警報後 21日 {mu(f21)*100:+5.1f}% 63日 {mu(f63)*100:+5.1f}%｜真警報後 63日 {mu(t63)*100:+5.1f}%')
    if list_dates:
        print('     ' + ' '.join(rows))
    return dict(n=tot, T=T, F=F, base=base)


def fwd_study(label, ev_flag, sym, start, hz=(63, 126, 252)):
    p = PX[sym].dropna()
    p = p[p.index >= pd.Timestamp(start)]
    parts = []
    days = [d for d in ev_flag[ev_flag].index if d in p.index]
    for h in hz:
        f = (p.shift(-h) / p - 1)
        e = f.reindex(days).dropna()
        b = f.dropna()
        parts.append(f'{h:>3}日 {e.mean()*100:+5.1f}%（勝率 {(e > 0).mean()*100:3.0f}%，n={len(e)}）vs 任意日 {b.mean()*100:+5.1f}%（{(b > 0).mean()*100:3.0f}%）')
    print(f'  {label:<30}{sym:<4} ' + '｜'.join(parts))


# ── 主程式 ───────────────────────────────────────────────────────────────────
def main():
    print('=' * 100)
    print('信用利差擇時回測  2026-11-22（回測止於 2025-12-31；事前登記見腳本開頭）')
    print('=' * 100)

    print('\n【一】資料長度')
    print(f'  高收益債利差 BAMLH0A0HYM2：FRED 今天只給 {HY_ALL.index[0].date()} → {HY_ALL.index[-1].date()}，共 {len(HY_ALL)} 筆'
          f'（到 2025-12-31 為 {len(HY)} 筆，約 {len(HY)/252:.1f} 年）。')
    print('  → 儀表板燈號無法用自己的資料做長期驗證；以下一律用 BAA10Y 當替代品。')
    print(f'  BAA10Y {BAA.index[0].date()} → {BAA.index[-1].date()}（{len(BAA)} 筆）；AAA10Y {AAA.index[0].date()} →；DTB3 {DTB3.index[0].date()} →')
    for s in ('SPY', 'QQQ', 'SMH', '^VIX', '^VIX3M'):
        x = PX[s].dropna()
        print(f'  {s:<6} {x.index[0].date()} → {x.index[-1].date()}（{len(x)} 筆）')

    print('\n【二】替代品跟高收益債利差貼得多近（重疊期）')
    M = {}
    for nm, sub in (('BAA10Y', BAA), ('Baa−Aaa', BAA_AAA)):
        m = match_thresholds(sub)
        M[nm] = m
        print(f'  {nm:<8} 重疊 {m["span"][0]} → {m["span"][1]}（{m["n"]} 日）水準相關 {m["level_corr"]:.2f}'
              f'｜5日變化相關 {m[5]["corr"]:.2f}、20日變化相關 {m[20]["corr"]:.2f}'
              f'｜替代品每動 1bp 高收益債動 {m[5]["beta"]:.1f}bp（5日）／{m[20]["beta"]:.1f}bp（20日）')
        print(f'           高收益債原門檻的亮燈分位：5日 {m[5]["q"]*100:.1f}%、20日 {m[20]["q"]*100:.1f}% → 換算門檻 a={m[5]["thr"]:.0f}bp／5日、b={m[20]["thr"]:.0f}bp／20日'
              f'（標準差比例法會得到 {HY_FAST_5D/m[5]["sd_ratio"]:.1f}／{HY_FAST_20D/m[20]["sd_ratio"]:.1f}bp，僅對照）')
    A, B = M['BAA10Y'][5]['thr'], M['BAA10Y'][20]['thr']
    A2, B2 = M['Baa−Aaa'][5]['thr'], M['Baa−Aaa'][20]['thr']
    K = known(BAA)
    K2 = known(BAA_AAA)
    KH = known(HY)
    # 同日一致性（重疊期，已含公布延遲）
    wh = wf(KH, HY_FAST_5D, HY_FAST_20D)
    wb = wf(K, A, B)
    ov = KH.dropna().index[20:]
    a_, b_ = wh.reindex(ov), wb.reindex(ov)
    print(f'  重疊期亮燈日：高收益債 {int(a_.sum())} 日、BAA10Y {int(b_.sum())} 日、同一天都亮 {int((a_ & b_).sum())} 日'
          f'（高收益債亮燈日裡 BAA10Y 也亮的比例 {((a_ & b_).sum()/max(1, a_.sum()))*100:.0f}%；BAA10Y 亮燈日裡高收益債也亮的比例 {((a_ & b_).sum()/max(1, b_.sum()))*100:.0f}%）')
    eh, eb = first_fire(wh).reindex(ov), first_fire(wb).reindex(ov)
    dh, db = list(eh[eh].index), list(eb[eb].index)
    near = lambda d, L: any(abs(CAL.get_loc(d) - CAL.get_loc(x)) <= 5 for x in L)
    print(f'  重疊期首次亮起：高收益債 {len(dh)} 次（{", ".join(str(d.date()) for d in dh)}）')
    print(f'                  BAA10Y   {len(db)} 次（{", ".join(str(d.date()) for d in db)}）')
    print(f'  高收益債的警報前後 5 日內 BAA10Y 也有警報：{sum(near(d, db) for d in dh)}／{len(dh)}；反過來：{sum(near(d, dh) for d in db)}／{len(db)}')
    wfull = wb[wb.index >= '1994-01-03']
    print(f'  BAA10Y 換算門檻在 1994→2025 的亮燈日比例 {wfull.mean()*100:.1f}%（重疊期 {b_.mean()*100:.1f}%）')

    # ── 規則表 ──
    C = {sym: Cond(sym, K, A, B) for sym in WINDOW}
    res = {}
    print('\n【三】規則 × 標的（括號 = 對買進持有的差；C× = Calmar 是買進持有的幾倍；成本 0；訊號延遲已含）')
    for sym in ('SPY', 'QQQ', 'SMH'):
        c = C[sym]
        bh = evaluate(sym, pd.Series(1.0, index=c.idx), 0.0, WINDOW[sym])
        print(f'\n── {sym}（{bh["start"]} → {END}，對半切在 {bh["split"]}）買進持有：年化 {bh["bh"][0]*100:+.1f}% 回撤 {bh["bh"][1]*100:.0f}% Calmar {bh["bh"][2]:.2f}'
              f'｜前半 {bh["bh1"][0]*100:+.1f}%／{bh["bh1"][1]*100:.0f}%｜後半 {bh["bh2"][0]*100:+.1f}%／{bh["bh2"][1]*100:.0f}%')
        if sym != 'SMH':
            b7 = evaluate(sym, pd.Series(1.0, index=c.idx), 0.0, VIXTERM_START)
            print(f'   （R3b 用的 2007→ 視窗買進持有：年化 {b7["bh"][0]*100:+.1f}% 回撤 {b7["bh"][1]*100:.0f}% Calmar {b7["bh"][2]:.2f}）')
        # 對照組
        res[('B200', sym)] = evaluate(sym, (~c.below).astype(float), 0.0, WINDOW[sym])
        res[('B200m', sym)] = evaluate(sym, machine(c.below, ~c.below), 0.0, WINDOW[sym])
        res[('VT20', sym)] = evaluate_expo(sym, vol_target(sym), WINDOW[sym])
        print('  ' + row('200日線', res[('B200', sym)]))
        print('  ' + row('200+21', res[('B200m', sym)]))
        print('  ' + row('波動20%', res[('VT20', sym)]))
        print('  ' + '-' * 60)
        for name, desc, kind, _ in RULES:
            v = evaluate(sym, rule_pos(name, c), 0.0 if kind == 'io' else 0.5, start_of(name, sym))
            res[(name, sym)] = v
            print('  ' + row(name, v) + f'  〔{desc}〕')

    # ── 過關判定 ──
    print('\n【四】對照事前過關線（只看 SPY 與 QQQ；甲 = 前後半年化都贏且每年來回 ≤2；乙 = 前後半 Calmar 都 ≥1.2 倍且少賺 ≤1 個百分點）')
    npass = 0
    for name, desc, kind, _ in RULES:
        rs, rq = res[(name, 'SPY')], res[(name, 'QQQ')]
        a, b = pass_a(rs, rq), pass_b(rs, rq)
        verdict = (a if kind == 'io' else b)
        npass += verdict
        cells = ' '.join(f'{s}{h[-1]} {(v[h][0]-v["bh"+h[-1]][0])*100:+5.1f}/{cx(v[h][2], v["bh"+h[-1]][2])}' for s, v in (('S', rs), ('Q', rq)) for h in ('h1', 'h2'))
        print(f'  {name}  適用線 {"甲" if kind == "io" else "乙"} → {"過關" if verdict else "不過"}  〔{cells}〕（參考：甲 {"過" if a else "不過"}、乙 {"過" if b else "不過"}）')
    for name in ('B200', 'B200m', 'VT20'):
        rs, rq = res[(name, 'SPY')], res[(name, 'QQQ')]
        cells = ' '.join(f'{s}{h[-1]} {(v[h][0]-v["bh"+h[-1]][0])*100:+5.1f}/{cx(v[h][2], v["bh"+h[-1]][2])}' for s, v in (('S', rs), ('Q', rq)) for h in ('h1', 'h2'))
        print(f'  對照 {name:<5} 甲 {"過" if pass_a(rs, rq) else "不過"}、乙 {"過" if pass_b(rs, rq) else "不過"}  〔{cells}〕')
    print(f'  → 14 條交易規則裡過關 {npass} 條。')

    # ── 事件表 ──
    print('\n【五】警報本身的事件表（BAA10Y 換算門檻；首次亮起 = 前 21 日沒亮；真 = 之後 63 日內再跌 ≥10%）')
    for sym in ('SPY', 'QQQ', 'SMH'):
        c = C[sym]
        ev = first_fire(c.W)
        alarm_table('W 全部', ev, sym, WINDOW[sym], list_dates=(sym == 'SPY'))
        alarm_table('W 且價<200日線（R3a）', ev & c.below, sym, WINDOW[sym])
        alarm_table('W 且離高點<5%（R3c）', ev & c.near, sym, WINDOW[sym])
        alarm_table('W 且已跌≥10%（R3d）', ev & c.late, sym, WINDOW[sym])
        if sym != 'SMH':
            alarm_table('W 全部（2007→）', ev, sym, VIXTERM_START)
            alarm_table('W 且VIX倒掛（R3b，2007→）', ev & c.inv.fillna(False), sym, VIXTERM_START)
        print()
    print('  高收益債自己的短歷史（儀表板原門檻 25／50bp；樣本極小，只當描述）')
    evh = first_fire(wf(KH, HY_FAST_5D, HY_FAST_20D))
    for sym in ('SPY', 'QQQ', 'SMH'):
        alarm_table('高收益債 W', evh.reindex(PX[sym].dropna().index).fillna(False), sym, str(KH.dropna().index[25].date()), list_dates=(sym == 'SPY'))

    # ── R5b ──
    print('\n【六】R5b 反向讀法事件研究（位階 >90% 且利差剛跌破 20 日均；21 日內第一次）vs VIX 首次站上 30')
    for sym in ('SPY', 'QQQ', 'SMH'):
        c = C[sym]
        nn = c.N.fillna(False)
        cross = nn & ~nn.shift(1).fillna(False) & (c.P > 0.90)
        fwd_study('R5b 高利差開始收斂', first_fire(cross), sym, WINDOW[sym])
        v30 = (PX['^VIX'] >= 30).reindex(c.idx).fillna(False)
        fwd_study('對照 VIX 首次 ≥30（20日去叢集）', first_fire(v30, 20), sym, WINDOW[sym])

    # ── 最佳規則：鄰近參數 ──
    io = [r[0] for r in RULES if r[2] == 'io']
    sz = [r[0] for r in RULES if r[2] == 'sz']
    best_io = max(io, key=lambda n: np.mean([res[(n, s)]['full'][0] - res[(n, s)]['bh'][0] for s in ('SPY', 'QQQ')]))
    best_sz = max(sz, key=lambda n: np.mean([res[(n, s)]['full'][2] / res[(n, s)]['bh'][2] for s in ('SPY', 'QQQ')]))
    print(f'\n【七】最佳規則的鄰近參數檢查（選法事前寫死）：最佳全出／全進 = {best_io}；最佳只調部位 = {best_sz}')
    ncell = 0
    for name in (best_io, best_sz):
        kind = KIND[name]
        floor = 0.0 if kind == 'io' else 0.5
        grid = (0.70, 0.80, 0.90, 0.95) if name in LEVEL_RULES else (0.5, 0.75, 1.0, 1.5, 2.0)
        ok = tot = 0
        print(f'\n  {name}（{"百分位" if name in LEVEL_RULES else "門檻倍數"} × 最短出場日）')
        for g in grid:
            for mo in (21, 63):
                cells, vv = [], {}
                for sym in ('SPY', 'QQQ', 'SMH'):
                    c = C[sym] if name in LEVEL_RULES else Cond(sym, K, A, B, scale=g)
                    v = evaluate(sym, rule_pos(name, c, pct=(g if name in LEVEL_RULES else None), min_out=mo), floor, start_of(name, sym))
                    vv[sym] = v
                    cells.append(f'{sym} {(v["full"][0]-v["bh"][0])*100:+5.1f}/×{v["full"][2]/v["bh"][2]:.2f}〔前 {(v["h1"][0]-v["bh1"][0])*100:+5.1f}/{cx(v["h1"][2], v["bh1"][2])} 後 {(v["h2"][0]-v["bh2"][0])*100:+5.1f}/{cx(v["h2"][2], v["bh2"][2])}〕來回{v["tpy"]:.1f}/年')
                p = pass_a(vv['SPY'], vv['QQQ']) if kind == 'io' else pass_b(vv['SPY'], vv['QQQ'])
                tot += 1
                ok += p
                ncell += 1
                gl = f'{g*100:.0f}%' if name in LEVEL_RULES else f'×{g}'
                print(f'   {gl:<5} 出場≥{mo:>2}日 {"過" if p else "不過"}｜' + '｜'.join(cells))
        print(f'   → {tot} 格裡過適用線 {ok} 格')
        # 副替代品
        cells, vv = [], {}
        for sym in ('SPY', 'QQQ', 'SMH'):
            c2 = Cond(sym, K2, A2, B2)
            v = evaluate(sym, rule_pos(name, c2), floor, start_of(name, sym))
            vv[sym] = v
            cells.append(f'{sym} {(v["full"][0]-v["bh"][0])*100:+5.1f}/×{v["full"][2]/v["bh"][2]:.2f}〔前 {(v["h1"][0]-v["bh1"][0])*100:+5.1f}/{cx(v["h1"][2], v["bh1"][2])} 後 {(v["h2"][0]-v["bh2"][0])*100:+5.1f}/{cx(v["h2"][2], v["bh2"][2])}〕')
        p = pass_a(vv['SPY'], vv['QQQ']) if kind == 'io' else pass_b(vv['SPY'], vv['QQQ'])
        ncell += 1
        print(f'   換成 Baa−Aaa（a={A2:.0f}、b={B2:.0f}bp）{"過" if p else "不過"}｜' + '｜'.join(cells))
    print(f'\n  鄰近參數格數合計 {ncell}（只看穩不穩，不當候選）')

    # ── 信用 vs 價格 ──
    print('\n【八】信用利差有沒有說出價格沒說的事（最佳規則 vs 已驗證的對照組）')
    for name in (best_io, best_sz):
        for sym in ('SPY', 'QQQ', 'SMH'):
            v = res[(name, sym)]
            e, e200 = v['e'], res[('B200', sym)]['e'].reindex(v['e'].index)
            off = e < 1 - 1e-9
            both = float((e200[off] < 1 - 1e-9).mean()) if off.any() else np.nan
            b2, vt = res[('B200', sym)], res[('VT20', sym)]
            print(f'  {name} {sym}：訊號亮的日子裡 200 日線也在場外的比例 {both*100:3.0f}%'
                  f'｜年化 {v["full"][0]*100:+.1f}% Calmar {v["full"][2]:.2f}  vs  200日線 {b2["full"][0]*100:+.1f}%／{b2["full"][2]:.2f}  vs  波動目標 {vt["full"][0]*100:+.1f}%／{vt["full"][2]:.2f}'
                  f'  vs  買進持有 {v["bh"][0]*100:+.1f}%／{v["bh"][2]:.2f}')
    print('\n  首跑後補的對照（不是候選）：只看 200 日線、線下就減半，不用信用利差——拿來跟 S3a 比，看利差多加了什麼')
    for sym in ('SPY', 'QQQ', 'SMH'):
        c = C[sym]
        print(f'  {sym} ' + row('200減半', evaluate(sym, machine(c.below, ~c.below), 0.5, WINDOW[sym])))
        print(f'  {sym} ' + row('S3a', res[('S3a', sym)]))
    print('\n變體數：事前登記 14 條交易規則 + 1 個事件研究 = 15；鄰近參數格另計（見【七】）；事後探索另列於【九】。')


# ── 事後探索（看過首跑結果才加；不計入過關判定）────────────────────────────────
def post_hoc():
    f = DATA / 'px_posthoc.csv'
    if f.exists():
        e = pd.read_csv(f, index_col=0, parse_dates=True)
    else:
        import yfinance as yf
        e = yf.download(['HYG', 'IEI'], period='max', progress=False, auto_adjust=True)['Close']
        e.index = pd.to_datetime(e.index).tz_localize(None)
        e.to_csv(f)
    e = e.loc[:END].dropna()
    start = '2007-07-02'
    rel = np.log(e['HYG'] / e['IEI'])                      # 高收益債相對公債的累計還原報酬
    k = (-rel * 10000).reindex(CAL)                        # 取負號：數字變大 = 高收益債輸給公債 = 利差擴大（bp，未除存續期間）
    print('\n' + '=' * 100)
    print('【九】事後探索（看過結果才加；不計入過關判定）：用 HYG 對 IEI 的相對報酬當高收益債利差代理（2007-07→2025）')
    print('=' * 100)
    print(f'  HYG {e.index[0].date()} → {e.index[-1].date()}；代理 = −log(HYG÷IEI)×10000，當天收盤已知（無公布延遲）')
    # 對齊門檻：同一天的高收益債利差變化 vs 代理變化（都不延遲）
    hy = (HY * 100).reindex(CAL).ffill()
    j = pd.concat([hy, k], axis=1, keys=['hy', 'px']).dropna()
    thr = {}
    for n, th in ((5, HY_FAST_5D), (20, HY_FAST_20D)):
        dh = (j['hy'] - j['hy'].shift(n)).dropna()
        dp = (j['px'] - j['px'].shift(n)).dropna()
        q = float((dh < th).mean())
        thr[n] = float(np.round(np.quantile(dp, q)))
        print(f'  {n:>2} 日變化：與高收益債利差變化的相關 {dh.corr(dp):.2f}；高收益債每動 1bp 代理動 {np.polyfit(dh.to_numpy(), dp.to_numpy(), 1)[0]:.1f}bp；'
              f'原門檻 {th}bp 的亮燈分位 {q*100:.1f}% → 代理門檻 {thr[n]:.0f}bp')
    a, b = thr[5], thr[20]
    wp_all = wf(k, a, b)
    wh = wf(hy, HY_FAST_5D, HY_FAST_20D)
    ov = j.index[20:]
    x, y = wh.reindex(ov), wp_all.reindex(ov)
    eh, ep = first_fire(wh).reindex(ov), first_fire(wp_all).reindex(ov)
    dh_, dp_ = list(eh[eh].index), list(ep[ep].index)
    near = lambda d, L: any(abs(CAL.get_loc(d) - CAL.get_loc(z)) <= 5 for z in L)
    print(f'  重疊期亮燈日：高收益債 {int(x.sum())}、代理 {int(y.sum())}、同日 {int((x & y).sum())}；'
          f'首次亮起：高收益債 {len(dh_)} 次、代理 {len(dp_)} 次；高收益債警報 ±5 日內代理也有 {sum(near(d, dp_) for d in dh_)}／{len(dh_)}，反過來 {sum(near(d, dh_) for d in dp_)}／{len(dp_)}')
    w07 = wp_all[wp_all.index >= start]
    print(f'  代理門檻在 2007-07→2025 的亮燈日比例 {w07.mean()*100:.1f}%')
    res = {}
    for sym in ('SPY', 'QQQ', 'SMH'):
        c = Cond(sym, k, a, b)
        st = max(start, WINDOW[sym])
        bh = evaluate(sym, pd.Series(1.0, index=c.idx), 0.0, st, lag=1)
        print(f'\n── {sym}（{bh["start"]} → {END}，對半切在 {bh["split"]}）買進持有：年化 {bh["bh"][0]*100:+.1f}% 回撤 {bh["bh"][1]*100:.0f}% Calmar {bh["bh"][2]:.2f}'
              f'｜前半 {bh["bh1"][0]*100:+.1f}%／{bh["bh1"][1]*100:.0f}%｜後半 {bh["bh2"][0]*100:+.1f}%／{bh["bh2"][1]*100:.0f}%')
        print('  ' + row('200日線', evaluate(sym, (~c.below).astype(float), 0.0, st, lag=1)))
        print('  ' + row('波動20%', evaluate_expo(sym, vol_target(sym), st, lag=1)))
        for name in ('R1c', 'R3a', 'S3a'):
            v = evaluate(sym, rule_pos(name, c), 0.0 if KIND[name] == 'io' else 0.5, st, lag=1)
            res[(name, sym)] = v
            print('  ' + row(name, v))
    for name in ('R1c', 'R3a', 'S3a'):
        rs, rq = res[(name, 'SPY')], res[(name, 'QQQ')]
        p = pass_a(rs, rq) if KIND[name] == 'io' else pass_b(rs, rq)
        print(f'  事後探索 {name}：若套同一條過關線 → {"過" if p else "不過"}（僅供參考）')
    print('\n  事件表（代理門檻；真 = 之後 63 日內再跌 ≥10%）')
    for sym in ('SPY', 'QQQ', 'SMH'):
        c = Cond(sym, k, a, b)
        st = max(start, WINDOW[sym])
        ev = first_fire(c.W)
        alarm_table('代理 W 全部', ev, sym, st, list_dates=(sym == 'SPY'))
        alarm_table('代理 W 且價<200日線', ev & c.below, sym, st)
    print('\n事後探索變體數：3（R1c、R3a、S3a 換代理各一次）。')


if __name__ == '__main__':
    main()
    post_hoc()
