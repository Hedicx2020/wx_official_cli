from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from .source import RuntimeConfig, load_main_module


class ApiError(RuntimeError):
    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


@dataclass
class ApiResponse:
    data: Any | None = None
    content: bytes | None = None
    content_type: str = ""
    headers: dict[str, str] | None = None
    status_code: int = 200


class LocalApiClient:
    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.main_module = load_main_module(config)
        self.client = TestClient(self.main_module.app)

    @staticmethod
    def normalize_path(path: str, prefix: str = "/api") -> str:
        if not path:
            raise ValueError("empty API path")
        normalized = "/" + path.lstrip("/")
        if prefix and not normalized.startswith(prefix + "/") and normalized != prefix:
            normalized = prefix.rstrip("/") + normalized
        return normalized

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
        file_path: str | None = None,
        file_field: str = "file",
        prefix: str = "/api",
    ) -> ApiResponse:
        url = self.normalize_path(path, prefix=prefix)
        files = None
        handle = None
        try:
            if file_path:
                path_obj = Path(file_path).expanduser()
                handle = path_obj.open("rb")
                files = {file_field: (path_obj.name, handle)}
            response = self.client.request(
                method.upper(),
                url,
                params=params or None,
                json=json_body,
                headers=headers or None,
                files=files,
            )
        finally:
            if handle is not None:
                handle.close()

        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400:
            raise ApiError(response.status_code, self._error_detail(response, content_type))

        if "application/json" in content_type:
            return ApiResponse(
                data=response.json(),
                content_type=content_type,
                headers=dict(response.headers),
                status_code=response.status_code,
            )
        return ApiResponse(
            content=response.content,
            content_type=content_type,
            headers=dict(response.headers),
            status_code=response.status_code,
        )

    @staticmethod
    def _error_detail(response, content_type: str) -> Any:
        if "application/json" in content_type:
            try:
                payload = response.json()
                return payload.get("detail", payload) if isinstance(payload, dict) else payload
            except json.JSONDecodeError:
                return response.text
        return response.text


class HttpApiClient:
    def __init__(self, api_base: str):
        self.api_base = api_base.rstrip("/")
        self.client = httpx.Client(base_url=self.api_base, timeout=None)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
        file_path: str | None = None,
        file_field: str = "file",
        prefix: str = "/api",
    ) -> ApiResponse:
        url = LocalApiClient.normalize_path(path, prefix=prefix)
        files = None
        handle = None
        try:
            if file_path:
                path_obj = Path(file_path).expanduser()
                handle = path_obj.open("rb")
                files = {file_field: (path_obj.name, handle)}
            response = self.client.request(
                method.upper(),
                url,
                params=params or None,
                json=json_body,
                headers=headers or None,
                files=files,
            )
        finally:
            if handle is not None:
                handle.close()

        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400:
            raise ApiError(response.status_code, LocalApiClient._error_detail(response, content_type))

        if "application/json" in content_type:
            return ApiResponse(
                data=response.json(),
                content_type=content_type,
                headers=dict(response.headers),
                status_code=response.status_code,
            )
        return ApiResponse(
            content=response.content,
            content_type=content_type,
            headers=dict(response.headers),
            status_code=response.status_code,
        )


def create_api_client(config: RuntimeConfig) -> LocalApiClient | HttpApiClient:
    if config.api_base:
        return HttpApiClient(config.api_base)
    return LocalApiClient(config)
