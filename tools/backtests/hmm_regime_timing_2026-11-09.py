"""
隱馬可夫（Gaussian HMM）擇時回測 — 2026-11-09 用戶問「加入隱馬可夫鏈幫忙擇時有意義嗎」

設計要點（防 look-ahead）：
- 自寫 numpy Baum-Welch（無 hmmlearn 依賴），K=2/3 state，觀測 = 日對數報酬
- walk-forward：首次擬合用 5 年，之後每 63 個交易日重擬合（窗最長 15 年，warm start）
- 訊號用「filtered」機率 P(state_t | x_≤t)，不是 Viterbi/smoothed（那會偷看未來）
- t 日收盤機率 → t+1 日部位；出場放現金（^IRX 13 週 T-bill）
- 對照：買進持有、SMA200 濾網、波動目標（15%，無槓桿）、以及「全樣本 smoothed」（錯誤做法）示範幻覺差距
- 另測：HMM 狀態對次日/次 20 日報酬有無預測力（而非只偵測波動）；P(crisis) 與 VIX / rv20 的相關
"""
import sys, warnings
import numpy as np, pandas as pd, yfinance as yf
warnings.filterwarnings("ignore")
np.set_printoptions(suppress=True)

REFIT, MIN_FIT, MAX_WIN = 63, 1260, 3780
SQ2PI = np.sqrt(2 * np.pi)

def gauss(x, mu, sd):
    return np.exp(-0.5 * ((x[:, None] - mu[None, :]) / sd[None, :]) ** 2) / (sd[None, :] * SQ2PI)

def forward(B, A, pi):
    T, K = B.shape
    al = np.empty((T, K)); c = np.empty(T)
    a = pi * B[0]; c[0] = a.sum(); al[0] = a / c[0]
    for t in range(1, T):
        a = (al[t - 1] @ A) * B[t]; c[t] = a.sum() + 1e-300; al[t] = a / c[t]
    return al, c

def backward(B, A, c):
    T, K = B.shape
    be = np.ones((T, K))
    for t in range(T - 2, -1, -1):
        be[t] = (A @ (B[t + 1] * be[t + 1])) / c[t + 1]
    return be

def fit(x, K, init=None, iters=40, tol=1e-5):
    s = x.std(); m = x.mean()
    if init is None:
        mult = {2: [0.7, 1.8], 3: [0.5, 1.0, 2.0]}[K]
        mu = np.full(K, m); sd = s * np.array(mult)
        A = np.full((K, K), 0.02 / (K - 1)); np.fill_diagonal(A, 0.98)
        pi = np.full(K, 1.0 / K)
    else:
        mu, sd, A, pi = [v.copy() for v in init]
    ll_old = -np.inf
    for _ in range(iters):
        B = gauss(x, mu, sd) + 1e-300
        al, c = forward(B, A, pi); be = backward(B, A, c)
        ll = np.log(c).sum()
        g = al * be; g /= g.sum(1, keepdims=True)
        xi = A * (al[:-1].T @ (B[1:] * be[1:] / c[1:, None]))
        A = xi / xi.sum(1, keepdims=True); pi = g[0]
        w = g.sum(0); mu = (g * x[:, None]).sum(0) / w
        sd = np.sqrt((g * (x[:, None] - mu) ** 2).sum(0) / w); sd = np.maximum(sd, 0.2 * s)
        if ll - ll_old < tol: break
        ll_old = ll
    o = np.argsort(sd)  # state 0 = 最平靜, 最後 = crisis
    return mu[o], sd[o], A[np.ix_(o, o)], pi[o]

def walk_forward(x, K):
    T = len(x); P = np.full((T, K), np.nan); params = None
    for F in range(MIN_FIT, T, REFIT):
        lo = max(0, F - MAX_WIN)
        params = fit(x[lo:F], K, init=params)
        mu, sd, A, pi = params
        hi = min(T, F + REFIT)
        al, _ = forward(gauss(x[lo:hi], mu, sd) + 1e-300, A, pi)
        P[F:hi] = al[F - lo:hi - lo]
    return P

def smoothed_full(x, K):
    mu, sd, A, pi = fit(x, K, iters=200)
    B = gauss(x, mu, sd) + 1e-300; al, c = forward(B, A, pi); be = backward(B, A, c)
    g = al * be; return g / g.sum(1, keepdims=True), al

def metrics(r, cash, w):
    r = r.dropna(); cash = cash.reindex(r.index).fillna(0); w = w.reindex(r.index)
    yrs = len(r) / 252; eq = (1 + r).cumprod()
    cagr = eq.iloc[-1] ** (1 / yrs) - 1; vol = r.std() * np.sqrt(252)
    sharpe = (r - cash).mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan
    mdd = (eq / eq.cummax() - 1).min()
    inmkt = (w > 0.5).mean(); sw = (np.sign(w - 0.5).diff().abs() > 0).sum() / yrs
    return cagr, vol, sharpe, mdd, inmkt, sw

