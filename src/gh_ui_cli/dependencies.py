from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any


HEAVY_PACKAGES = {
    "akshare",
    "ddddocr",
    "matplotlib",
    "onnxruntime",
    "opencv-python",
    "pyarrow",
    "pyecharts",
    "scipy",
}


@dataclass(frozen=True)
class Requirement:
    name: str
    specifier: str = ""
    marker: str = ""
    raw: str = ""


def parse_requirement_line(line: str) -> Requirement | None:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None
    requirement_part, marker = _split_marker(raw)
    match = re.match(r"^\s*([A-Za-z0-9_.-]+)\s*(.*)$", requirement_part)
    if not match:
        return None
    name = match.group(1)
    specifier = match.group(2).strip()
    return Requirement(name=name, specifier=specifier, marker=marker, raw=raw)


def build_dependency_report(requirements_path: Path, *, platform_name: str | None = None) -> dict[str, Any]:
    platform_value = platform_name or sys.platform
    requirements = _read_requirements(requirements_path)
    installed = []
    missing = []
    skipped = []

    for requirement in requirements:
        item = _requirement_item(requirement)
        if not marker_applies(requirement.marker, platform_value):
            skipped.append(item)
            continue
        version = installed_version(requirement.name)
        if version is None:
            missing.append(item)
        else:
            installed.append({**item, "installed_version": version})

    heavy_missing = sorted(item["name"] for item in missing if item["name"].lower() in HEAVY_PACKAGES)
    return {
        "ok": not missing,
        "source": str(requirements_path),
        "platform": platform_value,
        "total_requirements": len(requirements),
        "applicable_requirements": len(requirements) - len(skipped),
        "installed": installed,
        "missing": missing,
        "skipped": skipped,
        "heavy_missing": heavy_missing,
        "recommendation": _recommendation(missing, heavy_missing),
    }


def installed_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def marker_applies(marker: str, platform_name: str) -> bool:
    text = marker.strip()
    if not text:
        return True
    match = re.fullmatch(r"sys_platform\s*==\s*['\"]([^'\"]+)['\"]", text)
    if match:
        return platform_name == match.group(1)
    match = re.fullmatch(r"sys_platform\s*!=\s*['\"]([^'\"]+)['\"]", text)
    if match:
        return platform_name != match.group(1)
    return True


def _split_marker(raw: str) -> tuple[str, str]:
    if ";" not in raw:
        return raw, ""
    requirement_part, marker = raw.split(";", 1)
    return requirement_part.strip(), marker.strip()


def _read_requirements(path: Path) -> list[Requirement]:
    requirements = []
    for line in path.expanduser().read_text(encoding="utf-8").splitlines():
        requirement = parse_requirement_line(line)
        if requirement is not None:
            requirements.append(requirement)
    return requirements


def _requirement_item(requirement: Requirement) -> dict[str, str]:
    return {
        "name": requirement.name,
        "specifier": requirement.specifier,
        "marker": requirement.marker,
        "raw": requirement.raw,
    }


def _recommendation(missing: list[dict[str, str]], heavy_missing: list[str]) -> str:
    if not missing:
        return "All applicable source-mode requirements are installed."
    if heavy_missing:
        return (
            "Some heavy source-mode dependencies are missing. "
            "Use --api-base against a running sidecar for agent workflows, or allow a full install to finish."
        )
    return "Install missing source-mode dependencies, or use --api-base against a running sidecar."
