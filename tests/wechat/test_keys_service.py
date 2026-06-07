"""密钥服务测试 - 路径检测、读写 all_keys.json、password-status。"""

from __future__ import annotations

import json
import os
import types
import unittest
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gh_ui_cli.wechat.errors import KeyNotFound
from gh_ui_cli.wechat.services import keys as keys_svc
from tests.wechat.test_crypto import _build_encrypted_db


class KeysServiceTest(unittest.TestCase):
    def _env(self, tmp: str, **extras: str):
        return patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp, **extras}, clear=False)

    def test_load_returns_empty_when_no_file(self):
        with TemporaryDirectory() as tmp:
            with self._env(tmp):
                self.assertEqual(keys_svc.load_keys(), {})

    def test_save_and_load_round_trip(self):
        with TemporaryDirectory() as tmp:
            with self._env(tmp):
                keys_svc.save_keys({"abc": "deadbeef" * 8})
                self.assertEqual(keys_svc.load_keys(), {"abc": "deadbeef" * 8})

    def test_load_corrupt_returns_empty(self):
        with TemporaryDirectory() as tmp:
            with self._env(tmp):
                from gh_ui_cli.wechat import paths
                paths.keys_path().write_text("garbage")
                self.assertEqual(keys_svc.load_keys(), {})


class DetectPlatformPathsTest(unittest.TestCase):
    def test_darwin_with_db_storage(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_x/db_storage"
            root.mkdir(parents=True)
            with patch.dict("os.environ", {"HOME": str(home)}, clear=False):
                with patch("platform.system", return_value="Darwin"):
                    info = keys_svc.detect_platform_paths()
        self.assertEqual(info["platform"], "darwin")
        self.assertTrue(info["detected_path"].endswith("db_storage"))

    def test_windows_detects_wechat_files_under_userprofile_documents(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / "Documents" / "WeChat Files" / "wxid_x" / "db_storage"
            root.mkdir(parents=True)
            with patch.dict("os.environ", {"USERPROFILE": str(home)}, clear=True):
                with patch("platform.system", return_value="Windows"):
                    info = keys_svc.detect_platform_paths()
        self.assertEqual(info["platform"], "windows")
        self.assertEqual(info["detected_path"], str(root))

    def test_windows_keeps_searching_when_first_existing_candidate_has_no_db_storage(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "Documents" / "WeChat Files").mkdir(parents=True)
            root = home / "AppData" / "Roaming" / "Tencent" / "WeChat" / "WeChat Files" / "wxid_x" / "db_storage"
            root.mkdir(parents=True)
            with patch.dict("os.environ", {"USERPROFILE": str(home)}, clear=True):
                with patch("platform.system", return_value="Windows"):
                    info = keys_svc.detect_platform_paths()
        self.assertEqual(info["detected_path"], str(root))

    def test_windows_detects_custom_wechat_files_path_from_registry(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "User"
            custom = Path(tmp) / "CustomWeChatData"
            home.mkdir()
            root = custom / "WeChat Files" / "wxid_custom" / "db_storage"
            root.mkdir(parents=True)

            def open_key(root_key: str, subkey: str) -> str:
                if root_key == "HKCU" and subkey == r"Software\Tencent\WeChat":
                    return subkey
                raise FileNotFoundError(subkey)

            def query_value_ex(_key: str, value_name: str) -> tuple[str, int]:
                if value_name == "FileSavePath":
                    return "%WECHAT_CUSTOM_ROOT%", 1
                raise FileNotFoundError(value_name)

            fake_winreg = types.SimpleNamespace(
                HKEY_CURRENT_USER="HKCU",
                HKEY_LOCAL_MACHINE="HKLM",
                OpenKey=open_key,
                QueryValueEx=query_value_ex,
                CloseKey=lambda _key: None,
            )
            env = {
                "USERPROFILE": str(home),
                "WECHAT_CUSTOM_ROOT": str(custom),
            }
            with patch.dict("os.environ", env, clear=True):
                with patch.dict("sys.modules", {"winreg": fake_winreg}):
                    with patch("platform.system", return_value="Windows"):
                        info = keys_svc.detect_platform_paths()
        self.assertEqual(info["detected_path"], str(root))

    def test_windows_detects_wechat_files_under_redirected_documents_registry(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "User"
            redirected_docs = Path(tmp) / "RedirectedDocuments"
            home.mkdir()
            root = redirected_docs / "WeChat Files" / "wxid_docs" / "db_storage"
            root.mkdir(parents=True)

            def open_key(root_key: str, subkey: str) -> str:
                if root_key == "HKCU" and subkey == r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders":
                    return subkey
                raise FileNotFoundError(subkey)

            def query_value_ex(_key: str, value_name: str) -> tuple[str, int]:
                if value_name == "Personal":
                    return "%REDIRECTED_DOCS%", 1
                raise FileNotFoundError(value_name)

            fake_winreg = types.SimpleNamespace(
                HKEY_CURRENT_USER="HKCU",
                HKEY_LOCAL_MACHINE="HKLM",
                OpenKey=open_key,
                QueryValueEx=query_value_ex,
                CloseKey=lambda _key: None,
            )
            env = {
                "USERPROFILE": str(home),
                "REDIRECTED_DOCS": str(redirected_docs),
            }
            with patch.dict("os.environ", env, clear=True):
                with patch.dict("sys.modules", {"winreg": fake_winreg}):
                    with patch("platform.system", return_value="Windows"):
                        info = keys_svc.detect_platform_paths()
        self.assertEqual(info["detected_path"], str(root))

    def test_unsupported_platform(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"HOME": tmp}, clear=False):
                with patch("platform.system", return_value="OS/2"):
                    info = keys_svc.detect_platform_paths()
        self.assertEqual(info["platform"], "os/2")
        self.assertEqual(info["detected_path"], "")


class PasswordStatusTest(unittest.TestCase):
    def test_status_includes_summary(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp, "HOME": tmp}, clear=False):
                with patch("platform.system", return_value="Darwin"):
                    out = keys_svc.password_status()
        self.assertIn("platform", out)
        self.assertIn("detected_path", out)
        self.assertIn("configured_path", out)
        self.assertIn("has_password", out)
        self.assertIn("key_count", out)
        self.assertFalse(out["has_password"])
        self.assertEqual(out["key_count"], 0)

    def test_status_reflects_stored_keys(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp, "HOME": tmp}, clear=False):
                keys_svc.save_keys({"salt1": "ff" * 32, "salt2": "ee" * 32})
                from gh_ui_cli.wechat.services import config as config_svc
                config_svc.save({"database_password": "aa" * 32})
                with patch("platform.system", return_value="Darwin"):
                    out = keys_svc.password_status()
        self.assertTrue(out["has_password"])
        self.assertEqual(out["key_count"], 2)

    def test_status_reports_windows_wechat_process_visibility(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp, "USERPROFILE": tmp}, clear=False):
                with patch("platform.system", return_value="Windows"):
                    with patch(
                        "gh_ui_cli.wechat.adapters.scanner_win._list_weixin_pids",
                        return_value=[(123, 456000), (456, 120000)],
                    ):
                        out = keys_svc.password_status()

        self.assertTrue(out["wechat_process_running"])
        self.assertEqual(out["wechat_process_count"], 2)
        self.assertEqual(out["wechat_process_pids"], [123, 456])


