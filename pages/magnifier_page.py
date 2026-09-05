# SPDX-License-Identifier: GPL-3.0-or-later
"""
开镜放大页面 - PySide6 Widget实现
"""
import json
import time
import threading
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                                QComboBox, QSlider, QLineEdit, QCheckBox, QFrame,
                                QScrollArea, QGridLayout, QTabWidget, QSizePolicy)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIntValidator, QDoubleValidator
from config import config
from cfg_utils import setup_autoexec
from core.cfg_compiler import write_cs2customizer_cfg
from core.magnifier_sensitivity import (
    DEFAULT_SYNC_TRIGGER_KEY,
    compute_zoom_sensitivity,
    format_sensitivity_value,
    get_keyboard_key_for_sync,
    get_magnifier_runtime_cfg_path,
    write_magnifier_runtime_cfg,
)
from core.utils.logger import get_logger
from core.utils.format_utils import format_percent
from ctypes import windll, c_float, c_int, create_unicode_buffer
from pages.audio_status_badge import create_badge_label, render_badges
from theme_manager import get_color, get_theme_manager
from ctypes.wintypes import BOOL
from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
from ui_style_applier import keep_inline_style
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard

# 加载必要的DLL
user32 = windll.user32
kernel32 = windll.kernel32

# 尝试加载Magnification API
try:
    magnification = windll.Magnification
    if not hasattr(magnification, 'MagInitialize'):
        magnification_available = False
    else:
        magnification_available = True
        
        # 定义函数原型
        MagInitialize = magnification.MagInitialize
        MagInitialize.restype = BOOL
        
        MagUninitialize = magnification.MagUninitialize
        MagUninitialize.restype = BOOL
        
        MagSetFullscreenTransform = magnification.MagSetFullscreenTransform
        MagSetFullscreenTransform.argtypes = [c_float, c_int, c_int]
        MagSetFullscreenTransform.restype = BOOL
        
        MagShowSystemCursor = magnification.MagShowSystemCursor
        MagShowSystemCursor.argtypes = [BOOL]
        MagShowSystemCursor.restype = BOOL
except Exception:
    magnification_available = False


class _StatusTrackingLabel(QLabel):
    """Hidden label that refreshes the overview card when text changes."""
    def __init__(self, text="", parent=None, on_change=None):
        super().__init__(text, parent)
        self._on_change = on_change

    def setText(self, text):
        super().setText(text)
        if self._on_change is None:
            return
        try:
            self._on_change()
        except Exception:
            pass


