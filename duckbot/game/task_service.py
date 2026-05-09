"""Сбор наград задач и турнирных кастомных поручений."""

from __future__ import annotations

from collections import Counter
from typing import Any

from duckbot.game.base import GameService

TASK_CATEGORY_PLAYER = "PLAYER"
TASK_CATEGORY_CLAN = "CLAN"
READY_TASK_STATE = 2
CUSTOM_READY_TASK_STATE = 3


def extract_tasks(category_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Возвращает список задач из ответа `/tasks`."""
    return ((category_payload.get("response") or {}).get("tasks") or [])


def count_task_states(tasks: list[dict[str, Any]]) -> dict[int, int]:
    """Считает распределение задач по состояниям."""
    return dict(Counter(int(task.get("state") or 0) for task in tasks))


def get_claimable_task_codes(tasks: list[dict[str, Any]]) -> list[str]:
    """Выделяет обычные задачи с готовой наградой."""
    return [
        str(task["code"])
        for task in tasks
        if task.get("state") == READY_TASK_STATE and task.get("code")
    ]


def get_custom_reward_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Выделяет кастомные задачи, которые требуют `tasks/reward/custom`."""
    return [
        task
        for task in tasks
        if task.get("state") == CUSTOM_READY_TASK_STATE and task.get("code")
    ]


def pick_custom_task_slot_ids(
    task: dict[str, Any],
    eggs: list[dict[str, Any]],
    *,
    max_merge_slot: int,
) -> list[int] | None:
    """Подбирает слоты яиц для кастомной турнирной награды."""
    criteria = task.get("criteria") or []
    if not criteria:
        return None

    chosen_slots: list[int] = []
    used_slots: set[int] = set()

    for criterion in criteria:
        egg_type = criterion.get("eggType")
        levels = set(criterion.get("eggLevel") or [])
        count = int(criterion.get("value") or 0)
        if not egg_type or count <= 0:
            continue

        matches = [
            egg
            for egg in eggs
            if int(egg.get("slot", 0)) not in used_slots
            and egg.get("type") == egg_type
            and (not levels or egg.get("level") in levels)
        ]
        matches.sort(
            key=lambda egg: (
                int(egg.get("slot", 0)) <= max_merge_slot,
                int(egg.get("level", 0)),
                int(egg.get("slot", 0)),
            )
        )
        if len(matches) < count:
            return None

        for egg in matches[:count]:
            slot = int(egg["slot"])
            chosen_slots.append(slot)
            used_slots.add(slot)

    return chosen_slots or None


class TaskService(GameService):
    """Управляет обычными и кастомными наградами задач."""

    def fetch_categories(self, *, include_clan: bool) -> dict[str, dict[str, Any]]:
        categories = [TASK_CATEGORY_PLAYER]
        if include_clan:
            categories.append(TASK_CATEGORY_CLAN)

        category_payloads: dict[str, dict[str, Any]] = {}
        for category in categories:
            response = self.safe_post("/tasks", {"category": category})
            if not response:
                continue
            tasks = extract_tasks(response)
            self.logger.info(
                "Задачи %s: %s шт., состояния=%s",
                category.lower(),
                len(tasks),
                count_task_states(tasks),
            )
            category_payloads[category] = response
        return category_payloads

    def collect_standard_rewards(self, category_payloads: dict[str, dict[str, Any]]) -> int:
        collected_count = 0
        for category, payload in category_payloads.items():
            for code in get_claimable_task_codes(extract_tasks(payload)):
                response = self.safe_post("/tasks/reward", {"code": code})
                if not response:
                    continue
                collected_count += 1
                self.logger.info(
                    "Забрали награду задачи %s из категории %s",
                    code,
                    category.lower(),
                )
                self.sleep_range(self.settings.between_actions_delay_seconds)
        return collected_count

    def collect_custom_rewards(
        self,
        category_payloads: dict[str, dict[str, Any]],
        eggs: list[dict[str, Any]],
    ) -> set[int]:
        reserved_slots: set[int] = set()
        for category, payload in category_payloads.items():
            for task in get_custom_reward_tasks(extract_tasks(payload)):
                code = str(task["code"])
                available_eggs = [egg for egg in eggs if int(egg.get("slot", 0)) not in reserved_slots]
                slot_ids = pick_custom_task_slot_ids(
                    task,
                    available_eggs,
                    max_merge_slot=self.settings.game.max_merge_slot,
                )
                if not slot_ids:
                    self.logger.info(
                        "Для кастомной задачи %s из категории %s не нашлось подходящих яиц.",
                        code,
                        category.lower(),
                    )
                    continue

                response = self.safe_post("/tasks/reward/custom", {"code": code, "slotIds": slot_ids})
                if not response:
                    continue

                reserved_slots.update(slot_ids)
                self.logger.info(
                    "Забрали кастомную награду %s, использованы слоты яиц %s",
                    code,
                    slot_ids,
                )
                self.sleep_range(self.settings.between_actions_delay_seconds)
        return reserved_slots

    def count_custom_reward_candidates(self, category_payloads: dict[str, dict[str, Any]]) -> int:
        return sum(len(get_custom_reward_tasks(extract_tasks(payload))) for payload in category_payloads.values())
