"""Высокоуровневая оркестрация профилей и рабочего цикла."""

from __future__ import annotations

import logging
import random
import time
from typing import Iterable

import requests

from duckbot.config import ProfileSettings, ProjectSettings
from duckbot.exceptions import ConfigurationError
from duckbot.game.automation import DuckAutomation
from duckbot.http.api_client import DuckApiClient
from duckbot.http.auth_manager import AuthManager
from duckbot.http.header_builder import HeaderBuilder
from duckbot.storage.runtime_state import RuntimeStateStore


class DuckBotRunner:
    """Запускает команды для одного или нескольких профилей."""

    def __init__(
        self,
        settings: ProjectSettings,
        *,
        sleep_func=time.sleep,
    ) -> None:
        self.settings = settings
        self.state_store = RuntimeStateStore(settings.app.auth.state_path)
        self.sleep = sleep_func
        self.logger = logging.getLogger(__name__)

    def auth_check(self, profiles: Iterable[ProfileSettings]) -> None:
        for profile in profiles:
            try:
                with self._build_profile_stack(profile) as stack:
                    auth_session = stack["auth_manager"].ensure_auth(force_refresh=True)
                    player_data = stack["api_client"].post("/player/me")
                    player = (player_data.get("response") or {}).get("player", {})
                    player_name = (
                        player.get("name")
                        or player.get("username")
                        or auth_session.player_name
                        or "Неизвестно"
                    )
                    stack["logger"].info(
                        "Проверка авторизации прошла успешно для игрока %s (id=%s)",
                        player_name,
                        player.get("id") or auth_session.player_id,
                    )
            except Exception as exc:
                self.logger.error(
                    "Проверка авторизации профиля %s завершилась ошибкой: %s",
                    profile.name,
                    exc,
                    extra={"profile": profile.name},
                )
                raise

    def run_once(self, profiles: Iterable[ProfileSettings]) -> None:
        selected_profiles = list(profiles)
        for index, profile in enumerate(selected_profiles):
            try:
                with self._build_profile_stack(profile) as stack:
                    stack["logger"].info("Начинаем цикл профиля")
                    automation = DuckAutomation(
                        profile=profile,
                        settings=self.settings.app,
                        state_store=self.state_store,
                        api_client=stack["api_client"],
                        logger=stack["logger"],
                        sleep_func=self.sleep,
                    )
                    automation.run_once()
                    stack["logger"].info("Цикл профиля завершен")
            except Exception as exc:
                self.logger.exception(
                    "Профиль %s завершился ошибкой, остальные профили продолжат работу: %s",
                    profile.name,
                    exc,
                    extra={"profile": profile.name},
                )

            if index < len(selected_profiles) - 1:
                self._sleep_between_profiles()

    def run_forever(self, profiles: Iterable[ProfileSettings]) -> None:
        selected_profiles = list(profiles)
        while True:
            self.run_once(selected_profiles)
            self.logger.info(
                "Глобальный цикл завершен. Пауза %s секунд.",
                self.settings.app.cycle_sleep_seconds,
                extra={"profile": "-"},
            )
            self.sleep(self.settings.app.cycle_sleep_seconds)

    def resolve_profiles(
        self,
        *,
        profile_name: str | None = None,
        all_profiles: bool = False,
    ) -> list[ProfileSettings]:
        if profile_name:
            profile = self.settings.get_profile(profile_name)
            if not profile.enabled:
                self.logger.warning(
                    "Профиль %s отключен, но был выбран явно.",
                    profile.name,
                    extra={"profile": profile.name},
                )
            return [profile]

        if all_profiles or not profile_name:
            profiles = self.settings.enabled_profiles()
            if not profiles:
                raise ConfigurationError("Нет включенных профилей для запуска.")
            return profiles

        return []

    def _sleep_between_profiles(self) -> None:
        minimum, maximum = self.settings.app.between_profiles_delay_seconds
        self.sleep(random.uniform(minimum, maximum))

    def _build_profile_stack(self, profile: ProfileSettings):
        return _ProfileRuntimeContext(self.settings, self.state_store, profile)


class _ProfileRuntimeContext:
    """Создает и корректно закрывает зависимости времени выполнения для профиля."""

    def __init__(self, settings: ProjectSettings, state_store: RuntimeStateStore, profile: ProfileSettings) -> None:
        self.settings = settings
        self.state_store = state_store
        self.profile = profile
        self.session: requests.Session | None = None
        self.objects: dict[str, object] = {}

    def __enter__(self) -> dict[str, object]:
        profile_logger = logging.LoggerAdapter(
            logging.getLogger(f"duckbot.profile.{self.profile.name}"),
            {"profile": self.profile.name},
        )
        api_base_url = self.profile.api_base_url or self.settings.app.api_base_url
        session = requests.Session()
        header_builder = HeaderBuilder(self.settings.app.http_headers)
        auth_manager = AuthManager(
            session=session,
            profile=self.profile,
            api_base_url=api_base_url,
            header_builder=header_builder,
            auth_settings=self.settings.app.auth,
            state_store=self.state_store,
            logger=profile_logger,
            timeout_seconds=self.settings.app.request_timeout_seconds,
        )
        api_client = DuckApiClient(
            session=session,
            api_base_url=api_base_url,
            header_builder=header_builder,
            auth_manager=auth_manager,
            retry_settings=self.settings.app.retry,
            timeout_seconds=self.settings.app.request_timeout_seconds,
            logger=profile_logger,
        )
        self.session = session
        self.objects = {
            "logger": profile_logger,
            "api_base_url": api_base_url,
            "header_builder": header_builder,
            "auth_manager": auth_manager,
            "api_client": api_client,
        }
        return self.objects

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.session is not None:
            self.session.close()
