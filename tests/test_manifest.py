import unittest

from gh_ui_cli.manifest import build_agent_manifest


class ManifestTest(unittest.TestCase):
    def test_builds_agent_friendly_entries_from_backend_audit(self):
        audit = {
            "openapi_components": {
                "schemas": {
                    "SearchRequest": {
                        "type": "object",
                        "properties": {"keyword": {"type": "string"}},
                    }
                }
            },
            "routes": {
                "operations": [
                    {
                        "path": "/api/health",
                        "method": "GET",
                        "name": "health",
                        "category": "health",
                        "preferred": "gh-ui health",
                        "generic": "gh-ui api request GET /api/health",
                        "requires_path_values": False,
                        "path_parameters": [],
                        "parameters": [
                            {
                                "name": "verbose",
                                "in": "query",
                                "required": False,
                                "schema": {"type": "boolean"},
                            }
                        ],
                        "request_body": {},
                    }
                ]
            },
            "data_capabilities": {
                "query": [
                    {
                        "module": "stock",
                        "method": "stock_price",
                        "action": "query",
                        "preferred": "gh-ui data query stock stock_price",
                        "generic": "gh-ui api request GET /api/stock/stock_price",
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

        manifest = build_agent_manifest(audit)

        self.assertGreaterEqual(manifest["total"], 5)
        self.assertEqual(manifest["entries"][0]["id"], "route:GET:/api/health")
        self.assertEqual(manifest["entries"][1]["id"], "data:query:stock/stock_price")
        self.assertEqual(manifest["entries"][2]["id"], "factor_data:query:factor_info")
        self.assertEqual(manifest["entries"][0]["parameters"][0]["name"], "verbose")
        self.assertFalse(manifest["entries"][0]["request_body_required"])
        self.assertEqual(manifest["entries"][0]["request_content_types"], [])
        self.assertEqual(manifest["entries"][0]["argv"], ["gh-ui", "health"])
        self.assertEqual(
            manifest["entries"][1]["argv"],
            ["gh-ui", "data", "query", "stock", "stock_price"],
        )
        self.assertEqual(
            manifest["entries"][1]["invoke_argv"],
            ["gh-ui", "invoke", "data:query:stock/stock_price"],
        )
        self.assertFalse(manifest["entries"][1]["requires_token"])

    def test_exposes_local_cli_operations_for_agents(self):
        manifest = build_agent_manifest(
            {"routes": {"operations": []}, "data_capabilities": {}, "factor_data_capabilities": []},
            category="cli",
            global_args=["--api-base", "http://127.0.0.1:8765"],
        )

        ids = {entry["id"]: entry for entry in manifest["entries"]}

        self.assertIn("cli:profile:get", ids)
        self.assertIn("cli:profile:set", ids)
        self.assertIn("cli:verify", ids)
        self.assertIn("cli:verify-plan", ids)
        self.assertIn("cli:verify-bundle", ids)
        self.assertIn("cli:ci-status", ids)
        self.assertIn("cli:ci-log-report", ids)
        self.assertIn("cli:runtime-verify", ids)
        self.assertIn("cli:verify-merge", ids)
        self.assertEqual(ids["cli:profile:get"]["kind"], "cli")
        self.assertEqual(
            ids["cli:profile:set"]["required_env"],
            ["GH_API_TOKEN", "GH_ACCESS_TOKEN"],
        )
        self.assertEqual(ids["cli:profile:set"]["invoke_argv"], [])
        self.assertEqual(
            ids["cli:verify-plan"]["argv"],
            [
                "gh-ui",
                "--api-base",
                "http://127.0.0.1:8765",
                "verify-plan",
            ],
        )
        self.assertIn("$env:GH_API_TOKEN", ids["cli:profile:set"]["command_shell"]["powershell"])
        self.assertIn("%GH_ACCESS_TOKEN%", ids["cli:profile:set"]["command_shell"]["cmd"])
        self.assertEqual(
            ids["cli:verify"]["argv"],
            [
                "gh-ui",
                "--api-base",
                "http://127.0.0.1:8765",
                "verify",
                "--with-data-query",
                "--windows-deps-preflight",
            ],
        )
        self.assertEqual(
            ids["cli:runtime-verify"]["argv"],
            [
                "gh-ui",
                "--api-base",
                "http://127.0.0.1:8765",
                "runtime-verify",
                "<VERIFY_JSON>",
            ],
        )

    def test_filters_manifest_by_category(self):
        audit = {
            "routes": {
                "operations": [
                    {
                        "path": "/api/{module}/{method}",
                        "method": "GET",
                        "name": "query_data",
                        "category": "data",
                        "preferred": "gh-ui invoke route:GET:/api/{module}/{method}",
                        "generic": "gh-ui api request GET /api/{module}/{method}",
                        "path_parameters": ["module", "method"],
                        "requires_path_values": True,
                    },
                    {
                        "path": "/api/update/{module}/{method}",
                        "method": "POST",
                        "name": "update_data",
                        "category": "data",
                        "preferred": "gh-ui invoke route:POST:/api/update/{module}/{method} --token $GH_API_TOKEN",
                        "generic": "gh-ui api request POST /api/update/{module}/{method}",
                        "path_parameters": ["module", "method"],
                        "requires_path_values": True,
                    },
                    {
                        "path": "/api/factor/db/update/{table}",
                        "method": "POST",
                        "name": "update_factor",
                        "category": "factor_data",
                        "preferred": "gh-ui invoke route:POST:/api/factor/db/update/{table} --token $GH_API_TOKEN",
                        "generic": "gh-ui api request POST /api/factor/db/update/{table}",
                        "path_parameters": ["table"],
                        "requires_path_values": True,
                    }
                ]
            },
            "data_capabilities": {
                "query": [{"module": "stock", "method": "stock_price", "action": "query", "preferred": "cmd"}],
                "download": [],
                "update": [],
            },
            "factor_data_capabilities": [],
        }

        manifest = build_agent_manifest(audit, category="data")

        self.assertEqual(manifest["total"], 3)
        self.assertEqual(manifest["entries"][0]["category"], "data")
        self.assertEqual(
            manifest["entries"][0]["invoke_argv"],
            ["gh-ui", "invoke", "route:GET:/api/{module}/{method}"],
        )
        self.assertEqual(
            manifest["entries"][1]["invoke_argv"],
            ["gh-ui", "invoke", "route:POST:/api/update/{module}/{method}", "--token", "<GH_API_TOKEN>"],
        )

        factor_manifest = build_agent_manifest(audit, category="factor_data")
        self.assertEqual(factor_manifest["total"], 1)
        self.assertEqual(
            factor_manifest["entries"][0]["invoke_argv"],
            ["gh-ui", "invoke", "route:POST:/api/factor/db/update/{table}", "--token", "<GH_API_TOKEN>"],
        )

    def test_adds_global_args_to_agent_argv(self):
        audit = {
            "routes": {
                "operations": [
                    {
                        "path": "/api/wechat/sessions",
                        "method": "GET",
                        "name": "list_sessions",
                        "category": "wechat",
                        "preferred": "gh-ui wechat request GET /sessions",
                        "generic": "gh-ui api request GET /api/wechat/sessions",
                    }
                ]
            },
            "data_capabilities": {"query": [], "download": [], "update": []},
            "factor_data_capabilities": [],
        }

        manifest = build_agent_manifest(
            audit,
            global_args=["--api-base", "http://127.0.0.1:8765"],
        )

        entry = manifest["entries"][0]
        self.assertEqual(
            entry["argv"],
            [
                "gh-ui",
                "--api-base",
                "http://127.0.0.1:8765",
                "wechat",
                "request",
                "GET",
                "/sessions",
            ],
        )
        self.assertEqual(
            entry["generic_argv"],
            [
                "gh-ui",
                "--api-base",
                "http://127.0.0.1:8765",
                "api",
                "request",
                "GET",
                "/api/wechat/sessions",
            ],
        )

    def test_token_commands_use_portable_placeholder_in_argv(self):
        audit = {
            "routes": {"operations": []},
            "data_capabilities": {
                "query": [],
                "download": [
                    {
                        "module": "stock",
                        "method": "stock_price",
                        "action": "download",
                        "preferred": "gh-ui data download stock stock_price --token $GH_API_TOKEN",
                        "generic": "gh-ui api request POST /api/download/stock/stock_price",
                    }
                ],
                "update": [],
            },
            "factor_data_capabilities": [],
        }

        manifest = build_agent_manifest(audit)

        entry = manifest["entries"][0]
        self.assertEqual(
            entry["argv"],
            ["gh-ui", "data", "download", "stock", "stock_price", "--token", "<GH_API_TOKEN>"],
        )
        self.assertEqual(
            entry["invoke_argv"],
            ["gh-ui", "invoke", "data:download:stock/stock_price", "--token", "<GH_API_TOKEN>"],
        )
        self.assertTrue(entry["requires_token"])

    def test_manifest_renders_access_token_placeholder_cross_platform(self):
        audit = {
            "routes": {
                "operations": [
                    {
                        "path": "/api/auth/active-token",
                        "method": "POST",
                        "name": "auth_active_token",
                        "category": "auth",
                        "preferred": "gh-ui auth active-token --access-token $GH_ACCESS_TOKEN",
                        "generic": "gh-ui api request POST /api/auth/active-token",
                    }
                ]
            },
            "data_capabilities": {"query": [], "download": [], "update": []},
            "factor_data_capabilities": [],
        }

        manifest = build_agent_manifest(audit)

        entry = manifest["entries"][0]
        self.assertEqual(
            entry["argv"],
            ["gh-ui", "auth", "active-token", "--access-token", "<GH_ACCESS_TOKEN>"],
        )
        self.assertEqual(
            entry["command_shell"]["powershell"],
            "gh-ui auth active-token --access-token $env:GH_ACCESS_TOKEN",
        )
        self.assertEqual(
            entry["command_shell"]["cmd"],
            "gh-ui auth active-token --access-token %GH_ACCESS_TOKEN%",
        )
        self.assertEqual(entry["required_env"], ["GH_ACCESS_TOKEN"])
        self.assertFalse(entry["requires_token"])
        self.assertTrue(entry["requires_access_token"])
        self.assertEqual(
            entry["invoke_argv"],
            [
                "gh-ui",
                "invoke",
                "route:POST:/api/auth/active-token",
                "--header",
                "Authorization=Bearer <GH_ACCESS_TOKEN>",
            ],
        )
        self.assertEqual(
            entry["invoke_shell"]["posix"],
            'gh-ui invoke route:POST:/api/auth/active-token --header "Authorization=Bearer $GH_ACCESS_TOKEN"',
        )
        self.assertEqual(
            entry["invoke_shell"]["powershell"],
            'gh-ui invoke route:POST:/api/auth/active-token --header "Authorization=Bearer $env:GH_ACCESS_TOKEN"',
        )
        self.assertEqual(
            entry["invoke_shell"]["cmd"],
            'gh-ui invoke route:POST:/api/auth/active-token --header "Authorization=Bearer %GH_ACCESS_TOKEN%"',
        )

    def test_manifest_exposes_cross_platform_shell_commands(self):
        audit = {
            "routes": {
                "operations": [
                    {
                        "path": "/api/update/{module}/{method}",
                        "method": "POST",
                        "name": "update_data",
                        "category": "data",
                        "preferred": "gh-ui invoke route:POST:/api/update/{module}/{method} --token $GH_API_TOKEN",
                        "generic": "gh-ui api request POST /api/update/{module}/{method}",
                        "path_parameters": ["module", "method"],
                        "requires_path_values": True,
                    }
                ]
            },
            "data_capabilities": {"query": [], "download": [], "update": []},
            "factor_data_capabilities": [],
        }

        manifest = build_agent_manifest(audit)

        entry = manifest["entries"][0]
        self.assertEqual(
            entry["invoke_shell"]["posix"],
            "gh-ui invoke 'route:POST:/api/update/{module}/{method}' --token $GH_API_TOKEN",
        )
        self.assertEqual(
            entry["invoke_shell"]["powershell"],
            "gh-ui invoke 'route:POST:/api/update/{module}/{method}' --token $env:GH_API_TOKEN",
        )
        self.assertEqual(
            entry["invoke_shell"]["cmd"],
            "gh-ui invoke route:POST:/api/update/{module}/{method} --token %GH_API_TOKEN%",
        )
        self.assertEqual(entry["required_env"], ["GH_API_TOKEN"])
        self.assertTrue(entry["requires_token"])
        self.assertFalse(entry["requires_access_token"])

    def test_factor_data_entries_expose_generic_fields_for_uniform_agent_schema(self):
        audit = {
            "routes": {"operations": []},
            "data_capabilities": {"query": [], "download": [], "update": []},
            "factor_data_capabilities": [
                {
                    "table": "factor_info",
                    "query": "gh-ui factor query factor_info",
                    "download": "gh-ui factor download factor_info --token $GH_API_TOKEN",
                    "update": "gh-ui factor update factor_info --token $GH_API_TOKEN",
                }
            ],
        }

        manifest = build_agent_manifest(audit, category="factor_data")

        entry = next(item for item in manifest["entries"] if item["id"] == "factor_data:query:factor_info")
        self.assertEqual(entry["generic"], entry["command"])
        self.assertEqual(entry["generic_argv"], entry["argv"])
        self.assertEqual(entry["generic_shell"], entry["command_shell"])

    def test_manifest_exposes_route_request_body_metadata(self):
        audit = {
            "openapi_components": {
                "schemas": {
                    "SearchRequest": {
                        "type": "object",
                        "properties": {"keyword": {"type": "string"}},
                    }
                }
            },
            "routes": {
                "operations": [
                    {
                        "path": "/api/wechat/messages/search",
                        "method": "POST",
                        "name": "search_messages",
                        "category": "wechat",
                        "preferred": "gh-ui wechat request POST /messages/search",
                        "generic": "gh-ui api request POST /api/wechat/messages/search",
                        "path_parameters": [],
                        "requires_path_values": False,
                        "parameters": [],
                        "request_body": {
                            "required": True,
                            "content_types": ["application/json"],
                            "schema": {"$ref": "#/components/schemas/SearchRequest"},
                        },
                    }
                ]
            },
            "data_capabilities": {"query": [], "download": [], "update": []},
            "factor_data_capabilities": [],
        }

        manifest = build_agent_manifest(audit)

        entry = manifest["entries"][0]
        self.assertTrue(entry["request_body_required"])
        self.assertEqual(entry["request_content_types"], ["application/json"])
        self.assertEqual(
            entry["request_body_schema"],
            {"$ref": "#/components/schemas/SearchRequest"},
        )
        self.assertEqual(
            manifest["openapi_components"]["schemas"]["SearchRequest"]["properties"]["keyword"],
            {"type": "string"},
        )

    def test_manifest_attaches_frontend_sources_to_matching_route_entries(self):
        audit = {
            "routes": {
                "operations": [
                    {
                        "path": "/api/wechat/messages/search",
                        "method": "POST",
                        "name": "search_messages",
                        "category": "wechat",
                        "preferred": "gh-ui wechat request POST /messages/search",
                        "generic": "gh-ui api request POST /api/wechat/messages/search",
                        "path_parameters": [],
                        "requires_path_values": False,
                    }
                ]
            },
            "data_capabilities": {"query": [], "download": [], "update": []},
            "factor_data_capabilities": [],
            "frontend_api_references": {
                "references": [
                    {
                        "path": "/api/wechat/messages/search",
                        "sources": [{"file": "src/lib/wechat-api.ts", "line": 172}],
                    }
                ]
            },
        }

        manifest = build_agent_manifest(audit, category="wechat")

        entry = manifest["entries"][0]
        self.assertEqual(entry["frontend_reference_paths"], ["/api/wechat/messages/search"])
        self.assertEqual(entry["frontend_reference_count"], 1)
        self.assertEqual(entry["frontend_sources"], [{"file": "src/lib/wechat-api.ts", "line": 172}])

    def test_manifest_does_not_attach_dynamic_data_source_to_literal_auth_route(self):
        audit = {
            "routes": {
                "operations": [
                    {
                        "path": "/api/auth/active-token",
                        "method": "POST",
                        "name": "auth_active_token",
                        "category": "auth",
                        "preferred": "gh-ui auth active-token --access-token $GH_ACCESS_TOKEN",
                        "generic": "gh-ui api request POST /api/auth/active-token",
                    }
                ]
            },
            "data_capabilities": {"query": [], "download": [], "update": []},
            "factor_data_capabilities": [],
            "frontend_api_references": {
                "references": [
                    {
                        "path": "/api/{module}/{method}",
                        "sources": [{"file": "src/lib/api.ts", "line": 96}],
                    },
                    {
                        "path": "/api/auth/active-token",
                        "sources": [{"file": "src/lib/api.ts", "line": 65}],
                    },
                ]
            },
        }

        manifest = build_agent_manifest(audit, category="auth")

        entry = manifest["entries"][0]
        self.assertEqual(entry["frontend_reference_paths"], ["/api/auth/active-token"])
        self.assertEqual(entry["frontend_sources"], [{"file": "src/lib/api.ts", "line": 65}])


if __name__ == "__main__":
    unittest.main()
