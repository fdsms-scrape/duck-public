"""Сборщик заголовков с фиксированным мобильным отпечатком Android."""

from __future__ import annotations

from collections.abc import Mapping

from duckbot.constants import (
    DEFAULT_HTTP_HEADERS,
    IMMUTABLE_FINGERPRINT_HEADER_KEYS,
    MOBILE_FINGERPRINT_HEADERS,
)


class HeaderBuilder:
    """Собирает заголовки запросов для авторизации и вызовов API."""

    def __init__(self, configured_headers: Mapping[str, str] | None = None) -> None:
        self._configured_headers = {
            str(key).lower(): str(value)
            for key, value in (configured_headers or {}).items()
        }

    def _base_headers(self) -> dict[str, str]:
        headers = dict(DEFAULT_HTTP_HEADERS)
        for key, value in self._configured_headers.items():
            if key in IMMUTABLE_FINGERPRINT_HEADER_KEYS:
                continue
            headers[key] = value

        headers.update(MOBILE_FINGERPRINT_HEADERS)
        return headers

    def build(self, authorization: str | None = None) -> dict[str, str]:
        headers = self._base_headers()
        if authorization:
            headers["authorization"] = authorization
        return headers

    def build_auth_headers(self) -> dict[str, str]:
        return self._base_headers()
