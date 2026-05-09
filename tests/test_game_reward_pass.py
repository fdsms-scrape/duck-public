from __future__ import annotations

import unittest

from duckbot.config import AppSettings, ProfileSettings
from duckbot.exceptions import ApiError
from duckbot.game.reward_pass_service import (
    RewardPassService,
    get_claimable_reward_pass_step_indices,
    get_uncollected_reward_pass_step_indices,
)


class _DummyLogger:
    def info(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def warning(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def error(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None


class _StubRewardPassService(RewardPassService):
    def __init__(
        self,
        *,
        reward_pass_payload: dict[str, object],
        player_payload: dict[str, object],
        claim_results: dict[tuple[str, int], bool],
    ) -> None:
        super().__init__(
            profile=ProfileSettings(name="main", init_data="query_id=1&auth_date=1"),
            settings=AppSettings(),
            state_store=None,
            api_client=None,
            logger=_DummyLogger(),
            sleep_func=lambda *_args, **_kwargs: None,
        )
        self.reward_pass_payload = reward_pass_payload
        self.player_payload = player_payload
        self.claim_results = claim_results
        self.safe_calls: list[tuple[str, dict[str, object] | None]] = []
        self.claim_calls: list[tuple[str, int]] = []
        self.sleep_calls = 0

    def safe_post(self, path: str, payload=None):  # noqa: ANN001
        self.safe_calls.append((path, payload))
        if path == "/reward-pass":
            return self.reward_pass_payload
        if path == "/player/me":
            return self.player_payload
        return None

    def sleep_range(self, delay_range: list[float]) -> None:
        self.sleep_calls += 1

    def _claim_step(self, pass_name: str, step_index: int):  # noqa: ANN001
        self.claim_calls.append((pass_name, step_index))
        success = self.claim_results.get((pass_name, step_index), False)
        if not success:
            return None, ApiError("not-claimable")
        return {"result": True}, None


class RewardPassHelpersTests(unittest.TestCase):
    def test_get_uncollected_reward_pass_step_indices_returns_only_false_flags(self) -> None:
        reward_pass = {
            "steps": [
                {"isCollected": True},
                {"isCollected": False},
                {"isCollected": False},
            ]
        }

        indices = get_uncollected_reward_pass_step_indices(reward_pass)

        self.assertEqual(indices, [1, 2])

    def test_get_claimable_reward_pass_step_indices_uses_known_special_resource_progress(self) -> None:
        reward_pass = {
            "resource": "regular",
            "steps": [
                {"value": 60, "isCollected": False},
                {"value": 200, "isCollected": False},
                {"value": 300, "isCollected": False},
                {"value": 550, "isCollected": False},
            ],
        }

        indices = get_claimable_reward_pass_step_indices(reward_pass, {"regular": 340})

        self.assertEqual(indices, [0, 1, 2])


class RewardPassServiceTests(unittest.TestCase):
    def test_collect_available_rewards_claims_all_known_steps_with_enough_progress(self) -> None:
        service = _StubRewardPassService(
            reward_pass_payload={
                "response": [
                    {
                        "name": "regular_EPIC",
                        "resource": "regular",
                        "lock": {"isLocked": False},
                        "steps": [
                            {"value": 60, "isCollected": False},
                            {"value": 200, "isCollected": False},
                            {"value": 300, "isCollected": False},
                            {"value": 550, "isCollected": False},
                        ],
                    }
                ]
            },
            player_payload={"response": {"specialResources": {"regular": 340}}},
            claim_results={
                ("regular_EPIC", 0): True,
                ("regular_EPIC", 1): True,
                ("regular_EPIC", 2): True,
            },
        )

        collected_count = service.collect_available_rewards()

        self.assertEqual(collected_count, 3)
        self.assertEqual(
            service.claim_calls,
            [("regular_EPIC", 0), ("regular_EPIC", 1), ("regular_EPIC", 2)],
        )
        self.assertEqual(service.sleep_calls, 3)

    def test_collect_available_rewards_skips_locked_passes(self) -> None:
        service = _StubRewardPassService(
            reward_pass_payload={
                "response": [
                    {
                        "name": "locked",
                        "resource": "regular",
                        "lock": {"isLocked": True},
                        "steps": [{"value": 60, "isCollected": False}],
                    }
                ]
            },
            player_payload={"response": {"specialResources": {"regular": 1000}}},
            claim_results={("locked", 0): True},
        )

        collected_count = service.collect_available_rewards()

        self.assertEqual(collected_count, 0)
        self.assertEqual(service.claim_calls, [])

    def test_collect_available_rewards_stops_known_pass_after_first_failed_step(self) -> None:
        service = _StubRewardPassService(
            reward_pass_payload={
                "response": [
                    {
                        "name": "regular_EPIC",
                        "resource": "regular",
                        "lock": {"isLocked": False},
                        "steps": [
                            {"value": 60, "isCollected": False},
                            {"value": 200, "isCollected": False},
                        ],
                    }
                ]
            },
            player_payload={"response": {"specialResources": {"regular": 500}}},
            claim_results={
                ("regular_EPIC", 0): True,
                ("regular_EPIC", 1): False,
            },
        )

        collected_count = service.collect_available_rewards()

        self.assertEqual(collected_count, 1)
        self.assertEqual(
            service.claim_calls,
            [("regular_EPIC", 0), ("regular_EPIC", 1)],
        )
        self.assertEqual(service.sleep_calls, 1)

    def test_collect_available_rewards_for_unknown_resource_probes_until_first_failure(self) -> None:
        service = _StubRewardPassService(
            reward_pass_payload={
                "response": [
                    {
                        "name": "clanShow_legendary_free",
                        "resource": "clanShowFans",
                        "lock": {"isLocked": False},
                        "steps": [
                            {"value": 100, "isCollected": False},
                            {"value": 250, "isCollected": False},
                            {"value": 500, "isCollected": False},
                        ],
                    }
                ]
            },
            player_payload={"response": {"specialResources": {"regular": 340}}},
            claim_results={
                ("clanShow_legendary_free", 0): True,
                ("clanShow_legendary_free", 1): False,
            },
        )

        collected_count = service.collect_available_rewards()

        self.assertEqual(collected_count, 1)
        self.assertEqual(
            service.claim_calls,
            [("clanShow_legendary_free", 0), ("clanShow_legendary_free", 1)],
        )
        self.assertEqual(service.sleep_calls, 1)
