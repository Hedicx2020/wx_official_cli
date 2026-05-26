import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_ui_cli.invoke import build_invoke_request
from gh_ui_cli.profile import save_profile


class InvokeTest(unittest.TestCase):
    def test_route_id_replaces_path_params_and_keeps_query_params(self):
        request = build_invoke_request(
            "route:GET:/api/wechat/articles/accounts/{mp_id}/categories",
            params={"mp_id": "abc/123", "limit": 20},
        )

        self.assertEqual(request.method, "GET")
        self.assertEqual(request.path, "/api/wechat/articles/accounts/abc%2F123/categories")
        self.assertEqual(request.params, {"limit": 20})
        self.assertIsNone(request.json_body)

    def test_route_update_data_template_uses_token_body_shape(self):
        request = build_invoke_request(
            "route:POST:/api/update/{module}/{method}",
            params={"module": "stock", "method": "stock_price", "adj_type": "forward"},
            token="secret",
            server="secondary",
        )

        self.assertEqual(request.method, "POST")
        self.assertEqual(request.path, "/api/update/stock/stock_price")
        self.assertEqual(request.params, {})
        self.assertEqual(
            request.json_body,
            {"adj_type": "forward", "token": "secret", "server": "secondary"},
        )

    def test_route_factor_data_template_uses_token_query_param(self):
        request = build_invoke_request(
            "route:POST:/api/factor/db/update/{table}",
            params={"table": "factor_info"},
            token="secret",
        )

        self.assertEqual(request.method, "POST")
        self.assertEqual(request.path, "/api/factor/db/update/factor_info")
        self.assertEqual(request.params, {"token": "secret"})
        self.assertIsNone(request.json_body)

    def test_route_id_requires_missing_path_param(self):
        with self.assertRaisesRegex(ValueError, "missing path parameter: mp_id"):
            build_invoke_request("route:GET:/api/wechat/articles/accounts/{mp_id}", params={})

    def test_data_query_id_maps_to_query_route(self):
        request = build_invoke_request(
            "data:query:stock/stock_price",
            params={"code": "000001", "limit": 5},
        )

        self.assertEqual(request.method, "GET")
        self.assertEqual(request.path, "/stock/stock_price")
        self.assertEqual(request.params, {"code": "000001", "limit": 5})

    def test_data_download_id_builds_existing_json_body_shape(self):
        request = build_invoke_request(
            "data:download:stock/stock_price",
            params={"adj_type": "forward"},
            token="secret",
            server="secondary",
        )

        self.assertEqual(request.method, "POST")
        self.assertEqual(request.path, "/download/stock/stock_price")
        self.assertEqual(
            request.json_body,
            {"adj_type": "forward", "token": "secret", "server": "secondary"},
        )

    def test_factor_data_update_id_maps_token_to_query_param(self):
        request = build_invoke_request(
            "factor_data:update:factor_info",
            params={},
            token="secret",
        )

        self.assertEqual(request.method, "POST")
        self.assertEqual(request.path, "/factor/db/update/factor_info")
        self.assertEqual(request.params, {"token": "secret"})

    def test_token_is_required_for_mutating_data_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            with (
                patch.dict(os.environ, {"GH_UI_CLI_PROFILE": str(path)}, clear=True),
                self.assertRaisesRegex(ValueError, "gh-ui profile set --api-token is required"),
            ):
                build_invoke_request("data:update:stock/stock_price", params={})

    def test_profile_token_and_server_are_used_for_mutating_data_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            with patch.dict(os.environ, {"GH_UI_CLI_PROFILE": str(path)}, clear=True):
                save_profile({"api_token": "profile-token", "server": "secondary"})

                request = build_invoke_request("data:update:stock/stock_price", params={})

        self.assertEqual(request.json_body, {"token": "profile-token", "server": "secondary"})


if __name__ == "__main__":
    unittest.main()
