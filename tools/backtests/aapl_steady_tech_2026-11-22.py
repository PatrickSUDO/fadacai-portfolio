"""AAPL「在科技股裡較穩，配一點」能不能少跌（2026-11-22 用戶，接在 vt_etf_drawdown 之後）。

同一把尺：帳戶回撤來自對半導體的曝險，所以看 AAPL 在半導體大跌時跌多少、對 SMH 與對帳本的 β，
以及把既有做法的「其餘部位」從 VOO 換一部分成 AAPL 的結果。MSFT／QQQ 放進來當對照。

做法
  1. 前提驗證：AAPL 比帳本裡的個股穩嗎（2023→ 年化波動、最大回撤、2026 高點至今），跟 VOO 比呢。
  2. 單獨比＋對 SMH 的相關與 β；對「帳本個股格」（現有 13 檔照現在權重，2023→）的相關與 β。
  3. SMH 每一段 ≥20% 回撤期間 AAPL／MSFT／QQQ／SPY 的報酬。
  4. AAPL 自己 ≥25% 的回撤（單一個股風險）。
  5. 配一點：70% 半導體＋30% VOO 為底，10%／20% AAPL 從 VOO 出或從半導體出；以及波動目標 20% 的其餘部位換 AAPL。
     用帳本個股格代替半導體再做一次（2023→）。
  6. 2026 年帳上差額。
AAPL 過去報酬是事後挑贏家，報酬欄只供參考；能參考的是它跟半導體一起跌多少。

首跑結論（2026-11-22）：前提對一半——AAPL 波動 25.7% 比帳本個股（37–87%）穩，但是 VOO（14.9%）的 1.7 倍、回撤 −33% vs −19%。
對 SMH 的 β 0.47–0.56，跟 SPY（0.40–0.46）一樣或略高；相關低（0.55 vs 0.80）代表多的是它自己的風險。
2015 年以來 SMH 六段大回撤，2026 以前五段 AAPL 跌得跟 SPY 一樣或更多（2015 −20% vs −11%、2024–25 −26% vs −11%），只有 2026 這次逆勢 +15.5%。
VOO 換 10% 成 AAPL：最大回撤不變（2010→ −39.3% vs −39.4%；帳本個股格 2023→ −29.6% vs −29.2%），年化多 1.6pp 全來自 AAPL 自己的報酬（事後挑贏家）。
AAPL 自己 2006 年以來 8 次 ≥25% 回撤，2012–13 那次 −44% 時 SPY +8%。不是降回撤工具，是選股；要買走正常進場流程。
Run: python3 tools/backtests/aapl_steady_tech_2026-11-22.py
Output: tools/backtests/data/aapl_steady_tech_2026-11-22.out.txt
"""
import os
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import yfinance as yf

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "aapl_steady_tech_2026-11-22.out.txt")
_lines = []


def p(s=""):
    print(s)
    _lines.append(s)


# 帳本個股格：research/position-state.json 2026-11-22 的權重（不含 VOO、XLE）
BOOK = {"AMAT": 2.28, "ANET": 4.38, "AVGO": 4.64, "CRDO": 1.05, "CRM": 5.9, "CRWD": 9.9, "DIOD": 3.66, "MU": 6.57,
        "NET": 2.07, "NVDA": 5.36, "PLTR": 6.84, "SNPS": 5.57, "TWLO": 3.2}
SYMS = ["SMH", "SPY", "VOO", "QQQ", "AAPL", "MSFT", "^IRX"] + list(BOOK)
C = yf.download(SYMS, start="1999-01-01", end="2026-11-21", progress=False, auto_adjust=True)["Close"]
R = C.pct_change()
rf_all = ((C["^IRX"] / 100).ffill().fillna(0.03) / 252)
wb = pd.Series(BOOK) / sum(BOOK.values())
book = (R[list(BOOK)][R.index >= "2023-01-01"] * wb).sum(axis=1)  # 每日再平衡到現在的權重


def metrics(ret, rfd):
    ret = np.asarray(ret, float)
    rfd = np.asarray(rfd, float)
    eq = np.cumprod(1 + ret)
    cagr = eq[-1] ** (252 / len(ret)) - 1
    mdd = (eq / np.maximum.accumulate(eq) - 1).min()
    ex = ret - rfd
    return cagr, ret.std() * np.sqrt(252), mdd, ex.mean() / ex.std() * np.sqrt(252), cagr / abs(mdd)


def fmt(m):
    return f"{m[0] * 100:+6.1f}% {m[1] * 100:5.1f}% {m[2] * 100:6.1f}% {m[3]:6.2f} {m[4]:6.2f}"


def vt_exposure(ret, target=0.20):
    vol = ret.rolling(20).std() * np.sqrt(252)
    raw_ = (target / vol).clip(upper=1.0).fillna(1.0)
    wk = raw_.where(raw_.index.weekday == 4).ffill().fillna(1.0)
    held = [1.0]
    for v_ in wk.iloc[1:]:
        held.append(v_ if abs(v_ - held[-1]) >= 0.10 else held[-1])
    return pd.Series(held, index=ret.index).shift(1).fillna(1.0)


