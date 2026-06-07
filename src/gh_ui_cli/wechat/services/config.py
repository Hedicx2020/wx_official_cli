"""微信缓存导出配置读写。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .. import paths
from ..models import DEFAULT_CONFIG


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
