"""Signal, target-weight and simulation engine (pure numpy/pandas; no data access).

Conventions (frozen by the spec):
* P[t] adjusted close of session t, R[t] = P[t]/P[t-1] - 1 (R[0] = 0).
* A check on session c uses P[0..c] only. The trade happens at the close of session c+1,
  so the new weights earn from session c+2 on. The old weights earn through session c+1.
* Cost = COST * sum(|w_new - w_drifted_old|) on the trade session (5bp per side of the traded
  amount); nothing is charged when no trade is needed. First buy from cash costs COST * 1.
* Weights drift between trades (buy and hold between checks); a trade resets them to target.
"""
from __future__ import annotations

import numpy as np

COST_BASE = 0.0005
LOOKBACKS = {"L126": (126, 0), "L252": (252, 0), "L252s21": (252, 21)}   # (L, skip)
FORMS = ("keep", "cull", "stay")        # 留強, 汰弱, 續抱


def returns(P):
    P = np.asarray(P, float)
    R = np.zeros_like(P)
    R[1:] = P[1:] / P[:-1] - 1
    return R


def momentum(P, c, L, skip):
    """Return of each asset from session c-L to c-skip, using only rows <= c."""
    assert c - L >= 0
    return P[c - skip] / P[c - L] - 1


def rank_order(score):
    """Indices from best to worst; ties by list order (stable)."""
    return np.argsort(-np.asarray(score), kind="stable")


def keep_n(n_assets, form):
    if form == "keep" or form == "stay":
        return 1
    return n_assets - 1 if n_assets == 3 else n_assets - 3     # G3: 2 of 3; G7: 4 of 7


def stay_rank(n_assets):
    return 2 if n_assets == 3 else 3                            # stay if held ETF is within top this many


def strategy_targets(P, checks, L, skip, form):
    """Target weight vectors for every check (len(checks), n). 'stay' uses its own holding state."""
    n = P.shape[1]
    W = np.zeros((len(checks), n))
    held = None
    for j, c in enumerate(checks):
        order = rank_order(momentum(P, c, L, skip))
        if form == "keep":
            W[j, order[0]] = 1.0
        elif form == "cull":
            k = keep_n(n, form)
            W[j, order[:k]] = 1.0 / k
        elif form == "stay":
            if held is not None and held in order[:stay_rank(n)]:
                pass
            else:
                held = order[0]
            W[j, held] = 1.0
        else:
            raise ValueError(form)
    return W


def simulate(R, trade_idx, W, cost=COST_BASE, track=True):
    """W: (D, m, n) target weights per draw. Returns daily returns (D, T) and weights (D, T, n)
    held at the close of each session (after any trade). Sessions before trade_idx[0] are 0."""
    R = np.asarray(R, float)
    W = np.asarray(W, float)
    D, m, n = W.shape
    T = R.shape[0]
    out = np.zeros((D, T))
    wt = np.zeros((D, T, n)) if track else None
    w = np.zeros((D, n))                   # current (drifted) weights, all cash at start
    cur = None
    for j in range(m):
        t0 = trade_idx[j]
        t1 = trade_idx[j + 1] if j + 1 < m else T - 1   # last session whose return we need
        # trade session t0: old weights earn R[t0], then rebalance at the close
        if j == 0:
            gross = np.zeros(D)
            drift = np.zeros((D, n))
        else:
            g = w * (1 + R[t0])
            tot = g.sum(1)
            gross = tot - 1
            drift = g / tot[:, None]
        turnover = np.abs(W[:, j, :] - drift).sum(1)
        out[:, t0] = (1 + gross) * (1 - cost * turnover) - 1
        w = W[:, j, :].copy()
        if track:
            wt[:, t0, :] = w
        for t in range(t0 + 1, t1 + (0 if j + 1 < m else 1)):
            g = w * (1 + R[t])
            tot = g.sum(1)
            out[:, t] = tot - 1
            w = g / tot[:, None]
            if track:
                wt[:, t, :] = w
    return out, wt


def check_days(first, H, T):
    """Check sessions first, first+H, ... such that the trade session c+1 exists (<= T-1)."""
    cs = []
    c = first
    while c + 1 <= T - 1:
        cs.append(c)
        c += H
    return cs


