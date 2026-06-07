"""端到端：通过 cli 入口跑 wechat config-get / config-set，验证 stdout JSON。"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gh_ui_cli import cli
from gh_ui_cli.wechat.adapters.article_store import Article, MpAccount
from gh_ui_cli.wechat.services.articles import store as article_store_mod


class WechatCliIntegrationTest(unittest.TestCase):
    def _run(self, argv: list[str], env: dict[str, str]) -> tuple[int, str]:
        buf = io.StringIO()
        # 防止 cli 误以为 source mode 可用而尝试 import gh_quant_ui
        full_env = {"GH_UI_API_BASE": "", "GH_QUANT_UI_PATH": ""}
        full_env.update(env)
        rc = 0
        with patch.dict("os.environ", full_env, clear=False):
            with redirect_stdout(buf):
                try:
                    cli.main(argv)
                except SystemExit as e:
                    rc = int(e.code or 0)
        return rc, buf.getvalue()

    def test_config_get_returns_defaults(self):
        with TemporaryDirectory() as tmp:
            rc, out = self._run(
                ["wechat", "config-get"],
                {"GH_WX_DATA_DIR": tmp},
            )
        self.assertEqual(rc, 0, msg=out)
        data = json.loads(out)
        self.assertEqual(data["llm_model"], "deepseek-chat")
        self.assertEqual(data["default_keyword"], "")

    def test_config_set_persists_and_get_reads(self):
        with TemporaryDirectory() as tmp:
            patch_file = Path(tmp) / "patch.json"
            patch_file.write_text(json.dumps({"default_keyword": "AI"}), encoding="utf-8")
            rc, out = self._run(
                ["wechat", "config-set", "--json", f"@{patch_file}"],
                {"GH_WX_DATA_DIR": tmp},
            )
            self.assertEqual(rc, 0, msg=out)
            data = json.loads(out)
            self.assertEqual(data["default_keyword"], "AI")
            self.assertNotEqual(data["last_updated"], "")

            rc2, out2 = self._run(
                ["wechat", "config-get"],
                {"GH_WX_DATA_DIR": tmp},
            )
            self.assertEqual(rc2, 0, msg=out2)
            data2 = json.loads(out2)
            self.assertEqual(data2["default_keyword"], "AI")

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
                    "wechat",
                    "articles-cache-export",
                    "Alpha",
                    "--no-scan",
                    "--no-fetch-html",
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
                        "wechat",
                        "articles-cache-export",
                        "Alpha",
                        "--no-auto-password",
                        "--no-fetch-html",
                    ],
                    {"GH_WX_DATA_DIR": tmp},
                )
        self.assertEqual(rc, 0, msg=out)
        export.assert_called_once()
        self.assertFalse(export.call_args.kwargs["auto_password"])
        self.assertFalse(export.call_args.kwargs["fetch_html"])

    def test_articles_cache_verify_strict_exits_nonzero_when_requirements_fail(self):
        with TemporaryDirectory() as tmp:
            with patch("gh_ui_cli.wechat.services.articles.sync.verify_cache_export") as verify:
                verify.return_value = {
                    "ok": False,
                    "requirements": {"articles_exported": {"ok": False}},
                }
                rc, out = self._run(
                    [
                        "wechat",
                        "articles-cache-verify",
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
                        "wechat",
                        "articles-cache-verify",
                        "Alpha",
                        "--limit",
                        "5",
                        "--output-dir",
                        str(Path(tmp) / "verify"),
                        "--no-fetch-html",
                        "--no-auto-password",
                    ],
                    {"GH_WX_DATA_DIR": tmp},
                )
        self.assertEqual(rc, 0, msg=out)
        kwargs = verify.call_args.kwargs
        self.assertEqual(kwargs["limit"], 5)
        self.assertFalse(kwargs["fetch_html"])
        self.assertFalse(kwargs["auto_password"])


if __name__ == "__main__":
    unittest.main()
