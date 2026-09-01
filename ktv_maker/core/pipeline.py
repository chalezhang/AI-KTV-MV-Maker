from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from threading import Event
from typing import Callable

from .loudness import LoudnessEngine, LoudnessReference
from .media import MediaTools
from .models import AppOptions, JobItem
from .muxer import KTVMuxer
from .separator import UVRSeparator
from .utils import sanitize_filename, unique_path

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[int, str], None]


class KTVPipeline:
    def __init__(self, opts: AppOptions, cancel: Event) -> None:
        self.opts = opts
        self.cancel = cancel
        self.media = MediaTools(opts.ffmpeg_path, opts.ffprobe_path)
        self.separator = UVRSeparator(
            opts.separator_path, opts.model_filename, opts.model_dir,
            opts.use_autocast, opts.detailed_log
        )
        self.muxer = KTVMuxer(self.media)
        self.loudness = LoudnessEngine(self.media, opts.true_peak_db)
        self.reference: LoudnessReference | None = None

    def prepare(self, on_log: LogCallback, on_model_progress: Callable[[int], None] | None = None) -> None:
        ok, msg = self.media.verify()
        if not ok:
            raise RuntimeError(f"FFmpeg/FFprobe 检测失败：{msg}")
        on_log(f"环境 | {msg}")

        env_ok, env_text, notes = self.separator.environment_info()
        if not env_ok:
            raise RuntimeError(f"audio-separator 环境检测失败：\n{env_text[-2500:]}")
        for note in notes:
            on_log(f"环境 | {note}")

        on_log(f"模型 | 准备 {self.opts.model_filename}")
        self.separator.prepare(
            self.cancel,
            on_log=lambda s: on_log(f"模型 | {s}"),
            on_percent=on_model_progress,
        )

        if self.opts.loudness_enabled:
            if self.opts.loudness_reference is None:
                raise RuntimeError("已启用响度均衡，但没有设置参考曲目。")
            on_log(f"响度 | 分析固定参考：{self.opts.loudness_reference.name}")
            self.reference = self.loudness.analyze_reference(self.opts.loudness_reference, self.cancel)
            s = self.reference.stats
            on_log(
                f"响度 | 参考标定完成：{s.integrated:.2f} LUFS，"
                f"True Peak {s.true_peak:.2f} dBTP；安全上限 {self.opts.true_peak_db:.1f} dBTP"
            )
        else:
            on_log("响度 | 已关闭响度均衡。")

    def output_for(self, job: JobItem) -> Path:
        parent = self.opts.output_dir / job.relative_parent if self.opts.mirror_tree else self.opts.output_dir
        ext = ".mp4" if self.opts.container == "mp4" else ".mkv"
        stem = sanitize_filename(job.source.stem)
        if self.opts.naming_mode == "suffix_ktv":
            stem += "_KTV"
        path = parent / f"{stem}{ext}"

        # Never overwrite the source file itself. This is the only safety case
        # where preserve-name mode may add a suffix automatically.
        try:
            same_as_source = path.resolve() == job.source.resolve()
        except Exception:
            same_as_source = False
        if same_as_source:
            path = parent / f"{sanitize_filename(job.source.stem)}_KTV{ext}"

        if path.exists():
            if self.opts.conflict_policy == "rename":
                path = unique_path(path)
            elif self.opts.conflict_policy == "skip":
                return path
        return path

    @staticmethod
    def _scale(local: int, start: int, end: int) -> int:
        return start + int(max(0, min(100, local)) / 100 * (end - start))

    def process(self, job: JobItem, on_log: LogCallback, on_progress: ProgressCallback) -> tuple[str, Path | None]:
        if self.cancel.is_set():
            return "已取消", None

        output = self.output_for(job)
        job.output = output
        if output.exists() and self.opts.conflict_policy == "skip":
            on_log(f"跳过 | {job.source.name} → 目标已存在")
            on_progress(100, "已跳过")
            return "已跳过", output

        on_progress(1, "媒体检查")
        probe = self.media.validate_av(job.source)
        duration = self.media.duration_from_probe(probe)
        if duration <= 0:
            raise RuntimeError("无法获得输入 MV 时长。")

        tmp_root = self.opts.output_dir / ".ktv_work"
        tmp_root.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix="job_", dir=str(tmp_root)))
        mix_wav = temp_dir / "original_mix.wav"
        orig_norm = temp_dir / "original_normalized.wav"
        acc_norm = temp_dir / "instrumental_normalized.wav"

        try:
            on_log(f"任务 | {job.source.name}")
            on_log("阶段 1/5 | 提取原唱音轨")
            self.media.extract_audio(
                job.source, mix_wav, self.cancel, duration,
                lambda p: on_progress(self._scale(p, 2, 10), f"提取音频 {p}%")
            )

            on_log(f"阶段 2/5 | UVR 分离伴奏：{self.opts.model_filename}")
            instrumental = self.separator.separate_instrumental(
                mix_wav, temp_dir, self.cancel,
                on_log=on_log,
                on_percent=lambda p: on_progress(self._scale(p, 10, 58), f"UVR 分离 {p}%"),
            )
            on_progress(58, "UVR 分离完成")

            original_for_mux = mix_wav
            acc_for_mux = instrumental
            if self.opts.loudness_enabled:
                assert self.reference is not None
                on_log("阶段 3/5 | 原唱响度匹配")
                orig_before, target = self.loudness.normalize(
                    mix_wav, orig_norm, self.reference, self.cancel, duration,
                    self.opts.sample_rate,
                    lambda p: on_progress(self._scale(p, 58, 72), f"原唱响度 {p}%"),
                )
                on_log(f"响度 | 原唱 {orig_before.integrated:.2f} → {target:.2f} LUFS")
                original_for_mux = orig_norm

                on_log("阶段 4/5 | 伴奏响度匹配")
                acc_before, target = self.loudness.normalize(
                    instrumental, acc_norm, self.reference, self.cancel, duration,
                    self.opts.sample_rate,
                    lambda p: on_progress(self._scale(p, 72, 86), f"伴奏响度 {p}%"),
                )
                on_log(f"响度 | 伴奏 {acc_before.integrated:.2f} → {target:.2f} LUFS")
                acc_for_mux = acc_norm
            else:
                on_progress(86, "响度均衡已关闭")

            if self.opts.keep_instrumental:
                stem_dir = self.opts.output_dir / "_instrumental"
                stem_dir.mkdir(parents=True, exist_ok=True)
                saved = stem_dir / f"{sanitize_filename(job.source.stem)}_伴奏.wav"
                if saved.exists() and self.opts.conflict_policy == "rename":
                    saved = unique_path(saved)
                shutil.copy2(acc_for_mux, saved)
                on_log(f"伴奏 | 已另存 {saved.name}")

            video_desc = "视频流直接复制" if self.opts.video_mode == "copy" else f"视频重编码 {self.opts.video_codec}"
            on_log(f"阶段 5/5 | KTV 封装（{video_desc}）")
            self.muxer.mux(
                job.source, original_for_mux, acc_for_mux, output,
                self.opts, self.cancel, duration,
                lambda p: on_progress(self._scale(p, 86, 98), f"封装 {p}%"),
            )

            packaged = self.media.probe(output)
            audio_streams = [s for s in packaged.get("streams", []) if s.get("codec_type") == "audio"]
            if self.opts.package_mode == "dual_track" and len(audio_streams) < 2:
                raise RuntimeError("输出校验失败：双音轨模式下没有检测到两条音频流。")
            if self.opts.package_mode == "stereo_channels":
                if not audio_streams or int(audio_streams[0].get("channels") or 0) != 2:
                    raise RuntimeError("输出校验失败：左右声道模式未得到双声道音轨。")
            on_progress(100, "完成")
            on_log(f"完成 | {output.name}")
            return "完成", output
        finally:
            if self.opts.cleanup_temp:
                shutil.rmtree(temp_dir, ignore_errors=True)
                try:
                    tmp_root.rmdir()
                except OSError:
                    pass
