from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def parse_value(value: str) -> Any:
    text = value.strip()
    if text == "":
        return ""
    if len(text) > 1 and text[0] == "0" and text[1].isdigit():
        return value
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    if text[0:1] in ("[", "{", '"'):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    try:
        if "." not in text:
            return int(text)
        return float(text)
    except ValueError:
        return value


def parse_key_values(items: list[str] | None) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"expected KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"empty key in {item!r}")
        parsed[key] = parse_value(value)
    return parsed


def read_text_arg(value: str) -> str:
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@"):
        return Path(value[1:]).expanduser().read_text(encoding="utf-8")
    return value


def read_json_arg(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    text = read_text_arg(value)
    if text.strip() == "":
        return default
    return json.loads(text)


def ensure_jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): ensure_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [ensure_jsonable(v) for v in value]
        return str(value)


def write_json(value: Any, save: str | None = None) -> None:
    payload = json.dumps(ensure_jsonable(value), ensure_ascii=True, indent=2)
    if save:
        path = Path(save).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload + "\n", encoding="utf-8")
    print(payload)


def write_bytes(content: bytes, save: str | None, metadata: dict[str, Any]) -> None:
    if not save:
        raise RuntimeError("response is binary or non-JSON; pass --save to write it to a file")
    path = Path(save).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    write_json({"saved": str(path), **metadata})
