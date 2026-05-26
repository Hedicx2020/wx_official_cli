from __future__ import annotations

from typing import Any

from .verification_plan import build_verification_plan


EVIDENCE_KEYS = (
    "route_operations_callable",
    "source_dynamic_capabilities_verified",
    "frontend_api_references_verified",
    "preferred_commands_parseable",
    "all_features_cli_callable",
    "agent_profile_verified",
    "mac_runtime_verified",
    "windows_runtime_verified",
    "windows_dependency_preflight",
)

SOURCE_CLI_COVERAGE_KEYS = (
    "route_operations_callable",
    "source_dynamic_capabilities_verified",
    "frontend_api_references_verified",
    "preferred_commands_parseable",
)


def build_goal_verification_report(
    *,
    checks: list[dict[str, Any]],
    platform_name: str,
    current_platform: str,
    mode: str,
) -> dict[str, Any]:
    failed_checks = [str(check.get("name", "")) for check in checks if not check.get("ok")]
    coverage = _check_by_name(checks, "coverage")
    smoke = _check_by_name(checks, "smoke")
    windows_preflight = _check_by_name(checks, "windows_dependency_preflight")

    route_operations_callable = bool(coverage.get("ok") and coverage.get("all_callables"))
    source_dynamic_capabilities_verified = mode == "source" and _has_source_dynamic_totals(coverage)
    frontend_api_references_verified = mode == "source" and _frontend_api_references_verified(coverage)
    preferred_commands_parseable = _preferred_commands_parseable(coverage)
    agent_profile_verified = _agent_profile_verified(smoke)
    all_features_cli_callable = (
        route_operations_callable
        and source_dynamic_capabilities_verified
        and frontend_api_references_verified
        and preferred_commands_parseable
        and agent_profile_verified
    )
    runtime_verified = bool(smoke.get("ok"))
    mac_runtime_verified = runtime_verified and current_platform == "darwin"
    windows_runtime_verified = runtime_verified and current_platform == "win32"
    windows_dependency_preflight = bool(windows_preflight.get("ok") and not windows_preflight.get("skipped"))

    limitations = []
    if not windows_runtime_verified:
        limitations.append("Windows runtime has not been verified in this run.")
    if not mac_runtime_verified:
        limitations.append("macOS runtime has not been verified in this run.")
    if mode == "api_base":
        limitations.append("HTTP mode cannot verify source dynamic capability inventory.")
    if not agent_profile_verified:
        limitations.append("Agent profile smoke has not been verified in this run.")

    completion_ready = (
        not failed_checks
        and all_features_cli_callable
        and mac_runtime_verified
        and windows_runtime_verified
    )

    return {
        "ok": not failed_checks,
        "completion_ready": completion_ready,
        "mode": mode,
        "platform": platform_name,
        "current_platform": current_platform,
        "failed_checks": failed_checks,
        "goal_evidence": {
            "route_operations_callable": route_operations_callable,
            "source_dynamic_capabilities_verified": source_dynamic_capabilities_verified,
            "frontend_api_references_verified": frontend_api_references_verified,
            "preferred_commands_parseable": preferred_commands_parseable,
            "all_features_cli_callable": all_features_cli_callable,
            "agent_profile_verified": agent_profile_verified,
            "mac_runtime_verified": mac_runtime_verified,
            "windows_runtime_verified": windows_runtime_verified,
            "windows_dependency_preflight": windows_dependency_preflight,
        },
        "limitations": limitations,
        "checks": checks,
    }


def merge_goal_verification_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    evidence_sources = {
        key: _report_evidence_sources(reports, key)
        for key in EVIDENCE_KEYS
    }
    evidence = {
        key: bool(sources)
        for key, sources in evidence_sources.items()
    }
    failed_reports = [
        {
            "index": index,
            "platform": report.get("platform", ""),
            "current_platform": report.get("current_platform", ""),
            "failed_checks": report.get("failed_checks", []),
        }
        for index, report in enumerate(reports)
        if not report.get("ok")
    ]
    completion_requirements = _completion_requirements(evidence_sources, failed_reports)
    completion_ready = all(requirement["ok"] for requirement in completion_requirements.values())
    limitations = _merged_limitations(evidence, completion_requirements)
    next_actions = _next_actions(completion_requirements)
    return {
        "ok": not failed_reports,
        "completion_ready": completion_ready,
        "mode": "merged",
        "input_count": len(reports),
        "failed_reports": failed_reports,
        "goal_evidence": evidence,
        "evidence_sources": evidence_sources,
        "completion_requirements": completion_requirements,
        "next_actions": next_actions,
        "limitations": limitations,
        "reports": reports,
    }


