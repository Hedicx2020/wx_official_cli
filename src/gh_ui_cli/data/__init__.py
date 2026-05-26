"""data 通用数据查询/下载/更新模块。

不再依赖 gh_quant_ui FastAPI，但 download/update 仍需 JyPy 私有库。
没装 JyPy 时给出明确报错。
"""

from . import parquet_map as _pm  # noqa: F401
from . import query as _query  # noqa: F401
from . import download as _download  # noqa: F401
