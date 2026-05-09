"""Вспомогательные функции и классы авторизации профиля."""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

from duckbot.config import AuthSettings, ProfileSettings
from duckbot.exceptions import AuthError
from duckbot.http.header_builder import HeaderBuilder
from duckbot.masking import sanitize_value
from duckbot.storage.runtime_state import ProfileRuntimeState, RuntimeStateStore

LOGGER = logging.getLogger(__name__)


def extract_init_data(raw_value: str) -> str:
    """Извлекает Telegram init data из полной ссылки веб-приложения или принимает raw-строку."""
    candidate = raw_value.strip()
    if not candidate:
        raise AuthError("Пустой источник авторизации.")

    if "query_id=" in candidate and "auth_date=" in candidate:
        return candidate

    parsed = urlparse(candidate)
    combined = "&".join(part for part in (parsed.fragment, parsed.query) if part)
    if not combined:
        raise AuthError("Не удалось найти tgWebAppData в ссылке профиля.")

    params = parse_qs(combined, keep_blank_values=True)
    if "tgWebAppData" in params and params["tgWebAppData"]:
        return params["tgWebAppData"][0]

    if combined.startswith("tgWebAppData="):
        encoded = combined.split("tgWebAppData=", maxsplit=1)[1].split("&", maxsplit=1)[0]
        return unquote(encoded)

    raise AuthError("В ссылке профиля отсутствует параметр `tgWebAppData`.")


def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Декодирует полезную нагрузку JWT без проверки подписи."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("JWT должен состоять из трех частей.")
        payload = parts[1]
        padded = payload + "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception as exc:  # pragma: no cover - защитная ветка
        raise AuthError(f"Не удалось декодировать JWT: {exc}") from exc


@dataclass(slots=True)
class AuthSession:
    """Нормализованное состояние авторизации."""

    token: str
    token_exp: int | None
    player_id: int | None = None
    account_id: int | None = None
    player_name: str | None = None


class AuthManager:
    """Управляет обновлением токена и сохранением состояния авторизации профиля."""

    def __init__(
        self,
        *,
        session: requests.Session,
        profile: ProfileSettings,
        api_base_url: str,
        header_builder: HeaderBuilder,
        auth_settings: AuthSettings,
        state_store: RuntimeStateStore,
        logger: logging.LoggerAdapter,
        timeout_seconds: float,
    ) -> None:
        self.session = session
        self.profile = profile
        self.api_base_url = api_base_url
        self.header_builder = header_builder
        self.auth_settings = auth_settings
        self.state_store = state_store
        self.logger = logger
        self.timeout_seconds = timeout_seconds

    def ensure_auth(self, force_refresh: bool = False) -> AuthSession:
        state = self.state_store.get(self.profile.name)
        if not force_refresh and state.token and not self._is_refresh_required(state):
            return AuthSession(
                token=state.token,
                token_exp=state.token_exp,
                player_id=state.player_id,
                account_id=state.account_id,
                player_name=state.player_name,
            )

        return self.refresh()

    def refresh(self) -> AuthSession:
        init_source = self.profile.webapp_url or self.profile.init_data or ""
        init_data = extract_init_data(init_source)
        request_url = f"{self.api_base_url}/auth/telegram"
        payload = {"data": {"init_data": init_data}, "hash": ""}
        headers = self.header_builder.build_auth_headers()

        self.logger.info("Обновляем JWT через /auth/telegram")
        self.logger.debug("Данные запроса авторизации: %s", payload)

        try:
            response = self.session.post(
                request_url,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise AuthError(f"Ошибка запроса к /auth/telegram: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise AuthError("Сервер авторизации вернул не-JSON ответ.") from exc

        if not response.ok or not data.get("result"):
            error = data.get("error") or data.get("message") or response.text
            raise AuthError(f"Авторизация профиля не удалась: {sanitize_value(str(error))}")

        response_body = data.get("response", {})
        token = response_body.get("token")
        if not token:
            raise AuthError("Сервер авторизации не вернул токен.")

        claims = decode_jwt_claims(token)
        player = response_body.get("player", {})
        auth_session = AuthSession(
            token=token,
            token_exp=claims.get("exp"),
            player_id=claims.get("playerId") or player.get("id"),
            account_id=claims.get("accountId"),
            player_name=player.get("username") or player.get("name"),
        )
        self._persist(auth_session)
        return auth_session

    def _persist(self, auth_session: AuthSession) -> None:
        self.state_store.update(
            self.profile.name,
            token=auth_session.token,
            token_exp=auth_session.token_exp,
            last_auth_at=int(time.time()),
            player_id=auth_session.player_id,
            account_id=auth_session.account_id,
            player_name=auth_session.player_name,
        )

    def _is_refresh_required(self, state: ProfileRuntimeState) -> bool:
        if not state.token or not state.token_exp:
            return True
        return state.token_exp <= int(time.time()) + self.auth_settings.refresh_margin_seconds
