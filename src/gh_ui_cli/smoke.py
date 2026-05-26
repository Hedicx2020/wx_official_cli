from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .profile import load_profile, public_profile, save_profile


def run_api_base_checks(client: Any, *, with_data_query: bool) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = [run_profile_check()]
    try:
        response = client.request("GET", "/health")
        health = response.data
        checks.append({"name": "api_base", "ok": health.get("status") == "ok", "health": health})
    except Exception as exc:
        checks.append({"name": "api_base", "ok": False, "error": str(exc), "type": type(exc).__name__})
        return checks

    if with_data_query:
        try:
            response = client.request("GET", "/stock/stock_code", params={"market": "ashare", "limit": 1})
            data = response.data or {}
            checks.append(
                {
                    "name": "data_query",
                    "ok": bool(data.get("total", 0) >= 1),
                    "total": data.get("total", 0),
                    "sample": data.get("data", [])[:1],
                }
            )
        except Exception as exc:
            checks.append({"name": "data_query", "ok": False, "error": str(exc), "type": type(exc).__name__})

    return checks


def run_profile_check() -> dict[str, Any]:
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            save_profile(
                {
                    "api_token": "profile-api-secret",
                    "access_token": "profile-access-secret",
                    "server": "secondary",
                    "username": "agent",
                },
                path=path,
            )
            profile = load_profile(path)
            public = public_profile(path)
            ok = (
                profile["api_token"] == "profile-api-secret"
                and profile["access_token"] == "profile-access-secret"
                and profile["server"] == "secondary"
                and public["has_api_token"]
                and public["has_access_token"]
                and "api_token" not in public
                and "access_token" not in public
            )
            return {
                "name": "agent_profile",
                "ok": ok,
                "has_api_token": bool(public["has_api_token"]),
                "has_access_token": bool(public["has_access_token"]),
            }
    except Exception as exc:
        return {"name": "agent_profile", "ok": False, "error": str(exc), "type": type(exc).__name__}


def build_smoke_report(
    checks: list[dict[str, Any]],
    *,
    platform_name: str,
    python_version: str,
) -> dict[str, Any]:
    failed = [str(check.get("name", "")) for check in checks if not check.get("ok")]
    return {
        "ok": not failed,
        "platform": platform_name,
        "python": python_version,
        "failed_checks": failed,
        "checks": checks,
    }
