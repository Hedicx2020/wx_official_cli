"""消息查询 -- 从已解密的 message_*.db 中按时间 / 聊天对象 / 关键词检索.

工作流:
  1) decrypt_all_dbs(db_dir, key_map) -> 把所有 *.db 解密到 cache_dir 下的同名文件
  2) list_sessions(cache_dir)         -> 聚合所有 message_*.db 中可识别的 chat_name
  3) search_messages(cache_dir, ...)  -> 按 chat / 关键词 / 日期范围查询消息

简化点 (v1):
  * 只走 message_*.db (聊天历史), 不解析 contact / favorite / media
  * 表名约定 Msg_<md5(username_hex)>; chat_name 直接当 username 走 md5 (后续可加 contact 名->wxid 反查)
  * 不解 media (图片 / 语音), 只取文本 / link 内容
  * Type 映射只覆盖最常用 (text=1, image=3, voice=34, video=43, link=49, sticker=47, system=10000)
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

def wlog(level: str, message: str) -> None:
    print(f"[wechat:{level}] {message}", file=sys.stderr)


from .crypto import full_decrypt, apply_wal


_MSG_DB_RE = re.compile(r"message_\d+\.db$", re.IGNORECASE)
_SAFE_TABLE_RE = re.compile(r"^Msg_[0-9a-f]{32}$")

# 微信 4.x macOS 的 local_type 值. 真实 type 在低 16 位, 高位是 source/origin flag
MSG_TYPE_NAMES: dict[int, str] = {
    1: "文本",
    3: "图片",
    34: "语音",
    37: "好友申请",
    42: "名片",
    43: "视频",
    47: "表情",
    48: "位置",
    49: "链接/文件",
    50: "通话",
    51: "小程序",
    62: "小视频",
    10000: "系统",
    10002: "撤回",
}


def _normalize_type(raw_type: int) -> int:
    """微信 4.x 把 source flag 编进 local_type 高位 (例如 21474836529 = 5<<32 | 1).
    取低 16 位才是真正的消息类型.
    """
    if raw_type in MSG_TYPE_NAMES:
        return raw_type
    low = raw_type & 0xFFFF
    if low in MSG_TYPE_NAMES:
        return low
    # 兜底取低 32 位
    return raw_type & 0xFFFFFFFF

# zstd magic
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_zstd_dctx = None


def _zdec():
    global _zstd_dctx
    if _zstd_dctx is None:
        import zstandard as zstd
        _zstd_dctx = zstd.ZstdDecompressor()
    return _zstd_dctx


def _decompress_content(blob) -> str:
    """微信 4.x 的 message_content 是 zstd 压缩的二进制. 解压后多为 UTF-8 文本或 XML."""
    if blob is None:
        return ""
    if isinstance(blob, str):
        return blob
    if not isinstance(blob, (bytes, bytearray)):
        return str(blob)
    if not blob:
        return ""
    data = bytes(blob)
    if data.startswith(_ZSTD_MAGIC):
        try:
            data = _zdec().decompress(data)
        except Exception:
            return data[:200].hex() + ("..." if len(data) > 200 else "")
    # 解压后可能是 UTF-8 文本 / XML / protobuf
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data[:200].hex() + ("..." if len(data) > 200 else "")
    return _strip_xml(text)


_XML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_xml(text: str) -> str:
    """微信系统消息 / 卡片消息常用 XML 包裹, 取主要文本."""
    s = text.strip()
    if not (s.startswith("<") and s.endswith(">")):
        return s
    inner = _XML_TAG_RE.sub(" ", s)
    inner = re.sub(r"\s+", " ", inner).strip()
    return inner or s[:200]


def _attr(xml: str, attr: str) -> str:
    m = re.search(rf'{attr}\s*=\s*"([^"]*)"', xml)
    return m.group(1) if m else ""


def _tag_text(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>([^<]*)</{tag}>", xml, re.DOTALL)
    if m:
        return m.group(1).strip()
    # CDATA
    m = re.search(rf"<{tag}[^>]*><!\[CDATA\[(.*?)\]\]></{tag}>", xml, re.DOTALL)
    return m.group(1).strip() if m else ""


def _human_size(n: str | int) -> str:
    try:
        size = int(n)
    except (TypeError, ValueError):
        return str(n)
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / 1024 / 1024:.1f}MB"
    return f"{size / 1024 / 1024 / 1024:.2f}GB"


def _format_image(xml: str) -> str:
    w = _attr(xml, "cdnmidwidth") or _attr(xml, "cdnthumbwidth")
    h = _attr(xml, "cdnmidheight") or _attr(xml, "cdnthumbheight")
    if w and h:
        return f"[图片] {w}×{h}"
    return "[图片]"


def _format_video(xml: str) -> str:
    sec = _attr(xml, "playlength")
    length = _attr(xml, "length")
    parts = []
    if sec:
        parts.append(f"{sec}秒")
    if length:
        parts.append(_human_size(length))
    return "[视频] " + " ".join(parts) if parts else "[视频]"


def _format_voice(xml: str) -> str:
    ms = _attr(xml, "voicelength")
    if ms:
        try:
            return f"[语音] {int(ms) / 1000:.1f}秒"
        except (TypeError, ValueError):
            pass
    return "[语音]"


def _format_sticker(xml: str) -> str:
    return "[表情]"


def _format_card(xml: str) -> str:
    nick = _attr(xml, "nickname") or _attr(xml, "fullpy") or _attr(xml, "alias")
    return f"[名片] {nick}" if nick else "[名片]"


def _format_appmsg(xml: str) -> str:
    """type=49 多种 appmsg 子类型: 5=链接, 6=文件, 33/36=小程序, 51=视频号, 87=群公告, 2000=转账..."""
    title = _tag_text(xml, "title") or ""
    des = _tag_text(xml, "des") or ""
    inner_type = _tag_text(xml, "type")
    appname = _tag_text(xml, "appname") or _tag_text(xml, "sourcedisplayname") or ""

    if inner_type == "6":
        size = _tag_text(xml, "totallen")
        return f"[文件] {title}" + (f" ({_human_size(size)})" if size else "")
    if inner_type == "5":
        return f"[链接] {title}" + (f" / {appname}" if appname else "")
    if inner_type in ("33", "36"):
        return f"[小程序] {title}"
    if inner_type == "51":
        return f"[视频号] {title}"
    if inner_type == "87":
        return f"[群公告] {title}"
    if inner_type == "2000":
        return f"[转账] {title}"
    if inner_type == "57":
        # 引用消息 (quote / refer)
        refer = _tag_text(xml, "refermsg") or des
        return f"[引用] {title} ← {refer[:80]}" if refer else f"[引用] {title}"
    text = title or des
    return f"[appmsg type={inner_type}] {text}".strip() if text else f"[appmsg type={inner_type}]"


def _format_system(xml: str) -> str:
    s = _strip_xml(xml)
    return s[:300] if s else "[系统消息]"


def format_content(local_type: int, raw) -> str:
    """根据 local_type 格式化 message_content.

    raw 可能是:
      * str: 普通好友库 (message_*.db) 的文本直接存 str
      * bytes (zstd magic 开头): 公众号库 (biz_message_*.db) 的文本 / 其他类型的 XML
      * bytes (无 magic): 罕见, 当 utf-8 二进制处理
    """
    # text: 普通好友是 str, 公众号是 zstd 压缩 BLOB
    if local_type == 1:
        if isinstance(raw, str):
            return raw
        if isinstance(raw, (bytes, bytearray)):
            data = bytes(raw)
            if data[:4] == _ZSTD_MAGIC:
                try:
                    return _zdec().decompress(data).decode("utf-8", errors="replace")
                except Exception:
                    return ""
            try:
                return data.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                # 可能是 protobuf 等二进制, 不显示
                return ""
        return str(raw or "")
    # 其他: 先解压
    text = _decompress_content(raw) if not isinstance(raw, str) else raw
    if not text:
        return ""
    handlers: dict[int, callable] = {
        3: _format_image,
        34: _format_voice,
        43: _format_video,
        47: _format_sticker,
        42: _format_card,
        49: _format_appmsg,
        10000: _format_system,
    }
    f = handlers.get(local_type)
    if f:
        try:
            return f(text)
        except Exception:
            return _strip_xml(text)
    if local_type == 50:
        return "[语音/视频通话]"
    if local_type == 62:
        return "[小视频]"
    return _strip_xml(text)


# ─── sender id (real_sender_id) -> 显示名 反查 ───────────
_SENDER_INDEX_CACHE: dict[int, str] | None = None
_SENDER_INDEX_FP: tuple = ()


def _build_sender_index(cache_dir: str) -> dict[int, str]:
    """把 contact / stranger 的 (id -> 显示名) 都加进字典."""
    idx: dict[int, str] = {1: "我"}
    contact_db = os.path.join(cache_dir, "contact", "contact.db")
    if not os.path.exists(contact_db):
        return idx
    try:
        conn = sqlite3.connect(contact_db)
    except sqlite3.DatabaseError:
        return idx
    try:
        for tbl in ("contact", "stranger"):
            try:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info([{tbl}])").fetchall()}
            except sqlite3.OperationalError:
                continue
            if "id" not in cols or "username" not in cols:
                continue
            select = ["id", "username"]
            for opt in ("nick_name", "remark"):
                if opt in cols:
                    select.append(opt)
            sql = f"SELECT {', '.join(select)} FROM [{tbl}]"
            try:
                cur = conn.execute(sql)
            except sqlite3.OperationalError:
                continue
            for row in cur:
                rid = row[0]
                if not isinstance(rid, int):
                    try:
                        rid = int(rid)
                    except (TypeError, ValueError):
                        continue
                if rid in idx and idx[rid] != "我":
                    continue
                username = row[1] or ""
                name = ""
                for i, c in enumerate(select):
                    if c in ("remark", "nick_name") and row[i]:
                        name = str(row[i])
                        break
                idx[rid] = name or username or f"id={rid}"
    finally:
        conn.close()
    return idx


def get_sender_index(cache_dir: str) -> dict[int, str]:
    global _SENDER_INDEX_CACHE, _SENDER_INDEX_FP
    fp = _index_fingerprint(cache_dir)
    if _SENDER_INDEX_CACHE is not None and fp == _SENDER_INDEX_FP:
        return _SENDER_INDEX_CACHE
    _SENDER_INDEX_CACHE = _build_sender_index(cache_dir)
    _SENDER_INDEX_FP = fp
    return _SENDER_INDEX_CACHE


# ─── 1. 整库解密缓存 ───────────────────────────────────────
def decrypt_all_dbs(db_dir: str, key_map: dict[str, str], cache_dir: str | None = None) -> dict[str, str]:
    """把 db_dir 下所有 .db 解密到 cache_dir, 返回 {rel_path: cache_abs_path}.

    db_dir 内子目录结构保留. key_map 是 salt_hex -> enc_key_hex.
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
            except Exception as e:
                # 跳过损坏 / 不可解密的, 不中断整体流程
                wlog("warning", f"[wechat_native] decrypt failed {rel}: {e}")
                continue
            wal_src = src + "-wal"
            if os.path.exists(wal_src):
                try:
                    apply_wal(wal_src, str(dst), key)
                except Exception as e:
                    wlog("warning", f"[wechat_native] wal apply failed {rel}: {e}")
            mapping[rel] = str(dst)
    return mapping


