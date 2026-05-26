"""hedicxl.cn 远程账户/Token 转发。

所有调用需要 access_token；优先从参数读取，缺失则从 profile / 环境变量回退。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..profile import load_profile
from ..wechat.errors import WechatError
from ..wechat.registry import capability


GHWEB_BASE = "https://hedicxl.cn/api/v1"


class RemoteAuthMissing(WechatError):
    default_code = "REMOTE_AUTH_MISSING"


class RemoteRequestFailed(WechatError):
    default_code = "REMOTE_REQUEST_FAILED"


def _resolve_access_token(payload: dict | None = None) -> str:
    if payload:
        for key in ("access_token", "access-token", "token"):
            v = payload.get(key)
            if v:
                return str(v)
    env = os.environ.get("GH_ACCESS_TOKEN", "").strip()
    if env:
        return env
    prof = load_profile()
    v = (prof.get("access_token") or "").strip()
    if v:
        return v
    raise RemoteAuthMissing(
        "缺少 access_token",
        hint="在调用时传 access_token 或 gh-ui profile set --access-token ...",
    )


def _request(method: str, path: str, *, access_token: str, json_body: Any | None = None) -> Any:
    headers = {"Authorization": f"Bearer {access_token}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    url = f"{GHWEB_BASE}{path}"
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.request(method.upper(), url, headers=headers, json=json_body)
    except Exception as e:
        raise RemoteRequestFailed(f"无法连接服务器: {e}")
    ctype = resp.headers.get("content-type", "")
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text) if "application/json" in ctype else resp.text
        except Exception:
            detail = resp.text
        raise RemoteRequestFailed(f"HTTP {resp.status_code}: {detail}", code=f"REMOTE_HTTP_{resp.status_code}")
    if "application/json" in ctype:
        return resp.json()
    return resp.text


def me(access_token: str | None = None) -> Any:
    return _request("GET", "/users/me", access_token=access_token or _resolve_access_token())


def tokens_list(access_token: str | None = None) -> Any:
    return _request("GET", "/api-tokens/list", access_token=access_token or _resolve_access_token())


def tokens_generate(name: str | None = None, access_token: str | None = None) -> Any:
    return _request(
        "POST",
        "/api-tokens/generate",
        access_token=access_token or _resolve_access_token(),
        json_body={"name": name},
    )


def tokens_revoke(token_id: int, access_token: str | None = None) -> Any:
    return _request(
        "DELETE",
        f"/api-tokens/{int(token_id)}",
        access_token=access_token or _resolve_access_token(),
    )


@capability("op:remote:me")
def _cap_me(payload: dict) -> Any:
    return me(payload.get("access_token") or _resolve_access_token(payload))


@capability("op:remote:tokens-list")
def _cap_list(payload: dict) -> Any:
    return tokens_list(payload.get("access_token") or _resolve_access_token(payload))


@capability("op:remote:tokens-generate")
def _cap_generate(payload: dict) -> Any:
    return tokens_generate(
        name=payload.get("name"),
        access_token=payload.get("access_token") or _resolve_access_token(payload),
    )


@capability("op:remote:tokens-revoke")
def _cap_revoke(payload: dict) -> Any:
    return tokens_revoke(
        token_id=int(payload["token_id"]),
        access_token=payload.get("access_token") or _resolve_access_token(payload),
    )
