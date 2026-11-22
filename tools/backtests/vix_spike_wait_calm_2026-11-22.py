"""「VIX 衝高＋價格跌破 50／200 日線，等波動（VIX 或 NATR）降回平緩再建倉／加碼」比「VIX 一衝高就買」好嗎
（2026-11-22 用戶，接在 spx_5d_drop8 之後）。

做法
  事件（t0）＝VIX 收盤站上門檻（預設 30），且之前 40 個交易日都沒站上過（一段恐慌只算一次）。
  設定條件（t0 當天）：不限／收盤在 50 日線下／收盤在 200 日線下。
  平緩訊號（t0 之後第一次成立的那天收盤進場，最多等 126 個交易日，等不到＝沒買）：
    V25   VIX 收盤 < 25
    V20   VIX 收盤 < 20
    N60   NATR(14) 回落到「t0 以來最高值」的 60% 以下（至少等 5 天）
    Nmed  NATR(14) 回到自己過去 252 日的中位數以下
  NATR(14)＝Wilder ATR(14)／收盤 ×100，用標的自己的高低收。
  比較對象：(a) t0 當天就買；(b) 任意日。
  公平比法＝「同一終點」：都從 t0 起算到 t0＋126／252 日，等待期間錢放現金（0%）或放 SPY（本帳戶的停泊池是 VOO）。
標的：SPY 1993→、QQQ 1999→、SMH 2012→（之前的歷史有缺陷）、^SOX 1994→（費半價格指數，補 SMH 的長歷史）。
事件少（QQQ 十幾次、SMH 個位數），所有數字都是描述性的。

首跑結論（2026-11-22）：等平緩＝買貴。QQQ 進場價比 t0 中位高 4.5%（VIX<25）到 11.8%（NATR 回一年中位），
比 t0 便宜的只有 5–10%。同一終點 t0＋252 日、等待期間放 SPY：QQQ 差 平均 −2.6% 到 +0.6%、中位 −1.8% 到 −2.0%、
等贏 4–9／22；SMH 等贏 0–2／9；VIX≥35 的事件用 VIX 訊號等贏 0／14。等的好處只有進場後 60 日的路比較平
（QQQ 最差 −20%／−23% vs −40%），12 個月最差結果沒有比較好。「平緩但還在 200 日線下」在 SPY 是最差的組合
（6 個月 −2.9% 到 −10.8%）。不新增影子、不進閘門。
第 8 節（同日追問「放長期呢」）：進場後差距固定成比例，QQQ 中位 −1.4% 到 −2.4%；恐慌日買抱 5 年不比任意日好。
Run: python3 tools/backtests/vix_spike_wait_calm_2026-11-22.py
Output: tools/backtests/data/vix_spike_wait_calm_2026-11-22.out.txt
"""
import os
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import yfinance as yf

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "vix_spike_wait_calm_2026-11-22.out.txt")
TIMEOUT = 126
FRESH = 40
_lines = []


def p(s=""):
    print(s)
    _lines.append(s)


raw = yf.download(["SPY", "QQQ", "SMH", "^SOX", "^VIX"], start="1990-01-01", end="2026-11-21",
                  progress=False, auto_adjust=True)
vix = raw["Close"]["^VIX"].dropna()


def ohlc(sym, start=None):
    df = pd.DataFrame({c: raw[c][sym] for c in ("High", "Low", "Close")}).dropna()
    if start:
        df = df[df.index >= start]
    return df


def natr(df, n=14):
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / df["Close"] * 100


ASSETS = {
    "SPY": ohlc("SPY"),
    "QQQ": ohlc("QQQ"),
    "SMH": ohlc("SMH", "2012-01-01"),
    "SOX": ohlc("^SOX"),
}
spy_c = ASSETS["SPY"]["Close"]


def fresh_cross(thr, fresh=FRESH):
    above = vix >= thr
    prior = above.shift(1).rolling(fresh).max().fillna(0).astype(bool)
    return list(vix.index[(above & ~prior).values])


def prep(df):
    c = df["Close"]
    d = pd.DataFrame({"c": c, "lo": df["Low"], "ma50": c.rolling(50).mean(), "ma200": c.rolling(200).mean(),
                      "natr": natr(df)})
    d["natr_med"] = d["natr"].rolling(252).median()
    d["vix"] = vix.reindex(d.index).ffill()
    return d