# ─── 2. 工具 ─────────────────────────────────────────────
def _msg_table_name(chat_name: str) -> str:
    """微信 4.x 表名 = Msg_<md5(username_hex)>, username 通常是 wxid_xxx 或群 chatroom@chatroom."""
    table_hash = hashlib.md5(chat_name.encode("utf-8")).hexdigest()
    return f"Msg_{table_hash}"


# ─── username 反查 (md5(username) -> 显示名) ───────────────
# 模块级缓存. cache_dir 指纹(mtime+size) 变了就重建.
_USERNAME_INDEX_CACHE: dict[str, dict[str, str]] | None = None
_USERNAME_INDEX_FP: tuple = ()


def _index_fingerprint(cache_dir: str) -> tuple:
    candidates = [
        os.path.join(cache_dir, "contact", "contact.db"),
        os.path.join(cache_dir, "session", "session.db"),
    ]
    fp = []
    for p in candidates:
        try:
            st = os.stat(p)
            fp.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            fp.append((p, 0, 0))
    return tuple(fp)


def _build_username_index(cache_dir: str) -> dict[str, dict[str, str]]:
    """扫 contact.db 把所有 username 聚合, 返回 {md5(username): {username, name}}."""
    idx: dict[str, dict[str, str]] = {}
    contact_db = os.path.join(cache_dir, "contact", "contact.db")
    if not os.path.exists(contact_db):
        return idx
    try:
        conn = sqlite3.connect(contact_db)
    except sqlite3.DatabaseError:
        return idx
    try:
        for tbl in ("contact", "stranger"):
            try:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info([{tbl}])").fetchall()}
            except sqlite3.OperationalError:
                continue
            if "username" not in cols:
                continue
            select_cols = ["username"]
            for opt in ("nick_name", "remark", "alias"):
                if opt in cols:
                    select_cols.append(opt)
            sql = f"SELECT {', '.join(select_cols)} FROM [{tbl}]"
            try:
                cur = conn.execute(sql)
            except sqlite3.OperationalError:
                continue
            col_idx = {c: i for i, c in enumerate(select_cols)}
            for row in cur:
                u = row[col_idx["username"]]
                if not u or not isinstance(u, str):
                    continue
                # 显示名优先级: remark > nick_name > alias > username
                name = ""
                for k in ("remark", "nick_name", "alias"):
                    if k in col_idx:
                        v = row[col_idx[k]]
                        if v:
                            name = str(v)
                            break
                if not name:
                    name = u
                h = hashlib.md5(u.encode("utf-8")).hexdigest()
                # 同名 hash 已存在不覆盖 (contact 优先于 stranger)
                if h not in idx:
                    idx[h] = {"username": u, "name": name}
    finally:
        conn.close()
    return idx


