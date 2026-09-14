#!/usr/bin/env python3
"""journal_stub.py — 當日 journal 缺檔時的機械補檔（2026-09-14）

9/14 launchd telegram tier 跑完沒寫 journal/2026-09-14.md（Step 0c 是散文規則）。journal 是歸因
（plan_order_refs 掃 journal 找單號）與旗標稽核的資料層，斷一天就有一天的成交無法歸因。
本工具不做判斷：只從 position-state.json（guard 渲染表）+ 當日成交（trade-ledger）產生骨架，
標明 `⚠️ 機械補檔`，模型/用戶之後可補理由。已存在則不動。

Usage: python3 tools/journal_stub.py [YYYY-MM-DD]   （預設今天；exit 0 已存在或已建立）
"""
import json, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(day: str) -> int:
    path = ROOT / "journal" / f"{day}.md"
    if path.exists():
        print(f"journal 已存在：{path.name}")
        return 0
    st = json.loads((ROOT / "research" / "position-state.json").read_text()) if (ROOT / "research" / "position-state.json").exists() else {}
    fills = []
    led = ROOT / "research" / "trade-ledger.jsonl"
    if led.exists():
        for line in led.read_text().splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("date") == day:
                fills.append(r)
    lines = [f"# {day} 交易日誌", "",
             f"> ⚠️ 機械補檔（journal_stub.py）：模型當日未寫 journal，本檔由 position-state + trade-ledger 生成，理由欄待補。權威倉位以 Firstrade live 為準。", ""]
    if st:
        lines += [f"## 倉位快照（position_guard {st.get('asof')}，來源 {st.get('source')}）",
                  f"- 總值 **${st.get('total_account_value', 0):,.0f}**｜現金 ${st.get('cash', 0):,.0f}（+停泊 ${st.get('parked_cash_equiv', 0):,.0f}）", "",
                  "| 標的 | 桶 | 股數 | 成本 | 現價 | 權重 | 未實現 | 自峰 | R23 |", "|---|---|---:|---:|---:|---:|---:|---:|---|"]
        for p in st.get("positions", []):
            lines.append(f"| {p.get('symbol')} | {p.get('bucket')} | {p.get('qty')} | {p.get('unit_cost')} | {p.get('last')} | "
                         f"{p.get('weight_pct')}% | {p.get('unrealized_pct')}% | {p.get('drawdown_from_peak_pct')}% | {p.get('r23_armed') or '—'} |")
        lines.append("")
    lines += ["## 當日成交（trade-ledger）"]
    if fills:
        lines += ["| 標的 | 方向 | 股數 | 價 | origin | 依據 |", "|---|---|---:|---:|---|---|"]
        for r in fills:
            lines.append(f"| {r.get('symbol')} | {r.get('side')} | {r.get('qty')} | {r.get('price')} | {r.get('origin') or '?'} | {(r.get('origin_evidence') or '')[:80]} |")
    else:
        lines.append("- 無成交")
    lines += ["", "## 決策項（待補）", "- （機械補檔：當日 briefing 見 briefing-out/" + day + "-full.md）", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"已建立機械補檔：{path.name}（{len(fills)} 筆成交）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()))
