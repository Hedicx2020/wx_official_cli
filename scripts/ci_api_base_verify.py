from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from gh_ui_cli.runtime_verify import run_runtime_verify


def run_verify(output_path: Path, *, command: list[str] | None = None) -> dict[str, Any]:
    return run_runtime_verify(output_path, command=command or ["gh-ui"])


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python scripts/ci_api_base_verify.py <verify-output.json>", file=sys.stderr)
        return 2
    report = run_verify(Path(args[0]))
    print(json.dumps({"output": str(Path(args[0])), "ok": report.get("ok")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
