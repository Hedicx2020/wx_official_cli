"""公众号文章 service 集成测试。

每个测试用临时 GH_WX_DATA_DIR 隔离 ArticleStore。
"""

from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gh_ui_cli.wechat.adapters.article_store import MpAccount
from gh_ui_cli.wechat.errors import WechatInvalidInput, WechatDataMissing
from gh_ui_cli.wechat.services.articles import (
    accounts as accounts_svc,
    categories as categories_svc,
    login as login_svc,
    settings as settings_svc,
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


class SettingsTest(_Env):
    def test_defaults(self):
        s = settings_svc.load()
        self.assertTrue(s["platform_url"])
        self.assertFalse(s["auto_sync"])
        self.assertEqual(s["sync_interval_minutes"], 60)
        self.assertFalse(s["has_credentials"])

    def test_update_persists(self):
        s = settings_svc.update({"auto_sync": True, "sync_interval_minutes": 30})
        self.assertTrue(s["auto_sync"])
        self.assertEqual(s["sync_interval_minutes"], 30)
        # min clamp
        s2 = settings_svc.update({"sync_interval_minutes": 1})
        self.assertEqual(s2["sync_interval_minutes"], 5)


class CategoriesTest(_Env):
    def test_create_and_list(self):
        cat = categories_svc.create("研究")
        self.assertEqual(cat["name"], "研究")
        listed = categories_svc.list_all()
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["items"][0]["name"], "研究")

    def test_create_empty_name(self):
        with self.assertRaises(WechatInvalidInput):
            categories_svc.create("   ")

    def test_create_duplicate(self):
        categories_svc.create("研究")
        with self.assertRaises(WechatInvalidInput):
            categories_svc.create("研究")

    def test_rename(self):
        cat = categories_svc.create("研究")
        cid = cat["category_id"]
        categories_svc.rename(cid, "市场")
        names = [c["name"] for c in categories_svc.list_all()["items"]]
        self.assertIn("市场", names)

    def test_rename_missing(self):
        with self.assertRaises(WechatDataMissing):
            categories_svc.rename(999, "x")

    def test_delete(self):
        cat = categories_svc.create("研究")
        categories_svc.delete(cat["category_id"])
        self.assertEqual(categories_svc.list_all()["total"], 0)


class AccountsTest(_Env):
    def _add(self, mp_id="biz_a", name="A"):
        store_mod.get_store().upsert_mp(MpAccount(mp_id=mp_id, name=name))

    def test_list_empty(self):
        self.assertEqual(accounts_svc.list_all()["total"], 0)

    def test_list_filters_by_category(self):
        self._add("biz_a", "A")
        cat = categories_svc.create("研究")
        accounts_svc.set_categories("biz_a", [cat["category_id"]])
        listed = accounts_svc.list_all(category_id=cat["category_id"])
        self.assertEqual(listed["total"], 1)

    def test_set_favorite(self):
        self._add("biz_a", "A")
        out = accounts_svc.set_favorite("biz_a", True)
        self.assertTrue(out["is_favorite"])

    def test_get_categories_missing(self):
        with self.assertRaises(WechatDataMissing):
            accounts_svc.get_categories("non_existent")

    def test_delete(self):
        self._add("biz_a", "A")
        out = accounts_svc.delete("biz_a")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(accounts_svc.list_all()["total"], 0)


class LoginStatusTest(_Env):
    def test_status_when_no_credentials(self):
        out = login_svc.status()
        self.assertFalse(out["logged_in"])

    def test_logout_clears_credentials(self):
        out = login_svc.logout()
        self.assertEqual(out["status"], "ok")


class SyncTest(_Env):
    def test_list_articles_empty(self):
        out = sync_svc.list_articles()
        self.assertEqual(out["total"], 0)

    def test_open_html_dir_creates_path(self):
        # Don't actually launch the explorer in tests; patch subprocess.Popen
        with patch("subprocess.Popen") as popen:
            out = sync_svc.open_html_dir()
        self.assertEqual(out["status"], "ok")
        self.assertTrue(popen.called)


class CapabilitiesTest(_Env):
    def test_all_registered(self):
        from gh_ui_cli.wechat import registry
        ids = set(registry.list_ids())
        expected = {
            "op:wechat:articles-settings",
            "op:wechat:articles-settings-set",
            "op:wechat:articles-categories",
            "op:wechat:articles-categories-create",
            "op:wechat:articles-accounts",
            "op:wechat:articles-account-categories",
            "op:wechat:articles-account-favorite",
            "op:wechat:articles-account-delete",
            "op:wechat:articles-list",
            "op:wechat:articles-scan-local",
            "op:wechat:articles-login-status",
        }
        self.assertTrue(expected.issubset(ids), f"missing: {expected - ids}")


if __name__ == "__main__":
    unittest.main()
