from __future__ import annotations

import traceback
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from ..core.models import AppOptions, JobItem
from ..core.pipeline import KTVPipeline


class BatchWorker(QObject):
    job_started = Signal(int)
    job_progress = Signal(int, int, str)
    job_finished = Signal(int, str, str, str)
    log = Signal(str)
    all_finished = Signal(bool)

    def __init__(self, jobs: list[JobItem], opts: AppOptions) -> None:
        super().__init__()
        self.jobs = jobs
        self.opts = opts
        self.cancel_event = Event()

    @Slot()
    def run(self) -> None:
        cancelled = False
        pipeline = KTVPipeline(self.opts, self.cancel_event)
        try:
            self.log.emit("预检 | 开始批处理环境、模型与参考响度检查")
            last_bucket = {-1}

            def model_progress(percent: int) -> None:
                bucket = max(0, min(100, percent)) // 10
                old = next(iter(last_bucket))
                if bucket != old:
                    last_bucket.clear()
                    last_bucket.add(bucket)
                    self.log.emit(f"模型 | 下载/校验 {percent}%")

            pipeline.prepare(self.log.emit, model_progress)
            self.log.emit("预检 | 通过，开始处理队列")
        except Exception as exc:
            msg = str(exc)
            self.log.emit(f"预检失败 | {msg}")
            if self.opts.detailed_log:
                self.log.emit(traceback.format_exc())
            for idx in range(len(self.jobs)):
                self.job_finished.emit(idx, "失败", "", f"批处理预检失败：{msg}")
            self.all_finished.emit(False)
            return

        for idx, job in enumerate(self.jobs):
            if self.cancel_event.is_set():
                cancelled = True
                break
            self.job_started.emit(idx)
            try:
                status, output = pipeline.process(
                    job,
                    on_log=self.log.emit,
                    on_progress=lambda p, s, i=idx: self.job_progress.emit(i, p, s),
                )
                if status == "已取消":
                    cancelled = True
                self.job_finished.emit(idx, status, str(output or ""), "")
            except Exception as exc:
                msg = str(exc)
                self.log.emit(f"失败 | {job.source.name} | {msg}")
                if self.opts.detailed_log:
                    self.log.emit(traceback.format_exc())
                self.job_finished.emit(idx, "失败", "", msg)
        self.all_finished.emit(cancelled or self.cancel_event.is_set())

    @Slot()
    def cancel(self) -> None:
        self.cancel_event.set()
        self.log.emit("任务 | 正在取消当前外部进程…")
