import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CiWorkflowTest(unittest.TestCase):
    def test_ci_matrix_focuses_on_wx_official_cli(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn("name: wx-official-cli", workflow)
        self.assertIn("windows-latest", workflow)
        self.assertIn("macos-latest", workflow)
        self.assertIn("python-version: [\"3.10\", \"3.12\"]", workflow)
        self.assertIn("python-version: ${{ matrix.python-version }}", workflow)
        self.assertIn('uv run python -m unittest discover -s tests -p "test_wx_official_cli.py"', workflow)
        self.assertIn("uv run python -m unittest discover -s tests/wechat", workflow)
        self.assertNotIn("--extra full", workflow)
        self.assertIn("Package build", workflow)
        self.assertIn("uv build", workflow)
        self.assertIn("Install built wheel", workflow)
        self.assertIn("python -m pip install dist/*.whl", workflow)
        self.assertIn("Installed wheel smoke", workflow)
        self.assertIn("uv run wx-official-cli --help", workflow)
        self.assertIn("uv run wx-official-cli manifest", workflow)
        self.assertIn("wx-official-cli --help", workflow)
        self.assertIn("wx-official-cli manifest", workflow)
        self.assertIn("wx-official-cli status", workflow)
        self.assertNotIn("gh-ui --help", workflow)
        self.assertNotIn("runtime-verify", workflow)
        self.assertNotIn("with-data-query", workflow)
        self.assertNotIn("actions/upload-artifact@v4", workflow)
        self.assertLess(workflow.index("Package build"), workflow.index("Unit tests"))
        self.assertLess(workflow.index("Package build"), workflow.index("Install built wheel"))
        self.assertLess(workflow.index("Install built wheel"), workflow.index("Installed wheel smoke"))


class WindowsVerifierScriptTest(unittest.TestCase):
    def test_windows_verifier_runs_from_script_repository_root(self):
        script = (ROOT / "scripts" / "verify_windows_cache.ps1").read_text(encoding="utf-8")

        self.assertIn("$RepoRoot = Resolve-Path", script)
        self.assertIn("Push-Location $RepoRoot", script)
        self.assertIn("finally {", script)
        self.assertIn("Pop-Location", script)
        self.assertLess(script.index("Push-Location $RepoRoot"), script.index("uv run wx-official-cli status"))
        self.assertLess(script.index("Push-Location $RepoRoot"), script.index("uv run wx-official-cli verify"))

    def test_windows_verifier_resolves_output_paths_from_caller_directory(self):
        script = (ROOT / "scripts" / "verify_windows_cache.ps1").read_text(encoding="utf-8")

        self.assertIn("$CallerRoot = Get-Location", script)
        self.assertIn("$OutputDirResolved = Resolve-OutputPath $OutputDir", script)
        self.assertIn("$ReportPathResolved = Resolve-OutputPath $ReportPath", script)
        self.assertIn("$StatusPathResolved = Resolve-OutputPath $StatusPath", script)
        self.assertIn("status --save $StatusPathResolved", script)
        self.assertIn("--output-dir $OutputDirResolved", script)
        self.assertIn("--save $ReportPathResolved", script)
        self.assertLess(script.index("$CallerRoot = Get-Location"), script.index("Push-Location $RepoRoot"))


if __name__ == "__main__":
    unittest.main()
