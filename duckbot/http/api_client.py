"""HTTP-клиент для API DuckMyDuck."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from duckbot.config import RetrySettings
from duckbot.exceptions import ApiError, ApiResponseError
from duckbot.http.auth_manager import AuthManager
from duckbot.http.header_builder import HeaderBuilder
from duckbot.masking import sanitize_value

NON_RETRYABLE_SERVER_ERROR_CODES = frozenset({"MONEY"})


class DuckApiClient:
    """Клиент API для одного профиля с повторами и обновлением токена."""

    def __init__(
        self,
        *,
        session: requests.Session,
        api_base_url: str,
        header_builder: HeaderBuilder,
        auth_manager: AuthManager,
        retry_settings: RetrySettings,
        timeout_seconds: float,
        logger: logging.LoggerAdapter,
        sleep_func=time.sleep,
    ) -> None:
        self.session = session
        self.api_base_url = api_base_url
        self.header_builder = header_builder
        self.auth_manager = auth_manager
        self.retry_settings = retry_settings
        self.timeout_seconds = timeout_seconds
        self.logger = logger
        self.sleep = sleep_func

    def post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("POST", path, payload or {})

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_payload = payload or {}
        request_url = f"{self.api_base_url}{path}"
        delay = self.retry_settings.base_delay_seconds
        auth_retry_available = True
        last_error: Exception | None = None

        for attempt in range(1, self.retry_settings.max_attempts + 1):
            auth_session = self.auth_manager.ensure_auth()
            headers = self.header_builder.build(auth_session.token)
            self.logger.debug(
                "HTTP %s %s данные=%s попытка=%s",
                method,
                path,
                request_payload,
                attempt,
            )

            try:
                response = self.session.request(
                    method,
                    request_url,
                    headers=headers,
                    json=request_payload,
                    timeout=self.timeout_seconds,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                if attempt >= self.retry_settings.max_attempts:
                    break
                self.logger.warning(
                    "Сетевая ошибка при %s %s: %s. Повтор через %.1fс",
                    method,
                    path,
                    exc,
                    delay,
                )
                self.sleep(delay)
                delay *= 2
                continue
            except requests.RequestException as exc:
                raise ApiError(f"Ошибка HTTP-клиента при запросе {path}: {exc}") from exc

            if response.status_code == 401 and auth_retry_available:
                self.logger.warning("Получен 401 для %s. Обновляем JWT и повторяем запрос.", path)
                self.auth_manager.ensure_auth(force_refresh=True)
                auth_retry_available = False
                continue

            if response.status_code == 429 and attempt < self.retry_settings.max_attempts:
                wait_seconds = self._resolve_rate_limit_delay(response, delay)
                self.logger.warning(
                    "Достигнут лимит запросов для %s. Ждем %.1fс перед повтором.",
                    path,
                    wait_seconds,
                )
                self.sleep(wait_seconds)
                delay *= 2
                continue

            if response.status_code >= 500:
                non_retryable_error = self._extract_non_retryable_server_error(response)
                if non_retryable_error is not None:
                    raise non_retryable_error

            if response.status_code >= 500 and attempt < self.retry_settings.max_attempts:
                self.logger.warning(
                    "Серверная ошибка %s для %s. Повтор через %.1fс.",
                    response.status_code,
                    path,
                    delay,
                )
                self.sleep(delay)
                delay *= 2
                continue

            data = self._parse_json(response, path)
            if not response.ok or data.get("result") is False:
                message = data.get("error") or data.get("message") or response.text
                raise ApiResponseError(
                    f"Запрос к API {path} завершился ошибкой: {sanitize_value(str(message))}",
                    error_code=str(data.get("error")) if data.get("error") else None,
                    status_code=response.status_code,
                    response_body=sanitize_value(response.text),
                )

            return data

        raise ApiError(f"Запрос {path} не удался после повторов: {last_error}")

    def _parse_json(self, response: requests.Response, path: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiResponseError(
                f"API {path} вернул невалидный JSON.",
                status_code=response.status_code,
                response_body=sanitize_value(response.text),
            ) from exc

        if not isinstance(payload, dict):
            raise ApiResponseError(
                f"API {path} вернул неожиданную структуру JSON.",
                status_code=response.status_code,
                response_body=sanitize_value(json.dumps(payload, ensure_ascii=False)),
            )

        return payload

    def _extract_non_retryable_server_error(self, response: requests.Response) -> ApiResponseError | None:
        try:
            payload = response.json()
        except ValueError:
            return None

        if not isinstance(payload, dict):
            return None

        error_code = payload.get("error")
        if not isinstance(error_code, str) or not error_code:
            return None

        if error_code == "UNKNOWN":
            return None

        if error_code not in NON_RETRYABLE_SERVER_ERROR_CODES and not error_code.startswith("error_"):
            return None

        return ApiResponseError(
            f"Запрос к API завершился ошибкой: {sanitize_value(error_code)}",
            error_code=error_code,
            status_code=response.status_code,
            response_body=sanitize_value(response.text),
        )

    def _resolve_rate_limit_delay(self, response: requests.Response, default_delay: float) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        return default_delay * self.retry_settings.rate_limit_multiplier
