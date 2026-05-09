from __future__ import annotations

import unittest

from duckbot.http.header_builder import HeaderBuilder


class HeaderBuilderTests(unittest.TestCase):
    def test_builder_keeps_android_fingerprint_and_adds_auth(self) -> None:
        builder = HeaderBuilder(
            {
                "sec-ch-ua-platform": '"Windows"',
                "user-agent": "Desktop UA",
                "x-app-version": "9.9.9",
            }
        )

        auth_headers = builder.build_auth_headers()
        api_headers = builder.build("token-123")

        self.assertEqual(auth_headers["sec-ch-ua-platform"], '"Android"')
        self.assertIn("Android 12", auth_headers["user-agent"])
        self.assertEqual(api_headers["authorization"], "token-123")
        self.assertEqual(api_headers["x-app-version"], "9.9.9")
