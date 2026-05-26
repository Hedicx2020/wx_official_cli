"""backtest 模块：本地 parquet 检查 + 组合上传 + 回测调度。

gh_backtest 是私有库；run 调用 lazy import + 失败时返回 GH_BACKTEST_MISSING。
"""

from . import service as _service  # noqa: F401
