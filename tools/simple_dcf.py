#!/usr/bin/env python3
"""
simple_dcf.py — 自建 2-stage DCF（台股自建估值錨，免付費 API）。

純 stdlib、無外部依賴、deterministic。Skill 把已從 FinMind MCP 抓到的
FCF / shares / cash / debt / growth 餵進來，得到內在價值/股，作 sanity flag
（不進 EV，僅與三錨點公允價交叉）。

用法：
  python3 tools/simple_dcf.py --fcf 2269700096 --shares 875553173 \\
      --cash 3843599872 --debt 5277199872 --growth 0.30 \\
      [--wacc 0.10] [--terminal 0.03] [--years 5]

輸出 JSON：intrinsic_value_per_share + 假設 + PV 拆解。
高成長股 DCF 對假設極敏感 → 僅作參考錨，不作主要估值。
"""
import argparse
import json
import sys


def two_stage_dcf(fcf0: float, shares: float, cash: float, debt: float,
                  g1: float, wacc: float = 0.10, g_term: float = 0.03,
                  years: int = 5) -> dict:
    if shares <= 0:
        return {"error": "shares must be > 0"}
    if wacc <= g_term:
        return {"error": f"WACC ({wacc}) must exceed terminal growth ({g_term})"}
    # 初始成長合理性上限（高成長股淡化，避免 DCF 爆走）
    g1 = max(min(g1, 0.35), -0.20)

    pv_fcf = 0.0
    fcf = fcf0
    schedule = []
    for t in range(1, years + 1):
        # 成長率自 g1 線性淡化至 g_term（第 1 年 g1、第 N 年趨近 g_term）
        g_t = g1 + (g_term - g1) * (t - 1) / max(years - 1, 1)
        fcf = fcf * (1 + g_t)
        disc = (1 + wacc) ** t
        pv = fcf / disc
        pv_fcf += pv
        schedule.append({"year": t, "growth": round(g_t, 4),
                         "fcf": int(round(fcf)), "pv": int(round(pv))})

    terminal_value = fcf * (1 + g_term) / (wacc - g_term)
    pv_terminal = terminal_value / ((1 + wacc) ** years)

    enterprise_value = pv_fcf + pv_terminal
    equity_value = enterprise_value + cash - debt
    per_share = equity_value / shares

    return {
        "intrinsic_value_per_share": round(per_share, 2),
        "assumptions": {
            "fcf0": int(round(fcf0)), "shares": int(round(shares)),
            "cash": int(round(cash)), "debt": int(round(debt)),
            "growth_y1": round(g1, 4), "wacc": wacc,
            "terminal_growth": g_term, "years": years,
        },
        "breakdown": {
            "pv_explicit_fcf": int(round(pv_fcf)),
            "pv_terminal": int(round(pv_terminal)),
            "enterprise_value": int(round(enterprise_value)),
            "equity_value": int(round(equity_value)),
            "terminal_pct_of_ev": round(pv_terminal / enterprise_value, 3)
                if enterprise_value else None,
        },
        "schedule": schedule,
        "caveat": "高成長股 DCF 對 WACC/terminal 假設極敏感；僅作 sanity flag，不進 EV。"
                  " FCF≤0 時不適用。",
    }


def main() -> int:
    p = argparse.ArgumentParser(description="自建 2-stage DCF (台股自建估值錨)")
    p.add_argument("--fcf", type=float, required=True, help="自由現金流 TTM (絕對值, NT$)")
    p.add_argument("--shares", type=float, required=True, help="流通股數")
    p.add_argument("--cash", type=float, default=0.0, help="總現金 (NT$)")
    p.add_argument("--debt", type=float, default=0.0, help="總負債 (NT$)")
    p.add_argument("--growth", type=float, required=True, help="第 1 年 FCF 成長率 (小數, 如 0.30)")
    p.add_argument("--wacc", type=float, default=0.10, help="折現率 (預設 0.10)")
    p.add_argument("--terminal", type=float, default=0.03, help="終值成長率 (預設 0.03)")
    p.add_argument("--years", type=int, default=5, help="明確預測年數 (預設 5)")
    args = p.parse_args()

    if args.fcf <= 0:
        print(json.dumps({"error": "FCF ≤ 0 — DCF 不適用 (公司未產生正自由現金流)",
                          "intrinsic_value_per_share": None}, ensure_ascii=False, indent=2))
        return 0

    result = two_stage_dcf(args.fcf, args.shares, args.cash, args.debt,
                           args.growth, args.wacc, args.terminal, args.years)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
