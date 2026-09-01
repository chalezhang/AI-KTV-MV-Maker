from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable

from .media import MediaTools
from .utils import run_streaming_process


@dataclass(frozen=True)
class LoudnessStats:
    integrated: float
    true_peak: float
    lra: float
    threshold: float
    target_offset: float


@dataclass(frozen=True)
class LoudnessReference:
    path: Path
    stats: LoudnessStats

    @property
    def target_i(self) -> float:
        return self.stats.integrated


class LoudnessEngine:
    """EBU R128 loudness matching using FFmpeg loudnorm in two-pass mode."""

    def __init__(self, media: MediaTools, true_peak_db: float = -1.0) -> None:
        self.media = media
        self.true_peak_db = max(-9.0, min(0.0, float(true_peak_db)))

    @staticmethod
    def _extract_json(lines: list[str]) -> dict:
        text = "\n".join(lines)
        matches = re.findall(r"\{\s*\"input_i\".*?\}", text, flags=re.S)
        if not matches:
            raise RuntimeError("FFmpeg loudnorm 未返回可解析的 JSON 响度统计。")
        return json.loads(matches[-1])

    @staticmethod
    def _stats_from_json(data: dict) -> LoudnessStats:
        try:
            return LoudnessStats(
                integrated=float(data["input_i"]),
                true_peak=float(data["input_tp"]),
                lra=float(data["input_lra"]),
                threshold=float(data["input_thresh"]),
                target_offset=float(data.get("target_offset", 0.0)),
            )
        except Exception as exc:
            raise RuntimeError(f"响度统计字段不完整：{data}") from exc

    def analyze(
        self,
        source: Path,
        cancel: Event,
        target_i: float = -16.0,
    ) -> LoudnessStats:
        # LRA=50 intentionally avoids compressing normal musical dynamics merely
        # to perform loudness matching. TP still protects inter-sample peaks.
        af = f"loudnorm=I={target_i:.2f}:TP={self.true_peak_db:.2f}:LRA=50:print_format=json"
        cmd = [
            self.media.ffmpeg, "-hide_banner", "-nostats", "-loglevel", "info",
            "-i", str(source), "-map", "0:a:0?", "-af", af,
            "-f", "null", "-",
        ]
        lines = run_streaming_process(cmd, cancel, tail_lines=260)
        return self._stats_from_json(self._extract_json(lines))

    def analyze_reference(self, reference: Path, cancel: Event) -> LoudnessReference:
        if not reference.exists() or not reference.is_file():
            raise RuntimeError(f"响度参考曲目不存在：{reference}")
        stats = self.analyze(reference, cancel, -16.0)
        if not (-70.0 <= stats.integrated <= -5.0):
            raise RuntimeError(f"参考曲目的 Integrated Loudness={stats.integrated:.2f} LUFS 超出 loudnorm 可用范围。")
        return LoudnessReference(reference, stats)

    def normalize(
        self,
        source: Path,
        output_wav: Path,
        reference: LoudnessReference,
        cancel: Event,
        duration: float,
        sample_rate: int,
        on_percent: Callable[[int], None] | None = None,
    ) -> tuple[LoudnessStats, float]:
        target_i = reference.target_i
        first = self.analyze(source, cancel, target_i)
        target_offset = first.target_offset
        # Use the first pass stats explicitly. With target LRA=50, loudnorm will
        # stay linear when peak headroom permits; otherwise its TP limiter/dynamic
        # path protects against clipping.
        af = (
            f"loudnorm=I={target_i:.2f}:TP={self.true_peak_db:.2f}:LRA=50:"
            f"measured_I={first.integrated:.2f}:measured_TP={first.true_peak:.2f}:"
            f"measured_LRA={first.lra:.2f}:measured_thresh={first.threshold:.2f}:"
            f"offset={target_offset:.2f}:linear=true:print_format=json"
        )
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        args = [
            "-y", "-i", str(source), "-map", "0:a:0?", "-af", af,
            "-ac", "2", "-ar", str(sample_rate), "-c:a", "pcm_s24le",
            str(output_wav),
        ]
        lines = self.media.run_ffmpeg_progress(
            args, cancel, duration, on_percent, tail_lines=320, loglevel="info"
        )
        text = "\n".join(lines)
        matches = re.findall(r"\{\s*\"input_i\".*?\}", text, flags=re.S)
        actual_i = target_i
        if matches:
            try:
                actual_i = float(json.loads(matches[-1]).get("output_i", target_i))
            except Exception:
                pass
        return first, actual_i
