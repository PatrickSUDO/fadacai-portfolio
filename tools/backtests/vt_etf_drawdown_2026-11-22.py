"""VT（Vanguard 全世界股票 ETF）放進來能不能少跌——拿目前測過的降回撤做法，把「停泊／其餘部位」從 VOO 換成 VT 重跑
（2026-11-22 用戶「目前所有減少 dd 的研究若考慮使用 vt etf 有沒有幫助，或加入配置」）。

既有結論（README 2026-11-20 一節）：回撤全部是曝險（帳本對 SMH 的 β 0.75）；固定比例是線性交換；
唯一拉開 Calmar 的是波動目標而且其餘部位要放國庫券，放 VOO 好處消失。
所以 VT 有沒有用只看一件事：半導體大跌時，VT 跌得比 VOO 少嗎（比較像國庫券還是比較像 VOO）。

做法
  1. VT／VOO（SPY 代）／VXUS（美國以外）／國庫券 單獨比：年化、波動、最大回撤、Sharpe、Calmar；對 SMH 的相關與 β。
  2. SMH 每一段 ≥20% 的回撤（高點→低點）同一段日子裡，各停泊資產的報酬。
  3. 既有降回撤做法換停泊資產：固定 70／30、50／50、波動目標 20%／25%、200 日線下半倉；
     其餘部位放 VOO／VT／國庫券／一半 VT 一半國庫券。規則照 strategy_leaderboard_2026-11-20.py 原樣。
  4. 把歷史拉長：VT 2008-06 才上市，用 55% SPY＋45% EFA 當替身（2001-09→，含 2001–02 熊市），先驗替身像不像。
  5. 2026 年：年初起、6/22 帳戶高點起，VOO 換成 VT 帳上差多少（停泊部位 85 股 VOO ≈ $54k）。
  6. 配息：近 12 個月殖利率 × 30% 預扣。
半導體報酬：SMH 含息。資料到 2026-11-20。

首跑結論（2026-11-22）：沒有幫助。VT 對 SPY 日相關 0.95、β 0.99，對 SMH 的相關與 β（0.76–0.81／0.41–0.50）跟 SPY 一樣。
SMH 九段 ≥20% 回撤裡 VT 有七段跌得比 SPY 多（平均多 1.5pp；2026-06-22 起 −9.6% vs −7.1%）。
既有做法把其餘部位從 VOO 換 VT（2008-07→／2010→／2020→ 共 18 格）：年化少 0.1–1.9pp、最大回撤深 0.4–1.6pp；
替身拉到 2001-09 的 6 格打平（年化差 −0.6 到 +0.1pp、回撤一樣深）；
有降回撤的只有其餘部位放國庫券（波動目標 20% 2010→ 回撤 −25.6% vs 放 VOO −35.4%、放 VT −36.5%）。
長期 VT 年化 +8.1% vs SPY +11.6%（2008-07→），配息預扣每年多拖 0.18pp。不採用、不加入配置。
Run: python3 tools/backtests/vt_etf_drawdown_2026-11-22.py
Output: tools/backtests/data/vt_etf_drawdown_2026-11-22.out.txt
"""
import os
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import yfinance as yf

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "vt_etf_drawdown_2026-11-22.out.txt")
_lines = []


def p(s=""):
    print(s)
    _lines.append(s)


SYMS = ["SMH", "SPY", "VOO", "VT", "VXUS", "EFA", "QQQ", "^IRX"]
dl = yf.download(SYMS, start="1999-01-01", end="2026-11-21", progress=False, auto_adjust=True)
C = dl["Close"]
R = C.pct_change()
rf_all = ((C["^IRX"] / 100).ffill().fillna(0.03) / 252)


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


def vt_exposure(ret, price, target=0.20, trend=False, vt=True):
    """strategy_leaderboard 的規則原樣：曝險 = min(1, 目標 ÷ 20 日實現波動)，週五決定、變動 <10% 不動；trend = 200 日線下減半；隔日生效。"""
    exp = pd.Series(1.0, index=ret.index)
    if vt:
        vol = ret.rolling(20).std() * np.sqrt(252)
        raw_ = (target / vol).clip(upper=1.0).fillna(1.0)
        wk = raw_.where(raw_.index.weekday == 4).ffill().fillna(1.0)
        held = [1.0]
        for v_ in wk.iloc[1:]:
            held.append(v_ if abs(v_ - held[-1]) >= 0.10 else held[-1])
        exp = pd.Series(held, index=ret.index)
    if trend:
        exp = exp * (price > price.rolling(200).mean()).astype(float).replace(0.0, 0.5)
    return exp.shift(1).fillna(1.0)


