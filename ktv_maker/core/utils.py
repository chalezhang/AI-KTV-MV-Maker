from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections import deque
from pathlib import Path
from threading import Event, Thread
from typing import Callable, Iterable

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".ts", ".m2ts",
    ".mpg", ".mpeg", ".vob", ".webm", ".m4v", ".mts"
}

ProgressCallback = Callable[[str], None]


class ExternalProcessError(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, output_tail: str = "") -> None:
        self.cmd = list(cmd)
        self.returncode = int(returncode)
        self.output_tail = output_tail.strip()
        text = f"外部进程退出码 {self.returncode}: {' '.join(self.cmd[:5])}"
        if self.output_tail:
            text += f"\n--- 外部进程末尾日志 ---\n{self.output_tail}"
        super().__init__(text)


def is_video(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def discover_videos(path: Path, recursive: bool = True) -> list[Path]:
    if path.is_file():
        return [path] if is_video(path) else []
    if not path.is_dir():
        return []
    iterator: Iterable[Path] = path.rglob("*") if recursive else path.glob("*")
    return sorted((p for p in iterator if is_video(p)), key=lambda p: str(p).lower())


def resolve_executable(configured: str, fallback_name: str) -> str:
    configured = (configured or "").strip()
    if configured:
        p = Path(configured).expanduser()
        if p.exists():
            return str(p)
        found = shutil.which(configured)
        if found:
            return found
    found = shutil.which(fallback_name)
    if found:
        return found
    sibling = Path(sys.executable).resolve().parent / fallback_name
    for c in (sibling, sibling.with_suffix(".exe")):
        if c.exists():
            return str(c)
    return configured or fallback_name


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" ._")
    return name or "untitled"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for idx in range(1, 10000):
        candidate = path.with_name(f"{path.stem} ({idx}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成不冲突的输出文件名: {path}")


def terminate_process_tree(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            proc.terminate()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_streaming_process(
    cmd: list[str],
    cancel_event: Event,
    on_line: ProgressCallback | None = None,
    cwd: Path | None = None,
    tail_lines: int = 160,
) -> list[str]:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags,
    )
    captured: deque[str] = deque(maxlen=max(40, int(tail_lines)))

    def cancel_watcher() -> None:
        cancel_event.wait()
        if cancel_event.is_set() and proc.poll() is None:
            terminate_process_tree(proc)

    Thread(target=cancel_watcher, daemon=True).start()
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            if cancel_event.is_set():
                terminate_process_tree(proc)
                raise RuntimeError("用户已取消")
            line = raw.rstrip()
            if line:
                captured.append(line)
                if on_line:
                    on_line(line)
        code = proc.wait()
        if cancel_event.is_set():
            raise RuntimeError("用户已取消")
        if code != 0:
            raise ExternalProcessError(cmd, code, "\n".join(captured))
        return list(captured)
    finally:
        if cancel_event.is_set():
            terminate_process_tree(proc)
