#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Resource import wizard page."""

# 注释来历：docs/notes/代码注释的来历_audio_import_wizard_page.md
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import config
from core.audio.audio_task_runner import submit_import_refresh_task
from core.resource_import_source import (
    ImportCancelled,
    ImportSourceError,
    open_source,
)
from widgets.kill_icon_import_task import KillIconImportTask
from widgets.page_notice_bar import PageNoticeBar
import core.resource_generation as resource_generation
from core.resource_import_wizard import (
    apply_resource_import_plan,
    plan_from_decisions,
    prepare_decisions,
    remember_decisions,
    undo_import,
)
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from resource_manager import ResourceManager
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard
from widgets.settings_row import PLAIN_LABEL_WIDTH, plain_row
from widgets.page_header import PageHeader
from widgets.status_strip import StatusStrip


# 未识别原因按用户可操作的方式说明。
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
        # 扫描报告及源状态必须一起作废，统一走 _invalidate_scan。
        self._invalidate_scan()
        self._last_import_result = None
        self._init_ui()
        # 对标主流：把文件夹/音频文件直接拖进页面即可填入并扫描
        self.setAcceptDrops(True)

    # ---------------- 拖拽导入（对标修缮） ----------------

    def dragEnterEvent(self, event):
        # ⛔ 不许写回 `event.mimeData().hasUrls()`（RN-674，理由在 `urls_from_drop`）。
        from widgets.drop_import_mixin import urls_from_drop

        if urls_from_drop(event):
            self._set_drop_highlight(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        # ⚠ 少这一条，高亮就留在屏上不走 —— 界面一直说「松手即可放入」而那时松手没用。
        self._set_drop_highlight(False)
        super().dragLeaveEvent(event)

    def _set_drop_highlight(self, on: bool):
        """RN-674：投放高亮每次取当前主题色，避免换主题后沿用构造时的快照。"""
        box = getattr(self, "preview_text", None)
        if box is None:
            return
        if not on:
            box.setStyleSheet(getattr(self, "_preview_base_qss", ""))
            return
        try:
            from theme_manager import get_color

            accent = get_color("accent_primary")
        except Exception:
            accent = "#7C5CFF"
        box.setStyleSheet(
            getattr(self, "_preview_base_qss", "")
            + "\nQTextEdit { border: 2px dashed %s; }" % accent)

    @staticmethod
    def _drop_noun(path):
        """源类型由 resource_import_source 判断，页面仅兜底，不能只区分目录和压缩包。"""
        try:
            from core.resource_import_source import source_noun

            return source_noun(path)
        except Exception:
            import os

            return "文件夹" if os.path.isdir(path) else "文件"

    def accept_sources(self, paths, handed_from: str = "") -> bool:
        """本页拖放与跨页转交共用入口；handed_from 说明切页来源。"""
        import os

        dropped = [p for p in (paths or []) if p and (os.path.isdir(p) or os.path.isfile(p))]
        if not dropped:
            return False
        # 文件与目录均直接交给 open_source，不能取父目录而误扫整个下载目录。
        path = dropped[0]
        self.source_edit.setText(path)
        self.logger.info(f"拖拽导入: {path}（共拖入 {len(dropped)} 个{('，来自' + handed_from) if handed_from else ''}）")
        try:
            from ui_toast import toast_info

            # ⚠ 这句话放 toast 不放提示条：提示条紧接着就会被扫描结果
            #   （`_scan_unified` 那条"导入前请注意"）顶掉，等于没说。
            extra = ("" if len(dropped) == 1
                     else "（共 %d 个，先处理这一个）" % len(dropped))
            where = f"从「{handed_from}」转到这里导入：" if handed_from else "已填入拖入的"
            toast_info(
                "%s%s%s，正在识别…" % (where, self._drop_noun(path), extra),
                3200 if handed_from or len(dropped) > 1 else 2400)
        except Exception:
            pass
        self._scan_source()
        return True

    def dropEvent(self, event):
        # ⚠ 放在最外面：下面每一条出路（收下 / 不是本地文件 / 抛异常）
        #   都得把高亮撤掉，而"每条路各写一遍"正是漏掉一条的写法。
        self._set_drop_highlight(False)
        try:
            # 一次只处理一个源，必须明确提示其余源尚未导入。
            from widgets.drop_import_mixin import urls_from_drop

            dropped = [url.toLocalFile() for url in urls_from_drop(event)]
            if self.accept_sources(dropped):
                event.acceptProposedAction()
                return
            # 非本地文件也须给出可见反馈，避免放下后毫无反应。
            try:
                from ui_toast import toast_warning

                toast_warning("拖进来的不是本地文件。请先把资源下载到本地，"
                              "再把下载好的压缩包或文件夹拖进来。", 3600)
            except Exception:
                pass
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

        # UP-047：沿用本页字号与间距，保持现有布局。
        from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
        header = PageHeader(
            "导入资源",
            # 入口同时接收音频与视觉资源，说明需覆盖两类。
            description=("压缩包、文件夹，或单个素材文件都能直接拖进来，不用先解压。"
                         "软件先认出它是哪一类（音效、语音、击杀图标、准心…），"
                         "给你看清了再写入 —— 确认之前不动你现有的素材。"),
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        # RN-001b：帮助内容表不会自动安装入口，各页需显式挂载帮助面板。
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["audio_import_wizard"])

        card = StatusStrip()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(8)
        self.status_card = card

        self.status_badge_label = create_badge_label()
        card_layout.addWidget(self.status_badge_label)
        layout.addWidget(card)

        # RN-508：用卡片标题标明步骤，当前动作由 _sync_first_step 按状态决定。
        controls_card, controls_layout = SettingsCard.make(
            # 标题避免中点、冒号和逗号：搜索索引会将其判为状态或句子而丢弃。
            "第 1 步 选中素材并扫描",
        )

        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        source_label = QLabel("素材来源")
        source_label.setFixedWidth(PLAIN_LABEL_WIDTH)
        source_row.addWidget(source_label)

        self.source_edit = QLineEdit()
        source_row.addWidget(self.source_edit, 1)
        # ⚠ 占位文案**只有一处真源**（`_source_placeholder`），且要等
        #   `mode_combo` 建好才取得到模式名 ⇒ 在下面那一行统一设。

        # RN-674：文件入口与目录入口分开，并优先构造，以匹配默认动作与 Tab 顺序。
        # 源选择不放进动作行，避免紧凑档按钮挤压。
        self.browse_archive_btn = QPushButton("选择压缩包 / 文件…")
        self.browse_archive_btn.setObjectName("secondaryButton")
        self.browse_archive_btn.clicked.connect(self._choose_source_archive)
        source_row.addWidget(self.browse_archive_btn)

        self.browse_btn = browse_btn = QPushButton("选择文件夹")
        browse_btn.setObjectName("secondaryButton")
        browse_btn.clicked.connect(self._choose_source_dir)
        source_row.addWidget(browse_btn)

        # 多种导入提示合在页内显示，避免连续模态框被机械确认。
        self.notice_bar = PageNoticeBar(self)
        controls_layout.addLayout(source_row)
        controls_layout.addWidget(self.notice_bar)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("音频", "audio")
        self.mode_combo.addItem("视觉", "visual")
        self.mode_combo.addItem("全部", "all")
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        self.dry_run_checkbox = QCheckBox("仅生成建议（不复制文件）")
        self.dry_run_checkbox.setChecked(False)
        controls_layout.addWidget(plain_row("导入模式", self.mode_combo, self.dry_run_checkbox))

        # ⚠ 位置就得在这儿：`_source_placeholder()` 要读 `mode_combo`。
        self.source_edit.setPlaceholderText(self._source_placeholder())

        # UP-100：操作与目录入口分两组；窄页时外层转竖排，避免按钮文字被裁。
        actions = QBoxLayout(QBoxLayout.LeftToRight)
        actions.setSpacing(8)
        self.actions_row = actions

        self.scan_btn = QPushButton("扫描素材")
        # 主次随是否已选源变化，未选源时不能引导用户盲点扫描。
        self.scan_btn.setObjectName("secondaryButton")
        # RN-508：按钮直接说明安全性质，避免使用内部术语。
        self.import_btn = QPushButton("开始导入（不覆盖已有文件）")
        self.import_btn.setObjectName("secondaryButton")
        # v2.2.1: 未识别文件不再是死胡同——手动归类为新风格
        self.classify_btn = QPushButton("把未识别音频导入为新风格…")
        self.classify_btn.setObjectName("secondaryButton")
        self.classify_btn.setEnabled(False)
        self.open_source_btn = QPushButton("打开来源位置")
        self.open_source_btn.setObjectName("secondaryButton")
        self.open_resource_btn = QPushButton("打开资源目录")
        self.open_resource_btn.setObjectName("secondaryButton")

        # RN-508：导入按钮只放在结果步骤，不在选择步骤保留副本。
        work_row = QHBoxLayout()
        work_row.setSpacing(8)
        work_row.setContentsMargins(0, 0, 0, 0)
        work_row.addWidget(self.scan_btn)

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
            "第 2 步 看清结果再导入",
        )

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(240)
        # RN-674：setPlaceholderText 只显示第一行，多行空态写进正文。
        # RN-519：提示中的按钮名直接从按钮读取。
        self.preview_text.setPlaceholderText(self._EMPTY_LEAD)
        self._show_empty_preview()
        # ⭐ 拖拽高亮要能**原样复原** —— 记下底样式，别用 `setStyleSheet("")` 抹。
        self._preview_base_qss = self.preview_text.styleSheet()
        preview_layout.addWidget(self.preview_text)

        # 「确认无误后再导入」——那就把导入放在确认的地方。
        import_row = QHBoxLayout()
        import_row.setSpacing(8)
        import_row.setContentsMargins(0, 0, 0, 0)
        import_row.addWidget(self.import_btn)
        import_row.addWidget(self.classify_btn)
        import_row.addStretch()
        preview_layout.addLayout(import_row)

        layout.addWidget(preview_card, 1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.action_bar = PageActionBar(self)
        root.addWidget(self.action_bar, 0)

        self.scan_btn.clicked.connect(self._scan_source)
        self.import_btn.clicked.connect(self._run_import)
        self.classify_btn.clicked.connect(self._classify_unrecognized)
        self.open_source_btn.clicked.connect(self._open_source_dir)
        self.open_resource_btn.clicked.connect(self._open_resource_dir)
        self.source_edit.textChanged.connect(lambda _text: self._sync_status_strip())
        self.dry_run_checkbox.toggled.connect(lambda _checked: self._sync_status_strip())
        self._sync_status_strip()

    # UP-100：960 位于紧凑档 860 与完整档 1000 之间；sizeHint 含 QSS padding，不能等同文字裁切。
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
        # RN-102/506：动作在卡片内已有入口，底栏不保留副本或随状态换义的主按钮。
        self.action_bar.configure_secondary("", None, visible=False)
        self.action_bar.configure_primary("", None, visible=False)
        self._sync_first_step(bool(source_dir))

        if self._last_import_result:
            summary = self._last_import_result.get("summary", {}) or {}
            copied = int(summary.get("copied_count", 0) or 0)
            skipped = int(summary.get("skipped_conflicts_count", 0) or 0)
            failed = int(summary.get("failed_count", 0) or 0)
            action_message = (
                f"当前模式：{mode_text} · 最近一次{'预演' if dry_run else '导入'}结果 "
                f"{copied}/{skipped}/{failed}，可点上面「{self.open_resource_btn.text()}」继续核对。"
            )
        elif self._scan_report:
            summary = (self._scan_report or {}).get("summary", {}) or {}
            recognized = int(summary.get("recognized_count", 0) or 0)
            conflicts = int(summary.get("conflict_count", 0) or 0)
            action_message = (
                f"当前模式：{mode_text} · 已扫描 {recognized} 个可识别条目、{conflicts} 个冲突；"
                f"下一步可直接{'生成建议' if dry_run else '开始导入'}。"
            )
        elif source_dir:
            action_message = (
                f"当前模式：{mode_text} · 已选中 {self._compact_source_text(source_dir)}，"
                "建议先扫描再决定是否导入。"
            )
        else:
            action_message = f"当前模式：{mode_text} · 先选中素材并扫描，确认识别结果后再执行导入。"
        self.action_bar.set_message(action_message)

    def _sync_first_step(self, has_source: bool):
        """未选源时主动作是选择文件，已选时是扫描；无源就禁用扫描并解释原因。"""
        from page_theme_helper import style_as_primary_button, style_as_secondary_button

        first = self.scan_btn if has_source else self.browse_archive_btn
        buttons = (self.scan_btn, self.browse_btn, self.browse_archive_btn)
        for btn in buttons:
            if btn is first:
                style_as_primary_button(btn)
            else:
                style_as_secondary_button(btn)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

        # ⛔ 这两颗**一起动**：它们空点下去是同一个死胡同
        #   （`_run_import` 没报告就自己去 `_scan_source`，撞的是同一句提示）。
        blocked_tip = "" if has_source else "先选中素材（压缩包、文件夹，或单个素材文件），这一步才有东西可做。"
        # RN-150：次按钮禁用态按全站主题以文字和边框区分，不在单页另改填充。
        for btn in (self.scan_btn, self.import_btn):
            btn.setEnabled(has_source)
            btn.setToolTip(blocked_tip)

    def _sync_status_strip(self):
        source_dir = self.source_edit.text().strip()
        mode_text = self._mode_text()
        dry_run = bool(self.dry_run_checkbox.isChecked())

        badges = [
            ("positive" if source_dir else "warning", f"素材来源 · {self._compact_source_text(source_dir)}"),
            ("info", f"模式 · {mode_text}"),
            ("info" if dry_run else "positive", f"策略 · {'只预演' if dry_run else '不覆盖已有'}"),
        ]

        if self._last_import_result:
            summary = self._last_import_result.get("summary", {}) or {}
            copied = int(summary.get("copied_count", 0) or 0)
            skipped = int(summary.get("skipped_conflicts_count", 0) or 0)
            failed = int(summary.get("failed_count", 0) or 0)
            badges.append(("positive" if failed == 0 else "warning", f"结果 · {copied}/{skipped}/{failed}"))
            detail_text = (
                f"当前使用“{mode_text}”模式，"
                f"{'只做预演，不写入文件' if dry_run else '导入时不覆盖已有文件'}。"
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
            badges.append(("info", "结果 · 待扫描"))
            detail_text = (
                f"当前使用“{mode_text}”模式，"
                f"{'只做预演，不写入文件' if dry_run else '导入时不覆盖已有文件'}。"
                "先选中素材并扫描，再决定是否导入。"
            )

        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
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

    def _choose_source_archive(self):
        """文件入口兼收压缩包与单素材；open_source 按文件头识别真实格式。"""
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择压缩包或单个素材文件",
            self.source_edit.text().strip() or os.path.expanduser("~"),
            "资源包与素材 (*.zip *.mp3 *.wav *.ogg *.png *.jpg *.jpeg *.xchr);;"
            "压缩包 (*.zip);;所有文件 (*.*)",
        )
        if path:
            self.source_edit.setText(path)
            self._scan_source()

    def _open_import_source(self):
        """解压在后台线程执行，局部事件循环等待结果并保持重绘和取消响应。"""
        raw = self.source_edit.text().strip()
        if not raw:
            QMessageBox.information(self, "提示", "请先选择压缩包或目录。")
            return None

        holder = {}

        def work(progress, should_cancel):
            holder["source"] = open_source(
                raw, progress=progress, should_cancel=should_cancel)
            return holder["source"]

        ok = self._run_in_background(work, "正在读取资源包")
        if not ok:
            return None
        return holder.get("source")

    def _run_in_background(self, work, label) -> bool:
        """后台任务复用 KillIconImportTask，保留调用方异常类型和取消语义。"""
        from PySide6.QtCore import QEventLoop

        task = KillIconImportTask(self)
        loop = QEventLoop(self)
        state = {"ok": False, "error": "", "cancelled": False}

        progress_box = QProgressDialog(label, "取消", 0, 0, self)
        progress_box.setWindowModality(Qt.WindowModal)
        # ⛔ 不许它自己弹出来（CLAUDE.md §3：跑测试/审计时不弹真窗口）——
        #   只有真的花了时间才显示。
        progress_box.setMinimumDuration(400)
        progress_box.setAutoClose(False)
        progress_box.setAutoReset(False)
        progress_box.canceled.connect(task.cancel)

        def on_progress(done, total, stage):
            if total > 0:
                progress_box.setMaximum(total)
                progress_box.setValue(done)
            progress_box.setLabelText(f"{label}\n{stage}")

        def on_finished(_result):
            state["ok"] = True
            loop.quit()

        def on_failed(message):
            state["error"] = str(message)
            loop.quit()

        def on_cancelled():
            state["cancelled"] = True
            loop.quit()

        task.progress.connect(on_progress)
        task.finished.connect(on_finished)
        task.failed.connect(on_failed)
        task.cancelled.connect(on_cancelled)

        started = task.start(work, label,
                             cancelled_exc=ImportCancelled,
                             error_exc=ImportSourceError)
        if not started:
            return False
        loop.exec()
        progress_box.close()

        if state["cancelled"]:
            return False
        if state["error"]:
            # ⭐ 这里的消息是**能照着做**的（"这是 RAR，请先解压"），直接展示。
            QMessageBox.warning(self, "打不开这个资源", state["error"])
            return False
        return state["ok"]

    def _decide_groups(self, source):
        """识别 → 拿不准就问一次 → 决定清单。用户取消返回 None。"""
        # prepare_decisions 必须接收当前模式，避免视觉模式导入音频。
        prepared = prepare_decisions(source, self._current_mode())
        self._domain_skipped = list(prepared.get("skipped_by_domain") or [])
        # RN-674：在任何 return 前统一归零，避免多条退出路径漏清状态。
        self._skipped_unsure = []
        if not prepared["groups"]:
            return []
        decided = prepared["decided"]
        manifest_style = str(prepared["default_style"])
        unsure = prepared["unsure"]
        if not unsure:
            return decided

        from dialogs.resource_import_decision_dialog import (
            ResourceImportDecisionDialog,
        )

        dialog = ResourceImportDecisionDialog(
            unsure, parent=self, default_style_name=manifest_style)
        if dialog.exec() != QDialog.Accepted:
            return None
        picked = dialog.decisions()
        # RN-675：未选类别的组也需记录；decisions 会跳过未选行，必须按文件集而非下标对应。
        answered = {tuple(str(p) for p in (d.get("paths") or [])) for d in picked}
        self._skipped_unsure = [g for g in unsure
                                if tuple(str(p) for p in (getattr(g, "paths", None) or ()))
                                not in answered]
        # ⭐ 记下这一次的选择：同样结构的素材下次不再问。
        #   ⚠ 只记问过的那几组（`unsure`），顺序与对话框里的一一对应。
        remember_decisions(unsure, picked)
        return decided + picked

    def _scan_unified(self):
        """目录与压缩包统一扫描；退出前先作废旧报告，避免源失败后重用上一个包。"""
        # ⚠ 位置就得在这儿 —— 在任何一个 `return` 之前。
        self._invalidate_scan()
        # ⭐ 提示条也要归零：实测里 `.tar.gz` 被正确拒绝之后，条上仍写着
        #   上一次的「导入完成：成功 1」—— 一句过期的好消息压在一条错误上面。
        # ⛔ 这一句不许搬进 `_invalidate_scan()`：撤销那条路是先 `show_message`
        #   再作废报告，搬进去会把「已撤销」当场擦掉。
        self.notice_bar.clear()
        source = self._open_import_source()
        if source is None:
            return
        try:
            decisions = self._decide_groups(source)
            if decisions is None:      # 用户在确认框里取消
                # RN-675：取消也需可见反馈，不能静默返回。
                self.notice_bar.show_message(
                    "已取消，这一次没有改动你的素材。再点一次「%s」会重新问你。"
                    % self.scan_btn.text())
                return
            if not decisions:
                QMessageBox.information(
                    self, "没有可导入的内容", self._nothing_to_import_reason())
                return
            report = plan_from_decisions(source, decisions, self.resources_root)
            self._scan_report = report
            self._scan_report_source = self.source_edit.text().strip()
            self._last_import_result = None
            self._render_report(report)
            warnings = [str(line) for line in (report.get("warnings") or [])]
            # RN-675：即使有可导内容，也必须说明哪些组被跳过。
            unanswered = self._unanswered_notice()
            if unanswered:
                warnings.insert(0, unanswered)
            skipped = len(getattr(self, "_domain_skipped", []) or [])
            if skipped:
                # ⭐ 被「导入模式」挡掉的也要说：用户看到"成功 0"而不知道为什么，
                #   比报一句错还难受。
                warnings.insert(0, (
                    f"当前模式是「{self._mode_text()}」，"
                    f"包里有 {skipped} 组不属于这一类的素材没有导入 —— "
                    f"要一起导就把模式切到「全部」再扫一次"))
            aside = self._aside_notice(source)
            if aside:
                # ⭐ 摘出来没导入的那些**必须讲出来** —— 悄悄扔掉别人的文件，
                #   和悄悄把垃圾导进资源库一样不该。位置是"结果可见"，不是弹窗。
                warnings.insert(0, aside)
            if warnings:
                # 落盘前合并提示已导入但不会生效的条目，避免多次弹窗被连点忽略。
                self.notice_bar.show_message("导入前请注意：" + "；".join(warnings))
        finally:
            # ⚠ 报告里存的是**绝对路径**，指向临时解压目录 ——
            #   所以清理必须等到真正落盘之后，见 `_run_import`。
            self._pending_source = source

    def _unanswered_notice(self) -> str:
        """RN-675：未选类别的组既不导入也不归入未识别，必须单独告知。"""
        groups = getattr(self, "_skipped_unsure", None) or []
        if not groups:
            return ""
        files = [str(p) for g in groups for p in (getattr(g, "paths", None) or ())]
        shown = "、".join(os.path.basename(p) or p for p in files[:3])
        more = f"等 {len(files)} 个文件" if len(files) > 3 else ""
        return (f"{shown}{more} 你刚才没有选类别，这一次没有导入 —— "
                f"再点一次「{self.scan_btn.text()}」会重新问你")

    def _nothing_to_import_reason(self) -> str:
        """RN-675：分别说明未选类别、模式不符和未识别，不能共用无资源的保证。"""
        parts = []
        unanswered = self._unanswered_notice()
        if unanswered:
            parts.append(unanswered)
        skipped = len(getattr(self, "_domain_skipped", []) or [])
        if skipped:
            parts.append(
                f"当前模式是「{self._mode_text()}」，包里有 {skipped} 组素材"
                f"不属于这一类 —— 把模式切到「全部」再扫一次就能导")
        if not parts:
            parts.append("这个包里没有认得出来的资源文件。")
        return "；".join(parts)

    @staticmethod
    def _aside_notice(source) -> str:
        """附带文件逐个点名便于保留，系统临时文件仅报数量。"""
        import os as _os

        companions = [str(p) for p in (getattr(source, "companions", None) or [])]
        junk = int(getattr(source, "junk_count", 0) or 0)
        parts = []
        if companions:
            shown = "、".join(_os.path.basename(p) for p in companions[:3])
            more = f"等 {len(companions)} 个文件" if len(companions) > 3 else ""
            parts.append(f"包里的 {shown}{more} 不是素材，没有导入")
        if junk:
            parts.append(f"另丢掉 {junk} 个系统临时文件")
        return "；".join(parts)

    # RN-674：占位仅显示首行，与正文共用完整首句；其后留空行，避免紧凑档切断下一句。
    _EMPTY_LEAD = "把压缩包、文件夹，或单个素材文件直接拖到这里 —— 不用先解压。"

    def _show_empty_preview(self):
        """多行空态写进正文，按钮名现读；占位只能显示第一行。"""
        self.preview_text.setPlainText(
            f"{self._EMPTY_LEAD}\n\n"
            f"也可以点上面的「{self.browse_archive_btn.text()}」"
            f"或「{self.browse_btn.text()}」选一个，再点「{self.scan_btn.text()}」。\n\n"
            f"扫描之后这里会列出：能认出来的、有冲突的、没认出来的条目各多少；"
            f"扫描只看不写，确认之前不动你现有的素材。")

    def _source_placeholder(self) -> str:
        """RN-674：源输入提示共用一份；投放区仅指第 2 步结果框。"""
        return f"压缩包、文件夹，或单个{self._mode_text()}素材文件的路径"

    def _current_mode(self) -> str:
        return str(self.mode_combo.currentData() or "audio")

    def _mode_text(self) -> str:
        return str(self.mode_combo.currentText() or "音频")

    def _on_mode_changed(self):
        # RN-674：模式切换与建页共用提示，不能把文件入口说成只接受根目录。
        self.source_edit.setPlaceholderText(self._source_placeholder())
        self._invalidate_scan()
        self._last_import_result = None
        # RN-520：模式切换后恢复空态正文，不能清成空白。
        self._show_empty_preview()
        self._sync_status_strip()

    def _scan_source(self):
        """统一委托 _scan_unified，certain 档保持规范包的既有识别规则。"""
        self._scan_unified()

    def _invalidate_scan(self):
        """报告含源的绝对路径，源变化后必须作废。"""
        self._scan_report = None
        self._scan_report_source = ""

    def _scan_is_stale(self) -> bool:
        """报告只对扫描时的源路径有效，路径变化后必须重扫。"""
        if not self._scan_report:
            return False        # 没有报告不叫"过期"，叫"还没扫"
        return self._scan_report_source != self.source_edit.text().strip()

    def _run_import(self):
        if self._scan_is_stale():
            self._invalidate_scan()
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

        # ⚠ 真正逐文件 `shutil.copy2` 的是这一步 —— 一个几百兆的包在 UI 线程上
        #   复制会把界面冻住，而冻多久由用户的素材大小决定。⇒ 也走后台。
        holder = {}

        def work(progress, should_cancel):
            # 写盘阶段也必须传递进度与取消回调，不能只关闭进度框而继续复制。
            holder["result"] = apply_resource_import_plan(
                self._scan_report,
                dry_run=dry_run,
                overwrite_existing=False,
                progress=progress,
                should_cancel=should_cancel,
            )
            progress(1, 1, "已写入资源目录")
            return holder["result"]

        if not self._run_in_background(work, "正在写入资源目录"):
            return
        result = holder.get("result")
        if result is None:
            return
        self._last_import_result = result
        if not dry_run and result.get("summary", {}).get("copied_count", 0) > 0:
            resource_generation.bump()      # 批 123：转交过来的那一页切回去就重扫，不看冷却
        # ⚠ 临时解压目录只能在**落盘之后**清 —— 报告里存的是指向它的绝对路径。
        #   ⭐ 不清的代价是每导一个包在 `%TEMP%` 留一份副本，慢慢把盘填满。
        pending = getattr(self, "_pending_source", None)
        if pending is not None and not dry_run:
            pending.cleanup()
            self._pending_source = None

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
        rolled = (result.get("rollback") or {}).get("rolled_back")
        parts = [f"{mode_text}：成功 {copied}"]
        # 导入结果需保留已执行的重命名信息；扫描阶段的提醒不重复。
        did = [line for line in (self._scan_report or {}).get("warnings", []) or []
               if "替你重命名" in str(line) or "没有导入" in str(line)]
        parts.extend(str(line) for line in did[:2])
        if skipped:
            parts.append(f"冲突跳过 {skipped}（同名的旧素材没被覆盖）")
        if failed:
            parts.append(f"失败 {failed}")
        if result.get("cancelled"):
            # ⭐ 取消不是失败，但**必须说清停在哪** —— 已经写进去的那些还在。
            parts.insert(0, "已取消（前面写进去的还在，可以点撤销收回）")
        if rolled:
            # ⭐ 回滚发生过就要说 —— 不说的话用户以为"失败几个"是"其余都进去了"。
            stuck = int((result.get("rollback") or {}).get("stuck_count", 0) or 0)
            if stuck:
                # 回滚也可能失败，必须按实际删除结果报告残留。
                parts.append(
                    f"这一次已收回大部分，但有 {stuck} 个删不掉"
                    f"（多半正被别的程序占用），资源目录里还留着它们")
            else:
                parts.append("这一次已整体收回，资源目录没有留下半套素材")
        # ⭐ 撤销只在**真写了东西**的时候给：一个点下去什么都不会发生的按钮，
        #   比没有还糟。
        can_undo = bool(copied) and not dry_run and not rolled

        # 导入后只画本次结果再作废报告；立即重扫会清掉回执和撤销，并重复询问类别。
        self._render_report(self._scan_report, result)
        if not dry_run:
            self._invalidate_scan()
        self.notice_bar.show_message(
            "；".join(parts),
            undo_callback=(lambda: self._undo_last_import(result)) if can_undo else None,
        )

    def _undo_last_import(self, import_result):
        """把刚导进去的收回来。⭐ 走 core 的 `undo_import` ——
        它和"失败自动回滚"是同一个函数，两条路不会各自漂。"""
        outcome = undo_import(import_result)
        resource_generation.bump()          # 批 123：各页进页时据此重扫
        removed = int(outcome["summary"]["removed_count"])
        failed = int(outcome["summary"]["failed_count"])
        if failed:
            # ⚠ 点名按钮要**从按钮上读**，不能写死 —— 按钮改了名，
            #   这句话会静静地指向一个不存在的东西（判据 RN：文案点名按钮那条）。
            self.notice_bar.show_message(
                f"撤销了 {removed} 个文件，还有 {failed} 个删不掉"
                "（可能正被别的程序占用）。剩下的可以点"
                f"「{self.open_resource_btn.text()}」自己清。")
        else:
            self.notice_bar.show_message(f"已撤销，{removed} 个文件放回去了。")
        self._last_import_result = None
        self._invalidate_scan()
        self._sync_status_strip()

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