def get_username_index(cache_dir: str) -> dict[str, dict[str, str]]:
    """带缓存的 hash -> {username, name} 索引."""
    global _USERNAME_INDEX_CACHE, _USERNAME_INDEX_FP
    fp = _index_fingerprint(cache_dir)
    if _USERNAME_INDEX_CACHE is not None and fp == _USERNAME_INDEX_FP:
        return _USERNAME_INDEX_CACHE
    _USERNAME_INDEX_CACHE = _build_username_index(cache_dir)
    _USERNAME_INDEX_FP = fp
    return _USERNAME_INDEX_CACHE


def resolve_chat_name(cache_dir: str, raw_input: str) -> str:
    """用户输入的 chat 标识 -> 真实 username (用作 md5 输入).

    支持:
      * 直接 wxid / chatroom 标识 -> 原样返回
      * nick_name / remark 关键词 -> 找第一个匹配的 username
      * 已经是 32 位 hex hash -> 反查
    """
    s = (raw_input or "").strip()
    if not s:
        return ""
    idx = get_username_index(cache_dir)
    # hex hash 反查
    if len(s) == 32 and all(c in "0123456789abcdef" for c in s.lower()):
        ent = idx.get(s.lower())
        return ent["username"] if ent else s
    # 直接当 username (md5 算出的 hash 已存在)
    if hashlib.md5(s.encode("utf-8")).hexdigest() in idx:
        return s
    # 模糊匹配 name (备注 / 昵称)
    for ent in idx.values():
        if s in ent["name"] or ent["name"] == s:
            return ent["username"]
    return s   # 找不到, 原样返回 (后续 md5 算出的 hash 没表会跳过)


