#!/usr/bin/env python3
"""Unit tests for thesis_ledger.py (stdlib unittest, no external deps)."""

import json
import os
import tempfile
import unittest
from datetime import date

import thesis_ledger as tl


def empty_ledger():
    return {"theses": []}


def base_add_kwargs(**over):
    kw = dict(
        ticker="2330",
        slug="memory-cycle",
        thesis="DRAM 進入漲價週期，FY26 毛利率 > 40%",
        falsification=["次季 ASP 不再漲", "HBM3E 指引下修>10%"],
        trigger_type="event",
        trigger_date="2026-06-25",
        event="earnings",
        metric="DRAM ASP QoQ + 毛利率 vs 40%",
        source="briefing",
        ev="+1.0% (7d)",
        asof="2026-05-31",
    )
    kw.update(over)
    return kw


class SlugAndId(unittest.TestCase):
    def test_normalize_slug_lowercases_and_hyphenates(self):
        self.assertEqual(tl.normalize_slug("Memory Cycle"), "memory-cycle")

    def test_normalize_slug_strips_and_collapses(self):
        self.assertEqual(tl.normalize_slug("  HBM  Capacity  "), "hbm-capacity")

    def test_normalize_slug_keeps_existing_hyphens(self):
        self.assertEqual(tl.normalize_slug("dram-pricing"), "dram-pricing")

    def test_make_id_joins_ticker_and_slug(self):
        self.assertEqual(tl.make_id("2330", "Memory Cycle"), "2330:memory-cycle")

    def test_make_id_uppercases_ticker(self):
        self.assertEqual(tl.make_id("2330", "memory-cycle"), "2330:memory-cycle")


class TrigramSimilarity(unittest.TestCase):
    def test_identical_strings_are_one(self):
        self.assertEqual(tl.trigram_similarity("abcdef", "abcdef"), 1.0)

    def test_completely_different_is_low(self):
        self.assertLess(tl.trigram_similarity("DRAM 漲價週期毛利率", "鋼鐵需求關稅政策"), 0.3)

    def test_minor_rewording_is_high(self):
        a = "DRAM 進入漲價週期，FY26 毛利率 > 40%"
        b = "DRAM 進入漲價週期，FY26 毛利率超過 40%"
        self.assertGreaterEqual(tl.trigram_similarity(a, b), 0.3)


class AddInsert(unittest.TestCase):
    def test_insert_into_empty_ledger(self):
        data = empty_ledger()
        res = tl.add_thesis(data, **base_add_kwargs())
        self.assertEqual(res["action"], "inserted")
        self.assertEqual(res["id"], "2330:memory-cycle")
        self.assertEqual(len(data["theses"]), 1)

    def test_inserted_entry_has_expected_fields(self):
        data = empty_ledger()
        tl.add_thesis(data, **base_add_kwargs())
        e = data["theses"][0]
        self.assertEqual(e["ticker"], "2330")
        self.assertEqual(e["slug"], "memory-cycle")
        self.assertEqual(e["status"], "pending")
        self.assertEqual(e["trigger"]["type"], "event")
        self.assertEqual(e["trigger"]["date"], "2026-06-25")
        self.assertEqual(e["created"], "2026-05-31")
        self.assertEqual(e["history"], [])
        self.assertEqual(e["aliases"], [])
        self.assertIsNone(e["superseded_by"])


class AddUpdate(unittest.TestCase):
    def test_same_key_similar_thesis_updates_in_place(self):
        data = empty_ledger()
        tl.add_thesis(data, **base_add_kwargs())
        res = tl.add_thesis(
            data,
            **base_add_kwargs(
                thesis="DRAM 進入漲價週期，FY26 毛利率超過 40%",
                trigger_date="2026-06-27",
                asof="2026-06-01",
            ),
        )
        self.assertEqual(res["action"], "updated")
        self.assertEqual(len(data["theses"]), 1)
        e = data["theses"][0]
        self.assertEqual(e["trigger"]["date"], "2026-06-27")
        self.assertEqual(e["updated"], "2026-06-01")
        self.assertEqual(e["created"], "2026-05-31")  # unchanged


class AddCollision(unittest.TestCase):
    def test_same_key_divergent_thesis_is_collision(self):
        data = empty_ledger()
        tl.add_thesis(data, **base_add_kwargs())
        res = tl.add_thesis(
            data,
            **base_add_kwargs(
                thesis="鋼鐵需求受關稅政策驅動，2027 產能利用率回升",
            ),
        )
        self.assertEqual(res["action"], "collision")
        self.assertIn("existing_thesis", res)
        self.assertEqual(len(data["theses"]), 1)  # not overwritten
        self.assertEqual(
            data["theses"][0]["thesis"], "DRAM 進入漲價週期，FY26 毛利率 > 40%"
        )


