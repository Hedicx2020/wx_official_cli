"""AI 报告复现 service - vendor 自 gh_quant_ui/api/ai.py。"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..wechat.errors import WechatDataMissing, WechatInvalidInput
from ..wechat.registry import capability


MAX_LOG_LINES = 600
_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def workspace_root(workspace: str | None = None) -> Path:
    value = workspace or os.environ.get("REPORT_REPRODUCE_PATH") or str(Path.home() / "report_reproduce")
    return Path(value).expanduser()


def output_root(workspace: Path, output_path: str | None = None) -> Path:
    value = output_path or os.environ.get("REPORT_REPRODUCE_OUTPUT_PATH") or "output"
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = workspace / p
    return p


def runner_info() -> dict[str, dict[str, Any]]:
    return {
        "codex": {
            "available": shutil.which("codex") is not None,
            "path": shutil.which("codex"),
            "label": "Codex",
        },
        "claude": {
            "available": shutil.which("claude") is not None,
            "path": shutil.which("claude"),
            "label": "Claude Code",
        },
    }


def _file_info(path: Path, root: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "relative_path": str(path.relative_to(root)) if path.is_relative_to(root) else path.name,
        "size_kb": round(stat.st_size / 1024, 1),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def scan_project(name: str, workspace: Path, output_dir: Path | None = None) -> dict:
    output_dir = output_dir or workspace / "output"
    plan_dir = workspace / "plan" / name
    src_dir = workspace / "src" / name
    out_dir = output_dir / name

    files: list[dict] = []
    for base in (plan_dir, src_dir, out_dir):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.name != ".DS_Store":
                files.append(_file_info(path, workspace))
    updated_at = max((f["modified_at"] for f in files), default=None)
    return {
        "name": name,
        "plan_exists": (plan_dir / "plan.md").exists(),
        "source_exists": src_dir.exists() and any(src_dir.rglob("*.py")),
        "verify_exists": (out_dir / "verify_report.md").exists(),
        "output_exists": out_dir.exists() and any(out_dir.iterdir()),
        "plan_path": str(plan_dir / "plan.md") if (plan_dir / "plan.md").exists() else None,
        "source_path": str(src_dir) if src_dir.exists() else None,
        "output_path": str(out_dir) if out_dir.exists() else None,
        "updated_at": updated_at,
        "files": files[:80],
    }


def scan_projects(workspace: Path, output_dir: Path | None = None) -> list[dict]:
    output_dir = output_dir or workspace / "output"
    names: set[str] = set()
    for part in ("plan", "src"):
        root = workspace / part
        if root.exists():
            names.update(p.name for p in root.iterdir() if p.is_dir())
    if output_dir.exists():
        names.update(p.name for p in output_dir.iterdir() if p.is_dir())
    return sorted(
        (scan_project(name, workspace, output_dir) for name in names),
        key=lambda p: p["updated_at"] or "",
        reverse=True,
    )


def recent_pdf_candidates(workspace: Path) -> list[dict]:
    roots = [
        workspace / "reports",
        Path.home() / "wiki" / "raw" / "pdf",
        Path.home() / "Downloads",
        Path.home() / "Desktop" / "报告",
    ]
    seen: set[Path] = set()
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            for path in root.rglob("*.pdf"):
                if path.is_file() and path not in seen:
                    files.append(path)
                    seen.add(path)
        except OSError:
            continue
    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return [_file_info(p, p.parent) for p in files[:30]]


def status(workspace: str | None = None, output_path: str | None = None) -> dict:
    ws = workspace_root(workspace)
    out = output_root(ws, output_path)
    return {
        "workspace": str(ws),
        "output_path": str(out),
        "workspace_exists": ws.exists(),
        "output_path_exists": out.exists(),
        "reproduce_command_exists": (ws / "reproduce.md").exists(),
        "claude_project_config_exists": (ws / "CLAUDE.md").exists(),
        "builtin_backtest": True,
        "builtin_subagents": True,
        "runners": runner_info(),
    }


def list_projects(workspace: str | None = None, output_path: str | None = None) -> dict:
    ws = workspace_root(workspace)
    out = output_root(ws, output_path)
    projects = scan_projects(ws, out) if ws.exists() else []
    return {"workspace": str(ws), "output_path": str(out), "projects": projects}


def list_pdfs(workspace: str | None = None) -> dict:
    ws = workspace_root(workspace)
    return {"workspace": str(ws), "pdfs": recent_pdf_candidates(ws)}


def _sanitize_report_name(value: str | None, pdf_path: Path) -> str:
    raw = (value or "").strip() or pdf_path.stem
    name = re.sub(r"[^\w一-鿿.-]+", "_", raw, flags=re.UNICODE).strip("_.-")
    if not name:
        name = f"report_{uuid.uuid4().hex[:8]}"
    return name[:90]


def _build_command(runner: str, pdf_path: Path, report_name: str, workspace: Path, out_dir: Path) -> tuple[list[str], str]:
    info = runner_info().get(runner)
    if info is None:
        raise WechatInvalidInput(f"未知 runner: {runner}")
    rp = info["path"]
    if not rp:
        raise WechatInvalidInput(f"{info['label']} 未安装或不在 PATH")

    prompt = (
        f"你在本机 {workspace} 研报复现工作区执行任务。\n"
        f"目标: 复现 PDF 研报 `{pdf_path}`。\n"
        f"报告目录名固定使用 `{report_name}`。\n"
        f"产物输出根目录固定使用 `{out_dir}`，本次报告产物必须写到 `{out_dir / report_name}`。"
    )
    if runner == "claude":
        cmd = [str(rp), "-p", prompt, "--permission-mode", "bypassPermissions", "--output-format", "stream-json"]
    else:
        cmd = [str(rp), "exec", "--cd", str(workspace), "--skip-git-repo-check",
               "--dangerously-bypass-approvals-and-sandbox", prompt]
    return cmd, shlex.join(cmd)


def _public(task: dict) -> dict:
    return {k: v for k, v in task.items() if k != "process"}


def list_tasks() -> dict:
    with _LOCK:
        items = [_public(t) for t in _TASKS.values()]
    items.sort(key=lambda t: t.get("started_at", ""), reverse=True)
    return {"tasks": items}


def get_task(task_id: str) -> dict:
    with _LOCK:
        t = _TASKS.get(task_id)
        if t is None:
            raise WechatDataMissing(f"任务不存在: {task_id}", code="AI_TASK_MISSING")
        return _public(t)


def start(payload: dict) -> dict:
    pdf = (payload.get("pdf_path") or "").strip()
    if not pdf:
        raise WechatInvalidInput("pdf_path 必填")
    pdf_path = Path(pdf).expanduser()
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        raise WechatInvalidInput(f"PDF 文件不存在或不是 .pdf: {pdf_path}")

    ws = workspace_root(payload.get("workspace"))
    if not ws.exists():
        raise WechatInvalidInput(f"工作区不存在: {ws}")
    out = output_root(ws, payload.get("output_path"))
    out.mkdir(parents=True, exist_ok=True)
    runner = (payload.get("runner") or "codex").strip()
    report_name = _sanitize_report_name(payload.get("report_name"), pdf_path)
    cmd, preview = _build_command(runner, pdf_path, report_name, ws, out)

    task_id = uuid.uuid4().hex
    task = {
        "id": task_id, "runner": runner, "status": "running",
        "pdf_path": str(pdf_path), "report_name": report_name,
        "workspace": str(ws), "output_path": str(out),
        "command": preview, "logs": [], "artifacts": None,
        "return_code": None, "error": None,
        "started_at": _now(), "updated_at": _now(), "ended_at": None,
        "process": None,
    }
    with _LOCK:
        _TASKS[task_id] = task
    thread = threading.Thread(target=_run_task, args=(task_id, cmd, ws, report_name, out), daemon=True)
    thread.start()
    return _public(task)


def cancel(task_id: str) -> dict:
    with _LOCK:
        t = _TASKS.get(task_id)
        if t is None:
            raise WechatDataMissing(f"任务不存在: {task_id}", code="AI_TASK_MISSING")
        if t["status"] != "running":
            return _public(t)
        t["status"] = "cancelled"
        t["updated_at"] = _now()
        proc = t.get("process")
    if proc:
        try:
            _terminate(proc)
        except Exception:
            pass
    with _LOCK:
        return _public(_TASKS[task_id])


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        proc.terminate()
    else:
        os.killpg(proc.pid, signal.SIGTERM)


def _append_log(task_id: str, line: str) -> None:
    line = line.rstrip()
    if not line:
        return
    with _LOCK:
        t = _TASKS.get(task_id)
        if t is None:
            return
        logs = t.setdefault("logs", [])
        logs.append(line)
        if len(logs) > MAX_LOG_LINES:
            del logs[: len(logs) - MAX_LOG_LINES]
        t["updated_at"] = _now()


def _update(task_id: str, **patch) -> None:
    with _LOCK:
        t = _TASKS.get(task_id)
        if t is None:
            return
        t.update(patch)
        t["updated_at"] = _now()


def _run_task(task_id: str, cmd: list[str], workspace: Path, report_name: str, out_dir: Path) -> None:
    try:
        kwargs: dict = {}
        if os.name != "nt":
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(
            cmd, cwd=str(workspace),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, **kwargs,
        )
        _update(task_id, process=proc)
        assert proc.stdout is not None
        for line in proc.stdout:
            _append_log(task_id, line)
        rc = proc.wait()
        with _LOCK:
            status = _TASKS.get(task_id, {}).get("status")
        if status == "cancelled":
            _update(task_id, ended_at=_now(), return_code=rc)
            return
        artifacts = scan_project(report_name, workspace, out_dir)
        if rc == 0:
            _update(task_id, status="done", ended_at=_now(), return_code=rc, artifacts=artifacts)
        else:
            _update(task_id, status="error", ended_at=_now(), return_code=rc,
                    error=f"runner exited with code {rc}", artifacts=artifacts)
    except Exception as exc:  # noqa: BLE001
        _append_log(task_id, f"ERROR: {type(exc).__name__}: {exc}")
        _update(task_id, status="error", ended_at=_now(), error=str(exc))


@capability("op:ai:status")
def _cap_status(payload: dict) -> dict:
    return status(workspace=payload.get("workspace"), output_path=payload.get("output_path"))


@capability("op:ai:report-projects")
def _cap_projects(payload: dict) -> dict:
    return list_projects(workspace=payload.get("workspace"), output_path=payload.get("output_path"))


@capability("op:ai:report-pdf-candidates")
def _cap_pdfs(payload: dict) -> dict:
    return list_pdfs(workspace=payload.get("workspace"))


@capability("op:ai:report-tasks")
def _cap_tasks(_payload: dict) -> dict:
    return list_tasks()


@capability("op:ai:report-task")
def _cap_task(payload: dict) -> dict:
    return get_task(str(payload.get("task_id") or ""))


@capability("op:ai:report-task-cancel")
def _cap_cancel(payload: dict) -> dict:
    return cancel(str(payload.get("task_id") or ""))


@capability("op:ai:report-start")
def _cap_start(payload: dict) -> dict:
    return start(payload or {})
