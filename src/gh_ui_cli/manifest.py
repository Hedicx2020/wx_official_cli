from __future__ import annotations

import shlex
from typing import Any


TOKEN_PLACEHOLDER = "<GH_API_TOKEN>"
ACCESS_TOKEN_PLACEHOLDER = "<GH_ACCESS_TOKEN>"
ENV_PLACEHOLDERS = {
    "$GH_API_TOKEN": TOKEN_PLACEHOLDER,
    "%GH_API_TOKEN%": TOKEN_PLACEHOLDER,
    "${GH_API_TOKEN}": TOKEN_PLACEHOLDER,
    "$GH_ACCESS_TOKEN": ACCESS_TOKEN_PLACEHOLDER,
    "%GH_ACCESS_TOKEN%": ACCESS_TOKEN_PLACEHOLDER,
    "${GH_ACCESS_TOKEN}": ACCESS_TOKEN_PLACEHOLDER,
}
PLACEHOLDER_TO_ENV = {
    TOKEN_PLACEHOLDER: "GH_API_TOKEN",
    ACCESS_TOKEN_PLACEHOLDER: "GH_ACCESS_TOKEN",
}
CLI_COMMANDS = (
    {
        "id": "cli:profile:get",
        "name": "profile_get",
        "description": "Show the redacted local CLI profile.",
        "command": "gh-ui profile get",
    },
    {
        "id": "cli:profile:set",
        "name": "profile_set",
        "description": "Persist token and server defaults for non-interactive agent calls.",
        "command": "gh-ui profile set --api-token $GH_API_TOKEN --access-token $GH_ACCESS_TOKEN --server primary",
    },
    {
        "id": "cli:profile:clear",
        "name": "profile_clear",
        "description": "Remove the local CLI profile.",
        "command": "gh-ui profile clear",
    },
    {
        "id": "cli:doctor",
        "name": "doctor",
        "description": "Inspect source or API-base runtime configuration.",
        "command": "gh-ui doctor",
    },
    {
        "id": "cli:deps",
        "name": "deps",
        "description": "Check source-mode Python dependencies without importing gh_quant_ui.",
        "command": "gh-ui deps",
    },
    {
        "id": "cli:routes",
        "name": "routes",
        "description": "List callable FastAPI route operations.",
        "command": "gh-ui routes",
    },
    {
        "id": "cli:coverage:summary",
        "name": "coverage_summary",
        "description": "Summarize CLI coverage for routes, data capabilities, and parser-ready commands.",
        "command": "gh-ui coverage --summary",
    },
    {
        "id": "cli:manifest",
        "name": "manifest",
        "description": "Emit the agent-callable command manifest.",
        "command": "gh-ui manifest",
    },
    {
        "id": "cli:smoke",
        "name": "smoke",
        "description": "Run cross-platform runtime smoke checks.",
        "command": "gh-ui smoke --with-data-query",
    },
    {
        "id": "cli:verify",
        "name": "verify",
        "description": "Run goal-oriented verification checks for the current platform.",
        "command": "gh-ui verify --with-data-query --windows-deps-preflight",
    },
    {
        "id": "cli:verify-plan",
        "name": "verify_plan",
        "description": "Emit machine-readable completion requirements and platform-specific verification commands.",
        "command": "gh-ui verify-plan",
    },
    {
        "id": "cli:verify-bundle",
        "name": "verify_bundle",
        "description": "Write source verification, plan, manifest, and handoff instructions for Windows completion.",
        "command": "gh-ui verify-bundle <OUTPUT_DIR> --with-data-query --strict",
    },
    {
        "id": "cli:ci-status",
        "name": "ci_status",
        "description": "Inspect GitHub Actions workflow evidence for Windows runtime verification.",
        "command": "gh-ui ci-status --repo <OWNER/REPO>",
    },
    {
        "id": "cli:ci-log-report",
        "name": "ci_log_report",
        "description": "Extract a marked verify report from GitHub Actions logs.",
        "command": "gh-ui ci-log-report <RUN_ID> --platform win32 --save <VERIFY_JSON>",
    },
    {
        "id": "cli:runtime-verify",
        "name": "runtime_verify",
        "description": "Generate an installed-runtime verification report against a temporary mock sidecar.",
        "command": "gh-ui runtime-verify <VERIFY_JSON>",
    },
    {
        "id": "cli:verify-merge",
        "name": "verify_merge",
        "description": "Merge macOS, Windows runtime, and Windows WeChat cache reports for final goal evidence.",
        "command": "gh-ui verify-merge <MAC_VERIFY_JSON> <WINDOWS_VERIFY_JSON_OR_DIR> <WECHAT_CACHE_VERIFY_JSON>",
    },
)
WECHAT_COMMANDS = (
    {
        "id": "wechat:articles-cache-export",
        "name": "articles_cache_export",
        "description": "Export local cached WeChat official-account articles by account name.",
        "command": "gh-ui wechat articles-cache-export <ACCOUNT_NAME> --limit 100 --output-dir <OUTPUT_DIR>",
    },
    {
        "id": "wechat:articles-cache-verify",
        "name": "articles_cache_verify",
        "description": "Run the real WeChat cache export path and emit a strict goal verification report.",
        "command": "gh-ui wechat articles-cache-verify <ACCOUNT_NAME> --strict --save <VERIFY_JSON>",
    },
)


