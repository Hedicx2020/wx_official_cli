"""消息检索 service 测试。

为了避免真实微信进程依赖，全部用 fixture：
- 直接 monkeypatch keys_svc.ensure_decrypted 返回测试用 cache_dir
- monkeypatch adapters.messages.list_sessions / search_messages 返回固定 fixture
- 验证 service 层的参数解析、deletion 过滤、limit 边界
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from gh_ui_cli.wechat.services import messages as msg_svc


class SessionsTest(unittest.TestCase):
    def test_sessions_delegates_to_adapter(self):
        fake = [{"talker": "wxid_a", "display_name": "Alice"}]
        with patch.object(msg_svc.keys_svc, "ensure_decrypted", return_value="/cache"):
            with patch(
                "gh_ui_cli.wechat.adapters.messages.list_sessions", return_value=fake
            ) as ls:
                got = msg_svc.sessions()
                ls.assert_called_once_with("/cache")
        self.assertEqual(got, fake)


class SearchTest(unittest.TestCase):
    def _fake_search(self, *args, **kwargs):
        return [
            {"time": "2026-01-01", "sender": "Alice", "content": "hello world"},
            {"time": "2026-01-02", "sender": "Bob", "content": "delete this please"},
            {"time": "2026-01-03", "sender": "Alice", "content": "good morning"},
        ]

    def test_search_basic(self):
        payload = {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "keyword": "",
            "limit": 100,
        }
        with patch.object(msg_svc.keys_svc, "ensure_decrypted", return_value="/cache"):
            with patch(
                "gh_ui_cli.wechat.adapters.messages.search_messages",
                side_effect=self._fake_search,
            ):
                msgs = msg_svc.search(payload)
        self.assertEqual(len(msgs), 3)

    def test_search_applies_delete_keywords(self):
        payload = {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "delete_keywords": "delete,spam",
        }
        with patch.object(msg_svc.keys_svc, "ensure_decrypted", return_value="/cache"):
            with patch(
                "gh_ui_cli.wechat.adapters.messages.search_messages",
                side_effect=self._fake_search,
            ):
                msgs = msg_svc.search(payload)
        self.assertEqual(len(msgs), 2)
        self.assertNotIn("delete", msgs[1]["content"])

    def test_search_clamps_limit(self):
        payload = {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "limit": 999999,
        }
        captured = {}

        def fake_search(*args, **kwargs):
            captured["limit"] = kwargs.get("limit")
            return []

        with patch.object(msg_svc.keys_svc, "ensure_decrypted", return_value="/cache"):
            with patch(
                "gh_ui_cli.wechat.adapters.messages.search_messages",
                side_effect=fake_search,
            ):
                msg_svc.search(payload)
        self.assertEqual(captured["limit"], 20000)

    def test_search_requires_dates(self):
        with patch.object(msg_svc.keys_svc, "ensure_decrypted", return_value="/cache"):
            with self.assertRaises(ValueError):
                msg_svc.search({"start_date": "", "end_date": ""})

    def test_search_strips_string_fields(self):
        captured = {}

        def fake_search(*args, **kwargs):
            captured.update(kwargs)
            return []

        with patch.object(msg_svc.keys_svc, "ensure_decrypted", return_value="/cache"):
            with patch(
                "gh_ui_cli.wechat.adapters.messages.search_messages",
                side_effect=fake_search,
            ):
                msg_svc.search({
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-31",
                    "chat_name": "  alice ",
                    "sender_name": " Bob ",
                    "keyword": " kw ",
                })
        self.assertEqual(captured["chat_name"], "alice")
        self.assertEqual(captured["sender_name"], "Bob")
        self.assertEqual(captured["keyword"], "kw")


class CapabilityTest(unittest.TestCase):
    def test_sessions_capability(self):
        from gh_ui_cli.wechat.registry import invoke
        with patch.object(msg_svc.keys_svc, "ensure_decrypted", return_value="/c"):
            with patch(
                "gh_ui_cli.wechat.adapters.messages.list_sessions",
                return_value=[{"talker": "x"}],
            ):
                out = invoke("op:wechat:sessions", {})
        self.assertEqual(out, [{"talker": "x"}])

    def test_search_capability(self):
        from gh_ui_cli.wechat.registry import invoke
        with patch.object(msg_svc.keys_svc, "ensure_decrypted", return_value="/c"):
            with patch(
                "gh_ui_cli.wechat.adapters.messages.search_messages",
                return_value=[{"content": "y"}],
            ):
                out = invoke("op:wechat:messages-search", {
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-31",
                })
        self.assertEqual(out, [{"content": "y"}])


if __name__ == "__main__":
    unittest.main()
