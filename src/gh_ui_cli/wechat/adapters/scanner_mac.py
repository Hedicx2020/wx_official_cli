"""macOS 微信进程内存扫描 + 重签名 (用于自动获取数据库密钥).

整体流程 (用户视角):
  1. 用户点击「重签名微信」按钮:
     - osascript 弹系统密码框 (sudo 等价)
     - 在 root 权限下: codesign --force --sign - --entitlements 给 WeChat.app
       追加 com.apple.security.get-task-allow entitlement
     - 保留微信原有 entitlements
  2. 用户手动退出 WeChat -> 重新打开 (重签后必须重启进程才生效)
  3. 用户点击「自动获取密码」:
     - osascript 再次弹密码框
     - 在 root 权限下用 /usr/bin/python3 跑 _mac_helper.py
     - helper 用 ctypes 调 task_for_pid + mach_vm_read 扫内存
     - 输出 {salt_hex: enc_key_hex} JSON

权衡:
  * 重签名微信会让微信下次自动更新失效 (App Store 不会更新签名修改过的版本),
    用户需要重新跑「重签名」流程
  * 弹密码框由 osascript 完成, 不需要给 sidecar 申请额外 entitlement
"""

from __future__ import annotations

import json
import os
import platform
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

IS_MACOS = platform.system() == "Darwin"

CANDIDATE_DB_ROOTS = [
    "Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/com.tencent.xinWeChat",
    "Library/Containers/com.tencent.xinWeChat",
    "Library/Application Support/com.tencent.xinWeChat",
]


def detect_db_storage(home: str | None = None) -> str:
    base = Path(home or os.path.expanduser("~"))
    for rel in CANDIDATE_DB_ROOTS:
        root = base / rel
        if not root.exists():
            continue
        for child in root.rglob("db_storage"):
            if child.is_dir():
                return str(child)
        if root.is_dir():
            return str(root)
    return ""


# ─── WeChat.app 定位 ──────────────────────────────
WECHAT_BUNDLE_IDS = ("com.tencent.xinWeChat", "com.tencent.WeChat")


