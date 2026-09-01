from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from threading import Event
from typing import Callable

from .utils import ExternalProcessError, resolve_executable, run_streaming_process


class MediaTools:
    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe") -> None:
        self.ffmpeg = resolve_executable(ffmpeg_path, "ffmpeg")
        self.ffprobe = resolve_executable(ffprobe_path, "ffprobe")

    def verify(self) -> tuple[bool, str]:
        try:
            out = subprocess.run(
                [self.ffmpeg, "-version"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10, check=False
            )
            if out.returncode != 0:
                return False, out.stderr or out.stdout
            first = (out.stdout or "").splitlines()[0]
            probe = subprocess.run(
                [self.ffprobe, "-version"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10, check=False
            )
            if probe.returncode != 0:
                return False, f"FFmpeg 可用，但 FFprobe 不可用：{probe.stderr or probe.stdout}"
            return True, first
        except Exception as exc:
            return False, str(exc)

    def probe(self, source: Path) -> dict:
        cmd = [
            self.ffprobe, "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(source),
        ]
        out = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, check=False
        )
        if out.returncode != 0:
            raise RuntimeError(f"FFprobe 读取失败: {out.stderr.strip()}")
        data = json.loads(out.stdout)
        return data

    def validate_av(self, source: Path) -> dict:
        data = self.probe(source)
        streams = data.get("streams", [])
        if not any(s.get("codec_type") == "video" for s in streams):
            raise RuntimeError("输入文件不包含视频流")
        if not any(s.get("codec_type") == "audio" for s in streams):
            raise RuntimeError("输入文件不包含音频流")
        return data

    @staticmethod
    def duration_from_probe(data: dict) -> float:
        try:
            return float(data.get("format", {}).get("duration") or 0.0)
        except Exception:
            return 0.0

    def duration(self, source: Path) -> float:
        return self.duration_from_probe(self.probe(source))

    def run_ffmpeg_progress(
        self,
        args: list[str],
        cancel: Event,
        duration: float,
        on_percent: Callable[[int], None] | None = None,
        tail_lines: int = 160,
        loglevel: str = "error",
    ) -> list[str]:
        cmd = [self.ffmpeg, "-hide_banner", "-nostats", "-loglevel", loglevel, "-progress", "pipe:1"] + args

        def handler(line: str) -> None:
            if not on_percent or duration <= 0:
                return
            if line.startswith("out_time_us="):
                try:
                    seconds = int(line.split("=", 1)[1]) / 1_000_000.0
                    on_percent(max(0, min(100, int(seconds / duration * 100))))
                except Exception:
                    pass
            elif line.startswith("out_time_ms="):
                # Older builds use microseconds despite the historical key name.
                try:
                    seconds = int(line.split("=", 1)[1]) / 1_000_000.0
                    on_percent(max(0, min(100, int(seconds / duration * 100))))
                except Exception:
                    pass
            elif line == "progress=end":
                on_percent(100)

        return run_streaming_process(cmd, cancel, handler, tail_lines=tail_lines)

    def extract_audio(
        self,
        source: Path,
        out_wav: Path,
        cancel: Event,
        duration: float,
        on_percent: Callable[[int], None] | None = None,
    ) -> None:
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        args = [
            "-y", "-i", str(source),
            "-map", "0:a:0", "-vn", "-sn", "-dn",
            "-ac", "2", "-ar", "44100", "-c:a", "pcm_s24le",
            str(out_wav),
        ]
        self.run_ffmpeg_progress(args, cancel, duration, on_percent)
