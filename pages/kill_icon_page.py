# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标设置页（KI-7：只服务「用素材的人」）。

**KI-6 做对了功能，但把编辑器当成了首页。** 那一版把五个击杀等级摊成一块
清单板，每格自带预览、时长滑条、右键菜单——功能上是对的，可它摆在页面正中。
于是一个只想"下载一套图标、拖进去、开着"的人，一进来就要面对 30 多个可操作
控件和七八个概念（等级 / 爆头变体 / 帧率 / 定格 / 图集 / 帧序列 / 裁边 /
抠背景）。参照物就在同一个软件里：击杀音效页没让用户逐帧调音频，准心页也
没让用户逐像素画十字。

所以 KI-7 把这一页拆成两层：

* **这一页**只回答三件事——用哪一套、放在屏幕哪儿、开没开。
  控件从 30+ 降到个位数，风格从下拉框换成**看得见的卡片**（原来换之前
  根本不知道会换成什么样，而"挑一套图标"恰恰是这一页最主要的动作）。
* **素材工坊**（`dialogs/kill_icon_workshop.py`）装走清单板、每格的节奏、
  导出、删除与撤销、以及抠背景/裁边/行列/批量。**一个功能都没删。**

导入也收成了一个入口：不管拖的是 zip / 动图 / 帧序列文件夹 / 单张图，都走
`dialogs/kill_icon_import_wizard.py`，最多问一句「用在几杀」——文件名认得出
（`3hs.gif`）就连这一句都不问。裁边、抠背景、帧率、定格时长全部自动判。

