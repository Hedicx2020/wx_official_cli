from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any


PATH_PARAM_RE = re.compile(r"\{([^}/]+)\}")
DATA_MODULES = {"trade", "stock", "index", "fund", "bond", "macro", "future"}
HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
FRONTEND_API_TEMPLATE_RE = re.compile(r"`\$\{(\w+)\}([^`]*)`")
FRONTEND_API_CONST_RE = re.compile(r"const\s+(\w+)\s*=\s*`\$\{(API_HOST|\w+)\}([^`]*)`")
REMOTE_REQUEST_CALL_RE = re.compile(r"\bremoteRequest(?:<[^>]+>)?\(\s*([`'\"])(.*?)\1")


def classify_route(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2 or parts[0] != "api":
        return "other"

    head = parts[1]
    if len(parts) >= 3 and head == "{module}" and parts[2] == "{method}":
        return "data"
    if len(parts) >= 4 and head in {"download", "update"} and parts[2] == "{module}" and parts[3] == "{method}":
        return "data"
    if len(parts) >= 5 and head == "factor" and parts[2] == "db" and parts[3] in {"query", "download", "update"}:
        return "factor_data"
    if head in DATA_MODULES:
        return "data"
    if head == "download":
        return "data_download"
    if head == "update":
        return "data_update"
    if head in {"factor", "backtest", "wechat", "ai", "remote"}:
        return head
    if head in {"health", "logs", "local", "config", "auth", "export", "feedback"}:
        return head
    return "other"


def path_parameters(path: str) -> list[str]:
    return PATH_PARAM_RE.findall(path)


def build_route_command(route: dict[str, Any], method: str) -> dict[str, Any]:
    path = str(route.get("path", ""))
    method = method.upper()
    params = path_parameters(path)
    category = classify_route(path)
    preferred = preferred_command(path, method, category)
    generic = f"gh-ui api request {method} {path}"
    operation = _operation_metadata(route, method)

    return {
        "path": path,
        "method": method,
        "name": route.get("name", ""),
        "category": category,
        "generic": generic,
        "preferred": preferred,
        "path_parameters": params,
        "requires_path_values": bool(params),
        "parameters": operation.get("parameters", []),
        "request_body": operation.get("request_body", {}),
        "callable": bool(path and method),
    }


def preferred_command(path: str, method: str, category: str) -> str:
    parts = [part for part in path.split("/") if part]
    if path == "/api/{module}/{method}" and method == "GET":
        return "gh-ui invoke route:GET:/api/{module}/{method}"
    if path == "/api/download/{module}/{method}" and method == "POST":
        return "gh-ui invoke route:POST:/api/download/{module}/{method} --token $GH_API_TOKEN"
    if path == "/api/update/{module}/{method}" and method == "POST":
        return "gh-ui invoke route:POST:/api/update/{module}/{method} --token $GH_API_TOKEN"
    if path == "/api/factor/db/query/{table}" and method == "GET":
        return "gh-ui invoke route:GET:/api/factor/db/query/{table}"
    if path == "/api/factor/db/download/{table}" and method == "POST":
        return "gh-ui invoke route:POST:/api/factor/db/download/{table} --token $GH_API_TOKEN"
    if path == "/api/factor/db/update/{table}" and method == "POST":
        return "gh-ui invoke route:POST:/api/factor/db/update/{table} --token $GH_API_TOKEN"

    core_commands = {
        ("GET", "/api/health"): "gh-ui health",
        ("GET", "/api/download/progress"): "gh-ui data progress",
        ("GET", "/api/local/files"): "gh-ui data files",
        ("GET", "/api/config/paths"): "gh-ui config get-paths",
        ("POST", "/api/config/paths"): "gh-ui config set-paths --db-path <DB_PATH>",
        ("GET", "/api/logs"): "gh-ui logs",
        ("POST", "/api/export/excel"): "gh-ui export excel --input @export.json",
        ("POST", "/api/feedback"): "gh-ui feedback submit --json @feedback.json",
    }
    if (method, path) in core_commands:
        return core_commands[(method, path)]

    if len(parts) >= 3 and category == "data" and method == "GET":
        return f"gh-ui data query {parts[1]} {parts[2]}"

    if len(parts) >= 4 and category == "data_download" and method == "POST":
        return f"gh-ui data download {parts[2]} {parts[3]} --token $GH_API_TOKEN"

    if len(parts) >= 4 and category == "data_update" and method == "POST":
        return f"gh-ui data update {parts[2]} {parts[3]} --token $GH_API_TOKEN"

    if len(parts) >= 5 and path.startswith("/api/factor/db/query/") and method == "GET":
        return f"gh-ui factor query {parts[4]}"

    if len(parts) >= 5 and path.startswith("/api/factor/db/download/") and method == "POST":
        return f"gh-ui factor download {parts[4]} --token $GH_API_TOKEN"

    if len(parts) >= 5 and path.startswith("/api/factor/db/update/") and method == "POST":
        return f"gh-ui factor update {parts[4]} --token $GH_API_TOKEN"

    wechat_commands = {
        ("POST", "/api/wechat/log"): "gh-ui wechat log --message <MESSAGE>",
        ("GET", "/api/wechat/config"): "gh-ui wechat config-get",
        ("POST", "/api/wechat/config"): "gh-ui wechat config-set --json @wechat_config.json",
        ("POST", "/api/wechat/macos/resign-wechat"): "gh-ui wechat macos-resign",
        ("GET", "/api/wechat/password/status"): "gh-ui wechat password-status",
        ("POST", "/api/wechat/password/auto"): "gh-ui wechat password-auto",
        ("GET", "/api/wechat/debug/inspect"): "gh-ui wechat debug-inspect",
        ("GET", "/api/wechat/sessions"): "gh-ui wechat sessions",
        ("POST", "/api/wechat/messages/search"): "gh-ui wechat search --json @wechat_search.json",
        ("POST", "/api/wechat/llm/summarize"): "gh-ui wechat summarize --json @summarize.json",
        ("GET", "/api/wechat/contacts/export"): "gh-ui wechat contacts-export",
        ("POST", "/api/wechat/messages/export"): "gh-ui wechat messages-export --json @wechat_search.json",
        ("GET", "/api/wechat/search/stats"): "gh-ui wechat search-stats",
        ("GET", "/api/wechat/stock/stats"): "gh-ui wechat stock-stats",
        ("POST", "/api/wechat/stock/preload"): "gh-ui wechat stock-preload",
        ("POST", "/api/wechat/stock/review"): "gh-ui wechat kline-review --json @kline_review.json",
        ("POST", "/api/wechat/stock/review/export"): "gh-ui wechat kline-review-export --json @kline_review.json",
        ("POST", "/api/wechat/stock/screener"): "gh-ui wechat stock-screener --json @stock_screener.json",
        (
            "POST",
            "/api/wechat/stock/screener/export",
        ): "gh-ui wechat stock-screener-export --json @stock_screener.json",
        ("POST", "/api/wechat/stock/picks"): "gh-ui wechat stock-picks --json @stock_pick.json",
        ("POST", "/api/wechat/image/extract-keys"): "gh-ui wechat image-extract-keys",
        ("GET", "/api/wechat/image/get-keys"): "gh-ui wechat image-keys",
        ("POST", "/api/wechat/image/convert"): "gh-ui wechat image-convert --json @image_convert.json",
        ("GET", "/api/wechat/image/list"): "gh-ui wechat image-list",
        ("GET", "/api/wechat/image/months"): "gh-ui wechat image-months",
        ("POST", "/api/wechat/image/batch-convert"): "gh-ui wechat image-batch-convert --json @image_batch_convert.json",
        ("POST", "/api/wechat/llm/chat"): "gh-ui wechat llm-chat --json @llm_chat.json",
        ("POST", "/api/wechat/llm/test"): "gh-ui wechat llm-test --json @llm_config.json",
        ("POST", "/api/wechat/llm/batch/stream"): "gh-ui wechat llm-batch-stream --json @llm_batch.json",
        ("POST", "/api/wechat/llm/export"): "gh-ui wechat llm-export --json @llm_export.json",
        ("POST", "/api/wechat/report/pdf"): "gh-ui wechat pdf-report --json @pdf_report.json",
        ("POST", "/api/wechat/articles/llm_analyze"): "gh-ui wechat articles-analyze --json @article_analyze.json",
        ("GET", "/api/wechat/articles/analyses"): "gh-ui wechat articles-analyses",
        ("GET", "/api/wechat/articles/analyses/{analysis_id}"): "gh-ui wechat articles-analysis-get {analysis_id}",
        (
            "DELETE",
            "/api/wechat/articles/analyses/{analysis_id}",
        ): "gh-ui wechat articles-analysis-delete {analysis_id}",
        (
            "POST",
            "/api/wechat/articles/analyses/export",
        ): "gh-ui wechat articles-export-analysis --json @article_analysis_export.json",
        ("GET", "/api/wechat/articles/settings"): "gh-ui wechat articles-settings",
        ("POST", "/api/wechat/articles/settings"): "gh-ui wechat articles-settings-set --json @article_settings.json",
        ("GET", "/api/wechat/articles/login/qrcode"): "gh-ui wechat articles-login-qrcode",
        ("POST", "/api/wechat/articles/login/poll"): "gh-ui wechat articles-login-poll --scan-id <SCAN_ID>",
        ("POST", "/api/wechat/articles/login/logout"): "gh-ui wechat articles-login-logout",
        ("GET", "/api/wechat/articles/login/status"): "gh-ui wechat articles-login-status",
        ("GET", "/api/wechat/articles/accounts"): "gh-ui wechat articles-accounts",
        ("POST", "/api/wechat/articles/open_html_dir"): "gh-ui wechat articles-open-html-dir",
        ("GET", "/api/wechat/articles/categories"): "gh-ui wechat articles-categories",
        ("POST", "/api/wechat/articles/categories"): "gh-ui wechat articles-category-create --name <NAME>",
        (
            "PUT",
            "/api/wechat/articles/categories/{category_id}",
        ): "gh-ui wechat articles-category-rename {category_id} --name <NAME>",
        (
            "DELETE",
            "/api/wechat/articles/categories/{category_id}",
        ): "gh-ui wechat articles-category-delete {category_id}",
        (
            "GET",
            "/api/wechat/articles/accounts/{mp_id}/categories",
        ): "gh-ui wechat articles-account-categories {mp_id}",
        (
            "POST",
            "/api/wechat/articles/accounts/{mp_id}/categories",
        ): "gh-ui wechat articles-account-set-categories {mp_id} --category-id <CATEGORY_ID>",
        (
            "POST",
            "/api/wechat/articles/accounts/{mp_id}/favorite",
        ): "gh-ui wechat articles-account-favorite {mp_id} --favorite",
        (
            "POST",
            "/api/wechat/articles/accounts/add_by_url",
        ): "gh-ui wechat articles-account-add-by-url <ARTICLE_URL>",
        ("DELETE", "/api/wechat/articles/accounts/{mp_id}"): "gh-ui wechat articles-account-delete {mp_id}",
        ("POST", "/api/wechat/articles/accounts/dedupe"): "gh-ui wechat articles-account-dedupe",
        ("GET", "/api/wechat/articles/articles"): "gh-ui wechat articles-list",
        (
            "POST",
            "/api/wechat/articles/articles/{article_id}/fetch",
        ): "gh-ui wechat articles-fetch {article_id}",
        (
            "POST",
            "/api/wechat/articles/articles/fetch_batch",
        ): "gh-ui wechat articles-fetch-batch --json @articles_fetch_batch.json",
        ("GET", "/api/wechat/articles/articles/{article_id}/html"): "gh-ui wechat articles-html {article_id}",
        ("POST", "/api/wechat/articles/sync"): "gh-ui wechat articles-sync --json @articles_sync.json",
        ("GET", "/api/wechat/articles/sync/status"): "gh-ui wechat articles-status",
        (
            "POST",
            "/api/wechat/articles/sync_by_category",
        ): "gh-ui wechat articles-sync-by-category --json @sync_by_category.json",
        ("GET", "/api/wechat/articles/sync_by_category/status"): "gh-ui wechat articles-sync-by-category-status",
        (
            "POST",
            "/api/wechat/articles/sync_by_category/purge_invalid",
        ): "gh-ui wechat articles-purge-invalid --category-id <CATEGORY_ID>",
        (
            "GET",
            "/api/wechat/articles/sync_by_category/preview",
        ): "gh-ui wechat articles-sync-by-category-preview --category-id <CATEGORY_ID> --mode <MODE>",
        ("POST", "/api/wechat/articles/sync_local"): "gh-ui wechat articles-sync-local --json @articles_sync_local.json",
        ("POST", "/api/wechat/articles/_fixture/seed"): "gh-ui wechat articles-fixture-seed --json @articles_fixture.json",
    }
    if (method, path) in wechat_commands:
        return wechat_commands[(method, path)]

    if path.startswith("/api/wechat"):
        suffix = path.removeprefix("/api/wechat") or "/"
        return f"gh-ui wechat request {method} {suffix}"

    if path == "/api/auth/verify" and method == "POST":
        return "gh-ui auth verify --token $GH_API_TOKEN"

    if path == "/api/auth/login" and method == "POST":
        return "gh-ui auth login --json @login.json"

    if path == "/api/auth/active-token" and method == "POST":
        return "gh-ui auth active-token --access-token $GH_ACCESS_TOKEN"

    if path == "/api/ai/status" and method == "GET":
        return "gh-ui ai status"

    if path == "/api/ai/report-reproduce/projects" and method == "GET":
        return "gh-ui ai projects"

    if path == "/api/ai/report-reproduce/pdf-candidates" and method == "GET":
        return "gh-ui ai pdf-candidates"

    if path == "/api/ai/report-reproduce/tasks" and method == "GET":
        return "gh-ui ai tasks"

    if path == "/api/ai/report-reproduce/tasks/{task_id}" and method == "GET":
        return "gh-ui ai task {task_id}"

    if path == "/api/ai/report-reproduce/tasks/{task_id}/cancel" and method == "POST":
        return "gh-ui ai cancel {task_id}"

    if path == "/api/ai/report-reproduce/start" and method == "POST":
        return "gh-ui ai start --json @report_reproduce.json"

    if path.startswith("/api/ai"):
        suffix = path.removeprefix("/api/ai") or "/"
        return f"gh-ui ai request {method} {suffix}"

    backtest_commands = {
        ("GET", "/api/backtest/check-data"): "gh-ui backtest check-data",
        ("GET", "/api/backtest/index-codes"): "gh-ui backtest index-codes",
        ("POST", "/api/backtest/upload-portfolio-json"): "gh-ui backtest upload-json --json @portfolio.json",
        ("GET", "/api/backtest/uploaded-portfolio/{upload_id}"): "gh-ui backtest uploaded-portfolio {upload_id}",
        ("POST", "/api/backtest/upload-portfolio"): "gh-ui backtest upload <FILE>",
        ("GET", "/api/backtest/sample-portfolio"): "gh-ui backtest sample-portfolio",
        ("POST", "/api/backtest/monitoring"): "gh-ui backtest monitoring --json @monitoring.json",
        (
            "GET",
            "/api/backtest/monitoring/holdings",
        ): "gh-ui backtest monitoring-holdings --upload-id {upload_id} --date YYYY-MM-DD",
        ("POST", "/api/backtest/brinson"): "gh-ui backtest brinson --json @brinson.json",
        ("POST", "/api/backtest/risk"): "gh-ui backtest risk --json @risk.json",
        ("POST", "/api/backtest/run"): "gh-ui backtest run --json @backtest_config.json",
        ("GET", "/api/backtest/results/{task_id}"): "gh-ui backtest result {task_id}",
        ("GET", "/api/backtest/results/{task_id}/holdings"): "gh-ui backtest holdings {task_id}",
        ("GET", "/api/backtest/results/{task_id}/export"): "gh-ui backtest export {task_id}",
    }
    if (method, path) in backtest_commands:
        return backtest_commands[(method, path)]

    factor_commands = {
        ("POST", "/api/factor/upload"): "gh-ui factor upload <FILE>",
        ("GET", "/api/factor/sample"): "gh-ui factor sample",
        ("POST", "/api/factor/analyze"): "gh-ui factor analyze --json @factor_analyze.json",
        ("POST", "/api/factor/report"): "gh-ui factor report --json @factor_report.json",
        ("GET", "/api/factor/db/databases"): "gh-ui factor databases",
        ("GET", "/api/factor/db/tables"): "gh-ui factor tables",
        ("GET", "/api/factor/db/catalog"): "gh-ui factor catalog",
        ("GET", "/api/factor/db/values"): "gh-ui factor values <FACTOR_ID>",
        ("GET", "/api/factor/db/progress"): "gh-ui factor progress",
        ("GET", "/api/factor/barra/returns"): "gh-ui factor barra-returns",
        ("GET", "/api/factor/rank/meta"): "gh-ui factor rank-meta",
        (
            "GET",
            "/api/factor/rank/list",
        ): "gh-ui factor rank-list --param ind_code=<IND_CODE> --param year=<YEAR>",
        (
            "GET",
            "/api/factor/rank/detail/{factor_id}",
        ): "gh-ui factor rank-detail {factor_id} --ind-code <IND_CODE>",
    }
    if (method, path) in factor_commands:
        return factor_commands[(method, path)]

    if path == "/api/remote/me" and method == "GET":
        return "gh-ui remote me --access-token $GH_ACCESS_TOKEN"

    if path == "/api/remote/tokens" and method == "GET":
        return "gh-ui remote tokens --access-token $GH_ACCESS_TOKEN"

    if path == "/api/remote/tokens" and method == "POST":
        return "gh-ui remote token-generate --access-token $GH_ACCESS_TOKEN --name <TOKEN_NAME>"

    if path == "/api/remote/tokens/{token_id}" and method == "DELETE":
        return "gh-ui remote token-revoke {token_id} --access-token $GH_ACCESS_TOKEN"

    if path.startswith("/api/remote"):
        suffix = path.removeprefix("/api/remote") or "/"
        return f"gh-ui remote request {method} {suffix}"

    return f"gh-ui api request {method} {path}"


def audit_routes(routes: list[dict[str, Any]]) -> dict[str, Any]:
    operations = []
    category_counts: Counter[str] = Counter()
    missing = []

    for route in routes:
        for method in sorted(route.get("methods", []) or []):
            op = build_route_command(route, str(method))
            operations.append(op)
            category_counts[op["category"]] += 1
            if not op["callable"]:
                missing.append(op)

    total = len(operations)
    callable_count = total - len(missing)
    return {
        "total_operations": total,
        "callable_operations": callable_count,
        "missing_operations": missing,
        "coverage_ratio": callable_count / total if total else 1.0,
        "categories": dict(sorted(category_counts.items())),
        "operations": operations,
    }


def routes_from_openapi(schema: dict[str, Any]) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for path, path_item in sorted((schema.get("paths") or {}).items()):
        if not isinstance(path_item, dict):
            continue
        methods = []
        names = []
        operations: dict[str, dict[str, Any]] = {}
        for key, operation in path_item.items():
            key_lower = str(key).lower()
            if key_lower not in HTTP_METHODS:
                continue
            method = key_lower.upper()
            methods.append(method)
            if isinstance(operation, dict):
                names.append(str(operation.get("operationId") or operation.get("summary") or ""))
                operations[method] = _openapi_operation_metadata(operation)
        if not methods:
            continue
        name = next((item for item in names if item), "")
        routes.append(
            {
                "path": str(path),
                "methods": sorted(methods),
                "name": name,
                "operations": operations,
            }
        )
    return routes


def enrich_routes_from_openapi(routes: list[dict[str, Any]], schema: dict[str, Any]) -> list[dict[str, Any]]:
    openapi_routes = {str(route.get("path", "")): route for route in routes_from_openapi(schema)}
    enriched = []
    for route in routes:
        path = str(route.get("path", ""))
        openapi_route = openapi_routes.get(path, {})
        operations = openapi_route.get("operations", {})
        if not isinstance(operations, dict):
            operations = {}
        enriched.append({**route, "operations": operations})
    return enriched


def audit_backend(
    routes: list[dict[str, Any]],
    *,
    query_methods: list[tuple[str, str]] | set[tuple[str, str]] | None = None,
    download_methods: list[tuple[str, str]] | set[tuple[str, str]] | None = None,
    update_methods: list[tuple[str, str]] | set[tuple[str, str]] | None = None,
    factor_tables: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    route_audit = audit_routes(routes)
    data_capabilities = {
        "query": [_data_capability(module, method, "query") for module, method in _sorted_keys(query_methods)],
        "download": [
            _data_capability(module, method, "download") for module, method in _sorted_keys(download_methods)
        ],
        "update": [_data_capability(module, method, "update") for module, method in _sorted_keys(update_methods)],
    }
    factor_capabilities = [_factor_table_capability(table) for table in sorted(set(factor_tables or []))]
    all_callables = (
        route_audit["coverage_ratio"] == 1.0
        and all(item["callable"] for items in data_capabilities.values() for item in items)
        and all(item["callable"] for item in factor_capabilities)
    )

    return {
        "all_callables": all_callables,
        "totals": {
            "route_operations": route_audit["total_operations"],
            "data_query_methods": len(data_capabilities["query"]),
            "data_download_methods": len(data_capabilities["download"]),
            "data_update_methods": len(data_capabilities["update"]),
            "factor_data_tables": len(factor_capabilities),
        },
        "routes": route_audit,
        "data_capabilities": data_capabilities,
        "factor_data_capabilities": factor_capabilities,
    }


def audit_frontend_api_references(source_root: Path, routes: list[dict[str, Any]]) -> dict[str, Any]:
    references = _frontend_api_references(source_root)
    route_paths = [str(route.get("path", "")) for route in routes if str(route.get("path", "")).startswith("/api")]
    missing = [
        reference
        for reference in references
        if not any(_path_patterns_match(reference["path"], route_path) for route_path in route_paths)
    ]
    total = len(references)
    covered = total - len(missing)
    return {
        "total_references": total,
        "covered_references": covered,
        "missing_references": missing,
        "coverage_ratio": covered / total if total else 1.0,
        "references": references,
    }


def _frontend_api_references(source_root: Path) -> list[dict[str, Any]]:
    lib_dir = source_root / "src" / "lib"
    if not lib_dir.exists():
        return []

    by_path: dict[str, dict[str, Any]] = {}
    for file_path in sorted(lib_dir.glob("*.ts")):
        text = file_path.read_text(encoding="utf-8")
        prefixes = _frontend_api_prefixes(text)
        for line_no, line in enumerate(text.splitlines(), 1):
            for path in _remote_request_paths(line):
                entry = by_path.setdefault(path, {"path": path, "sources": []})
                entry["sources"].append(
                    {"file": str(file_path.relative_to(source_root)), "line": line_no}
                )
            if not _line_may_contain_api_reference(line):
                continue
            if re.search(r"const\s+\w+\s*=\s*`\$\{\w+\}/api", line):
                continue
            for match in FRONTEND_API_TEMPLATE_RE.finditer(line):
                name, suffix = match.groups()
                if name not in prefixes or _is_dynamic_frontend_wrapper(suffix):
                    continue
                path = _normalize_frontend_api_path(prefixes[name] + suffix)
                if not path.startswith("/api"):
                    continue
                entry = by_path.setdefault(path, {"path": path, "sources": []})
                entry["sources"].append(
                    {"file": str(file_path.relative_to(source_root)), "line": line_no}
                )

    return [by_path[path] for path in sorted(by_path)]


def _remote_request_paths(line: str) -> list[str]:
    paths = []
    for match in REMOTE_REQUEST_CALL_RE.finditer(line):
        suffix = match.group(2)
        path = _normalize_frontend_api_path("/api/remote" + suffix)
        if path.startswith("/api/remote"):
            paths.append(path)
    return paths


def _frontend_api_prefixes(text: str) -> dict[str, str]:
    prefixes: dict[str, str] = {}
    for _ in range(5):
        for match in FRONTEND_API_CONST_RE.finditer(text):
            name, base, suffix = match.groups()
            if base == "API_HOST":
                base_path = ""
            elif base in prefixes:
                base_path = prefixes[base]
            else:
                continue
            prefixes[name] = base_path + suffix
    return prefixes


def _line_may_contain_api_reference(line: str) -> bool:
    return any(marker in line for marker in ("fetch(", "request(`", "const url =", "return `${"))


def _is_dynamic_frontend_wrapper(suffix: str) -> bool:
    normalized = suffix.strip()
    return normalized == "${path}" or normalized.endswith("${path}")


def _normalize_frontend_api_path(path: str) -> str:
    path = re.sub(r"\$\{[^}]*\?[^}]*\}", "", path)
    path = re.sub(r"\$\{\s*pathQuery\([^}]*\)\s*\}", "", path)
    path = re.sub(r"\$\{\s*(sp|qs|params|query)\s*\}", "", path)
    path = path.split("?", 1)[0]
    path = re.sub(
        r"\$\{\s*encodeURIComponent\(([^)]+)\)\s*\}",
        lambda match: "{" + match.group(1).strip() + "}",
        path,
    )
    path = re.sub(
        r"\$\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}",
        lambda match: "{" + match.group(1) + "}",
        path,
    )
    path = re.sub(r"\$\{[^}]+\}", "{param}", path)
    path = re.sub(r"/+", "/", path)
    return path.rstrip("/") or "/"


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


def _sorted_keys(keys: list[tuple[str, str]] | set[tuple[str, str]] | None) -> list[tuple[str, str]]:
    return sorted(set(keys or []))


def _operation_metadata(route: dict[str, Any], method: str) -> dict[str, Any]:
    operations = route.get("operations", {})
    if not isinstance(operations, dict):
        return {}
    metadata = operations.get(method, {})
    return metadata if isinstance(metadata, dict) else {}


def _openapi_operation_metadata(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "parameters": _openapi_parameters(operation.get("parameters", [])),
        "request_body": _openapi_request_body(operation.get("requestBody")),
    }


def _openapi_parameters(parameters: Any) -> list[dict[str, Any]]:
    if not isinstance(parameters, list):
        return []
    normalized = []
    for parameter in parameters:
        if not isinstance(parameter, dict):
            continue
        normalized.append(
            {
                "name": str(parameter.get("name", "")),
                "in": str(parameter.get("in", "")),
                "required": bool(parameter.get("required", False)),
                "schema": parameter.get("schema", {}),
            }
        )
    return normalized


def _openapi_request_body(request_body: Any) -> dict[str, Any]:
    if not isinstance(request_body, dict):
        return {}
    content = request_body.get("content", {})
    if not isinstance(content, dict):
        content = {}
    content_types = sorted(str(content_type) for content_type in content)
    schema: Any = {}
    if content_types:
        first_content = content.get(content_types[0])
        if isinstance(first_content, dict):
            schema = first_content.get("schema", {})
    return {
        "required": bool(request_body.get("required", False)),
        "content_types": content_types,
        "schema": schema,
    }


def _data_capability(module: str, method: str, action: str) -> dict[str, Any]:
    if action == "query":
        preferred = f"gh-ui data query {module} {method}"
        generic = f"gh-ui api request GET /api/{module}/{method}"
    else:
        preferred = f"gh-ui data {action} {module} {method} --token $GH_API_TOKEN"
        generic = f"gh-ui api request POST /api/{action}/{module}/{method}"
    return {
        "module": module,
        "method": method,
        "action": action,
        "preferred": preferred,
        "generic": generic,
        "callable": True,
    }


def _factor_table_capability(table: str) -> dict[str, Any]:
    return {
        "table": table,
        "query": f"gh-ui factor query {table}",
        "download": f"gh-ui factor download {table} --token $GH_API_TOKEN",
        "update": f"gh-ui factor update {table} --token $GH_API_TOKEN",
        "callable": True,
    }
