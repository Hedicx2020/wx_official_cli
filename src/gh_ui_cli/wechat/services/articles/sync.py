"""公众号文章同步与本地扫描。

精简版：保留 list articles / fetch / scan_local / import_local 几个核心操作。
完整的 sync_by_category 流程依赖 WereadClient 真实 platform 调用，agent
环境多数情况下走 scan_local 即可。
"""

from __future__ import annotations

import csv
import json
import time
import unicodedata
from pathlib import Path
from typing import Any

from ... import paths
from ...adapters.local_articles import import_to_store, scan_local
from ...adapters.weread_client import WereadClient
from ...errors import WechatDataMissing, WechatError, WechatInvalidInput
from ...registry import capability
from .store import get_store, to_jsonable


def list_articles(category_id: int | None = None,
                  mp_id: str | None = None,
                  limit: int = 100,
                  offset: int = 0) -> dict[str, Any]:
    store = get_store()
    if category_id is not None:
        items = store.list_articles_by_category(int(category_id), limit=int(limit), offset=int(offset))
    else:
        items = store.list_articles(mp_id=mp_id or None, limit=int(limit), offset=int(offset))
    return {"items": [to_jsonable(a) for a in items], "total": len(items)}


def scan_from_wechat_cache() -> dict[str, Any]:
    """从已解密的微信消息缓存中扫描公众号文章（不需要登录）。"""
    from .. import keys as keys_svc

    cache_dir = keys_svc.ensure_decrypted()
    found = scan_local(cache_dir)
    return {
        "count": len(found),
        "items": [
            {
                "url": a.url,
                "title": a.title,
                "publisher": a.publisher,
                "publish_ts": a.publish_ts,
            }
            for a in found[:200]
        ],
    }


def import_scanned() -> dict[str, Any]:
    """扫描 + 导入到本地 ArticleStore。"""
    from .. import keys as keys_svc

    cache_dir = keys_svc.ensure_decrypted()
    found = scan_local(cache_dir)
    stats = import_to_store(found, get_store())
    return {"scanned": len(found), **stats}


def export_cached_by_account(
    account_name: str,
    *,
    limit: int = 100,
    output_dir: str | None = None,
    scan_first: bool = True,
    auto_password: bool = True,
    fetch_html: bool = True,
) -> dict[str, Any]:
    """按公众号名字从本地缓存导出文章到目录。

    本函数只使用本机已授权缓存。默认先解密并扫描 message/biz_message 缓存，
    再按公众号名匹配本地 ArticleStore。已有全文 HTML 会复制到导出目录；
    尚未抓取全文的文章会写 metadata 占位页，包含标题、摘要和原文链接。
    """
    name = (account_name or "").strip()
    if not name:
        raise WechatInvalidInput("公众号名字不能为空")
    if limit <= 0:
        raise WechatInvalidInput("limit 必须大于 0")

    store = get_store()
    scanned = 0
    password_auto_result: dict[str, Any] | None = None
    import_stats: dict[str, int] = {"accounts_added": 0, "articles_added": 0, "deduped": 0}
    if scan_first:
        from .. import keys as keys_svc

        try:
            cache_dir = keys_svc.ensure_decrypted()
        except WechatError:
            if not auto_password:
                raise
            password_auto_result = keys_svc.password_auto()
            if password_auto_result.get("status") != "ok":
                raise WechatDataMissing(
                    str(password_auto_result.get("message") or "自动获取微信数据库解密 key 失败"),
                    hint="请确认 Windows 微信已运行并登录，或手动配置 wechat_files_path 和 database_password。",
                )
            cache_dir = keys_svc.ensure_decrypted()
        found = scan_local(cache_dir)
        scanned = len(found)
        import_stats = import_to_store(found, store)

    account = _resolve_account(store, name)
    articles = store.list_articles(mp_id=account.mp_id, limit=int(limit), offset=0)
    out_dir = _resolve_output_dir(output_dir, account.name)
    out_dir.mkdir(parents=True, exist_ok=True)

    exported: list[dict[str, Any]] = []
    html_files: list[str] = []
    for idx, article in enumerate(articles, start=1):
        target = out_dir / f"{idx:03d}-{_safe_fs_name(article.title or article.id)}.html"
        html_text, html_source, fetch_error = _article_html(
            store,
            article,
            account.name,
            fetch_html=fetch_html,
        )
        target.write_text(html_text, encoding="utf-8")
        html_files.append(str(target))
        exported.append({
            "id": article.id,
            "title": article.title,
            "url": article.url,
            "summary": article.summary,
            "published_at": int(article.published_at or 0),
            "published_date": _format_ts(article.published_at),
            "html_path": str(target),
            "source_html_path": article.html_path,
            "html_source": html_source,
            "fetch_error": fetch_error,
        })

    index_payload = {
        "account": to_jsonable(account),
        "article_count": len(exported),
        "generated_at": int(time.time()),
        "scan_first": bool(scan_first),
        "scanned": scanned,
        "import_stats": import_stats,
        "articles": exported,
    }
    index_json = out_dir / "index.json"
    index_json.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index_csv = out_dir / "index.csv"
    _write_index_csv(index_csv, exported)
    return {
        "status": "ok",
        "account": to_jsonable(account),
        "article_count": len(exported),
        "output_dir": str(out_dir),
        "index_json": str(index_json),
        "index_csv": str(index_csv),
        "html_files": html_files,
        "articles": exported,
        "scanned": scanned,
        "import_stats": import_stats,
        "password_auto": password_auto_result or {"status": "skipped"},
        "note": "全文缺失时已生成本地 metadata 占位页，原文链接保留在 index 和 HTML 中。",
    }


