from __future__ import annotations

import unittest

from duckbot.config import AppSettings, FeedRuleSettings, ProfileSettings
from duckbot.exceptions import ApiResponseError
from duckbot.game.duck_service import DuckService, resolve_feed_rule, select_active_ducks


class _DummyLogger:
    def info(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def warning(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def error(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None


class _StubFeedClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, path, payload):  # noqa: ANN001
        self.calls.append((path, payload))
        if self.error:
            raise self.error
        return {"result": True}


class _ScriptedApiClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, path, payload):  # noqa: ANN001
        self.calls.append((path, payload))
        if not self.responses:
            return {"result": True}
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response



class DuckSelectionTests(unittest.TestCase):
    def test_select_active_ducks_returns_all_actionable_ducks_without_slot_limit(self) -> None:
        ducks = [{"id": 1, "state": "STAKE"}]
        ducks.extend({"id": duck_id, "state": "FEED"} for duck_id in range(2, 23))

        active_ducks = select_active_ducks(ducks)

        self.assertEqual(len(active_ducks), 21)
        self.assertTrue(all(duck["state"] == "FEED" for duck in active_ducks))
        self.assertEqual(active_ducks[0]["id"], 2)
        self.assertEqual(active_ducks[-1]["id"], 22)

    def test_select_active_ducks_limits_window_after_filtering_stake(self) -> None:
        ducks = [{"id": 1, "state": "STAKE"}]
        ducks.extend({"id": duck_id, "state": "FEED"} for duck_id in range(2, 24))

        active_ducks = select_active_ducks(ducks, duck_slots_count=20)

        self.assertEqual(len(active_ducks), 20)
        self.assertEqual(active_ducks[0]["id"], 2)
        self.assertEqual(active_ducks[-1]["id"], 21)

    def test_select_active_ducks_ignores_non_actionable_states(self) -> None:
        ducks = [
            {"id": 1, "state": "STAKE"},
            {"id": 2, "state": "MARKET"},
            {"id": 3, "state": "FEED"},
            {"id": 4, "state": "BREED"},
        ]

        active_ducks = select_active_ducks(ducks)

        self.assertEqual([duck["id"] for duck in active_ducks], [3, 4])

    def test_resolve_feed_rule_matches_by_rarity_and_level(self) -> None:
        rules = [
            FeedRuleSettings(quality="COMMON", min_level=1, max_level=5, max_cost=20),
            FeedRuleSettings(quality="COMMON", min_level=6, max_cost=50),
        ]

        rule = resolve_feed_rule({"quality": "COMMON", "level": 7}, rules)

        self.assertIsNotNone(rule)
        self.assertEqual(rule.max_cost, 50)

    def test_resolve_feed_rule_skips_disabled_rules(self) -> None:
        rules = [
            FeedRuleSettings(quality="RARE", min_level=1, max_cost=120, enabled=False),
        ]

        self.assertIsNone(resolve_feed_rule({"quality": "RARE", "level": 3}, rules))

    def test_feed_duck_once_returns_stop_reason_for_known_state_errors(self) -> None:
        client = _StubFeedClient(
            ApiResponseError(
                "Запрос к API /ducks/feed завершился ошибкой: error_duck_bad_state",
                error_code="error_duck_bad_state",
                status_code=500,
            )
        )
        service = DuckService(
            profile=ProfileSettings(name="main", init_data="query_id=1&auth_date=1"),
            settings=AppSettings(),
            state_store=None,
            api_client=client,
            logger=_DummyLogger(),
        )

        response, stop_reason = service._feed_duck_once(123)

        self.assertIsNone(response)
        self.assertEqual(stop_reason, "error_duck_bad_state")
        self.assertEqual(client.calls[0][0], "/ducks/feed")

    def test_process_duck_returns_false_for_slot_window_exhaustion(self) -> None:
        client = _StubFeedClient(
            ApiResponseError(
                "Запрос к API /ducks/feed завершился ошибкой: error_slot_not_available",
                error_code="error_slot_not_available",
                status_code=500,
            )
        )
        service = DuckService(
            profile=ProfileSettings(name="main", init_data="query_id=1&auth_date=1"),
            settings=AppSettings(),
            state_store=None,
            api_client=client,
            logger=_DummyLogger(),
        )

        should_continue = service._process_duck(
            {
                "id": 123,
                "state": "FEED",
                "quality": "COMMON",
                "level": 1,
                "feedCost": [1],
                "feedCount": 0,
            },
            player_context=type("Ctx", (), {"corn": 10})(),
        )

        self.assertFalse(should_continue)

    def test_process_duck_skips_breed_when_cost_exceeds_available_corn(self) -> None:
        client = _ScriptedApiClient([])
        service = DuckService(
            profile=ProfileSettings(name="main", init_data="query_id=1&auth_date=1"),
            settings=AppSettings(),
            state_store=None,
            api_client=client,
            logger=_DummyLogger(),
        )

        should_continue = service._process_duck(
            {
                "id": 777,
                "state": "BREED",
                "quality": "COMMON",
                "level": 1,
                "breedingPrice": {"corn": 6000},
            },
            player_context=type("Ctx", (), {"corn": 4172})(),
        )

        self.assertTrue(should_continue)
        self.assertEqual(client.calls, [])

    def test_process_duck_deducts_corn_after_successful_breed(self) -> None:
        client = _ScriptedApiClient(
            [
                {"result": True},
                {"result": True},
            ]
        )
        service = DuckService(
            profile=ProfileSettings(name="main", init_data="query_id=1&auth_date=1"),
            settings=AppSettings(),
            state_store=None,
            api_client=client,
            logger=_DummyLogger(),
        )
        player_context = type("Ctx", (), {"corn": 4172})()

        should_continue = service._process_duck(
            {
                "id": 778,
                "state": "BREED",
                "quality": "COMMON",
                "level": 1,
                "breedingPrice": {"corn": 600},
            },
            player_context=player_context,
        )

        self.assertTrue(should_continue)
        self.assertEqual(player_context.corn, 3572)
        self.assertEqual(
            [path for path, _payload in client.calls],
            ["/ducks/breed/pay", "/ducks/breed/search"],
        )

    def test_process_duck_refreshes_balance_after_money_error_on_breed(self) -> None:
        client = _ScriptedApiClient(
            [
                ApiResponseError(
                    "Запрос к API /ducks/breed/pay завершился ошибкой: MONEY",
                    error_code="MONEY",
                    status_code=500,
                ),
                {"result": True, "response": {"player": {"corn": 250}}},
            ]
        )
        service = DuckService(
            profile=ProfileSettings(name="main", init_data="query_id=1&auth_date=1"),
            settings=AppSettings(),
            state_store=None,
            api_client=client,
            logger=_DummyLogger(),
        )
        player_context = type("Ctx", (), {"corn": 7000})()

        should_continue = service._process_duck(
            {
                "id": 779,
                "state": "BREED",
                "quality": "COMMON",
                "level": 1,
                "breedingPrice": {"corn": 6000},
            },
            player_context=player_context,
        )

        self.assertTrue(should_continue)
        self.assertEqual(player_context.corn, 250)
        self.assertEqual(
            [path for path, _payload in client.calls],
            ["/ducks/breed/pay", "/player/me"],
        )
