"""Обработка наград и подтверждений через игровые алерты."""

from __future__ import annotations

from typing import Any

from duckbot.game.base import GameService


def iter_confirmable_alert_actions(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Извлекает подтверждаемые действия из списка алертов."""
    actions: list[dict[str, Any]] = []
    for alert in alerts:
        alert_id = alert.get("id")
        alert_name = alert.get("typeHuman") or f"alert:{alert.get('type')}"
        for button in alert.get("buttons") or []:
            params = button.get("params") or {}
            if button.get("url") != "/alert/action":
                continue
            if params.get("action") != "confirm" or not params.get("id"):
                continue
            actions.append(
                {
                    "alert_id": alert_id,
                    "alert_name": alert_name,
                    "path": button["url"],
                    "payload": params,
                }
            )
    return actions


class AlertsService(GameService):
    """Подтверждает награды и результаты, приходящие в алертах."""

    def collect_confirmable_rewards(self, alerts: list[dict[str, Any]]) -> int:
        collected_count = 0
        for action in iter_confirmable_alert_actions(alerts):
            response = self.safe_post(action["path"], action["payload"])
            if not response:
                continue
            collected_count += 1
            self.logger.info(
                "Подтвердили алерт %s (%s)",
                action["alert_name"],
                action["alert_id"],
            )
            self.sleep_range(self.settings.between_actions_delay_seconds)
        return collected_count
