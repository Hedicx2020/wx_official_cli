import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_ui_cli.dependencies import build_dependency_report, parse_requirement_line

ROOT = Path(__file__).resolve().parents[1]


class DependenciesTest(unittest.TestCase):
    def test_parse_requirement_line_keeps_name_spec_and_marker(self):
        requirement = parse_requirement_line('pymem>=1.13; sys_platform == "win32"')

        self.assertEqual(requirement.name, "pymem")
        self.assertEqual(requirement.specifier, ">=1.13")
        self.assertEqual(requirement.marker, 'sys_platform == "win32"')

    def test_dependency_report_skips_non_matching_platform_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            requirements = Path(tmpdir) / "requirements.txt"
            requirements.write_text(
                "\n".join(
                    [
                        "fastapi>=0.115",
                        'pymem>=1.13; sys_platform == "win32"',
                        "ddddocr>=1.5",
                    ]
                ),
                encoding="utf-8",
            )

            with patch("gh_ui_cli.dependencies.installed_version") as version:
                version.side_effect = lambda name: "1.0" if name == "fastapi" else None
                report = build_dependency_report(requirements, platform_name="darwin")

        self.assertEqual(report["source"], str(requirements))
        self.assertEqual(report["total_requirements"], 3)
        self.assertEqual(report["applicable_requirements"], 2)
        self.assertEqual([item["name"] for item in report["installed"]], ["fastapi"])
        self.assertEqual([item["name"] for item in report["missing"]], ["ddddocr"])
        self.assertEqual([item["name"] for item in report["skipped"]], ["pymem"])
        self.assertEqual(report["heavy_missing"], ["ddddocr"])
        self.assertEqual(report["ok"], False)

    def test_dependency_report_applies_windows_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            requirements = Path(tmpdir) / "requirements.txt"
            requirements.write_text('pymem>=1.13; sys_platform == "win32"\n', encoding="utf-8")

            with patch("gh_ui_cli.dependencies.installed_version", return_value=None):
                report = build_dependency_report(requirements, platform_name="win32")

        self.assertEqual([item["name"] for item in report["missing"]], ["pymem"])
        self.assertEqual(report["skipped"], [])

    def test_full_extra_keeps_onnxruntime_installable_on_python_310(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('"onnxruntime<1.24; python_version < \'3.11\'"', pyproject)

    def test_project_publishes_only_wx_official_cli_console_script(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('name = "wx-official-cli"', pyproject)
        self.assertNotIn('gh-ui = "gh_ui_cli.cli:main"', pyproject)
        self.assertIn('wx-official-cli = "gh_ui_cli.wx_official_cli:main"', pyproject)


if __name__ == "__main__":
    unittest.main()
