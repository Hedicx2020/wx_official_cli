from __future__ import annotations

from typing import Any

from .manifest import _shell_commands


OBJECTIVE = (
    "Build and publish wx_official_cli so agents can export locally cached "
    "WeChat official-account articles by account name on Windows, with macOS "
    "source evidence, Windows runtime evidence, and real Windows WeChat cache export evidence."
)
SOURCE_CLI_EVIDENCE = [
    "route_operations_callable",
    "source_dynamic_capabilities_verified",
    "frontend_api_references_verified",
    "preferred_commands_parseable",
]


def build_verification_plan(
    *,
    mac_report: str = "verify-macos.json",
    windows_report: str = "verify-windows.json",
    wechat_cache_report: str = "verify-wechat-cache-windows.json",
    artifact_dir: str = "verify-artifacts",
) -> dict[str, Any]:
    return {
        "objective": OBJECTIVE,
        "completion_claimable_without_windows_runtime": False,
        "completion_claimable_without_windows_wechat_cache": False,
        "completion_requirements": {
            "no_failed_reports": {
                "description": "Every input report passed its own checks.",
                "evidence": ["merge_reports.ok"],
            },
            "source_cli_coverage": {
                "description": (
                    "Source-mode CLI coverage for routes, dynamic capabilities, "
                    "frontend API references, and preferred commands."
                ),
                "required_evidence": SOURCE_CLI_EVIDENCE,
                "proven_by": ["commands.macos_source_report"],
            },
            "agent_profile": {
                "description": "Non-interactive profile smoke check passed.",
                "proven_by": ["commands.macos_source_report", "commands.windows_runtime_report"],
            },
            "mac_runtime": {
                "description": "Runtime checks ran on current_platform=darwin.",
                "required_platform": "darwin",
                "proven_by": ["commands.macos_source_report"],
            },
            "windows_runtime": {
                "description": "Runtime checks ran on current_platform=win32.",
                "required_platform": "win32",
                "proven_by": [
                    "commands.windows_runtime_report",
                    "commands.windows_http_sidecar_report",
                    "commands.merge_artifacts",
                ],
            },
            "wechat_cache_export": {
                "description": (
                    "Real Windows WeChat cache export succeeded for an already logged-in "
                    "local WeChat client and wrote article index plus HTML files."
                ),
                "required_platform": "win32",
                "required_evidence": [
                    "requirements.wechat_path_detected.ok",
                    "requirements.database_key_available.ok",
                    "requirements.articles_exported.ok",
                    "requirements.html_files_written.ok",
                ],
                "proven_by": ["commands.windows_wechat_cache_report"],
            },
        },
        "commands": {
            "macos_source_report": _command(
                [
                    "gh-ui",
                    "verify",
                    "--with-data-query",
                    "--windows-deps-preflight",
                    "--strict",
                    "--save",
                    mac_report,
                ],
                platform="darwin",
                proves=["source_cli_coverage", "agent_profile", "mac_runtime"],
            ),
            "macos_verification_bundle": _command(
                [
                    "gh-ui",
                    "verify-bundle",
                    "verify-bundle",
                    "--source-report",
                    mac_report,
                    "--windows-report",
                    windows_report,
                    "--artifact-dir",
                    artifact_dir,
                    "--with-data-query",
                    "--strict",
                ],
                platform="darwin",
                proves=["source_cli_coverage", "agent_profile", "mac_runtime"],
            ),
            "check_github_actions_status": _command(
                [
                    "gh-ui",
                    "ci-status",
                    "--workflow",
                    "ci.yml",
                    "--mac-report",
                    mac_report,
                    "--artifact-dir",
                    artifact_dir,
                    "--artifact-name",
                    "gh-ui-verify-Windows-py3.12",
                ],
                platform="any",
                proves=["windows_runtime"],
                optional=True,
            ),
            "extract_windows_ci_log_report": _command(
                [
                    "gh-ui",
                    "ci-log-report",
                    "<RUN_ID>",
                    "--platform",
                    "win32",
                    "--save",
                    windows_report,
                ],
                platform="any",
                proves=["windows_runtime"],
                optional=True,
            ),
            "windows_runtime_report": _command(
                ["gh-ui", "runtime-verify", windows_report],
                platform="win32",
                proves=["windows_runtime", "agent_profile"],
            ),
            "windows_http_sidecar_report": _command(
                [
                    "gh-ui",
                    "--api-base",
                    "http://127.0.0.1:8765",
                    "verify",
                    "--with-data-query",
                    "--strict",
                    "--save",
                    windows_report,
                ],
                platform="win32",
                proves=["windows_runtime", "agent_profile"],
            ),
            "windows_wechat_cache_report": _command(
                [
                    "gh-ui",
                    "wechat",
                    "articles-cache-verify",
                    "<ACCOUNT_NAME>",
                    "--strict",
                    "--save",
                    wechat_cache_report,
                ],
                platform="win32",
                proves=["wechat_cache_export"],
            ),
            "merge_reports": _command(
                ["gh-ui", "verify-merge", mac_report, windows_report, wechat_cache_report, "--strict-goal"],
                platform="any",
                proves=["completion_ready"],
            ),
            "merge_artifacts": _command(
                ["gh-ui", "verify-merge", mac_report, artifact_dir, wechat_cache_report, "--strict-goal"],
                platform="any",
                proves=["completion_ready"],
            ),
            "download_windows_ci_artifact": _command(
                [
                    "gh",
                    "run",
                    "download",
                    "--name",
                    "gh-ui-verify-Windows-py3.12",
                    "--dir",
                    artifact_dir,
                ],
                platform="any",
                proves=["windows_runtime"],
                optional=True,
            ),
        },
        "notes": [
            "Do not mark the goal complete until merge_reports or merge_artifacts exits 0 with completion_ready=true.",
            "A macOS report cannot prove windows_runtime; a Windows report must contain current_platform=win32.",
            "A mock runtime or GitHub Actions report cannot prove wechat_cache_export; run articles-cache-verify on a Windows machine with local WeChat cache.",
            "HTTP/API-base Windows reports can prove runtime only, not source_cli_coverage.",
        ],
    }


def _command(
    argv: list[str],
    *,
    platform: str,
    proves: list[str],
    optional: bool = False,
) -> dict[str, Any]:
    return {
        "argv": argv,
        "command_shell": _shell_commands(argv),
        "platform": platform,
        "proves": proves,
        "optional": optional,
    }
