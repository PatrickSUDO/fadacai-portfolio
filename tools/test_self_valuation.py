#!/usr/bin/env python3
"""
test_self_valuation.py — Unit tests for compute_self_valuation() in fetch_fundamentals.py.

Tests cover:
- CAGR geometric computation
- Growth cap (40%) and deceleration toward terminal growth (8%)
- Macro adjustment asymmetric clamp (-4pp to +2pp)
- Guardrails: <3 years, net_margin ≤ 0, shares missing → unavailable
- High revenue stdev (>30%) → confidence=low
- Stable growth → confidence=ok
- Margin trend logic (USE_MARGIN_TREND knob)
- own_fwdEPS formula and own_target_price=None when no PE anchors

Usage:
  cd tools && python3 -m unittest test_self_valuation -v
  # or from repo root:
  python3 -m unittest tools.test_self_valuation -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure tools/ directory is on sys.path for direct import
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_fundamentals as ff


# ── Test helpers ────────────────────────────────────────────────────────────

def make_highlights(
    profit_margin=0.20,
    revenue_ttm=1_000_000_000,
    quarterly_revenue_growth_yoy=0.10,
    pe_ratio=None,
    peg_ratio=None,
    wall_street_target=None,
    eps_ttm=None,
):
    """Build a minimal highlights dict for compute_self_valuation()."""
    return {
        "profit_margin": profit_margin,
        "revenue_ttm": revenue_ttm,
        "quarterly_revenue_growth_yoy": quarterly_revenue_growth_yoy,
        "pe_ratio": pe_ratio,
        "peg_ratio": peg_ratio,
        "wall_street_target": wall_street_target,
        "eps_ttm": eps_ttm,
        "operating_margin_ttm": None,
        "roe_ttm": None,
        "quarterly_earnings_growth_yoy": None,
        "dividend_yield": None,
        "market_cap": None,
    }


def make_financials(revenues, net_incomes=None, shares=1_000_000_000):
    """Build a minimal financials dict.

    revenues: list of annual revenue values, newest-first (e.g. [400e9, 300e9, 200e9]).
    net_incomes: list of annual net income values, newest-first (same length as revenues).
    shares: shares outstanding (int or None).
    """
    rev_yearly = [
        {"date": f"{2023 - i}-12-31", "value": v}
        for i, v in enumerate(revenues)
    ]
    ni_yearly = []
    if net_incomes:
        ni_yearly = [
            {"date": f"{2023 - i}-12-31", "value": v}
            for i, v in enumerate(net_incomes)
        ]
    return {
        "revenue_yearly": rev_yearly,
        "net_income_yearly": ni_yearly,
        "shares_outstanding": shares,
    }


# ── Guardrail tests ─────────────────────────────────────────────────────────

class TestGuardrails(unittest.TestCase):
    """compute_self_valuation() must return confidence='unavailable' and null fields
    when required inputs are missing or invalid."""

    def test_fewer_than_3_revenue_years_returns_unavailable(self):
        h = make_highlights()
        f = make_financials([400e9, 300e9])  # only 2 years
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertEqual(result["confidence"], "unavailable")
        self.assertIsNone(result["own_target_price"])
        self.assertIsNone(result["own_fwdEPS"])
        self.assertIn("revenue", result["notes"].lower())

    def test_only_1_revenue_year_returns_unavailable(self):
        h = make_highlights()
        f = make_financials([400e9])
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertEqual(result["confidence"], "unavailable")

    def test_empty_revenue_years_returns_unavailable(self):
        h = make_highlights()
        f = make_financials([])
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertEqual(result["confidence"], "unavailable")

    def test_negative_net_margin_returns_unavailable(self):
        h = make_highlights(profit_margin=-0.05)
        f = make_financials([400e9, 300e9, 200e9])
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertEqual(result["confidence"], "unavailable")
        self.assertIn("margin", result["notes"].lower())

    def test_zero_net_margin_returns_unavailable(self):
        h = make_highlights(profit_margin=0.0)
        f = make_financials([400e9, 300e9, 200e9])
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertEqual(result["confidence"], "unavailable")

    def test_none_net_margin_returns_unavailable(self):
        h = make_highlights(profit_margin=None)
        f = make_financials([400e9, 300e9, 200e9])
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertEqual(result["confidence"], "unavailable")

    def test_shares_outstanding_none_returns_unavailable(self):
        h = make_highlights()
        f = make_financials([400e9, 300e9, 200e9], shares=None)
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertEqual(result["confidence"], "unavailable")
        self.assertIn("shares", result["notes"].lower())

    def test_shares_outstanding_zero_returns_unavailable(self):
        h = make_highlights()
        f = make_financials([400e9, 300e9, 200e9], shares=0)
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertEqual(result["confidence"], "unavailable")

    def test_revenue_ttm_none_returns_unavailable(self):
        h = make_highlights(revenue_ttm=None)
        f = make_financials([400e9, 300e9, 200e9])
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertEqual(result["confidence"], "unavailable")

    def test_revenue_ttm_zero_returns_unavailable(self):
        h = make_highlights(revenue_ttm=0)
        f = make_financials([400e9, 300e9, 200e9])
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertEqual(result["confidence"], "unavailable")


# ── Confidence level tests ──────────────────────────────────────────────────

class TestConfidenceLevel(unittest.TestCase):
    """Verify confidence=low for high revenue stdev, confidence=ok for stable growth."""

    def test_cyclical_revenue_high_stdev_is_low(self):
        # MU-like swings: +80%, -40%, +67% → stdev >> 30%
        # newest-first: 180, 100, 167, 100
        revs = [180e9, 100e9, 167e9, 100e9]
        h = make_highlights(revenue_ttm=180e9)
        f = make_financials(revs)
        result = ff.compute_self_valuation("MU", h, f)
        self.assertEqual(result["confidence"], "low")
        # Still computes own_fwdEPS (just flagged as low confidence)
        self.assertIsNotNone(result["own_fwdEPS"])
        self.assertGreater(result["own_fwdEPS"], 0)

    def test_stable_20pct_growth_is_ok(self):
        # Steady 20% YoY: 100→120→144→172.8 (newest-first)
        revs = [172.8e9, 144e9, 120e9, 100e9]
        h = make_highlights(revenue_ttm=172.8e9, profit_margin=0.25)
        f = make_financials(revs)
        result = ff.compute_self_valuation("NVDA", h, f)
        self.assertEqual(result["confidence"], "ok")
        self.assertIsNotNone(result["own_fwdEPS"])


# ── CAGR computation tests ──────────────────────────────────────────────────

class TestCAGRComputation(unittest.TestCase):
    """Geometric CAGR = (newest/oldest)^(1/n_periods) - 1."""

    def test_cagr_geometric_2x_over_2_periods(self):
        # 100 → 200 → 400 (newest-first: 400, 200, 100)
        # CAGR over 2 periods = (400/100)^(1/2) - 1 = sqrt(4) - 1 = 1.00 (100%)
        revs = [400e9, 200e9, 100e9]
        h = make_highlights(revenue_ttm=400e9)
        f = make_financials(revs)
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertAlmostEqual(result["revenue_cagr"], 1.0, places=2)

    def test_cagr_20pct_over_2_periods(self):
        # 100 → 120 → 144 (newest-first: 144, 120, 100)
        # CAGR = (144/100)^(1/2) - 1 = 1.2 - 1 = 0.20
        import math
        revs = [144e9, 120e9, 100e9]
        h = make_highlights(revenue_ttm=144e9)
        f = make_financials(revs)
        result = ff.compute_self_valuation("TEST", h, f)
        expected_cagr = math.sqrt(144.0 / 100.0) - 1  # ≈ 0.2
        self.assertAlmostEqual(result["revenue_cagr"], expected_cagr, places=3)


# ── Growth cap + deceleration tests ────────────────────────────────────────

class TestGrowthProjection(unittest.TestCase):
    """Growth cap at 40% and deceleration toward terminal (8%) via DECEL_FACTOR."""

    def test_growth_cap_at_40_pct(self):
        # CAGR=100% → base_growth capped at GROWTH_CAP=40%
        # g_next = TERMINAL + (GROWTH_CAP - TERMINAL) × (1 - DECEL)
        revs = [400e9, 200e9, 100e9]  # CAGR=100%
        h = make_highlights(revenue_ttm=400e9)
        f = make_financials(revs)
        result = ff.compute_self_valuation("TEST", h, f)
        expected_g_next = ff.TERMINAL_GROWTH + (ff.GROWTH_CAP - ff.TERMINAL_GROWTH) * (1 - ff.DECEL_FACTOR)
        self.assertAlmostEqual(result["g_next"], expected_g_next, places=4)

    def test_moderate_growth_deceleration_toward_terminal(self):
        # CAGR ≈ 20% → g_next should be between TERMINAL and CAGR
        import math
        revs = [144e9, 120e9, 100e9]
        h = make_highlights(revenue_ttm=144e9)
        f = make_financials(revs)
        result = ff.compute_self_valuation("TEST", h, f)
        expected_cagr = math.sqrt(144.0 / 100.0) - 1
        expected_g_next = ff.TERMINAL_GROWTH + (expected_cagr - ff.TERMINAL_GROWTH) * (1 - ff.DECEL_FACTOR)
        self.assertAlmostEqual(result["g_next"], expected_g_next, places=4)

    def test_projected_revenue_uses_g_adj(self):
        # projected_revenue = revenue_ttm × (1 + g_adj)
        rev_ttm = 144e9
        revs = [rev_ttm, 120e9, 100e9]
        h = make_highlights(revenue_ttm=rev_ttm)
        f = make_financials(revs)
        result = ff.compute_self_valuation("TEST", h, f)
        expected_proj = rev_ttm * (1.0 + result["g_adj"])
        self.assertAlmostEqual(result["projected_revenue"], expected_proj, delta=1000)


# ── Macro adjustment clamp tests ────────────────────────────────────────────

class TestMacroAdjustmentClamp(unittest.TestCase):
    """Macro adjustment: asymmetric clamp max(-0.04, min(0.02, macro_adj)).
    Tests inject a synthetic macro-snapshot.json by patching ff.CACHE_DIR.
    """

    def _run_with_macro(self, macro_data: dict):
        """Patch CACHE_DIR to a temp dir with a synthetic macro-snapshot.json."""
        original_cache_dir = ff.CACHE_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            macro_path = Path(tmpdir) / "macro-snapshot.json"
            macro_path.write_text(json.dumps(macro_data))
            ff.CACHE_DIR = Path(tmpdir)
            try:
                revs = [144e9, 120e9, 100e9]
                h = make_highlights(revenue_ttm=144e9)
                f = make_financials(revs)
                return ff.compute_self_valuation("TEST", h, f)
            finally:
                ff.CACHE_DIR = original_cache_dir

    def test_no_macro_file_means_zero_adj(self):
        # Patch to empty temp dir (no macro-snapshot.json) → macro_adj=0.0
        original_cache_dir = ff.CACHE_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            ff.CACHE_DIR = Path(tmpdir)
            try:
                revs = [144e9, 120e9, 100e9]
                h = make_highlights(revenue_ttm=144e9)
                f = make_financials(revs)
                result = ff.compute_self_valuation("TEST", h, f)
            finally:
                ff.CACHE_DIR = original_cache_dir
        self.assertAlmostEqual(result["macro_adj"], 0.0, places=4)

    def test_recession_signal_minus_3pp(self):
        result = self._run_with_macro({"regime_tag": "recession_signal", "series": {}})
        self.assertAlmostEqual(result["macro_adj"], -0.03, places=4)

    def test_risk_on_plus_1pp(self):
        result = self._run_with_macro({"regime_tag": "risk_on", "series": {}})
        self.assertAlmostEqual(result["macro_adj"], 0.01, places=4)

    def test_multiple_negative_factors_clamped_to_minus_4pp(self):
        # recession_signal (−3pp) + CPI↑ (−1pp) + fed↑>25bp (−1pp) = −5pp → clamped to −4pp
        result = self._run_with_macro({
            "regime_tag": "recession_signal",
            "series": {
                "cpi_yoy": {"trend": "up"},
                "fed_funds": {"change_30d": 0.50},  # 50bp > 25bp threshold
            },
        })
        self.assertAlmostEqual(result["macro_adj"], -0.04, places=4)

    def test_positive_adj_never_exceeds_plus_2pp(self):
        # risk_on only gives +1pp < +2pp clamp; confirm never above 2pp
        result = self._run_with_macro({"regime_tag": "risk_on", "series": {}})
        self.assertLessEqual(result["macro_adj"], 0.02)

    def test_g_adj_never_negative(self):
        # Even with extreme macro drag (-4pp), g_adj must be ≥ 0.0
        original_cache_dir = ff.CACHE_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            macro_path = Path(tmpdir) / "macro-snapshot.json"
            macro_path.write_text(json.dumps({
                "regime_tag": "recession_signal",
                "series": {
                    "cpi_yoy": {"trend": "up"},
                    "fed_funds": {"change_30d": 0.50},
                },
            }))
            ff.CACHE_DIR = Path(tmpdir)
            try:
                # Low-CAGR stock (≈10% CAGR) + full recession drag
                revs = [110e9, 100e9, 90.9e9]
                h = make_highlights(revenue_ttm=110e9)
                f = make_financials(revs)
                result = ff.compute_self_valuation("TEST", h, f)
            finally:
                ff.CACHE_DIR = original_cache_dir
        self.assertGreaterEqual(result["g_adj"], 0.0)

    def test_g_adj_never_above_45_pct(self):
        # Even with maximum growth + risk_on, g_adj must be ≤ 0.45
        result = self._run_with_macro({"regime_tag": "risk_on", "series": {}})
        self.assertLessEqual(result["g_adj"], 0.45)


# ── Margin trend tests ──────────────────────────────────────────────────────

class TestMarginTrend(unittest.TestCase):
    """USE_MARGIN_TREND: use avg(last2) when both positive, rising, |Δ|<3pp."""

    def test_margin_trend_applied_when_steadily_rising(self):
        if not ff.USE_MARGIN_TREND:
            self.skipTest("USE_MARGIN_TREND is disabled")
        # Margins: m0=20%, m1=18% — both positive, rising, |Δ|=2%<3%
        revs = [200e9, 180e9, 150e9]
        ni = [40e9, 32.4e9, 25e9]   # 200×0.20=40, 180×0.18=32.4
        h = make_highlights(profit_margin=0.20, revenue_ttm=200e9)
        f = make_financials(revs, net_incomes=ni)
        result = ff.compute_self_valuation("TEST", h, f)
        # trend margin = avg(20%, 18%) = 19%
        self.assertAlmostEqual(result["net_margin"], 0.19, places=3)
        self.assertIn("trend_avg", result["notes"])

    def test_margin_trend_not_applied_when_declining(self):
        # Margins: m0=18%, m1=20% — declining → do NOT use trend avg
        # newest-first revenues: 180, 200, 150 (declining from prior year)
        revs = [180e9, 200e9, 150e9]
        ni = [32.4e9, 40e9, 25e9]   # 180×0.18=32.4, 200×0.20=40
        h = make_highlights(profit_margin=0.18, revenue_ttm=180e9)
        f = make_financials(revs, net_incomes=ni)
        result = ff.compute_self_valuation("TEST", h, f)
        # m0(0.18) < m1(0.20) → trend avg NOT applied → net_margin stays at trailing 0.18
        self.assertAlmostEqual(result["net_margin"], 0.18, places=3)

    def test_margin_trend_not_applied_when_change_exceeds_3pp(self):
        if not ff.USE_MARGIN_TREND:
            self.skipTest("USE_MARGIN_TREND is disabled")
        # m0=25%, m1=20%: rising but |Δ|=5%>3% — trend avg NOT applied
        revs = [200e9, 180e9, 150e9]
        ni = [50e9, 36e9, 25e9]    # 200×0.25=50, 180×0.20=36
        h = make_highlights(profit_margin=0.25, revenue_ttm=200e9)
        f = make_financials(revs, net_incomes=ni)
        result = ff.compute_self_valuation("TEST", h, f)
        # |Δ|=0.05 > 0.03 → trailing margin used = 0.25
        self.assertAlmostEqual(result["net_margin"], 0.25, places=3)


# ── Own fwdEPS + target price tests ────────────────────────────────────────

class TestOwnFwdEPS(unittest.TestCase):
    """Validate own_fwdEPS = projected_revenue × net_margin / shares."""

    def test_own_fwdEPS_formula_correct(self):
        revs = [144e9, 120e9, 100e9]
        net_margin = 0.25
        shares = 1_000_000_000
        h = make_highlights(revenue_ttm=144e9, profit_margin=net_margin)
        f = make_financials(revs, shares=shares)
        result = ff.compute_self_valuation("TEST", h, f)
        # own_fwdEPS = projected_revenue × net_margin / shares
        expected_eps = result["projected_revenue"] * net_margin / shares
        self.assertAlmostEqual(result["own_fwdEPS"], expected_eps, places=4)

    def test_own_target_price_none_when_no_pe_anchors(self):
        # No A1, A2, A3 anchors → base_fair_pe_approx = None → own_target_price = None
        revs = [144e9, 120e9, 100e9]
        h = make_highlights(
            revenue_ttm=144e9,
            profit_margin=0.25,
            pe_ratio=None,                       # A1 N/A
            quarterly_revenue_growth_yoy=0.0,    # A2 N/A (growth=0 → excluded)
            wall_street_target=None,             # A3 N/A
            eps_ttm=None,
        )
        f = make_financials(revs)
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertIsNotNone(result["own_fwdEPS"])   # EPS still computed
        self.assertIsNone(result["own_target_price"])  # no PE anchor → can't price
        self.assertIsNone(result["base_fair_pe_approx"])

    def test_own_target_price_computes_with_pe_anchor(self):
        # A1 = pe_ratio=30 → base_fair_pe = 30 → own_target_price should be positive
        revs = [144e9, 120e9, 100e9]
        h = make_highlights(
            revenue_ttm=144e9,
            profit_margin=0.25,
            pe_ratio=30.0,       # provides A1 anchor
        )
        f = make_financials(revs)
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertIsNotNone(result["own_target_price"])
        self.assertGreater(result["own_target_price"], 0)
        # Sanity: own_target_price ≈ own_fwdEPS × base_fair_pe
        expected = result["own_fwdEPS"] * result["base_fair_pe_approx"]
        self.assertAlmostEqual(result["own_target_price"], expected, places=1)

    def test_own_fwdEPS_positive(self):
        revs = [144e9, 120e9, 100e9]
        h = make_highlights(revenue_ttm=144e9, profit_margin=0.15)
        f = make_financials(revs, shares=500_000_000)
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertGreater(result["own_fwdEPS"], 0)


# ── Return structure tests ──────────────────────────────────────────────────

class TestReturnStructure(unittest.TestCase):
    """Verify all expected keys are present in both ok and unavailable results."""

    EXPECTED_KEYS = {
        "own_fwdEPS", "projected_revenue", "revenue_cagr", "g_next",
        "macro_adj", "g_adj", "net_margin", "shares_outstanding",
        "base_fair_pe_approx", "own_target_price", "confidence", "notes",
        # added by commit 16ecd10 (A3 anchor provenance: consensus_curr_fy /
        # consensus_next_fy / approx) — CLAUDE.md 0e tells callers to read it rather
        # than re-derive the forward EPS, so it is part of the contract
        "a3_fwdeps_source",
    }

    def test_ok_result_has_all_keys(self):
        revs = [144e9, 120e9, 100e9]
        h = make_highlights(revenue_ttm=144e9)
        f = make_financials(revs)
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertEqual(set(result.keys()), self.EXPECTED_KEYS)

    def test_unavailable_result_has_all_keys(self):
        h = make_highlights(profit_margin=-0.1)  # triggers unavailable
        f = make_financials([400e9, 300e9, 200e9])
        result = ff.compute_self_valuation("TEST", h, f)
        self.assertEqual(set(result.keys()), self.EXPECTED_KEYS)
        self.assertEqual(result["confidence"], "unavailable")

    def test_confidence_values_are_valid(self):
        valid_confidences = {"ok", "low", "unavailable"}
        # Test ok
        revs = [144e9, 120e9, 100e9]
        h = make_highlights(revenue_ttm=144e9)
        f = make_financials(revs)
        r = ff.compute_self_valuation("TEST", h, f)
        self.assertIn(r["confidence"], valid_confidences)
        # Test unavailable
        h2 = make_highlights(profit_margin=-0.1)
        r2 = ff.compute_self_valuation("TEST", h2, f)
        self.assertIn(r2["confidence"], valid_confidences)


if __name__ == "__main__":
    unittest.main(verbosity=2)
