from __future__ import annotations

import unittest

from memory.runtime_recall import maybe_build_memory_pack
from retrieval.service import recall_memory


def _stage_at_least(stage: str) -> bool:
    ranks = {"M0": 0, "M1": 1, "M2": 2, "M3": 3}
    return ranks.get(stage, 0) <= ranks["M3"]


class ControllerBudgetApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_recall_memory_applies_budget_limits_and_tier_mix(self):
        events_pool: list[dict] = []
        next_id = 1
        for tier in (0, 1, 2):
            for i in range(10):
                events_pool.append(
                    {
                        "id": next_id,
                        "tier": tier,
                        "text": f"event tier={tier} idx={i}",
                        "topic_id": f"topic_{tier}_{i}",
                        "channel_id": 100,
                        "author_id": 1000 + i + (tier * 100),
                    }
                )
                next_id += 1

        summaries_pool = [
            {"id": 1, "topic_id": "ops", "summary_text": "s1"},
            {"id": 2, "topic_id": "ops2", "summary_text": "s2"},
            {"id": 3, "topic_id": "ops3", "summary_text": "s3"},
            {"id": 4, "topic_id": "ops4", "summary_text": "s4"},
        ]

        event_limits_seen: list[int] = []
        summary_limits_seen: list[int] = []

        def _search_events(_conn, _query, _scope, limit):
            event_limits_seen.append(int(limit))
            return list(events_pool)

        def _search_summaries(_conn, _query, _scope, limit):
            summary_limits_seen.append(int(limit))
            return list(summaries_pool)[: int(limit)]

        small_budget = {"hot": 1, "warm": 1, "cold": 0, "summaries": 1, "meta": 0}
        large_budget = {"hot": 4, "warm": 3, "cold": 2, "summaries": 3, "meta": 0}

        events_small, summaries_small = await recall_memory(
            "query",
            "auto channel:100 guild:1",
            small_budget,
            stage_at_least=_stage_at_least,
            db_lock=_NoopAsyncLock(),
            db_conn=object(),
            search_memory_events_sync=_search_events,
            search_memory_summaries_sync=_search_summaries,
        )
        events_large, summaries_large = await recall_memory(
            "query",
            "auto channel:100 guild:1",
            large_budget,
            stage_at_least=_stage_at_least,
            db_lock=_NoopAsyncLock(),
            db_conn=object(),
            search_memory_events_sync=_search_events,
            search_memory_summaries_sync=_search_summaries,
        )

        self.assertEqual(len(events_small), 2)
        self.assertEqual(sum(1 for e in events_small if int(e["tier"]) == 0), 1)
        self.assertEqual(sum(1 for e in events_small if int(e["tier"]) == 1), 1)
        self.assertEqual(sum(1 for e in events_small if int(e["tier"]) == 2), 0)
        self.assertEqual(len(summaries_small), 1)

        self.assertEqual(len(events_large), 9)
        self.assertEqual(sum(1 for e in events_large if int(e["tier"]) == 0), 4)
        self.assertEqual(sum(1 for e in events_large if int(e["tier"]) == 1), 3)
        self.assertEqual(sum(1 for e in events_large if int(e["tier"]) == 2), 2)
        self.assertEqual(len(summaries_large), 3)

        self.assertEqual(event_limits_seen[0], 20)  # max(20, (1+1+0)*5)
        self.assertEqual(event_limits_seen[1], 45)  # (4+3+2)*5
        self.assertEqual(summary_limits_seen[0], 1)
        self.assertEqual(summary_limits_seen[1], 3)

    async def test_runtime_memory_pack_forwards_memory_budget(self):
        seen_budget: list[dict | None] = []

        async def _recall(prompt: str, scope: str | None = None, memory_budget: dict | None = None):
            seen_budget.append(memory_budget)
            return ([], [])

        events, summaries, ids, pack = await maybe_build_memory_pack(
            stage_at_least=_stage_at_least,
            infer_scope=lambda _p: "auto",
            recall_memory_func=_recall,
            format_memory_for_llm=lambda _e, _s, max_chars=1700: "",
            safe_prompt="hello",
            scope="auto channel:1 guild:1",
            memory_budget={"hot": 2, "warm": 1, "cold": 0, "summaries": 1, "meta": 0},
            max_chars=500,
        )

        self.assertEqual(events, [])
        self.assertEqual(summaries, [])
        self.assertEqual(ids, [])
        self.assertEqual(pack, "")
        self.assertEqual(len(seen_budget), 1)
        self.assertEqual(seen_budget[0], {"hot": 2, "warm": 1, "cold": 0, "summaries": 1, "meta": 0})


class _NoopAsyncLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


if __name__ == "__main__":
    unittest.main()
