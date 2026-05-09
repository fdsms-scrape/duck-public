"""Пользовательские исключения проекта DuckBot."""

from __future__ import annotations


class DuckBotError(Exception):
    """Базовое исключение проекта."""


class ConfigurationError(DuckBotError):
    """Ошибка конфигурации."""


class AuthError(DuckBotError):
    """Ошибка авторизации профиля."""


class ApiError(DuckBotError):
    """Ошибка вызова API."""


class ApiResponseError(ApiError):
    """Ошибка ответа API при неуспешном или невалидном результате."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
