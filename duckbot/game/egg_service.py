"""Обработка, объединение и открытие яиц."""

from __future__ import annotations

import time
from typing import Any

from duckbot.constants import DEFAULT_EGG_MERGE_LIMITS
from duckbot.game.alerts_service import iter_confirmable_alert_actions
from duckbot.game.base import GameService
from duckbot.game.task_service import extract_tasks, get_custom_reward_tasks, pick_custom_task_slot_ids


def _egg_type(egg: dict[str, Any]) -> str:
    return str(egg.get("type") or "").strip().upper()


def _egg_level(egg: dict[str, Any]) -> int:
    return int(egg.get("level", 0))


def _egg_slot(egg: dict[str, Any]) -> int:
    return int(egg.get("slot", 0))


def _normalize_slot_pair(slot1: int, slot2: int) -> tuple[int, int]:
    return tuple(sorted((int(slot1), int(slot2))))


def is_cooldown_egg(egg: dict[str, Any]) -> bool:
    """Определяет яйца, которые открываются только после таймера."""
    return egg.get("tsOpen") is not None


def is_repeatable_tournament_egg(egg: dict[str, Any]) -> bool:
    """Определяет повторяемые яйца, которые можно перевести в режим отката."""
    return "REPEATABLE" in _egg_type(egg)


def is_cooldown_egg_ready(egg: dict[str, Any], current_ts: int) -> bool:
    """Проверяет, истек ли таймер открытия у яйца с откатом."""
    ts_open = egg.get("tsOpen")
    if ts_open is None:
        return False
    return current_ts >= int(ts_open)


def find_ready_cooldown_egg(eggs: list[dict[str, Any]], current_ts: int) -> dict[str, Any] | None:
    """Ищет первое яйцо с таймером, которое уже можно открыть."""
    ready_eggs = [
        egg
        for egg in eggs
        if is_cooldown_egg(egg) and is_cooldown_egg_ready(egg, current_ts)
    ]
    if not ready_eggs:
        return None
    return min(ready_eggs, key=lambda egg: (_egg_slot(egg), _egg_level(egg), _egg_type(egg)))


def find_pending_cooldown_eggs(eggs: list[dict[str, Any]], current_ts: int) -> list[dict[str, Any]]:
    """Возвращает яйца с откатом, которые еще ждут окончания таймера."""
    pending_eggs = [
        egg
        for egg in eggs
        if is_cooldown_egg(egg) and not is_cooldown_egg_ready(egg, current_ts)
    ]
    return sorted(pending_eggs, key=lambda egg: (int(egg.get("tsOpen") or 0), _egg_slot(egg)))


