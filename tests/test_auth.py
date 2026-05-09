from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from duckbot.http.auth_manager import AuthManager, extract_init_data
from duckbot.config import AuthSettings, ProfileSettings
from duckbot.http.header_builder import HeaderBuilder
from duckbot.storage.runtime_state import RuntimeStateStore


def make_jwt(payload: dict[str, object]) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.signature"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)
        self.ok = status_code < 400

    def json(self) -> dict[str, object]:
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return self.response


class AuthTests(unittest.TestCase):
    def test_extract_init_data_from_webapp_url(self) -> None:
        url = (
            "https://selector.duckmyduck.com/#"
            "tgWebAppData=query_id%3D1%26user%3D%257B%257D%26auth_date%3D2%26hash%3D3"
            "&tgWebAppVersion=9.5"
        )
        extracted = extract_init_data(url)
        self.assertEqual(extracted, "query_id=1&user=%7B%7D&auth_date=2&hash=3")

    def test_auth_manager_refreshes_and_persists_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_store = RuntimeStateStore(Path(temp_dir) / "state.json")
            profile = ProfileSettings(name="main", init_data="query_id=1&auth_date=2&hash=3")
            token = make_jwt({"exp": 4_000_000_000, "playerId": 123, "accountId": 456})
            response = FakeResponse(
                200,
                {
                    "result": True,
                    "response": {
                        "token": token,
                        "player": {"id": 123, "username": "duck-user"},
                    },
                },
            )
            session = FakeSession(response)
            logger = type("Logger", (), {"info": lambda *a, **k: None, "debug": lambda *a, **k: None})()
            auth_manager = AuthManager(
                session=session,
                profile=profile,
                api_base_url="https://api.duckmyduck.com",
                header_builder=HeaderBuilder(),
                auth_settings=AuthSettings(refresh_margin_seconds=300, state_path="runtime/state.json"),
                state_store=state_store,
                logger=logger,
                timeout_seconds=15,
            )

            auth_session = auth_manager.ensure_auth(force_refresh=True)
            stored_state = state_store.get("main")

            self.assertEqual(auth_session.token, token)
            self.assertEqual(stored_state.player_id, 123)
            self.assertEqual(stored_state.account_id, 456)
            self.assertEqual(stored_state.player_name, "duck-user")
            self.assertEqual(len(session.calls), 1)
