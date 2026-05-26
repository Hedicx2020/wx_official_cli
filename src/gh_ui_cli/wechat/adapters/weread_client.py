"""微信读书订阅公众号接口封装 (走 platform 转发协议).

设计参考 cooderl/wewe-rss 的 trpc.service.ts:
1. 用户对接的不是 weread.qq.com 直连, 而是 platform 转发服务
   (默认 https://weread.111965.xyz, 备用 https://weread.965111.xyz, 也可自建);
2. platform 内部用微信读书 token 伪装请求, 规避 mp.weixin.qq.com 反爬;
3. 用户体验:
   - 首次: 扫码登录拿 token (1 次性)
   - 添加公众号: 贴一篇该公众号文章 URL → 系统反查 mpId
   - 之后: 完全自动同步历史 + 增量

所有网络调用走 httpx, 可注入 transport 做单测;
当 platform 服务出错时降级到空列表 / offline payload, UI 不崩.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


# 默认走 wewe-rss 公共转发服务 (用户可在配置里改)
DEFAULT_PLATFORM_URL = "https://weread.111965.xyz"
FALLBACK_PLATFORM_URL = "https://weread.965111.xyz"


# Platform 端点 (与 wewe-rss configuration 对齐)
EP_LOGIN_CREATE = "/api/v2/login/platform"
EP_LOGIN_RESULT = "/api/v2/login/platform/{id}"
EP_MP_INFO = "/api/v2/platform/wxs2mp"
EP_MP_ARTICLES = "/api/v2/platform/mps/{mp_id}/articles"


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


@dataclass
class WereadCredentials:
    """登录后从 platform 拿到的凭证.

    - vid: 微信读书用户 id (xid 头里发);
    - token: Bearer token, 调 mp/article 接口要带.
    - expires_at: epoch seconds, 0 表示未知;
    - cookie: 兜底 (旧实现兼容).
    """

    vid: str = ""
    skey: str = ""
    rt: str = ""
    access_token: str = ""
    expires_at: int = 0
    cookie: str = ""

    @property
    def token(self) -> str:
        # access_token 是新名, cookie 兜底
        return self.access_token or self.skey or self.cookie

    def is_expired(self, *, leeway: int = 60) -> bool:
        if self.expires_at == 0:
            return False
        return time.time() + leeway >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "vid": self.vid,
            "skey": self.skey,
            "rt": self.rt,
            "access_token": self.access_token,
            "expires_at": self.expires_at,
            "cookie": self.cookie,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "WereadCredentials | None":
        if data is None:
            return None
        return cls(
            vid=str(data.get("vid", "")),
            skey=str(data.get("skey", "")),
            rt=str(data.get("rt", "")),
            access_token=str(data.get("access_token", "")),
            expires_at=int(data.get("expires_at", 0) or 0),
            cookie=str(data.get("cookie", "")),
        )


@dataclass
class MpAccountDTO:
    mp_id: str
    name: str
    avatar: str = ""
    intro: str = ""


@dataclass
class ArticleDTO:
    id: str
    mp_id: str
    title: str
    url: str = ""
    cover: str = ""
    summary: str = ""
    published_at: int = 0


@dataclass
class QrCodePayload:
    """二维码登录素材, 前端 qrcode 包渲染."""
    qr_url: str
    image_url: str
    scan_id: str


class WereadError(RuntimeError):
    pass


class WereadClient:
    """与 platform 服务通信的轻封装.

    每个实例对应一个微信读书账号. 测试时可注入 transport.
    """

    def __init__(
        self,
        creds: WereadCredentials | None = None,
        *,
        platform_url: str = DEFAULT_PLATFORM_URL,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ):
        self.creds = creds or WereadCredentials()
        self.platform_url = platform_url.rstrip("/")
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout,
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            base_url=self.platform_url,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "WereadClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ─── 内部 ───
    def _auth_headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.creds.vid:
            h["xid"] = self.creds.vid
        if self.creds.token:
            h["Authorization"] = f"Bearer {self.creds.token}"
        return h

    def _request(self, method: str, path: str, *, with_auth: bool = True, **kwargs) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        if with_auth:
            headers.update(self._auth_headers())
        try:
            resp = self._client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as e:
            raise WereadError(f"network error: {e}") from e
        if resp.status_code == 401:
            raise WereadError(f"401 unauthorized: token 失效 (path={path})")
        if resp.status_code == 429:
            raise WereadError(f"429 too many requests: 触发 platform 限流 (path={path})")
        if resp.status_code >= 400:
            raise WereadError(
                f"HTTP {resp.status_code} on {path}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except Exception:
            return {"_raw": resp.text}

    # ─── 登录 ───
    def get_login_qrcode(self) -> QrCodePayload:
        """Platform 创建登录请求, 返回二维码 url + scan_id (异步轮询用)."""
        data = self._request("POST", EP_LOGIN_CREATE, with_auth=False, json={})
        scan_id = str(data.get("id") or data.get("uuid") or "")
        url = str(data.get("url") or data.get("qrcode") or "")
        if not scan_id or not url:
            raise WereadError(f"platform 返回缺字段: {data}")
        # url 已经是二维码内嵌内容; image_url 给前端做兜底图
        image_url = url if url.startswith("http") else ""
        return QrCodePayload(qr_url=url, image_url=image_url, scan_id=scan_id)

    def poll_login(self, scan_id: str) -> dict[str, Any]:
        """轮询扫码状态. 返回 {status, credentials?}."""
        path = EP_LOGIN_RESULT.format(id=scan_id)
        try:
            data = self._request("GET", path, with_auth=False)
        except WereadError as e:
            return {"status": "error", "message": str(e)}

        message = str(data.get("message") or "").lower()
        # platform 协议: confirmed 时返回 vid + token
        token = str(data.get("token") or data.get("accessToken") or "")
        vid = str(data.get("vid") or "")
        if token and vid:
            creds = WereadCredentials(
                vid=vid,
                access_token=token,
                expires_at=int(data.get("expires_at", 0) or 0),
            )
            self.creds = creds
            return {"status": "confirmed", "credentials": creds.to_dict()}
        if "scan" in message or "scanned" in message:
            return {"status": "scanned"}
        if "expir" in message or "timeout" in message:
            return {"status": "expired"}
        return {"status": "pending"}

    # ─── 业务 ───
    def get_mp_info_by_url(self, wxs_link: str) -> MpAccountDTO:
        """用一篇 mp.weixin.qq.com/s/... URL 反查公众号信息.

        这是用户"添加订阅"的入口: 不依赖在微信读书 App 里订阅,
        只要能找到任意一篇该公众号的文章 URL 就能加进来.
        """
        if not wxs_link.startswith("https://mp.weixin.qq.com/s"):
            raise WereadError("URL 必须以 https://mp.weixin.qq.com/s 开头")
        data = self._request("POST", EP_MP_INFO, json={"wxsLink": wxs_link})
        # platform 返回字段名兼容
        mp_id = str(data.get("id") or data.get("mp_id") or data.get("biz") or "")
        if not mp_id:
            raise WereadError(f"platform 未返回 mpId: {data}")
        return MpAccountDTO(
            mp_id=mp_id,
            name=str(data.get("name") or data.get("title") or mp_id),
            avatar=str(data.get("avatar") or data.get("cover") or ""),
            intro=str(data.get("intro") or data.get("desc") or ""),
        )

    def list_mp_articles(
        self,
        mp_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> list[ArticleDTO]:
        path = EP_MP_ARTICLES.format(mp_id=mp_id)
        params: dict[str, Any] = {"page": page, "pageSize": page_size}
        data = self._request("GET", path, params=params)
        items = data if isinstance(data, list) else (
            data.get("data") or data.get("items") or data.get("list") or []
        )
        out: list[ArticleDTO] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            art_id = str(it.get("id") or it.get("article_id") or "")
            if not art_id:
                continue
            out.append(ArticleDTO(
                id=art_id,
                mp_id=mp_id,
                title=str(it.get("title") or ""),
                url=str(it.get("url") or it.get("link") or ""),
                cover=str(it.get("cover") or it.get("picUrl") or ""),
                summary=str(it.get("summary") or it.get("digest") or ""),
                published_at=int(
                    it.get("published_at")
                    or it.get("publishTime")
                    or it.get("ctime")
                    or 0
                ),
            ))
        return out

    def fetch_article_html(self, article_id: str, *, url: str = "") -> str:
        """直接用 mp.weixin.qq.com URL 拿正文 HTML.

        platform 协议下没有专门的"取正文"端点 — 用 articleId 拼出 mp 短链直接 GET.
        """
        target = url or f"https://mp.weixin.qq.com/s/{article_id}"
        try:
            resp = httpx.get(
                target,
                headers={"User-Agent": DEFAULT_HEADERS["User-Agent"]},
                timeout=15,
                follow_redirects=True,
            )
        except httpx.HTTPError as e:
            raise WereadError(f"fetch html error: {e}") from e
        if resp.status_code >= 400:
            raise WereadError(f"HTTP {resp.status_code} on {target}")
        return resp.text


def make_client_from_dict(
    data: dict[str, Any] | None,
    *,
    platform_url: str = DEFAULT_PLATFORM_URL,
) -> WereadClient:
    """从持久化 dict 构造 client."""
    creds = WereadCredentials.from_dict(data) if data else WereadCredentials()
    return WereadClient(creds=creds, platform_url=platform_url)
