from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

PackageMode = Literal["dual_track", "stereo_channels"]
Container = Literal["mp4", "mkv"]
ConflictPolicy = Literal["overwrite", "skip", "rename"]
StereoOrder = Literal["acc_left", "orig_left"]
TrackOrder = Literal["original_first", "instrumental_first"]
NamingMode = Literal["preserve", "suffix_ktv"]
VideoMode = Literal["copy", "reencode"]


@dataclass(slots=True)
class JobItem:
    source: Path
    relative_parent: Path = field(default_factory=Path)
    status: str = "等待"
    progress: int = 0
    output: Path | None = None
    error: str = ""


@dataclass(slots=True)
class AppOptions:
    output_dir: Path
    model_filename: str
    model_dir: Path
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    separator_path: str = "audio-separator"

    # KTV package
    container: Container = "mp4"
    package_mode: PackageMode = "dual_track"
    track_order: TrackOrder = "original_first"
    stereo_order: StereoOrder = "acc_left"
    audio_bitrate: str = "256k"
    sample_rate: int = 48000

    # Loudness equalization
    loudness_enabled: bool = True
    loudness_reference: Path | None = None
    true_peak_db: float = -1.0

    # Naming/output
    naming_mode: NamingMode = "preserve"
    recursive: bool = True
    mirror_tree: bool = True
    keep_instrumental: bool = False
    use_autocast: bool = True
    conflict_policy: ConflictPolicy = "overwrite"
    cleanup_temp: bool = True

    # Video
    video_mode: VideoMode = "copy"
    video_codec: str = "libx264"
    video_preset: str = "medium"
    video_quality: int = 18
    video_bitrate: str = ""
    video_pix_fmt: str = "yuv420p"
    video_custom_args: str = ""

    # Logging
    detailed_log: bool = False
