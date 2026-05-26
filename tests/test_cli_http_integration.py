import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]


class CliHttpIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _SidecarHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.api_base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def run_cli(self, *args):
        env = os.environ.copy()
        src_path = str(ROOT / "src")
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = src_path if not existing_pythonpath else os.pathsep.join([src_path, existing_pythonpath])
        result = subprocess.run(
            [sys.executable, "-m", "gh_ui_cli", "--api-base", self.api_base, *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(f"CLI failed with {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return json.loads(result.stdout)

    def test_api_base_manifest_invoke_and_smoke_work_against_mock_sidecar(self):
        data_manifest = self.run_cli("manifest", "--category", "data")
        self.assertEqual(data_manifest["total"], 3)
        self.assertEqual(
            sorted(entry["id"] for entry in data_manifest["entries"]),
            [
                "route:GET:/api/{module}/{method}",
                "route:POST:/api/download/{module}/{method}",
                "route:POST:/api/update/{module}/{method}",
            ],
        )

        health = self.run_cli("health")
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["db_path"], "/tmp/local_data")

        factor_manifest = self.run_cli("manifest", "--category", "factor_data")
        self.assertEqual(
            sorted(entry["id"] for entry in factor_manifest["entries"]),
            [
                "route:GET:/api/factor/db/query/{table}",
                "route:POST:/api/factor/db/download/{table}",
                "route:POST:/api/factor/db/update/{table}",
            ],
        )

        query = self.run_cli(
            "invoke",
            "route:GET:/api/{module}/{method}",
            "-p",
            "module=stock",
            "-p",
            "method=stock_code",
            "-p",
            "market=ashare",
            "-p",
            "limit=1",
        )
        self.assertEqual(query["data"][0]["stock_code"], "000001")

        factor_query = self.run_cli(
            "invoke",
            "route:GET:/api/factor/db/query/{table}",
            "-p",
            "table=factor_info",
            "-p",
            "limit=1",
        )
        self.assertEqual(factor_query["data"][0]["factor_id"], "demo_factor")

        factor_catalog = self.run_cli("factor", "catalog")
        self.assertEqual(factor_catalog["quality"]["basic"][0]["factor_id"], "demo_factor")

        ai_status = self.run_cli("ai", "status", "-p", "workspace=/tmp/report_reproduce")
        self.assertTrue(ai_status["workspace_exists"])
        self.assertEqual(ai_status["workspace"], "/tmp/report_reproduce")

        remote_me = self.run_cli("remote", "me", "--access-token", "access-token")
        self.assertEqual(remote_me["username"], "agent")
        self.assertEqual(remote_me["credits"], 1200)

        feedback = self.run_cli("feedback", "submit", "--content", "need cli", "--category", "suggestion")
        self.assertEqual(feedback["message"], "saved")

        backtest_ready = self.run_cli("backtest", "check-data")
        self.assertTrue(backtest_ready["ready"])
        self.assertEqual(backtest_ready["missing"], [])

        smoke = self.run_cli("smoke", "--with-data-query")
        self.assertTrue(smoke["ok"])
        self.assertEqual(smoke["failed_checks"], [])

        verify = self.run_cli("verify", "--with-data-query", "--strict")
        self.assertTrue(verify["ok"])
        self.assertFalse(verify["completion_ready"])
        self.assertTrue(verify["goal_evidence"]["route_operations_callable"])
        self.assertFalse(verify["goal_evidence"]["all_features_cli_callable"])
        self.assertEqual(verify["failed_checks"], [])


class _SidecarHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/openapi.json":
            self._write_json(_openapi_schema())
            return
        if parsed.path == "/api/health":
            self._write_json({"status": "ok", "db_path": "/tmp/local_data"})
            return
        if parsed.path == "/api/stock/stock_code":
            self._write_json(
                {
                    "data": [
                        {
                            "stock_name": "平安银行",
                            "stock_code": "000001",
                            "list_date": "1991-04-03",
                            "list_state": 1,
                        }
                    ],
                    "columns": ["stock_name", "stock_code", "list_date", "list_state"],
                    "total": 1,
                }
            )
            return
        if parsed.path == "/api/factor/db/query/factor_info":
            query = parse_qs(parsed.query)
            self._write_json(
                {
                    "data": [{"factor_id": "demo_factor", "limit": query.get("limit", [""])[0]}],
                    "columns": ["factor_id", "limit"],
                    "total": 1,
                }
            )
            return
        if parsed.path == "/api/factor/db/catalog":
            self._write_json(
                {
                    "quality": {
                        "basic": [
                            {
                                "factor_id": "demo_factor",
                                "factor_id_cn": "示例因子",
                            }
                        ]
                    }
                }
            )
            return
        if parsed.path == "/api/backtest/check-data":
            self._write_json(
                {
                    "ready": True,
                    "missing": [],
                    "files": {
                        "ashare_stock_price.parquet": {
                            "exists": True,
                            "rows": 10,
                            "size_mb": 1.0,
                        }
                    },
                }
            )
            return
        if parsed.path == "/api/ai/status":
            query = parse_qs(parsed.query)
            workspace = query.get("workspace", ["/tmp/report_reproduce"])[0]
            self._write_json(
                {
                    "workspace": workspace,
                    "output_path": f"{workspace}/output",
                    "workspace_exists": True,
                    "output_path_exists": True,
                    "reproduce_command_exists": True,
                    "claude_project_config_exists": False,
                    "builtin_backtest": True,
                    "builtin_subagents": True,
                    "runners": {},
                }
            )
            return
        if parsed.path == "/api/remote/me":
            if self.headers.get("authorization") != "Bearer access-token":
                self.send_error(401)
                return
            self._write_json(
                {
                    "id": 1,
                    "email": "agent@example.com",
                    "username": "agent",
                    "credits": 1200,
                    "roles": ["user"],
                }
            )
            return
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/feedback":
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if payload.get("content") != "need cli":
                self.send_error(400)
                return
            self._write_json({"message": "saved"})
            return
        self.send_error(404)

    def log_message(self, format, *args):
        return

    def _write_json(self, payload):
        content = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def _openapi_schema():
    return {
        "openapi": "3.1.0",
        "paths": {
            "/api/health": {"get": {"operationId": "health"}},
            "/api/{module}/{method}": {
                "get": {
                    "operationId": "query_data",
                    "parameters": [
                        {"name": "module", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "method", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "market", "in": "query", "required": False, "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}},
                    ],
                }
            },
            "/api/download/{module}/{method}": {
                "post": {
                    "operationId": "download_data",
                    "parameters": [
                        {"name": "module", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "method", "in": "path", "required": True, "schema": {"type": "string"}},
                    ],
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {}}}},
                }
            },
            "/api/update/{module}/{method}": {
                "post": {
                    "operationId": "update_data",
                    "parameters": [
                        {"name": "module", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "method", "in": "path", "required": True, "schema": {"type": "string"}},
                    ],
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {}}}},
                }
            },
            "/api/factor/db/query/{table}": {
                "get": {
                    "operationId": "query_factor",
                    "parameters": [
                        {"name": "table", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}},
                    ],
                }
            },
            "/api/factor/db/download/{table}": {
                "post": {
                    "operationId": "download_factor",
                    "parameters": [
                        {"name": "table", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "token", "in": "query", "required": True, "schema": {"type": "string"}},
                    ],
                }
            },
            "/api/factor/db/update/{table}": {
                "post": {
                    "operationId": "update_factor",
                    "parameters": [
                        {"name": "table", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "token", "in": "query", "required": True, "schema": {"type": "string"}},
                    ],
                }
            },
            "/api/factor/db/catalog": {"get": {"operationId": "factor_db_catalog"}},
            "/api/backtest/check-data": {"get": {"operationId": "check_data"}},
            "/api/ai/status": {
                "get": {
                    "operationId": "ai_status",
                    "parameters": [
                        {"name": "workspace", "in": "query", "required": False, "schema": {"type": "string"}},
                        {"name": "output_path", "in": "query", "required": False, "schema": {"type": "string"}},
                    ],
                }
            },
            "/api/remote/me": {
                "get": {
                    "operationId": "remote_me",
                    "parameters": [
                        {"name": "authorization", "in": "header", "required": True, "schema": {"type": "string"}},
                    ],
                }
            },
            "/api/feedback": {
                "post": {
                    "operationId": "submit_feedback",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {}}}},
                }
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
