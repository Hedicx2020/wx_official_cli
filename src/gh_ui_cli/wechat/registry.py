"""微信能力注册表。

设计：
- 每个本地服务函数通过 @capability(id) 注册到全局 registry。
- CLI 层和未来的 manifest 都从这里查询可调用能力。
- 不依赖 FastAPI，能力 id 形如 "op:wechat:config-get"。
"""

from __future__ import annotations

from typing import Any, Callable


Handler = Callable[[dict[str, Any]], Any]

_REGISTRY: dict[str, Handler] = {}


def capability(cap_id: str) -> Callable[[Handler], Handler]:
    def decorator(func: Handler) -> Handler:
        _REGISTRY[cap_id] = func
        return func

    return decorator


def get(cap_id: str) -> Handler | None:
    return _REGISTRY.get(cap_id)


def invoke(cap_id: str, payload: dict[str, Any]) -> Any:
    handler = _REGISTRY.get(cap_id)
    if handler is None:
        raise KeyError(f"unknown capability: {cap_id}")
    return handler(payload or {})


def list_ids() -> list[str]:
    return sorted(_REGISTRY.keys())
