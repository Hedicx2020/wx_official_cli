"""LLM 集成 - OpenAI 兼容 chat/summarize。"""

from __future__ import annotations

import json
from typing import Any

from ..errors import LLMAuthFailed, WechatInvalidInput
from ..registry import capability
from . import config as config_svc


DEFAULT_SUMMARIZE_PROMPT = (
    "你是金融研究助理。请用中文总结以下聊天记录的要点，输出："
    "1) 关键决策与共识；2) 待办事项与负责人；3) 客户/对手方核心问题；"
    "4) 风险或异常信号。每条用一句话，按重要性排序。"
)


def _resolve_llm_config() -> tuple[str, str, str]:
    cfg = config_svc.load()
    base = (cfg.get("llm_api_base") or "").rstrip("/")
    api_key = cfg.get("llm_api_key") or ""
    model = cfg.get("llm_model") or ""
    if not base or not api_key or not model:
        raise LLMAuthFailed(
            "LLM 未配置",
            hint="先 gh-ui wechat config-set 填 llm_api_base / llm_api_key / llm_model",
        )
    return base, api_key, model


def chat(messages: list[dict], stream: bool = False) -> dict[str, Any]:
    import httpx

    base, key, model = _resolve_llm_config()
    if not messages:
        raise WechatInvalidInput("messages 不能为空")
    body = {"model": model, "stream": False, "messages": messages}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    url = f"{base}/chat/completions"
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
        resp = client.post(url, json=body, headers=headers)
        if resp.status_code != 200:
            return {
                "status": "error",
                "status_code": resp.status_code,
                "body": resp.text[:1000],
            }
        return {"status": "ok", "response": resp.json()}


def test_connection() -> dict[str, Any]:
    try:
        out = chat([{"role": "user", "content": "ping"}])
    except LLMAuthFailed as e:
        return {"status": "error", "code": e.code, "message": e.message}
    return out


def summarize(messages: list[dict], prompt_template: str | None = None) -> dict[str, Any]:
    if not messages:
        raise WechatInvalidInput("messages 不能为空")
    lines: list[str] = []
    total = 0
    for m in messages:
        line = f"[{m.get('time', '')}] {m.get('sender', '')}: {m.get('content', '')}"
        if total + len(line) > 30000:
            lines.append("... (已截断, 仅保留前部分消息)")
            break
        lines.append(line)
        total += len(line)
    sys_prompt = (prompt_template or "").strip() or DEFAULT_SUMMARIZE_PROMPT
    return chat([
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "\n".join(lines)},
    ])


@capability("op:wechat:llm-chat")
def _cap_chat(payload: dict) -> dict:
    return chat(list(payload.get("messages") or []))


@capability("op:wechat:llm-test")
def _cap_test(_payload: dict) -> dict:
    return test_connection()


@capability("op:wechat:llm-summarize")
def _cap_summarize(payload: dict) -> dict:
    return summarize(
        list(payload.get("messages") or []),
        prompt_template=payload.get("prompt_template"),
    )
