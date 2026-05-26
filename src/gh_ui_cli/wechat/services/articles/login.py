"""微信读书登录 (扫码) - CLI 版本。

agent 不能扫码，但可以读 qr_url 然后用户用手机扫；之后用 scan_id poll 登录态。
"""

from __future__ import annotations

import time
from typing import Any

from ...adapters.weread_client import WereadClient, WereadCredentials, WereadError
from ...errors import WechatError
from ...registry import capability
from . import settings as settings_svc


def _client(creds: WereadCredentials | None = None) -> WereadClient:
    s = settings_svc.load_raw()
    return WereadClient(
        creds=creds,
        platform_url=s.get("platform_url") or "",
    )


def qrcode() -> dict[str, Any]:
    try:
        with _client() as c:
            qr = c.get_login_qrcode()
        return {
            "qr_url": qr.qr_url,
            "image_url": qr.image_url,
            "scan_id": qr.scan_id,
        }
    except WereadError as e:
        scan_id = f"local-{int(time.time())}"
        return {
            "qr_url": f"weread:offline:{scan_id}",
            "image_url": "",
            "scan_id": scan_id,
            "fallback": True,
            "error": str(e),
        }


def poll(scan_id: str) -> dict[str, Any]:
    try:
        with _client() as c:
            res = c.poll_login(scan_id)
    except WereadError as e:
        return {"status": "error", "message": str(e)}
    creds = WereadCredentials.from_dict(res.get("credentials") or {}) if res.get("status") == "ok" else None
    if creds:
        settings_svc.save_credentials(creds)
    return res


def logout() -> dict[str, Any]:
    settings_svc.save_credentials(None)
    return {"status": "ok"}


def status() -> dict[str, Any]:
    creds = settings_svc.load_credentials()
    return {
        "logged_in": bool(creds and creds.token),
        "has_token": bool(creds and creds.token),
    }


@capability("op:wechat:articles-login-qrcode")
def _cap_qrcode(_payload: dict) -> dict:
    return qrcode()


@capability("op:wechat:articles-login-poll")
def _cap_poll(payload: dict) -> dict:
    sid = str(payload.get("scan_id") or "")
    if not sid:
        raise WechatError("scan_id 缺失", code="WX_INVALID_INPUT")
    return poll(sid)


@capability("op:wechat:articles-login-logout")
def _cap_logout(_payload: dict) -> dict:
    return logout()


@capability("op:wechat:articles-login-status")
def _cap_status(_payload: dict) -> dict:
    return status()
