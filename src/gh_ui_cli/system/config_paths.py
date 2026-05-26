"""/api/config/paths 本地实现。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..wechat.errors import WechatInvalidInput
from ..wechat.registry import capability
from . import paths


def get_paths() -> dict[str, Any]:
    return {
        "db_path": paths.db_path(),
        "factor_path": paths.factor_path(),
        "export_path": paths.export_path(),
        "default_start_date": paths.default_start_date(),
    }


def set_paths(payload: dict) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    result: dict[str, Any] = {}

    for key, env_label in (("db_path", "数据"), ("factor_path", "因子"), ("export_path", "导出")):
        if key in payload and payload[key] is not None:
            new_path = str(payload[key]).strip()
            if not new_path:
                raise WechatInvalidInput(f"{env_label}路径不能为空")
            p = Path(new_path).expanduser()
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise WechatInvalidInput(f"无法创建{env_label}目录: {e}")
            patch[key] = str(p)
            result[key] = str(p)

    if "default_start_date" in payload and payload["default_start_date"] is not None:
        s = str(payload["default_start_date"]).strip()
        if not s:
            raise WechatInvalidInput("起始日期不能为空")
        try:
            datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            raise WechatInvalidInput(f"起始日期格式错误 (需 YYYY-MM-DD): {s}")
        patch["default_start_date"] = s
        result["default_start_date"] = s

    if patch:
        paths.save_config(patch)
    return result


@capability("op:system:config-paths-get")
def _cap_get(_payload: dict) -> dict:
    return get_paths()


@capability("op:system:config-paths-set")
def _cap_set(payload: dict) -> dict:
    return set_paths(payload or {})
