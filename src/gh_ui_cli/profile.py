from __future__ import annotations

import json
import os
from contextlib import suppress
from pathlib import Path
from typing import Any


PROFILE_ENV = "GH_UI_CLI_PROFILE"
API_TOKEN_ENV = "GH_API_TOKEN"
ACCESS_TOKEN_ENV = "GH_ACCESS_TOKEN"
SERVER_ENV = "GH_JYDB_SERVER"
SERVER_CHOICES = {"primary", "secondary"}
PROFILE_KEYS = ("api_token", "access_token", "server", "username")


def profile_path() -> Path:
    configured = os.environ.get(PROFILE_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".gh_ui_cli" / "profile.json"


def load_profile(path: Path | None = None) -> dict[str, str]:
    target = path or profile_path()
    if not target.exists():
        return _default_profile()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid gh-ui profile JSON: {target}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid gh-ui profile shape: {target}")
    return _normalize_profile(data)


def save_profile(profile: dict[str, Any], path: Path | None = None) -> dict[str, str]:
    target = path or profile_path()
    normalized = _normalize_profile(profile)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalized


def clear_profile(path: Path | None = None) -> None:
    target = path or profile_path()
    with suppress(FileNotFoundError):
        target.unlink()


def public_profile(path: Path | None = None) -> dict[str, Any]:
    target = path or profile_path()
    profile = load_profile(target)
    return {
        "path": str(target),
        "server": profile["server"],
        "username": profile["username"],
        "has_api_token": bool(profile["api_token"]),
        "has_access_token": bool(profile["access_token"]),
    }


def resolve_api_token(value: str | None) -> str:
    token = api_token_value(value)
    if not token:
        raise ValueError("--token, GH_API_TOKEN, or gh-ui profile set --api-token is required")
    return token


def resolve_access_token(value: str | None) -> str:
    token = access_token_value(value)
    if not token:
        raise ValueError("--access-token, GH_ACCESS_TOKEN, or gh-ui profile set --access-token is required")
    return token


def resolve_server(value: str | None) -> str:
    server = _first_non_empty(value, os.environ.get(SERVER_ENV))
    if not server:
        server = load_profile()["server"] or "primary"
    if server not in SERVER_CHOICES:
        raise ValueError(f"server must be one of: {', '.join(sorted(SERVER_CHOICES))}")
    return server


def api_token_value(value: str | None) -> str:
    token = _first_non_empty(value, os.environ.get(API_TOKEN_ENV))
    if token:
        return token
    return load_profile()["api_token"]


def access_token_value(value: str | None) -> str:
    token = _first_non_empty(value, os.environ.get(ACCESS_TOKEN_ENV))
    if token:
        return token
    return load_profile()["access_token"]


def _default_profile() -> dict[str, str]:
    return {
        "api_token": "",
        "access_token": "",
        "server": "primary",
        "username": "",
    }


def _normalize_profile(data: dict[str, Any]) -> dict[str, str]:
    profile = _default_profile()
    for key in PROFILE_KEYS:
        if key in data and data[key] is not None:
            profile[key] = str(data[key])
    if profile["server"] not in SERVER_CHOICES:
        raise ValueError(f"server must be one of: {', '.join(sorted(SERVER_CHOICES))}")
    return profile


def _first_non_empty(*values: str | None) -> str:
    for value in values:
        if value:
            return value
    return ""