PREP = {k: prep(v) for k, v in ASSETS.items()}
TRIG = ["V25", "V20", "N60", "Nmed"]
TRIG_NAME = {"V25": "VIX<25", "V20": "VIX<20", "N60": "NATR≤峰值60%", "Nmed": "NATR≤一年中位"}


def find_entry(d, i0, trig):
    """t0 之後第一個平緩日的位置；等不到回 None。"""
    end = min(i0 + TIMEOUT, len(d) - 1)
    peak = d["natr"].iloc[i0]
    for i in range(i0 + 1, end + 1):
        n = d["natr"].iloc[i]
        peak = max(peak, n)
        if trig == "V25" and d["vix"].iloc[i] < 25:
            return i
        if trig == "V20" and d["vix"].iloc[i] < 20:
            return i
        if trig == "N60" and i >= i0 + 5 and n <= 0.6 * peak:
            return i
        if trig == "Nmed" and n <= d["natr_med"].iloc[i]:
            return i
    return None


def episodes(sym, thr=30):
    """該標的可用的事件：t0 當天 MA200、NATR 中位都算得出來。"""
    d = PREP[sym]
    out = []
    for t0 in fresh_cross(thr):
        if t0 not in d.index:
            continue
        i0 = d.index.get_loc(t0)
        if np.isnan(d["ma200"].iloc[i0]) or np.isnan(d["natr_med"].iloc[i0]):
            continue
        out.append(i0)
    return out


def ret(c, i, h):
    return c.iloc[i + h] / c.iloc[i] - 1 if i + h < len(c) else np.nan


def mae(d, i, h=60):
    return d["lo"].iloc[i + 1:i + 1 + h].min() / d["c"].iloc[i] - 1 if i + h < len(d) else np.nan


def ms(x):
    x = np.array([v for v in x if not np.isnan(v)])
    if len(x) == 0:
        return "    —     "
    return f"{x.mean() * 100:+6.1f}%/{(x > 0).mean() * 100:3.0f}%"


def setup_ok(d, i0, setup):
    if setup == "不限":
        return True
    if setup == "50日線下":
        return d["c"].iloc[i0] < d["ma50"].iloc[i0]
    return d["c"].iloc[i0] < d["ma200"].iloc[i0]


SETUPS = ["不限", "50日線下", "200日線下"]

p("VIX 衝高＋跌破均線，等波動平緩再買 vs 當天就買      資料到 2026-11-20")
p("=" * 100)
p("事件＝VIX 收盤站上 30，且之前 40 個交易日沒站上過。括號外＝平均報酬，斜線後＝上漲比例。")

# ── 1 事件當天的狀態
p("\n1. 事件當天各標的在均線的哪一邊")
ev_all = fresh_cross(30)
p(f"   VIX 首次站上 30 的事件（1990→）：{len(ev_all)} 次：" + "、".join(d.strftime("%Y-%m") for d in ev_all))
for sym in ASSETS:
    d = PREP[sym]
    E = episodes(sym)
    b50 = sum(d["c"].iloc[i] < d["ma50"].iloc[i] for i in E)
    b200 = sum(d["c"].iloc[i] < d["ma200"].iloc[i] for i in E)
    p(f"   {sym:<4} 可用 {len(E):>2} 次；當天在 50 日線下 {b50} 次、在 200 日線下 {b200} 次")

