#!/usr/bin/env python3
"""第一部分：帳戶實際淨值標記（equity-marks.json, kind=total, excluded=false）上套各種對沖覆蓋。
只讀 repo，輸出到本目錄 part1_*.csv / part1_results.json。"""
import json, re, os, glob, math, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from statistics import NormalDist
N = NormalDist().cdf
from pathlib import Path
REPO = str(Path(__file__).resolve().parents[3])
OUT = os.path.dirname(os.path.abspath(__file__))
STOCK_FRAC = 231200 / 242997           # 股票市值 / 總值（主程數字）
BETA_SMH_MAIN, BETA_SPY_MAIN = 0.835, 2.62

def bs_put(S, K, T, r, sig):
    if T <= 0: return max(0.0, K - S)
    d1 = (math.log(S / K) + (r + sig * sig / 2) * T) / (sig * math.sqrt(T)); d2 = d1 - sig * math.sqrt(T)
    return K * math.exp(-r * T) * N(-d2) - S * N(-d1)

def implied_vol(price_fn, target, lo=0.05, hi=2.0):
    for _ in range(80):
        mid = (lo + hi) / 2
        if price_fn(mid) < target: lo = mid
        else: hi = mid
    return (lo + hi) / 2

# ---------- 1. 標記 ----------
d = json.load(open(f"{REPO}/research/equity-marks.json"))
marks = [m for m in d["marks"] if not m.get("excluded") and m.get("kind") == "total"]
mk = pd.Series({pd.Timestamp(m["date"]): float(m["value"]) for m in marks}).sort_index()
# 連續兩個標記值完全相同（10/05=10/06、10/18=10/19）→ 後者是抄前日的陳舊值，刪掉
dup = mk[(mk.diff() == 0)]
mk = mk[~mk.index.isin(dup.index)]
print(f"標記 {len(mk)} 點 {mk.index[0].date()} → {mk.index[-1].date()}（刪除陳舊重複 {list(dup.index.date)}）")

px = yf.download(["SMH", "SPY", "QQQ", "VOO", "^IRX"], start="2026-01-01", end="2026-10-24", progress=False, auto_adjust=True)["Close"].ffill()
# 非交易日標記（週日 10/18）→ 用前一收盤
al = px.reindex(px.index.union(mk.index)).ffill().loc[mk.index]
df = pd.DataFrame({"acct": mk})
for s in ("SMH", "SPY", "QQQ", "VOO"): df[s] = al[s]
df["irx"] = al["^IRX"] / 100
seg = df.pct_change().dropna()[["acct", "SMH", "SPY", "QQQ", "VOO"]]
seg["days"] = np.diff(df.index.values).astype("timedelta64[D]").astype(int)
seg["rf"] = (df["irx"].shift(1).loc[seg.index] * seg["days"] / 365).values
years = (df.index[-1] - df.index[0]).days / 365.25
segs_per_year = len(seg) / years
seg.to_csv(f"{OUT}/part1_segments.csv")

# ---------- 2. 回歸 ----------
def ols(y, x):
    X = np.column_stack([np.ones(len(x)), x]); b, res, *_ = np.linalg.lstsq(X, y, rcond=None)
    yhat = X @ b; r2 = 1 - ((y - yhat) ** 2).sum() / ((y - y.mean()) ** 2).sum() if len(y) > 2 else np.nan
    return b[1], b[0], r2
reg = {}
for b in ("SMH", "SPY", "QQQ"):
    ya, xa = (seg["acct"] - seg["rf"]).values, (seg[b] - seg["rf"]).values
    beta, alpha, r2 = ols(ya, xa)
    up = seg[b] > 0; dn = ~up
    bu, _, _ = ols(ya[up.values], xa[up.values]); bd, _, _ = ols(ya[dn.values], xa[dn.values])
    reg[b] = dict(beta=beta, alpha_per_seg=alpha, alpha_ann=alpha * segs_per_year, r2=r2, beta_up=bu, beta_down=bd,
                  n_up=int(up.sum()), n_down=int(dn.sum()), capture=bu / bd if bd else np.nan)
print("\n回歸（段報酬，超額對超額）")
for b, v in reg.items():
    print(f"  對 {b}: β={v['beta']:.2f}  上漲段β={v['beta_up']:.2f} 下跌段β={v['beta_down']:.2f} (n={v['n_up']}/{v['n_down']})  α年化={v['alpha_ann']:+.1%}  R²={v['r2']:.2f}")
print(f"  主程日頻 180 天：SMH 0.835 / SPY 2.62。段頻 β 差異原因：段長 1–7 天混合、標記含盤中（briefing 11:00）與收盤（journal）混雜、n={len(seg)} 段。")
beta_smh, beta_spy = reg["SMH"]["beta"], reg["SPY"]["beta"]

