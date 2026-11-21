"""dumb_money_sentiment_2026-11-21.py — 「Dumb Money 指數」（散戶情緒當反向指標）有沒有用？
（2026-11-21 用戶「那dumb money index有用嗎」；承 bias_overheat_2026-11-20.py 的同一套檢定）

SentimenTrader 的 Dumb Money Confidence 是付費的專屬合成指數：十多個指標、權重不公開、原始數列拿不到。
它公開點名的原料有三樣，這裡用免費資料測其中兩樣，再加上最常被當成散戶情緒的問卷：
  買權熱度   Cboe 個股選擇權 put/call 比，取 10 日均、反向（比值低 = 搶買 call = 樂觀）；2003-10→，日
  全市場買權 同上但含指數與 ETF 選擇權（個股版 2003-10 才有，這條 1995-09→，才看得到 2000 年那次）
  期貨小戶   CFTC 持倉報告「小額交易人」在 S&P 500 期貨（大型＋E-mini 換算）的淨多單 ÷ 未平倉；週二部位、週五公布；1993→
  小戶−避險者 同一份報告，小額交易人淨多 − 商業避險者淨多（SentimenTrader 的「聰明錢／散戶」差的期貨版）
  AAII 問卷  美國散戶協會每週問卷 看多% − 看空%；1987-07→，週四公布
  合成      買權熱度（2006-10 以前用全市場版代替）、期貨小戶、AAII 三者的百分位取平均，再排一次百分位 = 自製「散戶樂觀指數」
            （Rydex 資金流拿不到，沒有放）；1999-10→

每個指標都轉成「在過去 3 年（756 個交易日）裡排第幾」的百分位，只用當下以前的資料；≥90 = 極度樂觀，≤10 = 極度悲觀。
訊號在公布日收盤判定、隔日生效。資產：大盤（S&P 500 含息指數）與半導體（SMH 含息，2000-06 前用費半）。

A. 極端區之後的報酬：落在極度樂觀／極度悲觀區的日子，之後 20／60／120／250 個交易日報酬，對「同期間任意一天」的差；
   顯著性用圓形位移置換（把訊號整條平移 2,000 次），獨立事件數另列（離開 60 日以上再進入算新的一次）。
B. 做成規則，對照「平常就抱同樣比例」：過熱減碼（100% → 50%，回到中位數才買回）、恐慌加碼（70% → 100%）、兩邊都做（70%，40%／100%）；
   其餘放國庫券、每次調整 10bp；分全期、2009 以前、2010 以後。每個指標用自己有資料的全部期間。
C. 跟已經在跑的兩個落底影子重不重複：VIX ≥30、標普收 5 日新低且距 10 日高 ≤ −2%。
D. 2026 年這一次：6/22 見頂前後各指標讀數。

B2. 同樣的規則換成絕對門檻（百分位改用全部歷史；AAII 用傳統的 +30／−20）。
E. 穩健性：門檻 80／20、95／5；百分位改用全部歷史；AAII 絕對門檻分 2009 前後。

首跑結論（2026-11-21）：
- 主測（相對過去 3 年的百分位，≥90／≤10）沒有東西：96 格只有 6 格 p<0.05（純運氣預期 5 格），多重檢定校正後 0 格。
  36 條規則沒有一條在 2009 前後兩段都贏「同比例固定」；全期年化差中位數 −0.14 到 −0.27pp，回撤反而深 2–6pp。門檻換 80／20、95／5 也一樣。
- 換成絕對讀法才有一點：百分位改用全部歷史，方向對 77／96 格、p<0.05 14 格、校正後剩 3 格——但那 3 格都是期貨小戶類、各只有 4 次獨立事件。
  AAII 傳統門檻：多空差 ≥ +30 之後半導體 250 日 −2.4%（任意日 +23.1%，p 0.01，21 次）；≤ −20 之後大盤 250 日 +17.0%（任意 +12.6%，p 0.22，30 次）。
  前後段不一致：≤ −20 在 2009 以前完全沒用（大盤 +10.2% 對 +10.2%），2010 以後才有（+21.4% 對 +15.0%，p 0.03）。這些是主測失敗後才看的讀法，p 值沒校正。
- 做成規則還是贏不了少抱一點：絕對百分位版 36 條有 4 條兩段都贏、108 格 p<0.05 9 格（運氣預期 5）、Sharpe 差中位數 0；
  AAII 傳統門檻版半導體全期 +1.0 到 +1.7pp（p 0.06–0.10），但過熱減碼 2010 以後 −1.1pp，前後段方向相反。
- 落底那一側跟 VIX 重複：合成指數極度悲觀但 VIX<30，之後 250 日大盤 +4.6%（任意 +9.8%）、半導體 +11.5%（任意 +16.6%）——比平常差。
  有用的是 VIX ≥30 那一半（大盤 +23%、半導體 +45%），而「不悲觀但 VIX ≥30」一樣好（+24%／+39%）→ 已在跑的 cf-vix-spike 影子就涵蓋了。
- 2026 年這次沒幫上忙：6/22 見頂當天合成指數在第 25 百分位、AAII 多空差 −3（看空的比看多的多），AAII 全年沒到過 +30。
  買權熱度 1/29 就進極度樂觀，之後半導體到頂還漲 60%。AAII ≤ −20 在 9/17 出現，之後半導體再跌 29%。
  唯一對上的是期貨小戶：小戶−避險者 7/06–8/20 進極度樂觀（見頂之後、下跌途中還在加碼），之後半導體再跌約三成；樣本 1 次。
- 現在（11/20）：合成指數第 4 百分位、個股 put/call 10 日均 0.68、VIX 收 35.9。兩個落底讀數都亮了，依上面的拆解，有資訊的是 VIX 那個。
裁決（待用戶）：不新增影子、不進任何閘門（訊號層 2026-10-30 已凍結）。當背景讀數可以，值得看的只有 AAII ≥ +30 那種絕對極端，今年沒出現過。
限制：測的是原料不是 SentimenTrader 本尊（它另有 Rydex 資金流等十多項、權重不公開）。它自己的績效表是樣本內——
  成分是「事後看在高低點表現對」才被選進去的（官方說明頁原話：consistently shows too much pessimism near a low and too much optimism near a high）。

用法：python3 tools/backtests/dumb_money_sentiment_2026-11-21.py [--refresh]      # 需要 xlrd：uv run --with xlrd …
"""
import sys, re, json, warnings, urllib.request, urllib.parse, concurrent.futures as cf
import numpy as np, pandas as pd, yfinance as yf
from pathlib import Path
warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent; DATA = HERE / "data" / "dumb_money"; DATA.mkdir(parents=True, exist_ok=True)
REFRESH = "--refresh" in sys.argv
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
RNG = np.random.default_rng(20261121)
WIN, HI, LO, COST = 756, 90, 10, 0.001
CBOE = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/"
NAMES = {"pc": "買權熱度", "pctot": "全市場買權", "small": "期貨小戶", "gap": "小戶−避險者", "aaii": "AAII 問卷", "comp": "合成"}
KEYS = tuple(NAMES)