# ── 2 從進場日起算
p("\n2. 從「進場日」起算的之後報酬（等到平緩才買 vs t0 當天買 vs 任意日）")
p("   注意：這一節兩種買法的起算日不同，等的人少賺的那一段沒算進去；公平比較看第 3 節。")
for sym in ASSETS:
    d = PREP[sym]
    c = d["c"]
    anyd = {h: (c.shift(-h) / c - 1).dropna() for h in (63, 126, 252)}
    p(f"\n  {sym}   任意日 3／6／12 個月："
      + "  ".join(f"{anyd[h].mean() * 100:+.1f}%/{(anyd[h] > 0).mean() * 100:.0f}%" for h in (63, 126, 252)))
    for setup in SETUPS:
        E = [i for i in episodes(sym) if setup_ok(d, i, setup) and i + 1 < len(d) - 5 and d.index[i] < pd.Timestamp("2026-06-01")]
        if not E:
            continue
        p(f"   設定＝{setup}（{len(E)} 次）")
        p(f"     {'買法':<14}{'買到':>5}{'等待日中位':>8}{'進場價比t0':>12}{'較便宜':>6}   "
          f"{'3個月':>11} {'6個月':>11} {'12個月':>11}   {'之後60日最深 中位/最差':>20}")
        imm_m = [mae(d, i) for i in E]
        p(f"     {'t0 當天買':<14}{len(E):>5}{0:>10}{'—':>13}{'—':>8}   "
          f"{ms([ret(c, i, 63) for i in E])} {ms([ret(c, i, 126) for i in E])} {ms([ret(c, i, 252) for i in E])}   "
          f"{np.nanmedian(imm_m) * 100:+6.1f}% / {np.nanmin(imm_m) * 100:+6.1f}%")
        for trig in TRIG:
            ent = [(i, find_entry(d, i, trig)) for i in E]
            got = [(i, j) for i, j in ent if j is not None]
            if not got:
                p(f"     {TRIG_NAME[trig]:<14}{0:>5}")
                continue
            wait = np.median([j - i for i, j in got])
            rel = np.array([c.iloc[j] / c.iloc[i] - 1 for i, j in got])
            em = [mae(d, j) for _, j in got]
            p(f"     {TRIG_NAME[trig]:<14}{len(got):>5}{wait:>10.0f}{np.median(rel) * 100:>+11.1f}%{(rel < 0).mean() * 100:>7.0f}%   "
              f"{ms([ret(c, j, 63) for _, j in got])} {ms([ret(c, j, 126) for _, j in got])} {ms([ret(c, j, 252) for _, j in got])}   "
              f"{np.nanmedian(em) * 100:+6.1f}% / {np.nanmin(em) * 100:+6.1f}%")


# ── 3 同一終點
def same_end(sym, E, trig, H, park):
    """回傳 (立刻買報酬, 等待買報酬) 兩個陣列；都從 t0 到 t0+H。等待期間放 park（'cash' 或 'SPY'）。"""
    d = PREP[sym]
    c = d["c"]
    a, b = [], []
    for i in E:
        if i + H >= len(c):
            continue
        t0, tH = c.index[i], c.index[i + H]
        j = find_entry(d, i, trig)
        imm = c.iloc[i + H] / c.iloc[i] - 1
        jj = min(j, i + H) if j is not None else i + H
        tj = c.index[jj]
        if park == "cash":
            pre = 1.0
        else:
            s = spy_c.reindex([t0, tj]).ffill()
            pre = s.iloc[1] / s.iloc[0]
        post = c.iloc[i + H] / c.iloc[jj]
        a.append(imm)
        b.append(pre * post - 1)
    return np.array(a), np.array(b)


p("\n3. 同一終點的公平比較：都從 t0 算到 t0＋N 日；「等」的人等待期間錢放現金或放 SPY")
p("   差＝等 − 立刻買（正＝等比較好）。等不到平緩訊號的事件，等的人整段都停在現金／SPY。")
for sym in ASSETS:
    d = PREP[sym]
    p(f"\n  {sym}")
    for setup in SETUPS:
        E = [i for i in episodes(sym) if setup_ok(d, i, setup)]
        if not E:
            continue
        for H in (126, 252):
            a0, _ = same_end(sym, E, "V25", H, "cash")
            if len(a0) == 0:
                continue
            p(f"   設定＝{setup}，終點 t0＋{H} 日（{len(a0)} 次）  立刻買：平均 {a0.mean() * 100:+.1f}%、中位 {np.median(a0) * 100:+.1f}%、最差 {a0.min() * 100:+.1f}%")
            for trig in TRIG:
                row = f"     {TRIG_NAME[trig]:<14}"
                for park in ("cash", "SPY"):
                    if sym == "SPY" and park == "SPY":
                        continue
                    a, b = same_end(sym, E, trig, H, park)
                    df_ = b - a
                    row += (f" 等待放{'現金' if park == 'cash' else ' SPY'}：平均 {b.mean() * 100:+6.1f}%、最差 {b.min() * 100:+6.1f}%、"
                            f"差 平均 {df_.mean() * 100:+5.1f}%／中位 {np.median(df_) * 100:+5.1f}%、等贏 {int((df_ > 0).sum())}/{len(df_)} |")
                p(row)