class DueAndExpire(unittest.TestCase):
    def _ledger_with(self, *dates_status):
        data = empty_ledger()
        for i, (d, status) in enumerate(dates_status):
            tl.add_thesis(data, **base_add_kwargs(slug=f"t{i}", trigger_date=d))
            data["theses"][i]["status"] = status
        return data

    def test_pending_with_trigger_today_is_due(self):
        data = self._ledger_with(("2026-06-25", "pending"))
        res = tl.due_theses(data, asof="2026-06-25")
        self.assertEqual([e["id"] for e in res["due"]], ["2330:t0"])

    def test_pending_with_past_trigger_is_due(self):
        data = self._ledger_with(("2026-06-20", "pending"))
        res = tl.due_theses(data, asof="2026-06-25")
        self.assertEqual(len(res["due"]), 1)

    def test_future_trigger_is_not_due(self):
        data = self._ledger_with(("2026-07-01", "pending"))
        res = tl.due_theses(data, asof="2026-06-25")
        self.assertEqual(res["due"], [])

    def test_resolved_thesis_is_not_due(self):
        data = self._ledger_with(("2026-06-20", "passed"))
        res = tl.due_theses(data, asof="2026-06-25")
        self.assertEqual(res["due"], [])

    def test_pending_past_expiry_window_is_auto_expired(self):
        data = self._ledger_with(("2026-06-25", "pending"))
        res = tl.due_theses(data, asof="2026-07-30")  # 35 days later
        self.assertEqual([e["id"] for e in res["expired"]], ["2330:t0"])
        self.assertEqual(data["theses"][0]["status"], "expired")
        self.assertEqual(res["due"], [])  # expired not also reported as due

    def test_expiry_appends_history_note(self):
        data = self._ledger_with(("2026-06-25", "pending"))
        tl.due_theses(data, asof="2026-07-30")
        self.assertEqual(data["theses"][0]["history"][-1]["verdict"], "expired")

    def test_within_expiry_window_still_due_not_expired(self):
        data = self._ledger_with(("2026-06-25", "pending"))
        res = tl.due_theses(data, asof="2026-07-20")  # 25 days, < 30
        self.assertEqual(len(res["due"]), 1)
        self.assertEqual(res["expired"], [])


class Resolve(unittest.TestCase):
    def _one(self):
        data = empty_ledger()
        tl.add_thesis(data, **base_add_kwargs())
        return data

    def test_resolve_sets_status_and_appends_history(self):
        data = self._one()
        res = tl.resolve_thesis(
            data, entry_id="2330:memory-cycle", verdict="passed",
            actual="ASP +8% QoQ，毛利率 42%", note="右峰兌現",
            next_action="HOLD，加碼門檻 $XXX", asof="2026-06-26",
        )
        self.assertEqual(res["action"], "resolved")
        e = data["theses"][0]
        self.assertEqual(e["status"], "passed")
        self.assertEqual(len(e["history"]), 1)
        h = e["history"][0]
        self.assertEqual(h["verdict"], "passed")
        self.assertEqual(h["actual"], "ASP +8% QoQ，毛利率 42%")
        self.assertEqual(h["next_action"], "HOLD，加碼門檻 $XXX")
        self.assertEqual(h["date"], "2026-06-26")

    def test_resolve_unknown_id_errors(self):
        data = self._one()
        res = tl.resolve_thesis(
            data, entry_id="2330:nope", verdict="passed", actual="x",
            note="y", next_action="z", asof="2026-06-26",
        )
        self.assertEqual(res["action"], "not_found")

    def test_resolve_invalid_verdict_errors(self):
        data = self._one()
        with self.assertRaises(ValueError):
            tl.resolve_thesis(
                data, entry_id="2330:memory-cycle", verdict="maybe",
                actual="x", note="y", next_action="z", asof="2026-06-26",
            )


class Reschedule(unittest.TestCase):
    def test_reschedule_moves_trigger_keeps_pending(self):
        data = empty_ledger()
        tl.add_thesis(data, **base_add_kwargs())
        res = tl.reschedule(
            data, entry_id="2330:memory-cycle", to="2026-06-27",
            reason="財報延期", asof="2026-06-25",
        )
        self.assertEqual(res["action"], "rescheduled")
        e = data["theses"][0]
        self.assertEqual(e["trigger"]["date"], "2026-06-27")
        self.assertEqual(e["status"], "pending")
        self.assertEqual(e["history"][-1]["verdict"], "rescheduled")


