from __future__ import annotations

import hashlib
import ssl
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable

from .utils import run_streaming_process

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[int], None]


@dataclass(frozen=True)
class MirrorFile:
    filename: str
    urls: tuple[str, ...]
    min_size: int
    sha256: str | None = None


@dataclass(frozen=True)
class ModelSpec:
    model: MirrorFile
    configs: tuple[MirrorFile, ...] = ()


KNOWN_MODEL_SPECS: dict[str, ModelSpec] = {
    "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt": ModelSpec(
        model=MirrorFile(
            filename="mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt",
            urls=(
                "https://huggingface.co/jarredou/aufr33-viperx-karaoke-melroformer-model/resolve/main/mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt?download=true",
                "https://huggingface.co/shiromiya/audio-separation-models/resolve/main/mel_band_roformer_karaoke_aufr33_viperx/mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt?download=true",
            ),
            min_size=800 * 1024 * 1024,
            sha256="1de20d459332fe8869aeb01327a31df0032262706e1365114e852dc271779813",
        ),
        configs=(
            MirrorFile(
                filename="config_mel_band_roformer_karaoke.yaml",
                urls=(
                    "https://huggingface.co/jarredou/aufr33-viperx-karaoke-melroformer-model/resolve/main/config_mel_band_roformer_karaoke.yaml?download=true",
                    "https://huggingface.co/shiromiya/audio-separation-models/resolve/main/mel_band_roformer_karaoke_aufr33_viperx/config_mel_band_roformer_karaoke.yaml?download=true",
                ),
                min_size=1000,
            ),
        ),
    ),
    "model_bs_roformer_ep_317_sdr_12.9755.ckpt": ModelSpec(
        model=MirrorFile(
            filename="model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            urls=(
                "https://huggingface.co/Blane187/all_public_uvr_models/resolve/main/model_bs_roformer_ep_317_sdr_12.9755.ckpt?download=true",
            ),
            min_size=550 * 1024 * 1024,
            sha256="5b84f37e8d444c8cb30c79d77f613a41c05868ff9c9ac6c7049c00aefae115aa",
        ),
    ),
}


