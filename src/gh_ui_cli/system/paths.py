"""gh_ui_cli 的全局路径与配置。

读写 ~/.gh_ui_cli/config.json，并兼容旧的 ~/.gh_quant_ui/config.json。
环境变量优先级最高：DB_PATH / FACTOR_PATH / GH_EXPORT_PATH。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


CONFIG_DIR = Path.home() / ".gh_ui_cli"
CONFIG_PATH = CONFIG_DIR / "config.json"
LEGACY_CONFIG_PATH = Path.home() / ".gh_quant_ui" / "config.json"

DEFAULTS = {
    "db_path": str(Path.home() / "local_data"),
    "factor_path": "",  # 空表示跟随 db_path
    "export_path": str(Path.home() / "Desktop"),
    "default_start_date": "2010-01-01",
}


def _read(p: Path) -> dict[str, Any]:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def load_config() -> dict[str, Any]:
    legacy = _read(LEGACY_CONFIG_PATH)
    current = _read(CONFIG_PATH)
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in legacy.items() if v})
    merged.update({k: v for k, v in current.items() if v})
    return merged


def save_config(patch: dict[str, Any]) -> dict[str, Any]:
    cur = load_config()
    for k, v in (patch or {}).items():
        if v is not None and k in DEFAULTS:
            cur[k] = v
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    return cur


def db_path() -> str:
    env = os.environ.get("DB_PATH", "").strip()
    if env:
        return env
    return load_config().get("db_path") or DEFAULTS["db_path"]


def factor_path() -> str:
    env = os.environ.get("FACTOR_PATH", "").strip()
    if env:
        return env
    fp = (load_config().get("factor_path") or "").strip()
    return fp or db_path()


def export_path() -> str:
    env = os.environ.get("GH_EXPORT_PATH", "").strip()
    if env:
        return env
    return load_config().get("export_path") or DEFAULTS["export_path"]


def default_start_date() -> str:
    return load_config().get("default_start_date") or DEFAULTS["default_start_date"]


def feedback_file() -> Path:
    return CONFIG_DIR / "feedback.jsonl"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
