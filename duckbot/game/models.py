"""Структуры данных игрового слоя."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PlayerContext:
    """Снимок состояния игрока на текущий цикл."""

    player_id: int | None
    player_name: str
    corn: int
    duck_slots_count: int
    clan_id: int | None
    alerts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_clan(self) -> bool:
        return self.clan_id is not None


@dataclass(slots=True)
class ClanShowTournamentContext:
    """Минимальный контекст активного Clan Show."""

    tournament_group_id: int
    group_name: str | None = None
    league_level: int | None = None