def get(url, timeout=40):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def cached(name, url):
    p = DATA / name
    if REFRESH or not p.exists(): p.write_bytes(get(url))
    return p


# ---------- 資料 ----------
def prices():
    p = DATA / "prices.csv"
    if REFRESH or not p.exists():
        yf.download(["^SP500TR", "SMH", "^SOX", "^IRX", "^VIX"], start="1987-01-01", auto_adjust=True, progress=False)["Close"].to_csv(p)
    d = pd.read_csv(p, index_col=0, parse_dates=True)
    d = d[d["^SP500TR"].notna()]
    r_semi = d["SMH"].pct_change().where(d["SMH"].notna() & d["SMH"].shift(1).notna(), d["^SOX"].pct_change())
    out = pd.DataFrame({"mkt": d["^SP500TR"], "semi": (1 + r_semi.fillna(0)).cumprod().where(r_semi.notna().cummax()),
                        "rf": (d["^IRX"].ffill() / 100 / 252).fillna(0), "vix": d["^VIX"]})
    return out


def _cboe_csv(name, col):
    out = {}
    for ln in cached(name, CBOE + name).read_bytes().decode("latin-1").splitlines():
        m = re.match(r"^\s*(\d{1,2}/\d{1,2}/\d{4})\s*,(.*)$", ln)
        if not m: continue
        try: out[pd.Timestamp(m.group(1))] = float(m.group(2).split(",")[col])
        except (ValueError, IndexError): pass
    return pd.Series(out).sort_index()


