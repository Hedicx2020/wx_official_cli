"""data 模块测试 - 用 pandas 临时 parquet。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from gh_ui_cli.data import download, parquet_map, query
from gh_ui_cli.wechat import registry
from gh_ui_cli.wechat.errors import WechatDataMissing, WechatError, WechatInvalidInput


class ParquetMapTest(unittest.TestCase):
    def test_known_modules(self):
        mods = parquet_map.known_modules()
        self.assertIn("stock", mods)
        self.assertIn("bond", mods)
        self.assertIn("trade", mods)

    def test_resolve_stock_price_forward(self):
        self.assertEqual(
            parquet_map.resolve_parquet_name("stock", "stock_price", {"adj_type": "forward"}),
            "ashare_stock_price_forward.parquet",
        )

    def test_resolve_stock_price_default(self):
        self.assertEqual(
            parquet_map.resolve_parquet_name("stock", "stock_price", {}),
            "ashare_stock_price.parquet",
        )

    def test_resolve_trade_date_by_market(self):
        self.assertEqual(
            parquet_map.resolve_parquet_name("trade", "trade_date", {"market": "hkshare"}),
            "hkshare_tradeday.parquet",
        )

    def test_resolve_unknown_returns_empty(self):
        self.assertEqual(parquet_map.resolve_parquet_name("nonexistent", "x", {}), "")


class QueryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._patch = patch.dict("os.environ", {"DB_PATH": self._tmp.name}, clear=False)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def _write_parquet(self, name: str, df: pd.DataFrame):
        df.to_parquet(Path(self._tmp.name) / name, index=False)

    def test_query_returns_filtered_rows(self):
        self._write_parquet(
            "ashare_stock.parquet",
            pd.DataFrame([
                {"stock_code": "000001", "name": "平安"},
                {"stock_code": "000002", "name": "万科"},
                {"stock_code": "600519", "name": "茅台"},
            ]),
        )
        out = query.query("stock", "stock_code", {"code": "000001,600519"})
        codes = [r["stock_code"] for r in out["data"]]
        self.assertCountEqual(codes, ["000001", "600519"])
        self.assertEqual(out["total"], 2)

    def test_query_applies_date_range(self):
        self._write_parquet(
            "ashare_stock_price_forward.parquet",
            pd.DataFrame([
                {"stock_code": "000001", "trade_date": "2024-01-01", "close": 10.0},
                {"stock_code": "000001", "trade_date": "2024-02-15", "close": 12.0},
                {"stock_code": "000001", "trade_date": "2024-03-01", "close": 11.5},
            ]),
        )
        out = query.query("stock", "stock_price", {
            "adj_type": "forward",
            "start_date": "2024-02-01",
            "end_date": "2024-02-28",
        })
        self.assertEqual(out["total"], 1)
        self.assertEqual(out["data"][0]["close"], 12.0)

    def test_query_limit(self):
        self._write_parquet(
            "fund_code.parquet",
            pd.DataFrame([{"code": f"F{i:03d}", "name": f"fund{i}"} for i in range(10)]),
        )
        out = query.query("fund", "fund_code", {}, limit=3)
        self.assertEqual(out["total"], 10)
        self.assertEqual(len(out["data"]), 3)

    def test_query_unknown_method_raises(self):
        with self.assertRaises(WechatInvalidInput):
            query.query("nope", "nada", {})

    def test_query_missing_file_raises(self):
        with self.assertRaises(WechatDataMissing):
            query.query("stock", "stock_code", {})

    def test_list_files_returns_meta(self):
        self._write_parquet("ashare_stock.parquet", pd.DataFrame([{"a": 1}]))
        out = query.list_files()
        names = [f["name"] for f in out]
        self.assertIn("ashare_stock.parquet", names)


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._env = patch.dict(
            "os.environ",
            {"DB_PATH": self._tmp.name, "GH_API_TOKEN": "", "GH_JYDB_SERVER": "primary"},
            clear=False,
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_download_without_token_raises(self):
        with patch("gh_ui_cli.remote.service.load_profile", return_value={"api_token": ""}):
            with self.assertRaises(WechatInvalidInput):
                download.download("stock", "stock_code", {})

    def test_download_without_jypy_raises(self):
        import importlib

        original = importlib.import_module

        def faulty_import(name, *args, **kwargs):
            if name.startswith("JyPy"):
                raise ImportError("no JyPy")
            return original(name, *args, **kwargs)

        with patch("importlib.import_module", side_effect=faulty_import):
            with self.assertRaises(WechatError) as ctx:
                download.download("stock", "stock_code", {"token": "t"})
        self.assertEqual(ctx.exception.code, "JYPY_MISSING")

    def test_unknown_module_raises(self):
        with self.assertRaises(WechatInvalidInput):
            download.download("nope", "nada", {"token": "t"})


class CapabilitiesTest(unittest.TestCase):
    def test_all_registered(self):
        ids = set(registry.list_ids())
        expected = {
            "op:data:query",
            "op:data:download",
            "op:data:update",
            "op:data:local-files",
            "op:data:progress",
        }
        missing = expected - ids
        self.assertFalse(missing, f"missing: {missing}")


if __name__ == "__main__":
    unittest.main()
