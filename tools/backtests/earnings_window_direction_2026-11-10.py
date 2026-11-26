"""T2 財報窗方向：R18「財報前後 48 小時不加新曝險」是不是擋錯方向？財報前 10 日內停利是不是賣早？
宇宙：30 檔核心（vix_spike_timing_2026-11-07.py 的 HOLD+CAND，今日名單 → 倖存者偏差；所以一律跟
「同一檔的任意日窗」比，不跟零比）。2019 起。基準：半導體（tools/trade_ledger.py SEMI_AI）用 SMH、其餘 SPY。
財報日與 EPS 驚喜：yfinance Ticker.get_earnings_dates(limit=60)；時間戳 ≥16 點視為盤後 → 反應日 t0＝下一個交易日，
否則 t0＝當日。快取 data/earnings_dates_2026-11-10.csv（--refresh 重抓）。價格 auto_adjust=True。
窗（都是收盤對收盤，個股報酬 − 基準報酬）：
  前 10 日 [t0−11 收 → t0−1 收]、反應 2 日 [t0−1 收 → t0+1 收]、後 20 日 [t0+1 收 → t0+21 收]、後 60 日 [t0+1 收 → t0+61 收]、
  跨財報持有 12 日 [t0−11 收 → t0+1 收]。
對照：同檔 2019 起所有同長度窗（任意日），以及其中「不含任何反應日（t0、t0+1）」的窗（非財報窗；60 日幾乎必含財報故只列任意日）。
t 值：財報擠在同幾週 → 每個日曆季取一個橫斷面平均（事件值 − 該檔對照平均），對季序列算 t。
另讀 research/shadow-signals.jsonl 的 earnings-window-blocked-add 逐筆列出（軼事，不進統計）。
用法：python3 earnings_window_direction_2026-11-10.py [--refresh]
輸出：data/earnings_window_direction_2026-11-10.out.txt

首跑結論（2026-11-10）：
- 903 筆事件、30 檔、32 季；反應日對位檢查 75% 的最大單日波動落在 t0（時間戳大致可信）。
- 前 10 日超額 +1.11% vs 同檔非財報窗 +0.41%（差 +0.69pp，季群集 t +1.33）。
- 反應 2 日 +1.22% vs +0.10%（差 +1.12pp，t +2.76）；代價是標準差 11.3% vs 3.3%，跌 ≥10% 的事件佔 13.1%、漲 ≥10% 佔 17.3%。
- 跨財報持有 12 日 +2.35% vs +0.49%（差 +1.86pp，t +2.81）；平均÷標準差 0.170 vs 0.064。
- 財報後沒有補回：後 20 日差 +0.07pp（t +0.03）、後 60 日 −0.93pp（t −0.94）。
- 不穩：2019–2022 反應 2 日差只有 +0.27pp（t +0.45），全靠 2023→ 的 +1.94pp（t +3.64）；半導體 +0.49pp（t +1.03）、其餘 +1.50pp（t +2.41）。
  拿掉反應最好的 5 檔（GEV／HWM／STRL／CLS／ATI）後反應 2 日 +0.65pp（t +1.43）、12 日 +1.39pp（t +2.12）。
- (b) 財報前賣出：t0−10／−5／−1 收盤賣，到 t0+1 放棄 +1.51／+1.36／+1.08pp（t +2.27／+2.73／+2.67）；拉到 t0+21、t0+61 差距不顯著（t ≤ +1.0）。
- 判讀：這份名單上，財報窗平均有正補償、等財報後再買沒有比較便宜 → R18 在「平均報酬」上擋錯方向，買到的是尾部（單次 −15% 以下佔 5%）。
  但名單是今天的贏家，贏家的財報反應本來就偏正；2019–2022 不顯著。當作「R18 不是免費的」的證據，不足以單獨推翻。
- 軼事 6 筆（R18 實際擋下的加碼）：8/4 四筆至今（68 日）對基準 AMD +13.4pp、ANET +13.1pp、DDOG −35.5pp、ONTO −17.2pp；10/30 兩筆才 6 日。
- 限制：倖存者偏差；yfinance 歷史時間戳有 25% 對不到最大波動日；EPS 驚喜為 yfinance 口徑；基準未扣 β。
"""
import sys, json, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = HERE / "data"; DATA.mkdir(exist_ok=True)
NAME = "earnings_window_direction_2026-11-10"
REFRESH = "--refresh" in sys.argv
ECSV = DATA / "earnings_dates_2026-11-10.csv"
PCSV = DATA / "earnings_px_2026-11-10.csv"
HOLD = ['AMAT','ANET','AVGO','CLS','CRM','CRWD','DIOD','MU','NET','NVDA','PLTR','PWR','SNPS','TWLO']
CAND = ['HWM','ATI','FN','GEV','COHR','VRT','PAYC','WDAY','DOCU','ZS','OKTA','AMZN','LITE','MRVL','ONTO','STRL']
U = HOLD + CAND
SEMI_AI = {"AMD","ANET","ARM","ASML","AVGO","COHR","CRDO","DIOD","ICHR","INTC","LITE","LRCX","MRVL","MU","NVDA","ON","ONTO",
           "QCOM","SNPS","STX","TSM","CIEN","CDNS","KLAC","AMAT","TER"}   # = tools/trade_ledger.py SEMI_AI（2026-11-10 抄錄）
