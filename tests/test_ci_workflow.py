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
        self.assertIn('uv run --extra full python -m unittest discover -s tests -p "test_wx_official_cli.py"', workflow)
        self.assertIn("uv run --extra full python -m unittest discover -s tests/wechat", workflow)
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
        self.assertLess(workflow.index("Package build"), workflow.index("Install built wheel"))
        self.assertLess(workflow.index("Install built wheel"), workflow.index("Installed wheel smoke"))


if __name__ == "__main__":
    unittest.main()
