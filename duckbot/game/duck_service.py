"""Кормление, разведение и выбор активных уток."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Mapping
from typing import Any

from duckbot.config import BreedRuleSettings, FeedRuleSettings
from duckbot.exceptions import ApiError, ApiResponseError
from duckbot.game.base import GameService
from duckbot.game.models import PlayerContext

ACTIONABLE_DUCK_STATES = frozenset({"FEED", "BREED", "BREEDING"})


def count_duck_states(ducks: list[dict[str, Any]]) -> dict[str, int]:
    """Считает количество уток по состояниям."""
    return dict(Counter(str(duck.get("state") or "UNKNOWN") for duck in ducks))


def select_active_ducks(
    ducks: list[dict[str, Any]],
    duck_slots_count: int | None = None,
) -> list[dict[str, Any]]:
    """Возвращает активное окно уток для текущего экрана по порядку ответа сервера.

    Сервер может возвращать длинную очередь уток со статусом FEED, но реально доступными
    для действий оказываются только первые `duckSlotsCount` уток из активного окна.
    Утки в STAKE в это окно не попадают, поэтому сначала фильтруем по состояниям, а уже
    потом ограничиваем список длиной видимого окна.
    """
    actionable_ducks = [duck for duck in ducks if duck.get("state") in ACTIONABLE_DUCK_STATES]
    if duck_slots_count is None or duck_slots_count <= 0:
        return actionable_ducks
    return actionable_ducks[:duck_slots_count]


def resolve_breed_rule(duck: dict[str, Any], breed_rules: list[BreedRuleSettings]) -> BreedRuleSettings | None:
    """Подбирает первое подходящее правило скрещивания для утки."""
    rarity = str(duck.get("quality") or "").upper()
    level = int(duck.get("level") or 0)
    if level < 1:
        return None

    for rule in breed_rules:
        if not rule.enabled:
            continue
        if rule.quality != rarity:
            continue
        if level < rule.min_level:
            continue
        if rule.max_level is not None and level > rule.max_level:
            continue
        return rule

    return None


def resolve_breed_cost(duck: dict[str, Any], currency: str) -> int | None:
    """Возвращает стоимость скрещивания в нужной валюте, если сервер прислал ее в данных утки."""
    for field_name in ("breedingPrice", "breedPrice", "breedCost", "price"):
        cost = _extract_currency_amount(duck.get(field_name), currency)
        if cost is not None:
            return cost
    return None


def resolve_feed_rule(duck: dict[str, Any], feed_rules: list[FeedRuleSettings]) -> FeedRuleSettings | None:
    """Подбирает первое подходящее правило кормления для утки."""
    rarity = str(duck.get("quality") or "").upper()
    level = int(duck.get("level") or 0)
    if level < 1:
        return None

    for rule in feed_rules:
        if not rule.enabled:
            continue
        if rule.quality != rarity:
            continue
        if level < rule.min_level:
            continue
        if rule.max_level is not None and level > rule.max_level:
            continue
        return rule

    return None


def _extract_currency_amount(raw_value: Any, currency: str) -> int | None:
    """Извлекает сумму из числа или объекта вида {"corn": 6000}."""
    if isinstance(raw_value, bool):
        return None

    if isinstance(raw_value, int):
        return raw_value if raw_value >= 0 else None

    if isinstance(raw_value, float):
        amount = int(raw_value)
        return amount if amount >= 0 else None

    if not isinstance(raw_value, Mapping):
        return None

    currency_value = raw_value.get(currency)
    if isinstance(currency_value, bool):
        return None
    if isinstance(currency_value, int):
        return currency_value if currency_value >= 0 else None
    if isinstance(currency_value, float):
        amount = int(currency_value)
        return amount if amount >= 0 else None

    value = raw_value.get("value")
    raw_currency = raw_value.get("currency")
    if raw_currency is not None and str(raw_currency).strip().lower() != currency:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        amount = int(value)
        return amount if amount >= 0 else None

    return None


class DuckService(GameService):
    """Управляет циклом кормления и разведения уток."""

    def fetch_ducks(self) -> list[dict[str, Any]]:
        response = self.safe_post("/ducks")
        ducks = (response or {}).get("response", [])
        if ducks:
            self.logger.info(
                "Получили %s уток, распределение состояний=%s",
                len(ducks),
                count_duck_states(ducks),
            )
        return ducks

    def process_active_ducks(
        self,
        ducks: list[dict[str, Any]],
        player_context: PlayerContext,
        *,
        total_actionable_count: int | None = None,
    ) -> None:
        if not ducks:
            self.logger.info("Активные утки для обработки не найдены.")
            return

        self.logger.info(
            "В работу взято %s уток из активного окна. Серверный duckSlotsCount=%s, всего actionable-уток в ответе=%s.",
            len(ducks),
            player_context.duck_slots_count,
            total_actionable_count if total_actionable_count is not None else len(ducks),
        )
        for index, duck in enumerate(ducks):
            should_continue = self._process_duck(duck, player_context)
            if not should_continue:
                remaining = len(ducks) - index - 1
                self.logger.info(
                    "Сервер закрыл оставшиеся слоты кормления. Прерываем обработку хвоста списка, пропускаем %s уток до следующего цикла.",
                    remaining,
                )
                break
            self.sleep_range(self.settings.between_actions_delay_seconds)

    def _process_duck(self, duck: dict[str, Any], player_context: PlayerContext) -> bool:
        duck_id = duck.get("id")
        state = duck.get("state")
        rarity = duck.get("quality", "COMMON")
        level = int(duck.get("level") or 0)

        if state == "BREEDING":
            breeding_id = duck.get("breedingId")
            if breeding_id:
                response = self.safe_post("/ducks/breed/eggs/collect", {"id": breeding_id})
                if response:
                    self.logger.info("Собрали яйца для утки %s", duck_id)
            return True

        if state == "FEED":
            feed_costs = duck.get("feedCost", [])
            feed_count = duck.get("feedCount", 0)
            feed_rule = resolve_feed_rule(duck, self.settings.game.feed_rules)
            if feed_rule is None:
                self.logger.info(
                    "Пропустили кормление утки %s: редкость=%s, уровень=%s не подходят под правила.",
                    duck_id,
                    rarity,
                    level,
                )
                return True

            limit = feed_rule.max_cost

            while feed_count < len(feed_costs):
                cost = feed_costs[feed_count]
                if cost > limit or player_context.corn < cost:
                    break

                response, stop_reason = self._feed_duck_once(duck_id)
                if stop_reason:
                    self.logger.info(
                        "Остановили кормление утки %s: сервер сменил состояние или слот стал недоступен (%s).",
                        duck_id,
                        stop_reason,
                    )
                    return stop_reason != "error_slot_not_available"
                if not response:
                    return True

                player_context.corn -= cost
                feed_count += 1
                self.logger.info(
                    "Покормили утку %s редкости %s (%s/%s), стоимость шага=%s corn, остаток=%s corn",
                    duck_id,
                    rarity,
                    feed_count,
                    len(feed_costs),
                    cost,
                    player_context.corn,
                )
                self.sleep_range(self.settings.after_feed_delay_seconds)
            return True

        if state == "BREED":
            breed_rule = resolve_breed_rule(duck, self.settings.game.breed_rules)
            if breed_rule is None:
                self.logger.info(
                    "Пропустили скрещивание утки %s: редкость=%s, уровень=%s не подходят под правила.",
                    duck_id,
                    rarity,
                    level,
                )
                return True

            breed_cost = resolve_breed_cost(duck, breed_rule.currency)
            if breed_rule.currency == "corn" and breed_cost is not None and player_context.corn < breed_cost:
                self.logger.info(
                    "Пропустили скрещивание утки %s: нужно %s corn, доступно %s corn.",
                    duck_id,
                    breed_cost,
                    player_context.corn,
                )
                return True

            pay_response, stop_reason = self._breed_duck_once(duck_id, breed_rule.currency)
            if stop_reason == "MONEY":
                self._refresh_player_corn(player_context)
                if breed_rule.currency == "corn":
                    if breed_cost is not None:
                        self.logger.info(
                            "Пропустили скрещивание утки %s: сервер вернул MONEY, нужно %s corn, доступно %s corn.",
                            duck_id,
                            breed_cost,
                            player_context.corn,
                        )
                    else:
                        self.logger.info(
                            "Пропустили скрещивание утки %s: сервер вернул MONEY, доступно %s corn.",
                            duck_id,
                            player_context.corn,
                        )
                else:
                    self.logger.info(
                        "Пропустили скрещивание утки %s: сервер вернул MONEY для валюты %s.",
                        duck_id,
                        breed_rule.currency,
                    )
                return True

            if stop_reason:
                self.logger.info(
                    "Остановили скрещивание утки %s: сервер сменил состояние (%s).",
                    duck_id,
                    stop_reason,
                )
                return True

            if pay_response:
                if breed_rule.currency == "corn":
                    if breed_cost is not None:
                        player_context.corn = max(player_context.corn - breed_cost, 0)
                    else:
                        self._refresh_player_corn(player_context)
                self.logger.info(
                    "Отправили утку %s на скрещивание по правилу %s [%s-%s], валюта=%s",
                    duck_id,
                    breed_rule.quality,
                    breed_rule.min_level,
                    breed_rule.max_level if breed_rule.max_level is not None else "∞",
                    breed_rule.currency,
                )
                self.safe_post("/ducks/breed/search", {"id": duck_id})
            return True

        return True

    def _breed_duck_once(
        self,
        duck_id: int | None,
        currency: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        try:
            response = self.api_client.post(
                "/ducks/breed/pay",
                {"id": duck_id, "currency": currency},
            )
            return response, None
        except ApiResponseError as exc:
            if exc.error_code in {"MONEY", "error_duck_bad_state", "error_slot_not_available"}:
                return None, exc.error_code
            self.logger.error("Вызов /ducks/breed/pay завершился ошибкой: %s", exc)
            return None, None
        except ApiError as exc:
            self.logger.error("Вызов /ducks/breed/pay завершился ошибкой: %s", exc)
            return None, None

    def _refresh_player_corn(self, player_context: PlayerContext) -> int | None:
        player_data = self.safe_post("/player/me")
        if not player_data:
            return None

        response = player_data.get("response")
        if not isinstance(response, Mapping):
            return None

        player = response.get("player")
        if not isinstance(player, Mapping):
            return None

        corn = player.get("corn")
        if isinstance(corn, bool) or not isinstance(corn, (int, float)):
            return None

        player_context.corn = int(corn)
        return player_context.corn

    def _feed_duck_once(self, duck_id: int | None) -> tuple[dict[str, Any] | None, str | None]:
        try:
            response = self.api_client.post(
                "/ducks/feed",
                {"id": duck_id, "timestamps": [int(time.time())]},
            )
            return response, None
        except ApiResponseError as exc:
            if exc.error_code in {"error_duck_bad_state", "error_slot_not_available"}:
                return None, exc.error_code
            self.logger.error("Вызов /ducks/feed завершился ошибкой: %s", exc)
            return None, None
        except ApiError as exc:
            self.logger.error("Вызов /ducks/feed завершился ошибкой: %s", exc)
            return None, None