def _format_ts(ts: int) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return ""


def _date_to_unix(date_str: str, end: bool = False) -> int:
    """日期字符串 -> unix ts (本地时区).

    支持格式 (按优先级):
      * "2025-11-28T14:30"      datetime-local 输入
      * "2025-11-28 14:30:00"   带秒
      * "2025-11-28 14:30"      带时分
      * "2025-11-28"            仅日期 (end=True 自动取 23:59:59)

    end=True 且只给了日期: 取当天结束.
    """
    if not date_str:
        return 0
    s = date_str.strip()
    has_time = "T" in s or (" " in s and ":" in s)
    fmts = (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    )
    dt = None
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            break
        except ValueError:
            continue
    if dt is None:
        return 0
    if end and not has_time:
        dt = dt.replace(hour=23, minute=59, second=59)
    return int(dt.timestamp())


def _columns_of(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info([{table}])").fetchall()]


def _safe_text(val) -> str:
    if val is None:
        return ""
    if isinstance(val, bytes):
        try:
            return val.decode("utf-8", errors="replace")
        except Exception:
            return val.hex()
    return str(val)


# ─── 3. Sessions 列表 ─────────────────────────────────────
def list_sessions(cache_dir: str) -> list[dict]:
    """从所有 Msg_* 表里聚合 (table_hash -> count + last_time).

    chat_name 不在表里 (表名是 hash), 所以这里只能给出 hash + 计数;
    UI 让用户在「搜索」Tab 直接输 wxid / 群名, 我们会 md5 找到对应表.
    """
    sessions: dict[str, dict] = {}
    for root, _dirs, names in os.walk(cache_dir):
        for name in names:
            if not _MSG_DB_RE.search(name):
                continue
            path = os.path.join(root, name)
            try:
                with closing(sqlite3.connect(path)) as conn:
                    rows = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
                    ).fetchall()
                    for (tname,) in rows:
                        if not _SAFE_TABLE_RE.fullmatch(tname):
                            continue
                        cols = _columns_of(conn, tname)
                        if "create_time" in cols:
                            r = conn.execute(
                                f"SELECT COUNT(*), MAX(create_time) FROM [{tname}]"
                            ).fetchone()
                        else:
                            r = (conn.execute(f"SELECT COUNT(*) FROM [{tname}]").fetchone()[0], 0)
                        cnt, max_ct = (r[0] or 0), (r[1] or 0)
                        cur = sessions.get(tname)
                        if cur is None or (max_ct and max_ct > cur["_max_ct"]):
                            sessions[tname] = {
                                "chat_hash": tname[4:],   # 去掉 Msg_ 前缀
                                "message_count": cnt,
                                "last_message_time": _format_ts(max_ct),
                                "_max_ct": max_ct,
                            }
            except sqlite3.DatabaseError:
                continue
    out = []
    for s in sessions.values():
        s.pop("_max_ct", None)
        out.append({
            "chat_name": s["chat_hash"],     # 占位, UI 上提示用户用 hash 反查
            "message_count": s["message_count"],
            "last_message_time": s["last_message_time"],
        })
    out.sort(key=lambda r: r["last_message_time"], reverse=True)
    return out


