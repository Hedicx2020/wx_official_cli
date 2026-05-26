from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import re
import shlex
import subprocess
import sys
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .api_client import ApiError, LocalApiClient, create_api_client
from .coverage_audit import (
    audit_backend,
    audit_frontend_api_references,
    audit_routes,
    enrich_routes_from_openapi,
    routes_from_openapi,
)
from .dependencies import build_dependency_report
from .invoke import build_invoke_request
from .manifest import _shell_commands, build_agent_manifest
from .io import parse_key_values, read_json_arg, write_bytes, write_json
from .profile import (
    clear_profile,
    load_profile,
    profile_path,
    public_profile,
    resolve_access_token,
    resolve_api_token,
    resolve_server,
    save_profile,
)
from .runtime_verify import run_runtime_verify
from .smoke import build_smoke_report, run_api_base_checks, run_profile_check
from .source import RuntimeConfig, load_main_module, resolve_source_root, route_inventory
from .verify import build_goal_verification_report, merge_goal_verification_reports
from .verification_plan import build_verification_plan


CORE_QUICK_UPDATE = [
    ("trade", "trade_date", {"market": "ashare"}),
    ("stock", "stock_code", {"market": "ashare"}),
    ("stock", "stock_price", {"adj_type": "forward"}),
    ("index", "index_price", {"code": "000300"}),
    ("fund", "fund_netvalue", {}),
    ("bond", "bond_yield_curve", {}),
]

ANGLE_PLACEHOLDERS = {
    "<ARTICLE_URL>": "https://mp.weixin.qq.com/s/demo",
    "<CATEGORY_ID>": "1",
    "<DB_PATH>": "/tmp/local_data",
    "<FACTOR_ID>": "quality",
    "<FILE>": "/tmp/input.xlsx",
    "<IND_CODE>": "CI005001",
    "<MESSAGE>": "message",
    "<MODE>": "incremental",
    "<NAME>": "name",
    "<SCAN_ID>": "scan-1",
    "<TOKEN_NAME>": "agent",
}
BRACED_PLACEHOLDERS = {
    "analysis_id": "1",
    "article_id": "article_1",
    "category_id": "1",
    "factor_id": "quality",
    "method": "stock_code",
    "module": "stock",
    "mp_id": "mp_1",
    "table": "factor_info",
    "task_id": "task-1",
    "token_id": "1",
    "upload_id": "upload-1",
}
BRACED_PLACEHOLDER_RE = re.compile(r"\{([^}]+)\}")


def build_config(args: argparse.Namespace) -> RuntimeConfig:
    return RuntimeConfig(
        source_root=getattr(args, "source_root", None),
        db_path=getattr(args, "db_path", None),
        factor_path=getattr(args, "factor_path", None),
        export_path=getattr(args, "export_path", None),
        jypy_path=getattr(args, "jypy_path", None),
        gh_backtest_path=getattr(args, "gh_backtest_path", None),
        api_base=getattr(args, "api_base", None) or os.environ.get("GH_UI_API_BASE"),
    )


def emit_response(response, save: str | None = None) -> None:
    if response.data is not None:
        write_json(response.data, save=save)
        return
    if response.content_type.startswith("text/") or "event-stream" in response.content_type:
        text = (response.content or b"").decode("utf-8", errors="replace")
        if save:
            Path(save).expanduser().write_text(text, encoding="utf-8")
        print(text, end="" if text.endswith("\n") else "\n")
        return
    metadata = {
        "status_code": response.status_code,
        "content_type": response.content_type,
        "headers": response.headers or {},
    }
    write_bytes(response.content or b"", save, metadata)


def handle_doctor(args: argparse.Namespace) -> None:
    config = build_config(args)
    if config.api_base:
        _handle_api_base_doctor(config, args.save)
        return

    source_root = resolve_source_root(config)
    main_module = load_main_module(config)
    routes = route_inventory(config)
    data_methods = sorted(f"{m}/{f}" for m, f in getattr(main_module, "METHOD_MAP", {}).keys())
    download_methods = sorted(f"{m}/{f}" for m, f in getattr(main_module, "DOWNLOAD_MAP", {}).keys())
    stream_methods = sorted(f"{m}/{f}" for m, f in getattr(main_module, "STREAM_DOWNLOAD_MAP", {}).keys())
    update_methods = sorted(f"{m}/{f}" for m, f in getattr(main_module, "UPDATE_MAP", {}).keys())
    write_json(
        {
            "status": "ok",
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "source_root": str(source_root),
            "api_main": str(Path(main_module.__file__).resolve()),
            "db_path": getattr(main_module, "DB_PATH", ""),
            "factor_path": getattr(main_module, "FACTOR_PATH", ""),
            "export_path": getattr(main_module, "EXPORT_PATH", ""),
            "routes": len(routes),
            "data_query_methods": len(data_methods),
            "data_download_methods": len(set(download_methods + stream_methods)),
            "data_update_methods": len(update_methods),
            "sample_query_methods": data_methods[:10],
        },
        save=args.save,
    )


def handle_routes(args: argparse.Namespace) -> None:
    routes = _routes_for_config(build_config(args))
    if args.prefix:
        routes = [r for r in routes if str(r["path"]).startswith(args.prefix)]
    if args.method:
        method = args.method.upper()
        routes = [r for r in routes if method in r["methods"]]
    write_json(routes, save=args.save)


def handle_deps(args: argparse.Namespace) -> None:
    requirements = Path(args.requirements).expanduser() if args.requirements else _default_requirements(build_config(args))
    report = build_dependency_report(requirements, platform_name=args.platform or None)
    write_json(report, save=args.save)
    if args.strict and not report["ok"]:
        raise SystemExit(1)


def handle_coverage(args: argparse.Namespace) -> None:
    config = build_config(args)
    audit = _http_coverage_audit(config) if config.api_base else _coverage_audit(config)
    if args.summary:
        audit = _coverage_summary_from_audit(audit)
    write_json(audit, save=args.save)


def handle_manifest(args: argparse.Namespace) -> None:
    config = build_config(args)
    if args.category == "cli":
        audit = {"routes": {"operations": []}, "data_capabilities": {}, "factor_data_capabilities": []}
    else:
        audit = _http_coverage_audit(config) if config.api_base else _coverage_audit(config)
    manifest = build_agent_manifest(audit, category=args.category, global_args=_manifest_global_args(config))
    write_json(manifest, save=args.save)


def handle_verify(args: argparse.Namespace) -> None:
    report = _run_verify_report(args)
    write_json(report, save=args.save)
    if args.strict and not report["ok"]:
        raise SystemExit(1)
    if args.strict_goal and not report["completion_ready"]:
        raise SystemExit(1)


def _run_verify_report(args: argparse.Namespace) -> dict[str, Any]:
    config = build_config(args)
    checks: list[dict[str, Any]] = []
    mode = "api_base" if config.api_base else "source"

    if not config.api_base:
        dependency_report = build_dependency_report(_default_requirements(config), platform_name=args.platform or None)
        checks.append({"name": "dependencies", "ok": dependency_report["ok"], "report": dependency_report})

    try:
        summary = _http_coverage_summary(config) if config.api_base else _coverage_summary(config)
        checks.append({"name": "coverage", "ok": bool(summary["all_callables"]), **summary})
    except Exception as exc:
        checks.append({"name": "coverage", "ok": False, "error": str(exc), "type": type(exc).__name__})

    smoke_checks = (
        run_api_base_checks(create_api_client(config), with_data_query=args.with_data_query)
        if config.api_base
        else _source_smoke_checks(config, with_data_query=args.with_data_query)
    )
    smoke_report = build_smoke_report(
        smoke_checks,
        platform_name=platform.platform(),
        python_version=sys.version.split()[0],
    )
    checks.append({"name": "smoke", "ok": smoke_report["ok"], "report": smoke_report})

    if args.windows_deps_preflight:
        if config.api_base:
            checks.append(
                {
                    "name": "windows_dependency_preflight",
                    "ok": True,
                    "skipped": True,
                    "note": "Skipped in API-base mode because no source requirements file is required.",
                }
            )
        else:
            windows_report = build_dependency_report(_default_requirements(config), platform_name="win32")
            checks.append(_windows_dependency_preflight_check(windows_report))

    report = build_goal_verification_report(
        checks=checks,
        platform_name=platform.platform(),
        current_platform=sys.platform,
        mode=mode,
    )
    return report


def handle_verify_merge(args: argparse.Namespace) -> None:
    reports = [_read_verify_report_arg(path) for path in _expand_verify_report_args(args.reports)]
    report = merge_goal_verification_reports(reports)
    write_json(report, save=args.save)
    if args.strict and not report["ok"]:
        raise SystemExit(1)
    if args.strict_goal and not report["completion_ready"]:
        raise SystemExit(1)


def handle_verify_plan(args: argparse.Namespace) -> None:
    write_json(
        build_verification_plan(
            mac_report=args.mac_report,
            windows_report=args.windows_report,
            artifact_dir=args.artifact_dir,
        ),
        save=args.save,
    )


def handle_ci_status(args: argparse.Namespace) -> None:
    report = _build_ci_status_report(args)
    write_json(report, save=args.save)
    if args.strict and not report["ci_ready"]:
        raise SystemExit(1)


def handle_ci_log_report(args: argparse.Namespace) -> None:
    repo_args = ["--repo", args.repo] if args.repo else []
    log_text = _run_gh_text(["run", "view", args.run_id, *repo_args, "--log"])
    reports = _extract_marked_verify_reports(log_text)
    selected = _select_marked_verify_report(
        reports,
        platform_name=args.platform,
        job_contains=args.job_contains,
    )
    if selected is None:
        write_json(
            {
                "error": "No matching marked verify report found in CI logs.",
                "reports": [
                    {
                        "job": report["job"],
                        "current_platform": report["report"].get("current_platform", ""),
                    }
                    for report in reports
                ],
            }
        )
        if args.strict:
            raise SystemExit(1)
        return
    write_json(selected["report"], save=args.save)


def _extract_marked_verify_reports(log_text: str) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    capturing = False
    current_job = ""
    buffer: list[str] = []
    for raw_line in log_text.splitlines():
        job, content = _ci_log_content(raw_line)
        if job:
            current_job = job
        if "GH_UI_VERIFY_REPORT_BEGIN" in content:
            capturing = True
            buffer = []
            continue
        if "GH_UI_VERIFY_REPORT_END" in content and capturing:
            try:
                report = json.loads("\n".join(buffer))
            except json.JSONDecodeError:
                report = {}
            if isinstance(report, dict) and report:
                reports.append({"job": current_job, "report": report})
            capturing = False
            continue
        if capturing:
            buffer.append(content)
    return reports


