import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from gh_ui_cli.cli import (
    _preferred_command_parse_audit,
    build_config,
    build_parser,
    handle_ci_log_report,
    handle_ci_status,
    handle_deps,
    handle_doctor,
    handle_feedback_submit,
    handle_health,
    handle_invoke,
    handle_remote_me,
    handle_remote_token_generate,
    handle_remote_token_revoke,
    handle_remote_tokens,
    handle_routes,
    handle_verify,
    handle_verify_bundle,
    handle_verify_plan,
    handle_verify_merge,
)
from gh_ui_cli.profile import save_profile


class CliParserTest(unittest.TestCase):
    def test_global_api_base_survives_subcommand_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["--api-base", "http://127.0.0.1:8765", "smoke"])

        config = build_config(args)

        self.assertEqual(config.api_base, "http://127.0.0.1:8765")

    def test_routes_with_api_base_uses_openapi_without_source_import(self):
        parser = build_parser()
        args = parser.parse_args(["--api-base", "http://127.0.0.1:8765", "routes"])
        client = _FakeClient(
            {
                ("GET", "/openapi.json", ""): {
                    "paths": {"/api/health": {"get": {"operationId": "health"}}}
                }
            }
        )

        with (
            patch("gh_ui_cli.cli.create_api_client", return_value=client),
            patch("gh_ui_cli.cli.route_inventory", side_effect=AssertionError("source should not load")),
            redirect_stdout(StringIO()) as stdout,
        ):
            handle_routes(args)

        self.assertIn('"path": "/api/health"', stdout.getvalue())
        self.assertEqual(client.calls, [("GET", "/openapi.json", "")])

    def test_doctor_with_api_base_reports_http_mode_without_source_import(self):
        parser = build_parser()
        args = parser.parse_args(["--api-base", "http://127.0.0.1:8765", "doctor"])
        client = _FakeClient(
            {
                ("GET", "/health", "/api"): {"status": "ok", "db_path": "/tmp/local_data"},
                ("GET", "/openapi.json", ""): {
                    "paths": {"/api/health": {"get": {"operationId": "health"}}}
                },
            }
        )

        with (
            patch("gh_ui_cli.cli.create_api_client", return_value=client),
            patch("gh_ui_cli.cli.load_main_module", side_effect=AssertionError("source should not load")),
            redirect_stdout(StringIO()) as stdout,
        ):
            handle_doctor(args)

        output = stdout.getvalue()
        self.assertIn('"mode": "api_base"', output)
        self.assertIn('"route_operations": 1', output)
        self.assertEqual(
            client.calls,
            [("GET", "/health", "/api"), ("GET", "/openapi.json", "")],
        )

    def test_manifest_cli_category_does_not_require_source_or_sidecar(self):
        parser = build_parser()
        args = parser.parse_args(["manifest", "--category", "cli"])

        with (
            patch("gh_ui_cli.cli._coverage_audit", side_effect=AssertionError("source should not load")),
            patch("gh_ui_cli.cli._http_coverage_audit", side_effect=AssertionError("sidecar should not load")),
            redirect_stdout(StringIO()) as stdout,
        ):
            args.func(args)

        output = json.loads(stdout.getvalue())
        self.assertEqual(output["category"], "cli")
        self.assertIn("cli:profile:set", {entry["id"] for entry in output["entries"]})

    def test_deps_uses_explicit_requirements_without_source_import(self):
        parser = build_parser()
        args = parser.parse_args(["deps", "--requirements", "/tmp/requirements.txt"])

        with (
            patch("gh_ui_cli.cli.resolve_source_root", side_effect=AssertionError("source should not load")),
            patch("gh_ui_cli.cli.build_dependency_report", return_value={"ok": True, "missing": []}) as report,
            redirect_stdout(StringIO()) as stdout,
        ):
            handle_deps(args)

        report.assert_called_once()
        self.assertIn('"ok": true', stdout.getvalue())

    def test_deps_passes_requested_platform_to_dependency_report(self):
        parser = build_parser()
        args = parser.parse_args(["deps", "--requirements", "/tmp/requirements.txt", "--platform", "win32"])

        with (
            patch("gh_ui_cli.cli.build_dependency_report", return_value={"ok": True, "missing": []}) as report,
            redirect_stdout(StringIO()),
        ):
            handle_deps(args)

        report.assert_called_once()
        self.assertEqual(report.call_args.kwargs, {"platform_name": "win32"})

    def test_deps_strict_exits_nonzero_when_dependencies_are_missing(self):
        parser = build_parser()
        args = parser.parse_args(["deps", "--requirements", "/tmp/requirements.txt", "--strict"])

        with (
            patch("gh_ui_cli.cli.build_dependency_report", return_value={"ok": False, "missing": [{"name": "pandas"}]}),
            redirect_stdout(StringIO()) as stdout,
        ):
            with self.assertRaises(SystemExit) as exc:
                handle_deps(args)

        self.assertEqual(exc.exception.code, 1)
        self.assertIn('"ok": false', stdout.getvalue())

    def test_verify_summarizes_source_checks_and_windows_preflight(self):
        parser = build_parser()
        args = parser.parse_args(["verify", "--with-data-query", "--windows-deps-preflight"])

        dependency_reports = [
            {"ok": True, "missing": [], "platform": "darwin"},
            {
                "ok": False,
                "missing": [
                    {
                        "name": "pymem",
                        "marker": 'sys_platform == "win32"',
                    }
                ],
                "platform": "win32",
            },
        ]

        with (
            patch("gh_ui_cli.cli._default_requirements", return_value=Path("/tmp/requirements.txt")),
            patch("gh_ui_cli.cli.build_dependency_report", side_effect=dependency_reports),
            patch("gh_ui_cli.cli._coverage_summary", return_value={"all_callables": True, "totals": {}}),
            patch("gh_ui_cli.cli._source_smoke_checks", return_value=[{"name": "source", "ok": True}]),
            patch("gh_ui_cli.cli.platform.platform", return_value="macOS"),
            patch("gh_ui_cli.cli.sys.platform", "darwin"),
            redirect_stdout(StringIO()) as stdout,
        ):
            handle_verify(args)

        output = stdout.getvalue()
        self.assertIn('"mode": "source"', output)
        self.assertIn('"completion_ready": false', output)
        self.assertIn('"windows_dependency_preflight"', output)
        self.assertIn('"failed_checks": []', output)
        self.assertIn('"windows_dependency_preflight": true', output)

    def test_verify_with_api_base_does_not_require_source_for_windows_preflight(self):
        parser = build_parser()
        args = parser.parse_args(
            ["--api-base", "http://127.0.0.1:8765", "verify", "--windows-deps-preflight"]
        )

        with (
            patch("gh_ui_cli.cli._http_coverage_summary", return_value={"all_callables": True, "totals": {}}),
            patch("gh_ui_cli.cli.run_api_base_checks", return_value=[{"name": "api_base", "ok": True}]),
            patch("gh_ui_cli.cli.resolve_source_root", side_effect=AssertionError("source should not load")),
            redirect_stdout(StringIO()) as stdout,
        ):
            handle_verify(args)

        output = stdout.getvalue()
        self.assertIn('"mode": "api_base"', output)
        self.assertIn('"windows_dependency_preflight": false', output)

    def test_verify_plan_outputs_agent_commands_without_source_or_sidecar(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "verify-plan",
                "--mac-report",
                "mac.json",
                "--windows-report",
                "win.json",
                "--artifact-dir",
                "artifacts",
            ]
        )

        with (
            patch("gh_ui_cli.cli.resolve_source_root", side_effect=AssertionError("source should not load")),
            patch("gh_ui_cli.cli.create_api_client", side_effect=AssertionError("sidecar should not load")),
            redirect_stdout(StringIO()) as stdout,
        ):
            handle_verify_plan(args)

        output = json.loads(stdout.getvalue())
        self.assertFalse(output["completion_claimable_without_windows_runtime"])
        self.assertEqual(
            output["commands"]["macos_source_report"]["argv"],
            [
                "gh-ui",
                "verify",
                "--with-data-query",
                "--windows-deps-preflight",
                "--strict",
                "--save",
                "mac.json",
            ],
        )
        self.assertEqual(
            output["commands"]["windows_runtime_report"]["argv"],
            ["gh-ui", "runtime-verify", "win.json"],
        )
        self.assertEqual(
            output["commands"]["merge_reports"]["argv"],
            ["gh-ui", "verify-merge", "mac.json", "win.json", "--strict-goal"],
        )
        self.assertEqual(
            output["commands"]["merge_artifacts"]["argv"],
            ["gh-ui", "verify-merge", "mac.json", "artifacts", "--strict-goal"],
        )
        self.assertEqual(
            output["commands"]["macos_verification_bundle"]["argv"],
            [
                "gh-ui",
                "verify-bundle",
                "verify-bundle",
                "--source-report",
                "mac.json",
                "--windows-report",
                "win.json",
                "--artifact-dir",
                "artifacts",
                "--with-data-query",
                "--strict",
            ],
        )
        self.assertEqual(
            output["commands"]["check_github_actions_status"]["argv"],
            [
                "gh-ui",
                "ci-status",
                "--workflow",
                "ci.yml",
                "--mac-report",
                "mac.json",
                "--artifact-dir",
                "artifacts",
                "--artifact-name",
                "gh-ui-verify-Windows-py3.12",
            ],
        )
        self.assertEqual(
            output["commands"]["extract_windows_ci_log_report"]["argv"],
            [
                "gh-ui",
                "ci-log-report",
                "<RUN_ID>",
                "--platform",
                "win32",
                "--save",
                "win.json",
            ],
        )
        self.assertIn("windows_runtime", output["completion_requirements"])

    def test_ci_status_reports_missing_workflow_and_next_commands(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "ci-status",
                "--repo",
                "Hedicx2020/ghfe_web",
                "--workflow",
                "ci.yml",
                "--ref",
                "main",
                "--mac-report",
                "mac.json",
                "--artifact-dir",
                "artifacts",
                "--artifact-name",
                "gh-ui-verify-Windows-py3.12",
            ]
        )

        with (
            patch("gh_ui_cli.cli._run_gh_json", return_value={"total_count": 0, "workflows": []}) as run_gh,
            redirect_stdout(StringIO()) as stdout,
        ):
            handle_ci_status(args)

        output = json.loads(stdout.getvalue())
        self.assertFalse(output["workflow_found"])
        self.assertFalse(output["ci_ready"])
        self.assertEqual(output["repo"], "Hedicx2020/ghfe_web")
        self.assertEqual(
            output["commands"]["dispatch_ci_workflow"]["argv"],
            ["gh", "workflow", "run", "ci.yml", "--repo", "Hedicx2020/ghfe_web", "--ref", "main"],
        )
        self.assertEqual(
            output["commands"]["download_windows_ci_artifact"]["argv"],
            [
                "gh",
                "run",
                "download",
                "--repo",
                "Hedicx2020/ghfe_web",
                "--name",
                "gh-ui-verify-Windows-py3.12",
                "--dir",
                "artifacts",
            ],
        )
        self.assertEqual(
            output["commands"]["merge_artifacts"]["argv"],
            ["gh-ui", "verify-merge", "mac.json", "artifacts", "--strict-goal"],
        )
        self.assertEqual(output["next_actions"][0]["kind"], "publish_workflow")
        run_gh.assert_called_once_with(["api", "repos/Hedicx2020/ghfe_web/actions/workflows"])

    def test_ci_status_strict_exits_when_workflow_is_missing(self):
        parser = build_parser()
        args = parser.parse_args(["ci-status", "--repo", "Hedicx2020/ghfe_web", "--strict"])

        with (
            patch("gh_ui_cli.cli._run_gh_json", return_value={"total_count": 0, "workflows": []}),
            redirect_stdout(StringIO()),
        ):
            with self.assertRaises(SystemExit) as exc:
                handle_ci_status(args)

        self.assertEqual(exc.exception.code, 1)

    def test_ci_status_requires_named_windows_artifact_from_successful_run(self):
        parser = build_parser()
        args = parser.parse_args(["ci-status", "--repo", "Hedicx2020/ghfe_web", "--workflow", "ci.yml"])
        workflow = {
            "id": 123,
            "name": "gh-ui-cli",
            "path": ".github/workflows/ci.yml",
            "state": "active",
        }
        run = {
            "id": 456,
            "name": "CLI light checks",
            "status": "completed",
            "conclusion": "success",
            "head_branch": "main",
            "created_at": "2026-05-26T00:00:00Z",
            "html_url": "https://github.com/Hedicx2020/ghfe_web/actions/runs/456",
        }
        artifact = {"name": "gh-ui-verify-Windows-py3.12", "archive_download_url": "https://example/artifact.zip"}

        with (
            patch(
                "gh_ui_cli.cli._run_gh_json",
                side_effect=[
                    {"workflows": [workflow]},
                    {"workflow_runs": [run]},
                    {"artifacts": [artifact]},
                ],
            ) as run_gh,
            redirect_stdout(StringIO()) as stdout,
        ):
            handle_ci_status(args)

        output = json.loads(stdout.getvalue())
        self.assertTrue(output["workflow_found"])
        self.assertTrue(output["windows_artifact_found"])
        self.assertTrue(output["ci_ready"])
        self.assertEqual(output["latest_successful_run"]["id"], "456")
        self.assertEqual(output["windows_artifact"]["name"], "gh-ui-verify-Windows-py3.12")
        self.assertEqual(output["next_actions"], [])
        self.assertEqual(run_gh.call_count, 3)

    def test_ci_status_rejects_expired_windows_artifact(self):
        parser = build_parser()
        args = parser.parse_args(["ci-status", "--repo", "Hedicx2020/ghfe_web", "--workflow", "ci.yml"])
        workflow = {
            "id": 123,
            "name": "gh-ui-cli",
            "path": ".github/workflows/ci.yml",
            "state": "active",
        }
        run = {
            "id": 456,
            "status": "completed",
            "conclusion": "success",
            "head_branch": "main",
        }
        artifact = {
            "name": "gh-ui-verify-Windows-py3.12",
            "expired": True,
            "archive_download_url": "https://example/artifact.zip",
        }

        with (
            patch(
                "gh_ui_cli.cli._run_gh_json",
                side_effect=[
                    {"workflows": [workflow]},
                    {"workflow_runs": [run]},
                    {"artifacts": [artifact]},
                ],
            ),
            redirect_stdout(StringIO()) as stdout,
        ):
            handle_ci_status(args)

        output = json.loads(stdout.getvalue())
        self.assertFalse(output["windows_artifact_found"])
        self.assertFalse(output["ci_ready"])
        self.assertEqual(output["next_actions"][0]["kind"], "rerun_ci_workflow")
        self.assertEqual(output["next_actions"][0]["reason"], "Expected Windows artifact is expired.")

    def test_ci_log_report_extracts_windows_report_from_marked_logs(self):
        parser = build_parser()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "verify-windows.json"
            args = parser.parse_args(
                [
                    "ci-log-report",
                    "123456",
                    "--repo",
                    "Hedicx2020/ghfe_web",
                    "--platform",
                    "win32",
                    "--save",
                    str(output),
                ]
            )
            log_text = "\n".join(
                [
                    "CLI light checks (macos-latest, Python 3.12)\tPrint\t2026-05-25T00:00:00Z GH_UI_VERIFY_REPORT_BEGIN",
                    "CLI light checks (macos-latest, Python 3.12)\tPrint\t2026-05-25T00:00:01Z {",
                    "CLI light checks (macos-latest, Python 3.12)\tPrint\t2026-05-25T00:00:02Z   \"ok\": true,",
                    "CLI light checks (macos-latest, Python 3.12)\tPrint\t2026-05-25T00:00:03Z   \"current_platform\": \"darwin\"",
                    "CLI light checks (macos-latest, Python 3.12)\tPrint\t2026-05-25T00:00:04Z }",
                    "CLI light checks (macos-latest, Python 3.12)\tPrint\t2026-05-25T00:00:05Z GH_UI_VERIFY_REPORT_END",
                    "CLI light checks (windows-latest, Python 3.12)\tPrint\t2026-05-25T00:00:06Z GH_UI_VERIFY_REPORT_BEGIN",
                    "CLI light checks (windows-latest, Python 3.12)\tPrint\t2026-05-25T00:00:07Z {",
                    "CLI light checks (windows-latest, Python 3.12)\tPrint\t2026-05-25T00:00:08Z   \"ok\": true,",
                    "CLI light checks (windows-latest, Python 3.12)\tPrint\t2026-05-25T00:00:09Z   \"current_platform\": \"win32\"",
                    "CLI light checks (windows-latest, Python 3.12)\tPrint\t2026-05-25T00:00:10Z }",
                    "CLI light checks (windows-latest, Python 3.12)\tPrint\t2026-05-25T00:00:11Z GH_UI_VERIFY_REPORT_END",
                ]
            )

            with (
                patch("gh_ui_cli.cli._run_gh_text", return_value=log_text) as run_gh,
                redirect_stdout(StringIO()) as stdout,
            ):
                handle_ci_log_report(args)

            report = json.loads(stdout.getvalue())
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["current_platform"], "win32")
            self.assertEqual(saved["current_platform"], "win32")
            run_gh.assert_called_once_with(["run", "view", "123456", "--repo", "Hedicx2020/ghfe_web", "--log"])

    def test_ci_log_report_strict_exits_when_no_matching_report_exists(self):
        parser = build_parser()
        args = parser.parse_args(["ci-log-report", "123456", "--platform", "win32", "--strict"])

        with (
            patch("gh_ui_cli.cli._run_gh_text", return_value="no report"),
            redirect_stdout(StringIO()),
        ):
            with self.assertRaises(SystemExit) as exc:
                handle_ci_log_report(args)

        self.assertEqual(exc.exception.code, 1)

    def test_verify_bundle_writes_agent_handoff_files(self):
        parser = build_parser()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "bundle"
            args = parser.parse_args(
                [
                    "verify-bundle",
                    str(output_dir),
                    "--source-report",
                    "verify-source.json",
                    "--windows-report",
                    "verify-windows.json",
                    "--artifact-dir",
                    "artifacts",
                ]
            )

            with (
                patch("gh_ui_cli.cli._run_verify_report", return_value={"ok": True, "completion_ready": False}),
                patch("gh_ui_cli.cli._cli_manifest", return_value={"entries": [{"id": "cli:verify-plan"}]}),
                redirect_stdout(StringIO()) as stdout,
            ):
                handle_verify_bundle(args)

            summary = json.loads(stdout.getvalue())
            self.assertEqual(summary["output_dir"], str(output_dir))
            self.assertEqual(summary["files"]["source_report"], str(output_dir / "verify-source.json"))
            self.assertFalse(summary["source_report"]["completion_ready"])

            source_report = json.loads((output_dir / "verify-source.json").read_text(encoding="utf-8"))
            plan = json.loads((output_dir / "verify-plan.json").read_text(encoding="utf-8"))
            manifest = json.loads((output_dir / "manifest-cli.json").read_text(encoding="utf-8"))
            readme = (output_dir / "README_NEXT.md").read_text(encoding="utf-8")

            self.assertEqual(source_report["ok"], True)
            self.assertEqual(plan["commands"]["windows_runtime_report"]["argv"], ["gh-ui", "runtime-verify", "verify-windows.json"])
            self.assertEqual(manifest["entries"][0]["id"], "cli:verify-plan")
            self.assertIn("gh-ui ci-status", readme)
            self.assertIn("gh-ui ci-log-report", readme)
            self.assertIn("gh-ui runtime-verify verify-windows.json", readme)
            self.assertIn("gh-ui verify-merge verify-source.json verify-windows.json --strict-goal", readme)

    def test_verify_merge_reads_report_files_and_reports_completion(self):
        parser = build_parser()
        args = parser.parse_args(["verify-merge", "@mac.json", "@windows.json"])
        reports = [
            {
                "ok": True,
                "mode": "source",
                "platform": "macOS",
                "current_platform": "darwin",
                "failed_checks": [],
                "goal_evidence": {
                    "route_operations_callable": True,
                    "source_dynamic_capabilities_verified": True,
                    "frontend_api_references_verified": True,
                    "preferred_commands_parseable": True,
                    "all_features_cli_callable": True,
                    "agent_profile_verified": True,
                    "mac_runtime_verified": True,
                    "windows_runtime_verified": False,
                },
            },
            {
                "ok": True,
                "mode": "api_base",
                "platform": "Windows",
                "current_platform": "win32",
                "failed_checks": [],
                "goal_evidence": {
                    "all_features_cli_callable": False,
                    "agent_profile_verified": True,
                    "mac_runtime_verified": False,
                    "windows_runtime_verified": True,
                },
            },
        ]

        with (
            patch("gh_ui_cli.cli.read_json_arg", side_effect=reports),
            redirect_stdout(StringIO()) as stdout,
        ):
            handle_verify_merge(args)

        output = stdout.getvalue()
        self.assertIn('"mode": "merged"', output)
        self.assertIn('"completion_ready": true', output)

    def test_verify_merge_accepts_plain_file_paths(self):
        parser = build_parser()
        with tempfile.TemporaryDirectory() as tmpdir:
            mac = Path(tmpdir) / "mac.json"
            windows = Path(tmpdir) / "windows.json"
            mac.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "mode": "source",
                        "platform": "macOS",
                        "current_platform": "darwin",
                        "failed_checks": [],
                        "goal_evidence": {
                            "route_operations_callable": True,
                            "source_dynamic_capabilities_verified": True,
                            "frontend_api_references_verified": True,
                            "preferred_commands_parseable": True,
                            "all_features_cli_callable": True,
                            "agent_profile_verified": True,
                            "mac_runtime_verified": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            windows.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "mode": "api_base",
                        "platform": "Windows",
                        "current_platform": "win32",
                        "failed_checks": [],
                        "goal_evidence": {
                            "agent_profile_verified": True,
                            "windows_runtime_verified": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            args = parser.parse_args(["verify-merge", str(mac), str(windows)])

            with redirect_stdout(StringIO()) as stdout:
                handle_verify_merge(args)

        self.assertIn('"completion_ready": true', stdout.getvalue())

    def test_verify_merge_expands_report_directories(self):
        parser = build_parser()
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "reports"
            nested_dir = report_dir / "gh-ui-verify-Windows-py3.12"
            nested_dir.mkdir(parents=True)
            mac = report_dir / "verify-macos.json"
            windows = nested_dir / "verify-Windows-py3.12.json"
            (report_dir / "README.txt").write_text("ignore me", encoding="utf-8")
            mac.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "mode": "source",
                        "platform": "macOS",
                        "current_platform": "darwin",
                        "failed_checks": [],
                        "goal_evidence": {
                            "route_operations_callable": True,
                            "source_dynamic_capabilities_verified": True,
                            "frontend_api_references_verified": True,
                            "preferred_commands_parseable": True,
                            "all_features_cli_callable": True,
                            "agent_profile_verified": True,
                            "mac_runtime_verified": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            windows.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "mode": "api_base",
                        "platform": "Windows",
                        "current_platform": "win32",
                        "failed_checks": [],
                        "goal_evidence": {
                            "agent_profile_verified": True,
                            "windows_runtime_verified": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            args = parser.parse_args(["verify-merge", str(report_dir)])

            with redirect_stdout(StringIO()) as stdout:
                handle_verify_merge(args)

        output = json.loads(stdout.getvalue())
        self.assertEqual(output["input_count"], 2)
        self.assertTrue(output["completion_ready"])

    def test_invoke_route_id_calls_api_client_with_replaced_path(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--api-base",
                "http://127.0.0.1:8765",
                "invoke",
                "route:GET:/api/wechat/articles/accounts/{mp_id}/categories",
                "-p",
                "mp_id=abc",
                "-p",
                "limit=2",
            ]
        )
        client = _RecordingClient({"ok": True})

        with (
            patch("gh_ui_cli.cli.create_api_client", return_value=client),
            redirect_stdout(StringIO()),
        ):
            handle_invoke(args)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["method"], "GET")
        self.assertEqual(client.calls[0]["path"], "/api/wechat/articles/accounts/abc/categories")
        self.assertEqual(client.calls[0]["params"], {"limit": 2})
        self.assertIsNone(client.calls[0]["json_body"])

    def test_invoke_data_id_uses_token_and_json_body(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "invoke",
                "data:update:stock/stock_price",
                "--token",
                "secret",
                "--server",
                "secondary",
                "-p",
                "adj_type=forward",
                "--json",
                '{"start_date":"2024-01-01"}',
            ]
        )
        client = _RecordingClient({"ok": True})

        with (
            patch("gh_ui_cli.cli.create_api_client", return_value=client),
            redirect_stdout(StringIO()),
        ):
            handle_invoke(args)

        self.assertEqual(client.calls[0]["method"], "POST")
        self.assertEqual(client.calls[0]["path"], "/update/stock/stock_price")
        self.assertEqual(
            client.calls[0]["json_body"],
            {
                "start_date": "2024-01-01",
                "adj_type": "forward",
                "token": "secret",
                "server": "secondary",
            },
        )

    def test_invoke_data_id_uses_profile_token_and_server_when_flags_missing(self):
        parser = build_parser()
        client = _RecordingClient({"ok": True})

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            with patch.dict(os.environ, {"GH_UI_CLI_PROFILE": str(path)}, clear=True):
                save_profile({"api_token": "profile-api", "server": "secondary"})
                args = parser.parse_args(
                    [
                        "invoke",
                        "data:update:stock/stock_price",
                        "-p",
                        "adj_type=forward",
                    ]
                )

                with (
                    patch("gh_ui_cli.cli.create_api_client", return_value=client),
                    redirect_stdout(StringIO()),
                ):
                    handle_invoke(args)

        self.assertEqual(client.calls[0]["method"], "POST")
        self.assertEqual(client.calls[0]["path"], "/update/stock/stock_price")
        self.assertEqual(
            client.calls[0]["json_body"],
            {"adj_type": "forward", "token": "profile-api", "server": "secondary"},
        )

    def test_data_update_uses_profile_token_and_server_when_flags_missing(self):
        parser = build_parser()
        client = _RecordingClient({"ok": True})

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            with patch.dict(os.environ, {"GH_UI_CLI_PROFILE": str(path)}, clear=True):
                save_profile({"api_token": "profile-api", "server": "secondary"})
                args = parser.parse_args(["data", "update", "stock", "stock_price", "-p", "adj_type=forward"])

                with (
                    patch("gh_ui_cli.cli.create_api_client", return_value=client),
                    redirect_stdout(StringIO()),
                ):
                    args.func(args)

        self.assertEqual(client.calls[0]["method"], "POST")
        self.assertEqual(client.calls[0]["path"], "/update/stock/stock_price")
        self.assertEqual(
            client.calls[0]["json_body"],
            {"adj_type": "forward", "token": "profile-api", "server": "secondary"},
        )

    def test_auth_commands_call_stable_auth_routes(self):
        parser = build_parser()
        client = _RecordingClient({"ok": True})

        cases = [
            (
                ["auth", "verify", "--token", "jy-token"],
                {
                    "method": "POST",
                    "path": "/auth/verify",
                    "json_body": {"token": "jy-token"},
                },
            ),
            (
                ["auth", "login", "--username", "user", "--password", "pass"],
                {
                    "method": "POST",
                    "path": "/auth/login",
                    "json_body": {"username": "user", "password": "pass"},
                },
            ),
            (
                ["auth", "active-token", "--access-token", "access"],
                {
                    "method": "POST",
                    "path": "/auth/active-token",
                    "headers": {"Authorization": "Bearer access"},
                },
            ),
        ]

        with (
            patch("gh_ui_cli.cli.create_api_client", return_value=client),
            redirect_stdout(StringIO()),
        ):
            for argv, expected in cases:
                parser.parse_args(argv).func(parser.parse_args(argv))

        self.assertEqual(len(client.calls), 3)
        for call, expected in zip(client.calls, [case[1] for case in cases]):
            self.assertEqual(call["method"], expected["method"])
            self.assertEqual(call["path"], expected["path"])
            if "json_body" in expected:
                self.assertEqual(call["json_body"], expected["json_body"])
            if "headers" in expected:
                self.assertEqual(call["headers"], expected["headers"])

    def test_auth_commands_use_profile_tokens_when_flags_missing(self):
        parser = build_parser()
        client = _RecordingClient({"ok": True})

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            with patch.dict(os.environ, {"GH_UI_CLI_PROFILE": str(path)}, clear=True):
                save_profile({"api_token": "profile-api", "access_token": "profile-access"})

                with (
                    patch("gh_ui_cli.cli.create_api_client", return_value=client),
                    redirect_stdout(StringIO()),
                ):
                    for argv in (["auth", "verify"], ["auth", "active-token"]):
                        args = parser.parse_args(argv)
                        args.func(args)

        self.assertEqual(client.calls[0]["path"], "/auth/verify")
        self.assertEqual(client.calls[0]["json_body"], {"token": "profile-api"})
        self.assertEqual(client.calls[1]["path"], "/auth/active-token")
        self.assertEqual(client.calls[1]["headers"], {"Authorization": "Bearer profile-access"})

    def test_ai_commands_call_stable_report_reproduce_routes(self):
        parser = build_parser()
        client = _RecordingClient({"ok": True})

        cases = [
            (
                ["ai", "status", "-p", "workspace=/tmp/work", "-p", "output_path=/tmp/out"],
                {
                    "method": "GET",
                    "path": "/ai/status",
                    "params": {"workspace": "/tmp/work", "output_path": "/tmp/out"},
                },
            ),
            (
                ["ai", "projects"],
                {"method": "GET", "path": "/ai/report-reproduce/projects", "params": {}},
            ),
            (
                ["ai", "pdf-candidates", "-p", "workspace=/tmp/work"],
                {
                    "method": "GET",
                    "path": "/ai/report-reproduce/pdf-candidates",
                    "params": {"workspace": "/tmp/work"},
                },
            ),
            (
                ["ai", "tasks"],
                {"method": "GET", "path": "/ai/report-reproduce/tasks", "params": {}},
            ),
            (
                ["ai", "task", "task-1"],
                {"method": "GET", "path": "/ai/report-reproduce/tasks/task-1", "params": {}},
            ),
            (
                ["ai", "start", "--json", '{"pdf_path":"/tmp/a.pdf","runner":"codex"}'],
                {
                    "method": "POST",
                    "path": "/ai/report-reproduce/start",
                    "json_body": {"pdf_path": "/tmp/a.pdf", "runner": "codex"},
                },
            ),
            (
                ["ai", "cancel", "task-1"],
                {"method": "POST", "path": "/ai/report-reproduce/tasks/task-1/cancel", "params": {}},
            ),
        ]

        with (
            patch("gh_ui_cli.cli.create_api_client", return_value=client),
            redirect_stdout(StringIO()),
        ):
            for argv, _expected in cases:
                args = parser.parse_args(argv)
                args.func(args)

        self.assertEqual(len(client.calls), len(cases))
        for call, expected in zip(client.calls, [case[1] for case in cases]):
            self.assertEqual(call["method"], expected["method"])
            self.assertEqual(call["path"], expected["path"])
            if "params" in expected:
                self.assertEqual(call["params"], expected["params"])
            if "json_body" in expected:
                self.assertEqual(call["json_body"], expected["json_body"])

    def test_remote_commands_call_stable_account_routes(self):
        parser = build_parser()
        client = _RecordingClient({"ok": True})

        cases = [
            (
                ["--api-base", "http://test", "remote", "me", "--access-token", "access"],
                handle_remote_me,
                {
                    "method": "GET",
                    "path": "/remote/me",
                    "headers": {"Authorization": "Bearer access"},
                },
            ),
            (
                ["--api-base", "http://test", "remote", "tokens", "--access-token", "access"],
                handle_remote_tokens,
                {
                    "method": "GET",
                    "path": "/remote/tokens",
                    "headers": {"Authorization": "Bearer access"},
                },
            ),
            (
                ["--api-base", "http://test", "remote", "token-generate", "--access-token", "access", "--name", "agent"],
                handle_remote_token_generate,
                {
                    "method": "POST",
                    "path": "/remote/tokens",
                    "json_body": {"name": "agent"},
                    "headers": {"Authorization": "Bearer access"},
                },
            ),
            (
                ["--api-base", "http://test", "remote", "token-revoke", "42", "--access-token", "access"],
                handle_remote_token_revoke,
                {
                    "method": "DELETE",
                    "path": "/remote/tokens/42",
                    "headers": {"Authorization": "Bearer access"},
                },
            ),
        ]

        with (
            patch("gh_ui_cli.cli.create_api_client", return_value=client),
            redirect_stdout(StringIO()),
        ):
            for argv, expected_func, _expected in cases:
                args = parser.parse_args(argv)
                self.assertIs(args.func, expected_func)
                args.func(args)

        self.assertEqual(len(client.calls), len(cases))
        for call, expected in zip(client.calls, [case[2] for case in cases]):
            self.assertEqual(call["method"], expected["method"])
            self.assertEqual(call["path"], expected["path"])
            self.assertEqual(call["headers"], expected["headers"])
            if "json_body" in expected:
                self.assertEqual(call["json_body"], expected["json_body"])

    def test_remote_commands_use_profile_access_token_when_flag_missing(self):
        parser = build_parser()
        client = _RecordingClient({"ok": True})

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            with patch.dict(os.environ, {"GH_UI_CLI_PROFILE": str(path)}, clear=True):
                save_profile({"access_token": "profile-access"})
                args = parser.parse_args(["--api-base", "http://test", "remote", "me"])

                with (
                    patch("gh_ui_cli.cli.create_api_client", return_value=client),
                    redirect_stdout(StringIO()),
                ):
                    args.func(args)

        self.assertEqual(client.calls[0]["method"], "GET")
        self.assertEqual(client.calls[0]["path"], "/remote/me")
        self.assertEqual(client.calls[0]["headers"], {"Authorization": "Bearer profile-access"})

    def test_profile_commands_store_redacted_local_defaults(self):
        parser = build_parser()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            with patch.dict(os.environ, {"GH_UI_CLI_PROFILE": str(path)}, clear=True):
                set_args = parser.parse_args(
                    [
                        "profile",
                        "set",
                        "--api-token",
                        "api-secret",
                        "--access-token",
                        "access-secret",
                        "--server",
                        "secondary",
                        "--username",
                        "agent",
                    ]
                )
                with redirect_stdout(StringIO()) as stdout:
                    set_args.func(set_args)
                output = json.loads(stdout.getvalue())

                self.assertEqual(output["server"], "secondary")
                self.assertEqual(output["username"], "agent")
                self.assertTrue(output["has_api_token"])
                self.assertTrue(output["has_access_token"])
                self.assertNotIn("api-secret", stdout.getvalue())
                self.assertNotIn("access-secret", stdout.getvalue())

                get_args = parser.parse_args(["profile", "get"])
                with redirect_stdout(StringIO()) as get_stdout:
                    get_args.func(get_args)
                self.assertEqual(json.loads(get_stdout.getvalue())["path"], str(path))

                clear_args = parser.parse_args(["profile", "clear"])
                with redirect_stdout(StringIO()) as clear_stdout:
                    clear_args.func(clear_args)
                self.assertEqual(json.loads(clear_stdout.getvalue()), {"cleared": True, "path": str(path)})
                self.assertFalse(path.exists())

    def test_backtest_commands_call_stable_routes(self):
        parser = build_parser()
        client = _RecordingClient({"ok": True})

        cases = [
            (
                ["backtest", "check-data"],
                {"method": "GET", "path": "/backtest/check-data", "params": {}},
            ),
            (
                ["backtest", "upload-json", "--json", '{"rows":[],"name":"demo"}'],
                {
                    "method": "POST",
                    "path": "/backtest/upload-portfolio-json",
                    "json_body": {"rows": [], "name": "demo"},
                },
            ),
            (
                ["backtest", "upload", "/tmp/portfolio.xlsx"],
                {"method": "POST", "path": "/backtest/upload-portfolio", "file_path": "/tmp/portfolio.xlsx"},
            ),
            (
                ["backtest", "uploaded-portfolio", "up_1"],
                {"method": "GET", "path": "/backtest/uploaded-portfolio/up_1"},
            ),
            (
                [
                    "backtest",
                    "monitoring-holdings",
                    "--upload-id",
                    "up_1",
                    "--date",
                    "2024-01-02",
                    "--benchmark-index",
                    "000905",
                    "--aum",
                    "10",
                ],
                {
                    "method": "GET",
                    "path": "/backtest/monitoring/holdings",
                    "params": {
                        "upload_id": "up_1",
                        "date": "2024-01-02",
                        "benchmark_index": "000905",
                        "aum": 10.0,
                    },
                },
            ),
            (
                ["backtest", "result", "task-1"],
                {"method": "GET", "path": "/backtest/results/task-1"},
            ),
            (
                ["backtest", "holdings", "task-1", "-p", "date=2024-01-02"],
                {"method": "GET", "path": "/backtest/results/task-1/holdings", "params": {"date": "2024-01-02"}},
            ),
            (
                ["backtest", "export", "task-1"],
                {"method": "GET", "path": "/backtest/results/task-1/export"},
            ),
        ]

        with (
            patch("gh_ui_cli.cli.create_api_client", return_value=client),
            redirect_stdout(StringIO()),
        ):
            for argv, _expected in cases:
                args = parser.parse_args(argv)
                args.func(args)

        self.assertEqual(len(client.calls), len(cases))
        for call, expected in zip(client.calls, [case[1] for case in cases]):
            self.assertEqual(call["method"], expected["method"])
            self.assertEqual(call["path"], expected["path"])
            if "params" in expected:
                self.assertEqual(call["params"], expected["params"])
            if "json_body" in expected:
                self.assertEqual(call["json_body"], expected["json_body"])
            if "file_path" in expected:
                self.assertEqual(call["file_path"], expected["file_path"])

    def test_factor_commands_call_stable_routes(self):
        parser = build_parser()
        client = _RecordingClient({"ok": True})

        cases = [
            (
                ["factor", "sample"],
                {"method": "GET", "path": "/factor/sample", "params": {}},
            ),
            (
                ["factor", "catalog"],
                {"method": "GET", "path": "/factor/db/catalog", "params": {}},
            ),
            (
                ["factor", "values", "quality", "-p", "start_date=2024-01-01"],
                {
                    "method": "GET",
                    "path": "/factor/db/values",
                    "params": {"factor_id": "quality", "start_date": "2024-01-01"},
                },
            ),
            (
                ["factor", "rank-list", "-p", "ind_code=CI005001", "-p", "year=2024"],
                {
                    "method": "GET",
                    "path": "/factor/rank/list",
                    "params": {"ind_code": "CI005001", "year": 2024},
                },
            ),
            (
                ["factor", "rank-detail", "quality", "--ind-code", "CI005001"],
                {
                    "method": "GET",
                    "path": "/factor/rank/detail/quality",
                    "params": {"ind_code": "CI005001"},
                },
            ),
            (
                ["factor", "analyze", "--json", '{"upload_id":"up_1"}'],
                {"method": "POST", "path": "/factor/analyze", "json_body": {"upload_id": "up_1"}},
            ),
            (
                ["factor", "upload", "/tmp/factor.xlsx"],
                {"method": "POST", "path": "/factor/upload", "file_path": "/tmp/factor.xlsx"},
            ),
        ]

        with (
            patch("gh_ui_cli.cli.create_api_client", return_value=client),
            redirect_stdout(StringIO()),
        ):
            for argv, _expected in cases:
                args = parser.parse_args(argv)
                args.func(args)

        self.assertEqual(len(client.calls), len(cases))
        for call, expected in zip(client.calls, [case[1] for case in cases]):
            self.assertEqual(call["method"], expected["method"])
            self.assertEqual(call["path"], expected["path"])
            if "params" in expected:
                self.assertEqual(call["params"], expected["params"])
            if "json_body" in expected:
                self.assertEqual(call["json_body"], expected["json_body"])
            if "file_path" in expected:
                self.assertEqual(call["file_path"], expected["file_path"])

    def test_wechat_commands_call_stable_routes(self):
        parser = build_parser()
        client = _RecordingClient({"ok": True})

        cases = [
            (
                ["wechat", "log", "--level", "warning", "--message", "frontend failed"],
                {"method": "POST", "path": "/wechat/log", "json_body": {"level": "warning", "message": "frontend failed"}},
            ),
            (
                ["wechat", "debug-inspect", "-p", "table_limit=2"],
                {"method": "GET", "path": "/wechat/debug/inspect", "params": {"table_limit": 2}},
            ),
            (
                ["wechat", "contacts-export"],
                {"method": "GET", "path": "/wechat/contacts/export", "params": {}},
            ),
            (
                ["wechat", "messages-export", "--json", '{"start_date":"2024-01-01","end_date":"2024-01-31"}'],
                {
                    "method": "POST",
                    "path": "/wechat/messages/export",
                    "json_body": {"start_date": "2024-01-01", "end_date": "2024-01-31"},
                },
            ),
            (
                ["wechat", "image-extract-keys"],
                {"method": "POST", "path": "/wechat/image/extract-keys", "params": {}},
            ),
            (
                ["wechat", "image-list", "-p", "month=2026-05", "-p", "limit=20"],
                {"method": "GET", "path": "/wechat/image/list", "params": {"month": "2026-05", "limit": 20}},
            ),
            (
                ["wechat", "llm-export", "--json", '{"history":[{"role":"user","content":"hi"}]}'],
                {
                    "method": "POST",
                    "path": "/wechat/llm/export",
                    "json_body": {"history": [{"role": "user", "content": "hi"}]},
                },
            ),
            (
                ["wechat", "articles-login-poll", "--scan-id", "scan-1"],
                {"method": "POST", "path": "/wechat/articles/login/poll", "json_body": {"scan_id": "scan-1"}},
            ),
            (
                ["wechat", "articles-login-qrcode"],
                {"method": "GET", "path": "/wechat/articles/login/qrcode", "params": {}},
            ),
            (
                ["wechat", "articles-analysis-get", "7"],
                {"method": "GET", "path": "/wechat/articles/analyses/7"},
            ),
            (
                ["wechat", "articles-analysis-delete", "7"],
                {"method": "DELETE", "path": "/wechat/articles/analyses/7"},
            ),
            (
                ["wechat", "articles-category-create", "--name", "研究"],
                {"method": "POST", "path": "/wechat/articles/categories", "json_body": {"name": "研究"}},
            ),
            (
                ["wechat", "articles-category-rename", "3", "--name", "策略"],
                {"method": "PUT", "path": "/wechat/articles/categories/3", "json_body": {"name": "策略"}},
            ),
            (
                ["wechat", "articles-category-delete", "3"],
                {"method": "DELETE", "path": "/wechat/articles/categories/3"},
            ),
            (
                ["wechat", "articles-account-categories", "mp_1"],
                {"method": "GET", "path": "/wechat/articles/accounts/mp_1/categories"},
            ),
            (
                ["wechat", "articles-account-set-categories", "mp_1", "--category-id", "1", "--category-id", "2"],
                {
                    "method": "POST",
                    "path": "/wechat/articles/accounts/mp_1/categories",
                    "json_body": {"category_ids": [1, 2]},
                },
            ),
            (
                ["wechat", "articles-account-favorite", "mp_1", "--unfavorite"],
                {
                    "method": "POST",
                    "path": "/wechat/articles/accounts/mp_1/favorite",
                    "json_body": {"is_favorite": False},
                },
            ),
            (
                ["wechat", "articles-account-add-by-url", "https://mp.weixin.qq.com/s/demo"],
                {
                    "method": "POST",
                    "path": "/wechat/articles/accounts/add_by_url",
                    "json_body": {"article_url": "https://mp.weixin.qq.com/s/demo"},
                },
            ),
            (
                ["wechat", "articles-account-delete", "mp_1"],
                {"method": "DELETE", "path": "/wechat/articles/accounts/mp_1"},
            ),
            (
                ["wechat", "articles-fetch", "article_1"],
                {"method": "POST", "path": "/wechat/articles/articles/article_1/fetch"},
            ),
            (
                ["wechat", "articles-html", "article_1"],
                {"method": "GET", "path": "/wechat/articles/articles/article_1/html"},
            ),
            (
                ["wechat", "articles-purge-invalid", "--category-id", "5"],
                {
                    "method": "POST",
                    "path": "/wechat/articles/sync_by_category/purge_invalid",
                    "params": {"category_id": 5},
                },
            ),
            (
                ["wechat", "articles-sync-by-category-preview", "--category-id", "5", "--mode", "since", "--since-date", "2024-01-01"],
                {
                    "method": "GET",
                    "path": "/wechat/articles/sync_by_category/preview",
                    "params": {"category_id": 5, "mode": "since", "since_date": "2024-01-01"},
                },
            ),
        ]

        with (
            patch("gh_ui_cli.cli.create_api_client", return_value=client),
            redirect_stdout(StringIO()),
        ):
            for argv, _expected in cases:
                # 强制走远端 mock client，避开本地 wechat capability 分发
                args = parser.parse_args(["--api-base", "http://test", *argv])
                args.func(args)

        self.assertEqual(len(client.calls), len(cases))
        for call, expected in zip(client.calls, [case[1] for case in cases]):
            self.assertEqual(call["method"], expected["method"])
            self.assertEqual(call["path"], expected["path"])
            if "params" in expected:
                self.assertEqual(call["params"], expected["params"])
            if "json_body" in expected:
                self.assertEqual(call["json_body"], expected["json_body"])

    def test_core_commands_call_stable_routes(self):
        parser = build_parser()
        client = _RecordingClient({"ok": True})

        cases = [
            (
                ["health"],
                handle_health,
                {"method": "GET", "path": "/health"},
            ),
            (
                ["data", "progress"],
                None,
                {"method": "GET", "path": "/download/progress"},
            ),
            (
                ["data", "progress", "--factor"],
                None,
                {"method": "GET", "path": "/factor/db/progress"},
            ),
            (
                ["data", "files"],
                None,
                {"method": "GET", "path": "/local/files"},
            ),
            (
                ["config", "get-paths"],
                None,
                {"method": "GET", "path": "/config/paths"},
            ),
            (
                [
                    "config",
                    "set-paths",
                    "--db-path",
                    "/tmp/local_data",
                    "--default-start-date",
                    "2020-01-01",
                ],
                None,
                {
                    "method": "POST",
                    "path": "/config/paths",
                    "json_body": {
                        "db_path": "/tmp/local_data",
                        "default_start_date": "2020-01-01",
                    },
                },
            ),
            (
                ["logs", "--category", "system", "--limit", "10"],
                None,
                {"method": "GET", "path": "/logs", "params": {"category": "system", "limit": 10}},
            ),
            (
                [
                    "export",
                    "excel",
                    "--input",
                    '{"data":[{"code":"000001"}],"columns":["code"]}',
                    "--filename",
                    "demo",
                    "--sheet-name",
                    "Sheet1",
                ],
                None,
                {
                    "method": "POST",
                    "path": "/export/excel",
                    "json_body": {
                        "data": [{"code": "000001"}],
                        "columns": ["code"],
                        "filename": "demo",
                        "sheet_name": "Sheet1",
                    },
                },
            ),
            (
                [
                    "feedback",
                    "submit",
                    "--json",
                    '{"content":"need cli","category":"suggestion","contact":"agent@example.com"}',
                ],
                handle_feedback_submit,
                {
                    "method": "POST",
                    "path": "/feedback",
                    "json_body": {
                        "content": "need cli",
                        "category": "suggestion",
                        "contact": "agent@example.com",
                    },
                },
            ),
        ]

        with (
            patch("gh_ui_cli.cli.create_api_client", return_value=client),
            redirect_stdout(StringIO()),
        ):
            for argv, expected_func, _expected in cases:
                args = parser.parse_args(argv)
                if expected_func is not None:
                    self.assertIs(args.func, expected_func)
                args.func(args)

        self.assertEqual(len(client.calls), len(cases))
        for call, expected in zip(client.calls, [case[2] for case in cases]):
            self.assertEqual(call["method"], expected["method"])
            self.assertEqual(call["path"], expected["path"])
            if "params" in expected:
                self.assertEqual(call["params"], expected["params"])
            if "json_body" in expected:
                self.assertEqual(call["json_body"], expected["json_body"])

    def test_preferred_command_parse_audit_accepts_placeholders_and_dynamic_entries(self):
        audit = {
            "routes": {
                "operations": [
                    {
                        "path": "/api/wechat/articles/sync_by_category/preview",
                        "method": "GET",
                        "category": "wechat",
                        "preferred": "gh-ui wechat articles-sync-by-category-preview --category-id <CATEGORY_ID> --mode <MODE>",
                    },
                    {
                        "path": "/api/remote/tokens/{token_id}",
                        "method": "DELETE",
                        "category": "remote",
                        "preferred": "gh-ui remote token-revoke {token_id} --access-token $GH_ACCESS_TOKEN",
                    },
                ]
            },
            "data_capabilities": {
                "query": [
                    {
                        "module": "stock",
                        "method": "stock_code",
                        "action": "query",
                        "preferred": "gh-ui data query stock stock_code",
                    }
                ],
                "download": [],
                "update": [],
            },
            "factor_data_capabilities": [
                {
                    "table": "factor_info",
                    "query": "gh-ui factor query factor_info",
                    "download": "gh-ui factor download factor_info --token $GH_API_TOKEN",
                    "update": "gh-ui factor update factor_info --token $GH_API_TOKEN",
                }
            ],
        }

        result = _preferred_command_parse_audit(audit)

        self.assertTrue(result["all_parseable"])
        self.assertEqual(result["total"], 6)
        self.assertEqual(result["unparseable"], [])

    def test_preferred_command_parse_audit_reports_invalid_recommendations(self):
        audit = {
            "routes": {
                "operations": [
                    {
                        "path": "/api/wechat/sessions",
                        "method": "GET",
                        "category": "wechat",
                        "preferred": "gh-ui wechat missing-command",
                    }
                ]
            },
            "data_capabilities": {"query": [], "download": [], "update": []},
            "factor_data_capabilities": [],
        }

        result = _preferred_command_parse_audit(audit)

        self.assertFalse(result["all_parseable"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["parseable"], 0)
        self.assertEqual(result["unparseable"][0]["command"], "gh-ui wechat missing-command")


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, method, path, *, prefix="/api", **kwargs):
        key = (method, path, prefix)
        self.calls.append(key)
        return _FakeResponse(self.responses[key])


class _RecordingClient:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append({"method": method, "path": path, **kwargs})
        return _FakeResponse(self.data)


if __name__ == "__main__":
    unittest.main()
