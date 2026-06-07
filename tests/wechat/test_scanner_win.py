"""Windows 微信进程扫描器测试。"""

from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace
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

    def test_configures_kernel32_ctypes_signatures_for_64bit_handles(self):
        fake_kernel32 = SimpleNamespace(
            OpenProcess=SimpleNamespace(),
            VirtualQueryEx=SimpleNamespace(),
            ReadProcessMemory=SimpleNamespace(),
            CloseHandle=SimpleNamespace(),
        )
        fake_ctypes = SimpleNamespace(
            wintypes=SimpleNamespace(
                DWORD="DWORD",
                BOOL="BOOL",
                HANDLE="HANDLE",
                LPCVOID="LPCVOID",
                LPVOID="LPVOID",
                SIZE_T="SIZE_T",
            ),
            POINTER=lambda value: ("POINTER", value),
        )

        scanner_win._configure_kernel32_api(fake_kernel32, fake_ctypes)

        self.assertEqual(fake_kernel32.OpenProcess.restype, "HANDLE")
        self.assertEqual(fake_kernel32.OpenProcess.argtypes, ["DWORD", "BOOL", "DWORD"])
        self.assertEqual(fake_kernel32.VirtualQueryEx.restype, "SIZE_T")
        self.assertEqual(fake_kernel32.VirtualQueryEx.argtypes[0], "HANDLE")
        self.assertEqual(fake_kernel32.VirtualQueryEx.argtypes[1], "LPCVOID")
        self.assertEqual(fake_kernel32.ReadProcessMemory.restype, "BOOL")
        self.assertEqual(fake_kernel32.ReadProcessMemory.argtypes[:4], [
            "HANDLE",
            "LPCVOID",
            "LPVOID",
            "SIZE_T",
        ])
        self.assertEqual(fake_kernel32.CloseHandle.argtypes, ["HANDLE"])

    def test_read_mem_uses_pointer_width_address_argument(self):
        class _Buffer:
            raw = b"abcd"

        class _Size:
            def __init__(self, value: int):
                self.value = value

        class _FakeCtypes:
            @staticmethod
            def create_string_buffer(_size: int):
                return _Buffer()

            c_size_t = _Size

            @staticmethod
            def c_uint64(value: int):
                return ("c_uint64", value)

            @staticmethod
            def c_void_p(value: int):
                return ("c_void_p", value)

            @staticmethod
            def byref(value):
                return value

        fake_kernel32 = SimpleNamespace()

        def read_process_memory(_handle, address, _buffer, size, read_count):
            fake_kernel32.address = address
            read_count.value = size
            return True

        fake_kernel32.ReadProcessMemory = read_process_memory

        with patch.object(scanner_win, "ctypes", _FakeCtypes):
            with patch("gh_ui_cli.wechat.adapters.scanner_win._kernel32", return_value=fake_kernel32):
                out = scanner_win._read_mem("handle", 1234, 4)

        self.assertEqual(out, b"abcd")
        self.assertEqual(fake_kernel32.address, ("c_void_p", 1234))


if __name__ == "__main__":
    unittest.main()
