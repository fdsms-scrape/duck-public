"""Анализ активных турниров и их контекста."""

from __future__ import annotations

from typing import Any

from duckbot.game.base import GameService
from duckbot.game.models import ClanShowTournamentContext


def count_uncollected_reward_pass_steps(tournament: dict[str, Any]) -> int:
    """Считает количество несобранных шагов reward pass."""
    total = 0
    for reward_pass in tournament.get("rewardPasses") or []:
        for step in reward_pass.get("steps") or []:
            if step.get("isCollected") is False:
                total += 1
    return total


class TournamentService(GameService):
    """Читает активные турниры и вытаскивает контекст Clan Show."""

    def inspect(self) -> ClanShowTournamentContext | None:
        response = self.safe_post("/tournaments", {})
        tournaments = (response or {}).get("response", [])
        if not tournaments:
            self.logger.info("Активные турниры не найдены.")
            return None

        active_codes = [str(item.get("code")) for item in tournaments if item.get("isParticipant")]
        self.logger.info("Активные участия в турнирах: %s", active_codes or ["нет"])

        for tournament in tournaments:
            if tournament.get("code") != "clanShow" or not tournament.get("isParticipant"):
                continue
            group = tournament.get("group") or {}
            context = ClanShowTournamentContext(
                tournament_group_id=int(group["id"]),
                group_name=group.get("name"),
                league_level=group.get("leagueLevel"),
            )
            self.logger.info(
                "Clan Show активен: группа=%s, лига=%s, несобранных шагов пропуска=%s",
                context.group_name or context.tournament_group_id,
                context.league_level,
                count_uncollected_reward_pass_steps(tournament),
            )
            return context

        return None
