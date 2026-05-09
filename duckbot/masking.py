"""Вспомогательные функции для скрытия секретов в логах."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
SELECTOR_URL_RE = re.compile(r"https://selector\.duckmyduck\.com/[^\s]+")
QUERY_PARAM_REPLACEMENTS = (
    (re.compile(r"(tgWebAppData=)[^&\s]+"), r"\1<скрыто>"),
    (re.compile(r"((?:query_id|auth_date|hash|signature|user)=)[^&\s]+"), r"\1<скрыто>"),
)
JSON_FIELD_REPLACEMENTS = (
    re.compile(r'("authorization"\s*:\s*")([^"]+)(")'),
    re.compile(r'("token"\s*:\s*")([^"]+)(")'),
    re.compile(r'("init_data"\s*:\s*")([^"]+)(")'),
    re.compile(r'("webapp_url"\s*:\s*")([^"]+)(")'),
)
SENSITIVE_KEYS = {"authorization", "token", "init_data", "webapp_url"}


def _mask_jwt(match: re.Match[str]) -> str:
    token = match.group(0)
    if len(token) <= 20:
        return "<jwt:скрыт>"
    return f"{token[:10]}...<скрыто>...{token[-6:]}"


def sanitize_string(value: str) -> str:
    """Скрывает секреты внутри строки."""
    if "query_id=" in value and "auth_date=" in value and ("hash=" in value or "signature=" in value):
        return "<данные-telegram-init>"

    masked = JWT_RE.sub(_mask_jwt, value)
    masked = SELECTOR_URL_RE.sub("https://selector.duckmyduck.com/<скрыто>", masked)

    for pattern, replacement in QUERY_PARAM_REPLACEMENTS:
        masked = pattern.sub(replacement, masked)

    for pattern in JSON_FIELD_REPLACEMENTS:
        masked = pattern.sub(r"\1<скрыто>\3", masked)

    return masked


def sanitize_value(value: Any) -> Any:
    """Рекурсивно скрывает данные в строках, словарях и последовательностях."""
    if isinstance(value, str):
        return sanitize_string(value)

    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in SENSITIVE_KEYS:
                redacted[key] = "<скрыто>"
            else:
                redacted[key] = sanitize_value(item)
        return redacted

    if isinstance(value, tuple):
        return tuple(sanitize_value(item) for item in value)

    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [sanitize_value(item) for item in value]

    return value


class SensitiveDataFilter(logging.Filter):
    """Фильтр логирования, который скрывает секреты и гарантирует наличие профиля."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "profile"):
            record.profile = "-"

        record.msg = sanitize_value(record.msg)
        if record.args:
            record.args = sanitize_value(record.args)

        return True