p("VT（全世界股票 ETF）能不能幫忙少跌      資料到 2026-11-20")
p("=" * 100)

# ── 1 單獨比
p("\n1. 單獨比（年化／波動／最大回撤／Sharpe／Calmar），以及對 SMH 的日相關、β")
WINS = {"2008-07→": "2008-07-01", "2011-02→（VXUS 上市後）": "2011-02-01", "2020→": "2020-01-01", "2026 年初→": "2026-01-01"}
for wn, st in WINS.items():
    p(f"  【{wn}】")
    for s in ("SMH", "SPY", "VT", "VXUS", "QQQ"):
        r = R[s][R.index >= st].dropna()
        if len(r) < 100 or r.index[0] > pd.Timestamp(st) + pd.Timedelta(days=10):
            continue
        rf = rf_all.reindex(r.index)
        x = pd.concat([r, R["SMH"].reindex(r.index)], axis=1).dropna()
        corr = x.iloc[:, 0].corr(x.iloc[:, 1])
        beta = x.iloc[:, 0].cov(x.iloc[:, 1]) / x.iloc[:, 1].var()
        p(f"     {s:<5} {fmt(metrics(r, rf))}   對 SMH 相關 {corr:.2f}、β {beta:.2f}")
x = pd.concat([R["VT"], R["SPY"]], axis=1).dropna()
p(f"   VT 對 SPY：日相關 {x['VT'].corr(x['SPY']):.3f}、β {x['VT'].cov(x['SPY']) / x['SPY'].var():.2f}")

# ── 2 SMH 大回撤期間
p("\n2. SMH 每一段 ≥20% 的回撤（高點→低點），同一段日子裡各資產的報酬")
smh = C["SMH"].dropna()
smh = smh[smh.index >= "2008-06-26"]
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
p(f"   {'高點':<11}{'低點':<11}{'SMH':>8}{'SPY':>8}{'VT':>8}{'VXUS':>8}{'國庫券':>7}   VT−SPY")
diffs = []
for a, b in episodes:
    da, db = smh.index[a], smh.index[b]
    row = f"   {da.strftime('%Y-%m-%d'):<11}{db.strftime('%Y-%m-%d'):<11}"
    vals = {}
    for s in ("SMH", "SPY", "VT", "VXUS"):
        c = C[s].dropna()
        if da in c.index and db in c.index:
            vals[s] = c[db] / c[da] - 1
            row += f"{vals[s] * 100:>+7.1f}%"
        else:
            row += f"{'—':>8}"
    bill = (1 + rf_all[(rf_all.index > da) & (rf_all.index <= db)]).prod() - 1
    row += f"{bill * 100:>+6.1f}%"
    if "VT" in vals and "SPY" in vals:
        diffs.append(vals["VT"] - vals["SPY"])
        row += f"   {(vals['VT'] - vals['SPY']) * 100:+5.1f}%"
    p(row)
diffs = np.array(diffs)
p(f"   VT 比 SPY：平均 {diffs.mean() * 100:+.1f}%、跌得比 SPY 少的有 {int((diffs > 0).sum())}/{len(diffs)} 段")

# ── 3 既有做法換停泊資產
p("\n3. 既有降回撤做法，把其餘部位換成 VT（年化／波動／最大回撤／Sharpe／Calmar）")


def run_block(rest_map, start, label):
    idx = R.index[R.index >= start]
    rs = R["SMH"].reindex(idx).fillna(0)
    rf = rf_all.reindex(idx)
    price = C["SMH"].reindex(idx).ffill()
    exps = {
        "半導體 100%": pd.Series(1.0, index=idx),
        "固定 70／30": pd.Series(0.7, index=idx),
        "固定 50／50": pd.Series(0.5, index=idx),
        "波動目標 20%": vt_exposure(rs, price, 0.20),
        "波動目標 25%": vt_exposure(rs, price, 0.25),
        "200 日線下半倉": vt_exposure(rs, price, vt=False, trend=True),
        "波動目標 20%＋200 日線下半倉": vt_exposure(rs, price, 0.20, trend=True),
    }
    p(f"  【{label}】")
    for nm, w in exps.items():
        if nm == "半導體 100%":
            p(f"     {nm:<22}{'':<14} {fmt(metrics(rs, rf))}")
            continue
        for rn, rr in rest_map.items():
            r = w * rs + (1 - w) * rr.reindex(idx).fillna(0)
            r.iloc[1:] -= np.abs(np.diff(w.values)) * 0.001
            p(f"     {nm:<22}其餘放 {rn:<10} {fmt(metrics(r, rf))}   平均半導體 {w.mean() * 100:.0f}%")


