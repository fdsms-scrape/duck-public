"""Кормление, разведение и выбор активных уток."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from duckbot.config import BreedRuleSettings, FeedRuleSettings
from duckbot.game.base import GameService
from duckbot.game.models import PlayerContext

ACTIONABLE_DUCK_STATES = frozenset({"FEED", "BREED", "BREEDING"})


def count_duck_states(ducks: list[dict[str, Any]]) -> dict[str, int]:
    """Считает количество уток по состояниям."""
    return dict(Counter(str(duck.get("state") or "UNKNOWN") for duck in ducks))


def select_active_ducks(ducks: list[dict[str, Any]], duck_slots_count: int) -> list[dict[str, Any]]:
    """Берет первые доступные игровые слоты после исключения стейкинга и прочих неактивных состояний."""
    if duck_slots_count <= 0:
        return []
    return [duck for duck in ducks if duck.get("state") in ACTIONABLE_DUCK_STATES][:duck_slots_count]


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

    def process_active_ducks(self, ducks: list[dict[str, Any]], player_context: PlayerContext) -> None:
        if not ducks:
            self.logger.info("Активные утки для обработки не найдены.")
            return

        self.logger.info(
            "В работу взято %s активных уток из %s доступных слотов.",
            len(ducks),
            player_context.duck_slots_count,
        )
        for duck in ducks:
            self._process_duck(duck, player_context)
            self.sleep_range(self.settings.between_actions_delay_seconds)

    def _process_duck(self, duck: dict[str, Any], player_context: PlayerContext) -> None:
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
            return

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
                return

            limit = feed_rule.max_cost

            while feed_count < len(feed_costs):
                cost = feed_costs[feed_count]
                if cost > limit or player_context.corn < cost:
                    break

                response = self.safe_post(
                    "/ducks/feed",
                    {"id": duck_id, "timestamps": [int(time.time())]},
                )
                if not response:
                    break

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
            return

        if state == "BREED":
            breed_rule = resolve_breed_rule(duck, self.settings.game.breed_rules)
            if breed_rule is None:
                self.logger.info(
                    "Пропустили скрещивание утки %s: редкость=%s, уровень=%s не подходят под правила.",
                    duck_id,
                    rarity,
                    level,
                )
                return

            pay_response = self.safe_post(
                "/ducks/breed/pay",
                {"id": duck_id, "currency": breed_rule.currency},
            )
            if pay_response:
                self.logger.info(
                    "Отправили утку %s на скрещивание по правилу %s [%s-%s], валюта=%s",
                    duck_id,
                    breed_rule.quality,
                    breed_rule.min_level,
                    breed_rule.max_level if breed_rule.max_level is not None else "∞",
                    breed_rule.currency,
                )
                self.safe_post("/ducks/breed/search", {"id": duck_id})
