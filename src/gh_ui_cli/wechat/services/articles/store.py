"""ArticleStore 实例管理 + 公共辅助。

把 article_store.ArticleStore 包成单例工厂，挂在 paths.articles_root() 下。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ... import paths
from ...adapters.article_store import ArticleStore


def get_store() -> ArticleStore:
    return ArticleStore(paths.articles_root())


def to_jsonable(obj: Any) -> Any:
    from ...adapters.article_store import to_dict

    if hasattr(obj, "__dict__") or hasattr(obj, "_asdict"):
        try:
            return to_dict(obj)
        except Exception:
            pass
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj
