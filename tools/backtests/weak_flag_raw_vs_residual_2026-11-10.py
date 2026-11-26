"""T1 弱倉旗標：原始落後（R36 型）vs 扣掉 β 的殘差落後——哪一個比較能挑出「之後繼續落後」的名字。
宇宙：options_long_short_2026-10-23/short_alpha/universe.py 的 83 檔（今天看得到的名單，有倖存者偏差），
板塊 ETF 對應同檔（SMH／IGV／SPY）。2015 起、每 5 個交易日取樣一次。yfinance auto_adjust=True。
  定義 A＝W 日報酬 − 板塊 ETF W 日報酬 ≤ −10pp。
  定義 B＝個股日（對數）報酬對板塊 ETF 日報酬做 252 日滾動回歸取 β；最近 W 日的 (r_s − β·r_e) 累積
        ÷（回歸殘差日波動 × √W）≤ −1.0（另報 −1.5）。累積時不扣截距——截距正是要量的漂移。
  兩者都另有「且收盤 < SMA50」版本。W 預設 90 個交易日；另跑 W=63（position_guard 實作的 ret90 是 63 根日線）。
量測：旗標後 60／120 日「個股 − 板塊 ETF」超額報酬（另列扣 β 版：個股 − β×ETF）。
四格：只有 A、只有 B、兩者都亮、都不亮（基準）。
t 值：事件高度重疊，不把重疊樣本當獨立——每月取一個橫斷面平均，對月序列算 Newey-West t
（60 日用 3 階、120 日用 6 階）；格與格的差也是先在同月相減再算。
用法：python3 weak_flag_raw_vs_residual_2026-11-10.py [W=90] [--refresh]
輸出：data/weak_flag_raw_vs_residual_2026-11-10.out.txt（W=90）、…w63.out.txt（W=63）

首跑結論（2026-11-10；W=90 為主，W=63 在 …w63.out.txt）：
- 取樣 41,906 個（檔×日）、82 檔、140 個月。A 亮 26.5%、B（z ≤ −1.0）亮 15.3%，B 幾乎是 A 的子集（只有 B 亮 n=192）。
- 兩個旗標都挑不出「之後繼續落後」。60 日對基準（都不亮）的同月差：全部 A −0.30pp（t −0.37）、全部 B −0.46pp（t −0.52）；
  B − A −0.15pp（t −0.44）。120 日同樣不顯著（−0.31pp／−0.96pp，t −0.18／−0.50）。z ≤ −1.5 反而偏反彈（+1.10pp，t +0.97）。
- A 亮 B 不亮（n=4,662）60 日平均 +2.66% vs 基準 +2.76%（同月差 −0.38pp，t −0.43）＝不弱。但它們不是高 β（1.19 vs 1.16），
  是殘差波動高（日 2.46% vs 1.95%）——−10pp 對這些名字不到一個標準差，是雜訊不是機械性 β 落後。
- 加「收盤 < SMA50」沒有幫助，方向還偏反彈（全部 A 60 日 +0.75pp，t +0.86；2015–2019 120 日 +3.09pp，t +2.37）。
- 唯一像樣的格子：W=63 時「只有 B 亮」（n=478，低波動名字的小幅持續落後）60 日 −2.50pp（t −2.57）、120 日 −4.38pp（t −2.21）；
  W=90 同格 n=192、−1.37pp（t −0.81）。小樣本、對窗長敏感，只算線索。
- 分段：2015–2019 旗標後偏反彈、2020→ 偏續弱（全部 B 60 日 −1.51pp，t −1.13），都不顯著。中位數與勝率略低於基準（A：0.0%／50.0% vs +0.7%／52.0%）。
- 限制：今日名單倖存者偏差（一路落後到被剔除／下市的名字不在樣本，會把旗標後報酬往上推，等於偏袒「弱倉會反彈」）；
  沒有 revision 條件（R36 的第二腿無歷史資料）；板塊對應手標；基準格本身 60 日 +2.76% 也是倖存者偏差。
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = HERE / "data"; DATA.mkdir(exist_ok=True)
NAME = Path(__file__).stem
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
W = int(ARGS[0]) if ARGS else 90
REFRESH = "--refresh" in sys.argv
OUT = DATA / (f"{NAME}.out.txt" if W == 90 else f"{NAME}.w{W}.out.txt")
PX = DATA / "weak_flag_px_2026-11-10.csv"
HZ = (60, 120); NW = {60: 3, 120: 6}
START = pd.Timestamp("2015-01-01")

sys.path.insert(0, str(HERE / "options_long_short_2026-10-23" / "short_alpha"))
import universe as UNI  # noqa: E402
# universe.py 的 _ROOT 少算一層（指到 tools/），這裡覆寫路徑，不改原檔
UNI.LEDGER = str(ROOT / "research/trade-ledger.jsonl"); UNI.TL_PY = str(ROOT / "tools/trade_ledger.py")
UNI.BENCH_JSON = str(ROOT / "research/bench.json")
SYMS = UNI.test2_universe()
ETF = {s: UNI.sector_etf(s) for s in SYMS}

_lines = []
def P(*a):
    s = " ".join(str(x) for x in a); print(s); _lines.append(s)

def load_px():
    if PX.exists() and not REFRESH:
        return pd.read_csv(PX, index_col=0, parse_dates=True)
    import yfinance as yf
    c = yf.download(SYMS + ["SMH", "IGV", "SPY"], start="2013-01-01", progress=False, auto_adjust=True, threads=True)["Close"]
    c = c.dropna(axis=1, how="all"); c.to_csv(PX); return c

def nw_t(x, L):
    x = np.asarray(x, float); x = x[~np.isnan(x)]; n = len(x)
    if n < 12: return np.nan
    d = x - x.mean(); v = (d * d).sum() / n
    for k in range(1, min(L, n - 1) + 1):
        v += 2 * (1 - k / (L + 1)) * (d[k:] * d[:-k]).sum() / n
    return x.mean() / np.sqrt(v / n) if v > 0 else np.nan

def build(C):
    cal = C["SPY"].dropna().index
    samp = cal[cal >= START][::5]
    rows = []
    for s in SYMS:
        if s not in C.columns: continue
        e = ETF[s]; d = C[[s, e]].dropna()
        if len(d) < 252 + W + 5: continue
        ps, pe = d[s], d[e]; ls, le = np.log(ps).diff(), np.log(pe).diff()
        ve = le.rolling(252).var(); beta = ls.rolling(252).cov(le) / ve
        rsd = np.sqrt((ls.rolling(252).var() - beta ** 2 * ve).clip(lower=1e-12))
        f = pd.DataFrame({
            "A": (ps / ps.shift(W) - 1) - (pe / pe.shift(W) - 1),
            "z": (ls.rolling(W).sum() - beta * le.rolling(W).sum()) / (rsd * np.sqrt(W)),
            "below": (ps < ps.rolling(50).mean()).astype(float),
            "beta": beta, "rsd": rsd, "etfW": pe / pe.shift(W) - 1})
        for h in HZ:
            rs_, re_ = ps.shift(-h) / ps - 1, pe.shift(-h) / pe - 1
            f[f"x{h}"] = rs_ - re_; f[f"b{h}"] = rs_ - beta * re_
        f = f.reindex(samp).dropna(subset=["A", "z"]); f["sym"] = s; f["etf"] = e
        rows.append(f)
    df = pd.concat(rows).reset_index(names="date")
    df["ym"] = df["date"].dt.to_period("M")
    return df

def cell_stats(df, mask, base, h, col="x"):
    """回傳 平均、中位、勝率、n、檔數、月序列 NW t、對基準的同月差 與其 NW t。"""
    c = f"{col}{h}"; a = df[mask & df[c].notna()]; b = df[base & df[c].notna()]
    if len(a) == 0: return None
    ma = a.groupby("ym")[c].mean(); mb = b.groupby("ym")[c].mean()
    diff = (ma - mb).dropna()
    return dict(mean=a[c].mean(), med=a[c].median(), win=(a[c] > 0).mean(), n=len(a), names=a["sym"].nunique(),
                months=len(ma), t=nw_t(ma.values, NW[h]), d=diff.mean() if len(diff) else np.nan, dt=nw_t(diff.values, NW[h]))

def pair_diff(df, m1, m2, h, col="x"):
    c = f"{col}{h}"
    a = df[m1 & df[c].notna()].groupby("ym")[c].mean(); b = df[m2 & df[c].notna()].groupby("ym")[c].mean()
    d = (a - b).dropna()
    return (d.mean() if len(d) else np.nan, nw_t(d.values, NW[h]), len(d))

def fmt(st):
    if st is None: return "  （無樣本）"
    return (f"平均 {st['mean']*100:+6.2f}%  中位 {st['med']*100:+6.2f}%  勝率 {st['win']*100:4.1f}%  n={st['n']:>6}（{st['names']:>2} 檔／{st['months']:>3} 月）"
            f"  月序列 t {st['t']:+5.2f} | 對基準同月差 {st['d']*100:+6.2f}pp（t {st['dt']:+5.2f}）")

def table(df, zthr, sma, seg_label):
    A = df["A"] <= -0.10; B = df["z"] <= zthr
    if sma:
        A = A & (df["below"] == 1); B = B & (df["below"] == 1)
    cells = [("只有 A 亮", A & ~B), ("只有 B 亮", ~A & B), ("A、B 都亮", A & B), ("都不亮（基準）", ~A & ~B),
             ("全部 A（不管 B）", A), ("全部 B（不管 A）", B)]
    base = ~A & ~B
    P(f"\n### {seg_label}｜B 門檻 z ≤ {zthr}｜{'且收盤 < SMA50' if sma else '不加 SMA50'}｜取樣點 {len(df)}，A 亮 {A.mean()*100:.1f}%、B 亮 {B.mean()*100:.1f}%")
    for name, m in cells:
        sub = df[m]
        P(f"  [{name}] 平均 β {sub['beta'].mean():.2f}、殘差日波動 {sub['rsd'].mean()*100:.2f}%、旗標時板塊 ETF {W} 日報酬 {sub['etfW'].mean()*100:+.1f}%、A 值中位 {sub['A'].median()*100:+.1f}pp、z 中位 {sub['z'].median():+.2f}")
        for h in HZ:
            P(f"    {h:>3} 日 個股−ETF   " + fmt(cell_stats(df, m, base, h, "x")))
            P(f"    {h:>3} 日 個股−β×ETF " + fmt(cell_stats(df, m, base, h, "b")))
    for h in HZ:
        for lab, m1, m2 in [("只有 B − 只有 A", ~A & B, A & ~B), ("都亮 − 只有 A", A & B, A & ~B), ("全部 B − 全部 A", B, A)]:
            d, t, n = pair_diff(df, m1, m2, h)
            P(f"  同月差 {h:>3} 日 {lab:<12} {d*100:+6.2f}pp  t {t:+5.2f}  （{n} 個月）")

def main():
    C = load_px()
    miss = [s for s in SYMS if s not in C.columns]
    df = build(C)
    P(f"T1 弱倉旗標：原始落後 A vs β 殘差 B｜回看窗 W={W} 個交易日｜價格至 {C.index.max().date()}")
    P(f"宇宙 {len(SYMS)} 檔（今日名單，倖存者偏差），抓不到價 {miss or '無'}；進樣本 {df['sym'].nunique()} 檔（需 ≥{252+W} 根日線）")
    P(f"板塊 ETF 對應：SMH {sum(v=='SMH' for v in ETF.values())}、IGV {sum(v=='IGV' for v in ETF.values())}、SPY {sum(v=='SPY' for v in ETF.values())}")
    P(f"取樣 {df['date'].min().date()} → {df['date'].max().date()}，每 5 個交易日，共 {df['date'].nunique()} 個取樣日、{len(df)} 個（檔×日）")
    P("超額 = 之後 h 日 個股報酬 − 板塊 ETF 報酬；勝率 = 超額 > 0 的比例；t = 每月橫斷面平均的時間序列 Newey-West t")
    segs = [("全期 2015→", df), ("2015–2019", df[df["date"] < "2020-01-01"]), ("2020→", df[df["date"] >= "2020-01-01"])]
    for lab, d in segs:
        table(d, -1.0, False, lab)
    table(df, -1.5, False, "全期 2015→")
    for lab, d in segs:
        table(d, -1.0, True, lab)
    table(df, -1.5, True, "全期 2015→")
    # A 亮的樣本裡，z 分數有沒有額外資訊：A 亮者按 z 三分位
    P("\n### A 亮的樣本按 z 分三組（z 越負 = 扣 β 後越弱）——B 在 A 之上有沒有增量")
    a = df[df["A"] <= -0.10].copy()
    a["zq"] = a.groupby("date")["z"].transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=False) if len(s) >= 6 else np.nan)
    for h in HZ:
        c = f"x{h}"; ms = {}
        for q, lab in [(0, "z 最負 1/3"), (1, "中間 1/3"), (2, "z 最不負 1/3")]:
            sub = a[(a["zq"] == q) & a[c].notna()]; ms[q] = sub.groupby("ym")[c].mean()
            P(f"  {h:>3} 日 {lab:<12} 平均 {sub[c].mean()*100:+6.2f}%  中位 {sub[c].median()*100:+6.2f}%  勝率 {(sub[c]>0).mean()*100:4.1f}%  n={len(sub)}  平均 β {sub['beta'].mean():.2f}")
        d = (ms[0] - ms[2]).dropna()
        P(f"  {h:>3} 日 最負 − 最不負 同月差 {d.mean()*100:+6.2f}pp  t {nw_t(d.values, NW[h]):+5.2f}（{len(d)} 個月）")
    # 分板塊：全部 A vs 全部 B
    P("\n### 分板塊（全期、不加 SMA50、z ≤ −1.0）：60 日個股−ETF")
    for e in ("SMH", "IGV", "SPY"):
        d = df[df["etf"] == e]; A = d["A"] <= -0.10; B = d["z"] <= -1.0; base = ~A & ~B
        for name, m in [("只有 A", A & ~B), ("只有 B", ~A & B), ("都亮", A & B), ("基準", base)]:
            st = cell_stats(d, m, base, 60)
            P(f"  {e} [{name:<4}] " + fmt(st))
    OUT.write_text("\n".join(_lines) + "\n")
    print(f"\n→ {OUT}")

if __name__ == "__main__":
    main()
