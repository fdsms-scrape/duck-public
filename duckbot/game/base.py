"""Базовые инструменты игрового доменного слоя."""

from __future__ import annotations

import random
import time
from typing import Any

from duckbot.config import AppSettings, ProfileSettings
from duckbot.exceptions import ApiError
from duckbot.http.api_client import DuckApiClient
from duckbot.storage.runtime_state import RuntimeStateStore


class GameService:
    """Общая база для сервисов игровой автоматизации."""

    def __init__(
        self,
        *,
        profile: ProfileSettings,
        settings: AppSettings,
        state_store: RuntimeStateStore,
        api_client: DuckApiClient,
        logger,
        sleep_func=time.sleep,
    ) -> None:
        self.profile = profile
        self.settings = settings
        self.state_store = state_store
        self.api_client = api_client
        self.logger = logger
        self.sleep = sleep_func

    def safe_post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Вызывает API и превращает ошибки в лог без падения цикла."""
        try:
            return self.api_client.post(path, payload)
        except ApiError as exc:
            self.logger.error("Вызов %s завершился ошибкой: %s", path, exc)
            return None

    def sleep_range(self, delay_range: list[float]) -> None:
        """Спит случайное время внутри заданного диапазона."""
        self.sleep(random.uniform(delay_range[0], delay_range[1]))