def putcall(days):
    """put/call 比（個股、全市場）：三段官方存檔 + 2019-10-07 之後的每日統計頁。"""
    p = DATA / "cboe_daily_pc.json"
    have = json.loads(p.read_text()) if p.exists() else {}
    need = [d for d in days if d > "2019-10-04" and (d not in have or (REFRESH and have[d] is None))]

    def one(d):
        try:
            j = {r["name"]: float(r["value"]) for r in json.loads(get(f"https://cdn.cboe.com/data/us/options/market_statistics/daily/{d}_daily_options", 20))["ratios"]}
            return d, [j["EQUITY PUT/CALL RATIO"], j["TOTAL PUT/CALL RATIO"]]
        except Exception:
            return d, None
    if need:
        with cf.ThreadPoolExecutor(8) as ex:
            for d, v in ex.map(one, need): have[d] = v
        p.write_text(json.dumps(have))
    out = []
    for i, (old, mid, new) in enumerate(((_cboe_csv("pcratioarchive.csv", 2), _cboe_csv("equitypcarchive.csv", 3), _cboe_csv("equitypc.csv", 3)),
                                         (_cboe_csv("pcratioarchive.csv", 0), _cboe_csv("totalpcarchive.csv", 3), _cboe_csv("totalpc.csv", 3)))):
        e = pd.Series({pd.Timestamp(k): v[i] for k, v in have.items() if v}).sort_index()
        x = pd.concat([old[old.index < mid.index[0]], mid[mid.index < new.index[0]], new, e[e.index > new.index[-1]]])
        out.append(x[(~x.index.duplicated()) & (x > 0)].sort_index())
    return out


def cot():
    p = DATA / "cot_legacy.csv"
    if REFRESH or not p.exists():
        q = {"$select": "report_date_as_yyyy_mm_dd,cftc_contract_market_code,open_interest_all,comm_positions_long_all,comm_positions_short_all,"
                        "nonrept_positions_long_all,nonrept_positions_short_all",
             "$where": "cftc_contract_market_code in('13874A','138741')", "$limit": "50000", "$order": "report_date_as_yyyy_mm_dd"}
        p.write_bytes(get("https://publicreporting.cftc.gov/resource/6dca-aqww.csv?" + urllib.parse.urlencode(q), 90))
    d = pd.read_csv(p, parse_dates=["report_date_as_yyyy_mm_dd"], dtype={"cftc_contract_market_code": str})
    d = d[d.cftc_contract_market_code.isin(["13874A", "138741"])].copy()
    cols = ["open_interest_all", "comm_positions_long_all", "comm_positions_short_all", "nonrept_positions_long_all", "nonrept_positions_short_all"]
    d[cols] = d[cols].mul(np.where(d.cftc_contract_market_code == "138741", 5, 1), axis=0)      # 大型契約一口 = 5 口 E-mini
    g = d.groupby("report_date_as_yyyy_mm_dd")[cols].sum()
    small = (g.nonrept_positions_long_all - g.nonrept_positions_short_all) / g.open_interest_all
    comm = (g.comm_positions_long_all - g.comm_positions_short_all) / g.open_interest_all
    out = pd.DataFrame({"small": small, "gap": small - comm})
    out.index = out.index + pd.Timedelta(days=3)                                                # 週二部位，週五下午公布
    return out[out.index >= "1993-01-01"]


def aaii():
    d = pd.read_excel(cached("aaii_sentiment.xls", "https://www.aaii.com/files/surveys/sentiment.xls"), sheet_name=0, header=None)
    d = d[pd.to_datetime(d[0], errors="coerce").notna()]
    s = pd.Series(pd.to_numeric(d[6], errors="coerce").to_numpy(), index=pd.to_datetime(d[0])).dropna()
    return s[~s.index.duplicated()].sort_index()


