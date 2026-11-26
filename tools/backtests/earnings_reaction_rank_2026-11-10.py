"""T3 財報反應當排序：(1) 財報反應好的之後 60 日是不是繼續好（財報後漂移）；(2)「上次驚喜越大、這次越弱」成不成立。
事件與價格沿用 T2（earnings_window_direction_2026-11-10.py：30 檔核心宇宙、2019 起、半導體對 SMH 其餘對 SPY、
盤後公布 t0 取隔日；今日名單 → 倖存者偏差）。
  EAR＝[t0−1 收 → t0+1 收] 個股 − 基準。
  (1) 每個日曆季內按 EAR 排三分位（同季橫斷面排序，避免跨季行情混進排序），看 [t0+1 收 → t0+61 收] 超額（另列 20 日）。
      高低組差的 t：每季一個「高組平均 − 低組平均」，對季序列算 t。另報全樣本固定門檻（EAR ≥ +5%／≤ −5%）版。
  (2) 按「上一次 EPS 驚喜%」同季內高低二分，看本次 [t0−1 收 → t0+10 收] 超額（含反應日）與 EAR 本身。
      低基期驚喜% 失真 → 另報「上次是否 beat（驚喜 > 0）」二分，與驚喜% winsorize 到 ±50% 後的每季橫斷面回歸斜率（Fama-MacBeth）。
用法：python3 earnings_reaction_rank_2026-11-10.py [--refresh]
輸出：data/earnings_reaction_rank_2026-11-10.out.txt

首跑結論（2026-11-10）：
- (1) 沒有財報後漂移。EAR 同季三分位之後 60 日超額：高 +3.91%／中 +2.84%／低 +3.13%，高 − 低每季差 +1.03pp（t +0.44，31 季）；
  後 20 日 +0.23pp（t +0.21）。固定門檻（≥+5% vs ≤−5%）+0.18pp（t +0.09）。兩段（2019–2022、2023→）都不顯著。
  三組中位數都在 0 附近、勝率 49–51%：財報反應好壞不能拿來排之後 60 日的先後。
- (2)「上次驚喜越大、這次越弱」不成立。上次驚喜高半 vs 低半，本次 [t0, t0+10] +1.70% vs +0.87%，差 +0.85pp（t +1.01）——符號相反。
  分段不一致：2019–2022 −0.77pp（t −0.65）、2023→ +2.58pp（t +2.42）。上次 beat vs 未 beat +2.35pp（t +1.54，未 beat 只有 85 筆）；
  驚喜% winsorize ±50% 後的橫斷面斜率 每 10 個百分點 +0.27pp（t +0.89）。
- 背景：這 30 檔 beat 比例 91%，「是否 beat」幾乎沒有區分力；EAR 與驚喜% 相關只有 +0.16。
- 限制：倖存者偏差；每季橫斷面只有約 28 檔、三分位每組約 9 檔；yfinance 驚喜口徑；低基期驚喜%（|驚喜| >50% 佔 13.6%）。
"""
import sys, warnings, importlib.util
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
NAME = "earnings_reaction_rank_2026-11-10"
spec = importlib.util.spec_from_file_location("t2", HERE / "earnings_window_direction_2026-11-10.py")
T2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(T2)
REFRESH = "--refresh" in sys.argv

_lines = []
def P(*a):
    s = " ".join(str(x) for x in a); print(s); _lines.append(s)

