"""微信模块数据模型与默认值。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_CONFIG: dict[str, str] = {
    "database_password": "",
    "wechat_files_path": "",
    "default_start_date": "",
    "default_end_date": "",
    "default_chat_name": "",
    "default_keyword": "",
    "delete_keywords": "",
    "last_updated": "",
    "llm_api_base": "https://api.deepseek.com/v1",
    "llm_api_key": "",
    "llm_model": "deepseek-chat",
}


@dataclass
class MessageQuery:
    start_date: str = ""
    end_date: str = ""
    keyword: str = ""
    chat_name: str = ""
    limit: int = 100
    talker: str = ""
    exclude_keywords: list[str] = field(default_factory=list)


@dataclass
class SessionInfo:
    talker: str
    display_name: str
    last_message: str = ""
    last_time: str = ""
    unread: int = 0


@dataclass
class ArticleAccount:
    mp_id: str
    name: str
    avatar: str = ""
    fakeid: str = ""
    categories: list[int] = field(default_factory=list)
    favorite: bool = False
    last_fetched_at: str = ""


@dataclass
class ArticleRecord:
    article_id: str
    title: str
    mp_id: str
    publish_time: str = ""
    fetched_at: str = ""
    html_path: str = ""
    url: str = ""
    summary: str = ""


def jsonable(obj: Any) -> Any:
    if hasattr(obj, "__dict__"):
        return {k: jsonable(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, list):
        return [jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    return obj
