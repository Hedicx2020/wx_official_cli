"""公众号分类 CRUD。"""

from __future__ import annotations

import sqlite3
from typing import Any

from ...errors import WechatInvalidInput, WechatDataMissing
from ...registry import capability
from .store import get_store, to_jsonable


def list_all() -> dict[str, Any]:
    items = [to_jsonable(c) for c in get_store().list_categories()]
    return {"items": items, "total": len(items)}


def create(name: str) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise WechatInvalidInput("分类名不能为空")
    try:
        cat = get_store().create_category(name)
    except sqlite3.IntegrityError as e:
        raise WechatInvalidInput(f"分类名已存在: {name}") from e
    return to_jsonable(cat)


def rename(category_id: int, name: str) -> dict[str, Any]:
    store = get_store()
    if store.get_category(category_id) is None:
        raise WechatDataMissing(f"category not found: {category_id}")
    try:
        store.rename_category(category_id, name)
    except sqlite3.IntegrityError as e:
        raise WechatInvalidInput(f"分类名已存在: {name}") from e
    return {"status": "ok"}


def delete(category_id: int) -> dict[str, Any]:
    get_store().delete_category(category_id)
    return {"status": "ok"}


@capability("op:wechat:articles-categories")
def _cap_list(_payload: dict) -> dict:
    return list_all()


@capability("op:wechat:articles-categories-create")
def _cap_create(payload: dict) -> dict:
    return create(str(payload.get("name") or ""))


@capability("op:wechat:articles-categories-rename")
def _cap_rename(payload: dict) -> dict:
    return rename(int(payload["category_id"]), str(payload.get("name") or ""))


@capability("op:wechat:articles-categories-delete")
def _cap_delete(payload: dict) -> dict:
    return delete(int(payload["category_id"]))
