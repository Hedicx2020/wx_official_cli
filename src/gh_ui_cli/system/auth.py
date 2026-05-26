"""/api/auth/* 本地实现 - 转发到 hedicxl.cn。"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..wechat.errors import WechatError, WechatInvalidInput
from ..wechat.registry import capability


GHWEB_BASE = "https://hedicxl.cn/api/v1"
VERIFY_URL = f"{GHWEB_BASE}/api-tokens/verify"


class AuthRemoteError(WechatError):
    default_code = "AUTH_REMOTE_ERROR"


def _post(url: str, body: dict, headers: dict | None = None, timeout: float = 15.0) -> Any:
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json=body, headers=headers or {})
    except Exception as e:
        raise AuthRemoteError(f"无法连接服务器: {e}")
    ctype = r.headers.get("content-type", "")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text) if "application/json" in ctype else r.text
        except Exception:
            detail = r.text
        raise AuthRemoteError(f"HTTP {r.status_code}: {detail}", code=f"AUTH_HTTP_{r.status_code}")
    return r.json() if "application/json" in ctype else r.text


def _get(url: str, headers: dict | None = None, timeout: float = 15.0) -> Any:
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url, headers=headers or {})
    except Exception as e:
        raise AuthRemoteError(f"无法连接服务器: {e}")
    ctype = r.headers.get("content-type", "")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text) if "application/json" in ctype else r.text
        except Exception:
            detail = r.text
        raise AuthRemoteError(f"HTTP {r.status_code}: {detail}", code=f"AUTH_HTTP_{r.status_code}")
    return r.json() if "application/json" in ctype else r.text


def verify(token: str) -> dict:
    if not token:
        raise WechatInvalidInput("token 必填")
    return _post(VERIFY_URL, {"token": token})


def login(username: str, password: str) -> dict:
    if not username or not password:
        raise WechatInvalidInput("username 与 password 必填")
    return _post(f"{GHWEB_BASE}/auth/login", {"username": username, "password": password}, timeout=10)


def register(payload: dict) -> dict:
    required = ("email", "username", "password", "invitation_code")
    for k in required:
        if not str(payload.get(k) or "").strip():
            raise WechatInvalidInput(f"{k} 必填")
    body = {k: str(payload.get(k, "")).strip() for k in required}
    body["password"] = str(payload["password"])  # 密码不 strip
    for opt in ("full_name", "company_name"):
        v = str(payload.get(opt) or "").strip()
        if v:
            body[opt] = v
    return _post(f"{GHWEB_BASE}/auth/register", body)


def active_token(access_token: str | None = None) -> dict:
    tok = access_token or os.environ.get("GH_ACCESS_TOKEN", "").strip()
    if not tok:
        raise WechatInvalidInput("缺少 access_token，可通过参数或 GH_ACCESS_TOKEN 提供")
    return _get(f"{GHWEB_BASE}/api-tokens/active-token", headers={"Authorization": f"Bearer {tok}"})


@capability("op:system:auth-verify")
def _cap_verify(payload: dict) -> dict:
    return verify(str(payload.get("token") or ""))


@capability("op:system:auth-login")
def _cap_login(payload: dict) -> dict:
    return login(str(payload.get("username") or ""), str(payload.get("password") or ""))


@capability("op:system:auth-register")
def _cap_register(payload: dict) -> dict:
    return register(payload or {})


@capability("op:system:auth-active-token")
def _cap_active_token(payload: dict) -> dict:
    return active_token(payload.get("access_token"))