BENCH = {s: ("SMH" if s in SEMI_AI else "SPY") for s in U}
START = pd.Timestamp("2019-01-01")

_lines = []
def P(*a):
    s = " ".join(str(x) for x in a); print(s); _lines.append(s)

def load_px(refresh=False):
    if PCSV.exists() and not refresh:
        return pd.read_csv(PCSV, index_col=0, parse_dates=True)
    import yfinance as yf
    c = yf.download(U + ["SMH", "SPY"], start="2018-06-01", progress=False, auto_adjust=True, threads=True)["Close"]
    c = c.dropna(axis=1, how="all"); c.to_csv(PCSV); return c

def load_earn(refresh=False):
    """回傳 DataFrame[sym, ts(紐約時間, naive), hour, eps_est, eps_rep, surp]；抓不到的 ticker 在 attrs['failed']。"""
    if ECSV.exists() and not refresh:
        e = pd.read_csv(ECSV, parse_dates=["ts"]); e.attrs["failed"] = sorted(set(U) - set(e["sym"])); return e
    import yfinance as yf
    rows, failed = [], []
    for s in U:
        d = None
        for _ in range(3):
            try:
                d = yf.Ticker(s).get_earnings_dates(limit=60)
                if d is not None and len(d): break
            except Exception:
                d = None
        if d is None or not len(d):
            failed.append(s); continue
        d = d.reset_index(); d.columns = ["ts", "eps_est", "eps_rep", "surp"][:len(d.columns)]
        d["ts"] = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York").dt.tz_localize(None)
        d["sym"] = s; rows.append(d)
    e = pd.concat(rows, ignore_index=True); e["hour"] = e["ts"].dt.hour
    e = e[["sym", "ts", "hour", "eps_est", "eps_rep", "surp"]].sort_values(["sym", "ts"])
    e.to_csv(ECSV, index=False); e.attrs["failed"] = failed; return e

def build_events(C, E):
    """每筆事件算好各窗超額。回傳 (events DataFrame, 丟棄統計)。"""
    now = C.index.max(); out = []; drop = {"未公布或缺 EPS": 0, "2019 前": 0, "重複日": 0, "價格不足": 0}
    for s, g in E.groupby("sym"):
        if s not in C.columns: continue
        b = BENCH[s]; d = C[[s, b]].dropna(); idx = d.index; ps, pb = d[s].values, d[b].values
        g = g.sort_values("ts"); seen = set(); prev = np.nan
        for r in g.itertuples():
            day = r.ts.normalize()
            if pd.isna(r.eps_rep) and pd.isna(r.surp): drop["未公布或缺 EPS"] += 1; continue
            if day in seen: drop["重複日"] += 1; continue
            seen.add(day)
            surp_prev, prev = prev, r.surp          # 上一次驚喜（含 2019 前那一次）
            if day < START: drop["2019 前"] += 1; continue
            i0 = idx.searchsorted(day, side="right" if r.hour >= 16 else "left")
            if i0 >= len(idx) or i0 < 12 or idx[i0] > now: drop["價格不足"] += 1; continue
            x = lambda a, z: ((ps[z] / ps[a] - 1) - (pb[z] / pb[a] - 1)) if (a >= 0 and z < len(idx)) else np.nan
            d1 = lambda k: x(i0 + k - 1, i0 + k)
            out.append(dict(sym=s, bench=b, ts=r.ts, hour=r.hour, t0=idx[i0], i0=i0, surp=r.surp, surp_prev=surp_prev,
                            pre10=x(i0 - 11, i0 - 1), ear=x(i0 - 1, i0 + 1), post20=x(i0 + 1, i0 + 21), post60=x(i0 + 1, i0 + 61),
                            hold12=x(i0 - 11, i0 + 1), t0to10=x(i0 - 1, i0 + 10),
                            raw_ear=(ps[i0 + 1] / ps[i0 - 1] - 1) if i0 + 1 < len(idx) else np.nan,
                            dm1=d1(-1), d0=d1(0), dp1=d1(1),
                            **{f"s{k}_{h}": x(i0 - k, i0 + h) for k in (10, 5, 1) for h in (1, 21, 61)}))
    ev = pd.DataFrame(out); ev["q"] = ev["t0"].dt.to_period("Q")
    return ev, drop

