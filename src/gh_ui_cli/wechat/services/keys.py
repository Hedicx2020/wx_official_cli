"""密钥与解密路径服务。

对应原 wechat.py 中的：
  /password/status              -> password_status
  /password/auto                -> password_auto (本地版)
  内部 _detect_platform_paths   -> detect_platform_paths
  内部 _resolve_db_dir          -> resolve_db_dir
  内部 _save_keys / _load_keys  -> save_keys / load_keys
"""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path

from .. import paths
from ..errors import KeyNotFound, PlatformUnsupported, WechatError
from ..registry import capability
from . import config as config_svc


def load_keys() -> dict[str, str]:
    p = paths.keys_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_keys(key_map: dict[str, str]) -> None:
    p = paths.keys_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(key_map, indent=2), encoding="utf-8")
    tmp.replace(p)


def detect_platform_paths() -> dict[str, str]:
    """与原版相同：v4 优先，v3 fallback；Windows 看 ~/xwechat_files。"""
    sys_name = platform.system()
    home = Path(os.environ.get("HOME") or str(Path.home()))
    candidates: list[Path] = []
    if sys_name == "Darwin":
        candidates.append(home / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files")
        candidates.append(home / "Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/com.tencent.xinWeChat")
    elif sys_name == "Windows":
        candidates.append(home / "xwechat_files")
        candidates.append(home / "Documents" / "xwechat_files")
    elif sys_name == "Linux":
        candidates.append(home / ".local/share/xwechat_files")

    detected = ""
    for c in candidates:
        if not c.exists():
            continue
        for sub in c.rglob("db_storage"):
            if sub.is_dir():
                detected = str(sub)
                break
        if detected:
            break
        detected = str(c)
        break
    return {
        "platform": "darwin" if sys_name == "Darwin" else sys_name.lower(),
        "detected_path": detected,
    }


def resolve_db_dir() -> str:
    cur = config_svc.load()
    p = (cur.get("wechat_files_path") or "").strip()
    if p and Path(p).exists():
        return p
    return detect_platform_paths()["detected_path"]


def password_status() -> dict:
    cur = config_svc.load()
    plat = detect_platform_paths()
    keys = load_keys()
    return {
        "platform": plat["platform"],
        "detected_path": plat["detected_path"],
        "configured_path": cur.get("wechat_files_path", ""),
        "has_password": bool(cur.get("database_password")),
        "key_count": len(keys),
    }


def password_auto() -> dict:
    """扫描微信进程内存提取密钥。平台相关。"""
    db_dir = resolve_db_dir()
    if not db_dir or not Path(db_dir).exists():
        return {
            "status": "error",
            "code": "NO_WECHAT_PATH",
            "message": "未检测到微信数据库目录。请打开微信登录后再试，或在「配置」Tab 手动填写 wechat_files_path。",
        }

    sys_name = platform.system()
    log_lines: list[str] = []

    def on_log(msg: str) -> None:
        log_lines.append(msg)

    try:
        if sys_name == "Windows":
            from ..adapters import scanner_win
            key_map = scanner_win.extract_keys(db_dir, on_log=on_log)
        elif sys_name == "Darwin":
            from ..adapters import scanner_mac
            key_map = scanner_mac.extract_keys(db_dir, on_log=on_log)
        else:
            return {
                "status": "error",
                "code": "PLATFORM_UNSUPPORTED",
                "message": f"暂不支持当前平台: {sys_name}",
            }
    except RuntimeError as e:
        msg = str(e)
        for code in ("RESIGN_NEEDED", "USER_CANCELLED", "NO_WECHAT"):
            prefix = f"{code}:"
            if msg.startswith(prefix):
                return {
                    "status": "error",
                    "code": code,
                    "message": msg[len(prefix):].strip(),
                    "log": "\n".join(log_lines),
                }
        return {
            "status": "error",
            "code": "SCAN_FAILED",
            "message": msg,
            "log": "\n".join(log_lines),
        }
    except Exception as e:  # pragma: no cover - 防御性
        return {
            "status": "error",
            "code": "OTHER",
            "message": f"{type(e).__name__}: {e}",
            "log": "\n".join(log_lines),
        }

    if not key_map:
        return {
            "status": "error",
            "code": "NO_KEY_FOUND",
            "message": "扫描完成但未匹配到任何密钥, 请确认微信已运行登录。",
            "log": "\n".join(log_lines),
        }

    save_keys(key_map)
    first_key = next(iter(key_map.values()))
    config_svc.save({
        "database_password": first_key,
        "wechat_files_path": db_dir,
    })
    return {
        "status": "ok",
        "key_count": len(key_map),
        "wechat_files_path": db_dir,
        "first_key_preview": first_key[:8] + "..." + first_key[-4:],
        "log": "\n".join(log_lines),
    }


def ensure_decrypted() -> str:
    """确保 db_dir 已解密到 cache_dir，返回 cache_dir。

    简单策略：直接每次重新解密（与原版一致，不做差量）。
    """
    db_dir = resolve_db_dir()
    if not db_dir:
        raise WechatError(
            "未配置微信数据目录",
            hint="先在「密码」自动获取或在「配置」手动填写",
            code="WX_NO_DB_DIR",
        )

    cache_dir = paths.decrypt_cache_dir()
    keys = load_keys()
    if not keys:
        cur = config_svc.load()
        single = (cur.get("database_password") or "").strip().lower()
        if not (len(single) == 64 and all(c in "0123456789abcdef" for c in single)):
            raise KeyNotFound(
                "尚未获取密钥",
                hint="先运行 password-auto 或在配置里填合法的 64 位 hex database_password",
            )
        from ..adapters import key_scan
        dbs, _salt_map = key_scan.collect_db_files(db_dir)
        try:
            single_bytes = bytes.fromhex(single)
        except ValueError as e:
            raise KeyNotFound("database_password 不是合法的 64 位十六进制") from e
        keys = {}
        for db in dbs:
            if key_scan.verify_enc_key(single_bytes, db.page1):
                keys[db.salt_hex] = single

    from ..adapters import decrypt
    decrypt.decrypt_all_dbs(db_dir, keys, cache_dir=str(cache_dir))
    return str(cache_dir)


@capability("op:wechat:password-status")
def _cap_status(_payload: dict) -> dict:
    return password_status()


@capability("op:wechat:password-auto")
def _cap_auto(_payload: dict) -> dict:
    return password_auto()


@capability("op:wechat:macos-resign")
def _cap_resign(_payload: dict) -> dict:
    if platform.system() != "Darwin":
        raise PlatformUnsupported("仅 macOS 可用")
    from ..adapters import scanner_mac
    return scanner_mac.resign_wechat()