def build():
    px = prices(); idx = px.index
    on = lambda s: s.reindex(idx.union(s.index)).ffill().reindex(idx)                           # 公布日（含）之後才看得到
    pc, pct_ = putcall([str(d.date()) for d in idx])
    c = cot(); a = aaii()
    ma = lambda s: -on(s).rolling(10).mean().where(idx >= s.index[0])                            # 反向：越高 = 越樂觀
    raw = pd.DataFrame({"pc": ma(pc), "pctot": ma(pct_), "small": on(c.small), "gap": on(c.gap), "aaii": on(a)}, index=idx)
    pct = raw.rolling(WIN, min_periods=WIN).rank(pct=True) * 100
    opt = pct["pc"].where(pct["pc"].notna(), pct["pctot"])                                       # 個股版還沒滿 3 年以前用全市場版
    mix = pd.concat([opt, pct["small"], pct["aaii"]], axis=1).mean(axis=1, skipna=False)
    pct["comp"] = mix.rolling(WIN, min_periods=252).rank(pct=True) * 100                         # 合成後再排一次，門檻才跟單項同一把尺
    return px, raw, pct[list(KEYS)], {"pc": pc, "pctot": pct_, "cot": c, "aaii": a}


# ---------- 檢定 ----------
def episodes(mask, gap=60):
    n = 0; last = -10 ** 9
    for k in np.where(mask)[0]:
        if k - last > gap: n += 1
        last = k
    return n


def mask_stats(P, mask, valid, H, nshift=2000):
    """mask 為真的日子，隔日起 H 個交易日的報酬，對同期間任意一天的差；p 來自把 mask 整條圓形位移。"""
    fwd = P.shift(-(H + 1)) / P.shift(-1) - 1
    ok = (valid & fwd.notna()).to_numpy()
    f = fwd.to_numpy()[ok]; m = mask.to_numpy()[ok]
    if m.sum() < 30: return None
    base = f.mean(); d = f[m].mean() - base
    null = np.array([f[np.roll(m, int(k))].mean() - base for k in RNG.integers(250, len(f) - 250, nshift)])
    return dict(days=int(m.sum()), ep=episodes(m), mean=f[m].mean(), base=base, diff=d, p=float((np.abs(null) >= abs(d)).mean()), win=float((f[m] > 0).mean()))


def zone_stats(P, q, H, hi=HI, lo=LO, nshift=2000):
    return {"樂觀": mask_stats(P, q >= hi, q.notna(), H, nshift), "悲觀": mask_stats(P, q <= lo, q.notna(), H, nshift)}


KINDS = {"過熱減碼": (1.0, 0.5, None), "恐慌加碼": (0.7, None, 1.0), "兩邊都做": (0.7, 0.4, 1.0)}
WINS = {"全期": (None, None), "2009 以前": (None, "2009-12-31"), "2010 以後": ("2010-01-01", None)}


def rule_path(q, kind, hi=HI, lo=LO, mid=50.0):
    """q ≥ hi 進入減碼、回到 mid 以下才恢復；q ≤ lo 進入加碼、回到 mid 以上才恢復。mid 可以是一條跟 q 等長的數列。"""
    base, trim_to, add_to = KINDS[kind]
    mid = np.broadcast_to(np.asarray(mid, float), (len(q),))
    e = np.full(len(q), np.nan); st = 0
    for i, p in enumerate(q):
        if np.isnan(p): continue
        if st == 0:
            if trim_to is not None and p >= hi: st = 1
            elif add_to is not None and p <= lo: st = -1
        elif (st == 1 and p <= mid[i]) or (st == -1 and p >= mid[i]): st = 0
        e[i] = trim_to if st == 1 else add_to if st == -1 else base
    return e


def perf(r, rf, e):
    pos = np.roll(e, 1); pos[0] = e[0]                                                         # 收盤判定、隔日生效
    ret = pos * r + (1 - pos) * rf - COST * np.abs(np.diff(pos, prepend=pos[0]))
    nav = np.cumprod(1 + ret); cagr = nav[-1] ** (252 / len(ret)) - 1; mdd = (nav / np.maximum.accumulate(nav) - 1).min()
    return cagr, mdd, (ret - rf).mean() / ret.std() * np.sqrt(252), cagr / abs(mdd)


