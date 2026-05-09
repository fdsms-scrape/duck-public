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
        player_name = player.get("name") or player.get("username") or "Неизвестно"
        player_context = PlayerContext(
            player_id=player.get("id"),
            player_name=player_name,
            corn=player.get("corn", 0),
            duck_slots_count=player.get("duckSlotsCount", 0),
            clan_id=player.get("clanId"),
            alerts=alerts,
        )
        self.state_store.update(self.profile.name, player_name=player_name)
        self.logger.info(
            "Игрок %s: corn=%s, слотов уток=%s, алертов=%s",
            player_context.player_name,
            player_context.corn,
            player_context.duck_slots_count,
            len(player_context.alerts),
        )
        return player_context
