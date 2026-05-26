"""factor JYDB 下载 - lazy import sqlalchemy。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..system import paths as sys_paths
from ..wechat.errors import WechatError, WechatInvalidInput


_PROGRESS: dict[str, dict] = {}


def download(table: str, token: str = "") -> dict[str, Any]:
    if not token:
        raise WechatInvalidInput("缺少 token")

    try:
        from sqlalchemy import create_engine, text
    except ImportError as e:
        raise WechatError("缺少 sqlalchemy", code="FACTOR_DB_UNAVAILABLE") from e

    url = os.environ.get("GH_FACTOR_DB_URL", "").strip()
    if not url:
        raise WechatError(
            "未配置 GH_FACTOR_DB_URL (mysql+pymysql://user:pw@host:port/factor)",
            code="FACTOR_DB_UNAVAILABLE",
        )

    try:
        import pandas as pd
    except ImportError as e:
        raise WechatError("缺少 pandas", code="FACTOR_MISSING_DEP") from e

    out_dir = Path(sys_paths.factor_path())
    out_dir.mkdir(parents=True, exist_ok=True)

    _PROGRESS[table] = {"status": "running"}
    try:
        eng = create_engine(url, pool_pre_ping=True)
        df = pd.read_sql(text(f"SELECT * FROM `{table}`"), eng)
        fp = out_dir / f"factor_{table}.parquet"
        df.to_parquet(fp, index=False)
    except Exception as e:
        _PROGRESS[table] = {"status": "error", "message": str(e)}
        raise WechatError(f"因子下载失败: {e}", code="FACTOR_DOWNLOAD_FAILED") from e

    _PROGRESS[table] = {"status": "done", "rows": int(len(df)), "parquet": str(fp)}
    return {"status": "ok", "table": table, "rows": int(len(df)), "parquet": str(fp)}
