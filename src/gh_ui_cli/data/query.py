"""data 查询：读 parquet + 通用过滤 + 返回 JSON。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..system import paths as sys_paths
from ..wechat.errors import WechatDataMissing, WechatInvalidInput
from ..wechat.registry import capability
from . import parquet_map


def _filter_df(df, params: dict):
    """对 pandas DataFrame 应用通用过滤器（避免显式 import pandas 在模块顶层）。"""
    code = (params.get("code") or "").strip()
    if code and "stock_code" in df.columns:
        df = df[df["stock_code"].astype(str).isin([c.strip() for c in code.split(",") if c.strip()])]
    elif code and "code" in df.columns:
        df = df[df["code"].astype(str).isin([c.strip() for c in code.split(",") if c.strip()])]
    elif code:
        # 兜底匹配 *_code 列
        for col in df.columns:
            if col.endswith("_code"):
                df = df[df[col].astype(str).isin([c.strip() for c in code.split(",") if c.strip()])]
                break

    start = (params.get("start_date") or "").strip()
    end = (params.get("end_date") or "").strip()
    if start or end:
        date_col = next(
            (c for c in ("trade_date", "date", "end_date", "publish_date", "trading_day") if c in df.columns),
            None,
        )
        if date_col:
            if start:
                df = df[df[date_col].astype(str) >= start]
            if end:
                df = df[df[date_col].astype(str) <= end]

    item = (params.get("item") or "").strip()
    if item and "item" in df.columns:
        df = df[df["item"].astype(str) == item]

    curve = (params.get("curve_code") or "").strip()
    if curve and "curve_code" in df.columns:
        codes = [c.strip() for c in curve.split(",") if c.strip()]
        df = df[df["curve_code"].astype(str).isin(codes)]

    return df


def query(module: str, method: str, params: dict | None = None, limit: int = 0) -> dict[str, Any]:
    params = params or {}
    fname = parquet_map.resolve_parquet_name(module, method, params)
    if not fname:
        raise WechatInvalidInput(f"未知方法: {module}/{method}")
    fp = Path(sys_paths.db_path()) / fname
    if not fp.exists():
        raise WechatDataMissing(
            f"本地数据文件不存在: {fname}",
            hint="先用 gh-ui data download/update 拉取",
            code="DATA_FILE_MISSING",
        )

    try:
        import pandas as pd  # noqa: F401
    except ImportError as e:
        raise WechatDataMissing(
            "缺少 pandas，请 uv pip install pandas pyarrow",
            code="DATA_MISSING_DEP",
        ) from e

    import pandas as pd

    try:
        df = pd.read_parquet(fp)
    except Exception as e:
        raise WechatDataMissing(f"读取 parquet 失败: {e}", code="DATA_PARQUET_BAD") from e

    df = _filter_df(df, params)
    total = int(len(df))
    if limit and limit > 0:
        df = df.head(int(limit))

    # NaN -> None；datetime -> 字符串
    return {
        "data": df.where(df.notnull(), None).astype(object).to_dict(orient="records"),
        "columns": [str(c) for c in df.columns],
        "total": total,
        "parquet": fname,
    }


def list_files() -> list[dict]:
    """扫 db_path 下所有 .parquet 给出大小、修改时间、行数。"""
    root = Path(sys_paths.db_path())
    if not root.exists():
        return []
    try:
        import pyarrow.parquet as pq  # noqa: F401
    except ImportError:
        pq = None  # type: ignore
    result: list[dict] = []
    for f in sorted(root.glob("*.parquet")):
        try:
            st = f.stat()
        except OSError:
            continue
        rows = 0
        status = "ok"
        if pq is not None:
            try:
                rows = int(__import__("pyarrow.parquet", fromlist=["read_metadata"]).read_metadata(f).num_rows)
            except Exception:
                status = "corrupted"
        result.append({
            "name": f.name,
            "size_mb": round(st.st_size / 1024 / 1024, 2),
            "last_modified": __import__("datetime").datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "rows": rows,
            "status": status,
        })
    return result


def progress() -> dict:
    """返回当前进程内的下载进度。CLI 独立运行时是空 dict。"""
    from . import download as dl_mod
    return dict(dl_mod._PROGRESS)


@capability("op:data:query")
def _cap_query(payload: dict) -> dict:
    return query(
        module=str(payload.get("module") or ""),
        method=str(payload.get("method") or ""),
        params={k: v for k, v in payload.items() if k not in {"module", "method", "limit"}},
        limit=int(payload.get("limit") or 0),
    )


@capability("op:data:local-files")
def _cap_files(_payload: dict) -> list:
    return list_files()


@capability("op:data:progress")
def _cap_progress(_payload: dict) -> dict:
    return progress()