def run(sym, df, cash, vix):
    px = df[sym].dropna(); r = np.log(px).diff().dropna(); x = r.values
    rs = px.pct_change().reindex(r.index)
    out = {}; probs = {}
    for K in (2, 3):
        P = walk_forward(x, K)
        pc = pd.Series(P[:, -1], index=r.index)  # P(crisis)
        probs[K] = pc
        pos = (pc < 0.5).astype(float).shift(1)       # t 收盤機率 → t+1 部位
        posw = (1 - pc).clip(0, 1).shift(1)
        for lab, w in ((f"HMM{K} 二元（P(crisis)<0.5 持有）", pos), (f"HMM{K} 機率權重 1−P(crisis)", posw)):
            out[lab] = (rs * w + cash.reindex(r.index).fillna(0) * (1 - w), w)
    oos = probs[2].dropna().index
    # 對照
    sma = px.rolling(200).mean(); wsma = (px > sma).astype(float).shift(1)
    rv = r.rolling(20).std() * np.sqrt(252); wvt = (0.15 / rv).clip(0, 1).shift(1)
    one = pd.Series(1.0, index=r.index)
    out["買進持有"] = (rs, one)
    out["SMA200 濾網"] = (rs * wsma + cash.reindex(r.index).fillna(0) * (1 - wsma), wsma)
    out["波動目標 15%（無槓桿）"] = (rs * wvt + cash.reindex(r.index).fillna(0) * (1 - wvt), wvt)
    # 幻覺示範：全樣本參數 smoothed / filtered
    g, al = smoothed_full(x, 2)
    for lab, p in (("⚠️ 全樣本 smoothed（偷看未來）", g[:, -1]), ("⚠️ 全樣本參數 filtered（偷看參數）", al[:, -1])):
        pc = pd.Series(p, index=r.index); w = (pc < 0.5).astype(float).shift(1)
        out[lab] = (rs * w + cash.reindex(r.index).fillna(0) * (1 - w), w)

    print(f"\n==== {sym}  OOS {oos[0].date()} → {oos[-1].date()}  ({len(oos)/252:.1f} 年) ====")
    for per, start in (("全 OOS", oos[0]), ("2010–", "2010-01-01"), ("2020–", "2020-01-01")):
        print(f"\n[{per}]  {'策略':<34}{'CAGR':>7}{'波動':>7}{'Sharpe':>7}{'MDD':>7}{'在市%':>6}{'切換/年':>8}")
        for lab, (rr, w) in out.items():
            rr2 = rr.loc[start:].loc[oos[0]:]; w2 = w.loc[rr2.index]
            c, v, s, m, im, sw = metrics(rr2, cash, w2)
            print(f"        {lab:<34}{c:>7.1%}{v:>7.1%}{s:>7.2f}{m:>7.1%}{im:>6.0%}{sw:>8.1f}")
    # 預測力：狀態對次日 / 次 20 日報酬
    pc = probs[2].loc[oos]; st = (pc >= 0.5)
    nxt1 = rs.shift(-1).loc[oos]; nxt20 = px.pct_change(20).shift(-20).loc[oos]
    def tdiff(a, b):
        return (a.mean() - b.mean()) / np.sqrt(a.var() / len(a) + b.var() / len(b))
    print(f"\n  HMM2 狀態預測力（OOS）：crisis 日數 {st.sum()} / {len(st)} = {st.mean():.0%}")
    print(f"    次 1 日均報酬  平靜 {nxt1[~st].mean()*1e4:+.1f}bp  crisis {nxt1[st].mean()*1e4:+.1f}bp  t={tdiff(nxt1[~st].dropna(), nxt1[st].dropna()):+.2f}")
    print(f"    次 1 日波動    平靜 {nxt1[~st].std()*np.sqrt(252):.1%}  crisis {nxt1[st].std()*np.sqrt(252):.1%}")
    print(f"    次 20 日均報酬 平靜 {nxt20[~st].mean():+.2%}  crisis {nxt20[st].mean():+.2%}  t={tdiff(nxt20[~st].dropna(), nxt20[st].dropna()):+.2f}")
    v = vix.reindex(oos); rv20 = rv.reindex(oos)
    print(f"    corr(P(crisis), VIX)={pc.corr(v):.2f}   corr(P(crisis), 20日已實現波動)={pc.corr(rv20):.2f}")
    print(f"    corr(P(crisis), 次 20 日報酬)={pc.corr(nxt20):+.2f}")
    return probs

if __name__ == "__main__":
    raw = yf.download(["SPY", "SMH", "^VIX", "^IRX"], period="max", progress=False, auto_adjust=True)["Close"]
    cash = (raw["^IRX"].ffill() / 100 / 252).fillna(0)
    vix = raw["^VIX"]
    p_spy = run("SPY", raw, cash, vix)
    p_smh = run("SMH", raw, cash, vix)
    # SPY 的狀態拿來管 SMH
    px = raw["SMH"].dropna(); rs = px.pct_change()
    pc = p_spy[2].reindex(rs.index); w = (pc < 0.5).astype(float).shift(1); oos = pc.dropna().index
    rr = (rs * w + cash.reindex(rs.index).fillna(0) * (1 - w)).loc[oos[0]:]
    c, v, s, m, im, sw = metrics(rr, cash, w.loc[rr.index])
    c0, v0, s0, m0, *_ = metrics(rs.loc[oos[0]:], cash, pd.Series(1.0, index=rs.index).loc[oos[0]:])
    print(f"\n==== 用 SPY 的 HMM2 狀態管 SMH（{oos[0].date()}→）====")
    print(f"  SMH 買進持有  CAGR {c0:.1%}  Sharpe {s0:.2f}  MDD {m0:.1%}")
    print(f"  SPY-HMM2 濾網 CAGR {c:.1%}  Sharpe {s:.2f}  MDD {m:.1%}  在市 {im:.0%}  切換/年 {sw:.1f}")
