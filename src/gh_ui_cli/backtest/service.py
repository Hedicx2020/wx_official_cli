"""backtest 业务实现 - parquet readiness、组合 CRUD、回测运行（lazy gh_backtest）。"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from ..system import paths as sys_paths
from ..wechat.errors import WechatDataMissing, WechatError, WechatInvalidInput
from ..wechat.registry import capability


REQUIRED_FILES = [
    "ashare_stock_price.parquet",
    "ashare_stock.parquet",
    "ashare_stock_st.parquet",
    "ashare_index_components.parquet",
    "ashare_index_price.parquet",
]

# 内存缓存上传 + 任务结果（agent 单进程使用足够）
_UPLOADS: dict[str, dict] = {}
_RESULTS: dict[str, dict] = {}


def check_data() -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        pq = None  # type: ignore
    root = Path(sys_paths.db_path())
    files: dict[str, dict] = {}
    missing: list[str] = []
    for name in REQUIRED_FILES:
        fp = root / name
        if not fp.exists():
            files[name] = {"exists": False}
            missing.append(name)
            continue
        meta = {"exists": True, "rows": 0, "size_mb": round(fp.stat().st_size / 1024 / 1024, 1)}
        if pq is not None:
            try:
                meta["rows"] = int(pq.read_metadata(fp).num_rows)
            except Exception:
                meta["rows"] = 0
        files[name] = meta
    return {"ready": len(missing) == 0, "files": files, "missing": missing}


def index_codes() -> list[dict]:
    fp = Path(sys_paths.db_path()) / "ashare_index_components.parquet"
    if not fp.exists():
        return []
    try:
        import pandas as pd
    except ImportError as e:
        raise WechatDataMissing("缺少 pandas", code="BACKTEST_MISSING_DEP") from e
    df = pd.read_parquet(fp, columns=["index_code", "index_name"])
    df = df.drop_duplicates(subset="index_code")
    top_codes = [
        "000300", "000905", "000852", "000016", "000985",
        "399006", "399303", "000688", "000001", "399001",
    ]
    top = df[df["index_code"].isin(top_codes)].copy()
    top["_sort"] = top["index_code"].map({c: i for i, c in enumerate(top_codes)})
    top = top.sort_values("_sort").drop(columns="_sort")
    rest = df[~df["index_code"].isin(top_codes)].sort_values("index_code")
    return pd.concat([top, rest]).head(100).to_dict(orient="records")


def upload_portfolio_json(payload: dict) -> dict[str, Any]:
    rows = payload.get("rows") or []
    if not rows:
        raise WechatInvalidInput("rows 不能为空")
    try:
        import pandas as pd
    except ImportError as e:
        raise WechatDataMissing("缺少 pandas", code="BACKTEST_MISSING_DEP") from e
    df = pd.DataFrame(rows)
    for col in ("date", "stock_code", "weight"):
        if col not in df.columns:
            raise WechatInvalidInput(f"rows 缺少字段: {col}")
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["stock_code"] = df["stock_code"].astype(str).str.zfill(6)
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0)
    dates = sorted(df["date"].unique().tolist())
    upload_id = f"up_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    _UPLOADS[upload_id] = {"df": df, "created_at": time.time(), "name": payload.get("name", "")}
    return {
        "upload_id": upload_id,
        "start_date": dates[0],
        "end_date": dates[-1],
        "num_periods": len(dates),
        "num_stocks": int(df["stock_code"].nunique()),
    }


def uploaded_portfolio(upload_id: str) -> dict[str, Any]:
    if not upload_id or upload_id not in _UPLOADS:
        raise WechatDataMissing("upload_id 不存在或已过期", code="BACKTEST_UPLOAD_MISSING")
    df = _UPLOADS[upload_id]["df"]
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "date": str(r["date"]),
            "stock_code": str(r["stock_code"]).zfill(6),
            "weight": float(r["weight"]),
        })
    return {"rows": rows, "num_rows": len(rows)}


def sample_portfolio() -> dict[str, Any]:
    return {
        "rows": [
            {"date": "2024-01-01", "stock_code": "000001", "weight": 0.5},
            {"date": "2024-01-01", "stock_code": "600519", "weight": 0.5},
            {"date": "2024-02-01", "stock_code": "000001", "weight": 0.6},
            {"date": "2024-02-01", "stock_code": "600519", "weight": 0.4},
        ]
    }


def _load_gh_backtest():
    try:
        import importlib

        return importlib.import_module("gh_backtest")
    except ImportError as e:
        raise WechatError(
            "需要 gh_backtest 私有库",
            code="GH_BACKTEST_MISSING",
            hint=f"原因：{e}。请把 gh_backtest/src 加到 PYTHONPATH。",
        ) from e


def run(payload: dict) -> dict[str, Any]:
    upload_id = (payload.get("upload_id") or "").strip()
    if not upload_id:
        raise WechatInvalidInput("upload_id 必填")
    if upload_id not in _UPLOADS:
        raise WechatDataMissing(f"upload_id 不存在: {upload_id}", code="BACKTEST_UPLOAD_MISSING")
    gh_backtest = _load_gh_backtest()  # noqa: F841 - 暴露错误

    task_id = f"bt_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    _RESULTS[task_id] = {
        "status": "queued",
        "upload_id": upload_id,
        "params": {k: v for k, v in payload.items() if k != "upload_id"},
    }
    # 实际跑回测的代码留给 gh_backtest 调用方实现；这里给 agent 留一个稳定的句柄
    return {"task_id": task_id, "status": "queued"}


def result(task_id: str) -> dict[str, Any]:
    if not task_id or task_id not in _RESULTS:
        raise WechatDataMissing(f"task_id 不存在: {task_id}", code="BACKTEST_TASK_MISSING")
    return _RESULTS[task_id]


@capability("op:backtest:check-data")
def _cap_check(_payload: dict) -> dict:
    return check_data()


@capability("op:backtest:index-codes")
def _cap_index(_payload: dict) -> list:
    return index_codes()


@capability("op:backtest:upload-portfolio-json")
def _cap_upload(payload: dict) -> dict:
    return upload_portfolio_json(payload or {})


@capability("op:backtest:uploaded-portfolio")
def _cap_uploaded(payload: dict) -> dict:
    return uploaded_portfolio(str(payload.get("upload_id") or ""))


@capability("op:backtest:sample-portfolio")
def _cap_sample(_payload: dict) -> dict:
    return sample_portfolio()


@capability("op:backtest:run")
def _cap_run(payload: dict) -> dict:
    return run(payload or {})


@capability("op:backtest:result")
def _cap_result(payload: dict) -> dict:
    return result(str(payload.get("task_id") or ""))
