from __future__ import annotations

import unittest

from memory.meta_service import apply_policy_enforcement
from memory.meta_service import format_policy_directive


class PolicyEnforcementRuntimeTests(unittest.TestCase):
    def test_member_context_redacts_other_mentions(self):
        policy_bundle = {
            "policy_ids": [1],
            "enforcement": {
                "no_cross_member_private_disclosure": True,
                "redact_discord_mentions_in_member_context": True,
            },
            "policies": [
                {
                    "id": 1,
                    "priority": "critical",
                    "scope": "policy:member_privacy",
                    "statement": "Do not reveal private information about other members in member-facing contexts.",
                }
            ],
        }
        text, clamps = apply_policy_enforcement(
            "Check with <@123456789012345678> and <@!987654321098765432>.",
            policy_bundle=policy_bundle,
            author_id=123456789012345678,
            caller_type="member",
            surface="public_channel",
        )
        self.assertIn("<@123456789012345678>", text)
        self.assertIn("[redacted-user]", text)
        self.assertIn("redact_discord_mentions", clamps)

    def test_non_member_context_no_redaction(self):
        policy_bundle = {
            "policy_ids": [1],
            "enforcement": {
                "no_cross_member_private_disclosure": True,
                "redact_discord_mentions_in_member_context": True,
            },
            "policies": [],
        }
        text, clamps = apply_policy_enforcement(
            "Check with <@123456789012345678> and <@!987654321098765432>.",
            policy_bundle=policy_bundle,
            author_id=123456789012345678,
            caller_type="founder",
            surface="coach_channel",
        )
        self.assertEqual(text, "Check with <@123456789012345678> and <@!987654321098765432>.")
        self.assertEqual(clamps, [])

    def test_policy_directive_format(self):
        directive = format_policy_directive(
            {
                "policies": [
                    {
                        "priority": "critical",
                        "scope": "policy:member_privacy",
                        "statement": "Do not reveal private information about other members in member-facing contexts.",
                    }
                ]
            }
        )
        self.assertIn("Policy constraints", directive)
        self.assertIn("Do not reveal private information", directive)


if __name__ == "__main__":
    unittest.main()
