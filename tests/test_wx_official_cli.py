from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class WxOfficialCliTest(unittest.TestCase):
    def _run(self, argv: list[str], env: dict[str, str] | None = None) -> tuple[int, str, str]:
        from gh_ui_cli import wx_official_cli

        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = 0
        with patch.dict(os.environ, env or {}, clear=False):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                try:
                    wx_official_cli.main(argv)
                except SystemExit as exc:
                    rc = int(exc.code or 0)
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_help_is_only_about_official_account_export(self):
        rc, out, err = self._run(["--help"])

        self.assertEqual(rc, 0, msg=err)
        self.assertIn("wx-official-cli", out)
        self.assertIn("export", out)
        self.assertIn("verify", out)
        self.assertIn("status", out)
        self.assertNotIn("data", out)
        self.assertNotIn("factor", out)
        self.assertNotIn("backtest", out)
        self.assertNotIn("gh_quant_ui", out)

    def test_export_command_calls_cache_export_service(self):
        with TemporaryDirectory() as tmp:
            result = {"status": "ok", "account": {"name": "Alpha 研究"}, "article_count": 1}
            with patch(
                "gh_ui_cli.wechat.services.articles.sync.export_cached_by_account",
                return_value=result,
            ) as export:
                rc, out, err = self._run(
                    [
                        "export",
                        "Alpha 研究",
                        "--limit",
                        "5",
                        "--output-dir",
                        str(Path(tmp) / "out"),
                        "--no-fetch-html",
                        "--no-auto-password",
                    ],
                    {"GH_WX_DATA_DIR": tmp},
                )

        self.assertEqual(rc, 0, msg=err)
        self.assertEqual(json.loads(out), result)
        export.assert_called_once_with(
            "Alpha 研究",
            limit=5,
            output_dir=str(Path(tmp) / "out"),
            scan_first=True,
            auto_password=False,
            fetch_html=False,
        )

    def test_crawl_is_export_alias_for_agents(self):
        with patch(
            "gh_ui_cli.wechat.services.articles.sync.export_cached_by_account",
            return_value={"status": "ok", "article_count": 0},
        ) as export:
            rc, out, err = self._run(["crawl", "Alpha", "--no-scan"])

        self.assertEqual(rc, 0, msg=err)
        self.assertEqual(json.loads(out)["status"], "ok")
        self.assertFalse(export.call_args.kwargs["scan_first"])

    def test_verify_strict_exits_nonzero_when_goal_evidence_fails(self):
        with patch(
            "gh_ui_cli.wechat.services.articles.sync.verify_cache_export",
            return_value={"ok": False, "goal_evidence": {"wechat_cache_verified": False}},
        ):
            rc, out, _err = self._run(["verify", "Alpha", "--strict"])

        self.assertEqual(rc, 1)
        self.assertFalse(json.loads(out)["ok"])

    def test_status_outputs_wechat_cache_status(self):
        status = {
            "platform": "windows",
            "detected_path": "C:/Users/me/Documents/WeChat Files/wxid/db_storage",
            "configured_path": "",
            "has_password": True,
            "key_count": 1,
        }
        with patch("gh_ui_cli.wechat.services.keys.password_status", return_value=status):
            rc, out, err = self._run(["status"])

        self.assertEqual(rc, 0, msg=err)
        self.assertEqual(json.loads(out), status)

    def test_manifest_exposes_only_agent_direct_wechat_commands(self):
        rc, out, err = self._run(["manifest"])

        self.assertEqual(rc, 0, msg=err)
        manifest = json.loads(out)
        commands = [entry["command"] for entry in manifest["entries"]]
        self.assertEqual(manifest["category"], "wx_official")
        self.assertTrue(commands)
        self.assertTrue(all(command.startswith("wx-official-cli ") for command in commands))
        self.assertIn("wx-official-cli export <ACCOUNT_NAME>", commands)
        self.assertNotIn("gh-ui", out)
        self.assertNotIn("data", out)
        self.assertNotIn("factor", out)
        self.assertNotIn("backtest", out)

    def test_pyproject_points_console_script_to_simplified_entry(self):
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('name = "wx-official-cli"', pyproject)
        self.assertNotIn('gh-ui = "gh_ui_cli.cli:main"', pyproject)
        self.assertIn(
            'wx-official-cli = "gh_ui_cli.wx_official_cli:main"',
            pyproject,
        )

    def test_module_can_run_as_console_script_target(self):
        with patch.object(sys, "argv", ["wx-official-cli", "--help"]):
            rc, out, err = self._run(["--help"])

        self.assertEqual(rc, 0, msg=err)
        self.assertIn("wx-official-cli", out)


if __name__ == "__main__":
    unittest.main()