def _completion_requirements(
    evidence_sources: dict[str, list[dict[str, Any]]],
    failed_reports: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    source_cli_coverage_sources = _source_cli_coverage_evidence_sources(evidence_sources)
    return {
        "no_failed_reports": {
            "ok": not failed_reports,
            "failed_report_indices": [int(report.get("index", -1)) for report in failed_reports],
        },
        "source_cli_coverage": {
            "ok": all(bool(source_cli_coverage_sources[key]) for key in SOURCE_CLI_COVERAGE_KEYS),
            "required_evidence": list(SOURCE_CLI_COVERAGE_KEYS),
            "evidence_sources": source_cli_coverage_sources,
        },
        "agent_profile": {
            "ok": bool(evidence_sources["agent_profile_verified"]),
            "evidence_sources": evidence_sources["agent_profile_verified"],
        },
        "mac_runtime": {
            "ok": bool(evidence_sources["mac_runtime_verified"]),
            "evidence_sources": evidence_sources["mac_runtime_verified"],
        },
        "windows_runtime": {
            "ok": bool(evidence_sources["windows_runtime_verified"]),
            "evidence_sources": evidence_sources["windows_runtime_verified"],
        },
    }


def _source_cli_coverage_evidence_sources(
    evidence_sources: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        key: [
            source
            for source in evidence_sources[key]
            if str(source.get("mode", "")) == "source"
        ]
        for key in SOURCE_CLI_COVERAGE_KEYS
    }


def _next_actions(completion_requirements: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    plan_commands = build_verification_plan()["commands"]
    command_names_by_requirement = {
        "no_failed_reports": ["merge_reports", "merge_artifacts"],
        "source_cli_coverage": ["macos_source_report"],
        "agent_profile": ["macos_source_report", "windows_runtime_report"],
        "mac_runtime": ["macos_source_report"],
        "windows_runtime": ["windows_runtime_report", "windows_http_sidecar_report", "download_windows_ci_artifact"],
    }
    return {
        requirement_name: [
            plan_commands[command_name]
            for command_name in command_names
            if command_name in plan_commands
        ]
        for requirement_name, command_names in command_names_by_requirement.items()
        if requirement_name in completion_requirements
        and not completion_requirements[requirement_name].get("ok")
    }


def _report_evidence_sources(reports: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "platform": str(report.get("platform", "")),
            "current_platform": str(report.get("current_platform", "")),
            "mode": str(report.get("mode", "")),
        }
        for index, report in enumerate(reports)
        if _valid_report_evidence(report, key)
    ]


def _valid_report_evidence(report: dict[str, Any], key: str) -> bool:
    if not report.get("ok"):
        return False
    evidence = report.get("goal_evidence") or {}
    if not isinstance(evidence, dict) or not evidence.get(key):
        return False
    mode = str(report.get("mode", ""))
    current_platform = str(report.get("current_platform", ""))
    if key == "mac_runtime_verified":
        return current_platform == "darwin"
    if key == "windows_runtime_verified":
        return current_platform == "win32"
    if key in {
        "source_dynamic_capabilities_verified",
        "frontend_api_references_verified",
        "all_features_cli_callable",
        "windows_dependency_preflight",
    }:
        return mode == "source"
    return True


def _merged_limitations(
    evidence: dict[str, bool],
    completion_requirements: dict[str, dict[str, Any]],
) -> list[str]:
    limitations = []
    if not completion_requirements["source_cli_coverage"]["ok"]:
        limitations.append("Full source CLI feature coverage has not been verified.")
    if not evidence["agent_profile_verified"]:
        limitations.append("Agent profile smoke has not been verified.")
    if not evidence["mac_runtime_verified"]:
        limitations.append("macOS runtime has not been verified.")
    if not evidence["windows_runtime_verified"]:
        limitations.append("Windows runtime has not been verified.")
    return limitations


def _check_by_name(checks: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for check in checks:
        if check.get("name") == name:
            return check
    return {}


def _has_source_dynamic_totals(coverage: dict[str, Any]) -> bool:
    totals = coverage.get("totals", {})
    if not isinstance(totals, dict):
        return False
    return any(
        int(totals.get(name, 0) or 0) > 0
        for name in (
            "data_query_methods",
            "data_download_methods",
            "data_update_methods",
            "factor_data_tables",
        )
    )


def _frontend_api_references_verified(coverage: dict[str, Any]) -> bool:
    frontend = coverage.get("frontend_api_references", {})
    if not isinstance(frontend, dict):
        return False
    return bool(
        int(frontend.get("total_references", 0) or 0) > 0
        and not frontend.get("missing_references")
    )


def _preferred_commands_parseable(coverage: dict[str, Any]) -> bool:
    preferred = coverage.get("preferred_command_parse", {})
    return bool(isinstance(preferred, dict) and preferred.get("all_parseable"))


def _agent_profile_verified(smoke: dict[str, Any]) -> bool:
    report = smoke.get("report", {})
    if not isinstance(report, dict):
        return False
    checks = report.get("checks", [])
    if not isinstance(checks, list):
        return False
    return any(
        isinstance(check, dict) and check.get("name") == "agent_profile" and check.get("ok")
        for check in checks
    )
