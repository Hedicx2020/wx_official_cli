from __future__ import annotations

import unittest

from gh_ui_cli.wechat import models


class WechatModelsTest(unittest.TestCase):
    def test_default_config_has_only_cache_export_keys(self):
        self.assertEqual(len(models.DEFAULT_CONFIG), 3)

    def test_default_config_contains_known_fields(self):
        for k in (
            "database_password",
            "wechat_files_path",
            "last_updated",
        ):
            self.assertIn(k, models.DEFAULT_CONFIG)

    def test_default_config_values_are_strings(self):
        for value in models.DEFAULT_CONFIG.values():
            self.assertIsInstance(value, str)


if __name__ == "__main__":
    unittest.main()
