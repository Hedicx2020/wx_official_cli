"""把 (HTTP method, api path) 映射到本地 capability，并提供调用包装。

这是新「不依赖 gh_quant_ui」路径的接入点。CLI 的 wechat handler 在拿到 path 后
会优先调用 resolve_capability(); 命中时走 call_local() 而不再访问 FastAPI/HTTP。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import registry
from . import errors as wx_errors


@dataclass
class LocalResponse:
    data: Any
    content_type: str = "application/json"
    status_code: int = 200
    content: bytes | None = None
    headers: dict[str, str] | None = None


# 路由 -> 本地 capability id
ROUTE_MAP: dict[str, str] = {
    "GET /api/wechat/config": "op:wechat:config-get",
    "POST /api/wechat/config": "op:wechat:config-set",
    "GET /api/wechat/password/status": "op:wechat:password-status",
    "POST /api/wechat/password/auto": "op:wechat:password-auto",
    "POST /api/wechat/macos/resign-wechat": "op:wechat:macos-resign",
    "GET /api/wechat/sessions": "op:wechat:sessions",
    "POST /api/wechat/messages/search": "op:wechat:messages-search",
    "GET /api/wechat/search/stats": "op:wechat:search-stats",
    "GET /api/wechat/contacts/export": "op:wechat:contacts-export",
    # 图片
    "GET /api/wechat/image/list": "op:wechat:image-list",
    "GET /api/wechat/image/months": "op:wechat:image-months",
    "POST /api/wechat/image/convert": "op:wechat:image-convert",
    # LLM
    "POST /api/wechat/llm/chat": "op:wechat:llm-chat",
    "POST /api/wechat/llm/test": "op:wechat:llm-test",
    "POST /api/wechat/llm/summarize": "op:wechat:llm-summarize",
    # PDF
    "POST /api/wechat/report/pdf": "op:wechat:report-pdf",
    # 股票
    "GET /api/wechat/stock/stats": "op:wechat:stock-stats",
    "POST /api/wechat/stock/screener": "op:wechat:stock-screener",
    "POST /api/wechat/stock/review": "op:wechat:stock-review",
    "POST /api/wechat/stock/picks": "op:wechat:stock-picks",
    # 公众号
    "GET /api/wechat/articles/settings": "op:wechat:articles-settings",
    "POST /api/wechat/articles/settings": "op:wechat:articles-settings-set",
    "GET /api/wechat/articles/categories": "op:wechat:articles-categories",
    "POST /api/wechat/articles/categories": "op:wechat:articles-categories-create",
    "GET /api/wechat/articles/accounts": "op:wechat:articles-accounts",
    "POST /api/wechat/articles/accounts/dedupe": "op:wechat:articles-accounts-dedupe",
    "POST /api/wechat/articles/open_html_dir": "op:wechat:articles-open-html-dir",
    "GET /api/wechat/articles/articles": "op:wechat:articles-list",
    "POST /api/wechat/articles/sync_local": "op:wechat:articles-sync-local",
    "GET /api/wechat/articles/login/status": "op:wechat:articles-login-status",
    "POST /api/wechat/articles/login/logout": "op:wechat:articles-login-logout",
    "GET /api/wechat/articles/login/qrcode": "op:wechat:articles-login-qrcode",
    "POST /api/wechat/articles/login/poll": "op:wechat:articles-login-poll",
}


def _normalize(path: str) -> str:
    if not path:
        return ""
    norm = "/" + path.lstrip("/")
    if not norm.startswith("/api/"):
        norm = "/api" + norm
    return norm


def route_map() -> dict[str, str]:
    return dict(ROUTE_MAP)


def resolve_capability(method: str, path: str) -> str | None:
    key = f"{method.upper()} {_normalize(path)}"
    return ROUTE_MAP.get(key)


def call_local(cap_id: str, *, payload: dict[str, Any] | None = None) -> LocalResponse:
    try:
        data = registry.invoke(cap_id, payload or {})
    except wx_errors.WechatError as e:
        return LocalResponse(data=e.to_payload(), status_code=400)
    return LocalResponse(data=data, status_code=200)
