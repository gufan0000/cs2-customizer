#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Resource import wizard page."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import config
from core.audio.audio_task_runner import submit_import_refresh_task
from core.resource_import_wizard import (
    apply_resource_import_plan,
    scan_resource_import_candidates,
)
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from resource_manager import ResourceManager
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard
from widgets.page_header import PageHeader


# v2.2.1: 未识别原因中文化——旧版直接把英文 reason 打给用户，无从下手
_REASON_TRANSLATIONS = {
    "source directory missing": "源目录不存在",
    "path does not include a supported resource category root": "路径里没有可识别的分类目录名（如 kill_sounds）",
    "path does not include a supported audio category root": "路径里没有可识别的分类目录名（如 kill_sounds）",
    "resource category not supported in current mode": "该分类不属于当前导入模式（试试切换 音频/视觉/全部）",
    "resolved target escapes resources root": "目标路径越界，已拦截",
    "resolved target escapes audio root": "目标路径越界，已拦截",
    "invalid plan item": "条目信息不完整",
}


def _translate_reason(reason: str) -> str:
    text = str(reason or "").strip()
    if text in _REASON_TRANSLATIONS:
        return _REASON_TRANSLATIONS[text]
    if text.startswith("unsupported file extension"):
        return "文件扩展名不被该分类支持"
    return text  # io_validation 等已是中文的原样保留


_STRUCTURE_GUIDE = (
    "\n[未识别文件怎么办]\n"
    "方式一（推荐）：点上方“把未识别音频导入为新风格…”，选择类别和风格名即可自动改名落盘，无需整理目录。\n"
    "方式二：把素材整理成标准结构后重新扫描，例如：\n"
    "  你的目录/kill_sounds/我的风格/1.mp3 … 5.mp3      （击杀音效，1-5 对应连杀数）\n"
    "  你的目录/kill_voices/我的风格/1.mp3 … 5.mp3      （击杀语音）\n"
    "  你的目录/switch_weapons/weapon_ak47/我的风格/任意.mp3（切枪音效）\n"
    "  你的目录/death/风格名.mp3                        （被击杀音效，文件名即风格名）\n"
)


