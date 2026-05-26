import unittest
from io import BytesIO, TextIOWrapper
from unittest.mock import patch

from gh_ui_cli.api_client import LocalApiClient
from gh_ui_cli.io import parse_key_values, parse_value, read_json_arg, write_json


class IoHelpersTest(unittest.TestCase):
    def test_parse_value_scalars(self):
        self.assertEqual(parse_value("1"), 1)
        self.assertEqual(parse_value("1.5"), 1.5)
        self.assertEqual(parse_value("true"), True)
        self.assertIsNone(parse_value("null"))
        self.assertEqual(parse_value("000001"), "000001")

    def test_parse_key_values(self):
        self.assertEqual(parse_key_values(["code=000001", "limit=5"]), {"code": "000001", "limit": 5})

    def test_read_json_arg_inline(self):
        self.assertEqual(read_json_arg('{"a": 1}'), {"a": 1})

    def test_write_json_is_safe_for_non_utf8_stdout(self):
        buffer = BytesIO()
        stream = TextIOWrapper(buffer, encoding="cp1252")

        with patch("sys.stdout", stream):
            write_json({"name": "股票"})
            stream.flush()

        self.assertIn(b"\\u80a1\\u7968", buffer.getvalue())


class ApiPathTest(unittest.TestCase):
    def test_normalize_api_path(self):
        self.assertEqual(LocalApiClient.normalize_path("health"), "/api/health")
        self.assertEqual(LocalApiClient.normalize_path("/api/health"), "/api/health")

    def test_normalize_prefixed_path(self):
        self.assertEqual(
            LocalApiClient.normalize_path("sessions", prefix="/api/wechat"),
            "/api/wechat/sessions",
        )
        self.assertEqual(
            LocalApiClient.normalize_path("/api/wechat/sessions", prefix="/api/wechat"),
            "/api/wechat/sessions",
        )


if __name__ == "__main__":
    unittest.main()
