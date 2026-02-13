from __future__ import annotations

import copy
import unittest
from pathlib import Path

from eval.controller_policy_adherence import load_controller_policy_fixture
from eval.controller_policy_adherence import run_controller_policy_adherence_baseline
from eval.controller_policy_adherence import run_controller_policy_adherence_baseline_from_fixture


_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "eval_controller_policy_adherence.json"


class EvalControllerPolicyAdherenceTests(unittest.TestCase):
    def test_controller_policy_baseline_fixture_passes(self):
        report = run_controller_policy_adherence_baseline_from_fixture(str(_FIXTURE_PATH))
        self.assertTrue(report["passed"])
        self.assertEqual(report["failed"], 0)
        self.assertEqual(report["total"], 3)

    def test_controller_policy_baseline_detects_regression(self):
        fixture = load_controller_policy_fixture(str(_FIXTURE_PATH))
        bad_fixture = copy.deepcopy(fixture)
        bad_fixture["cases"][1]["forbidden_substrings"] = ["<@222222222>"]

        report = run_controller_policy_adherence_baseline(bad_fixture)
        self.assertFalse(report["passed"])
        self.assertGreaterEqual(report["failed"], 1)
        failing = [row for row in report["results"] if not row["passed"]]
        self.assertGreaterEqual(len(failing), 1)
        self.assertIn("forbidden_substring_present", " ".join(failing[0]["reasons"]))


if __name__ == "__main__":
    unittest.main()

