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
            "软件设置快照",
            # ⚠⚠ 批 45 改完复跑逮到，**外审 9/9 判高**：这句原来只说
            # （⛔ 这里**故意不写那条还开着的 RN 号** —— 产品代码点名一条未结条目，
            #   那个指针会跟着状态一起过期，而
            #   `test_product_code_that_names_an_rn_is_not_still_open` 正是为此存在。
            #   要查这一条的去向，从档案 `X_补齐清单不等于补齐那件事.md` 走。）
            #   「给**当前设置**『拍照』存档」——而「当前设置」指谁的设置？
            #   外审 9 发全部报同一句：不知道备份的是**软件自己的配置**还是
            #   **CS2 游戏内参数**（键位/准星/画质），「玩家因担心游戏参数被覆盖
            #   而不敢操作」。
            # ⭐⭐ 正确的说法**一直存在** —— 帮助文案里逐字写着「快照存的是设置本身
            #   （config.json），不含音频 / 图片素材」。而它在**折叠面板里**，
            #   要点「?」才看得到。
            #   ⇒ 这就是 RN-131 那条：**一句只在模态框/折叠面板里出现过的说明，
            #     等于没有说明。**
            # ⛔ 不写「不会影响游戏」这种承诺 —— 只说我们**存了什么、不动什么**
            #   （RN-011 / RN-254：描述我们做了什么，不承诺别人会怎样）。
            # ⚠ 这里是 QLabel 纯文本，**不许用 `**` 那种 Markdown 加粗** ——
            #   它不会渲染成粗体，会原样显示两个星号（我第一版就这么写的）。
            description=("给这个软件自己的设置「拍照」存档（就是 config.json），"
                         "改坏了随时一键回滚；不碰 CS2 里的任何游戏配置。"
                         "点右上角「?」看用法。"),
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
        # ⚠⚠ **这一颗我撤过一次，外审 12/12 判高，改完复跑当场逮住。**
        #   撤的理由是批 31 规则②「留离它作用的对象最近的那一颗」，
        #   我判断「创建快照作用的对象是**当前设置**，跟这张卡没有比底栏更近的关系」。
        #   ⭐⭐⭐ **判错了：那张卡的副标题就是它的语境** ——
        #     副标题逐字写着「**手动创建**适合做版本节点」，
        #     而撤掉这颗之后，卡里说了「创建」、卡里却没有创建按钮。
        #     外审 12 发全部报同一句：「文案提示『手动创建』，卡片内却只有
        #     置灰的『恢复选中』与『刷新』，核心动作被孤立在右下角底栏」。
        #   ⭐⭐ **我撤掉一颗按钮，让它旁边那句话变成了假话**（批 43 RN-502 同形第二次）。
        # ⇒ 三个动作全留卡内，底栏**不放按钮**、只留回执（同批 31 在 voice_output 的处置）。
        #   这一颗是这一页的主动作 ⇒ 它就是这一屏唯一那颗紫的。
        self.create_btn = QPushButton("创建快照")
        self.create_btn.setObjectName("primaryButton")
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

        # ⛔ RN-102（批 45 撤除）：这里原来是 `configure_secondary("刷新快照", …)`，
        #   而「快照操作」卡里就有一颗「刷新」绑着同一个 `_reload`。
        #   ⭐ 底栏那颗是**纯副本**：它不携带任何卡内那颗没有的信息。
        self.action_bar.configure_secondary("", None, visible=False)

        # ⭐⭐⭐ RN-506（批 45）：这颗主按钮原来是**状态相关**的 ——
        #   没选中时是「创建快照」，选中一行之后**同一个像素**变成「恢复选中」。
        #   而这两个动作的性质是相反的：创建是多存一份（安全），
        #   恢复会**覆盖用户当前的全部设置**（本页自己的回执写着
        #   「恢复前请确认这就是要回退的版本」）。
        #   ⭐⭐⭐ **肌肉记忆记的是位置，不是文案** —— 一个刚点过「创建」的人，
        #     选中一行之后在同一个位置按下去，按到的是「恢复」。
        # ⇒ 底栏**一颗按钮都不放**：三个动作全留在「快照操作」卡里
        #   （那张卡的副标题就是它们的语境 —— 撤走任何一颗都会让副标题变成假话）。
        #   底栏只留回执，它本来就是干这个的。
        # ⚠ 这不是 RN-139（一屏两颗紫的）那一族，方向相反：
        #   它只有一颗紫的，而**那一颗的含义会变**。
        self.action_bar.configure_primary("", None, visible=False)

        if selected_id:
            action_message = (
                f"当前选中：{self._compact_snapshot_id(selected_id)} · 共 {snapshot_count} 份快照；"
                f"要回退就点上面「快照操作」里的「{self.restore_btn.text()}」——"
                "恢复前请确认这就是要回退的版本。"
            )
        else:
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
            else "当前还没有可恢复的设置快照。"
        )
        detail_text = (
            f"当前共有 {snapshot_count} 份设置快照，保留上限 {keep_count} 份。"
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
