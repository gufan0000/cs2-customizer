#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Resource health diagnostics page."""

from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.resource_health import (
    apply_conservative_resource_fix,
    collect_resource_system_health,
    format_resource_system_health,
)
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from resource_manager import ResourceManager
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard
from widgets.page_header import PageHeader


class AudioHealthPage(QWidget):
    """Diagnostics and conservative repair page for app resources."""

    # 后台体检完成信号（worker线程 → 主线程渲染）
    _health_report_ready = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("AudioHealthPage")
        self._last_report = None
        self._health_checking = False
        self._init_ui()
        self._health_report_ready.connect(self._on_health_report_ready)
        # 对标修缮：体检的全盘资源扫描原在 UI 线程同步执行，导致切到本页
        # 卡顿 >1.5s（审查实测）。改为后台线程 + 占位文案，切页即时响应。
        self._run_health_check()

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
            "资源体检",
            # ⚠ RN-509 改完复跑逼出来的第二刀：把侧栏从「音频体检」改成「资源体检」之后，
            #   行为题（击杀图标不出现的玩家会不会来这一页）**只在紧凑档翻了身**，
            #   完整档 4/4 仍答「不会」—— 理由逐字指向这一句：它只举了「音效不响」一个例子，
            #   于是这一页又被框回声音。⭐ **改了容器的名字，里面那句话还在替旧名字说话。**
            description=("检查音效和图片素材是不是齐的 —— 音效不响、击杀图标不出现，"
                         "都先来这儿查一遍。点右上角「?」看用法。"),
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["audio_health"])

        card, card_layout = SettingsCard.make("当前状态")
        self.status_card = card

        self.status_badge_label = create_badge_label()
        card_layout.addWidget(self.status_badge_label)

        self.summary_label = QLabel("等待体检结果...")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        card_layout.addWidget(self.summary_label)
        layout.addWidget(card)

        actions_card, actions_layout = SettingsCard.make(
            "体检与修复",
            # RN-508：按钮已改名成「一键修复（只补不删）」，这句话得跟着说人话。
            "先体检，看清楚缺什么，再决定要不要让软件把缺的目录补上；导出报告适合留档或发给我继续排查。",
        )

        actions = QHBoxLayout()
        # ⭐ 批 46：底栏那颗变身式主按钮撤掉之后，这一屏一颗主按钮都不剩，
        #   外审当场报「按钮平级、无视觉重心」。⇒ 把**第一步**升为主按钮，
        #   且**恒定不变**（不像底栏那颗随状态换词）。这一页的第一步是「立即体检」：副标题自己写着「先体检，再决定是否执行保守修复」。
        self.check_btn = QPushButton("立即体检")
        # RN-508：「保守」是内部说法。外审 5/6 报「不知道会动什么文件、不敢点」。
        #   ⇒ 按钮上直接写它的安全性质（它只建缺的目录、清失效引用，不删素材）。
        self.fix_btn = QPushButton("一键修复（只补不删）")
        self.open_btn = QPushButton("打开资源目录")
        self.export_btn = QPushButton("导出报告")
        # ⚠ 这两颗的主/次由 `_sync_first_step()` 按体检结果定，不在这里写死 ——
        #   批 46 第一版把「立即体检」恒定为主，外审 3 发报
        #   「已检出 17 项问题但主视觉仍高亮『立即体检』」。
        self.check_btn.setObjectName("primaryButton")
        self.fix_btn.setObjectName("secondaryButton")
        self.open_btn.setObjectName("secondaryButton")
        self.export_btn.setObjectName("secondaryButton")
        actions.addWidget(self.check_btn)
        actions.addWidget(self.fix_btn)
        actions.addWidget(self.open_btn)
        actions.addWidget(self.export_btn)
        actions.addStretch()
        actions_layout.addLayout(actions)
        layout.addWidget(actions_card)

        report_card, report_layout = SettingsCard.make(
            "体检报告",
            "报告会汇总资源缺失、失效引用和空目录等问题，便于确认修复前后的差异。",
        )

        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setMinimumHeight(400)
        report_layout.addWidget(self.report_text)

        layout.addWidget(report_card)
        layout.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(116)
        self.action_bar.primary_btn.setMinimumWidth(148)
        root.addWidget(self.action_bar, 0)

        self.check_btn.clicked.connect(self._run_health_check)
        self.fix_btn.clicked.connect(self._run_conservative_fix)
        self.open_btn.clicked.connect(self._open_resource_directory)
        self.export_btn.clicked.connect(self._export_report)

    def _sync_action_bar(self, report: dict):
        if not hasattr(self, "action_bar"):
            return

        summary = (report or {}).get("summary", {}) or {}
        overall_ok = bool(summary.get("ok", False))
        issue_count = int(summary.get("missing_directories", 0) or 0)
        issue_count += int(summary.get("invalid_config_refs", 0) or 0)
        issue_count += int(summary.get("empty_style_dirs", 0) or 0)

        # ⛔ RN-102 / RN-506（2026-09-04 批 46）：底栏原来有两颗，**都是副本**——
        #   `configure_secondary("立即体检", self._run_health_check)` 与
        #   「体检与修复」卡里那颗「立即体检」是同一个方法；
        #   而主按钮**随体检结果变身**：健康时是「导出报告」、有问题时是
        #   「一键修复（保守）」—— 而这两颗卡内**也都有**。
        # ⭐⭐ 一颗位置固定、含义会变的按钮，比两颗按钮更难防（肌肉记忆记的是位置）。
        # ⇒ 底栏不放按钮，四个动作全留「体检与修复」卡 —— 那张卡的副标题
        #   （「先体检，再决定是否执行保守修复；导出报告适合留档…」）就是它们的语境。
        self.action_bar.configure_secondary("", None, visible=False)
        self.action_bar.configure_primary("", None, visible=False)
        self._sync_first_step(overall_ok)
        # ⚠⚠ 改完复跑逮到（外审 r3 逐字报「底部提示写『一键修复（保守）』，
        #   而按钮实为『一键修复（只补不删）』」）：**我改了按钮名，
        #   而点名它的这句话留在原地** —— 批 45 那条教训的同一形态第二次。
        # ⭐ 顺手把「在上面…里的」也去掉：那是在描述版面（RN-077），版面一动它就腐烂。
        if overall_ok:
            action_message = "当前状态：资源健康 · 音频和视觉目录都正常，需要留档就导出报告。"
        else:
            action_message = (
                f"当前状态：发现 {issue_count} 项问题 · 建议先看报告，"
                f"确认后再点「{self.fix_btn.text()}」。"
            )
        self.action_bar.set_message(action_message)

    def _sync_first_step(self, overall_ok: bool):
        """⭐ 那一颗紫的必须是**当下的第一步**（批 44 RN-450 的裁定）。

        健康 ⇒ 第一步是再体检一次（或什么都不用做）；
        发现问题 ⇒ 第一步是修它。
        ⚠ 这两个都是**安全动作**（保守修复只补不删），所以在它们之间换
          不触碰 RN-506 那条线（安全 ↔ 破坏性）。
        """
        from page_theme_helper import style_as_primary_button, style_as_secondary_button

        first, other = ((self.check_btn, self.fix_btn) if overall_ok
                        else (self.fix_btn, self.check_btn))
        style_as_primary_button(first)
        style_as_secondary_button(other)
        for btn in (first, other):
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def _sync_status_strip(self, report: dict):
        summary = (report or {}).get("summary", {}) or {}
        audio_summary = (report or {}).get("audio", {}).get("summary", {}) or {}
        visual_summary = (report or {}).get("visual", {}).get("summary", {}) or {}

        overall_ok = bool(summary.get("ok", False))
        audio_ok = bool(audio_summary.get("ok", overall_ok))
        visual_ok = bool(visual_summary.get("ok", overall_ok))
        issue_count = int(summary.get("missing_directories", 0) or 0)
        issue_count += int(summary.get("invalid_config_refs", 0) or 0)
        issue_count += int(summary.get("empty_style_dirs", 0) or 0)

        badges = [
            ("positive" if overall_ok else "warning", f"体检 · {'健康' if overall_ok else '发现问题'}"),
            ("positive" if audio_ok else "warning", f"音频 · {'正常' if audio_ok else '检查'}"),
            ("positive" if visual_ok else "warning", f"视觉 · {'正常' if visual_ok else '检查'}"),
            ("positive" if issue_count == 0 else "warning", f"项目 · {issue_count} 项"),
        ]

        compact_summary = (
            f"状态 · {'健康' if overall_ok else '发现问题'}"
            f" · 音频{'正常' if audio_ok else '待检查'}"
            f" · 视觉{'正常' if visual_ok else '待检查'}"
            f" · {issue_count}项"
        )
        detail_text = (
            f"资源体检结果：音频{'正常' if audio_ok else '需要关注'}，"
            f"视觉{'正常' if visual_ok else '需要关注'}，"
            f"共发现 {issue_count} 项问题。"
            f"缺失目录 {summary.get('missing_directories', 0)} 项，"
            f"失效引用 {summary.get('invalid_config_refs', 0)} 项，"
            f"空风格目录 {summary.get('empty_style_dirs', 0)} 项。"
        )
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.summary_label.setText(compact_summary)
        self.summary_label.setToolTip(detail_text)
        if hasattr(self, "status_card"):
            self.status_card.setToolTip(detail_text)
        self._sync_action_bar(report)

    def _render_report(self, report: dict):
        self._last_report = report
        self._sync_status_strip(report)
        self.report_text.setPlainText(format_resource_system_health(report))

    #: ⭐⭐⭐ RN-146：**这一页的控件树在同一份配置下复跑会变**（CI 上实测 18 条差异，
    #: 本机测不出来）。根因是构造函数第 52 行就起了一个后台线程去扫盘 ——
    #: 扫描完成得比快照早还是晚，决定了屏幕上是「扫描中」（按钮置灰、芯片还没算）
    #: 还是结果列表。**它是一场竞速，而基线是在随机的某一刻拍的。**
    #:
    #: ⛔ 修法**不是**「工装下就别扫」：那会让基线拍到一个几乎没有内容的空壳，
    #:   报告区域以后怎么坏都没人看得见。这正是 `_audit_sandbox` 当年选
    #:   「重定向」而不是「禁写」的同一条理由 —— **别把被审计的对象改掉**。
    #: ⇒ 改成：工装可以要求这一次**同步扫**，扫完再返回。拍到的是**结果态**，
    #:   也就是用户真正会停留的那一态，而且每次都一样。
    #: ⚠ 产品代码任何地方都不设这个环境变量（同 `CS2C_NO_GLOBAL_HOTKEYS` 的口径）。
    SYNC_SCAN_ENV = "CS2C_SYNC_HEALTH_SCAN"

    def _run_health_check(self):
        """触发体检：扫描在后台线程执行，UI 显示进行中占位。"""
        if self._health_checking:
            return
        if os.environ.get(self.SYNC_SCAN_ENV) == "1":
            # 工装档：就地扫完再回去，不留竞速窗口。
            try:
                self._render_report(collect_resource_system_health())
            except Exception as e:
                self.logger.error(f"Audio health check failed: {e}")
            return
        self._health_checking = True
        try:
            self.report_text.setPlainText("正在扫描音频与视觉资源，请稍候…")
            self.check_btn.setEnabled(False)
        except Exception:
            pass

        def _worker():
            try:
                report = collect_resource_system_health()
                self._health_report_ready.emit(report, "")
            except Exception as e:
                self._health_report_ready.emit(None, str(e)[:160])

        import threading

        threading.Thread(target=_worker, name="AudioHealthScan", daemon=True).start()

    def _on_health_report_ready(self, report, error_text):
        self._health_checking = False
        try:
            self.check_btn.setEnabled(True)
        except Exception:
            pass
        if report is None:
            self.logger.error(f"Audio health check failed: {error_text}")
            QMessageBox.warning(self, "体检失败", f"执行体检失败：{error_text}")
            return
        self._render_report(report)

    def _run_conservative_fix(self):
        try:
            result = apply_conservative_resource_fix()
            after = result.get("after", {})
            self._render_report(after)
            audio_fix = result.get("audio_fix", {}) or {}
            created_audio = len(audio_fix.get("created_directories", []))
            created_visual = len(result.get("created_visual_directories", []))
            reset = len(audio_fix.get("reset_config_keys", []))
            QMessageBox.information(
                self,
                "修复完成",
                "修复已执行（只补缺的、不删你的文件）。"
                f"\n音频目录补齐：{created_audio}"
                f"\n视觉目录补齐：{created_visual}"
                f"\n回退配置项：{reset}",
            )
        except Exception as e:
            self.logger.error(f"Audio conservative fix failed: {e}", exc_info=True)
            QMessageBox.warning(self, "修复失败", "执行修复失败：资源目录可能被占用或无写入权限，请稍后重试。")

    def _open_resource_directory(self):
        resource_root = ResourceManager.get_app_data_path("resources")
        os.makedirs(resource_root, exist_ok=True)
        try:
            os.startfile(resource_root)  # type: ignore[attr-defined]
        except Exception as e:
            self.logger.warning(f"打开资源目录失败: {e}")
            QMessageBox.warning(self, "打开失败", f"无法自动打开目录，请手动前往：\n{resource_root}")

    def _export_report(self):
        report = self._last_report or collect_resource_system_health()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出体检报告",
            os.path.join(ResourceManager.get_app_data_path("logs"), "resource_health_report.json"),
            "JSON 文件 (*.json);;文本文件 (*.txt)",
        )
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if path.lower().endswith(".txt"):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(format_resource_system_health(report))
            else:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"导出体检报告失败: {e}")
            QMessageBox.warning(self, "导出失败", "导出报告失败：目标位置可能无写入权限，请换个位置后重试。")
