from __future__ import annotations

import json
import unittest

from duckbot.http.api_client import DuckApiClient
from duckbot.http.auth_manager import AuthSession
from duckbot.config import RetrySettings
from duckbot.http.header_builder import HeaderBuilder


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object], headers=None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload, ensure_ascii=False)
        self.ok = status_code < 400

    def json(self) -> dict[str, object]:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def request(self, method, url, headers=None, json=None, timeout=None):  # noqa: ANN001
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return self.responses.pop(0)


class StubAuthManager:
    def __init__(self) -> None:
        self.current_token = "old-token"
        self.calls: list[bool] = []

    def ensure_auth(self, force_refresh: bool = False) -> AuthSession:
        self.calls.append(force_refresh)
        if force_refresh:
            self.current_token = "new-token"
        return AuthSession(token=self.current_token, token_exp=4_000_000_000)


class ApiClientTests(unittest.TestCase):
    def test_client_refreshes_token_after_401(self) -> None:
        auth_manager = StubAuthManager()
        session = FakeSession(
            [
                FakeResponse(401, {"result": False, "error": "UNAUTHORIZED"}),
                FakeResponse(200, {"result": True, "response": {"ok": True}}),
            ]
        )
        sleep_calls: list[float] = []
        logger = type(
            "Logger",
            (),
            {
                "debug": lambda *a, **k: None,
                "warning": lambda *a, **k: None,
            },
        )()
        client = DuckApiClient(
            session=session,
            api_base_url="https://api.duckmyduck.com",
            header_builder=HeaderBuilder(),
            auth_manager=auth_manager,
            retry_settings=RetrySettings(max_attempts=3, base_delay_seconds=1, rate_limit_multiplier=5),
            timeout_seconds=15,
            logger=logger,
            sleep_func=sleep_calls.append,
        )

        result = client.post("/player/me", {})

        self.assertTrue(result["response"]["ok"])
        self.assertEqual(auth_manager.calls, [False, True, False])
        self.assertEqual(session.calls[1]["headers"]["authorization"], "new-token")
        self.assertEqual(sleep_calls, [])

    def test_client_waits_after_429(self) -> None:
        auth_manager = StubAuthManager()
        session = FakeSession(
            [
                FakeResponse(429, {"result": False, "error": "RATE_LIMIT"}),
                FakeResponse(200, {"result": True, "response": {"ok": True}}),
            ]
        )
        sleep_calls: list[float] = []
        logger = type(
            "Logger",
            (),
            {
                "debug": lambda *a, **k: None,
                "warning": lambda *a, **k: None,
            },
        )()
        client = DuckApiClient(
            session=session,
            api_base_url="https://api.duckmyduck.com",
            header_builder=HeaderBuilder(),
            auth_manager=auth_manager,
            retry_settings=RetrySettings(max_attempts=3, base_delay_seconds=2, rate_limit_multiplier=5),
            timeout_seconds=15,
            logger=logger,
            sleep_func=sleep_calls.append,
        )

        result = client.post("/ducks", {})

        self.assertTrue(result["response"]["ok"])
        self.assertEqual(sleep_calls, [10])
