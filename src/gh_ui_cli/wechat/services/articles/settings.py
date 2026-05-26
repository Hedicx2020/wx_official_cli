"""公众号模块设置：platform_url / auto_sync / 凭据。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ... import paths
from ...adapters.weread_client import DEFAULT_PLATFORM_URL, WereadCredentials
from ...registry import capability


_DEFAULT = {
    "platform_url": DEFAULT_PLATFORM_URL,
    "auto_sync": False,
    "sync_interval_minutes": 60,
    "credentials": None,
}


def _path() -> Path:
    return paths.articles_root() / "settings.json"


def load_raw() -> dict[str, Any]:
    p = _path()
    if not p.exists():
        return dict(_DEFAULT)
    try:
        out = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return dict(_DEFAULT)
    merged = dict(_DEFAULT)
    merged.update({k: out.get(k, _DEFAULT.get(k)) for k in _DEFAULT})
    return merged


def save_raw(s: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def load() -> dict[str, Any]:
    s = load_raw()
    return {
        "platform_url": s.get("platform_url") or DEFAULT_PLATFORM_URL,
        "auto_sync": bool(s.get("auto_sync")),
        "sync_interval_minutes": int(s.get("sync_interval_minutes") or 60),
        "default_platform_url": DEFAULT_PLATFORM_URL,
        "has_credentials": bool(s.get("credentials")),
    }


def update(patch: dict) -> dict[str, Any]:
    s = load_raw()
    if "platform_url" in patch and patch["platform_url"] is not None:
        s["platform_url"] = (str(patch["platform_url"]).strip() or DEFAULT_PLATFORM_URL)
    if "auto_sync" in patch and patch["auto_sync"] is not None:
        s["auto_sync"] = bool(patch["auto_sync"])
    if "sync_interval_minutes" in patch and patch["sync_interval_minutes"] is not None:
        s["sync_interval_minutes"] = max(5, int(patch["sync_interval_minutes"]))
    save_raw(s)
    return load()


def load_credentials() -> WereadCredentials | None:
    return WereadCredentials.from_dict(load_raw().get("credentials"))


def save_credentials(creds: WereadCredentials | None) -> None:
    s = load_raw()
    s["credentials"] = creds.to_dict() if creds else None
    save_raw(s)


@capability("op:wechat:articles-settings")
def _cap_get(_payload: dict) -> dict:
    return load()


@capability("op:wechat:articles-settings-set")
def _cap_set(payload: dict) -> dict:
    return update(payload or {})
