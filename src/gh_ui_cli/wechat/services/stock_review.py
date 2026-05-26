"""股票筛选 / K 线复盘 / 选股。

底层依赖：
- stock_filter.py: pymysql JYDB（远程数据库，私有库）
- stock_kline.py: akshare + pyecharts
- stock_selection.py: 综合选股

stock_filter 需要 JYDB 连接信息，未配置时返回 NEED_CONFIG。
其余的依赖在 full extra 中（akshare/pyecharts），缺失时报 MISSING_DEP。
"""

from __future__ import annotations

from typing import Any

from ..errors import WechatInvalidInput
from ..registry import capability


def _safe_call(loader, runner):
    try:
        mod = loader()
    except ImportError as e:
        return {"status": "error", "code": "MISSING_DEP", "message": str(e)}
    try:
        return runner(mod)
    except Exception as e:  # pragma: no cover - 防御性
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}


def stock_stats(_payload: dict | None = None) -> dict[str, Any]:
    def _runner(mod):
        if hasattr(mod, "get_stock_pool_stats"):
            return {"status": "ok", "stats": mod.get_stock_pool_stats()}
        return {"status": "ok", "message": "stock_filter loaded, no stats fn"}

    return _safe_call(lambda: __import__("gh_ui_cli.wechat.adapters.stock_filter", fromlist=["*"]), _runner)


def screener(payload: dict) -> dict[str, Any]:
    keywords = list(payload.get("keywords") or [])
    if not keywords:
        raise WechatInvalidInput("keywords 不能为空")

    def _runner(mod):
        if hasattr(mod, "filter_messages_by_stock"):
            return {"status": "ok", "result": mod.filter_messages_by_stock(payload)}
        return {"status": "error", "message": "stock_filter.filter_messages_by_stock 未实现"}

    return _safe_call(lambda: __import__("gh_ui_cli.wechat.adapters.stock_filter", fromlist=["*"]), _runner)


def kline_review(payload: dict) -> dict[str, Any]:
    stock_code = (payload.get("stock_code") or "").strip()
    if not stock_code:
        raise WechatInvalidInput("stock_code 必填")

    def _runner(mod):
        if hasattr(mod, "fetch_kline_data"):
            data = mod.fetch_kline_data(stock_code, **{k: v for k, v in payload.items() if k != "stock_code"})
            return {"status": "ok", "stock_code": stock_code, "data": data}
        return {"status": "error", "message": "stock_kline.fetch_kline_data 未实现"}

    return _safe_call(lambda: __import__("gh_ui_cli.wechat.adapters.stock_kline", fromlist=["*"]), _runner)


def stock_picks(payload: dict) -> dict[str, Any]:
    def _runner(mod):
        if hasattr(mod, "extract_stock_picks"):
            return {"status": "ok", "picks": mod.extract_stock_picks(payload)}
        return {"status": "error", "message": "stock_selection.extract_stock_picks 未实现"}

    return _safe_call(lambda: __import__("gh_ui_cli.wechat.adapters.stock_selection", fromlist=["*"]), _runner)


@capability("op:wechat:stock-stats")
def _cap_stats(payload: dict) -> dict:
    return stock_stats(payload)


@capability("op:wechat:stock-screener")
def _cap_screener(payload: dict) -> dict:
    return screener(payload or {})


@capability("op:wechat:stock-review")
def _cap_review(payload: dict) -> dict:
    return kline_review(payload or {})


@capability("op:wechat:stock-picks")
def _cap_picks(payload: dict) -> dict:
    return stock_picks(payload or {})
