#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio background task panel."""

from __future__ import annotations

from datetime import datetime

from core.audio_event_text import label_task_source, label_task_type
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.audio.audio_task_runner import get_audio_task_runner
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard
from widgets.page_header import PageHeader


class AudioTaskPanelPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("AudioTaskPanelPage")
        self.runner = get_audio_task_runner()
        self._active_task_id = ""
        self._active_reason = ""
        self._active_progress = 0
        self._active_message = ""
        self._last_result_success: bool | None = None
        self._last_result_message = ""
        self._init_ui()
        self._bind_runner_signals()
        self._reload_history()

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
            "音频任务面板",
            # RN-508：「后台音频任务」是实现词。用户不知道什么叫「任务」，
            #   但知道「我刚导入了一包音效」。⇒ 用它做的那几件事来说明它。
            description="导入音效包、刷新资源、重新载入音频这些要跑一会儿的事，都在这里看进度和结果。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        # ⚠ 批 45（RN-001b）：只往 `PAGE_HELP_TEXTS` 加一段是不够的 ——
        #   那颗「?」要每页自己装，否则表里有、屏幕上没有。
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["audio_task_panel"])

        card, card_layout = SettingsCard.make("当前状态")
        self.status_card = card

        self.status_badge_label = create_badge_label()
        card_layout.addWidget(self.status_badge_label)

        self.summary_label = QLabel("暂无任务")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.hide()
        self.status_label = self.summary_label
        card_layout.addWidget(self.summary_label)
        layout.addWidget(card)

        history_card, history_layout = SettingsCard.make(
            "任务历史",
            "已经跑完的后台任务：做了什么、成没成。正在跑的任务看「当前状态」。",
        )

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        # ⭐ 批 46：底栏那颗变身式主按钮撤掉之后，这一屏一颗主按钮都不剩，
        #   外审当场报「按钮平级、无视觉重心」。⇒ 把**第一步**升为主按钮，
        #   且**恒定不变**（不像底栏那颗随状态换词）。这一页的第一步是「刷新」：它是这张卡上唯一能推进的动作。
        self.refresh_btn = QPushButton("刷新")
        # ⚠ 主/次由 `_sync_first_step()` 按「有没有历史」定 ——
        #   批 46 第一版把「刷新」恒定为主，外审 6 发报
        #   「最抢眼的紫色主按钮是**无实质产出的**『刷新』，点后毫无反馈」：
        #   空状态下刷新确实刷不出任何东西，第一步是去产生一个任务。
        self.refresh_btn.setObjectName("secondaryButton")
        self.refresh_btn.setMinimumHeight(34)
        self.refresh_btn.clicked.connect(self._reload_history)
        action_row.addWidget(self.refresh_btn)
        action_row.addStretch()
        history_layout.addLayout(action_row)

        self.table = QTableWidget(0, 6)
        # RN-508：「原因」这一栏摆的是 `audio_import_wizard_manual` 这种内部名，
        #   而它答的其实是「这个任务是谁发起的」。表头跟着改成它真正回答的问题。
        self.table.setHorizontalHeaderLabels(
            ["任务编号", "做了什么", "谁发起的", "开始", "耗时(秒)", "结果"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(180)
        history_layout.addWidget(self.table)

        self.empty_history_label = QLabel("当前还没有后台音频任务历史，导入、刷新或重载完成后会自动显示在这里。")
        self.empty_history_label.setObjectName("hintLabel")
        self.empty_history_label.setAlignment(Qt.AlignCenter)
        self.empty_history_label.setWordWrap(True)
        self.empty_history_label.setMinimumHeight(96)
        history_layout.addWidget(self.empty_history_label)

        # Phase1-1.3: 空状态给一个明确的"下一步"入口，而不是一片留白
        self.empty_action_btn = QPushButton("前往资源导入向导")
        self.empty_action_btn.setFixedHeight(36)
        self.empty_action_btn.setMinimumWidth(170)
        self.empty_action_btn.clicked.connect(lambda: self._navigate_to_page("audio_import_wizard"))
        empty_action_row = QHBoxLayout()
        empty_action_row.addStretch(1)
        empty_action_row.addWidget(self.empty_action_btn)
        empty_action_row.addStretch(1)
        history_layout.addLayout(empty_action_row)

        layout.addWidget(history_card)
        layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(116)
        self.action_bar.primary_btn.setMinimumWidth(132)
        root.addWidget(self.action_bar, 0)

    def _select_latest_task(self):
        if self.table.rowCount() <= 0:
            return
        self.table.selectRow(0)

    def _sync_action_bar(self, history: list[dict]):
        if not hasattr(self, "action_bar"):
            return

        history_count = len(history)
        running = bool(self._active_task_id)
        # ⛔ RN-102（2026-09-04 批 46）：这里原来是 `configure_secondary("刷新历史",
        #   self._reload_history)`，而「任务历史」卡里那颗「刷新」绑的是同一个方法。
        # ⭐ 留卡内那颗（批 31 规则②：它作用的对象是那张卡里的历史列表）。
        self.action_bar.configure_secondary("", None, visible=False)
        self._sync_first_step(bool(history_count))

        # ⚠ 主按钮**保留** —— 它和这一族其它三页不同：
        #   「定位最新任务」是**底栏独有**的动作（卡内没有第二个入口），
        #   而且它只有一种文案（没历史时收起来，不换词）⇒ 不构成 RN-506 那个变身。
        # ⭐ **撤副本不等于清空底栏** —— 底栏独有的动作留着才是对的。
        if history_count:
            self.action_bar.configure_primary("定位最新任务", self._select_latest_task, visible=True)
        else:
            self.action_bar.configure_primary("", None, visible=False)

        if running:
            action_message = (
                f"当前任务：{self._active_task_id} · 进度 {self._active_progress}%"
                f" · {self._active_message or self._active_reason or '处理中'}"
            )
        elif history_count:
            latest = history[-1]
            result_text = "成功" if bool(latest.get("success", False)) else "失败"
            action_message = (
                f"最近任务：{latest.get('task_id', '')} · {result_text}"
                f" · 共 {history_count} 条历史，可直接定位到最新记录。"
            )
        else:
            action_message = "当前没有后台音频任务历史，可先刷新等待新任务写入。"
        self.action_bar.set_message(action_message)

    def _sync_first_step(self, has_history: bool):
        """⭐ 那一颗紫的必须是**当下的第一步**（批 44 RN-450 的裁定）。

        没有历史 ⇒ 刷新刷不出东西，第一步是**去产生一个任务**（跳导入向导）；
        有历史 ⇒ 第一步是刷新（看看有没有新的）。
        ⚠ 两个都是安全动作 ⇒ 不触碰 RN-506 那条线（安全 ↔ 破坏性）。
        """
        from page_theme_helper import style_as_primary_button, style_as_secondary_button

        first, other = ((self.refresh_btn, self.empty_action_btn) if has_history
                        else (self.empty_action_btn, self.refresh_btn))
        style_as_primary_button(first)
        style_as_secondary_button(other)
        for btn in (first, other):
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def _sync_status_strip(self, history: list[dict] | None = None):
        history = history if history is not None else self.runner.get_history(limit=150)
        history_count = len(history)
        latest = history[-1] if history else None
        running = bool(self._active_task_id)

        badges = [
            ("positive" if running else "info", f"任务 · {'运行中' if running else '空闲'}"),
            ("positive" if history_count else "warning", f"历史 · {history_count} 条"),
        ]

        if running:
            badges.append(
                ("positive" if self._active_progress >= 100 else "info", f"进度 · {self._active_progress}%")
            )
        else:
            # ⚠ 原来这里是「进度 · 待执行」——**没有任务在跑的时候，"进度"这一栏**
            #   **本身就没有意义**，而「待执行」听起来像「有个任务排着队」。
            #   ⭐ 一颗芯片要么携带信息，要么说清楚"现在没有这回事"。
            badges.append(("info", "进度 · 没有任务在跑"))

        if latest:
            latest_success = bool(latest.get("success", False))
            result_text = "成功" if latest_success else "失败"
            result_tone = "positive" if latest_success else "warning"
        elif self._last_result_success is not None:
            result_text = "成功" if self._last_result_success else "失败"
            result_tone = "positive" if self._last_result_success else "warning"
        else:
            result_text = "还没跑过"
            result_tone = "info"
        badges.append((result_tone, f"结果 · {result_text}"))

        if running:
            detail_text = (
                f"当前任务 {self._active_task_id} 正在执行，"
                f"进度 {self._active_progress}%：{self._active_message or self._active_reason or '处理中'}。"
            )
        elif latest:
            detail_text = (
                f"最近一次任务 {latest.get('task_id', '')} "
                f"{'成功' if bool(latest.get('success', False)) else '失败'}，"
                f"做了什么：{label_task_type(str(latest.get('task_type', '')))}，"
                f"谁发起的：{label_task_source(str(latest.get('reason', '')))}。"
            )
        else:
            detail_text = "当前没有正在执行的后台音频任务，可以在这里查看历史执行结果。"

        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.status_label.setToolTip(detail_text)
        self.status_card.setToolTip(detail_text)
        self._sync_action_bar(history)

    def _bind_runner_signals(self):
        self.runner.task_started.connect(self._on_task_started)
        self.runner.task_progress.connect(self._on_task_progress)
        self.runner.task_finished.connect(self._on_task_finished)

    def _on_task_started(self, task_id: str, reason: str):
        self._active_task_id = str(task_id or "")
        self._active_reason = str(reason or "")
        self._active_progress = 1
        self._active_message = "任务开始"
        self.status_label.setText(f"任务开始: {task_id} ({reason})")
        self._sync_status_strip()

    def _on_task_progress(self, task_id: str, progress: int, message: str):
        self._active_task_id = str(task_id or self._active_task_id)
        self._active_progress = int(progress or 0)
        self._active_message = str(message or "")
        self.status_label.setText(f"{task_id}: {progress}% - {message}")
        self._sync_status_strip()

    def _on_task_finished(self, task_id: str, success: bool, message: str):
        self._last_result_success = bool(success)
        self._last_result_message = str(message or "")
        self.status_label.setText(f"{task_id}: {'成功' if success else '失败'} - {message}")
        self._active_task_id = ""
        self._active_reason = ""
        self._active_progress = 0
        self._active_message = ""
        self._reload_history()

    def _navigate_to_page(self, page_id: str):
        """Phase1-1.3: 空状态按钮跳转到指定功能页（经主窗口导航）。"""
        win = self.window()
        try:
            ensure = getattr(win, "ensure_page_loaded", None)
            if callable(ensure):
                ensure(page_id)
            nav = getattr(win, "show_page", None)
            if callable(nav):
                nav(page_id)
        except Exception:
            pass

    def _reload_history(self):
        history = self.runner.get_history(limit=150)
        has_history = bool(history)
        self.table.setVisible(has_history)
        self.empty_history_label.setVisible(not has_history)
        if hasattr(self, "empty_action_btn"):
            self.empty_action_btn.setVisible(not has_history)
        self.table.setRowCount(len(history))
        for row, item in enumerate(reversed(history)):
            started_at = float(item.get("started_at", 0.0) or 0.0)
            started_text = ""
            if started_at > 0:
                started_text = datetime.fromtimestamp(started_at).strftime("%H:%M:%S")
            duration = float(item.get("duration", 0.0) or 0.0)
            result_text = "成功" if bool(item.get("success", False)) else "失败"
            if item.get("message"):
                result_text = f"{result_text}: {item.get('message')}"
            values = [
                str(item.get("task_id", "")),
                label_task_type(str(item.get("task_type", ""))),
                label_task_source(str(item.get("reason", ""))),
                started_text,
                f"{duration:.2f}",
                result_text,
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))

        if not self._active_task_id:
            self.status_label.setText(f"任务历史: {len(history)} 条")
        self._sync_status_strip(history)