# ── 4 逐筆
p("\n4. QQQ 逐筆（設定不限）：t0 當天買 vs 等 VIX<25 vs 等 NATR 回一年中位；報酬都算到 t0＋252 日，等待期間放 SPY")
d = PREP["QQQ"]
c = d["c"]
p(f"   {'t0':<11}{'VIX':>5}{'距50線':>8}{'距200線':>8}{'NATR':>6} | {'立刻買':>8} | {'VIX<25 等幾日':>12}{'價差':>7}{'總報酬':>8} | {'NATR中位 等幾日':>14}{'價差':>7}{'總報酬':>8}")
for i in episodes("QQQ"):
    t0 = d.index[i]
    row = (f"   {t0.strftime('%Y-%m-%d'):<11}{d['vix'].iloc[i]:>5.1f}{(c.iloc[i] / d['ma50'].iloc[i] - 1) * 100:>+7.1f}%"
           f"{(c.iloc[i] / d['ma200'].iloc[i] - 1) * 100:>+7.1f}%{d['natr'].iloc[i]:>6.2f} | ")
    done = i + 252 < len(c)
    row += f"{ret(c, i, 252) * 100:>+7.1f}% | " if done else f"{'未滿':>8} | "
    for trig in ("V25", "Nmed"):
        j = find_entry(d, i, trig)
        if j is None:
            row += f"{'等不到':>12}{'':>7}"
        else:
            row += f"{j - i:>12}{(c.iloc[j] / c.iloc[i] - 1) * 100:>+6.1f}%"
        if done:
            _, b = same_end("QQQ", [i], trig, 252, "SPY")
            row += f"{b[0] * 100:>+7.1f}% | "
        else:
            row += f"{'未滿':>8} | "
    p(row)

# ── 5 進場當天還在不在均線下
p("\n5. 平緩訊號出現那天，價格還在均線下嗎（還在線下才算「便宜又平靜」）；之後 6 個月報酬分開看")
for sym in ("SPY", "QQQ", "SOX"):
    d = PREP[sym]
    c = d["c"]
    for trig in TRIG:
        got = [(i, find_entry(d, i, trig)) for i in episodes(sym)]
        got = [(i, j) for i, j in got if j is not None and j + 126 < len(c)]
        if not got:
            continue
        b200 = [j for _, j in got if c.iloc[j] < d["ma200"].iloc[j]]
        a200 = [j for _, j in got if c.iloc[j] >= d["ma200"].iloc[j]]
        b50 = [j for _, j in got if c.iloc[j] < d["ma50"].iloc[j]]
        p(f"   {sym:<4}{TRIG_NAME[trig]:<13} 進場 {len(got):>2} 次；仍在 50 日線下 {len(b50):>2} 次；"
          f"仍在 200 日線下 {len(b200):>2} 次 → 6 個月 {ms([ret(c, j, 126) for j in b200])}；"
          f"已回 200 日線上 {len(a200):>2} 次 → {ms([ret(c, j, 126) for j in a200])}")

# ── 6 門檻穩健性
p("\n6. 換 VIX 門檻看結論穩不穩（QQQ、設定不限、終點 t0＋252 日、等待期間放 SPY；差＝等 − 立刻買）")
for thr in (25, 30, 35, 40):
    d = PREP["QQQ"]
    E = []
    for t0 in fresh_cross(thr):
        if t0 in d.index:
            i0 = d.index.get_loc(t0)
            if not (np.isnan(d["ma200"].iloc[i0]) or np.isnan(d["natr_med"].iloc[i0])):
                E.append(i0)
    row = f"   VIX≥{thr}："
    for trig in TRIG:
        a, b = same_end("QQQ", E, trig, 252, "SPY")
        if len(a) == 0:
            continue
        df_ = b - a
        row += f" {TRIG_NAME[trig]} 差 {df_.mean() * 100:+5.1f}%（等贏 {int((df_ > 0).sum())}/{len(df_)}）|"
    p(row + f"  立刻買平均 {a.mean() * 100:+.1f}%")

