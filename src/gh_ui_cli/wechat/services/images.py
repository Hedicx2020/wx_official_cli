"""微信 .dat 图片解密与转换。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .. import paths
from ..errors import WechatDataMissing
from ..registry import capability
from . import keys as keys_svc


def _dat_root() -> Path | None:
    """微信 v4 把图片放在 db_storage 同级的 msg/ 或 image/ 下；按本机 layout 找。"""
    db_dir = keys_svc.resolve_db_dir()
    if not db_dir:
        return None
    p = Path(db_dir).parent
    # 4.x layout: ../msg/attach/<biz>/...
    return p


def list_images(month: str | None = None, limit: int = 100) -> dict[str, Any]:
    root = _dat_root()
    if root is None or not root.exists():
        return {"items": [], "total": 0}
    out: list[dict] = []
    for path in root.rglob("*.dat"):
        if month and month not in str(path):
            continue
        out.append({
            "path": str(path),
            "size": path.stat().st_size,
            "name": path.name,
        })
        if len(out) >= limit:
            break
    return {"items": out, "total": len(out)}


def list_months() -> dict[str, Any]:
    root = _dat_root()
    if root is None or not root.exists():
        return {"months": []}
    months: set[str] = set()
    for path in root.rglob("*.dat"):
        parts = str(path).split(os.sep)
        for p in parts:
            if len(p) == 7 and p[4] == "-" and p[:4].isdigit():  # YYYY-MM
                months.add(p)
    return {"months": sorted(months, reverse=True)}


def convert(dat_path: str, aes_key: str, xor_key: int, output_dir: str | None = None) -> dict[str, Any]:
    src = Path(dat_path)
    if not src.exists():
        raise WechatDataMissing(f"file not found: {dat_path}")
    from ..adapters import dat_to_image
    out_dir = Path(output_dir) if output_dir else paths.images_cache_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    decryptor = dat_to_image.DatImageDecryptor(xor_key=xor_key, aes_key=aes_key)
    try:
        data = decryptor.decrypt_v4(str(src), aes_key, xor_key)
        fmt = dat_to_image.detect_image_format(data) or "bin"
        dst = out_dir / (src.stem + "." + fmt)
        dst.write_bytes(data)
    except dat_to_image.DatDecryptError as e:
        return {"status": "error", "message": str(e), "source": str(src), "code": type(e).__name__}
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}", "source": str(src)}
    return {"status": "ok", "source": str(src), "output": str(dst), "format": fmt}


@capability("op:wechat:image-list")
def _cap_list(payload: dict) -> dict:
    return list_images(month=payload.get("month"), limit=int(payload.get("limit") or 100))


@capability("op:wechat:image-months")
def _cap_months(_payload: dict) -> dict:
    return list_months()


@capability("op:wechat:image-convert")
def _cap_convert(payload: dict) -> dict:
    return convert(
        dat_path=str(payload.get("dat_path") or ""),
        aes_key=str(payload.get("aes_key") or ""),
        xor_key=int(payload.get("xor_key") or 0),
        output_dir=payload.get("output_dir"),
    )
