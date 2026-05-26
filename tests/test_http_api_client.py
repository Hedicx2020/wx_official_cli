import unittest
from unittest.mock import Mock

from gh_ui_cli.api_client import ApiError, HttpApiClient


class FakeResponse:
    def __init__(self, status_code=200, headers=None, payload=None, content=b""):
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/json"}
        self._payload = payload
        self.content = content
        self.text = content.decode("utf-8", errors="replace") if content else ""

    def json(self):
        return self._payload


class HttpApiClientTest(unittest.TestCase):
    def test_request_uses_api_base_and_normalized_path(self):
        client = HttpApiClient("http://127.0.0.1:8765")
        client.client.request = Mock(
            return_value=FakeResponse(payload={"status": "ok"})
        )

        response = client.request("GET", "health")

        self.assertEqual(response.data, {"status": "ok"})
        client.client.request.assert_called_once_with(
            "GET",
            "/api/health",
            params=None,
            json=None,
            headers=None,
            files=None,
        )

    def test_request_raises_api_error_for_http_failure(self):
        client = HttpApiClient("http://127.0.0.1:8765")
        client.client.request = Mock(
            return_value=FakeResponse(status_code=500, payload={"detail": "boom"})
        )

        with self.assertRaises(ApiError) as ctx:
            client.request("GET", "/api/health")

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(ctx.exception.detail, "boom")


if __name__ == "__main__":
    unittest.main()
