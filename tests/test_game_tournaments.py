from __future__ import annotations

import unittest

from duckbot.config import AppSettings, FeatureSettings, GameSettings, ProfileSettings
from duckbot.game.clan_show_service import (
    ClanShowService,
    rank_clan_show_targets,
    select_clan_show_targets,
    summarize_sabotage_attacks,
)
from duckbot.game.models import ClanShowTournamentContext, PlayerContext
from duckbot.game.tournament_service import count_uncollected_reward_pass_steps


class _DummyLogger:
    def info(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def warning(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def error(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None


class _StubClanShowService(ClanShowService):
    def __init__(self) -> None:
        super().__init__(
            profile=ProfileSettings(name="main", init_data="query_id=1&auth_date=1"),
            settings=AppSettings(
                features=FeatureSettings(use_clan_show_sabotages=True),
                game=GameSettings(
                    clan_show_attack_limit_per_cycle=1,
                    clan_show_attack_min_success_chance=0.75,
                    clan_show_attack_max_revenge_chance=0.6,
                    clan_show_attack_require_same_group=True,
                    clan_show_attack_refresh_targets_each_use=False,
                ),
            ),
            state_store=None,
            api_client=None,
            logger=_DummyLogger(),
        )
        self.calls: list[tuple[str, dict[str, object] | None]] = []
        self.use_calls: list[tuple[str, dict[str, object]]] = []
        self.sleep_calls = 0
        self.responses = {
            "/clans/show/sabotages": {
                "response": {
                    "sabotages": [
                        {
                            "id": 3317468,
                            "rarity": "COMMON",
                            "attacks": [{"type": "BASIC_ATTACK", "value": 1}],
                        }
                    ],
                    "empty": [],
                }
            },
            "/clans/show/sabotage/best-targets": {
                "response": [
                    {
                        "id": 17674,
                        "state": "ACTIVE",
                        "name": "Троглодиты",
                        "hp": {"currentHp": 280, "maxHp": 750},
                        "sabotageChance": {"successChance": 0.8},
                        "revengeAbilityChance": {"chance": 0.58},
                        "showRating": {"place": 123},
                        "showSameGroup": True,
                    },
                    {
                        "id": 1052,
                        "state": "ACTIVE",
                        "name": "Goldy",
                        "hp": {"currentHp": 747, "maxHp": 750},
                        "sabotageChance": {"successChance": 0.70},
                        "revengeAbilityChance": {"chance": 0.24},
                        "showRating": {"place": 103},
                        "showSameGroup": True,
                    },
                ]
            },
            "/clans/show/sabotage/attacks": {"response": []},
        }

    def safe_post(self, path: str, payload=None):  # noqa: ANN001
        self.calls.append((path, payload))
        return self.responses.get(path)

    def sleep_range(self, delay_range: list[float]) -> None:
        self.sleep_calls += 1

    def _post_once(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        self.use_calls.append((path, payload))
        return {"result": True}


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

    def test_select_clan_show_targets_filters_by_thresholds_and_own_clan(self) -> None:
        targets = [
            {
                "id": 6934,
                "state": "ACTIVE",
                "name": "own",
                "hp": {"currentHp": 500, "maxHp": 750},
                "sabotageChance": {"successChance": 0.99},
                "revengeAbilityChance": {"chance": 0.01},
                "showRating": {"place": 1},
                "showSameGroup": True,
            },
            {
                "id": 17674,
                "state": "ACTIVE",
                "name": "best",
                "hp": {"currentHp": 280, "maxHp": 750},
                "sabotageChance": {"successChance": 0.8},
                "revengeAbilityChance": {"chance": 0.58},
                "showRating": {"place": 123},
                "showSameGroup": True,
            },
            {
                "id": 1052,
                "state": "ACTIVE",
                "name": "too-risky",
                "hp": {"currentHp": 747, "maxHp": 750},
                "sabotageChance": {"successChance": 0.78},
                "revengeAbilityChance": {"chance": 0.7},
                "showRating": {"place": 103},
                "showSameGroup": True,
            },
            {
                "id": 777,
                "state": "ACTIVE",
                "name": "not-same-group",
                "hp": {"currentHp": 300, "maxHp": 750},
                "sabotageChance": {"successChance": 0.9},
                "revengeAbilityChance": {"chance": 0.1},
                "showRating": {"place": 20},
                "showSameGroup": False,
            },
        ]

        filtered = select_clan_show_targets(
            targets,
            own_clan_id=6934,
            min_success_chance=0.75,
            max_revenge_chance=0.6,
            require_same_group=True,
        )

        self.assertEqual([target["id"] for target in filtered], [17674])

    def test_summarize_sabotage_attacks_formats_attack_list(self) -> None:
        sabotage = {
            "attacks": [
                {"type": "BASIC_ATTACK", "value": 2},
                {"type": "FAN_ATTACK", "value": 100},
            ]
        }

        summary = summarize_sabotage_attacks(sabotage)

        self.assertEqual(summary, "BASIC_ATTACK=2, FAN_ATTACK=100")

    def test_clan_show_service_uses_sabotage_with_target_id(self) -> None:
        service = _StubClanShowService()
        player_context = PlayerContext(
            player_id=1596220,
            player_name="main",
            corn=0,
            duck_slots_count=20,
            clan_id=6934,
            egg_slots=[],
            alerts=[],
        )
        tournament_context = ClanShowTournamentContext(
            tournament_group_id=145530,
            group_name="LEAGUE_4",
            league_level=4,
        )

        service.inspect(player_context, tournament_context)

        self.assertEqual(
            service.use_calls,
            [("/clans/show/sabotage/use", {"sabotageId": 3317468, "targetId": 17674})],
        )
