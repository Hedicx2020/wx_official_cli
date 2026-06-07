from __future__ import annotations

import argparse
from typing import Any

from .io import write_json
from .wechat.errors import WechatError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wx-official-cli",
        description="Export local cached WeChat official-account articles.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("export", "export articles for one official account"),
        ("crawl", "agent-friendly alias for export"),
    ):
        command = sub.add_parser(name, help=help_text)
        _add_export_args(command)
        command.set_defaults(func=handle_export)

    verify = sub.add_parser("verify", help="run export and emit a verification report")
    _add_export_args(verify)
    verify.add_argument("--strict", action="store_true", help="exit 1 when verification fails")
    verify.set_defaults(func=handle_verify)

    status = sub.add_parser("status", help="show local WeChat cache path and key status")
    _add_save(status)
    status.set_defaults(func=handle_status)

    manifest = sub.add_parser("manifest", help="emit agent-direct command manifest")
    _add_save(manifest)
    manifest.set_defaults(func=handle_manifest)

    return parser


def _add_export_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("account_name", help="official account name or mp_id")
    parser.add_argument("--limit", type=int, default=100, help="maximum articles to export")
    parser.add_argument("--output-dir", default="", help="directory for index and HTML files")
    parser.add_argument("--no-scan", action="store_true", help="use the existing local article store only")
    parser.add_argument(
        "--no-auto-password",
        action="store_true",
        help="skip automatic local key extraction when decrypted cache is not ready",
    )
    _add_save(parser)


def _add_save(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--save", default=None, help="write JSON output to this file")


def handle_export(args: argparse.Namespace) -> None:
    from .wechat.services.articles import sync as sync_svc

    result = sync_svc.export_cached_by_account(
        args.account_name,
        limit=args.limit,
        output_dir=args.output_dir or None,
        scan_first=not args.no_scan,
        auto_password=not args.no_auto_password,
    )
    write_json(result, save=args.save)


def handle_verify(args: argparse.Namespace) -> None:
    from .wechat.services.articles import sync as sync_svc

    report = sync_svc.verify_cache_export(
        args.account_name,
        limit=args.limit,
        output_dir=args.output_dir or None,
        scan_first=not args.no_scan,
        auto_password=not args.no_auto_password,
    )
    write_json(report, save=args.save)
    if args.strict and not report.get("ok"):
        raise SystemExit(1)


def handle_status(args: argparse.Namespace) -> None:
    from .wechat.services import keys as keys_svc

    write_json(keys_svc.password_status(), save=args.save)


def handle_manifest(args: argparse.Namespace) -> None:
    write_json(build_manifest(), save=args.save)


def build_manifest() -> dict[str, Any]:
    entries = [
        {
            "id": "wx_official:status",
            "name": "status",
            "description": "Show whether local WeChat cache path and key are available.",
            "command": "wx-official-cli status",
            "argv": ["wx-official-cli", "status"],
        },
        {
            "id": "wx_official:export",
            "name": "export",
            "description": "Export cached articles for one official account.",
            "command": "wx-official-cli export <ACCOUNT_NAME>",
            "argv": ["wx-official-cli", "export", "<ACCOUNT_NAME>"],
        },
        {
            "id": "wx_official:crawl",
            "name": "crawl",
            "description": "Alias for export, intended for agent instructions.",
            "command": "wx-official-cli crawl <ACCOUNT_NAME>",
            "argv": ["wx-official-cli", "crawl", "<ACCOUNT_NAME>"],
        },
        {
            "id": "wx_official:verify",
            "name": "verify",
            "description": "Run export and produce a strict verification report.",
            "command": "wx-official-cli verify <ACCOUNT_NAME> --strict --save <VERIFY_JSON>",
            "argv": [
                "wx-official-cli",
                "verify",
                "<ACCOUNT_NAME>",
                "--strict",
                "--save",
                "<VERIFY_JSON>",
            ],
        },
    ]
    return {
        "category": "wx_official",
        "total": len(entries),
        "default_command": "wx-official-cli export <ACCOUNT_NAME>",
        "entries": entries,
    }


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except WechatError as exc:
        write_json(exc.to_payload())
        raise SystemExit(1) from exc
    except Exception as exc:
        write_json({"error": str(exc), "type": type(exc).__name__})
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
