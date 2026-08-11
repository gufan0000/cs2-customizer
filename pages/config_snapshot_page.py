#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Config snapshot management page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import config
from core.config_snapshot_manager import create_snapshot, list_snapshots, prune_snapshots, restore_snapshot
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard
from widgets.page_header import PageHeader


class ConfigSnapshotPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("ConfigSnapshotPage")
        self._snapshots = []
        self._init_ui()
        self._reload()

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
        from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
        header = PageHeader(
            "配置快照",
            description="给当前设置「拍照」存档，改坏了随时一键回滚。点右上角「?」看用法。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["config_snapshot"])

        card, card_layout = SettingsCard.make("当前状态")
        self.status_card = card

        self.status_badge_label = create_badge_label()
        card_layout.addWidget(self.status_badge_label)

        self.summary_label = QLabel("暂无快照")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.hide()
        card_layout.addWidget(self.summary_label)
        layout.addWidget(card)

        actions_card, actions_layout = SettingsCard.make(
            "快照操作",
            "手动创建适合做版本节点，恢复前先确认选中的条目是否是你要回退的那一份。",
        )

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.create_btn = QPushButton("创建快照")
        self.create_btn.setObjectName("secondaryButton")
        self.create_btn.setMinimumHeight(34)
        self.create_btn.clicked.connect(self._create_snapshot)
        action_row.addWidget(self.create_btn)

        self.restore_btn = QPushButton("恢复选中")
        self.restore_btn.setObjectName("secondaryButton")
        self.restore_btn.setMinimumHeight(34)
        self.restore_btn.clicked.connect(self._restore_selected)
        action_row.addWidget(self.restore_btn)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setObjectName("secondaryButton")
        self.refresh_btn.setMinimumHeight(34)
        self.refresh_btn.clicked.connect(self._reload)
        action_row.addWidget(self.refresh_btn)
        action_row.addStretch()
        actions_layout.addLayout(action_row)
        layout.addWidget(actions_card)

        list_card, list_layout = SettingsCard.make(
            "快照列表",
            "列表按时间倒序展示，状态卡会同步显示当前选中的快照编号。",
        )

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "时间", "原因", "大小", "哈希"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._sync_status_strip)
        list_layout.addWidget(self.table)

        layout.addWidget(list_card)
        layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(116)
        self.action_bar.primary_btn.setMinimumWidth(132)
        root.addWidget(self.action_bar, 0)

    def _compact_snapshot_id(self, snapshot_id: str) -> str:
        snapshot_id = str(snapshot_id or "").strip()
        if not snapshot_id:
            return "未选择"
        if len(snapshot_id) <= 14:
            return snapshot_id
        return snapshot_id[:14] + "…"

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        snapshot_count = len(self._snapshots)
        selected_id = self._selected_snapshot_id()
        self.action_bar.configure_secondary("刷新快照", self._reload, visible=True)

        if selected_id:
            self.action_bar.configure_primary("恢复选中", self._restore_selected, visible=True)
            action_message = (
                f"当前选中：{self._compact_snapshot_id(selected_id)} · 共 {snapshot_count} 份快照，"
                "恢复前请确认这就是要回退的版本。"
            )
        else:
            self.action_bar.configure_primary("创建快照", self._create_snapshot, visible=True)
            action_message = (
                f"当前共有 {snapshot_count} 份快照 · 还没有选中条目，"
                "适合先创建一个新的安全点再继续调整。"
            )
        self.action_bar.set_message(action_message)

    def _sync_status_strip(self):
        snapshot_count = len(self._snapshots)
        keep_count = int(getattr(config, "config_snapshot_max_keep", 20) or 20)
        selected_id = self._selected_snapshot_id()

        badges = [
            ("positive" if snapshot_count else "warning", f"状态 · {'已有快照' if snapshot_count else '暂无快照'}"),
            ("positive" if snapshot_count else "warning", f"快照 · {snapshot_count} 份"),
            ("info", f"保留 · {keep_count} 份"),
            ("info" if selected_id else "warning", f"选中 · {self._compact_snapshot_id(selected_id)}"),
        ]

        latest_snapshot = self._snapshots[0] if self._snapshots else None
        latest_text = (
            f"最新快照：{latest_snapshot.snapshot_id}（{latest_snapshot.created_at}）"
            if latest_snapshot
            else "当前还没有可恢复的配置快照。"
        )
        detail_text = (
            f"当前共有 {snapshot_count} 份配置快照，保留上限 {keep_count} 份。"
            f"{latest_text}"
        )
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.summary_label.setText(
            f"快照数: {snapshot_count} · 保留上限 {keep_count} · 选中 {selected_id or '无'}"
        )
        self.summary_label.setToolTip(detail_text)
        if hasattr(self, "status_card"):
            self.status_card.setToolTip(detail_text)
        self._sync_action_bar()

    def _reload(self):
        self._snapshots = list_snapshots()
        self.table.setRowCount(len(self._snapshots))
        for row, snap in enumerate(self._snapshots):
            values = [snap.snapshot_id, snap.created_at, snap.reason, str(snap.size), snap.sha256[:16]]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self._sync_status_strip()

    def _selected_snapshot_id(self) -> str:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._snapshots):
            return ""
        return self._snapshots[row].snapshot_id

    def _create_snapshot(self):
        try:
            snap = create_snapshot("manual_page")
            prune_snapshots(int(getattr(config, "config_snapshot_max_keep", 20) or 20))
            self._reload()
            QMessageBox.information(self, "成功", f"快照已创建\n{snap.snapshot_id}")
        except Exception as exc:
            QMessageBox.warning(self, "失败", f"创建快照失败: {exc}")

    def _restore_selected(self):
        snapshot_id = self._selected_snapshot_id()
        if not snapshot_id:
            QMessageBox.information(self, "提示", "请先选中一条快照。")
            return
        # UP-075: 此前点一下就直接覆盖 config.json,没有任何确认。
        reply = QMessageBox.question(
            self,
            "确认恢复",
            f"将用快照 {snapshot_id} 覆盖当前配置。\n\n"
            "恢复前会自动为当前配置建一张快照，事后可以再恢复回来。\n\n确定继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # ⚠ 必须在**恢复之前**读保留上限：restore 会把 config 换成快照里的内容，
        # 恢复后再读就成了「用被恢复快照里的 max_keep 去删用户当前的快照历史」——
        # 用户现在设的是 20、快照里存的是 2 的话，一次恢复会顺手删掉 4 份历史快照。
        keep = int(getattr(config, "config_snapshot_max_keep", 20) or 20)

        result = restore_snapshot(snapshot_id)
        if result.ok:
            try:
                prune_snapshots(keep)
            except Exception:
                pass
            if result.backup_id:
                tail = f"\n\n恢复前的配置已存为快照: {result.backup_id}"
            else:
                # 如实告知——别让用户以为后悔药一定在
                tail = "\n\n注意：未能为恢复前的配置建立快照，此次恢复无法撤销。"
            if result.error:
                # ok=True 但带 error = 文件换好了、内存重载没成功，必须说出来
                tail += f"\n\n⚠ {result.error}"
            QMessageBox.information(self, "恢复成功", f"已恢复到快照: {snapshot_id}{tail}")
            self._reload()
        else:
            # 失败时也要把后悔药 id 说出来：失败路径同样可能已经建了快照
            extra = f"\n\n恢复前的配置已存为快照: {result.backup_id}" if result.backup_id else ""
            QMessageBox.warning(self, "恢复失败", f"{result.error or '未知错误'}{extra}")
            self._reload()
