"""網路流傳表：「標普 500 在 5 個交易日內跌 ≥8% 之後 3／6／12 個月」（NeuroQuant，1956→ 共 17 次，
12 個月中位 +21.5%、上漲 76%）。問題：VOO／QQQ／SMH 有沒有這個特性、能不能用（2026-11-22 用戶）。

做法
  1. 重現原表：^GSPC 收盤，5 日累計 ≤ −8%，40 個交易日內只算第一次；之後 63／126／252 日，從事件日收盤算。
  2. 跟「任意日」比（原表沒放基準）；隨機抽同樣次數的日子 20,000 次算 p。
  3. 同一批事件日看 那斯達克 100（^NDX 1985-10→）、費半（^SOX 1994-05→）；ETF 含息對照 SPY 1993→、QQQ 1999→、SMH 2012→。
  4. 換過去划不划算：事件日之後 NDX／SOX 減 S&P 的超額 vs 任意日的超額。
  5. 各自觸發：各指數自己的 5 日跌幅（固定門檻與「跟 S&P −8% 一樣罕見」的門檻）。
  6. 買了之後還要忍多深、事件當下的狀態（S&P／費半距一年高、VIX）逐筆列出。
  7. 跟既有影子 cf-vix-spike（VIX 首次站上 30）重不重複。
  8. 停泊池試算：平時 SPY，事件日換 QQQ／SMH 抱 252 日再換回。

指數是價格指數（不含息）；ETF 為還原價。事件少（17／13 次），所有數字都是描述性的。

首跑結論（2026-11-22）：原表重現無誤但沒放基準——12 個月上漲 76% vs 任意日 74%，差在幅度與前 3–6 個月
（S&P 3 個月 +7.4%／88% vs +2.1%／66%）。同一批事件日 NDX 3 個月 +12.7%／86%、費半 +15.6%／85%，都明顯高於任意日；
12 個月 NDX、費半跟任意日分不出來，2000／2001 兩次之後一年 −28% 到 −48%。各指數自己的 5 日跌幅當觸發沒有訊號。
1990→ 14 次事件 VIX 全部 ≥30 ＝ 既有影子 cf-vix-spike 的子集。不新增影子、不進閘門。
第 9 節（同日追問「現在升曝險呢」）：自己 5 日大跌分兩種——同時大盤恐慌（NDX 3 個月 +14.7%／92%、費半 +29.9%／86%）
與只有自己跌（NDX 3 個月 +0.6%／38%、費半 6 個月 −2.7%／40%）。最像現在的三條件：NDX 10 次 3 個月 +16.4%／90%，
費半只有 4 次。事件日 $10,000 從 VOO 換 NDX 3 個月平均多 $543、最差少 $606；換費半平均多 $690、最差少 $3,273。
Run: python3 tools/backtests/spx_5d_drop8_2026-11-22.py
Output: tools/backtests/data/spx_5d_drop8_2026-11-22.out.txt
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import yfinance as yf

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "spx_5d_drop8_2026-11-22.out.txt")
HZ = {"3個月": 63, "6個月": 126, "12個月": 252}
GAP = 40
rng = np.random.default_rng(20261122)
_lines = []


def p(s=""):
    print(s)
    _lines.append(s)


raw = yf.download(["^GSPC", "^NDX", "^SOX", "SPY", "QQQ", "SMH", "^VIX"], start="1955-01-01", end="2026-11-21",
                  progress=False, auto_adjust=True)["Close"]
spx = raw["^GSPC"].dropna()
spx = spx[spx.index >= "1956-11-01"]
ndx = raw["^NDX"].dropna()
sox = raw["^SOX"].dropna()
spy = raw["SPY"].dropna()
qqq = raw["QQQ"].dropna()
smh = raw["SMH"].dropna()
smh = smh[smh.index >= "2012-01-01"]
vix = raw["^VIX"].dropna()


def decluster(cond, gap=GAP):
    """條件成立日裡，距上一個『保留事件』超過 gap 個交易日才算新事件。"""
    pos = np.flatnonzero(cond.fillna(False).values)
    keep, last = [], None
    for i in pos:
        if last is None or i - last > gap:
            keep.append(i)
            last = i
    return cond.index[keep]


def fwd(s, days, h):
    """事件日收盤起 h 日後報酬；事件日不在序列或未滿 h 日 → 略過。"""
    out = {}
    for d in days:
        if d in s.index:
            i = s.index.get_loc(d)
            if i + h < len(s):
                out[d] = s.iloc[i + h] / s.iloc[i] - 1
    return pd.Series(out, dtype=float)


def base(s, h):
    return (s.shift(-h) / s - 1).dropna()


def rand_p(b, n, obs_mean, obs_med, draws=20000):
    """隨機抽 n 個日子的平均／中位 ≥ 觀察值的比例（單尾）。"""
    v = b.values
    idx = rng.integers(0, len(v), size=(draws, n))
    smp = v[idx]
    return (smp.mean(1) >= obs_mean).mean(), (np.median(smp, 1) >= obs_med).mean()


def line(label, r, b):
    if len(r) == 0:
        return f"  {label:<8} n=0"
    pm, pmed = rand_p(b, len(r), r.mean(), r.median())
    return (f"  {label:<6} n={len(r):>2}  事件後 平均 {r.mean()*100:+6.1f}% 中位 {r.median()*100:+6.1f}% 上漲 {(r>0).mean()*100:3.0f}%"
            f" 最差 {r.min()*100:+6.1f}%  ｜任意日 平均 {b.mean()*100:+5.1f}% 中位 {b.median()*100:+5.1f}% 上漲 {(b>0).mean()*100:3.0f}%"
            f"  ｜p(平均) {pm:.2f} p(中位) {pmed:.2f}")


# ── 1. 重現原表 ───────────────────────────────────────────────
r5 = spx / spx.shift(5) - 1
ev = decluster(r5 <= -0.08)
p("=== 1. 重現原表（^GSPC，5 日 ≤ −8%，40 日內只算第一次）===")
p(f"事件數 {len(ev)}（原表 17 次＋2026-11-20 這次）")
p(f"{'事件日':<12}{'5日':>7}{'3個月':>8}{'6個月':>8}{'12個月':>8}")
for d in ev:
    row = f"{d.date()!s:<12}{r5[d]*100:>+6.1f}%"
    for h in HZ.values():
        f = fwd(spx, [d], h)
        row += f"{f.iloc[0]*100:>+7.1f}%" if len(f) else f"{'—':>8}"
    p(row)
p("")
p("原表下面兩列對不上它自己的 17 筆：")
for name, h in HZ.items():
    f = fwd(spx, ev, h)
    b = base(spx, h)
    p(f"  {name}: 17 筆平均 {f.mean()*100:+.1f}%、上漲那幾筆平均 {f[f>0].mean()*100:+.1f}%；"
      f"1956→ 任意日平均 {b.mean()*100:+.1f}%、任意日上漲時平均 {b[b>0].mean()*100:+.1f}%、任意日上漲比例 {(b>0).mean()*100:.0f}%")

# ── 2. 跟任意日比 ─────────────────────────────────────────────
p("\n=== 2. S&P 事件後 vs 任意日（p = 隨機抽同樣次數的日子，結果不輸事件的比例）===")
for name, h in HZ.items():
    p(f"[{name}]")
    p(line("S&P", fwd(spx, ev, h), base(spx, h)))
    e93 = [d for d in ev if d >= spy.index[0]]
    p(line("SPY含息", fwd(spy, e93, h), base(spy, h)))

# ── 3. 同一批事件日看 NDX／SOX ────────────────────────────────
p("\n=== 3. 同一批 S&P 事件日 → 那斯達克 100／費半／ETF（各自跟自己的任意日比）===")
series = {"S&P(1985→)": spx[spx.index >= ndx.index[0]], "NDX(1985→)": ndx, "S&P(1994→)": spx[spx.index >= sox.index[0]],
          "SOX(1994→)": sox, "QQQ含息(1999→)": qqq, "SMH含息(2012→)": smh}
for name, h in HZ.items():
    p(f"[{name}]")
    for lab, s in series.items():
        days = [d for d in ev if d >= s.index[0]]
        p(line(lab, fwd(s, days, h), base(s, h)).replace(f"  {lab:<6}", f"  {lab:<15}"))

# ── 4. 換過去的超額 ───────────────────────────────────────────
p("\n=== 4. 事件日把 S&P 換成 NDX／SOX：之後的超額（X − S&P）vs 任意日的超額 ===")
for lab, s in (("NDX−S&P", ndx), ("SOX−S&P", sox)):
    sp = spx.reindex(s.index).dropna()
    s2 = s.reindex(sp.index)
    days = [d for d in ev if d >= s2.index[0]]
    for name, h in HZ.items():
        x = fwd(s2, days, h) - fwd(sp, days, h)
        bx = (base(s2, h) - base(sp, h)).dropna()
        pm, pmed = rand_p(bx, len(x), x.mean(), x.median())
        p(f"  {lab} {name}: n={len(x)} 事件後超額 平均 {x.mean()*100:+6.1f}pp 中位 {x.median()*100:+6.1f}pp 贏 S&P {(x>0).mean()*100:3.0f}%"
          f" 最差 {x.min()*100:+6.1f}pp ｜任意日 平均 {bx.mean()*100:+5.1f}pp 中位 {bx.median()*100:+5.1f}pp 贏 {(bx>0).mean()*100:3.0f}%"
          f" ｜p(平均) {pm:.2f} p(中位) {pmed:.2f}")

# ── 5. 各自觸發 ───────────────────────────────────────────────
p("\n=== 5. 各指數用自己的 5 日跌幅當觸發（40 日去叢集）===")
q_spx = (r5[r5.index >= "1994-05-04"] <= -0.08).mean()
p(f"S&P 5 日 ≤ −8% 在 1994-05→ 佔 {q_spx*100:.2f}% 的日子；『同樣罕見』門檻 = 各指數 5 日報酬的同一分位")
for lab, s in (("S&P 1956→", spx), ("NDX 1985→", ndx), ("SOX 1994→", sox)):
    rr = s / s.shift(5) - 1
    eq = rr[rr.index >= "1994-05-04"].quantile(q_spx)
    ths = [-0.08, -0.10, -0.12, -0.15]
    if lab[:3] != "S&P":
        ths.append(round(float(eq), 3))
    for th in sorted(set(ths), reverse=True):
        e2 = decluster(rr <= th)
        tag = "（同樣罕見）" if lab[:3] != "S&P" and abs(th - eq) < 1e-3 else ""
        parts = []
        for name, h in HZ.items():
            f = fwd(s, e2, h)
            b = base(s, h)
            if len(f) == 0:
                continue
            pm, _ = rand_p(b, len(f), f.mean(), f.median())
            parts.append(f"{name} 平均 {f.mean()*100:+5.1f}% 中位 {f.median()*100:+5.1f}% 漲 {(f>0).mean()*100:3.0f}%"
                         f"（任意 {b.mean()*100:+.1f}%／{b.median()*100:+.1f}%／{(b>0).mean()*100:.0f}%，p {pm:.2f}）")
        p(f"  {lab} ≤{th*100:+.1f}%{tag} 事件 {len(e2)} 次：" + "；".join(parts))

# ── 6. 買了之後要忍多深＋逐筆狀態 ─────────────────────────────
p("\n=== 6. 事件日買進後，126 日內收盤最深再跌多少（相對事件日收盤）===")
for lab, s in (("S&P", spx), ("NDX", ndx), ("SOX", sox)):
    mae = []
    for d in ev:
        if d in s.index:
            i = s.index.get_loc(d)
            if i + 126 < len(s):
                mae.append(s.iloc[i + 1:i + 127].min() / s.iloc[i] - 1)
    bm = (s.rolling(126).min().shift(-126) / s - 1).dropna()
    mae = np.array(mae)
    p(f"  {lab}: n={len(mae)} 中位 {np.median(mae)*100:+.1f}% 最差 {mae.min()*100:+.1f}% 再跌超過 10% 的比例 {(mae<=-0.10).mean()*100:.0f}%"
      f" ｜任意日 中位 {bm.median()*100:+.1f}%、再跌超過 10% 的比例 {(bm<=-0.10).mean()*100:.0f}%")

p("\n逐筆（1985→）：事件當下 S&P／NDX／費半 距一年高、VIX；之後 12 個月三者報酬")
p(f"{'事件日':<12}{'S&P距高':>8}{'NDX距高':>8}{'SOX距高':>8}{'VIX':>6}  {'S&P12m':>8}{'NDX12m':>8}{'SOX12m':>8}{'SOX6m內最深':>12}")


def dd_hi(s, d):
    if d not in s.index:
        return np.nan
    i = s.index.get_loc(d)
    return s.iloc[i] / s.iloc[max(0, i - 251):i + 1].max() - 1


def fmt(x, w=8):
    return f"{x*100:>+{w-1}.1f}%" if pd.notna(x) else f"{'—':>{w}}"


rows = []
for d in ev:
    if d < ndx.index[0]:
        continue
    f = {k: (fwd(s, [d], 252).iloc[0] if len(fwd(s, [d], 252)) else np.nan) for k, s in (("spx", spx), ("ndx", ndx), ("sox", sox))}
    mae = np.nan
    if d in sox.index:
        i = sox.index.get_loc(d)
        mae = sox.iloc[i + 1:i + 127].min() / sox.iloc[i] - 1 if i + 1 < len(sox) else np.nan
    v = vix[d] if d in vix.index else np.nan
    rows.append((d, dd_hi(spx, d), dd_hi(ndx, d), dd_hi(sox, d), v, f["spx"], f["ndx"], f["sox"], mae))
    p(f"{d.date()!s:<12}{fmt(dd_hi(spx, d))}{fmt(dd_hi(ndx, d))}{fmt(dd_hi(sox, d))}{v:>6.1f}  {fmt(f['spx'])}{fmt(f['ndx'])}{fmt(f['sox'])}{fmt(mae, 12)}")

T = pd.DataFrame(rows, columns=["d", "spx_dd", "ndx_dd", "sox_dd", "vix", "spx12", "ndx12", "sox12", "soxmae"]).set_index("d")
done = T.dropna(subset=["spx12"])
p("\n分組（已滿 12 個月的事件）：事件當下 S&P 距一年高")
for lab, m in (("跌幅 < 15%（高檔急殺）", done.spx_dd > -0.15), ("跌幅 ≥ 15%（已在跌勢中）", done.spx_dd <= -0.15)):
    g = done[m]
    p(f"  {lab}: n={len(g)}  S&P 12m 中位 {g.spx12.median()*100:+.1f}% 漲 {(g.spx12>0).mean()*100:.0f}%；"
      f"NDX 中位 {g.ndx12.median()*100:+.1f}% 漲 {(g.ndx12>0).mean()*100:.0f}%；"
      f"SOX 中位 {g.sox12.median()*100:+.1f}% 漲 {(g.sox12.dropna()>0).mean()*100:.0f}%（n={g.sox12.notna().sum()}）")
p("分組：事件當下費半距一年高（1994→）")
ds = done.dropna(subset=["sox12"])
for lab, m in (("費半跌幅 < 30%", ds.sox_dd > -0.30), ("費半跌幅 ≥ 30%（像現在）", ds.sox_dd <= -0.30)):
    g = ds[m]
    p(f"  {lab}: n={len(g)}  SOX 12m 平均 {g.sox12.mean()*100:+.1f}% 中位 {g.sox12.median()*100:+.1f}% 漲 {(g.sox12>0).mean()*100:.0f}% 最差 {g.sox12.min()*100:+.1f}%；"
      f"S&P 12m 中位 {g.spx12.median()*100:+.1f}%；日期 {', '.join(str(x.date()) for x in g.index)}")
now = T.iloc[-1]
p(f"現在（{T.index[-1].date()}）：S&P 距一年高 {now.spx_dd*100:+.1f}%、NDX {now.ndx_dd*100:+.1f}%、費半 {now.sox_dd*100:+.1f}%、VIX {now.vix:.1f}")

# ── 7. 跟 cf-vix-spike 重不重複 ───────────────────────────────
p("\n=== 7. 跟既有影子 cf-vix-spike（VIX 收盤首次站上 30，前 20 日未見）重不重複（1990→）===")
v30 = decluster(vix >= 30, gap=20)
e90 = [d for d in ev if d >= vix.index[0]]
hit = 0
for d in e90:
    i = vix.index.get_loc(d)
    win = vix.iloc[max(0, i - 10):i + 6]
    near = [x for x in v30 if win.index[0] <= x <= win.index[-1]]
    already = vix.iloc[max(0, i - 20):i + 1].max() >= 30
    hit += bool(near) or already
    p(f"  {d.date()} VIX {vix[d]:.1f}｜前後（−10／+5 日）VIX 首次站上 30：{near[0].date() if near else '無'}｜事件日前 20 日 VIX 最高 {vix.iloc[max(0, i-20):i+1].max():.1f}")
p(f"  {len(e90)} 次事件中 {hit} 次在事件日（含）之前 20 日內 VIX 已 ≥30 或前後幾天內觸發首次站上 30")
p(f"  反過來：VIX 首次站上 30 共 {len(v30)} 次，其中落在 S&P 事件日 −10／+5 日內的 {sum(any(abs(vix.index.get_loc(x) - vix.index.get_loc(d)) <= 10 for d in e90) for x in v30)} 次")
for name, h in HZ.items():
    p(f"[VIX 首次站上 30 → SPY {name}]")
    p(line("SPY含息", fwd(spy, v30, h), base(spy, h)))

# ── 8. 停泊池試算 ─────────────────────────────────────────────
p("\n=== 8. 停泊池試算：平時 SPY；S&P 事件日收盤換成 X，抱 252 日換回（期間再觸發不延長）；每次換 5bp ===")


def pool(alt, start, hold=252):
    a = alt[alt.index >= start]
    s = spy.reindex(a.index).ffill()
    ra, rs = a.pct_change().fillna(0), s.pct_change().fillna(0)
    inalt = pd.Series(False, index=a.index)
    for d in ev:
        if d in a.index:
            i = a.index.get_loc(d)
            inalt.iloc[i + 1:i + 1 + hold] = True
    r = np.where(inalt, ra, rs)
    sw = inalt.astype(int).diff().abs().fillna(0)
    r = r - sw.values * 0.0005
    eq = pd.Series((1 + r).cumprod(), index=a.index)
    return eq, inalt.mean(), ra, rs


def perf(eq):
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    mdd = (eq / eq.cummax() - 1).min()
    r = eq.pct_change().dropna()
    return cagr, mdd, r.mean() / r.std() * np.sqrt(252)


for lab, alt, start in (("QQQ", qqq, "1999-03-10"), ("QQQ", qqq, "2010-01-01"), ("SMH", smh, "2012-01-01")):
    eq, frac, ra, rs = pool(alt, start)
    fix = pd.Series((1 + frac * ra + (1 - frac) * rs).cumprod(), index=eq.index)   # 同平均比例的固定配置
    bh_s = pd.Series((1 + rs).cumprod(), index=eq.index)
    bh_a = pd.Series((1 + ra).cumprod(), index=eq.index)
    p(f"[{lab} {start}→，在 {lab} 的時間 {frac*100:.0f}%]")
    for n2, e2 in ((f"事件換 {lab}", eq), (f"固定 {frac*100:.0f}% {lab}", fix), ("一直 SPY", bh_s), (f"一直 {lab}", bh_a)):
        c, m, sh = perf(e2)
        p(f"  {n2:<14} 年化 {c*100:+5.1f}%  最大回撤 {m*100:+6.1f}%  Sharpe {sh:.2f}")

# ── 9. QQQ／SMH 自己「現在這種跌法」之後（2026-11-22 追問：現在升曝險呢）────────────
p("\n=== 9. NDX／費半自己處在『現在這種情境』之後（1／3／6／12 個月；40 日去叢集）===")
HZ4 = {"1個月": 21, "3個月": 63, "6個月": 126, "12個月": 252}
panic = (r5 <= -0.08).rolling(5).max().fillna(0).astype(bool)      # 近 5 日內 S&P 出現過 5 日 ≤ −8%


def dd_series(s):
    return s / s.rolling(252, min_periods=60).max() - 1


def block(lab, s, days):
    parts = []
    for name, h in HZ4.items():
        f = fwd(s, days, h)
        b = base(s, h)
        if len(f) == 0:
            parts.append(f"{name} —")
            continue
        pm, _ = rand_p(b, len(f), f.mean(), f.median())
        parts.append(f"{name} 平均 {f.mean()*100:+5.1f}% 中位 {f.median()*100:+5.1f}% 漲 {(f>0).mean()*100:3.0f}%（任意 {b.mean()*100:+.1f}%／{(b>0).mean()*100:.0f}%，p {pm:.2f}）")
    p(f"  {lab}：n={len(days)}｜" + "；".join(parts))


def mae6(s, d):
    i = s.index.get_loc(d)
    return s.iloc[i + 1:i + 127].min() / s.iloc[i] - 1 if i + 1 < len(s) else np.nan


for lab, s, th5, thdd in (("NDX", ndx, -0.10, -0.15), ("SOX", sox, -0.15, -0.35)):
    rr = s / s.shift(5) - 1
    dd = dd_series(s)
    pn = panic.reindex(s.index).fillna(False)
    p(f"[{lab}] 現在：5 日 {rr.iloc[-1]*100:+.1f}%、距一年高 {dd.iloc[-1]*100:+.1f}%｜門檻取 5 日 ≤ {th5*100:.0f}%、距高 ≤ {thdd*100:.0f}%")
    own = rr <= th5
    block(f"a 自己 5 日 ≤ {th5*100:.0f}%（不管大盤）", s, decluster(own))
    block("b 　同時大盤恐慌（S&P 5 日 ≤ −8%）", s, decluster(own & pn))
    block("c 　大盤沒恐慌，只有自己跌", s, decluster(own & ~pn))
    block(f"d 自己 5 日 ≤ {th5*100:.0f}% 且已距高 ≤ {thdd*100:.0f}%", s, decluster(own & (dd <= thdd)))
    now_like = decluster(own & pn & (dd <= thdd))
    block("e 三個條件都有（最像現在）", s, now_like)
    block(f"f 對照：已距高 ≤ {thdd*100:.0f}% 的任何一天（去叢集）", s, decluster(dd <= thdd))
    p(f"  e 逐筆：{'事件日':<12}{'5日':>7}{'距高':>8}{'1個月':>8}{'3個月':>8}{'6個月':>8}{'12個月':>8}{'6個月內最深':>10}")
    for d in now_like:
        row = f"          {d.date()!s:<12}{rr[d]*100:>+6.1f}%{dd[d]*100:>+7.1f}%"
        for h in HZ4.values():
            f = fwd(s, [d], h)
            row += f"{f.iloc[0]*100:>+7.1f}%" if len(f) else f"{'—':>8}"
        m = mae6(s, d)
        row += f"{m*100:>+9.1f}%" if pd.notna(m) and d != s.index[-1] else f"{'—':>10}"
        p(row)

p("\n每 $10,000 在 S&P 事件日從 VOO 換過去，3 個月後比留在 VOO 多／少（1985→／1994→ 的事件）")
for lab, s in (("NDX", ndx), ("SOX", sox)):
    sp = spx.reindex(s.index).dropna()
    s2 = s.reindex(sp.index)
    days = [d for d in ev if d >= s2.index[0]]
    for name, h in (("3個月", 63), ("12個月", 252)):
        x = (fwd(s2, days, h) - fwd(sp, days, h)) * 10000
        p(f"  換 {lab} {name}: 平均 {x.mean():+,.0f}、中位 {x.median():+,.0f}、最好 {x.max():+,.0f}、最差 {x.min():+,.0f}、少賺的次數 {(x<0).sum()}／{len(x)}")

with open(OUT, "w") as fh:
    fh.write("\n".join(_lines) + "\n")
print(f"\n→ {OUT}", file=sys.stderr)
