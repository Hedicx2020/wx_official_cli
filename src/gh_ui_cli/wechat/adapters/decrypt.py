"""批量解密：把 db_dir 下所有可解密的 .db 解密到 cache_dir。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .crypto import full_decrypt, apply_wal


def decrypt_all_dbs(db_dir: str, key_map: dict[str, str], cache_dir: str | None = None) -> dict[str, str]:
    """把 db_dir 下所有 .db 解密到 cache_dir，返回 {rel_path: cache_abs_path}。

    db_dir 内子目录结构保留。key_map 是 salt_hex -> enc_key_hex。
    """
    out_dir = Path(cache_dir or os.path.join(tempfile.gettempdir(), "gh_wx_cache"))
    out_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    for root, _dirs, names in os.walk(db_dir):
        for name in names:
            if not name.endswith(".db") or name.endswith(("-wal", "-shm")):
                continue
            src = os.path.join(root, name)
            try:
                with open(src, "rb") as f:
                    salt = f.read(16).hex()
            except OSError:
                continue
            key_hex = key_map.get(salt)
            if not key_hex:
                continue
            try:
                key = bytes.fromhex(key_hex)
            except ValueError:
                continue
            rel = os.path.relpath(src, db_dir)
            dst = out_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                full_decrypt(src, str(dst), key)
            except Exception:
                continue
            wal_src = src + "-wal"
            if os.path.exists(wal_src):
                try:
                    apply_wal(wal_src, str(dst), key)
                except Exception:
                    pass
            mapping[rel] = str(dst)
    return mapping