def qt(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    return (x.mean(), x.mean() / (x.std(ddof=1) / np.sqrt(len(x))), len(x)) if len(x) >= 6 and x.std(ddof=1) > 0 else (np.nan, np.nan, len(x))

def desc(e, col):
    v = e[col].dropna()
    return f"平均 {v.mean()*100:+6.2f}%  中位 {v.median()*100:+6.2f}%  勝率 {(v>0).mean()*100:4.1f}%  n={len(v):>3}"

def within_q_group(ev, key, k, min_n):
    """同季內按 key 等分 k 組（0 = 最低）；該季樣本 < min_n 不排。"""
    def f(s):
        s2 = s.dropna()
        if len(s2) < min_n: return pd.Series(np.nan, index=s.index)
        return pd.qcut(s2.rank(method="first"), k, labels=False).reindex(s.index)
    return ev.groupby("q")[key].transform(f)

def hl_diff(ev, grp, hi, lo, col):
    a = ev[ev[grp] == hi].groupby("q")[col].mean(); b = ev[ev[grp] == lo].groupby("q")[col].mean()
    return qt((a - b).dropna().values)

def part1(ev, title):
    ev = ev.copy(); ev["g"] = within_q_group(ev, "ear", 3, 9)
    P(f"\n### (1) {title}｜EAR 同季三分位 → 之後漂移｜可排序事件 {ev['g'].notna().sum()} 筆、{ev.loc[ev['g'].notna(),'q'].nunique()} 季")
    for g, lab in [(2, "高 1/3"), (1, "中 1/3"), (0, "低 1/3")]:
        e = ev[ev["g"] == g]
        P(f"  EAR {lab}（組內 EAR 平均 {e['ear'].mean()*100:+6.2f}%）  後 60 日 {desc(e,'post60')} | 後 20 日 {desc(e,'post20')}")
    for col, lab in (("post60", "後 60 日"), ("post20", "後 20 日")):
        m, t, n = hl_diff(ev, "g", 2, 0, col)
        P(f"  高 − 低 {lab}：每季差平均 {m*100:+5.2f}pp  t {t:+5.2f}（{n} 季）")

def part2(ev, title):
    ev = ev[ev["surp_prev"].notna()].copy()
    P(f"\n### (2) {title}｜上次 EPS 驚喜 → 本次反應｜有上次驚喜的事件 {len(ev)} 筆")
    P(f"  上次驚喜% 分布：中位 {ev['surp_prev'].median():+.1f}%、5% 分位 {ev['surp_prev'].quantile(.05):+.1f}%、95% 分位 {ev['surp_prev'].quantile(.95):+.1f}%、|驚喜| > 50% 的比例 {(ev['surp_prev'].abs()>50).mean()*100:.1f}%、上次 beat 比例 {(ev['surp_prev']>0).mean()*100:.1f}%")
    ev["h"] = within_q_group(ev, "surp_prev", 2, 8)
    for g, lab in [(1, "上次驚喜高半"), (0, "上次驚喜低半")]:
        e = ev[ev["h"] == g]
        P(f"  {lab}（上次驚喜中位 {e['surp_prev'].median():+5.1f}%）  本次 [t0, t0+10] {desc(e,'t0to10')} | 本次 EAR {desc(e,'ear')}")
    for col, lab in (("t0to10", "[t0, t0+10]"), ("ear", "EAR")):
        m, t, n = hl_diff(ev, "h", 1, 0, col)
        P(f"  高半 − 低半 {lab}：每季差平均 {m*100:+5.2f}pp  t {t:+5.2f}（{n} 季）")
    ev["beat"] = (ev["surp_prev"] > 0).astype(int)
    for g, lab in [(1, "上次 beat"), (0, "上次未 beat")]:
        e = ev[ev["beat"] == g]
        P(f"  {lab:<8} 本次 [t0, t0+10] {desc(e,'t0to10')} | 本次 EAR {desc(e,'ear')}")
    for col, lab in (("t0to10", "[t0, t0+10]"), ("ear", "EAR")):
        m, t, n = hl_diff(ev, "beat", 1, 0, col)
        P(f"  beat − 未 beat {lab}：每季差平均 {m*100:+5.2f}pp  t {t:+5.2f}（{n} 季；未 beat 樣本少，有的季沒有）")
    # winsorize ±50% 後每季橫斷面回歸斜率（每 10 個百分點驚喜對應多少 pp 超額）
    ev["w"] = ev["surp_prev"].clip(-50, 50)
    for col, lab in (("t0to10", "[t0, t0+10]"), ("ear", "EAR")):
        sl = []
        for q, g in ev.dropna(subset=[col]).groupby("q"):
            if len(g) >= 8 and g["w"].std() > 0:
                sl.append(np.polyfit(g["w"].values, g[col].values, 1)[0] * 10 * 100)
        m, t, n = qt(sl)
        P(f"  winsorize ±50% 橫斷面斜率 {lab}：上次驚喜每多 10 個百分點 → 本次超額 {m:+5.2f}pp  t {t:+5.2f}（{n} 季）")
    # 驚喜特別大（winsorize 後同季最高 1/3）vs 最低 1/3
    ev["w3"] = within_q_group(ev, "w", 3, 9)
    for g, lab in [(2, "上次驚喜最高 1/3"), (0, "上次驚喜最低 1/3")]:
        e = ev[ev["w3"] == g]
        P(f"  {lab}（中位 {e['surp_prev'].median():+5.1f}%）  本次 [t0, t0+10] {desc(e,'t0to10')}")
    m, t, n = hl_diff(ev, "w3", 2, 0, "t0to10")
    P(f"  最高 1/3 − 最低 1/3 [t0, t0+10]：每季差平均 {m*100:+5.2f}pp  t {t:+5.2f}（{n} 季）")

def main():
    C = T2.load_px(REFRESH); E = T2.load_earn(REFRESH)
    ev, drop = T2.build_events(C, E)
    P(f"T3 財報反應當排序｜30 檔核心宇宙（今日名單，倖存者偏差）｜2019-01 → {C.index.max().date()}｜事件 {len(ev)} 筆、{ev['sym'].nunique()} 檔、{ev['q'].nunique()} 季")
    P("超額 = 個股 − 基準（半導體 SMH、其餘 SPY）；勝率 = 超額 > 0；t = 每季一個橫斷面統計量的時間序列 t")
    part1(ev, "全期 2019→")
    part1(ev[ev["t0"] < "2023-01-01"], "2019–2022")
    part1(ev[ev["t0"] >= "2023-01-01"], "2023→")
    P("\n### (1b) 固定門檻版（全樣本，不分季）")
    for lab, m in [("EAR ≥ +5%", ev["ear"] >= 0.05), ("−5% < EAR < +5%", ev["ear"].abs() < 0.05), ("EAR ≤ −5%", ev["ear"] <= -0.05),
                   ("EAR ≥ +10%", ev["ear"] >= 0.10), ("EAR ≤ −10%", ev["ear"] <= -0.10)]:
        e = ev[m]; P(f"  {lab:<16} 後 60 日 {desc(e,'post60')} | 後 20 日 {desc(e,'post20')}")
    ev2 = ev.copy(); ev2["f"] = np.where(ev2["ear"] >= 0.05, 2, np.where(ev2["ear"] <= -0.05, 0, 1))
    for col, lab in (("post60", "後 60 日"), ("post20", "後 20 日")):
        m, t, n = hl_diff(ev2, "f", 2, 0, col)
        P(f"  (≥+5%) − (≤−5%) {lab}：每季差平均 {m*100:+5.2f}pp  t {t:+5.2f}（{n} 季）")
    # EAR 與本次驚喜的關係（背景）
    e = ev.dropna(subset=["surp"]); e = e.assign(w=e["surp"].clip(-50, 50))
    P(f"\n  背景：本次 EPS beat 比例 {(e['surp']>0).mean()*100:.1f}%；beat 的 EAR 平均 {e.loc[e['surp']>0,'ear'].mean()*100:+.2f}%、未 beat {e.loc[e['surp']<=0,'ear'].mean()*100:+.2f}%；EAR 與 winsorize 驚喜% 的相關 {np.corrcoef(e['w'], e['ear'])[0,1]:+.2f}")
    part2(ev, "全期 2019→")
    part2(ev[ev["t0"] < "2023-01-01"], "2019–2022")
    part2(ev[ev["t0"] >= "2023-01-01"], "2023→")
    (DATA / f"{NAME}.out.txt").write_text("\n".join(_lines) + "\n")
    print(f"\n→ {DATA / (NAME + '.out.txt')}")

if __name__ == "__main__":
    main()
