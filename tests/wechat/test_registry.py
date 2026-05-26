from __future__ import annotations

import unittest

from gh_ui_cli.wechat import registry


class RegistryTest(unittest.TestCase):
    def setUp(self):
        registry._REGISTRY.clear()

    def tearDown(self):
        registry._REGISTRY.clear()

    def test_register_and_lookup(self):
        @registry.capability("op:wechat:config-get")
        def handler(payload):
            return {"x": 1}

        self.assertIs(registry.get("op:wechat:config-get"), handler)

    def test_get_missing_returns_none(self):
        self.assertIsNone(registry.get("op:wechat:not-there"))

    def test_invoke_runs_registered_handler(self):
        @registry.capability("op:wechat:test")
        def handler(payload):
            return {"echo": payload}

        out = registry.invoke("op:wechat:test", {"a": 1})
        self.assertEqual(out, {"echo": {"a": 1}})

    def test_invoke_missing_raises(self):
        with self.assertRaises(KeyError):
            registry.invoke("op:wechat:nope", {})

    def test_list_ids(self):
        registry.capability("op:wechat:a")(lambda p: None)
        registry.capability("op:wechat:b")(lambda p: None)
        self.assertEqual(set(registry.list_ids()), {"op:wechat:a", "op:wechat:b"})


if __name__ == "__main__":
    unittest.main()
