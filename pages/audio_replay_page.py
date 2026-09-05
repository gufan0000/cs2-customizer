#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio replay diagnostics page."""

from __future__ import annotations

import json
import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
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
from core.audio_event_text import (
    ACTION_LABELS,
    label_action,
    label_event,
    label_reason,
    label_result,
)
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
        from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
        header = PageHeader(
            "音频事件回放",
            # RN-508：原文是「方便快速验证筛选条件、动作链和重放结果」——
            #   「动作链」「验证筛选条件」是开发排错的说法，外审 3/3 报
            #   「玩家完全无法理解这界面与配音效有什么关系」。
            #   ⇒ 说它能回答的那个问题：**刚才那一下为什么没响。**
            description="刚才那个音效为什么没响？这里能看到它到底播了、被顶掉了还是没找到文件。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        # ⚠ 批 45（RN-001b）：只往 `PAGE_HELP_TEXTS` 加一段是不够的 ——
        #   那颗「?」要每页自己装，否则表里有、屏幕上没有。
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["audio_replay"])

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

        # ⭐⭐⭐ RN-508（2026-09-05 批 48）：这三个筛选原来是**自由输入框**，
        #   提示语分别写着 `play/drop/preempt/load`、`kill/headshot/c4/...`、
        #   「按 key 子串过滤」—— 屏幕上摆的是给写代码的人看的词。
        # ⚠⚠ 而中间那条**给的例子一行都匹配不上**：`event_type` 的真实取值是
        #   `kill_voice` / `round_sounds` / `health_warning` 这一类，筛选做的是
        #   **精确比较**，照着提示语输 `kill` 或 `c4` 永远返回 0 条。
        #   ⭐ 而「筛选不出东西」看起来完全像「本来就没有这种事件」。
        # ⇒ 前两个改**下拉**：动作是闭集（词表在 `core/audio_event_text`），
        #   事件从**当前真有的记录**里生成 —— 用户不必知道拼写，
        #   也**不可能选到一个匹配不上的值**。
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("动作"))
        self.action_combo = QComboBox()
        self.action_combo.addItem("全部", "")
        for value, label in ACTION_LABELS.items():
            self.action_combo.addItem(label, value)
        self.action_combo.setFixedWidth(130)
        self.action_combo.setFixedHeight(34)
        filter_row.addWidget(self.action_combo)
        filter_row.addWidget(QLabel("事件"))
        self.event_combo = QComboBox()
        self.event_combo.addItem("全部", "")
        self.event_combo.setFixedWidth(150)
        self.event_combo.setFixedHeight(34)
        filter_row.addWidget(self.event_combo)
        filter_row.addWidget(QLabel("音效名"))
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("输入一段音效名搜索，留空为全部")
        self.key_edit.setFixedWidth(180)
        self.key_edit.setFixedHeight(34)
        filter_row.addWidget(self.key_edit)
        filter_row.addStretch()
        filter_layout.addLayout(filter_row)

        # ⚠ 这三个筛选**原来一根线都没接**：改完要再点一次「刷新」才生效，
        #   而这张卡的副标题逐字写着「动作、事件和关键字筛选会影响当前列表」——
        #   ⭐ 那句话在接上线之前是假的（同 RN-502 那一族：卡片副标题就是承诺）。
        #   自由输入时这还能靠「输完总要点一下」蒙混过去；换成下拉之后，
        #   选完没反应就是明显的坏掉。⇒ 接上，让那句话成真。
        self.action_combo.currentIndexChanged.connect(self._refresh_events)
        self.event_combo.currentIndexChanged.connect(self._refresh_events)
        self.key_edit.textChanged.connect(self._refresh_events)

        # 2.2.0 排版修复:原先筛选+按钮挤一行(min 宽 1061px),默认 1200 窗口即横滚。
        # 拆两行后整页最小宽 ≤660,紧凑模式(860 窗)也不再出横向滚动条。
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addStretch()

        # ⭐ 批 46：底栏那颗变身式主按钮撤掉之后，这一屏一颗主按钮都不剩，
        #   外审当场报「按钮平级、无视觉重心」。⇒ 把**第一步**升为主按钮，
        #   且**恒定不变**（不像底栏那颗随选中状态换词）。
        #   这一页的第一步是「刷新」：先把最近的事件取回来，才谈得上筛选/重放/导出。
        self.refresh_btn = QPushButton("刷新")
        # ⚠ 主/次由 `_sync_first_step()` 定：一条记录都没有时，刷新刷不出东西，
        #   第一步在空状态卡里（去试听一次）；有记录了刷新才是第一步。
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

        # Phase1-1.3: 空状态提供直接动作，避免大片留白没有出路。
        # ⚠⚠ 但它原来写的是「立即刷新事件」，绑 `_refresh_events` ——
        #   那是这一页**第三个**刷新入口（筛选卡一颗、底栏一颗、这里一颗），
        #   而且**答非所问**：上面那句空状态文案说的出路是
        #   「可以先**放宽筛选条件**或等待新的事件写入」，两条都不是「刷新」。
        # ⭐⭐ **空状态该给的，是它自己那句话点名的那个动作。**
        # ⛔ 不是撤掉了事：批 3 的空库引导先例 —— 空状态要有直接出路，
        #   只留一段话等于把人留在原地。
        self.empty_refresh_btn = QPushButton("清空筛选条件")
        self.empty_refresh_btn.setObjectName("secondaryButton")
        self.empty_refresh_btn.setFixedHeight(36)
        self.empty_refresh_btn.setMinimumWidth(150)
        self.empty_refresh_btn.clicked.connect(self._clear_filters)

        # ⚠⚠ 另一态的出路完全不同：**一条记录都还没有**时，清筛选没用、
        #   刷新也没用 —— 事件只有在真的播过一次音效之后才会写进来。
        #   外审 6 发逐字报「无一键测试或跳转引导导致操作断流」。
        # ⭐ 空状态该给的是**能产生第一条记录**的那条路。
        self.empty_goto_btn = QPushButton("去「击杀音效」试听一次")
        self.empty_goto_btn.setObjectName("primaryButton")
        self.empty_goto_btn.setFixedHeight(36)
        self.empty_goto_btn.setMinimumWidth(170)
        self.empty_goto_btn.clicked.connect(
            lambda: self._navigate_to_page("kill_sound"))
        empty_btn_row = QHBoxLayout()
        empty_btn_row.addStretch(1)
        empty_btn_row.addWidget(self.empty_goto_btn)
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

    def showEvent(self, event):
        """重新显示这一页时自动取一次最新记录（RN-520）。

        ⭐ 空状态那颗按钮把玩家送去「击杀音效」试听，**回来还得自己点刷新** ——
        外审 3/3 逐字报这条动线是断的。回到本页本身就是「我试完了」的信号。
        ⛔ 没有用定时器：那会让这一页的内容取决于「快照拍在第几秒」，
          等于把 RN-146 那类不确定性再引进来一次。重新显示是一个**确定的时刻**。
        """
        super().showEvent(event)
        try:
            self._refresh_events()
        except Exception:
            self.logger.exception("回放页重新显示时刷新失败")

    def _current_action(self) -> str:
        """下拉里选中的动作（内部值）。「全部」是空串。"""
        return str(self.action_combo.currentData() or "")

    def _current_event_type(self) -> str:
        return str(self.event_combo.currentData() or "")

    def _sync_event_choices(self):
        """事件下拉的选项**从真有的记录里生成**。

        ⭐ 这样用户不可能选到一个匹配不上的值 —— 而原来那条自由输入的提示语
        （`kill/headshot/c4/...`）给的例子恰恰一条都匹配不上（RN-508）。
        ⚠ 取的是**不带筛选**的全量，否则选中一个事件之后列表变短，
          下拉里就只剩它自己，等于把别的选项锁死。
        """
        try:
            everything = self.timeline.query(limit=500, filters={})
        except Exception:
            everything = list(self._events)
        present = sorted({str(e.event_type or "") for e in everything if e.event_type})
        keep = self._current_event_type()
        self.event_combo.blockSignals(True)
        self.event_combo.clear()
        self.event_combo.addItem("全部", "")
        for value in present:
            self.event_combo.addItem(label_event(value), value)
        index = self.event_combo.findData(keep)
        self.event_combo.setCurrentIndex(index if index >= 0 else 0)
        self.event_combo.blockSignals(False)

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

        # RN-508：屏幕上一律显示人话；`label_*` 认不出来就原样交出去。
        action_text = label_action(self._current_action())
        event_text = label_event(self._current_event_type())
        key_text = self.key_edit.text().strip()
        selected_event = self._selected_event()

        # ⛔ RN-102 / RN-506（2026-09-04 批 46）：底栏这两颗**全是副本**——
        #   「刷新事件」与「筛选与操作」卡里那颗「刷新」是同一个方法；
        #   而主按钮随选中状态在「重放选中」与「导出 JSON」之间变身，
        #   这两个动作卡内也都有。
        # ⭐⭐ 肌肉记忆记的是位置 —— 同一个位置两种含义。
        # ⇒ 底栏不放按钮，三个动作全留「筛选与操作」卡（副标题就是语境）。
        self.action_bar.configure_secondary("", None, visible=False)
        self.action_bar.configure_primary("", None, visible=False)
        if selected_event is not None:
            action_message = (
                f"当前筛选：动作 {action_text or '全部'} / 事件 {event_text or '全部'} / 关键字 {key_text or '全部'}"
                f" · 已选中 {self._compact_event_value(selected_event.key)}"
            )
        else:
            action_message = (
                f"当前筛选：动作 {action_text or '全部'} / 事件 {event_text or '全部'} / 关键字 {key_text or '全部'}"
                f" · 共 {len(self._events)} 条结果；要导出就点上面「筛选与操作」里的"
                f"「{self.export_btn.text()}」。"
            )
        self.action_bar.set_message(action_message)

    def _sync_status_strip(self):
        # RN-508：屏幕上一律显示人话；`label_*` 认不出来就原样交出去。
        action_text = label_action(self._current_action())
        event_text = label_event(self._current_event_type())
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
        if self._current_action():
            filters["action"] = self._current_action()
        if self._current_event_type():
            filters["event_type"] = self._current_event_type()
        if self.key_edit.text().strip():
            filters["key_contains"] = self.key_edit.text().strip()
        return filters

    def _navigate_to_page(self, page_id: str):
        """跳到能产生音频事件的地方（经主窗口导航，同 `audio_task_panel`）。"""
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

    def _sync_first_step(self, has_events: bool):
        """⭐ 那一颗紫的必须是**当下的第一步**（批 44 RN-450 的裁定）。"""
        from page_theme_helper import style_as_primary_button, style_as_secondary_button

        if has_events:
            style_as_primary_button(self.refresh_btn)
        else:
            style_as_secondary_button(self.refresh_btn)
        self.refresh_btn.style().unpolish(self.refresh_btn)
        self.refresh_btn.style().polish(self.refresh_btn)
        self.refresh_btn.update()

    def _clear_filters(self):
        """把三个筛选框清空并重新取一遍 —— 空状态那句话点名的那条出路。"""
        self.action_combo.setCurrentIndex(0)
        self.event_combo.setCurrentIndex(0)
        self.key_edit.clear()
        self._refresh_events()

    def _refresh_events(self):
        self._events = self.timeline.query(limit=500, filters=self._build_filters())
        self._sync_event_choices()
        has_events = bool(self._events)
        self.table.setVisible(has_events)
        self.empty_results_label.setVisible(not has_events)
        # ⚠⚠ 空状态有**两种**，出路完全不同，而原来只写了一种。
        #   批 46 外审 3/3 判高：「首次进入无数据却提示『放宽筛选条件』，
        #   完全未说明如何产生数据」。⭐ 而我第一版把按钮从「立即刷新事件」
        #   换成「清空筛选条件」时**没分这两态** —— 首次进入根本没有筛选可清，
        #   ⭐⭐⭐ 于是我用一个**更精确的错答案**替换了一个不精确的错答案。
        # ⇒ 有筛选 ⇒ 出路是清空它；没筛选 ⇒ 出路是**去产生一条记录**
        #   （事件由 `audio_manager` 在真的播了一次音效时写入）。
        filtering = bool(self._build_filters())
        self._sync_first_step(has_events)
        if not has_events:
            if filtering:
                self.empty_results_label.setText(
                    "当前筛选条件下没有音频事件。放宽或清掉筛选条件再看看。")
            else:
                self.empty_results_label.setText(
                    "还没有任何音频事件。软件每真的播一次音效就会在这里留一条记录 —— "
                    # ⚠ 这句原来写「再回来刷新」，而本批已改成**回到这一页就自动取一次**
                    #   （`showEvent`）。⭐ 我改了行为，而描述它的这句话留在原地 ——
                    #   同一形态第三次（批 45 撤按钮 / 批 48 改按钮名 / 这次改行为）。
                    "进游戏打一局，或者先去「击杀音效」点一次「试听」；本页每次重新打开都会自动取最新记录。")
        if hasattr(self, "empty_refresh_btn"):
            self.empty_refresh_btn.setVisible(not has_events and filtering)
        if hasattr(self, "empty_goto_btn"):
            self.empty_goto_btn.setVisible(not has_events and not filtering)
        self.table.setRowCount(len(self._events))
        for row, event in enumerate(self._events):
            ts = datetime.fromtimestamp(event.timestamp).strftime("%H:%M:%S.%f")[:-3]
            # RN-508：这几列原来是原样的蛇形英文与 OK/FAIL。
            # 认不出来的值**原样交出去**，不假装认识（`label_*` 自己保证）。
            values = [
                ts,
                label_action(event.action),
                label_event(event.event_type),
                label_event(event.channel_type),
                event.key,
                label_reason(event.reason),
                label_result(bool(event.success)),
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
