"""wx_official_cli 本地路径解析。"""

from __future__ import annotations

import os
from pathlib import Path


def _default_root() -> Path:
    return Path.home() / ".wx_official_cli"


def data_dir() -> Path:
    env = os.environ.get("GH_WX_DATA_DIR", "").strip()
    base = Path(env).expanduser().resolve() if env else _default_root().resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    return data_dir() / "config.json"


def decrypt_cache_dir() -> Path:
    d = data_dir() / "decrypted"
    d.mkdir(parents=True, exist_ok=True)
    return d


def keys_path() -> Path:
    return data_dir() / "all_keys.json"


def articles_root() -> Path:
    d = data_dir() / "articles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def articles_html_dir() -> Path:
    d = articles_root() / "html"
    d.mkdir(parents=True, exist_ok=True)
    return d