def find_activatable_cooldown_egg(eggs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Ищет повторяемое яйцо без таймера, которое нужно поставить на откат."""
    activatable_eggs = [
        egg
        for egg in eggs
        if is_repeatable_tournament_egg(egg) and egg.get("tsOpen") is None
    ]
    if not activatable_eggs:
        return None
    return min(activatable_eggs, key=lambda egg: (_egg_slot(egg), _egg_level(egg), _egg_type(egg)))


def is_egg_merge_allowed(egg: dict[str, Any], egg_merge_limits: dict[str, int]) -> bool:
    """Проверяет, можно ли объединять яйцо дальше по его типу и уровню."""
    egg_type = _egg_type(egg)
    max_level = egg_merge_limits.get(egg_type)
    if max_level is None:
        if "TOURNAMENT" in egg_type or "REPEATABLE" in egg_type:
            max_level = 5
        else:
            max_level = DEFAULT_EGG_MERGE_LIMITS["DUCK"]
    return 1 <= _egg_level(egg) < max_level


def find_merge_pair(
    eggs: list[dict[str, Any]],
    egg_merge_limits: dict[str, int],
    excluded_slots: set[int] | None = None,
) -> tuple[int, int] | None:
    """Ищет первую допустимую пару одинаковых яиц для объединения."""
    excluded_slots = excluded_slots or set()
    seen: dict[tuple[str, int], int] = {}
    for egg in sorted(
        eggs,
        key=lambda item: (-_egg_level(item), _egg_type(item), _egg_slot(item)),
    ):
        key = (_egg_type(egg), _egg_level(egg))
        slot = _egg_slot(egg)
        if slot in excluded_slots:
            continue
        if key in seen and is_egg_merge_allowed(egg, egg_merge_limits):
            return _normalize_slot_pair(seen[key], slot)
        seen[key] = slot
    return None


def find_custom_task_submission(
    category_payloads: dict[str, dict[str, Any]],
    eggs: list[dict[str, Any]],
    *,
    max_merge_slot: int,
    active_slots: set[int] | None = None,
) -> dict[str, Any] | None:
    """Ищет первую турнирную задачу, которую уже можно закрыть яйцами с активного поля."""
    for category, payload in category_payloads.items():
        for task in get_custom_reward_tasks(extract_tasks(payload)):
            slot_ids = pick_custom_task_slot_ids(
                task,
                eggs,
                max_merge_slot=max_merge_slot,
                prefer_inventory_slots=False,
                active_slots_only=True,
                active_slots=active_slots,
            )
            if not slot_ids:
                continue
            return {
                "category": category.lower(),
                "code": str(task["code"]),
                "task_type": str(task.get("type") or "UNKNOWN"),
                "slot_ids": slot_ids,
            }
    return None


def find_inventory_tournament_egg_to_open(
    eggs: list[dict[str, Any]],
    *,
    max_merge_slot: int,
) -> dict[str, Any] | None:
    """Ищет обычное турнирное яйцо в инвентаре, которое можно сразу открыть вне режима участия."""
    inventory_tournament_eggs = [
        egg
        for egg in eggs
        if egg.get("id")
        and _egg_slot(egg) > max_merge_slot
        and _egg_type(egg) == "REGULAR_TOURNAMENT_EGG"
        and not is_cooldown_egg(egg)
    ]
    if not inventory_tournament_eggs:
        return None
    return min(inventory_tournament_eggs, key=lambda egg: (_egg_level(egg), _egg_slot(egg)))


class EggService(GameService):
    """Управляет merge/open логикой яиц на активном поле."""

    def fetch_eggs(self) -> list[dict[str, Any]]:
        response = self.safe_post("/eggs")
        return (response or {}).get("response", [])

    def process(
        self,
        *,
        initial_eggs: list[dict[str, Any]] | None = None,
        reserved_slots: set[int] | None = None,
        task_payloads: dict[str, dict[str, Any]] | None = None,
        include_clan_tasks: bool = False,
        active_slots: list[int] | None = None,
    ) -> None:
        reserved_slots = reserved_slots or set()
        merge_count = 0
        open_count = 0
        current_eggs = initial_eggs
        current_task_payloads = task_payloads or {}
        custom_reward_stop = False
        active_slot_set = {
            slot
            for slot in (active_slots or [])
            if 1 <= int(slot) <= self.settings.game.max_merge_slot
        }
        if not active_slot_set:
            active_slot_set = set(range(1, self.settings.game.max_merge_slot + 1))

        if reserved_slots:
            self.logger.info(
                "Зарезервированы слоты яиц, которые нельзя трогать в этом цикле: %s",
                sorted(reserved_slots),
            )

        while True:
            eggs = current_eggs if current_eggs is not None else self.fetch_eggs()
            current_eggs = None
            if not eggs:
                break

            if not self.settings.features.participate_egg_tournaments:
                inventory_tournament_egg = find_inventory_tournament_egg_to_open(
                    eggs,
                    max_merge_slot=self.settings.game.max_merge_slot,
                )
                if inventory_tournament_egg and self._open_egg(
                    _egg_slot(inventory_tournament_egg),
                    int(inventory_tournament_egg["id"]),
                    int(inventory_tournament_egg.get("queue") or 1),
                ):
                    self._collect_open_alert_rewards(_egg_type(inventory_tournament_egg))
                    self.logger.info(
                        "Открыли инвентарное турнирное яйцо %s уровня %s в слоте %s, потому что участие в яйцевом турнире отключено",
                        inventory_tournament_egg["type"],
                        inventory_tournament_egg["level"],
                        inventory_tournament_egg["slot"],
                    )
                    open_count += 1
                    self.sleep_range(self.settings.after_feed_delay_seconds)
                    continue

            current_ts = int(time.time())
            valid_eggs = [
                egg
                for egg in eggs
                if egg.get("id")
                and _egg_slot(egg) in active_slot_set
                and _egg_slot(egg) not in reserved_slots
            ]
            all_available_eggs = [
                egg
                for egg in eggs
                if egg.get("id")
                and _egg_slot(egg) not in reserved_slots
            ]
            occupied_active_slots = {
                _egg_slot(egg)
                for egg in eggs
                if egg.get("id") and _egg_slot(egg) in active_slot_set
            }
            eggs_by_slot = {_egg_slot(egg): egg for egg in valid_eggs}
            queue_eggs = [
                egg
                for egg in eggs
                if egg.get("id") and _egg_slot(egg) not in active_slot_set
            ]
            free_active_slots = sorted(active_slot_set.difference(occupied_active_slots))

            if current_task_payloads and not custom_reward_stop:
                submission = find_custom_task_submission(
                    current_task_payloads,
                    valid_eggs,
                    max_merge_slot=self.settings.game.max_merge_slot,
                    active_slots=active_slot_set,
                )
                if submission:
                    response = self.safe_post(
                        "/tasks/reward/custom",
                        {"code": submission["code"], "slotIds": submission["slot_ids"]},
                    )
                    if response:
                        self.logger.info(
                            "Сдали яйца по турнирной задаче %s (%s) из категории %s, использованы слоты %s",
                            submission["code"],
                            submission["task_type"],
                            submission["category"],
                            submission["slot_ids"],
                        )
                        current_task_payloads = self._fetch_task_categories(include_clan_tasks)
                        current_eggs = None
                        self.sleep_range(self.settings.between_actions_delay_seconds)
                        continue

                    custom_reward_stop = True
                    current_task_payloads = {}
                    self.logger.warning(
                        "Автосдача турнирных яиц остановлена до следующего цикла после ошибки задачи %s.",
                        submission["code"],
                    )

            ready_cooldown_egg = (
                find_ready_cooldown_egg(all_available_eggs, current_ts)
                if self.settings.features.participate_egg_tournaments
                else None
            )
            if ready_cooldown_egg:
                if self._open_egg(
                    _egg_slot(ready_cooldown_egg),
                    int(ready_cooldown_egg["id"]),
                    int(ready_cooldown_egg.get("queue") or 1),
                ):
                    self._collect_open_alert_rewards(_egg_type(ready_cooldown_egg))
                    self.logger.info(
                        "Открыли яйцо с откатом %s в слоте %s",
                        _egg_type(ready_cooldown_egg),
                        _egg_slot(ready_cooldown_egg),
                    )
                    open_count += 1
                    self.sleep_range(self.settings.after_feed_delay_seconds)
                    continue

            activatable_cooldown_egg = (
                find_activatable_cooldown_egg(all_available_eggs)
                if self.settings.features.participate_egg_tournaments
                else None
            )
            if activatable_cooldown_egg:
                if self._open_egg(
                    _egg_slot(activatable_cooldown_egg),
                    int(activatable_cooldown_egg["id"]),
                    int(activatable_cooldown_egg.get("queue") or 1),
                ):
                    self.logger.info(
                        "Поставили яйцо %s в слоте %s на откат",
                        _egg_type(activatable_cooldown_egg),
                        _egg_slot(activatable_cooldown_egg),
                    )
                    open_count += 1
                    self.sleep_range(self.settings.after_feed_delay_seconds)
                    continue

            rejected_pairs: set[tuple[int, int]] = set()
            rejected_slots: set[int] = set()
            merge_succeeded = False
            while True:
                merge_pair = find_merge_pair(
                    valid_eggs,
                    self.settings.game.egg_merge_limits,
                    excluded_slots=rejected_slots,
                )
                if merge_pair is None:
                    break

                base_egg = eggs_by_slot[merge_pair[0]]
                if self._merge_eggs(*merge_pair):
                    self.logger.info(
                        "Объединили яйцо %s уровня %s",
                        base_egg["type"],
                        base_egg["level"],
                    )
                    merge_count += 1
                    merge_succeeded = True
                    if current_task_payloads and not custom_reward_stop:
                        current_task_payloads = self._fetch_task_categories(include_clan_tasks)
                    self.sleep_range(self.settings.after_egg_merge_delay_seconds)
                    break

                rejected_pairs.add(merge_pair)
                rejected_slots.update(merge_pair)
                self.logger.warning(
                    "Пропускаем пару яиц %s уровня %s в слотах %s и %s: сервер отклонил merge, попробуем другую пару в этом цикле.",
                    base_egg["type"],
                    base_egg["level"],
                    merge_pair[0],
                    merge_pair[1],
                )

            if merge_succeeded:
                continue

            level_12_standard = [
                egg
                for egg in valid_eggs
                if _egg_level(egg) == 12 and _egg_type(egg) in {"DUCK", "HEART"}
            ]
            if level_12_standard:
                egg = level_12_standard[0]
                if self._open_egg(_egg_slot(egg), int(egg["id"]), int(egg.get("queue") or 1)):
                    self._collect_open_alert_rewards(_egg_type(egg))
                    self.logger.info("Открыли яйцо %s 12 уровня", egg["type"])
                    open_count += 1
                    self.sleep_range(self.settings.after_feed_delay_seconds)
                    continue

            if queue_eggs and not free_active_slots and not rejected_pairs:
                standard_eggs = [egg for egg in valid_eggs if _egg_type(egg) in {"DUCK", "HEART"}]
                if standard_eggs:
                    sacrificial_egg = min(
                        standard_eggs,
                        key=lambda item: (
                            _egg_type(item) != "HEART",
                            _egg_level(item),
                            -_egg_slot(item),
                        ),
                    )
                    if self._open_egg(
                        _egg_slot(sacrificial_egg),
                        int(sacrificial_egg["id"]),
                        int(sacrificial_egg.get("queue") or 1),
                    ):
                        self._collect_open_alert_rewards(_egg_type(sacrificial_egg))
                        self.logger.info(
                            "Аварийно открыли %s в слоте %s",
                            sacrificial_egg["type"],
                            sacrificial_egg["slot"],
                        )
                        open_count += 1
                        self.sleep_range(self.settings.after_feed_delay_seconds)
                        continue

            pending_cooldown_eggs = (
                find_pending_cooldown_eggs(all_available_eggs, current_ts)
                if self.settings.features.participate_egg_tournaments
                else []
            )
            if pending_cooldown_eggs:
                descriptions = [
                    f"{_egg_type(egg)} слот={_egg_slot(egg)} уровень={_egg_level(egg)} откроется_через={int(egg['tsOpen']) - current_ts}с"
                    for egg in pending_cooldown_eggs[:3]
                ]
                self.logger.info(
                    "Есть яйца с откатом, которые пока рано открывать: %s",
                    descriptions,
                )

            if queue_eggs and not free_active_slots:
                if rejected_pairs:
                    rejected_description = [f"{slot1}-{slot2}" for slot1, slot2 in sorted(rejected_pairs)]
                    self.logger.info(
                        "Дальнейшая обработка очереди остановлена: сервер отклонил merge для пар %s, поэтому аварийное вскрытие обычных яиц в этом цикле отменено. В очереди остается %s яиц.",
                        rejected_description,
                        len(queue_eggs),
                    )
                else:
                    self.logger.info(
                        "Дальнейшая обработка очереди остановлена: все открытые egg-слоты заняты, свободных слотов нет. Открытых слотов=%s, яиц в очереди=%s.",
                        sorted(active_slot_set),
                        len(queue_eggs),
                    )

            break

        if merge_count or open_count:
            self.logger.info(
                "Цикл обработки яиц завершен: %s объединений, %s открытий",
                merge_count,
                open_count,
            )

    def _fetch_task_categories(self, include_clan: bool) -> dict[str, dict[str, Any]]:
        categories = ["PLAYER"]
        if include_clan:
            categories.append("CLAN")

        category_payloads: dict[str, dict[str, Any]] = {}
        for category in categories:
            response = self.safe_post("/tasks", {"category": category})
            if response:
                category_payloads[category] = response
        return category_payloads

    def _merge_eggs(self, slot1: int, slot2: int) -> bool:
        response = self.safe_post("/eggs/merge", {"values": [slot1, slot2], "queue": 1})
        return response is not None

    def _open_egg(self, slot: int, egg_id: int, queue: int) -> bool:
        response = self.safe_post(
            "/eggs/open",
            {"value": slot, "queue": queue, "eggId": egg_id},
        )
        return bool(response and response.get("result") is True)

    def _collect_open_alert_rewards(self, egg_type: str) -> int:
        if egg_type == "HEART" or not self.settings.features.collect_alert_rewards:
            return 0

        alert_payload = self.safe_post("/alert", {})
        alerts = (alert_payload or {}).get("response") or []
        collected_count = 0
        for action in iter_confirmable_alert_actions(alerts):
            response = self.safe_post(action["path"], action["payload"])
            if not response:
                continue
            collected_count += 1
            self.logger.info(
                "Сразу подтвердили алерт после открытия яйца: %s (%s)",
                action["alert_name"],
                action["alert_id"],
            )
            self.sleep_range(self.settings.between_actions_delay_seconds)
        return collected_count
