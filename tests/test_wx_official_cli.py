from __future__ import annotations

import io
import json
import os
import subprocess
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
        self.assertNotIn("--no-fetch-html", out)
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

    def test_save_creates_parent_directories_for_agent_report_paths(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "reports" / "manifest.json"
            try:
                rc, out, err = self._run(["manifest", "--save", str(target)])
            except FileNotFoundError as exc:
                self.fail(f"--save should create parent directories for agent report paths: {exc}")

            self.assertEqual(rc, 0, msg=err)
            self.assertTrue(target.exists())
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), json.loads(out))

    def test_pyproject_points_console_script_to_simplified_entry(self):
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('name = "wx-official-cli"', pyproject)
        self.assertNotIn('gh-ui = "gh_ui_cli.cli:main"', pyproject)
        self.assertNotIn('"fastapi', pyproject)
        self.assertNotIn('"uvicorn', pyproject)
        self.assertNotIn('"httpx', pyproject)
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

        self.assertIn('__all__ = ["errors", "models", "paths"]', init_file)
        self.assertNotIn("registry", init_file)
        self.assertNotIn("dispatch", init_file)
        self.assertNotIn("weread", init_file)
        self.assertNotIn("from .services import messages", init_file)
        self.assertNotIn("from .services import contacts", init_file)
        self.assertNotIn("from .services import images", init_file)
        self.assertNotIn("from .services import llm", init_file)
        self.assertNotIn("from .services import pdf_report", init_file)
        self.assertNotIn("from .services import stock_review", init_file)

    def test_source_tree_is_only_wx_official_cache_export(self):
        allowed_files = {
            "src/gh_ui_cli/__init__.py",
            "src/gh_ui_cli/__main__.py",
            "src/gh_ui_cli/io.py",
            "src/gh_ui_cli/wx_official_cli.py",
            "src/gh_ui_cli/wechat/__init__.py",
            "src/gh_ui_cli/wechat/errors.py",
            "src/gh_ui_cli/wechat/models.py",
            "src/gh_ui_cli/wechat/paths.py",
            "src/gh_ui_cli/wechat/adapters/__init__.py",
            "src/gh_ui_cli/wechat/adapters/article_store.py",
            "src/gh_ui_cli/wechat/adapters/crypto.py",
            "src/gh_ui_cli/wechat/adapters/decrypt.py",
            "src/gh_ui_cli/wechat/adapters/key_scan.py",
            "src/gh_ui_cli/wechat/adapters/local_articles.py",
            "src/gh_ui_cli/wechat/adapters/scanner_win.py",
            "src/gh_ui_cli/wechat/services/__init__.py",
            "src/gh_ui_cli/wechat/services/config.py",
            "src/gh_ui_cli/wechat/services/keys.py",
            "src/gh_ui_cli/wechat/services/articles/__init__.py",
            "src/gh_ui_cli/wechat/services/articles/store.py",
            "src/gh_ui_cli/wechat/services/articles/sync.py",
        }
        actual_files = {
            str(path)
            for path in Path("src/gh_ui_cli").rglob("*.py")
            if "__pycache__" not in path.parts
        }

        self.assertEqual(actual_files, allowed_files)

    def test_repository_tracks_only_wx_official_cache_export_files(self):
        tracked_files = set(
            subprocess.check_output(["git", "ls-files"], text=True, encoding="utf-8").splitlines()
        )
        allowed_files = {
            ".gitignore",
            ".github/workflows/ci.yml",
            "MANIFEST.in",
            "README.md",
            "pyproject.toml",
            "scripts/verify_windows_cache.ps1",
            "src/gh_ui_cli/__init__.py",
            "src/gh_ui_cli/__main__.py",
            "src/gh_ui_cli/io.py",
            "src/gh_ui_cli/wx_official_cli.py",
            "src/gh_ui_cli/wechat/__init__.py",
            "src/gh_ui_cli/wechat/errors.py",
            "src/gh_ui_cli/wechat/models.py",
            "src/gh_ui_cli/wechat/paths.py",
            "src/gh_ui_cli/wechat/adapters/__init__.py",
            "src/gh_ui_cli/wechat/adapters/article_store.py",
            "src/gh_ui_cli/wechat/adapters/crypto.py",
            "src/gh_ui_cli/wechat/adapters/decrypt.py",
            "src/gh_ui_cli/wechat/adapters/key_scan.py",
            "src/gh_ui_cli/wechat/adapters/local_articles.py",
            "src/gh_ui_cli/wechat/adapters/scanner_win.py",
            "src/gh_ui_cli/wechat/services/__init__.py",
            "src/gh_ui_cli/wechat/services/config.py",
            "src/gh_ui_cli/wechat/services/keys.py",
            "src/gh_ui_cli/wechat/services/articles/__init__.py",
            "src/gh_ui_cli/wechat/services/articles/store.py",
            "src/gh_ui_cli/wechat/services/articles/sync.py",
            "tests/test_ci_workflow.py",
            "tests/test_wx_official_cli.py",
            "tests/wechat/__init__.py",
            "tests/wechat/test_articles_service.py",
            "tests/wechat/test_cli_integration.py",
            "tests/wechat/test_config_service.py",
            "tests/wechat/test_crypto.py",
            "tests/wechat/test_errors.py",
            "tests/wechat/test_key_scan.py",
            "tests/wechat/test_keys_service.py",
            "tests/wechat/test_models.py",
            "tests/wechat/test_paths.py",
            "tests/wechat/test_scanner_win.py",
            "uv.lock",
        }

        self.assertEqual(tracked_files, allowed_files)

    def test_windows_agent_verify_script_uses_wx_official_cli_only(self):
        script = Path("scripts/verify_windows_cache.ps1").read_text(encoding="utf-8")

        self.assertIn("param(", script)
        self.assertIn("wx-official-cli status", script)
        self.assertIn("wx-official-cli verify", script)
        self.assertIn("verify-wechat-cache-windows.json", script)
        self.assertNotIn("gh-ui", script)
        self.assertNotIn("password-auto", script)
        self.assertNotIn("articles-cache-export", script)

    def test_windows_agent_verify_script_supports_windows_powershell_51(self):
        script = Path("scripts/verify_windows_cache.ps1").read_text(encoding="utf-8")

        self.assertIn("Get-Variable -Name IsWindows", script)
        self.assertIn("[System.Environment]::OSVersion.Platform", script)
        self.assertNotIn("if (-not $IsWindows)", script)

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
            "gh_ui_cli/wechat/adapters/_mac_helper.py",
            "gh_ui_cli/wechat/adapters/llm_client.py",
            "gh_ui_cli/wechat/adapters/messages.py",
            "gh_ui_cli/wechat/adapters/pdf_reporter.py",
            "gh_ui_cli/wechat/adapters/scanner_mac.py",
            "gh_ui_cli/wechat/adapters/stock_filter.py",
            "gh_ui_cli/wechat/adapters/stock_kline.py",
            "gh_ui_cli/wechat/adapters/stock_selection.py",
            "gh_ui_cli/wechat/adapters/weread_client.py",
            "gh_ui_cli/wechat/dispatch.py",
            "gh_ui_cli/wechat/registry.py",
            "gh_ui_cli/wechat/services/articles/accounts.py",
            "gh_ui_cli/wechat/services/articles/categories.py",
            "gh_ui_cli/wechat/services/articles/login.py",
            "gh_ui_cli/wechat/services/articles/settings.py",
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
        self.assertNotIn("Requires-Dist: httpx", metadata)
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