底层一行没动：格式兼容、zip 安全校验、`hold_seconds`、图集约定、导入导出
往返判据，全部原样。这一轮改的只是**露出来的那一面**。
"""


from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QSlider, QFrame, QScrollArea, QFileDialog, QProgressBar,
    QSizePolicy
)
from PySide6.QtCore import Qt, QTimer

from config import config
from resource_manager import ResourceManager
from core.kill_icon_library import LEVELS, style_summary
from core.utils.logger import get_logger
from core.utils.format_utils import format_percent
from kill_icon_overlay import load_level_animation
from pages.audio_status_badge import create_badge_label, render_badges
from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
from widgets.drop_import_mixin import enable_file_drop
from widgets.kill_icon_import_task import KillIconImportTask
from widgets.kill_icon_level_grid import DROP_EXTENSIONS
from widgets.kill_icon_preview import KillIconPositionMap, KillIconPreview
from widgets.kill_icon_style_strip import KillIconStyleStrip
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard

#: 试播用哪一个等级。5 杀（ACE）通常是一套风格里最好看的那一张；
#: 没有素材时会自动往下找，见 `_test_level`。
DEFAULT_TEST_LEVEL = 5


class KillIconPage(QWidget):
    """击杀图标设置页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("KillIconPage")
        self.kill_icon_player = None  # 将在外部设置

        self.available_icon_styles = []
        self._loading = False  # 防止 load_settings 触发 _on_style_selected
        self._preview_level = DEFAULT_TEST_LEVEL
        self._preview_pending = False

        self._import_task = KillIconImportTask(self)
        self._import_task.progress.connect(self._on_import_progress)
        self._import_task.finished.connect(self._on_import_finished)
        self._import_task.failed.connect(self._on_import_failed)
        self._import_task.cancelled.connect(self._on_import_cancelled)

        self._scan_icon_styles()
        self._init_ui()
        self.load_settings()

        # 预加载当前风格的图标
        if self.kill_icon_player and config.kill_icon_style != "0":
            self.kill_icon_player.load_style(config.kill_icon_style)

        self.logger.info("击杀图标页面初始化完成")

    def set_kill_icon_player(self, player):
        """设置kill_icon_player引用"""
        previous = self.kill_icon_player
        if previous is not None and hasattr(previous, "assets_ready"):
            try:
                previous.assets_ready.disconnect(self._on_assets_ready)
            except (RuntimeError, TypeError):
                pass
        self.kill_icon_player = player

        # `load_style` 同步返回、异步装载：不连这一枪，切完风格页面会一直显示
        # **上一个风格**的帧数与时长，而且不会自己好。
        if player is not None and hasattr(player, "assets_ready"):
            player.assets_ready.connect(self._on_assets_ready)

        if player and config.kill_icon_style != "0":
            player.load_style(config.kill_icon_style)
            self.logger.info(f"预加载击杀图标风格: {config.kill_icon_style}")

        self._schedule_preview_refresh()
        self._sync_status_strip()

    # ------------------------------------------------------------------ 建页

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        header = PageHeader(
            "击杀图标设置",
            description="挑一套图标、放到顺眼的位置，就完事了。想自己做素材再去工坊。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        main_layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["kill_icon"])

        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(14, 12, 14, 12)
        status_card_layout.setSpacing(8)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_title = QLabel("当前状态")
        status_title.setObjectName("statusLabel")
        status_row.addWidget(status_title)
        self.status_badge_label = create_badge_label()
        status_row.addWidget(self.status_badge_label, 1)
        status_row.addStretch()
        status_card_layout.addLayout(status_row)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        status_card_layout.addWidget(self.summary_label)
        main_layout.addWidget(self.status_card)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(10)

        scroll_layout.addWidget(self._create_hero_card())
        scroll_layout.addWidget(self._create_style_card())
        scroll_layout.addWidget(self._create_workshop_card())
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        self.scroll_area = scroll
        main_layout.addWidget(scroll, 1)

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(124)
        self.action_bar.primary_btn.setMinimumWidth(140)
        main_layout.addWidget(self.action_bar, 0)

        # 拖一个动图、一个帧序列文件夹、或者一整个 zip 图标包进来就能导入
        enable_file_drop(self, DROP_EXTENSIONS, self._on_files_dropped,
                         accept_directories=True)

        self._sync_status_strip()

    # ------------------------------------------------------------------ 卡片

    def _create_hero_card(self):
        """当前用的这一套长什么样、在屏幕哪儿、开没开。"""
        card, card_layout = SettingsCard.make(
            "当前图标",
            "左边就是击杀时会看到的样子。位置不顺眼点「调整位置和大小」。",
        )

        self.style_summary_label = QLabel("")
        self.style_summary_label.setObjectName("hintLabel")
        self.style_summary_label.setWordWrap(True)
        card_layout.addWidget(self.style_summary_label)

        body = QHBoxLayout()
        body.setSpacing(12)

        self.hero_preview = KillIconPreview(box=(212, 136))
        # 最小宽放开到 0：跟着预缩放尺寸走的话，窄窗口下整页会横向溢出。
        # 撑住宽度的是 `KillIconPreview.sizeHint`（它报画布尺寸）——
        # 这一版第一次写的时候那个 sizeHint 还不存在（QWidget 默认报 -1），
        # 于是这块预览被布局收成 0 宽、**页面上凭空消失**，而布局本身完全
        # "正常"：不溢出、不报错、判据全绿，是渲染成图肉眼看才发现的。
        self.hero_preview.setMinimumWidth(0)
        self.hero_preview.setMinimumHeight(120)
        body.addWidget(self.hero_preview, 0, Qt.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(8)

        self.enabled_check = QCheckBox("开启击杀图标")
        self.enabled_check.setToolTip("关掉之后击杀不会出图标，这一页的其他设置照常保存")
        self.enabled_check.setChecked(bool(getattr(config, "kill_icon_enabled", False)))
        self.enabled_check.stateChanged.connect(self._on_enabled_changed)
        right.addWidget(self.enabled_check)

        self.fade_check = QCheckBox("入场淡入 / 收尾渐隐")
        self.fade_check.setToolTip(
            "渐隐挂在动画播完之后，定格最后一帧淡出，不会吃掉素材本身的收尾动作。"
        )
        self.fade_check.setChecked(bool(getattr(config, "kill_icon_fade_enabled", True)))
        self.fade_check.stateChanged.connect(self._on_fade_changed)
        right.addWidget(self.fade_check)

        self.headshot_check = QCheckBox("爆头用专属图标")
        self.headshot_check.setToolTip(
            "需要先在素材工坊里给某个等级导入爆头素材；没导过就一直用普通图标。"
        )
        self.headshot_check.setChecked(bool(getattr(config, "kill_icon_headshot_enabled", True)))
        self.headshot_check.stateChanged.connect(self._on_headshot_changed)
        right.addWidget(self.headshot_check)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.test_btn = QPushButton("▶ 在屏幕上试播")
        self.test_btn.setObjectName("actionButton")
        self.test_btn.setFixedHeight(34)
        # 写下限不写死宽：中文文案 + 字号缩放 = 截断（UP-094 的教训）。
        self.test_btn.setMinimumWidth(140)
        self.test_btn.setToolTip("按当前设置在屏幕上真播一次，位置和大小所见即所得")
        self.test_btn.clicked.connect(self._test_current)
        button_row.addWidget(self.test_btn)

        self.adjust_toggle_btn = QPushButton("调整位置和大小 ⌄")
        self.adjust_toggle_btn.setObjectName("secondaryButton")
        self.adjust_toggle_btn.setFixedHeight(34)
        self.adjust_toggle_btn.setMinimumWidth(150)
        self.adjust_toggle_btn.setCheckable(True)
        self.adjust_toggle_btn.toggled.connect(self._on_adjust_toggled)
        button_row.addWidget(self.adjust_toggle_btn)
        button_row.addStretch()
        right.addLayout(button_row)
        right.addStretch()

        body.addLayout(right, 1)
        card_layout.addLayout(body)

        self.adjust_frame = self._create_adjust_frame()
        self.adjust_frame.hide()
        card_layout.addWidget(self.adjust_frame)

        return card

    def _create_adjust_frame(self):
        """位置/大小三滑条 + 示意图。默认折叠——绝大多数人一次都不会动它。"""
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)

        self.adjust_summary_label = QLabel("")
        self.adjust_summary_label.setObjectName("hintLabel")
        self.adjust_summary_label.setWordWrap(True)
        layout.addWidget(self.adjust_summary_label)

        body = QHBoxLayout()
        body.setSpacing(12)

        sliders = QVBoxLayout()
        sliders.setSpacing(6)

        self.x_slider, self.x_value_label = self._make_slider_row(
            sliders, "水平位置:", -200, 200, int(getattr(config, "kill_icon_offset_x", 0)),
            self._on_x_position_changed, f"{getattr(config, 'kill_icon_offset_x', 0)} px")
        self.y_slider, self.y_value_label = self._make_slider_row(
            sliders, "垂直位置:", -200, 200, int(getattr(config, "kill_icon_offset_y", 0)),
            self._on_y_position_changed, f"{getattr(config, 'kill_icon_offset_y', 0)} px")
        self.scale_slider, self.scale_value_label = self._make_slider_row(
            sliders, "图标大小:", 50, 200, int(getattr(config, "kill_icon_scale", 1.0) * 100),
            self._on_scale_changed, format_percent(getattr(config, "kill_icon_scale", 1.0), hi=2.0))

        reset_btn = QPushButton("重置位置和大小")
        reset_btn.setObjectName("secondaryButton")
        reset_btn.setFixedHeight(32)
        # UP-094: 写死宽度 + 中文文案 + 字号缩放 = 截断。只写下限。
        reset_btn.setMinimumWidth(146)
        reset_btn.clicked.connect(self._reset_position_and_scale)
        reset_row = QHBoxLayout()
        reset_row.setContentsMargins(0, 4, 0, 0)
        reset_row.addWidget(reset_btn)
        reset_row.addStretch()
        sliders.addLayout(reset_row)

        body.addLayout(sliders, 1)

        self.position_map = KillIconPositionMap()
        self.position_map.setMinimumWidth(180)
        self.position_map.position_changed.connect(self._on_map_dragged)
        body.addWidget(self.position_map, 0)

        layout.addLayout(body)
        self._sync_position_map()
        return frame

    def _make_slider_row(self, parent_layout, title, minimum, maximum, value,
                         handler, value_text):
        row = QFrame()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        label = QLabel(title)
        label.setFixedWidth(80)
        row_layout.addWidget(label)

        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(minimum)
        slider.setMaximum(maximum)
        slider.setValue(value)
        slider.valueChanged.connect(handler)
        row_layout.addWidget(slider)

        value_label = QLabel(value_text)
        value_label.setFixedWidth(60)
        row_layout.addWidget(value_label)

        parent_layout.addWidget(row)
        return slider, value_label

    def _create_style_card(self):
        card, card_layout = SettingsCard.make(
            "风格库",
            "点一张卡就换。一个 zip 图标包就是一整套风格，拖进来即可。",
        )

        self.style_strip = KillIconStyleStrip()
        self.style_strip.style_selected.connect(self._on_style_selected)
        self.style_strip.import_requested.connect(self._choose_file_to_import)

        # 卡片是固定宽的，风格多了要能横着滚，不能把整页撑宽
        strip_scroll = QScrollArea()
        strip_scroll.setWidgetResizable(True)
        strip_scroll.setFrameShape(QFrame.NoFrame)
        strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 滚动区默认自己画一层底色，卡片右边会多出一大块深色矩形，看着像
        # "这里还应该有东西"。透明掉，让卡片直接落在卡片底色上。
        # ⚠ 这条 QSS 里**不许出现颜色**：`background: transparent` 是"别画"，
        # 不是"画成某个色"——本项目 QSS 正文的 #RRGGBB 字面量数为 0，
        # 8 个主题全靠 token，写死一个颜色就有 7 个主题会错。
        strip_scroll.viewport().setAutoFillBackground(False)
        strip_scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget "
                                   "{ background: transparent; }")
        self.style_strip.setAutoFillBackground(False)
        strip_scroll.setWidget(self.style_strip)
        strip_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.style_scroll = strip_scroll
        self._sync_strip_height()
        card_layout.addWidget(strip_scroll)

        drop_hint = QLabel(
            "把图标包(.zip)、动图或图片拖到这一页上就能导入；"
            "推荐 WebP 动图 / APNG / PNG 帧序列——边缘干净，GIF 的透明是 1-bit 的，会有硬白边。"
        )
        drop_hint.setObjectName("hintLabel")
        drop_hint.setWordWrap(True)
        card_layout.addWidget(drop_hint)

        # ---- 页内提示条（取代弹窗）
        self.notice_frame = QFrame()
        self.notice_frame.setObjectName("card")
        notice_layout = QHBoxLayout(self.notice_frame)
        notice_layout.setContentsMargins(10, 6, 10, 6)
        notice_layout.setSpacing(8)
        self.notice_label = QLabel("")
        self.notice_label.setObjectName("hintLabel")
        self.notice_label.setWordWrap(True)
        notice_layout.addWidget(self.notice_label, 1)
        self.undo_btn = QPushButton("撤销")
        self.undo_btn.setObjectName("secondaryButton")
        self.undo_btn.setFixedHeight(26)
        self.undo_btn.clicked.connect(self._undo_last_delete)
        self.undo_btn.hide()
        notice_layout.addWidget(self.undo_btn)
        dismiss_btn = QPushButton("知道了")
        dismiss_btn.setObjectName("secondaryButton")
        dismiss_btn.setFixedHeight(26)
        dismiss_btn.clicked.connect(self._clear_notice)
        notice_layout.addWidget(dismiss_btn)
        self.notice_frame.hide()
        card_layout.addWidget(self.notice_frame)

        # ---- 进度条（导入跑在后台线程上）
        self.progress_frame = QFrame()
        progress_layout = QHBoxLayout(self.progress_frame)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(8)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("hintLabel")
        progress_layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(14)
        progress_layout.addWidget(self.progress_bar, 1)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("secondaryButton")
        self.cancel_btn.setFixedHeight(26)
        self.cancel_btn.clicked.connect(self._import_task.cancel)
        progress_layout.addWidget(self.cancel_btn)
        self.progress_frame.hide()
        card_layout.addWidget(self.progress_frame)

        return card

    def _sync_strip_height(self, _deferred=False):
        """卡片条的高度要跟着**真实卡片**走。

        建页那一刻条上只有「＋ 导入」那一张，风格卡是 `load_settings` 之后才
        塞进去的。在建页时把高度写死，就会把真卡片的最后一行（「素材齐全」/
        「2/5 个等级」）裁掉——而那一行恰恰是"切换之前就知道缺不缺素材"的
        全部信息，裁掉了整条设计就白做了。

        ⚠ **光在 `set_styles()` 之后调一次是不够的**（实测：视口 124px、内容 127px，
        「＋导入」卡最后一行「zip / 动图 / 图片」被切掉 3px）。两个原因：

          1. 调用那一刻 QSS 还没抛光完，`sizeHint()` 比最终值小——等抛光后卡片
             长高，而高度已经写死了；
          2. 卡片一多就冒出**横向**滚动条，它自己要吃掉十几个像素的**纵向**空间，
             没算进去就又矮一截。

        而这个滚动区是 `ScrollBarAlwaysOff`（纵向），**裁掉的部分滚都滚不出来**，
        所以宁可高一点也不能矮。故：取 sizeHint 与 minimumSizeHint 的较大者、
        显式加上横向滚动条的高度，并在事件循环空转一轮后**再校一次**。
        """
        if not hasattr(self, "style_scroll"):
            return
        strip = self.style_strip
        need = max(strip.sizeHint().height(), strip.minimumSizeHint().height())
        bar = self.style_scroll.horizontalScrollBar()
        if (bar is not None
                and self.style_scroll.horizontalScrollBarPolicy() != Qt.ScrollBarAlwaysOff):
            need += bar.sizeHint().height()
        self.style_scroll.setFixedHeight(need + 6)
        if not _deferred:
            QTimer.singleShot(0, self._resync_strip_height)

    def _resync_strip_height(self):
        """布局抛光后的二次校准。单独开一个方法而不是塞 lambda：
        控件可能已经被销毁，这里要能安全地什么都不做。"""
        try:
            if hasattr(self, "style_scroll") and self.style_scroll is not None:
                self._sync_strip_height(_deferred=True)
        except RuntimeError:
            pass        # 控件已析构，正常情况

    def _create_workshop_card(self):
        card, card_layout = SettingsCard.make(
            "自己做一套",
            "逐个等级换素材、调节奏、抠背景、导出分享——这些都在工坊里，"
            "平时不用管它。",
        )

        row = QHBoxLayout()
        row.setSpacing(8)
        self.workshop_btn = QPushButton("打开素材工坊")
        self.workshop_btn.setObjectName("secondaryButton")
        self.workshop_btn.setFixedHeight(34)
        self.workshop_btn.setMinimumWidth(140)
        self.workshop_btn.clicked.connect(self._open_workshop)
        row.addWidget(self.workshop_btn)
        row.addStretch()
        card_layout.addLayout(row)
        return card

    # ------------------------------------------------------------------ 摘要

    def _compact_text(self, text, fallback="未设置", max_length=14):
        value = str(text or "").strip() or fallback
        if len(value) > max_length:
            return value[: max_length - 1] + "…"
        return value

    def _current_style(self):
        style = getattr(self, "_selected_style", None)
        return style or getattr(config, "kill_icon_style", "")

    def _ready_levels(self, style=None):
        """这套风格有几个等级有素材。**读磁盘**，不读播放器缓存。

        播放器只装着"当前风格"一套，而风格卡片上要给每一套都标齐全度。
        """
        style = style or self._current_style()
        if not style:
            return []
        try:
            return list(style_summary(style).get("levels") or [])
        except Exception:
            return []

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        style_text = self._current_style()
        self.action_bar.configure_secondary("打开素材工坊", self._open_workshop, visible=True)
        self.action_bar.configure_primary("在屏幕上试播", self._test_current, visible=True)
        self.action_bar.set_message(
            f"当前风格：{self._compact_text(style_text, '未设置', 16)}"
            f" · 素材 {len(self._ready_levels())}/{len(LEVELS)}"
            f" · 位置 {getattr(config, 'kill_icon_offset_x', 0)}/{getattr(config, 'kill_icon_offset_y', 0)}"
            f" · 大小 {format_percent(getattr(config, 'kill_icon_scale', 1.0), hi=2.0)}。"
        )

    def _sync_status_strip(self):
        """状态条只留四条：开没开 · 用哪套 · 素材齐不齐 · 放在哪儿。

        KI-6 那版有七条，把「时长 · 1.5-5.0s」「预览 · 已连接」这类**只有做
        素材的人才关心**的数也摆在了首屏。它们现在要么进了工坊，要么退到
        下面这段详情文案里（鼠标停在状态条上能看到）。
        """
        style_text = self._compact_text(self._current_style(), "未设置")
        position_text = f"{getattr(config, 'kill_icon_offset_x', 0)}/{getattr(config, 'kill_icon_offset_y', 0)}"
        scale_text = format_percent(getattr(config, "kill_icon_scale", 1.0), hi=2.0)
        player_ready = self.kill_icon_player is not None
        enabled = bool(getattr(config, "kill_icon_enabled", False))
        ready_levels = self._ready_levels()

        badges = [
            ("positive" if enabled else "warning", f"总开关 · {'已开启' if enabled else '未开启'}"),
            (
                "positive" if self._current_style() not in ("", "0") else "warning",
                f"风格 · {style_text}",
            ),
            ("positive" if len(ready_levels) == len(LEVELS) else "warning",
             f"素材 · {len(ready_levels)}/{len(LEVELS)}"),
            ("info", f"位置 · {position_text} · {scale_text}"),
        ]

        missing = [k for k in LEVELS if k not in ready_levels]
        detail_text = (
            f"总开关：{'已开启' if enabled else '未开启（开启后击杀才会出图标）'}\n"
            f"当前风格：{self._current_style() or '未设置'}\n"
            f"可用风格：{len(self.available_icon_styles)} 项\n"
            f"已备素材：{len(ready_levels)}/{len(LEVELS)} 个等级"
            f"{'（缺 ' + '、'.join(f'{k} 杀' for k in missing) + '）' if missing else ''}\n"
            f"位置偏移：X {getattr(config, 'kill_icon_offset_x', 0)} / Y {getattr(config, 'kill_icon_offset_y', 0)}\n"
            f"图标缩放：{scale_text}\n"
            f"预览组件：{'已连接' if player_ready else '未连接'}"
        )
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.summary_label.setText(detail_text)
        self.summary_label.setToolTip(detail_text)
        self.status_card.setToolTip(detail_text)

        if hasattr(self, "style_summary_label"):
            self.style_summary_label.setText(
                f"当前风格：{self._current_style() or '未设置'}"
                f" · 素材 {len(ready_levels)}/{len(LEVELS)} 个等级"
                f" · 共 {len(self.available_icon_styles)} 套可选"
            )
            self.style_summary_label.setToolTip(detail_text)

        if hasattr(self, "adjust_summary_label"):
            self.adjust_summary_label.setText(
                f"当前位置：X {getattr(config, 'kill_icon_offset_x', 0)}"
                f" / Y {getattr(config, 'kill_icon_offset_y', 0)} · 缩放 {scale_text}"
            )
            self.adjust_summary_label.setToolTip(detail_text)

        if hasattr(self, "test_btn"):
            # 播放器没接上时试播是个空动作，灰掉比点了没反应强
            self.test_btn.setEnabled(player_ready)
            self.test_btn.setToolTip(
                "按当前设置在屏幕上真播一次，位置和大小所见即所得"
                if player_ready else "图标播放器还没就绪"
            )

        if hasattr(self, "style_strip"):
            for name in self.available_icon_styles:
                self.style_strip.set_level_count(
                    name, len(self._ready_levels(name)), len(LEVELS))
        self._sync_action_bar()

    # ------------------------------------------------------------------ 设置

    def _scan_icon_styles(self):
        """扫描可用的图标风格"""
        self.available_icon_styles = ResourceManager.list_kill_icon_styles()
        if not self.available_icon_styles:
            self.logger.warning("未扫描到任何击杀图标风格")
        self.logger.info(f"扫描到的击杀图标风格: {self.available_icon_styles}")

    def load_settings(self):
        """加载设置"""
        self._loading = True
        try:
            current = getattr(config, "kill_icon_style", "")
            if current not in self.available_icon_styles:
                current = self.available_icon_styles[0] if self.available_icon_styles else ""
            self._selected_style = current
            self.style_strip.set_styles(self.available_icon_styles, current)
            self._sync_strip_height()

            if hasattr(self, "enabled_check"):
                self.enabled_check.setChecked(bool(getattr(config, "kill_icon_enabled", False)))

            self.logger.debug("加载击杀图标设置完成")
        finally:
            self._loading = False
            self._schedule_preview_refresh()
            self._sync_status_strip()

    def _on_assets_ready(self, style_name):
        """后台把新风格的素材装完了——把大预览刷成新风格的。"""
        if style_name != self._current_style():
            return          # 用户在装载期间又换了一次，这一枪已经过期
        self._schedule_preview_refresh()
        self._sync_status_strip()

    # ------------------------------------------------------------ 预览

    def _schedule_preview_refresh(self):
        """把预览素材的装载挪到建页之后。

        装载要解码整套帧：默认风格 46 帧实测 41ms，占建页耗时的一半，
        而上限允许到 600 帧。同步做的话表现是"点开这一页要顿一下"，
        且顿的时间由用户素材大小决定——最不该由用户素材决定的就是建页速度。
        合并连续请求（改风格时会连着触发好几次）。
        """
        if self._preview_pending:
            return
        self._preview_pending = True
        QTimer.singleShot(0, self._run_scheduled_preview_refresh)

    def _run_scheduled_preview_refresh(self):
        self._preview_pending = False
        try:
            self._refresh_preview()
        except Exception as exc:  # 预览挂了不该把整页拖下水
            self.logger.error(f"刷新击杀图标预览失败: {exc}")

    def _refresh_preview(self):
        """大预览播当前风格里"最能代表它"的那一个等级。"""
        style = self._current_style()
        level = self._best_level(style)
        self._preview_level = level
        animation = None
        if style:
            try:
                animation = load_level_animation(style, level)
            except Exception as exc:
                self.logger.error(f"预览素材装载失败: {exc}")
        if hasattr(self, "hero_preview"):
            self.hero_preview.set_animation(
                animation,
                "这套风格还没有素材，拖一个图标包进来" if style else "先导入一套风格",
            )
        if animation is not None and hasattr(self, "position_map"):
            self.position_map.set_target(
                getattr(config, "kill_icon_offset_x", 0),
                getattr(config, "kill_icon_offset_y", 0),
                getattr(config, "kill_icon_scale", 1.0),
                (animation.frame_width, animation.frame_height),
            )

    def _best_level(self, style=None):
        """挑一个有素材的等级来预览/试播。5 杀优先，往下找。"""
        ready = self._ready_levels(style)
        for kills in (DEFAULT_TEST_LEVEL, 4, 3, 2, 1):
            if kills in ready:
                return kills
        return DEFAULT_TEST_LEVEL

    @property
    def preview_widget(self):
        """老接口：页面上那块动画预览。"""
        return getattr(self, "hero_preview", None)

    def _sync_position_map(self):
        if hasattr(self, "position_map"):
            self.position_map.set_target(
                getattr(config, "kill_icon_offset_x", 0),
                getattr(config, "kill_icon_offset_y", 0),
                getattr(config, "kill_icon_scale", 1.0),
            )

    # ------------------------------------------------------------ 提示条

    def _show_notice(self, message, undo_token=None):
        """页内提示条取代弹窗。

        导入一次要点两三个模态框是这一页最伤"亲民"的地方；提示条还能挂一个
        「撤销」——弹窗关掉就没了。
        """
        self._undo_token = undo_token
        self.notice_label.setText(message)
        self.notice_frame.show()
        self.undo_btn.setVisible(bool(undo_token))

    def _clear_notice(self):
        self._undo_token = None
        self.notice_frame.hide()
        self.undo_btn.hide()

    def _undo_last_delete(self):
        from core.kill_icon_library import restore_level

        token = getattr(self, "_undo_token", None)
        if not token:
            return
        if restore_level(token):
            self._clear_notice()
            self._reload_after_import()
            self._show_notice("已撤销，素材放回去了。")
        else:
            self._show_notice("撤销失败：这一格已经被新的素材占了。")

    # ------------------------------------------------------------ 后台导入

    def _run_import(self, fn, label):
        if self._import_task.running:
            self._show_notice("上一次导入还没跑完，等一下再来。")
            return False
        self._clear_notice()
        self.progress_label.setText(label)
        self.progress_bar.setRange(0, 0)
        self.progress_frame.show()
        return self._import_task.start(fn, label)

    def _on_import_progress(self, done, total, stage):
        self.progress_label.setText(stage)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(done)

    def _on_import_finished(self, result):
        self.progress_frame.hide()
        self._reload_after_import(
            result.get("style") if isinstance(result, dict) else None)
        self._show_notice(self._describe_result(result))

    def _on_import_failed(self, message):
        self.progress_frame.hide()
        self._show_notice(f"导入失败：{message}")

    def _on_import_cancelled(self):
        self.progress_frame.hide()
        self._show_notice("已取消，什么都没改。")

    def _describe_result(self, result):
        if not isinstance(result, dict):
            return "导入完成。"

        if "imported" in result:      # 图标包
            levels = "、".join(f"{k}{'（爆头）' if v else ''} 杀"
                              for k, v in result.get("levels", []))
            lines = [f"已装入风格「{result.get('style')}」：{levels or '（空）'}"]
            if result.get("author"):
                lines.append(f"作者：{result['author']}")
            if result.get("failed"):
                lines.append("跳过：" + "；".join(result["failed"][:3]))
            warnings = result.get("warnings") or []
            lines.extend(f"⚠ {w}" for w in warnings[:3])
            return "\n".join(lines)

        hold = result.get("hold_seconds") or 0.0
        timing = (f"定格 {hold:.1f} 秒" if result.get("frames") == 1 and hold
                  else f"{result.get('frames')} 帧 @ {result.get('fps')} FPS")
        lines = [
            f"已导入到「{result.get('style')}」的 {result.get('kills')} 杀"
            f"{'（爆头专用）' if result.get('variant') else ''}：{timing}"
        ]
        lines.extend(f"⚠ {w}" for w in (result.get("warnings") or [])[:3])
        return "\n".join(lines)

    # ------------------------------------------------------------ 导入入口

    def _import_paths(self, paths):
        """统一入口：zip 直接装整套，单个素材问一句「用在几杀」。

        KI-7 之前这里是"进当前关注的那一格"——而简单层根本没有"当前关注的
        等级"这个概念，猜错了用户还得自己去别处翻。**问一句比猜错强**，
        何况文件名认得出来时那一句也不用问（下拉已经预选好）。
        """
        from core.kill_icon_pack import import_pack

        packs = [p for p in paths if str(p).lower().endswith(".zip")]
        if packs:
            def _work(progress, cancel):
                return import_pack(packs[0], progress=progress, cancel=cancel)

            self._run_import(_work, "正在装入图标包…")
            return True

        assets = [p for p in paths if p not in packs]
        if not assets:
            self._show_notice("没有可导入的文件。")
            return False

        target = self._ask_target(assets[0])
        if target is None:
            return False
        return self._import_assets(assets, target[0], target[1])

    def _ask_target(self, path):
        """开导入小窗问「用在几杀」。取消返回 None，探测失败翻成提示条。"""
        from dialogs.kill_icon_import_wizard import (
            KillIconImportError, wizard_target_for
        )

        try:
            return wizard_target_for(path, parent=self)
        except KillIconImportError as exc:
            self._show_notice(str(exc))
            return None

    def _import_assets(self, paths, kills, variant=""):
        from core.kill_icon_import import convert_to_style

        style = self._current_style() or "默认"

        def _work(progress, cancel):
            result = None
            for path in paths:
                result = convert_to_style(path, style, kills, variant=variant,
                                          progress=progress, cancel=cancel)
            return result

        return self._run_import(_work, f"正在导入 {kills} 杀素材…")

    def _on_files_dropped(self, paths):
        self._import_paths(paths)

    def _choose_file_to_import(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, "选择图标包或素材", "",
            "图标包与素材 (*.zip *.gif *.webp *.png *.apng *.avif *.jpg *.jpeg *.bmp);;"
            "图标包 (*.zip);;所有文件 (*.*)")
        if path:
            self._import_paths([path])

    def _reload_after_import(self, style=None):
        """导入之后把风格库、播放器、预览一起刷新。"""
        self._scan_icon_styles()
        self._loading = True
        try:
            current = style or self._current_style()
            if current not in self.available_icon_styles:
                current = self.available_icon_styles[0] if self.available_icon_styles else ""
            self._selected_style = current
            self.style_strip.set_styles(self.available_icon_styles, current)
            self._sync_strip_height()
        finally:
            self._loading = False

        if self._selected_style:
            config.kill_icon_style = self._selected_style
            config.save_config()
            if self.kill_icon_player:
                self.kill_icon_player.load_style(self._selected_style)
        self._refresh_preview()
        self._sync_status_strip()

    def _open_workshop(self):
        """打开素材工坊（逐等级换素材、调节奏、抠背景、导出）。"""
        # try 只包"把窗建出来"这一段。关窗之后的收尾也裹进去的话，收尾里
        # 任何一个小错都会被报成「无法打开素材工坊」——而窗其实开得好好的，
        # 用户在里面改了半天，回来看到一句打不开。
        try:
            from dialogs.kill_icon_workshop import KillIconWorkshop

            workshop = KillIconWorkshop(self._current_style(),
                                        player=self.kill_icon_player, parent=self)
        except Exception as exc:
            self._show_notice("无法打开素材工坊，请稍后重试。")
            self.logger.error(f"打开素材工坊失败: {exc}")
            return

        workshop.exec()
        # 工坊里能换风格，换了就一路生效到播放器。这里必须拿**它**最后停在
        # 哪一套，拿页面自己的 `_current_style()` 会把选中卡片和真正装载着的
        # 风格拆成两套。
        style = workshop.style_name
        if workshop.changed or style != self._current_style():
            self._reload_after_import(style)
        else:
            self._sync_status_strip()

    # ------------------------------------------------------------------ 事件

    def _on_map_dragged(self, offset_x, offset_y):
        """在示意图上拖蓝框 == 拖那两条滑条。

        刻意**只走滑条这一条路**：直接写 config 的话，位置就有了两个真源，
        拖完滑条还停在老位置，下一次动滑条又把拖的结果覆盖掉。
        """
        self.x_slider.setValue(int(offset_x))
        self.y_slider.setValue(int(offset_y))

    def _on_adjust_toggled(self, checked):
        self.adjust_frame.setVisible(bool(checked))
        self.adjust_toggle_btn.setText(
            "调整位置和大小 ⌃" if checked else "调整位置和大小 ⌄")

    def _on_enabled_changed(self, _state=None):
        if self._loading:
            return
        config.kill_icon_enabled = bool(self.enabled_check.isChecked())
        config.save_config()
        if self.kill_icon_player:
            if config.kill_icon_enabled:
                self.kill_icon_player.enable_kill_icons()
            else:
                self.kill_icon_player.disable_kill_icons()
        self._sync_status_strip()

    def _on_fade_changed(self, _state=None):
        if self._loading:
            return
        config.kill_icon_fade_enabled = bool(self.fade_check.isChecked())
        config.save_config()

    def _on_headshot_changed(self, _state=None):
        if self._loading:
            return
        config.kill_icon_headshot_enabled = bool(self.headshot_check.isChecked())
        config.save_config()

    def _on_style_selected(self, style_name):
        """点了某一张风格卡。"""
        if self._loading:
            return
        style = str(style_name or "")
        if not style or style == self._current_style():
            return

        self._selected_style = style
        self.style_strip.set_selected(style)
        config.kill_icon_style = style
        config.save_config()
        self.logger.info(f"击杀图标风格更新: {style}")

        if self.kill_icon_player:
            self.kill_icon_player.load_style(style)
        self._schedule_preview_refresh()
        self._sync_status_strip()

    def _on_x_position_changed(self, value):
        config.kill_icon_offset_x = value
        config.save_config()
        self.x_value_label.setText(f"{value} px")
        if self.kill_icon_player:
            self.kill_icon_player.update_position_offset(
                config.kill_icon_offset_x, config.kill_icon_offset_y)
        self._sync_position_map()
        self._sync_status_strip()

    def _on_y_position_changed(self, value):
        config.kill_icon_offset_y = value
        config.save_config()
        self.y_value_label.setText(f"{value} px")
        if self.kill_icon_player:
            self.kill_icon_player.update_position_offset(
                config.kill_icon_offset_x, config.kill_icon_offset_y)
        self._sync_position_map()
        self._sync_status_strip()

    def _on_scale_changed(self, value):
        scale = value / 100.0
        config.kill_icon_scale = scale
        config.save_config()
        self.scale_value_label.setText(f"{value}%")
        if self.kill_icon_player:
            self.kill_icon_player.update_scale(scale)
        self._sync_position_map()
        self._sync_status_strip()

    def _reset_position_and_scale(self):
        config.kill_icon_offset_x = 0
        config.kill_icon_offset_y = 0
        config.kill_icon_scale = 1.0
        config.save_config()

        self.x_slider.setValue(0)
        self.y_slider.setValue(0)
        self.scale_slider.setValue(100)
        self.x_value_label.setText("0 px")
        self.y_value_label.setText("0 px")
        self.scale_value_label.setText("100%")

        if self.kill_icon_player:
            self.kill_icon_player.update_position_offset(0, 0)
            self.kill_icon_player.update_scale(1.0)
        self._sync_position_map()
        self._sync_status_strip()
        self.logger.info("重置位置和大小")

    def _test_current(self):
        """在屏幕上真播一次。

        有素材就按真实节奏播那一套；一帧都没有的话退回落点示意——总得让用户
        看见"图标会出现在哪儿"，否则点了跟没点一样，比灰掉还费解。
        """
        if not self.kill_icon_player:
            self._show_notice("图标播放器未初始化。")
            return
        level = self._best_level()
        self._preview_level = level
        if level in self._ready_levels():
            self.kill_icon_player.play_icon(level)
            self.logger.info(f"试播 {level} 杀图标")
        else:
            self.kill_icon_player.preview_position_and_scale(level, 3)
            self.logger.info("当前风格没有素材，改为预览落点")

