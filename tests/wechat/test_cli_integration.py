"""端到端：通过 wx-official-cli 入口导出公众号缓存文章，验证 stdout JSON。"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gh_ui_cli import wx_official_cli
from gh_ui_cli.wechat.adapters.article_store import Article, MpAccount
from gh_ui_cli.wechat.services.articles import store as article_store_mod


class WechatCliIntegrationTest(unittest.TestCase):
    def _run(self, argv: list[str], env: dict[str, str]) -> tuple[int, str]:
        buf = io.StringIO()
        rc = 0
        with patch.dict("os.environ", env, clear=False):
            with redirect_stdout(buf):
                try:
                    wx_official_cli.main(argv)
                except SystemExit as e:
                    rc = int(e.code or 0)
        return rc, buf.getvalue()

    def test_articles_cache_export_command_writes_account_articles(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_WX_DATA_DIR": tmp}, clear=False):
                store = article_store_mod.get_store()
                store.upsert_mp(MpAccount(mp_id="biz_alpha", name="Alpha 研究"))
                store.upsert_articles([
                    Article(
                        id="alpha-1",
                        mp_id="biz_alpha",
                        title="Alpha 文章",
                        url="https://mp.weixin.qq.com/s/alpha",
                        published_at=1_765_000_000,
                    )
                ])
            output_dir = str(Path(tmp) / "cli-export")
            rc, out = self._run(
                [
                    "export",
                    "Alpha",
                    "--no-scan",
                    "--output-dir",
                    output_dir,
                ],
                {"GH_WX_DATA_DIR": tmp},
            )
            self.assertEqual(rc, 0, msg=out)
            data = json.loads(out)
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["account"]["name"], "Alpha 研究")
            self.assertEqual(data["article_count"], 1)
            self.assertTrue(Path(data["index_json"]).exists())

    def test_articles_cache_export_command_accepts_no_auto_password(self):
        with TemporaryDirectory() as tmp:
            with patch("gh_ui_cli.wechat.services.articles.sync.export_cached_by_account") as export:
                export.return_value = {"status": "ok", "account": {"name": "Alpha"}, "article_count": 0}
                rc, out = self._run(
                    [
                        "export",
                        "Alpha",
                        "--no-auto-password",
                    ],
                    {"GH_WX_DATA_DIR": tmp},
                )
        self.assertEqual(rc, 0, msg=out)
        export.assert_called_once()
        self.assertFalse(export.call_args.kwargs["auto_password"])

    def test_articles_cache_verify_strict_exits_nonzero_when_requirements_fail(self):
        with TemporaryDirectory() as tmp:
            with patch("gh_ui_cli.wechat.services.articles.sync.verify_cache_export") as verify:
                verify.return_value = {
                    "ok": False,
                    "requirements": {"articles_exported": {"ok": False}},
                }
                rc, out = self._run(
                    [
                        "verify",
                        "Alpha",
                        "--strict",
                    ],
                    {"GH_WX_DATA_DIR": tmp},
                )
        self.assertEqual(rc, 1, msg=out)
        data = json.loads(out)
        self.assertFalse(data["ok"])
        verify.assert_called_once()

    def test_articles_cache_verify_passes_options_to_service(self):
        with TemporaryDirectory() as tmp:
            with patch("gh_ui_cli.wechat.services.articles.sync.verify_cache_export") as verify:
                verify.return_value = {"ok": True, "requirements": {}}
                rc, out = self._run(
                    [
                        "verify",
                        "Alpha",
                        "--limit",
                        "5",
                        "--output-dir",
                        str(Path(tmp) / "verify"),
                        "--no-auto-password",
                    ],
                    {"GH_WX_DATA_DIR": tmp},
                )
        self.assertEqual(rc, 0, msg=out)
        kwargs = verify.call_args.kwargs
        self.assertEqual(kwargs["limit"], 5)
        self.assertFalse(kwargs["auto_password"])


if __name__ == "__main__":
    unittest.main()
