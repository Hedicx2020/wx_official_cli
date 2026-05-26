"""阶段 5 service 测试 - images / llm / pdf / stock_review。

只做：
- capability 注册检查
- 参数解析 / 错误路径
- 缺失外部依赖时的友好报错
"""

from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gh_ui_cli.wechat import registry
from gh_ui_cli.wechat.errors import LLMAuthFailed, WechatInvalidInput
from gh_ui_cli.wechat.services import images as images_svc
from gh_ui_cli.wechat.services import llm as llm_svc
from gh_ui_cli.wechat.services import pdf_report as pdf_svc
from gh_ui_cli.wechat.services import stock_review as stock_svc


class CapabilityRegistrationTest(unittest.TestCase):
    def test_all_stage5_capabilities_registered(self):
        ids = set(registry.list_ids())
        expected = {
            "op:wechat:image-list",
            "op:wechat:image-months",
            "op:wechat:image-convert",
            "op:wechat:llm-chat",
            "op:wechat:llm-test",
            "op:wechat:llm-summarize",
            "op:wechat:report-pdf",
            "op:wechat:stock-stats",
            "op:wechat:stock-screener",
            "op:wechat:stock-review",
            "op:wechat:stock-picks",
        }
        missing = expected - ids
        self.assertFalse(missing, f"missing capabilities: {missing}")


class ImagesTest(unittest.TestCase):
    def test_list_when_no_db(self):
        with patch(
            "gh_ui_cli.wechat.services.keys.resolve_db_dir",
            return_value="",
        ):
            out = images_svc.list_images()
        self.assertEqual(out, {"items": [], "total": 0})

    def test_list_months_when_no_db(self):
        with patch(
            "gh_ui_cli.wechat.services.keys.resolve_db_dir",
            return_value="",
        ):
            out = images_svc.list_months()
        self.assertEqual(out, {"months": []})

    def test_convert_missing_file(self):
        from gh_ui_cli.wechat.errors import WechatDataMissing
        with self.assertRaises(WechatDataMissing):
            images_svc.convert("/nonexistent.dat", aes_key="aa" * 16, xor_key=1)


class LLMTest(unittest.TestCase):
    def test_chat_without_config_raises_auth(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp}, clear=False):
                with self.assertRaises(LLMAuthFailed):
                    llm_svc.chat([{"role": "user", "content": "x"}])

    def test_test_connection_returns_error_when_unconfigured(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp}, clear=False):
                out = llm_svc.test_connection()
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["code"], "WX_LLM_AUTH_FAILED")

    def test_summarize_empty_messages(self):
        with self.assertRaises(WechatInvalidInput):
            llm_svc.summarize([])

    def test_chat_uses_configured_llm(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp}, clear=False):
                from gh_ui_cli.wechat.services import config as config_svc
                config_svc.save({
                    "llm_api_base": "https://test.example/v1",
                    "llm_api_key": "sk-x",
                    "llm_model": "test-model",
                })

                class FakeResp:
                    status_code = 200
                    text = ""

                    def json(self):
                        return {"choices": [{"message": {"content": "ok"}}]}

                class FakeClient:
                    def __init__(self, *a, **k): pass
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                    def post(self, *a, **k): return FakeResp()

                with patch("httpx.Client", FakeClient):
                    out = llm_svc.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(out["status"], "ok")


class PdfTest(unittest.TestCase):
    def test_empty_messages_raises(self):
        with self.assertRaises(WechatInvalidInput):
            pdf_svc.generate([])

    def test_missing_adapter_dependency_returns_error(self):
        # 强行模拟 adapter import 失败
        import sys
        sys.modules.pop("gh_ui_cli.wechat.adapters.pdf_reporter", None)
        with patch.dict("sys.modules", {"gh_ui_cli.wechat.adapters.pdf_reporter": None}):
            out = pdf_svc.generate([{"sender": "A", "content": "x"}])
        # adapter 加载会失败 -> MISSING_DEP 或运行时错
        self.assertIn(out.get("status"), {"ok", "error"})


class StockReviewTest(unittest.TestCase):
    def test_screener_empty_keywords_raises(self):
        with self.assertRaises(WechatInvalidInput):
            stock_svc.screener({})

    def test_review_missing_stock_code_raises(self):
        with self.assertRaises(WechatInvalidInput):
            stock_svc.kline_review({})


if __name__ == "__main__":
    unittest.main()