def build_agent_manifest(
    audit: dict[str, Any],
    *,
    category: str = "",
    global_args: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    normalized_global_args = [str(item) for item in global_args or []]
    frontend_references = _frontend_references_by_route(audit.get("frontend_api_references", {}))
    entries: list[dict[str, Any]] = []
    for operation in audit.get("routes", {}).get("operations", []):
        entries.append(
            _route_entry(
                operation,
                normalized_global_args,
                frontend_references=_matching_frontend_references(
                    str(operation.get("path", "")),
                    frontend_references,
                ),
            )
        )

    for action, items in audit.get("data_capabilities", {}).items():
        for item in items:
            entries.append(_data_entry(action, item, normalized_global_args))

    for item in audit.get("factor_data_capabilities", []):
        entries.extend(_factor_entries(item, normalized_global_args))

    entries.extend(_cli_entries(normalized_global_args))
    entries.extend(_wechat_entries(normalized_global_args))

    if category:
        entries = [entry for entry in entries if entry["category"] == category]

    return {
        "total": len(entries),
        "category": category or "all",
        "global_args": normalized_global_args,
        "openapi_components": audit.get("openapi_components", {}),
        "entries": entries,
    }


def _route_entry(
    operation: dict[str, Any],
    global_args: list[str],
    *,
    frontend_references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    method = str(operation.get("method", ""))
    path = str(operation.get("path", ""))
    entry_id = f"route:{method}:{path}"
    command = str(operation.get("preferred") or operation.get("generic") or "")
    generic = str(operation.get("generic") or "")
    argv = _command_argv(command, global_args)
    generic_argv = _command_argv(generic, global_args)
    required_env = _required_env(argv)
    invoke_argv = _invoke_argv(
        entry_id,
        global_args,
        requires_token=_requires_token(argv),
        requires_access_token=_requires_access_token(argv),
    )
    request_body = operation.get("request_body", {})
    if not isinstance(request_body, dict):
        request_body = {}
    entry = {
        "id": entry_id,
        "kind": "route",
        "category": str(operation.get("category", "other")),
        "name": str(operation.get("name", "")),
        "command": _command_text(argv),
        "generic": _command_text(generic_argv),
        "invoke": _command_text(invoke_argv),
        "command_shell": _shell_commands(argv),
        "generic_shell": _shell_commands(generic_argv),
        "invoke_shell": _shell_commands(invoke_argv),
        "argv": argv,
        "generic_argv": generic_argv,
        "invoke_argv": invoke_argv,
        "required_env": required_env,
        "requires_token": _requires_token(argv),
        "requires_access_token": _requires_access_token(argv),
        "http_method": method,
        "path": path,
        "path_parameters": list(operation.get("path_parameters", [])),
        "requires_path_values": bool(operation.get("requires_path_values", False)),
        "parameters": list(operation.get("parameters", [])),
        "request_body_required": bool(request_body.get("required", False)),
        "request_content_types": list(request_body.get("content_types", [])),
        "request_body_schema": request_body.get("schema", {}),
    }
    normalized_frontend_references = list(frontend_references or [])
    entry["frontend_reference_paths"] = [
        str(reference.get("path", "")) for reference in normalized_frontend_references
    ]
    entry["frontend_sources"] = _frontend_sources(normalized_frontend_references)
    entry["frontend_reference_count"] = len(entry["frontend_sources"])
    return entry


def _data_entry(action: str, item: dict[str, Any], global_args: list[str]) -> dict[str, Any]:
    module = str(item.get("module", ""))
    method = str(item.get("method", ""))
    entry_id = f"data:{action}:{module}/{method}"
    command = str(item.get("preferred") or "")
    generic = str(item.get("generic") or "")
    argv = _command_argv(command, global_args)
    generic_argv = _command_argv(generic, global_args)
    required_env = _required_env(argv)
    invoke_argv = _invoke_argv(entry_id, global_args, requires_token=_requires_token(argv))
    return {
        "id": entry_id,
        "kind": "data",
        "category": "data",
        "action": action,
        "module": module,
        "method": method,
        "command": _command_text(argv),
        "generic": _command_text(generic_argv),
        "invoke": _command_text(invoke_argv),
        "command_shell": _shell_commands(argv),
        "generic_shell": _shell_commands(generic_argv),
        "invoke_shell": _shell_commands(invoke_argv),
        "argv": argv,
        "generic_argv": generic_argv,
        "invoke_argv": invoke_argv,
        "required_env": required_env,
        "requires_token": _requires_token(argv),
        "requires_access_token": _requires_access_token(argv),
    }


def _factor_entries(item: dict[str, Any], global_args: list[str]) -> list[dict[str, Any]]:
    table = str(item.get("table", ""))
    entries = []
    for action in ("query", "download", "update"):
        entry_id = f"factor_data:{action}:{table}"
        argv = _command_argv(str(item.get(action) or ""), global_args)
        generic_argv = list(argv)
        required_env = _required_env(argv)
        invoke_argv = _invoke_argv(entry_id, global_args, requires_token=_requires_token(argv))
        entries.append(
            {
                "id": entry_id,
                "kind": "factor_data",
                "category": "factor_data",
                "action": action,
                "table": table,
                "command": _command_text(argv),
                "generic": _command_text(generic_argv),
                "invoke": _command_text(invoke_argv),
                "command_shell": _shell_commands(argv),
                "generic_shell": _shell_commands(generic_argv),
                "invoke_shell": _shell_commands(invoke_argv),
                "argv": argv,
                "generic_argv": generic_argv,
                "invoke_argv": invoke_argv,
                "required_env": required_env,
                "requires_token": _requires_token(argv),
                "requires_access_token": _requires_access_token(argv),
            }
        )
    return entries


def _cli_entries(global_args: list[str]) -> list[dict[str, Any]]:
    entries = []
    for item in CLI_COMMANDS:
        argv = _command_argv(str(item["command"]), global_args)
        entries.append(
            {
                "id": str(item["id"]),
                "kind": "cli",
                "category": "cli",
                "name": str(item["name"]),
                "description": str(item["description"]),
                "command": _command_text(argv),
                "generic": _command_text(argv),
                "invoke": "",
                "command_shell": _shell_commands(argv),
                "generic_shell": _shell_commands(argv),
                "invoke_shell": {"posix": "", "powershell": "", "cmd": ""},
                "argv": argv,
                "generic_argv": list(argv),
                "invoke_argv": [],
                "required_env": _required_env(argv),
                "requires_token": _requires_token(argv),
                "requires_access_token": _requires_access_token(argv),
            }
        )
    return entries


def _wechat_entries(global_args: list[str]) -> list[dict[str, Any]]:
    entries = []
    for item in WECHAT_COMMANDS:
        argv = _command_argv(str(item["command"]), global_args)
        entries.append(
            {
                "id": str(item["id"]),
                "kind": "wechat_local",
                "category": "wechat",
                "name": str(item["name"]),
                "description": str(item["description"]),
                "command": _command_text(argv),
                "generic": _command_text(argv),
                "invoke": "",
                "command_shell": _shell_commands(argv),
                "generic_shell": _shell_commands(argv),
                "invoke_shell": {"posix": "", "powershell": "", "cmd": ""},
                "argv": argv,
                "generic_argv": list(argv),
                "invoke_argv": [],
                "required_env": _required_env(argv),
                "requires_token": _requires_token(argv),
                "requires_access_token": _requires_access_token(argv),
            }
        )
    return entries


def _command_argv(command: str, global_args: list[str]) -> list[str]:
    if not command:
        return []
    argv = [_normalize_arg(item) for item in shlex.split(command)]
    if argv and argv[0] == "gh-ui":
        return [argv[0], *global_args, *argv[1:]]
    return [*global_args, *argv]


def _frontend_references_by_route(frontend_api_references: Any) -> list[dict[str, Any]]:
    if not isinstance(frontend_api_references, dict):
        return []
    references = frontend_api_references.get("references", [])
    return [reference for reference in references if isinstance(reference, dict)]


def _matching_frontend_references(path: str, references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        reference
        for reference in references
        if _path_patterns_match(path, str(reference.get("path", "")))
    ]


def _frontend_sources(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources = []
    seen = set()
    for reference in references:
        for source in reference.get("sources", []):
            if not isinstance(source, dict):
                continue
            normalized = {
                "file": str(source.get("file", "")),
                "line": int(source.get("line", 0) or 0),
            }
            key = (normalized["file"], normalized["line"])
            if key in seen:
                continue
            seen.add(key)
            sources.append(normalized)
    return sources


def _path_patterns_match(left: str, right: str) -> bool:
    left_parts = [part for part in left.split("/") if part]
    right_parts = [part for part in right.split("/") if part]
    if len(left_parts) != len(right_parts):
        return False
    return all(_path_part_matches(left_part, right_part) for left_part, right_part in zip(left_parts, right_parts))


def _is_path_placeholder(value: str) -> bool:
    return value.startswith("{") and value.endswith("}")


def _path_part_matches(left: str, right: str) -> bool:
    return left == right or (_is_path_placeholder(left) and _is_path_placeholder(right))


def _normalize_arg(value: str) -> str:
    return ENV_PLACEHOLDERS.get(value, value)


def _command_text(argv: list[str]) -> str:
    return shlex.join(argv) if argv else ""


def _shell_commands(argv: list[str]) -> dict[str, str]:
    return {
        "posix": _join_shell(argv, shell="posix"),
        "powershell": _join_shell(argv, shell="powershell"),
        "cmd": _join_shell(argv, shell="cmd"),
    }


def _join_shell(argv: list[str], *, shell: str) -> str:
    if shell == "posix":
        return " ".join(_posix_arg(arg) for arg in argv)
    if shell == "powershell":
        return " ".join(_powershell_arg(arg) for arg in argv)
    if shell == "cmd":
        return " ".join(_cmd_arg(arg) for arg in argv)
    raise ValueError(f"unknown shell: {shell}")


def _posix_arg(value: str) -> str:
    if value in PLACEHOLDER_TO_ENV:
        return "$" + PLACEHOLDER_TO_ENV[value]
    if _has_placeholder(value):
        return '"' + _render_placeholder_arg(value, shell="posix").replace("\\", "\\\\").replace('"', '\\"') + '"'
    return shlex.quote(value)


def _powershell_arg(value: str) -> str:
    if value in PLACEHOLDER_TO_ENV:
        return "$env:" + PLACEHOLDER_TO_ENV[value]
    if _has_placeholder(value):
        return '"' + _render_placeholder_arg(value, shell="powershell").replace("`", "``").replace('"', '`"') + '"'
    if value == "":
        return "''"
    if all(char.isalnum() or char in "-_./:" for char in value):
        return value
    return "'" + value.replace("'", "''") + "'"


def _cmd_arg(value: str) -> str:
    if value in PLACEHOLDER_TO_ENV:
        return "%" + PLACEHOLDER_TO_ENV[value] + "%"
    if _has_placeholder(value):
        return '"' + _render_placeholder_arg(value, shell="cmd").replace('"', r'\"') + '"'
    if value == "":
        return '""'
    if all(char.isalnum() or char in "-_./:{}" for char in value):
        return value
    return '"' + value.replace('"', r'\"') + '"'


def _requires_token(argv: list[str]) -> bool:
    return TOKEN_PLACEHOLDER in argv


def _requires_access_token(argv: list[str]) -> bool:
    return ACCESS_TOKEN_PLACEHOLDER in argv


def _required_env(argv: list[str]) -> list[str]:
    required = []
    for placeholder in (TOKEN_PLACEHOLDER, ACCESS_TOKEN_PLACEHOLDER):
        if placeholder in argv:
            required.append(PLACEHOLDER_TO_ENV[placeholder])
    return required


def _has_placeholder(value: str) -> bool:
    return any(placeholder in value for placeholder in PLACEHOLDER_TO_ENV)


def _render_placeholder_arg(value: str, *, shell: str) -> str:
    rendered = value
    for placeholder, env_name in PLACEHOLDER_TO_ENV.items():
        if shell == "posix":
            replacement = "$" + env_name
        elif shell == "powershell":
            replacement = "$env:" + env_name
        elif shell == "cmd":
            replacement = "%" + env_name + "%"
        else:
            raise ValueError(f"unknown shell: {shell}")
        rendered = rendered.replace(placeholder, replacement)
    return rendered


def _invoke_argv(
    entry_id: str,
    global_args: list[str],
    requires_token: bool,
    requires_access_token: bool = False,
) -> list[str]:
    argv = ["gh-ui", *global_args, "invoke", entry_id]
    if requires_token:
        argv.extend(["--token", TOKEN_PLACEHOLDER])
    if requires_access_token:
        argv.extend(["--header", f"Authorization=Bearer {ACCESS_TOKEN_PLACEHOLDER}"])
    return argv
