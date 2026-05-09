from __future__ import annotations

import unittest

from duckbot.config import BreedRuleSettings
from duckbot.game.duck_service import resolve_breed_rule


class BreedRuleTests(unittest.TestCase):
    def test_resolve_breed_rule_matches_by_rarity_and_level(self) -> None:
        rules = [
            BreedRuleSettings(quality="COMMON", min_level=1, max_level=5),
            BreedRuleSettings(quality="RARE", min_level=3, currency="stars"),
        ]

        rule = resolve_breed_rule({"quality": "RARE", "level": 4}, rules)

        self.assertIsNotNone(rule)
        self.assertEqual(rule.quality, "RARE")
        self.assertEqual(rule.currency, "stars")

    def test_resolve_breed_rule_skips_disabled_and_out_of_range_rules(self) -> None:
        rules = [
            BreedRuleSettings(quality="COMMON", min_level=1, max_level=3, enabled=False),
            BreedRuleSettings(quality="COMMON", min_level=5, max_level=7),
        ]

        self.assertIsNone(resolve_breed_rule({"quality": "COMMON", "level": 2}, rules))
        self.assertIsNone(resolve_breed_rule({"quality": "COMMON", "level": 4}, rules))