def baselines(C, ev, lengths):
    """同檔任意日窗、非財報窗（不含任何 t0、t0+1 日報酬）的平均／勝率／標準差。"""
    res = {}
    for s in ev["sym"].unique():
        b = BENCH[s]; d = C[[s, b]].dropna(); d = d[d.index >= START - pd.Timedelta(days=20)]
        n = len(d); react = np.zeros(n)
        pos0 = d.index.searchsorted(ev.loc[ev["sym"] == s, "t0"].values)
        for p in pos0:
            for k in (0, 1):
                if 0 <= p + k < n: react[p + k] = 1
        cum = np.concatenate([[0], np.cumsum(react)])
        for L in lengths:
            xs = (d[s].shift(-L) / d[s] - 1) - (d[b].shift(-L) / d[b] - 1)
            xs = xs.values[: n - L]; j = np.arange(n - L)
            clean = (cum[j + L + 1] - cum[j + 1]) == 0      # 窗內日報酬為 j+1 … j+L
            ok = d.index[: n - L] >= START
            a, c = xs[ok], xs[ok & clean]
            res[(s, L)] = dict(any_mean=a.mean(), any_win=(a > 0).mean(), any_sd=a.std(), any_n=len(a),
                               cl_mean=c.mean() if len(c) else np.nan, cl_win=(c > 0).mean() if len(c) else np.nan,
                               cl_sd=c.std() if len(c) else np.nan, cl_n=len(c))
    return res

def qt(series_by_q):
    x = np.asarray(series_by_q, float); x = x[~np.isnan(x)]
    return (x.mean() / (x.std(ddof=1) / np.sqrt(len(x))), len(x)) if len(x) >= 6 and x.std(ddof=1) > 0 else (np.nan, len(x))

def row(ev, base, col, L, label, use_clean=True):
    e = ev[ev[col].notna()]
    if not len(e): P(f"  {label:<26} （無樣本）"); return
    k = "cl_mean" if use_clean else "any_mean"
    bm = e["sym"].map(lambda s: base[(s, L)][k]); anym = e["sym"].map(lambda s: base[(s, L)]["any_mean"])
    anyw = e["sym"].map(lambda s: base[(s, L)]["any_win"]); bsd = e["sym"].map(lambda s: base[(s, L)]["cl_sd" if use_clean else "any_sd"])
    adj = e[col] - bm; t, nq = qt(adj.groupby(e["q"]).mean())
    P(f"  {label:<26} 事件 平均 {e[col].mean()*100:+6.2f}%  中位 {e[col].median()*100:+6.2f}%  勝率 {(e[col]>0).mean()*100:4.1f}%  標準差 {e[col].std()*100:5.2f}%  n={len(e):>3}"
      f" | 同檔任意日 {anym.mean()*100:+5.2f}%（勝率 {anyw.mean()*100:4.1f}%）" + (f"、非財報窗 {bm.mean()*100:+5.2f}%（標準差 {bsd.mean()*100:5.2f}%）" if use_clean else "")
      + f" | 事件 − {'非財報窗' if use_clean else '任意日'} {adj.mean()*100:+5.2f}pp  季群集 t {t:+5.2f}（{nq} 季）")

LEN = {"pre10": 10, "ear": 2, "post20": 20, "post60": 60, "hold12": 12}
SELL_LEN = {(k, h): k + h for k in (10, 5, 1) for h in (1, 21, 61)}

