"""Windows 微信进程内存扫描.

通过 ctypes 直接调用 kernel32.OpenProcess + VirtualQueryEx + ReadProcessMemory,
不依赖任何外部 binary. 需要管理员权限 (微信 4.x 进程权限较松, 普通管理员即可).

extract_keys(db_dir) -> dict[str, str]   # salt_hex -> enc_key_hex
"""

from __future__ import annotations

import re
import subprocess
import time
from typing import Optional

from .key_scan import collect_db_files, scan_buffer

# 仅 Windows 时 import ctypes (其他平台 import 模块仍要不报错)
try:  # noqa: SIM105 - 避免运行时 raise
    import ctypes
    import ctypes.wintypes as wt
except Exception:  # pragma: no cover - 非 Windows
    ctypes = None  # type: ignore[assignment]
    wt = None  # type: ignore[assignment]


MEM_COMMIT = 0x1000
# 可读内存保护标志
READABLE_PROTECTS = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}
# 进程访问权限: PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
PROC_ACCESS = 0x0010 | 0x0400


def _kernel32():
    if ctypes is None:
        raise RuntimeError("scanner_win 仅在 Windows 可用")
    return ctypes.windll.kernel32


class _MBI(ctypes.Structure if ctypes else object):  # type: ignore[misc]
    if ctypes is not None:
        _fields_ = [
            ("BaseAddress", ctypes.c_uint64),
            ("AllocationBase", ctypes.c_uint64),
            ("AllocationProtect", wt.DWORD),
            ("_pad1", wt.DWORD),
            ("RegionSize", ctypes.c_uint64),
            ("State", wt.DWORD),
            ("Protect", wt.DWORD),
            ("Type", wt.DWORD),
            ("_pad2", wt.DWORD),
        ]


def _list_weixin_pids() -> list[tuple[int, int]]:
    """返回 [(pid, mem_kb), ...] 按内存降序排列."""
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, timeout=15,
    )
    pids: list[tuple[int, int]] = []
    for line in (out.stdout or "").strip().splitlines():
        cells = line.strip('"').split('","')
        if len(cells) < 5:
            continue
        try:
            pid = int(cells[1])
            mem_kb = int(cells[4].replace(",", "").replace(" K", "").strip() or "0")
        except ValueError:
            continue
        pids.append((pid, mem_kb))
    pids.sort(key=lambda x: x[1], reverse=True)
    return pids


def _read_mem(h, addr: int, size: int) -> Optional[bytes]:
    k = _kernel32()
    buf = ctypes.create_string_buffer(size)  # type: ignore[union-attr]
    n = ctypes.c_size_t(0)  # type: ignore[union-attr]
    ok = k.ReadProcessMemory(h, ctypes.c_uint64(addr), buf, size, ctypes.byref(n))  # type: ignore[union-attr]
    if not ok:
        return None
    return buf.raw[: n.value]


def _enum_regions(h) -> list[tuple[int, int]]:
    """返回 [(base, size), ...] 中所有可读、已提交、< 500MB 的区域."""
    k = _kernel32()
    regions: list[tuple[int, int]] = []
    addr = 0
    mbi = _MBI()
    while addr < 0x7FFF_FFFF_FFFF:
        if k.VirtualQueryEx(h, ctypes.c_uint64(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:  # type: ignore[union-attr]
            break
        if (
            mbi.State == MEM_COMMIT
            and mbi.Protect in READABLE_PROTECTS
            and 0 < mbi.RegionSize < 500 * 1024 * 1024
        ):
            regions.append((mbi.BaseAddress, mbi.RegionSize))
        nxt = mbi.BaseAddress + mbi.RegionSize
        if nxt <= addr:
            break
        addr = nxt
    return regions


def extract_keys(db_dir: str, on_log=None) -> dict[str, str]:
    """扫所有 Weixin.exe 内存, 返回 salt_hex -> enc_key_hex.

    Raises:
        RuntimeError: 非 Windows 调用 / 微信未运行 / 全部进程都打不开.
    """
    if ctypes is None:
        raise RuntimeError("scanner_win.extract_keys 只能在 Windows 上运行")

    log = on_log or (lambda *_args, **_kw: None)
    db_files, salt_map = collect_db_files(db_dir)
    if not salt_map:
        raise RuntimeError(f"未在 {db_dir} 找到任何 .db 文件")

    pids = _list_weixin_pids()
    if not pids:
        raise RuntimeError("Weixin.exe 未运行, 请先打开并登录微信")

    log(f"找到 {len(db_files)} 个数据库, {len(salt_map)} 个 salt; {len(pids)} 个 Weixin.exe 进程")

    key_map: dict[str, str] = {}
    remaining = set(salt_map.keys())
    started = time.time()

    def on_found(salt: str, key: str, dbs: list[str]) -> None:
        log(f"[FOUND] salt={salt} key={key} dbs={','.join(dbs)}")

    k = _kernel32()
    for pid, _mem in pids:
        h = k.OpenProcess(PROC_ACCESS, False, pid)
        if not h:
            log(f"[WARN] OpenProcess({pid}) 失败 (errno={ctypes.get_last_error()})")  # type: ignore[union-attr]
            continue
        try:
            regions = _enum_regions(h)
            log(f"扫描 PID={pid}: {len(regions)} 区域")
            for base, size in regions:
                buf = _read_mem(h, base, size)
                if not buf:
                    continue
                scan_buffer(buf, db_files, salt_map, key_map, remaining, on_found=on_found)
                if not remaining:
                    break
        finally:
            k.CloseHandle(h)
        if not remaining:
            break

    elapsed = time.time() - started
    log(f"扫描结束: {len(key_map)}/{len(salt_map)} 命中, 耗时 {elapsed:.1f}s")
    return key_map
