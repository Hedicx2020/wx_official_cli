"""微信模块本地路径解析。

不依赖 gh_quant_ui 源码。优先级：
- 数据根目录：GH_WX_DATA_DIR > ~/.gh_ui_cli/wechat
- 本地行情数据：DB_PATH > ~/.gh_quant_ui/config.json:db_path > ~/local_data
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _default_root() -> Path:
    return Path.home() / ".gh_ui_cli" / "wechat"


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


def articles_db_path() -> Path:
    return articles_root() / "articles.db"


def images_cache_dir() -> Path:
    d = data_dir() / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def local_data_dir() -> Path:
    env = os.environ.get("DB_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    cfg = Path.home() / ".gh_quant_ui" / "config.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            db = str(data.get("db_path") or "").strip()
            if db:
                return Path(db).expanduser()
        except Exception:
            pass
    return Path.home() / "local_data"
