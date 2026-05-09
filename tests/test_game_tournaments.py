from __future__ import annotations

import unittest

from duckbot.game.clan_show_service import rank_clan_show_targets
from duckbot.game.tournament_service import count_uncollected_reward_pass_steps


class TournamentHelpersTests(unittest.TestCase):
    def test_count_uncollected_reward_pass_steps_counts_false_flags(self) -> None:
        tournament = {
            "rewardPasses": [
                {"steps": [{"isCollected": False}, {"isCollected": True}]},
                {"steps": [{"isCollected": False}, {"isCollected": False}]},
            ]
        }

        total = count_uncollected_reward_pass_steps(tournament)

        self.assertEqual(total, 3)

    def test_rank_clan_show_targets_prefers_safer_and_more_profitable_targets(self) -> None:
        targets = [
            {
                "id": 1,
                "name": "low-chance",
                "sabotageChance": {"successChance": 0.7},
                "revengeAbilityChance": {"chance": 0.1},
                "hp": {"currentHp": 100},
                "showRating": {"place": 20},
            },
            {
                "id": 2,
                "name": "best",
                "sabotageChance": {"successChance": 0.8},
                "revengeAbilityChance": {"chance": 0.1},
                "hp": {"currentHp": 150},
                "showRating": {"place": 40},
            },
            {
                "id": 3,
                "name": "same-chance-more-risk",
                "sabotageChance": {"successChance": 0.8},
                "revengeAbilityChance": {"chance": 0.2},
                "hp": {"currentHp": 50},
                "showRating": {"place": 10},
            },
        ]

        ranked = rank_clan_show_targets(targets)

        self.assertEqual([target["id"] for target in ranked], [2, 3, 1])
