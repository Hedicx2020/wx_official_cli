"""gh_ui_cli 内置微信模块。

本模块取代原 gh_quant_ui/api/wechat*.py + wechat_native/，使 gh-ui 不再需要
gh_quant_ui 源码即可执行所有微信功能。
"""

from . import (  # noqa: F401  保证 capability 被注册
    paths,
    errors,
    models,
    registry,
)
from .services import config as _config  # noqa: F401
from .services import keys as _keys  # noqa: F401
from .services import messages as _messages  # noqa: F401
from .services import contacts as _contacts  # noqa: F401
from .services import articles as _articles  # noqa: F401
from .services import images as _images  # noqa: F401
from .services import llm as _llm  # noqa: F401
from .services import pdf_report as _pdf_report  # noqa: F401
from .services import stock_review as _stock_review  # noqa: F401
