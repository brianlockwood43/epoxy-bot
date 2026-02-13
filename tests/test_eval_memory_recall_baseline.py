from __future__ import annotations

import copy
import unittest
from pathlib import Path

from eval.memory_recall_baseline import load_memory_recall_fixture
from eval.memory_recall_baseline import run_memory_recall_baseline
from eval.memory_recall_baseline import run_memory_recall_baseline_from_fixture


_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "eval_memory_recall_baseline.json"


class EvalMemoryRecallBaselineTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_recall_baseline_fixture_passes(self):
        report = await run_memory_recall_baseline_from_fixture(str(_FIXTURE_PATH))
        self.assertTrue(report["passed"])
        self.assertEqual(report["failed"], 0)
        self.assertEqual(report["total"], 3)

    async def test_memory_recall_baseline_detects_regression(self):
        fixture = load_memory_recall_fixture(str(_FIXTURE_PATH))
        bad_fixture = copy.deepcopy(fixture)
        bad_fixture["cases"][0]["expected_event_ids"] = [999999]

        report = await run_memory_recall_baseline(bad_fixture)
        self.assertFalse(report["passed"])
        self.assertGreaterEqual(report["failed"], 1)
        failing = [row for row in report["results"] if not row["passed"]]
        self.assertGreaterEqual(len(failing), 1)
        self.assertIn("expected_event_ids", " ".join(failing[0]["reasons"]))


if __name__ == "__main__":
    unittest.main()

