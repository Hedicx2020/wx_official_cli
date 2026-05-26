from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gh_ui_cli.wechat import dispatch
from gh_ui_cli.wechat import registry


class DispatchTest(unittest.TestCase):
    def test_route_map_covers_config(self):
        rm = dispatch.route_map()
        self.assertEqual(rm.get("GET /api/wechat/config"), "op:wechat:config-get")
        self.assertEqual(rm.get("POST /api/wechat/config"), "op:wechat:config-set")

    def test_resolve_capability_returns_id(self):
        self.assertEqual(
            dispatch.resolve_capability("GET", "/api/wechat/config"),
            "op:wechat:config-get",
        )
        self.assertEqual(
            dispatch.resolve_capability("get", "/wechat/config"),
            "op:wechat:config-get",
        )
        self.assertIsNone(
            dispatch.resolve_capability("PATCH", "/api/wechat/config"),
        )

    def test_call_local_returns_response_for_config_get(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp}, clear=False):
                resp = dispatch.call_local("op:wechat:config-get", payload={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, "application/json")
        self.assertIsInstance(resp.data, dict)
        self.assertEqual(resp.data["llm_model"], "deepseek-chat")

    def test_call_local_returns_error_payload_on_wechat_error(self):
        @registry.capability("op:wechat:_test-error")
        def handler(_payload):
            from gh_ui_cli.wechat import errors
            raise errors.KeyNotFound(message="no key", hint="run x")

        try:
            resp = dispatch.call_local("op:wechat:_test-error", payload={})
            self.assertEqual(resp.status_code, 400)
            self.assertIsInstance(resp.data, dict)
            self.assertEqual(resp.data["ok"], False)
            self.assertEqual(resp.data["error"]["code"], "WX_KEY_NOT_FOUND")
        finally:
            registry._REGISTRY.pop("op:wechat:_test-error", None)

    def test_call_local_round_trips_config_save_then_get(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp}, clear=False):
                save_resp = dispatch.call_local(
                    "op:wechat:config-set",
                    payload={"default_keyword": "AI"},
                )
                self.assertEqual(save_resp.data["default_keyword"], "AI")
                get_resp = dispatch.call_local("op:wechat:config-get", payload={})
                self.assertEqual(get_resp.data["default_keyword"], "AI")


if __name__ == "__main__":
    unittest.main()