# ─── 4. 搜索消息 ─────────────────────────────────────────
def search_messages(
    cache_dir: str,
    *,
    start_date: str = "",
    end_date: str = "",
    chat_name: str = "",
    sender_name: str = "",
    exclude_contacts: str = "",
    keyword: str = "",
    message_type: str | int | None = None,
    exclude_self: bool = False,
    dedup_day: bool = False,
    dedup_content_latest: bool = False,
    dedup_content_earliest: bool = False,
    limit: int = 5000,
) -> list[dict]:
    """在已解密的 message_*.db 中按条件查询 (1:1 对齐 gh_wx).

    Args:
        chat_name: 聊天对象, 多个用逗号分隔 (留空 = 不限制)
        sender_name: 发送人筛选, 多个用逗号分隔 (在群聊中过滤特定发言人)
        exclude_contacts: 排除的聊天对象, 多个用逗号分隔
        keyword: 内容关键词 (子串匹配)
        message_type: 消息类型 ID (int) 或字符串. None / "" = 全部类型
        exclude_self: 排除自己发送的消息
        dedup_day: 同一聊天对象同一天的同内容只保留 1 条
        dedup_content_latest: 跨群按内容去重, 保留最晚一条
        dedup_content_earliest: 跨群按内容去重, 保留最早一条 (与 latest 互斥, 后者优先)
    """
    ts_lo = _date_to_unix(start_date, end=False)
    ts_hi = _date_to_unix(end_date, end=True)

    # 索引 (各自带模块级缓存)
    name_idx = get_username_index(cache_dir)
    sender_idx = get_sender_index(cache_dir)

    # 解析 message_type
    type_filter: int | None = None
    if message_type not in (None, "", 0, "0"):
        try:
            type_filter = int(message_type)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            type_filter = None

    # 解析多 chat_name (CSV)
    chat_names_raw = [c.strip() for c in (chat_name or "").split(",") if c.strip()]
    sender_names = {s.strip() for s in (sender_name or "").split(",") if s.strip()}
    exclude_set = {x.strip() for x in (exclude_contacts or "").split(",") if x.strip()}

    # 多 chat 时不能用单表定位, 全表扫
    if len(chat_names_raw) == 1:
        resolved_chat = resolve_chat_name(cache_dir, chat_names_raw[0])
        target_table = _msg_table_name(resolved_chat) if resolved_chat else None
        chat_filter_set: set[str] = set()
    elif len(chat_names_raw) > 1:
        target_table = None
        resolved_chat = ""
        # 多个 chat: 后续按 chat_display 过滤
        chat_filter_set = set()
        for c in chat_names_raw:
            r = resolve_chat_name(cache_dir, c)
            if r:
                chat_filter_set.add(r)
            chat_filter_set.add(c)
    else:
        target_table = None
        resolved_chat = ""
        chat_filter_set = set()

    out: list[dict] = []

    for root, _dirs, names in os.walk(cache_dir):
        for name in names:
            if len(out) >= limit:
                break
            if not _MSG_DB_RE.search(name):
                continue
            path = os.path.join(root, name)
            try:
                conn = sqlite3.connect(path)
            except sqlite3.DatabaseError:
                continue
            try:
                if target_table:
                    if not _SAFE_TABLE_RE.fullmatch(target_table):
                        continue
                    exists = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (target_table,),
                    ).fetchone()
                    if not exists:
                        continue
                    tables = [target_table]
                else:
                    tables = [
                        t for (t,) in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
                        ).fetchall() if _SAFE_TABLE_RE.fullmatch(t)
                    ]

                for t in tables:
                    if len(out) >= limit:
                        break
                    cols = set(_columns_of(conn, t))
                    have_ct = "create_time" in cols
                    where = []
                    params: list = []
                    if have_ct and ts_lo:
                        where.append("create_time >= ?")
                        params.append(ts_lo)
                    if have_ct and ts_hi:
                        where.append("create_time <= ?")
                        params.append(ts_hi)
                    # 关键词过滤在 Python 里做 (message_content 是 zstd 压缩的, SQL LIKE 没用)
                    sql = f"SELECT * FROM [{t}]"
                    if where:
                        sql += " WHERE " + " AND ".join(where)
                    if have_ct:
                        sql += " ORDER BY create_time DESC"
                    # 多取一些再做 keyword 过滤, 避免 LIMIT 后没结果
                    sql += f" LIMIT {max(1, (limit - len(out)) * (5 if keyword else 1))}"
                    try:
                        cur = conn.execute(sql, params)
                    except sqlite3.OperationalError:
                        continue
                    rows = cur.fetchall()
                    col_names = [d[0] for d in cur.description] if cur.description else []
                    for row in rows:
                        rec = dict(zip(col_names, row))
                        ct = rec.get("create_time") or 0
                        type_id = rec.get("local_type") or rec.get("Type") or 0
                        try:
                            type_id_int = int(type_id) if type_id else 0
                        except (TypeError, ValueError):
                            type_id_int = 0
                        type_id_int = _normalize_type(type_id_int)
                        sender_id = rec.get("real_sender_id")
                        try:
                            sid_int = int(sender_id) if sender_id is not None else 0
                        except (TypeError, ValueError):
                            sid_int = 0
                        # 反查 Msg 表对应的 chat (用于判断是否群聊)
                        thash = t[4:]
                        chat_ent = name_idx.get(thash)
                        is_group = bool(chat_ent and "@chatroom" in chat_ent["username"])
                        # 按消息类型格式化内容
                        raw = rec.get("message_content") or rec.get("compress_content") or rec.get("source") or ""
                        content = format_content(type_id_int, raw)

                        sender = ""
                        # 群聊文本消息内容头部带 "wxid:\n" 前缀, 优先用这个反查
                        group_wxid = ""
                        if is_group and isinstance(content, str):
                            head, sep, body = content.partition(":\n")
                            if sep and 0 < len(head) < 80 and "\n" not in head and " " not in head:
                                group_wxid = head.strip()
                                content = body
                        if group_wxid:
                            h = hashlib.md5(group_wxid.encode("utf-8")).hexdigest()
                            ent = name_idx.get(h)
                            sender = (ent["name"] if ent else group_wxid)
                        elif sid_int == 1:
                            sender = "我"
                        elif is_group:
                            # 非文本消息或者解析不出前缀: 兜底 contact.id 反查
                            sender = sender_idx.get(sid_int) or f"id={sid_int}"
                        else:
                            # 私聊: 非自己即对方
                            sender = chat_ent["name"] if chat_ent else f"id={sid_int}"
                        if keyword and keyword not in content:
                            continue
                        # 消息类型过滤
                        if type_filter is not None and type_id_int != type_filter:
                            continue
                        # 排除自己
                        if exclude_self and (sid_int == 1 or sender == "我"):
                            continue
                        # 发送人过滤 (多个 OR)
                        if sender_names and not any(sn in sender for sn in sender_names):
                            continue
                        # 反查 chat 显示名: 表名后 32 位 = md5(username)
                        thash = t[4:]
                        ent = name_idx.get(thash)
                        if ent:
                            chat_display = ent["name"] if ent["name"] != ent["username"] else ent["username"]
                        elif resolved_chat:
                            chat_display = resolved_chat
                        else:
                            chat_display = thash
                        # 多 chat 过滤
                        if chat_filter_set and not any(c in chat_display or c == ent.get("username", "") if ent else c == chat_display for c in chat_filter_set):
                            continue
                        # 排除联系人
                        if exclude_set and any(x in chat_display for x in exclude_set):
                            continue
                        out.append({
                            "time": _format_ts(ct),
                            "create_ts": ct,
                            "sender": sender,
                            "type": MSG_TYPE_NAMES.get(type_id_int, f"type={type_id_int}"),
                            "type_id": type_id_int,
                            "content": content[:500],
                            "chat_name": chat_display,
                        })
                        if len(out) >= limit:
                            break
            finally:
                conn.close()
        if len(out) >= limit:
            break

    # ─── 去重 ───
    if dedup_day:
        seen: set[str] = set()
        unique: list[dict] = []
        for m in out:
            day = (m.get("time") or "")[:10]
            key = f"{m.get('chat_name', '')}|{day}|{m.get('content', '')}"
            if key in seen:
                continue
            seen.add(key)
            unique.append(m)
        out = unique
    if dedup_content_latest or dedup_content_earliest:
        # 先按时间排序 (latest=保留最大 ts; earliest=保留最小 ts)
        reverse = bool(dedup_content_latest)
        out.sort(key=lambda m: m.get("create_ts", 0), reverse=reverse)
        seen_c: set[str] = set()
        unique = []
        for m in out:
            c = (m.get("content") or "").strip()
            if not c or c in seen_c:
                continue
            seen_c.add(c)
            unique.append(m)
        # 还原默认时间倒序
        out = sorted(unique, key=lambda m: m.get("create_ts", 0), reverse=True)

    return out[:limit]
