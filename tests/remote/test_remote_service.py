"""remote.service 单元测试 - mock httpx.Client。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from gh_ui_cli.remote import service
from gh_ui_cli.remote.service import RemoteAuthMissing, RemoteRequestFailed


def _resp(status: int, body=None, text: str = "", json_ct: bool = True) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.headers = {"content-type": "application/json"} if json_ct else {"content-type": "text/plain"}
    r.text = text if text else (str(body) if body else "")
    r.json = MagicMock(return_value=body)
    return r


class TokenResolutionTest(unittest.TestCase):
    def test_payload_wins(self):
        env = {"GH_ACCESS_TOKEN": "env-tok"}
        with patch.dict("os.environ", env, clear=False):
            self.assertEqual(service._resolve_access_token({"access_token": "pay-tok"}), "pay-tok")

    def test_env_fallback(self):
        env = {"GH_ACCESS_TOKEN": "env-tok"}
        with patch.dict("os.environ", env, clear=False):
            with patch("gh_ui_cli.remote.service.load_profile", return_value={"access_token": ""}):
                self.assertEqual(service._resolve_access_token({}), "env-tok")

    def test_profile_fallback(self):
        with patch.dict("os.environ", {"GH_ACCESS_TOKEN": ""}, clear=False):
            with patch("gh_ui_cli.remote.service.load_profile", return_value={"access_token": "prof"}):
                self.assertEqual(service._resolve_access_token({}), "prof")

    def test_missing_raises(self):
        with patch.dict("os.environ", {"GH_ACCESS_TOKEN": ""}, clear=False):
            with patch("gh_ui_cli.remote.service.load_profile", return_value={"access_token": ""}):
                with self.assertRaises(RemoteAuthMissing):
                    service._resolve_access_token({})


class RequestTest(unittest.TestCase):
    def _patched_client(self, response):
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.request.return_value = response
        return patch("httpx.Client", return_value=client), client

    def test_me_ok(self):
        resp = _resp(200, body={"username": "u"})
        ctx, client = self._patched_client(resp)
        with ctx:
            out = service.me(access_token="t")
        self.assertEqual(out, {"username": "u"})
        client.request.assert_called_once()
        args, kwargs = client.request.call_args
        self.assertEqual(args[0], "GET")
        self.assertTrue(args[1].endswith("/users/me"))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer t")

    def test_request_raises_on_http_error(self):
        resp = _resp(403, body={"detail": "denied"})
        ctx, _ = self._patched_client(resp)
        with ctx:
            with self.assertRaises(RemoteRequestFailed) as ctx_err:
                service.me(access_token="t")
        self.assertIn("403", str(ctx_err.exception))

    def test_request_raises_on_network_error(self):
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.request.side_effect = Exception("conn refused")
        with patch("httpx.Client", return_value=client):
            with self.assertRaises(RemoteRequestFailed):
                service.me(access_token="t")

    def test_tokens_list(self):
        ctx, _ = self._patched_client(_resp(200, body=[{"id": 1}]))
        with ctx:
            out = service.tokens_list(access_token="t")
        self.assertEqual(out, [{"id": 1}])

    def test_tokens_generate(self):
        resp = _resp(201, body={"id": 2, "token": "tok"})
        ctx, client = self._patched_client(resp)
        with ctx:
            out = service.tokens_generate(name="agent", access_token="t")
        self.assertEqual(out["id"], 2)
        kwargs = client.request.call_args[1]
        self.assertEqual(kwargs["json"], {"name": "agent"})

    def test_tokens_revoke(self):
        ctx, client = self._patched_client(_resp(200, body={"ok": True}))
        with ctx:
            out = service.tokens_revoke(token_id=7, access_token="t")
        self.assertEqual(out["ok"], True)
        args = client.request.call_args[0]
        self.assertEqual(args[0], "DELETE")
        self.assertTrue(args[1].endswith("/api-tokens/7"))


class CapabilitiesTest(unittest.TestCase):
    def test_all_registered(self):
        from gh_ui_cli.wechat import registry
        ids = set(registry.list_ids())
        expected = {"op:remote:me", "op:remote:tokens-list", "op:remote:tokens-generate", "op:remote:tokens-revoke"}
        self.assertTrue(expected.issubset(ids))


if __name__ == "__main__":
    unittest.main()
