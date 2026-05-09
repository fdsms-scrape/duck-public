"""Аналитика и сопровождение механики Clan Show."""

from __future__ import annotations

from typing import Any

from duckbot.game.base import GameService
from duckbot.game.models import ClanShowTournamentContext, PlayerContext


def rank_clan_show_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Сортирует цели по шансу успеха, риску мести и остаточному HP."""
    return sorted(
        targets,
        key=lambda target: (
            -float(((target.get("sabotageChance") or {}).get("successChance") or 0.0)),
            float(((target.get("revengeAbilityChance") or {}).get("chance") or 0.0)),
            float(((target.get("hp") or {}).get("currentHp") or 0.0)),
            int(((target.get("showRating") or {}).get("place") or 10**9)),
        ),
    )


class ClanShowService(GameService):
    """Собирает контекст саботажей и топ-целей для Clan Show."""

    def inspect(self, player_context: PlayerContext, tournament_context: ClanShowTournamentContext | None) -> None:
        if not player_context.has_clan or tournament_context is None:
            return

        payload = {
            "clanId": player_context.clan_id,
            "tournamentGroupId": tournament_context.tournament_group_id,
        }
        sabotages_response = self.safe_post("/clans/show/sabotages", payload)
        best_targets_response = self.safe_post(
            "/clans/show/sabotage/best-targets",
            {
                **payload,
                "scope": [
                    "hp",
                    "sabotageChance",
                    "revengeAbilityChance",
                    "showRating",
                    "sabotageBadges",
                    "showSameGroup",
                    "war",
                ],
            },
        )
        attacks_response = self.safe_post("/clans/show/sabotage/attacks", payload)
        if not sabotages_response or not best_targets_response or not attacks_response:
            return

        sabotages_payload = sabotages_response.get("response") or {}
        sabotages = sabotages_payload.get("sabotages") or []
        empty_slots = sabotages_payload.get("empty") or []
        best_targets = rank_clan_show_targets((best_targets_response.get("response") or []))
        recent_attacks = attacks_response.get("response") or []

        target_preview = [
            (
                f"{target.get('name')}#{target.get('id')}"
                f" шанс={((target.get('sabotageChance') or {}).get('successChance') or 0.0):.0%}"
                f" месть={((target.get('revengeAbilityChance') or {}).get('chance') or 0.0):.0%}"
                f" hp={((target.get('hp') or {}).get('currentHp') or 0)}/{((target.get('hp') or {}).get('maxHp') or 0)}"
            )
            for target in best_targets[: self.settings.game.clan_show_log_best_targets_limit]
        ]

        self.logger.info(
            "Clan Show: саботажей=%s, пустых слотов=%s, лучших целей=%s",
            len(sabotages),
            len(empty_slots),
            target_preview or ["нет"],
        )
        if recent_attacks:
            self.logger.info(
                "Clan Show: недавних атак по группе=%s, показываем %s последних.",
                len(recent_attacks),
                min(len(recent_attacks), self.settings.game.clan_show_log_recent_attacks_limit),
            )
