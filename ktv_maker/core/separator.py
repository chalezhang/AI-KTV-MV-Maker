from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from threading import Event
from typing import Callable

from .model_manager import ModelManager
from .utils import ExternalProcessError, resolve_executable, run_streaming_process


class UVRSeparator:
    def __init__(
        self,
        separator_path: str,
        model_filename: str,
        model_dir: Path,
        use_autocast: bool = True,
        detailed_log: bool = False,
    ) -> None:
        self.executable = resolve_executable(separator_path, "audio-separator")
        self.model_filename = model_filename.strip()
        self.model_dir = model_dir
        self.use_autocast = use_autocast
        self.detailed_log = detailed_log
        self.manager = ModelManager(self.executable, model_dir, self.model_filename)

    def prepare(
        self,
        cancel: Event,
        on_log: Callable[[str], None] | None = None,
        on_percent: Callable[[int], None] | None = None,
        force_redownload: bool = False,
    ) -> Path:
        return self.manager.ensure_ready(cancel, on_log, on_percent, force_redownload)

    def environment_info(self) -> tuple[bool, str, list[str]]:
        try:
            cp = subprocess.run(
                [self.executable, "--env_info"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=45, check=False
            )
            text = "\n".join(x for x in (cp.stdout, cp.stderr) if x).strip()
        except Exception as exc:
            return False, str(exc), ["无法执行 audio-separator --env_info"]
        low = text.lower()
        notes: list[str] = []
        torch_model = self.model_filename.lower().endswith((".ckpt", ".pth", ".pt"))
        onnx_model = self.model_filename.lower().endswith(".onnx")
        if "cuda is available in torch" in low and torch_model:
            notes.append("当前 RoFormer/PyTorch 模型检测到 CUDA，可使用 GPU。")
        if any(x in low for x in ("failed to load cublas", "failed to load cudart", "failed to load cufft")):
            if onnx_model:
                notes.append("ONNX CUDA DLL 缺失，当前 ONNX 模型的 GPU 加速需要修复。")
            else:
                notes.append("存在 ONNX Runtime CUDA DLL 警告；当前 .ckpt 模型主要走 PyTorch，不是直接致命错误。")
        return cp.returncode == 0, text, notes

    def command_for(self, mix_wav: Path, work_dir: Path) -> list[str]:
        cmd = [
            self.executable, str(mix_wav),
            "--model_filename", self.model_filename,
            "--output_format", "WAV",
            "--output_dir", str(work_dir),
            "--model_file_dir", str(self.model_dir),
            "--single_stem", "Instrumental",
            "--custom_output_names", json.dumps({"Instrumental": "instrumental"}, ensure_ascii=False),
            "--log_level", "INFO" if self.detailed_log else "WARNING",
        ]
        if self.use_autocast and not self.model_filename.lower().endswith(".onnx"):
            cmd.append("--use_autocast")
        return cmd

    @staticmethod
    def _is_corrupt_model_error(exc: BaseException) -> bool:
        text = str(exc).lower()
        return any(x in text for x in (
            "failed finding central directory", "checkpoint file is corrupted",
            "model file is corrupt or incomplete", "pytorchstreamreader failed",
            "invalid load key", "unexpected eof",
        ))

    def separate_instrumental(
        self,
        mix_wav: Path,
        work_dir: Path,
        cancel: Event,
        on_log: Callable[[str], None] | None = None,
        on_percent: Callable[[int], None] | None = None,
    ) -> Path:
        before = {p.resolve() for p in work_dir.glob("*.wav")}
        last_percent = -1

        def line_handler(line: str) -> None:
            nonlocal last_percent
            matches = re.findall(r"(?<!\d)(100|\d{1,2})(?:\.\d+)?%", line)
            if matches and on_percent:
                p = max(0, min(100, int(matches[-1])))
                if p != last_percent:
                    last_percent = p
                    on_percent(p)
            if on_log and self.detailed_log:
                on_log(f"UVR | {line}")
            elif on_log and any(k in line.lower() for k in ("error", "failed", "warning")):
                on_log(f"UVR | {line}")

        cmd = self.command_for(mix_wav, work_dir)
        try:
            run_streaming_process(cmd, cancel, line_handler, tail_lines=180)
        except ExternalProcessError as exc:
            if self._is_corrupt_model_error(exc) and not cancel.is_set():
                if on_log:
                    on_log("检测到 checkpoint 损坏，自动清理模型并重试一次。")
                self.prepare(cancel, on_log, None, force_redownload=True)
                run_streaming_process(cmd, cancel, line_handler, tail_lines=180)
            else:
                raise

        exact = work_dir / "instrumental.wav"
        if exact.exists() and exact.stat().st_size > 1024:
            return exact
        candidates = [
            p for p in work_dir.glob("*.wav")
            if p.resolve() not in before and p.resolve() != mix_wav.resolve() and p.stat().st_size > 1024
        ]
        preferred = [p for p in candidates if "instrument" in p.name.lower() or "other" in p.name.lower()]
        if preferred:
            return max(preferred, key=lambda p: p.stat().st_mtime)
        if candidates:
            return max(candidates, key=lambda p: p.stat().st_mtime)
        raise RuntimeError("UVR 分离完成但未找到 Instrumental WAV。")