REST = {"VOO": R["SPY"], "VT": R["VT"], "國庫券": rf_all, "半VT半國庫券": 0.5 * R["VT"] + 0.5 * rf_all}
run_block(REST, "2008-07-01", "2008-07→（VT 上市後，含金融海嘯）")
run_block(REST, "2010-01-01", "2010→")
run_block(REST, "2020-01-01", "2020→")

# ── 4 替身拉長歷史
p("\n4. 拉長到 2001-09（含 2001–02 熊市）：VT 替身＝55% SPY＋45% EFA")
proxy = 0.55 * R["SPY"] + 0.45 * R["EFA"]
x = pd.concat([R["VT"], proxy], axis=1).dropna()
x.columns = ["vt", "px"]
te = (x["vt"] - x["px"]).std() * np.sqrt(252)
p(f"   替身驗證（2008-07→）：日相關 {x['vt'].corr(x['px']):.3f}、年化追蹤誤差 {te * 100:.1f}%、"
  f"年化 VT {((1 + x['vt']).prod() ** (252 / len(x)) - 1) * 100:+.1f}% vs 替身 {((1 + x['px']).prod() ** (252 / len(x)) - 1) * 100:+.1f}%")
run_block({"VOO": R["SPY"], "VT替身": proxy, "國庫券": rf_all}, "2001-09-01", "2001-09→（替身）")
idx = R.index[(R.index >= "2001-09-01") & (R.index < "2010-01-01")]
p("  【2001-09 到 2009-12 單獨比】")
for nm, r in (("SPY", R["SPY"]), ("VT替身", proxy), ("EFA", R["EFA"]), ("SMH", R["SMH"])):
    p(f"     {nm:<8} {fmt(metrics(r.reindex(idx).fillna(0), rf_all.reindex(idx)))}")

# ── 5 2026
p("\n5. 2026 年實際：停泊部位 85 股 VOO（約 $54,000）如果是 VT")
for lab, st in (("年初起", "2025-12-31"), ("6/22 帳戶高點起", "2026-06-22"), ("10/21 這批 VOO 買進日起", "2026-10-21")):
    row = f"   {lab:<16}"
    vals = {}
    for s in ("SMH", "QQQ", "VOO", "VT", "VXUS"):
        c = C[s].dropna()
        c0 = c[c.index <= st].iloc[-1]
        vals[s] = c.iloc[-1] / c0 - 1
        row += f" {s} {vals[s] * 100:+6.1f}%"
    bill = (1 + rf_all[rf_all.index > st]).prod() - 1
    row += f" 國庫券 {bill * 100:+5.1f}% | $54k 換 VT 差 ${(vals['VT'] - vals['VOO']) * 54000:+,.0f}、換國庫券差 ${(bill - vals['VOO']) * 54000:+,.0f}"
    p(row)
for s in ("VOO", "VT", "VXUS"):
    c = C[s].dropna()
    c = c[c.index >= "2026-01-01"]
    p(f"   {s:<5} 2026 年內最大回撤 {(c / c.cummax() - 1).min() * 100:+.1f}%、目前距年內高點 {(c.iloc[-1] / c.max() - 1) * 100:+.1f}%")

# ── 6 配息
p("\n6. 配息與 30% 預扣（近 12 個月配息 ÷ 現價）")
for s in ("VOO", "VT", "VXUS", "QQQ"):
    try:
        dv = yf.Ticker(s).dividends
        dv = dv[dv.index >= (dv.index[-1] - pd.Timedelta(days=365))]
        px = yf.Ticker(s).history(period="5d", auto_adjust=False)["Close"].iloc[-1]
        y = dv.sum() / px
        p(f"   {s:<5} 殖利率 {y * 100:.2f}% → 預扣 30% 每年拖 {y * 30:.2f}%")
    except Exception as e:  # noqa: BLE001
        p(f"   {s:<5} 配息資料取不到（{type(e).__name__}）")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(_lines) + "\n")