class AudioImportWizardPage(QWidget):
    """Import external resources into app resource directories."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("AudioImportWizardPage")
        self.audio_root = ResourceManager.get_app_data_path("resources/audio")
        self.resources_root = ResourceManager.get_app_data_path("resources")
        self._scan_report = None
        self._last_import_result = None
        self._init_ui()
        # 对标主流：把文件夹/音频文件直接拖进页面即可填入并扫描
        self.setAcceptDrops(True)

    # ---------------- 拖拽导入（对标修缮） ----------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        try:
            import os

            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if not path:
                    continue
                # 拖文件→取其所在目录；拖目录→直接用
                source_dir = path if os.path.isdir(path) else os.path.dirname(path)
                if source_dir and os.path.isdir(source_dir):
                    self.source_edit.setText(source_dir)
                    self.logger.info(f"拖拽导入目录: {source_dir}")
                    try:
                        from ui_toast import toast_info

                        toast_info("已填入拖入的目录，正在扫描…", 2400)
                    except Exception:
                        pass
                    self._scan_source()
                    event.acceptProposedAction()
                    return
            event.ignore()
        except Exception:
            self.logger.exception("处理拖拽失败")
            event.ignore()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        header = PageHeader(
            "资源导入向导",
            description="这里把外部素材扫描、预演和导入收在一起，适合先看识别结果，再决定要不要真正写入资源目录。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)

        card, card_layout = SettingsCard.make("当前状态")
        self.status_card = card

        self.status_badge_label = create_badge_label()
        card_layout.addWidget(self.status_badge_label)
        self.summary_label = QLabel("请先选择目录并扫描。")
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.hide()
        card_layout.addWidget(self.summary_label)
        layout.addWidget(card)

        controls_card, controls_layout = SettingsCard.make(
            "导入设置",
            "先选源目录，再决定导入模式和是否只做预演；保守导入默认不会覆盖已有文件。",
        )

        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        source_label = QLabel("源目录")
        source_label.setMinimumWidth(64)
        source_row.addWidget(source_label)

        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("请选择包含音频资源的根目录")
        self.source_edit.setMinimumHeight(34)
        source_row.addWidget(self.source_edit, 1)

        browse_btn = QPushButton("选择目录")
        browse_btn.setObjectName("secondaryButton")
        browse_btn.setMinimumHeight(34)
        browse_btn.clicked.connect(self._choose_source_dir)
        source_row.addWidget(browse_btn)
        controls_layout.addLayout(source_row)

        options_row = QHBoxLayout()
        options_row.setSpacing(8)
        options_row.addWidget(QLabel("导入模式"))

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("音频", "audio")
        self.mode_combo.addItem("视觉", "visual")
        self.mode_combo.addItem("全部", "all")
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.setMinimumHeight(34)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        options_row.addWidget(self.mode_combo, 0)

        self.dry_run_checkbox = QCheckBox("仅生成建议（不复制文件）")
        self.dry_run_checkbox.setChecked(False)
        options_row.addWidget(self.dry_run_checkbox)
        options_row.addStretch()
        controls_layout.addLayout(options_row)

        # UP-100: 原本是一个 QHBoxLayout 平铺 5 个按钮。五个按钮的 sizeHint 合计
        # 实测 967(x1.0) / 996(x1.1) / 1062(x1.25) px，而紧凑模式（860×640）的
        # 内容视口只有 854px —— 三个按钮的文案被打省略号（「一键导入（保守）」
        # 可用区 121px 需 128px 等，8/24 个主题×字号组合命中）。
        #
        # 改成两组：outer 是 QBoxLayout，横排时 [扫描/导入/归类][打开源/打开资源]
        # 两个子行并排，内外间距都是 8 —— 与改之前的单行**逐像素相同**；
        # 装不下时 outer 竖过来，变成两行。分组本身也讲得通：前三个是"干活"，
        # 后两个是"打开目录"。
        actions = QBoxLayout(QBoxLayout.LeftToRight)
        actions.setSpacing(8)
        self.actions_row = actions

        self.scan_btn = QPushButton("扫描目录")
        self.scan_btn.setObjectName("secondaryButton")
        self.import_btn = QPushButton("一键导入（保守）")
        self.import_btn.setObjectName("secondaryButton")
        # v2.2.1: 未识别文件不再是死胡同——手动归类为新风格
        self.classify_btn = QPushButton("把未识别音频导入为新风格…")
        self.classify_btn.setObjectName("secondaryButton")
        self.classify_btn.setEnabled(False)
        self.open_source_btn = QPushButton("打开源目录")
        self.open_source_btn.setObjectName("secondaryButton")
        self.open_resource_btn = QPushButton("打开资源目录")
        self.open_resource_btn.setObjectName("secondaryButton")
        for button in (self.scan_btn, self.import_btn, self.classify_btn, self.open_source_btn, self.open_resource_btn):
            button.setMinimumHeight(34)

        work_row = QHBoxLayout()
        work_row.setSpacing(8)
        work_row.setContentsMargins(0, 0, 0, 0)
        work_row.addWidget(self.scan_btn)
        work_row.addWidget(self.import_btn)
        work_row.addWidget(self.classify_btn)

        open_row = QHBoxLayout()
        open_row.setSpacing(8)
        open_row.setContentsMargins(0, 0, 0, 0)
        open_row.addWidget(self.open_source_btn)
        open_row.addWidget(self.open_resource_btn)

        actions.addLayout(work_row)
        actions.addLayout(open_row)
        actions.addStretch()
        controls_layout.addLayout(actions)
        layout.addWidget(controls_card)

        preview_card, preview_layout = SettingsCard.make(
            "扫描与导入结果",
            "这里会展示可识别、冲突和未识别条目，方便在真正导入前先确认目录结构是否符合预期。",
        )

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(400)
        preview_layout.addWidget(self.preview_text)

        layout.addWidget(preview_card)
        layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(116)
        self.action_bar.primary_btn.setMinimumWidth(148)
        root.addWidget(self.action_bar, 0)

        self.scan_btn.clicked.connect(self._scan_source)
        self.import_btn.clicked.connect(self._run_import)
        self.classify_btn.clicked.connect(self._classify_unrecognized)
        self.open_source_btn.clicked.connect(self._open_source_dir)
        self.open_resource_btn.clicked.connect(self._open_resource_dir)
        self.source_edit.textChanged.connect(lambda _text: self._sync_status_strip())
        self.dry_run_checkbox.toggled.connect(lambda _checked: self._sync_status_strip())
        self._sync_status_strip()

    # UP-100: 页宽阈值。实测锚点：紧凑模式页宽 **860**（必须竖排——那一档实测
    # 三个按钮的文案被打省略号）；完整模式页宽 **1000**（窗口 1200，CI 与页面指纹
    # 都用这一档）与 **1080**（窗口 1280）必须保持横排。取 960 = 两个锚点之间，
    # 下留 100px、上留 40px 余量。
    #
    # ⚠ 这里先写过一版"实测法"——量五个按钮的 `minimumSizeHint()` 合计（967/996/
    # 1062px 三档）跟可用宽比，想着自带字号缩放不变性。它**判过头了**：
    # 在 1200×800（可用约 946px）下就换成了竖排，而那一档排版审计明明是绿的。
    # 原因是 `minimumSizeHint` 里含 QSS 的 padding，padding 被压缩不等于文字被裁——
    # **判据必须对准缺陷本身**。页面指纹当场逮住了这次判过头（16 个控件挪位）。
    _ACTIONS_ROW_MIN_WIDTH = 960

    def _update_actions_layout(self):
        """窄到装不下时，把动作行的两组按钮从并排改成上下两行（UP-100）。"""
        row = getattr(self, "actions_row", None)
        if row is None:
            return
        direction = (QBoxLayout.TopToBottom
                     if self.width() < self._ACTIONS_ROW_MIN_WIDTH
                     else QBoxLayout.LeftToRight)
        if row.direction() != direction:
            row.setDirection(direction)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_actions_layout()

    def _compact_source_text(self, path: str) -> str:
        source_dir = str(path or "").strip()
        if not source_dir:
            return "未选择"
        name = os.path.basename(source_dir.rstrip("\\/")) or source_dir
        if len(name) > 12:
            name = name[:11] + "…"
        return name

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        source_dir = self.source_edit.text().strip()
        mode_text = self._mode_text()
        dry_run = bool(self.dry_run_checkbox.isChecked())
        self.action_bar.configure_secondary("扫描目录", self._scan_source, visible=True)

        if self._last_import_result:
            summary = self._last_import_result.get("summary", {}) or {}
            copied = int(summary.get("copied_count", 0) or 0)
            skipped = int(summary.get("skipped_conflicts_count", 0) or 0)
            failed = int(summary.get("failed_count", 0) or 0)
            self.action_bar.configure_primary("打开资源目录", self._open_resource_dir, visible=True)
            action_message = (
                f"当前模式：{mode_text} · 最近一次{'预演' if dry_run else '导入'}结果 "
                f"{copied}/{skipped}/{failed}，可直接打开资源目录继续核对。"
            )
        elif self._scan_report:
            summary = (self._scan_report or {}).get("summary", {}) or {}
            recognized = int(summary.get("recognized_count", 0) or 0)
            conflicts = int(summary.get("conflict_count", 0) or 0)
            primary_text = "生成建议" if dry_run else "一键导入（保守）"
            self.action_bar.configure_primary(primary_text, self._run_import, visible=True)
            action_message = (
                f"当前模式：{mode_text} · 已扫描 {recognized} 个可识别条目、{conflicts} 个冲突；"
                f"下一步可直接{'生成建议' if dry_run else '执行保守导入'}。"
            )
        elif source_dir:
            self.action_bar.configure_primary("打开源目录", self._open_source_dir, visible=True)
            action_message = (
                f"当前模式：{mode_text} · 已选中源目录 {self._compact_source_text(source_dir)}，"
                "建议先扫描再决定是否导入。"
            )
        else:
            self.action_bar.configure_primary("打开资源目录", self._open_resource_dir, visible=True)
            action_message = f"当前模式：{mode_text} · 先选择源目录并扫描，确认识别结果后再执行导入。"
        self.action_bar.set_message(action_message)

    def _sync_status_strip(self):
        source_dir = self.source_edit.text().strip()
        mode_text = self._mode_text()
        dry_run = bool(self.dry_run_checkbox.isChecked())

        badges = [
            ("positive" if source_dir else "warning", f"源目录 · {self._compact_source_text(source_dir)}"),
            ("info", f"模式 · {mode_text}"),
            ("info" if dry_run else "positive", f"策略 · {'预演' if dry_run else '保守导入'}"),
        ]

        if self._last_import_result:
            summary = self._last_import_result.get("summary", {}) or {}
            copied = int(summary.get("copied_count", 0) or 0)
            skipped = int(summary.get("skipped_conflicts_count", 0) or 0)
            failed = int(summary.get("failed_count", 0) or 0)
            badges.append(("positive" if failed == 0 else "warning", f"结果 · {copied}/{skipped}/{failed}"))
            detail_text = (
                f"当前使用“{mode_text}”模式，"
                f"{'只做预演，不写入文件' if dry_run else '按保守策略执行导入'}。"
                f"最近一次执行结果：成功 {copied}，冲突跳过 {skipped}，失败 {failed}。"
            )
        elif self._scan_report:
            summary = (self._scan_report or {}).get("summary", {}) or {}
            recognized = int(summary.get("recognized_count", 0) or 0)
            conflicts = int(summary.get("conflict_count", 0) or 0)
            unrecognized = int(summary.get("unrecognized_count", 0) or 0)
            badges.append(("positive" if recognized > 0 else "warning", f"扫描 · {recognized}/{conflicts}"))
            detail_text = (
                f"当前使用“{mode_text}”模式，已完成扫描。"
                f"识别 {recognized} 项，冲突 {conflicts} 项，未识别 {unrecognized} 项。"
            )
        else:
            badges.append(("warning" if source_dir else "info", "结果 · 待扫描"))
            detail_text = (
                f"当前使用“{mode_text}”模式，"
                f"{'只做预演，不写入文件' if dry_run else '按保守策略执行导入'}。"
                "先选择源目录并扫描，再决定是否导入。"
            )

        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.summary_label.setToolTip(detail_text)
        self.status_card.setToolTip(detail_text)
        self._sync_action_bar()

    def _choose_source_dir(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择要导入的资源目录",
            self.source_edit.text().strip() or os.path.expanduser("~"),
        )
        if directory:
            self.source_edit.setText(directory)
            self._scan_source()

    def _current_mode(self) -> str:
        return str(self.mode_combo.currentData() or "audio")

    def _mode_text(self) -> str:
        return str(self.mode_combo.currentText() or "音频")

    def _on_mode_changed(self):
        mode_text = self._mode_text()
        self.source_edit.setPlaceholderText(f"请选择包含{mode_text}资源的根目录")
        self._scan_report = None
        self._last_import_result = None
        self.summary_label.setText(f"当前模式：{mode_text}。请选择目录并扫描。")
        self.preview_text.clear()
        self._sync_status_strip()

    def _scan_source(self):
        source_dir = self.source_edit.text().strip()
        if not source_dir:
            QMessageBox.information(self, "提示", "请先选择源目录。")
            return

        report = scan_resource_import_candidates(
            source_dir,
            self.resources_root,
            domain=self._current_mode(),
        )
        self._scan_report = report
        self._last_import_result = None
        self._render_report(report)

    def _run_import(self):
        if not self._scan_report:
            self._scan_source()
            if not self._scan_report:
                return

        dry_run = bool(self.dry_run_checkbox.isChecked())
        if not dry_run and bool(getattr(config, "config_snapshot_auto_before_risky_ops", True)):
            try:
                from core.config_snapshot_manager import create_snapshot, prune_snapshots

                create_snapshot("resource_import_wizard")
                prune_snapshots(int(getattr(config, "config_snapshot_max_keep", 20) or 20))
            except Exception as exc:
                self.logger.warning(f"导入前自动快照失败: {exc}")

        result = apply_resource_import_plan(
            self._scan_report,
            dry_run=dry_run,
            overwrite_existing=False,
        )
        self._last_import_result = result

        if (
            not dry_run
            and result.get("summary", {}).get("copied_count", 0) > 0
            and any(str(item.get("domain", "")) == "audio" for item in result.get("copied", []) or [])
        ):
            try:
                submit_import_refresh_task("audio_import_wizard")
            except Exception as exc:
                self.logger.warning(f"导入后重扫失败: {exc}")

        copied = result.get("summary", {}).get("copied_count", 0)
        skipped = result.get("summary", {}).get("skipped_conflicts_count", 0)
        failed = result.get("summary", {}).get("failed_count", 0)
        mode_text = "建议预演完成" if dry_run else "导入完成"
        QMessageBox.information(
            self,
            mode_text,
            f"{mode_text}\n成功: {copied}\n冲突跳过: {skipped}\n失败: {failed}",
        )

        if not dry_run:
            self._scan_source()
        else:
            self._render_report(self._scan_report, result)

    def _unrecognized_audio_files(self) -> list[str]:
        """当前扫描结果中未识别、且确为音频的文件（按文件名自然排序）。"""
        from core.audio.audio_file_utils import is_audio_filename

        items = (self._scan_report or {}).get("unrecognized", []) or []
        paths = [
            str(item.get("source_path", ""))
            for item in items
            if item.get("source_path")
            and os.path.isfile(str(item.get("source_path", "")))
            and is_audio_filename(os.path.basename(str(item.get("source_path", ""))))
        ]

        def natural_key(path: str):
            import re

            name = os.path.basename(path).lower()
            return [int(seg) if seg.isdigit() else seg for seg in re.split(r"(\d+)", name)]

        return sorted(paths, key=natural_key)

    def _classify_unrecognized(self):
        """v2.2.1: 把未识别音频手动归类为新风格——选类别→复用新建风格向导自动改名落盘。"""
        files = self._unrecognized_audio_files()
        if not files:
            QMessageBox.information(self, "提示", "当前没有可归类的未识别音频文件，请先扫描目录。")
            return

        from PySide6.QtWidgets import QInputDialog

        from core.audio.style_creator import CATEGORY_TEMPLATES
        from dialogs.style_creator_dialog import StyleCreatorDialog
        from pages.kill_sound_page import KillSoundPage

        labels = {tpl.label: key for key, tpl in CATEGORY_TEMPLATES.items()}
        label, ok = QInputDialog.getItem(
            self,
            "选择音效类别",
            f"找到 {len(files)} 个未识别音频。\n它们属于哪类音效？（将按文件名顺序自动映射）",
            list(labels.keys()),
            0,
            False,
        )
        if not ok or not label:
            return

        category = labels[label]
        template = CATEGORY_TEMPLATES[category]
        selected = files[: template.max_files]
        if len(files) > template.max_files:
            if template.max_files > 1:
                hint = (
                    f"{template.label}最多 {template.max_files} 个文件，"
                    f"已按文件名顺序取前 {template.max_files} 个；其余可再次点击本按钮分批归类。"
                )
            else:
                hint = f"{template.label}只需 1 个文件，已取排序后的第 1 个；其余可再次归类。"
            QMessageBox.information(self, "提示", hint)

        dialog = StyleCreatorDialog(
            category,
            self,
            weapons=KillSoundPage.WEAPON_NAMES,
            initial_files=selected,
        )
        dialog.style_created.connect(lambda name, weapon: self._on_manual_classified(name, weapon, category))
        dialog.exec()

    def _on_manual_classified(self, style_name: str, weapon: str, category: str):
        try:
            submit_import_refresh_task("audio_import_wizard_manual")
        except Exception as exc:
            self.logger.warning(f"手动归类后重扫失败: {exc}")
        self.logger.info(f"手动归类完成: category={category}, style={style_name}, weapon={weapon or '全局'}")
        # 重新扫描以更新未识别列表（已归类的文件仍在源目录，但用户已明确处理过）
        self._scan_source()

    def _open_source_dir(self):
        source_dir = self.source_edit.text().strip()
        if not source_dir:
            QMessageBox.information(self, "提示", "请先选择源目录。")
            return
        self._open_path(source_dir)

    def _open_resource_dir(self):
        os.makedirs(self.resources_root, exist_ok=True)
        self._open_path(self.resources_root)

    def _open_path(self, path: str):
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as exc:
            QMessageBox.warning(self, "打开失败", f"无法打开目录：{exc}\n{path}")

    def _render_report(self, report: dict, import_result: dict | None = None):
        summary = (report or {}).get("summary", {})
        mode_text = self._mode_text()
        self.summary_label.setText(
            f"扫描完成（{mode_text}）："
            f"资源文件 {summary.get('scanned_resource_files', 0)}，"
            f"可识别 {summary.get('recognized_count', 0)}，"
            f"冲突 {summary.get('conflict_count', 0)}，"
            f"未识别 {summary.get('unrecognized_count', 0)}"
        )

        lines = []
        lines.append("[导入向导扫描结果]")
        lines.append(f"源目录: {report.get('source_dir', '')}")
        lines.append(f"导入模式: {report.get('domain', self._current_mode())}")
        lines.append(f"目标目录: {report.get('resources_root', '')}")
        lines.append(
            "统计: "
            f"扫描资源={summary.get('scanned_resource_files', 0)}, "
            f"可识别={summary.get('recognized_count', 0)}, "
            f"冲突={summary.get('conflict_count', 0)}, "
            f"未识别={summary.get('unrecognized_count', 0)}"
        )
        lines.append("")

        recognized = report.get("recognized", []) or []
        lines.append(f"[可识别文件] {len(recognized)}")
        for item in recognized[:80]:
            tag = "冲突" if item.get("conflict") else "可导入"
            spec_label = str(item.get("spec_label", item.get("spec_key", "")) or "").strip()
            lines.append(
                f"- [{tag}] {spec_label}: {item.get('source_path', '')} -> {item.get('target_rel_path', '')}"
            )
        if len(recognized) > 80:
            lines.append(f"... 其余 {len(recognized) - 80} 条已省略")

        unrecognized = report.get("unrecognized", []) or []
        lines.append("")
        lines.append(f"[未识别文件] {len(unrecognized)}")
        for item in unrecognized[:80]:
            lines.append(f"- {item.get('source_path', '')}（{_translate_reason(item.get('reason', ''))}）")
        if len(unrecognized) > 80:
            lines.append(f"... 其余 {len(unrecognized) - 80} 条已省略")
        if unrecognized:
            lines.append(_STRUCTURE_GUIDE)
        # 手动归类按钮随扫描结果联动
        if hasattr(self, "classify_btn"):
            self.classify_btn.setEnabled(bool(self._unrecognized_audio_files()))

        if import_result:
            import_summary = import_result.get("summary", {})
            lines.append("")
            lines.append("[最近一次执行]")
            lines.append(f"模式: {'建议预演' if import_result.get('dry_run') else '实际导入'}")
            lines.append(
                "结果: "
                f"成功={import_summary.get('copied_count', 0)}, "
                f"冲突跳过={import_summary.get('skipped_conflicts_count', 0)}, "
                f"失败={import_summary.get('failed_count', 0)}"
            )

        self.preview_text.setPlainText("\n".join(lines))
        self._sync_status_strip()
