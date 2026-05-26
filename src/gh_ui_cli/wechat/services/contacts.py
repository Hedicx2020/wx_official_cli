"""通讯录 service - 扫描解密后的 contact*.db 输出去重后的联系人列表。

对应原 wechat.py：
  GET /api/wechat/contacts/export         -> export_contacts (原版返回 xlsx 文件)
  POST /api/wechat/messages/export        -> export_messages

为了 agent 友好，CLI 版优先返回 JSON 列表；如需 xlsx 由 CLI 层用 openpyxl 落盘。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..errors import WechatDataMissing
from ..registry import capability
from . import keys as keys_svc


SYSTEM_ACCOUNTS = {"filehelper", "newsapp", "fmessage", "medianote", "floatbottle", "weixin"}


def export() -> list[dict[str, str]]:
    cache_dir = keys_svc.ensure_decrypted()
    contact_dbs = sorted(Path(cache_dir).rglob("contact*.db"))
    if not contact_dbs:
        raise WechatDataMissing(
            "未找到解密后的 contact.db",
            hint="先确认密钥可用并运行 password-auto",
        )

    rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for db_path in contact_dbs:
        try:
            conn = sqlite3.connect(str(db_path))
        except Exception:
            continue
        try:
            try:
                cur = conn.execute(
                    "SELECT nick_name, remark, alias, username, local_type "
                    "FROM contact WHERE delete_flag = 0 AND username NOT LIKE 'gh_%' "
                    "ORDER BY local_type, remark, nick_name"
                )
            except sqlite3.OperationalError:
                continue
            for nick, remark, alias, username, ltype in cur.fetchall():
                uid = username or ""
                if uid in SYSTEM_ACCOUNTS or uid in seen_ids:
                    continue
                seen_ids.add(uid)
                if "@chatroom" in uid:
                    ctype = "群聊"
                elif ltype == 1:
                    ctype = "好友"
                else:
                    ctype = "其他"
                rows.append({
                    "nick_name": nick or "",
                    "remark": remark or "",
                    "alias": alias or "",
                    "username": uid,
                    "type": ctype,
                })
        finally:
            conn.close()
    return rows


@capability("op:wechat:contacts-export")
def _cap_contacts(_payload: dict) -> list[dict]:
    return export()
