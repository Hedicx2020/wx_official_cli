"""SQLCipher 4 解密 -- 纯 Python 实现。

直接搬运自 gh_quant_ui/api/wechat_native/crypto.py，逻辑等价。
SQLCipher 协议公开规范：
  PAGE_SZ = 4096
  SALT_SZ = 16  (在 page1 开头，构造 mac_salt = salt ^ 0x3A)
  RESERVE = 80 = IV(16) + HMAC-SHA512(64)  (在每页末尾)
  KDF: PBKDF2-SHA512, 256000 iter (cipher_key), 2 iter (mac_key, dklen=32)
  encrypt: AES-256-CBC, IV = page[PAGE_SZ - RESERVE : PAGE_SZ - RESERVE + 16]
  page1 特殊：前 16 字节是 SALT，解密时输出 "SQLite format 3\\x00" + 解密内容

外部 API：
  decrypt_page(enc_key, page_data, pgno) -> bytes
  full_decrypt(src_db, dst_db, enc_key)  -> int  (返回 page 数)
  apply_wal(wal_path, dst_db, enc_key)   -> int  (返回回填 page 数)
"""

from __future__ import annotations

import os
import struct
from typing import Final

from Crypto.Cipher import AES

PAGE_SZ: Final = 4096
SALT_SZ: Final = 16
RESERVE_SZ: Final = 80
IV_OFFSET: Final = PAGE_SZ - RESERVE_SZ
SQLITE_HDR: Final = b"SQLite format 3\x00"

WAL_HEADER_SZ: Final = 32
WAL_FRAME_HEADER_SZ: Final = 24


def decrypt_page(enc_key: bytes, page_data: bytes, pgno: int) -> bytes:
    if len(page_data) != PAGE_SZ:
        raise ValueError(f"page size != {PAGE_SZ}: {len(page_data)}")
    iv = page_data[IV_OFFSET: IV_OFFSET + 16]
    if pgno == 1:
        encrypted = page_data[SALT_SZ: IV_OFFSET]
        plain = AES.new(enc_key, AES.MODE_CBC, iv).decrypt(encrypted)
        return SQLITE_HDR + plain + b"\x00" * RESERVE_SZ
    encrypted = page_data[:IV_OFFSET]
    plain = AES.new(enc_key, AES.MODE_CBC, iv).decrypt(encrypted)
    return plain + b"\x00" * RESERVE_SZ


def full_decrypt(src_db: str, dst_db: str, enc_key: bytes) -> int:
    file_size = os.path.getsize(src_db)
    total_pages = file_size // PAGE_SZ
    os.makedirs(os.path.dirname(dst_db) or ".", exist_ok=True)
    with open(src_db, "rb") as fin, open(dst_db, "wb") as fout:
        for pgno in range(1, total_pages + 1):
            page = fin.read(PAGE_SZ)
            if len(page) < PAGE_SZ:
                break
            fout.write(decrypt_page(enc_key, page, pgno))
    return total_pages


def apply_wal(wal_path: str, dst_db: str, enc_key: bytes) -> int:
    if not os.path.exists(wal_path):
        return 0
    wal_size = os.path.getsize(wal_path)
    if wal_size <= WAL_HEADER_SZ:
        return 0
    patched = 0
    with open(wal_path, "rb") as wf, open(dst_db, "r+b") as df:
        wal_hdr = wf.read(WAL_HEADER_SZ)
        wal_salt1 = struct.unpack(">I", wal_hdr[16:20])[0]
        wal_salt2 = struct.unpack(">I", wal_hdr[20:24])[0]
        frame_size = WAL_FRAME_HEADER_SZ + PAGE_SZ
        while wf.tell() + frame_size <= wal_size:
            fh = wf.read(WAL_FRAME_HEADER_SZ)
            if len(fh) < WAL_FRAME_HEADER_SZ:
                break
            pgno = struct.unpack(">I", fh[0:4])[0]
            fsalt1 = struct.unpack(">I", fh[8:12])[0]
            fsalt2 = struct.unpack(">I", fh[12:16])[0]
            ep = wf.read(PAGE_SZ)
            if len(ep) < PAGE_SZ:
                break
            if pgno == 0 or pgno > 1_000_000:
                continue
            if fsalt1 != wal_salt1 or fsalt2 != wal_salt2:
                continue
            plain = decrypt_page(enc_key, ep, pgno)
            df.seek((pgno - 1) * PAGE_SZ)
            df.write(plain)
            patched += 1
    return patched