p("AAPL「科技股裡較穩，配一點」能不能少跌      資料到 2026-11-20")
p("=" * 100)

# ── 1 前提
p("\n1. 前提驗證：AAPL 比帳本裡的個股穩嗎（2023-01→）")
p(f"   {'標的':<6}{'年化波動':>8}{'最大回撤':>9}{'2026 高點至今':>12}")
rows = []
for s in ["VOO", "QQQ", "AAPL", "MSFT", "SMH"] + list(BOOK):
    r = R[s][R.index >= "2023-01-01"].dropna()
    c = C[s].dropna()
    c26 = c[c.index >= "2026-01-01"]
    eq = (1 + r).cumprod()
    rows.append((s, r.std() * np.sqrt(252), (eq / eq.cummax() - 1).min(), c26.iloc[-1] / c26.max() - 1))
for s, vol, mdd, d26 in sorted(rows, key=lambda x: x[1]):
    p(f"   {s:<6}{vol * 100:>9.1f}%{mdd * 100:>9.1f}%{d26 * 100:>12.1f}%")

# ── 2 單獨比
p("\n2. 單獨比（年化／波動／最大回撤／Sharpe／Calmar）與對 SMH 的日相關、β")
for wn, st in {"2000-07→": "2000-07-01", "2010→": "2010-01-01", "2020→": "2020-01-01", "2026 年初→": "2026-01-01"}.items():
    p(f"  【{wn}】")
    for s in ("SMH", "SPY", "QQQ", "AAPL", "MSFT"):
        r = R[s][R.index >= st].dropna()
        x = pd.concat([r, R["SMH"].reindex(r.index)], axis=1).dropna()
        p(f"     {s:<5} {fmt(metrics(r, rf_all.reindex(r.index)))}   對 SMH 相關 {x.iloc[:, 0].corr(x.iloc[:, 1]):.2f}、"
          f"β {x.iloc[:, 0].cov(x.iloc[:, 1]) / x.iloc[:, 1].var():.2f}")
p("  【對帳本個股格（13 檔照現在權重），2023-01→／只看 2026】")
for s in ("SPY", "QQQ", "AAPL", "MSFT", "SMH"):
    out = f"     {s:<5}"
    for st in ("2023-01-01", "2026-01-01"):
        x = pd.concat([R[s], book], axis=1).dropna()
        x = x[x.index >= st]
        out += f" 相關 {x.iloc[:, 0].corr(x.iloc[:, 1]):.2f}、β {x.iloc[:, 0].cov(x.iloc[:, 1]) / x.iloc[:, 1].var():.2f} ｜"
    p(out)

# ── 3 SMH 大回撤
p("\n3. SMH 每一段 ≥20% 的回撤（高點→低點），同一段日子裡的報酬")
smh = C["SMH"].dropna()
smh = smh[smh.index >= "2003-01-01"]
episodes = []
peak_i, trough_i, in_dd = 0, 0, False
v = smh.values
for i in range(1, len(v)):
    if v[i] >= v[peak_i]:
        if in_dd and v[trough_i] / v[peak_i] - 1 <= -0.20:
            episodes.append((peak_i, trough_i))
        peak_i, trough_i, in_dd = i, i, False
    else:
        in_dd = True
        if v[i] < v[trough_i] or trough_i == peak_i:
            trough_i = i
if in_dd and v[trough_i] / v[peak_i] - 1 <= -0.20:
    episodes.append((peak_i, trough_i))
p(f"   {'高點':<11}{'低點':<11}{'SMH':>8}{'SPY':>8}{'QQQ':>8}{'AAPL':>8}{'MSFT':>8}   AAPL−SPY")
d_a, d_m = [], []
for a, b in episodes:
    da, db = smh.index[a], smh.index[b]
    vals = {s: C[s][db] / C[s][da] - 1 for s in ("SMH", "SPY", "QQQ", "AAPL", "MSFT")}
    d_a.append(vals["AAPL"] - vals["SPY"])
    d_m.append(vals["MSFT"] - vals["SPY"])
    p(f"   {da.strftime('%Y-%m-%d'):<11}{db.strftime('%Y-%m-%d'):<11}" + "".join(f"{vals[s] * 100:>+7.1f}%" for s in vals)
      + f"   {d_a[-1] * 100:+6.1f}%")
d_a, d_m = np.array(d_a), np.array(d_m)
p(f"   AAPL 比 SPY：平均 {d_a.mean() * 100:+.1f}%、中位 {np.median(d_a) * 100:+.1f}%、跌得比 SPY 少 {int((d_a > 0).sum())}/{len(d_a)} 段；"
  f"MSFT 比 SPY：平均 {d_m.mean() * 100:+.1f}%、少 {int((d_m > 0).sum())}/{len(d_m)} 段")

