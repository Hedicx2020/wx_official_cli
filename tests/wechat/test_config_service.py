from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gh_ui_cli.wechat.services import config as config_svc


class ConfigServiceTest(unittest.TestCase):
    def _env(self, tmp: str):
        return patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp}, clear=False)

    def test_load_returns_defaults_when_file_missing(self):
        with TemporaryDirectory() as tmp:
            with self._env(tmp):
                got = config_svc.load()
        self.assertEqual(got["database_password"], "")
        self.assertEqual(got["wechat_files_path"], "")
        self.assertEqual(len(got), 3)

    def test_save_persists_patch_and_updates_last_updated(self):
        with TemporaryDirectory() as tmp:
            with self._env(tmp):
                saved = config_svc.save({"wechat_files_path": "/wx"})
                self.assertEqual(saved["wechat_files_path"], "/wx")
                self.assertNotEqual(saved["last_updated"], "")
                loaded = config_svc.load()
        self.assertEqual(loaded["wechat_files_path"], "/wx")
        self.assertEqual(loaded["last_updated"], saved["last_updated"])

    def test_save_ignores_unknown_keys(self):
        with TemporaryDirectory() as tmp:
            with self._env(tmp):
                saved = config_svc.save({"unknown_key": "x", "wechat_files_path": "/wx"})
        self.assertNotIn("unknown_key", saved)
        self.assertEqual(saved["wechat_files_path"], "/wx")

    def test_save_ignores_none_values(self):
        with TemporaryDirectory() as tmp:
            with self._env(tmp):
                config_svc.save({"wechat_files_path": "/wx"})
                config_svc.save({"wechat_files_path": None})
                loaded = config_svc.load()
        self.assertEqual(loaded["wechat_files_path"], "/wx")

    def test_load_returns_defaults_when_file_corrupt(self):
        with TemporaryDirectory() as tmp:
            with self._env(tmp):
                Path(tmp, "config.json").write_text("not json", encoding="utf-8")
                loaded = config_svc.load()
        self.assertEqual(loaded["database_password"], "")

    def test_save_writes_atomically(self):
        with TemporaryDirectory() as tmp:
            with self._env(tmp):
                config_svc.save({"wechat_files_path": "/wx"})
                disk = json.loads(Path(tmp, "config.json").read_text(encoding="utf-8"))
        self.assertEqual(disk["wechat_files_path"], "/wx")

    def test_save_coerces_non_string_to_string(self):
        with TemporaryDirectory() as tmp:
            with self._env(tmp):
                saved = config_svc.save({"database_password": 1234})
        self.assertEqual(saved["database_password"], "1234")


if __name__ == "__main__":
    unittest.main()
