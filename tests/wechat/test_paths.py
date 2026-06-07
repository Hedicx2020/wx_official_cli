from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gh_ui_cli.wechat import paths


class WechatPathsTest(unittest.TestCase):
    def test_data_dir_uses_env_when_set(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp}, clear=False):
                p = paths.data_dir()
                self.assertEqual(p, Path(tmp).resolve())
                self.assertTrue(p.exists())

    def test_data_dir_default(self):
        with TemporaryDirectory() as tmp:
            env = {"GH_WX_DATA_DIR": "", "HOME": tmp}
            with patch.dict("os.environ", env, clear=False):
                p = paths.data_dir()
                self.assertTrue(p.is_absolute())
                self.assertTrue(p.exists())
                self.assertEqual(p.name, ".wx_official_cli")

    def test_config_path_under_data_dir(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp}, clear=False):
                p = paths.config_path()
                self.assertEqual(p.parent, Path(tmp).resolve())
                self.assertEqual(p.name, "config.json")

    def test_decrypt_cache_dir(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp}, clear=False):
                p = paths.decrypt_cache_dir()
                self.assertEqual(p.name, "decrypted")
                self.assertTrue(p.exists())

    def test_keys_path(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp}, clear=False):
                p = paths.keys_path()
                self.assertEqual(p.name, "all_keys.json")

if __name__ == "__main__":
    unittest.main()
