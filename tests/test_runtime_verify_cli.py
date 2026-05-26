import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeVerifyCliTest(unittest.TestCase):
    def test_runtime_verify_generates_report_against_temporary_api_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "verify.json"
            env = os.environ.copy()
            src_path = str(ROOT / "src")
            existing_pythonpath = env.get("PYTHONPATH")
            env["PYTHONPATH"] = (
                src_path if not existing_pythonpath else os.pathsep.join([src_path, existing_pythonpath])
            )

            result = subprocess.run(
                [sys.executable, "-m", "gh_ui_cli", "runtime-verify", str(output)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(summary["output"], str(output))
            self.assertTrue(summary["ok"])
            self.assertTrue(report["ok"])
            self.assertFalse(report["completion_ready"])
            self.assertTrue(report["goal_evidence"]["route_operations_callable"])
            self.assertTrue(report["goal_evidence"]["agent_profile_verified"])
            self.assertEqual(report["failed_checks"], [])


if __name__ == "__main__":
    unittest.main()
