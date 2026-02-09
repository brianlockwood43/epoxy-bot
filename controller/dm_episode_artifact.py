from __future__ import annotations

from typing import Any


def build_dm_episode_artifact(*, parse_payload: dict[str, Any], result_payload: dict[str, Any]) -> dict[str, Any]:
    """
    Stable artifact envelope for DM draft episodes.
    Shape:
      episode.kind = "dm_draft"
      episode.artifact.dm.parse = {...}
      episode.artifact.dm.result = {...}
    """
    return {
        "episode": {
            "kind": "dm_draft",
            "artifact": {
                "dm": {
                    "parse": dict(parse_payload or {}),
                    "result": dict(result_payload or {}),
                }
            },
        }
    }