# ---------- 3. 統計 ----------
def stats(r):
    """r: 段報酬 Series（與 seg 同 index）"""
    eq = (1 + r).cumprod(); tot = eq.iloc[-1] - 1
    vol = r.std() * math.sqrt(segs_per_year)
    ex = (r - seg["rf"]).mean() * segs_per_year
    sh = ex / vol if vol > 0 else np.nan
    mdd = (eq / eq.cummax() - 1).min()
    pf = r[r > 0].sum() / abs(r[r < 0].sum()) if (r < 0).any() else np.inf
    def win(a, b):
        e = pd.concat([pd.Series([1.0], index=[df.index[0]]), eq]); e = e[(e.index >= a) & (e.index <= b)]
        return e.iloc[-1] / e.iloc[0] - 1 if len(e) > 1 else np.nan
    # 回撤窗以窗起點標記（6/22、10/07）為基準，到窗終點標記
    i0 = df.index.get_indexer([pd.Timestamp("2026-06-22")])[0]; i1 = df.index.get_indexer([pd.Timestamp("2026-07-28")])[0]
    j0 = df.index.get_indexer([pd.Timestamp("2026-10-07")])[0]; j1 = df.index.get_indexer([pd.Timestamp("2026-10-16")])[0]
    full = pd.concat([pd.Series([1.0], index=[df.index[0]]), eq])
    w1 = full.iloc[i1] / full.iloc[i0] - 1; w2 = full.iloc[j1] / full.iloc[j0] - 1
    return dict(total=tot, ann_vol=vol, sharpe=sh, mdd=mdd, pf=pf, w_0622_0728=w1, w_1007_1016=w2, n_neg=int((r < 0).sum()))

rows = {}; legs = {}
acct = seg["acct"]
rows["0 帳戶原樣"] = stats(acct)
rows["0b SMH 買抱"] = stats(seg["SMH"]); rows["0c SPY 買抱"] = stats(seg["SPY"]); rows["0d QQQ 買抱"] = stats(seg["QQQ"])

# (i)(ii) 空 ETF β 對沖：名目/淨值 = h × β × 股票占比；成本借券 0.5%/年（融資利息省略；與不開槓桿硬線衝突）
for bench, beta in (("SMH", beta_smh), ("SPY", beta_spy)):
    for h in (0.25, 0.5, 1.0):
        n = h * beta * STOCK_FRAC
        r = acct - n * seg[bench] - n * 0.005 * seg["days"] / 365
        key = f"{'i' if bench=='SMH' else 'ii'} 空{bench} h={h:.2f}（名目 {n:.0%} 淨值）"; rows[key] = stats(r); legs[key] = r - acct

# (iii) 買 SMH 價外 put，60 曆日滾；名目 = β_SMH × 股票市值；到期按內含價值，期中 BS（IV = 開倉權利金隱含、固定）
def put_overlay(otm, prem_pct, roll_days=60, notional_frac=None):
    nf = notional_frac if notional_frac is not None else beta_smh * STOCK_FRAC
    dates = df.index; S = df["SMH"].values; irx = df["irx"].values
    T0 = roll_days / 365
    hist = []  # 每段的覆蓋 PnL（占淨值比）
    k = None; mtm_prev = 0.0
    for i in range(len(dates)):
        pnl = 0.0
        if k is not None:
            # 先把到期日前的部位結算 / MTM
            days_left = (k["exp"] - dates[i]).days
            if days_left <= 0:
                val = max(0.0, k["K"] - S[i]) / k["S0"]      # 內含價值（每 1 元名目）
                k = None
            else:
                val = bs_put(S[i], k["K"], days_left / 365, irx[i], k["iv"]) / k["S0"]
            pnl += (val - mtm_prev) * nf
            mtm_prev = val if k is not None else 0.0
        if k is None and (i == 0 or days_left <= 0):
            S0 = S[i]; K = S0 * (1 - otm)
            iv = implied_vol(lambda s: bs_put(S0, K, T0, irx[i], s) / S0, prem_pct)
            k = dict(S0=S0, K=K, exp=dates[i] + pd.Timedelta(days=roll_days), iv=iv)
            pnl -= prem_pct * nf        # 付權利金
            mtm_prev = prem_pct         # 以成本入帳
            if i == 0: first_iv = iv
        hist.append(pnl)
    ov = pd.Series(hist, index=dates)
    return (acct + ov.iloc[1:]), first_iv
r, iv = put_overlay(0.10, 0.019); key = f"iii 買SMH 10%價外put 60日滾 1.9%（隱含IV {iv:.0%}）"; rows[key] = stats(r); legs[key] = r - acct
r, iv = put_overlay(0.05, 0.032); key = f"iii 買SMH 5%價外put 60日滾 3.2%（隱含IV {iv:.0%}）"; rows[key] = stats(r); legs[key] = r - acct

