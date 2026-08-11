# SPDX-License-Identifier: GPL-3.0-or-later
"""
UI设计系统 - 统一组件规范
定义所有UI组件的标准尺寸、间距、圆角、阴影等设计规范
确保整个应用的视觉一致性
"""

from dataclasses import dataclass, fields
from typing import Dict


# ========== 设计标准 ==========

@dataclass
class Spacing:
    """间距标准（v4: 拉开节奏，呼吸感）"""
    xs: int = 4      # 超小间距（图标和文字间）
    sm: int = 8      # 小间距（紧凑控件间）
    md: int = 12     # 中等间距（一般控件间）
    lg: int = 20     # 大间距（卡片内分组间，原 16）
    xl: int = 28     # 超大间距（卡片间，原 24）
    xxl: int = 40    # 巨大间距（区块间，原 32）
    huge: int = 56   # 顶部 hero 区域


@dataclass
class BorderRadius:
    """圆角标准（v4: 略放大，更柔和）"""
    sm: int = 6      # 小圆角（输入框、tag）
    md: int = 8      # 中圆角（按钮、combobox）
    lg: int = 12     # 大圆角（卡片，原 10）
    xl: int = 14     # 超大圆角（大区块，原 12）
    full: str = "50%"  # 完全圆形


@dataclass
class FontSize:
    """字体大小标准（v4: 拉开层级差异）"""
    caption: int = 11    # 标签性文字（badge、tag 内）
    xs: int = 12         # 辅助说明（hint）
    sm: int = 13         # 次要正文（描述）
    md: int = 14         # 主要正文（默认）
    lg: int = 15         # 强调正文（卡片小标题）
    # R7/D-02(UP-043): 卡片标题专用档。D-02 原定 15px，改为 16px——
    # 依据是执行期实测：SettingsCard 的标题走 #statusLabel 实际只有 14px（与正文同号，
    # 阶梯确实塌了），但 gui_widget._create_card 那条路的 #cardTitle 实际是 **18px**、
    # 层级本来就成立。若照 15 落地，首页 6 张卡的标题会从 18 掉到 15，是把好的那条也压坏。
    # 取 16 两边都成立（14→16 抬起来、18→16 只降一档），且仍在蓝图"16px 左右"容差内。
    # 偏离已记入 docs/ui-perf/03_执行日志.md。
    card_title: int = 16
    xl: int = 18         # 节标题（H3）
    xxl: int = 22        # 卡片标题（H2，原 16）
    h1: int = 28         # 页面主标题（H1，原 22）


@dataclass
class Motion:
    """动效时长标准(2.2.0):全应用统一手感,改这里=全局调速。

    现状对齐:切页/toast 本就 150-200ms,token 化不改变现有体感。"""
    fast: int = 150    # 退出类(toast 隐藏、收起)
    base: int = 200    # 主流转场(切页、toast 弹出)
    slow: int = 300    # 强调类(大面板展开)


@dataclass
class FontWeight:
    """字重标准（v4 新增）"""
    light: int = 300
    regular: int = 400
    medium: int = 500
    semibold: int = 600
    bold: int = 700


@dataclass
class LetterSpacing:
    """字间距（v4 新增，QSS 不直接支持，用作 QFont 配置）"""
    tight: float = -0.4    # H1/H2 紧凑
    normal: float = 0.0    # 正文
    wide: float = 0.5      # 标签 uppercase


@dataclass
class ComponentHeight:
    """组件高度标准"""
    xs: int = 24     # 超小组件
    sm: int = 28     # 小组件
    md: int = 34     # 中等组件（输入框、combobox）
    lg: int = 38     # 大组件（按钮，原 36）
    xl: int = 42     # 超大组件（主按钮）


@dataclass
class Shadow:
    """阴影标准"""
    sm: str = "0 1px 3px rgba(0, 0, 0, 0.12)"
    md: str = "0 4px 6px rgba(0, 0, 0, 0.1)"
    lg: str = "0 10px 20px rgba(0, 0, 0, 0.15)"
    xl: str = "0 20px 40px rgba(0, 0, 0, 0.2)"


# ========== 组件规范 ==========

@dataclass
class ButtonSpec:
    """按钮规范"""
    # 主要按钮
    primary_height: int = 36
    primary_padding_horizontal: int = 18
    primary_padding_vertical: int = 8
    primary_border_radius: int = 8
    primary_font_size: int = 13
    primary_min_width: int = 80
    
    # 次要按钮
    secondary_height: int = 36
    secondary_padding_horizontal: int = 18
    secondary_padding_vertical: int = 8
    secondary_border_radius: int = 8
    secondary_font_size: int = 13
    secondary_border_width: int = 1
    
    # 操作按钮
    action_height: int = 34
    action_padding_horizontal: int = 16
    action_padding_vertical: int = 7
    action_border_radius: int = 8
    action_font_size: int = 13
    
    # 图标按钮
    icon_size: int = 36
    icon_border_radius: int = 8
    
    # 危险按钮
    danger_height: int = 36
    danger_padding_horizontal: int = 18
    danger_padding_vertical: int = 8
    danger_border_radius: int = 8
    danger_font_size: int = 13


