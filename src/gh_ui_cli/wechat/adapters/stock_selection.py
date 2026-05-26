"""Stock picking aggregation helpers for WeChat message matches.

This module is intentionally pure: callers provide already-fetched messages and
a stock matcher. Keeping ranking logic here makes the API route easy to test
without touching local WeChat databases or the JyPy stock-name source.
"""

from __future__ import annotations

from typing import Any, Protocol


class StockMatcherLike(Protocol):
    def find_matches(self, text: str, match_code: bool = False) -> list[str]:
        ...

    def resolve_stock_code(self, name: str) -> str:
        ...


def _matched_names(
    matcher: StockMatcherLike,
    content: str,
    *,
    match_code: bool,
) -> list[str]:
    names = matcher.find_matches(content, match_code=match_code)
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _collect_previous_stocks(
    messages: list[dict[str, Any]],
    matcher: StockMatcherLike,
    *,
    match_code: bool,
) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for message in messages:
        names = _matched_names(
            matcher,
            str(message.get("content") or ""),
            match_code=match_code,
        )
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            ordered.append(name)
    return ordered


def _resolve_stock_code(matcher: StockMatcherLike, stock_name: str) -> str:
    resolver = getattr(matcher, "resolve_stock_code", None)
    if not callable(resolver):
        return ""
    try:
        return str(resolver(stock_name) or "")
    except Exception:
        return ""


def _lookup_industry(
    industry_lookup: dict[str, dict[str, str]] | None,
    *,
    stock_name: str,
    stock_code: str,
) -> dict[str, str]:
    if not industry_lookup:
        return {}
    return industry_lookup.get(stock_code) or industry_lookup.get(stock_name) or {}


def rank_stock_picks(
    messages: list[dict[str, Any]],
    matcher: StockMatcherLike,
    *,
    mode: str = "mentions",
    previous_messages: list[dict[str, Any]] | None = None,
    match_code: bool = False,
    top_n: int = 50,
    sample_limit: int = 3,
    industry_lookup: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Rank stocks mentioned in recent WeChat messages.

    Modes:
      - ``mentions``: count matched messages in the recent window.
      - ``new_recommendations``: same count, but exclude stocks that appeared in
        the previous quiet window.
    """
    if mode not in {"mentions", "new_recommendations"}:
        raise ValueError(f"unsupported stock pick mode: {mode}")

    previous_stocks = _collect_previous_stocks(
        previous_messages or [],
        matcher,
        match_code=match_code,
    )
    previous_set = set(previous_stocks)

    buckets: dict[str, dict[str, Any]] = {}
    total_matched = 0

    for index, message in enumerate(messages):
        content = str(message.get("content") or "")
        names = _matched_names(matcher, content, match_code=match_code)
        if not names:
            continue
        total_matched += 1

        for name in names:
            if mode == "new_recommendations" and name in previous_set:
                continue
            entry = buckets.get(name)
            msg_time = str(message.get("time") or "")
            stock_code = _resolve_stock_code(matcher, name)
            industry = _lookup_industry(
                industry_lookup,
                stock_name=name,
                stock_code=stock_code,
            )
            sample = {
                "time": msg_time,
                "sender": message.get("sender", ""),
                "chat_name": message.get("chat_name", ""),
                "content": content,
                "matched_stock": name,
            }
            if entry is None:
                buckets[name] = {
                    "stock": name,
                    "stock_code": stock_code or industry.get("stock_code", ""),
                    "first_industry_name": industry.get("first_industry_name", ""),
                    "second_industry_name": industry.get("second_industry_name", ""),
                    "third_industry_name": industry.get("third_industry_name", ""),
                    "mention_count": 1,
                    "first_time": msg_time,
                    "last_time": msg_time,
                    "_first_seen": index,
                    "sample_messages": [sample],
                }
            else:
                entry["mention_count"] += 1
                if msg_time and (not entry["first_time"] or msg_time < entry["first_time"]):
                    entry["first_time"] = msg_time
                if msg_time and msg_time > entry["last_time"]:
                    entry["last_time"] = msg_time
                if len(entry["sample_messages"]) < sample_limit:
                    entry["sample_messages"].append(sample)

    limit = max(1, min(int(top_n or 50), 500))
    items = sorted(
        buckets.values(),
        key=lambda item: (-int(item["mention_count"]), int(item["_first_seen"])),
    )[:limit]
    for item in items:
        item.pop("_first_seen", None)

    return {
        "mode": mode,
        "total_input": len(messages),
        "total_matched": total_matched,
        "total_stocks": len(buckets),
        "excluded_previous_stocks": previous_stocks if mode == "new_recommendations" else [],
        "items": items,
    }