def _ci_log_content(line: str) -> tuple[str, str]:
    parts = line.split("\t", 2)
    if len(parts) >= 3:
        content = re.sub(r"^\ufeff?\d{4}-\d{2}-\d{2}T[^ ]+Z ", "", parts[2])
        return parts[0], content
    return "", line


def _select_marked_verify_report(
    reports: list[dict[str, Any]],
    *,
    platform_name: str,
    job_contains: str,
) -> dict[str, Any] | None:
    for item in reversed(reports):
        report = item["report"]
        if platform_name and str(report.get("current_platform", "")) != platform_name:
            continue
        if job_contains and job_contains not in str(item.get("job", "")):
            continue
        return item
    return None


def _build_ci_status_report(args: argparse.Namespace) -> dict[str, Any]:
    repo = str(args.repo or os.environ.get("GH_REPOSITORY", ""))
    workflow = str(args.workflow)
    commands = _ci_status_commands(
        repo=repo,
        workflow=workflow,
        ref=str(args.ref),
        artifact_name=str(args.artifact_name),
        artifact_dir=str(args.artifact_dir),
        mac_report=str(args.mac_report),
    )
    base: dict[str, Any] = {
        "repo": repo,
        "workflow": workflow,
        "ref": str(args.ref),
        "artifact_name": str(args.artifact_name),
        "artifact_dir": str(args.artifact_dir),
        "workflow_found": False,
        "workflow_state": "",
        "latest_runs": [],
        "windows_artifact_found": False,
        "windows_artifact": {},
        "ci_ready": False,
        "commands": commands,
        "next_actions": [],
    }
    if not repo:
        base["next_actions"].append(
            {
                "kind": "set_repo",
                "reason": "Set --repo OWNER/REPO or GH_REPOSITORY before checking GitHub Actions.",
            }
        )
        return base

    try:
        workflows = _run_gh_json(["api", f"repos/{repo}/actions/workflows"])
    except Exception as exc:
        base["gh_error"] = str(exc)
        base["next_actions"].append(
            {
                "kind": "check_gh_auth",
                "reason": "GitHub CLI could not read repository workflows.",
                "argv": ["gh", "auth", "status"],
            }
        )
        return base

    matched_workflow = _find_workflow(workflows.get("workflows", []), workflow)
    if not matched_workflow:
        base["next_actions"].append(
            {
                "kind": "publish_workflow",
                "reason": "No matching GitHub Actions workflow is available on the remote repository.",
                "local_path": ".github/workflows/ci.yml",
            }
        )
        return base

    workflow_id = matched_workflow.get("id", workflow)
    base["workflow_found"] = True
    base["workflow_id"] = workflow_id
    base["workflow_state"] = str(matched_workflow.get("state", ""))
    base["workflow_path"] = str(matched_workflow.get("path", ""))
    try:
        runs = _run_gh_json(["api", f"repos/{repo}/actions/workflows/{workflow_id}/runs?per_page=5"])
    except Exception as exc:
        base["gh_error"] = str(exc)
        base["next_actions"].append(
            {
                "kind": "list_runs",
                "reason": "Workflow exists, but GitHub CLI could not list workflow runs.",
                "argv": commands["list_ci_runs"]["argv"],
            }
        )
        return base

    latest_runs = [_run_summary(run) for run in runs.get("workflow_runs", [])]
    base["latest_runs"] = latest_runs
    successful_run = next(
        (run for run in latest_runs if run["status"] == "completed" and run["conclusion"] == "success"),
        None,
    )
    if successful_run:
        base["latest_successful_run"] = successful_run
        try:
            artifacts = _run_gh_json(
                ["api", f"repos/{repo}/actions/runs/{successful_run['id']}/artifacts"]
            )
        except Exception as exc:
            base["gh_error"] = str(exc)
            base["next_actions"].append(
                {
                    "kind": "list_artifacts",
                    "reason": "A successful workflow run exists, but GitHub CLI could not list its artifacts.",
                    "run_id": successful_run["id"],
                }
            )
            return base
        artifact = _find_artifact(artifacts.get("artifacts", []), str(args.artifact_name))
        if artifact and artifact.get("expired") is True:
            base["windows_artifact"] = artifact
            base["next_actions"].append(
                {
                    "kind": "rerun_ci_workflow",
                    "reason": "Expected Windows artifact is expired.",
                    "expected_artifact": str(args.artifact_name),
                    "argv": commands["dispatch_ci_workflow"]["argv"],
                }
            )
        elif artifact:
            base["windows_artifact_found"] = True
            base["windows_artifact"] = artifact
            base["ci_ready"] = True
        else:
            base["next_actions"].append(
                {
                    "kind": "rerun_ci_workflow",
                    "reason": "A successful workflow run exists, but the expected Windows artifact was not found.",
                    "expected_artifact": str(args.artifact_name),
                    "argv": commands["dispatch_ci_workflow"]["argv"],
                }
            )
    else:
        base["next_actions"].append(
            {
                "kind": "dispatch_ci_workflow",
                "reason": "No successful workflow run is available for downloading Windows verification artifacts.",
                "argv": commands["dispatch_ci_workflow"]["argv"],
            }
        )
    return base


def _ci_status_commands(
    *,
    repo: str,
    workflow: str,
    ref: str,
    artifact_name: str,
    artifact_dir: str,
    mac_report: str,
) -> dict[str, dict[str, Any]]:
    repo_args = ["--repo", repo] if repo else []
    return {
        "dispatch_ci_workflow": _command_spec(["gh", "workflow", "run", workflow, *repo_args, "--ref", ref]),
        "list_ci_runs": _command_spec(["gh", "run", "list", *repo_args, "--workflow", workflow, "--limit", "5"]),
        "download_windows_ci_artifact": _command_spec(
            ["gh", "run", "download", *repo_args, "--name", artifact_name, "--dir", artifact_dir]
        ),
        "merge_artifacts": _command_spec(["gh-ui", "verify-merge", mac_report, artifact_dir, "--strict-goal"]),
    }


def _command_spec(argv: list[str]) -> dict[str, Any]:
    return {"argv": argv, "command_shell": _shell_commands(argv)}


