"""AI 报告复现工作流（report-reproduce）。

vendor 原 ai.py 的纯逻辑部分；run 用 subprocess 调用本机 codex/claude CLI。
"""

from . import service as _service  # noqa: F401
