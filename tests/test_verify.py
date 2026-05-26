import unittest

from gh_ui_cli.verify import build_goal_verification_report, merge_goal_verification_reports


class VerifyReportTest(unittest.TestCase):
    def test_report_separates_current_run_success_from_goal_completion(self):
        report = build_goal_verification_report(
            checks=[
                {"name": "dependencies", "ok": True},
                {
                    "name": "coverage",
                    "ok": True,
                    "all_callables": True,
                    "preferred_command_parse": {"all_parseable": True},
                    "frontend_api_references": {"total_references": 8, "missing_references": []},
                    "totals": {
                        "data_query_methods": 85,
                        "data_download_methods": 78,
                        "data_update_methods": 78,
                        "factor_data_tables": 15,
                    },
                },
                {"name": "smoke", "ok": True, "report": {"checks": [{"name": "agent_profile", "ok": True}]}},
                {"name": "windows_dependency_preflight", "ok": True},
            ],
            platform_name="macOS-26.2-arm64",
            current_platform="darwin",
            mode="source",
        )

        self.assertTrue(report["ok"])
        self.assertFalse(report["completion_ready"])
        self.assertTrue(report["goal_evidence"]["all_features_cli_callable"])
        self.assertTrue(report["goal_evidence"]["agent_profile_verified"])
        self.assertTrue(report["goal_evidence"]["preferred_commands_parseable"])
        self.assertTrue(report["goal_evidence"]["frontend_api_references_verified"])
        self.assertTrue(report["goal_evidence"]["mac_runtime_verified"])
        self.assertFalse(report["goal_evidence"]["windows_runtime_verified"])
        self.assertTrue(report["goal_evidence"]["windows_dependency_preflight"])
        self.assertIn("Windows runtime has not been verified in this run.", report["limitations"])

    def test_report_fails_when_any_required_check_fails(self):
        report = build_goal_verification_report(
            checks=[
                {"name": "dependencies", "ok": True},
                {"name": "coverage", "ok": False, "all_callables": False},
                {"name": "smoke", "ok": True, "report": {"checks": [{"name": "agent_profile", "ok": True}]}},
            ],
            platform_name="Windows",
            current_platform="win32",
            mode="source",
        )

        self.assertFalse(report["ok"])
        self.assertFalse(report["completion_ready"])
        self.assertEqual(report["failed_checks"], ["coverage"])

    def test_api_base_report_does_not_treat_route_coverage_as_full_feature_coverage(self):
        report = build_goal_verification_report(
            checks=[
                {"name": "coverage", "ok": True, "all_callables": True},
                {"name": "smoke", "ok": True},
            ],
            platform_name="macOS",
            current_platform="darwin",
            mode="api_base",
        )

        self.assertTrue(report["ok"])
        self.assertTrue(report["goal_evidence"]["route_operations_callable"])
        self.assertFalse(report["goal_evidence"]["all_features_cli_callable"])
        self.assertIn("HTTP mode cannot verify source dynamic capability inventory.", report["limitations"])

    def test_source_report_requires_frontend_api_reference_coverage_for_all_features(self):
        report = build_goal_verification_report(
            checks=[
                {
                    "name": "coverage",
                    "ok": True,
                    "all_callables": True,
                    "preferred_command_parse": {"all_parseable": True},
                    "frontend_api_references": {
                        "total_references": 2,
                        "missing_references": [{"path": "/api/missing"}],
                    },
                    "totals": {
                        "data_query_methods": 85,
                        "data_download_methods": 78,
                        "data_update_methods": 78,
                        "factor_data_tables": 15,
                    },
                },
                {"name": "smoke", "ok": True},
            ],
            platform_name="macOS",
            current_platform="darwin",
            mode="source",
        )

        self.assertFalse(report["goal_evidence"]["frontend_api_references_verified"])
        self.assertFalse(report["goal_evidence"]["all_features_cli_callable"])

    def test_source_report_requires_agent_profile_smoke_for_all_features(self):
        report = build_goal_verification_report(
            checks=[
                {
                    "name": "coverage",
                    "ok": True,
                    "all_callables": True,
                    "preferred_command_parse": {"all_parseable": True},
                    "frontend_api_references": {
                        "total_references": 2,
                        "missing_references": [],
                    },
                    "totals": {
                        "data_query_methods": 85,
                        "data_download_methods": 78,
                        "data_update_methods": 78,
                        "factor_data_tables": 15,
                    },
                },
                {"name": "smoke", "ok": True, "report": {"checks": []}},
            ],
            platform_name="macOS",
            current_platform="darwin",
            mode="source",
        )

        self.assertFalse(report["goal_evidence"]["agent_profile_verified"])
        self.assertFalse(report["goal_evidence"]["all_features_cli_callable"])

    def test_source_report_requires_preferred_command_parse_coverage_for_all_features(self):
        report = build_goal_verification_report(
            checks=[
                {
                    "name": "coverage",
                    "ok": True,
                    "all_callables": True,
                    "preferred_command_parse": {
                        "all_parseable": False,
                        "unparseable": [{"command": "gh-ui wechat missing-command"}],
                    },
                    "frontend_api_references": {
                        "total_references": 2,
                        "missing_references": [],
                    },
                    "totals": {
                        "data_query_methods": 85,
                        "data_download_methods": 78,
                        "data_update_methods": 78,
                        "factor_data_tables": 15,
                    },
                },
                {"name": "smoke", "ok": True},
            ],
            platform_name="macOS",
            current_platform="darwin",
            mode="source",
        )

        self.assertFalse(report["goal_evidence"]["preferred_commands_parseable"])
        self.assertFalse(report["goal_evidence"]["all_features_cli_callable"])

    def test_merge_reports_marks_completion_ready_when_mac_and_windows_evidence_exist(self):
        mac_source = _report(
            platform="macOS",
            current_platform="darwin",
            evidence={
                "route_operations_callable": True,
                "source_dynamic_capabilities_verified": True,
                "frontend_api_references_verified": True,
                "preferred_commands_parseable": True,
                "all_features_cli_callable": True,
                "agent_profile_verified": True,
                "mac_runtime_verified": True,
                "windows_runtime_verified": False,
                "windows_dependency_preflight": True,
            },
        )
        windows_http = _report(
            platform="Windows",
            current_platform="win32",
            mode="api_base",
            evidence={
                "route_operations_callable": True,
                "source_dynamic_capabilities_verified": False,
                "all_features_cli_callable": False,
                "agent_profile_verified": True,
                "mac_runtime_verified": False,
                "windows_runtime_verified": True,
                "windows_dependency_preflight": False,
            },
        )

        merged = merge_goal_verification_reports([mac_source, windows_http])

        self.assertTrue(merged["ok"])
        self.assertTrue(merged["completion_ready"])
        self.assertTrue(merged["goal_evidence"]["all_features_cli_callable"])
        self.assertTrue(merged["goal_evidence"]["mac_runtime_verified"])
        self.assertTrue(merged["goal_evidence"]["windows_runtime_verified"])
        self.assertEqual(merged["failed_reports"], [])
        self.assertEqual(
            merged["evidence_sources"]["all_features_cli_callable"],
            [{"index": 0, "platform": "macOS", "current_platform": "darwin", "mode": "source"}],
        )
        self.assertEqual(
            merged["evidence_sources"]["windows_runtime_verified"],
            [{"index": 1, "platform": "Windows", "current_platform": "win32", "mode": "api_base"}],
        )
        requirements = merged["completion_requirements"]
        self.assertTrue(requirements["no_failed_reports"]["ok"])
        self.assertTrue(requirements["source_cli_coverage"]["ok"])
        self.assertTrue(requirements["agent_profile"]["ok"])
        self.assertTrue(requirements["mac_runtime"]["ok"])
        self.assertTrue(requirements["windows_runtime"]["ok"])
        self.assertEqual(merged["next_actions"], {})
        self.assertEqual(
            requirements["source_cli_coverage"]["evidence_sources"],
            {
                "route_operations_callable": [
                    {"index": 0, "platform": "macOS", "current_platform": "darwin", "mode": "source"}
                ],
                "source_dynamic_capabilities_verified": [
                    {"index": 0, "platform": "macOS", "current_platform": "darwin", "mode": "source"}
                ],
                "frontend_api_references_verified": [
                    {"index": 0, "platform": "macOS", "current_platform": "darwin", "mode": "source"}
                ],
                "preferred_commands_parseable": [
                    {"index": 0, "platform": "macOS", "current_platform": "darwin", "mode": "source"}
                ],
            },
        )

    def test_merge_reports_keeps_source_cli_coverage_separate_from_agent_profile(self):
        mac_source = _report(
            platform="macOS",
            current_platform="darwin",
            evidence={
                "route_operations_callable": True,
                "source_dynamic_capabilities_verified": True,
                "frontend_api_references_verified": True,
                "preferred_commands_parseable": True,
                "all_features_cli_callable": False,
                "agent_profile_verified": False,
                "mac_runtime_verified": True,
            },
        )

        merged = merge_goal_verification_reports([mac_source])

        requirements = merged["completion_requirements"]
        self.assertFalse(merged["completion_ready"])
        self.assertTrue(requirements["source_cli_coverage"]["ok"])
        self.assertFalse(requirements["agent_profile"]["ok"])
        self.assertEqual(
            set(requirements["source_cli_coverage"]["evidence_sources"]),
            {
                "route_operations_callable",
                "source_dynamic_capabilities_verified",
                "frontend_api_references_verified",
                "preferred_commands_parseable",
            },
        )
        self.assertNotIn("Full source CLI feature coverage has not been verified.", merged["limitations"])

    def test_merge_reports_keeps_completion_false_when_any_input_failed(self):
        good = _report(platform="macOS", current_platform="darwin", evidence={"mac_runtime_verified": True})
        failed = _report(platform="Windows", current_platform="win32", evidence={"windows_runtime_verified": True}, ok=False)

        merged = merge_goal_verification_reports([good, failed])

        self.assertFalse(merged["ok"])
        self.assertFalse(merged["completion_ready"])
        self.assertEqual(merged["failed_reports"][0]["index"], 1)
        self.assertFalse(merged["goal_evidence"]["windows_runtime_verified"])
        self.assertEqual(merged["evidence_sources"]["windows_runtime_verified"], [])
        self.assertFalse(merged["completion_requirements"]["no_failed_reports"]["ok"])
        self.assertEqual(merged["completion_requirements"]["no_failed_reports"]["failed_report_indices"], [1])
        self.assertFalse(merged["completion_requirements"]["windows_runtime"]["ok"])

    def test_merge_reports_ignores_windows_runtime_evidence_from_non_windows_report(self):
        mac_source = _report(
            platform="macOS",
            current_platform="darwin",
            evidence={
                "all_features_cli_callable": True,
                "agent_profile_verified": True,
                "mac_runtime_verified": True,
                "windows_runtime_verified": True,
            },
        )

        merged = merge_goal_verification_reports([mac_source])

        self.assertFalse(merged["completion_ready"])
        self.assertFalse(merged["goal_evidence"]["windows_runtime_verified"])
        self.assertIn("Windows runtime has not been verified.", merged["limitations"])
        self.assertEqual(
            merged["next_actions"]["windows_runtime"][0]["argv"],
            ["gh-ui", "runtime-verify", "verify-windows.json"],
        )
        self.assertEqual(merged["next_actions"]["windows_runtime"][0]["platform"], "win32")

    def test_merge_reports_requires_full_feature_evidence_from_source_mode(self):
        api_base_claim = _report(
            platform="Windows",
            current_platform="win32",
            mode="api_base",
            evidence={
                "all_features_cli_callable": True,
                "agent_profile_verified": True,
                "windows_runtime_verified": True,
            },
        )

        merged = merge_goal_verification_reports([api_base_claim])

        self.assertFalse(merged["completion_ready"])
        self.assertFalse(merged["goal_evidence"]["all_features_cli_callable"])
        self.assertIn("Full source CLI feature coverage has not been verified.", merged["limitations"])
        self.assertEqual(
            merged["next_actions"]["source_cli_coverage"][0]["argv"],
            [
                "gh-ui",
                "verify",
                "--with-data-query",
                "--windows-deps-preflight",
                "--strict",
                "--save",
                "verify-macos.json",
            ],
        )


def _report(*, platform, current_platform, evidence, ok=True, mode="source"):
    defaults = {
        "route_operations_callable": False,
        "source_dynamic_capabilities_verified": False,
        "frontend_api_references_verified": False,
        "preferred_commands_parseable": False,
        "all_features_cli_callable": False,
        "agent_profile_verified": False,
        "mac_runtime_verified": False,
        "windows_runtime_verified": False,
        "windows_dependency_preflight": False,
    }
    return {
        "ok": ok,
        "completion_ready": False,
        "mode": mode,
        "platform": platform,
        "current_platform": current_platform,
        "failed_checks": [] if ok else ["smoke"],
        "goal_evidence": {**defaults, **evidence},
        "limitations": [],
        "checks": [],
    }


if __name__ == "__main__":
    unittest.main()
