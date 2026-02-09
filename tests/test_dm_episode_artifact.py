from __future__ import annotations

import unittest

from controller.dm_episode_artifact import build_dm_episode_artifact


class DmEpisodeArtifactTests(unittest.TestCase):
    def test_builds_stable_dm_artifact_shape(self):
        parse_payload = {"objective": "de-escalate", "tone": "steady"}
        result_payload = {"status": "drafted", "drafts": [{"id": "primary", "text": "hello"}]}
        artifact = build_dm_episode_artifact(
            parse_payload=parse_payload,
            result_payload=result_payload,
        )
        self.assertIn("episode", artifact)
        self.assertEqual(artifact["episode"]["kind"], "dm_draft")
        self.assertIn("artifact", artifact["episode"])
        self.assertIn("dm", artifact["episode"]["artifact"])
        self.assertEqual(artifact["episode"]["artifact"]["dm"]["parse"]["objective"], "de-escalate")
        self.assertEqual(artifact["episode"]["artifact"]["dm"]["result"]["status"], "drafted")


if __name__ == "__main__":
    unittest.main()
