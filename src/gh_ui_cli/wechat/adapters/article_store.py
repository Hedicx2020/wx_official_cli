"""公众号文章本地持久化 (SQLite + HTML 文件).

DB 与 HTML 全文分离: 元数据进 SQLite, HTML 大文本存独立文件.
路径: <data_dir>/articles/articles.db, <data_dir>/articles/html/<id>.html
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Iterator


_SCHEMA = """
CREATE TABLE IF NOT EXISTS mp_account (
    mp_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    avatar TEXT DEFAULT '',
    intro TEXT DEFAULT '',
    last_synced_at INTEGER DEFAULT 0,
    is_favorite INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS article (
    id TEXT PRIMARY KEY,
    mp_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT DEFAULT '',
    cover TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    published_at INTEGER DEFAULT 0,
    html_path TEXT DEFAULT '',
    fetched_at INTEGER DEFAULT 0,
    FOREIGN KEY (mp_id) REFERENCES mp_account(mp_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_article_mp_pub
    ON article(mp_id, published_at DESC);

CREATE TABLE IF NOT EXISTS mp_category (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS mp_account_category (
    mp_id TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    PRIMARY KEY (mp_id, category_id),
    FOREIGN KEY (mp_id) REFERENCES mp_account(mp_id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES mp_category(category_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mac_cat ON mp_account_category(category_id);

CREATE TABLE IF NOT EXISTS article_analysis (
    analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER,
    category_name TEXT NOT NULL,
    since_date TEXT,
    article_count INTEGER NOT NULL,
    llm_provider TEXT NOT NULL,
    llm_model TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    result_text TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    duration_ms INTEGER DEFAULT 0,
    FOREIGN KEY (category_id) REFERENCES mp_category(category_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_analysis_cat
    ON article_analysis(category_id, created_at DESC);
"""


@dataclass
class MpAccount:
    mp_id: str
    name: str
    avatar: str = ""
    intro: str = ""
    last_synced_at: int = 0
    is_favorite: int = 0


@dataclass
class Article:
    id: str
    mp_id: str
    title: str
    url: str = ""
    cover: str = ""
    summary: str = ""
    published_at: int = 0
    html_path: str = ""
    fetched_at: int = 0


@dataclass
class MpCategory:
    category_id: int
    name: str
    sort_order: int = 0
    created_at: int = 0
    account_count: int = 0
    article_count: int = 0


@dataclass
class ArticleAnalysisRecord:
    analysis_id: int
    category_id: int | None
    category_name: str
    since_date: str | None
    article_count: int
    llm_provider: str
    llm_model: str
    prompt_text: str
    result_text: str
    created_at: int
    duration_ms: int = 0


class ArticleStore:
    """单进程使用的小型持久化层."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "html").mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "articles.db"
        self._init_schema()

    # ─── 内部 ───
    def _init_schema(self) -> None:
        with self._conn() as cur:
            cur.executescript(_SCHEMA)
            # 老 DB 兜底 migration: is_favorite 列可能不存在
            cur.execute("PRAGMA table_info(mp_account)")
            cols = {row[1] for row in cur.fetchall()}
            if "is_favorite" not in cols:
                cur.execute("ALTER TABLE mp_account ADD COLUMN is_favorite INTEGER DEFAULT 0")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Cursor]:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            cur = conn.cursor()
            yield cur
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _safe_fs_name(s: str) -> str:
        """清理跨平台 (Windows/macOS) 文件名不允许的字符, 折叠空白, 反转义 HTML entity."""
        if not s:
            return ""
        import html as _html
        s = _html.unescape(s)
        bad = '\\/:*?"<>|\n\r\t'
        out = "".join("_" if c in bad else c for c in s)
        return " ".join(out.split()).strip()

    def _html_file(self, article_id: str) -> Path:
        """文件命名: <标题>-<公众号名>-<YYYY-MM-DD>-<短码>.html

        短码取 article_id 前 8 位 hex, 避免极少数同标题+同公众号+同日的多篇撞名。
        若 article 元数据缺失 (例如 save 前 db 还没 upsert), 退回旧规则。
        """
        art = self.get_article(article_id)
        if art is None:
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in article_id)
            return self.root / "html" / f"{safe}.html"
        title = self._safe_fs_name(art.title) or "untitled"
        mp = self.get_mp(art.mp_id) if art.mp_id else None
        mp_name = self._safe_fs_name(mp.name) if mp else self._safe_fs_name(art.mp_id)
        date_str = ""
        if art.published_at:
            try:
                date_str = time.strftime("%Y-%m-%d", time.localtime(int(art.published_at)))
            except (ValueError, OSError):
                date_str = ""
        # 标题最多保留 100 字符防超长 (中文按 1 字符算, NTFS/APFS 都支持)
        if len(title) > 100:
            title = title[:100]
        parts = [title]
        if mp_name:
            parts.append(mp_name)
        if date_str:
            parts.append(date_str)
        short = "".join(c for c in article_id if c.isalnum())[:8]
        if short:
            parts.append(short)
        name = "-".join(parts)
        return self.root / "html" / f"{name}.html"

    # ─── MpAccount ───
    def upsert_mp(self, mp: MpAccount) -> None:
        with self._conn() as cur:
            cur.execute(
                """
                INSERT INTO mp_account(mp_id, name, avatar, intro, last_synced_at, is_favorite)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(mp_id) DO UPDATE SET
                    name = excluded.name,
                    avatar = excluded.avatar,
                    intro = excluded.intro,
                    last_synced_at = MAX(mp_account.last_synced_at, excluded.last_synced_at)
                """,
                (mp.mp_id, mp.name, mp.avatar, mp.intro, mp.last_synced_at, mp.is_favorite),
            )

    def set_favorite(self, mp_id: str, is_favorite: bool) -> None:
        with self._conn() as cur:
            cur.execute(
                "UPDATE mp_account SET is_favorite = ? WHERE mp_id = ?",
                (1 if is_favorite else 0, mp_id),
            )

    def list_mps(self, *, only_favorite: bool = False, q: str | None = None) -> list[MpAccount]:
        sql = "SELECT mp_id, name, avatar, intro, last_synced_at, is_favorite FROM mp_account WHERE 1=1"
        args: list = []
        if only_favorite:
            sql += " AND is_favorite = 1"
        if q:
            sql += " AND lower(name) LIKE ?"
            args.append(f"%{q.lower()}%")
        sql += " ORDER BY is_favorite DESC, name"
        with self._conn() as cur:
            cur.execute(sql, args)
            return [MpAccount(*row) for row in cur.fetchall()]

    def list_mps_with_stats(self, *, only_favorite: bool = False, q: str | None = None) -> list[dict]:
        """list_mps + 每个 mp 的文章总数和已抓全文数, 单 SQL JOIN. 给前端选公众号批量抓时提示进度."""
        sql = (
            "SELECT m.mp_id, m.name, m.avatar, m.intro, m.last_synced_at, m.is_favorite, "
            "  COUNT(a.id) AS total, "
            "  SUM(CASE WHEN a.html_path != '' THEN 1 ELSE 0 END) AS fetched "
            "FROM mp_account m LEFT JOIN article a ON a.mp_id = m.mp_id "
            "WHERE 1=1"
        )
        args: list = []
        if only_favorite:
            sql += " AND m.is_favorite = 1"
        if q:
            sql += " AND lower(m.name) LIKE ?"
            args.append(f"%{q.lower()}%")
        sql += " GROUP BY m.mp_id ORDER BY m.is_favorite DESC, m.name"
        with self._conn() as cur:
            cur.execute(sql, args)
            return [
                {
                    "mp_id": row[0], "name": row[1], "avatar": row[2] or "",
                    "intro": row[3] or "", "last_synced_at": int(row[4] or 0),
                    "is_favorite": bool(row[5]),
                    "articles_total": int(row[6] or 0),
                    "articles_fetched": int(row[7] or 0),
                }
                for row in cur.fetchall()
            ]

    def get_mp(self, mp_id: str) -> MpAccount | None:
        with self._conn() as cur:
            cur.execute(
                "SELECT mp_id, name, avatar, intro, last_synced_at, is_favorite FROM mp_account WHERE mp_id = ?",
                (mp_id,),
            )
            row = cur.fetchone()
            return MpAccount(*row) if row else None

    def delete_mp(self, mp_id: str) -> int:
        """删除公众号 + 关联文章 + HTML 文件. 返回删除的文章数."""
        with self._conn() as cur:
            cur.execute(
                "SELECT id, html_path FROM article WHERE mp_id = ?", (mp_id,)
            )
            rows = cur.fetchall()
            for _, path in rows:
                if path:
                    p = Path(path)
                    if p.exists():
                        p.unlink(missing_ok=True)
            cur.execute("DELETE FROM article WHERE mp_id = ?", (mp_id,))
            cur.execute("DELETE FROM mp_account WHERE mp_id = ?", (mp_id,))
            return len(rows)

    def touch_mp_synced(self, mp_id: str, ts: int | None = None) -> None:
        ts = ts if ts is not None else int(time.time())
        with self._conn() as cur:
            cur.execute(
                "UPDATE mp_account SET last_synced_at = ? WHERE mp_id = ?",
                (ts, mp_id),
            )

    # ─── Article ───
    def dedupe_by_title_per_mp(self) -> int:
        """合并历史"同 mp_id + 同 title" 的文章: 保留永久链接 + 最早一条, 删除临时/弱链接.

        排序优先级 (留下的是排第一):
          1) URL 质量分高 (永久 /s/SHORTID 或 __biz+mid+idx > 带 tempkey 的临时链接)
          2) published_at 早 (假设最早转发的是原始来源)
          3) id 字典序

        删除时连带清掉 html 文件.
        """
        from .local_articles import url_quality_score
        with self._conn() as cur:
            cur.execute(
                "SELECT id, mp_id, title, url, html_path, published_at FROM article WHERE title != ''"
            )
            rows = cur.fetchall()
        if not rows:
            return 0
        # 按 (mp_id, title) 分组
        groups: dict[tuple, list] = {}
        for r in rows:
            groups.setdefault((r[1], r[2]), []).append(r)
        # 每组挑要删的 (排名第 2 起)
        to_delete: list[tuple[str, str]] = []
        for items in groups.values():
            if len(items) <= 1:
                continue
            items.sort(
                key=lambda r: (
                    -url_quality_score(r[3] or ""),
                    r[5] or 0,
                    r[0],
                )
            )
            for r in items[1:]:
                to_delete.append((r[0], r[4] or ""))
        if not to_delete:
            return 0
        # 先删 html 文件
        for _aid, html_path in to_delete:
            if html_path:
                p = Path(html_path)
                if p.exists():
                    p.unlink(missing_ok=True)
        with self._conn() as cur:
            cur.executemany(
                "DELETE FROM article WHERE id = ?",
                [(aid,) for aid, _ in to_delete],
            )
        return len(to_delete)

    def upsert_articles(self, items: Iterable[Article]) -> int:
        rows = list(items)
        if not rows:
            return 0
        with self._conn() as cur:
            cur.executemany(
                """
                INSERT INTO article(
                    id, mp_id, title, url, cover, summary,
                    published_at, html_path, fetched_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    url = excluded.url,
                    cover = excluded.cover,
                    summary = excluded.summary,
                    published_at = excluded.published_at,
                    html_path = COALESCE(NULLIF(excluded.html_path, ''), article.html_path),
                    fetched_at = MAX(article.fetched_at, excluded.fetched_at)
                """,
                [
                    (
                        a.id, a.mp_id, a.title, a.url, a.cover, a.summary,
                        a.published_at, a.html_path, a.fetched_at,
                    )
                    for a in rows
                ],
            )
        return len(rows)

    def list_articles(
        self,
        mp_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        since: int | None = None,
    ) -> list[Article]:
        q = (
            "SELECT id, mp_id, title, url, cover, summary, published_at, html_path, fetched_at "
            "FROM article WHERE 1=1"
        )
        args: list = []
        if mp_id:
            q += " AND mp_id = ?"
            args.append(mp_id)
        if since:
            q += " AND published_at >= ?"
            args.append(since)
        q += " ORDER BY published_at DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        with self._conn() as cur:
            cur.execute(q, args)
            return [Article(*row) for row in cur.fetchall()]

    def count_articles(self, mp_id: str | None = None) -> int:
        q = "SELECT COUNT(*) FROM article WHERE 1=1"
        args: list = []
        if mp_id:
            q += " AND mp_id = ?"
            args.append(mp_id)
        with self._conn() as cur:
            cur.execute(q, args)
            return int(cur.fetchone()[0])

    def get_article(self, article_id: str) -> Article | None:
        with self._conn() as cur:
            cur.execute(
                "SELECT id, mp_id, title, url, cover, summary, published_at, html_path, fetched_at "
                "FROM article WHERE id = ?",
                (article_id,),
            )
            row = cur.fetchone()
            return Article(*row) if row else None

    def save_article_html(self, article_id: str, html: str) -> str:
        path = self._html_file(article_id)
        path.write_text(html, encoding="utf-8")
        with self._conn() as cur:
            cur.execute(
                "UPDATE article SET html_path = ?, fetched_at = ? WHERE id = ?",
                (str(path), int(time.time()), article_id),
            )
        return str(path)

    def read_article_html(self, article_id: str) -> str | None:
        art = self.get_article(article_id)
        if not art or not art.html_path:
            return None
        p = Path(art.html_path)
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8")

    # ─── Category ───
    def list_categories(self) -> list[MpCategory]:
        """列分类, 顺带聚合每个分类下的账号数 + 文章数."""
        sql = (
            "SELECT c.category_id, c.name, c.sort_order, c.created_at, "
            "  COUNT(DISTINCT mac.mp_id) AS acc_n, "
            "  COUNT(DISTINCT a.id) AS art_n "
            "FROM mp_category c "
            "LEFT JOIN mp_account_category mac ON mac.category_id = c.category_id "
            "LEFT JOIN article a ON a.mp_id = mac.mp_id "
            "GROUP BY c.category_id "
            "ORDER BY c.sort_order, c.name"
        )
        with self._conn() as cur:
            cur.execute(sql)
            return [
                MpCategory(
                    category_id=int(row[0]), name=row[1],
                    sort_order=int(row[2] or 0), created_at=int(row[3] or 0),
                    account_count=int(row[4] or 0),
                    article_count=int(row[5] or 0),
                )
                for row in cur.fetchall()
            ]

    def create_category(self, name: str) -> MpCategory:
        name = (name or "").strip()
        if not name:
            raise ValueError("分类名不能为空")
        ts = int(time.time())
        with self._conn() as cur:
            cur.execute(
                "INSERT INTO mp_category(name, sort_order, created_at) VALUES (?, 0, ?)",
                (name, ts),
            )
            cid = int(cur.lastrowid or 0)
        return MpCategory(category_id=cid, name=name, sort_order=0, created_at=ts)

    def rename_category(self, category_id: int, name: str) -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("分类名不能为空")
        with self._conn() as cur:
            cur.execute(
                "UPDATE mp_category SET name = ? WHERE category_id = ?",
                (name, category_id),
            )

    def delete_category(self, category_id: int) -> None:
        with self._conn() as cur:
            cur.execute("DELETE FROM mp_category WHERE category_id = ?", (category_id,))

    def get_category(self, category_id: int) -> MpCategory | None:
        with self._conn() as cur:
            cur.execute(
                "SELECT category_id, name, sort_order, created_at "
                "FROM mp_category WHERE category_id = ?",
                (category_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return MpCategory(
                category_id=int(row[0]), name=row[1],
                sort_order=int(row[2] or 0), created_at=int(row[3] or 0),
            )

    def get_account_categories(self, mp_id: str) -> list[int]:
        with self._conn() as cur:
            cur.execute(
                "SELECT category_id FROM mp_account_category WHERE mp_id = ?",
                (mp_id,),
            )
            return [int(r[0]) for r in cur.fetchall()]

    def set_account_categories(self, mp_id: str, category_ids: list[int]) -> None:
        """全量替换某账号的分类归属."""
        ids = [int(c) for c in category_ids if c is not None]
        with self._conn() as cur:
            cur.execute("DELETE FROM mp_account_category WHERE mp_id = ?", (mp_id,))
            if ids:
                cur.executemany(
                    "INSERT OR IGNORE INTO mp_account_category(mp_id, category_id) VALUES (?, ?)",
                    [(mp_id, cid) for cid in ids],
                )

    def list_mp_ids_by_category(self, category_id: int) -> list[str]:
        with self._conn() as cur:
            cur.execute(
                "SELECT mp_id FROM mp_account_category WHERE category_id = ?",
                (category_id,),
            )
            return [str(r[0]) for r in cur.fetchall()]

    def list_mps_by_category(self, category_id: int) -> list[MpAccount]:
        sql = (
            "SELECT m.mp_id, m.name, m.avatar, m.intro, m.last_synced_at, m.is_favorite "
            "FROM mp_account m "
            "JOIN mp_account_category mac ON mac.mp_id = m.mp_id "
            "WHERE mac.category_id = ? "
            "ORDER BY m.is_favorite DESC, m.name"
        )
        with self._conn() as cur:
            cur.execute(sql, (category_id,))
            return [MpAccount(*row) for row in cur.fetchall()]

    def get_mp_categories_map(self, mp_ids: list[str]) -> dict[str, list[int]]:
        """批量取多个 mp_id 的分类归属, 返回 {mp_id: [cid, ...]}."""
        if not mp_ids:
            return {}
        placeholders = ",".join("?" for _ in mp_ids)
        with self._conn() as cur:
            cur.execute(
                f"SELECT mp_id, category_id FROM mp_account_category WHERE mp_id IN ({placeholders})",
                list(mp_ids),
            )
            out: dict[str, list[int]] = {mid: [] for mid in mp_ids}
            for mid, cid in cur.fetchall():
                out.setdefault(str(mid), []).append(int(cid))
        return out

    def purge_missing_html_in_category(self, category_id: int) -> int:
        """该分类下 html_path 非空但文件已不存在的 article, 把 html_path / fetched_at 清空.

        用户可能手动删了 html 目录, 这时 db 仍指向旧路径会导致 UI 算出错误的 "已抓" 计数。
        返回清理的条数。
        """
        sql = (
            "SELECT a.id, a.html_path FROM article a "
            "JOIN mp_account_category mac ON mac.mp_id = a.mp_id "
            "WHERE mac.category_id = ? AND a.html_path != ''"
        )
        missing: list[str] = []
        with self._conn() as cur:
            cur.execute(sql, (category_id,))
            for aid, path in cur.fetchall():
                if path and not Path(path).exists():
                    missing.append(aid)
        if not missing:
            return 0
        with self._conn() as cur:
            cur.executemany(
                "UPDATE article SET html_path = '', fetched_at = 0 WHERE id = ?",
                [(aid,) for aid in missing],
            )
        return len(missing)

    def list_articles_by_category(
        self,
        category_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
        since: int | None = None,
    ) -> list[Article]:
        sql = (
            "SELECT a.id, a.mp_id, a.title, a.url, a.cover, a.summary, "
            "  a.published_at, a.html_path, a.fetched_at "
            "FROM article a "
            "JOIN mp_account_category mac ON mac.mp_id = a.mp_id "
            "WHERE mac.category_id = ?"
        )
        args: list = [category_id]
        if since:
            sql += " AND a.published_at >= ?"
            args.append(since)
        sql += " ORDER BY a.published_at DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        with self._conn() as cur:
            cur.execute(sql, args)
            return [Article(*row) for row in cur.fetchall()]

    def count_articles_by_category(self, category_id: int, since: int | None = None) -> int:
        sql = (
            "SELECT COUNT(DISTINCT a.id) FROM article a "
            "JOIN mp_account_category mac ON mac.mp_id = a.mp_id "
            "WHERE mac.category_id = ?"
        )
        args: list = [category_id]
        if since:
            sql += " AND a.published_at >= ?"
            args.append(since)
        with self._conn() as cur:
            cur.execute(sql, args)
            return int(cur.fetchone()[0])

    # ─── 分析记录 ───
    def save_analysis(self, rec: ArticleAnalysisRecord) -> int:
        with self._conn() as cur:
            cur.execute(
                """
                INSERT INTO article_analysis(
                    category_id, category_name, since_date, article_count,
                    llm_provider, llm_model, prompt_text, result_text,
                    created_at, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.category_id, rec.category_name, rec.since_date, rec.article_count,
                    rec.llm_provider, rec.llm_model, rec.prompt_text, rec.result_text,
                    rec.created_at, rec.duration_ms,
                ),
            )
            return int(cur.lastrowid or 0)

    def list_analyses(
        self, category_id: int | None = None, limit: int = 50
    ) -> list[ArticleAnalysisRecord]:
        sql = (
            "SELECT analysis_id, category_id, category_name, since_date, article_count, "
            "  llm_provider, llm_model, prompt_text, result_text, created_at, duration_ms "
            "FROM article_analysis"
        )
        args: list = []
        if category_id is not None:
            sql += " WHERE category_id = ?"
            args.append(category_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self._conn() as cur:
            cur.execute(sql, args)
            return [
                ArticleAnalysisRecord(
                    analysis_id=int(r[0]),
                    category_id=int(r[1]) if r[1] is not None else None,
                    category_name=r[2],
                    since_date=r[3],
                    article_count=int(r[4] or 0),
                    llm_provider=r[5],
                    llm_model=r[6],
                    prompt_text=r[7],
                    result_text=r[8],
                    created_at=int(r[9] or 0),
                    duration_ms=int(r[10] or 0),
                )
                for r in cur.fetchall()
            ]

    def get_analysis(self, analysis_id: int) -> ArticleAnalysisRecord | None:
        items = []
        with self._conn() as cur:
            cur.execute(
                "SELECT analysis_id, category_id, category_name, since_date, article_count, "
                "  llm_provider, llm_model, prompt_text, result_text, created_at, duration_ms "
                "FROM article_analysis WHERE analysis_id = ?",
                (analysis_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return ArticleAnalysisRecord(
                analysis_id=int(row[0]),
                category_id=int(row[1]) if row[1] is not None else None,
                category_name=row[2],
                since_date=row[3],
                article_count=int(row[4] or 0),
                llm_provider=row[5],
                llm_model=row[6],
                prompt_text=row[7],
                result_text=row[8],
                created_at=int(row[9] or 0),
                duration_ms=int(row[10] or 0),
            )
        return items[0] if items else None

    def delete_analysis(self, analysis_id: int) -> None:
        with self._conn() as cur:
            cur.execute("DELETE FROM article_analysis WHERE analysis_id = ?", (analysis_id,))

    # ─── 重名账号合并 ───
    def merge_duplicate_accounts(self) -> dict:
        """合并同名公众号: 把 name_xxx (无 __biz 兜底 ID) 的内容合并到对应 biz_xxx 账号上.

        合并条件: 同名 + 至少有一个 biz_ 开头 + 至少有一个 name_ 开头.
        合并动作:
          1) 选 biz_ 中文章数最多的为 primary
          2) 把 name_ 账号下所有 article.mp_id 改成 primary
             (article.id 是 PK, 不受影响; 若 primary 已有同 id 文章则保留 primary 的)
          3) 把 name_ 账号的分类绑定迁移到 primary
          4) 删除 name_ 账号 (CASCADE 不会再删文章, 因为已迁走)

        两个 biz_ 账号同名 (如「半导体行业观察」「寻瑕记」) 不合并 — 可能是真不同的公众号.

        返回: {
          merged_groups: int,           # 合并的同名组数
          dropped_accounts: int,        # 删除的 name_ 账号数
          rewired_articles: int,        # 改写 mp_id 的文章数
          skipped_dupes: list[str],     # 仍剩多条记录的同名 (用户手动决定)
        }
        """
        with self._conn() as cur:
            cur.execute("SELECT mp_id, name FROM mp_account ORDER BY name")
            all_rows = cur.fetchall()
        from collections import defaultdict
        by_name: dict[str, list[str]] = defaultdict(list)
        for mp_id, name in all_rows:
            if name:
                by_name[name].append(mp_id)

        merged_groups = 0
        dropped = 0
        rewired = 0
        skipped: list[str] = []

        for name, ids in by_name.items():
            if len(ids) <= 1:
                continue
            biz_ids = [i for i in ids if i.startswith("biz_")]
            name_ids = [i for i in ids if i.startswith("name_")]
            other_ids = [i for i in ids if not i.startswith(("biz_", "name_"))]

            # 没有 biz_ 锚点 (全都是 name_), 不合并 (理论上 name 哈希相同会得到同 mp_id, 不会出现)
            if not biz_ids:
                skipped.append(name)
                continue

            # 选 primary: biz_ 中文章数最多的
            with self._conn() as cur:
                cur.execute(
                    "SELECT mp_id, COUNT(*) FROM article WHERE mp_id IN ("
                    + ",".join("?" for _ in biz_ids)
                    + ") GROUP BY mp_id",
                    biz_ids,
                )
                cnt_map = {row[0]: int(row[1]) for row in cur.fetchall()}
            primary = max(biz_ids, key=lambda i: cnt_map.get(i, 0))

            # 多个 biz_ 共存 (真不同公众号或脏数据): 不合并 biz_ 之间, 但 name_ 仍可并入 primary
            if len(biz_ids) > 1:
                skipped.append(name)

            # 合并 name_ → primary
            losers = name_ids + other_ids
            if not losers:
                continue
            for loser in losers:
                with self._conn() as cur:
                    # 1) 改写 article.mp_id (id 冲突会被 OR IGNORE 跳过, 老 article 直接删)
                    cur.execute(
                        "UPDATE OR IGNORE article SET mp_id = ? WHERE mp_id = ?",
                        (primary, loser),
                    )
                    rewired += cur.rowcount or 0
                    cur.execute("DELETE FROM article WHERE mp_id = ?", (loser,))
                    # 2) 迁分类绑定 (主已绑则忽略)
                    cur.execute(
                        "INSERT OR IGNORE INTO mp_account_category(mp_id, category_id) "
                        "SELECT ?, category_id FROM mp_account_category WHERE mp_id = ?",
                        (primary, loser),
                    )
                    # 3) 删 loser 账号 (CASCADE 自动清掉 mp_account_category)
                    cur.execute("DELETE FROM mp_account WHERE mp_id = ?", (loser,))
                    dropped += 1
            merged_groups += 1

        return {
            "merged_groups": merged_groups,
            "dropped_accounts": dropped,
            "rewired_articles": rewired,
            "skipped_dupes": skipped,
        }


def to_dict(obj) -> dict:
    """dataclass → dict 的小工具."""
    return asdict(obj)
