"""Аналитика и применение саботажей в Clan Show."""

from __future__ import annotations

from typing import Any

import requests

from duckbot.exceptions import ApiError, ApiResponseError
from duckbot.game.base import GameService
from duckbot.game.models import ClanShowTournamentContext, PlayerContext
from duckbot.masking import sanitize_value


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


def summarize_sabotage_attacks(sabotage: dict[str, Any]) -> str:
    """Строит короткое описание эффектов саботажа для логов."""
    parts: list[str] = []
    for attack in sabotage.get("attacks") or []:
        attack_type = str(attack.get("type") or "").strip()
        value = attack.get("value")
        if not attack_type:
            continue
        parts.append(f"{attack_type}={value}")
    return ", ".join(parts) or "без эффектов"


def describe_clan_show_target(target: dict[str, Any]) -> str:
    """Возвращает человекочитаемую строку цели Clan Show."""
    return (
        f"{target.get('name')}#{target.get('id')}"
        f" шанс={((target.get('sabotageChance') or {}).get('successChance') or 0.0):.0%}"
        f" месть={((target.get('revengeAbilityChance') or {}).get('chance') or 0.0):.0%}"
        f" hp={((target.get('hp') or {}).get('currentHp') or 0)}/{((target.get('hp') or {}).get('maxHp') or 0)}"
    )


def select_clan_show_targets(
    targets: list[dict[str, Any]],
    *,
    own_clan_id: int | None,
    min_success_chance: float,
    max_revenge_chance: float,
    require_same_group: bool,
) -> list[dict[str, Any]]:
    """Фильтрует и сортирует цели, пригодные для автоматической атаки."""
    eligible_targets: list[dict[str, Any]] = []

    for target in rank_clan_show_targets(targets):
        target_id = target.get("id")
        if target_id is None or target_id == own_clan_id:
            continue

        if str(target.get("state") or "").upper() != "ACTIVE":
            continue

        if require_same_group and not bool(target.get("showSameGroup")):
            continue

        success_chance = float(((target.get("sabotageChance") or {}).get("successChance") or 0.0))
        revenge_chance = float(((target.get("revengeAbilityChance") or {}).get("chance") or 0.0))
        current_hp = int(((target.get("hp") or {}).get("currentHp") or 0))

        if current_hp <= 0:
            continue
        if success_chance < min_success_chance:
            continue
        if revenge_chance > max_revenge_chance:
            continue

        eligible_targets.append(target)

    return eligible_targets


