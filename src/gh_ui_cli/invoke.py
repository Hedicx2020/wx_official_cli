from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from .profile import resolve_api_token, resolve_server


PATH_PARAM_RE = re.compile(r"\{([^}/]+)\}")


@dataclass(frozen=True)
class InvokeRequest:
    method: str
    path: str
    params: dict[str, Any]
    json_body: Any | None = None


def build_invoke_request(
    target_id: str,
    *,
    params: dict[str, Any],
    json_body: Any | None = None,
    token: str | None = None,
    server: str | None = None,
) -> InvokeRequest:
    kind, action, target = _parse_target_id(target_id)
    if kind == "route":
        path, remaining_params = _replace_path_params(target, params)
        if target.startswith("/api/download/{module}/{method}") or target.startswith("/api/update/{module}/{method}"):
            body = _body_dict(json_body)
            body.update(remaining_params)
            body["token"] = _require_token(token)
            body["server"] = resolve_server(server)
            return InvokeRequest(method=action, path=path, params={}, json_body=body)
        if target.startswith("/api/factor/db/download/{table}") or target.startswith("/api/factor/db/update/{table}"):
            return InvokeRequest(
                method=action,
                path=path,
                params={"token": _require_token(token), **remaining_params},
            )
        return InvokeRequest(method=action, path=path, params=remaining_params, json_body=json_body)

    if kind == "data":
        module, method_name = _parse_module_method(target)
        return _data_request(action, module, method_name, params, json_body, token, server)

    if kind == "factor_data":
        return _factor_data_request(action, target, params, token)

    raise ValueError(f"unsupported manifest id kind: {kind}")


def _parse_target_id(target_id: str) -> tuple[str, str, str]:
    parts = target_id.split(":", 2)
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"invalid manifest id: {target_id}")
    return parts[0], parts[1], parts[2]


def _parse_module_method(target: str) -> tuple[str, str]:
    if "/" not in target:
        raise ValueError(f"expected module/method target, got: {target}")
    module, method_name = target.split("/", 1)
    if not module or not method_name:
        raise ValueError(f"expected module/method target, got: {target}")
    return module, method_name


def _replace_path_params(path: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    remaining = dict(params)
    for name in PATH_PARAM_RE.findall(path):
        if name not in remaining:
            raise ValueError(f"missing path parameter: {name}")
        value = quote(str(remaining.pop(name)), safe="")
        path = path.replace("{" + name + "}", value)
    return path, remaining


def _data_request(
    action: str,
    module: str,
    method_name: str,
    params: dict[str, Any],
    json_body: Any | None,
    token: str | None,
    server: str | None,
) -> InvokeRequest:
    if action == "query":
        return InvokeRequest(method="GET", path=f"/{module}/{method_name}", params=dict(params))

    if action not in {"download", "update"}:
        raise ValueError(f"unsupported data action: {action}")

    body = _body_dict(json_body)
    body.update(params)
    body["token"] = _require_token(token)
    body["server"] = resolve_server(server)
    return InvokeRequest(method="POST", path=f"/{action}/{module}/{method_name}", params={}, json_body=body)


def _factor_data_request(
    action: str,
    table: str,
    params: dict[str, Any],
    token: str | None,
) -> InvokeRequest:
    if action == "query":
        return InvokeRequest(method="GET", path=f"/factor/db/query/{table}", params=dict(params))

    if action not in {"download", "update"}:
        raise ValueError(f"unsupported factor_data action: {action}")

    return InvokeRequest(
        method="POST",
        path=f"/factor/db/{action}/{table}",
        params={"token": _require_token(token), **dict(params)},
    )


def _require_token(token: str | None) -> str:
    try:
        return resolve_api_token(token)
    except ValueError as exc:
        raise ValueError("--token, GH_API_TOKEN, or gh-ui profile set --api-token is required for this manifest id") from exc


def _body_dict(json_body: Any | None) -> dict[str, Any]:
    if json_body is None:
        return {}
    if not isinstance(json_body, dict):
        raise ValueError("--json must be a JSON object for data download/update manifest ids")
    return dict(json_body)
