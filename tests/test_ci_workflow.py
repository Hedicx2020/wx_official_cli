import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CiWorkflowTest(unittest.TestCase):
    def test_ci_matrix_runs_api_base_verify_integration_on_windows(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn("windows-latest", workflow)
        self.assertIn("macos-latest", workflow)
        self.assertIn("python-version: [\"3.10\", \"3.12\"]", workflow)
        self.assertIn("python-version: ${{ matrix.python-version }}", workflow)
        self.assertIn("uv run --extra full python -m unittest discover -s tests", workflow)
        self.assertIn("API-base manifest/invoke/smoke/verify integration", workflow)
        self.assertIn("tests.test_cli_http_integration", workflow)
        self.assertIn("Package build", workflow)
        self.assertIn("uv build", workflow)
        self.assertIn("Install built wheel", workflow)
        self.assertIn("python -m pip install dist/*.whl", workflow)
        self.assertIn("Installed wheel CLI smoke", workflow)
        self.assertIn("gh-ui --help", workflow)
        self.assertIn("GH_UI_CLI_PROFILE:", workflow)
        self.assertIn("gh-ui profile set --api-token ci-api --access-token ci-access --server primary", workflow)
        self.assertIn("gh-ui profile get", workflow)
        self.assertIn("gh-ui deps --requirements tests/fixtures/minimal_requirements.txt --strict", workflow)
        self.assertIn("Installed wheel API-base verify report", workflow)
        self.assertIn("gh-ui runtime-verify verify-${{ runner.os }}-py${{ matrix.python-version }}.json", workflow)
        self.assertIn("Print installed wheel verify report", workflow)
        self.assertIn("GH_UI_VERIFY_REPORT_BEGIN", workflow)
        self.assertIn("GH_UI_VERIFY_REPORT_END", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("continue-on-error: true", workflow)
        self.assertIn("verify-${{ runner.os }}-py${{ matrix.python-version }}.json", workflow)
        self.assertLess(workflow.index("Package build"), workflow.index("Install built wheel"))
        self.assertLess(workflow.index("Install built wheel"), workflow.index("Installed wheel CLI smoke"))
        self.assertLess(workflow.index("Installed wheel CLI smoke"), workflow.index("Installed wheel API-base verify report"))


if __name__ == "__main__":
    unittest.main()
