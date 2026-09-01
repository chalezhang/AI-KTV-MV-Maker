from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from threading import Event

from PySide6.QtCore import QSettings, QThread, Qt, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QApplication
)

from ..core.loudness import LoudnessEngine
from ..core.media import MediaTools
from ..core.model_manager import ModelManager
from ..core.models import AppOptions, JobItem
from ..core.separator import UVRSeparator
from ..core.utils import discover_videos
from .worker import BatchWorker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE = PROJECT_ROOT / "resources" / "loudness_reference.wav"
DEFAULT_MODELS = [
    "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt",
    "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
    "UVR-MDX-NET-Inst_HQ_5.onnx",
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("UVR5 KTV MV 批量制作器 v3")
        self.resize(1220, 880)
        self.settings = QSettings("UVR5KTV", "KTVMakerV3")
        self.jobs: list[JobItem] = []
        self.worker: BatchWorker | None = None
        self.thread: QThread | None = None
        self._build_ui()
        self._load_settings()
        self._update_mode_ui()
        self._update_video_ui()
        self._update_loudness_ui()

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        main = QVBoxLayout(root)

        src_box = QGroupBox("输入与输出")
        sg = QGridLayout(src_box)
        self.input_edit = QLineEdit()
        self.output_edit = QLineEdit()
        btn_file = QPushButton("添加文件")
        btn_dir = QPushButton("添加目录")
        btn_out = QPushButton("输出目录")
        btn_clear = QPushButton("清空队列")
        self.recursive_cb = QCheckBox("递归扫描")
        self.recursive_cb.setChecked(True)
        self.mirror_cb = QCheckBox("保持原目录结构")
        self.mirror_cb.setChecked(True)
        sg.addWidget(QLabel("最近输入"), 0, 0)
        sg.addWidget(self.input_edit, 0, 1, 1, 4)
        sg.addWidget(btn_file, 0, 5)
        sg.addWidget(btn_dir, 0, 6)
        sg.addWidget(QLabel("输出目录"), 1, 0)
        sg.addWidget(self.output_edit, 1, 1, 1, 4)
        sg.addWidget(btn_out, 1, 5)
        sg.addWidget(btn_clear, 1, 6)
        sg.addWidget(self.recursive_cb, 2, 1)
        sg.addWidget(self.mirror_cb, 2, 2)
        main.addWidget(src_box)

        tabs = QTabWidget()
        tabs.addTab(self._build_basic_tab(), "KTV / UVR")
        tabs.addTab(self._build_loudness_tab(), "响度均衡")
        tabs.addTab(self._build_video_tab(), "视频编码")
        main.addWidget(tabs)

        splitter = QSplitter(Qt.Orientation.Vertical)
        table_wrap = QWidget()
        tv = QVBoxLayout(table_wrap)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["MV", "输出", "状态", "进度", "错误"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tv.addWidget(self.table)
        splitter.addWidget(table_wrap)

        log_wrap = QWidget()
        lv = QVBoxLayout(log_wrap)
        lh = QHBoxLayout()
        lh.addWidget(QLabel("结构化运行日志"))
        lh.addStretch(1)
        self.detailed_log_cb = QCheckBox("详细日志（排障）")
        lh.addWidget(self.detailed_log_cb)
        lv.addLayout(lh)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(6000)
        lv.addWidget(self.log_edit)
        splitter.addWidget(log_wrap)
        splitter.setSizes([390, 220])
        main.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        self.overall_label = QLabel("等待任务")
        self.overall_progress = QProgressBar()
        self.start_btn = QPushButton("开始批量制作")
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setEnabled(False)
        self.open_output_btn = QPushButton("打开输出目录")
        self.env_btn = QPushButton("环境检测")
        bottom.addWidget(self.overall_label)
        bottom.addWidget(self.overall_progress, 1)
        bottom.addWidget(self.env_btn)
        bottom.addWidget(self.start_btn)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.open_output_btn)
        main.addLayout(bottom)

        btn_file.clicked.connect(self._add_files)
        btn_dir.clicked.connect(self._add_directory)
        btn_out.clicked.connect(self._choose_output)
        btn_clear.clicked.connect(self._clear_queue)
        self.env_btn.clicked.connect(self._check_environment)
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn.clicked.connect(self._cancel)
        self.open_output_btn.clicked.connect(self._open_output)

    def _build_basic_tab(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        self.model_combo = QComboBox(); self.model_combo.setEditable(True); self.model_combo.addItems(DEFAULT_MODELS)
        self.model_dir_edit = QLineEdit()
        self.separator_edit = QLineEdit("audio-separator")
        self.ffmpeg_edit = QLineEdit("ffmpeg")
        self.container_combo = QComboBox(); self.container_combo.addItem("MP4", "mp4"); self.container_combo.addItem("MKV", "mkv")
        self.mode_combo = QComboBox(); self.mode_combo.addItem("双音轨", "dual_track"); self.mode_combo.addItem("左右声道", "stereo_channels")
        self.track_order_combo = QComboBox()
        self.track_order_combo.addItem("轨道1：原唱 / 轨道2：伴奏（默认）", "original_first")
        self.track_order_combo.addItem("轨道1：伴奏 / 轨道2：原唱", "instrumental_first")
        self.stereo_combo = QComboBox(); self.stereo_combo.addItem("左伴奏 / 右原唱", "acc_left"); self.stereo_combo.addItem("左原唱 / 右伴奏", "orig_left")
        self.bitrate_combo = QComboBox(); self.bitrate_combo.addItems(["192k", "256k", "320k"]); self.bitrate_combo.setCurrentText("256k")
        self.rate_spin = QSpinBox(); self.rate_spin.setRange(32000, 96000); self.rate_spin.setSingleStep(1000); self.rate_spin.setValue(48000)
        self.naming_combo = QComboBox(); self.naming_combo.addItem("保持原文件名（默认）", "preserve"); self.naming_combo.addItem("添加 _KTV 后缀", "suffix_ktv")
        self.conflict_combo = QComboBox(); self.conflict_combo.addItem("覆盖输出目标（默认）", "overwrite"); self.conflict_combo.addItem("跳过", "skip"); self.conflict_combo.addItem("自动改名", "rename")
        self.autocast_cb = QCheckBox("GPU autocast"); self.autocast_cb.setChecked(True)
        self.keep_stem_cb = QCheckBox("另存最终伴奏 WAV")

        rows = [
            ("UVR 模型", self.model_combo, 0, 0), ("模型缓存目录", self.model_dir_edit, 1, 0),
            ("audio-separator", self.separator_edit, 2, 0), ("FFmpeg", self.ffmpeg_edit, 3, 0),
            ("输出容器", self.container_combo, 0, 3), ("KTV 模式", self.mode_combo, 1, 3),
            ("双音轨顺序", self.track_order_combo, 2, 3), ("左右声道顺序", self.stereo_combo, 3, 3),
            ("音频码率", self.bitrate_combo, 4, 0), ("采样率", self.rate_spin, 4, 3),
            ("文件命名", self.naming_combo, 5, 0), ("重名策略", self.conflict_combo, 5, 3),
        ]
        for label, widget, row, col in rows:
            g.addWidget(QLabel(label), row, col); g.addWidget(widget, row, col + 1, 1, 2)
        g.addWidget(self.autocast_cb, 6, 1)
        g.addWidget(self.keep_stem_cb, 6, 4)
        self.mode_combo.currentIndexChanged.connect(self._update_mode_ui)
        return w

    def _build_loudness_tab(self) -> QWidget:
        w = QWidget(); g = QGridLayout(w)
        self.loudness_cb = QCheckBox("启用参考曲目响度均衡（默认）"); self.loudness_cb.setChecked(True)
        self.reference_edit = QLineEdit(str(DEFAULT_REFERENCE))
        ref_btn = QPushButton("选择参考曲目")
        analyze_btn = QPushButton("分析参考响度")
        self.ref_status = QLabel("固定参考会在每次批处理预检时重新标定。")
        self.tp_spin = QDoubleSpinBox(); self.tp_spin.setRange(-9.0, 0.0); self.tp_spin.setDecimals(1); self.tp_spin.setSingleStep(0.1); self.tp_spin.setValue(-1.0); self.tp_spin.setSuffix(" dBTP")
        note = QLabel(
            "机制：参考曲目的 Integrated Loudness（LUFS）作为统一目标；原唱和伴奏分别执行 EBU R128/loudnorm 两遍归一。"
            "为避免削波，True Peak 使用独立安全上限；不主动压缩音乐动态范围。"
        )
        note.setWordWrap(True)
        g.addWidget(self.loudness_cb, 0, 0, 1, 4)
        g.addWidget(QLabel("固定参考曲目"), 1, 0); g.addWidget(self.reference_edit, 1, 1, 1, 3); g.addWidget(ref_btn, 1, 4)
        g.addWidget(QLabel("True Peak 上限"), 2, 0); g.addWidget(self.tp_spin, 2, 1); g.addWidget(analyze_btn, 2, 3)
        g.addWidget(self.ref_status, 3, 1, 1, 4)
        g.addWidget(note, 4, 0, 1, 5)
        ref_btn.clicked.connect(self._choose_reference)
        analyze_btn.clicked.connect(self._analyze_reference)
        self.loudness_cb.toggled.connect(self._update_loudness_ui)
        return w

    def _build_video_tab(self) -> QWidget:
        w = QWidget(); g = QGridLayout(w)
        self.reencode_cb = QCheckBox("启用视频重编码（默认关闭）")
        self.video_codec_combo = QComboBox(); self.video_codec_combo.setEditable(True); self.video_codec_combo.addItems(["libx264", "libx265", "h264_nvenc", "hevc_nvenc"])
        self.video_preset_edit = QLineEdit("medium")
        self.video_quality_spin = QSpinBox(); self.video_quality_spin.setRange(0, 51); self.video_quality_spin.setValue(18)
        self.video_bitrate_edit = QLineEdit(); self.video_bitrate_edit.setPlaceholderText("可留空，例如 8M")
        self.video_pixfmt_edit = QLineEdit("yuv420p")
        self.video_custom_edit = QLineEdit(); self.video_custom_edit.setPlaceholderText("可选，例如 -profile:v high -level 4.1")
        note = QLabel("关闭重编码时使用 -c:v copy，速度最快且画质不变。开启后：x264/x265 使用 CRF；NVENC 使用 CQ。")
        note.setWordWrap(True)
        g.addWidget(self.reencode_cb, 0, 0, 1, 4)
        pairs = [
            ("视频编码器", self.video_codec_combo, 1), ("Preset", self.video_preset_edit, 2),
            ("CRF/CQ", self.video_quality_spin, 3), ("目标/限制码率", self.video_bitrate_edit, 4),
            ("像素格式", self.video_pixfmt_edit, 5), ("额外 FFmpeg 参数", self.video_custom_edit, 6),
        ]
        for label, widget, row in pairs:
            g.addWidget(QLabel(label), row, 0); g.addWidget(widget, row, 1, 1, 3)
        g.addWidget(note, 7, 0, 1, 4)
        self.reencode_cb.toggled.connect(self._update_video_ui)
        return w

    def _load_settings(self) -> None:
        home = Path.home()
        self.output_edit.setText(self.settings.value("output", str(home / "KTV_Output")))
        self.model_dir_edit.setText(self.settings.value("model_dir", str(home / ".uvr5_models")))
        self.model_combo.setCurrentText(self.settings.value("model", DEFAULT_MODELS[0]))
        self.separator_edit.setText(self.settings.value("separator", "audio-separator"))
        self.ffmpeg_edit.setText(self.settings.value("ffmpeg", "ffmpeg"))
        self.reference_edit.setText(self.settings.value("reference", str(DEFAULT_REFERENCE)))
        self.recursive_cb.setChecked(self.settings.value("recursive", True, bool))
        self.mirror_cb.setChecked(self.settings.value("mirror", True, bool))
        self.loudness_cb.setChecked(self.settings.value("loudness", True, bool))
        self.tp_spin.setValue(float(self.settings.value("tp", -1.0)))
        self.detailed_log_cb.setChecked(self.settings.value("detailed_log", False, bool))
        self._set_combo_data(self.container_combo, self.settings.value("container", "mp4"))
        self._set_combo_data(self.mode_combo, self.settings.value("package_mode", "dual_track"))
        self._set_combo_data(self.track_order_combo, self.settings.value("track_order", "original_first"))
        self._set_combo_data(self.stereo_combo, self.settings.value("stereo_order", "acc_left"))
        self.bitrate_combo.setCurrentText(self.settings.value("audio_bitrate", "256k"))
        self.rate_spin.setValue(int(self.settings.value("sample_rate", 48000)))
        self._set_combo_data(self.naming_combo, self.settings.value("naming_mode", "preserve"))
        self._set_combo_data(self.conflict_combo, self.settings.value("conflict", "overwrite"))
        self.autocast_cb.setChecked(self.settings.value("autocast", True, bool))
        self.keep_stem_cb.setChecked(self.settings.value("keep_stem", False, bool))
        self.reencode_cb.setChecked(self.settings.value("reencode", False, bool))
        self.video_codec_combo.setCurrentText(self.settings.value("video_codec", "libx264"))
        self.video_preset_edit.setText(self.settings.value("video_preset", "medium"))
        self.video_quality_spin.setValue(int(self.settings.value("video_quality", 18)))
        self.video_bitrate_edit.setText(self.settings.value("video_bitrate", ""))
        self.video_pixfmt_edit.setText(self.settings.value("video_pixfmt", "yuv420p"))
        self.video_custom_edit.setText(self.settings.value("video_custom", ""))

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: object) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def _save_settings(self) -> None:
        for key, val in {
            "output": self.output_edit.text(), "model_dir": self.model_dir_edit.text(),
            "model": self.model_combo.currentText(), "separator": self.separator_edit.text(),
            "ffmpeg": self.ffmpeg_edit.text(), "reference": self.reference_edit.text(),
            "recursive": self.recursive_cb.isChecked(), "mirror": self.mirror_cb.isChecked(),
            "loudness": self.loudness_cb.isChecked(), "tp": self.tp_spin.value(),
            "detailed_log": self.detailed_log_cb.isChecked(),
            "container": self.container_combo.currentData(), "package_mode": self.mode_combo.currentData(),
            "track_order": self.track_order_combo.currentData(), "stereo_order": self.stereo_combo.currentData(),
            "audio_bitrate": self.bitrate_combo.currentText(), "sample_rate": self.rate_spin.value(),
            "naming_mode": self.naming_combo.currentData(), "conflict": self.conflict_combo.currentData(),
            "autocast": self.autocast_cb.isChecked(), "keep_stem": self.keep_stem_cb.isChecked(),
            "reencode": self.reencode_cb.isChecked(), "video_codec": self.video_codec_combo.currentText(),
            "video_preset": self.video_preset_edit.text(), "video_quality": self.video_quality_spin.value(),
            "video_bitrate": self.video_bitrate_edit.text(), "video_pixfmt": self.video_pixfmt_edit.text(),
            "video_custom": self.video_custom_edit.text(),
        }.items():
            self.settings.setValue(key, val)

    @Slot()
    def _update_mode_ui(self) -> None:
        dual = self.mode_combo.currentData() == "dual_track"
        self.track_order_combo.setEnabled(dual)
        self.stereo_combo.setEnabled(not dual)

    @Slot()
    def _update_video_ui(self) -> None:
        enabled = self.reencode_cb.isChecked()
        for w in (self.video_codec_combo, self.video_preset_edit, self.video_quality_spin, self.video_bitrate_edit, self.video_pixfmt_edit, self.video_custom_edit):
            w.setEnabled(enabled)

    @Slot()
    def _update_loudness_ui(self) -> None:
        enabled = self.loudness_cb.isChecked()
        self.reference_edit.setEnabled(enabled)
        self.tp_spin.setEnabled(enabled)

    def _add_job(self, path: Path, root: Path | None) -> None:
        resolved = path.resolve()
        if any(j.source.resolve() == resolved for j in self.jobs):
            return
        relative_parent = Path()
        if root and self.mirror_cb.isChecked():
            try:
                relative_parent = path.parent.resolve().relative_to(root.resolve())
            except Exception:
                pass
        self.jobs.append(JobItem(path, relative_parent))
        row = self.table.rowCount(); self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(path)))
        self.table.setItem(row, 1, QTableWidgetItem("")); self.table.setItem(row, 2, QTableWidgetItem("等待"))
        bar = QProgressBar(); bar.setRange(0, 100); bar.setValue(0); self.table.setCellWidget(row, 3, bar)
        self.table.setItem(row, 4, QTableWidgetItem(""))

    @Slot()
    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择 MV", self.input_edit.text() or str(Path.home()), "Video (*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.ts *.m2ts *.mpg *.mpeg *.vob *.webm *.m4v *.mts);;All files (*)")
        for f in files:
            p = Path(f); self.input_edit.setText(str(p.parent)); self._add_job(p, None)

    @Slot()
    def _add_directory(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择 MV 目录", self.input_edit.text() or str(Path.home()))
        if not folder: return
        root = Path(folder); self.input_edit.setText(folder)
        videos = discover_videos(root, self.recursive_cb.isChecked())
        for p in videos: self._add_job(p, root)
        self._log(f"队列 | 扫描 {root}，找到 {len(videos)} 个视频")

    @Slot()
    def _choose_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "输出目录", self.output_edit.text() or str(Path.home()))
        if folder: self.output_edit.setText(folder)

    @Slot()
    def _choose_reference(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "选择固定响度参考曲目", self.reference_edit.text() or str(Path.home()), "Audio/Video (*.wav *.flac *.mp3 *.m4a *.aac *.mp4 *.mkv *.mov);;All files (*)")
        if f: self.reference_edit.setText(f)

    @Slot()
    def _analyze_reference(self) -> None:
        path = Path(self.reference_edit.text()).expanduser()
        if not path.exists():
            QMessageBox.warning(self, "参考曲目", "参考曲目不存在。")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            opts = self._make_options()
            media = MediaTools(opts.ffmpeg_path, opts.ffprobe_path)
            engine = LoudnessEngine(media, opts.true_peak_db)
            ref = engine.analyze_reference(path, Event())
            s = ref.stats
            self.ref_status.setText(f"参考：{s.integrated:.2f} LUFS | True Peak {s.true_peak:.2f} dBTP | LRA {s.lra:.2f} LU")
        except Exception as exc:
            QMessageBox.critical(self, "参考响度分析失败", str(exc))
        finally:
            QApplication.restoreOverrideCursor()

    @Slot()
    def _clear_queue(self) -> None:
        if self.thread and self.thread.isRunning(): return
        self.jobs.clear(); self.table.setRowCount(0); self.overall_progress.setValue(0); self.overall_label.setText("等待任务")

    def _make_options(self) -> AppOptions:
        ffmpeg = self.ffmpeg_edit.text().strip() or "ffmpeg"
        ffprobe = "ffprobe"
        fp = Path(ffmpeg)
        if fp.exists():
            sib = fp.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
            if sib.exists(): ffprobe = str(sib)
        ref_text = self.reference_edit.text().strip()
        return AppOptions(
            output_dir=Path(self.output_edit.text()).expanduser(),
            model_filename=self.model_combo.currentText().strip(),
            model_dir=Path(self.model_dir_edit.text()).expanduser(),
            ffmpeg_path=ffmpeg, ffprobe_path=ffprobe,
            separator_path=self.separator_edit.text().strip() or "audio-separator",
            container=self.container_combo.currentData(), package_mode=self.mode_combo.currentData(),
            track_order=self.track_order_combo.currentData(), stereo_order=self.stereo_combo.currentData(),
            audio_bitrate=self.bitrate_combo.currentText(), sample_rate=self.rate_spin.value(),
            loudness_enabled=self.loudness_cb.isChecked(),
            loudness_reference=Path(ref_text).expanduser() if ref_text else None,
            true_peak_db=self.tp_spin.value(), naming_mode=self.naming_combo.currentData(),
            recursive=self.recursive_cb.isChecked(), mirror_tree=self.mirror_cb.isChecked(),
            keep_instrumental=self.keep_stem_cb.isChecked(), use_autocast=self.autocast_cb.isChecked(),
            conflict_policy=self.conflict_combo.currentData(),
            video_mode="reencode" if self.reencode_cb.isChecked() else "copy",
            video_codec=self.video_codec_combo.currentText().strip(), video_preset=self.video_preset_edit.text().strip(),
            video_quality=self.video_quality_spin.value(), video_bitrate=self.video_bitrate_edit.text().strip(),
            video_pix_fmt=self.video_pixfmt_edit.text().strip(), video_custom_args=self.video_custom_edit.text().strip(),
            detailed_log=self.detailed_log_cb.isChecked(),
        )

    @Slot()
    def _check_environment(self) -> None:
        opts = self._make_options(); media = MediaTools(opts.ffmpeg_path, opts.ffprobe_path)
        ok, ffmsg = media.verify()
        sep = UVRSeparator(opts.separator_path, opts.model_filename, opts.model_dir, opts.use_autocast, opts.detailed_log)
        sep_ok, sep_msg, notes = sep.environment_info()
        manager = ModelManager(sep.executable, opts.model_dir, opts.model_filename)
        model_ok, model_msg = manager.validate_model()
        ref_msg = "关闭"
        if opts.loudness_enabled:
            ref_msg = "存在" if opts.loudness_reference and opts.loudness_reference.exists() else "未找到"
        note_text = "\n".join(f"• {x}" for x in notes) or "• 未发现针对当前模型的明显问题。"
        text = (
            f"FFmpeg: {'OK' if ok else '失败'}\n{ffmsg}\n\n"
            f"audio-separator: {'OK' if sep_ok else '失败'}\n"
            f"模型缓存: {'OK' if model_ok else '需要准备/修复'} — {model_msg}\n"
            f"响度参考: {ref_msg}\n"
            f"视频模式: {'重编码 '+opts.video_codec if opts.video_mode == 'reencode' else 'copy（不重编码）'}\n\n"
            f"诊断：\n{note_text}\n\n"
            f"env_info 末尾：\n{sep_msg[-1600:]}"
        )
        QMessageBox.information(self, "环境检测", text)

    @Slot()
    def _start(self) -> None:
        if not self.jobs:
            QMessageBox.warning(self, "没有任务", "请先添加 MV 文件或目录。")
            return
        if not self.output_edit.text().strip():
            QMessageBox.warning(self, "输出目录", "请设置输出目录。")
            return
        opts = self._make_options()
        if opts.loudness_enabled and (opts.loudness_reference is None or not opts.loudness_reference.exists()):
            QMessageBox.warning(self, "响度参考", "已启用响度均衡，但参考曲目不存在。请选择参考曲目或使用项目内置参考。")
            return
        opts.output_dir.mkdir(parents=True, exist_ok=True); self._save_settings()
        for row in range(self.table.rowCount()):
            self.table.item(row, 2).setText("等待"); self.table.item(row, 4).setText("")
            bar = self.table.cellWidget(row, 3)
            if isinstance(bar, QProgressBar): bar.setValue(0); bar.setFormat("%p%")
        self.overall_progress.setValue(0); self.start_btn.setEnabled(False); self.cancel_btn.setEnabled(True)
        self.thread = QThread(self); self.worker = BatchWorker(self.jobs, opts); self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.job_started.connect(self._job_started); self.worker.job_progress.connect(self._job_progress)
        self.worker.job_finished.connect(self._job_finished); self.worker.log.connect(self._log)
        self.worker.all_finished.connect(self._all_finished); self.worker.all_finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater); self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    @Slot()
    def _cancel(self) -> None:
        if self.worker: self.worker.cancel()
        self.cancel_btn.setEnabled(False)

    @Slot(int)
    def _job_started(self, idx: int) -> None:
        self.table.item(idx, 2).setText("处理中"); self.overall_label.setText(f"处理 {idx+1}/{len(self.jobs)}")

    @Slot(int, int, str)
    def _job_progress(self, idx: int, percent: int, stage: str) -> None:
        bar = self.table.cellWidget(idx, 3)
        if isinstance(bar, QProgressBar): bar.setValue(percent); bar.setFormat(f"{percent}% {stage}")
        total = ((idx + percent / 100.0) / max(1, len(self.jobs))) * 100
        self.overall_progress.setValue(int(total)); self.overall_label.setText(f"{idx+1}/{len(self.jobs)} · {stage}")

    @Slot(int, str, str, str)
    def _job_finished(self, idx: int, status: str, output: str, error: str) -> None:
        self.table.item(idx, 1).setText(output); self.table.item(idx, 2).setText(status); self.table.item(idx, 4).setText(error)
        bar = self.table.cellWidget(idx, 3)
        if isinstance(bar, QProgressBar) and status in {"完成", "已跳过"}: bar.setValue(100); bar.setFormat(status)

    @Slot(bool)
    def _all_finished(self, cancelled: bool) -> None:
        self.start_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        done = sum(self.table.item(r, 2).text() == "完成" for r in range(self.table.rowCount()))
        failed = sum(self.table.item(r, 2).text() == "失败" for r in range(self.table.rowCount()))
        skipped = sum(self.table.item(r, 2).text() == "已跳过" for r in range(self.table.rowCount()))
        if not cancelled: self.overall_progress.setValue(100)
        self.overall_label.setText(("已取消" if cancelled else "结束") + f"：完成 {done} / 失败 {failed} / 跳过 {skipped}")
        self.worker = None; self.thread = None

    @Slot(str)
    def _log(self, text: str) -> None:
        if not text: return
        self.log_edit.appendPlainText(text)
        self.log_edit.verticalScrollBar().setValue(self.log_edit.verticalScrollBar().maximum())

    @Slot()
    def _open_output(self) -> None:
        path = Path(self.output_edit.text()).expanduser(); path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt": os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin": subprocess.Popen(["open", str(path)])
        else: subprocess.Popen(["xdg-open", str(path)])

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.thread and self.thread.isRunning():
            ans = QMessageBox.question(self, "任务运行中", "确定退出并取消当前任务吗？")
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore(); return
            if self.worker: self.worker.cancel()
        self._save_settings(); event.accept()
