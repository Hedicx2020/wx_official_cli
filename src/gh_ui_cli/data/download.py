"""data 下载与更新：lazy import JyPy，缺失时给清晰报错。

由于 JyPy 是私有库，不会作为 gh_ui_cli 的硬依赖。
如果未安装，调用 download/update 会返回结构化错误码 JYPY_MISSING。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..system import paths as sys_paths
from ..wechat.errors import WechatError, WechatInvalidInput
from ..wechat.registry import capability
from . import parquet_map


_PROGRESS: dict[str, dict] = {}


def _resolve_token(payload: dict) -> str:
    for k in ("token", "api_token", "GH_API_TOKEN"):
        v = (payload.get(k) or "").strip() if isinstance(payload.get(k), str) else ""
        if v:
            return v
    env = os.environ.get("GH_API_TOKEN", "").strip()
    if env:
        return env
    try:
        from ..profile import load_profile

        prof = load_profile()
        v = (prof.get("api_token") or "").strip()
        if v:
            return v
    except Exception:
        pass
    return ""


def _resolve_server(payload: dict) -> str:
    s = (payload.get("server") or os.environ.get("GH_JYDB_SERVER") or "primary").strip()
    if s not in {"primary", "secondary"}:
        raise WechatInvalidInput(f"server must be primary|secondary, got {s!r}")
    return s


def _load_jypy(module: str):
    """按模块名 lazy import JyPy 子类 (Stock/Index/Fund/Bond/Future/Macro/Trade)。"""
    name_map = {
        "trade": "Trade",
        "stock": "Stock",
        "index": "Index",
        "fund": "Fund",
        "bond": "Bond",
        "future": "Future",
        "macro": "Macro",
    }
    cls_name = name_map.get(module)
    if cls_name is None:
        raise WechatInvalidInput(f"未知模块: {module}")
    try:
        import importlib

        mod = importlib.import_module(f"JyPy.{cls_name}")
        return getattr(mod, cls_name)
    except ImportError as e:
        raise WechatError(
            "需要 JyPy 私有库，请联系开发者获取。",
            code="JYPY_MISSING",
            hint=f"原因：{e}。可通过 PYTHONPATH 加入 JyPy 源码目录。",
        ) from e


def download(module: str, method: str, payload: dict | None = None) -> dict[str, Any]:
    payload = payload or {}
    token = _resolve_token(payload)
    if not token:
        raise WechatInvalidInput(
            "缺少 token，可通过 --token 参数或 GH_API_TOKEN 环境变量提供",
        )
    server = _resolve_server(payload)
    cls = _load_jypy(module)
    db_path = sys_paths.db_path()
    Path(db_path).mkdir(parents=True, exist_ok=True)

    fname = parquet_map.resolve_parquet_name(module, method, payload)
    if not fname:
        raise WechatInvalidInput(f"未知方法: {module}/{method}")

    inst = cls(api_token=token, server=server, db_path=db_path)
    method_fn = getattr(inst, f"get_{method}", None)
    if method_fn is None:
        # 财务/复权变种 get_stock_price_forward 等
        if method == "stock_price":
            method_fn = inst.get_stock_price
        else:
            raise WechatInvalidInput(f"JyPy.{cls.__name__} 无方法 get_{method}")

    key = f"{module}/{method}"
    _PROGRESS[key] = {"status": "running", "module": module, "method": method, "filepath": str(Path(db_path) / fname)}
    try:
        kwargs = {}
        if payload.get("start_date"):
            kwargs["start_date"] = payload["start_date"]
        if payload.get("end_date"):
            kwargs["end_date"] = payload["end_date"]
        if payload.get("market"):
            kwargs["market"] = payload["market"]
        if module == "stock" and method == "stock_price" and payload.get("adj_type"):
            kwargs["adj_type"] = payload["adj_type"]
        df = method_fn(**kwargs)
    except Exception as e:
        _PROGRESS[key] = {"status": "error", "message": str(e)}
        raise WechatError(f"JyPy 下载失败: {e}", code="JYPY_DOWNLOAD_FAILED") from e

    fp = Path(db_path) / fname
    try:
        df.to_parquet(fp, index=False)
    except Exception as e:
        _PROGRESS[key] = {"status": "error", "message": str(e)}
        raise WechatError(f"写 parquet 失败: {e}", code="DATA_PARQUET_WRITE_FAILED") from e

    rows = int(len(df))
    _PROGRESS[key] = {"status": "done", "rows": rows, "parquet": fname}
    return {"status": "ok", "module": module, "method": method, "parquet": fname, "rows": rows}


def update(module: str, method: str, payload: dict | None = None) -> dict[str, Any]:
    """简化策略：本地无 parquet → 走 download；存在 → 同样调 download 整表覆盖。

    原 gh_quant_ui 的 update_* 走 JSID 增量，但接口比较多样；这里先用最低风险
    的整表 download，跟用户在 README 里看到的「不存在 pq → download / 存在 pq
    → 增量」语义保持兼容（增量优化留给后续）。
    """
    payload = payload or {}
    fname = parquet_map.resolve_parquet_name(module, method, payload)
    fp = Path(sys_paths.db_path()) / fname
    out = download(module, method, payload)
    out["update_mode"] = "full" if not fp.parent.exists() else "overwrite"
    return out


@capability("op:data:download")
def _cap_download(payload: dict) -> dict:
    return download(
        module=str(payload.get("module") or ""),
        method=str(payload.get("method") or ""),
        payload={k: v for k, v in payload.items() if k not in {"module", "method"}},
    )


@capability("op:data:update")
def _cap_update(payload: dict) -> dict:
    return update(
        module=str(payload.get("module") or ""),
        method=str(payload.get("method") or ""),
        payload={k: v for k, v in payload.items() if k not in {"module", "method"}},
    )
