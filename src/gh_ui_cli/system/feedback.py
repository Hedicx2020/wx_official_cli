"""/api/feedback 本地实现 - 转发或落本地 jsonl。"""

from __future__ import annotations

import json
from datetime import datetime

import httpx

from ..wechat.errors import WechatInvalidInput
from ..wechat.registry import capability
from . import paths
from .auth import GHWEB_BASE


def submit(payload: dict) -> dict:
    content = str(payload.get("content") or "").strip()
    if not content:
        raise WechatInvalidInput("反馈内容不能为空")
    body = {
        "category": str(payload.get("category") or "suggestion"),
        "content": content,
        "contact": str(payload.get("contact") or "").strip(),
        "source": "cli",
        "username": str(payload.get("username") or ""),
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(f"{GHWEB_BASE}/feedback", json=body)
        if r.status_code in (200, 201):
            return {"message": "感谢反馈, 已提交成功", "remote": True}
    except Exception:
        pass

    paths.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    f = paths.feedback_file()
    with f.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), **body}, ensure_ascii=False) + "\n")
    return {"message": "反馈已保存到本地", "remote": False, "file": str(f)}


@capability("op:system:feedback-submit")
def _cap(payload: dict) -> dict:
    return submit(payload or {})
