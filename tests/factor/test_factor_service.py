"""factor 模块测试。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from gh_ui_cli.factor import service as factor_svc
from gh_ui_cli.wechat import registry
from gh_ui_cli.wechat.errors import WechatDataMissing, WechatError, WechatInvalidInput


class FactorPathTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._env = patch.dict("os.environ", {"FACTOR_PATH": self._tmp.name}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_list_tables_empty(self):
        out = factor_svc.list_tables()
        self.assertTrue(any(t["table"] == "factor_info" for t in out) or out)
        for entry in out:
            self.assertIn("available", entry)

    def test_list_tables_reports_existing(self):
        (Path(self._tmp.name) / "factor_factor_info.parquet").touch()
        out = factor_svc.list_tables()
        fi = next(t for t in out if t["table"] == "factor_info")
        self.assertTrue(fi["available"])


class FactorQueryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._env = patch.dict("os.environ", {"FACTOR_PATH": self._tmp.name}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_query_factor_info(self):
        df = pd.DataFrame([
            {"factor_id": "PE", "factor_id_cn": "市盈率", "level1": "估值", "level2": "市盈率"},
            {"factor_id": "ROE", "factor_id_cn": "净资产收益率", "level1": "盈利", "level2": "ROE"},
        ])
        df.to_parquet(Path(self._tmp.name) / "factor_factor_info.parquet", index=False)
        out = factor_svc.query("factor_info", {})
        self.assertEqual(out["total"], 2)
        self.assertIn("factor_id", out["columns"])

    def test_query_factor_info_filter(self):
        df = pd.DataFrame([
            {"factor_id": "PE", "level1": "估值"},
            {"factor_id": "ROE", "level1": "盈利"},
        ])
        df.to_parquet(Path(self._tmp.name) / "factor_factor_info.parquet", index=False)
        out = factor_svc.query("factor_info", {"factor_id": "PE"})
        self.assertEqual(out["total"], 1)

    def test_query_missing_factor_info_raises(self):
        with self.assertRaises(WechatDataMissing):
            factor_svc.query("factor_info", {})

    def test_query_unknown_table_raises(self):
        with self.assertRaises(WechatInvalidInput):
            factor_svc.query("nope", {})

    def test_catalog_builds_tree(self):
        df = pd.DataFrame([
            {"factor_id": "PE", "factor_id_cn": "市盈率", "level1": "估值", "level2": "PE"},
            {"factor_id": "PB", "factor_id_cn": "市净率", "level1": "估值", "level2": "PB"},
            {"factor_id": "ROE", "factor_id_cn": "ROE", "level1": "盈利", "level2": "ROE"},
        ])
        df.to_parquet(Path(self._tmp.name) / "factor_factor_info.parquet", index=False)
        tree = factor_svc.catalog()
        self.assertIn("估值", tree)
        self.assertEqual(len(tree["估值"]), 2)

    def test_values_searches_factor_dirs(self):
        d = Path(self._tmp.name) / "factors" / "valuation"
        d.mkdir(parents=True)
        df = pd.DataFrame([
            {"trade_dt": "20240101", "stcode": "000001.SZ", "factor_value": 1.5},
            {"trade_dt": "20240201", "stcode": "000001.SZ", "factor_value": 1.8},
        ])
        df.to_parquet(d / "PE.parquet", index=False)
        out = factor_svc.values("PE")
        self.assertEqual(out["rows"], 2)


class FactorDownloadTest(unittest.TestCase):
    def test_download_requires_token(self):
        with self.assertRaises(WechatInvalidInput):
            factor_svc.download("analyst", token="")

    def test_databases_without_db_url_raises(self):
        with patch.dict("os.environ", {"GH_FACTOR_DB_URL": ""}, clear=False):
            with self.assertRaises(WechatError) as ctx:
                factor_svc.databases()
        self.assertEqual(ctx.exception.code, "FACTOR_DB_UNAVAILABLE")


class FactorCapabilitiesTest(unittest.TestCase):
    def test_registered(self):
        ids = set(registry.list_ids())
        expected = {
            "op:factor:tables",
            "op:factor:query",
            "op:factor:catalog",
            "op:factor:values",
            "op:factor:progress",
            "op:factor:download",
            "op:factor:databases",
        }
        self.assertTrue(expected.issubset(ids))


if __name__ == "__main__":
    unittest.main()
