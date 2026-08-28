# SPDX-License-Identifier: GPL-3.0-or-later
"""整活页：死亡后在屏幕边上贴一块竖屏刷短视频。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config import config
from core.fun.platforms import CUSTOM_KEY, PLATFORM_PRESETS, get_platform
from core.utils.logger import get_logger
from widgets.page_header import PageHeader
from widgets.settings_card import SettingsCard
from widgets.settings_row import SettingsRow

#: RN-429：死亡刷短视频用的是**贴屏浏览器窗口**（不是 Qt 覆盖层），但受同一条前提约束，本页同样早就自己写了 ⇒ 第二个阳性对照。
DRAWS_OVER_THE_GAME = True

# GSI map.mode 的取值 → 中文名。列常见的即可，勾了才生效。
MODE_OPTIONS = [
    ("deathmatch", "死亡竞赛"),
    ("casual", "休闲"),
    ("competitive", "竞技"),
    ("gungameprogressive", "军备竞赛"),
    ("gungametrbomb", "拆弹突击"),
    ("scrimcomp2v2", "搭档"),
    ("survival", "危险区"),
    ("custom", "自定义/社区服"),
]

SIDE_OPTIONS = [("right", "屏幕右侧"), ("left", "屏幕左侧")]


class FunPage(QWidget):
    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.logger = get_logger("FunPage")
        self.controller = controller
        self._loading = False
        self._mode_boxes = {}
        self._init_ui()
        self._load_settings()
        if self.controller is not None:
            self.controller.statusChanged.connect(self._on_status_changed)

    # ---- UI ----

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

        layout.addWidget(PageHeader(
            "死亡刷短视频",
            description="阵亡后在屏幕边上贴一块竖屏短视频，复活自动暂停并切回游戏。纯整活功能，默认关闭。",
            spacing=12,
        ))

        # 状态
        status_card, status_layout = SettingsCard.make("当前状态", None)
        self.status_label = QLabel("未启用")
        self.status_label.setObjectName("statusLabel")
        status_layout.addWidget(self.status_label)

        self.notice_label = QLabel(
            "需要游戏使用「全屏窗口化」显示模式。独占全屏下贴屏窗口无法压在游戏上层，"
            "切换还会导致画面黑屏数秒。"
        )
        self.notice_label.setObjectName("hintLabel")
        self.notice_label.setWordWrap(True)
        status_layout.addWidget(self.notice_label)
        layout.addWidget(status_card)

        # 总开关
        main_card, main_layout = SettingsCard.make(
            "总开关", "打开后会在后台预先备好浏览器窗口，阵亡时才显示出来。"
        )
        self.enable_box = QCheckBox("启用死亡刷短视频")
        self.enable_box.stateChanged.connect(self._on_enable_changed)
        main_layout.addWidget(self.enable_box)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.login_button = QPushButton("打开并登录抖音")
        self.login_button.clicked.connect(self._on_login_clicked)
        self.preview_button = QPushButton("预览效果")
        self.preview_button.clicked.connect(self._on_preview_clicked)
        self.retract_button = QPushButton("收回窗口")
        self.retract_button.clicked.connect(self._on_retract_clicked)
        for btn in (self.login_button, self.preview_button, self.retract_button):
            button_row.addWidget(btn)
        button_row.addStretch()
        main_layout.addLayout(button_row)

        login_hint = QLabel(
            "登录态保存在软件自己的浏览器数据目录里，与你日常使用的浏览器完全隔离；"
            "账号密码只在浏览器内输入，本软件不经手。"
        )
        login_hint.setObjectName("hintLabel")
        login_hint.setWordWrap(True)
        main_layout.addWidget(login_hint)
        layout.addWidget(main_card)

        # 触发条件
        trigger_card, trigger_layout = SettingsCard.make(
            "触发条件", "只在勾选的对局模式里生效。观战队友阵亡不会触发。"
        )
        grid = QGridLayout()
        grid.setSpacing(6)
        for index, (mode_key, mode_name) in enumerate(MODE_OPTIONS):
            box = QCheckBox(mode_name)
            box.stateChanged.connect(self._on_modes_changed)
            self._mode_boxes[mode_key] = box
            grid.addWidget(box, index // 3, index % 3)
        trigger_layout.addLayout(grid)

        self.max_per_match_spin = QSpinBox()
        self.max_per_match_spin.setRange(0, 999)
        self.max_per_match_spin.setSpecialValueText("不限")
        self.max_per_match_spin.valueChanged.connect(self._on_max_per_match_changed)
        trigger_layout.addWidget(SettingsRow(
            "每局最多触发", self.max_per_match_spin, hint="到达次数后本局不再弹出，换图重新计数。"
        ))

        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 10000)
        self.delay_spin.setSingleStep(100)
        self.delay_spin.setSuffix(" 毫秒")
        self.delay_spin.valueChanged.connect(self._on_delay_changed)
        trigger_layout.addWidget(SettingsRow(
            "阵亡后延迟弹出", self.delay_spin, hint="留一点缓冲，先看完自己的死亡镜头。"
        ))
        layout.addWidget(trigger_card)

        # 窗口
        window_card, window_layout = SettingsCard.make("窗口", "竖屏 9:16，贴在屏幕边缘。")
        self.side_combo = QComboBox()
        for value, name in SIDE_OPTIONS:
            self.side_combo.addItem(name, value)
        self.side_combo.currentIndexChanged.connect(self._on_side_changed)
        window_layout.addWidget(SettingsRow("贴在哪边", self.side_combo))

        self.height_slider = QSlider(Qt.Horizontal)
        self.height_slider.setRange(30, 100)
        self.height_slider.valueChanged.connect(self._on_height_changed)
        self.height_value_label = QLabel("")
        height_row = QHBoxLayout()
        height_row.addWidget(self.height_slider, 1)
        height_row.addWidget(self.height_value_label)
        height_holder = QWidget()
        height_holder.setLayout(height_row)
        window_layout.addWidget(SettingsRow("窗口高度", height_holder))
        layout.addWidget(window_card)

        # 内容
        content_card, content_layout = SettingsCard.make("看什么", None)
        self.platform_combo = QComboBox()
        for preset in PLATFORM_PRESETS:
            self.platform_combo.addItem(preset["name"], preset["key"])
        self.platform_combo.currentIndexChanged.connect(self._on_platform_changed)
        content_layout.addWidget(SettingsRow("平台", self.platform_combo))

        self.platform_form_label = QLabel("")
        self.platform_form_label.setObjectName("hintLabel")
        self.platform_form_label.setWordWrap(True)
        content_layout.addWidget(self.platform_form_label)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://")
        self.url_edit.editingFinished.connect(self._on_url_changed)
        self.url_row = SettingsRow("网址", self.url_edit, control_align="left")
        content_layout.addWidget(self.url_row)

        self.mobile_ua_box = QCheckBox("以手机模式打开（推荐）")
        self.mobile_ua_box.stateChanged.connect(self._on_mobile_ua_changed)
        content_layout.addWidget(self.mobile_ua_box)
        self.mobile_hint = QLabel("关掉会变成电脑版网页，在竖窗里会被挤成一团，基本没法看。")
        self.mobile_hint.setObjectName("hintLabel")
        self.mobile_hint.setWordWrap(True)
        content_layout.addWidget(self.mobile_hint)
        layout.addWidget(content_card)

        # 高级
        advanced_card, advanced_layout = SettingsCard.make("高级", None)
        self.max_stay_spin = QSpinBox()
        self.max_stay_spin.setRange(0, 3600)
        self.max_stay_spin.setSuffix(" 秒")
        self.max_stay_spin.setSpecialValueText("不自动收回")
        self.max_stay_spin.valueChanged.connect(self._on_max_stay_changed)
        advanced_layout.addWidget(SettingsRow(
            "最长停留", self.max_stay_spin,
            hint="退出游戏等情况下收不到复活信号时，靠这个兜底把窗口收回来。",
        ))
        layout.addWidget(advanced_card)

        layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll)

    # ---- 读写配置 ----

    def _load_settings(self):
        self._loading = True
        try:
            self.enable_box.setChecked(bool(getattr(config, "fun_afterlife_enabled", False)))
            enabled_modes = {str(m).lower() for m in (getattr(config, "fun_afterlife_modes", None) or [])}
            for mode_key, box in self._mode_boxes.items():
                box.setChecked(mode_key in enabled_modes)
            self.max_per_match_spin.setValue(int(getattr(config, "fun_afterlife_max_per_match", 0) or 0))
            self.delay_spin.setValue(int(getattr(config, "fun_afterlife_delay_ms", 800) or 0))
            side = str(getattr(config, "fun_afterlife_side", "right") or "right")
            index = self.side_combo.findData(side)
            self.side_combo.setCurrentIndex(index if index >= 0 else 0)
            ratio = float(getattr(config, "fun_afterlife_height_ratio", 0.82) or 0.82)
            self.height_slider.setValue(int(round(ratio * 100)))
            self.height_value_label.setText(f"{int(round(ratio * 100))}%")
            platform_key = str(getattr(config, "fun_afterlife_platform", "douyin") or "douyin")
            platform_index = self.platform_combo.findData(platform_key)
            self.platform_combo.setCurrentIndex(platform_index if platform_index >= 0 else 0)
            self.url_edit.setText(str(getattr(config, "fun_afterlife_url", "") or ""))
            self.mobile_ua_box.setChecked(bool(getattr(config, "fun_afterlife_mobile_ua", True)))
            self._sync_platform_widgets()
            self.max_stay_spin.setValue(int(getattr(config, "fun_afterlife_max_stay_sec", 180) or 0))
        finally:
            self._loading = False
        self._refresh_status()

    def _save(self, key, value):
        if self._loading:
            return
        setattr(config, key, value)
        config.save_config()

    def _on_enable_changed(self, _state):
        enabled = self.enable_box.isChecked()
        self._save("fun_afterlife_enabled", enabled)
        if self._loading or self.controller is None:
            return
        # 开关一变就要立刻见效：开了就预热备好窗口，关了就把浏览器进程收掉
        if enabled:
            self.controller.preheat()
        else:
            self.controller.shutdown()
        self._refresh_status()

    def _on_modes_changed(self, _state):
        selected = [key for key, box in self._mode_boxes.items() if box.isChecked()]
        self._save("fun_afterlife_modes", selected)
        self._refresh_status()

    def _on_max_per_match_changed(self, value):
        self._save("fun_afterlife_max_per_match", int(value))

    def _on_delay_changed(self, value):
        self._save("fun_afterlife_delay_ms", int(value))

    def _on_side_changed(self, _index):
        self._save("fun_afterlife_side", self.side_combo.currentData() or "right")

    def _on_height_changed(self, value):
        self.height_value_label.setText(f"{int(value)}%")
        self._save("fun_afterlife_height_ratio", round(value / 100.0, 2))

    def _on_platform_changed(self, _index):
        key = self.platform_combo.currentData() or "douyin"
        self._save("fun_afterlife_platform", key)
        self._sync_platform_widgets()
        if self._loading or self.controller is None:
            return
        # 网址和 UA 是浏览器启动参数，运行中改不了，必须整个重开
        self.controller.reload_platform()

    def _sync_platform_widgets(self):
        """自定义平台才让填网址、才让改 UA；选抖音时按预设走。"""
        key = self.platform_combo.currentData() or "douyin"
        preset = get_platform(key)
        is_custom = key == CUSTOM_KEY
        self.platform_form_label.setText(preset["form"])
        self.url_row.setVisible(is_custom)
        self.mobile_ua_box.setVisible(is_custom)
        self.mobile_hint.setVisible(is_custom)
        self.login_button.setText("打开网页并登录" if is_custom else f"打开并登录{preset['name']}")

    def _on_url_changed(self):
        text = self.url_edit.text().strip()
        self._save("fun_afterlife_url", text)
        if self._loading or self.controller is None:
            return
        self.controller.reload_platform()

    def _on_mobile_ua_changed(self, _state):
        self._save("fun_afterlife_mobile_ua", self.mobile_ua_box.isChecked())
        if self._loading or self.controller is None:
            return
        self.controller.reload_platform()

    def _on_max_stay_changed(self, value):
        self._save("fun_afterlife_max_stay_sec", int(value))

    # ---- 按钮 ----

    def _on_login_clicked(self):
        if self.controller is None:
            return
        if not self.controller.open_login():
            self.status_label.setText("打开失败，请检查是否安装了 Edge 或 Chrome")

    def _on_preview_clicked(self):
        if self.controller is None:
            return
        if not self.controller.preview():
            self.status_label.setText("预览失败，请检查是否安装了 Edge 或 Chrome")

    def _on_retract_clicked(self):
        if self.controller is not None:
            self.controller.retract_now()

    # ---- 状态 ----

    def _on_status_changed(self, text):
        self.status_label.setText(text)

    def _refresh_status(self):
        if not self.enable_box.isChecked():
            self.status_label.setText("未启用")
            return
        if not any(box.isChecked() for box in self._mode_boxes.values()):
            self.status_label.setText("已启用，但没有勾选任何对局模式，不会触发")
            return
        self.status_label.setText("已启用")
