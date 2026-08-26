#!/usr/bin/env python3
"""Unit tests for source_credit.py (stdlib unittest, no external deps)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import source_credit as sc  # noqa: E402
import trade_ledger  # noqa: E402  (score_view lazily imports from this module)


SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "source_credit.py")

THRESHOLDS = {
    "half_life_days": 90,
    "stale_days": 14,
    "fact_magnitude_tolerance": 0.5,
    "view_horizons_allowed": [30, 60],
    "view_default_horizon_days": 30,
    "fact_expire_after_days": 30,
    "trusted": {"min_hits": 3, "min_hit_rate": 0.65},
    "core": {"min_hits": 6, "min_hit_rate": 0.75, "min_distinct_tickers": 2},
    "demote": {"misses_in_last_n": 2, "last_n": 5, "min_n_for_rate": 4, "max_hit_rate": 0.5},
    "noise": {"max_vague_ratio": 0.7, "min_total": 5},
}


def base_source(**over):
    s = {
        "id": "semi_daily", "platform": "x", "handle": "semi_daily",
        "url": "https://x.com/semi_daily", "kind": "fact",
        "domains": ["semis", "memory"], "tier": "probation",
        "tier_since": "2026-08-26", "tier_lock": False, "tier_history": [],
        "x_user_id": None, "enabled": True, "added": "2026-08-26", "notes": "",
    }
    s.update(over)
    return s


def base_config(sources=None):
    return {
        "version": "test", "note": "test",
        "sources": sources if sources is not None else [base_source()],
        "x_fetch": {
            "enabled": True, "max_reads_per_run": 60, "per_account_limit": 10,
            "lookback_hours": 48, "exclude": ["retweets", "replies"],
            "cost_per_read_usd": 0.005, "keywords": [], "extra_tickers": [], "aliases": {},
        },
        "credit_thresholds": THRESHOLDS,
    }


# ── pure-function tests ──────────────────────────────────────────────────────
class MagnitudeCheck(unittest.TestCase):
    def test_wrong_direction_is_miss(self):
        self.assertEqual(sc.magnitude_check("up", 8, -3), "miss")

    def test_right_direction_within_tolerance_is_hit(self):
        self.assertEqual(sc.magnitude_check("up", 8, 6), "hit")  # rel_err 0.25 <= 0.5

    def test_right_direction_over_tolerance_is_partial(self):
        self.assertEqual(sc.magnitude_check("up", 8, 20), "partial")  # rel_err 1.5 > 0.5

    def test_missing_actual_is_null(self):
        self.assertIsNone(sc.magnitude_check("up", 8, None))

    def test_missing_value_is_null(self):
        self.assertIsNone(sc.magnitude_check("up", None, 6))

    def test_down_direction_hit(self):
        self.assertEqual(sc.magnitude_check("down", -10, -9), "hit")

    def test_down_direction_wrong_sign_is_miss(self):
        self.assertEqual(sc.magnitude_check("down", -10, 5), "miss")


class LeadTime(unittest.TestCase):
    def test_positive_lead_has_positive_credit(self):
        lead = sc.lead_time_days("2026-08-01", "2026-08-20", first_news_date="2026-08-15")
        self.assertEqual(lead, 14)
        self.assertEqual(sc.timeliness_credit(lead), 14)

    def test_negative_lead_has_zero_credit(self):
        lead = sc.lead_time_days("2026-08-15", "2026-08-10")
        self.assertEqual(lead, -5)
        self.assertEqual(sc.timeliness_credit(lead), 0)

    def test_zero_lead_has_zero_credit(self):
        lead = sc.lead_time_days("2026-08-15", "2026-08-15")
        self.assertEqual(lead, 0)
        self.assertEqual(sc.timeliness_credit(lead), 0)

    def test_falls_back_to_confirm_date_without_first_news_date(self):
        lead = sc.lead_time_days("2026-08-01", "2026-08-10")
        self.assertEqual(lead, 9)


class Weight(unittest.TestCase):
    def test_zero_days_is_full_weight(self):
        self.assertAlmostEqual(sc.weight(0, 90), 1.0)

    def test_one_half_life(self):
        self.assertAlmostEqual(sc.weight(90, 90), 0.5)

    def test_two_half_lives(self):
        self.assertAlmostEqual(sc.weight(180, 90), 0.25)


class ProposeTier(unittest.TestCase):
    def test_core_boundary_met(self):
        t = sc.propose_tier(n_scored=8, hits=6, partial=0, misses=2, hit_rate=0.75,
                             distinct_tickers_hit=2, misses_in_last_n=0, thresholds=THRESHOLDS)
        self.assertEqual(t, "core")

    def test_core_needs_distinct_tickers(self):
        t = sc.propose_tier(n_scored=8, hits=6, partial=0, misses=2, hit_rate=0.75,
                             distinct_tickers_hit=1, misses_in_last_n=0, thresholds=THRESHOLDS)
        self.assertEqual(t, "trusted")  # still clears trusted, just not core

    def test_trusted_boundary_met(self):
        t = sc.propose_tier(n_scored=4, hits=3, partial=0, misses=1, hit_rate=0.65,
                             distinct_tickers_hit=1, misses_in_last_n=0, thresholds=THRESHOLDS)
        self.assertEqual(t, "trusted")

    def test_below_trusted_stays_probation(self):
        t = sc.propose_tier(n_scored=3, hits=2, partial=0, misses=1, hit_rate=0.6,
                             distinct_tickers_hit=1, misses_in_last_n=0, thresholds=THRESHOLDS)
        self.assertEqual(t, "probation")

    def test_demote_overrides_core(self):
        # numerically clears core (hits=6, hit_rate=0.9, distinct=3) but 2 misses in
        # the last 5 scored claims → demote wins per the evaluation order
        t = sc.propose_tier(n_scored=8, hits=6, partial=0, misses=2, hit_rate=0.9,
                             distinct_tickers_hit=3, misses_in_last_n=2, thresholds=THRESHOLDS)
        self.assertEqual(t, "probation")

    def test_demote_via_low_hit_rate_with_enough_n(self):
        t = sc.propose_tier(n_scored=4, hits=1, partial=0, misses=3, hit_rate=0.25,
                             distinct_tickers_hit=1, misses_in_last_n=0, thresholds=THRESHOLDS)
        self.assertEqual(t, "probation")

    def test_tier_lock_freezes_current_tier_even_when_qualifying_for_core(self):
        t = sc.propose_tier(n_scored=8, hits=6, partial=0, misses=2, hit_rate=0.9,
                             distinct_tickers_hit=3, misses_in_last_n=0, thresholds=THRESHOLDS,
                             tier_lock=True, current_tier="trusted")
        self.assertEqual(t, "trusted")

    def test_tier_lock_freezes_current_tier_even_when_demote_condition_true(self):
        t = sc.propose_tier(n_scored=4, hits=1, partial=0, misses=3, hit_rate=0.25,
                             distinct_tickers_hit=1, misses_in_last_n=2, thresholds=THRESHOLDS,
                             tier_lock=True, current_tier="core")
        self.assertEqual(t, "core")


class IsNoise(unittest.TestCase):
    def test_noise_when_ratio_high_and_enough_volume(self):
        self.assertTrue(sc.is_noise(6, 0.8, THRESHOLDS))

    def test_not_noise_below_min_total(self):
        self.assertFalse(sc.is_noise(3, 0.9, THRESHOLDS))

    def test_not_noise_below_ratio_threshold(self):
        self.assertFalse(sc.is_noise(10, 0.5, THRESHOLDS))


class ScoreView(unittest.TestCase):
    def setUp(self):
        self._orig_eod_series = trade_ledger.eod_series

    def tearDown(self):
        trade_ledger.eod_series = self._orig_eod_series

    def test_up_direction_is_hit_when_alpha_positive(self):
        def fake_eod_series(symbol, start, end, cache=None, token=None):
            if symbol.startswith("XYZ"):
                return {"2026-08-01": 100.0, "2026-08-31": 130.0}  # +30%
            return {"2026-08-01": 100.0, "2026-08-31": 110.0}      # bench +10%

        trade_ledger.eod_series = fake_eod_series
        claim = {"id": "src:2026-08-01:XYZ:up-h30", "ticker": "XYZ",
                  "posted_date": "2026-08-01", "target_date": "2026-08-31", "direction": "up"}
        res = sc.score_view(claim, "2026-08-31")
        self.assertEqual(res["verdict"], "hit")
        self.assertAlmostEqual(res["excess_alpha_pct"], 20.0, places=2)
        self.assertEqual(res["benchmark"], "SPY")

    def test_down_direction_is_hit_when_alpha_negative(self):
        def fake_eod_series(symbol, start, end, cache=None, token=None):
            if symbol.startswith("XYZ"):
                return {"2026-08-01": 100.0, "2026-08-31": 80.0}   # -20%
            return {"2026-08-01": 100.0, "2026-08-31": 90.0}       # bench -10%

        trade_ledger.eod_series = fake_eod_series
        claim = {"id": "src:2026-08-01:XYZ:down-h30", "ticker": "XYZ",
                  "posted_date": "2026-08-01", "target_date": "2026-08-31", "direction": "down"}
        res = sc.score_view(claim, "2026-08-31")
        self.assertEqual(res["verdict"], "hit")
        self.assertAlmostEqual(res["excess_alpha_pct"], -10.0, places=2)

    def test_up_direction_is_miss_when_alpha_negative(self):
        def fake_eod_series(symbol, start, end, cache=None, token=None):
            if symbol.startswith("XYZ"):
                return {"2026-08-01": 100.0, "2026-08-31": 90.0}   # -10%
            return {"2026-08-01": 100.0, "2026-08-31": 110.0}      # bench +10%

        trade_ledger.eod_series = fake_eod_series
        claim = {"id": "src:2026-08-01:XYZ:up-h30", "ticker": "XYZ",
                  "posted_date": "2026-08-01", "target_date": "2026-08-31", "direction": "up"}
        res = sc.score_view(claim, "2026-08-31")
        self.assertEqual(res["verdict"], "miss")


class ComputeSourceStats(unittest.TestCase):
    def _claim(self, kind="fact", ticker="MU", verdict="hit", status="resolved", **over):
        c = {
            "kind": kind, "ticker": ticker, "status": status, "posted_date": "2026-08-01",
            "backtest": False,
            "resolution": ({"resolved_at": "2026-08-15", "verdict": verdict,
                            "lead_time_days": 5, "excess_alpha_pct": 3.0}
                           if status == "resolved" else None),
        }
        c.update(over)
        return c

    def test_hit_rate_counts_partial_as_half(self):
        claims = [self._claim(verdict="hit"), self._claim(verdict="partial"),
                  self._claim(verdict="miss")]
        stats = sc.compute_source_stats(claims, "2026-08-20", THRESHOLDS, "probation", False)
        self.assertEqual(stats["n_scored"], 3)
        self.assertAlmostEqual(stats["hit_rate"], (1 + 0.5) / 3)

    def test_vague_ratio_and_noise(self):
        claims = ([self._claim(status="unscorable", verdict=None)] * 4
                  + [self._claim(status="expired", verdict=None)] * 2)
        stats = sc.compute_source_stats(claims, "2026-08-20", THRESHOLDS, "probation", False)
        self.assertAlmostEqual(stats["vague_ratio"], 1.0)
        self.assertTrue(stats["noise"])

    def test_distinct_tickers_hit_counts_unique_ticker_on_hit_only(self):
        claims = [self._claim(ticker="MU", verdict="hit"),
                  self._claim(ticker="MU", verdict="hit"),
                  self._claim(ticker="ON", verdict="hit"),
                  self._claim(ticker="BE", verdict="miss")]
        stats = sc.compute_source_stats(claims, "2026-08-20", THRESHOLDS, "probation", False)
        self.assertEqual(stats["distinct_tickers_hit"], 2)


class ComputeTierChanges(unittest.TestCase):
    def test_locked_source_never_changes(self):
        sources = [base_source(id="s1", tier="core", tier_lock=True)]
        claims = [{"source_id": "s1", "kind": "fact", "ticker": "MU", "status": "resolved",
                   "posted_date": "2026-08-01", "backtest": False,
                   "resolution": {"resolved_at": "2026-08-05", "verdict": "miss"}}] * 5
        changes = sc.compute_tier_changes(sources, claims, THRESHOLDS, "2026-08-20")
        self.assertEqual(changes, [])

    def test_unlocked_source_proposes_promotion(self):
        sources = [base_source(id="s1", tier="probation", tier_lock=False)]
        claims = [
            {"source_id": "s1", "kind": "fact", "ticker": t, "status": "resolved",
             "posted_date": "2026-08-01", "backtest": False,
             "resolution": {"resolved_at": "2026-08-05", "verdict": "hit"}}
            for t in ("MU", "ON", "BE")
        ]
        changes = sc.compute_tier_changes(sources, claims, THRESHOLDS, "2026-08-20")
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["to"], "trusted")

    def test_apply_tier_changes_updates_history(self):
        sources = [base_source(id="s1", tier="probation")]
        changes = [{"id": "s1", "from": "probation", "to": "trusted", "n_scored": 3, "hit_rate": 0.67}]
        sc.apply_tier_changes(sources, changes, "2026-08-20")
        self.assertEqual(sources[0]["tier"], "trusted")
        self.assertEqual(sources[0]["tier_since"], "2026-08-20")
        self.assertEqual(len(sources[0]["tier_history"]), 1)
        self.assertEqual(sources[0]["tier_history"][0]["to"], "trusted")


# ── file IO ──────────────────────────────────────────────────────────────────
class FileIO(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ledger = os.path.join(self.tmp, "claims.jsonl")
        self.config = os.path.join(self.tmp, "config.json")

    def test_load_missing_ledger_returns_empty(self):
        self.assertEqual(sc.load_claims(self.ledger), [])

    def test_save_then_load_claims_roundtrip(self):
        claims = [{"id": "a:1", "status": "pending"}]
        sc.save_claims(self.ledger, claims)
        self.assertEqual(sc.load_claims(self.ledger), claims)

    def test_save_claims_is_atomic_no_temp_left(self):
        sc.save_claims(self.ledger, [])
        leftovers = [f for f in os.listdir(self.tmp) if f != "claims.jsonl"]
        self.assertEqual(leftovers, [])

    def test_save_then_load_config_roundtrip(self):
        cfg = base_config()
        sc.save_config(self.config, cfg)
        self.assertEqual(sc.load_config(self.config), cfg)

    def test_load_missing_config_raises(self):
        with self.assertRaises(SystemExit):
            sc.load_config(os.path.join(self.tmp, "nope.json"))

    def test_find_source(self):
        cfg = base_config()
        self.assertIsNotNone(sc.find_source(cfg, "semi_daily"))
        self.assertIsNone(sc.find_source(cfg, "nope"))


# ── CLI (subprocess) ─────────────────────────────────────────────────────────
class CLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ledger = os.path.join(self.tmp, "claims.jsonl")
        self.config = os.path.join(self.tmp, "config.json")
        cfg = base_config(sources=[
            base_source(id="semi_daily", kind="fact", platform="x"),
            base_source(id="convertbond", kind="view", platform="x"),
        ])
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

    def run_cli(self, *args):
        return subprocess.run(
            ["python3", SCRIPT, "--ledger", self.ledger, "--config", self.config, *args],
            capture_output=True, text=True,
        )

    def _add_fact(self, **over):
        kw = dict(source_id="semi_daily", kind="fact", tickers="MU",
                  claim="MU DRAM ASP guide +8% QoQ per channel checks",
                  raw_quote="channel checks point to ASP up 8pct next quarter",
                  url="https://x.com/semi_daily/status/1", posted_date="2026-08-01",
                  metric="ASP_QoQ_pct", value="8", value_num="8",
                  direction="up", confirm_by="2026-08-25")
        kw.update(over)
        args = ["add-claim"]
        for k, v in kw.items():
            args += [f"--{k.replace('_', '-')}", str(v)]
        return self.run_cli(*args)

    def _add_view(self, **over):
        kw = dict(source_id="convertbond", kind="view", tickers="XYZ",
                  claim="look at XYZ next month",
                  raw_quote="worth watching XYZ into next print",
                  url="https://x.com/Convertbond/status/1", posted_date="2026-08-01",
                  direction="up", horizon_days="30")
        kw.update(over)
        args = ["add-claim"]
        for k, v in kw.items():
            args += [f"--{k.replace('_', '-')}", str(v)]
        return self.run_cli(*args)

    # -- id determinism / upsert / collision --
    def test_add_claim_id_is_deterministic_and_upsert_updates_in_place(self):
        p1 = self._add_fact()
        self.assertEqual(p1.returncode, 0, p1.stderr)
        d1 = json.loads(p1.stdout)
        self.assertEqual(d1["action"], "inserted")

        p2 = self._add_fact(claim="MU DRAM ASP guide +8pct QoQ (revised wording)")
        self.assertEqual(p2.returncode, 0, p2.stderr)
        d2 = json.loads(p2.stdout)
        self.assertEqual(d2["id"], d1["id"])
        self.assertEqual(d2["action"], "updated")

        with open(self.ledger, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        self.assertEqual(len(lines), 1)

    def test_reregistering_resolved_claim_is_collision_exit_2(self):
        p1 = self._add_fact()
        claim_id = json.loads(p1.stdout)["id"]
        pr = self.run_cli("resolve", "--id", claim_id, "--verdict", "hit",
                           "--actual", "ASP +7pct", "--actual-num", "7",
                           "--confirm-date", "2026-08-15")
        self.assertEqual(pr.returncode, 0, pr.stderr)

        p2 = self._add_fact()
        self.assertEqual(p2.returncode, 2)

    # -- validation --
    def test_unknown_source_exits_3(self):
        p = self._add_fact(source_id="nope")
        self.assertEqual(p.returncode, 3)

    def test_raw_quote_121_chars_exits_1(self):
        p = self._add_fact(raw_quote="x" * 121)
        self.assertEqual(p.returncode, 1)

    def test_raw_quote_120_chars_is_accepted(self):
        p = self._add_fact(raw_quote="x" * 120)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_tickers_none_only_valid_for_view(self):
        p = self._add_fact(tickers="none")
        self.assertEqual(p.returncode, 1)

    def test_tickers_none_view_is_unscorable(self):
        p = self._add_view(tickers="none")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["status"], "unscorable")

    def test_fact_requires_confirm_by(self):
        args = ["add-claim", "--source-id", "semi_daily", "--kind", "fact", "--tickers", "MU",
                "--claim", "x", "--raw-quote", "x", "--url", "u", "--posted-date", "2026-08-01",
                "--direction", "up"]
        p = self.run_cli(*args)
        self.assertEqual(p.returncode, 1)

    def test_view_direction_flat_rejected(self):
        p = self._add_view(direction="flat")
        self.assertEqual(p.returncode, 1)

    def test_view_horizon_not_allowed(self):
        p = self._add_view(horizon_days="45")
        self.assertEqual(p.returncode, 1)

    # -- resolve-due --
    def test_resolve_due_leaves_facts_pending_and_lists_them(self):
        self._add_fact(confirm_by="2026-08-10")
        p = self.run_cli("--asof", "2026-08-15", "resolve-due")
        self.assertEqual(p.returncode, 0, p.stderr)

        # resolve-due prints human lines then a JSON summary as the final block
        # (indent=2 spans multiple lines, so slice from the first brace)
        summary = json.loads(p.stdout[p.stdout.index("{"):])
        self.assertEqual(summary["facts_pending_manual"], 1)
        self.assertEqual(summary["resolved_views"], 0)

        with open(self.ledger, encoding="utf-8") as f:
            claims = [json.loads(ln) for ln in f if ln.strip()]
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["status"], "pending")

    def test_resolve_due_always_exits_0_even_with_no_claims(self):
        p = self.run_cli("resolve-due")
        self.assertEqual(p.returncode, 0, p.stderr)

    # -- due (expiry sweep) --
    def test_due_lists_fact_within_expiry_window(self):
        self._add_fact(confirm_by="2026-08-10")
        p = self.run_cli("--asof", "2026-08-15", "due")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["facts_due_count"], 1)
        self.assertEqual(out["expired_count"], 0)

    def test_due_expires_fact_past_expiry_window(self):
        self._add_fact(confirm_by="2026-08-01")
        # 30 days over confirm_by (fact_expire_after_days=30) -> expired
        p = self.run_cli("--asof", "2026-09-05", "due")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["expired_count"], 1)
        self.assertEqual(out["facts_due_count"], 0)

    # -- resolve (manual, fact) --
    def test_resolve_fact_computes_lead_time_and_magnitude_check(self):
        p1 = self._add_fact(posted_date="2026-08-01")
        claim_id = json.loads(p1.stdout)["id"]
        p2 = self.run_cli("resolve", "--id", claim_id, "--verdict", "hit",
                           "--actual", "ASP +8pct QoQ, in line", "--actual-num", "8",
                           "--first-news-date", "2026-08-15")
        self.assertEqual(p2.returncode, 0, p2.stderr)
        res = json.loads(p2.stdout)
        self.assertEqual(res["lead_time_days"], 14)
        self.assertEqual(res["timeliness_credit"], 14)
        self.assertEqual(res["magnitude_check"], "hit")

    def test_resolve_unknown_id_exits_3(self):
        p = self.run_cli("resolve", "--id", "nope:x", "--verdict", "hit", "--actual", "x")
        self.assertEqual(p.returncode, 3)

    # -- list / stats / tiers smoke --
    def test_list_sources(self):
        p = self.run_cli("list", "--sources")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["count"], 2)

    def test_stats_runs_clean_on_empty_ledger(self):
        p = self.run_cli("stats")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertIn("promotion_rule", out)

    def test_score_is_an_alias_for_stats(self):
        p = self.run_cli("score")
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_tiers_dry_run_does_not_write_config(self):
        with open(self.config, encoding="utf-8") as f:
            before = f.read()
        p = self.run_cli("tiers", "--dry-run")
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(self.config, encoding="utf-8") as f:
            after = f.read()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
