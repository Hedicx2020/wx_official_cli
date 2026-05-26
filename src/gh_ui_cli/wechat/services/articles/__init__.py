"""公众号文章 service。

把 wechat_articles.py 的 31 个路由按 6 个语义模块拆分：
  settings / login / accounts / categories / store / sync
所有 capability id 以 op:wechat:articles-* 开头。
"""

from . import settings as _settings  # noqa: F401
from . import categories as _categories  # noqa: F401
from . import accounts as _accounts  # noqa: F401
from . import store as _store  # noqa: F401
from . import login as _login  # noqa: F401
from . import sync as _sync  # noqa: F401
