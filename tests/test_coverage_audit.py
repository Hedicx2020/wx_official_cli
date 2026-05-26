import unittest
import tempfile
from pathlib import Path

from gh_ui_cli.coverage_audit import (
    audit_backend,
    audit_frontend_api_references,
    audit_routes,
    build_route_command,
    classify_route,
    enrich_routes_from_openapi,
    routes_from_openapi,
)


class CoverageAuditTest(unittest.TestCase):
    def test_classifies_core_route_groups(self):
        self.assertEqual(classify_route("/api/stock/stock_price"), "data")
        self.assertEqual(classify_route("/api/{module}/{method}"), "data")
        self.assertEqual(classify_route("/api/download/{module}/{method}"), "data")
        self.assertEqual(classify_route("/api/update/{module}/{method}"), "data")
        self.assertEqual(classify_route("/api/download/progress"), "data_download")
        self.assertEqual(classify_route("/api/factor/db/query/{table}"), "factor_data")
        self.assertEqual(classify_route("/api/factor/db/update/{table}"), "factor_data")
        self.assertEqual(classify_route("/api/backtest/run"), "backtest")
        self.assertEqual(classify_route("/api/wechat/articles/categories"), "wechat")
        self.assertEqual(classify_route("/api/remote/tokens"), "remote")

    def test_builds_agent_safe_generic_command(self):
        command = build_route_command(
            {"path": "/api/wechat/articles/categories/{category_id}", "methods": ["DELETE"], "name": "delete_category"},
            "DELETE",
        )
        self.assertEqual(
            command["generic"],
            "gh-ui api request DELETE /api/wechat/articles/categories/{category_id}",
        )
        self.assertEqual(command["path_parameters"], ["category_id"])
        self.assertTrue(command["requires_path_values"])

    def test_suggests_stable_explicit_commands_for_common_routes(self):
        data = build_route_command(
            {"path": "/api/stock/stock_price", "methods": ["GET"], "name": "query_data"},
            "GET",
        )
        self.assertEqual(data["preferred"], "gh-ui data query stock stock_price")

        dynamic_data = build_route_command(
            {"path": "/api/{module}/{method}", "methods": ["GET"], "name": "query_data"},
            "GET",
        )
        self.assertEqual(dynamic_data["category"], "data")
        self.assertEqual(
            dynamic_data["preferred"],
            "gh-ui invoke route:GET:/api/{module}/{method}",
        )

        dynamic_update = build_route_command(
            {"path": "/api/update/{module}/{method}", "methods": ["POST"], "name": "update_data"},
            "POST",
        )
        self.assertEqual(dynamic_update["category"], "data")
        self.assertEqual(
            dynamic_update["preferred"],
            "gh-ui invoke route:POST:/api/update/{module}/{method} --token $GH_API_TOKEN",
        )

        dynamic_factor_update = build_route_command(
            {"path": "/api/factor/db/update/{table}", "methods": ["POST"], "name": "update_factor"},
            "POST",
        )
        self.assertEqual(dynamic_factor_update["category"], "factor_data")
        self.assertEqual(
            dynamic_factor_update["preferred"],
            "gh-ui invoke route:POST:/api/factor/db/update/{table} --token $GH_API_TOKEN",
        )

        wechat = build_route_command(
            {"path": "/api/wechat/sessions", "methods": ["GET"], "name": "list_sessions"},
            "GET",
        )
        self.assertEqual(wechat["preferred"], "gh-ui wechat sessions")

        auth_login = build_route_command(
            {"path": "/api/auth/login", "methods": ["POST"], "name": "auth_login"},
            "POST",
        )
        self.assertEqual(auth_login["preferred"], "gh-ui auth login --json @login.json")

        ai_start = build_route_command(
            {"path": "/api/ai/report-reproduce/start", "methods": ["POST"], "name": "start_report"},
            "POST",
        )
        self.assertEqual(ai_start["preferred"], "gh-ui ai start --json @report_reproduce.json")

        ai_cancel = build_route_command(
            {"path": "/api/ai/report-reproduce/tasks/{task_id}/cancel", "methods": ["POST"], "name": "cancel_report"},
            "POST",
        )
        self.assertEqual(ai_cancel["preferred"], "gh-ui ai cancel {task_id}")

        remote_me = build_route_command(
            {"path": "/api/remote/me", "methods": ["GET"], "name": "remote_me"},
            "GET",
        )
        self.assertEqual(remote_me["preferred"], "gh-ui remote me --access-token $GH_ACCESS_TOKEN")

        remote_tokens = build_route_command(
            {"path": "/api/remote/tokens", "methods": ["GET"], "name": "remote_tokens_list"},
            "GET",
        )
        self.assertEqual(remote_tokens["preferred"], "gh-ui remote tokens --access-token $GH_ACCESS_TOKEN")

        remote_generate = build_route_command(
            {"path": "/api/remote/tokens", "methods": ["POST"], "name": "remote_tokens_generate"},
            "POST",
        )
        self.assertEqual(
            remote_generate["preferred"],
            "gh-ui remote token-generate --access-token $GH_ACCESS_TOKEN --name <TOKEN_NAME>",
        )

        remote_revoke = build_route_command(
            {"path": "/api/remote/tokens/{token_id}", "methods": ["DELETE"], "name": "remote_tokens_revoke"},
            "DELETE",
        )
        self.assertEqual(
            remote_revoke["preferred"],
            "gh-ui remote token-revoke {token_id} --access-token $GH_ACCESS_TOKEN",
        )

    def test_suggests_stable_explicit_commands_for_backtest_routes(self):
        cases = [
            ("/api/backtest/check-data", "GET", "gh-ui backtest check-data"),
            ("/api/backtest/index-codes", "GET", "gh-ui backtest index-codes"),
            ("/api/backtest/upload-portfolio-json", "POST", "gh-ui backtest upload-json --json @portfolio.json"),
            ("/api/backtest/uploaded-portfolio/{upload_id}", "GET", "gh-ui backtest uploaded-portfolio {upload_id}"),
            ("/api/backtest/upload-portfolio", "POST", "gh-ui backtest upload <FILE>"),
            ("/api/backtest/sample-portfolio", "GET", "gh-ui backtest sample-portfolio"),
            ("/api/backtest/monitoring", "POST", "gh-ui backtest monitoring --json @monitoring.json"),
            (
                "/api/backtest/monitoring/holdings",
                "GET",
                "gh-ui backtest monitoring-holdings --upload-id {upload_id} --date YYYY-MM-DD",
            ),
            ("/api/backtest/brinson", "POST", "gh-ui backtest brinson --json @brinson.json"),
            ("/api/backtest/risk", "POST", "gh-ui backtest risk --json @risk.json"),
            ("/api/backtest/run", "POST", "gh-ui backtest run --json @backtest_config.json"),
            ("/api/backtest/results/{task_id}", "GET", "gh-ui backtest result {task_id}"),
            ("/api/backtest/results/{task_id}/holdings", "GET", "gh-ui backtest holdings {task_id}"),
            ("/api/backtest/results/{task_id}/export", "GET", "gh-ui backtest export {task_id}"),
        ]

        for path, method, expected in cases:
            with self.subTest(path=path, method=method):
                command = build_route_command({"path": path, "methods": [method], "name": "backtest"}, method)
                self.assertEqual(command["preferred"], expected)

    def test_suggests_stable_explicit_commands_for_factor_routes(self):
        cases = [
            ("/api/factor/upload", "POST", "gh-ui factor upload <FILE>"),
            ("/api/factor/sample", "GET", "gh-ui factor sample"),
            ("/api/factor/analyze", "POST", "gh-ui factor analyze --json @factor_analyze.json"),
            ("/api/factor/report", "POST", "gh-ui factor report --json @factor_report.json"),
            ("/api/factor/db/databases", "GET", "gh-ui factor databases"),
            ("/api/factor/db/tables", "GET", "gh-ui factor tables"),
            ("/api/factor/db/catalog", "GET", "gh-ui factor catalog"),
            ("/api/factor/db/values", "GET", "gh-ui factor values <FACTOR_ID>"),
            ("/api/factor/db/progress", "GET", "gh-ui factor progress"),
            ("/api/factor/barra/returns", "GET", "gh-ui factor barra-returns"),
            ("/api/factor/rank/meta", "GET", "gh-ui factor rank-meta"),
            ("/api/factor/rank/list", "GET", "gh-ui factor rank-list --param ind_code=<IND_CODE> --param year=<YEAR>"),
            (
                "/api/factor/rank/detail/{factor_id}",
                "GET",
                "gh-ui factor rank-detail {factor_id} --ind-code <IND_CODE>",
            ),
        ]

        for path, method, expected in cases:
            with self.subTest(path=path, method=method):
                command = build_route_command({"path": path, "methods": [method], "name": "factor"}, method)
                self.assertEqual(command["preferred"], expected)

    def test_suggests_stable_explicit_commands_for_core_routes(self):
        cases = [
            ("/api/health", "GET", "gh-ui health"),
            ("/api/download/progress", "GET", "gh-ui data progress"),
            ("/api/local/files", "GET", "gh-ui data files"),
            ("/api/config/paths", "GET", "gh-ui config get-paths"),
            ("/api/config/paths", "POST", "gh-ui config set-paths --db-path <DB_PATH>"),
            ("/api/logs", "GET", "gh-ui logs"),
            ("/api/export/excel", "POST", "gh-ui export excel --input @export.json"),
            ("/api/feedback", "POST", "gh-ui feedback submit --json @feedback.json"),
        ]

        for path, method, expected in cases:
            with self.subTest(path=path, method=method):
                command = build_route_command({"path": path, "methods": [method], "name": "core"}, method)
                self.assertEqual(command["preferred"], expected)

    def test_suggests_stable_explicit_commands_for_wechat_routes(self):
        cases = [
            ("/api/wechat/log", "POST", "gh-ui wechat log --message <MESSAGE>"),
            ("/api/wechat/config", "GET", "gh-ui wechat config-get"),
            ("/api/wechat/config", "POST", "gh-ui wechat config-set --json @wechat_config.json"),
            ("/api/wechat/macos/resign-wechat", "POST", "gh-ui wechat macos-resign"),
            ("/api/wechat/password/status", "GET", "gh-ui wechat password-status"),
            ("/api/wechat/password/auto", "POST", "gh-ui wechat password-auto"),
            ("/api/wechat/debug/inspect", "GET", "gh-ui wechat debug-inspect"),
            ("/api/wechat/sessions", "GET", "gh-ui wechat sessions"),
            ("/api/wechat/messages/search", "POST", "gh-ui wechat search --json @wechat_search.json"),
            ("/api/wechat/contacts/export", "GET", "gh-ui wechat contacts-export"),
            ("/api/wechat/messages/export", "POST", "gh-ui wechat messages-export --json @wechat_search.json"),
            ("/api/wechat/stock/review/export", "POST", "gh-ui wechat kline-review-export --json @kline_review.json"),
            ("/api/wechat/stock/screener/export", "POST", "gh-ui wechat stock-screener-export --json @stock_screener.json"),
            ("/api/wechat/image/extract-keys", "POST", "gh-ui wechat image-extract-keys"),
            ("/api/wechat/image/list", "GET", "gh-ui wechat image-list"),
            ("/api/wechat/llm/batch/stream", "POST", "gh-ui wechat llm-batch-stream --json @llm_batch.json"),
            ("/api/wechat/llm/export", "POST", "gh-ui wechat llm-export --json @llm_export.json"),
            ("/api/wechat/articles/login/qrcode", "GET", "gh-ui wechat articles-login-qrcode"),
            ("/api/wechat/articles/login/poll", "POST", "gh-ui wechat articles-login-poll --scan-id <SCAN_ID>"),
            ("/api/wechat/articles/login/logout", "POST", "gh-ui wechat articles-login-logout"),
            ("/api/wechat/articles/login/status", "GET", "gh-ui wechat articles-login-status"),
            ("/api/wechat/articles/settings", "POST", "gh-ui wechat articles-settings-set --json @article_settings.json"),
            ("/api/wechat/articles/analyses/{analysis_id}", "GET", "gh-ui wechat articles-analysis-get {analysis_id}"),
            (
                "/api/wechat/articles/analyses/{analysis_id}",
                "DELETE",
                "gh-ui wechat articles-analysis-delete {analysis_id}",
            ),
            ("/api/wechat/articles/open_html_dir", "POST", "gh-ui wechat articles-open-html-dir"),
            ("/api/wechat/articles/categories", "POST", "gh-ui wechat articles-category-create --name <NAME>"),
            (
                "/api/wechat/articles/categories/{category_id}",
                "PUT",
                "gh-ui wechat articles-category-rename {category_id} --name <NAME>",
            ),
            (
                "/api/wechat/articles/categories/{category_id}",
                "DELETE",
                "gh-ui wechat articles-category-delete {category_id}",
            ),
            (
                "/api/wechat/articles/accounts/{mp_id}/categories",
                "GET",
                "gh-ui wechat articles-account-categories {mp_id}",
            ),
            (
                "/api/wechat/articles/accounts/{mp_id}/categories",
                "POST",
                "gh-ui wechat articles-account-set-categories {mp_id} --category-id <CATEGORY_ID>",
            ),
            (
                "/api/wechat/articles/accounts/{mp_id}/favorite",
                "POST",
                "gh-ui wechat articles-account-favorite {mp_id} --favorite",
            ),
            (
                "/api/wechat/articles/accounts/add_by_url",
                "POST",
                "gh-ui wechat articles-account-add-by-url <ARTICLE_URL>",
            ),
            ("/api/wechat/articles/accounts/{mp_id}", "DELETE", "gh-ui wechat articles-account-delete {mp_id}"),
            ("/api/wechat/articles/accounts/dedupe", "POST", "gh-ui wechat articles-account-dedupe"),
            (
                "/api/wechat/articles/articles/{article_id}/fetch",
                "POST",
                "gh-ui wechat articles-fetch {article_id}",
            ),
            ("/api/wechat/articles/articles/{article_id}/html", "GET", "gh-ui wechat articles-html {article_id}"),
            (
                "/api/wechat/articles/sync_by_category",
                "POST",
                "gh-ui wechat articles-sync-by-category --json @sync_by_category.json",
            ),
            (
                "/api/wechat/articles/sync_by_category/status",
                "GET",
                "gh-ui wechat articles-sync-by-category-status",
            ),
            (
                "/api/wechat/articles/sync_by_category/purge_invalid",
                "POST",
                "gh-ui wechat articles-purge-invalid --category-id <CATEGORY_ID>",
            ),
            (
                "/api/wechat/articles/sync_by_category/preview",
                "GET",
                "gh-ui wechat articles-sync-by-category-preview --category-id <CATEGORY_ID> --mode <MODE>",
            ),
            ("/api/wechat/articles/_fixture/seed", "POST", "gh-ui wechat articles-fixture-seed --json @articles_fixture.json"),
        ]

        for path, method, expected in cases:
            with self.subTest(path=path, method=method):
                command = build_route_command({"path": path, "methods": [method], "name": "wechat"}, method)
                self.assertEqual(command["preferred"], expected)

    def test_audit_marks_every_route_callable(self):
        routes = [
            {"path": "/api/health", "methods": ["GET"], "name": "health"},
            {"path": "/api/backtest/run", "methods": ["POST"], "name": "run_backtest"},
            {"path": "/api/wechat/articles/accounts/{mp_id}", "methods": ["DELETE"], "name": "delete_account"},
        ]
        audit = audit_routes(routes)
        self.assertEqual(audit["total_operations"], 3)
        self.assertEqual(audit["callable_operations"], 3)
        self.assertEqual(audit["missing_operations"], [])
        self.assertEqual(audit["coverage_ratio"], 1.0)

    def test_backend_audit_includes_dynamic_data_capabilities(self):
        routes = [{"path": "/api/{module}/{method}", "methods": ["GET"], "name": "query_data"}]
        audit = audit_backend(
            routes,
            query_methods=[("stock", "stock_price"), ("fund", "fund_code")],
            download_methods=[("stock", "stock_price")],
            update_methods=[("stock", "stock_price")],
            factor_tables=["factor_info", "technical"],
        )

        self.assertEqual(audit["totals"]["route_operations"], 1)
        self.assertEqual(audit["totals"]["data_query_methods"], 2)
        self.assertEqual(audit["totals"]["data_download_methods"], 1)
        self.assertEqual(audit["totals"]["data_update_methods"], 1)
        self.assertEqual(audit["totals"]["factor_data_tables"], 2)
        self.assertTrue(audit["all_callables"])
        self.assertEqual(
            audit["data_capabilities"]["query"][0]["preferred"],
            "gh-ui data query fund fund_code",
        )

    def test_coverage_summary_includes_preferred_command_parse_audit(self):
        from gh_ui_cli.cli import _coverage_summary_from_audit

        audit = audit_backend(
            [{"path": "/api/wechat/sessions", "methods": ["GET"], "name": "sessions"}],
            query_methods=[],
            download_methods=[],
            update_methods=[],
            factor_tables=[],
        )

        summary = _coverage_summary_from_audit(audit)

        self.assertIn("preferred_command_parse", summary)
        self.assertTrue(summary["preferred_command_parse"]["all_parseable"])
        self.assertEqual(summary["preferred_command_parse"]["total"], 1)

    def test_routes_from_openapi_converts_schema_paths(self):
        schema = {
            "paths": {
                "/api/health": {"get": {"operationId": "health_api_health_get"}},
                "/api/items/{item_id}": {
                    "delete": {"operationId": "delete_item"},
                    "parameters": [{"name": "ignored"}],
                },
            }
        }

        routes = routes_from_openapi(schema)

        self.assertEqual(
            [{key: route[key] for key in ("path", "methods", "name")} for route in routes],
            [
                {"path": "/api/health", "methods": ["GET"], "name": "health_api_health_get"},
                {"path": "/api/items/{item_id}", "methods": ["DELETE"], "name": "delete_item"},
            ],
        )

    def test_routes_from_openapi_keeps_operation_parameter_metadata(self):
        schema = {
            "paths": {
                "/api/items/{item_id}": {
                    "get": {
                        "operationId": "read_item",
                        "parameters": [
                            {
                                "name": "item_id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "integer"},
                            },
                            {
                                "name": "limit",
                                "in": "query",
                                "required": False,
                                "schema": {"type": "integer", "default": 20},
                            },
                        ],
                    },
                    "post": {
                        "operationId": "update_item",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/UpdateItem"}
                                }
                            },
                        },
                    },
                },
            },
        }

        audit = audit_routes(routes_from_openapi(schema))
        operations = {operation["method"]: operation for operation in audit["operations"]}

        self.assertEqual(
            operations["GET"]["parameters"],
            [
                {
                    "name": "item_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "integer"},
                },
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "integer", "default": 20},
                },
            ],
        )
        self.assertEqual(operations["POST"]["request_body"]["required"], True)
        self.assertEqual(operations["POST"]["request_body"]["content_types"], ["application/json"])
        self.assertEqual(
            operations["POST"]["request_body"]["schema"],
            {"$ref": "#/components/schemas/UpdateItem"},
        )

    def test_enrich_routes_from_openapi_preserves_source_routes(self):
        routes = [
            {"path": "/api/items/{item_id}", "methods": ["GET", "POST"], "name": "item_route"},
            {"path": "/docs", "methods": ["GET"], "name": "swagger_ui_html"},
        ]
        schema = {
            "paths": {
                "/api/items/{item_id}": {
                    "get": {
                        "operationId": "read_item",
                        "parameters": [
                            {
                                "name": "item_id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "integer"},
                            }
                        ],
                    }
                }
            }
        }

        enriched = enrich_routes_from_openapi(routes, schema)
        audit = audit_routes(enriched)
        operations = {
            (operation["path"], operation["method"]): operation for operation in audit["operations"]
        }

        self.assertEqual(len(enriched), 2)
        self.assertEqual(operations[("/api/items/{item_id}", "GET")]["parameters"][0]["name"], "item_id")
        self.assertEqual(operations[("/api/items/{item_id}", "POST")]["parameters"], [])
        self.assertEqual(operations[("/docs", "GET")]["parameters"], [])

    def test_frontend_api_reference_audit_matches_ui_fetches_to_backend_routes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_root = Path(tmpdir)
            lib = source_root / "src" / "lib"
            lib.mkdir(parents=True)
            (lib / "wechat-api.ts").write_text(
                """
                const API_HOST = ''
                const WECHAT_API = `${API_HOST}/api/wechat`
                const ARTICLES_API = `${WECHAT_API}/articles`
                export async function search() {
                  return fetch(`${WECHAT_API}/messages/search`, { method: 'POST' })
                }
                export async function detail(article_id: string) {
                  return fetch(`${ARTICLES_API}/articles/${encodeURIComponent(article_id)}/fetch`, { method: 'POST' })
                }
                """,
                encoding="utf-8",
            )
            routes = [
                {"path": "/api/wechat/messages/search", "methods": ["POST"], "name": "search"},
                {
                    "path": "/api/wechat/articles/articles/{article_id}/fetch",
                    "methods": ["POST"],
                    "name": "fetch",
                },
            ]

            audit = audit_frontend_api_references(source_root, routes)

        self.assertEqual(audit["total_references"], 2)
        self.assertEqual(audit["missing_references"], [])
        self.assertEqual(audit["coverage_ratio"], 1.0)
        self.assertEqual(
            [item["path"] for item in audit["references"]],
            [
                "/api/wechat/articles/articles/{article_id}/fetch",
                "/api/wechat/messages/search",
            ],
        )

    def test_frontend_api_reference_audit_reports_unmatched_ui_fetches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_root = Path(tmpdir)
            lib = source_root / "src" / "lib"
            lib.mkdir(parents=True)
            (lib / "api.ts").write_text(
                """
                const API_HOST = ''
                const LOCAL_API = `${API_HOST}/api`
                export async function missing() {
                  return fetch(`${LOCAL_API}/missing/route`)
                }
                """,
                encoding="utf-8",
            )

            audit = audit_frontend_api_references(source_root, routes=[])

        self.assertEqual(audit["coverage_ratio"], 0.0)
        self.assertEqual(audit["missing_references"][0]["path"], "/api/missing/route")

    def test_frontend_api_reference_audit_skips_dynamic_remote_path_wrapper(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_root = Path(tmpdir)
            lib = source_root / "src" / "lib"
            lib.mkdir(parents=True)
            (lib / "api.ts").write_text(
                """
                const API_HOST = ''
                const LOCAL_API = `${API_HOST}/api`
                export async function requestRemote(path: string) {
                  return fetch(`${LOCAL_API}/remote${path}`)
                }
                """,
                encoding="utf-8",
            )

            audit = audit_frontend_api_references(source_root, routes=[])

        self.assertEqual(audit["references"], [])

    def test_frontend_api_reference_audit_expands_remote_request_helper_calls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_root = Path(tmpdir)
            lib = source_root / "src" / "lib"
            lib.mkdir(parents=True)
            (lib / "api.ts").write_text(
                """
                const API_HOST = ''
                const LOCAL_API = `${API_HOST}/api`
                async function remoteRequest<T>(path: string): Promise<T> {
                  return fetch(`${LOCAL_API}/remote${path}`)
                }
                export function getRemoteMe() {
                  return remoteRequest('/me')
                }
                export function listRemoteTokens() {
                  return remoteRequest('/tokens')
                }
                export function revokeRemoteToken(tokenId: number) {
                  return remoteRequest(`/tokens/${tokenId}`, { method: 'DELETE' })
                }
                """,
                encoding="utf-8",
            )
            routes = [
                {"path": "/api/remote/me", "methods": ["GET"], "name": "remote_me"},
                {"path": "/api/remote/tokens", "methods": ["GET", "POST"], "name": "remote_tokens"},
                {
                    "path": "/api/remote/tokens/{token_id}",
                    "methods": ["DELETE"],
                    "name": "remote_tokens_revoke",
                },
            ]

            audit = audit_frontend_api_references(source_root, routes)

        self.assertEqual(audit["missing_references"], [])
        self.assertEqual(
            [item["path"] for item in audit["references"]],
            [
                "/api/remote/me",
                "/api/remote/tokens",
                "/api/remote/tokens/{tokenId}",
            ],
        )

    def test_frontend_api_reference_audit_does_not_match_dynamic_data_wrapper_to_literal_auth_route(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_root = Path(tmpdir)
            lib = source_root / "src" / "lib"
            lib.mkdir(parents=True)
            (lib / "api.ts").write_text(
                """
                const API_HOST = ''
                const LOCAL_API = `${API_HOST}/api`
                export async function fetchData(module: string, method: string) {
                  return fetch(`${LOCAL_API}/${module}/${method}`)
                }
                """,
                encoding="utf-8",
            )

            audit = audit_frontend_api_references(
                source_root,
                routes=[{"path": "/api/auth/active-token", "methods": ["POST"], "name": "auth"}],
            )

        self.assertEqual(audit["missing_references"][0]["path"], "/api/{module}/{method}")


if __name__ == "__main__":
    unittest.main()
