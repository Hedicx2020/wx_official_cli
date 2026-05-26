#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信DAT图片解密转换工具（V2/V4 格式 + wxgf 视频）

支持:
  - V2 缩略图 (*_t.dat): 仅 XOR 即可解
  - V4 完整图 (*.dat / *_h.dat): AES + XOR
  - wxgf HEVC 视频流: 解密后头 4 字节是 b"wxgf", 写 .hevc 让用户用 VLC 播放

参考:
  - https://github.com/recarto404/WxDatDecrypt (原始 V4 解密思路)
  - https://github.com/ylytdeng/wechat-decrypt (魔术字节多格式校验 + JPEG marker chain + wxgf)
"""

import os
import sys
from pathlib import Path
from typing import Optional, Tuple

try:
    from wechat_log import wlog
except Exception:  # pragma: no cover
    def wlog(level: str, message: str) -> None:
        print(f"[wechat:{level}] {message}", file=sys.stderr)


# ─── 自定义异常: 让上层多 key 循环能区分"key 错"与"格式错"───────
class DatDecryptError(Exception):
    """所有解密失败的基类."""


class DatBadKeyError(DatDecryptError):
    """AES key 不对 (解密后头部既不是 image magic 也不是 wxgf), 应换 key 重试."""


class DatBadFormatError(DatDecryptError):
    """文件本身不是 V4 格式 / 头部损坏, 换 key 也救不了."""


class DatMissingKeyError(DatDecryptError):
    """需要 AES 但未提供 / 需要 XOR 但未提供."""


# ─── 图像格式严格校验 (参考 ylytdeng/wechat-decrypt:decode_image.py) ───
def detect_image_format(data: bytes) -> Optional[str]:
    """识别解密后字节流的图像/视频格式. 用于密钥验证 + 输出文件命名.

    返回:
      'jpg' / 'png' / 'bmp' / 'webp' / 'gif': 静态图
      'hevc': wxgf 微信短视频 (HEVC 裸流)
      None: 未识别 (key 可能错了)
    """
    if len(data) < 16:
        return None
    if data[:3] == b"\xFF\xD8\xFF":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:2] == b"BM" and len(data) >= 14:
        return "bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"wxgf":
        return "hevc"
    return None


def verify_jpeg_chain(data: bytes, max_markers: int = 32) -> bool:
    """走一遍 JPEG marker chain, 比单看 FFD8FF 更严格 (假阳性显著降低).

    JPEG 结构: SOI (FFD8) → 段 (FF + marker_id + len + payload) ... → SOS (FFDA) + 数据 → EOI (FFD9)
    """
    if len(data) < 4 or data[:2] != b"\xFF\xD8":
        return False
    pos = 2
    for _ in range(max_markers):
        if pos + 4 >= len(data):
            return False
        if data[pos] != 0xFF:
            return False
        marker = data[pos + 1]
        if marker == 0xD9:  # EOI
            return True
        if marker == 0xDA:  # SOS - 后面是压缩数据, 直接认为合法
            return True
        if marker in (0x00, 0xFF):  # 填充
            pos += 1
            continue
        seg_len = (data[pos + 2] << 8) | data[pos + 3]
        if seg_len < 2:
            return False
        pos += 2 + seg_len
    return True  # 跑完 max_markers 没 fail, 认为是 JPEG

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    wlog("warning", "[WARNING] 未安装pycryptodome，无法使用")
    wlog("info", "[INFO] 安装命令: pip install pycryptodome")


class DatImageDecryptor:
    """DAT图片解密器（仅V4格式）"""

    # V4格式文件头
    V4_SIGNATURE = b"\x07\x08V2\x08\x07"

    def __init__(self, xor_key: Optional[int] = None, aes_key: Optional[str] = None):
        """
        初始化解密器

        参数:
            xor_key: XOR密钥(0-255)
            aes_key: AES密钥(32字节十六进制字符串)
        """
        self.xor_key = xor_key
        self.aes_key = aes_key

    def is_v4_format(self, dat_file_path: str) -> bool:
        """
        检测是否为V4格式

        参数:
            dat_file_path: DAT文件路径

        返回:
            True: V4格式, False: 不是V4格式
        """
        try:
            with open(dat_file_path, 'rb') as f:
                header = f.read(6)
            return header == self.V4_SIGNATURE
        except Exception:
            return False

    def decrypt_v4(self, dat_file_path: str, aes_key: str, xor_key: int, strict: bool = True) -> bytes:
        """
        解密 V4 格式 (AES + XOR 混合加密).

        文件结构:
        [0-5]:   签名 (b"\x07\x08V2\x08\x07")
        [6-10]:  AES 加密数据大小 (小端序 int)
        [11-14]: XOR 加密数据大小 (小端序 int)
        [15-]:   加密数据

        Raises:
            DatBadFormatError: 签名 / 头部不对, 换 key 也无济于事
            DatBadKeyError:    AES 解密后既不是 image magic 也不是 wxgf, key 不对
            DatMissingKeyError: 没装 pycryptodome 或 key 不合法
        """
        if not HAS_CRYPTO:
            raise DatMissingKeyError("v4 格式需要 pycryptodome (pip install pycryptodome)")

        with open(dat_file_path, 'rb') as f:
            data = f.read()

        # 1) 签名检查 (格式错, 换 key 也救不了)
        if data[:6] != b"\x07\x08V2\x08\x07":
            raise DatBadFormatError(f"v4 签名不匹配 (head={data[:6].hex()})")

        aes_size_original = int.from_bytes(data[6:10], byteorder='little')
        xor_size = int.from_bytes(data[10:14], byteorder='little')

        # 2) AES key 标准化
        if isinstance(aes_key, bytes):
            aes_key_bytes = aes_key[:16]
        else:
            aes_key_bytes = str(aes_key).encode()[:16]
        if len(aes_key_bytes) != 16:
            raise DatMissingKeyError(f"AES 密钥长度不足 ({len(aes_key_bytes)} 字节, 需要 16)")

        # 3) 切分三段 (AES 段需要 16 字节对齐)
        encrypted = data[15:]
        aes_size = aes_size_original + AES.block_size - aes_size_original % AES.block_size
        aes_blob = encrypted[:aes_size]
        if xor_size > 0:
            middle = encrypted[aes_size:-xor_size]
            xor_blob = encrypted[-xor_size:]
        else:
            middle = encrypted[aes_size:]
            xor_blob = b''

        # 4) AES-ECB 解密 (key 错时这步也可能不抛, 仅产出乱码)
        try:
            aes_dec = AES.new(aes_key_bytes, AES.MODE_ECB).decrypt(aes_blob)
        except Exception as e:
            raise DatBadFormatError(f"AES 解密报错: {e}") from e

        try:
            aes_dec = unpad(aes_dec, AES.block_size)
        except Exception:
            aes_dec = aes_dec[:aes_size_original]

        xor_dec = bytes(b ^ xor_key for b in xor_blob) if xor_size else b''
        decrypted = aes_dec + middle + xor_dec

        # 5) 校验头部 magic, 失败 → 多半 AES key 不对
        fmt = detect_image_format(decrypted)
        if fmt is None and strict:
            raise DatBadKeyError(f"解密后未识别格式 (head={decrypted[:8].hex()}), 可能 AES key 不对")
        if fmt == "jpg" and not verify_jpeg_chain(decrypted):
            # JPEG marker chain 失败 → 也认为 key 不对 (假阳性极少)
            if strict:
                raise DatBadKeyError("JPEG marker chain 校验失败, 可能 AES key 不对")
        return decrypted

    def decrypt_dat(self, dat_file_path: str, strict: bool = True) -> bytes:
        """
        解密 DAT 文件 (V4 格式).

        Raises:
            DatBadFormatError / DatBadKeyError / DatMissingKeyError
        """
        if not self.is_v4_format(dat_file_path):
            raise DatBadFormatError(f"文件不是 V4 格式: {dat_file_path}")
        if not self.aes_key:
            raise DatMissingKeyError("需要 AES 密钥 (V4 完整图)")
        if not self.xor_key:
            raise DatMissingKeyError("需要 XOR 密钥")
        return self.decrypt_v4(dat_file_path, self.aes_key, self.xor_key, strict=strict)

    def convert_dat_to_jpg(self, dat_file_path: str, output_path: Optional[str] = None) -> str:
        """
        将 DAT 文件解密落盘. 名字保留兼容, 实际后缀按真实格式决定 (jpg/png/bmp/webp/gif/hevc).

        Raises:
            DatDecryptError 子类 (DatBadKeyError 表示 key 不对, 调用方可换 key 重试).
        """
        decrypted_data = self.decrypt_dat(dat_file_path)

        # 根据真实格式决定后缀 (PNG/BMP/WebP/HEVC 也会正常落盘)
        fmt = detect_image_format(decrypted_data) or "jpg"
        ext = f".{fmt}"

        if output_path is None:
            dat_path = Path(dat_file_path)
            output_path = dat_path.parent / f"{dat_path.stem}{ext}"
        else:
            output_path = Path(output_path)
            if output_path.suffix.lower() != ext:
                output_path = output_path.with_suffix(ext)

        with open(output_path, 'wb') as f:
            f.write(decrypted_data)
        return str(output_path)

    def batch_convert(self, dat_directory: str, output_directory: Optional[str] = None,
                     recursive: bool = False) -> Tuple[int, int]:
        """
        批量转换目录下的所有DAT文件

        参数:
            dat_directory: DAT文件所在目录
            output_directory: 输出目录(可选)
            recursive: 是否递归子目录

        返回:
            (成功数量, 失败数量)
        """
        dat_dir = Path(dat_directory)
        if not dat_dir.exists():
            wlog("error", f"[ERROR] 目录不存在: {dat_directory}")
            return 0, 0

        # 查找所有DAT文件
        if recursive:
            dat_files = list(dat_dir.rglob('*.dat'))
        else:
            dat_files = list(dat_dir.glob('*.dat'))

        if len(dat_files) == 0:
            wlog("error", f"[ERROR] 未找到DAT文件: {dat_directory}")
            return 0, 0

        wlog("info", f"[INFO] 找到 {len(dat_files)} 个DAT文件")

        # 确定输出目录
        if output_directory:
            output_dir = Path(output_directory)
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            output_dir = dat_dir

        success = 0
        fail = 0

        for dat_file in dat_files:
            # V2 缩略图 / V4 完整图都尝试. AES key 是否就绪由调用方决定.
            if not self.is_v4_format(str(dat_file)):
                wlog("info", f"[SKIP] {dat_file.name} (非 V4 格式)")
                fail += 1
                continue

            # 确定输出路径
            if output_directory:
                # 保持相对路径结构
                rel_path = dat_file.relative_to(dat_dir)
                output_path = output_dir / rel_path.parent / f"{dat_file.stem}.jpg"
                output_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                output_path = dat_file.parent / f"{dat_file.stem}.jpg"

            # 转换 (新版会抛 DatDecryptError 子类, 老调用方期望返回路径; 这里 try 包一下)
            try:
                result = self.convert_dat_to_jpg(str(dat_file), str(output_path))
                wlog("info", f"[OK] {dat_file.name} -> {Path(result).name}")
                success += 1
            except DatDecryptError as e:
                wlog("warning", f"[FAIL] {dat_file.name}: {e}")
                fail += 1

        wlog("info", f"[INFO] 批量转换完成: 成功 {success} 个, 失败 {fail} 个")
        return success, fail


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print("  python dat_to_image.py <dat文件或目录> [输出目录] [--xor-key KEY] [--aes-key KEY]")
        print("\n示例:")
        print("  python dat_to_image.py image.dat --xor-key 69")
        print("  python dat_to_image.py dat_directory/ output/ --xor-key 69")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = None
    xor_key = None
    aes_key = None

    # 解析参数
    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == '--xor-key' and i + 1 < len(sys.argv):
            xor_key = int(sys.argv[i + 1])
            i += 2
        elif arg == '--aes-key' and i + 1 < len(sys.argv):
            aes_key = sys.argv[i + 1]
            i += 2
        elif not arg.startswith('--'):
            output_path = arg
            i += 1
        else:
            i += 1

    if xor_key is None:
        print("[ERROR] 请提供XOR密钥: --xor-key KEY")
        sys.exit(1)

    # 创建解密器
    decryptor = DatImageDecryptor(xor_key, aes_key)

    # 转换
    if Path(input_path).is_file():
        result = decryptor.convert_dat_to_jpg(input_path, output_path)
        if result:
            print(f"\n[SUCCESS] 输出: {result}")
    elif Path(input_path).is_dir():
        decryptor.batch_convert(input_path, output_path)
    else:
        print(f"[ERROR] 路径不存在: {input_path}")
