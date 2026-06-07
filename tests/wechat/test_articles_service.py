"""公众号文章 service 集成测试。

每个测试用临时 GH_WX_DATA_DIR 隔离 ArticleStore。
"""

from __future__ import annotations

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gh_ui_cli.wechat.adapters.article_store import Article, MpAccount
from gh_ui_cli.wechat.adapters.local_articles import LocalArticle
from gh_ui_cli.wechat.errors import KeyNotFound, WechatDataMissing
from gh_ui_cli.wechat.services.articles import (
    store as store_mod,
    sync as sync_svc,
)


class _Env(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._patch = patch.dict("os.environ", {"GH_WX_DATA_DIR": self._tmp.name}, clear=False)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()


class SyncTest(_Env):
    def test_list_articles_empty(self):
        out = sync_svc.list_articles()
        self.assertEqual(out["total"], 0)

    def test_scan_from_wechat_cache_serializes_local_article_fields(self):
        scanned = [
            LocalArticle(
                url="https://mp.weixin.qq.com/s?__biz=biz_alpha&mid=1&idx=1",
                title="Alpha 扫描摘要",
                mp_name="Alpha 研究",
                published_at=1_765_000_000,
            )
        ]

        with patch("gh_ui_cli.wechat.services.keys.ensure_decrypted", return_value="/cache"):
            with patch("gh_ui_cli.wechat.services.articles.sync.scan_local", return_value=scanned):
                out = sync_svc.scan_from_wechat_cache()

        self.assertEqual(out["count"], 1)
        self.assertEqual(out["items"][0]["publisher"], "Alpha 研究")
        self.assertEqual(out["items"][0]["publish_ts"], 1_765_000_000)

    def test_open_html_dir_creates_path(self):
        # Don't actually launch the explorer in tests; patch subprocess.Popen
        with patch("subprocess.Popen") as popen:
            out = sync_svc.open_html_dir()
        self.assertEqual(out["status"], "ok")
        self.assertTrue(popen.called)

    def test_export_cached_by_account_scans_imports_and_writes_local_files(self):
        scanned = [
            LocalArticle(
                url="https://mp.weixin.qq.com/s?__biz=biz_alpha&mid=1&idx=1",
                title="Alpha 一季报点评",
                mp_name="Alpha 研究",
                summary="本地缓存摘要",
                published_at=1_765_000_000,
            ),
            LocalArticle(
                url="https://mp.weixin.qq.com/s?__biz=biz_beta&mid=2&idx=1",
                title="Beta 文章",
                mp_name="Beta 研究",
                published_at=1_765_000_100,
            ),
        ]
        out_dir = Path(self._tmp.name) / "exported"
        with patch("gh_ui_cli.wechat.services.keys.ensure_decrypted", return_value="/cache"):
            with patch("gh_ui_cli.wechat.services.articles.sync.scan_local", return_value=scanned):
                out = sync_svc.export_cached_by_account(
                    "Alpha 研究",
                    output_dir=str(out_dir),
                )

        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["account"]["name"], "Alpha 研究")
        self.assertEqual(out["article_count"], 1)
        self.assertEqual(out["scanned"], 2)
        self.assertTrue(Path(out["index_json"]).exists())
        payload = json.loads(Path(out["index_json"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["account"]["name"], "Alpha 研究")
        self.assertEqual(payload["articles"][0]["title"], "Alpha 一季报点评")
        self.assertEqual(len(out["html_files"]), 1)
        html = Path(out["html_files"][0]).read_text(encoding="utf-8")
        self.assertIn("Alpha 一季报点评", html)
        self.assertIn("https://mp.weixin.qq.com", html)

    def test_export_cached_by_account_writes_placeholder_for_cached_url(self):
        store = store_mod.get_store()
        store.upsert_mp(MpAccount(mp_id="biz_alpha", name="Alpha 研究"))
        store.upsert_articles([
            Article(
                id="alpha-1",
                mp_id="biz_alpha",
                title="Alpha 占位",
                url="https://mp.weixin.qq.com/s/alpha",
                published_at=1_765_000_000,
            )
        ])

        out = sync_svc.export_cached_by_account(
            "Alpha",
            output_dir=str(Path(self._tmp.name) / "placeholder"),
            scan_first=False,
        )

        html = Path(out["html_files"][0]).read_text(encoding="utf-8")
        self.assertIn("此文件来自本机微信缓存导出", html)
        self.assertIn("https://mp.weixin.qq.com/s/alpha", html)
        self.assertEqual(out["articles"][0]["html_source"], "placeholder")

    def test_export_cached_by_account_auto_gets_password_then_retries_decrypt(self):
        scanned = [
            LocalArticle(
                url="https://mp.weixin.qq.com/s?__biz=biz_alpha&mid=1&idx=1",
                title="Alpha 自动密钥",
                mp_name="Alpha 研究",
                published_at=1_765_000_000,
            )
        ]
        ensure_calls = []

        def ensure_decrypted():
            ensure_calls.append(1)
            if len(ensure_calls) == 1:
                raise KeyNotFound("尚未获取密钥")
            return "/cache"

        with patch("gh_ui_cli.wechat.services.keys.ensure_decrypted", side_effect=ensure_decrypted):
            with patch(
                "gh_ui_cli.wechat.services.keys.password_auto",
                return_value={"status": "ok", "key_count": 1, "wechat_files_path": "/wx/db_storage"},
            ) as password_auto:
                with patch("gh_ui_cli.wechat.services.articles.sync.scan_local", return_value=scanned):
                    out = sync_svc.export_cached_by_account(
                        "Alpha 研究",
                        output_dir=str(Path(self._tmp.name) / "auto"),
                    )

        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["article_count"], 1)
        self.assertEqual(out["password_auto"]["status"], "ok")
        self.assertEqual(len(ensure_calls), 2)
        self.assertEqual(password_auto.call_count, 1)

    def test_export_cached_by_account_can_disable_auto_password(self):
        with patch(
            "gh_ui_cli.wechat.services.keys.ensure_decrypted",
            side_effect=KeyNotFound("尚未获取密钥"),
        ):
            with patch("gh_ui_cli.wechat.services.keys.password_auto") as password_auto:
                with self.assertRaises(KeyNotFound):
                    sync_svc.export_cached_by_account(
                        "Alpha 研究",
                        output_dir=str(Path(self._tmp.name) / "no-auto"),
                        auto_password=False,
                    )
        self.assertEqual(password_auto.call_count, 0)

    def test_export_cached_by_account_can_use_existing_store_without_scan(self):
        store = store_mod.get_store()
        store.upsert_mp(MpAccount(mp_id="biz_alpha", name="Alpha 研究"))
        store.upsert_articles([
            Article(
                id="alpha-1",
                mp_id="biz_alpha",
                title="已有文章",
                url="https://mp.weixin.qq.com/s/alpha",
                published_at=1_765_000_000,
            )
        ])
        out = sync_svc.export_cached_by_account(
            "Alpha",
            output_dir=str(Path(self._tmp.name) / "existing"),
            scan_first=False,
        )
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["scanned"], 0)
        self.assertEqual(out["article_count"], 1)

    def test_export_cached_by_account_matches_name_ignoring_spaces(self):
        store = store_mod.get_store()
        store.upsert_mp(MpAccount(mp_id="biz_alpha", name="Alpha 研究"))
        store.upsert_articles([
            Article(
                id="alpha-space-1",
                mp_id="biz_alpha",
                title="空格名称匹配",
                url="https://mp.weixin.qq.com/s/alpha-space",
                published_at=1_765_000_000,
            )
        ])

        out = sync_svc.export_cached_by_account(
            "Alpha研究",
            output_dir=str(Path(self._tmp.name) / "normalized-name"),
            scan_first=False,
        )

        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["account"]["name"], "Alpha 研究")
        self.assertEqual(out["article_count"], 1)

    def test_verify_cache_export_reports_goal_requirements(self):
        html_file = Path(self._tmp.name) / "out" / "001.html"
        html_file.parent.mkdir()
        html_file.write_text("<html>正文</html>", encoding="utf-8")
        index_json = html_file.parent / "index.json"
        index_json.write_text(json.dumps({"article_count": 1, "articles": [{"title": "Alpha"}]}), encoding="utf-8")
        index_csv = html_file.parent / "index.csv"
        index_csv.write_text("title\nAlpha\n", encoding="utf-8-sig")
        export = {
            "status": "ok",
            "article_count": 1,
            "html_files": [str(html_file)],
            "index_json": str(index_json),
            "index_csv": str(index_csv),
            "output_dir": str(html_file.parent),
            "password_auto": {"status": "ok"},
        }
        status = {
            "platform": "windows",
            "detected_path": "C:/Users/me/Documents/WeChat Files/wxid/db_storage",
            "configured_path": "",
            "has_password": True,
            "key_count": 1,
            "wechat_process_running": True,
            "wechat_process_count": 1,
            "wechat_process_pids": [123],
        }
        with patch("gh_ui_cli.wechat.services.articles.sync.export_cached_by_account", return_value=export):
            with patch("gh_ui_cli.wechat.services.keys.password_status", return_value=status):
                out = sync_svc.verify_cache_export("Alpha 研究")
        self.assertTrue(out["ok"])
        self.assertTrue(out["requirements"]["wechat_path_detected"]["ok"])
        self.assertTrue(out["requirements"]["database_key_available"]["ok"])
        self.assertTrue(out["requirements"]["wechat_process_visible"]["ok"])
        self.assertTrue(out["requirements"]["articles_exported"]["ok"])
        self.assertTrue(out["requirements"]["html_files_written"]["ok"])
        self.assertTrue(out["requirements"]["index_files_written"]["ok"])
        self.assertEqual(out["requirements"]["index_files_written"]["index_article_count"], 1)
        self.assertEqual(out["mode"], "wechat_cache")
        self.assertEqual(out["current_platform"], "windows")
        self.assertTrue(out["goal_evidence"]["wechat_cache_verified"])
        self.assertEqual(out["goal_evidence"]["wechat_cache_account"], "Alpha 研究")

    def test_verify_cache_export_fails_when_index_json_is_missing(self):
        html_file = Path(self._tmp.name) / "out" / "001.html"
        html_file.parent.mkdir()
        html_file.write_text("<html>正文</html>", encoding="utf-8")
        export = {
            "status": "ok",
            "article_count": 1,
            "html_files": [str(html_file)],
            "index_json": str(html_file.parent / "missing-index.json"),
            "index_csv": str(html_file.parent / "index.csv"),
            "output_dir": str(html_file.parent),
            "password_auto": {"status": "ok"},
        }
        Path(export["index_csv"]).write_text("title\nAlpha\n", encoding="utf-8-sig")
        status = {
            "platform": "windows",
            "detected_path": "C:/Users/me/Documents/WeChat Files/wxid/db_storage",
            "configured_path": "",
            "has_password": True,
            "key_count": 1,
            "wechat_process_running": True,
            "wechat_process_count": 1,
            "wechat_process_pids": [123],
        }
        with patch("gh_ui_cli.wechat.services.articles.sync.export_cached_by_account", return_value=export):
            with patch("gh_ui_cli.wechat.services.keys.password_status", return_value=status):
                out = sync_svc.verify_cache_export("Alpha 研究")

        self.assertFalse(out["ok"])
        self.assertFalse(out["requirements"]["index_files_written"]["ok"])
        self.assertFalse(out["goal_evidence"]["wechat_cache_verified"])

    def test_verify_cache_export_fails_when_no_articles_exported(self):
        export = {
            "status": "ok",
            "article_count": 0,
            "html_files": [],
            "output_dir": str(Path(self._tmp.name) / "out"),
            "password_auto": {"status": "skipped"},
        }
        status = {
            "platform": "windows",
            "detected_path": "C:/Users/me/Documents/WeChat Files/wxid/db_storage",
            "configured_path": "",
            "has_password": True,
            "key_count": 1,
            "wechat_process_running": True,
            "wechat_process_count": 1,
            "wechat_process_pids": [123],
        }
        with patch("gh_ui_cli.wechat.services.articles.sync.export_cached_by_account", return_value=export):
            with patch("gh_ui_cli.wechat.services.keys.password_status", return_value=status):
                out = sync_svc.verify_cache_export("Alpha 研究")
        self.assertFalse(out["ok"])
        self.assertFalse(out["requirements"]["articles_exported"]["ok"])
        self.assertFalse(out["requirements"]["html_files_written"]["ok"])
        self.assertEqual(out["mode"], "wechat_cache")
        self.assertEqual(out["current_platform"], "windows")
        self.assertFalse(out["goal_evidence"]["wechat_cache_verified"])

    def test_verify_cache_export_fails_when_windows_wechat_process_is_not_visible(self):
        html_file = Path(self._tmp.name) / "out" / "001.html"
        html_file.parent.mkdir()
        html_file.write_text("<html>正文</html>", encoding="utf-8")
        index_json = html_file.parent / "index.json"
        index_json.write_text(json.dumps({"article_count": 1, "articles": [{"title": "Alpha"}]}), encoding="utf-8")
        index_csv = html_file.parent / "index.csv"
        index_csv.write_text("title\nAlpha\n", encoding="utf-8-sig")
        export = {
            "status": "ok",
            "article_count": 1,
            "html_files": [str(html_file)],
            "index_json": str(index_json),
            "index_csv": str(index_csv),
            "output_dir": str(html_file.parent),
            "password_auto": {"status": "skipped"},
        }
        status = {
            "platform": "windows",
            "detected_path": "C:/Users/me/Documents/WeChat Files/wxid/db_storage",
            "configured_path": "",
            "has_password": True,
            "key_count": 1,
            "wechat_process_running": False,
            "wechat_process_count": 0,
            "wechat_process_pids": [],
        }
        with patch("gh_ui_cli.wechat.services.articles.sync.export_cached_by_account", return_value=export):
            with patch("gh_ui_cli.wechat.services.keys.password_status", return_value=status):
                out = sync_svc.verify_cache_export("Alpha 研究")

        self.assertFalse(out["ok"])
        self.assertFalse(out["requirements"]["wechat_process_visible"]["ok"])
        self.assertFalse(out["goal_evidence"]["wechat_cache_verified"])
        self.assertIn("Weixin.exe", "\n".join(out["next_actions"]))

    def test_verify_cache_export_reports_export_error_instead_of_raising(self):
        status = {
            "platform": "windows",
            "detected_path": "",
            "configured_path": "",
            "has_password": False,
            "key_count": 0,
            "wechat_process_running": False,
            "wechat_process_count": 0,
            "wechat_process_pids": [],
        }
        err = WechatDataMissing(
            "自动获取微信数据库解密 key 失败",
            hint="确认 Weixin.exe 正在运行并已登录。",
        )
        with patch("gh_ui_cli.wechat.services.articles.sync.export_cached_by_account", side_effect=err):
            with patch("gh_ui_cli.wechat.services.keys.password_status", return_value=status):
                out = sync_svc.verify_cache_export("Alpha 研究")

        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "WX_DATA_MISSING")
        self.assertIn("解密 key", out["error"]["message"])
        self.assertFalse(out["requirements"]["wechat_path_detected"]["ok"])
        self.assertFalse(out["requirements"]["database_key_available"]["ok"])
        self.assertFalse(out["requirements"]["wechat_process_visible"]["ok"])
        self.assertFalse(out["requirements"]["articles_exported"]["ok"])
        self.assertFalse(out["requirements"]["html_files_written"]["ok"])
        self.assertEqual(out["mode"], "wechat_cache")
        self.assertEqual(out["current_platform"], "windows")
        self.assertFalse(out["goal_evidence"]["wechat_cache_verified"])
        next_actions = "\n".join(out["next_actions"])
        self.assertIn("Weixin.exe", next_actions)
        self.assertIn("WeChat.exe", next_actions)
        self.assertIn("wx-official-cli status", next_actions)
        self.assertIn("wx-official-cli verify", next_actions)
        self.assertIn("WECHAT_FILES_DIR", next_actions)
        self.assertNotIn("wechat password-auto", next_actions)
        self.assertNotIn("wechat config-set", next_actions)
        self.assertNotIn("articles-cache-export", next_actions)


if __name__ == "__main__":
    unittest.main()
