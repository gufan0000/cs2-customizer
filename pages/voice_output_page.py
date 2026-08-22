#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
语音输出页面 - PySide6 Widgets版本
功能：音板、语音输出、音效转发
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QComboBox, QCheckBox, QFrame, QScrollArea,
    QGroupBox, QFileDialog, QMessageBox,
    QTabWidget, QGridLayout, QSizePolicy, QLayout
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont
import keyboard
import threading

from config import config
from core.utils.logger import get_logger
from core.utils.format_utils import format_percent
from pages.audio_status_badge import create_badge_label, render_badges
from voice_output_manager import get_voice_output_manager
from page_theme_helper import style_as_danger_button
from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar


# QA-014: 驱动包下载**必须**有超时。
# 原来用的是 `urllib.request.urlretrieve(url, path)` —— 这个 API 根本不接受
# timeout 参数，而进程级 `socket.setdefaulttimeout` 全仓零调用，所以默认超时是 None。
# 对端 accept 了不发数据、或 body 传到一半断流（实测两种都会），下载线程**永久阻塞**：
# 状态行永远停在「正在下载VB-Cable驱动...」，没有取消按钮、没有看门狗，
# 连 finally 里的 `shutil.rmtree(temp_dir)` 都跑不到，临时目录泄漏、线程堆积。
#
# ⚠ 这里的 timeout 是**每次 socket 操作**的超时，不是整个下载的总时限。
# 写成总时限会把 20KB/s 的跨境慢链路误杀（真实包 1.09MB 要 ~56 秒），
# 那是比原缺陷更严重的回归 —— 它打的是正常用户。
# max_bytes 是防「劫持/错发的无限流把系统盘写爆」，1.09MB 对 64MB 有 58 倍余量。
def _download_to_file(url: str, dest: str, timeout: int = 30,
                      max_bytes: int = 64 * 1024 * 1024) -> int:
    """分块下载到 dest，返回落盘字节数。任何异常原样上抛，由调用方兜。"""
    import urllib.request

    written = 0
    with urllib.request.urlopen(url, timeout=timeout) as resp, open(dest, "wb") as fh:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                fh.write(chunk[: max_bytes - (written - len(chunk))])
                raise ValueError(
                    f"下载内容超过上限 {max_bytes} 字节，已中止（可能是来源异常）")
            fh.write(chunk)
    return written


