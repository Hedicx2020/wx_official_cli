"""factor 因子库 / 收益归因 / 排名模块。

依赖说明：
- 本地 parquet 查询：纯 pandas，零额外依赖
- 在线 JYDB MySQL 调用：lazy import sqlalchemy + pymysql；缺失时给清晰错误
"""

from . import service as _service  # noqa: F401
