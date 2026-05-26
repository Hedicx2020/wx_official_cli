"""SQLCipher 4 解密算法单元测试。

构造 known-good 加密 page 验证 decrypt_page 与 verify_enc_key 的逆/正逻辑。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from Crypto.Cipher import AES

from gh_ui_cli.wechat.adapters import crypto


def _build_encrypted_db(enc_key: bytes, pages: int = 2, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """造一个简单的 SQLCipher 4 加密 db 字节串，返回 (db_bytes, page1_salt)。"""
    salt = salt or os.urandom(crypto.SALT_SZ)
    out = bytearray()
    for pgno in range(1, pages + 1):
        if pgno == 1:
            plain = b"\x00" * (crypto.PAGE_SZ - crypto.SALT_SZ - crypto.RESERVE_SZ)
            plain = plain[: ((len(plain) // 16) * 16)]
            iv = os.urandom(16)
            enc = AES.new(enc_key, AES.MODE_CBC, iv).encrypt(plain)
            page = bytearray(crypto.PAGE_SZ)
            page[: crypto.SALT_SZ] = salt
            page[crypto.SALT_SZ: crypto.SALT_SZ + len(enc)] = enc
            page[crypto.IV_OFFSET: crypto.IV_OFFSET + 16] = iv
            # HMAC tail
            mac_salt = bytes(b ^ 0x3A for b in salt)
            mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=32)
            hmac_data = bytes(page[crypto.SALT_SZ: crypto.PAGE_SZ - 64])
            h = hmac.new(mac_key, hmac_data, hashlib.sha512)
            h.update(struct.pack("<I", 1))
            page[crypto.PAGE_SZ - 64: crypto.PAGE_SZ] = h.digest()
            out.extend(bytes(page))
        else:
            plain = b"\x00" * crypto.IV_OFFSET
            plain = plain[: ((len(plain) // 16) * 16)]
            iv = os.urandom(16)
            enc = AES.new(enc_key, AES.MODE_CBC, iv).encrypt(plain)
            page = bytearray(crypto.PAGE_SZ)
            page[: len(enc)] = enc
            page[crypto.IV_OFFSET: crypto.IV_OFFSET + 16] = iv
            out.extend(bytes(page))
    return bytes(out), salt


class CryptoTest(unittest.TestCase):
    def test_decrypt_page_round_trip_page1(self):
        enc_key = os.urandom(32)
        db, _salt = _build_encrypted_db(enc_key, pages=1)
        page1 = db[: crypto.PAGE_SZ]
        plain = crypto.decrypt_page(enc_key, page1, 1)
        self.assertEqual(len(plain), crypto.PAGE_SZ)
        self.assertTrue(plain.startswith(b"SQLite format 3\x00"))

    def test_decrypt_page_round_trip_page2(self):
        enc_key = os.urandom(32)
        db, _salt = _build_encrypted_db(enc_key, pages=2)
        page2 = db[crypto.PAGE_SZ:]
        plain = crypto.decrypt_page(enc_key, page2, 2)
        self.assertEqual(len(plain), crypto.PAGE_SZ)

    def test_decrypt_page_rejects_wrong_size(self):
        enc_key = os.urandom(32)
        with self.assertRaises(ValueError):
            crypto.decrypt_page(enc_key, b"too short", 1)

    def test_full_decrypt_writes_dst(self):
        enc_key = os.urandom(32)
        db, _salt = _build_encrypted_db(enc_key, pages=3)
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.db"
            dst = Path(tmp) / "dst.db"
            src.write_bytes(db)
            n = crypto.full_decrypt(str(src), str(dst), enc_key)
            self.assertEqual(n, 3)
            blob = dst.read_bytes()
            self.assertTrue(blob.startswith(b"SQLite format 3\x00"))
            self.assertEqual(len(blob), 3 * crypto.PAGE_SZ)


if __name__ == "__main__":
    unittest.main()