class VoiceOutputPage(QWidget):
    """语音输出页面"""
    
    # 状态更新信号
    status_updated = Signal(str, str)  # (status_type, message)
    hotkey_set_signal = Signal(int, str)  # (slot_id, key) - 槽位快捷键设置完成
    stop_key_set_signal = Signal(str)  # (key) - 中断键设置完成
    # UP-039: 热键注册结果 (冲突列表, 失败列表, 成功数)。
    # 走 Signal 而不是就地弹 toast：注册链路会被配置变更从多处触发，
    # 用信号能保证提示一定在 GUI 线程上出。
    _hotkey_report_signal = Signal(list, list, int)
    ptt_key_set_signal = Signal(str)  # (key) - PTT键设置完成
    _status_signal = Signal(str)  # 跨线程安全的状态更新
    _status_clear_signal = Signal(int)  # 跨线程安全的延迟清除状态
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("VoiceOutputPage")
        
        # 管理器实例
        self.voice_manager = get_voice_output_manager()
        self.vb_installer = None  # 稍后初始化
        
        # 音板槽位数据 {slot_id: {key: str, audio: str, volume: float, name: str}}
        self.soundboard_slots = {}
        self.initial_slots = 5  # 初始槽位数
        self.max_slots = 50  # 最大槽位数
        self.current_slot_count = 0
        
        # 快捷键监听
        self.hotkey_listeners = {}
        self.is_listening_for_key = False
        self.current_listening_slot = None
        
        # 中断快捷键
        self.stop_hotkey = None
        self.stop_hotkey_listener = None
        self.is_listening_for_stop_key = False
        
        # PTT设置
        self.ptt_key = config.voice_output_ptt_key if hasattr(config, 'voice_output_ptt_key') else "v"
        self.ptt_delay = config.voice_output_ptt_delay if hasattr(config, 'voice_output_ptt_delay') else 500
        self.ptt_enabled = config.voice_output_ptt_enabled if hasattr(config, 'voice_output_ptt_enabled') else True
        self.is_listening_for_ptt_key = False
        
        # UI初始化
        self._create_ui()
        
        # 连接快捷键设置信号
        self.hotkey_set_signal.connect(self._on_hotkey_set)
        self.stop_key_set_signal.connect(self._on_stop_key_set)
        self.ptt_key_set_signal.connect(self._on_ptt_key_set)
        self._status_signal.connect(self._set_status_text)
        self._status_clear_signal.connect(lambda ms: QTimer.singleShot(ms, self._clear_status))
        
        # 加载配置
        self._load_config()
        
        # 启动全局快捷键监听器
        self._start_global_hotkey_listener()
        
        self.logger.info("语音输出页面初始化完成")

    def _configured_slot_count(self):
        slots = getattr(self, "soundboard_slots", {}) or {}
        return sum(1 for slot in slots.values() if slot.get("audio"))

    def _configured_hotkey_count(self):
        slots = getattr(self, "soundboard_slots", {}) or {}
        return sum(1 for slot in slots.values() if slot.get("audio") and slot.get("key"))

    def _enabled_sfx_option_count(self):
        option_checks = getattr(self, "sfx_option_checks", {}) or {}
        if option_checks:
            total = len(option_checks)
            enabled = sum(1 for check in option_checks.values() if check.isChecked())
            return enabled, total

        option_keys = getattr(self, "sfx_option_keys", []) or []
        options = getattr(config, "sfx_forwarding_options", {}) or {}
        total = len(option_keys)
        enabled = sum(1 for key in option_keys if bool(options.get(key, True)))
        return enabled, total

    def _driver_ready(self):
        manager = getattr(self, "voice_manager", None)
        return getattr(manager, "vb_cable_device_id", None) is not None

    @staticmethod
    def _is_checked_state(state):
        if state == Qt.CheckState.Checked:
            return True
        try:
            return int(getattr(state, "value", state)) == int(Qt.CheckState.Checked.value)
        except Exception:
            return False

    def _current_mode_text(self):
        combo = getattr(self, "play_mode_combo", None)
        if combo is not None and hasattr(combo, "currentText"):
            text = combo.currentText().strip()
            if text:
                return text
        return str(getattr(config, "voice_output_mode", "覆盖") or "覆盖")

    def _current_microphone_text(self):
        combo = getattr(self, "mic_combo", None)
        if combo is not None and hasattr(combo, "currentText"):
            text = combo.currentText().strip()
            if text:
                return text
        return str(getattr(config, "voice_output_microphone", "默认") or "默认")

    def _current_runtime_text(self):
        label = getattr(self, "status_label", None)
        if label is not None and hasattr(label, "text"):
            text = label.text().strip()
            if text:
                return text
        return "就绪"

    def _current_tab_text(self):
        tab_widget = getattr(self, "tab_widget", None)
        if tab_widget is not None and tab_widget.count() > 0:
            index = tab_widget.currentIndex()
            if index < 0:
                index = 0
            return tab_widget.tabText(index)
        return "语音设置"

    def _sync_action_bar_state(self):
        if not hasattr(self, "action_bar"):
            return

        runtime_text = self._current_runtime_text()
        current_tab = self._current_tab_text()

        self.action_bar.configure_secondary("使用说明", self._show_instructions, visible=True)

        if current_tab == "音效转发":
            forwarding_enabled = bool(getattr(config, "sfx_forwarding_enabled", False))
            sfx_enabled, sfx_total = self._enabled_sfx_option_count()
            self.action_bar.configure_primary("导出配置", self._export_config, visible=True)
            action_message = (
                f"当前标签：{current_tab} · 转发{'已启用' if forwarding_enabled else '未启用'}"
                f"{f' {sfx_enabled}/{sfx_total}' if sfx_total else ''}；最近状态：{runtime_text}"
            )
        else:
            slot_total = len(getattr(self, "soundboard_slots", {}) or {})
            slot_configured = self._configured_slot_count()
            hotkey_configured = self._configured_hotkey_count()
            self.action_bar.configure_primary("添加槽位", self._add_slot, visible=True)
            action_message = (
                f"当前标签：{current_tab} · 已配置 {slot_configured}/{slot_total} 个槽位，"
                f"已绑定 {hotkey_configured} 个快捷键；最近状态：{runtime_text}"
            )

        self.action_bar.set_message(action_message)

    def _sync_overview_status(self):
        if not hasattr(self, "status_badge_label"):
            return

        driver_ready = self._driver_ready()
        mode_text = self._current_mode_text()
        slot_total = len(getattr(self, "soundboard_slots", {}) or {})
        slot_configured = self._configured_slot_count()
        hotkey_configured = self._configured_hotkey_count()
        forwarding_enabled = bool(getattr(config, "sfx_forwarding_enabled", False))
        sfx_enabled, sfx_total = self._enabled_sfx_option_count()
        volume_percent = int(round(float(getattr(config, "voice_output_volume", 1.0)) * 100))
        runtime_text = self._current_runtime_text()
        ptt_enabled = bool(getattr(config, "voice_output_ptt_enabled", getattr(self, "ptt_enabled", True)))
        ptt_key = str(getattr(config, "voice_output_ptt_key", getattr(self, "ptt_key", "未设置")) or "未设置")
        stop_key = str(getattr(config, "voice_output_stop_key", getattr(self, "stop_hotkey", "")) or "未设置")
        also_local = bool(getattr(config, "voice_output_also_local", True))

        if forwarding_enabled:
            forwarding_text = f"转发 · {sfx_enabled}/{sfx_total}" if sfx_total else "转发 · 已启用"
            forwarding_level = "success" if sfx_enabled else "info"
        else:
            forwarding_text = "转发 · 未启用"
            forwarding_level = "warn"

        badges = [
            ("success" if driver_ready else "warn", f"驱动 · {'已就绪' if driver_ready else '待安装'}"),
            ("success" if mode_text == "自动" else "info", f"模式 · {mode_text}"),
            ("success" if slot_configured else "info", f"槽位 · {slot_configured}/{slot_total}"),
            (forwarding_level, forwarding_text),
        ]

        detail_lines = [
            f"驱动状态：{'VB-Cable 已就绪' if driver_ready else 'VB-Cable 待安装'}",
            f"当前模式：{mode_text}",
            f"主音量：{volume_percent}%",
            f"麦克风：{self._current_microphone_text()}",
            f"本地监听：{'已启用' if also_local else '未启用'}",
            f"PTT：{ptt_key} · {'已启用' if ptt_enabled else '未启用'}",
            f"中断键：{stop_key}",
            f"音板槽位：{slot_configured}/{slot_total}",
            f"快捷键已绑定：{hotkey_configured}",
            f"音效转发：{'已启用' if forwarding_enabled else '未启用'}"
            + (f"（{sfx_enabled}/{sfx_total}）" if sfx_total else ""),
            f"最近状态：{runtime_text}",
        ]

        summary_text = "\n".join(detail_lines)
        render_badges(self.status_badge_label, badges, detail_tooltip=summary_text)
        self.summary_label.setText(summary_text)
        self.summary_label.setToolTip(summary_text)
        self.status_card.setToolTip(summary_text)
        self._refresh_control_panel_summary()
        self._sync_action_bar_state()

    @staticmethod
    def _apply_compact_button(button, *, width=None, height=34, primary=False):
        button.setObjectName("primaryButton" if primary else "secondaryButton")
        button.setMinimumHeight(height)
        if width is not None:
            button.setMinimumWidth(width)
        return button

    @staticmethod
    def _apply_compact_combo(combo, *, min_width=120, max_width=None, height=34, expanding=True):
        combo.setMinimumHeight(height)
        combo.setMinimumWidth(min_width)
        if max_width is not None:
            combo.setMaximumWidth(max_width)
        combo.setSizePolicy(
            QSizePolicy.Expanding if expanding else QSizePolicy.Fixed,
            QSizePolicy.Fixed,
        )
        return combo

    @staticmethod
    def _apply_compact_label(label, *, width=None, bold=False):
        label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold if bold else QFont.Normal))
        if width is not None:
            label.setFixedWidth(width)
        return label

    def _create_panel_card(self, title, description=None):
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("statusLabel")
        layout.addWidget(title_label)

        if description:
            description_label = QLabel(description)
            description_label.setObjectName("hintLabel")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)

        return card, layout

    def _refresh_control_panel_summary(self):
        if hasattr(self, "driver_hint_label"):
            if self._driver_ready():
                self.driver_hint_label.setText("虚拟驱动已就绪，可直接使用音板或语音转发。")
            else:
                self.driver_hint_label.setText("当前缺少 VB-Cable，安装后才能把音频可靠送进游戏语音。")

        if hasattr(self, "routing_summary_label"):
            volume_percent = int(round(float(getattr(config, "voice_output_volume", 1.0)) * 100))
            local_text = "本地监听开启" if bool(getattr(config, "voice_output_also_local", True)) else "仅发送到虚拟设备"
            self.routing_summary_label.setText(
                f"当前路由：{self._current_mode_text()} · 主音量 {volume_percent}% · {local_text}"
            )

        if hasattr(self, "config_summary_label"):
            slot_configured = self._configured_slot_count()
            slot_total = len(getattr(self, "soundboard_slots", {}) or {})
            self.config_summary_label.setText(
                f"当前麦克风：{self._current_microphone_text()} · 已配置 {slot_configured}/{slot_total} 个槽位"
                f" · 最近状态 {self._current_runtime_text()}"
            )

        if hasattr(self, "control_frame") and self.control_frame.layout() is not None:
            self.control_frame.setFixedHeight(self.control_frame.layout().sizeHint().height())
    
    def _create_ui(self):
        """创建UI"""
        # 主布局：外层承载滚动区（修复矮窗口下控制面板与选项卡被压扁重叠）
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

        # 页面标题
        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        header = PageHeader(
            "语音输出",
            description="三件事：把文字转成语音说进游戏、用快捷键放音板、把击杀音效转给队友听。都要先装好虚拟声卡。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["voice_output"])

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
        
        # 顶部控制面板
        self._create_control_panel(layout)
        
        # 选项卡视图
        tab_widget = QTabWidget()
        self.tab_widget = tab_widget
        tab_widget.setMinimumHeight(360)  # 给选项卡一个高度下限，避免在外层滚动区里被压塌
        
        # 语音设置选项卡
        soundboard_tab = QWidget()
        self._create_soundboard_tab(soundboard_tab)
        tab_widget.addTab(soundboard_tab, "语音设置")
        
        # 音效转发选项卡
        sfx_forward_tab = QWidget()
        self._create_sfx_forward_tab(sfx_forward_tab)
        tab_widget.addTab(sfx_forward_tab, "音效转发")
        tab_widget.currentChanged.connect(lambda *_args: self._sync_action_bar_state())
        
        layout.addWidget(tab_widget)
        
        # 底部状态栏
        self._create_status_bar(layout)

        page_scroll.setWidget(page_widget)
        outer.addWidget(page_scroll, 1)

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(116)
        self.action_bar.primary_btn.setMinimumWidth(132)
        outer.addWidget(self.action_bar, 0)
        self._sync_overview_status()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self._refresh_control_panel_summary()
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._refresh_control_panel_summary)
        # 每次进页按当前配置(含语音总开关)重注册全局热键：
        # 用户在首页切了总开关后进本页，热键状态随之同步(关→撤销拦截，开→恢复)
        if hasattr(self, "_register_hotkeys_func"):
            self._register_hotkeys_func()
    
    def _create_control_panel(self, parent_layout):
        """创建顶部控制面板"""
        control_frame = QFrame()
        self.control_frame = control_frame
        control_frame.setObjectName("card")
        control_frame.setToolTip("这里负责驱动、主音量、模式、麦克风和整页配置导入导出。")
        control_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        control_layout = QVBoxLayout(control_frame)
        control_layout.setContentsMargins(12, 12, 12, 12)
        control_layout.setSpacing(8)
        control_layout.setSizeConstraint(QLayout.SetMinimumSize)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        driver_card, driver_layout = self._create_panel_card(
            "驱动与说明",
            "先确认 VB-Cable 是否就绪，再决定是否需要打开说明或手动安装驱动。",
        )
        self.vb_status_label = QLabel("⚪ 检测中...")
        self.vb_status_label.setObjectName("statusLabel")
        driver_layout.addWidget(self.vb_status_label)

        self.driver_hint_label = QLabel("")
        self.driver_hint_label.setObjectName("hintLabel")
        self.driver_hint_label.setWordWrap(True)
        driver_layout.addWidget(self.driver_hint_label)

        driver_actions = QHBoxLayout()
        driver_actions.setSpacing(8)
        self.install_button = QPushButton("安装驱动")
        self.install_button.setEnabled(False)
        self._apply_compact_button(self.install_button, width=100)
        self.install_button.clicked.connect(self._install_vb_cable)
        driver_actions.addWidget(self.install_button)

        help_button = QPushButton("使用说明")
        self._apply_compact_button(help_button, width=100)
        help_button.clicked.connect(self._show_instructions)
        driver_actions.addWidget(help_button)
        driver_actions.addStretch()
        driver_layout.addLayout(driver_actions)
        top_row.addWidget(driver_card, 4, Qt.AlignTop)

        routing_card, routing_layout = self._create_panel_card(
            "播放路由",
            "语音播出去时多大声、和麦克风怎么混，以及要不要自己也听到一份。",
        )
        volume_label = QLabel("主音量:")
        self._apply_compact_label(volume_label, width=58, bold=True)
        volume_row = QHBoxLayout()
        volume_row.setSpacing(8)
        volume_row.addWidget(volume_label)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 200)
        self.volume_slider.setValue(int(config.voice_output_volume * 100))
        self.volume_slider.setMinimumWidth(160)
        self.volume_slider.valueChanged.connect(self._update_volume)
        volume_row.addWidget(self.volume_slider, 1)

        self.volume_label = QLabel(format_percent(config.voice_output_volume, hi=2.0))
        self.volume_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        self.volume_label.setFixedWidth(60)
        self.volume_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        volume_row.addWidget(self.volume_label)
        routing_layout.addLayout(volume_row)

        route_options_row = QHBoxLayout()
        route_options_row.setSpacing(8)
        mode_label = QLabel("模式:")
        self._apply_compact_label(mode_label, width=42)
        route_options_row.addWidget(mode_label)

        self.play_mode_combo = QComboBox()
        self.play_mode_combo.addItems(["覆盖", "混音", "自动"])
        self.play_mode_combo.setCurrentText(config.voice_output_mode if hasattr(config, 'voice_output_mode') else "覆盖")
        self.play_mode_combo.setFont(QFont("Microsoft YaHei", 11))
        self._apply_compact_combo(self.play_mode_combo, min_width=120, max_width=136, expanding=False)
        self.play_mode_combo.currentTextChanged.connect(self._update_play_mode)
        route_options_row.addWidget(self.play_mode_combo)

        self.also_local_check = QCheckBox("本地监听")
        self.also_local_check.setFont(QFont("Microsoft YaHei", 11))
        self.also_local_check.setChecked(config.voice_output_also_local if hasattr(config, 'voice_output_also_local') else True)
        self.also_local_check.stateChanged.connect(self._update_also_local)
        route_options_row.addWidget(self.also_local_check)
        route_options_row.addStretch()
        routing_layout.addLayout(route_options_row)

        self.routing_summary_label = QLabel("")
        self.routing_summary_label.setObjectName("hintLabel")
        self.routing_summary_label.setWordWrap(True)
        routing_layout.addWidget(self.routing_summary_label)
        top_row.addWidget(routing_card, 5, Qt.AlignTop)
        control_layout.addLayout(top_row)

        device_card, device_layout = self._create_panel_card(
            "输入设备与配置",
            "选用哪个麦克风；换电脑或换设备时，整页设置可以导出再导入。",
        )
        mic_row = QHBoxLayout()
        mic_row.setSpacing(8)
        mic_label = QLabel("麦克风:")
        self._apply_compact_label(mic_label, width=58)
        mic_row.addWidget(mic_label)
        self.mic_combo = QComboBox()
        self.mic_combo.addItem("默认")
        self.mic_combo.setFont(QFont("Microsoft YaHei", 11))
        self._apply_compact_combo(self.mic_combo, min_width=240, max_width=620)
        # UP-028: 连 currentIndexChanged 而不是 currentTextChanged——
        # 要存的是 itemData 里那个稳定 key，不是展示文案（重名设备的展示文案带序号）。
        self.mic_combo.currentIndexChanged.connect(
            lambda _i: self._update_microphone(self._current_microphone_key()))
        mic_row.addWidget(self.mic_combo, 1)
        device_layout.addLayout(mic_row)

        config_actions = QHBoxLayout()
        config_actions.setSpacing(8)
        self.import_button = QPushButton("导入")
        self._apply_compact_button(self.import_button, width=84)
        self.import_button.clicked.connect(self._import_config)
        config_actions.addWidget(self.import_button)

        self.export_button = QPushButton("导出")
        self._apply_compact_button(self.export_button, width=84)
        self.export_button.clicked.connect(self._export_config)
        config_actions.addWidget(self.export_button)
        config_actions.addStretch()
        device_layout.addLayout(config_actions)

        self.config_summary_label = QLabel("")
        self.config_summary_label.setObjectName("hintLabel")
        self.config_summary_label.setWordWrap(True)
        device_layout.addWidget(self.config_summary_label)
        control_layout.addWidget(device_card)
        self._refresh_control_panel_summary()
        
        parent_layout.addWidget(control_frame)
    
    def _create_soundboard_tab(self, parent):
        """创建音板设置选项卡"""
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        tools_frame = QFrame()
        self.soundboard_tools_frame = tools_frame
        tools_frame.setObjectName("card")
        tools_frame.setToolTip("这里集中管理音板槽位、PTT 开麦键和中断键。")
        tools_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        tools_layout = QVBoxLayout(tools_frame)
        tools_layout.setContentsMargins(12, 12, 12, 12)
        tools_layout.setSpacing(8)
        tools_layout.setSizeConstraint(QLayout.SetMinimumSize)

        title_row = QHBoxLayout()
        tools_title = QLabel("快捷控制")
        tools_title.setObjectName("statusLabel")
        title_row.addWidget(tools_title)
        title_row.addStretch()
        tools_layout.addLayout(title_row)

        controls_grid = QGridLayout()
        controls_grid.setHorizontalSpacing(12)
        controls_grid.setVerticalSpacing(8)
        controls_grid.setColumnStretch(6, 1)

        add_slot_button = QPushButton("添加槽位")
        self._apply_compact_button(add_slot_button, width=116, primary=True)
        add_slot_button.clicked.connect(self._add_slot)
        controls_grid.addWidget(add_slot_button, 0, 0)

        stop_label = QLabel("中断键:")
        self._apply_compact_label(stop_label, width=56)
        controls_grid.addWidget(stop_label, 0, 1)

        self.stop_key_button = QPushButton(config.voice_output_stop_key or "未设置")
        self._apply_compact_button(self.stop_key_button, width=100)
        self.stop_key_button.clicked.connect(self._set_stop_key)
        controls_grid.addWidget(self.stop_key_button, 0, 2)

        ptt_label = QLabel("开麦键:")
        self._apply_compact_label(ptt_label, width=56)
        controls_grid.addWidget(ptt_label, 0, 3)

        self.ptt_key_button = QPushButton(self.ptt_key)
        self._apply_compact_button(self.ptt_key_button, width=100)
        self.ptt_key_button.clicked.connect(self._set_ptt_key)
        controls_grid.addWidget(self.ptt_key_button, 0, 4)

        self.ptt_enabled_check = QCheckBox("启用PTT")
        self.ptt_enabled_check.setFont(QFont("Microsoft YaHei", 11))
        self.ptt_enabled_check.setChecked(self.ptt_enabled)
        self.ptt_enabled_check.stateChanged.connect(self._update_ptt_enabled)
        controls_grid.addWidget(self.ptt_enabled_check, 0, 5)

        tools_layout.addLayout(controls_grid)
        layout.addWidget(tools_frame)
        
        # 槽位列表区域（可滚动）
        # RN-177：这里的内层滚动是**对的** —— 槽位数由用户决定（初始 5、上限 50），
        # 那是一份列表控件，不是被高度上限钉死的固定内容。排版审计第 5 条判据
        # 按 objectName 在 `NESTED_SCROLL_ALLOWED` 里放行它，所以这个名字不能改
        # （改了例外就失配，判据会当成新缺陷报出来 —— 那是它该有的行为）。
        scroll = QScrollArea()
        scroll.setObjectName("voiceSlotList")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self.slots_widget = QWidget()
        self.slots_layout = QVBoxLayout(self.slots_widget)
        self.slots_layout.setSpacing(10)
        self.slots_layout.setContentsMargins(4, 4, 4, 4)
        
        scroll.setWidget(self.slots_widget)
        layout.addWidget(scroll)
        
        # 初始化槽位
        self._initialize_slots()
    
    def _create_sfx_forward_tab(self, parent):
        """创建音效转发选项卡"""
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # 功能说明
        info_label = QLabel("将游戏内的音效（击杀音效、枪声等）转发到游戏语音，让队友也能听到！")
        info_label.setWordWrap(True)
        info_label.setFont(QFont("Microsoft YaHei", 11))
        layout.addWidget(info_label)
        
        # 主开关
        self.sfx_forwarding_check = QCheckBox("启用音效转发")
        self.sfx_forwarding_check.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        
        # 获取配置值
        initial_enabled = config.sfx_forwarding_enabled if hasattr(config, 'sfx_forwarding_enabled') else False
        self.logger.info(f"[音效转发初始化] config中的值: {initial_enabled}")
        
        # 设置复选框状态（在连接信号之前）
        self.sfx_forwarding_check.setChecked(initial_enabled)
        self.logger.info(f"[音效转发初始化] 复选框已设置为: {self.sfx_forwarding_check.isChecked()}")
        
        # 连接信号
        self.sfx_forwarding_check.stateChanged.connect(self._update_sfx_forwarding)
        layout.addWidget(self.sfx_forwarding_check)
        
        # 音效选项
        options_group = QGroupBox("音效选项")
        options_group.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        options_layout = QGridLayout(options_group)
        options_layout.setSpacing(10)
        
        # 音效选项列表
        sfx_options = [
            ("kill_sound", "击杀音效"),
            ("kill_voice", "击杀语音"),
            ("switch_weapon", "切枪音效"),
            ("reload_sound", "换弹音效"),
            ("gun_sound", "枪声替换"),
            ("death_sound", "被击杀音效"),
            ("special_sound", "特殊音效"),
            ("round_sound", "回合音效")
        ]
        self.sfx_option_keys = [key for key, _label in sfx_options]
        
        self.sfx_option_checks = {}
        
        # 获取当前配置
        sfx_config = config.sfx_forwarding_options if hasattr(config, 'sfx_forwarding_options') else {}
        
        for i, (key, label) in enumerate(sfx_options):
            check = QCheckBox(label)
            check.setFont(QFont("Microsoft YaHei", 11))
            check.setChecked(sfx_config.get(key, True))
            # 修复：正确处理 Qt.CheckState 枚举
            check.stateChanged.connect(lambda state, k=key: self._update_sfx_option(k, (state == Qt.CheckState.Checked) or (int(state) == 2)))
            self.sfx_option_checks[key] = check
            
            row = i // 2
            col = i % 2
            options_layout.addWidget(check, row, col)
        
        layout.addWidget(options_group)
        
        # 提示信息
        warning_label = QLabel("⚠️ 注意：音效转发建议在\"覆盖\"或\"自动\"模式下使用，\"混音\"模式可能会有回声。")
        warning_label.setWordWrap(True)
        warning_label.setFont(QFont("Microsoft YaHei", 10))
        layout.addWidget(warning_label)
        
        layout.addStretch()
    
    def _create_status_bar(self, parent_layout):
        """创建底部状态栏"""
        status_frame = QFrame()
        status_frame.setObjectName("card")
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(10, 5, 10, 5)
        
        self.status_label = QLabel("就绪")
        self.status_label.setFont(QFont("Microsoft YaHei", 10))
        status_layout.addWidget(self.status_label)
        
        status_layout.addStretch()
        
        parent_layout.addWidget(status_frame)
    
    def _initialize_slots(self):
        """初始化音板槽位"""
        # 加载配置中的槽位
        slots_config = config.voice_output_slots if hasattr(config, 'voice_output_slots') else {}

        # 槽位 id 可能不连续（删中间槽位再新增会产生稀疏 key，如 0,1,3,5），
        # 必须按最大 key+1 创建，只按 len() 创建会永久丢弃高位槽位的配置
        max_slot_id = -1
        for key in slots_config:
            try:
                max_slot_id = max(max_slot_id, int(key))
            except (TypeError, ValueError):
                continue

        for i in range(max(self.initial_slots, max_slot_id + 1)):
            self._add_slot(auto_init=True)
    
    def _add_slot(self, auto_init=False):
        """添加一个音板槽位"""
        if self.current_slot_count >= self.max_slots:
            QMessageBox.warning(self, "提示", f"已达到最大槽位数（{self.max_slots}）！")
            return
        
        slot_id = self.current_slot_count
        self.current_slot_count += 1
        
        # 创建槽位框架
        slot_frame = QFrame()
        slot_frame.setObjectName("card")
        slot_layout = QHBoxLayout(slot_frame)
        slot_layout.setContentsMargins(12, 10, 12, 10)
        slot_layout.setSpacing(8)
        
        # 槽位编号
        id_label = QLabel(f"#{slot_id + 1}")
        id_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        id_label.setFixedWidth(40)
        slot_layout.addWidget(id_label)
        
        # 快捷键按钮
        key_button = QPushButton("未设置")
        self._apply_compact_button(key_button, width=100, height=32)
        key_button.clicked.connect(lambda: self._set_slot_hotkey(slot_id))
        slot_layout.addWidget(key_button)
        
        # 音频文件路径
        audio_label = QLabel("未选择")
        audio_label.setFont(QFont("Microsoft YaHei", 10))
        audio_label.setWordWrap(False)
        audio_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        audio_label.setToolTip("未选择")
        slot_layout.addWidget(audio_label, 1)
        
        # 选择文件按钮
        browse_button = QPushButton("选择")
        self._apply_compact_button(browse_button, width=84, height=32)
        browse_button.clicked.connect(lambda: self._browse_audio(slot_id))
        slot_layout.addWidget(browse_button)
        
        # 预览按钮
        preview_button = QPushButton("试听")
        self._apply_compact_button(preview_button, width=72, height=32)
        preview_button.setEnabled(False)
        preview_button.clicked.connect(lambda: self._preview_audio(slot_id))
        slot_layout.addWidget(preview_button)
        
        # 音量滑块
        volume_slider = QSlider(Qt.Horizontal)
        volume_slider.setRange(0, 200)
        volume_slider.setValue(100)
        volume_slider.setFixedWidth(110)
        volume_slider.valueChanged.connect(lambda v: self._update_slot_volume(slot_id, v))
        slot_layout.addWidget(volume_slider)
        
        volume_label = QLabel("100%")
        volume_label.setFont(QFont("Microsoft YaHei", 10))
        volume_label.setFixedWidth(45)
        slot_layout.addWidget(volume_label)
        
        # 删除按钮
        delete_button = QPushButton("删除")
        # R7/D-06: 一次性抹掉「音频文件路径 + 全局热键绑定 + 音量 + 名称」并立即
        # _save_config()，无 undo、无快照；重建要重新选文件再重新录热键。
        self._apply_compact_button(delete_button, width=72, height=32)
        style_as_danger_button(delete_button)
        delete_button.clicked.connect(lambda: self._delete_slot(slot_id))
        slot_layout.addWidget(delete_button)
        
        # 添加到布局
        self.slots_layout.addWidget(slot_frame)
        
        # 存储槽位UI元素
        self.soundboard_slots[slot_id] = {
            "frame": slot_frame,
            "key_button": key_button,
            "audio_label": audio_label,
            "preview_button": preview_button,
            "volume_slider": volume_slider,
            "volume_label": volume_label,
            "audio": None,
            "key": None,
            "volume": 1.0,
            "name": ""
        }
        
        # 如果是自动初始化，加载配置
        if auto_init and hasattr(config, 'voice_output_slots'):
            slots_config = config.voice_output_slots
            if str(slot_id) in slots_config:
                slot_data = slots_config[str(slot_id)]
                self._load_slot_config(slot_id, slot_data)
        
        self.logger.info(f"添加音板槽位 #{slot_id + 1}")
        self._sync_overview_status()
    
    def _load_slot_config(self, slot_id, slot_data):
        """加载槽位配置"""
        slot = self.soundboard_slots.get(slot_id)
        if not slot:
            return
        
        # 加载音频文件
        if "audio" in slot_data and slot_data["audio"]:
            slot["audio"] = slot_data["audio"]
            slot["name"] = slot_data.get("name", "")
            slot["audio_label"].setText(slot["name"] or slot["audio"])
            slot["preview_button"].setEnabled(True)
        
        # 加载快捷键
        if "key" in slot_data and slot_data["key"]:
            slot["key"] = slot_data["key"]
            slot["key_button"].setText(slot["key"])
        
        # 加载音量
        if "volume" in slot_data:
            volume = int(slot_data["volume"] * 100)
            slot["volume_slider"].setValue(volume)
            slot["volume_label"].setText(f"{volume}%")
            slot["volume"] = slot_data["volume"]
    
    def _delete_slot(self, slot_id):
        """删除槽位"""
        if slot_id not in self.soundboard_slots:
            return
        
        # 确认删除
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除槽位 #{slot_id + 1} 吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            slot = self.soundboard_slots[slot_id]
            slot["frame"].deleteLater()
            del self.soundboard_slots[slot_id]
            self._save_config()
            self.logger.info(f"删除音板槽位 #{slot_id + 1}")
    
    def _browse_audio(self, slot_id):
        """浏览选择音频文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择音频文件",
            "",
            "音频文件 (*.mp3 *.wav *.ogg *.flac);;所有文件 (*.*)"
        )
        
        if file_path:
            slot = self.soundboard_slots.get(slot_id)
            if slot:
                slot["audio"] = file_path
                slot["name"] = file_path.split("/")[-1]  # 获取文件名
                slot["audio_label"].setText(slot["name"])
                slot["preview_button"].setEnabled(True)
                self._save_config()
                self.logger.info(f"槽位 #{slot_id + 1} 选择音频: {file_path}")
    
    def _preview_audio(self, slot_id):
        """预览音频"""
        slot = self.soundboard_slots.get(slot_id)
        if slot and slot["audio"]:
            self.logger.info(f"预览槽位 #{slot_id + 1} 音频: {slot['audio']}")
            
            # 使用voice_manager播放音频预览
            try:
                # 计算最终音量（主音量 × 槽位音量）
                final_volume = config.voice_output_volume * slot["volume"]
                
                # 获取音频时长
                duration = self.voice_manager.get_sound_duration(slot["audio"])
                
                # 播放音频（本地预览，不使用PTT）
                self.voice_manager.play_audio_with_ptt_protocol(
                    audio_path=slot["audio"],
                    volume=final_volume,
                    mode="覆盖",
                    also_local=True,  # 只在本地播放
                    ptt_key=None,  # 预览不使用PTT
                    ptt_delay=0
                )
                
                # 更新状态
                self.status_label.setText(f"🔊 预览: {slot['name']}")
                self._sync_overview_status()
                self.logger.info(f"预览成功: {slot['name']}, 音量: {format_percent(final_volume, hi=2.0)}")
                
                # 播放结束后自动清除状态
                if duration > 0:
                    clear_time = int((duration + 0.5) * 1000)  # 添加0.5秒缓冲
                    QTimer.singleShot(clear_time, self._clear_status)
            except Exception as e:
                self.status_label.setText(f"✗ 预览失败: {str(e)}")
                self._sync_overview_status()
                self.logger.error(f"预览音频失败: {e}")
                # 3秒后清除错误状态
                QTimer.singleShot(3000, self._clear_status)
    
    def _set_slot_hotkey(self, slot_id):
        """设置槽位快捷键"""
        self.logger.info(f"设置槽位 #{slot_id + 1} 快捷键")
        
        if self.is_listening_for_key:
            QMessageBox.warning(self, "提示", "正在监听其他快捷键，请稍候...")
            return
        
        self.is_listening_for_key = True
        self.current_listening_slot = slot_id
        
        # 更新按钮文字
        slot = self.soundboard_slots.get(slot_id)
        if slot:
            slot["key_button"].setText("按下按键...")
        
        # 在后台线程监听键盘输入（支持组合键）
        def listen_thread():
            hook_handle = None
            try:
                pressed_keys = set()  # 记录当前按下的所有键
                modifiers = {'ctrl', 'alt', 'shift', 'win'}  # 修饰键

                def on_key_event(event):
                    nonlocal pressed_keys

                    if event.event_type == 'down':
                        pressed_keys.add(event.name)

                        # 如果按下的不是修饰键，就完成快捷键设置
                        if event.name not in modifiers:
                            # 构建组合键字符串
                            hotkey_parts = []

                            # 按顺序添加修饰键
                            if 'ctrl' in pressed_keys:
                                hotkey_parts.append('ctrl')
                            if 'alt' in pressed_keys:
                                hotkey_parts.append('alt')
                            if 'shift' in pressed_keys:
                                hotkey_parts.append('shift')
                            if 'win' in pressed_keys:
                                hotkey_parts.append('win')

                            # 添加主键（过滤掉修饰键）
                            main_keys = [k for k in pressed_keys if k not in modifiers]
                            if main_keys:
                                hotkey_parts.append(main_keys[-1])  # 使用最后按下的非修饰键

                            hotkey = '+'.join(hotkey_parts)
                            self.hotkey_set_signal.emit(slot_id, hotkey)
                            return False  # 停止监听

                    elif event.event_type == 'up':
                        # 键释放时从集合中移除
                        pressed_keys.discard(event.name)

                    return True  # 继续监听

                hook_handle = keyboard.hook(on_key_event)
                # 等待10秒超时
                for _ in range(100):
                    if not self.is_listening_for_key:
                        break
                    threading.Event().wait(0.1)
            except Exception as e:
                self.logger.error(f"监听快捷键失败: {e}")
            finally:
                if hook_handle is not None:
                    try:
                        keyboard.unhook(hook_handle)
                    except Exception:
                        pass
                self.is_listening_for_key = False

        threading.Thread(target=listen_thread, daemon=True, name="VoiceHotkeyCapture").start()
    
    def _set_stop_key(self):
        """设置中断快捷键"""
        self.logger.info("设置中断快捷键")
        
        if self.is_listening_for_stop_key:
            QMessageBox.warning(self, "提示", "正在监听快捷键，请稍候...")
            return
        
        self.is_listening_for_stop_key = True
        self.stop_key_button.setText("按下按键...")
        
        def listen_thread():
            hook_handle = None
            try:
                pressed_keys = set()
                modifiers = {'ctrl', 'alt', 'shift', 'win'}

                def on_key_event(event):
                    nonlocal pressed_keys

                    if event.event_type == 'down':
                        pressed_keys.add(event.name)

                        if event.name not in modifiers:
                            hotkey_parts = []
                            if 'ctrl' in pressed_keys:
                                hotkey_parts.append('ctrl')
                            if 'alt' in pressed_keys:
                                hotkey_parts.append('alt')
                            if 'shift' in pressed_keys:
                                hotkey_parts.append('shift')
                            if 'win' in pressed_keys:
                                hotkey_parts.append('win')

                            main_keys = [k for k in pressed_keys if k not in modifiers]
                            if main_keys:
                                hotkey_parts.append(main_keys[-1])

                            hotkey = '+'.join(hotkey_parts)
                            self.stop_key_set_signal.emit(hotkey)
                            return False

                    elif event.event_type == 'up':
                        pressed_keys.discard(event.name)

                    return True

                hook_handle = keyboard.hook(on_key_event)
                for _ in range(100):
                    if not self.is_listening_for_stop_key:
                        break
                    threading.Event().wait(0.1)
            except Exception as e:
                self.logger.error(f"监听中断键失败: {e}")
            finally:
                if hook_handle is not None:
                    try:
                        keyboard.unhook(hook_handle)
                    except Exception:
                        pass
                self.is_listening_for_stop_key = False

        threading.Thread(target=listen_thread, daemon=True, name="VoiceStopKeyCapture").start()

    def _set_ptt_key(self):
        """设置PTT快捷键"""
        self.logger.info("设置PTT快捷键")
        
        if self.is_listening_for_ptt_key:
            QMessageBox.warning(self, "提示", "正在监听快捷键，请稍候...")
            return
        
        self.is_listening_for_ptt_key = True
        self.ptt_key_button.setText("按下按键...")
        
        def listen_thread():
            hook_handle = None
            try:
                pressed_keys = set()
                modifiers = {'ctrl', 'alt', 'shift', 'win'}

                def on_key_event(event):
                    nonlocal pressed_keys

                    if event.event_type == 'down':
                        pressed_keys.add(event.name)

                        if event.name not in modifiers:
                            hotkey_parts = []
                            if 'ctrl' in pressed_keys:
                                hotkey_parts.append('ctrl')
                            if 'alt' in pressed_keys:
                                hotkey_parts.append('alt')
                            if 'shift' in pressed_keys:
                                hotkey_parts.append('shift')
                            if 'win' in pressed_keys:
                                hotkey_parts.append('win')

                            main_keys = [k for k in pressed_keys if k not in modifiers]
                            if main_keys:
                                hotkey_parts.append(main_keys[-1])

                            hotkey = '+'.join(hotkey_parts)
                            self.ptt_key_set_signal.emit(hotkey)
                            return False

                    elif event.event_type == 'up':
                        pressed_keys.discard(event.name)

                    return True

                hook_handle = keyboard.hook(on_key_event)
                for _ in range(100):
                    if not self.is_listening_for_ptt_key:
                        break
                    threading.Event().wait(0.1)
            except Exception as e:
                self.logger.error(f"监听PTT键失败: {e}")
            finally:
                if hook_handle is not None:
                    try:
                        keyboard.unhook(hook_handle)
                    except Exception:
                        pass
                self.is_listening_for_ptt_key = False

        threading.Thread(target=listen_thread, daemon=True, name="VoicePTTKeyCapture").start()
    
    def _update_volume(self, value):
        """更新主音量"""
        volume = value / 100.0
        config.voice_output_volume = volume
        config.save_config()
        self.volume_label.setText(f"{value}%")
        # voice_manager 没有 set_volume 方法，音量在播放时通过参数传递
        self.logger.info(f"主音量更新: {value}%")
        self._sync_overview_status()
    
    def _update_play_mode(self, mode):
        """更新播放模式"""
        config.voice_output_mode = mode
        config.save_config()
        self.logger.info(f"播放模式: {mode}")
        
        # 混音模式需要启动麦克风穿透
        if mode in ["混音", "自动"]:
            self._ensure_microphone_passthrough()
        else:
            # 覆盖模式不需要麦克风穿透，可以停止
            if self.voice_manager.microphone_passthrough_active:
                self.voice_manager.stop_microphone_passthrough()
                self.logger.info("已停止麦克风穿透（覆盖模式）")
        self._sync_overview_status()
    
    def _update_microphone(self, mic):
        """更新麦克风选择"""
        config.voice_output_microphone = mic
        config.save_config()
        self.logger.info(f"麦克风选择: {mic}")
        
        # 如果麦克风穿透正在运行，重启以应用新麦克风
        if self.voice_manager.microphone_passthrough_active:
            self.voice_manager.stop_microphone_passthrough()
            self._ensure_microphone_passthrough()
        self._sync_overview_status()
    
    def _update_also_local(self, state):
        """更新本地监听"""
        enabled = self._is_checked_state(state)
        config.voice_output_also_local = enabled
        config.save_config()
        self.logger.info(f"本地监听: {enabled}")
        self._sync_overview_status()
    
    def _update_ptt_enabled(self, state):
        """更新PTT启用状态"""
        self.ptt_enabled = self._is_checked_state(state)
        config.voice_output_ptt_enabled = self.ptt_enabled
        config.save_config()
        self.logger.info(f"PTT启用: {self.ptt_enabled}")
        self._sync_overview_status()
    
    def _update_slot_volume(self, slot_id, value):
        """更新槽位音量"""
        slot = self.soundboard_slots.get(slot_id)
        if slot:
            volume = value / 100.0
            slot["volume"] = volume
            slot["volume_label"].setText(f"{value}%")
            self._save_config()
    
    def _update_sfx_forwarding(self, state):
        """更新音效转发开关"""
        enabled = self._is_checked_state(state)
        state_value = getattr(state, "value", state)
        self.logger.info(
            f"[音效转发开关] state={state}, state(int)={state_value}, Qt.Checked={Qt.CheckState.Checked}, enabled={enabled}"
        )
        self.logger.info(f"[音效转发开关] 当前配置值={config.sfx_forwarding_enabled}, 新值={enabled}")
        
        config.sfx_forwarding_enabled = enabled
        config.save_config()
        
        self.logger.info(f"[音效转发开关] 已保存配置: {enabled}")
        self.logger.info(f"[音效转发开关] config.json 中的值: {config.sfx_forwarding_enabled}")
        self._sync_overview_status()
    
    def _update_sfx_option(self, option_key, enabled):
        """更新音效转发选项"""
        if not hasattr(config, 'sfx_forwarding_options'):
            config.sfx_forwarding_options = {}
        
        config.sfx_forwarding_options[option_key] = enabled
        config.save_config()
        self.logger.info(f"音效转发选项 {option_key}: {enabled}")
        self._sync_overview_status()
    
    def _import_config(self):
        """导入配置"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入配置",
            "",
            "JSON文件 (*.json);;所有文件 (*.*)"
        )

        if file_path:
            try:
                from core.io_validation import load_json_checked, validate_voice_config
                data = load_json_checked(file_path)
                ok, cleaned, errors = validate_voice_config(data)
                if not ok:
                    QMessageBox.warning(self, "导入未完成", "配置文件无法识别或字段类型不正确，请确认是本软件导出的语音配置后重试。")
                    self.logger.warning(f"语音配置导入被拒: {errors}")
                    return
                for cfg_key, value in cleaned.items():
                    setattr(config, cfg_key, value)
                config.save_config()

                # 重新加载UI
                self._reload_slots_from_config()
                QMessageBox.information(self, "成功", "配置导入成功！")
                self.logger.info(f"导入配置: {file_path}")
            except ValueError as e:
                QMessageBox.warning(self, "导入未完成", "文件过大或不是有效的配置文件，请确认后重试。")
                self.logger.warning(f"语音配置导入校验失败: {e}")
            except Exception as e:
                QMessageBox.critical(self, "错误", "导入失败：文件可能被占用或损坏，请稍后重试。")
                self.logger.error(f"导入配置失败: {e}")

    def _reload_slots_from_config(self):
        """从config重新加载槽位到UI"""
        slots_config = config.voice_output_slots if hasattr(config, 'voice_output_slots') else {}
        for slot_id, slot in self.soundboard_slots.items():
            str_id = str(slot_id)
            if str_id in slots_config:
                saved = slots_config[str_id]
                slot["key"] = saved.get("key", "")
                slot["audio"] = saved.get("audio", "")
                slot["volume"] = saved.get("volume", 1.0)
                slot["name"] = saved.get("name", "")
                slot["key_button"].setText(slot["key"] if slot["key"] else "未设置")
                slot["audio_label"].setText(slot["name"] if slot["name"] else (slot["audio"] or "未选择"))
                slot["preview_button"].setEnabled(bool(slot["audio"]))
                slot["volume_slider"].setValue(int(slot["volume"] * 100))
                slot["volume_label"].setText(format_percent(slot['volume'], hi=2.0))
            else:
                slot["key"] = ""
                slot["audio"] = ""
                slot["volume"] = 1.0
                slot["name"] = ""
                slot["key_button"].setText("未设置")
                slot["audio_label"].setText("未选择")
                slot["preview_button"].setEnabled(False)
                slot["volume_slider"].setValue(100)
                slot["volume_label"].setText("100%")
        # 更新其他设置
        if hasattr(config, 'voice_output_stop_key') and config.voice_output_stop_key:
            self.stop_hotkey = config.voice_output_stop_key
            self.stop_key_button.setText(self.stop_hotkey)
        if hasattr(config, 'voice_output_ptt_key') and config.voice_output_ptt_key:
            self.ptt_key = config.voice_output_ptt_key
            self.ptt_key_button.setText(self.ptt_key)
        # 重新注册快捷键
        if hasattr(self, '_register_hotkeys_func'):
            self._register_hotkeys_func()
        self._sync_overview_status()

    def _export_config(self):
        """导出配置"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出配置",
            "voice_output_config.json",
            "JSON文件 (*.json);;所有文件 (*.*)"
        )

        if file_path:
            try:
                import json
                data = {
                    "slots": {},
                    "stop_key": getattr(config, 'voice_output_stop_key', ''),
                    "ptt_key": getattr(config, 'voice_output_ptt_key', ''),
                    "ptt_enabled": getattr(config, 'voice_output_ptt_enabled', False),
                    "volume": getattr(config, 'voice_output_volume', 1.0),
                    "mode": getattr(config, 'voice_output_mode', '覆盖'),
                }
                for slot_id, slot in self.soundboard_slots.items():
                    if slot["audio"]:
                        data["slots"][str(slot_id)] = {
                            "key": slot["key"],
                            "audio": slot["audio"],
                            "volume": slot["volume"],
                            "name": slot["name"]
                        }
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                QMessageBox.information(self, "成功", "配置导出成功！")
                self.logger.info(f"导出配置: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", "导出失败：目标位置可能无写入权限或磁盘空间不足，请换个位置后重试。")
                self.logger.error(f"导出配置失败: {e}")
    
    def _install_vb_cable(self):
        """安装VB-Cable驱动（使用Qt对话框）"""
        self.logger.info("安装VB-Cable驱动")

        # 检查是否已安装
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            for device in devices:
                if 'CABLE' in device['name']:
                    QMessageBox.information(
                        self, "VB-Cable已安装",
                        "检测到VB-Cable虚拟音频驱动已经安装。\n\n"
                        "如果遇到问题，请尝试：\n"
                        "1. 重启电脑\n"
                        "2. 在Windows声音设置中检查设备"
                    )
                    return
        except Exception:
            pass

        # 确认安装
        result = QMessageBox.question(
            self, "安装VB-Cable虚拟音频驱动",
            "语音播放功能需要安装VB-Cable虚拟音频驱动。\n\n"
            "这是一个免费、安全的虚拟音频设备驱动，\n"
            "被SoundPad等专业软件广泛使用。\n\n"
            "是否现在安装？（需要管理员权限）",
            QMessageBox.Yes | QMessageBox.No
        )

        if result != QMessageBox.Yes:
            return

        # 在后台线程执行下载和安装
        def install_worker():
            import tempfile
            import zipfile
            import ctypes
            import subprocess
            temp_dir = None
            try:
                temp_dir = tempfile.mkdtemp(prefix="vbcable_")
                zip_path = os.path.join(temp_dir, "vbcable.zip")

                self._status_signal.emit("正在下载VB-Cable驱动...")
                url = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack43.zip"
                _download_to_file(url, zip_path, timeout=30)   # QA-014

                # 完整性校验：驱动级安装物必须校验，防下载被劫持/损坏。
                # 基准值为官方 Pack43 包的 SHA256（2026-07 从官方源计算）。
                # 官方若原地更新包会导致校验失败——那也应当失败并由我们更新基准值，
                # 而不是把未知内容装进内核驱动。
                expected_sha256 = "66fd0a4d9f4896ff41632b7e3d53892c085c4561f53e8ae8d0f0bc10eedd1cdd"
                import hashlib
                digest = hashlib.sha256()
                with open(zip_path, "rb") as fh:
                    for block in iter(lambda: fh.read(1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest() != expected_sha256:
                    self.logger.error(
                        f"VB-Cable 包校验失败: 期望 {expected_sha256}, 实际 {digest.hexdigest()}"
                    )
                    self._status_signal.emit("✗ 驱动包校验失败，已中止安装（可能是下载损坏或来源异常）")
                    return

                self._status_signal.emit("正在解压驱动文件...")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)

                # 查找安装程序
                import sys
                is_64bit = sys.maxsize > 2**32
                installer_name = "VBCABLE_Setup_x64.exe" if is_64bit else "VBCABLE_Setup.exe"
                installer_path = None
                for root, dirs, files in os.walk(temp_dir):
                    if installer_name in files:
                        installer_path = os.path.join(root, installer_name)
                        break

                if not installer_path:
                    self._status_signal.emit("✗ 未找到安装程序")
                    return

                self._status_signal.emit("正在安装驱动（请在弹出窗口中确认）...")

                # 以管理员权限运行安装程序
                is_admin = ctypes.windll.shell32.IsUserAnAdmin()
                if is_admin:
                    process = subprocess.Popen([installer_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    process.communicate()  # 读干 stdout/stderr 再等待:避免输出填满 PIPE 缓冲导致 wait() 死锁
                else:
                    ctypes.windll.shell32.ShellExecuteW(None, "runas", installer_path, None, None, 1)
                    # 等待用户完成安装
                    import time
                    time.sleep(5)

                # 验证安装
                import time
                time.sleep(2)
                import sounddevice as sd
                devices = sd.query_devices()
                installed = any('CABLE' in d['name'] for d in devices)
                if installed:
                    self._status_signal.emit("✓ VB-Cable安装成功！")
                    self.logger.info("VB-Cable安装成功")
                else:
                    self._status_signal.emit("⚠ 安装后未检测到设备，请重启电脑")
            except Exception as e:
                self._status_signal.emit(f"✗ 安装失败: {str(e)}")
                self.logger.error(f"VB-Cable安装失败: {e}")
            finally:
                if temp_dir:
                    try:
                        import shutil
                        shutil.rmtree(temp_dir)
                    except Exception:
                        pass

        import os
        threading.Thread(target=install_worker, daemon=True, name="VBCableInstall").start()
    
    def _show_instructions(self):
        """显示使用说明"""
        instructions = """
        <h2>语音输出使用说明</h2>
        <h3>功能概述</h3>
        <p>语音输出功能允许您将音频文件通过游戏语音播放给队友。</p>
        
        <h3>使用步骤</h3>
        <ol>
            <li>确保已安装VB-Cable虚拟音频驱动</li>
            <li>在游戏中设置麦克风为"CABLE Output"</li>
            <li>添加音板槽位，选择音频文件</li>
            <li>为每个槽位设置快捷键</li>
            <li>在游戏中按快捷键即可播放</li>
        </ol>
        
        <h3>播放模式</h3>
        <ul>
            <li><b>覆盖模式：</b>音频直接输出到虚拟设备，不传递麦克风声音</li>
            <li><b>混音模式：</b>将音频与麦克风混音输出，音频和语音同时播放</li>
            <li><b>自动模式：</b>智能切换，无音频时麦克风穿透，播放时音频覆盖，播放结束恢复穿透（推荐）</li>
        </ul>
        
        <h3>PTT（开麦键）</h3>
        <p>启用PTT后，播放音频前会自动按下开麦键，播放完成后释放。</p>
        
        <h3>模式选择建议</h3>
        <ul>
            <li><b>覆盖模式：</b>只想播放音频，不需要说话时使用</li>
            <li><b>混音模式：</b>需要一边播放音频一边说话时使用</li>
            <li><b>自动模式：</b>平时说话，播放时自动切换为音频（最智能）</li>
        </ul>
        """
        
        msg = QMessageBox(self)
        msg.setWindowTitle("使用说明")
        msg.setText(instructions)
        msg.setTextFormat(Qt.RichText)
        msg.setIcon(QMessageBox.Information)
        msg.exec()
    
    def _load_config(self):
        """加载配置"""
        self.logger.info("加载语音输出配置")
        # 配置在_initialize_slots中已加载
        
        # 检测VB-Cable状态
        self._check_vb_cable_status()
        self._sync_overview_status()
        
        # 如果当前模式是混音，启动麦克风穿透
        if getattr(config, "voice_output_mode", "覆盖") in ["混音", "自动"]:
            QTimer.singleShot(500, self._ensure_microphone_passthrough)
    
    def _ensure_microphone_passthrough(self):
        """确保麦克风穿透已启动（混音模式需要）"""
        if self.voice_manager.microphone_passthrough_active:
            self.logger.info("麦克风穿透已在运行")
            return
        
        # 获取选中的麦克风(UP-028: 用稳定 key,不用展示文案)
        selected_mic = self._current_microphone_key()
        if not selected_mic or selected_mic == "默认":
            # 尝试从配置加载
            saved = str(getattr(config, "voice_output_microphone", "") or "")
            if saved:
                idx = self.mic_combo.findData(saved)
                if idx < 0:
                    idx = self.mic_combo.findText(saved)
                if idx >= 0:
                    self.mic_combo.setCurrentIndex(idx)
                    selected_mic = self._current_microphone_key()
        
        # 启动麦克风穿透
        self.logger.info(f"启动麦克风穿透: {selected_mic}")
        success = self.voice_manager.start_microphone_passthrough(selected_mic)
        
        if success:
            self.status_label.setText(f"✓ 麦克风穿透已启动: {selected_mic}")
            self._sync_overview_status()
            self.logger.info(f"麦克风穿透启动成功: {selected_mic}")
            # 3秒后清除状态
            QTimer.singleShot(3000, self._clear_status)
        else:
            self.status_label.setText("✗ 麦克风穿透启动失败")
            self._sync_overview_status()
            self.logger.error("麦克风穿透启动失败")
    
    def _check_vb_cable_status(self):
        """检测VB-Cable设备状态"""
        if self.voice_manager.vb_cable_device_id is not None:
            # UP-049: 全站同义符号只有这两处用彩色 emoji,其余 9 处都是单色 ✓/✗
            self.vb_status_label.setText("✓ VB-Cable已就绪")
            self.install_button.setEnabled(False)
            self.logger.info(f"VB-Cable设备已检测到 (ID: {self.voice_manager.vb_cable_device_id})")
        else:
            self.vb_status_label.setText("✗ VB-Cable未安装")
            self.install_button.setEnabled(True)
            self.logger.warning("VB-Cable设备未检测到")
        
        # 更新麦克风列表
        self._update_microphone_list()
        self._sync_overview_status()
    
    def _update_microphone_list(self):
        """更新麦克风设备列表。

        UP-028: 原来只列原始设备名 + `findText()` 恢复。同一支麦在
        MME/WASAPI/DirectSound 下各出现一次、名字完全相同（实测 25 个设备里 4 条同名），
        于是 `findText` 只认第一条——**用户选的设备下次启动会被悄悄换掉**，
        而且用户在界面上根本没法把它们区分开。
        现在：展示名给重名的补序号，选中项另存一个稳定 key 到 itemData，
        恢复时优先按 key 精确匹配。
        """
        preferred = (
            str(getattr(config, "voice_output_microphone", "") or "").strip()
            or self.mic_combo.currentData()
            or self.mic_combo.currentText().strip()
            or "默认"
        )
        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()

        if hasattr(self.voice_manager, "get_microphone_entries"):
            for entry in self.voice_manager.get_microphone_entries():
                self.mic_combo.addItem(entry["label"], entry["key"])
        elif hasattr(self.voice_manager, 'get_microphone_list'):
            # 兼容旧 manager（含测试替身）：没有 key，就拿名字当 key
            for mic_name in self.voice_manager.get_microphone_list():
                self.mic_combo.addItem(mic_name, mic_name)
        else:
            self.mic_combo.addItem("默认", "默认")
            for mic_dict in getattr(self.voice_manager, 'microphone_devices', []):
                if isinstance(mic_dict, dict) and 'name' in mic_dict:
                    self.mic_combo.addItem(mic_dict['name'], mic_dict['name'])

        # 先按 key 精确恢复；再按展示名；最后才回退默认。
        # 旧配置里存的是纯设备名，所以名字这一路必须保留。
        saved_index = self.mic_combo.findData(preferred)
        if saved_index < 0:
            saved_index = self.mic_combo.findText(preferred)
        if saved_index >= 0:
            self.mic_combo.setCurrentIndex(saved_index)
        elif self.mic_combo.count() > 0:
            default_index = self.mic_combo.findText("默认")
            self.mic_combo.setCurrentIndex(default_index if default_index >= 0 else 0)

        self.mic_combo.blockSignals(False)
        # 统计"因为重名而被加了序号"的条数。
        # 注意不能去数展示文案的重复数——消歧之后它必然是 0，那样的日志毫无信息量。
        renamed = sum(
            1 for i in range(self.mic_combo.count())
            if self.mic_combo.itemText(i).rstrip().endswith(")")
            and " (" in self.mic_combo.itemText(i)
            and self.mic_combo.itemText(i).rsplit(" (", 1)[-1][:-1].isdigit()
        )
        self.logger.info(
            f"麦克风列表已更新: {self.mic_combo.count()} 个设备"
            + (f"（{renamed} 条重名已加序号区分）" if renamed else "")
        )
        self._sync_overview_status()

    def _current_microphone_key(self) -> str:
        """当前选中麦克风的持久化标识（拿不到 key 就退回展示名）。"""
        data = self.mic_combo.currentData()
        return str(data) if data else self.mic_combo.currentText().strip()
    
    def _save_config(self):
        """保存配置"""
        # 保存槽位配置
        slots_data = {}
        for slot_id, slot in self.soundboard_slots.items():
            if slot["audio"]:  # 只保存已配置的槽位
                slots_data[str(slot_id)] = {
                    "key": slot["key"],
                    "audio": slot["audio"],
                    "volume": slot["volume"],
                    "name": slot["name"]
                }
        
        config.voice_output_slots = slots_data
        config.save_config()
        self.logger.info("保存语音输出配置")
        self._sync_overview_status()
        
        # 重新注册快捷键（配置变更后需要更新）
        if hasattr(self, '_register_hotkeys_func'):
            self._register_hotkeys_func()
    
    def _game_key_warning(self, key: str) -> str:
        """若热键含游戏常用键，返回一段提示文案(否则空串)。"""
        from core.hotkeys import registry as hotkey_registry
        if hotkey_registry.hotkey_has_game_critical_key(key):
            return (
                f"\n\n⚠ 注意：{key} 含游戏常用键（如 Ctrl/移动键/武器键）。"
                "为避免游戏内按键延迟或失灵，此键不会被拦截——按下时游戏也会收到。"
                "建议改用 F1-F12 等游戏用不到的键。"
            )
        return ""

    def _on_hotkey_set(self, slot_id, key):
        """槽位快捷键设置完成回调"""
        self.is_listening_for_key = False
        slot = self.soundboard_slots.get(slot_id)
        if slot:
            slot["key"] = key
            slot["key_button"].setText(key)
            self._save_config()
            self.logger.info(f"槽位 #{slot_id + 1} 快捷键设置为: {key}")
            QMessageBox.information(
                self, "成功",
                f"槽位 #{slot_id + 1} 快捷键已设置为: {key}{self._game_key_warning(key)}",
            )
    
    def _on_stop_key_set(self, key):
        """中断键设置完成回调"""
        self.is_listening_for_stop_key = False
        self.stop_hotkey = key
        self.stop_key_button.setText(key)
        config.voice_output_stop_key = key
        config.save_config()
        self.logger.info(f"中断键设置为: {key}")
        self._sync_overview_status()
        conflict = config.check_hotkey_conflict(key, "语音输出中断")
        if conflict:
            from ui_toast import toast_warning
            toast_warning(f"快捷键 {key} 已被「{conflict}」使用", 4000)
        # 重新注册快捷键（包括新的中断键）
        if hasattr(self, '_register_hotkeys_func'):
            self._register_hotkeys_func()
        QMessageBox.information(self, "成功", f"中断键已设置为: {key}{self._game_key_warning(key)}")
    
    def _on_ptt_key_set(self, key):
        """PTT键设置完成回调"""
        self.is_listening_for_ptt_key = False
        self.ptt_key = key
        self.ptt_key_button.setText(key)
        config.voice_output_ptt_key = key
        config.save_config()
        self.logger.info(f"PTT键设置为: {key}")
        self._sync_overview_status()
        conflict = config.check_hotkey_conflict(key, "语音自动开麦")
        if conflict:
            from ui_toast import toast_warning
            toast_warning(f"快捷键 {key} 已被「{conflict}」使用", 4000)
        QMessageBox.information(self, "成功", f"PTT键已设置为: {key}")
    
    HOTKEY_OWNER = "语音输出音板"

    def _start_global_hotkey_listener(self):
        """启动全局快捷键监听器（P2.1: 经热键注册中心，行为等价 add_hotkey suppress=True）"""
        self._registered_hotkeys = set()

        def _suppress_for(hotkey: str) -> bool:
            """决定该热键是否 suppress(拦截不传给游戏)。
            含游戏常用键(ctrl/移动键/武器键)时绝不 suppress——否则修饰键被扣住
            产生按键延迟(蹲键要过一会才生效)、移动键被吞。这类键放行给游戏，
            双触发(游戏也收到)是可接受的代价，远好于游戏操作卡顿。"""
            from core.hotkeys import registry as hotkey_registry
            if hotkey_registry.hotkey_has_game_critical_key(hotkey):
                self.logger.warning(
                    f"[音板] 快捷键 {hotkey} 含游戏常用键，改为不拦截(放行给游戏)以避免按键延迟/吞键"
                )
                return False
            return True

        self._hotkey_report_signal.connect(self._on_hotkey_report)

        def register_hotkeys():
            """注册当前所有快捷键"""
            from core.hotkeys import registry as hotkey_registry

            # 清除之前的快捷键（按功能域批量注销）
            hotkey_registry.unregister_owner(self.HOTKEY_OWNER)
            self._registered_hotkeys.clear()
            conflicts, failures = [], []

            # 语音总开关关闭时不注册任何全局热键：功能未启用就不应干预键盘
            # （历史 bug：即便关了语音，遗留的 ctrl 组合槽位仍在延迟游戏蹲键）
            if not getattr(config, "voice_output_enabled", False):
                self.logger.info("[音板] 语音播放未启用，跳过全局快捷键注册")
                self._hotkey_report_signal.emit([], [], 0)
                return

            # 注册槽位快捷键
            for slot_id, slot in self.soundboard_slots.items():
                if slot.get("key") and slot.get("audio"):
                    others = hotkey_registry.find_conflicts(slot["key"], exclude_owner=self.HOTKEY_OWNER)
                    if others:
                        self.logger.warning(
                            f"槽位 #{slot_id + 1} 快捷键 {slot['key']} 与「{'、'.join(others)}」冲突，可能双触发"
                        )
                        # UP-039: 高级设置页白纸黑字写着"改键时若与其他功能撞键,
                        # 对应页面会给出冲突提示"——但这里一直只有日志。
                        # 用户按下键发现两个功能一起触发,根本不知道是撞键了。
                        conflicts.append((f"槽位 #{slot_id + 1}", slot["key"], list(others)))
                    token = hotkey_registry.register_hotkey(
                        self.HOTKEY_OWNER, slot["key"],
                        lambda sid=slot_id: self._trigger_slot(sid),
                        suppress=_suppress_for(slot["key"]), note=f"音板槽位#{slot_id + 1}",
                    )
                    if token is not None:
                        self._registered_hotkeys.add(slot["key"])
                        self.logger.info(f"注册槽位 #{slot_id + 1} 快捷键: {slot['key']}")
                    else:
                        self.logger.error(f"注册槽位 #{slot_id + 1} 快捷键失败: {slot['key']}")
                        failures.append((f"槽位 #{slot_id + 1}", slot["key"]))

            # 注册中断键
            if self.stop_hotkey:
                token = hotkey_registry.register_hotkey(
                    self.HOTKEY_OWNER, self.stop_hotkey, self._stop_playback,
                    suppress=_suppress_for(self.stop_hotkey), note="音板中断键",
                )
                if token is not None:
                    self._registered_hotkeys.add(self.stop_hotkey)
                    self.logger.info(f"注册中断键: {self.stop_hotkey}")
                else:
                    self.logger.error(f"注册中断键失败: {self.stop_hotkey}")
                    failures.append(("中断键", self.stop_hotkey))

            self.logger.info(f"已注册 {len(self._registered_hotkeys)} 个快捷键")
            # UP-039: 结果经 Signal 回主线程再弹提示。
            # 直接在这里弹 toast 不安全——注册可能由配置变更链路在别处触发。
            self._hotkey_report_signal.emit(conflicts, failures,
                                            len(self._registered_hotkeys))

        # 保存注册函数供后续调用（配置变更时）
        self._register_hotkeys_func = register_hotkeys

        # 初始注册
        register_hotkeys()
    

    def _on_hotkey_report(self, conflicts, failures, ok_count):
        """UP-039: 把热键注册结果告诉用户，兑现高级设置页的那句承诺。

        高级设置页写着"改键时若与其他功能撞键，对应页面会给出冲突提示"，
        但注册链路一直只写日志——用户按下键发现两个功能一起触发，
        或者干脆没反应，都无从判断原因。
        """
        try:
            from ui_toast import toast_error, toast_warning

            for owner, key, others in (conflicts or []):
                toast_warning(
                    f"{owner} 的快捷键 {key} 与「{'、'.join(others)}」重复，按下会同时触发",
                    5000,
                )
            if failures:
                names = "、".join(f"{o}({k})" for o, k in failures)
                toast_error(f"这些快捷键注册失败，可能被其他程序占用：{names}", 6000)

            bar = getattr(self, "action_bar", None)
            if bar is not None and hasattr(bar, "set_message"):
                if failures:
                    bar.set_message(f"有 {len(failures)} 个快捷键注册失败，可能被其他程序占用。")
                elif conflicts:
                    bar.set_message(f"有 {len(conflicts)} 个快捷键与其他功能重复，按下会同时触发。")
                elif ok_count:
                    bar.set_message(f"音板快捷键已就绪（{ok_count} 个）。")
        except Exception:
            self.logger.exception("热键结果提示失败（不影响热键本身）")

    def _trigger_slot(self, slot_id):
        """触发槽位播放（从keyboard回调线程调用，通过信号更新UI）"""
        slot = self.soundboard_slots.get(slot_id)
        if slot and slot["audio"]:
            self.logger.info(f"[语音输出] 快捷键触发槽位 #{slot_id + 1}: {slot['audio']}")

            try:
                # 计算最终音量（主音量 × 槽位音量）
                final_volume = config.voice_output_volume * slot["volume"]

                # 获取PTT设置
                ptt_key_to_use = self.ptt_key if self.ptt_enabled else None

                self.logger.info(f"[语音输出] 播放参数 - 音量: {format_percent(final_volume, hi=2.0)}, PTT启用: {self.ptt_enabled}, PTT键: {ptt_key_to_use}, 延迟: {self.ptt_delay}ms")

                # 获取音频时长（用于自动清除状态）
                duration = self.voice_manager.get_sound_duration(slot["audio"])

                # 播放音频到游戏语音
                # 本方法由 keyboard 钩子线程调用：读 config 缓存值而非 Qt 控件
                # （控件与 config 由 _update_play_mode/_update_also_local 保持同步）
                self.voice_manager.play_audio_with_ptt_protocol(
                    audio_path=slot["audio"],
                    volume=final_volume,
                    mode=getattr(config, "voice_output_mode", "覆盖"),
                    also_local=bool(getattr(config, "voice_output_also_local", True)),
                    ptt_key=ptt_key_to_use,
                    ptt_delay=self.ptt_delay
                )

                # 通过信号更新状态（线程安全）
                self._status_signal.emit(f"▶ 播放: {slot['name']}")
                self.logger.info(f"[语音输出] 播放成功 - 主音量: {format_percent(config.voice_output_volume, hi=2.0)}, 槽位音量: {format_percent(slot['volume'], hi=2.0)}, 最终音量: {format_percent(final_volume, hi=2.0)}")

                # 播放结束后自动清除状态
                if duration > 0:
                    clear_time = int((duration + self.ptt_delay / 1000.0 + 1.5) * 1000)
                    self._status_clear_signal.emit(clear_time)
            except Exception as e:
                self._status_signal.emit(f"✗ 播放失败: {str(e)}")
                self.logger.error(f"[语音输出] 播放音频失败: {e}")
                self._status_clear_signal.emit(3000)
    
    def _clear_status(self):
        """清除状态标签"""
        self.status_label.setText("就绪")
        self._sync_overview_status()

    def _set_status_text(self, text):
        """线程安全的状态文本设置（由信号调用，在主线程执行）"""
        self.status_label.setText(text)
        self._sync_overview_status()
    
    def _stop_playback(self):
        """停止当前播放（从keyboard回调线程调用，通过信号更新UI）"""
        self.logger.info("中断播放")
        self.voice_manager.stop_playback()
        self._status_signal.emit("⏹ 播放已停止")
        self._status_clear_signal.emit(2000)

    def cleanup(self):
        """清理资源：注销所有全局快捷键（P2.1: 改经热键注册中心按 owner 注销）"""
        try:
            from core.hotkeys import registry as hotkey_registry

            removed = hotkey_registry.unregister_owner(self.HOTKEY_OWNER)
            if removed:
                self.logger.info(f"已注销 {removed} 个音板热键")
        except Exception:
            self.logger.exception("注销音板热键异常（忽略）")
        if hasattr(self, '_registered_hotkeys'):
            self._registered_hotkeys.clear()
        try:
            self._stop_playback()
        except Exception:
            pass
        self.logger.info("语音输出页面清理完成")
