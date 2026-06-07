"""Windows 微信进程扫描器测试。"""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from gh_ui_cli.wechat.adapters import scanner_win


class ScannerWinProcessTest(unittest.TestCase):
    def test_lists_weixin_and_legacy_wechat_processes(self):
        outputs = {
            "Weixin.exe": (
                '"Weixin.exe","100","Console","1","120,000 K"\n'
                '"Weixin.exe","101","Console","1","80,000 K"\n'
            ),
            "WeChat.exe": '"WeChat.exe","200","Console","1","140,000 K"\n',
        }

        def run(cmd, **_kwargs):
            image = cmd[2].rsplit(" ", 1)[-1]
            return subprocess.CompletedProcess(cmd, 0, stdout=outputs[image], stderr="")

        with patch("gh_ui_cli.wechat.adapters.scanner_win.subprocess.run", side_effect=run):
            pids = scanner_win._list_weixin_pids()

        self.assertEqual(pids, [(200, 140000), (100, 120000), (101, 80000)])


if __name__ == "__main__":
    unittest.main()
