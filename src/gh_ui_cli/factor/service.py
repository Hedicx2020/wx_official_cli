"""factor 业务实现 - 主要走本地 parquet (factor_info / factor_{table}.parquet)。

JYDB 在线下载仅在 sqlalchemy + pymysql + 凭据齐全时可用，
缺失时返回结构化错误码 FACTOR_DB_UNAVAILABLE 或 JYPY_MISSING。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..system import paths as sys_paths
from ..wechat.errors import WechatDataMissing, WechatError, WechatInvalidInput
from ..wechat.registry import capability


FACTOR_VALUE_TABLES = [
    "analyst", "basic", "call_auction", "corporate_governance",
    "earnings_quality", "growth", "highfre_level2", "highfre_minutes",
    "ml", "operational_efficiency", "profitability", "security",
    "technical", "valuation",
]
FACTOR_TABLE_LABELS = {
    "factor_info": "因子目录",
    "analyst": "分析师", "basic": "基本面", "call_auction": "集合竞价",
    "corporate_governance": "公司治理", "earnings_quality": "盈利质量",
    "growth": "成长", "highfre_level2": "高频Level2", "highfre_minutes": "高频分钟",
    "ml": "机器学习", "operational_efficiency": "运营效率", "profitability": "盈利能力",
    "security": "安全", "technical": "技术面", "valuation": "估值",
}


def _factor_dir() -> Path:
    return Path(sys_paths.factor_path())


def _table_path(table: str) -> Path:
    if table == "factor_info":
        return _factor_dir() / "factor_factor_info.parquet"
    return _factor_dir() / "factors" / table


def list_tables() -> list[dict]:
    """列出本地已有的因子表（factor_info + factors/<table>/ 目录）。"""
    root = _factor_dir()
    out: list[dict] = []
    fi = root / "factor_factor_info.parquet"
    if fi.exists():
        out.append({"table": "factor_info", "label": FACTOR_TABLE_LABELS["factor_info"], "available": True})
    factors_root = root / "factors"
    for tbl in FACTOR_VALUE_TABLES:
        sub = factors_root / tbl
        available = sub.is_dir() and any(sub.glob("*.parquet"))
        out.append({
            "table": tbl,
            "label": FACTOR_TABLE_LABELS.get(tbl, tbl),
            "available": available,
        })
    return out


def query(table: str, params: dict | None = None) -> dict[str, Any]:
    """读取本地因子表。

    factor_info: 单文件 factor_factor_info.parquet
    其它表: factors/<table>/*.parquet（按 factor_id 切片）
    """
    params = params or {}
    if not table:
        raise WechatInvalidInput("table 不能为空")

    try:
        import pandas as pd
    except ImportError as e:
        raise WechatDataMissing("缺少 pandas", code="FACTOR_MISSING_DEP") from e

    factor_id = (params.get("factor_id") or "").strip()
    start = (params.get("start_date") or "").strip()
    end = (params.get("end_date") or "").strip()
    limit = int(params.get("limit") or 0)

    if table == "factor_info":
        fp = _table_path(table)
        if not fp.exists():
            raise WechatDataMissing(f"未找到 {fp.name}", code="FACTOR_FILE_MISSING")
        df = pd.read_parquet(fp)
        if factor_id:
            df = df[df["factor_id"].astype(str) == factor_id]
        total = int(len(df))
        if limit > 0:
            df = df.head(limit)
        return {
            "data": df.where(df.notnull(), None).astype(object).to_dict(orient="records"),
            "columns": [str(c) for c in df.columns],
            "total": total,
        }

    if table not in FACTOR_VALUE_TABLES:
        raise WechatInvalidInput(f"未知因子表: {table}")

    sub = _factor_dir() / "factors" / table
    if not sub.exists():
        raise WechatDataMissing(f"未找到因子表目录: factors/{table}", code="FACTOR_DIR_MISSING")

    if factor_id:
        candidate = sub / f"{factor_id}.parquet"
        if not candidate.exists():
            raise WechatDataMissing(
                f"未找到 factors/{table}/{factor_id}.parquet",
                code="FACTOR_FILE_MISSING",
            )
        df = pd.read_parquet(candidate)
    else:
        # 合并目录所有 parquet
        frames = []
        for f in sub.glob("*.parquet"):
            try:
                frames.append(pd.read_parquet(f))
            except Exception:
                continue
        if not frames:
            raise WechatDataMissing(f"factors/{table} 下没有可读 parquet")
        df = pd.concat(frames, ignore_index=True)

    if "trade_dt" in df.columns:
        if start:
            df = df[df["trade_dt"].astype(str) >= start.replace("-", "")]
        if end:
            df = df[df["trade_dt"].astype(str) <= end.replace("-", "")]
    total = int(len(df))
    if limit > 0:
        df = df.head(limit)
    return {
        "data": df.where(df.notnull(), None).astype(object).to_dict(orient="records"),
        "columns": [str(c) for c in df.columns],
        "total": total,
    }


def catalog() -> dict[str, Any]:
    """从本地 factor_info.parquet 生成 level1/level2 树。"""
    fp = _table_path("factor_info")
    if not fp.exists():
        raise WechatDataMissing("未找到 factor_factor_info.parquet", code="FACTOR_FILE_MISSING")
    try:
        import pandas as pd
    except ImportError as e:
        raise WechatDataMissing("缺少 pandas", code="FACTOR_MISSING_DEP") from e
    df = pd.read_parquet(fp)
    tree: dict[str, dict[str, list[dict]]] = {}
    for _, row in df.iterrows():
        l1 = str(row.get("level1") or "")
        l2 = str(row.get("level2") or "")
        tree.setdefault(l1, {}).setdefault(l2, []).append({
            "factor_id": str(row.get("factor_id") or ""),
            "factor_id_cn": str(row.get("factor_id_cn") or ""),
        })
    return tree


def values(factor_id: str, start_date: str = "", end_date: str = "") -> dict[str, Any]:
    if not factor_id:
        raise WechatInvalidInput("factor_id 不能为空")
    fp = _factor_dir() / "factors" / "values" / f"{factor_id}.parquet"
    if not fp.exists():
        # 兜底：扫 14 个因子值表目录
        for t in FACTOR_VALUE_TABLES:
            cand = _factor_dir() / "factors" / t / f"{factor_id}.parquet"
            if cand.exists():
                fp = cand
                break
        else:
            raise WechatDataMissing(f"未找到因子 {factor_id} 的 parquet", code="FACTOR_FILE_MISSING")
    try:
        import pandas as pd
    except ImportError as e:
        raise WechatDataMissing("缺少 pandas", code="FACTOR_MISSING_DEP") from e
    df = pd.read_parquet(fp)
    if "trade_dt" in df.columns:
        if start_date:
            df = df[df["trade_dt"].astype(str) >= start_date.replace("-", "")]
        if end_date:
            df = df[df["trade_dt"].astype(str) <= end_date.replace("-", "")]
    return {
        "factor_id": factor_id,
        "rows": int(len(df)),
        "data": df.where(df.notnull(), None).astype(object).to_dict(orient="records"),
    }


def progress() -> dict:
    from . import download as dl
    return dict(dl._PROGRESS)


def download(table: str, token: str | None = None) -> dict[str, Any]:
    from . import download as dl
    return dl.download(table=table, token=token or "")


def databases() -> list[str]:
    """SHOW DATABASES via SQLAlchemy + pymysql。失败时返回结构化错误。"""
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
    eng = create_engine(url, pool_pre_ping=True)
    with eng.connect() as c:
        rows = c.execute(text("SHOW DATABASES")).fetchall()
    return [r[0] for r in rows]


@capability("op:factor:tables")
def _cap_tables(_payload: dict) -> list:
    return list_tables()


@capability("op:factor:query")
def _cap_query(payload: dict) -> dict:
    return query(
        table=str(payload.get("table") or ""),
        params={k: v for k, v in payload.items() if k != "table"},
    )


@capability("op:factor:catalog")
def _cap_catalog(_payload: dict) -> dict:
    return catalog()


@capability("op:factor:values")
def _cap_values(payload: dict) -> dict:
    return values(
        factor_id=str(payload.get("factor_id") or ""),
        start_date=str(payload.get("start_date") or ""),
        end_date=str(payload.get("end_date") or ""),
    )


@capability("op:factor:progress")
def _cap_progress(_payload: dict) -> dict:
    return progress()


@capability("op:factor:download")
def _cap_download(payload: dict) -> dict:
    return download(table=str(payload.get("table") or ""), token=payload.get("token"))


@capability("op:factor:databases")
def _cap_databases(_payload: dict) -> list:
    return databases()
