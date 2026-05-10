from __future__ import annotations

import unittest

from duckbot.config import AppSettings, ProfileSettings
from duckbot.game.egg_service import (
    EggService,
    find_activatable_cooldown_egg,
    find_custom_task_submission,
    find_inventory_tournament_egg_to_open,
    find_merge_pair,
    find_pending_cooldown_eggs,
    find_ready_cooldown_egg,
)


class _DummyLogger:
    def info(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def warning(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def error(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None


class _RecordingEggService(EggService):
    def __init__(self) -> None:
        super().__init__(
            profile=ProfileSettings(name="main", init_data="query_id=1&auth_date=1"),
            settings=AppSettings(),
            state_store=None,
            api_client=None,
            logger=_DummyLogger(),
            sleep_func=lambda *_args, **_kwargs: None,
        )
        self.open_calls: list[tuple[int, int, int]] = []
        self.merge_calls: list[tuple[int, int]] = []
        self.api_calls: list[tuple[str, dict[str, object]]] = []
        self.fetched_eggs: list[dict[str, object]] = []
        self.refetched_task_payloads = 0
        self.alert_response: list[dict[str, object]] = []
        self.merge_results: dict[tuple[int, int], bool] = {}

    def fetch_eggs(self) -> list[dict[str, object]]:
        eggs = self.fetched_eggs
        self.fetched_eggs = []
        return eggs

    def _fetch_task_categories(self, include_clan: bool) -> dict[str, dict[str, object]]:
        self.refetched_task_payloads += 1
        return {"PLAYER": {"response": {"tasks": []}}}

    def safe_post(self, path: str, payload: dict[str, object] | None = None) -> dict[str, object] | None:
        normalized_payload = payload or {}
        self.api_calls.append((path, normalized_payload))
        if path == "/alert":
            return {"response": self.alert_response}
        if path == "/alert/action":
            return {"result": True}
        return {"result": True}

    def _open_egg(self, slot: int, egg_id: int, queue: int) -> bool:
        self.open_calls.append((slot, egg_id, queue))
        return True

    def _merge_eggs(self, slot1: int, slot2: int) -> bool:
        pair = tuple(sorted((slot1, slot2)))
        self.merge_calls.append(pair)
        return self.merge_results.get(pair, True)


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

    def test_find_merge_pair_merges_identical_unknown_type_by_default_limit(self) -> None:
        eggs = [
            {"slot": 1, "type": "BOX_CLAN_CARD", "level": 1},
            {"slot": 2, "type": "BOX_CLAN_CARD", "level": 1},
        ]

        pair = find_merge_pair(eggs, {"DUCK": 12})

        self.assertEqual(pair, (1, 2))

    def test_find_merge_pair_skips_tournament_points_egg_at_level_five(self) -> None:
        eggs = [
            {"slot": 9, "type": "REGULAR_TOURNAMENT_POINTS_EGG", "level": 5},
            {"slot": 10, "type": "REGULAR_TOURNAMENT_POINTS_EGG", "level": 5},
            {"slot": 11, "type": "REGULAR_TOURNAMENT_EGG", "level": 3},
            {"slot": 12, "type": "REGULAR_TOURNAMENT_EGG", "level": 3},
        ]

        pair = find_merge_pair(eggs, {"DUCK": 12, "REGULAR_TOURNAMENT_EGG": 5})

        self.assertEqual(pair, (11, 12))

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

    def test_find_activatable_cooldown_egg_returns_repeatable_without_tsopen(self) -> None:
        eggs = [
            {"slot": 12, "type": "DUCK", "level": 1, "tsOpen": None},
            {"slot": 13, "type": "REGULAR_TOUR_REPEATABLE_EGG", "level": 1, "tsOpen": None},
            {"slot": 14, "type": "REGULAR_TOUR_REPEATABLE_EGG", "level": 1, "tsOpen": 1_200},
        ]

        egg = find_activatable_cooldown_egg(eggs)

        self.assertEqual(egg, {"slot": 13, "type": "REGULAR_TOUR_REPEATABLE_EGG", "level": 1, "tsOpen": None})

    def test_process_opens_ready_cooldown_egg_outside_active_field(self) -> None:
        service = _RecordingEggService()
        service.process(
            initial_eggs=[
                {"slot": 26, "id": 201, "type": "REGULAR_TOUR_REPEATABLE_EGG", "level": 1, "queue": 2, "tsOpen": 1},
            ],
            active_slots=[6, 7],
        )

        self.assertEqual(service.merge_calls, [])
        self.assertEqual(service.open_calls, [(26, 201, 2)])

    def test_process_starts_cooldown_for_repeatable_egg_without_tsopen(self) -> None:
        service = _RecordingEggService()
        service.process(
            initial_eggs=[
                {"slot": 26, "id": 201, "type": "REGULAR_TOUR_REPEATABLE_EGG", "level": 1, "queue": 2, "tsOpen": None},
            ],
            active_slots=[6, 7],
        )

        self.assertEqual(service.merge_calls, [])
        self.assertEqual(service.open_calls, [(26, 201, 2)])

    def test_process_reports_pending_cooldown_egg_outside_active_field_without_opening(self) -> None:
        service = _RecordingEggService()
        service.process(
            initial_eggs=[
                {"slot": 26, "id": 201, "type": "REGULAR_TOUR_REPEATABLE_EGG", "level": 1, "queue": 2, "tsOpen": 9_999_999_999},
            ],
            active_slots=[6, 7],
        )

        self.assertEqual(service.merge_calls, [])
        self.assertEqual(service.open_calls, [])

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

    def test_process_opens_standard_egg_when_real_active_slots_are_full(self) -> None:
        service = _RecordingEggService()
        service.process(
            initial_eggs=[
                {"slot": 6, "id": 101, "type": "DUCK", "level": 3, "queue": 1},
                {"slot": 7, "id": 102, "type": "HEART", "level": 1, "queue": 1},
                {"slot": 26, "id": 201, "type": "DUCK", "level": 1, "queue": 1},
            ],
            active_slots=[6, 7],
        )

        self.assertEqual(service.merge_calls, [])
        self.assertEqual(service.open_calls, [(7, 102, 1)])

    def test_process_prefers_heart_for_emergency_open_even_if_duck_level_is_lower(self) -> None:
        service = _RecordingEggService()
        service.process(
            initial_eggs=[
                {"slot": 6, "id": 101, "type": "DUCK", "level": 1, "queue": 1},
                {"slot": 7, "id": 102, "type": "HEART", "level": 4, "queue": 1},
                {"slot": 26, "id": 201, "type": "DUCK", "level": 1, "queue": 1},
            ],
            active_slots=[6, 7],
        )

        self.assertEqual(service.merge_calls, [])
        self.assertEqual(service.open_calls, [(7, 102, 1)])

    def test_process_refetches_tasks_after_merge_to_recheck_tournament_submission(self) -> None:
        service = _RecordingEggService()
        service.process(
            initial_eggs=[
                {"slot": 6, "id": 101, "type": "BOX_CLAN_CARD", "level": 1, "queue": 1},
                {"slot": 7, "id": 102, "type": "BOX_CLAN_CARD", "level": 1, "queue": 1},
            ],
            task_payloads={"PLAYER": {"response": {"tasks": []}}},
            active_slots=[6, 7],
        )

        self.assertEqual(service.merge_calls, [(6, 7)])
        self.assertEqual(service.refetched_task_payloads, 1)

    def test_process_tries_next_pair_after_failed_merge(self) -> None:
        service = _RecordingEggService()
        service.merge_results[(6, 7)] = False

        service.process(
            initial_eggs=[
                {"slot": 6, "id": 101, "type": "DUCK", "level": 3, "queue": 1},
                {"slot": 7, "id": 102, "type": "DUCK", "level": 3, "queue": 1},
                {"slot": 8, "id": 103, "type": "DUCK", "level": 3, "queue": 1},
                {"slot": 9, "id": 104, "type": "DUCK", "level": 3, "queue": 1},
            ],
            active_slots=[6, 7, 8, 9],
        )

        self.assertEqual(service.merge_calls, [(6, 7), (8, 9)])
        self.assertEqual(service.open_calls, [])

    def test_process_does_not_open_standard_egg_after_rejected_merge_pair(self) -> None:
        service = _RecordingEggService()
        service.merge_results[(8, 9)] = False

        service.process(
            initial_eggs=[
                {"slot": 6, "id": 101, "type": "DUCK", "level": 1, "queue": 1},
                {"slot": 7, "id": 102, "type": "HEART", "level": 1, "queue": 1},
                {"slot": 8, "id": 103, "type": "REGULAR_TOURNAMENT_EGG", "level": 3, "queue": 1},
                {"slot": 9, "id": 104, "type": "REGULAR_TOURNAMENT_EGG", "level": 3, "queue": 1},
                {"slot": 26, "id": 201, "type": "DUCK", "level": 1, "queue": 1},
            ],
            active_slots=[6, 7, 8, 9],
        )

        self.assertEqual(service.merge_calls, [(8, 9)])
        self.assertEqual(service.open_calls, [])

    def test_process_collects_alert_after_opening_non_heart_egg(self) -> None:
        service = _RecordingEggService()
        service.alert_response = [
            {
                "id": 175286573,
                "type": "REWARD",
                "typeHuman": "Награда",
                "buttons": [
                    {
                        "url": "/alert/action",
                        "params": {"id": 175286573, "action": "confirm"},
                    }
                ],
            }
        ]

        service.process(
            initial_eggs=[
                {"slot": 6, "id": 101, "type": "DUCK", "level": 12, "queue": 1},
            ],
            active_slots=[6],
        )

        self.assertEqual(service.open_calls, [(6, 101, 1)])
        self.assertEqual(
            service.api_calls,
            [
                ("/alert", {}),
                ("/alert/action", {"id": 175286573, "action": "confirm"}),
            ],
        )
