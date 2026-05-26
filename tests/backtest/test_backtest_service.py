"""backtest 模块测试。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from gh_ui_cli.backtest import service as bt_svc
from gh_ui_cli.wechat import registry
from gh_ui_cli.wechat.errors import WechatDataMissing, WechatError, WechatInvalidInput


class CheckDataTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._env = patch.dict("os.environ", {"DB_PATH": self._tmp.name}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_check_data_reports_missing(self):
        out = bt_svc.check_data()
        self.assertFalse(out["ready"])
        self.assertEqual(set(out["missing"]), set(bt_svc.REQUIRED_FILES))

    def test_check_data_when_all_present(self):
        for f in bt_svc.REQUIRED_FILES:
            pd.DataFrame([{"x": 1}]).to_parquet(Path(self._tmp.name) / f, index=False)
        out = bt_svc.check_data()
        self.assertTrue(out["ready"])
        self.assertEqual(out["missing"], [])


class IndexCodesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._env = patch.dict("os.environ", {"DB_PATH": self._tmp.name}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_returns_empty_when_no_file(self):
        self.assertEqual(bt_svc.index_codes(), [])

    def test_top_codes_first(self):
        pd.DataFrame([
            {"index_code": "111111", "index_name": "其它"},
            {"index_code": "000300", "index_name": "沪深300"},
            {"index_code": "000905", "index_name": "中证500"},
        ]).to_parquet(Path(self._tmp.name) / "ashare_index_components.parquet", index=False)
        out = bt_svc.index_codes()
        self.assertEqual(out[0]["index_code"], "000300")


class PortfolioTest(unittest.TestCase):
    def setUp(self):
        bt_svc._UPLOADS.clear()
        bt_svc._RESULTS.clear()

    def test_upload_validates_rows(self):
        with self.assertRaises(WechatInvalidInput):
            bt_svc.upload_portfolio_json({"rows": []})
        with self.assertRaises(WechatInvalidInput):
            bt_svc.upload_portfolio_json({"rows": [{"date": "2024-01-01"}]})

    def test_upload_returns_summary(self):
        out = bt_svc.upload_portfolio_json({
            "rows": [
                {"date": "2024-01-01", "stock_code": "1", "weight": 0.5},
                {"date": "2024-01-01", "stock_code": "2", "weight": 0.5},
                {"date": "2024-02-01", "stock_code": "1", "weight": 1.0},
            ],
            "name": "test",
        })
        self.assertEqual(out["num_periods"], 2)
        self.assertEqual(out["num_stocks"], 2)
        self.assertTrue(out["upload_id"].startswith("up_"))

    def test_uploaded_round_trip(self):
        up = bt_svc.upload_portfolio_json({"rows": [
            {"date": "2024-01-01", "stock_code": "1", "weight": 1.0},
        ]})
        out = bt_svc.uploaded_portfolio(up["upload_id"])
        self.assertEqual(out["num_rows"], 1)
        self.assertEqual(out["rows"][0]["stock_code"], "000001")

    def test_uploaded_missing_raises(self):
        with self.assertRaises(WechatDataMissing):
            bt_svc.uploaded_portfolio("nope")

    def test_sample_returns_predefined(self):
        out = bt_svc.sample_portfolio()
        self.assertEqual(out["rows"][0]["stock_code"], "000001")


class RunTest(unittest.TestCase):
    def setUp(self):
        bt_svc._UPLOADS.clear()
        bt_svc._RESULTS.clear()

    def test_run_requires_upload(self):
        with self.assertRaises(WechatInvalidInput):
            bt_svc.run({})
        with self.assertRaises(WechatDataMissing):
            bt_svc.run({"upload_id": "nope"})

    def test_run_when_gh_backtest_missing(self):
        up = bt_svc.upload_portfolio_json({"rows": [
            {"date": "2024-01-01", "stock_code": "1", "weight": 1.0},
        ]})
        import importlib
        original = importlib.import_module

        def faulty(name, *a, **kw):
            if name == "gh_backtest":
                raise ImportError("no")
            return original(name, *a, **kw)

        with patch("importlib.import_module", side_effect=faulty):
            with self.assertRaises(WechatError) as ctx:
                bt_svc.run({"upload_id": up["upload_id"]})
        self.assertEqual(ctx.exception.code, "GH_BACKTEST_MISSING")

    def test_result_missing(self):
        with self.assertRaises(WechatDataMissing):
            bt_svc.result("nope")


class CapabilitiesTest(unittest.TestCase):
    def test_registered(self):
        ids = set(registry.list_ids())
        expected = {
            "op:backtest:check-data",
            "op:backtest:index-codes",
            "op:backtest:upload-portfolio-json",
            "op:backtest:uploaded-portfolio",
            "op:backtest:sample-portfolio",
            "op:backtest:run",
            "op:backtest:result",
        }
        self.assertTrue(expected.issubset(ids))


if __name__ == "__main__":
    unittest.main()
