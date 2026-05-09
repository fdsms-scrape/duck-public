from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from duckbot.config import load_settings
from duckbot.exceptions import ConfigurationError


class ConfigTests(unittest.TestCase):
    def write_file(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def test_duplicate_profiles_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_file(root / "config.yaml", "api_base_url: https://api.duckmyduck.com\n")
            self.write_file(
                root / "profiles.local.yaml",
                """
profiles:
  - name: main
    init_data: query_id=1&auth_date=2&hash=3
  - name: main
    init_data: query_id=4&auth_date=5&hash=6
""".strip(),
            )

            with self.assertRaises(ConfigurationError):
                load_settings(root / "config.yaml", root / "profiles.local.yaml")

    def test_breed_rule_rejects_invalid_level_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_file(
                root / "config.yaml",
                """
game:
  breed_rules:
    - quality: COMMON
      min_level: 10
      max_level: 5
""".strip(),
            )
            self.write_file(
                root / "profiles.local.yaml",
                """
profiles:
  - name: main
    init_data: query_id=1&auth_date=2&hash=3
""".strip(),
            )

            with self.assertRaises(ConfigurationError):
                load_settings(root / "config.yaml", root / "profiles.local.yaml")

    def test_feed_rule_rejects_invalid_level_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_file(
                root / "config.yaml",
                """
game:
  feed_rules:
    - quality: COMMON
      min_level: 8
      max_level: 3
      max_cost: 50
""".strip(),
            )
            self.write_file(
                root / "profiles.local.yaml",
                """
profiles:
  - name: main
    init_data: query_id=1&auth_date=2&hash=3
""".strip(),
            )

            with self.assertRaises(ConfigurationError):
                load_settings(root / "config.yaml", root / "profiles.local.yaml")

    def test_compact_feed_and_breed_rules_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_file(
                root / "config.yaml",
                """
game:
  feed_rules:
    COMMON: [10, 20, 30, 40, 50]
  breed_rules:
    COMMON:
      currency: corn
      levels: [1, 3, 5]
""".strip(),
            )
            self.write_file(
                root / "profiles.local.yaml",
                """
profiles:
  - name: main
    init_data: query_id=1&auth_date=2&hash=3
""".strip(),
            )

            settings = load_settings(root / "config.yaml", root / "profiles.local.yaml")

            self.assertEqual(len(settings.app.game.feed_rules), 5)
            self.assertEqual(settings.app.game.feed_rules[0].min_level, 1)
            self.assertEqual(settings.app.game.feed_rules[0].max_cost, 10)
            self.assertEqual(settings.app.game.feed_rules[-1].min_level, 5)
            self.assertEqual(settings.app.game.feed_rules[-1].max_cost, 50)
            self.assertEqual([rule.min_level for rule in settings.app.game.breed_rules], [1, 3, 5])
            self.assertTrue(all(rule.currency == "corn" for rule in settings.app.game.breed_rules))

    def test_profile_requires_exactly_one_auth_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_file(root / "config.yaml", "api_base_url: https://api.duckmyduck.com\n")
            self.write_file(
                root / "profiles.local.yaml",
                """
profiles:
  - name: main
    init_data: query_id=1&auth_date=2&hash=3
    webapp_url: https://selector.duckmyduck.com/#tgWebAppData=abc
""".strip(),
            )

            with self.assertRaises(ConfigurationError):
                load_settings(root / "config.yaml", root / "profiles.local.yaml")
