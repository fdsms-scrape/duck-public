from __future__ import annotations

import unittest

from duckbot.game.egg_service import (
    find_custom_task_submission,
    find_inventory_tournament_egg_to_open,
    find_merge_pair,
    find_pending_cooldown_eggs,
    find_ready_cooldown_egg,
)


class EggServiceHelpersTests(unittest.TestCase):
    def test_find_merge_pair_skips_pair_at_max_level_and_chooses_lower_valid_pair(self) -> None:
        eggs = [
            {"slot": 15, "type": "REGULAR_TOURNAMENT_EGG", "level": 5},
            {"slot": 22, "type": "REGULAR_TOURNAMENT_EGG", "level": 5},
            {"slot": 12, "type": "REGULAR_TOURNAMENT_EGG", "level": 2},
            {"slot": 16, "type": "REGULAR_TOURNAMENT_EGG", "level": 2},
        ]

        pair = find_merge_pair(
            eggs,
            {
                "DUCK": 12,
                "HEART": 12,
                "REGULAR_TOURNAMENT_EGG": 5,
            },
        )

        self.assertEqual(pair, (12, 16))

    def test_find_merge_pair_does_not_merge_unknown_type_without_limit(self) -> None:
        eggs = [
            {"slot": 1, "type": "BOX_CLAN_CARD", "level": 1},
            {"slot": 2, "type": "BOX_CLAN_CARD", "level": 1},
        ]

        pair = find_merge_pair(eggs, {"DUCK": 12})

        self.assertIsNone(pair)

    def test_find_ready_cooldown_egg_uses_tsopen_not_type_name(self) -> None:
        egg = {
            "slot": 11,
            "type": "UNIQUE_EVENT_EGG",
            "level": 1,
            "tsOpen": 1_000,
        }

        ready_egg = find_ready_cooldown_egg([egg], current_ts=1_000)

        self.assertEqual(ready_egg, egg)

    def test_find_pending_cooldown_eggs_returns_only_future_tsopen(self) -> None:
        eggs = [
            {"slot": 10, "type": "REGULAR_TOUR_REPEATABLE_EGG", "level": 1, "tsOpen": 1_200},
            {"slot": 11, "type": "REGULAR_TOUR_REPEATABLE_EGG", "level": 1, "tsOpen": 1_100},
            {"slot": 12, "type": "DUCK", "level": 1, "tsOpen": None},
        ]

        pending = find_pending_cooldown_eggs(eggs, current_ts=1_050)

        self.assertEqual([egg["slot"] for egg in pending], [11, 10])

    def test_find_custom_task_submission_prefers_satisfiable_task_on_active_field(self) -> None:
        category_payloads = {
            "PLAYER": {
                "response": {
                    "tasks": [
                        {
                            "code": "regTourMicroEpic2",
                            "state": 3,
                            "type": "EGG_GROUP_TASK",
                            "criteria": [{"eggType": "DUCK", "eggLevel": [5], "value": 1}],
                        },
                        {
                            "code": "regTourMicroEpic3",
                            "state": 3,
                            "type": "EGG_GROUP_TASK",
                            "criteria": [{"eggType": "DUCK", "eggLevel": [4], "value": 2}],
                        },
                    ]
                }
            }
        }
        eggs = [
            {"slot": 21, "type": "DUCK", "level": 5},
            {"slot": 23, "type": "DUCK", "level": 4},
            {"slot": 189, "type": "DUCK", "level": 4},
            {"slot": 190, "type": "DUCK", "level": 4},
        ]

        submission = find_custom_task_submission(
            category_payloads,
            eggs,
            max_merge_slot=25,
            active_slots={21, 23},
        )

        self.assertEqual(
            submission,
            {
                "category": "player",
                "code": "regTourMicroEpic2",
                "task_type": "EGG_GROUP_TASK",
                "slot_ids": [21],
            },
        )

    def test_find_custom_task_submission_ignores_locked_slots_even_if_number_is_small(self) -> None:
        category_payloads = {
            "PLAYER": {
                "response": {
                    "tasks": [
                        {
                            "code": "regTourMicroEpic2",
                            "state": 3,
                            "type": "EGG_GROUP_TASK",
                            "criteria": [{"eggType": "DUCK", "eggLevel": [5], "value": 1}],
                        },
                    ]
                }
            }
        }
        eggs = [
            {"slot": 5, "type": "DUCK", "level": 5},
            {"slot": 21, "type": "DUCK", "level": 5},
        ]

        submission = find_custom_task_submission(
            category_payloads,
            eggs,
            max_merge_slot=25,
            active_slots={21},
        )

        self.assertEqual(
            submission,
            {
                "category": "player",
                "code": "regTourMicroEpic2",
                "task_type": "EGG_GROUP_TASK",
                "slot_ids": [21],
            },
        )

    def test_find_inventory_tournament_egg_to_open_returns_only_inventory_regular_tournament_egg(self) -> None:
        eggs = [
            {"slot": 21, "id": 1, "type": "REGULAR_TOURNAMENT_EGG", "level": 5},
            {"slot": 111, "id": 2, "type": "REGULAR_TOURNAMENT_EGG", "level": 2},
            {"slot": 112, "id": 3, "type": "REGULAR_TOUR_REPEATABLE_EGG", "level": 1, "tsOpen": 9999},
        ]

        egg = find_inventory_tournament_egg_to_open(eggs, max_merge_slot=25)

        self.assertEqual(egg, {"slot": 111, "id": 2, "type": "REGULAR_TOURNAMENT_EGG", "level": 2})
