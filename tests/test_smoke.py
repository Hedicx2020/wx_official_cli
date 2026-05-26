import unittest
from unittest.mock import Mock

from gh_ui_cli.smoke import build_smoke_report, run_api_base_checks, run_profile_check


class SmokeReportTest(unittest.TestCase):
    def test_report_marks_required_checks_ok(self):
        checks = [
            {"name": "source", "ok": True},
            {"name": "coverage", "ok": True},
            {"name": "health", "ok": True},
        ]

        report = build_smoke_report(checks, platform_name="Windows", python_version="3.12.1")

        self.assertTrue(report["ok"])
        self.assertEqual(report["platform"], "Windows")
        self.assertEqual(report["python"], "3.12.1")
        self.assertEqual(report["failed_checks"], [])

    def test_report_lists_failed_checks(self):
        checks = [
            {"name": "source", "ok": True},
            {"name": "coverage", "ok": False, "error": "missing route"},
        ]

        report = build_smoke_report(checks, platform_name="macOS", python_version="3.13.5")

        self.assertFalse(report["ok"])
        self.assertEqual(report["failed_checks"], ["coverage"])
        self.assertEqual(report["checks"][1]["error"], "missing route")

    def test_api_base_checks_do_not_require_source_root(self):
        client = Mock()
        client.request.return_value.data = {"status": "ok"}

        checks = run_api_base_checks(client, with_data_query=False)

        self.assertEqual(
            checks,
            [
                {"name": "agent_profile", "ok": True, "has_api_token": True, "has_access_token": True},
                {"name": "api_base", "ok": True, "health": {"status": "ok"}},
            ],
        )
        client.request.assert_called_once_with("GET", "/health")

    def test_profile_check_round_trips_tokens_without_exposing_secret_values(self):
        check = run_profile_check()

        self.assertTrue(check["ok"])
        self.assertEqual(check["name"], "agent_profile")
        self.assertTrue(check["has_api_token"])
        self.assertTrue(check["has_access_token"])
        self.assertNotIn("secret", str(check).lower())


if __name__ == "__main__":
    unittest.main()
