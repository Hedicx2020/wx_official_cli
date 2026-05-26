"""微信模块统一异常。

CLI 层捕获后转 JSON: {"ok": false, "error": {"code", "message", "hint"}}
"""

from __future__ import annotations


class WechatError(Exception):
    default_code: str = "WX_ERROR"

    def __init__(self, message: str, *, hint: str | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or self.default_code
        self.message = message
        self.hint = hint

    def to_payload(self) -> dict:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "hint": self.hint,
            },
        }


class KeyNotFound(WechatError):
    default_code = "WX_KEY_NOT_FOUND"


class DecryptFailed(WechatError):
    default_code = "WX_DECRYPT_FAILED"


class PlatformUnsupported(WechatError):
    default_code = "WX_PLATFORM_UNSUPPORTED"


class ArticleFetchBlocked(WechatError):
    default_code = "WX_ARTICLE_FETCH_BLOCKED"


class LLMAuthFailed(WechatError):
    default_code = "WX_LLM_AUTH_FAILED"


class WechatDataMissing(WechatError):
    default_code = "WX_DATA_MISSING"


class WechatInvalidInput(WechatError):
    default_code = "WX_INVALID_INPUT"