def verify_cache_export(
    account_name: str,
    *,
    limit: int = 100,
    output_dir: str | None = None,
    scan_first: bool = True,
    auto_password: bool = True,
    fetch_html: bool = True,
) -> dict[str, Any]:
    """运行公众号缓存导出并输出可用于 Windows 真机验收的结构化报告。"""
    from .. import keys as keys_svc

    error: dict[str, Any] | None = None
    try:
        export = export_cached_by_account(
            account_name,
            limit=limit,
            output_dir=output_dir,
            scan_first=scan_first,
            auto_password=auto_password,
            fetch_html=fetch_html,
        )
    except WechatError as exc:
        error = exc.to_payload()["error"]
        export = {
            "status": "error",
            "article_count": 0,
            "html_files": [],
            "password_auto": {"status": "error"},
            "error": error,
        }
    status = keys_svc.password_status()
    html_files = [Path(p) for p in export.get("html_files") or []]
    missing_files = [str(p) for p in html_files if not p.exists()]
    article_count = int(export.get("article_count") or 0)
    password_auto_status = str((export.get("password_auto") or {}).get("status") or "")
    requirements = {
        "wechat_path_detected": {
            "ok": bool(status.get("detected_path") or status.get("configured_path")),
            "detected_path": status.get("detected_path", ""),
            "configured_path": status.get("configured_path", ""),
        },
        "database_key_available": {
            "ok": bool(
                status.get("has_password")
                or int(status.get("key_count") or 0) > 0
                or password_auto_status == "ok"
            ),
            "has_password": bool(status.get("has_password")),
            "key_count": int(status.get("key_count") or 0),
            "password_auto_status": password_auto_status,
        },
        "articles_exported": {
            "ok": article_count > 0,
            "article_count": article_count,
        },
        "html_files_written": {
            "ok": article_count > 0 and len(html_files) >= article_count and not missing_files,
            "html_file_count": len(html_files),
            "missing_files": missing_files,
        },
    }
    ok = all(bool(item.get("ok")) for item in requirements.values())
    return {
        "ok": ok,
        "account_name": account_name,
        "requirements": requirements,
        "password_status": status,
        "export": export,
        **({"error": error} if error else {}),
        "next_actions": [] if ok else _cache_verify_next_actions(requirements),
    }


