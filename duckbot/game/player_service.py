"""Получение и нормализация состояния игрока."""

from __future__ import annotations

from duckbot.game.base import GameService
from duckbot.game.models import PlayerContext


class PlayerService(GameService):
    """Обновляет контекст игрока и сохраняет полезный runtime-кэш."""

    def refresh(self) -> PlayerContext | None:
        data = self.safe_post("/player/me")
        if not data:
            return None

        response = data.get("response") or {}
        player = response.get("player") or {}
        alerts = data.get("alerts") or []
        raw_egg_slots = player.get("eggSlots") or []
        egg_slots: list[int] = []
        for slot in raw_egg_slots:
            try:
                normalized_slot = int(slot)
            except (TypeError, ValueError):
                continue
            egg_slots.append(normalized_slot)
        egg_slots = sorted(set(egg_slots))
        player_name = player.get("name") or player.get("username") or "Неизвестно"
        player_context = PlayerContext(
            player_id=player.get("id"),
            player_name=player_name,
            corn=player.get("corn", 0),
            duck_slots_count=player.get("duckSlotsCount", 0),
            clan_id=player.get("clanId"),
            egg_slots=egg_slots,
            alerts=alerts,
        )
        self.state_store.update(self.profile.name, player_name=player_name)
        self.logger.info(
            "Игрок %s: corn=%s, слотов уток=%s, открытых egg-слотов=%s, алертов=%s",
            player_context.player_name,
            player_context.corn,
            player_context.duck_slots_count,
            len(player_context.egg_slots),
            len(player_context.alerts),
        )
        return player_context
