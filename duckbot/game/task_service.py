"""Сбор наград задач и турнирных кастомных поручений."""

from __future__ import annotations

from collections import Counter
from typing import Any

from duckbot.game.base import GameService

TASK_CATEGORY_PLAYER = "PLAYER"
TASK_CATEGORY_CLAN = "CLAN"
READY_TASK_STATE = 2
CUSTOM_READY_TASK_STATE = 3
STANDARD_REWARD_STATES = {READY_TASK_STATE, CUSTOM_READY_TASK_STATE}
MAX_AUTO_TOURNAMENT_EGG_LEVEL = 9


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_tasks(category_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Возвращает список задач из ответа `/tasks`."""
    return ((category_payload.get("response") or {}).get("tasks") or [])


def count_task_states(tasks: list[dict[str, Any]]) -> dict[int, int]:
    """Считает распределение задач по состояниям."""
    return dict(Counter(int(task.get("state") or 0) for task in tasks))


def is_custom_reward_task(task: dict[str, Any]) -> bool:
    """Определяет задачи, которые нужно забирать через `/tasks/reward/custom`."""
    return bool(
        task.get("state") == CUSTOM_READY_TASK_STATE
        and task.get("code")
        and task.get("type") == "EGG_GROUP_TASK"
        and isinstance(task.get("criteria"), list)
    )


def is_standard_reward_task_claimable(task: dict[str, Any]) -> bool:
    """Пытается консервативно определить, можно ли безопасно забирать обычную награду."""
    if task.get("state") not in STANDARD_REWARD_STATES or not task.get("code"):
        return False

    if is_custom_reward_task(task):
        return False

    rewards = task.get("reward") or []
    if not rewards:
        return False

    value = _to_int(task.get("value"))
    progress = _to_int(task.get("progress"))
    if value is None or progress is None:
        return False

    if value < 0:
        return False

    return progress >= value


def get_claimable_task_codes(tasks: list[dict[str, Any]]) -> list[str]:
    """Выделяет обычные задачи, которые выглядят готовыми к безопасному автосбору."""
    return [
        str(task["code"])
        for task in tasks
        if is_standard_reward_task_claimable(task)
    ]


def get_custom_reward_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Выделяет кастомные задачи, которые требуют `tasks/reward/custom`."""
    return [task for task in tasks if is_custom_reward_task(task)]


def pick_custom_task_slot_ids(
    task: dict[str, Any],
    eggs: list[dict[str, Any]],
    *,
    max_merge_slot: int,
    prefer_inventory_slots: bool = True,
    active_slots_only: bool = False,
    active_slots: set[int] | None = None,
) -> list[int] | None:
    """Подбирает слоты яиц для кастомной турнирной награды."""
    criteria = task.get("criteria") or []
    if not criteria:
        return None

    chosen_slots: list[int] = []
    used_slots: set[int] = set()

    for criterion in criteria:
        if not isinstance(criterion, dict):
            continue
        egg_type = criterion.get("eggType")
        levels = {
            int(level)
            for level in (criterion.get("eggLevel") or [])
            if _to_int(level) is not None and int(level) <= MAX_AUTO_TOURNAMENT_EGG_LEVEL
        }
        requested_levels = {
            int(level)
            for level in (criterion.get("eggLevel") or [])
            if _to_int(level) is not None
        }
        count = int(criterion.get("value") or 0)
        if not egg_type or count <= 0:
            continue
        if requested_levels and not levels:
            return None

        matches = [
            egg
            for egg in eggs
            if int(egg.get("slot", 0)) not in used_slots
            and (
                not active_slots_only
                or (
                    int(egg.get("slot", 0)) in active_slots
                    if active_slots is not None
                    else 1 <= int(egg.get("slot", 0)) <= max_merge_slot
                )
            )
            and egg.get("type") == egg_type
            and (not levels or egg.get("level") in levels)
        ]
        matches.sort(
            key=lambda egg: (
                (int(egg.get("slot", 0)) <= max_merge_slot)
                if prefer_inventory_slots
                else (int(egg.get("slot", 0)) > max_merge_slot),
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
            tasks = extract_tasks(payload)
            claimable_tasks = [task for task in tasks if is_standard_reward_task_claimable(task)]
            skipped_tasks = [
                task
                for task in tasks
                if task.get("state") in STANDARD_REWARD_STATES
                and task.get("code")
                and not is_custom_reward_task(task)
                and not is_standard_reward_task_claimable(task)
            ]

            if skipped_tasks:
                skipped_by_type = dict(Counter(str(task.get("type") or "UNKNOWN") for task in skipped_tasks))
                skipped_by_state = dict(Counter(int(task.get("state") or 0) for task in skipped_tasks))
                self.logger.info(
                    "Пропускаем %s задач для /tasks/reward из категории %s: они не выглядят готовыми к безопасному автосбору, состояния=%s, типы=%s",
                    len(skipped_tasks),
                    category.lower(),
                    skipped_by_state,
                    skipped_by_type,
                )

            for task in claimable_tasks:
                code = str(task["code"])
                task_type = str(task.get("type") or "UNKNOWN")
                response = self.safe_post("/tasks/reward", {"code": code})
                if not response:
                    self.logger.warning(
                        "Не удалось забрать награду задачи %s (%s) из категории %s. Останавливаем автосбор обычных задач до следующего цикла.",
                        code,
                        task_type,
                        category.lower(),
                    )
                    return collected_count
                collected_count += 1
                self.logger.info(
                    "Забрали награду задачи %s (%s) из категории %s",
                    code,
                    task_type,
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
            skipped_tasks = [
                task
                for task in extract_tasks(payload)
                if task.get("state") == CUSTOM_READY_TASK_STATE
                and task.get("code")
                and not task.get("criteria")
            ]
            if skipped_tasks:
                skipped_by_type = dict(Counter(str(task.get("type") or "UNKNOWN") for task in skipped_tasks))
                self.logger.info(
                    "Пропускаем %s задач state=3 из категории %s без criteria: для них пока нет безопасного обработчика, типы=%s",
                    len(skipped_tasks),
                    category.lower(),
                    skipped_by_type,
                )

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
                    self.logger.warning(
                        "Не удалось забрать кастомную награду %s из категории %s со слотами %s. Останавливаем автосбор кастомных задач до следующего цикла.",
                        code,
                        category.lower(),
                        slot_ids,
                    )
                    return reserved_slots

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