class ResolveDbDirTest(unittest.TestCase):
    def test_uses_configured_path_when_exists(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "wx"
            target.mkdir()
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp, "HOME": tmp}, clear=False):
                from gh_ui_cli.wechat.services import config as config_svc
                config_svc.save({"wechat_files_path": str(target)})
                resolved = keys_svc.resolve_db_dir()
        self.assertEqual(resolved, str(target))

    def test_falls_back_to_platform_detect(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_x/db_storage"
            root.mkdir(parents=True)
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp, "HOME": str(home)}, clear=False):
                with patch("platform.system", return_value="Darwin"):
                    resolved = keys_svc.resolve_db_dir()
        self.assertTrue(resolved.endswith("db_storage"))


class EnsureDecryptedTest(unittest.TestCase):
    def test_missing_key_hint_uses_wx_official_cli(self):
        with TemporaryDirectory() as tmp:
            db_dir = Path(tmp) / "db_storage"
            db_dir.mkdir()
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp, "HOME": tmp}, clear=False):
                with patch("gh_ui_cli.wechat.services.keys.resolve_db_dir", return_value=str(db_dir)):
                    with self.assertRaises(KeyNotFound) as ctx:
                        keys_svc.ensure_decrypted()

        self.assertIn("wx-official-cli verify", ctx.exception.hint or "")
        self.assertIn("--no-auto-password", ctx.exception.hint or "")
        self.assertNotIn("password-auto", ctx.exception.hint or "")

    def test_stale_single_database_password_raises_key_not_found(self):
        with TemporaryDirectory() as tmp:
            db_dir = Path(tmp) / "db_storage"
            db_dir.mkdir()
            encrypted_db, _salt = _build_encrypted_db(secrets.token_bytes(32), pages=1)
            (db_dir / "message_0.db").write_bytes(encrypted_db)
            stale_key = "00" * 32
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp, "HOME": tmp}, clear=False):
                from gh_ui_cli.wechat.services import config as config_svc

                config_svc.save({"wechat_files_path": str(db_dir), "database_password": stale_key})
                with self.assertRaises(KeyNotFound) as ctx:
                    keys_svc.ensure_decrypted()

        self.assertIn("不匹配", str(ctx.exception))
        self.assertIn("wx-official-cli verify", ctx.exception.hint or "")


if __name__ == "__main__":
    unittest.main()