def _cache_verify_next_actions(requirements: dict[str, dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if not requirements["wechat_path_detected"]["ok"]:
        actions.append("打开并登录 Windows 微信，或用 wechat config-set 手动填写 wechat_files_path。")
    if not requirements["database_key_available"]["ok"]:
        actions.append("确认 Weixin.exe / WeChat.exe 正在运行并已登录，然后运行 wechat password-auto。")
    if not requirements["articles_exported"]["ok"]:
        actions.append("确认该公众号文章已出现在本机微信消息缓存中，并使用更完整的公众号名字重试。")
    if not requirements["html_files_written"]["ok"]:
        actions.append("检查 output_dir 写入权限，或重试 articles-cache-export。")
    return actions


def _resolve_account(store, name: str):
    direct = store.get_mp(name)
    if direct is not None:
        return direct
    matches = store.list_mps(q=name)
    if not matches:
        normalized = _normalize_account_query(name)
        if normalized:
            matches = [
                mp for mp in store.list_mps()
                if _normalize_account_query(mp.name) == normalized
                or _normalize_account_query(mp.mp_id) == normalized
            ]
    if not matches:
        raise WechatDataMissing(
            f"未找到公众号: {name}",
            hint="先运行 articles-cache-export 时保持默认扫描，或运行 articles-sync-local 导入缓存。",
        )
    needle = name.casefold()
    exact = [m for m in matches if m.name.casefold() == needle or m.mp_id.casefold() == needle]
    if exact:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    candidates = ", ".join(m.name for m in matches[:8])
    raise WechatInvalidInput(
        f"公众号名字匹配到多个候选: {name}",
        hint=f"请使用更完整的名称。候选: {candidates}",
    )


def _normalize_account_query(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(ch for ch in text if not ch.isspace())


def _resolve_output_dir(output_dir: str | None, account_name: str) -> Path:
    if output_dir:
        return Path(output_dir).expanduser()
    return paths.articles_root() / "exports" / _safe_fs_name(account_name)


def _safe_fs_name(value: str) -> str:
    text = (value or "").strip() or "untitled"
    bad = '\\/:*?"<>|\n\r\t'
    cleaned = "".join("_" if ch in bad else ch for ch in text)
    cleaned = " ".join(cleaned.split()).strip(". ")
    return (cleaned or "untitled")[:120]


def _format_ts(value: int | str | None) -> str:
    try:
        ts = int(value or 0)
    except (TypeError, ValueError):
        ts = 0
    if ts <= 0:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _escape_html(value: str) -> str:
    return (
        (value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _article_html(store, article, account_name: str, *, fetch_html: bool) -> tuple[str, str, str]:
    if article.html_path:
        p = Path(article.html_path)
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace"), "cached", ""
    if fetch_html and article.url:
        try:
            html = WereadClient().fetch_article_html(article.id, url=article.url)
            if html.strip():
                return html, "fetched", ""
        except Exception as exc:
            fetch_error = f"{type(exc).__name__}: {exc}"
        else:
            fetch_error = "empty html response"
    else:
        fetch_error = ""
    title = _escape_html(article.title or "(无标题)")
    account = _escape_html(account_name)
    summary = _escape_html(article.summary or "")
    url = _escape_html(article.url or "")
    date_text = _escape_html(_format_ts(article.published_at))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;max-width:760px;margin:32px auto;padding:0 24px;line-height:1.7;color:#222}}
    h1{{font-size:24px;line-height:1.4;margin:0 0 12px}}
    .meta{{color:#666;font-size:13px;margin-bottom:20px}}
    .summary{{background:#f6f8fa;border:1px solid #e5e7eb;border-radius:6px;padding:14px 16px;margin:18px 0;color:#333}}
    a{{color:#1f77b4}}
    .note{{margin-top:28px;color:#777;font-size:13px}}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <div class="meta">{account}{' · ' + date_text if date_text else ''}</div>
  {f'<div class="summary">{summary}</div>' if summary else ''}
  {f'<p><a href="{url}" target="_blank" rel="noopener noreferrer">打开微信原文链接</a></p>' if url else ''}
  <div class="note">此文件来自本机微信缓存导出。缓存中没有正文 HTML 时，CLI 会保留标题、摘要和原文链接。</div>
</body>
</html>
""", "placeholder", fetch_error


def _write_index_csv(path: Path, articles: list[dict[str, Any]]) -> None:
    fields = ["id", "title", "published_date", "url", "summary", "html_path"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for article in articles:
            writer.writerow({field: article.get(field, "") for field in fields})


def open_html_dir() -> dict[str, Any]:
    import platform
    import subprocess

    from ... import paths

    p = paths.articles_html_dir()
    sys_name = platform.system()
    try:
        if sys_name == "Darwin":
            subprocess.Popen(["open", str(p)])
        elif sys_name == "Windows":
            subprocess.Popen(["explorer", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception as e:
        return {"status": "error", "message": str(e), "path": str(p)}
    return {"status": "ok", "path": str(p)}


@capability("op:wechat:articles-list")
def _cap_list(payload: dict) -> dict:
    return list_articles(
        category_id=payload.get("category_id"),
        mp_id=payload.get("mp_id"),
        limit=int(payload.get("limit") or 100),
        offset=int(payload.get("offset") or 0),
    )


@capability("op:wechat:articles-scan-local")
def _cap_scan(_payload: dict) -> dict:
    return scan_from_wechat_cache()


@capability("op:wechat:articles-sync-local")
def _cap_import(_payload: dict) -> dict:
    return import_scanned()


@capability("op:wechat:articles-cache-export")
def _cap_export(payload: dict) -> dict:
    return export_cached_by_account(
        str(payload.get("account_name") or payload.get("name") or ""),
        limit=int(payload.get("limit") or 100),
        output_dir=str(payload.get("output_dir") or "") or None,
        scan_first=bool(payload.get("scan_first", True)),
        auto_password=bool(payload.get("auto_password", True)),
        fetch_html=bool(payload.get("fetch_html", True)),
    )


@capability("op:wechat:articles-cache-verify")
def _cap_verify(payload: dict) -> dict:
    return verify_cache_export(
        str(payload.get("account_name") or payload.get("name") or ""),
        limit=int(payload.get("limit") or 100),
        output_dir=str(payload.get("output_dir") or "") or None,
        scan_first=bool(payload.get("scan_first", True)),
        auto_password=bool(payload.get("auto_password", True)),
        fetch_html=bool(payload.get("fetch_html", True)),
    )


@capability("op:wechat:articles-open-html-dir")
def _cap_open_dir(_payload: dict) -> dict:
    return open_html_dir()
