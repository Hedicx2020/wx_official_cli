"""本地 PC 微信公众号文章扫描.

来源:
- message_*.db: 用户在聊天 / 群里收到/转发的公众号文章卡片 (type=49 appmsg type=5)
- biz_message_*.db: 用户在 PC 微信里订阅的公众号推送 (同样 type=49 appmsg)

输出: 提取出 (mp.weixin.qq.com 链接, 标题, 公众号名, 发送时间), 入 articles.db

完全本地, 不依赖任何外部 API. 用户预条件: Windows 微信已登录并已有本地消息缓存,
由 wx-official-cli 自动完成路径检测、key 提取和 DB 解密。
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# 内联轻量 XML 提取逻辑，避免拉入任何非公众号导出模块。
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_TAG_RE_CACHE: dict[str, re.Pattern] = {}
_ATTR_RE_CACHE: dict[str, re.Pattern] = {}


def _tag_text(xml: str, tag: str) -> str:
    pat = _TAG_RE_CACHE.get(tag)
    if pat is None:
        pat = re.compile(rf"<{tag}[^>]*>(.*?)</{tag}>", re.IGNORECASE | re.DOTALL)
        _TAG_RE_CACHE[tag] = pat
    m = pat.search(xml or "")
    if not m:
        return ""
    raw = m.group(1).strip()
    # 去 CDATA 包裹
    if raw.startswith("<![CDATA[") and raw.endswith("]]>"):
        raw = raw[9:-3]
    return raw.strip()


def _attr(xml: str, attr: str) -> str:
    pat = _ATTR_RE_CACHE.get(attr)
    if pat is None:
        pat = re.compile(rf'{attr}="([^"]*)"', re.IGNORECASE)
        _ATTR_RE_CACHE[attr] = pat
    m = pat.search(xml or "")
    return m.group(1) if m else ""


# 模块级标志 + 单次告警 (避免日志洪水), 让上层能感知 zstd 不可用
_zstd_unavailable_warned = False


def _decompress_content(blob) -> str:
    """zstd 解压. 失败 / 非 zstd 时尝试当 utf-8 文本读.

    Raises:
        RuntimeError: 当 blob 是 zstd 但 zstandard 库没装. 让 scan_local 能感知,
                      避免静默返回 0 篇 (历史 bug: pip 漏装 → 全部消息当 "" 处理).
    """
    global _zstd_unavailable_warned
    if blob is None:
        return ""
    if isinstance(blob, str):
        return blob
    if not isinstance(blob, (bytes, bytearray)):
        return ""
    data = bytes(blob)
    if data[:4] == _ZSTD_MAGIC:
        try:
            import zstandard as zstd  # 延迟 import, 避免常规路径加载
        except ImportError as e:
            if not _zstd_unavailable_warned:
                _zstd_unavailable_warned = True
                # 抛出让上层处理, 否则会"扫描成功 0 条"误导用户
                raise RuntimeError(
                    "缺少 zstandard 库, 无法解压 message_content. "
                    "请运行: pip install zstandard"
                ) from e
            return ""
        try:
            return zstd.ZstdDecompressor().decompress(data).decode("utf-8", errors="replace")
        except Exception:
            return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return ""


_MP_URL_RE = re.compile(
    r"https?://mp\.weixin\.qq\.com/s[/?][^\s\"'<>]+", re.IGNORECASE
)
_MSG_DB_RE = re.compile(r"^(message|biz_message)_\d+\.db$", re.IGNORECASE)
_MSG_TABLE_RE = re.compile(r"^Msg_[0-9a-f]{32}$", re.IGNORECASE)


def url_quality_score(url: str) -> int:
    """URL 越接近"永久公开链接", 分越高. 用于 dedupe 时优先保留稳定 URL.

    临时分享 / redirect 链接 (带 tempkey, 可能在几小时后失效, chksm 可能过期)
    应该让位给永久链接.
    """
    if not url:
        return 0
    if "tempkey=" in url.lower():
        return 0  # 临时链接, 最低优先级
    if re.search(r"/s/[A-Za-z0-9_-]+", url):
        return 4  # /s/SHORTID, 永久短链
    if re.search(r"[?&]mid=\d+", url) and re.search(r"[?&]idx=\d+", url):
        return 3  # __biz+mid+idx, 标准消息中心 URL
    if re.search(r"[?&]sn=", url):
        return 2
    return 1


@dataclass
class LocalArticle:
    """本地扫描出的公众号文章卡片."""
    url: str           # mp.weixin.qq.com/s/... 完整 URL (key)
    title: str
    mp_name: str       # 公众号名 (从 sourcedisplayname / appname / nickname 取)
    summary: str = ""
    cover: str = ""
    published_at: int = 0   # 消息时间, 不一定是文章原始发布时间, 但是可读

    @property
    def article_id(self) -> str:
        """从 URL 提取稳定 article id, 防止同篇文章被多次转发 / 不同访问路径产生不同 id.

        优先级 (从稳定到弱):
          1) /s/SHORTID 短链 (最稳, mp.weixin 自己生成的固定短码)
          2) ?__biz=&mid=&idx= (标准消息中心格式, 三参锁定一篇)
          3) ?__biz=&sn= (sn 是 mp.weixin 的"verifier"参数)
          4) ?__biz=&chksm= (公众号「点击查看原文」/redirect 链接, 带 tempkey 但 chksm 稳定)
          5) 兜底: base URL md5 (无任何稳定参数时, 已是残缺数据)

        策略 4 解决用户案例: 形如
          mp.weixin.qq.com/s?__biz=...&tempkey=...&chksm=...&xtrack=1&scene=90...
        的 redirect 链接, 没有 mid/idx/sn 但 chksm 是文章内容校验和, 跨转发稳定.
        """
        # 1) 短链
        m = re.search(r"/s/([A-Za-z0-9_-]+)", self.url)
        if m:
            return m.group(1)
        # 2-4) 解析 query 里的稳定参数
        qs = ""
        if "?" in self.url:
            qs = self.url.split("?", 1)[1].split("#", 1)[0]
        params: dict[str, str] = {}
        for kv in qs.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k.lower()] = v
        biz = params.get("__biz", "").rstrip("=")
        mid = params.get("mid", "")
        idx = params.get("idx", "1")
        sn = params.get("sn", "")
        chksm = params.get("chksm", "")
        if biz and mid:
            return f"biz_{biz}_{mid}_{idx}"
        if biz and sn:
            return f"biz_{biz}_sn_{sn}"
        if biz and chksm:
            return f"biz_{biz}_chk_{chksm}"
        # 5) 兜底
        base = self.url.split("?", 1)[0]
        return "u_" + hashlib.md5(base.encode("utf-8")).hexdigest()[:16]

    @property
    def mp_id(self) -> str:
        """从 URL 提取 __biz 参数; 否则用 mp_name 哈希."""
        m = re.search(r"__biz=([A-Za-z0-9=+/_-]+)", self.url)
        if m:
            return "biz_" + m.group(1).rstrip("=")
        if self.mp_name:
            return "name_" + hashlib.md5(self.mp_name.encode("utf-8")).hexdigest()[:16]
        return "unknown"


def _extract_from_appmsg_xml(xml_text: str, *, ts: int = 0) -> LocalArticle | None:
    """解析 appmsg XML, 返回 LocalArticle 或 None.

    appmsg type=5 是公众号文章卡片. 也兼容 type 缺失但 url 含 mp.weixin.qq.com 的情况.
    """
    if not xml_text:
        return None
    if "mp.weixin.qq.com" not in xml_text:
        return None

    # 尝试取标准字段
    title = _tag_text(xml_text, "title") or ""
    url = _tag_text(xml_text, "url") or ""
    summary = _tag_text(xml_text, "des") or ""
    mp_name = (
        _tag_text(xml_text, "sourcedisplayname")
        or _tag_text(xml_text, "appname")
        or _tag_text(xml_text, "nickname")
        or ""
    )
    cover = _tag_text(xml_text, "cover") or _tag_text(xml_text, "thumburl") or ""

    # url 字段可能不直接命中, 兜底从全文搜
    if "mp.weixin.qq.com" not in url:
        m = _MP_URL_RE.search(xml_text)
        if not m:
            return None
        url = m.group(0)

    # url 可能 HTML 转义; 简单还原
    url = url.replace("&amp;", "&").strip()
    if not url.startswith("http"):
        return None

    return LocalArticle(
        url=url,
        title=title.strip(),
        mp_name=mp_name.strip(),
        summary=summary.strip(),
        cover=cover.strip(),
        published_at=ts,
    )


def _extract_from_raw_content(raw, *, ts: int = 0) -> LocalArticle | None:
    """从 message_content 字段提取, 自动解压 zstd."""
    if isinstance(raw, str):
        text = raw
    elif isinstance(raw, (bytes, bytearray)):
        text = _decompress_content(bytes(raw)) or ""
    else:
        return None
    return _extract_from_appmsg_xml(text, ts=ts)


def _iter_msg_dbs(cache_dir: str) -> Iterable[Path]:
    """yield message_*.db / biz_message_*.db 路径."""
    for root, _dirs, names in os.walk(cache_dir):
        for name in names:
            if not _MSG_DB_RE.match(name):
                continue
            yield Path(root) / name


def _list_msg_tables(conn: sqlite3.Connection) -> list[str]:
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
        )
    except sqlite3.DatabaseError:
        return []
    out: list[str] = []
    for row in cur.fetchall():
        name = row[0]
        if isinstance(name, (bytes, bytearray)):
            try:
                name = bytes(name).decode("utf-8")
            except UnicodeDecodeError:
                continue
        if isinstance(name, str) and _MSG_TABLE_RE.match(name):
            out.append(name)
    return out


def _scan_table(conn: sqlite3.Connection, table: str) -> Iterable[LocalArticle]:
    """从单表里捞 type=49 + 公众号链接."""
    cur = conn.cursor()
    # 不同表 schema 可能差异: 优先字段 (local_type, message_content, create_time)
    # 容错: 如果找不到 local_type 则全表扫
    cols = _table_columns(conn, table)
    if not cols:
        return
    type_col = "local_type" if "local_type" in cols else None
    content_col = (
        "message_content" if "message_content" in cols
        else ("StrContent" if "StrContent" in cols else None)
    )
    time_col = (
        "create_time" if "create_time" in cols
        else ("CreateTime" if "CreateTime" in cols else None)
    )
    if not content_col:
        return

    where = ""
    if type_col:
        where = f"WHERE {type_col} & 0xFFFF = 49 OR {type_col} = 49"
    select_cols = [content_col]
    if time_col:
        select_cols.append(time_col)
    sql = f"SELECT {', '.join(select_cols)} FROM \"{table}\" {where}"
    try:
        cur.execute(sql)
    except sqlite3.DatabaseError:
        return
    for row in cur.fetchall():
        raw = row[0]
        ts = int(row[1]) if (time_col and len(row) > 1 and row[1]) else 0
        art = _extract_from_raw_content(raw, ts=ts)
        if art:
            yield art


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.cursor()
    try:
        cur.execute(f"PRAGMA table_info(\"{table}\")")
    except sqlite3.DatabaseError:
        return set()
    out: set[str] = set()
    for row in cur.fetchall():
        n = row[1]
        if isinstance(n, (bytes, bytearray)):
            try:
                n = bytes(n).decode("utf-8")
            except UnicodeDecodeError:
                continue
        if isinstance(n, str):
            out.add(n)
    return out


def _scan_keep_rank(a: LocalArticle) -> tuple:
    """决定 scan_local dedupe 时保留哪条. 越大越优先保留.

    规则: 有标题 > URL 越稳定 > 发布越早.
    """
    return (
        1 if a.title else 0,
        url_quality_score(a.url),
        -(a.published_at or 0),  # 取负, 让早的更大
    )


def scan_local(cache_dir: str) -> list[LocalArticle]:
    """对 cache_dir 下所有解密后的 message DB 扫公众号文章卡片. 返回去重后的列表.

    去重 key = article_id; 同 key 多条按 _scan_keep_rank 取最优 (永久链接 > 临时链接).
    """
    seen: dict[str, LocalArticle] = {}
    for db_path in _iter_msg_dbs(cache_dir):
        try:
            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.text_factory = bytes  # message_content 可能是二进制 zstd
                for table in _list_msg_tables(conn):
                    for art in _scan_table(conn, table):
                        key = art.article_id
                        prev = seen.get(key)
                        if prev is None or _scan_keep_rank(art) > _scan_keep_rank(prev):
                            seen[key] = art
        except sqlite3.DatabaseError:
            # DB 损坏, 跳过
            continue
    return list(seen.values())


def import_to_store(articles: Iterable[LocalArticle], store) -> dict[str, int]:
    """把扫描结果导入 ArticleStore. 返回 {accounts_added, articles_added}."""
    from .article_store import Article as StoreArticle, MpAccount as StoreMp
    mp_seen: dict[str, StoreMp] = {}
    arts: list[StoreArticle] = []
    now = int(time.time())
    for la in articles:
        mp_id = la.mp_id
        mp_name = la.mp_name or mp_id
        if mp_id not in mp_seen:
            mp_seen[mp_id] = StoreMp(
                mp_id=mp_id,
                name=mp_name,
                avatar="",
                intro="",
                last_synced_at=now,
            )
        arts.append(StoreArticle(
            id=la.article_id,
            mp_id=mp_id,
            title=la.title or "(无标题)",
            url=la.url,
            cover=la.cover,
            summary=la.summary,
            published_at=la.published_at,
            fetched_at=now,
        ))
    for mp in mp_seen.values():
        store.upsert_mp(mp)
    n = store.upsert_articles(arts)
    # 跑一次历史去重: 清理旧版按 url 落多条的同标题重复
    deduped = 0
    if hasattr(store, "dedupe_by_title_per_mp"):
        try:
            deduped = store.dedupe_by_title_per_mp()
        except Exception:
            deduped = 0
    return {"accounts_added": len(mp_seen), "articles_added": n, "deduped": deduped}
