"""/api/logs 本地实现。

进程内 ring buffer + 可选持久化到 ~/.gh_ui_cli/logs.jsonl。
"""

from __future__ import annotations

import json
import os
from collections import deque
from datetime import datetime
from typing import Any, Deque

from ..wechat.registry import capability
from . import paths


_BUFFER: Deque[dict[str, Any]] = deque(maxlen=2000)


def add_log(category: str, level: str, message: str) -> dict:
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "category": category or "system",
        "level": level or "info",
        "message": message,
    }
    _BUFFER.append(entry)
    if os.environ.get("GH_UI_PERSIST_LOGS", "").strip():
        try:
            paths.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            (paths.CONFIG_DIR / "logs.jsonl").open("a", encoding="utf-8").write(
                json.dumps(entry, ensure_ascii=False) + "\n"
            )
        except Exception:
            pass
    return entry


def get_logs(category: str = "", limit: int = 200) -> list[dict]:
    items = list(_BUFFER)
    if category:
        items = [l for l in items if l["category"] == category]
    return items[-int(limit):]


@capability("op:system:logs-get")
def _cap_get(payload: dict) -> list:
    return get_logs(
        category=str(payload.get("category") or ""),
        limit=min(int(payload.get("limit") or 200), 500),
    )


@capability("op:system:logs-add")
def _cap_add(payload: dict) -> dict:
    return add_log(
        category=str(payload.get("category") or "system"),
        level=str(payload.get("level") or "info"),
        message=str(payload.get("message") or ""),
    )
