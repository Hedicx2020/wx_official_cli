from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def run_runtime_verify(output_path: str | Path, *, command: list[str] | None = None) -> dict[str, Any]:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RuntimeVerifyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        api_base = f"http://127.0.0.1:{server.server_address[1]}"
        cli = command or [sys.executable, "-m", "gh_ui_cli"]
        subprocess.run(
            [
                *cli,
                "--api-base",
                api_base,
                "verify",
                "--with-data-query",
                "--strict",
                "--save",
                str(path),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(path.read_text(encoding="utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _RuntimeVerifyHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/openapi.json":
            self._write_json(_openapi_schema())
            return
        if path == "/api/health":
            self._write_json({"status": "ok", "db_path": "/tmp/local_data"})
            return
        if path == "/api/stock/stock_code":
            self._write_json(
                {
                    "data": [
                        {
                            "stock_name": "Ping An Bank",
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
        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _write_json(self, payload: dict[str, Any]) -> None:
        content = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def _openapi_schema() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "paths": {
            "/api/health": {"get": {"operationId": "health"}},
            "/api/{module}/{method}": {
                "get": {
                    "operationId": "query_data",
                    "parameters": [
                        {
                            "name": "module",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "method",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "market",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer"},
                        },
                    ],
                }
            },
        },
    }
