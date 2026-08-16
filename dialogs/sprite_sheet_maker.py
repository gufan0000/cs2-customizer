# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标高级导入 / 批量处理（KI-2 重写，KI-6 降级为"高级"入口）。

原来这个对话框叫「Sprite Sheet 制作工具」，只认 PNG 图片序列，而且
**生成完就把文件丢给用户自己处置**：QFileDialog 让你随便选个保存位置，
之后还得自己搬进 %LOCALAPPDATA% 的资源目录、自己改名成 `3.png`、
自己确认 JSON 对得上。

KI-2 把打包逻辑整体挪到 `core.kill_icon_import`，这里只管 UI。
KI-6 把"日常导入"整个搬到了设置页那块素材清单板上（拖到哪一格就进哪一格），
这个对话框从主路径降级成**高级入口**，专管四件页面上做不了的事：

    抠背景色 · 裁透明边 · 手填图集行列 · 按 1~5 批量导入

素材分析（要不要抠背景/裁边）与导入都跑在后台线程上：600 帧 1024px 的素材
做完整串是秒级的，跑在 UI 线程上就是"点完按钮整个界面卡死"。
"""

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QSpinBox, QVBoxLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
import os

from core.kill_icon_import import (
    DEFAULT_CHROMA_TOLERANCE, KillIconImportError, convert_to_style, guess_grid,
    parse_level_name, probe_source
)
from core.utils.logger import get_logger
from resource_manager import ResourceManager
from theme_manager import get_theme_manager
from widgets.kill_icon_import_task import KillIconImportTask

#: 击杀等级的中文说法。和设置页保持一致，别各写各的。
LEVEL_LABELS = {1: "1 杀", 2: "2 杀", 3: "3 杀", 4: "4 杀", 5: "5 杀（ACE）"}


class SpriteSheetMaker(QDialog):
    """把一段素材做成击杀图标，并直接装进风格库。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger()
        self.source_path = ""
        self.probe = None

        self.setWindowTitle("击杀图标高级导入")
        self.setMinimumSize(660, 640)

        self.theme_manager = get_theme_manager()
        self.setStyleSheet(self.theme_manager.get_stylesheet())

        self._task = KillIconImportTask(self)
        self._task.progress.connect(self._on_progress)
        self._task.finished.connect(self._on_task_finished)
        self._task.failed.connect(self._on_task_failed)
        self._task.cancelled.connect(lambda: self._set_busy(False))
        self._pending = None

        self._init_ui()
        self._refresh_styles()

    # ------------------------------------------------------------------ UI

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("击杀图标高级导入")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        info_frame = QFrame()
        info_frame.setFrameShape(QFrame.Shape.StyledPanel)
        info_layout = QVBoxLayout(info_frame)
        info_text = QLabel(
            "日常导入直接把素材拖到设置页的等级格子上就行；这里管的是四件"
            "页面上做不了的事：抠背景色、裁透明边、手填图集行列、按 1~5 批量导入。\n\n"
            "支持 GIF / WebP 动图 / APNG / AVIF / PNG / JPG / BMP，"
            "或者一个装着帧序列的文件夹、一份图集配置（含 Aseprite 导出）。"
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        layout.addWidget(info_frame)

        # ---------------- 素材来源
        source_frame = QFrame()
        source_layout = QHBoxLayout(source_frame)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.addWidget(QLabel("素材:"))

        self.folder_entry = QLineEdit()
        self.folder_entry.setReadOnly(True)
        self.folder_entry.setMinimumWidth(260)
        source_layout.addWidget(self.folder_entry, 1)

        file_btn = QPushButton("选择文件...")
        file_btn.setObjectName("actionButton")
        file_btn.setMinimumWidth(96)
        file_btn.clicked.connect(self._select_file)
        source_layout.addWidget(file_btn)

        browse_btn = QPushButton("选择文件夹...")
        browse_btn.setObjectName("secondaryButton")
        browse_btn.setMinimumWidth(110)
        browse_btn.clicked.connect(self._select_folder)
        source_layout.addWidget(browse_btn)

        layout.addWidget(source_frame)

        # ---------------- 目标
        target_frame = QFrame()
        target_layout = QHBoxLayout(target_frame)
        target_layout.setContentsMargins(0, 0, 0, 0)
        target_layout.setSpacing(8)

        target_layout.addWidget(QLabel("目标风格:"))
        self.style_combo = QComboBox()
        self.style_combo.setEditable(True)
        self.style_combo.setMinimumWidth(160)
        self.style_combo.setToolTip("可以直接输入一个新名字来新建风格")
        target_layout.addWidget(self.style_combo, 1)

        target_layout.addWidget(QLabel("击杀等级:"))
        self.level_combo = QComboBox()
        for level, label in LEVEL_LABELS.items():
            self.level_combo.addItem(label, level)
        target_layout.addWidget(self.level_combo)

        self.headshot_check = QCheckBox("爆头专用")
        self.headshot_check.setToolTip(
            "勾上后存成这个等级的爆头覆写；爆头击杀时优先用它，普通击杀仍用原来的图标。"
        )
        target_layout.addWidget(self.headshot_check)

        layout.addWidget(target_frame)

        # ---------------- 展示时长
        duration_frame = QFrame()
        duration_layout = QHBoxLayout(duration_frame)
        duration_layout.setContentsMargins(0, 0, 0, 0)
        duration_layout.addWidget(QLabel("展示时长:"))

        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.3, 8.0)
        self.duration_spin.setSingleStep(0.1)
        self.duration_spin.setDecimals(1)
        self.duration_spin.setSuffix(" 秒")
        self.duration_spin.setValue(1.0)
        duration_layout.addWidget(self.duration_spin)

        self.keep_source_rate = QCheckBox("沿用素材自带的节奏")
        self.keep_source_rate.setChecked(True)
        self.keep_source_rate.setToolTip(
            "动图里每帧的时长会被读出来换算成帧率；取消勾选才用上面的展示时长。\n"
            "静态图没有节奏可沿用，这里量的是「定格多久」。"
        )
        self.keep_source_rate.stateChanged.connect(self._sync_duration_enabled)
        duration_layout.addWidget(self.keep_source_rate)
        duration_layout.addStretch()

        layout.addWidget(duration_frame)
        self._sync_duration_enabled()

        # ---------------- 自动修正
        fix_frame = QFrame()
        fix_frame.setFrameShape(QFrame.Shape.StyledPanel)
        fix_layout = QVBoxLayout(fix_frame)
        fix_layout.setSpacing(6)
        fix_layout.addWidget(QLabel("自动修正:"))

        self.trim_check = QCheckBox("裁掉四周的全透明边（按所有帧的并集，动画不会抖）")
        self.trim_check.setToolTip(
            "很多素材四周留着大片空白，图标在屏幕上会显得又小又偏。"
        )
        fix_layout.addWidget(self.trim_check)

        chroma_row = QHBoxLayout()
        chroma_row.setSpacing(8)
        self.chroma_check = QCheckBox("抠掉背景色")
        self.chroma_check.setToolTip(
            "从视频转出来的素材大多不透明，叠在游戏上是一个方块。\n"
            "老 pygame 版靠纯黑抠图，为那一版自制的黑底素材迁过来也要用这个。"
        )
        chroma_row.addWidget(self.chroma_check)
        chroma_row.addWidget(QLabel("容差:"))
        self.chroma_spin = QSpinBox()
        self.chroma_spin.setRange(0, 128)
        self.chroma_spin.setValue(DEFAULT_CHROMA_TOLERANCE)
        chroma_row.addWidget(self.chroma_spin)
        self.chroma_label = QLabel("（未检测）")
        self.chroma_label.setObjectName("hintLabel")
        chroma_row.addWidget(self.chroma_label, 1)
        fix_layout.addLayout(chroma_row)

        grid_row = QHBoxLayout()
        grid_row.setSpacing(8)
        self.grid_check = QCheckBox("这张图是图集，按行列切:")
        self.grid_check.setToolTip("没有配套 JSON 的图集才需要手填。")
        grid_row.addWidget(self.grid_check)
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 64)
        self.cols_spin.setPrefix("列 ")
        grid_row.addWidget(self.cols_spin)
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 64)
        self.rows_spin.setPrefix("行 ")
        grid_row.addWidget(self.rows_spin)
        grid_row.addStretch()
        fix_layout.addLayout(grid_row)

        layout.addWidget(fix_frame)

        # ---------------- 预览
        preview_frame = QFrame()
        preview_frame.setFrameShape(QFrame.Shape.StyledPanel)
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.addWidget(QLabel("素材信息:"))

        self.preview_label = QLabel("请先选择素材")
        self.preview_label.setMinimumHeight(96)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.preview_label.setWordWrap(True)
        self.preview_label.setObjectName("previewLabel")
        preview_layout.addWidget(self.preview_label)

        layout.addWidget(preview_frame, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # ---------------- 按钮
        button_frame = QFrame()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 0, 0, 0)

        self.generate_btn = QPushButton("导入到风格库")
        self.generate_btn.setFixedHeight(36)
        self.generate_btn.setMinimumWidth(150)
        self.generate_btn.setObjectName("primaryButton")
        self.generate_btn.clicked.connect(self._import_to_library)
        button_layout.addWidget(self.generate_btn)

        batch_btn = QPushButton("批量处理")
        batch_btn.setObjectName("actionButton")
        batch_btn.setFixedHeight(36)
        batch_btn.setMinimumWidth(120)
        batch_btn.setToolTip(
            "选一个根目录，里面按 1~5 命名的子文件夹或文件会分别导入对应的击杀等级。\n"
            "也认 ace / kill1 / 三杀 / 4hs 这类写法。"
        )
        batch_btn.clicked.connect(self._batch_process)
        button_layout.addWidget(batch_btn)

        export_btn = QPushButton("另存为图集...")
        export_btn.setObjectName("secondaryButton")
        export_btn.setFixedHeight(36)
        export_btn.setMinimumWidth(130)
        export_btn.clicked.connect(self._export_to_file)
        button_layout.addWidget(export_btn)

        button_layout.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondaryButton")
        close_btn.setFixedHeight(36)
        close_btn.setMinimumWidth(90)
        close_btn.clicked.connect(self.reject)
        button_layout.addWidget(close_btn)

        layout.addWidget(button_frame)

    def _sync_duration_enabled(self):
        self.duration_spin.setEnabled(not self.keep_source_rate.isChecked())

    def _refresh_styles(self):
        self.style_combo.clear()
        styles = ResourceManager.list_kill_icon_styles()
        for style in styles:
            self.style_combo.addItem(style)
        if not styles:
            self.style_combo.setEditText("默认")

    # ------------------------------------------------------------- 选素材

    def _select_file(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, "选择素材文件", "",
            "图片与动图 (*.gif *.webp *.png *.apng *.avif *.jpg *.jpeg *.bmp);;"
            "图集配置 (*.json);;所有文件 (*.*)",
        )
        if path:
            self._set_source(path)

    def _select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择包含帧序列的文件夹")
        if folder:
            self._set_source(folder)

    def _set_source(self, path):
        self.source_path = path
        self.folder_entry.setText(path)
        try:
            self.probe = probe_source(path, grid=self._grid_argument())
        except KillIconImportError as exc:
            self.probe = None
            self.preview_label.setText(f"读不了这个素材：\n{exc}")
            return
        except Exception as exc:  # 防御：PIL 也可能抛别的
            self.probe = None
            self.preview_label.setText(f"读不了这个素材：\n{exc}")
            self.logger.error(f"探测击杀图标素材失败: {exc}")
            return

        self._render_probe()
        self.duration_spin.setValue(max(0.3, min(8.0, self.probe.duration)))
        self._suggest_grid(path)
        self._analyze_in_background(path)

    def _render_probe(self):
        if self.probe is None:
            return
        lines = [
            f"类型: {self._kind_label(self.probe.kind)}",
            f"帧数: {self.probe.frame_count}",
            f"画格: {self.probe.frame_width} x {self.probe.frame_height}",
            f"素材节奏: {self.probe.fps} FPS（约 {self.probe.duration:.2f} 秒）",
        ]
        if self.probe.hold_seconds:
            lines.append(f"定格: {self.probe.hold_seconds:.1f} 秒（单帧素材）")
        if self.probe.warnings:
            lines.append("")
            lines.extend(f"⚠ {w}" for w in self.probe.warnings)
        self.preview_label.setText("\n".join(lines))

    def _suggest_grid(self, path):
        """没有元数据的图集，能一眼看出来的行列就先填上。"""
        if self.probe is None or self.probe.kind == "spritesheet":
            self.grid_check.setEnabled(self.probe is not None
                                       and self.probe.kind == "animation")
            return
        if self.probe.frame_count != 1:
            self.grid_check.setEnabled(False)
            return
        self.grid_check.setEnabled(True)
        guessed = guess_grid(self.probe.frame_width, self.probe.frame_height)
        if guessed:
            self.cols_spin.setValue(guessed[0])
            self.rows_spin.setValue(guessed[1])

    def _analyze_in_background(self, path):
        """要不要抠背景 / 裁边——这一步要读像素，别放在 UI 线程上。"""
        grid = self._grid_argument()

        def _work(_progress, _cancel):
            return {"analysis": probe_source(path, grid=grid, analyze=True)}

        self._pending = "analyze"
        self._set_busy(True, "正在分析素材…")
        if not self._task.start(_work, "分析素材"):
            self._set_busy(False)

    @staticmethod
    def _kind_label(kind):
        return {
            "animation": "动图",
            "sequence": "帧序列文件夹",
            "spritesheet": "现成图集",
        }.get(kind, kind)

    # ------------------------------------------------------------- 后台任务

    def _set_busy(self, busy, message=""):
        self.progress_bar.setVisible(bool(busy))
        if busy:
            self.progress_bar.setRange(0, 0)
            if message:
                self.progress_bar.setFormat(message)
        self.generate_btn.setEnabled(not busy)

    def _on_progress(self, done, total, stage):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(done)
        self.progress_bar.setFormat(f"{stage} %p%")

    def _on_task_finished(self, result):
        self._set_busy(False)
        pending, self._pending = self._pending, None

        if pending == "analyze" and isinstance(result, dict) and "analysis" in result:
            self.probe = result["analysis"]
            self._render_probe()
            if self.probe.suggested_key_color:
                color = self.probe.suggested_key_color
                self.chroma_label.setText(f"检测到背景 RGB{color}")
                self.chroma_check.setChecked(True)
            elif self.probe.opaque_background:
                self.chroma_label.setText("背景不透明，但四角颜色不一致，需要自己判断")
            else:
                self.chroma_label.setText("（背景已经是透明的）")
            return

        if pending == "import":
            self._refresh_styles()
            self.style_combo.setEditText(result.get("style", ""))
            self._show_result(result)
            return

        if pending == "batch":
            self._refresh_styles()
            QMessageBox.information(self, "批量处理完成", self._batch_summary(result))

    def _on_task_failed(self, message):
        self._set_busy(False)
        pending, self._pending = self._pending, None
        if pending == "analyze":
            self.chroma_label.setText("（分析失败，可以手动勾选）")
            return
        QMessageBox.warning(self, "导入失败", message)

    # ------------------------------------------------------------- 导入

    def _target_style(self):
        return self.style_combo.currentText().strip()

    def _duration_argument(self):
        return None if self.keep_source_rate.isChecked() else self.duration_spin.value()

    def _hold_argument(self):
        """单帧素材：滑条量的是定格时长，不是播放速度。"""
        if self.probe is not None and self.probe.frame_count == 1 \
                and not self.keep_source_rate.isChecked():
            return self.duration_spin.value()
        return None

    def _grid_argument(self):
        if not self.grid_check.isChecked():
            return None
        return (self.cols_spin.value(), self.rows_spin.value())

    def _chroma_argument(self):
        if not self.chroma_check.isChecked():
            return None
        if self.probe is not None and self.probe.suggested_key_color:
            return tuple(self.probe.suggested_key_color)
        return (0, 0, 0)

    def _fix_kwargs(self):
        return {
            "grid": self._grid_argument(),
            "trim": self.trim_check.isChecked(),
            "chroma_key": self._chroma_argument(),
            "chroma_tolerance": self.chroma_spin.value(),
        }

    def _import_to_library(self):
        if not self.source_path:
            QMessageBox.warning(self, "提示", "请先选择素材")
            return
        style = self._target_style()
        if not style:
            QMessageBox.warning(self, "提示", "请填一个风格名")
            return

        source = self.source_path
        kills = self.level_combo.currentData()
        variant = "hs" if self.headshot_check.isChecked() else ""
        duration = self._duration_argument()
        hold = self._hold_argument()
        fixes = self._fix_kwargs()

        def _work(progress, cancel):
            return convert_to_style(
                source, style, kills,
                duration=None if hold is not None else duration,
                hold_seconds=hold, variant=variant,
                progress=progress, cancel=cancel, **fixes)

        self._pending = "import"
        self._set_busy(True, "正在导入…")
        if not self._task.start(_work, "导入素材"):
            self._set_busy(False)

    def _show_result(self, result):
        if not isinstance(result, dict):
            return
        message = (
            f"已导入到「{result['style']}」的 {LEVEL_LABELS.get(result['kills'], result['kills'])}"
            f"{'（爆头专用）' if result['variant'] else ''}\n\n"
        )
        if result.get("frames") == 1 and result.get("hold_seconds"):
            message += f"1 帧，定格 {result['hold_seconds']:.1f} 秒"
        else:
            message += (f"{result['frames']} 帧 @ {result['fps']} FPS"
                        f"（约 {result['frames'] / max(1, result['fps']):.2f} 秒）")
        if result.get("warnings"):
            message += "\n\n" + "\n".join(f"⚠ {w}" for w in result["warnings"])
        QMessageBox.information(self, "导入成功", message)
        self.logger.info(f"导入击杀图标成功: {result['sprite_path']}")

    def _export_to_file(self):
        """次选出口：只出文件，不进库。"""
        if not self.source_path:
            QMessageBox.warning(self, "提示", "请先选择素材")
            return
        save_path, _filter = QFileDialog.getSaveFileName(
            self, "另存为图集", "spritesheet.png", "PNG文件 (*.png)"
        )
        if not save_path:
            return
        json_path = os.path.splitext(save_path)[0] + ".json"
        try:
            result = convert_to_style(
                self.source_path,
                self._target_style() or "导出",
                self.level_combo.currentData(),
                duration=self._duration_argument(),
                hold_seconds=self._hold_argument(),
                output_paths=(save_path, json_path),
                **self._fix_kwargs(),
            )
        except KillIconImportError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return

        QMessageBox.information(
            self, "导出成功",
            f"图集: {os.path.basename(result['sprite_path'])}\n"
            f"配置: {os.path.basename(result['json_path'])}\n"
            f"{result['frames']} 帧 @ {result['fps']} FPS",
        )

    # ------------------------------------------------------------- 批量

    def _batch_process(self):
        style = self._target_style()
        if not style:
            QMessageBox.warning(self, "提示", "请先填一个目标风格名")
            return

        root_folder = QFileDialog.getExistingDirectory(
            self, "选择根目录（里面按 1~5 命名的文件或文件夹会分别导入）")
        if not root_folder:
            return

        duration = self._duration_argument()
        fixes = self._fix_kwargs()
        fixes.pop("grid", None)          # 批量时每个条目的图集行列各不相同，不套用

        def _work(progress, cancel):
            succeeded, failed, skipped = [], [], []
            entries = sorted(os.listdir(root_folder))
            for index, entry in enumerate(entries):
                path = os.path.join(root_folder, entry)
                parsed = parse_level_name(entry)
                if parsed is None:
                    skipped.append(entry)
                    continue
                kills, variant = parsed
                try:
                    convert_to_style(path, style, kills, variant=variant,
                                     duration=duration, cancel=cancel, **fixes)
                    succeeded.append(f"{entry} → {kills} 杀{'（爆头）' if variant else ''}")
                except KillIconImportError as exc:
                    failed.append(f"{entry}（{exc}）")
                progress(index + 1, len(entries), "批量导入")
            return {"succeeded": succeeded, "failed": failed, "skipped": skipped}

        self._pending = "batch"
        self._set_busy(True, "正在批量导入…")
        if not self._task.start(_work, "批量导入"):
            self._set_busy(False)

    @staticmethod
    def _batch_summary(result):
        if not isinstance(result, dict):
            return "没有处理任何条目"
        succeeded = result.get("succeeded", [])
        failed = result.get("failed", [])
        skipped = result.get("skipped", [])
        summary = [f"成功: {len(succeeded)} 项", f"失败: {len(failed)} 项"]
        if succeeded:
            summary.append("")
            summary.extend(succeeded[:8])
        if failed:
            summary.append("")
            summary.extend(failed[:5])
        if skipped:
            summary.append("")
            summary.append(
                f"跳过（认不出是几杀）: {', '.join(skipped[:8])}"
                f"\n可以改成 1~5、ace、kill1、三杀、4hs 这类名字。")
        return "\n".join(summary)
