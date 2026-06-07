from __future__ import annotations

import unittest

from gh_ui_cli.wechat import errors


class WechatErrorsTest(unittest.TestCase):
    def test_base_error_has_required_fields(self):
        e = errors.WechatError(code="X", message="msg", hint="do x")
        self.assertEqual(e.code, "X")
        self.assertEqual(e.message, "msg")
        self.assertEqual(e.hint, "do x")
        self.assertEqual(str(e), "msg")

    def test_to_payload(self):
        e = errors.WechatError(code="X", message="msg", hint=None)
        self.assertEqual(
            e.to_payload(),
            {"ok": False, "error": {"code": "X", "message": "msg", "hint": None}},
        )

    def test_subclasses_carry_default_code(self):
        e = errors.KeyNotFound(message="no key")
        self.assertEqual(e.code, "WX_KEY_NOT_FOUND")

        e = errors.DecryptFailed(message="bad key")
        self.assertEqual(e.code, "WX_DECRYPT_FAILED")

        e = errors.PlatformUnsupported(message="linux")
        self.assertEqual(e.code, "WX_PLATFORM_UNSUPPORTED")

    def test_subclass_with_hint(self):
        e = errors.KeyNotFound(message="no key", hint="run wx-official-cli verify")
        self.assertEqual(e.hint, "run wx-official-cli verify")


if __name__ == "__main__":
    unittest.main()