def eval_rule(r_all, rf_all, e_all):
    """各時段：(規則年化, 規則回撤, 年化差, 回撤差, Calmar 差, Sharpe 差, p)，差 = 規則 − 同平均比例的固定配置；不足 2 年回 None。"""
    out = {}
    for wn, (a_, b_) in WINS.items():
        e = e_all.loc[a_:b_].to_numpy(); r = r_all.loc[a_:b_].to_numpy(); rf = rf_all.loc[a_:b_].to_numpy()
        if len(e) < 500: out[wn] = None; continue
        c, d, s_, cal = perf(r, rf, e); c0, d0, s0, cal0 = perf(r, rf, np.full(len(e), e.mean()))
        null = np.array([perf(r, rf, np.roll(e, int(j)))[0] for j in RNG.integers(120, len(e) - 120, 300)])
        out[wn] = (c, d, c - c0, d - d0, cal - cal0, s_ - s0, float((null >= c).mean()))
    return out


def cells_of(res):
    return "｜".join("（不足 2 年，略）".center(46) if v is None else f"{fmt(v[0]):>6}／{fmt(v[1], 0):>5}　{v[2]*100:+5.1f}pp／{v[3]*100:+5.1f}pp（{v[6]:.2f}）" for v in res.values())


def rules_block(px, Q, show=True, **th):
    summ = []
    for asset, an in (("mkt", "大盤"), ("semi", "半導體")):
        for kind in KINDS:
            if show:
                print(f"\n  {an}｜{kind}")
                print("  指標（起點）　　　｜" + "｜".join(f"{w}：規則 年化／回撤　對同比例 年化差／回撤差（p）" for w in WINS))
            for k in Q.columns:
                st = max(Q[k].first_valid_index(), px[asset].first_valid_index())
                r_all = px[asset].loc[st:].pct_change().fillna(0)
                res = eval_rule(r_all, px["rf"].loc[st:], pd.Series(rule_path(Q[k].loc[st:].to_numpy(), kind, **th), index=r_all.index))
                if show: print(f"  {NAMES[k]:<7}（{st.year}）｜" + cells_of(res))
                summ += [(an, kind, k, wn) + v for wn, v in res.items() if v is not None]
    return summ


def rules_summary(summ):
    key = lambda x: (x[0], x[1], x[2])
    rules = sorted({key(x) for x in summ})
    sub = lambda g: [y for y in summ if key(y) == g and y[3] != "全期"]
    robust = [g for g in rules if len(sub(g)) == 2 and all(y[6] > 0 and y[8] > 0 for y in sub(g))]
    print(f"  共 {len(rules)} 條規則：2009 以前與 2010 以後「年化與 Calmar 都贏同比例固定」的 {len(robust)} 條" +
          ("：" + "、".join(f"{g[0]}{g[1]}（{NAMES[g[2]]}）" for g in robust) if robust else ""))
    print(f"  置換檢定 p<0.05 的格數 {sum(1 for x in summ if x[10] < 0.05)}/{len(summ)}（純運氣預期 {len(summ)*0.05:.0f}）")
    for kind in KINDS:
        xs = [x for x in summ if x[1] == kind and x[3] == "全期"]
        print(f"  {kind}（全期，{len(xs)} 條）：對同比例固定 年化差中位數 {np.median([x[6] for x in xs])*100:+.2f}pp（最差 {min(x[6] for x in xs)*100:+.1f}、最好 {max(x[6] for x in xs)*100:+.1f}）、"
              f"回撤差中位數 {np.median([x[7] for x in xs])*100:+.1f}pp、Sharpe 差中位數 {np.median([x[9] for x in xs]):+.2f}、Calmar 贏 {sum(1 for x in xs if x[8] > 0)}/{len(xs)}")


def fmt(x, d=1): return f"{x*100:+.{d}f}%"


