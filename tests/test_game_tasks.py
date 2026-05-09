from __future__ import annotations

import unittest

from duckbot.config import AppSettings, ProfileSettings
from duckbot.game.task_service import (
    TaskService,
    get_claimable_task_codes,
    get_custom_reward_tasks,
    pick_custom_task_slot_ids,
)


class _DummyLogger:
    def info(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def warning(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def error(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None


class _StubTaskService(TaskService):
    def __init__(self, responses: list[dict[str, object] | None]) -> None:
        super().__init__(
            profile=ProfileSettings(name="main", init_data="query_id=1&auth_date=1"),
            settings=AppSettings(),
            state_store=None,
            api_client=None,
            logger=_DummyLogger(),
        )
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object] | None]] = []
        self.sleep_calls = 0

    def safe_post(self, path: str, payload=None):  # noqa: ANN001
        self.calls.append((path, payload))
        if self.responses:
            return self.responses.pop(0)
        return None

    def sleep_range(self, delay_range: list[float]) -> None:
        self.sleep_calls += 1


class TaskHelpersTests(unittest.TestCase):
    def test_get_claimable_task_codes_returns_only_safe_candidates(self) -> None:
        tasks = [
            {"code": "task-in-progress", "state": 2, "type": "REFERRALS", "value": 10, "progress": 2, "reward": [{"type": "STARS", "value": 50}]},
            {"code": "task-complete", "state": 2, "type": "DUCK_STAKE", "value": 5, "progress": 5, "reward": [{"type": "STARS", "value": 300}]},
            {
                "code": "offer-box",
                "state": 2,
                "type": "PRICE",
                "groupCode": "offerBoxCard",
                "price": {"stars": 95},
                "dtStart": "2025-11-30 00:00:00",
                "dtEnd": "2026-11-30 23:59:59",
                "reward": [{"type": "EGG", "value": 5}],
                "value": 1,
                "progress": 0,
            },
            {"code": "task-custom", "state": 3},
            {"code": "task-done", "state": 4},
        ]

        codes = get_claimable_task_codes(tasks)

        self.assertEqual(codes, ["task-complete"])

    def test_collect_standard_rewards_stops_after_first_failed_reward(self) -> None:
        service = _StubTaskService([None])
        category_payloads = {
            "PLAYER": {
                "response": {
                    "tasks": [
                        {
                            "code": "offer-1",
                            "state": 2,
                            "type": "PRICE",
                            "groupCode": "offerBoxCard",
                            "price": {"stars": 95},
                            "dtStart": "2025-11-30 00:00:00",
                            "dtEnd": "2026-11-30 23:59:59",
                            "reward": [{"type": "EGG", "value": 5}],
                            "value": 1,
                            "progress": 1,
                        },
                        {
                            "code": "offer-2",
                            "state": 2,
                            "type": "PRICE",
                            "groupCode": "offerBoxCard",
                            "price": {"stars": 95},
                            "dtStart": "2025-11-30 00:00:00",
                            "dtEnd": "2026-11-30 23:59:59",
                            "reward": [{"type": "EGG", "value": 5}],
                            "value": 1,
                            "progress": 1,
                        },
                    ]
                }
            }
        }

        collected_count = service.collect_standard_rewards(category_payloads)

        self.assertEqual(collected_count, 0)
        self.assertEqual(service.calls, [("/tasks/reward", {"code": "offer-1"})])
        self.assertEqual(service.sleep_calls, 0)

    def test_get_custom_reward_tasks_requires_criteria(self) -> None:
        tasks = [
            {"code": "duck-feed-chain", "state": 3, "type": "DUCK_FEED"},
            {
                "code": "egg-group",
                "state": 3,
                "type": "EGG_GROUP_TASK",
                "criteria": [{"eggType": "DUCK", "eggLevel": [5], "value": 1}],
            },
        ]

        custom_tasks = get_custom_reward_tasks(tasks)

        self.assertEqual([task["code"] for task in custom_tasks], ["egg-group"])

    def test_collect_custom_rewards_stops_after_first_failed_reward(self) -> None:
        service = _StubTaskService([None])
        category_payloads = {
            "PLAYER": {
                "response": {
                    "tasks": [
                        {
                            "code": "duck-feed-chain",
                            "state": 3,
                            "type": "DUCK_FEED",
                        },
                        {
                            "code": "egg-group-1",
                            "state": 3,
                            "type": "EGG_GROUP_TASK",
                            "criteria": [{"eggType": "DUCK", "eggLevel": [5], "value": 1}],
                        },
                        {
                            "code": "egg-group-2",
                            "state": 3,
                            "type": "EGG_GROUP_TASK",
                            "criteria": [{"eggType": "DUCK", "eggLevel": [4], "value": 1}],
                        },
                    ]
                }
            }
        }
        eggs = [
            {"slot": 133, "type": "DUCK", "level": 5},
            {"slot": 134, "type": "DUCK", "level": 4},
        ]

        reserved_slots = service.collect_custom_rewards(category_payloads, eggs)

        self.assertEqual(reserved_slots, set())
        self.assertEqual(service.calls, [("/tasks/reward/custom", {"code": "egg-group-1", "slotIds": [133]})])

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

    def test_pick_custom_task_slot_ids_can_be_limited_to_active_slots(self) -> None:
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
        eggs = [
            {"slot": 21, "type": "DUCK", "level": 5},
            {"slot": 239, "type": "DUCK", "level": 5},
        ]

        slot_ids = pick_custom_task_slot_ids(
            task,
            eggs,
            max_merge_slot=25,
            prefer_inventory_slots=False,
            active_slots_only=True,
            active_slots={21},
        )

        self.assertEqual(slot_ids, [21])

    def test_pick_custom_task_slot_ids_respects_real_opened_slots(self) -> None:
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
        eggs = [
            {"slot": 5, "type": "DUCK", "level": 5},
            {"slot": 21, "type": "DUCK", "level": 5},
        ]

        slot_ids = pick_custom_task_slot_ids(
            task,
            eggs,
            max_merge_slot=25,
            prefer_inventory_slots=False,
            active_slots_only=True,
            active_slots={21},
        )

        self.assertEqual(slot_ids, [21])

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
