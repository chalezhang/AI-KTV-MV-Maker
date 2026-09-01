from __future__ import annotations

import os
import shlex
from pathlib import Path
from threading import Event
from typing import Callable

from .media import MediaTools
from .models import AppOptions


class KTVMuxer:
    def __init__(self, media: MediaTools) -> None:
        self.media = media

    @staticmethod
    def _custom_args(text: str) -> list[str]:
        text = (text or "").strip()
        if not text:
            return []
        return shlex.split(text, posix=(os.name != "nt"))

    def _video_args(self, opts: AppOptions) -> list[str]:
        if opts.video_mode == "copy":
            return ["-c:v", "copy"]
        codec = (opts.video_codec or "libx264").strip()
        args = ["-c:v", codec]
        if codec in {"libx264", "libx265"}:
            if opts.video_preset.strip():
                args += ["-preset", opts.video_preset.strip()]
            args += ["-crf", str(opts.video_quality)]
            if opts.video_bitrate.strip():
                args += ["-maxrate", opts.video_bitrate.strip(), "-bufsize", opts.video_bitrate.strip()]
        elif codec in {"h264_nvenc", "hevc_nvenc", "av1_nvenc"}:
            if opts.video_preset.strip():
                args += ["-preset", opts.video_preset.strip()]
            args += ["-rc", "vbr", "-cq", str(opts.video_quality)]
            args += ["-b:v", opts.video_bitrate.strip() or "0"]
        else:
            if opts.video_bitrate.strip():
                args += ["-b:v", opts.video_bitrate.strip()]
        if opts.video_pix_fmt.strip():
            args += ["-pix_fmt", opts.video_pix_fmt.strip()]
        args += self._custom_args(opts.video_custom_args)
        return args

    def mux(
        self,
        source_video: Path,
        original_audio: Path,
        instrumental_audio: Path,
        output: Path,
        opts: AppOptions,
        cancel: Event,
        duration: float,
        on_percent: Callable[[int], None] | None = None,
    ) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp_output = output.with_name(f".{output.stem}.ktv_tmp{output.suffix}")
        tmp_output.unlink(missing_ok=True)

        base = [
            "-y", "-i", str(source_video), "-i", str(original_audio), "-i", str(instrumental_audio),
        ]
        video_args = self._video_args(opts)

        if opts.package_mode == "dual_track":
            if opts.track_order == "original_first":
                first_map, second_map = "1:a:0", "2:a:0"
                first_title, second_title = "原唱", "伴奏"
            else:
                first_map, second_map = "2:a:0", "1:a:0"
                first_title, second_title = "伴奏", "原唱"
            args = base + [
                "-map", "0:v:0", "-map", first_map, "-map", second_map,
                "-map_metadata", "0", "-map_chapters", "0",
            ] + video_args + [
                "-c:a:0", "aac", "-b:a:0", opts.audio_bitrate,
                "-ar:a:0", str(opts.sample_rate), "-ac:a:0", "2",
                "-c:a:1", "aac", "-b:a:1", opts.audio_bitrate,
                "-ar:a:1", str(opts.sample_rate), "-ac:a:1", "2",
                "-metadata:s:a:0", f"title={first_title}",
                "-metadata:s:a:0", f"handler_name={first_title}",
                "-metadata:s:a:1", f"title={second_title}",
                "-metadata:s:a:1", f"handler_name={second_title}",
                "-disposition:a:0", "default", "-disposition:a:1", "0",
            ]
        else:
            if opts.stereo_order == "acc_left":
                filt = (
                    "[2:a:0]pan=mono|c0=0.5*c0+0.5*c1[acc];"
                    "[1:a:0]pan=mono|c0=0.5*c0+0.5*c1[orig];"
                    "[acc][orig]amerge=inputs=2[aout]"
                )
                title = "左伴奏 / 右原唱"
            else:
                filt = (
                    "[1:a:0]pan=mono|c0=0.5*c0+0.5*c1[orig];"
                    "[2:a:0]pan=mono|c0=0.5*c0+0.5*c1[acc];"
                    "[orig][acc]amerge=inputs=2[aout]"
                )
                title = "左原唱 / 右伴奏"
            args = base + [
                "-filter_complex", filt,
                "-map", "0:v:0", "-map", "[aout]",
                "-map_metadata", "0", "-map_chapters", "0",
            ] + video_args + [
                "-c:a", "aac", "-b:a", opts.audio_bitrate,
                "-ar", str(opts.sample_rate),
                "-metadata:s:a:0", f"title={title}",
                "-metadata:s:a:0", f"handler_name={title}",
                "-disposition:a:0", "default",
            ]

        if opts.container == "mp4":
            args += ["-movflags", "+faststart"]
        args.append(str(tmp_output))
        try:
            self.media.run_ffmpeg_progress(args, cancel, duration, on_percent)
            if not tmp_output.exists() or tmp_output.stat().st_size < 1024:
                raise RuntimeError("FFmpeg 封装完成但输出文件无效。")
            if output.exists():
                output.unlink()
            tmp_output.replace(output)
        finally:
            tmp_output.unlink(missing_ok=True)
