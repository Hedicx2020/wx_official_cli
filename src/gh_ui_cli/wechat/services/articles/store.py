"""ArticleStore 实例管理 + 公共辅助。

把 article_store.ArticleStore 包成单例工厂，挂在 paths.articles_root() 下。
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from ... import paths
from ...adapters.article_store import ArticleStore


def get_store() -> ArticleStore:
    return ArticleStore(paths.articles_root())


def to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj
