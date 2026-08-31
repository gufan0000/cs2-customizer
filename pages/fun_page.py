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
from page_theme_helper import style_as_primary_button, style_as_secondary_button
from pages.audio_status_badge import create_badge_label, render_badges
from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
from widgets.master_switch_link import make_master_switch_row
from widgets.overlay_requirement import make_overlay_requirement_label
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

        # ⚠ RN-001b（批 34）：这一页是全站 22/28 有帮助面板里**没有**的那几页之一，
        # 而外审 ④「你想知道这功能怎么用，这一屏上有地方问吗」**6/6 答「没有」**。
        header = PageHeader(
            "死亡刷短视频",
            description="阵亡后在屏幕边上贴一块竖屏短视频，复活自动暂停并切回游戏。纯整活功能，默认关闭。",
            spacing=12,
        )
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["fun_afterlife"])

        # 状态
        status_card, status_layout = SettingsCard.make("当前状态", None)

        # ⚠⚠ RN-190（批 34）：这一页原来手搓了一颗 `QCheckBox("启用死亡刷短视频")`，
        # 自己 `setattr`、自己调 preheat/shutdown。实测后果不是"少了个组件"，
        # 是**方向不对称的同步**：首页拨 → 页面会跟（`_on_switch_changed` 调
        # `page._load_settings()`），而**页面拨 → 首页那颗一动不动**（RN-107 族）。
        # ⭐ 全站 16 个首页功能开关里，另外 **15 个**都走这一行共用件；
        #   而它不只是"开关"——它自带双向同步、自带那句「现在可以调、改了会保存；
        #   游戏里还不生效」、自带参数区降权三件套。
        #   **一件一件补，就是一件一件会漏。**
        self.master_switch_row = make_master_switch_row(
            self, "fun_afterlife_enabled", "死亡刷短视频")
        status_layout.addWidget(self.master_switch_row)

        # ⚠ RN-102 族（批 34）：状态原来是一行裸文字，而全站 26/28 页用徽章条。
        self.status_badge_label = create_badge_label()
        status_layout.addWidget(self.status_badge_label)

        self.status_label = QLabel("未启用")
        self.status_label.setObjectName("hintLabel")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)

        # ⚠ RN-429（批 34）：这句话原来是本页**手写**的一份。共用件在
        # `widgets/overlay_requirement.py`（批 22 收出来的唯一一份）。
        # ⭐⭐ 批 24「共用件省的是重复，不是判断」的背面：
        #   **手写一份，就等于把自己从后续每一次改进里摘出去。**
        self.notice_label = make_overlay_requirement_label("短视频窗口")
        status_layout.addWidget(self.notice_label)
        layout.addWidget(status_card)

        # 总开关
        # ⚠ 总开关已经搬到上面那张状态卡的第一行（全站惯例：
        #   开关是这张卡的第一个扫视落点）。这里只剩「先做哪一步」。
        # ⚠⚠ 批 34 改完复跑逼出来的：把这张卡改名叫「第一次使用」又给了它一颗主按钮，
        # 于是「缺主流程指引 / 不知道该先开开关还是先登录」从改前 **1 发涨到 4 发** ——
        # ⭐ **我没有造出这个弱点，但我把它变响了**（批 33 同形：
        #   一句正确的指路，会把路那一头的问题顶到前台）。
        # ⇒ 那就把步骤真的排出来，别只改名字。
        main_card, main_layout = SettingsCard.make(
            "第一次使用",
            # ⚠⚠ 二版复跑：步骤排出来之后，抱怨**换了形状** ——
            # 改前是「不知道该先做什么」，二版变成
            # 「步骤引导在界面中『看中间→点下方→回上方开总开关→去底部勾选模式』，
            #   操作动线上下反复」。
            # ⭐⭐⭐ **票数从 3→6→5，而它指的东西在中途换了；票数没告诉我这件事，
            #   读原文才告诉我。**
            # ⇒ 序号按**屏幕从上到下**重排；「改 CS2 显示模式」那一步不进编号 ——
            #   它已经有自己那条 ⚠ 提示（就在上面那张卡里），
            #   写进来就是同一句话在一屏里说两遍（二版也有一发点了这个）。
            # ⚠⚠⚠ 三版那句写成了「打开**上面**那颗总开关 · 点**下面**那颗紫的 ·
            #   **再往下**勾」——**两条既有判据同时逮住它**：
            #   `test_no_copy_about_the_master_switch_describes_where_it_sits`
            #   与 `test_no_layout_self_talk_in_any_card_subtitle`。
            # ⭐⭐⭐ 而它们说的是同一件事，批 1 的原话就写在共用件里：
            #   **「需要用文字指路的控件，就是放错了地方 —— 指路是症状，不是修法。」**
            #   我为了修「动线上下反复」而写的那句话，正好是那条症状本身。
            # ⇒ 撤掉全部方位词：步骤仍按屏幕从上到下排，但一个「上面/下面」都不说。
            "① 打开总开关　② 先登录一次　③ 勾上你实际会玩的对局模式",
        )

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        # ⚠ 批 34：这三颗原来**一个层级都没有**（`style_as_*` 一次都没调），
        # 而它们的份量差得远。外审 ③ 有 5/6 把「预览效果」读成「只是打开东西看看」，
        # 而它其实会在屏幕上真的弹出一块贴屏窗口。
        # ⭐ 第一次使用必须先登录（没登录刷不出内容）⇒ 那一颗才是主按钮。
        self.login_button = QPushButton("打开并登录抖音")
        style_as_primary_button(self.login_button)
        self.login_button.clicked.connect(self._on_login_clicked)
        self.preview_button = QPushButton("预览效果")
        style_as_secondary_button(self.preview_button)
        self.preview_button.clicked.connect(self._on_preview_clicked)
        self.retract_button = QPushButton("收回窗口")
        style_as_secondary_button(self.retract_button)
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
            self.master_switch_row.refresh()
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

    def on_master_switch_synced(self):
        """总开关被别处拨动后，把本页状态重算一遍。

        ⭐ 全仓统一的钩子名（`widgets/master_switch_link` 调它）。
        ⚠ preheat / shutdown 那串副作用**不在这里做** —— 它们挂在
        `gui_widget._on_switch_changed` 上，也就是那条唯一的链路。
        RN-190 的要害正是这一页原来自己又做了一遍。
        ⭐ **同一件事只能有一条链路；第二条一定会缺东西，而缺的那部分不报错。**
        """
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
        """⭐⭐⭐ 「已启用」这三个字，对一个只打竞技的人是假的。

        默认触发模式是 `["deathmatch", "casual"]` —— **不含竞技、不含搭档**，
        而原来只有「一个都没勾」时才说「不会触发」；勾了死亡竞赛+休闲的人
        看到的是干干净净的「已启用」。外审 S4 档 **4/4** 报
        「竞技默认未勾选，玩家会误以为功能失效」。

        ⚠ 而**判断题那把尺子看不到这条**：整页图上问「你只打竞技会不会弹」，
        改前 **6/6 答「不会」**、依据逐字指向「竞技未勾选」——它们看得出来。
        ⭐⭐⭐ 两个数不矛盾，**它们量的是不同的时刻**：判断题问的是
        「你现在看着这一屏看得出来吗」，而这条缺陷发作在他**离开这一屏、
        进游戏死了之后**。⇒ **判断题默认「用户正看着这一屏」。**

        ⇒ 修法不是改默认值（那是替所有人做选择），是**把生效范围写出来**。
        """
        enabled = bool(getattr(config, "fun_afterlife_enabled", False))
        picked = [name for key, name in MODE_OPTIONS
                  if self._mode_boxes[key].isChecked()]
        badges = [
            ("positive" if enabled else "warning",
             f"总开关 · {'已开启' if enabled else '未开启'}"),
            ("positive" if picked else "warning", f"触发模式 · {len(picked)} 个"),
            ("info", f"平台 · {self.platform_combo.currentText() or '抖音'}"),
        ]
        render_badges(self.status_badge_label, badges)

        if not enabled:
            self.status_label.setText("未启用。打开上面的总开关之后才会在阵亡时弹出。")
            return
        if not picked:
            self.status_label.setText("已启用，但没有勾选任何对局模式，不会触发")
            return
        self.status_label.setText(
            "已启用 · 只在「" + " / ".join(picked) + "」里触发；"
            "其它模式阵亡不会弹出。"
        )
