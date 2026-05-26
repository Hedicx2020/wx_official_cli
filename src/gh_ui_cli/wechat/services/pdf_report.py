"""PDF 报告生成 - 包装原 pdf_reporter.py。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import paths
from ..errors import WechatInvalidInput
from ..registry import capability


def generate(messages: list[dict], output_path: str | None = None, title: str | None = None) -> dict[str, Any]:
    if not messages:
        raise WechatInvalidInput("messages 不能为空")
    try:
        from ..adapters import pdf_reporter
    except ImportError as e:
        return {"status": "error", "code": "MISSING_DEP", "message": str(e)}

    out = Path(output_path) if output_path else (paths.data_dir() / "reports" / "report.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = pdf_reporter.generate_pdf(
            messages=messages,
            output_path=str(out),
            title=title or "微信投研日报",
        ) if hasattr(pdf_reporter, "generate_pdf") else None
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}
    return {
        "status": "ok",
        "output": str(out),
        "size": out.stat().st_size if out.exists() else 0,
        "details": result,
    }


@capability("op:wechat:report-pdf")
def _cap(payload: dict) -> dict:
    return generate(
        messages=list(payload.get("messages") or []),
        output_path=payload.get("output_path"),
        title=payload.get("title"),
    )
