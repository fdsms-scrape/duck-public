from __future__ import annotations

import unittest

from duckbot.game.task_service import get_claimable_task_codes, pick_custom_task_slot_ids


class TaskHelpersTests(unittest.TestCase):
    def test_get_claimable_task_codes_returns_only_state_two(self) -> None:
        tasks = [
            {"code": "task-ready", "state": 2},
            {"code": "task-custom", "state": 3},
            {"code": "task-done", "state": 4},
        ]

        codes = get_claimable_task_codes(tasks)

        self.assertEqual(codes, ["task-ready"])

    def test_pick_custom_task_slot_ids_prefers_inventory_slots(self) -> None:
        task = {
            "code": "regTourMicroEpic3",
            "criteria": [
                {
                    "eggType": "DUCK",
                    "eggLevel": [4],
                    "value": 2,
                }
            ],
        }
        eggs = [
            {"slot": 10, "type": "DUCK", "level": 4},
            {"slot": 133, "type": "DUCK", "level": 4},
            {"slot": 134, "type": "DUCK", "level": 4},
        ]

        slot_ids = pick_custom_task_slot_ids(task, eggs, max_merge_slot=25)

        self.assertEqual(slot_ids, [133, 134])

    def test_pick_custom_task_slot_ids_returns_none_without_enough_eggs(self) -> None:
        task = {
            "code": "regTourMicroEpic2",
            "criteria": [
                {
                    "eggType": "DUCK",
                    "eggLevel": [5],
                    "value": 1,
                }
            ],
        }
        eggs = [{"slot": 133, "type": "DUCK", "level": 4}]

        slot_ids = pick_custom_task_slot_ids(task, eggs, max_merge_slot=25)

        self.assertIsNone(slot_ids)