def run_tranches(P, S, H, L, skip, form, cost=COST_BASE):
    """Blend of H/21 staggered tranches. Returns dict with blend returns (T,), per-tranche
    returns (k, T), blend weights (T,n), switches per tranche (list of (trade_idx list))."""
    T, n = P.shape
    R = returns(P)
    rets, wts, trade_lists, nsw = [], [], [], []
    for k in range(H // 21):
        checks = check_days(S + 21 * k, H, T)
        W = strategy_targets(P, checks, L, skip, form)
        tidx = [c + 1 for c in checks]
        r, w = simulate(R, tidx, W[None], cost)
        rets.append(r[0])
        wts.append(w[0])
        trade_lists.append(tidx)
        nsw.append(switch_flags(W))
    rets = np.array(rets)
    return {"tranche_rets": rets, "blend": rets.mean(0), "blend_w": np.mean(wts, 0),
            "trade_idx": trade_lists, "switch_flags": nsw, "first_live": max(t[0] for t in trade_lists)}


def switch_flags(W):
    """Per check after the first: did the holding set change?"""
    return [bool(not np.allclose(W[j], W[j - 1])) for j in range(1, len(W))]


# --------------------------------------------------------------------------- random control
def random_targets(rng, D, m, n, form, n_switch=None):
    """(D, m, n) random target weights. keep: one random asset per check. cull: random keep_n
    assets equal weight per check. stay: random initial asset, then exactly n_switch switches at
    random checks (among checks 1..m-1) to a random other asset."""
    W = np.zeros((D, m, n))
    if form == "keep":
        pick = rng.integers(0, n, size=(D, m))
        for j in range(m):
            W[np.arange(D), j, pick[:, j]] = 1.0
    elif form == "cull":
        k = keep_n(n, form)
        r = rng.random((D, m, n))
        top = np.argsort(r, axis=2)[:, :, :k]
        for j in range(m):
            for q in range(k):
                W[np.arange(D), j, top[:, j, q]] = 1.0 / k
    elif form == "stay":
        ns = min(n_switch, m - 1)
        cur = rng.integers(0, n, size=D)
        sw = np.zeros((D, m), bool)
        for d in range(D):
            sw[d, rng.choice(np.arange(1, m), size=ns, replace=False)] = True
        for j in range(m):
            new = (cur + rng.integers(1, n, size=D)) % n        # uniform over the other n-1 assets
            cur = np.where(sw[:, j], new, cur)
            W[np.arange(D), j, cur] = 1.0
    else:
        raise ValueError(form)
    return W


def null_blend(R, S, H, form, rng, D, n, T, cost=COST_BASE, switches=None):
    """Blend of random tranches for D draws -> (D, T) daily returns."""
    tot = np.zeros((D, T))
    K = H // 21
    for k in range(K):
        checks = check_days(S + 21 * k, H, T)
        tidx = [c + 1 for c in checks]
        W = random_targets(rng, D, len(checks), n, form, None if switches is None else switches[k])
        r, _ = simulate(R, tidx, W, cost, track=False)
        tot += r
    return tot / K


# --------------------------------------------------------------------------- metrics
def cagr(r):
    r = np.asarray(r, float)
    return float(np.prod(1 + r) ** (252.0 / len(r)) - 1)


def cagr_many(r):
    r = np.asarray(r, float)
    return np.exp(np.log1p(r).sum(1) * 252.0 / r.shape[1]) - 1


def mdd(r):
    eq = np.cumprod(1 + np.asarray(r, float))
    return float((eq / np.maximum.accumulate(eq) - 1).min())


def vol(r):
    return float(np.std(r, ddof=1) * np.sqrt(252))


def equal_weight_bench(R, start, H, cost=COST_BASE):
    """Equal weight from session `start`, pulled back to equal every H sessions (cost on traded
    amount at the rebalance close; none for the initial allocation). Returns daily returns for
    sessions start..T-1 (index 0 = session start; its return counts)."""
    T, n = R.shape
    w = np.full(n, 1.0 / n)
    out = []
    for t in range(start, T):
        g = w * (1 + R[t])
        tot = g.sum()
        r = tot - 1
        w = g / tot
        if t > start and (t - start) % H == 0:
            tgt = np.full(n, 1.0 / n)
            r = (1 + r) * (1 - cost * np.abs(tgt - w).sum()) - 1
            w = tgt
        out.append(r)
    return np.array(out)


def bh_adjust(p):
    p = np.asarray(p, float)
    m = len(p)
    order = np.argsort(p)
    q = np.empty(m)
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, p[i] * m / rank)
        q[i] = prev
    return q
