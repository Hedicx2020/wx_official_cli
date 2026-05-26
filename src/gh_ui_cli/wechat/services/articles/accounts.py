"""公众号账号 CRUD + 分类/收藏。"""

from __future__ import annotations

from typing import Any

from ...errors import WechatDataMissing
from ...registry import capability
from .store import get_store, to_jsonable


def list_all(category_id: int | None = None) -> dict[str, Any]:
    store = get_store()
    if category_id is not None:
        rows = store.list_mps_by_category(int(category_id))
    else:
        rows = store.list_mps()
    items = [to_jsonable(a) for a in rows]
    return {"items": items, "total": len(items)}


def get_categories(mp_id: str) -> dict[str, Any]:
    store = get_store()
    if store.get_mp(mp_id) is None:
        raise WechatDataMissing(f"account not found: {mp_id}")
    return {"category_ids": store.get_account_categories(mp_id)}


def set_categories(mp_id: str, category_ids: list[int]) -> dict[str, Any]:
    store = get_store()
    if store.get_mp(mp_id) is None:
        raise WechatDataMissing(f"account not found: {mp_id}")
    store.set_account_categories(mp_id, [int(c) for c in category_ids])
    return {"status": "ok", "mp_id": mp_id, "category_ids": list(category_ids)}


def set_favorite(mp_id: str, is_favorite: bool) -> dict[str, Any]:
    store = get_store()
    if store.get_mp(mp_id) is None:
        raise WechatDataMissing(f"account not found: {mp_id}")
    store.set_favorite(mp_id, bool(is_favorite))
    return {"status": "ok", "mp_id": mp_id, "is_favorite": bool(is_favorite)}


def delete(mp_id: str) -> dict[str, Any]:
    deleted = get_store().delete_mp(mp_id)
    return {"status": "ok", "mp_id": mp_id, "deleted_articles": deleted}


def dedupe() -> dict[str, Any]:
    return get_store().merge_duplicate_accounts()


@capability("op:wechat:articles-accounts")
def _cap_list(payload: dict) -> dict:
    cid = payload.get("category_id")
    return list_all(int(cid) if cid is not None else None)


@capability("op:wechat:articles-account-categories")
def _cap_get_cats(payload: dict) -> dict:
    return get_categories(str(payload["mp_id"]))


@capability("op:wechat:articles-account-set-categories")
def _cap_set_cats(payload: dict) -> dict:
    return set_categories(str(payload["mp_id"]), list(payload.get("category_ids") or []))


@capability("op:wechat:articles-account-favorite")
def _cap_favorite(payload: dict) -> dict:
    return set_favorite(str(payload["mp_id"]), bool(payload.get("is_favorite")))


@capability("op:wechat:articles-account-delete")
def _cap_delete(payload: dict) -> dict:
    return delete(str(payload["mp_id"]))


@capability("op:wechat:articles-accounts-dedupe")
def _cap_dedupe(_payload: dict) -> dict:
    return dedupe()
