"""公众号文章同步与本地扫描。

精简版：保留 list articles / fetch / scan_local / import_local 几个核心操作。
完整的 sync_by_category 流程依赖 WereadClient 真实 platform 调用，agent
环境多数情况下走 scan_local 即可。
"""

from __future__ import annotations

from typing import Any

from ...adapters.local_articles import import_to_store, scan_local
from ...registry import capability
from .store import get_store, to_jsonable


def list_articles(category_id: int | None = None,
                  mp_id: str | None = None,
                  limit: int = 100,
                  offset: int = 0) -> dict[str, Any]:
    store = get_store()
    if category_id is not None:
        items = store.list_articles_by_category(int(category_id), limit=int(limit), offset=int(offset))
    else:
        items = store.list_articles(mp_id=mp_id or None, limit=int(limit), offset=int(offset))
    return {"items": [to_jsonable(a) for a in items], "total": len(items)}


def scan_from_wechat_cache() -> dict[str, Any]:
    """从已解密的微信消息缓存中扫描公众号文章（不需要登录）。"""
    from .. import keys as keys_svc

    cache_dir = keys_svc.ensure_decrypted()
    found = scan_local(cache_dir)
    return {
        "count": len(found),
        "items": [
            {
                "url": a.url,
                "title": a.title,
                "publisher": a.publisher,
                "publish_ts": a.publish_ts,
            }
            for a in found[:200]
        ],
    }


def import_scanned() -> dict[str, Any]:
    """扫描 + 导入到本地 ArticleStore。"""
    from .. import keys as keys_svc

    cache_dir = keys_svc.ensure_decrypted()
    found = scan_local(cache_dir)
    stats = import_to_store(found, get_store())
    return {"scanned": len(found), **stats}


def open_html_dir() -> dict[str, Any]:
    import platform
    import subprocess

    from ... import paths

    p = paths.articles_html_dir()
    sys_name = platform.system()
    try:
        if sys_name == "Darwin":
            subprocess.Popen(["open", str(p)])
        elif sys_name == "Windows":
            subprocess.Popen(["explorer", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception as e:
        return {"status": "error", "message": str(e), "path": str(p)}
    return {"status": "ok", "path": str(p)}


@capability("op:wechat:articles-list")
def _cap_list(payload: dict) -> dict:
    return list_articles(
        category_id=payload.get("category_id"),
        mp_id=payload.get("mp_id"),
        limit=int(payload.get("limit") or 100),
        offset=int(payload.get("offset") or 0),
    )


@capability("op:wechat:articles-scan-local")
def _cap_scan(_payload: dict) -> dict:
    return scan_from_wechat_cache()


@capability("op:wechat:articles-sync-local")
def _cap_import(_payload: dict) -> dict:
    return import_scanned()


@capability("op:wechat:articles-open-html-dir")
def _cap_open_dir(_payload: dict) -> dict:
    return open_html_dir()
