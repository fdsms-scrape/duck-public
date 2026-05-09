from __future__ import annotations

import unittest

from duckbot.masking import sanitize_value


class MaskingTests(unittest.TestCase):
    def test_sanitize_value_redacts_tokens_and_urls(self) -> None:
        data = {
            "authorization": "eyJhbGciOiJIUzI1NiJ9.payload.signature",
            "webapp_url": "https://selector.duckmyduck.com/#tgWebAppData=secret",
            "nested": "query_id=1&auth_date=2&hash=3",
        }

        sanitized = sanitize_value(data)

        self.assertEqual(sanitized["authorization"], "<скрыто>")
        self.assertEqual(sanitized["webapp_url"], "<скрыто>")
        self.assertEqual(sanitized["nested"], "<данные-telegram-init>")