@dataclass
class InputSpec:
    """输入框规范"""
    # 文本输入框
    text_height: int = 34
    text_padding_horizontal: int = 12
    text_padding_vertical: int = 7
    text_border_radius: int = 8
    text_border_width: int = 1
    text_font_size: int = 13
    
    # 多行文本框
    textarea_padding: int = 12
    textarea_border_radius: int = 8
    textarea_border_width: int = 1
    textarea_font_size: int = 13
    textarea_line_height: float = 1.5
    
    # 下拉框
    combobox_height: int = 34
    combobox_padding_horizontal: int = 12
    combobox_padding_vertical: int = 7
    combobox_border_radius: int = 8
    combobox_border_width: int = 1
    combobox_font_size: int = 13
    combobox_arrow_width: int = 20


@dataclass
class ToggleSpec:
    """开关类控件规范"""
    # 复选框
    checkbox_size: int = 18
    checkbox_border_radius: int = 5
    checkbox_border_width: int = 2
    checkbox_check_size: int = 12
    
    # 单选框
    radio_size: int = 18
    radio_border_width: int = 2
    radio_inner_size: int = 10
    
    # 开关
    switch_width: int = 40
    switch_height: int = 20
    switch_handle_size: int = 16
    switch_border_radius: int = 10


@dataclass
class SliderSpec:
    """滑块规范"""
    # 水平滑块
    horizontal_height: int = 6
    horizontal_handle_size: int = 16
    horizontal_border_radius: int = 3
    
    # 垂直滑块
    vertical_width: int = 6
    vertical_handle_size: int = 16
    vertical_border_radius: int = 3
    
    # 进度条
    progressbar_height: int = 6
    progressbar_border_radius: int = 3


@dataclass
class Elevation:
    """v5: 阴影系统 — 让卡片在深底上"浮起"看得见.

    用 QGraphicsDropShadowEffect 时:
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(ds.elevation.md_blur)
        shadow.setColor(QColor(0, 0, 0, ds.elevation.md_alpha))
        shadow.setOffset(0, ds.elevation.md_offset_y)

    md 是默认级别(SettingsCard 用),lg 用于弹出层/重要卡片.
    """
    sm_blur: int = 8        # 输入框 / 小元素
    sm_alpha: int = 80
    sm_offset_y: int = 2

    md_blur: int = 16       # R7/D-01(UP-052): 24→16。blur 半径直接决定每次重绘要软件高斯模糊多大一圈
    md_alpha: int = 90      # R7/D-01(UP-052): 120→90。层级感够用即可，不追求"厚重"
    md_offset_y: int = 6

    lg_blur: int = 40       # 弹出层 / 模态 / 重要卡
    lg_alpha: int = 160
    lg_offset_y: int = 12


@dataclass
class ContainerSpec:
    """容器规范（v4: 加大 padding，留白）"""
    # 卡片（v4: padding 18→24，border_radius 12→14）
    card_padding: int = 24
    card_padding_compact: int = 16  # 紧凑卡片（信息密的）
    card_border_radius: int = 14
    card_border_width: int = 1
    card_shadow: str = "0 12px 28px rgba(0, 0, 0, 0.12)"

    # 卡片标题↔内容间距（v4 新增）
    card_title_to_content: int = 14
    card_section_gap: int = 16  # 卡片内分组间

    # 分组框
    groupbox_padding: int = 18
    groupbox_border_radius: int = 12
    groupbox_border_width: int = 1
    groupbox_title_padding: int = 10

    # 分隔线
    separator_thickness: int = 1
    separator_margin_vertical: int = 16

    # UP-053: 正文说明(hintLabel)的最大行宽。
    # 限的是**文字**不是内容区——给内容区限宽会让 4 个页面从 3 列掉到 2 列(R7 实测)。
    # 实测 2200px 窗口下 hintLabel 单行会拉到 1936px(约 242 个中文字),这里收到 720。
    #
    # 随字号档缩放(见 apply_font_scale):行长该按"每行多少个字"恒定而不是按像素恒定,
    # 否则大字号档下同样的 720px 会挤出更多行、把无滚动区的页面顶出可视区。
    hint_max_width: int = 720