class Merge(unittest.TestCase):
    def _two(self):
        data = empty_ledger()
        tl.add_thesis(data, **base_add_kwargs(slug="memory-cycle"))
        tl.add_thesis(data, **base_add_kwargs(slug="dram-pricing"))
        tl.resolve_thesis(
            data, entry_id="2330:dram-pricing", verdict="partial",
            actual="x", note="y", next_action="z", asof="2026-06-10",
        )
        # back to pending so both exist; we only care history carries over
        data["theses"][1]["status"] = "pending"
        return data

    def test_merge_removes_source_and_adds_alias(self):
        data = self._two()
        res = tl.merge(data, from_id="2330:dram-pricing", into_id="2330:memory-cycle",
                       asof="2026-06-11")
        self.assertEqual(res["action"], "merged")
        ids = [e["id"] for e in data["theses"]]
        self.assertEqual(ids, ["2330:memory-cycle"])
        self.assertIn("dram-pricing", data["theses"][0]["aliases"])

    def test_merge_carries_history(self):
        data = self._two()
        tl.merge(data, from_id="2330:dram-pricing", into_id="2330:memory-cycle",
                 asof="2026-06-11")
        self.assertTrue(any(h["verdict"] == "partial"
                            for h in data["theses"][0]["history"]))

    def test_after_merge_old_slug_add_redirects(self):
        data = self._two()
        tl.merge(data, from_id="2330:dram-pricing", into_id="2330:memory-cycle",
                 asof="2026-06-11")
        res = tl.add_thesis(data, **base_add_kwargs(
            slug="dram-pricing", trigger_date="2026-09-01", asof="2026-06-12"))
        self.assertEqual(res["action"], "redirected")
        self.assertEqual(len(data["theses"]), 1)


class Supersede(unittest.TestCase):
    def test_supersede_archives_old_creates_new(self):
        data = empty_ledger()
        tl.add_thesis(data, **base_add_kwargs(slug="memory-cycle"))
        res = tl.supersede(
            data, entry_id="2330:memory-cycle", new_slug="hbm-capacity",
            thesis="HBM 產能成為瓶頸，2027 供不應求",
            falsification=["HBM4 量產提前"], trigger_type="date",
            trigger_date="2026-09-01", source="briefing", asof="2026-06-15",
        )
        self.assertEqual(res["action"], "superseded")
        old = tl._find(data, "2330:memory-cycle")
        new = tl._find(data, "2330:hbm-capacity")
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(old["superseded_by"], "2330:hbm-capacity")
        self.assertEqual(new["status"], "pending")


class Stats(unittest.TestCase):
    def _mixed(self):
        data = empty_ledger()
        verdicts = [("a", "passed"), ("b", "passed"), ("c", "failed"),
                    ("d", "partial"), ("e", "expired")]
        for slug, status in verdicts:
            tl.add_thesis(data, **base_add_kwargs(slug=slug))
            if status in tl.VALID_VERDICTS:
                tl.resolve_thesis(data, entry_id=f"2330:{slug}", verdict=status,
                                  actual="x", note="y", next_action="z",
                                  asof="2026-06-26")
            else:
                data["theses"][-1]["status"] = status
        return data

    def test_hit_rate_excludes_partial_and_expired(self):
        data = self._mixed()
        s = tl.stats(data)
        self.assertAlmostEqual(s["hit_rate"], 2 / 3)  # 2 passed / (2+1 failed)

    def test_follow_through_excludes_only_expired_from_numerator(self):
        data = self._mixed()
        s = tl.stats(data)
        # resolved (passed+failed+partial)=4 ; +expired 1 = 5
        self.assertAlmostEqual(s["follow_through_rate"], 4 / 5)

    def test_counts_by_status(self):
        data = self._mixed()
        s = tl.stats(data)
        self.assertEqual(s["counts"]["passed"], 2)
        self.assertEqual(s["counts"]["expired"], 1)


class FileIO(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "ledger.json")

    def test_load_missing_file_returns_empty(self):
        data = tl.load_ledger(self.path)
        self.assertEqual(data, {"theses": []})

    def test_save_then_load_roundtrip(self):
        data = empty_ledger()
        tl.add_thesis(data, **base_add_kwargs())
        tl.save_ledger(self.path, data)
        again = tl.load_ledger(self.path)
        self.assertEqual(again["theses"][0]["id"], "2330:memory-cycle")

    def test_save_is_atomic_no_temp_left(self):
        data = empty_ledger()
        tl.save_ledger(self.path, data)
        leftovers = [f for f in os.listdir(self.tmp) if f != "ledger.json"]
        self.assertEqual(leftovers, [])

    def test_load_corrupt_file_raises(self):
        with open(self.path, "w") as f:
            f.write("{ not json")
        with self.assertRaises(ValueError):
            tl.load_ledger(self.path)

    def test_validate_rejects_bad_status(self):
        data = {"theses": [{"id": "X:y", "status": "weird"}]}
        with self.assertRaises(ValueError):
            tl.validate(data)


class CLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "ledger.json")
        self.script = os.path.join(os.path.dirname(__file__), "thesis_ledger.py")

    def run_cli(self, *args):
        import subprocess
        proc = subprocess.run(
            ["python3", self.script, "--ledger", self.path, *args],
            capture_output=True, text=True,
        )
        return proc

    def _add(self, slug="memory-cycle", thesis="DRAM 漲價週期毛利率 > 40%",
             trigger_date="2026-06-25"):
        return self.run_cli(
            "add", "--ticker", "2330", "--slug", slug, "--thesis", thesis,
            "--falsification", "次季 ASP 不再漲", "--trigger-type", "event",
            "--trigger-date", trigger_date, "--event", "earnings",
            "--metric", "ASP QoQ", "--source", "briefing", "--asof", "2026-05-31",
        )

    def test_add_outputs_json_and_exit_zero(self):
        proc = self._add()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["action"], "inserted")

    def test_collision_exits_code_2(self):
        self._add()
        proc = self._add(thesis="鋼鐵需求關稅政策產能利用率")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["action"], "collision")

    def test_resolve_unknown_id_exits_code_3(self):
        proc = self.run_cli(
            "resolve", "--id", "2330:nope", "--verdict", "passed",
            "--actual", "x", "--note", "y", "--next-action", "z",
            "--asof", "2026-06-26",
        )
        self.assertEqual(proc.returncode, 3)

    def test_due_lists_pending(self):
        self._add()
        proc = self.run_cli("due", "--asof", "2026-06-25")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(len(out["due"]), 1)

    def test_full_lifecycle_add_due_resolve_stats(self):
        self._add()
        self.run_cli("resolve", "--id", "2330:memory-cycle", "--verdict", "passed",
                     "--actual", "ASP +8%", "--note", "ok", "--next-action",
                     "HOLD", "--asof", "2026-06-26")
        proc = self.run_cli("stats")
        s = json.loads(proc.stdout)
        self.assertEqual(s["counts"]["passed"], 1)
        self.assertEqual(s["hit_rate"], 1.0)

    def test_resolve_impact_fields_round_trip(self):
        """D2 thesis-impact: resolve 帶 4 個 impact 旗標，history 中正確存入並可讀回。
        舊呼叫（無 impact 旗標）仍 exit 0 且 history 只有 5 鍵（向後相容）。"""
        self._add()

        # ── 新呼叫：帶完整 impact 旗標 ──────────────────────────────────────
        proc = self.run_cli(
            "resolve", "--id", "2330:memory-cycle",
            "--verdict", "partial",
            "--actual", "AI revenue +6%，GM 壓縮",
            "--note", "基本面 OK，多重 GM re-rate",
            "--next-action", "HOLD，加碼門檻 $350",
            "--fair-value-before", "460",
            "--fair-value-after", "415",
            "--price-impact-pct", "-9.8",
            "--impact-decomp", "thesis +6%/multiple −16%=net −9.8%",
            "--asof", "2026-06-26",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        # 讀回 JSON，確認 history[-1] 有 9 鍵
        with open(self.path) as f:
            data = json.load(f)
        entry = next(e for e in data["theses"] if e["id"] == "2330:memory-cycle")
        self.assertEqual(entry["status"], "partial")
        h = entry["history"][-1]
        self.assertEqual(h["verdict"], "partial")
        self.assertAlmostEqual(h["fair_value_before"], 460.0)
        self.assertAlmostEqual(h["fair_value_after"], 415.0)
        self.assertAlmostEqual(h["price_impact_pct"], -9.8)
        self.assertEqual(h["impact_decomp"], "thesis +6%/multiple −16%=net −9.8%")

    def test_resolve_without_impact_flags_still_exits_zero(self):
        """向後相容：舊呼叫（無 impact 旗標）exit 0，history 中 4 鍵為 None。"""
        self._add()
        proc = self.run_cli(
            "resolve", "--id", "2330:memory-cycle",
            "--verdict", "passed",
            "--actual", "ASP +8%", "--note", "ok", "--next-action", "HOLD",
            "--asof", "2026-06-26",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        with open(self.path) as f:
            data = json.load(f)
        entry = next(e for e in data["theses"] if e["id"] == "2330:memory-cycle")
        h = entry["history"][-1]
        self.assertIsNone(h.get("fair_value_before"))
        self.assertIsNone(h.get("fair_value_after"))
        self.assertIsNone(h.get("price_impact_pct"))
        self.assertIsNone(h.get("impact_decomp"))


if __name__ == "__main__":
    unittest.main()
