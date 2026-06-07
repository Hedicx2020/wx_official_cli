from __future__ import annotations

import io
import json
import os
import sys
import tarfile
import zipfile
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
        self.assertNotIn('"fastapi', pyproject)
        self.assertNotIn('"uvicorn', pyproject)
        self.assertNotIn('"pandas', pyproject)
        self.assertNotIn('"akshare', pyproject)
        self.assertNotIn('"pyecharts', pyproject)
        self.assertIn(
            'wx-official-cli = "gh_ui_cli.wx_official_cli:main"',
            pyproject,
        )

    def test_module_can_run_as_console_script_target(self):
        with patch.object(sys, "argv", ["wx-official-cli", "--help"]):
            rc, out, err = self._run(["--help"])

        self.assertEqual(rc, 0, msg=err)
        self.assertIn("wx-official-cli", out)

    def test_package_main_delegates_to_simplified_entry(self):
        main_file = Path("src/gh_ui_cli/__main__.py").read_text(encoding="utf-8")

        self.assertIn("from .wx_official_cli import main", main_file)
        self.assertNotIn("from .cli import main", main_file)

    def test_wechat_package_init_only_loads_official_article_chain(self):
        init_file = Path("src/gh_ui_cli/wechat/__init__.py").read_text(encoding="utf-8")

        self.assertIn("from .services import articles", init_file)
        self.assertIn("from .services import keys", init_file)
        self.assertNotIn("from .services import messages", init_file)
        self.assertNotIn("from .services import contacts", init_file)
        self.assertNotIn("from .services import images", init_file)
        self.assertNotIn("from .services import llm", init_file)
        self.assertNotIn("from .services import pdf_report", init_file)
        self.assertNotIn("from .services import stock_review", init_file)

    def test_built_wheel_excludes_unrelated_business_packages(self):
        wheel = _latest_wheel()
        sdist = _latest_sdist()
        unrelated_prefixes = (
            "gh_ui_cli/data/",
            "gh_ui_cli/factor/",
            "gh_ui_cli/backtest/",
            "gh_ui_cli/ai/",
            "gh_ui_cli/remote/",
            "gh_ui_cli/system/",
        )
        unrelated_modules = (
            "gh_ui_cli/api_client.py",
            "gh_ui_cli/cli.py",
            "gh_ui_cli/coverage_audit.py",
            "gh_ui_cli/dependencies.py",
            "gh_ui_cli/invoke.py",
            "gh_ui_cli/manifest.py",
            "gh_ui_cli/profile.py",
            "gh_ui_cli/runtime_verify.py",
            "gh_ui_cli/smoke.py",
            "gh_ui_cli/source.py",
            "gh_ui_cli/verification_plan.py",
            "gh_ui_cli/verify.py",
            "gh_ui_cli/wechat/adapters/dat_to_image.py",
            "gh_ui_cli/wechat/adapters/llm_client.py",
            "gh_ui_cli/wechat/adapters/messages.py",
            "gh_ui_cli/wechat/adapters/pdf_reporter.py",
            "gh_ui_cli/wechat/adapters/stock_filter.py",
            "gh_ui_cli/wechat/adapters/stock_kline.py",
            "gh_ui_cli/wechat/adapters/stock_selection.py",
            "gh_ui_cli/wechat/services/contacts.py",
            "gh_ui_cli/wechat/services/images.py",
            "gh_ui_cli/wechat/services/llm.py",
            "gh_ui_cli/wechat/services/messages.py",
            "gh_ui_cli/wechat/services/pdf_report.py",
            "gh_ui_cli/wechat/services/stock_review.py",
        )

        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            entry_points = archive.read("wx_official_cli-0.1.0.dist-info/entry_points.txt").decode()
            metadata = archive.read("wx_official_cli-0.1.0.dist-info/METADATA").decode()

        self.assertIn("wx-official-cli = gh_ui_cli.wx_official_cli:main", entry_points)
        self.assertNotIn("gh-ui =", entry_points)
        self.assertFalse(
            any(name.startswith(unrelated_prefixes) for name in names),
            "wheel should not package data/factor/backtest/ai/remote/system modules",
        )
        for module_name in unrelated_modules:
            self.assertNotIn(module_name, names)
        self.assertNotIn("Requires-Dist: fastapi", metadata)
        self.assertNotIn("Requires-Dist: uvicorn", metadata)
        self.assertNotIn("Requires-Dist: pandas", metadata)
        self.assertNotIn("Requires-Dist: akshare", metadata)

        with tarfile.open(sdist) as archive:
            sdist_names = set(archive.getnames())
        self.assertFalse(
            any(f"/src/{prefix}" in name for name in sdist_names for prefix in unrelated_prefixes),
            "sdist should not package data/factor/backtest/ai/remote/system modules",
        )
        for module_name in unrelated_modules:
            self.assertFalse(any(name.endswith(f"/src/{module_name}") for name in sdist_names), module_name)


def _latest_wheel() -> Path:
    wheels = sorted(Path("dist").glob("wx_official_cli-*.whl"))
    if not wheels:
        raise AssertionError("run `uv build` before checking wheel contents")
    return wheels[-1]


def _latest_sdist() -> Path:
    sdists = sorted(Path("dist").glob("wx_official_cli-*.tar.gz"))
    if not sdists:
        raise AssertionError("run `uv build` before checking sdist contents")
    return sdists[-1]


if __name__ == "__main__":
    unittest.main()
