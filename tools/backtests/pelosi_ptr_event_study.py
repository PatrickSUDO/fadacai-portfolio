#!/usr/bin/env python3
"""
pelosi_ptr_event_study.py — 國會議員（預設 Pelosi）申報抄單的事件回測，資料直接來自 House Clerk 官方 PTR PDF。

流程（全自動，首跑會下載）：
  1. https://disclosures-clerk.house.gov/public_disc/financial-pdfs/<YEAR>FD.zip → 索引 → 篩 Last=<name>、FilingType=P
  2. 下載 ptr-pdfs/<YEAR>/<DocID>.pdf 到 data/ptr/，pypdf 抽文字，regex 解析每筆交易
     （買股 / 買 call = BUY；賣股 / 買 put = SELL；Exercise 不算新資訊）
  3. 事件回測：申報日（你能做到的）vs 交易日（不可行）進場，21/63/126/252 交易日超額 vs SPY / QQQ
     BUY 看正、SELL 看負；並列剔除單一極端值、獨立申報日數

結論（2026-09-05 首跑，2021-01 → 2026-08，41 買 / 26 賣 / 22 個獨立申報日）：申報延遲中位 23 天吃光短期資訊
（交易日進場 21d +6.3% → 申報日 +0.3%）；126d 均值 +5.7% 但中位 −0.4%、勝率 49%，剔除 2023-11 NVDA LEAPS 一筆後
均值 +2.0%；賣單為反指標（126d −5.9% vs QQQ）。所有 t 值 <2。詳 README.md。

用法：python3 tools/backtests/pelosi_ptr_event_study.py [--name Pelosi] [--from-year 2021]
依賴：yfinance、pandas、pypdf（pip install --user pypdf）
"""
import argparse
import io
import re
import warnings
import zipfile
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CLERK = "https://disclosures-clerk.house.gov/public_disc"
UA = {"User-Agent": "Mozilla/5.0 research"}
H = [21, 63, 126, 252]
TX_RE = re.compile(
    r"\(([A-Z][A-Z.\-]{0,5})\) \[(ST|OP)\]\s*(P|S \(partial\)|S|E)\s+(\d\d/\d\d/\d{4})\s+(\d\d/\d\d/\d{4})"
    r"\s+\$([\d,]+)\s*-\s*\$?([\d,]+)(.*?)(?=(?:SP |JT |\* For the complete))", re.S)


def _get(url):
    with urlopen(Request(url, headers=UA), timeout=60) as r:
        return r.read()


def fetch_index(name, from_year):
    rows = []
    for y in range(from_year, date.today().year + 1):
        z = DATA / f"{y}FD.zip"
        if not z.exists():
            try:
                z.write_bytes(_get(f"{CLERK}/financial-pdfs/{y}FD.zip"))
            except Exception as ex:  # noqa: BLE001
                print(f"  index {y}: {ex}")
                continue
        with zipfile.ZipFile(z) as zf:
            txt = zf.read(f"{y}FD.txt").decode("utf-8", "replace").replace("\r", "")
        for line in txt.splitlines()[1:]:
            c = line.split("\t")
            if len(c) >= 9 and c[1] == name and c[4] == "P":
                rows.append(dict(year=y, filed=pd.to_datetime(c[7]), id=c[8]))
    return pd.DataFrame(rows)


def parse_ptrs(idx):
    import pypdf
    (DATA / "ptr").mkdir(parents=True, exist_ok=True)
    rows = []
    for _, r in idx.iterrows():
        pdf = DATA / "ptr" / f"{r.id}.pdf"
        if not pdf.exists():
            pdf.write_bytes(_get(f"{CLERK}/ptr-pdfs/{r.year}/{r.id}.pdf"))
        txt = re.sub(r"\s+", " ", "\n".join(p.extract_text() for p in pypdf.PdfReader(str(pdf)).pages))
        for tk, typ, tx, d, nd, lo, hi, desc in TX_RE.findall(txt):
            desc = desc.lower()
            if tx == "E":
                continue
            if tx == "P":
                side = "BUY" if typ == "ST" or "call" in desc else "SELL"
            else:
                side = "SELL" if typ == "ST" or "call" in desc else "BUY"
            rows.append(dict(id=r.id, filed=r.filed, tx_date=pd.to_datetime(d), ticker=tk, typ=typ, side=side,
                             lo=int(lo.replace(",", "")), hi=int(hi.replace(",", ""))))
    tr = pd.DataFrame(rows).drop_duplicates(subset=["filed", "ticker", "side"]).sort_values("filed")
    tr["lag_d"] = (tr.filed - tr.tx_date).dt.days
    return tr


