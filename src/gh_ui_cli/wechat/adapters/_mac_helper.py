"""macOS 内存扫描 helper -- 独立脚本, 只依赖 Python stdlib.

设计前提:
  * 通过 osascript "do shell script ... with administrator privileges" 由 root 启动
  * 启动用的 Python 解释器是 /usr/bin/python3 (macOS Command Line Tools 自带), 不是 venv
  * 因此本脚本**不能 import 项目其他模块**, 也不能用 pycryptodome / fastapi
  * HMAC 验证只用 hashlib (stdlib 自带 PBKDF2-SHA512); AES 通过 ctypes 调系统
    libSystem 里的 CCCrypt (CommonCrypto), 不需要 pycryptodome

模式:
  --mode db-key (默认): 扫 SQLCipher 数据库密钥. 输入 --db-dir.
  --mode image-key:     扫图片 AES 密钥. 输入 --dat-dir.
                        参考 ylytdeng/wechat-decrypt 的 pattern-based 批量验证思路.

输入:
  argv: --mode <db-key|image-key> --db-dir/--dat-dir <path> [--limit-mb 500]
输出:
  stdout: JSON {"keys": {pattern_hex: key_hex}, "log": [...], "error": null|"..."}
退出码:
  0 = 成功 (即使一个 key 都没扫到也是 0)
  1 = 致命错误
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import hashlib
import hmac
import json
import os
import re
import struct
import subprocess
import sys
import time

PAGE_SZ = 4096
SALT_SZ = 16
KEY_SZ = 32
HMAC_LEN = 64
HEX_RE = re.compile(rb"x'([0-9a-fA-F]{64,192})'")

# ─── mach API ─────────────────────────────────────
libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)

mach_task_self = libc.mach_task_self
mach_task_self.restype = ctypes.c_uint32

# kern_return_t task_for_pid(mach_port_name_t target_tport, int pid, mach_port_name_t *task)
libc.task_for_pid.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.POINTER(ctypes.c_uint32)]
libc.task_for_pid.restype = ctypes.c_int

# struct vm_region_basic_info_data_64_t (9 int32 words = 36 bytes)
VM_REGION_BASIC_INFO_64 = 9
VM_REGION_BASIC_INFO_COUNT_64 = 9
VM_PROT_READ = 0x1

libc.mach_vm_region.argtypes = [
    ctypes.c_uint32,                         # task
    ctypes.POINTER(ctypes.c_uint64),         # &addr
    ctypes.POINTER(ctypes.c_uint64),         # &size
    ctypes.c_int,                            # flavor
    ctypes.POINTER(ctypes.c_int * VM_REGION_BASIC_INFO_COUNT_64),
    ctypes.POINTER(ctypes.c_uint32),         # &count
    ctypes.POINTER(ctypes.c_uint32),         # &object_name
]
libc.mach_vm_region.restype = ctypes.c_int

libc.mach_vm_read.argtypes = [
    ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint64,
    ctypes.POINTER(ctypes.c_uint64),         # &data (vm_offset_t)
    ctypes.POINTER(ctypes.c_uint32),         # &dataCnt
]
libc.mach_vm_read.restype = ctypes.c_int

libc.mach_vm_deallocate.argtypes = [ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint64]
libc.mach_vm_deallocate.restype = ctypes.c_int

KERN_SUCCESS = 0


# ─── CommonCrypto (用于图片密钥扫描时的 AES 验证) ───
# CCCrypt 在 libSystem 里, libc 已经能解析符号
try:
    libc.CCCrypt.argtypes = [
        ctypes.c_uint32,   # CCOperation (kCCDecrypt = 1)
        ctypes.c_uint32,   # CCAlgorithm (kCCAlgorithmAES128 = 0)
        ctypes.c_uint32,   # CCOptions (kCCOptionPKCS7Padding=1, kCCOptionECBMode=2)
        ctypes.c_void_p,   # key
        ctypes.c_size_t,   # keyLength
        ctypes.c_void_p,   # iv (NULL for ECB)
        ctypes.c_void_p,   # dataIn
        ctypes.c_size_t,   # dataInLength
        ctypes.c_void_p,   # dataOut
        ctypes.c_size_t,   # dataOutAvailable
        ctypes.POINTER(ctypes.c_size_t),  # dataOutMoved
    ]
    libc.CCCrypt.restype = ctypes.c_int
    HAS_CCCRYPT = True
except Exception:
    HAS_CCCRYPT = False

CC_DECRYPT = 1
CC_AES = 0
CC_ECB = 2  # kCCOptionECBMode (no padding bit set: caller-managed)


# ─── 进程定位 ─────────────────────────────────────
def find_wechat_pids() -> list[int]:
    """同时找 WeChat (3.x) 和 Weixin (4.x)."""
    pids: list[int] = []
    for name in ("WeChat", "Weixin", "wechat", "weixin"):
        try:
            out = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True, timeout=5)
        except Exception:
            continue
        for line in out.stdout.split():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
    return sorted(set(pids))


# ─── HMAC 验证 ────────────────────────────────────
def verify_enc_key(enc_key: bytes, db_page1: bytes) -> bool:
    if len(db_page1) < PAGE_SZ:
        return False
    salt = db_page1[:SALT_SZ]
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SZ)
    hmac_data = db_page1[SALT_SZ: PAGE_SZ - HMAC_LEN]
    stored = db_page1[PAGE_SZ - HMAC_LEN: PAGE_SZ]
    h = hmac.new(mac_key, hmac_data, hashlib.sha512)
    h.update(struct.pack("<I", 1))
    return h.digest() == stored


# ─── DB 收集 ──────────────────────────────────────
def collect_dbs(db_dir: str):
    files = []
    salts: dict[str, list[str]] = {}
    for root, _dirs, names in os.walk(db_dir):
        for name in names:
            if not name.endswith(".db") or name.endswith(("-wal", "-shm")):
                continue
            full = os.path.join(root, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size < PAGE_SZ:
                continue
            try:
                with open(full, "rb") as f:
                    page1 = f.read(PAGE_SZ)
            except OSError:
                continue
            salt = page1[:SALT_SZ].hex()
            rel = os.path.relpath(full, db_dir)
            files.append({"path": full, "salt": salt, "page1": page1, "rel": rel})
            salts.setdefault(salt, []).append(rel)
    return files, salts


# ─── 内存扫描 ─────────────────────────────────────
def task_for_pid(pid: int) -> int:
    task = ctypes.c_uint32(0)
    rc = libc.task_for_pid(mach_task_self(), pid, ctypes.byref(task))
    if rc != KERN_SUCCESS:
        raise RuntimeError(f"task_for_pid({pid}) kr={rc} errno={ctypes.get_errno()}")
    return task.value


def enum_readable_regions(task: int, max_size: int = 500 * 1024 * 1024):
    addr = ctypes.c_uint64(0)
    while True:
        size = ctypes.c_uint64(0)
        info = (ctypes.c_int * VM_REGION_BASIC_INFO_COUNT_64)()
        cnt = ctypes.c_uint32(VM_REGION_BASIC_INFO_COUNT_64)
        obj = ctypes.c_uint32(0)
        rc = libc.mach_vm_region(
            task, ctypes.byref(addr), ctypes.byref(size),
            VM_REGION_BASIC_INFO_64, info, ctypes.byref(cnt), ctypes.byref(obj),
        )
        if rc != KERN_SUCCESS:
            break
        prot = info[0]   # vm_prot_t protection
        if (prot & VM_PROT_READ) and 0 < size.value < max_size:
            yield (addr.value, size.value)
        new_addr = addr.value + size.value
        if new_addr <= addr.value:
            break
        addr.value = new_addr


def read_region(task: int, addr: int, size: int) -> bytes | None:
    data = ctypes.c_uint64(0)
    dcnt = ctypes.c_uint32(0)
    rc = libc.mach_vm_read(task, addr, size, ctypes.byref(data), ctypes.byref(dcnt))
    if rc != KERN_SUCCESS:
        return None
    try:
        buf = ctypes.string_at(data.value, dcnt.value)
    finally:
        libc.mach_vm_deallocate(mach_task_self(), data.value, dcnt.value)
    return buf


def scan_buffer(buf, files, salts, key_map, remaining, diag):
    """diag = {"by_len": Counter, "salt_samples": list, "key_samples": list,
              "match_no_hmac": int}.

    新增策略 (与 wechat-cli C 实现对齐):
      * 96 hex: 后 32 hex 直接与已知 salt 配对, 配对成功即认为命中 (跳过 HMAC).
        HMAC 单独再做一次以决定是否入 remaining (有则更可信), 但不阻塞命中.
      * 64 hex: 仍走 HMAC 验证.
    """
    matches = 0
    for m in HEX_RE.finditer(buf):
        hex_str = m.group(1).decode().lower()
        matches += 1
        n = len(hex_str)
        diag["by_len"][n] = diag["by_len"].get(n, 0) + 1

        if n == 96 or (n > 96 and n % 2 == 0):
            enc_hex = hex_str[:64]
            salt_hex = hex_str[64:96] if n == 96 else hex_str[-32:]
            if len(diag["salt_samples"]) < 8:
                diag["salt_samples"].append(salt_hex)
            if salt_hex in remaining:
                try:
                    enc_key = bytes.fromhex(enc_hex)
                except ValueError:
                    continue
                for f in files:
                    if f["salt"] == salt_hex:
                        # 先 HMAC, 失败也按 C 实现兜底直接入 (旁路标记)
                        ok = verify_enc_key(enc_key, f["page1"])
                        if not ok:
                            diag["match_no_hmac"] += 1
                        key_map[salt_hex] = enc_hex
                        remaining.discard(salt_hex)
                        break
        elif n == 64:
            if len(diag["key_samples"]) < 8:
                diag["key_samples"].append(hex_str)
            if not remaining:
                continue
            try:
                enc_key = bytes.fromhex(hex_str)
            except ValueError:
                continue
            for f in files:
                if f["salt"] in remaining and verify_enc_key(enc_key, f["page1"]):
                    key_map[f["salt"]] = hex_str
                    remaining.discard(f["salt"])
                    break
    return matches


# ─── 图片密钥扫描 (image-key mode) ───────────────
V4_SIG = b"\x07\x08V2\x08\x07"


def aes_ecb_decrypt(key: bytes, ct: bytes) -> bytes | None:
    """用 CommonCrypto 做 AES-128-ECB 单/多块解密 (无 padding).

    ct 长度必须是 16 的倍数. 失败返回 None.
    """
    if not HAS_CCCRYPT or len(key) != 16 or len(ct) == 0 or len(ct) % 16 != 0:
        return None
    out = (ctypes.c_ubyte * len(ct))()
    moved = ctypes.c_size_t(0)
    rc = libc.CCCrypt(
        CC_DECRYPT, CC_AES, CC_ECB,
        key, len(key),
        None,
        ct, len(ct),
        out, len(ct),
        ctypes.byref(moved),
    )
    if rc != 0 or moved.value == 0:
        return None
    return bytes(out[: moved.value])


def is_image_magic(data: bytes) -> bool:
    """识别图像 magic, 验证 AES 解密结果是否为合法图像头.

    强化检查 (相对原 3 字节版): JPEG 必须满足 SOI + 合法 marker; BMP 必须有合理 data offset.
    弱检查时一份 600MB 内存可能命中数百个假阳性 (随机 16 字节 ECB 解出 FFD8FF 概率 1/2^24).
    """
    if len(data) < 8:
        return False
    # JPEG: FF D8 FF + 第 4 字节是合法 marker (E0=JFIF, E1=EXIF, E2=ICC, DB=DQT, C0=SOF0, C4=DHT 等)
    if data[:3] == b"\xFF\xD8\xFF":
        return data[3] in (0xE0, 0xE1, 0xE2, 0xE3, 0xE8, 0xEE, 0xDB, 0xC0, 0xC4, 0xFE)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:2] == b"BM" and len(data) >= 14:
        # BMP: 11-14 字节是 pixel data offset, 合理范围 [14, 0x1000]
        offset = int.from_bytes(data[10:14], "little")
        return 14 <= offset <= 0x1000
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    return False


def collect_dat_patterns(dat_dir: str, max_files: int = 200) -> list[dict]:
    """收集 V4 .dat 文件的前 16 字节 AES ciphertext 作为 pattern.

    每个 pattern: {"ct": 16 字节, "ct_hex": str, "rel": str}
    多个 .dat 可能用同一 key, 所以同 ct 去重.
    """
    seen: dict[str, dict] = {}
    for root, _dirs, names in os.walk(dat_dir):
        for name in names:
            if not name.lower().endswith(".dat"):
                continue
            full = os.path.join(root, name)
            try:
                with open(full, "rb") as f:
                    head = f.read(15 + 16)
            except OSError:
                continue
            if len(head) < 31 or head[:6] != V4_SIG:
                continue
            ct = head[15:31]
            ct_hex = ct.hex()
            if ct_hex in seen:
                continue
            seen[ct_hex] = {"ct": ct, "ct_hex": ct_hex, "rel": os.path.relpath(full, dat_dir)}
            if len(seen) >= max_files:
                break
        if len(seen) >= max_files:
            break
    return list(seen.values())


def scan_buffer_image(buf: bytes, patterns: list[dict], key_hits: dict[str, int], diag: dict) -> int:
    """对一个内存 buffer 做 16 字节对齐的候选 key 扫描, 累积每个 key 的命中数.

    与旧版差异:
      * 不在第一次命中后剔除 pattern; 而是统计每个候选 key 解出多少 pattern
      * 真实密钥可解全部同会话图片 (count 高); 假阳性只能解 1 个 (count = 1)
      * 上层根据 key_hits 排序, 取 hit 最高的几个作为权威密钥
    """
    if not patterns:
        return 0

    batch_ct = b"".join(p["ct"] for p in patterns)
    n_pat = len(patterns)
    matches = 0

    n = len(buf) - 16
    i = 0
    while i <= n:
        key = buf[i:i + 16]
        # 排除明显无效 key
        if key not in (b"\x00" * 16, b"\xFF" * 16):
            pt = aes_ecb_decrypt(key, batch_ct)
            if pt is not None:
                hits = 0
                for j in range(n_pat):
                    if is_image_magic(pt[j * 16:(j + 1) * 16]):
                        hits += 1
                if hits > 0:
                    key_hex = key.hex()
                    prev = key_hits.get(key_hex, 0)
                    if hits > prev:
                        key_hits[key_hex] = hits
                    matches += hits
                    if hits >= 3 and len(diag["solved_samples"]) < 5:
                        diag["solved_samples"].append({
                            "key": key_hex, "hits": hits, "of": n_pat,
                        })
        i += 16

    return matches


def run_image_key_mode(dat_dir: str, limit_mb: int, log: list, output: dict) -> int:
    if not HAS_CCCRYPT:
        output["error"] = "CommonCrypto (CCCrypt) 不可用, 无法做 AES 验证"
        return 1
    if not os.path.isdir(dat_dir):
        output["error"] = f"dat-dir 不存在: {dat_dir}"
        return 1

    patterns = collect_dat_patterns(dat_dir)
    log.append(f"collected {len(patterns)} V4 dat patterns from {dat_dir}")
    if not patterns:
        output["error"] = "未在 dat-dir 中找到 V4 格式 .dat 文件"
        return 1

    pids = find_wechat_pids()
    log.append(f"wechat pids: {pids}")
    if not pids:
        output["error"] = "WeChat / Weixin process not running"
        return 1

    key_hits: dict[str, int] = {}  # key_hex → 该 key 解出多少 pattern
    diag = {"solved_samples": [], "regions_scanned": 0, "bytes_scanned": 0}
    started = time.time()

    for pid in pids:
        try:
            task = task_for_pid(pid)
        except Exception as e:
            log.append(f"task_for_pid {pid} failed: {e}")
            continue
        for addr, size in enum_readable_regions(task, max_size=limit_mb * 1024 * 1024):
            buf = read_region(task, addr, size)
            if buf is None:
                continue
            diag["regions_scanned"] += 1
            diag["bytes_scanned"] += len(buf)
            scan_buffer_image(buf, patterns, key_hits, diag)

    elapsed = time.time() - started

    # 取命中数 ≥ 2 的 key 作为权威密钥; 只命中 1 的多半假阳性, 但保留前 8 个备用
    sorted_keys = sorted(key_hits.items(), key=lambda kv: kv[1], reverse=True)
    primary_keys = [k for k, c in sorted_keys if c >= 2]
    if not primary_keys and sorted_keys:
        primary_keys = [sorted_keys[0][0]]  # 兜底: pattern 太少时也得给一个
    extra_keys = [k for k, c in sorted_keys[:8] if c < 2 and k not in primary_keys]

    # 用 primary_keys 顺序解每个 pattern, 第一个能解开就赋值
    key_map: dict[str, str] = {}
    for p in patterns:
        for kh in primary_keys + extra_keys:
            pt = aes_ecb_decrypt(bytes.fromhex(kh), p["ct"])
            if pt and is_image_magic(pt):
                key_map[p["ct_hex"]] = kh
                break

    log.append(
        f"image-key done in {elapsed:.1f}s, "
        f"unique_keys={len(key_hits)}, primary(>=2)={len(primary_keys)}, "
        f"solved={len(key_map)}/{len(patterns)}, "
        f"regions={diag['regions_scanned']}, bytes={diag['bytes_scanned'] // (1024 * 1024)}MB"
    )
    if sorted_keys[:5]:
        log.append("top5 key hits: " + ", ".join(f"{k[:8]}..={c}" for k, c in sorted_keys[:5]))

    output["keys"] = key_map
    output["primary_keys"] = primary_keys
    output["diag"] = diag
    return 0


# ─── main ─────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["db-key", "image-key"], default="db-key")
    ap.add_argument("--db-dir", default=None)
    ap.add_argument("--dat-dir", default=None)
    ap.add_argument("--limit-mb", type=int, default=500)
    args = ap.parse_args()

    log: list[str] = []
    output = {"keys": {}, "log": log, "error": None, "mode": args.mode}

    if args.mode == "image-key":
        rc = run_image_key_mode(args.dat_dir or "", args.limit_mb, log, output)
        json.dump(output, sys.stdout, ensure_ascii=False)
        return rc

    # db-key 模式 (默认)
    db_dir = args.db_dir
    if not db_dir or not os.path.isdir(db_dir):
        output["error"] = f"db_dir not found: {db_dir}"
        json.dump(output, sys.stdout, ensure_ascii=False)
        return 1

    files, salts = collect_dbs(db_dir)
    log.append(f"collected {len(files)} db, {len(salts)} salts")
    if not salts:
        output["error"] = "no .db files in db_dir"
        json.dump(output, sys.stdout, ensure_ascii=False)
        return 1

    pids = find_wechat_pids()
    log.append(f"wechat pids: {pids}")
    if not pids:
        output["error"] = "WeChat / Weixin process not running"
        json.dump(output, sys.stdout, ensure_ascii=False)
        return 1

    key_map: dict[str, str] = {}
    remaining = set(salts.keys())
    total_matches = 0
    diag = {"by_len": {}, "salt_samples": [], "key_samples": [], "match_no_hmac": 0}
    started = time.time()

    for pid in pids:
        try:
            task = task_for_pid(pid)
        except Exception as e:
            log.append(f"task_for_pid {pid} failed: {e}")
            continue
        regions = list(enum_readable_regions(task, max_size=args.limit_mb * 1024 * 1024))
        log.append(f"pid={pid} regions={len(regions)}")
        for addr, size in regions:
            buf = read_region(task, addr, size)
            if buf:
                total_matches += scan_buffer(buf, files, salts, key_map, remaining, diag)
            if not remaining:
                break
        if not remaining:
            break

    elapsed = time.time() - started
    log.append(f"done in {elapsed:.1f}s, hits={len(key_map)}/{len(salts)}, hex_matches={total_matches}")
    log.append(f"hex 长度分布: {diag['by_len']}")
    log.append(f"扫到的 96-hex 后32位 sample (前8): {diag['salt_samples']}")
    log.append(f"已知 db salts (前8): {sorted(salts.keys())[:8]}")
    log.append(f"96-hex 长度命中但 HMAC 失败次数: {diag['match_no_hmac']}")
    if diag.get("key_samples"):
        log.append(f"扫到的 64-hex sample (前8): {diag['key_samples'][:8]}")
    output["keys"] = key_map
    output["diag"] = diag
    json.dump(output, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
