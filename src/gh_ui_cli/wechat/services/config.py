"""配置 CRUD：与原 wechat.py /config 端点 1:1 对应。

读写 ~/.gh_ui_cli/wechat/config.json （由 paths.config_path() 控制）。
不再读 ~/.gh_quant_ui/config.json，但 paths.local_data_dir() 仍兼容那一份。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .. import paths
from ..models import DEFAULT_CONFIG
from ..registry import capability


def load() -> dict[str, str]:
    p = paths.config_path()
    if not p.exists():
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update({k: str(v) for k, v in data.items() if k in DEFAULT_CONFIG})
    return merged


def save(patch: dict[str, Any]) -> dict[str, str]:
    cur = load()
    for k, v in patch.items():
        if k in DEFAULT_CONFIG and v is not None:
            cur[k] = str(v)
    cur["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    p = paths.config_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return cur


@capability("op:wechat:config-get")
def _cap_get(_payload: dict) -> dict:
    return load()


@capability("op:wechat:config-set")
def _cap_set(payload: dict) -> dict:
    return save(payload or {})