# ── 7 現況
p("\n7. 現在（2026-11-20 收盤）離各個「平緩」訊號多遠")
p(f"   VIX {vix.iloc[-1]:.1f}（訊號：<25／<20）")
for sym in ("SPY", "QQQ", "SMH"):
    d = PREP[sym]
    i = len(d) - 1
    E = [k for k in episodes(sym) if d.index[k] >= pd.Timestamp("2026-09-01")]
    peak = d["natr"].iloc[E[-1]:].max() if E else np.nan
    p(f"   {sym:<4} 收盤 {d['c'].iloc[i]:.2f}；距 50 日線 {(d['c'].iloc[i] / d['ma50'].iloc[i] - 1) * 100:+.1f}%、"
      f"距 200 日線 {(d['c'].iloc[i] / d['ma200'].iloc[i] - 1) * 100:+.1f}%；NATR {d['natr'].iloc[i]:.2f}、"
      f"一年中位 {d['natr_med'].iloc[i]:.2f}、這波峰值 {peak:.2f}（60%＝{0.6 * peak:.2f}）"
      + (f"；這波 t0＝{d.index[E[-1]].strftime('%Y-%m-%d')}" if E else "；這波沒有 t0"))

# ── 8 放長期（同日追問「你看的獲利是多久後的，若是放長期呢」）
p("\n8. 放長期：2／3／5 年")
p("   一旦兩種買法都進場了，之後兩邊漲跌完全一樣，差距就固定成一個比例＝「等的人最後的錢 ÷ 當天買的人的錢 − 1」，")
p("   抱多久都不變。等不到訊號的，算第 126 日強制進場。等待期間放 SPY（SPY 自己則放現金）。")
for sym in ASSETS:
    d = PREP[sym]
    c = d["c"]
    E = [i for i in episodes(sym) if i + TIMEOUT < len(c)]
    p(f"  {sym}（{len(E)} 次）")
    for trig in TRIG:
        rr = []
        for i in E:
            j = find_entry(d, i, trig) or i + TIMEOUT
            if sym == "SPY":
                pre = 1.0
            else:
                s = spy_c.reindex([c.index[i], c.index[j]]).ffill()
                pre = s.iloc[1] / s.iloc[0]
            rr.append(pre * c.iloc[i] / c.iloc[j] - 1)
        rr = np.array(rr)
        p(f"     {TRIG_NAME[trig]:<14} 固定差距 平均 {rr.mean() * 100:+5.1f}%、中位 {np.median(rr) * 100:+5.1f}%、"
          f"最差 {rr.min() * 100:+6.1f}%、最好 {rr.max() * 100:+6.1f}%、等贏 {int((rr > 0).sum())}/{len(rr)}")

p("\n   長期來看「恐慌日買」本身還算不算好買點：t0 當天買 vs 任意日買，抱 1／2／3／5 年（平均／上漲比例；年化用中位數）")
for sym in ASSETS:
    d = PREP[sym]
    c = d["c"]
    E = episodes(sym)
    row = f"  {sym:<4}"
    for H, lab in ((252, "1年"), (504, "2年"), (756, "3年"), (1260, "5年")):
        r = np.array([ret(c, i, H) for i in E])
        r = r[~np.isnan(r)]
        b = (c.shift(-H) / c - 1).dropna()
        if len(r) == 0:
            continue
        ann = lambda x: ((1 + np.median(x)) ** (252 / H) - 1) * 100
        row += (f" {lab}（{len(r)}次）{r.mean() * 100:+6.1f}%/{(r > 0).mean() * 100:3.0f}% 年化{ann(r):+5.1f}%"
                f" vs {b.mean() * 100:+6.1f}%/{(b > 0).mean() * 100:3.0f}% 年化{ann(b):+5.1f}% |")
    p(row)

p("\n   QQQ 逐筆：t0 當天買抱 1／3／5 年的總報酬，與等 NATR 回一年中位的固定差距")
d = PREP["QQQ"]
c = d["c"]
for i in episodes("QQQ"):
    if i + TIMEOUT >= len(c):
        continue
    j = find_entry(d, i, "Nmed") or i + TIMEOUT
    s = spy_c.reindex([c.index[i], c.index[j]]).ffill()
    gap = s.iloc[1] / s.iloc[0] * c.iloc[i] / c.iloc[j] - 1
    cells = "".join(f"{ret(c, i, H) * 100:>+9.1f}%" if i + H < len(c) else f"{'未滿':>10}" for H in (252, 756, 1260))
    p(f"   {d.index[i].strftime('%Y-%m-%d')}  1／3／5 年{cells}   等的固定差距 {gap * 100:+6.1f}%")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(_lines) + "\n")