# (iv) 賣權價差 −10/−25，5 個月（150 曆日）滾，成本 2.2% 名目；單一週期未到期 → 期末 MTM（BS，IV 以 2.2% 反推）
def spread_overlay(prem_pct=0.022, roll_days=150, lo=0.90, hi=0.75):
    nf = beta_smh * STOCK_FRAC; dates = df.index; S = df["SMH"].values; irx = df["irx"].values; T0 = roll_days / 365
    hist = []; k = None; mtm_prev = 0.0
    def sp(S_, k_, T, r_, iv): return (bs_put(S_, k_["K1"], T, r_, iv) - bs_put(S_, k_["K2"], T, r_, iv)) / k_["S0"]
    for i in range(len(dates)):
        pnl = 0.0
        if k is not None:
            dl = (k["exp"] - dates[i]).days
            if dl <= 0: val = (max(0.0, k["K1"] - S[i]) - max(0.0, k["K2"] - S[i])) / k["S0"]; k = None
            else: val = sp(S[i], k, dl / 365, irx[i], k["iv"])
            pnl += (val - mtm_prev) * nf; mtm_prev = val if k is not None else 0.0
        if k is None and (i == 0 or dl <= 0):
            S0 = S[i]; kk = dict(S0=S0, K1=S0 * lo, K2=S0 * hi, exp=dates[i] + pd.Timedelta(days=roll_days))
            kk["iv"] = implied_vol(lambda s: sp(S0, kk, T0, irx[i], s), prem_pct, 0.05, 0.9); k = kk
            pnl -= prem_pct * nf; mtm_prev = prem_pct
            if i == 0: first_iv = kk["iv"]
        hist.append(pnl)
    return acct + pd.Series(hist, index=dates).iloc[1:], first_iv
r, iv = spread_overlay(); key = f"iv 賣權價差 −10/−25 5月滾 2.2%（隱含IV {iv:.0%}；單週期未到期，期末MTM）"; rows[key] = stats(r); legs[key] = r - acct

# (v) 空個股多指數 pair sleeve：10% 市值 空「90 日對板塊最弱 2 檔」（put 複製，成本 25%/年名目，線性短倉近似）+ 10% 多 VOO，每月換
def journal_holdings(date):
    files = sorted(glob.glob(f"{REPO}/journal/2026-*.md"))
    cands = [f for f in files if os.path.basename(f)[:10] >= date][:6]
    for f in cands:
        txt = open(f, encoding="utf-8").read().splitlines(); names = set(); in_tab = False
        for ln in txt:
            if ln.startswith("|") and ("股數" in ln or "市值" in ln or "桶" in ln) and "標的" in ln: in_tab = True; continue
            if in_tab and not ln.startswith("|"): in_tab = False; continue
            if in_tab:
                cells = [c.strip() for c in ln.strip("|").split("|")]
                if len(cells) > 2 and re.fullmatch(r"[A-Z]{1,5}", cells[0]):
                    vals = [float(v.replace(",", "")) for v in re.findall(r"\$([\d,]+)", ln)]
                    nums = [float(c.replace(",", "")) for c in cells[1:3] if re.fullmatch(r"[\d.,]+", c)]
                    ok = (vals and max(vals) >= 1000) or (nums and nums[0] >= 1) or (cells[1] in ("信念", "認列", "樂透") and re.fullmatch(r"[\d.]+", cells[2]) and float(cells[2]) >= 1)
                    if ok: names.add(cells[0])
        names -= {"SGOV", "GLD", "XLE", "VOO", "BIL", "TMF", "IBB", "KWEB", "LEAPS", "PUT", "CALL", "SPY", "QQQ", "SMH"}
        if len(names) >= 10: return os.path.basename(f)[:10], sorted(names)
    return None, []
SECTOR = {"SMH": {"MU", "AVGO", "NVDA", "AMD", "SNPS", "LRCX", "AMAT", "ON", "CRDO", "ONTO", "ARM", "QCOM", "ICHR", "DIOD", "CIEN", "COHR", "LITE", "ANET", "CLS", "SMCI", "VRT"},
          "IGV": {"CRWD", "PLTR", "CRM", "DDOG", "TWLO", "NET", "MDB", "GOOGL", "META", "MSFT"}}