class ClanShowService(GameService):
    """Собирает контекст Clan Show и при необходимости отправляет саботажи."""

    def inspect(self, player_context: PlayerContext, tournament_context: ClanShowTournamentContext | None) -> None:
        if not player_context.has_clan or tournament_context is None:
            return

        payload = {
            "clanId": player_context.clan_id,
            "tournamentGroupId": tournament_context.tournament_group_id,
        }
        snapshot = self._fetch_snapshot(payload)
        if snapshot is None:
            return

        sabotages, empty_slots, best_targets, recent_attacks = snapshot
        target_preview = [
            describe_clan_show_target(target)
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

        if self.settings.features.use_clan_show_sabotages:
            self._use_sabotages(
                payload=payload,
                own_clan_id=player_context.clan_id,
                sabotages=sabotages,
                best_targets=best_targets,
            )

    def _fetch_snapshot(
        self,
        payload: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
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
            return None

        sabotages_payload = sabotages_response.get("response") or {}
        sabotages = list(sabotages_payload.get("sabotages") or [])
        empty_slots = list(sabotages_payload.get("empty") or [])
        best_targets = rank_clan_show_targets(list(best_targets_response.get("response") or []))
        recent_attacks = list(attacks_response.get("response") or [])
        return sabotages, empty_slots, best_targets, recent_attacks

    def _use_sabotages(
        self,
        *,
        payload: dict[str, Any],
        own_clan_id: int | None,
        sabotages: list[dict[str, Any]],
        best_targets: list[dict[str, Any]],
    ) -> int:
        if not sabotages:
            self.logger.info("Clan Show: активных саботажей для атаки нет.")
            return 0

        settings = self.settings.game
        used_sabotage_ids: set[int] = set()
        used_count = 0
        current_sabotages = list(sabotages)
        current_targets = list(best_targets)

        while used_count < settings.clan_show_attack_limit_per_cycle:
            available_sabotages = [
                sabotage
                for sabotage in current_sabotages
                if self._get_int(sabotage.get("id")) not in used_sabotage_ids
            ]
            if not available_sabotages:
                break

            eligible_targets = select_clan_show_targets(
                current_targets,
                own_clan_id=own_clan_id,
                min_success_chance=settings.clan_show_attack_min_success_chance,
                max_revenge_chance=settings.clan_show_attack_max_revenge_chance,
                require_same_group=settings.clan_show_attack_require_same_group,
            )
            if not eligible_targets:
                if used_count == 0:
                    self.logger.info(
                        "Clan Show: нет целей, подходящих под автоатаку. Требования: шанс >= %.0f%%, месть <= %.0f%%, same_group=%s.",
                        settings.clan_show_attack_min_success_chance,
                        settings.clan_show_attack_max_revenge_chance,
                        settings.clan_show_attack_require_same_group,
                    )
                break

            sabotage = available_sabotages[0]
            if not self._use_single_sabotage(sabotage, eligible_targets[0]):
                break

            sabotage_id = self._get_int(sabotage.get("id"))
            if sabotage_id is not None:
                used_sabotage_ids.add(sabotage_id)
            used_count += 1

            if used_count >= settings.clan_show_attack_limit_per_cycle:
                break

            self.sleep_range(self.settings.between_actions_delay_seconds)

            if not settings.clan_show_attack_refresh_targets_each_use:
                current_sabotages = available_sabotages[1:]
                continue

            refreshed_snapshot = self._fetch_snapshot(payload)
            if refreshed_snapshot is None:
                break
            current_sabotages, _empty_slots, current_targets, _recent_attacks = refreshed_snapshot

        if used_count:
            self.logger.info("Clan Show: автоатака завершена, использовано саботажей=%s.", used_count)
        return used_count

    def _use_single_sabotage(self, sabotage: dict[str, Any], target: dict[str, Any]) -> bool:
        sabotage_id = self._get_int(sabotage.get("id"))
        target_id = self._get_int(target.get("id"))
        if sabotage_id is None or target_id is None:
            return False

        try:
            self._post_once("/clans/show/sabotage/use", {"sabotageId": sabotage_id, "targetId": target_id})
        except ApiError as exc:
            self.logger.warning(
                "Clan Show: не удалось отправить саботаж %s по цели %s: %s",
                sabotage_id,
                describe_clan_show_target(target),
                exc,
            )
            return False

        self.logger.info(
            "Clan Show: отправили саботаж %s редкости %s (%s) по цели %s",
            sabotage_id,
            sabotage.get("rarity") or "UNKNOWN",
            summarize_sabotage_attacks(sabotage),
            describe_clan_show_target(target),
        )
        return True

    def _post_once(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request_url = f"{self.api_client.api_base_url}{path}"
        auth_retry_available = True

        while True:
            auth_session = self.api_client.auth_manager.ensure_auth()
            headers = self.api_client.header_builder.build(auth_session.token)

            try:
                response = self.api_client.session.request(
                    "POST",
                    request_url,
                    headers=headers,
                    json=payload,
                    timeout=self.api_client.timeout_seconds,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                raise ApiError(f"Сетевая ошибка при запросе {path}: {exc}") from exc
            except requests.RequestException as exc:
                raise ApiError(f"Ошибка HTTP-клиента при запросе {path}: {exc}") from exc

            if response.status_code == 401 and auth_retry_available:
                self.api_client.auth_manager.ensure_auth(force_refresh=True)
                auth_retry_available = False
                continue

            try:
                data = response.json()
            except ValueError as exc:
                raise ApiResponseError(
                    f"API {path} вернул невалидный JSON.",
                    status_code=response.status_code,
                    response_body=sanitize_value(response.text),
                ) from exc

            if not isinstance(data, dict):
                raise ApiResponseError(
                    f"API {path} вернул неожиданную структуру JSON.",
                    status_code=response.status_code,
                    response_body=sanitize_value(str(data)),
                )

            if not response.ok or data.get("result") is False:
                message = data.get("error") or data.get("message") or response.text
                raise ApiResponseError(
                    f"Запрос к API {path} завершился ошибкой: {sanitize_value(str(message))}",
                    error_code=str(data.get("error")) if data.get("error") else None,
                    status_code=response.status_code,
                    response_body=sanitize_value(response.text),
                )

            return data

    @staticmethod
    def _get_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
