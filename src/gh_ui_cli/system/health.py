"""/api/health 本地实现。"""

from __future__ import annotations

from ..wechat.registry import capability
from . import paths


def health() -> dict:
    return {"status": "ok", "db_path": paths.db_path()}


@capability("op:system:health")
def _cap(_payload: dict) -> dict:
    return health()
