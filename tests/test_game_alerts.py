from __future__ import annotations

import unittest

from duckbot.game.alerts_service import iter_confirmable_alert_actions


class AlertHelpersTests(unittest.TestCase):
    def test_iter_confirmable_alert_actions_returns_only_confirm_buttons(self) -> None:
        alerts = [
            {
                "id": 10,
                "typeHuman": "Clan Show Sabotage Result",
                "buttons": [
                    {
                        "url": "/alert/action",
                        "params": {"id": 10, "action": "confirm"},
                    }
                ],
            },
            {
                "id": 20,
                "typeHuman": "Другое окно",
                "buttons": [
                    {
                        "url": "/alert/action",
                        "params": {"id": 20, "action": "close"},
                    }
                ],
            },
        ]

        actions = iter_confirmable_alert_actions(alerts)

        self.assertEqual(
            actions,
            [
                {
                    "alert_id": 10,
                    "alert_name": "Clan Show Sabotage Result",
                    "path": "/alert/action",
                    "payload": {"id": 10, "action": "confirm"},
                }
            ],
        )