def main():
    px, raw, pct, src = build()
    last = px.index[-1]
    print(f"資料到 {last.date()}｜個股 put/call {src['pc'].index[0].date()}→（{len(src['pc'])} 日）｜全市場 put/call {src['pctot'].index[0].date()}→｜"
          f"期貨持倉 {src['cot'].index[0].date()}→{src['cot'].index[-1].date()}｜AAII {src['aaii'].index[0].date()}→{src['aaii'].index[-1].date()}")
    print(f"百分位視窗 {WIN} 日；極端門檻 ≥{HI}／≤{LO}；各指標百分位起點：" + "、".join(f"{NAMES[k]} {pct[k].first_valid_index().date()}" for k in KEYS))
    c0 = pct["comp"].first_valid_index()
    print("指標彼此相關（百分位，1999-10 起）：" + "、".join(f"{NAMES[a]}×{NAMES[b]} {pct.loc[c0:, a].corr(pct.loc[c0:, b]):+.2f}"
                                               for a, b in (("pctot", "small"), ("pctot", "aaii"), ("small", "aaii"), ("pc", "pctot"), ("comp", "pctot"), ("comp", "aaii"))))
    W, Q = px, pct

    print("\n=== A. 落在極端區之後的報酬（對同期間任意一天的差；p = 圓形位移置換）===")
    rowsA = []
    for asset, an in (("mkt", "大盤"), ("semi", "半導體")):
        for k in KEYS:
            for H in (20, 60, 120, 250):
                z = zone_stats(W[asset], Q[k], H)
                for side in ("樂觀", "悲觀"):
                    if z[side]: rowsA.append((an, k, H, side, z[side]))
    for an in ("大盤", "半導體"):
        for side in ("樂觀", "悲觀"):
            print(f"\n  {an}｜極度{side}（{'之後應該比較差' if side == '樂觀' else '之後應該比較好'}才算有用）")
            print("  指標　　　　｜落在區內日數／獨立次數｜" + "｜".join(f"{H:>3} 日：區內　任意　差（p）" for H in (20, 60, 120, 250)))
            for k in KEYS:
                rs = [r for r in rowsA if r[0] == an and r[1] == k and r[3] == side]
                if not rs: continue
                s0 = rs[0][4]
                print(f"  {NAMES[k]:<8}｜{s0['days']:>5}／{s0['ep']:>3}　　　　｜" + "｜".join(
                    f"{fmt(r[4]['mean']):>7} {fmt(r[4]['base']):>7} {fmt(r[4]['diff']):>7}（{r[4]['p']:.2f}）" for r in rs))
    ps = sorted(((r[4]["p"], i) for i, r in enumerate(rowsA))); m = len(ps)
    bh = max([i for i, (p, _) in enumerate(ps, 1) if p <= 0.10 * i / m], default=0)
    good = lambda r: (r[4]["diff"] < 0) == (r[3] == "樂觀")
    print(f"\n  共 {m} 格：方向對的 {sum(map(good, rowsA))} 格；p<0.05 的 {sum(1 for p, _ in ps if p < 0.05)} 格（純運氣預期 {m*0.05:.0f} 格）；多重檢定校正（BH 10%）後剩 {bh} 格")
    for side in ("樂觀", "悲觀"):
        rr = [r for r in rowsA if r[3] == side]
        print(f"  極度{side}：方向對 {sum(map(good, rr))}/{len(rr)} 格；p<0.05 且方向對 {sum(1 for r in rr if r[4]['p'] < 0.05 and good(r))} 格；"
              f"p<0.05 但方向反 {sum(1 for r in rr if r[4]['p'] < 0.05 and not good(r))} 格")
    survivors = [rowsA[i] for p, i in ps[:bh]]
    if survivors:
        print("  校正後還在的：" + "；".join(f"{r[0]} {NAMES[r[1]]} 極度{r[3]} {r[2]} 日 {fmt(r[4]['diff'])}（{'方向對' if good(r) else '方向反'}，{r[4]['ep']} 次）" for r in survivors))

    print("\n=== B. 做成規則 vs 平常就抱同樣比例（年化／最大回撤；差 = 規則 − 同比例固定；p = 置換後年化 ≥ 規則的比例）===")
    summ = rules_block(px, pct, show=True)
    print()
    rules_summary(summ)

    print("\n=== B2. 同樣的規則，換成「絕對」門檻（A 段最有訊號的讀法）===")
    ex = raw.expanding(min_periods=WIN).rank(pct=True) * 100
    opt = ex["pc"].where(ex["pc"].notna(), ex["pctot"])
    ex["comp"] = pd.concat([opt, ex["small"], ex["aaii"]], axis=1).mean(axis=1, skipna=False).expanding(min_periods=252).rank(pct=True) * 100
    ex = ex[list(KEYS)]
    print("  百分位改用到當天為止的全部歷史（≥90／≤10，回到 50 恢復）：")
    rules_summary(rules_block(px, ex, show=False))
    sp = raw["aaii"]; mean_sp = sp.expanding(min_periods=WIN).mean()
    print("  AAII 用傳統門檻（多空差 ≥ +30 減碼、≤ −20 加碼，回到當時的歷史平均才恢復）：")
    for asset, an in (("mkt", "大盤"), ("semi", "半導體")):
        st = max(mean_sp.first_valid_index(), px[asset].first_valid_index())
        r_all = px[asset].loc[st:].pct_change().fillna(0)
        for kind in KINDS:
            e = pd.Series(rule_path(sp.loc[st:].to_numpy(), kind, 0.30, -0.20, mean_sp.loc[st:].to_numpy()), index=r_all.index)
            print(f"    {an}｜{kind}（{st.year}，平均比例 {e.mean()*100:.0f}%）｜" + cells_of(eval_rule(r_all, px["rf"].loc[st:], e)))

    print("\n=== C. 跟已經在跑的落底影子重不重複（合成指數極度悲觀 × VIX ≥30 × 標普急跌訊號；1999-10 起）===")
    W = px.loc[c0:]; comp = pct["comp"].loc[c0:]; pess = comp <= LO; v30 = W["vix"] >= 30
    m5 = W["mkt"]; dip = (m5 <= m5.rolling(5).min()) & (m5 / m5.rolling(10).max() - 1 <= -0.02)
    near = lambda s, n=10: s.astype(float).rolling(2 * n + 1, center=True, min_periods=1).max().astype(bool)
    print(f"  極度悲觀 {int(pess.sum())} 日：其中當天 VIX ≥30 的 {(pess & v30).sum()/pess.sum()*100:.0f}%；前後 10 日內出現過 VIX ≥30 的 {(pess & near(v30)).sum()/pess.sum()*100:.0f}%；"
          f"前後 10 日內出現過急跌訊號的 {(pess & near(dip)).sum()/pess.sum()*100:.0f}%")
    print(f"  反過來：VIX ≥30 的 {int(v30.sum())} 日裡，合成指數同時極度悲觀的 {(pess & v30).sum()/v30.sum()*100:.0f}%")
    for asset, an in (("mkt", "大盤"), ("semi", "半導體")):
        for H in (60, 250):
            fwd = W[asset].shift(-(H + 1)) / W[asset].shift(-1) - 1; ok = fwd.notna() & comp.notna()
            cell = lambda mk: f"{fmt(fwd[ok & mk].mean())}（{int((ok & mk).sum())} 日／{episodes((ok & mk).to_numpy())} 次）" if (ok & mk).sum() >= 20 else "樣本不足"
            print(f"  {an} {H:>3} 日後：任意 {fmt(fwd[ok].mean())}｜悲觀且 VIX<30 {cell(pess & ~v30)}｜悲觀且 VIX≥30 {cell(pess & v30)}｜不悲觀但 VIX≥30 {cell(~pess & v30)}｜急跌訊號 {cell(dip)}")

    print("\n=== D. 2026 年這一次（百分位；≥90 極度樂觀、≤10 極度悲觀）===")
    for d in ("2026-01-02", "2026-04-24", "2026-05-22", "2026-06-22", "2026-07-22", "2026-08-21", "2026-10-29", str(last.date())):
        i = px.index[px.index.get_indexer([pd.Timestamp(d)], method="pad")[0]]
        print(f"  {i.date()}｜" + "｜".join(f"{NAMES[k]} {pct.loc[i, k]:>3.0f}" for k in KEYS) +
              f"｜半導體自年初 {fmt(px.loc[i, 'semi']/px.loc['2025-12-31', 'semi']-1, 0)}｜AAII 多空差 {raw.loc[i, 'aaii']*100:+.0f}、個股 put/call 10 日均 {-raw.loc[i, 'pc']:.2f}")
    y = pct.loc["2026-01-01":]
    f = lambda s: "沒有" if s.empty else f"{len(s)} 日，首次 {s.index[0].date()}、最後 {s.index[-1].date()}"
    for k in KEYS:
        print(f"  2026 年 {NAMES[k]}：極度樂觀 {f(y[k][y[k] >= HI])}；極度悲觀 {f(y[k][y[k] <= LO])}")
    pk = pd.Timestamp("2026-06-22"); pre = pct.loc[pk - pd.Timedelta(days=90):pk]
    print("  見頂前 90 天內各指標最高百分位：" + "、".join(f"{NAMES[k]} {pre[k].max():.0f}（{pre[k].idxmax().date()}）" for k in KEYS))
    s = px["semi"]
    for k in ("pc", "aaii", "comp"):
        hi_c = y[k][y[k] >= HI]
        if not hi_c.empty:
            d0 = hi_c.index[0]
            print(f"  {NAMES[k]} 2026 年首次極度樂觀 {d0.date()}：半導體從那天到 6/22 {fmt(s.loc[pk]/s.loc[d0]-1, 0)}、到最新 {fmt(s.iloc[-1]/s.loc[d0]-1, 0)}")


    print("\n=== E. 穩健性：換門檻、換百分位算法、AAII 用傳統的絕對門檻 ===")

    def sweep(Qx, hi, lo):
        rows = []
        for asset in ("mkt", "semi"):
            for k in KEYS:
                for H in (20, 60, 120, 250):
                    z = zone_stats(px[asset], Qx[k], H, hi, lo, 1000)
                    rows += [(side, z[side], f"{'大盤' if asset == 'mkt' else '半導體'} {NAMES[k]} 極度{side} {H} 日") for side in ("樂觀", "悲觀") if z[side]]
        rows.sort(key=lambda r: r[1]["p"]); ps = [r[1]["p"] for r in rows]; n = len(ps)
        bh = max([i for i, p in enumerate(ps, 1) if p <= 0.10 * i / n], default=0)
        right = sum(1 for sd, r, _ in rows if (r["diff"] < 0) == (sd == "樂觀"))
        return (f"{n} 格，方向對 {right}，p<0.05 {sum(p < 0.05 for p in ps)}（運氣預期 {n*0.05:.0f}），校正後剩 {bh}" +
                ("：" + "；".join(f"{nm} {fmt(r['diff'])}（{r['ep']} 次）" for _, r, nm in rows[:bh]) if bh else ""))
    print(f"  門檻 80／20（3 年視窗）：{sweep(pct, 80, 20)}")
    print(f"  門檻 95／5（3 年視窗）：{sweep(pct, 95, 5)}")
    print(f"  門檻 90／10（百分位改用到當天為止的全部歷史）：{sweep(ex, 90, 10)}")
    a = raw["aaii"]
    for nm, mk in (("AAII 多空差 ≤ −20（散戶極度看空）", a <= -0.20), ("AAII 多空差 ≥ +30（散戶極度看多）", a >= 0.30)):
        for asset, an in (("mkt", "大盤"), ("semi", "半導體")):
            zs = [(H, mask_stats(px[asset], mk, a.notna(), H)) for H in (60, 120, 250)]
            print(f"  {nm}｜{an}｜{zs[0][1]['days']} 日／{zs[0][1]['ep']} 次｜" +
                  "｜".join(f"{H} 日 {fmt(z['mean'])} vs 任意 {fmt(z['base'])}（p {z['p']:.2f}、勝率 {z['win']*100:.0f}%）" for H, z in zs))

    print("  AAII 絕對門檻分前後段（250 日後；區內 vs 同段任意一天）：")
    for nm, mk in (("≤ −20", a <= -0.20), ("≥ +30", a >= 0.30)):
        for asset, an in (("mkt", "大盤"), ("semi", "半導體")):
            cells = []
            for wn, (a_, b_) in (("2009 以前", (None, "2009-12-31")), ("2010 以後", ("2010-01-01", None))):
                z = mask_stats(px[asset].loc[a_:b_], mk.loc[a_:b_], a.loc[a_:b_].notna(), 250)
                cells.append(f"{wn} " + (f"{fmt(z['mean'])} vs {fmt(z['base'])}（{z['days']} 日／{z['ep']} 次，p {z['p']:.2f}）" if z else "樣本不足（不到 30 日）"))
            print(f"    {nm}｜{an}｜" + "｜".join(cells))
    wk = src["aaii"]["2026"]; sm = px["semi"]
    for nm, hit in (("≥ +30", wk[wk >= 0.30]), ("≤ −20", wk[wk <= -0.20])):
        print(f"  2026 年 AAII {nm} 的週數 {len(hit)}" + ("：" + "、".join(
            f"{d.date()}（{v*100:+.0f}，半導體之後到最新 {fmt(sm.iloc[-1] / sm.loc[:d].iloc[-1] - 1, 0)}）" for d, v in hit.items()) if len(hit) else ""))


if __name__ == "__main__":
    main()
