"""密钥扫描算法测试 - 模拟内存中 hex 模式与 salt 配对。"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gh_ui_cli.wechat.adapters import crypto, key_scan
from tests.wechat.test_crypto import _build_encrypted_db


def _make_db(tmp: Path, name: str, enc_key: bytes, salt: bytes | None = None) -> bytes:
    """造一个合法 page1 db 并返回 salt。"""
    db, salt_out = _build_encrypted_db(enc_key, pages=1, salt=salt)
    (tmp / name).write_bytes(db)
    return salt_out


class VerifyEncKeyTest(unittest.TestCase):
    def test_correct_key_passes(self):
        enc_key = os.urandom(32)
        db, _salt = _build_encrypted_db(enc_key, pages=1)
        self.assertTrue(key_scan.verify_enc_key(enc_key, db[: crypto.PAGE_SZ]))

    def test_wrong_key_fails(self):
        enc_key = os.urandom(32)
        bad_key = os.urandom(32)
        db, _salt = _build_encrypted_db(enc_key, pages=1)
        self.assertFalse(key_scan.verify_enc_key(bad_key, db[: crypto.PAGE_SZ]))

    def test_short_page_fails(self):
        self.assertFalse(key_scan.verify_enc_key(os.urandom(32), b"x" * 100))


class CollectDbFilesTest(unittest.TestCase):
    def test_finds_db_under_dir(self):
        enc_key = os.urandom(32)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "msg").mkdir()
            salt1 = _make_db(root / "msg", "msg.db", enc_key)
            salt2 = _make_db(root, "media.db", enc_key)
            files, salt_map = key_scan.collect_db_files(str(root))
            paths = {f.rel: f for f in files}
            self.assertIn("media.db", paths)
            self.assertIn(str(Path("msg") / "msg.db"), paths)
            self.assertIn(salt1.hex(), salt_map)
            self.assertIn(salt2.hex(), salt_map)

    def test_skips_too_small(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "tiny.db").write_bytes(b"x" * 100)
            files, _ = key_scan.collect_db_files(tmp)
            self.assertEqual(files, [])

    def test_skips_wal_shm(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "x.db-wal").write_bytes(b"x" * crypto.PAGE_SZ)
            (Path(tmp) / "x.db-shm").write_bytes(b"x" * crypto.PAGE_SZ)
            files, _ = key_scan.collect_db_files(tmp)
            self.assertEqual(files, [])


class ScanBufferTest(unittest.TestCase):
    def _setup(self, tmp: Path):
        enc_key = os.urandom(32)
        salt = _make_db(tmp, "test.db", enc_key)
        files, salt_map = key_scan.collect_db_files(str(tmp))
        return enc_key, salt, files, salt_map

    def test_scan_finds_64_byte_hex(self):
        with TemporaryDirectory() as tmp:
            enc_key, salt, files, salt_map = self._setup(Path(tmp))
            buf = b"foo x'" + enc_key.hex().encode() + b"' bar"
            key_map: dict[str, str] = {}
            remaining = set(salt_map.keys())
            found_calls = []
            n = key_scan.scan_buffer(
                buf,
                files,
                salt_map,
                key_map,
                remaining,
                on_found=lambda s, k, paths: found_calls.append((s, k)),
            )
            self.assertEqual(n, 1)
            self.assertEqual(key_map.get(salt.hex()), enc_key.hex())
            self.assertEqual(len(found_calls), 1)

    def test_scan_finds_96_byte_combined(self):
        with TemporaryDirectory() as tmp:
            enc_key, salt, files, salt_map = self._setup(Path(tmp))
            combined = enc_key.hex() + salt.hex()
            buf = b"x'" + combined.encode() + b"'"
            key_map: dict[str, str] = {}
            remaining = set(salt_map.keys())
            n = key_scan.scan_buffer(buf, files, salt_map, key_map, remaining)
            self.assertEqual(n, 1)
            self.assertEqual(key_map.get(salt.hex()), enc_key.hex())

    def test_scan_wrong_key_no_match(self):
        with TemporaryDirectory() as tmp:
            _enc_key, _salt, files, salt_map = self._setup(Path(tmp))
            wrong = os.urandom(32).hex()
            buf = b"x'" + wrong.encode() + b"'"
            key_map: dict[str, str] = {}
            remaining = set(salt_map.keys())
            n = key_scan.scan_buffer(buf, files, salt_map, key_map, remaining)
            self.assertEqual(n, 1)  # matched 1 hex pattern
            self.assertEqual(key_map, {})


if __name__ == "__main__":
    unittest.main()
