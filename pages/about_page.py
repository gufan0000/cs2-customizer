#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
关于页面 - PySide6 Widgets版本
功能：项目信息、版本、开源许可、诊断信息
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QFont, QDesktopServices

from config import VERSION
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from theme_manager import get_color, get_theme_manager
from page_theme_helper import style_as_primary_button, style_as_secondary_button
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard

# 开源版刻意不再引用 service_urls：那里的官网域名、QQ 群号属于闭源商业版的运营资产，
# 而且 fork 出去的客户端不该继续访问原作者的服务器（更新检查/更新日志接口同理已移除）。
# 这里只保留一组指向本仓库自身的常量，换 owner 时改这一处即可。
PROJECT_NAME = "CS2 Customizer"
PROJECT_LICENSE = "GPL-3.0"
PROJECT_REPO_URL = "https://github.com/OWNER/cs2-customizer"
PROJECT_ISSUES_URL = f"{PROJECT_REPO_URL}/issues"
PROJECT_RELEASES_URL = f"{PROJECT_REPO_URL}/releases"


class AboutPage(QWidget):
    """关于页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("AboutPage")

        self._create_ui()

        # 注册主题变更回调
        get_theme_manager().register_theme_changed_callback(self._apply_theme_styles)

        self.logger.info("关于页面初始化完成")

    def _build_info_text(self):
        return (
            "<p style='font-size: 14px; line-height: 1.8;'>"
            f"<b>项目：</b>{PROJECT_NAME}（原「帆派助手」开源版）<br>"
            "<b>作者：</b>孤帆<br>"
            f"<b>仓库：</b>{PROJECT_REPO_URL}<br><br>"
            "本工具通过监听 CS2 官方游戏状态接口 (GSI) 来实现击杀音效等功能，"
            "只读取游戏状态并读写 cfg 文件。<br>"
            "请确保已正确选择 CS 文件夹。<br><br>"
            f"<span style='color: {get_color('info')};'>"
            f"<b>开源软件 · {PROJECT_LICENSE} 许可 · 自由使用与修改</b></span>"
            "</p>"
        )

    def _sync_status_strip(self):
        detail_text = (
            f"当前安装版本：v{VERSION}\n"
            "运行渠道：桌面工具（开源版）\n"
            f"许可证：{PROJECT_LICENSE}\n"
            f"项目仓库：{PROJECT_REPO_URL}"
        )
        badges = [
            ("info", f"版本 · v{VERSION}"),
            ("positive", "渠道 · 桌面工具"),
            ("info", f"许可证 · {PROJECT_LICENSE}"),
        ]
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.summary_label.setText(detail_text)
        self.summary_label.setToolTip(detail_text)
        self.status_card.setToolTip(detail_text)
        self._sync_action_bar()

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        self.action_bar.configure_secondary("打开项目仓库", self._open_repository, visible=True)
        self.action_bar.configure_primary("查看发布记录", self._open_releases, visible=True)
        self.action_bar.set_message(
            f"当前版本：v{VERSION} · 开源版不内置更新检查，新版本发布在 GitHub Releases 页面。"
        )

    def _create_ui(self):
        """创建UI"""
        # UP-071/UP-072: 本页此前整页没有滚动区。实测 1200×800 下根布局最小高
        # 1091px、可视区只有 750px —— 下半截既看不到也滚不动，而排版审计当时
        # 只有横向判据，压根检测不到。这里套用 advanced_page 早就在用的
        # 「外层 outer + 内容滚动区 + 底部固定 action_bar」结构。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page_widget = QWidget()
        layout = QVBoxLayout(page_widget)
        # UP-045: 左右 20→16,与其余 19 页对齐到内容左边界 216px
        layout.setContentsMargins(16, 16, 16, 20)
        layout.setSpacing(12)

        # UP-047: 页头改用 PageHeader。
        # ⚠ 本页原来是 `layout.addWidget(title)` 直接铺满整宽（962px），
        # 换进 PageHeader 后标题在一条 QHBoxLayout 里、只占自身宽度。
        # 渲染无差别——`#titleLabel` 的 QSS 是 `background: transparent`，
        # 多出来的那段本来就是空白。
        header = PageHeader(
            "关于软件",
            description="版本信息、开源许可和产品说明都集中在这里，方便确认当前这台桌面端的安装状态。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)

        status_card = QFrame()
        status_card.setFrameShape(QFrame.StyledPanel)
        status_card.setObjectName("card")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(14, 14, 14, 14)
        status_layout.setSpacing(10)
        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_title = QLabel("当前状态")
        status_title.setObjectName("statusLabel")
        status_row.addWidget(status_title)
        self.status_badge_label = create_badge_label()
        status_row.addWidget(self.status_badge_label, 1)
        status_row.addStretch()
        status_layout.addLayout(status_row)
        self.status_card = status_card

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        status_layout.addWidget(self.summary_label)
        layout.addWidget(status_card)

        intro_card, intro_layout = SettingsCard.make(
            "产品信息",
            "桌面端当前以安装状态、项目信息和产品说明为主，功能演进都在开源仓库里公开进行。",
            margins=(14, 14, 14, 14), spacing=10
        )

        logo_layout = QVBoxLayout()
        logo_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        logo_layout.setSpacing(4)

        logo_text = QLabel(PROJECT_NAME)
        logo_text.setFont(QFont("Microsoft YaHei", 30, QFont.Bold))
        logo_text.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        logo_text.setObjectName("logoTitle")  # 使用主题样式
        logo_layout.addWidget(logo_text)

        version_text = QLabel(f"v{VERSION}")
        version_text.setFont(QFont("Arial", 16))
        version_text.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        version_text.setObjectName("versionText")  # 使用主题样式
        logo_layout.addWidget(version_text)
        intro_layout.addLayout(logo_layout)

        self.info_label = QLabel(self._build_info_text())
        self.info_label.setWordWrap(True)
        self.info_label.setTextFormat(Qt.RichText)
        self.info_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.info_label.setObjectName("infoLabel")  # 使用主题样式
        intro_layout.addWidget(self.info_label)
        layout.addWidget(intro_card)

        # 开源版没有更新检查，也不联网取更新日志：版本变更只在仓库的 Releases 页面公布，
        # 是否升级由用户自己决定，客户端不做版本封杀、也不回连任何服务器。
        release_card, release_layout = SettingsCard.make(
            "开源与发布",
            f"本项目以 {PROJECT_LICENSE} 许可开源，源码、更新日志和发布包都在 GitHub 仓库。",
            margins=(14, 14, 14, 14), spacing=10
        )
        release_hint = QLabel(
            "软件不会自动联网检查更新；想知道有没有新版本，到仓库的 Releases 页面看一眼即可。"
        )
        release_hint.setObjectName("hintLabel")
        release_hint.setWordWrap(True)
        release_layout.addWidget(release_hint)

        repo_label = QLabel(f"仓库：{PROJECT_REPO_URL.replace('https://', '')}")
        repo_label.setObjectName("hintLabel")
        repo_label.setWordWrap(True)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        button_layout.addWidget(repo_label, 1)

        releases_button = QPushButton("查看发布记录")
        releases_button.setFixedHeight(40)
        releases_button.setMinimumWidth(160)
        releases_button.setFont(QFont("Microsoft YaHei", 13))
        style_as_primary_button(releases_button)
        releases_button.clicked.connect(self._open_releases)
        button_layout.addStretch()
        button_layout.addWidget(releases_button)

        release_layout.addLayout(button_layout)
        layout.addWidget(release_card)

        # R2-5: 反馈入口——打开仓库 / 提交 Issue / 复制诊断信息
        feedback_card, feedback_layout = SettingsCard.make(
            "反馈与求助",
            "遇到问题或想提建议:复制诊断信息后附在 GitHub Issue 里,定位会快很多。",
            margins=(14, 14, 14, 14), spacing=10,
        )
        fb_row = QHBoxLayout()
        fb_row.setSpacing(8)

        self.open_repo_button = QPushButton("打开项目仓库")
        style_as_secondary_button(self.open_repo_button)
        self.open_repo_button.setFixedHeight(36)
        self.open_repo_button.clicked.connect(self._open_repository)
        fb_row.addWidget(self.open_repo_button)

        self.open_issues_button = QPushButton("提交 Issue")
        style_as_secondary_button(self.open_issues_button)
        self.open_issues_button.setFixedHeight(36)
        self.open_issues_button.clicked.connect(self._open_issues)
        fb_row.addWidget(self.open_issues_button)

        self.copy_diag_button = QPushButton("复制诊断信息")
        style_as_secondary_button(self.copy_diag_button)
        self.copy_diag_button.setFixedHeight(36)
        self.copy_diag_button.clicked.connect(self._copy_diagnostics)
        fb_row.addWidget(self.copy_diag_button)
        fb_row.addStretch()
        feedback_layout.addLayout(fb_row)
        layout.addWidget(feedback_card)

        layout.addStretch(1)

        page_scroll.setWidget(page_widget)
        outer.addWidget(page_scroll, 1)

        # 操作条钉在滚动区外——跟着内容滚走的话，页面一长就找不到主操作了
        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(116)
        self.action_bar.primary_btn.setMinimumWidth(132)
        outer.addWidget(self.action_bar, 0)
        self._sync_status_strip()

    # ---------------- R2-5: 反馈入口 ----------------

    def _open_repository(self):
        QDesktopServices.openUrl(QUrl(PROJECT_REPO_URL))

    def _open_issues(self):
        QDesktopServices.openUrl(QUrl(PROJECT_ISSUES_URL))

    def _open_releases(self):
        QDesktopServices.openUrl(QUrl(PROJECT_RELEASES_URL))

    def _collect_diagnostics(self) -> str:
        """汇总不含隐私的环境信息 + 脱敏日志尾部,方便贴到 Issue 里排障。"""
        import platform
        import sys

        from config import VERSION, config

        lines = [
            f"{PROJECT_NAME} {VERSION}",
            f"系统: {platform.system()} {platform.release()} ({platform.machine()})",
            f"Python 运行时: {platform.python_version()}",
            f"安装形态: {'冻结(打包)' if getattr(sys, 'frozen', False) else '源码运行'}",
            f"主题: {getattr(config, 'ui_theme', 'dark')} | 字号: {int(float(getattr(config, 'ui_font_scale', 1.0)) * 100)}%",
            f"专家模式: {bool(getattr(config, 'ui_expert_mode', False))}",
        ]
        try:
            import ctypes
            lines.append(f"管理员: {bool(ctypes.windll.shell32.IsUserAnAdmin())}")
        except Exception:
            pass
        load_error = getattr(config, "_load_error", "")
        if load_error:
            lines.append(f"配置加载: {load_error}")
        try:
            # QA-011: 这里原本 `from gsi_server import get_gsi_server` —— 那个名字不存在，
            # 100% 抛 ImportError 被下面的裸 except 吞成「GSI: 未知」，用户复制出来的
            # 诊断信息里最该看的一行永远是空的。实例改从主窗口拿（main_widget.py 挂的），
            # 运行态走 collect_gsi_status 统一取，属性名不再在这里手写第二遍。
            # gsi_server 保持方法内局部 import：提到模块顶层会把 flask 拖进启动路径。
            from core.runtime.system_status_service import collect_gsi_status
            from gsi_server import get_active_port

            status = collect_gsi_status(self.window())
            if not status.get("available"):
                lines.append("GSI: 未初始化")
            else:
                state = "运行中" if status.get("running") else "未运行"
                line = f"GSI: {state} | 端口 {get_active_port()}"
                err = str(status.get("startup_error") or "")
                if err:
                    line += f" | 启动错误: {err}"
                lines.append(line)
        except Exception:
            lines.append("GSI: 未知")
        try:
            from core.diagnostics import read_recent_log_tail
            from core.utils.log_filter import redact_text
            from core.utils.logger import get_logger

            log_dir = str(getattr(get_logger(), "log_dir", "") or "")
            tail = read_recent_log_tail(log_dir, max_lines=40, redactor=redact_text)
            if tail:
                lines.append("")
                lines.append("最近日志(已脱敏):")
                lines.append(tail)
        except Exception:
            pass
        return "\n".join(lines)

    def _copy_diagnostics(self):
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._collect_diagnostics())
        try:
            from ui_toast import toast_success

            toast_success("诊断信息已复制,可直接粘贴到 GitHub Issue 里")
        except Exception:
            pass

    def _apply_theme_styles(self):
        """主题变更时刷新内联样式"""
        if hasattr(self, 'info_label'):
            self.info_label.setText(self._build_info_text())

    def deleteLater(self):
        """清理：注销主题回调"""
        from theme_manager import get_theme_manager
        get_theme_manager().unregister_theme_changed_callback(self._apply_theme_styles)
        super().deleteLater()
