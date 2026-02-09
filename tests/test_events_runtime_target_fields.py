from __future__ import annotations

import unittest
from types import SimpleNamespace

try:
    from misc.events_runtime import _resolve_dm_target_fields
except ModuleNotFoundError:
    _resolve_dm_target_fields = None


class _FakeGuild:
    def __init__(self, members: dict[int, object]):
        self._members = members

    def get_member(self, user_id: int):
        return self._members.get(int(user_id))


@unittest.skipIf(_resolve_dm_target_fields is None, "discord.py not installed")
class EventsRuntimeTargetFieldsTests(unittest.TestCase):
    def test_resolves_member_target_from_guild(self):
        author = SimpleNamespace(id=111, display_name="Brian", global_name="Brian", name="block")
        target_member = SimpleNamespace(id=222, display_name="Caleb", global_name="Caleb", name="caleb")
        guild = _FakeGuild({222: target_member})
        message = SimpleNamespace(author=author, guild=guild)
        req = SimpleNamespace(target="<@222>", target_user_id=222)
        deps = SimpleNamespace(founder_user_ids=set(), user_is_owner=lambda u: False)

        out = _resolve_dm_target_fields(req=req, message=message, deps=deps)
        self.assertEqual(out["target_user_id"], 222)
        self.assertEqual(out["target_display_name"], "Caleb")
        self.assertEqual(out["target_type"], "member")
        self.assertIsNone(out["target_confidence"])
        self.assertEqual(out["target_entity_key"], "discord:222")

    def test_resolves_self_target_from_text_alias(self):
        author = SimpleNamespace(id=111, display_name="Brian", global_name="Brian", name="block")
        message = SimpleNamespace(author=author, guild=None)
        req = SimpleNamespace(target="me", target_user_id=None)
        deps = SimpleNamespace(founder_user_ids=set(), user_is_owner=lambda u: False)

        out = _resolve_dm_target_fields(req=req, message=message, deps=deps)
        self.assertEqual(out["target_user_id"], 111)
        self.assertEqual(out["target_type"], "self")
        self.assertAlmostEqual(float(out["target_confidence"]), 0.85, places=6)
        self.assertEqual(out["target_entity_key"], "discord:111")

    def test_resolves_staff_target_from_founder_set(self):
        author = SimpleNamespace(id=111, display_name="Brian", global_name="Brian", name="block")
        message = SimpleNamespace(author=author, guild=None)
        req = SimpleNamespace(target="<@333>", target_user_id=333)
        deps = SimpleNamespace(founder_user_ids={333}, user_is_owner=lambda u: False)

        out = _resolve_dm_target_fields(req=req, message=message, deps=deps)
        self.assertEqual(out["target_user_id"], 333)
        self.assertEqual(out["target_type"], "staff")
        self.assertIsNone(out["target_confidence"])
        self.assertEqual(out["target_entity_key"], "discord:333")

    def test_resolves_external_when_id_not_in_guild(self):
        author = SimpleNamespace(id=111, display_name="Brian", global_name="Brian", name="block")
        guild = _FakeGuild({})
        message = SimpleNamespace(author=author, guild=guild)
        req = SimpleNamespace(target="<@444>", target_user_id=444)
        deps = SimpleNamespace(founder_user_ids=set(), user_is_owner=lambda u: False)

        out = _resolve_dm_target_fields(req=req, message=message, deps=deps)
        self.assertEqual(out["target_user_id"], 444)
        self.assertEqual(out["target_type"], "external")
        self.assertAlmostEqual(float(out["target_confidence"]), 0.75, places=6)
        self.assertEqual(out["target_entity_key"], "discord:444")

    def test_resolves_explicit_external_entity_key_without_discord_id(self):
        author = SimpleNamespace(id=111, display_name="Brian", global_name="Brian", name="block")
        message = SimpleNamespace(author=author, guild=None)
        req = SimpleNamespace(target="external: Chloe", target_user_id=None)
        deps = SimpleNamespace(founder_user_ids=set(), user_is_owner=lambda u: False)

        out = _resolve_dm_target_fields(req=req, message=message, deps=deps)
        self.assertIsNone(out["target_user_id"])
        self.assertEqual(out["target_type"], "external")
        self.assertEqual(out["target_display_name"], "Chloe")
        self.assertEqual(out["target_entity_key"], "external:chloe")


if __name__ == "__main__":
    unittest.main()
