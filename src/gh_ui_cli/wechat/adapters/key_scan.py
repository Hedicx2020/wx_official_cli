"""本地微信数据库 key 候选校验与内存块扫描工具。

负责：
- 在 db_storage 下枚举 .db 文件，取 16 字节 salt
- 用 HMAC-SHA512 校验候选 enc_key 是否能匹配 page1
- 在二进制内存块中按正则匹配候选 hex 串
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import struct
from typing import Callable, Iterable

from .crypto import PAGE_SZ, SALT_SZ

KEY_SZ: int = 32
HMAC_LEN: int = 64
RESERVE_SZ: int = 80

HEX_PATTERN: re.Pattern[bytes] = re.compile(rb"x'([0-9a-fA-F]{64,192})'")


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


class DbFile:
    __slots__ = ("rel", "abs", "size", "salt_hex", "page1")

    def __init__(self, rel: str, abs_path: str, size: int, salt_hex: str, page1: bytes) -> None:
        self.rel = rel
        self.abs = abs_path
        self.size = size
        self.salt_hex = salt_hex
        self.page1 = page1


def collect_db_files(db_dir: str) -> tuple[list[DbFile], dict[str, list[str]]]:
    files: list[DbFile] = []
    salt_map: dict[str, list[str]] = {}
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
            files.append(DbFile(rel, full, size, salt, page1))
            salt_map.setdefault(salt, []).append(rel)
    return files, salt_map


def scan_buffer(
    buf: bytes,
    db_files: Iterable[DbFile],
    salt_map: dict[str, list[str]],
    key_map: dict[str, str],
    remaining_salts: set[str],
    on_found: Callable[[str, str, list[str]], None] | None = None,
) -> int:
    db_list = list(db_files)
    matches = 0
    for m in HEX_PATTERN.finditer(buf):
        hex_str = m.group(1).decode()
        matches += 1
        n = len(hex_str)

        if n == 96:
            enc_key_hex = hex_str[:64]
            salt_hex = hex_str[64:]
            if salt_hex not in remaining_salts:
                continue
            enc_key = bytes.fromhex(enc_key_hex)
            for db in db_list:
                if db.salt_hex == salt_hex and verify_enc_key(enc_key, db.page1):
                    key_map[salt_hex] = enc_key_hex
                    remaining_salts.discard(salt_hex)
                    if on_found:
                        on_found(salt_hex, enc_key_hex, salt_map[salt_hex])
                    break

        elif n == 64:
            if not remaining_salts:
                continue
            enc_key = bytes.fromhex(hex_str)
            for db in db_list:
                if db.salt_hex in remaining_salts and verify_enc_key(enc_key, db.page1):
                    key_map[db.salt_hex] = hex_str
                    remaining_salts.discard(db.salt_hex)
                    if on_found:
                        on_found(db.salt_hex, hex_str, salt_map[db.salt_hex])
                    break

        elif n > 96 and n % 2 == 0:
            enc_key_hex = hex_str[:64]
            salt_hex = hex_str[-32:]
            if salt_hex not in remaining_salts:
                continue
            enc_key = bytes.fromhex(enc_key_hex)
            for db in db_list:
                if db.salt_hex == salt_hex and verify_enc_key(enc_key, db.page1):
                    key_map[salt_hex] = enc_key_hex
                    remaining_salts.discard(salt_hex)
                    if on_found:
                        on_found(salt_hex, enc_key_hex, salt_map[salt_hex])
                    break

    return matches
