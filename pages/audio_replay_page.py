#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audio replay diagnostics page."""

from __future__ import annotations

import json
import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.audio.audio_event_timeline import AudioEvent, get_audio_event_timeline
from core.audio.runtime_audio import get_runtime_audio_manager
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from resource_manager import ResourceManager
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard
from widgets.page_header import PageHeader


class AudioReplayPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("AudioReplayPage")
        self.timeline = get_audio_event_timeline()
        self._events: list[AudioEvent] = []
        self._init_ui()
        self._refresh_events()

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
            "音频事件回放",
            description="这里用来回看最近记录下来的音频事件，方便快速验证筛选条件、动作链和重放结果。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)

        card, card_layout = SettingsCard.make("当前状态")
        self.status_card = card

        self.status_badge_label = create_badge_label()
        card_layout.addWidget(self.status_badge_label)

        self.summary_label = QLabel("暂无事件")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.hide()
        card_layout.addWidget(self.summary_label)
        layout.addWidget(card)

        filter_card, filter_layout = SettingsCard.make(
            "筛选与操作",
            "动作、事件和关键字筛选会影响当前列表；重放与导出都只针对当前筛选结果。",
        )

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("动作"))
        self.action_edit = QLineEdit()
        self.action_edit.setPlaceholderText("play/drop/preempt/load")
        self.action_edit.setFixedWidth(130)
        self.action_edit.setFixedHeight(34)
        filter_row.addWidget(self.action_edit)
        filter_row.addWidget(QLabel("事件"))
        self.event_edit = QLineEdit()
        self.event_edit.setPlaceholderText("kill/headshot/c4/...")
        self.event_edit.setFixedWidth(150)
        self.event_edit.setFixedHeight(34)
        filter_row.addWidget(self.event_edit)
        filter_row.addWidget(QLabel("关键字"))
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("按 key 子串过滤")
        self.key_edit.setFixedWidth(180)
        self.key_edit.setFixedHeight(34)
        filter_row.addWidget(self.key_edit)
        filter_row.addStretch()
        filter_layout.addLayout(filter_row)

        # 2.2.0 排版修复:原先筛选+按钮挤一行(min 宽 1061px),默认 1200 窗口即横滚。
        # 拆两行后整页最小宽 ≤660,紧凑模式(860 窗)也不再出横向滚动条。
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addStretch()

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setObjectName("secondaryButton")
        self.refresh_btn.setMinimumHeight(34)
        self.refresh_btn.clicked.connect(self._refresh_events)
        action_row.addWidget(self.refresh_btn)

        self.replay_btn = QPushButton("重放选中")
        self.replay_btn.setObjectName("secondaryButton")
        self.replay_btn.setMinimumHeight(34)
        self.replay_btn.clicked.connect(self._replay_selected)
        action_row.addWidget(self.replay_btn)

        self.export_btn = QPushButton("导出 JSON")
        self.export_btn.setObjectName("secondaryButton")
        self.export_btn.setMinimumHeight(34)
        self.export_btn.clicked.connect(self._export_json)
        action_row.addWidget(self.export_btn)
        filter_layout.addLayout(action_row)
        layout.addWidget(filter_card)

        table_card, table_layout = SettingsCard.make(
            "事件列表",
            "结果按时间倒序显示，适合先筛选后重放，快速定位某一次具体触发。",
        )

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["时间", "动作", "事件", "通道", "键", "原因", "结果"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._sync_status_strip)
        self.table.setMinimumHeight(220)
        table_layout.addWidget(self.table)

        self.empty_results_label = QLabel("当前筛选条件下还没有音频事件结果，可以先放宽筛选条件或等待新的事件写入。")
        self.empty_results_label.setObjectName("hintLabel")
        self.empty_results_label.setAlignment(Qt.AlignCenter)
        self.empty_results_label.setWordWrap(True)
        self.empty_results_label.setMinimumHeight(110)
        table_layout.addWidget(self.empty_results_label)

        # Phase1-1.3: 空状态提供直接动作，避免大片留白没有出路
        self.empty_refresh_btn = QPushButton("立即刷新事件")
        self.empty_refresh_btn.setFixedHeight(36)
        self.empty_refresh_btn.setMinimumWidth(150)
        self.empty_refresh_btn.clicked.connect(self._refresh_events)
        empty_btn_row = QHBoxLayout()
        empty_btn_row.addStretch(1)
        empty_btn_row.addWidget(self.empty_refresh_btn)
        empty_btn_row.addStretch(1)
        table_layout.addLayout(empty_btn_row)
        layout.addWidget(table_card)
        layout.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(116)
        self.action_bar.primary_btn.setMinimumWidth(132)
        root.addWidget(self.action_bar, 0)

    def _format_filter_badge(self, prefix: str, value: str, fallback: str = "全部") -> str:
        compact = value.strip() or fallback
        if len(compact) > 12:
            compact = compact[:11] + "…"
        return f"{prefix} · {compact}"

    def _compact_event_value(self, text: str, fallback: str = "未选择", max_length: int = 16) -> str:
        value = str(text or "").strip() or fallback
        if len(value) > max_length:
            return value[: max_length - 1] + "…"
        return value

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        action_text = self.action_edit.text().strip()
        event_text = self.event_edit.text().strip()
        key_text = self.key_edit.text().strip()
        selected_event = self._selected_event()

        self.action_bar.configure_secondary("刷新事件", self._refresh_events, visible=True)
        if selected_event is not None:
            self.action_bar.configure_primary("重放选中", self._replay_selected, visible=True)
            action_message = (
                f"当前筛选：动作 {action_text or '全部'} / 事件 {event_text or '全部'} / 关键字 {key_text or '全部'}"
                f" · 已选中 {self._compact_event_value(selected_event.key)}"
            )
        else:
            self.action_bar.configure_primary("导出 JSON", self._export_json, visible=True)
            action_message = (
                f"当前筛选：动作 {action_text or '全部'} / 事件 {event_text or '全部'} / 关键字 {key_text or '全部'}"
                f" · 共 {len(self._events)} 条结果，可直接导出。"
            )
        self.action_bar.set_message(action_message)

    def _sync_status_strip(self):
        action_text = self.action_edit.text().strip()
        event_text = self.event_edit.text().strip()
        key_text = self.key_edit.text().strip()

        badges = [
            ("positive" if self._events else "warning", f"记录 · {len(self._events)} 条"),
            ("info" if not action_text else "positive", self._format_filter_badge("动作", action_text)),
            ("info" if not event_text else "positive", self._format_filter_badge("事件", event_text)),
            ("info" if not key_text else "positive", self._format_filter_badge("关键字", key_text)),
        ]

        compact_parts = [
            f"{len(self._events)} 条",
            f"动作{action_text or '全部'}",
            f"事件{event_text or '全部'}",
            f"关键字{key_text or '全部'}",
        ]
        detail_text = (
            f"当前筛选结果共 {len(self._events)} 条事件。"
            f"动作筛选：{action_text or '全部'}；"
            f"事件筛选：{event_text or '全部'}；"
            f"关键字筛选：{key_text or '全部'}。"
        )
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.summary_label.setText(" · ".join(compact_parts))
        self.summary_label.setToolTip(detail_text)
        if hasattr(self, "status_card"):
            self.status_card.setToolTip(detail_text)
        self._sync_action_bar()

    def _build_filters(self):
        filters = {}
        if self.action_edit.text().strip():
            filters["action"] = self.action_edit.text().strip()
        if self.event_edit.text().strip():
            filters["event_type"] = self.event_edit.text().strip()
        if self.key_edit.text().strip():
            filters["key_contains"] = self.key_edit.text().strip()
        return filters

    def _refresh_events(self):
        self._events = self.timeline.query(limit=500, filters=self._build_filters())
        has_events = bool(self._events)
        self.table.setVisible(has_events)
        self.empty_results_label.setVisible(not has_events)
        if hasattr(self, "empty_refresh_btn"):
            self.empty_refresh_btn.setVisible(not has_events)
        self.table.setRowCount(len(self._events))
        for row, event in enumerate(self._events):
            ts = datetime.fromtimestamp(event.timestamp).strftime("%H:%M:%S.%f")[:-3]
            values = [
                ts,
                event.action,
                event.event_type,
                event.channel_type,
                event.key,
                event.reason,
                "OK" if event.success else "FAIL",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        self._sync_status_strip()

    def _selected_event(self) -> AudioEvent | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._events):
            return None
        return self._events[row]

    def _replay_selected(self):
        event = self._selected_event()
        if event is None:
            QMessageBox.information(self, "提示", "请先选中一条事件记录。")
            return
        manager = get_runtime_audio_manager()
        result = self.timeline.replay([event], manager)
        QMessageBox.information(
            self,
            "重放完成",
            f"请求: {result.get('requested', 0)}\n成功: {result.get('played', 0)}\n失败: {result.get('failed', 0)}",
        )

    def _export_json(self):
        default_dir = ResourceManager.get_app_data_path("logs")
        os.makedirs(default_dir, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出音频事件",
            os.path.join(default_dir, "audio_replay_timeline.json"),
            "JSON 文件 (*.json)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump([event.to_dict() for event in self._events], handle, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "导出成功", f"已导出 {len(self._events)} 条事件\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"{exc}")
