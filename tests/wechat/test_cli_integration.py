"""端到端：通过 cli 入口跑 wechat config-get / config-set，验证 stdout JSON。"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gh_ui_cli import cli


class WechatCliIntegrationTest(unittest.TestCase):
    def _run(self, argv: list[str], env: dict[str, str]) -> tuple[int, str]:
        buf = io.StringIO()
        # 防止 cli 误以为 source mode 可用而尝试 import gh_quant_ui
        full_env = {"GH_UI_API_BASE": "", "GH_QUANT_UI_PATH": ""}
        full_env.update(env)
        rc = 0
        with patch.dict("os.environ", full_env, clear=False):
            with redirect_stdout(buf):
                try:
                    cli.main(argv)
                except SystemExit as e:
                    rc = int(e.code or 0)
        return rc, buf.getvalue()

    def test_config_get_returns_defaults(self):
        with TemporaryDirectory() as tmp:
            rc, out = self._run(
                ["wechat", "config-get"],
                {"GH_WX_DATA_DIR": tmp},
            )
        self.assertEqual(rc, 0, msg=out)
        data = json.loads(out)
        self.assertEqual(data["llm_model"], "deepseek-chat")
        self.assertEqual(data["default_keyword"], "")

    def test_config_set_persists_and_get_reads(self):
        with TemporaryDirectory() as tmp:
            patch_file = Path(tmp) / "patch.json"
            patch_file.write_text(json.dumps({"default_keyword": "AI"}), encoding="utf-8")
            rc, out = self._run(
                ["wechat", "config-set", "--json", f"@{patch_file}"],
                {"GH_WX_DATA_DIR": tmp},
            )
            self.assertEqual(rc, 0, msg=out)
            data = json.loads(out)
            self.assertEqual(data["default_keyword"], "AI")
            self.assertNotEqual(data["last_updated"], "")

            rc2, out2 = self._run(
                ["wechat", "config-get"],
                {"GH_WX_DATA_DIR": tmp},
            )
            self.assertEqual(rc2, 0, msg=out2)
            data2 = json.loads(out2)
            self.assertEqual(data2["default_keyword"], "AI")


if __name__ == "__main__":
    unittest.main()