# ── 4 AAPL 自己的回撤
p("\n4. AAPL 自己 ≥25% 的回撤（2003→），同一段 SPY／SMH 的報酬")
ap = C["AAPL"].dropna()
ap = ap[ap.index >= "2003-01-01"]
v = ap.values
eps = []
peak_i, trough_i, in_dd = 0, 0, False
for i in range(1, len(v)):
    if v[i] >= v[peak_i]:
        if in_dd and v[trough_i] / v[peak_i] - 1 <= -0.25:
            eps.append((peak_i, trough_i, i))
        peak_i, trough_i, in_dd = i, i, False
    else:
        in_dd = True
        if v[i] < v[trough_i] or trough_i == peak_i:
            trough_i = i
if in_dd and v[trough_i] / v[peak_i] - 1 <= -0.25:
    eps.append((peak_i, trough_i, None))
for a, b, rec in eps:
    da, db = ap.index[a], ap.index[b]
    p(f"   {da.strftime('%Y-%m-%d')} → {db.strftime('%Y-%m-%d')}  AAPL {(v[b] / v[a] - 1) * 100:+6.1f}%  SPY {(C['SPY'][db] / C['SPY'][da] - 1) * 100:+6.1f}%"
      f"  SMH {(C['SMH'][db] / C['SMH'][da] - 1) * 100:+6.1f}%  回到前高 {'還沒' if rec is None else f'{rec - a} 個交易日'}")

# ── 5 配一點
p("\n5. 配一點（年化／波動／最大回撤／Sharpe／Calmar）")
MIX = {
    "70 半導體＋30 VOO（底）": {"core": 0.7, "SPY": 0.3},
    "70 半導體＋20 VOO＋10 AAPL": {"core": 0.7, "SPY": 0.2, "AAPL": 0.1},
    "70 半導體＋10 VOO＋20 AAPL": {"core": 0.7, "SPY": 0.1, "AAPL": 0.2},
    "60 半導體＋30 VOO＋10 AAPL": {"core": 0.6, "SPY": 0.3, "AAPL": 0.1},
    "60 半導體＋40 VOO（對照）": {"core": 0.6, "SPY": 0.4},
    "70 半導體＋20 VOO＋10 MSFT": {"core": 0.7, "SPY": 0.2, "MSFT": 0.1},
    "70 半導體＋20 VOO＋10 國庫券": {"core": 0.7, "SPY": 0.2, "bill": 0.1},
    "70 半導體＋30 國庫券": {"core": 0.7, "bill": 0.3},
}


def mix_ret(core, idx, w):
    r = pd.Series(0.0, index=idx)
    for k, x in w.items():
        src = core if k == "core" else (rf_all if k == "bill" else R[k])
        r = r + x * src.reindex(idx).fillna(0)
    return r


for label, core, st in (("半導體＝SMH，2000-07→", R["SMH"], "2000-07-01"), ("半導體＝SMH，2010→", R["SMH"], "2010-01-01"),
                        ("半導體＝SMH，2020→", R["SMH"], "2020-01-01"), ("改用帳本個股格，2023→", book, "2023-01-01"),
                        ("改用帳本個股格，只看 2026", book, "2026-01-01")):
    idx = R.index[R.index >= st]
    rf = rf_all.reindex(idx)
    p(f"  【{label}】")
    for nm, w in MIX.items():
        p(f"     {nm:<28} {fmt(metrics(mix_ret(core, idx, w), rf))}")
    w = vt_exposure(core.reindex(idx).fillna(0))
    for rn, rr in (("VOO", R["SPY"]), ("AAPL", R["AAPL"]), ("半 VOO 半 AAPL", 0.5 * R["SPY"] + 0.5 * R["AAPL"]), ("國庫券", rf_all)):
        r = w * core.reindex(idx).fillna(0) + (1 - w) * rr.reindex(idx).fillna(0)
        r.iloc[1:] -= np.abs(np.diff(w.values)) * 0.001
        p(f"     {'波動目標 20%，其餘放 ' + rn:<28} {fmt(metrics(r, rf))}")

# ── 6 2026
p("\n6. 2026 年帳上：VOO 換 $20,000 成 AAPL／MSFT／QQQ／國庫券 會差多少")
for lab, st in (("年初起", "2025-12-31"), ("6/22 帳戶高點起", "2026-06-22"), ("10/21 這批 VOO 買進日起", "2026-10-21")):
    row = f"   {lab:<16}"
    vals = {}
    for s in ("SMH", "VOO", "QQQ", "AAPL", "MSFT"):
        c = C[s].dropna()
        vals[s] = c.iloc[-1] / c[c.index <= st].iloc[-1] - 1
        row += f" {s} {vals[s] * 100:+6.1f}%"
    bill = (1 + rf_all[rf_all.index > st]).prod() - 1
    row += " | 差額 " + "、".join(f"{s} ${(vals[s] - vals['VOO']) * 20000:+,.0f}" for s in ("AAPL", "MSFT", "QQQ")) + f"、國庫券 ${(bill - vals['VOO']) * 20000:+,.0f}"
    p(row)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(_lines) + "\n")