@dataclass
class ScrollbarSpec:
    """滚动条规范（v4: 收窄到 6px，更精致）"""
    width: int = 6
    border_radius: int = 3
    handle_min_height: int = 36
    margin: int = 2


@dataclass
class TooltipSpec:
    """提示框规范"""
    padding_horizontal: int = 10
    padding_vertical: int = 6
    border_radius: int = 6
    font_size: int = 12
    max_width: int = 320


@dataclass
class TableSpec:
    """表格规范"""
    row_height: int = 38
    header_height: int = 40
    cell_padding_horizontal: int = 12
    cell_padding_vertical: int = 8
    border_width: int = 1


@dataclass
class ListSpec:
    """列表规范"""
    item_height: int = 36
    item_padding_horizontal: int = 12
    item_padding_vertical: int = 8
    item_border_radius: int = 6


# ========== 设计系统单例 ==========

class DesignSystem:
    """UI设计系统单例"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        # 初始化所有规范
        self.spacing = Spacing()
        self.radius = BorderRadius()
        self.font_size = FontSize()
        self.font_weight = FontWeight()
        self.motion = Motion()
        self.letter_spacing = LetterSpacing()
        self.height = ComponentHeight()
        self.shadow = Shadow()
        self.elevation = Elevation()  # v5 新加
        
        # 组件规范
        self.button = ButtonSpec()
        self.input = InputSpec()
        self.toggle = ToggleSpec()
        self.slider = SliderSpec()
        self.container = ContainerSpec()
        self.scrollbar = ScrollbarSpec()
        self.tooltip = TooltipSpec()
        self.table = TableSpec()
        self.list = ListSpec()
    
    def get_component_spec(self, component_type: str) -> Dict:
        """
        获取组件规范
        
        Args:
            component_type: 组件类型（button, input, toggle, slider等）
        
        Returns:
            组件规范字典
        """
        spec_map = {
            'button': self.button,
            'input': self.input,
            'toggle': self.toggle,
            'slider': self.slider,
            'container': self.container,
            'scrollbar': self.scrollbar,
            'tooltip': self.tooltip,
            'table': self.table,
            'list': self.list,
        }
        
        return spec_map.get(component_type)


# ========== 全局访问函数 ==========

def get_design_system() -> DesignSystem:
    """获取设计系统单例"""
    return DesignSystem()


# ========== 界面字号缩放(R1-1,2026-06-12) ==========
# 为什么在 token 层做:theme_manager 的 QSS 全部由 FontSize/ButtonSpec/InputSpec
# token 生成,缩放一处即可穿透 27 页;5 处图标字形 px(如帮助"×")刻意不缩放。

FONT_SCALE_CHOICES = (1.0, 1.1, 1.25)
_current_font_scale = 1.0


def normalize_font_scale(value) -> float:
    """把任意输入收敛到合法档位(脏配置自动回正到 1.0)。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 1.0
    for choice in FONT_SCALE_CHOICES:
        if abs(v - choice) < 0.01:
            return choice
    return 1.0


def get_font_scale() -> float:
    return _current_font_scale


def apply_font_scale(scale) -> float:
    """按档位缩放全部字号 token。

    幂等:每次都从 dataclass 出厂默认值重算,反复调用/换档不会累积漂移。
    返回实际生效的档位。调用后需重新应用主题(set_theme)以重生成 QSS。
    """
    global _current_font_scale
    scale = normalize_font_scale(scale)
    ds = get_design_system()

    base_font = FontSize()
    for f in fields(FontSize):
        setattr(ds.font_size, f.name, max(9, round(getattr(base_font, f.name) * scale)))

    base_button = ButtonSpec()
    for name in ("primary_font_size", "secondary_font_size", "action_font_size", "danger_font_size"):
        setattr(ds.button, name, max(9, round(getattr(base_button, name) * scale)))

    base_input = InputSpec()
    for name in ("text_font_size", "textarea_font_size", "combobox_font_size"):
        setattr(ds.input, name, max(9, round(getattr(base_input, name) * scale)))

    # UP-053: 行宽跟着字号走,让"每行多少个字"在三档下大致恒定。
    # 不跟着走的话,1.25 档同样的 720px 会多挤出几行、把无滚动区的页面顶出可视区。
    ds.container.hint_max_width = round(ContainerSpec().hint_max_width * scale)

    _current_font_scale = scale
    return scale


# ========== 使用示例 ==========

if __name__ == "__main__":
    ds = get_design_system()
    
    print(f"主要按钮高度: {ds.button.primary_height}px")
    print(f"输入框圆角: {ds.input.text_border_radius}px")
    print(f"卡片内边距: {ds.container.card_padding}px")
    print(f"标准间距: {ds.spacing.md}px")


