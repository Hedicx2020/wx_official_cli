from __future__ import annotations

import json
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
                self.assertEqual(p.name, "wechat")

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

    def test_local_data_dir_reads_db_path_env(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "my_data"
            target.mkdir()
            with patch.dict("os.environ", {"DB_PATH": str(target)}, clear=False):
                p = paths.local_data_dir()
                self.assertEqual(p, target)

    def test_local_data_dir_reads_quant_ui_config(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".gh_quant_ui").mkdir()
            target = home / "custom_db"
            target.mkdir()
            (home / ".gh_quant_ui" / "config.json").write_text(
                json.dumps({"db_path": str(target)}), encoding="utf-8"
            )
            env = {"DB_PATH": "", "HOME": str(home)}
            with patch.dict("os.environ", env, clear=False):
                p = paths.local_data_dir()
                self.assertEqual(p, target)


if __name__ == "__main__":
    unittest.main()