class ModelManager:
    def __init__(self, executable: str, model_dir: Path, model_filename: str) -> None:
        self.executable = executable
        self.model_dir = model_dir
        self.model_filename = model_filename.strip()
        self.model_dir.mkdir(parents=True, exist_ok=True)

    @property
    def model_path(self) -> Path:
        return self.model_dir / self.model_filename

    @staticmethod
    def _looks_like_error_page(path: Path) -> bool:
        try:
            head = path.read_bytes()[:4096].lstrip().lower()
        except OSError:
            return True
        markers = (
            b"<!doctype html", b"<html", b"access denied", b"bad gateway",
            b"service unavailable", b"version https://git-lfs.github.com/spec/v1",
        )
        return any(x in head for x in markers)

    def validate_model(self) -> tuple[bool, str]:
        path = self.model_path
        if not path.exists():
            return False, "模型文件不存在"
        size = path.stat().st_size
        spec = KNOWN_MODEL_SPECS.get(self.model_filename)
        min_size = spec.model.min_size if spec else (1024 * 1024 if path.suffix.lower() in {".ckpt", ".onnx", ".pt", ".pth"} else 256)
        if size < min_size:
            return False, f"模型文件仅 {size / 1024:.1f} KiB，明显不完整"
        if self._looks_like_error_page(path):
            return False, "模型内容是 HTML/错误页/Git-LFS 指针，不是真实权重"
        return True, f"模型缓存检查通过（{size / 1024 / 1024:.1f} MiB）"

    def remove_related(self, on_log: LogCallback | None = None) -> None:
        names = {self.model_filename}
        spec = KNOWN_MODEL_SPECS.get(self.model_filename)
        if spec:
            names.update(x.filename for x in spec.configs)
        for name in names:
            path = self.model_dir / name
            if path.exists():
                path.unlink()
                if on_log:
                    on_log(f"删除损坏缓存：{name}")

    def _official_download(self, cancel: Event, on_log: LogCallback | None = None) -> None:
        cmd = [
            self.executable,
            "--model_filename", self.model_filename,
            "--model_file_dir", str(self.model_dir),
            "--download_model_only",
            "--log_level", "WARNING",
        ]
        run_streaming_process(cmd, cancel, on_line=(on_log if on_log else None), tail_lines=100)

    @staticmethod
    def _sha256(path: Path, cancel: Event) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            while True:
                if cancel.is_set():
                    raise RuntimeError("用户已取消")
                chunk = f.read(4 * 1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _download_item(
        self,
        item: MirrorFile,
        cancel: Event,
        on_log: LogCallback | None,
        on_percent: ProgressCallback | None,
    ) -> None:
        target = self.model_dir / item.filename
        tmp = target.with_suffix(target.suffix + ".part")
        headers = {"User-Agent": "Mozilla/5.0 UVR5-KTV-Maker/3.0"}
        ctx = ssl.create_default_context()
        last_error: Exception | None = None
        for idx, url in enumerate(item.urls, 1):
            try:
                tmp.unlink(missing_ok=True)
                if on_log:
                    on_log(f"备用镜像 {idx}/{len(item.urls)}：{item.filename}")
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=90, context=ctx) as resp, tmp.open("wb") as out:
                    total = int(resp.headers.get("Content-Length") or 0)
                    done = 0
                    while True:
                        if cancel.is_set():
                            raise RuntimeError("用户已取消")
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        if on_percent and total > 0:
                            on_percent(min(99, int(done / total * 100)))
                if tmp.stat().st_size < item.min_size or self._looks_like_error_page(tmp):
                    raise RuntimeError("下载结果尺寸/内容异常，可能被代理替换")
                tmp.replace(target)
                if item.sha256:
                    digest = self._sha256(target, cancel)
                    if digest.lower() != item.sha256.lower():
                        target.unlink(missing_ok=True)
                        raise RuntimeError("SHA-256 校验失败")
                if on_percent:
                    on_percent(100)
                return
            except Exception as exc:
                last_error = exc
                tmp.unlink(missing_ok=True)
                if on_log:
                    on_log(f"镜像失败：{exc}")
        raise RuntimeError(f"所有备用镜像均失败：{last_error}")

    def ensure_ready(
        self,
        cancel: Event,
        on_log: LogCallback | None = None,
        on_percent: ProgressCallback | None = None,
        force_redownload: bool = False,
    ) -> Path:
        if force_redownload:
            self.remove_related(on_log)
        ok, msg = self.validate_model()
        if ok:
            if on_log:
                on_log(msg)
            return self.model_path
        if self.model_path.exists():
            if on_log:
                on_log(f"检测到无效模型：{msg}")
            self.remove_related(on_log)

        official_error: Exception | None = None
        try:
            if on_log:
                on_log("使用 audio-separator 官方下载器准备模型…")
            self._official_download(cancel, on_log)
        except Exception as exc:
            official_error = exc

        ok, msg = self.validate_model()
        if ok:
            if on_log:
                on_log(msg)
            return self.model_path

        if self.model_path.exists():
            self.remove_related(on_log)
        spec = KNOWN_MODEL_SPECS.get(self.model_filename)
        if not spec:
            raise RuntimeError(f"模型准备失败：{official_error or msg}。当前自定义模型没有内置备用镜像。")
        if on_log:
            on_log("官方下载结果无效，切换到备用镜像…")
        self._download_item(spec.model, cancel, on_log, on_percent)
        for cfg in spec.configs:
            cfg_path = self.model_dir / cfg.filename
            if not cfg_path.exists() or cfg_path.stat().st_size < cfg.min_size:
                self._download_item(cfg, cancel, on_log, None)
        ok, msg = self.validate_model()
        if not ok:
            raise RuntimeError(f"模型备用下载后仍无效：{msg}")
        if on_log:
            on_log(msg)
        return self.model_path