class MagnifierPage(QWidget):
    """开镜放大页面"""
    #: RN-175 / 批 24：**这一页不是自动保存的。** 倍率与偏移要点一下「应用」才写下去。
    #: ⚠ 底栏那条共用回执默认说「改动已自动保存，不用点任何按钮」——
    #:   而这一页同一行右边就摆着那颗必须点的按钮。实测 15 页里 2 页如此。
    #: ⭐ 共用件省的是重复，不是判断。
    SAVES_AUTOMATICALLY = False


    # P2.1: 热键注册中心里的功能域标识
    HOTKEY_OWNER = "开镜放大"

    # 定义信号 - 用于在主线程中执行放大操作
    activate_magnification_signal = Signal(str)  # 激活类型作参数传递，避免共享成员被快速连按覆盖
    deactivate_magnification_signal = Signal()
    # 武器更新信号 - GSI线程调用 update_current_weapon 时经此编组到主线程再碰UI
    weapon_update_signal = Signal(str)
    
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config = config_manager
        self.logger = get_logger()
        
        # 连接信号到槽函数（槽函数会在主线程中执行）
        self.activate_magnification_signal.connect(self._do_activate_magnification)
        self.deactivate_magnification_signal.connect(self._do_deactivate_magnification)
        self.weapon_update_signal.connect(self._do_update_current_weapon)
        
        # 初始化Magnification API（普通权限即可；失败时可在启用环节重试/引导提权）
        self._mag_dll_available = magnification_available
        self.magnification_available = False
        if self._mag_dll_available:
            self._attempt_mag_init()
        else:
            self.logger.error("Magnification API 不可用（DLL加载失败）")
        
        # 初始化变量
        self.zoom_factor = 2.0
        self.is_magnifier_active = False
        self.current_weapon = ""
        self.current_active_type = None  # 'primary' 或 'secondary'
        self.pending_activation_type = None  # 用于跨线程传递激活类型
        
        # 热键状态
        self.primary_key_pressed = False
        self.secondary_key_pressed = False
        
        # 防抖设置
        self.debounce_time = 150
        self.primary_key_press_time = 0
        self.primary_debouncing = False
        self.secondary_key_press_time = 0
        self.secondary_debouncing = False
        self.trigger_mode = "长按触发"
        
        # 屏幕尺寸
        self.screen_width = user32.GetSystemMetrics(0)
        self.screen_height = user32.GetSystemMetrics(1)
        self.screen_center_x = self.screen_width // 2
        self.screen_center_y = self.screen_height // 2
        
        # 放大倍率设置
        self.zoom_settings = {}
        self._last_sensitivity_cfg_signature = None
        self._sensitivity_runtime_applied = False
        
        # 准心组件引用
        self.crosshair_component = None
        self.original_crosshair_saved = False  # 标记是否已保存原始准心设置
        self.original_crosshair_size = 20
        self.original_crosshair_thickness = 2
        self.original_crosshair_color = 'green'
        # UP-089：原来写的是 'cross'，不是合法样式名（合法值见 crosshair_overlay.USER_STYLES）。
        # 目前够不着——真正的取值由 _set_magnifier_crosshair 从组件上读，且恢复路径有
        # original_crosshair_saved 兜着。但一旦哪天读不到，这个错值会被原样喂给渲染器，
        # 结果是准心「恢复」成一片空白且不报错。
        self.original_crosshair_style = 'crosshair'
        self.original_crosshair_animation = 'none'
        self.original_crosshair_kill_effect = 'none'
        self.original_crosshair_visible = True
        
        # 武器启用状态
        self.weapon_enabled_vars = {}
        
        # 键盘监听
        self.keyboard_thread = None
        self.keyboard_running = False
        self._mouse_hooks = []
        
        # 箭头按钮列表（用于主题刷新）
        self._arrow_buttons = []
        # 武器分类和名称映射
        self._init_weapon_data()
        
        # 创建UI
        self._init_ui()
        
        # 注册主题变更回调
        get_theme_manager().register_theme_changed_callback(self._apply_theme_styles)
        # 加载设置
        self.load_settings()
        
        # 检查全局启用状态（页面构造期不弹提权引导，避免启动时打扰）
        if not self.config.magnifier_enabled:
            self.disable_magnifier()
        else:
            self.enable_magnifier(interactive=False)
        
        self.logger.info("开镜放大页面初始化完成")
    
    @staticmethod
    def _compact_text(text, fallback="未设置", max_length=10):
        value = str(text or "").strip() or fallback
        if len(value) > max_length:
            return value[: max_length - 1] + "…"
        return value

    def _current_tab_text(self):
        if not hasattr(self, "weapon_tabview") or self.weapon_tabview.count() == 0:
            return "未分组"
        index = self.weapon_tabview.currentIndex()
        if index < 0:
            index = 0
        return self.weapon_tabview.tabText(index) or "未分组"

    def _enabled_weapon_count(self):
        return sum(1 for checkbox in self.weapon_enabled_vars.values() if checkbox.isChecked())

    def _current_offset_text(self):
        zoom_key = str(self.zoom_factor)
        zoom_settings = self.zoom_settings.get(zoom_key, {}) if isinstance(self.zoom_settings, dict) else {}
        x_offset = zoom_settings.get("x_offset", 0)
        y_offset = zoom_settings.get("y_offset", 0)
        return f"X={x_offset}, Y={y_offset}"

    def _current_runtime_text(self):
        if not self.magnification_available:
            return "不可用", "danger"
        if not self.config.magnifier_enabled:
            return "已禁用", "warn"
        if self.is_magnifier_active:
            if self.current_active_type == "primary":
                return "主武器激活", "success"
            if self.current_active_type == "secondary":
                return "手枪激活", "success"
            return "放大中", "success"
        if self.keyboard_running:
            return "监听中", "info"
        return "待命", "info"

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        enabled_weapon_count = self._enabled_weapon_count()
        total_weapon_count = len(self.weapon_enabled_vars)

        # ⭐⭐ RN-277（批 28）：底栏主按钮位原来放的是「全选武器 / 全不选武器」。
        # 54 把武器 `setChecked(True)  # 默认启用` ⇒ **每一个第一次打开这一页的人**
        # 看到的都是那颗写着「全不选武器」的紫按钮 —— 全页唯一的高亮控件。
        # 点一下：54 个复选框全部清空、`save_settings()` 当场落盘，
        # **没有确认，也没有撤销**。
        #
        # ⚠ 而它作用的那 54 个复选框在**第二~三屏**（可视区 750px，武器卡从
        #   y≈1050 起），按钮却钉在第一屏 ——
        #   ⭐⭐ **它唯一能改的东西，一个都不在用户眼前。**
        #   （批 27「入口不在第一屏上」的背面：这次是**出口**在第一屏上。）
        #
        # 外审行为题 12 发，四问四答全票一致：
        #   ① 12/12 读对了「全不选武器」并正确预期「清空 54 把」
        #   ② 12/12 答「先点总开关」—— **用户知道该点哪儿**，这不是入口问题
        #   ③ 12/12 指认它是会把已设好的东西弄没的那颗
        #   ④ **12/12「反方向」**
        # ⚠ 外审从没说「我会误点它」，它每次都读对了字。
        #   ⭐ **「这颗按钮指着反方向」是实测；「用户会误点」是推论，别混着写。**
        #
        # ⇒ 这一页没有该由底栏承担的动作：改动即时保存，偏移的 X / Y 有它自己
        #   那张卡上的「应用」，就在两个输入框旁边。主按钮位空着（同 crosshair
        #   批 10：那一轮外审的判词是「一颗灰着的、紫色的、蹲在右下角的按钮，
        #   形状本身就在说『这里有个保存动作』」——而这一页同样没有保存动作）。
        # ⚠ 全选 / 全不选**没有被删**：它们本来就在武器卡的表头上，紧贴那 54 个
        #   复选框 —— 在那儿点，用户看得见自己改了什么。
        # ⭐ 顺带解决 RN-143 在本页的一处：底栏那句话原来只分到 543px（需 758），
        #   两颗按钮撤走之后它拿回整行。
        self.action_bar.configure_primary("", None, visible=False)
        self.action_bar.configure_secondary("", None, visible=False)

        action_message = (
            # ⚠ 本页 `SAVES_AUTOMATICALLY = False`（批 24），所以共用回执**不会**
            # 替它说存不存。撤掉底栏按钮之后，这句话是唯一还在回答
            # 「我到底要不要点什么」的东西 —— 它必须说准。
            "改完就存下了；只有「偏移校准」里的 X / Y 要点那张卡上的"
            f"「{self.offset_apply_btn.text()}」才算数。"
            f"当前：倍率 {self.zoom_factor:.1f}x · 偏移 {self._current_offset_text()}"
            # ⚠ RN-407 家族（批 18）：这里数的是**勾选了几把武器**，不是
            # 「几件事正在跑」。写「已启用 12/18 项」时，如果总开关关着，
            # 这行字就在替一件没发生的事作证 —— 而它和底栏那句「不生效」
            # 挨着，同一屏自相矛盾。
            # ⭐ **「这个设置开着」和「这件事正在发生」是两回事**，
            #   而「已启用」三个字同时承担了这两个意思。⇒ 改说勾选。
            f" · 已勾选 {enabled_weapon_count}/{total_weapon_count} 项。"
        )
        self.action_bar.set_message(action_message)

    def on_master_switch_synced(self):
        """总开关被别处拨动后，把本页状态重算一遍（RN-189）。

        ⭐ 全仓统一的钩子名（`widgets/master_switch_link` 调它）。
        少了这一下，开关动了而徽章不动 —— 同屏两处说法不一致（RN-107 族）。
        """
        self._sync_overview_status()

    def _sync_overview_status(self, *_args):
        if not hasattr(self, "status_badge_label"):
            return

        enabled = bool(getattr(self.config, "magnifier_enabled", False))
        mode_text = "长按" if self.trigger_mode == "长按触发" else "切换"
        enabled_weapon_count = self._enabled_weapon_count()
        total_weapon_count = len(self.weapon_enabled_vars)
        runtime_text, runtime_level = self._current_runtime_text()
        current_weapon_text = "未识别"
        if hasattr(self, "weapon_label"):
            current_weapon_text = self.weapon_label.text().strip() or "未识别"
        status_text = "就绪"
        if hasattr(self, "status_label"):
            status_text = self.status_label.text().strip() or "就绪"

        badges = [
            ("success" if enabled else "warn", f"开关 · {'已启用' if enabled else '已禁用'}"),
            ("info", f"倍率 · {self.zoom_factor:.1f}x"),
            ("info", f"触发 · {mode_text}"),
            ("info", f"分类 · {self._compact_text(self._current_tab_text(), '未分组', 8)}"),
            (runtime_level, f"运行 · {runtime_text}"),
        ]

        sensitivity_enabled = bool(
            getattr(getattr(self, "sensitivity_sync_checkbox", None), "isChecked", lambda: False)()
        )
        preview_sensitivity_text = format_sensitivity_value(
            compute_zoom_sensitivity(
                self._get_base_sensitivity(),
                self._get_sensitivity_multiplier(),
            )
        )
        sensitivity_text = (
            preview_sensitivity_text
            if sensitivity_enabled
            else f"预设 {preview_sensitivity_text}"
        )

        detail_lines = [
            f"总开关：{'已启用' if enabled else '已禁用'}",
            f"当前状态：{status_text}",
            f"当前武器：{current_weapon_text}",
            f"当前分类：{self._current_tab_text()}",
            f"倍率：{self.zoom_factor:.1f}x · 偏移 {self._current_offset_text()}",
            f"主武器热键：{self.primary_hotkey_combo.currentText()} · 手枪热键：{self.secondary_hotkey_combo.currentText()}",
            f"触发方式：{self.trigger_mode} · 防抖 {self.debounce_time}ms",
            f"灵敏度联动：{'已启用' if sensitivity_enabled else '未启用'} · {sensitivity_text}",
            f"已启用武器：{enabled_weapon_count}/{total_weapon_count}",
        ]
        summary_text = "\n".join(detail_lines)
        render_badges(self.status_badge_label, badges, detail_tooltip=summary_text)
        self.summary_label.setText(summary_text)
        self.summary_label.setToolTip(summary_text)
        self.status_card.setToolTip(summary_text)
        self._refresh_basic_panel_summary()
        self._sync_action_bar()

    def _init_weapon_data(self):
        """初始化武器数据"""
        self.weapon_categories = {
            "手枪": ["weapon_usp_silencer", "weapon_hkp2000", "weapon_glock", "weapon_p250", 
                   "weapon_fiveseven", "weapon_cz75a", "weapon_elite", "weapon_deagle", 
                   "weapon_revolver", "weapon_tec9"],
            "冲锋枪": ["weapon_mac10", "weapon_mp9", "weapon_mp7", "weapon_ump45", 
                    "weapon_p90", "weapon_bizon", "weapon_mp5sd"],
            "步枪": ["weapon_ak47", "weapon_m4a1", "weapon_m4a1_silencer", "weapon_famas", 
                   "weapon_galilar", "weapon_aug", "weapon_sg556"],
            "狙击枪": ["weapon_awp", "weapon_ssg08", "weapon_scar20", "weapon_g3sg1"],
            "霰弹枪": ["weapon_nova", "weapon_xm1014", "weapon_mag7", "weapon_sawedoff"],
            "机枪": ["weapon_m249", "weapon_negev"],
            "近战": ["weapon_knife", "weapon_taser", "weapon_fists", "weapon_axe", "weapon_hammer", "weapon_spanner"],
            "投掷物": ["weapon_hegrenade", "weapon_flashbang", "weapon_smokegrenade", "weapon_molotov",
                    "weapon_incgrenade", "weapon_decoy", "weapon_tagrenade", "weapon_snowball"],
            "道具": ["weapon_c4", "weapon_healthshot", "weapon_breachcharge", "weapon_bumpmine",
                   "weapon_tablet", "weapon_shield"]
        }
        
        self.weapon_names = {
            "weapon_usp_silencer": "USP-S", "weapon_hkp2000": "P2000", "weapon_glock": "Glock-18",
            "weapon_p250": "P250", "weapon_fiveseven": "Five-SeveN", "weapon_cz75a": "CZ75-Auto",
            "weapon_elite": "Dual Berettas", "weapon_deagle": "Desert Eagle", "weapon_revolver": "R8 Revolver",
            "weapon_tec9": "Tec-9", "weapon_mac10": "MAC-10", "weapon_mp9": "MP9", "weapon_mp7": "MP7",
            "weapon_ump45": "UMP-45", "weapon_p90": "P90", "weapon_bizon": "PP-Bizon", "weapon_mp5sd": "MP5-SD",
            "weapon_ak47": "AK-47", "weapon_m4a1": "M4A4", "weapon_m4a1_silencer": "M4A1-S",
            "weapon_famas": "FAMAS", "weapon_galilar": "Galil AR", "weapon_aug": "AUG", "weapon_sg556": "SG 553",
            "weapon_awp": "AWP", "weapon_ssg08": "SSG 08", "weapon_scar20": "SCAR-20", "weapon_g3sg1": "G3SG1",
            "weapon_nova": "Nova", "weapon_xm1014": "XM1014", "weapon_mag7": "MAG-7", "weapon_sawedoff": "Sawed-Off",
            "weapon_m249": "M249", "weapon_negev": "Negev", "weapon_knife": "小刀", "weapon_taser": "电击枪",
            "weapon_hegrenade": "高爆手雷", "weapon_flashbang": "闪光弹", "weapon_smokegrenade": "烟雾弹",
            "weapon_molotov": "燃烧瓶", "weapon_incgrenade": "燃烧弹", "weapon_decoy": "诱饵弹",
            "weapon_tagrenade": "战术手雷", "weapon_snowball": "雪球", "weapon_c4": "C4",
            "weapon_healthshot": "治疗针", "weapon_breachcharge": "爆破装置", "weapon_bumpmine": "跳雷",
            "weapon_tablet": "平板", "weapon_shield": "盾牌", "weapon_fists": "拳套",
            "weapon_axe": "斧头", "weapon_hammer": "锤子", "weapon_spanner": "扳手"
        }
    
    def _init_ui(self):
        """创建UI"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)
        
        # UP-047: 页头改用 PageHeader。间距按本页原值传入，一个像素不动。
        header = PageHeader(
            "开镜放大",
            # ⚠ RN-034 的最后一笔：原文**无条件**写「先去「基础设置」打开总开关。」——
            # 开关已经开着的时候它照说不误，而同一屏的徽章写着「开关 · 已启用」。
            # RN-189 把开关搬到这一页的状态卡里之后，这句话连"去哪儿"都不必再提。
            description="开镜时把屏幕中心放大，模拟更高倍率的瞄准镜；还能在放大时自动切到更低的灵敏度。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        main_layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["magnifier"])
        self._create_status_card(main_layout)
        
        # 检查API是否可用
        if not self.magnification_available:
            error_label = QLabel("⚠️ Windows Magnification API不可用\n放大功能已禁用，请确保运行Windows 7或更高版本。")
            error_label.setWordWrap(True)
            error_label.setObjectName("hintLabel")
            main_layout.addWidget(error_label)
            main_layout.addStretch()
            return
        
        # UP-059: 页内锚点导航。实测本页内容 912px vs 可视 426px = **2.14 屏**,
        # 武器范围在最底下,每次都要一路滚过去。复用 R5 高级设置页的方案
        # (make_flow_container + anchorChip + ensureWidgetVisible)。
        from PySide6.QtCore import QTimer as _QT

        from widgets.flow_layout import make_flow_container

        anchor_wrap, self._anchor_bar = make_flow_container(h_spacing=6, v_spacing=6)
        main_layout.addWidget(anchor_wrap)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        main_layout.addWidget(scroll, 1)
        # 卡片要等下面建完才扫得到,推迟到事件循环下一轮
        _QT.singleShot(0, self._build_anchor_chips)
        
        # 内容widget
        content_widget = QWidget()
        scroll.setWidget(content_widget)
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        
        # 基本设置卡片
        self._create_basic_settings_card(content_layout)
        
        # 武器设置卡片
        self._create_weapon_settings_card(content_layout)
        
        content_layout.addStretch()

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(116)
        self.action_bar.primary_btn.setMinimumWidth(132)
        main_layout.addWidget(self.action_bar, 0)
        self._sync_overview_status()


    def _build_anchor_chips(self):
        """扫描页内各分区标题，生成一行跳转 chips（UP-059）。

        本页的分区有两种载体：顶层的 `SettingsCard`（基本设置 / 武器范围）
        与内层的 `QFrame#card`（灵敏度 / 触发方式 / 偏移）。
        只扫前者的话锚点只有 2 个，对 2.14 屏的滚动量没有意义——
        用户真正想直达的恰恰是那几个内层分区。
        """
        try:
            from PySide6.QtCore import QPoint
            from PySide6.QtWidgets import QPushButton, QScrollArea

            scroll = self.findChild(QScrollArea)
            if scroll is None:
                return

            from widgets.settings_card import SettingsCard

            # 只收**滚动区内**的分区：「当前状态」卡挂在 main_layout 上、
            # 在滚动区外面，给它做锚点点了也不会动。
            body = scroll.widget()
            if body is None:
                return

            sections = []
            # 顶层分区用 SettingsCard（基本设置 / 武器范围——后者是本页最深的目标）
            for card in body.findChildren(SettingsCard):
                label = getattr(card, "title_label", None)
                if label is not None and label.text().strip():
                    sections.append((label.text().strip(), card))
            # 内层分区用 QFrame#card（倍率与灵敏度 / 热键与触发 / 偏移校准）
            for card in body.findChildren(QFrame):
                if card.objectName() != "card":
                    continue
                label = card.findChild(QLabel)
                if label is None or label.objectName() != "statusLabel":
                    continue
                title = label.text().strip()
                if title:
                    sections.append((title, card))

            # 按在页面里的实际先后排序，chips 的顺序才和滚动顺序一致
            sections.sort(key=lambda item: item[1].mapTo(body, QPoint(0, 0)).y())

            # 截断要断在词上，别切成「倍率与灵」「热键与触」
            SHORT = {
                "基础控制": "基础",
                "倍率与灵敏度": "倍率",
                "热键与触发": "热键",
                "偏移校准": "偏移",
                "武器开镜范围": "武器范围",
            }
            seen = set()
            for title, card in sections:
                short = SHORT.get(title, title[:4])
                if short in seen:
                    continue
                seen.add(short)
                chip = QPushButton(short)
                # 与 R5 高级设置页同一套：anchorChip 有自己的 QSS，
                # 不复用 secondaryButton（那会吃到 min-width:80，白占宽还提前换行）。
                chip.setObjectName("anchorChip")
                chip.setFixedHeight(26)
                chip.setCursor(Qt.PointingHandCursor)
                chip.setToolTip(f"跳到「{title}」")
                # 不用 ensureWidgetVisible：它只做「最小滚动使其可见」，
                # 对本页这种高卡片会滚到把**底部**露出来——实测点第一个锚点
                # 反而向下滚了 83px，与「跳到这一节」的语义相反。
                # 锚点要的是把该节顶到上方，所以直接算目标位置。
                chip.clicked.connect(
                    lambda _=False, c=card: scroll.verticalScrollBar().setValue(
                        max(0, c.mapTo(body, QPoint(0, 0)).y() - 12)
                    )
                )
                self._anchor_bar.addWidget(chip)
        except Exception:
            # 锚点条是锦上添花，坏了不能连累整页——但要留下痕迹，
            # 否则表现为"锚点条整个不出现"而无人知道为什么（高级页踩过）。
            self.logger.exception("锚点导航生成失败(不影响页面)")

    def _create_inner_panel_card(self, title, description=None):
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
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

    def _refresh_basic_panel_summary(self):
        zoom_key = str(self.zoom_factor)
        zoom_profile = self.zoom_settings.get(zoom_key, {}) if isinstance(self.zoom_settings, dict) else {}
        x_offset = zoom_profile.get("x_offset", 0)
        y_offset = zoom_profile.get("y_offset", 0)
        has_saved_profile = zoom_key in self.zoom_settings

        if hasattr(self, "zoom_profile_label"):
            self.zoom_profile_label.setText(
                f"当前档位：{self.zoom_factor:.1f}x · {'已保存偏移' if has_saved_profile else '尚未单独校准'}"
                f" · X {x_offset} / Y {y_offset}"
            )

        if hasattr(self, "trigger_summary_label"):
            runtime_text, _runtime_level = self._current_runtime_text()
            self.trigger_summary_label.setText(
                f"当前触发：{self.trigger_mode} · 防抖 {self.debounce_time}ms"
                f" · 主武器 {self.primary_hotkey_combo.currentText()} / 手枪 {self.secondary_hotkey_combo.currentText()}"
                f" · 运行 {runtime_text}"
            )

        if hasattr(self, "offset_profile_label"):
            self.offset_profile_label.setText(
                f"当前记录：X {x_offset} / Y {y_offset}"
                f" · {'放大中会立即应用' if self.is_magnifier_active else '待激活时预加载'}"
            )
    
    def _create_basic_settings_card(self, parent_layout):
        """创建基本设置卡片"""
        card, card_layout = SettingsCard.make(
            "基础控制",
            "开镜放大多少倍、按哪个键触发、准心要不要偏一点。", spacing=10
        )
        parent_layout.addWidget(card)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        sensitivity_card, sensitivity_layout = self._create_inner_panel_card(
            "倍率与灵敏度",
            "调放大倍率，并让鼠标灵敏度跟着一起变，放大后手感才不会发飘。",
        )

        zoom_layout = QHBoxLayout()
        zoom_layout.setSpacing(8)
        # UP-031: 下面几个下拉原本 setFixedWidth 写死。QSS 给 QComboBox 留了
        # padding + 下拉箭头(arrow_width + 8 + padding-right 8)，扣掉之后
        # 90px 的框实际只剩约 28px 文本区、116px 只剩约 54px ——
        # 默认字号档下「4.0」「Mouse4」就已经被省略号截断了。
        # 改为 AdjustToContents + 保留原值当下限：宽度只会变宽不会变窄，
        # 既不破坏原有排版，也不会再裁掉文字。
        zoom_layout.addWidget(QLabel("放大倍率:"))
        self.zoom_combo = QComboBox()
        self.zoom_combo.addItems(["1.5", "2.0", "2.5", "3.0", "3.5", "4.0", "4.5", "5.0"])
        self.zoom_combo.setCurrentText("2.0")
        self.zoom_combo.currentTextChanged.connect(self._on_zoom_changed)
        self.zoom_combo.setMinimumWidth(90)
        self.zoom_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.zoom_combo.setFixedHeight(34)
        zoom_layout.addWidget(self.zoom_combo)
        zoom_layout.addStretch()
        sensitivity_layout.addLayout(zoom_layout)

        self.sensitivity_sync_checkbox = QCheckBox("启用开镜灵敏度联动")
        self.sensitivity_sync_checkbox.setToolTip("放大激活时切到开镜灵敏度，关闭时立即恢复基础灵敏度")
        self.sensitivity_sync_checkbox.stateChanged.connect(self._on_sensitivity_sync_changed)
        sensitivity_layout.addWidget(self.sensitivity_sync_checkbox)

        sensitivity_inputs_layout = QGridLayout()
        sensitivity_inputs_layout.setHorizontalSpacing(10)
        sensitivity_inputs_layout.setVerticalSpacing(8)
        sensitivity_inputs_layout.setColumnStretch(0, 0)
        sensitivity_inputs_layout.setColumnStretch(1, 0)
        sensitivity_inputs_layout.setColumnStretch(2, 1)

        sensitivity_inputs_layout.addWidget(QLabel("基础灵敏度:"), 0, 0)
        self.base_sensitivity_input = QLineEdit()
        self.base_sensitivity_input.setFixedWidth(108)
        self.base_sensitivity_input.setFixedHeight(34)
        self.base_sensitivity_input.setText("1.0")
        self.base_sensitivity_input.setPlaceholderText("1.00")
        self.base_sensitivity_input.setValidator(QDoubleValidator(0.01, 20.0, 4, self))
        self.base_sensitivity_input.editingFinished.connect(self._on_sensitivity_values_changed)
        sensitivity_inputs_layout.addWidget(self.base_sensitivity_input, 0, 1)

        sensitivity_inputs_layout.addWidget(QLabel("联动倍率:"), 1, 0)
        self.sensitivity_multiplier_input = QLineEdit()
        self.sensitivity_multiplier_input.setFixedWidth(108)
        self.sensitivity_multiplier_input.setFixedHeight(34)
        self.sensitivity_multiplier_input.setText("0.82")
        self.sensitivity_multiplier_input.setPlaceholderText("0.82")
        self.sensitivity_multiplier_input.setValidator(QDoubleValidator(0.05, 5.0, 4, self))
        self.sensitivity_multiplier_input.editingFinished.connect(self._on_sensitivity_values_changed)
        sensitivity_inputs_layout.addWidget(self.sensitivity_multiplier_input, 1, 1)
        sensitivity_inputs_layout.addWidget(
            # ⚠ RN-143（批 28）：原文 22 字，在紧凑档只分到 198px 而需要 322px，
            # 于是折成 6 行 —— 而它旁边**空着 230px**。
            # ⭐ 折行不是「放不下」，是「我说我能折行」（RN-121 的机制）：
            #   折行的 QLabel 在横排里把自己的宽度报小，布局就照那个窄宽给它。
            # 这一格是 2×1 跨行的说明位，压到一行放得下的长度即可。
            QLabel("联动关着也能先把数值填好。"),
            0,
            2,
            2,
            1,
        )
        sensitivity_layout.addLayout(sensitivity_inputs_layout)

        self.sensitivity_preview_label = QLabel("")
        self.sensitivity_preview_label.setObjectName("subtitleLabel")
        self.sensitivity_preview_label.setWordWrap(True)
        sensitivity_layout.addWidget(self.sensitivity_preview_label)

        self.zoom_profile_label = QLabel("")
        self.zoom_profile_label.setObjectName("hintLabel")
        self.zoom_profile_label.setWordWrap(True)
        sensitivity_layout.addWidget(self.zoom_profile_label)

        self.sensitivity_hint_label = QLabel(
            "基础灵敏度请填写你在 CS2 里的 sensitivity；联动开启后会直接按这里的预设同步。首次在当前游戏会话启用时，如未生效请在控制台执行一次 exec cs2customizer.cfg。"
        )
        self.sensitivity_hint_label.setObjectName("subtitleLabel")
        self.sensitivity_hint_label.setWordWrap(True)
        sensitivity_layout.addWidget(self.sensitivity_hint_label)

        trigger_card, trigger_layout = self._create_inner_panel_card(
            "热键与触发",
            # ⚠ RN-143（批 28）：原文 27 字 = 336px，而这一格分到 335px ——
            # **差 1 个像素**，于是折成两行。完整档同样差 4px（需 420 / 得 416）。
            # ⭐ 这是这一族最极端的一个样本：它证明「被挤到折行」和「放不下」
            #   完全不是一回事 —— 1px 的缺口，任何「有没有溢出 / 有没有截断」的
            #   判据眼里都一切正常。
            "主武器和手枪各自指定放大热键，并选长按还是单击切换。",
        )

        primary_layout = QHBoxLayout()
        primary_layout.setSpacing(8)
        primary_layout.addWidget(QLabel("主武器热键:"))
        self.primary_hotkey_combo = QComboBox()
        self.primary_hotkey_combo.addItems(["右键", "F2", "F3", "F4", "F5", "Z", "X", "中键", "Mouse3", "Mouse4"])
        self.primary_hotkey_combo.setCurrentText("右键")
        self.primary_hotkey_combo.currentTextChanged.connect(self._on_hotkey_changed)
        self.primary_hotkey_combo.setMinimumWidth(116)
        self.primary_hotkey_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.primary_hotkey_combo.setFixedHeight(34)
        primary_layout.addWidget(self.primary_hotkey_combo)
        
        primary_test_btn = QPushButton("测试")
        primary_test_btn.setObjectName("secondaryButton")
        primary_test_btn.setFixedWidth(86)
        primary_test_btn.setFixedHeight(34)
        primary_test_btn.clicked.connect(self._test_primary_hotkey)
        primary_layout.addWidget(primary_test_btn)
        primary_layout.addStretch()
        trigger_layout.addLayout(primary_layout)
        
        secondary_layout = QHBoxLayout()
        secondary_layout.setSpacing(8)
        secondary_layout.addWidget(QLabel("手枪热键:"))
        self.secondary_hotkey_combo = QComboBox()
        self.secondary_hotkey_combo.addItems(["右键", "F2", "F3", "F4", "F5", "Z", "X", "2", "中键", "Mouse3", "Mouse4"])
        self.secondary_hotkey_combo.setCurrentText("右键")
        self.secondary_hotkey_combo.currentTextChanged.connect(self._on_hotkey_changed)
        self.secondary_hotkey_combo.setMinimumWidth(116)
        self.secondary_hotkey_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.secondary_hotkey_combo.setFixedHeight(34)
        secondary_layout.addWidget(self.secondary_hotkey_combo)
        
        secondary_test_btn = QPushButton("测试")
        secondary_test_btn.setObjectName("secondaryButton")
        secondary_test_btn.setFixedWidth(86)
        secondary_test_btn.setFixedHeight(34)
        secondary_test_btn.clicked.connect(self._test_secondary_hotkey)
        secondary_layout.addWidget(secondary_test_btn)
        secondary_layout.addStretch()
        trigger_layout.addLayout(secondary_layout)

        trigger_mode_layout = QHBoxLayout()
        trigger_mode_layout.setSpacing(8)
        trigger_mode_layout.addWidget(QLabel("触发方式:"))
        self.trigger_mode_combo = QComboBox()
        self.trigger_mode_combo.addItems(["长按触发", "单击切换"])
        self.trigger_mode_combo.setCurrentText(self.trigger_mode)
        self.trigger_mode_combo.currentTextChanged.connect(self._on_trigger_mode_changed)
        self.trigger_mode_combo.setMinimumWidth(120)
        self.trigger_mode_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.trigger_mode_combo.setFixedHeight(34)
        trigger_mode_layout.addWidget(self.trigger_mode_combo)
        trigger_mode_layout.addStretch()
        trigger_layout.addLayout(trigger_mode_layout)

        debounce_layout = QHBoxLayout()
        debounce_layout.setSpacing(8)
        debounce_layout.addWidget(QLabel("防抖延迟(ms):"))
        self.debounce_slider = QSlider(Qt.Horizontal)
        self.debounce_slider.setMinimum(50)
        self.debounce_slider.setMaximum(500)
        self.debounce_slider.setValue(150)
        self.debounce_slider.setFixedWidth(180)
        self.debounce_slider.valueChanged.connect(self._on_debounce_changed)
        debounce_layout.addWidget(self.debounce_slider)
        
        self.debounce_label = QLabel("150ms")
        self.debounce_label.setFixedWidth(50)
        debounce_layout.addWidget(self.debounce_label)
        debounce_layout.addStretch()
        trigger_layout.addLayout(debounce_layout)

        self.trigger_summary_label = QLabel("")
        self.trigger_summary_label.setObjectName("hintLabel")
        self.trigger_summary_label.setWordWrap(True)
        trigger_layout.addWidget(self.trigger_summary_label)

        top_row.addWidget(sensitivity_card, 5, Qt.AlignTop)
        top_row.addWidget(trigger_card, 4, Qt.AlignTop)
        card_layout.addLayout(top_row)

        offset_card, offset_layout = self._create_inner_panel_card(
            "偏移校准",
            "放大后准心偏了就在这里校回来；每个倍率各自记住自己的偏移。",
        )
        
        offset_input_layout = QHBoxLayout()
        offset_input_layout.setSpacing(8)
        offset_input_layout.addWidget(QLabel("当前偏移:"))
        
        offset_input_layout.addWidget(QLabel("X:"))
        self.x_offset_input = QLineEdit()
        self.x_offset_input.setFixedWidth(60)
        self.x_offset_input.setFixedHeight(34)
        self.x_offset_input.setText("0")
        self.x_offset_input.setValidator(QIntValidator(-1000, 1000))
        self.x_offset_input.returnPressed.connect(self._apply_offset)
        offset_input_layout.addWidget(self.x_offset_input)
        
        offset_input_layout.addWidget(QLabel("Y:"))
        self.y_offset_input = QLineEdit()
        self.y_offset_input.setFixedWidth(60)
        self.y_offset_input.setFixedHeight(34)
        self.y_offset_input.setText("0")
        self.y_offset_input.setValidator(QIntValidator(-1000, 1000))
        self.y_offset_input.returnPressed.connect(self._apply_offset)
        offset_input_layout.addWidget(self.y_offset_input)
        
        # RN-519：底栏那句话要点名它，所以名字只能有一份 —— 挂到 self 上给那句话读。
        self.offset_apply_btn = QPushButton("应用")
        apply_btn = self.offset_apply_btn
        apply_btn.setObjectName("secondaryButton")
        apply_btn.setFixedWidth(86)
        apply_btn.setFixedHeight(34)
        apply_btn.clicked.connect(self._apply_offset)
        offset_input_layout.addWidget(apply_btn)
        
        reset_btn = QPushButton("重置")
        reset_btn.setObjectName("secondaryButton")
        reset_btn.setFixedWidth(86)
        reset_btn.setFixedHeight(34)
        reset_btn.clicked.connect(self._reset_offset)
        offset_input_layout.addWidget(reset_btn)
        
        offset_input_layout.addStretch()
        offset_layout.addLayout(offset_input_layout)

        self.offset_profile_label = QLabel("")
        self.offset_profile_label.setObjectName("hintLabel")
        self.offset_profile_label.setWordWrap(True)
        offset_layout.addWidget(self.offset_profile_label)
        
        # ⭐⭐ RN-196 横向那 29px（批 28 查实的根因）
        #
        # 这一行摆着 **8 颗方向键**。代码里写的是 `setFixedSize(QSize(30, 26))`，
        # 而它们实际渲染出来是 **80×50** —— `ui_style_applier._style_button` 在
        # 页面建完之后无条件把最小尺寸抬上去：
        #     if button.minimumWidth() < min_width: button.setMinimumWidth(min_width)
        # `setFixedSize` 把 min 和 max 都设成 (30,26)，这两行只抬 min、不动 max，
        # 于是 min > max，Qt 取 min ⇒ **调用点写的固定尺寸一个像素都不生效**。
        # ⇒ 这一行的最小宽从 ~300px 变成 ~800px，直接顶穿整页最小宽度。
        # ⭐ **一句无效的声明不是无害的** —— 它把这一行撑成了两倍半。
        # （全站实测 146/247 颗可见按钮的固定尺寸声明都是死的，已另立 RN-442；
        #   这里只治它在本页造成的那个后果。）
        #
        # ⛔ 不走「把按钮真的缩回 30×26」：那是把点击目标砍掉 3/4，
        #    换一条更糟的缺陷。改成**放得下就一行、放不下就换行**。
        # ⭐ 而这个语言 **同一个方法里 30 行开外就在用** —— `_init_ui` 的锚点条
        #   就是 `make_flow_container`（UP-059）。本工程第 N 次撞见
        #   「修法要用的东西，早就在这个文件里」。
        # ⚠⚠ **改完复跑当场逮住了我这一版修法自己的缺陷**（外审紧凑档整页图
        #   3/3 全票）：第一版是把 8 颗按钮和两个标签**平铺**进 FlowLayout，
        #   于是换行点落在了「大幅」那一组的**中间** —— 前 3 颗留在上一行，
        #   第 4 颗 `v` 掉到下一行最左边，和自己那组脱节。
        #   判词逐字：「按钮组断裂错位」。
        #   ⭐⭐ **我修掉了「放不下就溢出」，换来了「放不下就断在一组的中间」。**
        #     换行本身没错，错在**可换行的单位选错了**：
        #     ⭐ **能换行的单位应该是「一组」，不是「一颗」。**
        # ⇒ 每一组（标签 + 它的 4 颗方向键）先包成一个不可拆的小控件，
        #   再把这两个小控件丢进 FlowLayout。这样要么整组在上一行，要么整组下来。
        from widgets.flow_layout import make_flow_container

        adjust_wrap, adjust_layout = make_flow_container(h_spacing=15, v_spacing=6)

        # ⚠ 这一句留着是为了让「意图」还写在调用点上：它**目前不生效**
        # （原因见上），删掉会让下一个人以为这里从来没人管过尺寸。
        btn_size = QSize(30, 26)

        def _make_nudge_group(title, step):
            group = QWidget()
            group_layout = QHBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(6)
            group_layout.addWidget(QLabel(title))
            for text, axis, amount in [("<", 'x', -step), (">", 'x', step),
                                       ("^", 'y', -step), ("v", 'y', step)]:
                btn = QPushButton(text)
                btn.setFixedSize(btn_size)
                arrow = {'<': '向左', '>': '向右', '^': '向上'}.get(text, '向下')
                btn.setToolTip(f"{arrow}调整{step}像素")
                btn.clicked.connect(
                    lambda checked, a=axis, amt=amount: self._adjust_offset(a, amt))
                self._arrow_buttons.append(btn)
                keep_inline_style(btn)  # UP-019: 样式由 token 现算,免于统一清理
                btn.setStyleSheet(self._get_arrow_button_style())
                group_layout.addWidget(btn)
            return group

        adjust_layout.addWidget(_make_nudge_group("微调:", 1))
        adjust_layout.addWidget(_make_nudge_group("大幅:", 10))

        # FlowLayout 自己就是左对齐、放不下才换行，不需要 addStretch 顶右边。
        offset_layout.addWidget(adjust_wrap)
        card_layout.addWidget(offset_card)
        self._refresh_basic_panel_summary()
    
    def _create_status_card(self, parent_layout):
        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        parent_layout.addWidget(self.status_card)

        card_layout = QVBoxLayout(self.status_card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        # RN-189：就地总开关。首页「功能开关」里有「开镜放大」，而这一页
        # 此前只会写一句「先去「基础设置」打开总开关」把用户支走。
        # ⚠ 拨动走 `MainWindow.set_feature_enabled` ⇒ 首页那颗开关 ⇒ 一整串副作用
        # （放大器启停、提权检查、save_config）。**同一件事只能有一条链路**，
        # 这里绝不自己 `setattr(config, ...)`。
        from widgets.master_switch_link import make_master_switch_row

        self.master_switch_row = make_master_switch_row(
            self, "magnifier_enabled", "开镜放大")
        card_layout.addWidget(self.master_switch_row)

        status_header = QHBoxLayout()
        status_title = QLabel("当前状态")
        status_title.setObjectName("statusLabel")
        status_header.addWidget(status_title)
        status_header.addStretch()
        card_layout.addLayout(status_header)

        self.status_badge_label = create_badge_label()
        card_layout.addWidget(self.status_badge_label)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        card_layout.addWidget(self.summary_label)

        self.status_label = _StatusTrackingLabel("就绪", self.status_card, self._sync_overview_status)
        self.status_label.hide()
        card_layout.addWidget(self.status_label)

        self.weapon_label = _StatusTrackingLabel("未识别", self.status_card, self._sync_overview_status)
        self.weapon_label.hide()
        card_layout.addWidget(self.weapon_label)
        return
    
    def _create_weapon_settings_card(self, parent_layout):
        """创建武器设置卡片"""
        card, card_layout = SettingsCard.make(
            "武器开镜范围",
            "按武器分类勾选允许触发放大的项目，状态卡会同步显示当前所在分类和启用数量。", spacing=10
        )
        parent_layout.addWidget(card)

        header_layout = QHBoxLayout()
        header_layout.addStretch()
        
        select_all_btn = QPushButton("全选")
        select_all_btn.setObjectName("secondaryButton")
        select_all_btn.setFixedWidth(86)
        select_all_btn.setFixedHeight(34)
        select_all_btn.clicked.connect(self._select_all_weapons)
        header_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("全不选")
        deselect_all_btn.setObjectName("secondaryButton")
        deselect_all_btn.setFixedWidth(86)
        deselect_all_btn.setFixedHeight(34)
        deselect_all_btn.clicked.connect(self._deselect_all_weapons)
        header_layout.addWidget(deselect_all_btn)
        
        card_layout.addLayout(header_layout)
        
        self.weapon_tabview = QTabWidget()
        self.weapon_tabview.setMinimumHeight(220)
        self.weapon_tabview.currentChanged.connect(self._sync_overview_status)
        card_layout.addWidget(self.weapon_tabview)
        
        # 为每个类别创建选项卡
        for category, weapons in self.weapon_categories.items():
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(8, 8, 8, 8)
            tab_layout.setSpacing(8)
            
            # UP-059: 这里原本每个页签各套一个 QScrollArea,形成
            # 「页面滚动区 → 页签滚动区」的两层嵌套。实测九个页签的内容
            # 只有 0.05~0.52 屏(内容 24~92px vs 可视 464px)——**它们从来不需要滚动**,
            # 纯粹是白占一层、还把落在武器网格上的滚轮事件吃掉,
            # 用户以为页面卡住了。
            # 去掉之后页签内容直接撑开 tabview,由页面级滚动区兜底;
            # 武器数量以后增长也不会被裁掉,反而比原来更耐改。
            scroll_layout = QGridLayout()
            scroll_layout.setContentsMargins(0, 0, 0, 0)
            scroll_layout.setHorizontalSpacing(14)
            scroll_layout.setVerticalSpacing(10)
            tab_layout.addLayout(scroll_layout)
            tab_layout.addStretch()

            # 添加武器复选框（每行4个）
            weapons_per_row = 4
            for i, weapon in enumerate(weapons):
                row = i // weapons_per_row
                col = i % weapons_per_row
                
                friendly_name = self.weapon_names.get(weapon, weapon)
                checkbox = QCheckBox(friendly_name)
                checkbox.setChecked(True)  # 默认启用
                checkbox.stateChanged.connect(self.save_settings)
                
                self.weapon_enabled_vars[weapon] = checkbox
                scroll_layout.addWidget(checkbox, row, col)
            
            # 添加到选项卡
            self.weapon_tabview.addTab(tab, category)
    
    def _on_zoom_changed(self, text):
        """放大倍率改变"""
        self.zoom_factor = float(text)
        zoom_key = str(self.zoom_factor)
        
        # 更新偏移显示
        if zoom_key in self.zoom_settings:
            self.x_offset_input.setText(str(self.zoom_settings[zoom_key]["x_offset"]))
            self.y_offset_input.setText(str(self.zoom_settings[zoom_key]["y_offset"]))
            calibrated = "已保存设置"
        else:
            self.x_offset_input.setText("0")
            self.y_offset_input.setText("0")
            calibrated = "新设置"
        
        # 如果放大镜当前活动，立即更新
        if self.is_magnifier_active:
            self._update_magnification()
        
        self.status_label.setText(f"已切换到 {self.zoom_factor}x 倍率 ({calibrated})")
        self.logger.info(f"放大倍率更新: {self.zoom_factor}x ({calibrated})")
        self.save_settings()

    def _get_sync_trigger_key(self):
        magnifier_settings = getattr(self.config, "magnifier", {}) or {}
        if isinstance(magnifier_settings, dict):
            sync_key = magnifier_settings.get("sync_trigger_key", DEFAULT_SYNC_TRIGGER_KEY)
            if sync_key:
                return str(sync_key).strip().upper()
        return DEFAULT_SYNC_TRIGGER_KEY

    def _parse_float_input(self, line_edit, default_value, minimum, maximum):
        try:
            value = float(line_edit.text())
        except (TypeError, ValueError):
            value = float(default_value)
        value = max(minimum, min(maximum, value))
        line_edit.setText(format_sensitivity_value(value))
        return value

    def _get_base_sensitivity(self):
        return self._parse_float_input(self.base_sensitivity_input, 1.0, 0.01, 20.0)

    def _get_sensitivity_multiplier(self):
        return self._parse_float_input(self.sensitivity_multiplier_input, 0.82, 0.05, 5.0)

    def _refresh_sensitivity_controls(self):
        enabled = self.sensitivity_sync_checkbox.isChecked()
        self.base_sensitivity_input.setEnabled(True)
        self.sensitivity_multiplier_input.setEnabled(True)

        base_sensitivity = self._get_base_sensitivity()
        multiplier = self._get_sensitivity_multiplier()
        zoom_sensitivity = compute_zoom_sensitivity(base_sensitivity, multiplier)
        if enabled:
            preview_prefix = "当前开镜灵敏度"
            preview_suffix = ""
        else:
            preview_prefix = "预设开镜灵敏度"
            preview_suffix = " · 联动开启后生效"
        self.sensitivity_preview_label.setText(
            f"{preview_prefix}：{format_sensitivity_value(zoom_sensitivity)} "
            f"（{format_sensitivity_value(base_sensitivity)} × {format_sensitivity_value(multiplier)}）"
            f"{preview_suffix}"
        )

    def _get_sensitivity_cfg_signature(self):
        payload = {
            "csgo_dir": (self.config.csgo_dir or "").strip(),
            "enabled": bool(self.sensitivity_sync_checkbox.isChecked()),
            "base_sensitivity": self._get_base_sensitivity(),
            "multiplier": self._get_sensitivity_multiplier(),
            "sync_trigger_key": self._get_sync_trigger_key(),
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    def _ensure_sensitivity_support_files_if_needed(self, force=False):
        signature = self._get_sensitivity_cfg_signature()
        if not force and signature == self._last_sensitivity_cfg_signature:
            return True

        # ⚠ QA-006：签名原本在这一行、也就是**写盘之前**就记账了。
        # 于是写失败之后，下一次同签名调用会在上面的 `signature == 上次签名`
        # 分支直接 `return True` —— 本次会话再也不会重试，用户改回来也没用。
        # 现在挪到写成功之后再记。
        csgo_dir = (self.config.csgo_dir or "").strip()
        if not csgo_dir:
            self.logger.info("未配置 CS2 目录，跳过开镜灵敏度联动 CFG 同步")
            return False

        try:
            setup_autoexec(csgo_dir)
            warnings = write_cs2customizer_cfg(self.config)
            runtime_cfg_path = get_magnifier_runtime_cfg_path(csgo_dir)
            write_magnifier_runtime_cfg(
                runtime_cfg_path,
                self._get_base_sensitivity(),
                self._get_sensitivity_multiplier(),
                self.is_magnifier_active and self.sensitivity_sync_checkbox.isChecked(),
            )
            if warnings:
                try:
                    from ui_toast import toast_warning
                    toast_warning("\n".join(warnings), 5000)
                except Exception:
                    pass
            # QA-006: 写成功之后才记签名——失败时保持旧签名，下次还会重试。
            self._last_sensitivity_cfg_signature = signature
            return True
        except Exception as e:
            self.logger.warning(f"同步开镜灵敏度联动 CFG 失败: {e}")
            return False

    def _sync_magnifier_sensitivity_state(self, active, force=False):
        enabled = self.sensitivity_sync_checkbox.isChecked()
        desired_active = bool(active and enabled)
        if not desired_active and not force and not self._sensitivity_runtime_applied:
            return False

        csgo_dir = (self.config.csgo_dir or "").strip()
        runtime_cfg_path = get_magnifier_runtime_cfg_path(csgo_dir)
        if not runtime_cfg_path:
            return False

        self._ensure_sensitivity_support_files_if_needed(force=force)
        try:
            write_magnifier_runtime_cfg(
                runtime_cfg_path,
                self._get_base_sensitivity(),
                self._get_sensitivity_multiplier(),
                desired_active,
            )

            import keyboard

            keyboard.press_and_release(get_keyboard_key_for_sync(self._get_sync_trigger_key()))
            self._sensitivity_runtime_applied = desired_active
            self.logger.info(
                "已同步开镜灵敏度状态: %s",
                "active" if desired_active else "default",
            )
            return True
        except ImportError:
            self.logger.warning("未安装 keyboard 库，无法同步开镜灵敏度")
        except Exception as e:
            self.logger.warning(f"同步开镜灵敏度状态失败: {e}")
        return False

    def _on_sensitivity_sync_changed(self, _state):
        self._refresh_sensitivity_controls()
        self.save_settings()

        if self.sensitivity_sync_checkbox.isChecked():
            target = compute_zoom_sensitivity(
                self._get_base_sensitivity(),
                self._get_sensitivity_multiplier(),
            )
            self.status_label.setText(
                f"已启用开镜灵敏度联动：{format_sensitivity_value(target)}"
            )
            # ⚠ QA-006：这句「已同步到 CFG」原本是**无条件弹**的，
            # 而真正去写 CFG 的 `_ensure_sensitivity_support_files_if_needed`
            # 失败时只 `logger.warning` 并返回 False，没人看返回值；
            # 连"压根没配 CS2 目录"这种情况也照样报成功。
            # 结果：用户以为已经生效，进游戏发现灵敏度没变，且毫无线索。
            # 现在按真实结果给不同提示。
            ok = self._ensure_sensitivity_support_files_if_needed(force=True)
            if ok:
                try:
                    from ui_toast import toast_info
                    toast_info("已同步到 CFG；若当前游戏会话首次启用，请在控制台执行一次 exec cs2customizer.cfg", 4500)
                except Exception:
                    pass
            else:
                csgo_dir = (self.config.csgo_dir or "").strip()
                msg = ("尚未设置 CS2 目录，无法写入 CFG —— 请先到「高级设置」选择游戏目录"
                       if not csgo_dir else
                       "写入 CFG 失败，开镜灵敏度联动这次没有生效（详见日志）")
                self.status_label.setText(f"开镜灵敏度联动未生效：{msg}")
                try:
                    from ui_toast import toast_warning
                    toast_warning(msg, 6000)
                except Exception:
                    pass
            if self.is_magnifier_active:
                self._sync_magnifier_sensitivity_state(True, force=True)
        else:
            self.status_label.setText("已关闭开镜灵敏度联动")
            self._sync_magnifier_sensitivity_state(False, force=True)

    def _on_sensitivity_values_changed(self):
        self._refresh_sensitivity_controls()
        target = compute_zoom_sensitivity(
            self._get_base_sensitivity(),
            self._get_sensitivity_multiplier(),
        )
        if self.sensitivity_sync_checkbox.isChecked():
            self.status_label.setText(
                f"已更新开镜灵敏度：{format_sensitivity_value(target)}"
            )
        else:
            self.status_label.setText(
                f"已更新灵敏度预设：{format_sensitivity_value(target)}"
            )
        self.save_settings()
        if self.is_magnifier_active and self.sensitivity_sync_checkbox.isChecked():
            self._sync_magnifier_sensitivity_state(True, force=True)
    
    def _on_hotkey_changed(self):
        """热键改变"""
        primary_key = self.primary_hotkey_combo.currentText()
        secondary_key = self.secondary_hotkey_combo.currentText()
        
        # 重新设置键盘监听
        self._setup_key_detection()
        
        self.status_label.setText(f"已更新热键 - 主武器: {primary_key} | 手枪: {secondary_key}")
        self.logger.info(f"热键更新: 主武器={primary_key}, 手枪={secondary_key}")
        self.save_settings()

    def _on_trigger_mode_changed(self, text):
        """触发方式改变"""
        self.trigger_mode = text
        self.status_label.setText(f"已切换触发方式: {text}")
        self.logger.info(f"放大触发方式更新: {text}")
        self.save_settings()
    
    def _on_debounce_changed(self, value):
        """防抖时间改变"""
        self.debounce_time = value
        self.debounce_label.setText(f"{value}ms")
        self.status_label.setText(f"已设置防抖时间为 {value}ms")
        self.save_settings()
    
    def _apply_offset(self):
        """应用偏移"""
        if not self.config.magnifier_enabled:
            return
        
        try:
            x_offset = int(self.x_offset_input.text())
            y_offset = int(self.y_offset_input.text())
            
            zoom_key = str(self.zoom_factor)
            if zoom_key not in self.zoom_settings:
                self.zoom_settings[zoom_key] = {"x_offset": 0, "y_offset": 0}
            
            self.zoom_settings[zoom_key]["x_offset"] = x_offset
            self.zoom_settings[zoom_key]["y_offset"] = y_offset
            
            self.save_settings()
            
            if self.is_magnifier_active:
                self._update_magnification()
            
            self.status_label.setText(f"已应用偏移: X={x_offset}, Y={y_offset}")
        except Exception as e:
            self.status_label.setText(f"应用偏移错误: {e}")
    
    def _reset_offset(self):
        """重置偏移"""
        if not self.config.magnifier_enabled:
            return
        
        zoom_key = str(self.zoom_factor)
        if zoom_key in self.zoom_settings:
            self.zoom_settings[zoom_key]["x_offset"] = 0
            self.zoom_settings[zoom_key]["y_offset"] = 0
            
            self.x_offset_input.setText("0")
            self.y_offset_input.setText("0")
            
            self.save_settings()
            
            if self.is_magnifier_active:
                self._update_magnification()
            
            self.status_label.setText(f"已重置 {self.zoom_factor}x 倍率的偏移设置")
    
    def _adjust_offset(self, axis, amount):
        """微调偏移"""
        if not self.config.magnifier_enabled:
            return
        
        zoom_key = str(self.zoom_factor)
        if zoom_key not in self.zoom_settings:
            self.zoom_settings[zoom_key] = {"x_offset": 0, "y_offset": 0}
        
        if axis == 'x':
            self.zoom_settings[zoom_key]["x_offset"] += amount
            self.x_offset_input.setText(str(self.zoom_settings[zoom_key]["x_offset"]))
        else:
            self.zoom_settings[zoom_key]["y_offset"] += amount
            self.y_offset_input.setText(str(self.zoom_settings[zoom_key]["y_offset"]))
        
        self.save_settings()
        
        if self.is_magnifier_active:
            self._update_magnification()
        
        self.status_label.setText(f"偏移已调整: X={self.zoom_settings[zoom_key]['x_offset']}, Y={self.zoom_settings[zoom_key]['y_offset']}")
    
    def _test_primary_hotkey(self):
        """测试主武器热键"""
        hotkey = self.primary_hotkey_combo.currentText()
        self.logger.info(f"测试主武器热键: {hotkey}")
        self.status_label.setText(f"测试主武器热键: {hotkey}")
        # immediate=True：测试路径不模拟按键，防抖检查的 primary_key_pressed
        # 永远为 False，走防抖分支会静默不激活（测试按钮形同失效）
        self._activate_primary_magnifier(test=True, immediate=True)

        # 3秒后自动关闭
        threading.Timer(3.0, self._deactivate_magnifier).start()

    def _test_secondary_hotkey(self):
        """测试副武器热键"""
        hotkey = self.secondary_hotkey_combo.currentText()
        self.logger.info(f"测试副武器热键: {hotkey}")
        self.status_label.setText(f"测试副武器热键: {hotkey}")
        self._activate_secondary_magnifier(test=True, immediate=True)

        # 3秒后自动关闭
        threading.Timer(3.0, self._deactivate_magnifier).start()
    
    def _select_all_weapons(self):
        """全选武器"""
        for checkbox in self.weapon_enabled_vars.values():
            checkbox.setChecked(True)
        self.save_settings()
        self.status_label.setText("已启用所有武器的放大功能")
    
    def _deselect_all_weapons(self):
        """全不选武器"""
        for checkbox in self.weapon_enabled_vars.values():
            checkbox.setChecked(False)
        self.save_settings()
        self.status_label.setText("已禁用所有武器的放大功能")

    def _clear_mouse_hooks(self, mouse_module=None):
        """清理鼠标热键钩子"""
        if not self._mouse_hooks:
            return
        try:
            if mouse_module is None:
                import mouse as mouse_module
            for hook in self._mouse_hooks:
                try:
                    mouse_module.unhook(hook)
                except Exception:
                    pass
        finally:
            self._mouse_hooks = []
    
    def _setup_key_detection(self):
        """设置键盘监听"""
        # 停止现有线程
        if self.keyboard_thread and self.keyboard_thread.is_alive():
            self.keyboard_running = False
            self.keyboard_thread.join(timeout=1.0)
        
        if not self.config.magnifier_enabled:
            self.status_label.setText("开镜放大全局禁用中")
            return
        
        self.keyboard_running = True
        
        def key_listener():
            try:
                # P2.1: 经热键注册中心统一注册（底层仍是 keyboard/mouse，行为等价），
                # 获得跨功能域冲突检测与"已绑热键总览"。
                from core.hotkeys import registry as hotkey_registry

                # 键盘热键映射
                key_mapping = {
                    "F2": "f2", "F3": "f3", "F4": "f4", "F5": "f5",
                    "Z": "z", "X": "x", "2": "2",
                    "右键": None, "中键": None, "Mouse3": None, "Mouse4": None
                }

                # 清除本功能域现有热键（注册中心按 owner 批量注销）
                hotkey_registry.unregister_owner(self.HOTKEY_OWNER)
                self._clear_mouse_hooks()

                primary_key = self.primary_hotkey_combo.currentText()
                secondary_key = self.secondary_hotkey_combo.currentText()

                mouse_mapping = {
                    "右键": "right",
                    "中键": "middle",
                    "Mouse3": "x",
                    "Mouse4": "x2",
                }

                # 跨功能域冲突检测（advisory：提示但不阻止）
                conflict_notes = []
                for label, ui_key in (("主武器", primary_key), ("副武器", secondary_key)):
                    target = key_mapping.get(ui_key) or (
                        f"mouse:{mouse_mapping[ui_key]}" if ui_key in mouse_mapping else ""
                    )
                    if not target:
                        continue
                    owners = hotkey_registry.find_conflicts(target, exclude_owner=self.HOTKEY_OWNER)
                    if owners:
                        conflict_notes.append(f"{label}键({ui_key})已被「{'、'.join(owners)}」使用")
                if conflict_notes:
                    self.logger.warning("热键冲突: " + "；".join(conflict_notes))

                # 注册主武器键盘热键
                primary_kb_key = key_mapping.get(primary_key)
                if primary_kb_key:
                    self.logger.info(f"注册主武器键盘热键: {primary_kb_key}")
                    hotkey_registry.register_key(
                        self.HOTKEY_OWNER, primary_kb_key,
                        on_press=lambda e: self._global_primary_key_press(),
                        on_release=lambda e: self._global_primary_key_release(),
                        note="主武器开镜",
                    )

                # 注册副武器键盘热键(如果与主武器热键不同)
                if secondary_key != primary_key:
                    secondary_kb_key = key_mapping.get(secondary_key)
                    if secondary_kb_key:
                        self.logger.info(f"注册副武器键盘热键: {secondary_kb_key}")
                        hotkey_registry.register_key(
                            self.HOTKEY_OWNER, secondary_kb_key,
                            on_press=lambda e: self._global_secondary_key_press(),
                            on_release=lambda e: self._global_secondary_key_release(),
                            note="手枪开镜",
                        )

                primary_mouse_button = mouse_mapping.get(primary_key)
                if primary_mouse_button:
                    self.logger.info(f"注册主武器鼠标热键: {primary_mouse_button}")
                    hotkey_registry.register_mouse(
                        self.HOTKEY_OWNER, primary_mouse_button,
                        on_press=lambda: self._global_primary_key_press(),
                        on_release=lambda: self._global_primary_key_release(),
                        note="主武器开镜",
                    )

                if secondary_key != primary_key:
                    secondary_mouse_button = mouse_mapping.get(secondary_key)
                    if secondary_mouse_button:
                        self.logger.info(f"注册副武器鼠标热键: {secondary_mouse_button}")
                        hotkey_registry.register_mouse(
                            self.HOTKEY_OWNER, secondary_mouse_button,
                            on_press=lambda: self._global_secondary_key_press(),
                            on_release=lambda: self._global_secondary_key_release(),
                            note="手枪开镜",
                        )

                status_text = f"主武器热键: {primary_key} | 手枪热键: {secondary_key}"
                if conflict_notes:
                    status_text += " ⚠️ " + "；".join(conflict_notes)
                self.status_label.setText(status_text)
                self.logger.info(f"热键设置完成 - 主武器: {primary_key}, 副武器: {secondary_key}")
                
                # 保持监听线程存活
                while self.keyboard_running:
                    time.sleep(0.05)
                
            except ImportError:
                self.status_label.setText("未安装keyboard/mouse库")
                self.logger.warning("未安装keyboard/mouse库")
            except Exception as e:
                self.status_label.setText(f"热键错误: {e}")
                self.logger.error(f"热键错误: {e}")
        
        self.keyboard_thread = threading.Thread(target=key_listener, daemon=True, name="MagnifierKeyboard")
        self.keyboard_thread.start()

    def _is_toggle_mode(self):
        return self.trigger_mode == "单击切换"
    
    def _global_primary_key_press(self):
        """全局主武器热键按下处理"""
        if not self.primary_key_pressed:  # 避免重复触发
            self.logger.info("主武器热键按下")
            self.primary_key_pressed = True
            if self._is_toggle_mode():
                if self.is_magnifier_active and self.current_active_type == 'primary':
                    self._deactivate_magnifier()
                else:
                    self._activate_primary_magnifier(immediate=True)
            else:
                self._activate_primary_magnifier()
    
    def _global_primary_key_release(self):
        """全局主武器热键释放处理"""
        if self.primary_key_pressed:  # 避免重复触发
            self.logger.info("主武器热键释放")
            self.primary_key_pressed = False
            if not self._is_toggle_mode() and self.current_active_type == 'primary':
                self._deactivate_magnifier()
    
    def _global_secondary_key_press(self):
        """全局副武器热键按下处理"""
        if not self.secondary_key_pressed:  # 避免重复触发
            self.logger.info("副武器热键按下")
            self.secondary_key_pressed = True
            if self._is_toggle_mode():
                if self.is_magnifier_active and self.current_active_type == 'secondary':
                    self._deactivate_magnifier()
                else:
                    self._activate_secondary_magnifier(immediate=True)
            else:
                self._activate_secondary_magnifier()
    
    def _global_secondary_key_release(self):
        """全局副武器热键释放处理"""
        if self.secondary_key_pressed:  # 避免重复触发
            self.logger.info("副武器热键释放")
            self.secondary_key_pressed = False
            if not self._is_toggle_mode() and self.current_active_type == 'secondary':
                self._deactivate_magnifier()
    
    def _is_current_weapon_enabled(self):
        """检查当前武器是否启用了放大功能"""
        if not self.current_weapon:
            return False  # 无法确定当前武器时默认不放大，避免沿用上一把武器
        
        # 处理刀类武器 (统一映射到weapon_knife)
        weapon = self.current_weapon
        if weapon.startswith("weapon_knife"):
            weapon = "weapon_knife"
        
        # 检查武器是否在已知列表中，如果不在则默认不启用，避免误触发
        if weapon not in self.weapon_enabled_vars:
            return False
        
        return self.weapon_enabled_vars[weapon].isChecked()
    
    def _activate_primary_magnifier(self, test=False, immediate=False):
        """激活主武器放大"""
        # 标记测试模式下不需要检查武器启用状态
        if not test:
            # 如果全局禁用了，不响应激活命令
            if not self.config.magnifier_enabled:
                self.logger.info("放大功能全局禁用中，无法激活主武器放大")
                return
            
            # 检查当前武器是否启用了放大
            if not self._is_current_weapon_enabled():
                self.logger.info(f"当前武器 {self.current_weapon} 未启用放大功能")
                return
            
            # 如果已经激活了同类型的放大，不需要处理
            if self.is_magnifier_active and self.current_active_type == 'primary':
                return
            
            # 如果已经激活了其他类型的放大，先停止
            if self.is_magnifier_active:
                self._deactivate_magnifier()
        
        if immediate:
            if self.magnification_available:
                self.activate_magnification_signal.emit('primary')
            return

        # 设置当前激活类型
        self.current_active_type = 'primary'
        
        # 防抖处理
        current_time = time.time() * 1000  # 转换为毫秒
        
        # 主武器专用防抖状态
        if not self.primary_debouncing:
            # 启动防抖
            self.primary_key_press_time = current_time
            self.primary_debouncing = True
            
            # 设置定时器检查按键是否保持按下
            self.logger.info(f"启动主武器防抖处理，延迟: {self.debounce_time}ms")
            threading.Timer(self.debounce_time / 1000.0, self._check_primary_debounce).start()
    
    def _activate_secondary_magnifier(self, test=False, immediate=False):
        """激活副武器放大"""
        # 标记测试模式下不需要检查武器启用状态
        if not test:
            # 如果全局禁用了，不响应激活命令
            if not self.config.magnifier_enabled:
                self.logger.info("放大功能全局禁用中，无法激活副武器放大")
                return
            
            # 检查当前武器是否启用了放大
            if not self._is_current_weapon_enabled():
                self.logger.info(f"当前武器 {self.current_weapon} 未启用放大功能")
                return
            
            # 如果已经激活了同类型的放大，不需要处理
            if self.is_magnifier_active and self.current_active_type == 'secondary':
                return
            
            # 如果已经激活了其他类型的放大，先停止
            if self.is_magnifier_active:
                self._deactivate_magnifier()
        
        if immediate:
            if self.magnification_available:
                self.activate_magnification_signal.emit('secondary')
            return

        # 设置当前激活类型
        self.current_active_type = 'secondary'
        
        # 防抖处理 - 副武器专用
        current_time = time.time() * 1000  # 转换为毫秒
        
        # 副武器专用防抖状态
        if not self.secondary_debouncing:
            # 启动防抖
            self.secondary_key_press_time = current_time
            self.secondary_debouncing = True
            
            # 设置定时器检查按键是否保持按下
            self.logger.info(f"启动副武器防抖处理，延迟: {self.debounce_time}ms")
            threading.Timer(self.debounce_time / 1000.0, self._check_secondary_debounce).start()
    
    def _check_primary_debounce(self):
        """检查主武器防抖时间是否达到"""
        if not self.primary_debouncing:
            self.logger.info("主武器防抖状态已重置，不需要检查")
            return
        
        current_time = time.time() * 1000
        elapsed = current_time - self.primary_key_press_time
        
        self.logger.info(f"主武器防抖检查: 已按下 {elapsed}ms, 需要 {self.debounce_time}ms")
        self.logger.info(f"  - 按键状态: primary_key_pressed={self.primary_key_pressed}")
        self.logger.info(f"  - 放大状态: is_magnifier_active={self.is_magnifier_active}")
        self.logger.info(f"  - API可用: magnification_available={self.magnification_available}")
        
        # 检查按键是否仍然按下
        if self.primary_key_pressed:
            # 检查是否达到防抖时间
            if elapsed >= self.debounce_time:
                self.logger.info("[PASS] 主武器防抖时间达到，激活放大")
                # 防抖时间已达到，实际激活放大
                if not self.is_magnifier_active and self.magnification_available:
                    try:
                        # 使用信号在主线程中激活放大
                        self.activate_magnification_signal.emit('primary')
                        self.logger.info("[工作线程] 已发送主武器放大激活信号")
                    except Exception as e:
                        self.logger.error(f"发送主武器放大信号失败: {e}")
        
        # 重置防抖状态
        self.primary_debouncing = False
    
    def _check_secondary_debounce(self):
        """检查副武器防抖时间是否达到"""
        if not self.secondary_debouncing:
            self.logger.info("副武器防抖状态已重置，不需要检查")
            return
        
        current_time = time.time() * 1000
        elapsed = current_time - self.secondary_key_press_time
        
        self.logger.info(f"副武器防抖检查: 已按下 {elapsed}ms, 需要 {self.debounce_time}ms")
        self.logger.info(f"  - 按键状态: secondary_key_pressed={self.secondary_key_pressed}")
        self.logger.info(f"  - 放大状态: is_magnifier_active={self.is_magnifier_active}")
        self.logger.info(f"  - API可用: magnification_available={self.magnification_available}")
        
        # 检查按键是否仍然按下
        if self.secondary_key_pressed:
            # 检查是否达到防抖时间
            if elapsed >= self.debounce_time:
                self.logger.info("[PASS] 副武器防抖时间达到，激活放大")
                # 防抖时间已达到，实际激活放大
                if not self.is_magnifier_active and self.magnification_available:
                    try:
                        # 使用信号在主线程中激活放大
                        self.activate_magnification_signal.emit('secondary')
                        self.logger.info("[工作线程] 已发送副武器放大激活信号")
                    except Exception as e:
                        self.logger.error(f"发送副武器放大信号失败: {e}")
        
        # 重置防抖状态
        self.secondary_debouncing = False
    
    def _set_magnifier_crosshair(self):
        """设置放大时的准心样式"""
        if self.crosshair_component:
            # 保存原始准心设置（只保存一次）
            if not hasattr(self, 'original_crosshair_saved') or not self.original_crosshair_saved:
                self.original_crosshair_size = getattr(self.crosshair_component, 'size', 20)
                self.original_crosshair_thickness = getattr(self.crosshair_component, 'thickness', 2)
                self.original_crosshair_color = getattr(self.crosshair_component, 'color', 'green')
                self.original_crosshair_style = getattr(self.crosshair_component, 'style', 'crosshair')
                self.original_crosshair_animation = getattr(self.crosshair_component, 'animation_style', 'none')
                self.original_crosshair_kill_effect = getattr(self.crosshair_component, 'kill_effect', 'none')
                self.original_crosshair_visible = getattr(self.crosshair_component, 'is_visible', True)
                self.original_crosshair_saved = True
                self.logger.info(f"已保存原始准心设置: size={self.original_crosshair_size}, color={self.original_crosshair_color}, style={self.original_crosshair_style}")
            
            # 根据放大倍率决定准心变化
            if 3.0 <= self.zoom_factor <= 5.0:  # 3-5倍：准心变成红色小点
                if hasattr(self.crosshair_component, 'update_settings'):
                    self.crosshair_component.update_settings(
                        size=5,  # 小点
                        thickness=5,  # 点的厚度
                        color='red',  # 红色
                        style='dot',  # 点状
                        animation_style='none',  # 无动画
                        kill_effect='none'  # 无击杀效果
                    )
                    self.logger.info(f"高倍放大({self.zoom_factor}x)，准心已改为红色小点")
            elif 1.0 < self.zoom_factor < 3.0:  # 1-3倍：缩小当前准心
                if hasattr(self.crosshair_component, 'update_settings'):
                    # 计算缩小比例：倍数越高，准心越小
                    # 在1倍时保持原大小，在3倍时缩小到原来的40%
                    scale_factor = 1.0 - (self.zoom_factor - 1.0) / 2.0 * 0.6  # 从100%到40%
                    new_size = max(int(self.original_crosshair_size * scale_factor), 5)  # 最小5px
                    new_thickness = max(int(self.original_crosshair_thickness * scale_factor), 1)  # 最小1px
                    
                    self.crosshair_component.update_settings(
                        size=new_size,
                        thickness=new_thickness,
                        color=self.original_crosshair_color,  # 保持原色
                        style=self.original_crosshair_style,  # 保持原样式
                        animation_style='none',  # 关闭动画
                        kill_effect='none'  # 关闭击杀效果
                    )
                    self.logger.info(f"中低倍放大({self.zoom_factor}x)，准心已缩小至{format_percent(scale_factor)} (size={new_size}, thickness={new_thickness})")
    
    def _restore_original_crosshair(self):
        """恢复原始准心样式"""
        if self.crosshair_component and hasattr(self, 'original_crosshair_saved') and self.original_crosshair_saved:
            # 如果准心被隐藏了，先显示
            if hasattr(self.crosshair_component, 'show_crosshair'):
                self.crosshair_component.show_crosshair()
            
            # 恢复所有原始设置
            if hasattr(self.crosshair_component, 'update_settings'):
                self.crosshair_component.update_settings(
                    size=self.original_crosshair_size,
                    thickness=self.original_crosshair_thickness,
                    color=self.original_crosshair_color,
                    style=self.original_crosshair_style,
                    animation_style=self.original_crosshair_animation,
                    kill_effect=self.original_crosshair_kill_effect
                )
                self.logger.info("准心已恢复为原始样式")
            
            # 重置保存标志，以便下次重新保存
            self.original_crosshair_saved = False
    
    def _deactivate_magnifier(self):
        """停用放大（从工作线程调用，通过信号转到主线程）"""
        if not self.is_magnifier_active:
            return
        
        try:
            # 使用信号在主线程中停用放大
            self.deactivate_magnification_signal.emit()
            self.logger.info("[工作线程] 已发送停用放大信号")
        except Exception as e:
            self.logger.error(f"发送停用放大信号失败: {e}")
    
    def _update_magnification(self):
        """更新放大设置"""
        if not self.config.magnifier_enabled:
            self.logger.warning("放大功能未启用，无法激活")
            return False
        
        if not self.magnification_available:
            self.logger.error("Magnification API 不可用或初始化失败")
            self.logger.error("可能的原因：")
            self.logger.error("  1. Windows Magnification API 初始化失败（可尝试『以管理员身份重启』）")
            self.logger.error("  2. 系统不支持 Magnification API")
            return False
        
        try:
            zoom_key = str(self.zoom_factor)
            user_x_offset = 0
            user_y_offset = 0
            
            if zoom_key in self.zoom_settings:
                user_x_offset = self.zoom_settings[zoom_key]["x_offset"]
                user_y_offset = self.zoom_settings[zoom_key]["y_offset"]
            
            base_x_offset = self.screen_center_x * (1 - 1/self.zoom_factor)
            base_y_offset = self.screen_center_y * (1 - 1/self.zoom_factor)
            
            final_x_offset = int(base_x_offset) + user_x_offset
            final_y_offset = int(base_y_offset) + user_y_offset
            
            self.logger.debug(f"调用MagSetFullscreenTransform: zoom={self.zoom_factor}, x={final_x_offset}, y={final_y_offset}")
            
            # 清除之前的错误代码，以便准确获取本次调用的错误
            kernel32.SetLastError(0)
            
            result = MagSetFullscreenTransform(
                float(self.zoom_factor),  # ctypes会自动转换为c_float
                int(final_x_offset),      # ctypes会自动转换为c_int
                int(final_y_offset)       # ctypes会自动转换为c_int
            )
            
            self.logger.debug(f"MagSetFullscreenTransform 返回值: {result}")
            
            if result:
                MagShowSystemCursor(True)
                self.logger.info(f"放大成功: {self.zoom_factor}x, 偏移({final_x_offset}, {final_y_offset})")
                return True
            else:
                # 获取详细的Windows错误信息
                error_code = kernel32.GetLastError()
                buffer_size = 1024
                buffer = create_unicode_buffer(buffer_size)
                kernel32.FormatMessageW(
                    0x00001000 | 0x00000200,  # FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS
                    None,
                    error_code,
                    0,
                    buffer,
                    buffer_size,
                    None
                )
                error_msg = buffer.value.strip() if buffer.value else f"未知错误 (代码:{error_code})"
                self.logger.error(f"MagSetFullscreenTransform返回失败 (result={result})")
                self.logger.error(f"Windows错误: {error_msg} (错误代码: {error_code})")
                return False
            
        except Exception as e:
            self.logger.error(f"更新放大设置失败: {e}", exc_info=True)
            return False
    
    def _do_activate_magnification(self, activation_type: str):
        """槽函数：在主线程中激活放大（由信号触发，类型经信号参数传递）"""
        try:
            # 快速主/副连按时共享成员会被后一次覆盖，改为信号参数携带
            self.pending_activation_type = activation_type
            weapon_type = "主武器" if activation_type == 'primary' else "副武器"
            self.logger.info(f"[主线程] 开始激活放大 - 类型: {weapon_type}")
            success = self._update_magnification()
            if success:
                self.is_magnifier_active = True
                self.current_active_type = activation_type

                # 修改准心样式
                self._set_magnifier_crosshair()
                self._sync_magnifier_sensitivity_state(True, force=True)

                # 更新状态标签
                hotkey = self.primary_hotkey_combo.currentText() if activation_type == 'primary' else self.secondary_hotkey_combo.currentText()
                self.status_label.setText(f"{weapon_type}放大已激活 (热键: {hotkey})")
                self.logger.info(f"{weapon_type}放大已激活 (热键: {hotkey})")
            else:
                self.logger.warning(f"{weapon_type}放大激活失败")
        except Exception as e:
            self.logger.error(f"激活放大失败: {e}", exc_info=True)
    
    def _do_deactivate_magnification(self):
        """槽函数：在主线程中停用放大（由信号触发）"""
        if not self.is_magnifier_active:
            return
        
        if self.magnification_available:
            try:
                self.logger.info("[主线程] 开始停用放大")
                MagSetFullscreenTransform(float(1.0), 0, 0)
                self.is_magnifier_active = False
                self.current_active_type = None
                self._sync_magnifier_sensitivity_state(False, force=True)
                
                # 恢复原始准心样式
                self._restore_original_crosshair()
                
                self.status_label.setText("放大镜已关闭")
                self.logger.info("放大镜已关闭")
            except Exception as e:
                self.status_label.setText(f"关闭放大镜失败: {e}")
                self.logger.error(f"关闭放大镜失败: {e}", exc_info=True)
    
    def _attempt_mag_init(self):
        """尝试初始化 Magnification API，可重复调用。

        2.1.3 起程序默认普通权限运行——实测普通权限即可初始化成功；
        个别环境失败时不再武断要求管理员，而是保留重试与提权引导。
        """
        if not self._mag_dll_available or self.magnification_available:
            return self.magnification_available
        try:
            self.logger.info("正在初始化 Magnification API...")
            result = MagInitialize()
            self.logger.info(f"MagInitialize() 返回值: {result}")
            if result:
                self.magnification_available = True
                self.logger.info("[OK] Magnification API 初始化成功")
            else:
                error_code = kernel32.GetLastError()
                self.logger.error(f"初始化Magnification API失败 (错误代码: {error_code})")
                self.logger.error("可稍后重试；若持续失败，可尝试『以管理员身份重启』")
        except Exception as e:
            self.logger.error(f"初始化Magnification API出错: {e}", exc_info=True)
        return self.magnification_available

    def _offer_admin_restart(self):
        """放大初始化失败时，引导用户以管理员身份重启（仅少数环境需要）。"""
        from PySide6.QtWidgets import QApplication, QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("开镜放大")
        box.setIcon(QMessageBox.Warning)
        box.setText("放大功能初始化失败。")
        box.setInformativeText(
            "绝大多数电脑普通权限即可使用放大；当前环境初始化失败，\n"
            "以管理员身份重启 CS2 Customizer 通常可以解决。\n\n"
            "是否现在以管理员身份重启？"
        )
        restart_btn = box.addButton("以管理员身份重启", QMessageBox.AcceptRole)
        box.addButton("暂不", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is restart_btn:
            from core.utils.elevation import restart_as_admin

            if restart_as_admin():
                self.logger.info("已请求管理员重启，当前实例退出")
                QApplication.quit()
            else:
                from ui_toast import toast_warning

                toast_warning("提权被取消或失败，已继续以普通权限运行", 4000)

    def enable_magnifier(self, interactive=True):
        """启用放大功能。

        interactive=False 用于页面构造等非用户主动场景：失败时只记录
        状态、不弹提权引导弹窗，避免启动期打扰用户。
        """
        if not self.magnification_available:
            self._attempt_mag_init()
        if self.magnification_available:
            self._ensure_sensitivity_support_files_if_needed()
            self.status_label.setText("开镜放大已启用")
            self._setup_key_detection()
            self.logger.info("开镜放大功能已启用")
        else:
            self.status_label.setText("放大初始化失败")
            if interactive:
                self._offer_admin_restart()
    
    def disable_magnifier(self):
        """禁用放大功能"""
        if self.is_magnifier_active:
            self._deactivate_magnifier()
        elif self._sensitivity_runtime_applied:
            self._sync_magnifier_sensitivity_state(False, force=True)
        # P2.1: 注销本功能域全部热键（含键盘与鼠标）
        try:
            from core.hotkeys import registry as hotkey_registry

            hotkey_registry.unregister_owner(self.HOTKEY_OWNER)
        except Exception:
            pass
        self._clear_mouse_hooks()
        
        self.keyboard_running = False
        if self.keyboard_thread and self.keyboard_thread.is_alive():
            try:
                self.keyboard_thread.join(timeout=0.5)
            except Exception:
                pass

        self.status_label.setText("开镜放大已禁用")
        self.logger.info("开镜放大功能已禁用")
    
    def set_crosshair_component(self, crosshair_component):
        """设置准心组件引用"""
        self.crosshair_component = crosshair_component
        self.logger.info("已设置准心组件引用")
    
    def update_current_weapon(self, weapon_name):
        """更新当前武器（线程安全入口：GSI线程调用时经信号编组到主线程执行）"""
        self.weapon_update_signal.emit(weapon_name or "")

    def _do_update_current_weapon(self, weapon_name):
        """实际更新当前武器（仅主线程执行，允许直接操作UI）"""
        normalized_weapon = weapon_name or ""
        if normalized_weapon.startswith("weapon_knife"):
            normalized_weapon = "weapon_knife"

        if self.current_weapon != normalized_weapon:
            self.current_weapon = normalized_weapon

            if not normalized_weapon:
                display_name = "未识别"
            elif normalized_weapon == "weapon_knife":
                display_name = "小刀"
            else:
                display_name = self.weapon_names.get(normalized_weapon, normalized_weapon)

            self.weapon_label.setText(display_name)

            if self.is_magnifier_active and not self._is_current_weapon_enabled():
                self.logger.info(f"当前武器已切换为禁用项，自动关闭放大: {normalized_weapon or 'unknown'}")
                self._deactivate_magnifier()
    
    def load_settings(self):
        """加载设置"""
        if hasattr(config, 'magnifier') and isinstance(config.magnifier, dict):
            # 临时断开信号连接，避免加载时触发保存
            self.zoom_combo.currentTextChanged.disconnect(self._on_zoom_changed)
            self.primary_hotkey_combo.currentTextChanged.disconnect(self._on_hotkey_changed)
            self.secondary_hotkey_combo.currentTextChanged.disconnect(self._on_hotkey_changed)
            self.trigger_mode_combo.currentTextChanged.disconnect(self._on_trigger_mode_changed)
            self.debounce_slider.valueChanged.disconnect(self._on_debounce_changed)
            self.sensitivity_sync_checkbox.blockSignals(True)
            
            # 加载放大倍率
            if "zoom_factor" in config.magnifier:
                self.zoom_factor = config.magnifier["zoom_factor"]
                self.zoom_combo.setCurrentText(str(config.magnifier["zoom_factor"]))
            
            # 加载热键
            if "primary_hotkey" in config.magnifier:
                self.primary_hotkey_combo.setCurrentText(config.magnifier["primary_hotkey"])
            elif "hotkey" in config.magnifier:
                self.primary_hotkey_combo.setCurrentText(config.magnifier["hotkey"])
            if "secondary_hotkey" in config.magnifier:
                self.secondary_hotkey_combo.setCurrentText(config.magnifier["secondary_hotkey"])
            elif "hotkey" in config.magnifier:
                self.secondary_hotkey_combo.setCurrentText(config.magnifier["hotkey"])

            if "trigger_mode" in config.magnifier:
                trigger_mode = config.magnifier["trigger_mode"]
                if trigger_mode in {"长按触发", "单击切换"}:
                    self.trigger_mode = trigger_mode
            self.trigger_mode_combo.setCurrentText(self.trigger_mode)
            
            # 加载防抖时间
            if "debounce_time" in config.magnifier:
                self.debounce_time = config.magnifier["debounce_time"]
                self.debounce_slider.setValue(self.debounce_time)
                self.debounce_label.setText(f"{self.debounce_time}ms")

            sensitivity_enabled = bool(config.magnifier.get("sensitivity_sync_enabled", False))
            base_sensitivity = float(config.magnifier.get("base_sensitivity", 1.0))
            sensitivity_multiplier = float(config.magnifier.get("sensitivity_multiplier", 0.82))
            self.sensitivity_sync_checkbox.setChecked(sensitivity_enabled)
            self.base_sensitivity_input.setText(format_sensitivity_value(base_sensitivity))
            self.sensitivity_multiplier_input.setText(format_sensitivity_value(sensitivity_multiplier))
            
            # 重新连接信号
            self.zoom_combo.currentTextChanged.connect(self._on_zoom_changed)
            self.primary_hotkey_combo.currentTextChanged.connect(self._on_hotkey_changed)
            self.secondary_hotkey_combo.currentTextChanged.connect(self._on_hotkey_changed)
            self.trigger_mode_combo.currentTextChanged.connect(self._on_trigger_mode_changed)
            self.debounce_slider.valueChanged.connect(self._on_debounce_changed)
            self.sensitivity_sync_checkbox.blockSignals(False)
            
            # 加载放大倍率设置（必须先于武器设置：武器 setChecked 一旦触发
            # save_settings，会用尚未加载的空 zoom_settings 整体覆盖配置）
            if "zoom_settings" in config.magnifier and isinstance(config.magnifier["zoom_settings"], dict):
                self.zoom_settings = config.magnifier["zoom_settings"]

            # 加载武器设置（屏蔽信号：stateChanged 直连 save_settings，
            # 加载期触发会把用户的倍率偏移校准清空落盘）
            if "weapon_settings" in config.magnifier:
                for weapon, enabled in config.magnifier["weapon_settings"].items():
                    if weapon in self.weapon_enabled_vars:
                        checkbox = self.weapon_enabled_vars[weapon]
                        checkbox.blockSignals(True)
                        checkbox.setChecked(enabled)
                        checkbox.blockSignals(False)
                
                # 更新当前倍率的偏移显示
                zoom_key = str(self.zoom_factor)
                if zoom_key in self.zoom_settings:
                    self.x_offset_input.setText(str(self.zoom_settings[zoom_key]["x_offset"]))
                    self.y_offset_input.setText(str(self.zoom_settings[zoom_key]["y_offset"]))

            self._refresh_sensitivity_controls()
            self._last_sensitivity_cfg_signature = None
            if self.sensitivity_sync_checkbox.isChecked() and (self.config.csgo_dir or "").strip():
                self._ensure_sensitivity_support_files_if_needed(force=True)
            
            self.status_label.setText("已加载保存的设置")
            self.logger.info("开镜放大设置加载完成")
    
    def save_settings(self):
        """保存设置"""
        # 保存武器启用设置
        weapon_settings = {}
        for weapon, checkbox in self.weapon_enabled_vars.items():
            weapon_settings[weapon] = checkbox.isChecked()
        
        # 更新配置
        magnifier_settings = {
            "zoom_factor": self.zoom_factor,
            "primary_hotkey": self.primary_hotkey_combo.currentText(),
            "secondary_hotkey": self.secondary_hotkey_combo.currentText(),
            "trigger_mode": self.trigger_mode,
            "debounce_time": self.debounce_time,
            "weapon_settings": weapon_settings,
            "zoom_settings": self.zoom_settings,
            "sensitivity_sync_enabled": self.sensitivity_sync_checkbox.isChecked(),
            "base_sensitivity": self._get_base_sensitivity(),
            "sensitivity_multiplier": self._get_sensitivity_multiplier(),
            "sync_trigger_key": self._get_sync_trigger_key(),
        }
        
        config.magnifier = magnifier_settings
        config.save_config()
        self._ensure_sensitivity_support_files_if_needed()
        self._sync_overview_status()
    
    def cleanup(self):
        """清理资源"""
        from theme_manager import get_theme_manager
        get_theme_manager().unregister_theme_changed_callback(self._apply_theme_styles)

        if self.is_magnifier_active:
            self._deactivate_magnifier()
        elif self._sensitivity_runtime_applied:
            self._sync_magnifier_sensitivity_state(False, force=True)

        # P2.1: 注销注册中心里本功能域的全部热键（键盘+鼠标）
        try:
            from core.hotkeys import registry as hotkey_registry

            hotkey_registry.unregister_owner(self.HOTKEY_OWNER)
        except Exception:
            pass
        self._clear_mouse_hooks()
        self.keyboard_running = False
        if self.keyboard_thread and self.keyboard_thread.is_alive():
            try:
                self.keyboard_thread.join(timeout=0.5)
            except Exception:
                pass

        self.save_settings()
        
        if self.magnification_available:
            try:
                MagUninitialize()
            except Exception as e:
                self.logger.error(f"释放Magnification API失败: {e}")
        
        self.logger.info("开镜放大页面清理完成")

    
    def _get_arrow_button_style(self):
        """获取箭头按钮样式"""
        return f"""
            QPushButton {{
                background-color: {get_color('bg_tertiary')};
                border: 1px solid {get_color('border_primary')};
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
                color: {get_color('accent_primary')};
            }}
            QPushButton:hover {{
                background-color: {get_color('bg_elevated')};
                border-color: {get_color('accent_hover')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('accent_primary')};
                color: white;
            }}
        """
    
    def _apply_theme_styles(self):
        """应用主题样式到箭头按钮"""
        arrow_btn_style = f"""
            QPushButton {{
                background-color: {get_color('bg_tertiary')};
                border: 1px solid {get_color('border_primary')};
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
                color: {get_color('accent_primary')};
            }}
            QPushButton:hover {{
                background-color: {get_color('bg_elevated')};
                border-color: {get_color('accent_hover')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('accent_primary')};
                color: white;
            }}
        """
        for btn in self._arrow_buttons:
            btn.setStyleSheet(arrow_btn_style)