def find_wechat_app() -> str:
    """优先固定路径, 兜底 mdfind by bundle id."""
    for p in ("/Applications/WeChat.app", os.path.expanduser("~/Applications/WeChat.app")):
        if os.path.isdir(p):
            return p
    for bid in WECHAT_BUNDLE_IDS:
        try:
            out = subprocess.run(
                ["mdfind", f"kMDItemCFBundleIdentifier == '{bid}'"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            continue
        for line in out.stdout.splitlines():
            line = line.strip()
            if line and os.path.isdir(line):
                return line
    return ""


# ─── 重签名 ──────────────────────────────────────
def _extract_entitlements(app_path: str) -> dict:
    """读 app 现有 entitlements (不需要 sudo)."""
    try:
        out = subprocess.run(
            ["codesign", "-d", "--entitlements", ":-", app_path],
            capture_output=True, timeout=15,
        )
    except Exception:
        return {}
    if out.returncode != 0 or not out.stdout:
        return {}
    try:
        return plistlib.loads(out.stdout) or {}
    except Exception:
        return {}


def _build_entitlements(app_path: str) -> bytes:
    ent = _extract_entitlements(app_path)
    ent["com.apple.security.get-task-allow"] = True
    return plistlib.dumps(ent, fmt=plistlib.FMT_XML)


def _osascript_run_with_admin(shell_cmd: str, timeout: int = 180) -> tuple[int, str, str]:
    """通过 osascript 弹原生密码框, 用 admin 权限跑 shell_cmd.

    shell_cmd 中如果有双引号需要 escape; 这里假设调用方已经处理.
    返回 (returncode, stdout, stderr).
    用户取消授权时 osascript exit != 0, stderr 含 "User canceled".
    """
    script = f'do shell script "{shell_cmd}" with administrator privileges'
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "osascript timeout"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def resign_wechat() -> dict:
    """对 WeChat.app 重签名加 get-task-allow.

    返回:
      {"status": "ok"|"error", "code": ..., "message": ..., "app_path": ...}
    可能的 error code:
      NO_WECHAT_APP / USER_CANCELLED / CODESIGN_FAILED / OTHER
    """
    if not IS_MACOS:
        return {"status": "error", "code": "PLATFORM", "message": "仅 macOS 可用"}

    app = find_wechat_app()
    if not app:
        return {
            "status": "error",
            "code": "NO_WECHAT_APP",
            "message": "未找到 WeChat.app, 请先安装并登录微信",
        }

    # 写入 entitlements 到 /tmp/ (普通权限即可, sudo 时还能读)
    try:
        ent_xml = _build_entitlements(app)
    except Exception as e:
        return {"status": "error", "code": "OTHER", "message": f"entitlements 提取失败: {e}"}
    ent_path = tempfile.mkstemp(suffix=".plist", prefix="wechat_ent_")[1]
    try:
        with open(ent_path, "wb") as f:
            f.write(ent_xml)
        os.chmod(ent_path, 0o644)

        # 重签名 (sudo 跑)
        # 注意 app 路径含空格的话用单引号包裹; 另外 shell_cmd 经过 osascript 字符串再次解析,
        # 故内部双引号要 \\\" 转义
        cmd = f"/usr/bin/codesign --force --sign - --entitlements {ent_path} \\\"{app}\\\""
        rc, out, err = _osascript_run_with_admin(cmd, timeout=120)
        if rc != 0:
            if "canceled" in err.lower() or "user canceled" in err.lower():
                return {"status": "error", "code": "USER_CANCELLED", "message": "用户取消授权"}
            return {
                "status": "error",
                "code": "CODESIGN_FAILED",
                "message": (err or out or "codesign 失败").strip(),
            }
    finally:
        try:
            os.remove(ent_path)
        except OSError:
            pass

    return {
        "status": "ok",
        "code": "OK",
        "message": "重签名完成。请退出微信(完全退出, 不只是最小化)并重新打开, 然后再点「自动获取密码」。",
        "app_path": app,
    }


# ─── 内存扫描 (调 _mac_helper.py) ─────────────────
def _helper_path() -> Path:
    """定位 _mac_helper.py.

    PyInstaller 打包后, 同包文件会被解压到 sys._MEIPASS/wechat_native/.
    dev 模式下与本文件同目录.
    """
    here = Path(__file__).resolve().parent
    return here / "_mac_helper.py"


def extract_keys(db_dir: str, on_log: Callable[[str], None] | None = None) -> dict[str, str]:
    """走 osascript+sudo 跑 helper 拿 {salt_hex: enc_key_hex}.

    Raises:
        RuntimeError: 各类失败 (用户取消 / task_for_pid 失败 / 找不到 helper).
    """
    if not IS_MACOS:
        raise RuntimeError("scanner_mac 仅 macOS 可用")
    log = on_log or (lambda *_a, **_k: None)

    helper = _helper_path()
    if not helper.exists():
        raise RuntimeError(f"helper script 缺失: {helper}")

    # 构造 sudo 命令: /usr/bin/python3 <helper> --db-dir <db_dir>
    # 路径中可能有空格, 用 \\\"...\\\" 转义
    cmd = (
        f"/usr/bin/python3 \\\"{helper}\\\" "
        f"--db-dir \\\"{db_dir}\\\" --limit-mb 600"
    )
    log(f"osascript run: {cmd}")
    rc, out, err = _osascript_run_with_admin(cmd, timeout=300)

    if rc != 0:
        e = err.lower()
        if "canceled" in e or "user canceled" in e:
            raise RuntimeError("USER_CANCELLED: 用户取消授权")
        if "task_for_pid" in (out + err):
            raise RuntimeError(
                "RESIGN_NEEDED: task_for_pid 失败。请先点「重签名微信」, 重启微信后再试。"
            )
        raise RuntimeError((err or out or "scan helper failed").strip())

    # 解析 helper 的 JSON 输出
    try:
        data = json.loads(out.strip())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"helper 输出非 JSON: {e}; out[:200]={out[:200]!r}")

    for line in data.get("log") or []:
        log(line)

    if data.get("error"):
        err_text = str(data["error"])
        if "task_for_pid" in err_text or "kr=" in err_text:
            raise RuntimeError("RESIGN_NEEDED: task_for_pid 失败, 请先「重签名微信」并重启微信")
        if "not running" in err_text.lower():
            raise RuntimeError("NO_WECHAT: 微信未运行, 请先打开并登录微信")
        raise RuntimeError(err_text)

    keys = data.get("keys") or {}
    if not isinstance(keys, dict):
        raise RuntimeError("helper 返回 keys 字段类型错误")
    # 校验 hex 合法
    return {
        str(k): str(v).lower()
        for k, v in keys.items()
        if isinstance(k, str) and isinstance(v, str) and len(v) == 64
    }


def extract_image_keys(
    dat_dir: str,
    on_log: Callable[[str], None] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """走 osascript+sudo 跑 helper 扫图片 AES 密钥.

    与 extract_keys (DB 模式) 共用 helper 脚本, 只是 --mode image-key + --dat-dir.
    每个 .dat 文件前 16 字节 AES ciphertext 作 pattern, helper 在内存扫 16 字节候选
    key 并做强 magic 校验, 累积每个 key 的命中数, 取命中 ≥2 的作为权威密钥.

    Returns:
        (key_map, primary_keys):
          - key_map: {ct_hex: aes_key_hex} 每个 pattern 找到的 key
          - primary_keys: 跨 pattern 通用的真实密钥候选 (按命中数倒序)

    Raises:
        RuntimeError: 用户取消 / task_for_pid 失败 / 微信未运行 / dat 目录无效等.
    """
    if not IS_MACOS:
        raise RuntimeError("scanner_mac 仅 macOS 可用")
    log = on_log or (lambda *_a, **_k: None)

    helper = _helper_path()
    if not helper.exists():
        raise RuntimeError(f"helper script 缺失: {helper}")

    cmd = (
        f"/usr/bin/python3 \\\"{helper}\\\" --mode image-key "
        f"--dat-dir \\\"{dat_dir}\\\" --limit-mb 600"
    )
    log(f"osascript run: {cmd}")
    rc, out, err = _osascript_run_with_admin(cmd, timeout=600)

    if rc != 0:
        e = err.lower()
        if "canceled" in e or "user canceled" in e:
            raise RuntimeError("USER_CANCELLED: 用户取消授权")
        if "task_for_pid" in (out + err):
            raise RuntimeError(
                "RESIGN_NEEDED: task_for_pid 失败。请先点「重签名微信」, 重启微信后再试。"
            )
        raise RuntimeError((err or out or "image-key helper failed").strip())

    try:
        data = json.loads(out.strip())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"helper 输出非 JSON: {e}; out[:200]={out[:200]!r}")

    for line in data.get("log") or []:
        log(line)

    if data.get("error"):
        err_text = str(data["error"])
        if "task_for_pid" in err_text:
            raise RuntimeError("RESIGN_NEEDED: task_for_pid 失败, 请先「重签名微信」并重启微信")
        if "not running" in err_text.lower():
            raise RuntimeError("NO_WECHAT: 微信未运行, 请先打开并登录微信")
        raise RuntimeError(err_text)

    keys = data.get("keys") or {}
    if not isinstance(keys, dict):
        raise RuntimeError("helper 返回 keys 字段类型错误")
    key_map = {
        str(k): str(v).lower()
        for k, v in keys.items()
        if isinstance(k, str) and isinstance(v, str) and len(v) == 32
    }
    primary = [
        str(k).lower()
        for k in (data.get("primary_keys") or [])
        if isinstance(k, str) and len(k) == 32
    ]
    return key_map, primary
