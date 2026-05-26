"""AI 报告复现模块测试。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gh_ui_cli.ai import service as ai_svc
from gh_ui_cli.wechat import registry
from gh_ui_cli.wechat.errors import WechatDataMissing, WechatInvalidInput


class WorkspaceTest(unittest.TestCase):
    def test_default_workspace(self):
        with patch.dict("os.environ", {"REPORT_REPRODUCE_PATH": "", "HOME": "/tmp/fake"}, clear=False):
            ws = ai_svc.workspace_root()
        self.assertTrue(str(ws).endswith("report_reproduce"))

    def test_explicit_workspace(self):
        ws = ai_svc.workspace_root("/tmp/x")
        self.assertEqual(ws, Path("/tmp/x"))

    def test_output_path_relative(self):
        ws = Path("/tmp/ws")
        out = ai_svc.output_root(ws, "out")
        self.assertEqual(out, ws / "out")

    def test_output_path_absolute(self):
        ws = Path("/tmp/ws")
        out = ai_svc.output_root(ws, "/abs/out")
        self.assertEqual(out, Path("/abs/out"))


class StatusTest(unittest.TestCase):
    def test_status_when_no_workspace(self):
        with TemporaryDirectory() as tmp:
            out = ai_svc.status(workspace=tmp)
        # tmp 是 TemporaryDirectory 创建的，存在但没有 report_reproduce 子结构
        self.assertTrue(out["workspace_exists"])
        self.assertFalse(out["reproduce_command_exists"])
        self.assertIn("codex", out["runners"])
        self.assertIn("claude", out["runners"])

    def test_list_projects_with_seeded_dirs(self):
        with TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "plan" / "demo").mkdir(parents=True)
            (ws / "plan" / "demo" / "plan.md").write_text("# plan")
            (ws / "src" / "demo").mkdir(parents=True)
            (ws / "src" / "demo" / "main.py").write_text("print(1)")
            out = ai_svc.list_projects(workspace=tmp)
        self.assertEqual(out["projects"][0]["name"], "demo")
        self.assertTrue(out["projects"][0]["plan_exists"])
        self.assertTrue(out["projects"][0]["source_exists"])

    def test_list_pdfs_returns_list(self):
        with TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "reports").mkdir()
            (ws / "reports" / "test.pdf").write_bytes(b"%PDF-1.4")
            out = ai_svc.list_pdfs(workspace=tmp)
        names = [p["name"] for p in out["pdfs"]]
        self.assertIn("test.pdf", names)


class TaskLifecycleTest(unittest.TestCase):
    def setUp(self):
        ai_svc._TASKS.clear()

    def test_get_missing_raises(self):
        with self.assertRaises(WechatDataMissing):
            ai_svc.get_task("nope")

    def test_cancel_missing_raises(self):
        with self.assertRaises(WechatDataMissing):
            ai_svc.cancel("nope")

    def test_list_tasks_empty(self):
        out = ai_svc.list_tasks()
        self.assertEqual(out, {"tasks": []})

    def test_start_validates_pdf(self):
        with self.assertRaises(WechatInvalidInput):
            ai_svc.start({"pdf_path": ""})
        with self.assertRaises(WechatInvalidInput):
            ai_svc.start({"pdf_path": "/nonexistent.pdf"})

    def test_start_validates_workspace(self):
        with TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "x.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            with self.assertRaises(WechatInvalidInput):
                ai_svc.start({"pdf_path": str(pdf), "workspace": "/nope/path/that/does/not/exist"})


class CapabilitiesTest(unittest.TestCase):
    def test_registered(self):
        ids = set(registry.list_ids())
        expected = {
            "op:ai:status",
            "op:ai:report-projects",
            "op:ai:report-pdf-candidates",
            "op:ai:report-tasks",
            "op:ai:report-task",
            "op:ai:report-task-cancel",
            "op:ai:report-start",
        }
        self.assertTrue(expected.issubset(ids))


if __name__ == "__main__":
    unittest.main()
