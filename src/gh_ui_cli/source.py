from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True)
class RuntimeConfig:
    source_root: Path | None = None
    db_path: Path | None = None
    factor_path: Path | None = None
    export_path: Path | None = None
    jypy_path: Path | None = None
    gh_backtest_path: Path | None = None
    api_base: str | None = None


def default_source_root() -> Path:
    return Path(os.environ.get("GH_QUANT_UI_PATH", Path.home() / "gh_quant_ui")).expanduser()


def resolve_source_root(config: RuntimeConfig) -> Path:
    root = (config.source_root or default_source_root()).expanduser().resolve()
    if not root.exists():
        raise RuntimeError(
            f"gh_quant_ui source root not found: {root}. "
            "Use --source-root or GH_QUANT_UI_PATH."
        )
    api_dir = root / "api"
    main_py = api_dir / "main.py"
    if not main_py.exists():
        raise RuntimeError(f"not a gh_quant_ui checkout, missing {main_py}")
    return root


def _prepend_sys_path(path: Path) -> None:
    value = str(path.expanduser().resolve())
    if value not in sys.path:
        sys.path.insert(0, value)


def configure_paths(config: RuntimeConfig) -> Path:
    source_root = resolve_source_root(config)
    api_dir = source_root / "api"

    if config.db_path is not None:
        os.environ["DB_PATH"] = str(config.db_path.expanduser())
    if config.factor_path is not None:
        os.environ["FACTOR_PATH"] = str(config.factor_path.expanduser())

    jypy_path = config.jypy_path or Path(os.environ.get("JYPY_PATH", Path.home() / "JyPy"))
    gh_backtest_path = config.gh_backtest_path or Path(
        os.environ.get("GH_BACKTEST_PATH", Path.home() / "gh_backtest" / "src")
    )
    os.environ.setdefault("JYPY_PATH", str(jypy_path.expanduser()))
    os.environ.setdefault("GH_BACKTEST_PATH", str(gh_backtest_path.expanduser()))

    _prepend_sys_path(api_dir)
    _prepend_sys_path(Path(os.environ["JYPY_PATH"]))
    _prepend_sys_path(Path(os.environ["GH_BACKTEST_PATH"]))
    return source_root


def _module_file(module: ModuleType) -> Path | None:
    file = getattr(module, "__file__", None)
    return Path(file).resolve() if file else None


def load_main_module(config: RuntimeConfig) -> ModuleType:
    source_root = configure_paths(config)
    expected = (source_root / "api" / "main.py").resolve()
    existing = sys.modules.get("main")
    if existing is not None:
        loaded = _module_file(existing)
        if loaded == expected:
            main_module = existing
        else:
            raise RuntimeError(f"module name 'main' already loaded from {loaded}, expected {expected}")
    else:
        try:
            main_module = importlib.import_module("main")
        except ModuleNotFoundError as exc:
            missing = exc.name or str(exc)
            raise RuntimeError(
                f"missing dependency while loading gh_quant_ui API: {missing}. "
                "In a fresh uv environment run with full dependencies, for example: "
                "uv run --extra full gh-ui doctor"
            ) from exc

    apply_runtime_overrides(main_module, config)
    return main_module


def apply_runtime_overrides(main_module: ModuleType, config: RuntimeConfig) -> None:
    if config.db_path is not None:
        db_path = str(config.db_path.expanduser())
        setattr(main_module, "DB_PATH", db_path)
        if hasattr(main_module, "_init_modules") and hasattr(main_module, "MODULES"):
            main_module.MODULES.update(main_module._init_modules(db_path))

    if config.factor_path is not None:
        setattr(main_module, "FACTOR_PATH", str(config.factor_path.expanduser()))

    if config.export_path is not None:
        setattr(main_module, "EXPORT_PATH", str(config.export_path.expanduser()))


def route_inventory(config: RuntimeConfig) -> list[dict[str, object]]:
    main_module = load_main_module(config)
    routes: list[dict[str, object]] = []
    for route in getattr(main_module.app, "routes", []):
        path = getattr(route, "path", "")
        methods = sorted(getattr(route, "methods", []) or [])
        name = getattr(route, "name", "")
        if not path or not methods:
            continue
        routes.append({"path": path, "methods": methods, "name": name})
    return routes
