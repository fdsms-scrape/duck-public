"""Обработка, объединение и открытие яиц."""

from __future__ import annotations

import time
from typing import Any

from duckbot.game.base import GameService


def find_merge_pair(eggs: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Ищет пару одинаковых яиц для объединения."""
    seen: dict[tuple[str, int], int] = {}
    for egg in sorted(
        eggs,
        key=lambda item: (-int(item.get("level", 0)), str(item.get("type") or ""), int(item.get("slot", 0))),
    ):
        key = (str(egg.get("type") or ""), int(egg.get("level", 0)))
        slot = int(egg.get("slot", 0))
        if key in seen:
            return seen[key], slot
        seen[key] = slot
    return None


class EggService(GameService):
    """Управляет merge/open логикой яиц на активном поле."""

    def fetch_eggs(self) -> list[dict[str, Any]]:
        response = self.safe_post("/eggs")
        return (response or {}).get("response", [])

    def process(self, *, initial_eggs: list[dict[str, Any]] | None = None, reserved_slots: set[int] | None = None) -> None:
        reserved_slots = reserved_slots or set()
        merge_count = 0
        open_count = 0
        current_eggs = initial_eggs

        if reserved_slots:
            self.logger.info("Зарезервированы слоты яиц, которые нельзя трогать в этом цикле: %s", sorted(reserved_slots))

        while True:
            eggs = current_eggs if current_eggs is not None else self.fetch_eggs()
            current_eggs = None
            if not eggs:
                break

            current_ts = int(time.time())
            valid_eggs = [
                egg
                for egg in eggs
                if egg.get("id")
                and 1 <= int(egg.get("slot", 0)) <= self.settings.game.max_merge_slot
                and int(egg.get("slot", 0)) not in reserved_slots
            ]
            eggs_by_slot = {int(egg["slot"]): egg for egg in valid_eggs}

            ready_repeatable = [
                egg
                for egg in valid_eggs
                if "REPEATABLE" in str(egg.get("type") or "")
                and (egg.get("tsOpen") is None or current_ts >= int(egg["tsOpen"]))
            ]
            if ready_repeatable:
                egg = ready_repeatable[0]
                if self._open_egg(int(egg["slot"]), int(egg["id"]), int(egg.get("queue") or 1)):
                    self.logger.info("Открыли повторяемое яйцо в слоте %s", egg["slot"])
                    open_count += 1
                    self.sleep_range(self.settings.after_feed_delay_seconds)
                    continue

            merge_pair = find_merge_pair(valid_eggs)
            if merge_pair and self._merge_eggs(*merge_pair):
                base_egg = eggs_by_slot[merge_pair[0]]
                self.logger.info(
                    "Объединили яйцо %s уровня %s",
                    base_egg["type"],
                    base_egg["level"],
                )
                merge_count += 1
                self.sleep_range(self.settings.between_actions_delay_seconds)
                continue

            level_12_standard = [
                egg
                for egg in valid_eggs
                if int(egg.get("level", 0)) == 12 and egg.get("type") in {"DUCK", "HEART"}
            ]
            if level_12_standard:
                egg = level_12_standard[0]
                if self._open_egg(int(egg["slot"]), int(egg["id"]), int(egg.get("queue") or 1)):
                    self.logger.info("Открыли яйцо %s 12 уровня", egg["type"])
                    open_count += 1
                    self.sleep_range(self.settings.after_feed_delay_seconds)
                    continue

            if len(valid_eggs) >= self.settings.game.max_merge_slot:
                standard_eggs = [egg for egg in valid_eggs if egg.get("type") in {"DUCK", "HEART"}]
                if standard_eggs:
                    sacrificial_egg = min(
                        standard_eggs,
                        key=lambda item: (
                            int(item.get("level", 0)),
                            item.get("type") != "DUCK",
                            -int(item.get("slot", 0)),
                        ),
                    )
                    if self._open_egg(
                        int(sacrificial_egg["slot"]),
                        int(sacrificial_egg["id"]),
                        int(sacrificial_egg.get("queue") or 1),
                    ):
                        self.logger.info(
                            "Аварийно открыли %s в слоте %s",
                            sacrificial_egg["type"],
                            sacrificial_egg["slot"],
                        )
                        open_count += 1
                        self.sleep_range(self.settings.after_feed_delay_seconds)
                        continue

            break

        if merge_count or open_count:
            self.logger.info(
                "Цикл обработки яиц завершен: %s объединений, %s открытий",
                merge_count,
                open_count,
            )

    def _merge_eggs(self, slot1: int, slot2: int) -> bool:
        response = self.safe_post("/eggs/merge", {"values": [slot1, slot2], "queue": 1})
        return response is not None

    def _open_egg(self, slot: int, egg_id: int, queue: int) -> bool:
        response = self.safe_post(
            "/eggs/open",
            {"value": slot, "queue": queue, "eggId": egg_id},
        )
        return bool(response and response.get("result") is True)
