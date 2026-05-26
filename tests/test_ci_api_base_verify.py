import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_api_base_verify.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("ci_api_base_verify", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class CiApiBaseVerifyTest(unittest.TestCase):
    def test_script_generates_verify_report_against_mock_sidecar(self):
        script = _load_script()

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "verify.json"
            report = script.run_verify(output, command=[sys.executable, "-m", "gh_ui_cli"])

            self.assertTrue(output.exists())
            self.assertTrue(report["ok"])
            self.assertFalse(report["completion_ready"])
            self.assertTrue(report["goal_evidence"]["route_operations_callable"])
            self.assertTrue(report["goal_evidence"]["agent_profile_verified"])
            self.assertEqual(report["failed_checks"], [])


if __name__ == "__main__":
    unittest.main()