def event_study(tr):
    tks = sorted(set(tr.ticker)) + ["SPY", "QQQ"]
    px = yf.download(tks, start=str(tr.tx_date.min().date() - pd.Timedelta(days=30)),
                     auto_adjust=True, progress=False)["Close"]

    def fwd(tk, d, h):
        s = px[tk].dropna()
        i = s.index.searchsorted(d, side="right")
        return np.nan if i + h >= len(s) else s.iloc[i + h] / s.iloc[i] - 1

    res = []
    for _, t in tr.iterrows():
        if t.ticker not in px or px[t.ticker].dropna().empty:
            continue
        for h in H:
            for basis, d in (("disclosure", t.filed), ("tx_date(不可行)", t.tx_date)):
                r = fwd(t.ticker, d, h)
                if np.isnan(r):
                    continue
                res.append(dict(ticker=t.ticker, side=t.side, h=h, basis=basis, r=r,
                                xs_spy=r - fwd("SPY", d, h), xs_qqq=r - fwd("QQQ", d, h)))
    res = pd.DataFrame(res)
    sign = res.side.map({"BUY": 1, "SELL": -1})
    res["xs_qqq_s"], res["xs_spy_s"] = res.xs_qqq * sign, res.xs_spy * sign
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="Pelosi")
    ap.add_argument("--from-year", type=int, default=2021)
    a = ap.parse_args()
    DATA.mkdir(exist_ok=True)

    idx = fetch_index(a.name, a.from_year)
    print(f"{a.name}: PTR 申報 {len(idx)} 份（{a.from_year}–{date.today().year}）")
    tr = parse_ptrs(idx)
    print(f"交易訊號 {len(tr)} 筆 | BUY {sum(tr.side=='BUY')} / SELL {sum(tr.side=='SELL')} | "
          f"申報延遲中位 {tr.lag_d.median():.0f} 天 | 獨立申報日 {tr[tr.side=='BUY'].filed.nunique()}")
    print(tr[["filed", "tx_date", "ticker", "typ", "side", "lo", "hi"]].to_string(index=False))

    res = event_study(tr)
    print("\n=== 抄單事件回測（等權，BUY 看正、SELL 看負，超額 vs QQQ）===")
    for basis in ["disclosure", "tx_date(不可行)"]:
        print(f"\n進場基準：{basis}")
        for side in ["BUY", "SELL"]:
            for h in H:
                d = res[(res.basis == basis) & (res.side == side) & (res.h == h)]
                if len(d) < 3:
                    continue
                t = d.xs_qqq_s.mean() / (d.xs_qqq_s.std() / np.sqrt(len(d)))
                print(f"  {side:4s} {h:3d}d n={len(d):2d} | 絕對 {d.r.mean()*100:+6.1f}% | vs SPY {d.xs_spy_s.mean()*100:+6.1f}% "
                      f"| vs QQQ {d.xs_qqq_s.mean()*100:+6.1f}% (中位 {d.xs_qqq_s.median()*100:+5.1f}%, "
                      f"勝率 {(d.xs_qqq_s>0).mean()*100:.0f}%, t={t:+.2f})")
    print("\n=== BUY 申報日進場，剔除單一最大極端值 ===")
    for h in [126, 252]:
        d = res[(res.basis == "disclosure") & (res.side == "BUY") & (res.h == h)]
        d2 = d.drop(d.xs_qqq.idxmax())
        print(f"  {h}d n={len(d2)} | vs QQQ 均 {d2.xs_qqq.mean()*100:+.1f}% 中位 {d2.xs_qqq.median()*100:+.1f}% "
              f"勝率 {(d2.xs_qqq>0).mean()*100:.0f}%")


if __name__ == "__main__":
    main()
