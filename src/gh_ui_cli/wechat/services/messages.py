"""消息检索 service。

对应原 wechat.py 路由：
  GET  /api/wechat/sessions               -> list_sessions
  POST /api/wechat/messages/search        -> search_messages
  POST /api/wechat/messages/export        -> export_messages (返回 xlsx 字节)
  GET  /api/wechat/search/stats           -> search_stats
"""

from __future__ import annotations

from typing import Any

from ..registry import capability
from . import keys as keys_svc


def _ensure() -> str:
    return keys_svc.ensure_decrypted()


def sessions() -> list[dict]:
    from ..adapters import messages as msg_mod
    return msg_mod.list_sessions(_ensure())


def search(payload: dict) -> list[dict]:
    from ..adapters import messages as msg_mod
    cache_dir = _ensure()
    start = (payload.get("start_date") or "").strip()
    end = (payload.get("end_date") or "").strip()
    if not start or not end:
        raise ValueError("start_date 与 end_date 必填")
    msgs = msg_mod.search_messages(
        cache_dir,
        start_date=start,
        end_date=end,
        chat_name=(payload.get("chat_name") or "").strip(),
        sender_name=(payload.get("sender_name") or "").strip(),
        exclude_contacts=(payload.get("exclude_contacts") or "").strip(),
        keyword=(payload.get("keyword") or "").strip(),
        message_type=payload.get("message_type"),
        exclude_self=bool(payload.get("exclude_self")),
        dedup_day=bool(payload.get("dedup_day")),
        dedup_content_latest=bool(payload.get("dedup_content_latest")),
        dedup_content_earliest=bool(payload.get("dedup_content_earliest")),
        limit=max(1, min(int(payload.get("limit") or 5000), 20000)),
    )
    delete_csv = (payload.get("delete_keywords") or "").strip()
    if delete_csv:
        bans = [w.strip() for w in delete_csv.split(",") if w.strip()]
        msgs = [m for m in msgs if not any(w in (m.get("content") or "") for w in bans)]
    return msgs


def search_stats(payload: dict | None = None) -> dict:
    """返回最近一次解密缓存里 msg 数 / 表数 / 时间范围。"""
    import os
    import sqlite3

    cache_dir = _ensure()
    counts = {"db_files": 0, "msg_tables": 0, "approx_rows": 0}
    for root, _dirs, names in os.walk(cache_dir):
        for n in names:
            if not n.endswith(".db"):
                continue
            full = os.path.join(root, n)
            try:
                conn = sqlite3.connect(full)
            except sqlite3.DatabaseError:
                continue
            counts["db_files"] += 1
            try:
                tables = [
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
                    ).fetchall()
                ]
                counts["msg_tables"] += len(tables)
                for t in tables[:8]:
                    try:
                        n = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()
                        counts["approx_rows"] += int(n[0] or 0)
                    except sqlite3.OperationalError:
                        continue
            finally:
                conn.close()
    return counts


@capability("op:wechat:sessions")
def _cap_sessions(_payload: dict) -> list[dict]:
    return sessions()


@capability("op:wechat:messages-search")
def _cap_search(payload: dict) -> list[dict]:
    return search(payload)


@capability("op:wechat:search-stats")
def _cap_stats(payload: dict) -> dict:
    return search_stats(payload)