def block(ev, base, title):
    P(f"\n### {title}｜事件 {len(ev)} 筆、{ev['sym'].nunique()} 檔、{ev['q'].nunique()} 季")
    row(ev, base, "pre10", 10, "前 10 日 [t0−11→t0−1]")
    row(ev, base, "ear", 2, "反應 2 日 [t0−1→t0+1]")
    row(ev, base, "hold12", 12, "跨財報持有 12 日")
    row(ev, base, "post20", 20, "後 20 日 [t0+1→t0+21]")
    row(ev, base, "post60", 60, "後 60 日 [t0+1→t0+61]", use_clean=False)

def anecdotes(C):
    P("\n### 軼事：shadow-signals.jsonl 的 earnings-window-blocked-add（R18 實際擋下的加碼，不進統計）")
    f = ROOT / "research/shadow-signals.jsonl"
    rows = [json.loads(l) for l in open(f) if l.strip()]
    rows = [r for r in rows if "earnings-window-blocked-add" in (str(r.get("signal")), str(r.get("kind")))]
    import yfinance as yf
    need = sorted({r["ticker"] for r in rows} | {"SMH", "SPY"})
    px = yf.download(need, start="2026-07-01", progress=False, auto_adjust=True)["Close"]
    P(f"  共 {len(rows)} 筆。之後表現 = 登錄日收盤 → 各點收盤；超額 = 個股 − 基準（SEMI_AI 用 SMH，其餘 SPY）；最後收盤日 {px.index.max().date()}")
    for r in rows:
        s = r["ticker"]; b = "SMH" if s in SEMI_AI else "SPY"; d = px[[s, b]].dropna(); day = pd.Timestamp(r["date"])
        if day not in d.index: P(f"  {r['date']} {s}: 登錄日無收盤價"); continue
        i = d.index.get_loc(day); parts = []
        for h in (5, 20, 60):
            if i + h < len(d):
                parts.append(f"{h} 日 {(d[s].iloc[i+h]/d[s].iloc[i]-1)*100:+.1f}%（超額 {((d[s].iloc[i+h]/d[s].iloc[i])-(d[b].iloc[i+h]/d[b].iloc[i]))*100:+.1f}pp）")
            else: parts.append(f"{h} 日 未到")
        n = len(d) - 1 - i
        parts.append(f"至今 {n} 日 {(d[s].iloc[-1]/d[s].iloc[i]-1)*100:+.1f}%（超額 {((d[s].iloc[-1]/d[s].iloc[i])-(d[b].iloc[-1]/d[b].iloc[i]))*100:+.1f}pp）")
        P(f"  {r['date']} {s:<5} 被擋價 {r.get('ref_price')}（當日收盤 {d[s].iloc[i]:.2f}）擬加 ${r.get('size_usd'):,.0f} 基準 {b}｜" + "；".join(parts))
        P(f"      備註：{r.get('note','')[:110]}")

