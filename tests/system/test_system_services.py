"""system 模块 service 测试。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from gh_ui_cli.system import (
    auth,
    config_paths,
    export,
    feedback,
    health,
    logs,
    paths as paths_mod,
)
from gh_ui_cli.wechat import registry
from gh_ui_cli.wechat.errors import WechatError, WechatInvalidInput


def _resp(status: int, body=None, json_ct: bool = True):
    r = MagicMock()
    r.status_code = status
    r.headers = {"content-type": "application/json"} if json_ct else {"content-type": "text/plain"}
    r.text = str(body) if body else ""
    r.json = MagicMock(return_value=body)
    return r


def _patched_client(response):
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.post.return_value = response
    client.get.return_value = response
    client.request.return_value = response
    return patch("httpx.Client", return_value=client), client


class HealthTest(unittest.TestCase):
    def test_health_ok(self):
        out = health.health()
        self.assertEqual(out["status"], "ok")
        self.assertIn("db_path", out)


class ConfigPathsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._patch = patch.object(paths_mod, "CONFIG_DIR", Path(self._tmp.name))
        self._patch.start()
        self._patch2 = patch.object(paths_mod, "CONFIG_PATH", Path(self._tmp.name) / "config.json")
        self._patch2.start()
        self._patch3 = patch.object(paths_mod, "LEGACY_CONFIG_PATH", Path(self._tmp.name) / "_legacy")
        self._patch3.start()
        # also clear env so it doesn't override
        self._envpatch = patch.dict(
            "os.environ",
            {"DB_PATH": "", "FACTOR_PATH": "", "GH_EXPORT_PATH": ""},
            clear=False,
        )
        self._envpatch.start()

    def tearDown(self):
        self._envpatch.stop()
        self._patch3.stop()
        self._patch2.stop()
        self._patch.stop()
        self._tmp.cleanup()

    def test_get_defaults(self):
        out = config_paths.get_paths()
        self.assertIn("db_path", out)
        self.assertIn("default_start_date", out)

    def test_set_creates_dirs_and_persists(self):
        target = Path(self._tmp.name) / "new_db"
        out = config_paths.set_paths({"db_path": str(target)})
        self.assertEqual(out["db_path"], str(target))
        self.assertTrue(target.exists())
        cfg = json.loads(paths_mod.CONFIG_PATH.read_text())
        self.assertEqual(cfg["db_path"], str(target))

    def test_set_rejects_bad_date(self):
        with self.assertRaises(WechatInvalidInput):
            config_paths.set_paths({"default_start_date": "not-a-date"})


class LogsTest(unittest.TestCase):
    def setUp(self):
        logs._BUFFER.clear()

    def test_add_and_get(self):
        logs.add_log("data", "info", "hello")
        out = logs.get_logs()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["category"], "data")

    def test_filter_by_category(self):
        logs.add_log("data", "info", "a")
        logs.add_log("wechat", "warning", "b")
        out = logs.get_logs(category="wechat")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["message"], "b")

    def test_limit(self):
        for i in range(10):
            logs.add_log("data", "info", f"m{i}")
        out = logs.get_logs(limit=3)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[-1]["message"], "m9")


class AuthTest(unittest.TestCase):
    def test_verify_calls_remote(self):
        ctx, client = _patched_client(_resp(200, {"valid": True}))
        with ctx:
            out = auth.verify("tok")
        self.assertEqual(out, {"valid": True})

    def test_login_validates(self):
        with self.assertRaises(WechatInvalidInput):
            auth.login("", "")

    def test_register_requires_fields(self):
        with self.assertRaises(WechatInvalidInput):
            auth.register({"email": "a"})

    def test_active_token_requires_access(self):
        with patch.dict("os.environ", {"GH_ACCESS_TOKEN": ""}, clear=False):
            with self.assertRaises(WechatInvalidInput):
                auth.active_token()


class FeedbackTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._patch = patch.object(paths_mod, "CONFIG_DIR", Path(self._tmp.name))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_validates_content(self):
        with self.assertRaises(WechatInvalidInput):
            feedback.submit({"content": "   "})

    def test_falls_back_to_local_when_network_fails(self):
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.post.side_effect = Exception("offline")
        with patch("httpx.Client", return_value=client):
            out = feedback.submit({"content": "hello"})
        self.assertFalse(out["remote"])
        self.assertTrue(Path(out["file"]).exists())


class ExportTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._env = patch.dict("os.environ", {"GH_EXPORT_PATH": self._tmp.name}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_validates_inputs(self):
        with self.assertRaises(WechatInvalidInput):
            export.export_excel({"data": "no", "columns": ["a"]})
        with self.assertRaises(WechatInvalidInput):
            export.export_excel({"data": [], "columns": []})

    def test_export_writes_xlsx(self):
        out = export.export_excel({
            "data": [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}],
            "columns": ["a", "b"],
            "filename": "t",
        })
        self.assertTrue(Path(out["path"]).exists())
        self.assertTrue(out["path"].endswith(".xlsx"))

    def test_export_avoids_overwrite(self):
        out1 = export.export_excel({"data": [], "columns": ["a"], "filename": "t"})
        out2 = export.export_excel({"data": [], "columns": ["a"], "filename": "t"})
        self.assertNotEqual(out1["path"], out2["path"])


class CapabilitiesTest(unittest.TestCase):
    def test_all_registered(self):
        ids = set(registry.list_ids())
        expected = {
            "op:system:health",
            "op:system:config-paths-get",
            "op:system:config-paths-set",
            "op:system:logs-get",
            "op:system:logs-add",
            "op:system:auth-verify",
            "op:system:auth-login",
            "op:system:auth-register",
            "op:system:auth-active-token",
            "op:system:feedback-submit",
            "op:system:export-excel",
        }
        missing = expected - ids
        self.assertFalse(missing, f"missing: {missing}")


if __name__ == "__main__":
    unittest.main()
