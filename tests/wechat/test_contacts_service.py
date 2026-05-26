"""通讯录 service 测试 - 用临时 SQLite 模拟解密后的 contact.db。"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gh_ui_cli.wechat.services import contacts as contacts_svc
from gh_ui_cli.wechat import errors


def _seed_contact_db(path: Path, rows: list[tuple]):
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE contact ("
            "id INTEGER PRIMARY KEY, "
            "nick_name TEXT, remark TEXT, alias TEXT, username TEXT, "
            "local_type INTEGER, delete_flag INTEGER)"
        )
        conn.executemany(
            "INSERT INTO contact (nick_name, remark, alias, username, local_type, delete_flag) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


class ContactsExportTest(unittest.TestCase):
    def test_export_reads_friends_and_groups(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp)
            _seed_contact_db(cache / "contact.db", [
                ("Alice", "alice_remark", "", "wxid_alice", 1, 0),
                ("MyGroup", "", "", "group_abc@chatroom", 0, 0),
                ("System", "", "", "filehelper", 1, 0),
                ("Stranger", "", "", "wxid_b", 0, 0),
                ("Deleted", "", "", "wxid_c", 1, 1),
            ])
            with patch.object(contacts_svc.keys_svc, "ensure_decrypted", return_value=str(cache)):
                rows = contacts_svc.export()

        names = [r["nick_name"] for r in rows]
        self.assertIn("Alice", names)
        self.assertIn("MyGroup", names)
        self.assertNotIn("System", names)
        self.assertNotIn("Deleted", names)

        alice = next(r for r in rows if r["nick_name"] == "Alice")
        self.assertEqual(alice["type"], "好友")
        self.assertEqual(alice["username"], "wxid_alice")

        group = next(r for r in rows if r["nick_name"] == "MyGroup")
        self.assertEqual(group["type"], "群聊")

    def test_export_raises_when_no_contact_db(self):
        with TemporaryDirectory() as tmp:
            with patch.object(contacts_svc.keys_svc, "ensure_decrypted", return_value=tmp):
                with self.assertRaises(errors.WechatDataMissing):
                    contacts_svc.export()

    def test_export_dedupes_by_username(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp)
            _seed_contact_db(cache / "contact.db", [
                ("Alice", "", "", "wxid_alice", 1, 0),
                ("Alice2", "", "", "wxid_alice", 1, 0),  # same username
            ])
            with patch.object(contacts_svc.keys_svc, "ensure_decrypted", return_value=str(cache)):
                rows = contacts_svc.export()
        self.assertEqual(len([r for r in rows if r["username"] == "wxid_alice"]), 1)

    def test_capability_invokes_export(self):
        from gh_ui_cli.wechat.registry import invoke
        with TemporaryDirectory() as tmp:
            cache = Path(tmp)
            _seed_contact_db(cache / "contact.db", [
                ("Alice", "", "", "wxid_alice", 1, 0),
            ])
            with patch.object(contacts_svc.keys_svc, "ensure_decrypted", return_value=str(cache)):
                rows = invoke("op:wechat:contacts-export", {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["username"], "wxid_alice")


if __name__ == "__main__":
    unittest.main()
