"""Координация игрового цикла для одного профиля."""

from __future__ import annotations

import logging
import time

from duckbot.config import AppSettings, ProfileSettings
from duckbot.game.alerts_service import AlertsService
from duckbot.game.clan_show_service import ClanShowService
from duckbot.game.duck_service import DuckService, select_active_ducks
from duckbot.game.egg_service import EggService
from duckbot.game.player_service import PlayerService
from duckbot.game.task_service import TaskService
from duckbot.game.tournament_service import TournamentService
from duckbot.http.api_client import DuckApiClient
from duckbot.storage.runtime_state import RuntimeStateStore


class DuckAutomation:
    """Выполняет один игровой цикл профиля через специализированные сервисы."""

    def __init__(
        self,
        *,
        profile: ProfileSettings,
        settings: AppSettings,
        state_store: RuntimeStateStore,
        api_client: DuckApiClient,
        logger: logging.LoggerAdapter,
        sleep_func=time.sleep,
    ) -> None:
        common_kwargs = {
            "profile": profile,
            "settings": settings,
            "state_store": state_store,
            "api_client": api_client,
            "logger": logger,
            "sleep_func": sleep_func,
        }
        self.settings = settings
        self.player_service = PlayerService(**common_kwargs)
        self.duck_service = DuckService(**common_kwargs)
        self.alerts_service = AlertsService(**common_kwargs)
        self.task_service = TaskService(**common_kwargs)
        self.egg_service = EggService(**common_kwargs)
        self.tournament_service = TournamentService(**common_kwargs)
        self.clan_show_service = ClanShowService(**common_kwargs)
        self.logger = logger

    def run_once(self) -> None:
        player_context = self.player_service.refresh()
        if player_context is None:
            return

        if self.settings.features.collect_alert_rewards:
            self.alerts_service.collect_confirmable_rewards(player_context.alerts)

        ducks = self.duck_service.fetch_ducks()
        if ducks:
            active_ducks = select_active_ducks(ducks, player_context.duck_slots_count)
            self.duck_service.process_active_ducks(active_ducks, player_context)

        task_payloads: dict[str, dict] = {}
        if self.settings.features.collect_task_rewards or self.settings.features.collect_custom_task_rewards:
            task_payloads = self.task_service.fetch_categories(include_clan=player_context.has_clan)

        reserved_slots: set[int] = set()
        eggs_for_followup: list[dict] | None = None

        if task_payloads and self.settings.features.collect_task_rewards:
            self.task_service.collect_standard_rewards(task_payloads)

        if task_payloads and self.settings.features.collect_custom_task_rewards:
            eggs_for_followup = self.egg_service.fetch_eggs()
            reserved_slots = self.task_service.collect_custom_rewards(task_payloads, eggs_for_followup)
            if reserved_slots:
                eggs_for_followup = None
        elif task_payloads:
            custom_candidates = self.task_service.count_custom_reward_candidates(task_payloads)
            if custom_candidates:
                self.logger.info(
                    "Найдены кастомные турнирные награды (%s), но их автосбор отключен в конфиге.",
                    custom_candidates,
                )

        if self.settings.features.process_eggs:
            self.egg_service.process(initial_eggs=eggs_for_followup, reserved_slots=reserved_slots)

        tournament_context = None
        if self.settings.features.inspect_tournaments or self.settings.features.inspect_clan_show:
            tournament_context = self.tournament_service.inspect()

        if self.settings.features.inspect_clan_show:
            self.clan_show_service.inspect(player_context, tournament_context)
