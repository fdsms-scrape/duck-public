from __future__ import annotations

import unittest

from duckbot.config import FeedRuleSettings
from duckbot.game.duck_service import resolve_feed_rule, select_active_ducks


class DuckSelectionTests(unittest.TestCase):
    def test_select_active_ducks_skips_stake_before_slot_limit(self) -> None:
        ducks = [{"id": 1, "state": "STAKE"}]
        ducks.extend({"id": duck_id, "state": "FEED"} for duck_id in range(2, 23))

        active_ducks = select_active_ducks(ducks, 20)

        self.assertEqual(len(active_ducks), 20)
        self.assertTrue(all(duck["state"] == "FEED" for duck in active_ducks))
        self.assertEqual(active_ducks[0]["id"], 2)
        self.assertEqual(active_ducks[-1]["id"], 21)

    def test_select_active_ducks_ignores_non_actionable_states(self) -> None:
        ducks = [
            {"id": 1, "state": "STAKE"},
            {"id": 2, "state": "MARKET"},
            {"id": 3, "state": "FEED"},
            {"id": 4, "state": "BREED"},
        ]

        active_ducks = select_active_ducks(ducks, 5)

        self.assertEqual([duck["id"] for duck in active_ducks], [3, 4])

    def test_resolve_feed_rule_matches_by_rarity_and_level(self) -> None:
        rules = [
            FeedRuleSettings(quality="COMMON", min_level=1, max_level=5, max_cost=20),
            FeedRuleSettings(quality="COMMON", min_level=6, max_cost=50),
        ]

        rule = resolve_feed_rule({"quality": "COMMON", "level": 7}, rules)

        self.assertIsNotNone(rule)
        self.assertEqual(rule.max_cost, 50)

    def test_resolve_feed_rule_skips_disabled_rules(self) -> None:
        rules = [
            FeedRuleSettings(quality="RARE", min_level=1, max_cost=120, enabled=False),
        ]

        self.assertIsNone(resolve_feed_rule({"quality": "RARE", "level": 3}, rules))
