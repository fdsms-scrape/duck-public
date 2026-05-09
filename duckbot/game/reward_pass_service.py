"""Сбор наград reward-pass после игрового цикла."""

from __future__ import annotations

from typing import Any

import requests

from duckbot.exceptions import ApiError, ApiResponseError
from duckbot.game.base import GameService
from duckbot.masking import sanitize_value


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_uncollected_reward_pass_step_indices(reward_pass: dict[str, Any]) -> list[int]:
    """Возвращает индексы несобранных шагов reward-pass по порядку."""
    return [
        index
        for index, step in enumerate(reward_pass.get("steps") or [])
        if step.get("isCollected") is False
    ]


def get_claimable_reward_pass_step_indices(
    reward_pass: dict[str, Any],
    special_resources: dict[str, Any],
) -> list[int] | None:
    """Считает шаги, которые точно можно забрать по известному прогрессу ресурса."""
    resource = str(reward_pass.get("resource") or "").strip()
    if not resource or resource not in special_resources:
        return None

    progress = _to_int(special_resources.get(resource))
    if progress is None:
        return None

    claimable_indices: list[int] = []
    for index, step in enumerate(reward_pass.get("steps") or []):
        if step.get("isCollected") is not False:
            continue
        threshold = _to_int(step.get("value"))
        if threshold is None:
            continue
        if progress >= threshold:
            claimable_indices.append(index)

    return claimable_indices


class RewardPassService(GameService):
    """Забирает доступные награды reward-pass без лишних повторов."""

    def collect_available_rewards(self) -> int:
        reward_pass_payload = self.safe_post("/reward-pass", {})
        reward_passes = (reward_pass_payload or {}).get("response") or []
        if not reward_passes:
            return 0

        player_payload = self.safe_post("/player/me")
        if not player_payload:
            return 0

        special_resources = ((player_payload.get("response") or {}).get("specialResources") or {})
        collected_total = 0

        for reward_pass in reward_passes:
            if ((reward_pass.get("lock") or {}).get("isLocked")):
                continue

            claimable_indices = get_claimable_reward_pass_step_indices(reward_pass, special_resources)
            if claimable_indices is None:
                collected_total += self._collect_with_unknown_progress(reward_pass)
                continue

            collected_total += self._collect_known_steps(reward_pass, claimable_indices)

        if collected_total:
            self.logger.info("Собрали награды reward-pass: %s шаг(ов)", collected_total)
        return collected_total

    def _collect_known_steps(self, reward_pass: dict[str, Any], step_indices: list[int]) -> int:
        collected_count = 0
        pass_name = str(reward_pass.get("name") or "unknown")
        resource = str(reward_pass.get("resource") or "unknown")
        steps = reward_pass.get("steps") or []

        for step_index in step_indices:
            response, error = self._claim_step(pass_name, step_index)
            if not response:
                step_value = _to_int((steps[step_index] or {}).get("value"))
                self.logger.warning(
                    "Не удалось забрать reward-pass %s, stepIndex=%s, порог=%s, ресурс=%s. Останавливаем этот pass до следующего цикла. Причина: %s",
                    pass_name,
                    step_index,
                    step_value,
                    resource,
                    error,
                )
                return collected_count

            step_value = _to_int((steps[step_index] or {}).get("value"))
            collected_count += 1
            self.logger.info(
                "Забрали reward-pass %s, stepIndex=%s, порог=%s, ресурс=%s",
                pass_name,
                step_index,
                step_value,
                resource,
            )
            self.sleep_range(self.settings.between_actions_delay_seconds)

        return collected_count

    def _collect_with_unknown_progress(self, reward_pass: dict[str, Any]) -> int:
        collected_count = 0
        pass_name = str(reward_pass.get("name") or "unknown")
        resource = str(reward_pass.get("resource") or "unknown")
        steps = reward_pass.get("steps") or []

        for step_index in get_uncollected_reward_pass_step_indices(reward_pass):
            response, _error = self._claim_step(pass_name, step_index)
            if not response:
                if collected_count > 0:
                    step_value = _to_int((steps[step_index] or {}).get("value"))
                    self.logger.info(
                        "Дальше reward-pass %s пока не подтверждается: остановились на stepIndex=%s с порогом %s по ресурсу %s",
                        pass_name,
                        step_index,
                        step_value,
                        resource,
                    )
                return collected_count

            step_value = _to_int((steps[step_index] or {}).get("value"))
            collected_count += 1
            self.logger.info(
                "Забрали reward-pass %s, stepIndex=%s, порог=%s, ресурс=%s",
                pass_name,
                step_index,
                step_value,
                resource,
            )
            self.sleep_range(self.settings.between_actions_delay_seconds)

        return collected_count

    def _claim_step(self, pass_name: str, step_index: int) -> tuple[dict[str, Any] | None, ApiError | None]:
        try:
            response = self._post_once("/reward-pass/claim", {"stepIndex": step_index, "name": pass_name})
        except ApiError as exc:
            return None, exc
        return response, None

    def _post_once(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request_url = f"{self.api_client.api_base_url}{path}"
        auth_retry_available = True

        while True:
            auth_session = self.api_client.auth_manager.ensure_auth()
            headers = self.api_client.header_builder.build(auth_session.token)

            try:
                response = self.api_client.session.request(
                    "POST",
                    request_url,
                    headers=headers,
                    json=payload,
                    timeout=self.api_client.timeout_seconds,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                raise ApiError(f"Сетевая ошибка при запросе {path}: {exc}") from exc
            except requests.RequestException as exc:
                raise ApiError(f"Ошибка HTTP-клиента при запросе {path}: {exc}") from exc

            if response.status_code == 401 and auth_retry_available:
                self.api_client.auth_manager.ensure_auth(force_refresh=True)
                auth_retry_available = False
                continue

            try:
                data = response.json()
            except ValueError as exc:
                raise ApiResponseError(
                    f"API {path} вернул невалидный JSON.",
                    status_code=response.status_code,
                    response_body=sanitize_value(response.text),
                ) from exc

            if not isinstance(data, dict):
                raise ApiResponseError(
                    f"API {path} вернул неожиданную структуру JSON.",
                    status_code=response.status_code,
                    response_body=sanitize_value(str(data)),
                )

            if not response.ok or data.get("result") is False:
                message = data.get("error") or data.get("message") or response.text
                raise ApiResponseError(
                    f"Запрос к API {path} завершился ошибкой: {sanitize_value(str(message))}",
                    error_code=str(data.get("error")) if data.get("error") else None,
                    status_code=response.status_code,
                    response_body=sanitize_value(response.text),
                )

            return data