def sector_etf(t): return next((k for k, v in SECTOR.items() if t in v), "SPY")
month_starts = ["2026-06-02", "2026-07-01", "2026-08-03", "2026-09-01", "2026-10-01"]
hold = {m: journal_holdings(m) for m in month_starts}
all_names = sorted({n for _, (_, ns) in hold.items() for n in ns})
hp = yf.download(all_names + ["IGV"], start="2026-01-01", end="2026-10-24", progress=False, auto_adjust=True)["Close"].ffill()
failed = [n for n in all_names if n not in hp.columns or hp[n].dropna().empty]
hp = pd.concat([hp, px[["SMH", "SPY"]]], axis=1).ffill()
weak_log = []; short_ret = pd.Series(0.0, index=seg.index); pair_ret = pd.Series(0.0, index=seg.index)
for mi, m in enumerate(month_starts):
    src, names = hold[m]; names = [n for n in names if n not in failed]
    m0 = pd.Timestamp(m); m1 = pd.Timestamp(month_starts[mi + 1]) if mi + 1 < len(month_starts) else df.index[-1] + pd.Timedelta(days=1)
    i0 = hp.index.get_indexer([m0], method="pad")[0]; i90 = max(0, i0 - 63)
    rs = {n: hp[n].iloc[i0] / hp[n].iloc[i90] - 1 - (hp[sector_etf(n)].iloc[i0] / hp[sector_etf(n)].iloc[i90] - 1) for n in names}
    weak = sorted(rs, key=rs.get)[:2]
    weak_log.append(dict(month=m, journal=src, n_names=len(names), weak=weak, rs={w: round(rs[w], 3) for w in weak}))
    msk = (seg.index > m0) & (seg.index <= m1 - pd.Timedelta(days=0)) if mi else (seg.index <= m1)
    msk = (seg.index > m0) & (seg.index < m1) if mi else (seg.index < m1)
    for t in seg.index[msk]:
        prev = df.index[df.index.get_loc(t) - 1]
        rw = np.mean([hp[w].reindex(hp.index.union([prev, t])).ffill().loc[t] / hp[w].reindex(hp.index.union([prev, t])).ffill().loc[prev] - 1 for w in weak])
        cost = 0.25 * seg.loc[t, "days"] / 365
        short_ret.loc[t] = -rw - cost                   # 空腿本身（每 1 元名目）
        pair_ret.loc[t] = 0.10 * (-rw - cost) + 0.10 * seg.loc[t, "VOO"]   # 10% 空弱 + 10% 多 VOO
json.dump(weak_log, open(f"{OUT}/part1_pair_weak_log.json", "w"), ensure_ascii=False, indent=1)
print("\n(v) 每月最弱兩檔：", [(w["month"], w["weak"]) for w in weak_log], " 下載失敗：", failed)
rows["v 空腿本身（空最弱2檔 −25%/年成本，1元名目）"] = stats(short_ret); legs["v 空腿本身"] = short_ret; legs["v pair sleeve 腿（10%空弱+10%VOO）"] = pair_ret
rows["v pair sleeve：10%空最弱2檔 + 10%多VOO（原持倉降為 80%）"] = stats(0.8 * acct + pair_ret)
rows["v pair sleeve 疊加版：100%帳戶 + 10%空弱 + 10%多VOO（需融資）"] = stats(acct + pair_ret)

# (vi) 對照
rows["vi 10% 換 VOO"] = stats(0.9 * acct + 0.1 * seg["VOO"])
rows["vi 20% 換 VOO"] = stats(0.8 * acct + 0.2 * seg["VOO"])
rows["vi 20% 放 T-bill"] = stats(0.8 * acct + 0.2 * seg["rf"])

legstat = {k: dict(rho_vs_acct=float(np.corrcoef(v, acct)[0, 1]), sigma_H_ann=float(v.std() * math.sqrt(segs_per_year)), mean_ann=float(v.mean() * segs_per_year)) for k, v in legs.items()}
json.dump(legstat, open(f"{OUT}/part1_leg_rho.json", "w"), ensure_ascii=False, indent=1)
print("\n腿本身：與帳戶段報酬的相關 ρ / 年化 σ_H / 年化均值")
for k, v in legstat.items(): print(f"  {k[:45]:<45} ρ={v['rho_vs_acct']:+.2f}  σ_H={v['sigma_H_ann']:.1%}  均值={v['mean_ann']:+.1%}")
tab = pd.DataFrame(rows).T
tab.to_csv(f"{OUT}/part1_overlays.csv")
json.dump(dict(regression=reg, years=years, n_seg=len(seg), segs_per_year=segs_per_year, stock_frac=STOCK_FRAC,
               rows={k: {kk: (None if (isinstance(vv, float) and not np.isfinite(vv)) else vv) for kk, vv in v.items()} for k, v in rows.items()}),
          open(f"{OUT}/part1_results.json", "w"), ensure_ascii=False, indent=1, default=float)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 70)
print(f"\n樣本 {years*12:.1f} 個月，{len(seg)} 段，年化用 {segs_per_year:.0f} 段/年")
print(tab.to_string(float_format=lambda x: f"{x:+.3f}" if abs(x) < 10 else f"{x:.0f}"))
