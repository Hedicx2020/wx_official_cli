"""微信公众号文章本地持久化。"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


_SCHEMA = """
CREATE TABLE IF NOT EXISTS mp_account (
    mp_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    avatar TEXT DEFAULT '',
    intro TEXT DEFAULT '',
    last_synced_at INTEGER DEFAULT 0
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
"""


@dataclass
class MpAccount:
    mp_id: str
    name: str
    avatar: str = ""
    intro: str = ""
    last_synced_at: int = 0


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


class ArticleStore:
    """单进程使用的小型 SQLite 存储。"""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "html").mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "articles.db"
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as cur:
            cur.executescript(_SCHEMA)

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
    def _safe_fs_name(value: str) -> str:
        if not value:
            return ""
        import html as html_mod

        text = html_mod.unescape(value)
        bad = '\\/:*?"<>|\n\r\t'
        cleaned = "".join("_" if ch in bad else ch for ch in text)
        return " ".join(cleaned.split()).strip()

    def _html_file(self, article_id: str) -> Path:
        article = self.get_article(article_id)
        if article is None:
            safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in article_id)
            return self.root / "html" / f"{safe}.html"

        title = self._safe_fs_name(article.title) or "untitled"
        account = self.get_mp(article.mp_id)
        account_name = self._safe_fs_name(account.name if account else article.mp_id) or "unknown"
        date = time.strftime("%Y-%m-%d", time.localtime(article.published_at or time.time()))
        short = "".join(ch for ch in article.id if ch.isalnum())[:8] or "article"
        filename = f"{title}-{account_name}-{date}-{short}.html"[:180]
        return self.root / "html" / f"{filename}.html"

    def upsert_mp(self, account: MpAccount) -> None:
        with self._conn() as cur:
            cur.execute(
                """
                INSERT INTO mp_account(mp_id, name, avatar, intro, last_synced_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(mp_id) DO UPDATE SET
                    name = excluded.name,
                    avatar = excluded.avatar,
                    intro = excluded.intro,
                    last_synced_at = excluded.last_synced_at
                """,
                (
                    account.mp_id,
                    account.name,
                    account.avatar,
                    account.intro,
                    account.last_synced_at,
                ),
            )

    def get_mp(self, mp_id: str) -> MpAccount | None:
        with self._conn() as cur:
            cur.execute(
                "SELECT mp_id, name, avatar, intro, last_synced_at FROM mp_account WHERE mp_id = ?",
                (mp_id,),
            )
            row = cur.fetchone()
        return MpAccount(*row) if row else None

    def list_mps(self, *, q: str | None = None) -> list[MpAccount]:
        sql = "SELECT mp_id, name, avatar, intro, last_synced_at FROM mp_account WHERE 1=1"
        args: list[str] = []
        if q:
            sql += " AND (name LIKE ? OR mp_id LIKE ?)"
            args.extend([f"%{q}%", f"%{q}%"])
        sql += " ORDER BY name"
        with self._conn() as cur:
            cur.execute(sql, args)
            return [MpAccount(*row) for row in cur.fetchall()]

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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    mp_id = excluded.mp_id,
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
                        item.id,
                        item.mp_id,
                        item.title,
                        item.url,
                        item.cover,
                        item.summary,
                        item.published_at,
                        item.html_path,
                        item.fetched_at,
                    )
                    for item in rows
                ],
            )
        return len(rows)

    def list_articles(
        self,
        *,
        mp_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Article]:
        sql = (
            "SELECT id, mp_id, title, url, cover, summary, published_at, html_path, fetched_at "
            "FROM article"
        )
        args: list[object] = []
        if mp_id:
            sql += " WHERE mp_id = ?"
            args.append(mp_id)
        sql += " ORDER BY published_at DESC LIMIT ? OFFSET ?"
        args.extend([int(limit), int(offset)])
        with self._conn() as cur:
            cur.execute(sql, args)
            return [Article(*row) for row in cur.fetchall()]

    def get_article(self, article_id: str) -> Article | None:
        with self._conn() as cur:
            cur.execute(
                "SELECT id, mp_id, title, url, cover, summary, published_at, html_path, fetched_at "
                "FROM article WHERE id = ?",
                (article_id,),
            )
            row = cur.fetchone()
        return Article(*row) if row else None

    def save_html(self, article_id: str, html: str) -> Path:
        path = self._html_file(article_id)
        path.write_text(html, encoding="utf-8")
        with self._conn() as cur:
            cur.execute(
                "UPDATE article SET html_path = ?, fetched_at = ? WHERE id = ?",
                (str(path), int(time.time()), article_id),
            )
        return path

    def read_html(self, article_id: str) -> str | None:
        article = self.get_article(article_id)
        if not article or not article.html_path:
            return None
        path = Path(article.html_path)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8", errors="replace")