def main():
    C = load_px(REFRESH); E = load_earn(REFRESH)
    ev, drop = build_events(C, E)
    lens = sorted(set(LEN.values()) | set(SELL_LEN.values()))
    base = baselines(C, ev, lens)
    P(f"T2 財報窗方向｜30 檔核心宇宙（今日名單，倖存者偏差）｜2019-01 → {C.index.max().date()}")
    P(f"財報日抓不到的 ticker：{E.attrs.get('failed') or '無'}；丟棄：{drop}")
    P(f"事件 {len(ev)} 筆、{ev['sym'].nunique()} 檔；盤後（≥16 點，t0 取隔日）{(ev['hour']>=16).mean()*100:.0f}%、盤前/盤中 {(ev['hour']<16).mean()*100:.0f}%；基準 SMH {(ev['bench']=='SMH').sum()} 筆、SPY {(ev['bench']=='SPY').sum()} 筆")
    per = ev.groupby("sym").size(); P("每檔事件數：" + "、".join(f"{s} {n}" for s, n in per.items()))
    # 反應日對位檢查：|超額| 最大的一天落在 t0−1／t0／t0+1 的比例
    a = ev[["dm1", "d0", "dp1"]].abs().dropna(); w = a.values.argmax(axis=1)
    P(f"反應日對位檢查：三天中 |單日超額| 最大者落在 t0−1 {np.mean(w==0)*100:.0f}%、t0 {np.mean(w==1)*100:.0f}%、t0+1 {np.mean(w==2)*100:.0f}%（t0 平均 |超額| {a['d0'].mean()*100:.1f}%、t0−1 {a['dm1'].mean()*100:.1f}%、t0+1 {a['dp1'].mean()*100:.1f}%）")
    P("欄位：事件平均／中位／勝率（超額 > 0）；對照＝同檔 2019 起同長度窗；季群集 t＝每季橫斷面平均（事件 − 該檔對照）的 t")
    block(ev, base, "全期 2019→")
    block(ev[ev["t0"] < "2023-01-01"], base, "2019–2022")
    block(ev[ev["t0"] >= "2023-01-01"], base, "2023→")
    block(ev[ev["bench"] == "SMH"], base, "半導體（對 SMH）")
    block(ev[ev["bench"] == "SPY"], base, "其餘（對 SPY）")
    P("\n### (b) 財報前賣出放棄了什麼：賣出點 → 之後到 t0+1／t0+21／t0+61 的超額（正 = 賣早）；對照 = 同檔任意日同長度窗")
    for k in (10, 5, 1):
        for h, hl in ((1, "到 t0+1"), (21, "到 t0+21"), (61, "到 t0+61")):
            row(ev, base, f"s{k}_{h}", k + h, f"t0−{k} 收盤賣，{hl}", use_clean=False)
    # 風險補償：跨財報 12 日 vs 非財報 12 日的 平均/標準差
    e = ev.dropna(subset=["hold12"]); sd = e["sym"].map(lambda s: base[(s, 12)]["cl_sd"]); mu = e["sym"].map(lambda s: base[(s, 12)]["cl_mean"])
    P(f"\n### 補償：跨財報 12 日 平均 {e['hold12'].mean()*100:+.2f}%／標準差 {e['hold12'].std()*100:.2f}% → 比值 {e['hold12'].mean()/e['hold12'].std():+.3f}；"
      f"同檔非財報 12 日 平均 {mu.mean()*100:+.2f}%／標準差 {sd.mean()*100:.2f}% → 比值 {mu.mean()/sd.mean():+.3f}")
    P(f"    反應 2 日最差 5% 分位 {e['ear'].quantile(0.05)*100:+.1f}%、最差 {e['ear'].min()*100:+.1f}%；跌幅 ≤ −10% 的比例 {(e['ear']<=-0.10).mean()*100:.1f}%、漲幅 ≥ +10% 的比例 {(e['ear']>=0.10).mean()*100:.1f}%")
    # 倖存者偏差敏感度：贏家名單的財報反應本來就偏正 → 看有幾檔為正、拿掉反應最好的 5 檔還剩多少
    per = ev.groupby("sym").agg(ear=("ear", "mean"), hold=("hold12", "mean"), n=("ear", "size"))
    per["ear_adj"] = per["ear"] - per.index.map(lambda s: base[(s, 2)]["cl_mean"]); per["hold_adj"] = per["hold"] - per.index.map(lambda s: base[(s, 12)]["cl_mean"])
    top5 = per["ear"].sort_values(ascending=False).index[:5].tolist(); rest = ev[~ev["sym"].isin(top5)]
    P(f"\n### 倖存者偏差敏感度：{len(per)} 檔中 反應 2 日平均高於自身非財報窗的 {(per['ear_adj']>0).sum()} 檔、跨財報 12 日高於自身非財報窗的 {(per['hold_adj']>0).sum()} 檔")
    P(f"  反應 2 日平均最高的 5 檔：" + "、".join(f"{s} {per.loc[s,'ear']*100:+.1f}%" for s in top5) + "；最低 5 檔：" + "、".join(f"{s} {per.loc[s,'ear']*100:+.1f}%" for s in per['ear'].sort_values().index[:5]))
    P("  拿掉最高 5 檔後：")
    row(rest, base, "ear", 2, "反應 2 日 [t0−1→t0+1]")
    row(rest, base, "hold12", 12, "跨財報持有 12 日")
    row(rest, base, "pre10", 10, "前 10 日 [t0−11→t0−1]")
    try:
        anecdotes(C)
    except Exception as ex:
        P(f"  軼事段失敗：{ex!r}")
    (DATA / f"{NAME}.out.txt").write_text("\n".join(_lines) + "\n")
    print(f"\n→ {DATA / (NAME + '.out.txt')}")

if __name__ == "__main__":
    main()
