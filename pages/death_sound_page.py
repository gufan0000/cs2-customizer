# SPDX-License-Identifier: GPL-3.0-or-later
"""被击杀音效页面。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import config, get_app_data_dir
from core.audio.audio_file_utils import (
    DEFAULT_AUDIO_EXTENSIONS,
    find_audio_by_stem,
    list_unique_audio_stems,
)
from core.audio.runtime_audio import get_runtime_audio_manager
from core.utils.logger import get_logger
from widgets.preview_feedback import PreviewFailure, report_preview_failure
from widgets.settings_card import SettingsCard
from pages.audio_status_badge import (
    build_health_detail_tooltip,
    collect_category_health,
    create_badge_label,
    is_style_enabled,
    render_badges,
)
from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar


class DeathSoundPage(QWidget):
    """被击杀音效设置页面。"""

    DISABLED_STYLE_TEXT = "不启用"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("DeathSoundPage")
        self.audio_manager = get_runtime_audio_manager()
        self.death_styles: list[str] = []
        self._loading = False

        self._ensure_config_defaults()
        self.audio_manager.ensure_styles_scanned()

        self._init_ui()
        self.load_settings()

        self.logger.info("被击杀音效页面初始化完成")

        # UP-038: 直接把 mp3 拖到页面上就打开「新建风格」并预填文件。
        # StyleCreatorDialog 早就支持 initial_files 了,以前只是没人接这根线——
        # 用户想加一个音效得先找到菜单里的"新建风格…",再在对话框里选文件。
        try:
            from widgets.drop_import_mixin import enable_file_drop

            enable_file_drop(self, DEFAULT_AUDIO_EXTENSIONS, self._on_audio_files_dropped)
        except Exception:
            self.logger.exception("音频拖拽导入初始化失败(不影响其它功能)")

    def _ensure_config_defaults(self):
        if not isinstance(getattr(config, "death_sound_style", "0"), str):
            config.death_sound_style = "0"
        if not hasattr(config, "death_sound_enabled"):
            config.death_sound_enabled = False

    @staticmethod
    def _compact_text(text, fallback="未选择", max_length=12):
        value = str(text or "").strip() or fallback
        if len(value) > max_length:
            return value[: max_length - 1] + "…"
        return value

    def _current_style_value(self) -> str:
        combo = getattr(self, "style_combo", None)
        if combo is not None and hasattr(combo, "currentData"):
            value = combo.currentData()
            if value is not None:
                return str(value)
        return str(getattr(config, "death_sound_style", "0") or "0")

    def _style_preview_names(self, max_items: int = 4) -> list[str]:
        return list(getattr(self, "death_styles", [])[:max_items])

    def _init_ui(self):
        # UP-071: 本页整页没有滚动区。R8a 第一版的纵向判据说它"三档字号都装得下"，
        # 那个结论是错的——判据本身有洞（把 HelpPanel 内部的小滚动区误当成页面级
        # 滚动区，于是整页被豁免）。判据修好后实测 1.25 字号档超出可视区 60px。
        # 套用 advanced_page / about_page 同一套「外层 + 内容滚动区 + 底部固定操作条」。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page_widget = QWidget()
        layout = QVBoxLayout(page_widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        header = PageHeader(
            "被击杀音效设置",
            description="被击杀音效页保持轻量，只保留样式切换和快速试听，把说明收成更清楚的卡片层级。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["death_sound"])

        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(14, 12, 14, 12)
        status_card_layout.setSpacing(8)

        status_header = QHBoxLayout()
        status_header.setSpacing(10)
        status_title = QLabel("当前状态")
        status_title.setObjectName("statusLabel")
        status_header.addWidget(status_title)
        self.status_badge_label = create_badge_label()
        status_header.addWidget(self.status_badge_label, 1)
        status_header.addStretch()
        status_card_layout.addLayout(status_header)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        status_card_layout.addWidget(self.summary_label)
        layout.addWidget(self.status_card)

        selection_card, selection_layout = SettingsCard.make(
            "样式选择",
            "保留最常用的样式切换和试听，让这一页更像一块轻量工具面板。",
        )
        selection_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        style_row = QHBoxLayout()
        style_row.setSpacing(8)

        style_label = QLabel("音效风格")
        style_label.setFixedWidth(72)
        style_row.addWidget(style_label)

        self.style_combo = QComboBox()
        self.style_combo.setObjectName("styleCombo")
        self.style_combo.setMinimumWidth(240)
        self.style_combo.setMinimumHeight(34)
        self.style_combo.currentTextChanged.connect(self._on_style_changed)
        style_row.addWidget(self.style_combo, 1)

        self.test_btn = QPushButton("测试")
        self.test_btn.setObjectName("secondaryButton")
        self.test_btn.setFixedWidth(88)
        self.test_btn.setMinimumHeight(34)
        self.test_btn.clicked.connect(self._test_sound)
        style_row.addWidget(self.test_btn)

        selection_layout.addLayout(style_row)

        self.selection_state_label = QLabel("")
        self.selection_state_label.setObjectName("hintLabel")
        self.selection_state_label.setWordWrap(True)
        selection_layout.addWidget(self.selection_state_label)

        overview_card, overview_layout = SettingsCard.make(
            "当前方案概况",
            "把启用状态、候选数量和当前扫描到的风格直接摆出来，确认时不用来回切。"
        )
        overview_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self.style_overview_name_label = QLabel("")
        self.style_overview_name_label.setObjectName("statusLabel")
        overview_layout.addWidget(self.style_overview_name_label)

        self.style_overview_meta_label = QLabel("")
        self.style_overview_meta_label.setObjectName("hintLabel")
        self.style_overview_meta_label.setWordWrap(True)
        overview_layout.addWidget(self.style_overview_meta_label)

        self.style_overview_hint_label = QLabel("")
        self.style_overview_hint_label.setObjectName("hintLabel")
        self.style_overview_hint_label.setWordWrap(True)
        overview_layout.addWidget(self.style_overview_hint_label)

        self.top_content_layout = QBoxLayout(QBoxLayout.LeftToRight)
        self.top_content_layout.setSpacing(12)
        self.top_content_layout.addWidget(selection_card, 5)
        self.top_content_layout.addWidget(overview_card, 4)
        layout.addLayout(self.top_content_layout)

        resource_card, resource_layout = SettingsCard.make(
            "资源匹配策略",
            "程序会按样式名在 death 目录中匹配同名音频，新增素材后直接刷新风格列表即可。"
        )
        resource_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self.resource_summary_label = QLabel("")
        self.resource_summary_label.setObjectName("hintLabel")
        self.resource_summary_label.setWordWrap(True)
        resource_layout.addWidget(self.resource_summary_label)
        layout.addWidget(resource_card)

        layout.addStretch()

        page_scroll.setWidget(page_widget)
        outer.addWidget(page_scroll, 1)

        # 操作条钉在滚动区外——跟着内容滚走的话，页面一长就找不到主操作了
        self.action_bar = PageActionBar(self)
        self.action_bar.configure_extra("新建风格", self._open_style_creator, visible=True)
        self.action_bar.configure_secondary("刷新风格列表", self._refresh_style_catalog, visible=True)
        self.action_bar.configure_primary("打开音频资源", self._open_audio_resource_root, visible=True)
        self.action_bar.extra_btn.setMinimumWidth(120)
        self.action_bar.secondary_btn.setMinimumWidth(148)
        self.action_bar.primary_btn.setMinimumWidth(148)
        outer.addWidget(self.action_bar, 0)
        self._update_compact_layout()

    def _scan_death_styles(self):
        death_dir = getattr(self.audio_manager, "death_sounds_dir", "")
        self.death_styles = list_unique_audio_stems(
            death_dir,
            extensions=DEFAULT_AUDIO_EXTENSIONS,
            sort=True,
        )

    def _reset_style_items(self, current_value: str):
        self.style_combo.blockSignals(True)
        self.style_combo.clear()
        self.style_combo.addItem(self.DISABLED_STYLE_TEXT, "0")
        for style in self.death_styles:
            self.style_combo.addItem(style, style)

        index = self.style_combo.findData(current_value)
        self.style_combo.setCurrentIndex(index if index >= 0 else 0)
        self.style_combo.blockSignals(False)

    def _refresh_style_catalog(self):
        current_style = self._current_style_value()
        self._scan_death_styles()
        self._reset_style_items(current_style)
        self._refresh_status_badge()
        self.logger.info("被击杀音效风格列表已刷新")

    @staticmethod
    def _open_audio_resource_root():
        audio_root = get_app_data_dir(os.path.join("resources", "audio", "death"))
        QDesktopServices.openUrl(QUrl.fromLocalFile(audio_root))


    def _on_audio_files_dropped(self, paths):
        """UP-038: 拖入音频 → 直接打开「新建风格」对话框并预填。"""
        files = [p for p in (paths or []) if str(p).lower().endswith(DEFAULT_AUDIO_EXTENSIONS)]
        if not files:
            return
        self._open_style_creator(initial_files=files)

    def _open_style_creator(self, initial_files=None):
        """v2.2.1: 一步式新建风格——拖入 1 个音频文件，自动按风格名落盘并刷新。"""
        from dialogs.style_creator_dialog import StyleCreatorDialog

        dialog = StyleCreatorDialog("death_sound", self, audio_manager=self.audio_manager, initial_files=initial_files)
        dialog.style_created.connect(self._on_style_created)
        dialog.exec()

    def _on_style_created(self, style_name: str, _weapon: str):
        self._refresh_style_catalog()
        # 自动选中新风格（会触发 _on_style_changed 落配置）
        index = self.style_combo.findData(style_name)
        if index >= 0:
            self.style_combo.setCurrentIndex(index)
        self.logger.info(f"新建风格已就绪: {style_name}")

    def showEvent(self, event):
        """v2.2.1: 进页自动重扫（10s 冷却）——手动放文件后不再需要手动点刷新。"""
        super().showEvent(event)
        import time as _time

        now = _time.monotonic()
        last = getattr(self, "_last_auto_refresh", 0.0)
        if now - last >= 10.0:
            self._last_auto_refresh = now
            try:
                self._refresh_style_catalog()
            except Exception:
                self.logger.exception("进页自动刷新风格列表失败")

    def load_settings(self):
        self._scan_death_styles()

        self._loading = True
        try:
            current_style = getattr(config, "death_sound_style", "0")
            if not isinstance(current_style, str):
                current_style = "0"
            self._reset_style_items(current_style)
        finally:
            self._loading = False

        self._refresh_status_badge()
        self.logger.debug(f"加载被击杀音效设置: {getattr(config, 'death_sound_style', '0')}")

    def _on_style_changed(self, _text: str):
        if getattr(self, "_loading", False):
            return

        style_value = self._current_style_value()
        old_style = str(getattr(config, "death_sound_style", "0") or "0")
        if old_style == style_value:
            self._refresh_status_badge()
            return

        config.death_sound_style = style_value
        config.save_config()
        self._refresh_status_badge()

        self.logger.info(f"被击杀音效风格更新: {old_style} -> {style_value}")

    def _test_sound(self):
        style_value = self._current_style_value()
        if not is_style_enabled(style_value):
            # UP-037: 原来只写日志,用户看到的是"点了没反应"
            report_preview_failure(self, PreviewFailure.NO_STYLE)
            return

        sound_key = f"death-{style_value}"
        sounds = getattr(self.audio_manager, "_sounds", {})

        if sound_key not in sounds:
            sound_file = find_audio_by_stem(
                getattr(self.audio_manager, "death_sounds_dir", ""),
                style_value,
                extensions=DEFAULT_AUDIO_EXTENSIONS,
            )
            if not sound_file:
                self.logger.warning(f"音效文件不存在: {style_value}.mp3/.wav/.ogg")
                report_preview_failure(self, PreviewFailure.NO_FILE, style_value)
                return

            self.audio_manager.load_sound(
                sound_key,
                sound_file,
                "death_sound",
                style=style_value,
            )

        self.logger.info(f"测试被击杀音效: {sound_key}")
        if not self.audio_manager.play_sound(sound_key):
            report_preview_failure(self, PreviewFailure.DEVICE, style_value)

    def _refresh_status_badge(self, *_args):
        enabled = bool(getattr(config, "death_sound_enabled", False))
        current_style = str(getattr(config, "death_sound_style", "0") or "0")
        style_enabled = is_style_enabled(current_style)
        available_count = len(getattr(self, "death_styles", []))

        health = collect_category_health(("death",))
        detail_tooltip = build_health_detail_tooltip(health)
        health_level = "success"
        if not health["ok"]:
            health_level = "danger"
        elif health["empty"]:
            health_level = "warn"

        badges = [
            ("success" if enabled else "warn", f"开关 · {'已启用' if enabled else '未启用'}"),
            (
                "success" if style_enabled else "info",
                f"样式 · {self._compact_text(current_style if style_enabled else '未选择')}",
            ),
            ("success" if available_count else "info", f"候选 · {available_count}"),
            (
                health_level,
                "资源 · 正常" if health["ok"] else f"资源 · 异常 {health['issue_count']}",
            ),
        ]

        detail_lines = [
            f"总开关：{'已启用' if enabled else '已关闭'}",
            f"当前样式：{current_style if style_enabled else self.DISABLED_STYLE_TEXT}",
            f"已扫描样式：{available_count}",
            "测试策略：按样式名匹配 death 目录中的同名音频文件",
        ]
        preview_names = self._style_preview_names()
        if preview_names:
            detail_lines.append(f"样式预览：{', '.join(preview_names)}")
        if detail_tooltip:
            detail_lines.append(detail_tooltip)

        summary_text = "\n".join(detail_lines)
        render_badges(self.status_badge_label, badges, detail_tooltip=summary_text)
        self.summary_label.setText(summary_text)
        self.summary_label.setToolTip(summary_text)
        self.status_card.setToolTip(summary_text)
        self._refresh_style_overview(enabled, style_enabled, current_style, available_count)
        if hasattr(self, "action_bar"):
            if style_enabled:
                action_message = (
                    f"当前样式：{current_style} · 已扫描 {available_count} 个候选；"
                    "新增素材后可直接刷新风格列表。"
                )
            else:
                action_message = (
                    f"当前未启用样式 · 已扫描 {available_count} 个候选；"
                    "可先打开资源目录补充音频，再回来刷新。"
                )
            self.action_bar.set_message(action_message)

    def _refresh_style_overview(self, enabled: bool, style_enabled: bool, current_style: str, available_count: int):
        current_name = current_style if style_enabled else self.DISABLED_STYLE_TEXT
        preview_names = self._style_preview_names(max_items=4)
        preview_text = " / ".join(preview_names) if preview_names else "还没有扫描到可用风格，可先补充素材后再刷新。"

        if hasattr(self, "selection_state_label"):
            if style_enabled:
                self.selection_state_label.setText(
                    f"当前已选择“{current_name}”，切换后可以直接点击测试确认实际听感。"
                )
            else:
                self.selection_state_label.setText(
                    "当前未启用被击杀音效，先选一个风格后再测试会更直观。"
                )

        if hasattr(self, "style_overview_name_label"):
            self.style_overview_name_label.setText(current_name)
        if hasattr(self, "style_overview_meta_label"):
            self.style_overview_meta_label.setText(
                f"总开关 {'开启' if enabled else '关闭'} · 候选 {available_count} 个"
            )
        if hasattr(self, "style_overview_hint_label"):
            self.style_overview_hint_label.setText(f"当前可见风格：{preview_text}")
        if hasattr(self, "resource_summary_label"):
            self.resource_summary_label.setText(
                "匹配规则：样式名 = 文件名主干；支持 mp3 / wav / ogg。"
                f" 当前目录已扫描 {available_count} 个候选。"
            )

    def _update_compact_layout(self):
        if not hasattr(self, "top_content_layout"):
            return
        direction = QBoxLayout.TopToBottom if self.width() < 1080 else QBoxLayout.LeftToRight
        if self.top_content_layout.direction() != direction:
            self.top_content_layout.setDirection(direction)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_compact_layout()
