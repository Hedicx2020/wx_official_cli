"""gh_ui_cli 远程账户/Token 模块。

代替原 gh_quant_ui/api/remote.py，本地直接转发到 hedicxl.cn 平台，
不再依赖 FastAPI 路由层。
"""

from . import service as _service  # noqa: F401