def _run_gh_json(args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"gh exited {completed.returncode}"
        raise RuntimeError(message)
    if not completed.stdout.strip():
        return {}
    return json.loads(completed.stdout)


def _run_gh_text(args: list[str]) -> str:
    completed = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"gh exited {completed.returncode}"
        raise RuntimeError(message)
    return completed.stdout


def _find_workflow(workflows: Any, workflow: str) -> dict[str, Any] | None:
    if not isinstance(workflows, list):
        return None
    for item in workflows:
        if not isinstance(item, dict):
            continue
        candidates = {
            str(item.get("id", "")),
            str(item.get("name", "")),
            str(item.get("path", "")),
            Path(str(item.get("path", ""))).name,
        }
        if workflow in candidates:
            return item
    return None


def _find_artifact(artifacts: Any, artifact_name: str) -> dict[str, Any] | None:
    if not isinstance(artifacts, list):
        return None
    for item in artifacts:
        if isinstance(item, dict) and str(item.get("name", "")) == artifact_name:
            return item
    return None


def _run_summary(run: Any) -> dict[str, str]:
    if not isinstance(run, dict):
        return {}
    return {
        "id": str(run.get("id", "")),
        "name": str(run.get("name", "")),
        "status": str(run.get("status", "")),
        "conclusion": str(run.get("conclusion", "")),
        "head_branch": str(run.get("head_branch", "")),
        "created_at": str(run.get("created_at", "")),
        "html_url": str(run.get("html_url", "")),
    }


def handle_verify_bundle(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_report_path = output_dir / args.source_report
    plan_path = output_dir / "verify-plan.json"
    manifest_path = output_dir / "manifest-cli.json"
    readme_path = output_dir / "README_NEXT.md"

    report = _run_verify_report(args)
    plan = build_verification_plan(
        mac_report=args.source_report,
        windows_report=args.windows_report,
        artifact_dir=args.artifact_dir,
    )
    manifest = _cli_manifest()
    _write_json_file(source_report_path, report)
    _write_json_file(plan_path, plan)
    _write_json_file(manifest_path, manifest)
    readme_path.write_text(
        _verification_bundle_readme(
            source_report=args.source_report,
            windows_report=args.windows_report,
            artifact_dir=args.artifact_dir,
            plan=plan,
        ),
        encoding="utf-8",
    )
    summary = {
        "output_dir": str(output_dir),
        "source_report": {
            "ok": bool(report.get("ok")),
            "completion_ready": bool(report.get("completion_ready")),
            "platform": report.get("platform", ""),
            "current_platform": report.get("current_platform", ""),
        },
        "files": {
            "source_report": str(source_report_path),
            "verify_plan": str(plan_path),
            "manifest_cli": str(manifest_path),
            "readme": str(readme_path),
        },
        "next": plan["commands"]["windows_runtime_report"],
    }
    write_json(summary, save=args.save)
    if args.strict and not report["ok"]:
        raise SystemExit(1)


def _cli_manifest() -> dict[str, Any]:
    audit = {"routes": {"operations": []}, "data_capabilities": {}, "factor_data_capabilities": []}
    return build_agent_manifest(audit, category="cli", global_args=[])


def _write_json_file(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _verification_bundle_readme(
    *,
    source_report: str,
    windows_report: str,
    artifact_dir: str,
    plan: dict[str, Any],
) -> str:
    windows_runtime = plan["commands"]["windows_runtime_report"]["command_shell"]["posix"]
    windows_sidecar = plan["commands"]["windows_http_sidecar_report"]["command_shell"]["posix"]
    merge_reports = plan["commands"]["merge_reports"]["command_shell"]["posix"]
    merge_artifacts = plan["commands"]["merge_artifacts"]["command_shell"]["posix"]
    download_artifact = plan["commands"]["download_windows_ci_artifact"]["command_shell"]["posix"]
    ci_status = plan["commands"]["check_github_actions_status"]["command_shell"]["posix"]
    ci_log_report = plan["commands"]["extract_windows_ci_log_report"]["command_shell"]["posix"]
    return (
        "# gh-ui verification bundle\n\n"
        "This directory contains the current source verification report, the CLI manifest, "
        "and the machine-readable plan for completing cross-platform evidence.\n\n"
        "Files:\n"
        f"- {source_report}: source-mode report from the current machine.\n"
        f"- {windows_report}: expected Windows runtime report to add later.\n"
        "- verify-plan.json: requirements and platform-specific commands.\n"
        "- manifest-cli.json: local CLI operations available to agents.\n\n"
        "Run on Windows after installing gh-ui:\n\n"
        f"```powershell\n{windows_runtime}\n```\n\n"
        "If a gh_quant_ui sidecar is already running on Windows:\n\n"
        f"```powershell\n{windows_sidecar}\n```\n\n"
        "Then merge reports:\n\n"
        f"```bash\n{merge_reports}\n```\n\n"
        "Check GitHub Actions evidence before downloading artifacts:\n\n"
        f"```bash\n{ci_status}\n```\n\n"
        "If artifact upload is unavailable, extract the Windows report from CI logs:\n\n"
        f"```bash\n{ci_log_report}\n```\n\n"
        "Or download and merge CI artifacts:\n\n"
        f"```bash\n{download_artifact}\n{merge_artifacts}\n```\n"
    )


def _expand_verify_report_args(values: list[str]) -> list[str]:
    expanded: list[str] = []
    for value in values:
        if value == "-" or value.startswith("@"):
            expanded.append(value)
            continue
        path = Path(value).expanduser()
        if path.is_dir():
            reports = sorted(candidate for candidate in path.rglob("*.json") if candidate.is_file())
            if not reports:
                raise SystemExit(f"No JSON verify reports found in directory: {path}")
            expanded.extend(str(report) for report in reports)
            continue
        expanded.append(value)
    return expanded


def _read_verify_report_arg(value: str) -> Any:
    path = Path(value).expanduser()
    if value not in {"-"} and not value.startswith("@") and path.exists():
        return read_json_arg("@" + str(path))
    return read_json_arg(value)


def handle_runtime_verify(args: argparse.Namespace) -> None:
    report = run_runtime_verify(args.output)
    write_json(
        {
            "output": str(Path(args.output)),
            "ok": bool(report.get("ok")),
            "completion_ready": bool(report.get("completion_ready")),
            "platform": report.get("platform", ""),
            "current_platform": report.get("current_platform", ""),
        }
    )


def _http_coverage_audit(config: RuntimeConfig) -> dict[str, Any]:
    response = create_api_client(config).request("GET", "/openapi.json", prefix="")
    schema = response.data or {}
    route_audit = audit_routes(routes_from_openapi(schema))
    return {
        "all_callables": route_audit["coverage_ratio"] == 1.0,
        "totals": {
            "route_operations": route_audit["total_operations"],
            "data_query_methods": 0,
            "data_download_methods": 0,
            "data_update_methods": 0,
            "factor_data_tables": 0,
        },
        "routes": route_audit,
        "data_capabilities": {"query": [], "download": [], "update": []},
        "factor_data_capabilities": [],
        "openapi_components": schema.get("components", {}),
        "mode": "api_base",
        "note": "HTTP mode derives route operations from /openapi.json; dynamic METHOD_MAP details require source mode.",
    }


def _handle_api_base_doctor(config: RuntimeConfig, save: str | None) -> None:
    client = create_api_client(config)
    health = client.request("GET", "/health").data or {}
    routes = routes_from_openapi(client.request("GET", "/openapi.json", prefix="").data or {})
    route_audit = audit_routes(routes)
    write_json(
        {
            "status": "ok" if health.get("status") == "ok" else "error",
            "mode": "api_base",
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "api_base": config.api_base,
            "health": health,
            "routes": len(routes),
            "route_operations": route_audit["total_operations"],
            "route_coverage_ratio": route_audit["coverage_ratio"],
            "route_categories": route_audit["categories"],
            "missing_route_operations": route_audit["missing_operations"],
        },
        save=save,
    )


def _routes_for_config(config: RuntimeConfig) -> list[dict[str, Any]]:
    if not config.api_base:
        return route_inventory(config)
    response = create_api_client(config).request("GET", "/openapi.json", prefix="")
    return routes_from_openapi(response.data or {})


def _default_requirements(config: RuntimeConfig) -> Path:
    return resolve_source_root(config) / "api" / "requirements.txt"


def _coverage_audit(config: RuntimeConfig) -> dict[str, Any]:
    source_root = resolve_source_root(config)
    main_module = load_main_module(config)
    schema = main_module.app.openapi()
    routes = enrich_routes_from_openapi(route_inventory(config), schema)
    download_methods = set(getattr(main_module, "DOWNLOAD_MAP", {}).keys()) | set(
        getattr(main_module, "STREAM_DOWNLOAD_MAP", {}).keys()
    )
    factor_tables = []
    try:
        import factor  # type: ignore

        factor_tables = ["factor_info", *getattr(factor, "_FACTOR_VALUE_TABLES", [])]
    except Exception:
        factor_tables = []
    audit = audit_backend(
        routes,
        query_methods=list(getattr(main_module, "METHOD_MAP", {}).keys()),
        download_methods=download_methods,
        update_methods=list(getattr(main_module, "UPDATE_MAP", {}).keys()),
        factor_tables=factor_tables,
    )
    frontend_references = audit_frontend_api_references(source_root, routes)
    audit["frontend_api_references"] = frontend_references
    audit["totals"]["frontend_api_references"] = frontend_references["total_references"]
    audit["all_callables"] = bool(audit["all_callables"] and not frontend_references["missing_references"])
    audit["openapi_components"] = schema.get("components", {})
    return audit


def _preferred_command_parse_audit(audit: dict[str, Any]) -> dict[str, Any]:
    parser = build_parser()
    entries = _preferred_command_entries(audit)
    unparseable = []
    for entry in entries:
        command = entry["command"]
        try:
            argv = _normalized_command_argv(command)
        except ValueError as exc:
            unparseable.append({**entry, "error": str(exc), "argv": []})
            continue
        stderr = StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                parser.parse_args(argv)
        except SystemExit as exc:
            unparseable.append(
                {
                    **entry,
                    "argv": argv,
                    "error": stderr.getvalue().strip() or f"argparse exited with {exc.code}",
                }
            )
    total = len(entries)
    parseable = total - len(unparseable)
    return {
        "total": total,
        "parseable": parseable,
        "unparseable": unparseable,
        "coverage_ratio": parseable / total if total else 1.0,
        "all_parseable": not unparseable,
    }


def _preferred_command_entries(audit: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for operation in audit.get("routes", {}).get("operations", []):
        command = str(operation.get("preferred") or "")
        if command:
            entries.append(
                {
                    "kind": "route",
                    "path": str(operation.get("path", "")),
                    "method": str(operation.get("method", "")),
                    "category": str(operation.get("category", "")),
                    "command": command,
                }
            )
    for action, items in audit.get("data_capabilities", {}).items():
        for item in items:
            command = str(item.get("preferred") or "")
            if command:
                entries.append(
                    {
                        "kind": "data",
                        "action": str(action),
                        "module": str(item.get("module", "")),
                        "method": str(item.get("method", "")),
                        "category": "data",
                        "command": command,
                    }
                )
    for item in audit.get("factor_data_capabilities", []):
        table = str(item.get("table", ""))
        for action in ("query", "download", "update"):
            command = str(item.get(action) or "")
            if command:
                entries.append(
                    {
                        "kind": "factor_data",
                        "action": action,
                        "table": table,
                        "category": "factor_data",
                        "command": command,
                    }
                )
    return entries


def _normalized_command_argv(command: str) -> list[str]:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ValueError(f"cannot split command: {exc}") from exc
    if not parts:
        raise ValueError("empty command")
    if parts[0] != "gh-ui":
        raise ValueError("preferred command must start with gh-ui")
    return [_normalize_preferred_arg(part) for part in parts[1:]]


def _normalize_preferred_arg(value: str) -> str:
    normalized = value
    for placeholder, replacement in ANGLE_PLACEHOLDERS.items():
        normalized = normalized.replace(placeholder, replacement)

    def replace_braced(match: re.Match[str]) -> str:
        name = match.group(1)
        return BRACED_PLACEHOLDERS.get(name, f"value_{name}")

    return BRACED_PLACEHOLDER_RE.sub(replace_braced, normalized)


def _coverage_summary_from_audit(audit: dict[str, Any]) -> dict[str, Any]:
    preferred_command_parse = _preferred_command_parse_audit(audit)
    return {
        "all_callables": bool(audit["all_callables"] and preferred_command_parse["all_parseable"]),
        "totals": audit["totals"],
        "route_coverage_ratio": audit["routes"]["coverage_ratio"],
        "route_categories": audit["routes"]["categories"],
        "missing_route_operations": audit["routes"]["missing_operations"],
        "preferred_command_parse": preferred_command_parse,
        "frontend_api_references": audit.get("frontend_api_references", {}),
    }


def _coverage_summary(config: RuntimeConfig) -> dict[str, Any]:
    return _coverage_summary_from_audit(_coverage_audit(config))


def _http_coverage_summary(config: RuntimeConfig) -> dict[str, Any]:
    return _coverage_summary_from_audit(_http_coverage_audit(config))


def _windows_dependency_preflight_check(report: dict[str, Any]) -> dict[str, Any]:
    missing = report.get("missing", [])
    missing_items = [item for item in missing if isinstance(item, dict)]
    only_windows_marker_missing = len(missing_items) == len(missing) and bool(missing_items) and all(
        'sys_platform == "win32"' in str(item.get("marker", "")) for item in missing_items
    )
    ok = bool(report.get("ok")) or (sys.platform != "win32" and only_windows_marker_missing)
    check = {
        "name": "windows_dependency_preflight",
        "ok": ok,
        "report": report,
    }
    if ok and not report.get("ok"):
        check["note"] = "Static Windows preflight only; run verify on Windows for runtime evidence."
    return check


def _manifest_global_args(config: RuntimeConfig) -> list[str]:
    options: list[str] = []
    if config.api_base:
        options.extend(["--api-base", config.api_base])
    for flag, value in (
        ("--source-root", config.source_root),
        ("--db-path", config.db_path),
        ("--factor-path", config.factor_path),
        ("--export-path", config.export_path),
        ("--jypy-path", config.jypy_path),
        ("--gh-backtest-path", config.gh_backtest_path),
    ):
        if value is not None:
            options.extend([flag, str(value.expanduser())])
    return options


def handle_smoke(args: argparse.Namespace) -> None:
    config = build_config(args)

    if config.api_base:
        checks = run_api_base_checks(create_api_client(config), with_data_query=args.with_data_query)
        report = build_smoke_report(
            checks,
            platform_name=platform.platform(),
            python_version=sys.version.split()[0],
        )
        write_json(report, save=args.save)
        if not report["ok"]:
            raise SystemExit(1)
        return

    checks = _source_smoke_checks(config, with_data_query=args.with_data_query)
    report = build_smoke_report(
        checks,
        platform_name=platform.platform(),
        python_version=sys.version.split()[0],
    )
    write_json(report, save=args.save)
    if not report["ok"]:
        raise SystemExit(1)


def _source_smoke_checks(config: RuntimeConfig, *, with_data_query: bool) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = [run_profile_check()]
    source_ok = False
    try:
        source_root = resolve_source_root(config)
        main_module = load_main_module(config)
        source_ok = True
        checks.append(
            {
                "name": "source",
                "ok": True,
                "source_root": str(source_root),
                "api_main": str(Path(main_module.__file__).resolve()),
            }
        )
    except Exception as exc:
        checks.append({"name": "source", "ok": False, "error": str(exc), "type": type(exc).__name__})

    if source_ok:
        try:
            summary = _coverage_summary(config)
            checks.append({"name": "coverage", "ok": bool(summary["all_callables"]), **summary})
        except Exception as exc:
            checks.append({"name": "coverage", "ok": False, "error": str(exc), "type": type(exc).__name__})

    if source_ok:
        try:
            response = LocalApiClient(config).request("GET", "/health")
            checks.append({"name": "health", "ok": response.data.get("status") == "ok", "response": response.data})
        except Exception as exc:
            checks.append({"name": "health", "ok": False, "error": str(exc), "type": type(exc).__name__})

    if with_data_query and source_ok:
        try:
            response = LocalApiClient(config).request(
                "GET", "/stock/stock_code", params={"market": "ashare", "limit": 1}
            )
            checks.append(
                {
                    "name": "data_query",
                    "ok": bool(response.data and response.data.get("total", 0) >= 1),
                    "total": response.data.get("total") if response.data else 0,
                    "sample": response.data.get("data", [])[:1] if response.data else [],
                }
            )
        except Exception as exc:
            checks.append({"name": "data_query", "ok": False, "error": str(exc), "type": type(exc).__name__})

    return checks


def _client(args: argparse.Namespace):
    return create_api_client(build_config(args))


def handle_health(args: argparse.Namespace) -> None:
    emit_response(_client(args).request("GET", "/health"), save=args.save)


def handle_api_request(args: argparse.Namespace, prefix: str = "/api") -> None:
    params = parse_key_values(args.param)
    headers = parse_key_values(args.header)
    body = read_json_arg(args.json, default=None)
    response = _client(args).request(
        args.method,
        args.path,
        params=params,
        json_body=body,
        headers={str(k): str(v) for k, v in headers.items()},
        file_path=args.file,
        file_field=args.file_field,
        prefix=prefix,
    )
    emit_response(response, save=args.save)


def handle_invoke(args: argparse.Namespace) -> None:
    params = parse_key_values(args.param)
    headers = parse_key_values(args.header)
    invoke_request = build_invoke_request(
        args.target_id,
        params=params,
        json_body=read_json_arg(args.json, default=None),
        token=args.token,
        server=args.server,
    )
    response = _client(args).request(
        invoke_request.method,
        invoke_request.path,
        params=invoke_request.params,
        json_body=invoke_request.json_body,
        headers={str(k): str(v) for k, v in headers.items()},
        file_path=args.file,
        file_field=args.file_field,
    )
    emit_response(response, save=args.save)


def handle_data_modules(args: argparse.Namespace) -> None:
    main_module = load_main_module(build_config(args))
    methods: dict[str, list[str]] = {}
    for module, method in sorted(getattr(main_module, "METHOD_MAP", {}).keys()):
        methods.setdefault(module, []).append(method)

    try:
        import factor  # type: ignore

        factor_tables = ["factor_info", *getattr(factor, "_FACTOR_VALUE_TABLES", [])]
        methods["factor_data"] = factor_tables
    except Exception:
        pass

    write_json(methods, save=args.save)


def _data_params(args: argparse.Namespace) -> dict[str, Any]:
    params = parse_key_values(args.param)
    if getattr(args, "limit", None) is not None:
        params["limit"] = args.limit
    return params


def handle_data_query(args: argparse.Namespace) -> None:
    params = _data_params(args)
    if args.module == "factor_data":
        path = f"/factor/db/query/{args.method_name}"
    else:
        path = f"/{args.module}/{args.method_name}"
    response = _client(args).request("GET", path, params=params)
    emit_response(response, save=args.save)


def _download_body(args: argparse.Namespace) -> dict[str, Any]:
    body = parse_key_values(args.param)
    body["token"] = resolve_api_token(args.token)
    body["server"] = resolve_server(args.server)
    return body


def handle_data_download(args: argparse.Namespace) -> None:
    if args.module == "factor_data":
        params = {"token": resolve_api_token(args.token)}
        response = _client(args).request(
            "POST", f"/factor/db/download/{args.method_name}", params=params
        )
    else:
        response = _client(args).request(
            "POST", f"/download/{args.module}/{args.method_name}", json_body=_download_body(args)
        )
    emit_response(response, save=args.save)


def handle_data_update(args: argparse.Namespace) -> None:
    if args.module == "factor_data":
        params = {"token": resolve_api_token(args.token)}
        response = _client(args).request(
            "POST", f"/factor/db/update/{args.method_name}", params=params
        )
    else:
        response = _client(args).request(
            "POST", f"/update/{args.module}/{args.method_name}", json_body=_download_body(args)
        )
    emit_response(response, save=args.save)


def handle_data_progress(args: argparse.Namespace) -> None:
    path = "/factor/db/progress" if args.factor else "/download/progress"
    emit_response(_client(args).request("GET", path), save=args.save)


def handle_data_files(args: argparse.Namespace) -> None:
    emit_response(_client(args).request("GET", "/local/files"), save=args.save)


def handle_profile_get(args: argparse.Namespace) -> None:
    write_json(public_profile(), save=args.save)


def handle_profile_set(args: argparse.Namespace) -> None:
    profile = load_profile()
    updates = {
        "api_token": args.api_token,
        "access_token": args.access_token,
        "server": args.server,
        "username": args.username,
    }
    changed = {key: value for key, value in updates.items() if value is not None}
    if not changed:
        raise ValueError("provide at least one profile field to set")
    profile.update(changed)
    save_profile(profile)
    write_json(public_profile(), save=args.save)


def handle_profile_clear(args: argparse.Namespace) -> None:
    path = profile_path()
    clear_profile(path)
    write_json({"cleared": True, "path": str(path)}, save=args.save)


def handle_data_quick_update(args: argparse.Namespace) -> None:
    results = []
    client = _client(args)
    token = resolve_api_token(args.token)
    server = resolve_server(args.server)
    for module, method_name, default_params in CORE_QUICK_UPDATE:
        body = {**default_params, **parse_key_values(args.param), "token": token, "server": server}
        try:
            response = client.request("POST", f"/update/{module}/{method_name}", json_body=body)
            results.append({"module": module, "method": method_name, "ok": True, "result": response.data})
        except ApiError as exc:
            results.append({"module": module, "method": method_name, "ok": False, "error": exc.detail})
            if not args.continue_on_error:
                break
    write_json({"items": results}, save=args.save)


def handle_config_get(args: argparse.Namespace) -> None:
    emit_response(_client(args).request("GET", "/config/paths"), save=args.save)


def handle_config_set(args: argparse.Namespace) -> None:
    body = parse_key_values(args.param)
    for key in ("db_path", "factor_path", "export_path", "default_start_date"):
        value = getattr(args, key, None)
        if value is not None:
            body[key] = str(value)
    emit_response(_client(args).request("POST", "/config/paths", json_body=body), save=args.save)


def handle_logs(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit}
    if args.category:
        params["category"] = args.category
    emit_response(_client(args).request("GET", "/logs", params=params), save=args.save)


def handle_export_excel(args: argparse.Namespace) -> None:
    payload = read_json_arg(args.input, default={})
    if isinstance(payload, list):
        data = payload
        columns = args.columns.split(",") if args.columns else list(data[0].keys()) if data else []
    elif isinstance(payload, dict):
        data = payload.get("data", [])
        columns = payload.get("columns") or (args.columns.split(",") if args.columns else [])
    else:
        raise ValueError("--input must be a JSON array or object")
    body = {
        "data": data,
        "columns": columns,
        "filename": args.filename,
        "sheet_name": args.sheet_name,
    }
    emit_response(_client(args).request("POST", "/export/excel", json_body=body), save=args.save)


def handle_feedback_submit(args: argparse.Namespace) -> None:
    body = read_json_arg(args.json, default={})
    if not isinstance(body, dict):
        raise ValueError("--json must be a JSON object")
    if args.content is not None:
        body["content"] = args.content
    if args.category is not None:
        body["category"] = args.category
    if args.contact is not None:
        body["contact"] = args.contact
    if not str(body.get("content") or "").strip():
        raise ValueError("--content or --json with content is required")
    emit_response(_client(args).request("POST", "/feedback", json_body=body), save=args.save)


def handle_auth_verify(args: argparse.Namespace) -> None:
    body = read_json_arg(args.json, default={})
    if not isinstance(body, dict):
        raise ValueError("--json must be a JSON object")
    if args.token:
        body["token"] = args.token
    if not body.get("token"):
        body["token"] = resolve_api_token(None)
    emit_response(_client(args).request("POST", "/auth/verify", json_body=body), save=args.save)


def handle_auth_login(args: argparse.Namespace) -> None:
    body = read_json_arg(args.json, default={})
    if not isinstance(body, dict):
        raise ValueError("--json must be a JSON object")
    if args.username:
        body["username"] = args.username
    if args.password:
        body["password"] = args.password
    if not body.get("username") or not body.get("password"):
        raise ValueError("--username/--password or --json with username/password is required")
    emit_response(_client(args).request("POST", "/auth/login", json_body=body), save=args.save)


def handle_auth_active_token(args: argparse.Namespace) -> None:
    access_token = resolve_access_token(args.access_token)
    emit_response(
        _client(args).request(
            "POST",
            "/auth/active-token",
            headers={"Authorization": _bearer_token(access_token)},
        ),
        save=args.save,
    )


def _access_headers(args: argparse.Namespace) -> dict[str, str]:
    access_token = resolve_access_token(args.access_token)
    return {"Authorization": _bearer_token(access_token)}


def _bearer_token(access_token: str) -> str:
    if access_token.lower().startswith("bearer "):
        return access_token
    return f"Bearer {access_token}"


def handle_remote_me(args: argparse.Namespace) -> None:
    emit_response(_client(args).request("GET", "/remote/me", headers=_access_headers(args)), save=args.save)


def handle_remote_tokens(args: argparse.Namespace) -> None:
    emit_response(_client(args).request("GET", "/remote/tokens", headers=_access_headers(args)), save=args.save)


def handle_remote_token_generate(args: argparse.Namespace) -> None:
    body = read_json_arg(args.json, default={})
    if not isinstance(body, dict):
        raise ValueError("--json must be a JSON object")
    if args.name is not None:
        body["name"] = args.name
    else:
        body.setdefault("name", None)
    emit_response(
        _client(args).request("POST", "/remote/tokens", json_body=body, headers=_access_headers(args)),
        save=args.save,
    )


def handle_remote_token_revoke(args: argparse.Namespace) -> None:
    emit_response(
        _client(args).request(
            "DELETE",
            f"/remote/tokens/{args.token_id}",
            headers=_access_headers(args),
        ),
        save=args.save,
    )


def handle_ai_get(args: argparse.Namespace) -> None:
    emit_response(_client(args).request("GET", args.api_path, params=parse_key_values(args.param)), save=args.save)


def handle_ai_task(args: argparse.Namespace) -> None:
    emit_response(
        _client(args).request(
            "GET",
            f"/ai/report-reproduce/tasks/{args.task_id}",
            params=parse_key_values(args.param),
        ),
        save=args.save,
    )


def handle_ai_start(args: argparse.Namespace) -> None:
    emit_response(
        _client(args).request(
            "POST",
            "/ai/report-reproduce/start",
            json_body=read_json_arg(args.json, default={}),
        ),
        save=args.save,
    )


def handle_ai_cancel(args: argparse.Namespace) -> None:
    emit_response(
        _client(args).request(
            "POST",
            f"/ai/report-reproduce/tasks/{args.task_id}/cancel",
            params=parse_key_values(args.param),
        ),
        save=args.save,
    )


def handle_factor_simple(args: argparse.Namespace) -> None:
    emit_response(_client(args).request(args.http_method, args.api_path, params=parse_key_values(args.param)), save=args.save)


def handle_factor_json(args: argparse.Namespace) -> None:
    emit_response(
        _client(args).request(args.http_method, args.api_path, json_body=read_json_arg(args.json, default={})),
        save=args.save,
    )


def handle_factor_upload(args: argparse.Namespace) -> None:
    emit_response(_client(args).request("POST", "/factor/upload", file_path=args.file), save=args.save)


def handle_backtest_json(args: argparse.Namespace) -> None:
    emit_response(
        _client(args).request(args.http_method, args.api_path, json_body=read_json_arg(args.json, default={})),
        save=args.save,
    )


def handle_backtest_simple(args: argparse.Namespace) -> None:
    emit_response(_client(args).request(args.http_method, args.api_path, params=parse_key_values(args.param)), save=args.save)


def handle_backtest_upload(args: argparse.Namespace) -> None:
    emit_response(_client(args).request("POST", "/backtest/upload-portfolio", file_path=args.file), save=args.save)


def handle_backtest_uploaded_portfolio(args: argparse.Namespace) -> None:
    emit_response(
        _client(args).request("GET", f"/backtest/uploaded-portfolio/{args.upload_id}"),
        save=args.save,
    )


def handle_backtest_monitoring_holdings(args: argparse.Namespace) -> None:
    params = {
        "upload_id": args.upload_id,
        "date": args.date,
        "benchmark_index": args.benchmark_index,
        "aum": args.aum,
    }
    emit_response(_client(args).request("GET", "/backtest/monitoring/holdings", params=params), save=args.save)


def handle_wechat_simple(args: argparse.Namespace) -> None:
    emit_response(_client(args).request(args.http_method, args.api_path, params=parse_key_values(args.param)), save=args.save)


def handle_wechat_json(args: argparse.Namespace) -> None:
    emit_response(
        _client(args).request(args.http_method, args.api_path, json_body=read_json_arg(args.json, default={})),
        save=args.save,
    )


def _encoded_path_value(value: Any) -> str:
    return quote(str(value), safe="")


def _format_api_path(template: str, args: argparse.Namespace, names: tuple[str, ...]) -> str:
    values = {name: _encoded_path_value(getattr(args, name)) for name in names}
    return template.format(**values)


def handle_wechat_log(args: argparse.Namespace) -> None:
    emit_response(
        _client(args).request(
            "POST",
            "/wechat/log",
            json_body={"level": args.level, "message": args.message},
        ),
        save=args.save,
    )


def handle_wechat_path_simple(args: argparse.Namespace) -> None:
    path = _format_api_path(args.api_path_template, args, args.path_param_names)
    emit_response(
        _client(args).request(args.http_method, path, params=parse_key_values(getattr(args, "param", []))),
        save=args.save,
    )


def handle_wechat_login_poll(args: argparse.Namespace) -> None:
    body = read_json_arg(args.json, default={})
    if not isinstance(body, dict):
        raise ValueError("--json must be a JSON object")
    if args.scan_id:
        body["scan_id"] = args.scan_id
    if not body.get("scan_id"):
        raise ValueError("--scan-id or --json with scan_id is required")
    emit_response(_client(args).request("POST", "/wechat/articles/login/poll", json_body=body), save=args.save)


def handle_wechat_named_body(args: argparse.Namespace) -> None:
    body = read_json_arg(getattr(args, "json", None), default={})
    if not isinstance(body, dict):
        raise ValueError("--json must be a JSON object")
    body[args.body_key] = getattr(args, args.body_attr)
    emit_response(_client(args).request(args.http_method, args.api_path, json_body=body), save=args.save)


def handle_wechat_path_named_body(args: argparse.Namespace) -> None:
    body = read_json_arg(getattr(args, "json", None), default={})
    if not isinstance(body, dict):
        raise ValueError("--json must be a JSON object")
    body[args.body_key] = getattr(args, args.body_attr)
    path = _format_api_path(args.api_path_template, args, args.path_param_names)
    emit_response(_client(args).request(args.http_method, path, json_body=body), save=args.save)


def handle_wechat_account_categories_set(args: argparse.Namespace) -> None:
    body = read_json_arg(args.json, default={})
    if not isinstance(body, dict):
        raise ValueError("--json must be a JSON object")
    if args.category_id:
        body["category_ids"] = args.category_id
    if "category_ids" not in body:
        raise ValueError("--category-id or --json with category_ids is required")
    path = _format_api_path("/wechat/articles/accounts/{mp_id}/categories", args, ("mp_id",))
    emit_response(_client(args).request("POST", path, json_body=body), save=args.save)


def handle_wechat_account_favorite(args: argparse.Namespace) -> None:
    path = _format_api_path("/wechat/articles/accounts/{mp_id}/favorite", args, ("mp_id",))
    emit_response(
        _client(args).request("POST", path, json_body={"is_favorite": bool(args.is_favorite)}),
        save=args.save,
    )


def handle_wechat_sync_by_category_preview(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"category_id": args.category_id, "mode": args.mode}
    if args.since_date:
        params["since_date"] = args.since_date
    if args.sample is not None:
        params["sample"] = args.sample
    emit_response(_client(args).request("GET", "/wechat/articles/sync_by_category/preview", params=params), save=args.save)


def handle_wechat_purge_invalid(args: argparse.Namespace) -> None:
    emit_response(
        _client(args).request(
            "POST",
            "/wechat/articles/sync_by_category/purge_invalid",
            params={"category_id": args.category_id},
        ),
        save=args.save,
    )


def handle_wechat_request(args: argparse.Namespace) -> None:
    handle_api_request(args, prefix="/api/wechat")


def handle_prefixed_request(args: argparse.Namespace) -> None:
    handle_api_request(args, prefix=args.prefix)


def handle_serve(args: argparse.Namespace) -> None:
    import uvicorn

    main_module = load_main_module(build_config(args))
    uvicorn.run(main_module.app, host=args.host, port=args.port, log_level=args.log_level)


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-root", type=Path, default=argparse.SUPPRESS, help="gh_quant_ui project root")
    parser.add_argument("--db-path", type=Path, default=argparse.SUPPRESS, help="local parquet data directory")
    parser.add_argument("--factor-path", type=Path, default=argparse.SUPPRESS, help="factor parquet data directory")
    parser.add_argument("--export-path", type=Path, default=argparse.SUPPRESS, help="Excel/report export directory")
    parser.add_argument("--jypy-path", type=Path, default=argparse.SUPPRESS, help="JyPy project root")
    parser.add_argument("--gh-backtest-path", type=Path, default=argparse.SUPPRESS, help="gh_backtest/src path")
    parser.add_argument(
        "--api-base",
        default=argparse.SUPPRESS,
        help="call a running API server instead of importing source",
    )


def add_save(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--save", default=None, help="also save JSON output or binary response to this path")


def add_kv(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-p", "--param", action="append", default=[], help="request/query parameter KEY=VALUE")


def add_request_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("method", help="HTTP method")
    parser.add_argument("path", help="API path")
    add_kv(parser)
    parser.add_argument("--json", default=None, help="JSON body, @file, or - for stdin")
    parser.add_argument("--header", action="append", default=[], help="request header KEY=VALUE")
    parser.add_argument("--file", default=None, help="file upload path")
    parser.add_argument("--file-field", default="file", help="multipart file field name")
    add_save(parser)


def add_data_commands(sub: argparse._SubParsersAction) -> None:
    data = sub.add_parser("data", help="data query/download/update commands")
    add_common_options(data)
    data_sub = data.add_subparsers(dest="data_command", required=True)

    modules = data_sub.add_parser("modules", help="list queryable data modules")
    add_save(modules)
    modules.set_defaults(func=handle_data_modules)

    query = data_sub.add_parser("query", help="query local parquet data")
    query.add_argument("module")
    query.add_argument("method_name")
    add_kv(query)
    query.add_argument("--limit", type=int, default=None)
    add_save(query)
    query.set_defaults(func=handle_data_query)

    for name, func in (("download", handle_data_download), ("update", handle_data_update)):
        cmd = data_sub.add_parser(name, help=f"{name} data from JYDB")
        cmd.add_argument("module")
        cmd.add_argument("method_name")
        cmd.add_argument("--token", default=None)
        cmd.add_argument("--server", default=None, choices=["primary", "secondary"])
        add_kv(cmd)
        add_save(cmd)
        cmd.set_defaults(func=func)

    quick = data_sub.add_parser("quick-update", help="update core tables used by the desktop home page")
    quick.add_argument("--token", default=None)
    quick.add_argument("--server", default=None, choices=["primary", "secondary"])
    quick.add_argument("--continue-on-error", action="store_true")
    add_kv(quick)
    add_save(quick)
    quick.set_defaults(func=handle_data_quick_update)

    progress = data_sub.add_parser("progress", help="show download progress")
    progress.add_argument("--factor", action="store_true")
    add_save(progress)
    progress.set_defaults(func=handle_data_progress)

    files = data_sub.add_parser("files", help="list local parquet files")
    add_save(files)
    files.set_defaults(func=handle_data_files)


def add_profile_commands(sub: argparse._SubParsersAction) -> None:
    profile = sub.add_parser("profile", help="local CLI profile for agent-friendly credentials")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)

    get = profile_sub.add_parser("get", help="show redacted local profile")
    add_save(get)
    get.set_defaults(func=handle_profile_get)

    setp = profile_sub.add_parser("set", help="save local token/server defaults")
    setp.add_argument("--api-token", default=None)
    setp.add_argument("--access-token", default=None)
    setp.add_argument("--server", default=None, choices=["primary", "secondary"])
    setp.add_argument("--username", default=None)
    add_save(setp)
    setp.set_defaults(func=handle_profile_set)

    clear = profile_sub.add_parser("clear", help="remove local profile")
    add_save(clear)
    clear.set_defaults(func=handle_profile_clear)


def add_config_commands(sub: argparse._SubParsersAction) -> None:
    config = sub.add_parser("config", help="path configuration")
    add_common_options(config)
    config_sub = config.add_subparsers(dest="config_command", required=True)

    get = config_sub.add_parser("get-paths")
    add_save(get)
    get.set_defaults(func=handle_config_get)

    setp = config_sub.add_parser("set-paths")
    setp.add_argument("--db-path", dest="db_path", default=None)
    setp.add_argument("--factor-path", dest="factor_path", default=None)
    setp.add_argument("--export-path", dest="export_path", default=None)
    setp.add_argument("--default-start-date", default=None)
    add_kv(setp)
    add_save(setp)
    setp.set_defaults(func=handle_config_set)


def add_auth_commands(sub: argparse._SubParsersAction) -> None:
    auth = sub.add_parser("auth", help="authentication and token helper commands")
    add_common_options(auth)
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)

    verify = auth_sub.add_parser("verify", help="verify a JYDB/API token")
    verify.add_argument("--token", default=None)
    verify.add_argument("--json", default=None, help="JSON body, @file, or -")
    add_save(verify)
    verify.set_defaults(func=handle_auth_verify)

    login = auth_sub.add_parser("login", help="login with username/password")
    login.add_argument("--username", default=None)
    login.add_argument("--password", default=None)
    login.add_argument("--json", default=None, help="JSON body, @file, or -")
    add_save(login)
    login.set_defaults(func=handle_auth_login)

    active_token = auth_sub.add_parser("active-token", help="fetch active full API token")
    active_token.add_argument("--access-token", default=None)
    add_save(active_token)
    active_token.set_defaults(func=handle_auth_active_token)


def add_ai_commands(sub: argparse._SubParsersAction) -> None:
    ai = sub.add_parser("ai", help="AI workbench and report reproduction commands")
    add_common_options(ai)
    ai_sub = ai.add_subparsers(dest="ai_command", required=True)

    request = ai_sub.add_parser("request", help="call any /api/ai route")
    add_request_args(request)
    request.set_defaults(func=handle_prefixed_request, prefix="/api/ai")

    for name, path in (
        ("status", "/ai/status"),
        ("projects", "/ai/report-reproduce/projects"),
        ("pdf-candidates", "/ai/report-reproduce/pdf-candidates"),
        ("tasks", "/ai/report-reproduce/tasks"),
    ):
        cmd = ai_sub.add_parser(name)
        add_kv(cmd)
        add_save(cmd)
        cmd.set_defaults(func=handle_ai_get, api_path=path)

    task = ai_sub.add_parser("task")
    task.add_argument("task_id")
    add_kv(task)
    add_save(task)
    task.set_defaults(func=handle_ai_task)

    start = ai_sub.add_parser("start")
    start.add_argument("--json", required=True, help="JSON body, @file, or -")
    add_save(start)
    start.set_defaults(func=handle_ai_start)

    cancel = ai_sub.add_parser("cancel")
    cancel.add_argument("task_id")
    add_kv(cancel)
    add_save(cancel)
    cancel.set_defaults(func=handle_ai_cancel)


def add_remote_commands(sub: argparse._SubParsersAction) -> None:
    remote = sub.add_parser("remote", help="remote account and API token commands")
    add_common_options(remote)
    remote_sub = remote.add_subparsers(dest="remote_command", required=True)

    request = remote_sub.add_parser("request", help="call any /api/remote route")
    add_request_args(request)
    request.set_defaults(func=handle_prefixed_request, prefix="/api/remote")

    me = remote_sub.add_parser("me", help="show current remote user")
    me.add_argument("--access-token", default=None)
    add_save(me)
    me.set_defaults(func=handle_remote_me)

    tokens = remote_sub.add_parser("tokens", help="list remote API tokens")
    tokens.add_argument("--access-token", default=None)
    add_save(tokens)
    tokens.set_defaults(func=handle_remote_tokens)

    generate = remote_sub.add_parser("token-generate", help="generate a remote API token")
    generate.add_argument("--access-token", default=None)
    generate.add_argument("--name", default=None)
    generate.add_argument("--json", default=None, help="JSON body, @file, or -")
    add_save(generate)
    generate.set_defaults(func=handle_remote_token_generate)

    revoke = remote_sub.add_parser("token-revoke", help="revoke a remote API token")
    revoke.add_argument("token_id", type=int)
    revoke.add_argument("--access-token", default=None)
    add_save(revoke)
    revoke.set_defaults(func=handle_remote_token_revoke)


def add_factor_commands(sub: argparse._SubParsersAction) -> None:
    factor = sub.add_parser("factor", help="factor research and factor db commands")
    add_common_options(factor)
    fs = factor.add_subparsers(dest="factor_command", required=True)

    simple = {
        "sample": ("GET", "/factor/sample"),
        "catalog": ("GET", "/factor/db/catalog"),
        "databases": ("GET", "/factor/db/databases"),
        "tables": ("GET", "/factor/db/tables"),
        "progress": ("GET", "/factor/db/progress"),
        "rank-meta": ("GET", "/factor/rank/meta"),
        "rank-list": ("GET", "/factor/rank/list"),
        "barra-returns": ("GET", "/factor/barra/returns"),
    }
    for name, (method, path) in simple.items():
        p = fs.add_parser(name)
        add_kv(p)
        add_save(p)
        p.set_defaults(func=handle_factor_simple, http_method=method, api_path=path)

    values = fs.add_parser("values")
    values.add_argument("factor_id")
    add_kv(values)
    add_save(values)
    values.set_defaults(
        func=lambda a: emit_response(
            _client(a).request(
                "GET", "/factor/db/values", params={"factor_id": a.factor_id, **parse_key_values(a.param)}
            ),
            save=a.save,
        )
    )

    query = fs.add_parser("query")
    query.add_argument("table")
    add_kv(query)
    query.add_argument("--limit", type=int, default=None)
    add_save(query)
    query.set_defaults(
        func=lambda a: emit_response(
            _client(a).request(
                "GET",
                f"/factor/db/query/{a.table}",
                params={**parse_key_values(a.param), **({"limit": a.limit} if a.limit is not None else {})},
            ),
            save=a.save,
        )
    )

    for name, path in (("download", "/factor/db/download/{table}"), ("update", "/factor/db/update/{table}")):
        p = fs.add_parser(name)
        p.add_argument("table")
        p.add_argument("--token", required=True)
        add_save(p)
        p.set_defaults(
            func=lambda a, template=path: emit_response(
                _client(a).request("POST", template.format(table=a.table), params={"token": a.token}),
                save=a.save,
            )
        )

    detail = fs.add_parser("rank-detail")
    detail.add_argument("factor_id")
    detail.add_argument("--ind-code", required=True)
    add_save(detail)
    detail.set_defaults(
        func=lambda a: emit_response(
            _client(a).request(
                "GET", f"/factor/rank/detail/{a.factor_id}", params={"ind_code": a.ind_code}
            ),
            save=a.save,
        )
    )

    for name, path in (("analyze", "/factor/analyze"), ("report", "/factor/report")):
        p = fs.add_parser(name)
        p.add_argument("--json", required=True, help="JSON config, @file, or -")
        add_save(p)
        p.set_defaults(func=handle_factor_json, http_method="POST", api_path=path)

    upload = fs.add_parser("upload")
    upload.add_argument("file")
    add_save(upload)
    upload.set_defaults(func=handle_factor_upload)


def add_backtest_commands(sub: argparse._SubParsersAction) -> None:
    backtest = sub.add_parser("backtest", help="portfolio backtest commands")
    add_common_options(backtest)
    bs = backtest.add_subparsers(dest="backtest_command", required=True)

    simple = {
        "check-data": ("GET", "/backtest/check-data"),
        "index-codes": ("GET", "/backtest/index-codes"),
        "sample-portfolio": ("GET", "/backtest/sample-portfolio"),
    }
    for name, (method, path) in simple.items():
        p = bs.add_parser(name)
        add_kv(p)
        add_save(p)
        p.set_defaults(func=handle_backtest_simple, http_method=method, api_path=path)

    for name, path in (
        ("run", "/backtest/run"),
        ("upload-json", "/backtest/upload-portfolio-json"),
        ("monitoring", "/backtest/monitoring"),
        ("brinson", "/backtest/brinson"),
        ("risk", "/backtest/risk"),
    ):
        p = bs.add_parser(name)
        p.add_argument("--json", required=True, help="JSON body, @file, or -")
        add_save(p)
        p.set_defaults(func=handle_backtest_json, http_method="POST", api_path=path)

    upload = bs.add_parser("upload")
    upload.add_argument("file")
    add_save(upload)
    upload.set_defaults(func=handle_backtest_upload)

    uploaded = bs.add_parser("uploaded-portfolio")
    uploaded.add_argument("upload_id")
    add_save(uploaded)
    uploaded.set_defaults(func=handle_backtest_uploaded_portfolio)

    monitoring_holdings = bs.add_parser("monitoring-holdings")
    monitoring_holdings.add_argument("--upload-id", required=True)
    monitoring_holdings.add_argument("--date", required=True)
    monitoring_holdings.add_argument("--benchmark-index", default="000300")
    monitoring_holdings.add_argument("--aum", type=float, default=0.0)
    add_save(monitoring_holdings)
    monitoring_holdings.set_defaults(func=handle_backtest_monitoring_holdings)

    result = bs.add_parser("result")
    result.add_argument("task_id")
    add_save(result)
    result.set_defaults(
        func=lambda a: emit_response(_client(a).request("GET", f"/backtest/results/{a.task_id}"), save=a.save)
    )

    holdings = bs.add_parser("holdings")
    holdings.add_argument("task_id")
    add_kv(holdings)
    add_save(holdings)
    holdings.set_defaults(
        func=lambda a: emit_response(
            _client(a).request("GET", f"/backtest/results/{a.task_id}/holdings", params=parse_key_values(a.param)),
            save=a.save,
        )
    )

    export = bs.add_parser("export")
    export.add_argument("task_id")
    add_save(export)
    export.set_defaults(
        func=lambda a: emit_response(
            _client(a).request("GET", f"/backtest/results/{a.task_id}/export"), save=a.save
        )
    )


def add_wechat_commands(sub: argparse._SubParsersAction) -> None:
    wechat = sub.add_parser("wechat", help="wechat local tools and article commands")
    add_common_options(wechat)
    ws = wechat.add_subparsers(dest="wechat_command", required=True)

    request = ws.add_parser("request", help="call any /api/wechat route")
    add_request_args(request)
    request.set_defaults(func=handle_wechat_request)

    log = ws.add_parser("log")
    log.add_argument("--level", default="info")
    log.add_argument("--message", required=True)
    add_save(log)
    log.set_defaults(func=handle_wechat_log)

    simple = {
        "config-get": ("GET", "/wechat/config"),
        "macos-resign": ("POST", "/wechat/macos/resign-wechat"),
        "password-status": ("GET", "/wechat/password/status"),
        "password-auto": ("POST", "/wechat/password/auto"),
        "debug-inspect": ("GET", "/wechat/debug/inspect"),
        "sessions": ("GET", "/wechat/sessions"),
        "contacts-export": ("GET", "/wechat/contacts/export"),
        "search-stats": ("GET", "/wechat/search/stats"),
        "stock-stats": ("GET", "/wechat/stock/stats"),
        "stock-preload": ("POST", "/wechat/stock/preload"),
        "image-extract-keys": ("POST", "/wechat/image/extract-keys"),
        "image-keys": ("GET", "/wechat/image/get-keys"),
        "image-list": ("GET", "/wechat/image/list"),
        "image-months": ("GET", "/wechat/image/months"),
        "articles-login-qrcode": ("GET", "/wechat/articles/login/qrcode"),
        "articles-login-logout": ("POST", "/wechat/articles/login/logout"),
        "articles-login-status": ("GET", "/wechat/articles/login/status"),
        "articles-status": ("GET", "/wechat/articles/sync/status"),
        "articles-categories": ("GET", "/wechat/articles/categories"),
        "articles-settings": ("GET", "/wechat/articles/settings"),
        "articles-analyses": ("GET", "/wechat/articles/analyses"),
        "articles-open-html-dir": ("POST", "/wechat/articles/open_html_dir"),
        "articles-account-dedupe": ("POST", "/wechat/articles/accounts/dedupe"),
        "articles-sync-by-category-status": ("GET", "/wechat/articles/sync_by_category/status"),
    }
    for name, (method, path) in simple.items():
        p = ws.add_parser(name)
        add_kv(p)
        add_save(p)
        p.set_defaults(func=handle_wechat_simple, http_method=method, api_path=path)

    json_cmds = {
        "config-set": ("POST", "/wechat/config"),
        "search": ("POST", "/wechat/messages/search"),
        "messages-export": ("POST", "/wechat/messages/export"),
        "summarize": ("POST", "/wechat/llm/summarize"),
        "stock-picks": ("POST", "/wechat/stock/picks"),
        "stock-screener": ("POST", "/wechat/stock/screener"),
        "stock-screener-export": ("POST", "/wechat/stock/screener/export"),
        "kline-review": ("POST", "/wechat/stock/review"),
        "kline-review-export": ("POST", "/wechat/stock/review/export"),
        "image-convert": ("POST", "/wechat/image/convert"),
        "image-batch-convert": ("POST", "/wechat/image/batch-convert"),
        "llm-chat": ("POST", "/wechat/llm/chat"),
        "llm-test": ("POST", "/wechat/llm/test"),
        "llm-batch-stream": ("POST", "/wechat/llm/batch/stream"),
        "llm-export": ("POST", "/wechat/llm/export"),
        "pdf-report": ("POST", "/wechat/report/pdf"),
        "articles-settings-set": ("POST", "/wechat/articles/settings"),
        "articles-sync": ("POST", "/wechat/articles/sync"),
        "articles-sync-by-category": ("POST", "/wechat/articles/sync_by_category"),
        "articles-sync-local": ("POST", "/wechat/articles/sync_local"),
        "articles-fetch-batch": ("POST", "/wechat/articles/articles/fetch_batch"),
        "articles-analyze": ("POST", "/wechat/articles/llm_analyze"),
        "articles-export-analysis": ("POST", "/wechat/articles/analyses/export"),
        "articles-fixture-seed": ("POST", "/wechat/articles/_fixture/seed"),
    }
    for name, (method, path) in json_cmds.items():
        p = ws.add_parser(name)
        p.add_argument("--json", required=True, help="JSON body, @file, or -")
        add_save(p)
        p.set_defaults(func=handle_wechat_json, http_method=method, api_path=path)

    list_articles = ws.add_parser("articles-list")
    add_kv(list_articles)
    add_save(list_articles)
    list_articles.set_defaults(func=handle_wechat_simple, http_method="GET", api_path="/wechat/articles/articles")

    list_accounts = ws.add_parser("articles-accounts")
    add_kv(list_accounts)
    add_save(list_accounts)
    list_accounts.set_defaults(func=handle_wechat_simple, http_method="GET", api_path="/wechat/articles/accounts")

    login_poll = ws.add_parser("articles-login-poll")
    login_poll.add_argument("--scan-id", default="")
    login_poll.add_argument("--json", default=None, help="JSON body, @file, or -")
    add_save(login_poll)
    login_poll.set_defaults(func=handle_wechat_login_poll)

    for name, method, template, dest in (
        ("articles-analysis-get", "GET", "/wechat/articles/analyses/{analysis_id}", "analysis_id"),
        ("articles-analysis-delete", "DELETE", "/wechat/articles/analyses/{analysis_id}", "analysis_id"),
        ("articles-category-delete", "DELETE", "/wechat/articles/categories/{category_id}", "category_id"),
        ("articles-account-categories", "GET", "/wechat/articles/accounts/{mp_id}/categories", "mp_id"),
        ("articles-account-delete", "DELETE", "/wechat/articles/accounts/{mp_id}", "mp_id"),
        ("articles-fetch", "POST", "/wechat/articles/articles/{article_id}/fetch", "article_id"),
        ("articles-html", "GET", "/wechat/articles/articles/{article_id}/html", "article_id"),
    ):
        p = ws.add_parser(name)
        p.add_argument(dest)
        add_save(p)
        p.set_defaults(
            func=handle_wechat_path_simple,
            http_method=method,
            api_path_template=template,
            path_param_names=(dest,),
        )

    category_create = ws.add_parser("articles-category-create")
    category_create.add_argument("--name", required=True)
    category_create.add_argument("--json", default=None, help="JSON body, @file, or -")
    add_save(category_create)
    category_create.set_defaults(
        func=handle_wechat_named_body,
        http_method="POST",
        api_path="/wechat/articles/categories",
        body_key="name",
        body_attr="name",
    )

    category_rename = ws.add_parser("articles-category-rename")
    category_rename.add_argument("category_id")
    category_rename.add_argument("--name", required=True)
    category_rename.add_argument("--json", default=None, help="JSON body, @file, or -")
    add_save(category_rename)
    category_rename.set_defaults(
        func=handle_wechat_path_named_body,
        http_method="PUT",
        api_path_template="/wechat/articles/categories/{category_id}",
        path_param_names=("category_id",),
        body_key="name",
        body_attr="name",
    )

    set_categories = ws.add_parser("articles-account-set-categories")
    set_categories.add_argument("mp_id")
    set_categories.add_argument("--category-id", action="append", type=int, default=[])
    set_categories.add_argument("--json", default=None, help="JSON body, @file, or -")
    add_save(set_categories)
    set_categories.set_defaults(func=handle_wechat_account_categories_set)

    favorite = ws.add_parser("articles-account-favorite")
    favorite.add_argument("mp_id")
    favorite_group = favorite.add_mutually_exclusive_group(required=True)
    favorite_group.add_argument("--favorite", dest="is_favorite", action="store_true")
    favorite_group.add_argument("--unfavorite", dest="is_favorite", action="store_false")
    add_save(favorite)
    favorite.set_defaults(func=handle_wechat_account_favorite)

    add_by_url = ws.add_parser("articles-account-add-by-url")
    add_by_url.add_argument("article_url")
    add_by_url.add_argument("--json", default=None, help="JSON body, @file, or -")
    add_save(add_by_url)
    add_by_url.set_defaults(
        func=handle_wechat_named_body,
        http_method="POST",
        api_path="/wechat/articles/accounts/add_by_url",
        body_key="article_url",
        body_attr="article_url",
    )

    purge_invalid = ws.add_parser("articles-purge-invalid")
    purge_invalid.add_argument("--category-id", type=int, required=True)
    add_save(purge_invalid)
    purge_invalid.set_defaults(func=handle_wechat_purge_invalid)

    preview = ws.add_parser("articles-sync-by-category-preview")
    preview.add_argument("--category-id", type=int, required=True)
    preview.add_argument("--mode", required=True, choices=["full", "incremental", "since"])
    preview.add_argument("--since-date", default="")
    preview.add_argument("--sample", type=int, default=None)
    add_save(preview)
    preview.set_defaults(func=handle_wechat_sync_by_category_preview)


def add_prefixed_request_group(sub: argparse._SubParsersAction, name: str, prefix: str, help_text: str) -> None:
    group = sub.add_parser(name, help=help_text)
    add_common_options(group)
    gs = group.add_subparsers(dest=f"{name}_command", required=True)
    request = gs.add_parser("request")
    add_request_args(request)
    request.set_defaults(func=handle_prefixed_request, prefix=prefix)


def add_feedback_commands(sub: argparse._SubParsersAction) -> None:
    feedback = sub.add_parser("feedback", help="submit feedback through gh_quant_ui")
    add_common_options(feedback)
    feedback_sub = feedback.add_subparsers(dest="feedback_command", required=True)

    submit = feedback_sub.add_parser("submit", help="submit user feedback")
    submit.add_argument("--json", default=None, help="JSON body, @file, or -")
    submit.add_argument("--content", default=None)
    submit.add_argument("--category", default=None)
    submit.add_argument("--contact", default=None)
    add_save(submit)
    submit.set_defaults(func=handle_feedback_submit)

    request = feedback_sub.add_parser("request", help="generic feedback API request")
    add_request_args(request)
    request.set_defaults(func=handle_prefixed_request, prefix="/api/feedback")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gh-ui", description="CLI for gh_quant_ui")
    add_common_options(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    health = sub.add_parser("health", help="check API health")
    add_common_options(health)
    add_save(health)
    health.set_defaults(func=handle_health)

    doctor = sub.add_parser("doctor", help="check source import and route coverage")
    add_common_options(doctor)
    add_save(doctor)
    doctor.set_defaults(func=handle_doctor)

    routes = sub.add_parser("routes", help="list FastAPI routes from source project")
    add_common_options(routes)
    routes.add_argument("--prefix", default="")
    routes.add_argument("--method", default="")
    add_save(routes)
    routes.set_defaults(func=handle_routes)

    deps = sub.add_parser("deps", help="check source-mode Python dependencies without importing source")
    add_common_options(deps)
    deps.add_argument("--requirements", default="", help="requirements.txt path; defaults to source_root/api/requirements.txt")
    deps.add_argument("--platform", default="", help="override sys.platform for cross-platform preflight, e.g. darwin or win32")
    deps.add_argument("--strict", action="store_true", help="exit 1 when applicable dependencies are missing")
    add_save(deps)
    deps.set_defaults(func=handle_deps)

    coverage = sub.add_parser("coverage", help="audit route-to-CLI callable coverage")
    add_common_options(coverage)
    coverage.add_argument("--summary", action="store_true", help="omit per-operation command list")
    add_save(coverage)
    coverage.set_defaults(func=handle_coverage)

    manifest = sub.add_parser("manifest", help="emit agent-friendly callable command manifest")
    add_common_options(manifest)
    manifest.add_argument("--category", default="", help="filter by category, e.g. data, wechat, factor_data")
    add_save(manifest)
    manifest.set_defaults(func=handle_manifest)

    verify = sub.add_parser("verify", help="run goal-oriented agent verification checks")
    add_common_options(verify)
    verify.add_argument("--with-data-query", action="store_true", help="also query one local stock_code row")
    verify.add_argument("--platform", default="", help="override sys.platform for dependency preflight")
    verify.add_argument("--windows-deps-preflight", action="store_true", help="also parse source dependencies as win32")
    verify.add_argument("--strict", action="store_true", help="exit 1 when current verification checks fail")
    verify.add_argument("--strict-goal", action="store_true", help="exit 1 unless this run proves full goal completion")
    add_save(verify)
    verify.set_defaults(func=handle_verify)

    verify_plan = sub.add_parser("verify-plan", help="emit machine-readable goal verification plan")
    verify_plan.add_argument("--mac-report", default="verify-macos.json")
    verify_plan.add_argument("--windows-report", default="verify-windows.json")
    verify_plan.add_argument("--artifact-dir", default="verify-artifacts")
    add_save(verify_plan)
    verify_plan.set_defaults(func=handle_verify_plan)

    ci_status = sub.add_parser("ci-status", help="inspect GitHub Actions verification evidence")
    ci_status.add_argument("--repo", default=os.environ.get("GH_REPOSITORY", ""), help="GitHub repo as OWNER/REPO")
    ci_status.add_argument("--workflow", default="ci.yml", help="workflow file, name, or id")
    ci_status.add_argument("--ref", default="main", help="branch or ref for workflow_dispatch")
    ci_status.add_argument("--artifact-name", default="gh-ui-verify-Windows-py3.12")
    ci_status.add_argument("--artifact-dir", default="verify-artifacts")
    ci_status.add_argument("--mac-report", default="verify-macos.json")
    ci_status.add_argument("--strict", action="store_true", help="exit 1 when CI evidence is not ready")
    add_save(ci_status)
    ci_status.set_defaults(func=handle_ci_status)

    ci_log_report = sub.add_parser("ci-log-report", help="extract marked verify JSON from GitHub Actions logs")
    ci_log_report.add_argument("run_id", help="GitHub Actions run id")
    ci_log_report.add_argument("--repo", default=os.environ.get("GH_REPOSITORY", ""), help="GitHub repo as OWNER/REPO")
    ci_log_report.add_argument("--platform", default="", help="required current_platform value, e.g. win32")
    ci_log_report.add_argument("--job-contains", default="", help="only select reports whose job name contains this text")
    ci_log_report.add_argument("--strict", action="store_true", help="exit 1 when no matching report is found")
    add_save(ci_log_report)
    ci_log_report.set_defaults(func=handle_ci_log_report)

    verify_bundle = sub.add_parser("verify-bundle", help="write source report and agent handoff files")
    add_common_options(verify_bundle)
    verify_bundle.add_argument("output_dir", help="directory to write verification bundle files")
    verify_bundle.add_argument("--source-report", default="verify-macos.json")
    verify_bundle.add_argument("--windows-report", default="verify-windows.json")
    verify_bundle.add_argument("--artifact-dir", default="verify-artifacts")
    verify_bundle.add_argument("--with-data-query", action="store_true", help="also query one local stock_code row")
    verify_bundle.add_argument("--platform", default="", help="override sys.platform for dependency preflight")
    verify_bundle.add_argument("--strict", action="store_true", help="exit 1 when current source report fails")
    add_save(verify_bundle)
    verify_bundle.set_defaults(func=handle_verify_bundle, strict_goal=False, windows_deps_preflight=True)

    runtime_verify = sub.add_parser(
        "runtime-verify",
        help="generate an installed-runtime verify report against a temporary API-base sidecar",
    )
    runtime_verify.add_argument("output", help="verify report JSON path to write")
    runtime_verify.set_defaults(func=handle_runtime_verify)

    verify_merge = sub.add_parser("verify-merge", help="merge saved verify JSON reports")
    verify_merge.add_argument("reports", nargs="+", help="verify report JSON, report directory, @file, or -")
    verify_merge.add_argument("--strict", action="store_true", help="exit 1 when any input report failed")
    verify_merge.add_argument("--strict-goal", action="store_true", help="exit 1 unless merged evidence proves completion")
    add_save(verify_merge)
    verify_merge.set_defaults(func=handle_verify_merge)

    smoke = sub.add_parser("smoke", help="run agent-friendly cross-platform smoke checks")
    add_common_options(smoke)
    smoke.add_argument("--with-data-query", action="store_true", help="also query one local stock_code row")
    add_save(smoke)
    smoke.set_defaults(func=handle_smoke)

    invoke = sub.add_parser("invoke", help="call a manifest id directly")
    add_common_options(invoke)
    invoke.add_argument("target_id", help="manifest id, e.g. route:GET:/api/health")
    add_kv(invoke)
    invoke.add_argument("--json", default=None, help="JSON body, @file, or - for stdin")
    invoke.add_argument("--header", action="append", default=[], help="request header KEY=VALUE")
    invoke.add_argument("--file", default=None, help="file upload path")
    invoke.add_argument("--file-field", default="file", help="multipart file field name")
    invoke.add_argument("--token", default=None, help="token for data/factor_data download or update ids")
    invoke.add_argument("--server", default=None, choices=["primary", "secondary"])
    add_save(invoke)
    invoke.set_defaults(func=handle_invoke)

    api = sub.add_parser("api", help="generic API request")
    add_common_options(api)
    api_sub = api.add_subparsers(dest="api_command", required=True)
    request = api_sub.add_parser("request")
    add_request_args(request)
    request.set_defaults(func=handle_api_request)

    add_profile_commands(sub)
    add_data_commands(sub)
    add_config_commands(sub)
    add_auth_commands(sub)
    add_factor_commands(sub)
    add_backtest_commands(sub)
    add_wechat_commands(sub)
    add_ai_commands(sub)
    add_remote_commands(sub)
    add_feedback_commands(sub)

    logs = sub.add_parser("logs", help="list API logs")
    add_common_options(logs)
    logs.add_argument("--category", default="")
    logs.add_argument("--limit", type=int, default=200)
    add_save(logs)
    logs.set_defaults(func=handle_logs)

    export = sub.add_parser("export", help="export helpers")
    add_common_options(export)
    export_sub = export.add_subparsers(dest="export_command", required=True)
    excel = export_sub.add_parser("excel")
    excel.add_argument("--input", required=True, help="JSON data array/object, @file, or -")
    excel.add_argument("--columns", default="")
    excel.add_argument("--filename", default="export")
    excel.add_argument("--sheet-name", default="data")
    add_save(excel)
    excel.set_defaults(func=handle_export_excel)

    serve = sub.add_parser("serve", help="run gh_quant_ui FastAPI app")
    add_common_options(serve)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--log-level", default="info")
    serve.set_defaults(func=handle_serve)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ApiError as exc:
        write_json({"error": exc.detail, "status_code": exc.status_code})
        raise SystemExit(1) from exc
    except Exception as exc:
        write_json({"error": str(exc), "type": type(exc).__name__})
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
