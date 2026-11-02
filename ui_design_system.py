# SPDX-License-Identifier: GPL-3.0-or-later
"""
UI设计系统 - 统一组件规范
定义所有UI组件的标准尺寸、间距、圆角、阴影等设计规范
确保整个应用的视觉一致性
"""

from dataclasses import dataclass, fields


# ========== 设计标准 ==========

@dataclass
class Spacing:
    """间距：4 / 8 / 12 / 16 / 24（批 145）。"""
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32
    huge: int = 48


@dataclass
class BorderRadius:
    """圆角：控件 6，卡片 8（批 145）。"""
    sm: int = 6
    md: int = 6
    lg: int = 8
    xl: int = 8
    full: str = "50%"


@dataclass
class FontSize:
    """字号阶梯 12 / 13 / 14 / 16 / 18，靠字重分层，不靠猛跳字号（批 145）。"""
    caption: int = 12
    xs: int = 12         # 提示、页签、徽章
    sm: int = 13         # 次要正文
    md: int = 13         # 正文、控件
    lg: int = 14         # 小节标题
    card_title: int = 14
    xl: int = 16         # 品牌名、紧凑档标题
    xxl: int = 18
    h1: int = 18         # 页面标题


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


def qss_box(total: int, padding: int = 0, border: int = 0) -> int:
    """把「整个控件多大」的令牌，换算成 QSS 的 `min-*` / `max-*` 要的**内容盒**数。

    ⭐⭐⭐ RN-551（批 67）：本模块所有名字叫 `*_height` / `*_min_width` 的令牌，
    说的都是**整个控件**在屏幕上占多大；而 Qt 样式表跟 CSS 一样，
    `min-height` / `min-width` 量的是**内容盒**，padding 与 border 在它之外。
    于是 `min-height: {button.secondary_height}px` 发出去的 36，
    屏幕上是 **36 + padding 8×2 + border 1×2 = 54**（高 50%）。

    后果不是「差一点」，是**调用点写下的高度全成了死信**：`setFixedHeight(36)`
    把 max 定到 36，而样式表把 min 顶到 54，**Qt 在 min > max 时取 min** ⇒ 54。
    ⭐ **规格与调用点两处独立声明写着同一个数，而屏幕给的是第三个数。**
    批 66 全站实测 342 个受管控件里 **260 个**实高大于以它命名的那个令牌。

    ⚠ RN-442（宽 133 颗）与 RN-547（高 161 颗）都是它的表征，两条当时的修法
    是给按钮打 `fp_narrow` / `fp_short` 把**下限清零** —— 那是在下游一颗一颗补，
    上游的单位错配一直在，而且清零之后规格下限对那些按钮也一起没了。

    ⚠ `:focus` 档换 border 时 padding 也跟着减（`max(0, padding - Δborder)`），
    所以内容盒不变、总高不变 —— 换算只需按**常态**那一档算一次。
    """
    return max(0, total - 2 * padding - 2 * border)


@dataclass
class ComponentHeight:
    """组件高度标准"""
    xs: int = 24
    sm: int = 28
    md: int = 32     # 输入框、下拉框、按钮
    lg: int = 32
    xl: int = 36


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
    """按钮规范：一律高 32（批 145）。"""
    primary_height: int = 32
    primary_padding_horizontal: int = 14
    primary_padding_vertical: int = 5
    primary_border_radius: int = 6
    primary_font_size: int = 13
    primary_min_width: int = 64

    secondary_height: int = 32
    secondary_padding_horizontal: int = 12
    secondary_padding_vertical: int = 5
    secondary_border_radius: int = 6
    secondary_font_size: int = 13
    secondary_border_width: int = 1

    action_height: int = 32
    action_padding_horizontal: int = 12
    action_padding_vertical: int = 5
    action_border_radius: int = 6
    action_font_size: int = 13

    icon_size: int = 32
    icon_border_radius: int = 6

    danger_height: int = 32
    danger_padding_horizontal: int = 12
    danger_padding_vertical: int = 5
    danger_border_radius: int = 6
    danger_font_size: int = 13


@dataclass
class InputSpec:
    """输入框规范"""
    text_height: int = 32
    text_padding_horizontal: int = 10
    text_padding_vertical: int = 5
    text_border_radius: int = 6
    text_border_width: int = 1
    text_font_size: int = 13

    textarea_padding: int = 8
    textarea_border_radius: int = 6
    textarea_border_width: int = 1
    textarea_font_size: int = 13
    textarea_line_height: float = 1.5

    combobox_height: int = 32
    combobox_padding_horizontal: int = 10
    combobox_padding_vertical: int = 5
    combobox_border_radius: int = 6
    combobox_border_width: int = 1
    combobox_font_size: int = 13
    combobox_arrow_width: int = 16


@dataclass
class ToggleSpec:
    """开关类控件规范"""
    checkbox_size: int = 16
    checkbox_border_radius: int = 4
    checkbox_border_width: int = 1
    checkbox_check_size: int = 12

    radio_size: int = 14
    radio_border_width: int = 2
    radio_inner_size: int = 8

    switch_width: int = 36
    switch_height: int = 20
    switch_handle_size: int = 16
    switch_border_radius: int = 10


@dataclass
class SliderSpec:
    """滑块规范"""
    # 水平滑块
    horizontal_height: int = 4      # RN-642：6 → 4，槽是一根线不是一条带
    horizontal_handle_size: int = 14
    horizontal_border_radius: int = 2

    # 垂直滑块
    vertical_width: int = 4
    vertical_handle_size: int = 14
    vertical_border_radius: int = 3
    
    # 进度条
    progressbar_height: int = 6
    progressbar_border_radius: int = 3


@dataclass
class ContainerSpec:
    """容器规范：卡片不靠阴影立，靠底色和发丝线（批 145）。"""
    card_padding: int = 16
    card_padding_compact: int = 12
    card_border_radius: int = 8
    card_border_width: int = 1
    card_shadow: str = "none"

    card_title_to_content: int = 8
    card_section_gap: int = 12

    groupbox_padding: int = 12
    groupbox_border_radius: int = 8
    groupbox_border_width: int = 1
    groupbox_title_padding: int = 8

    separator_thickness: int = 1
    separator_margin_vertical: int = 12


@dataclass
class Density:
    """紧凑档的版面密度（RN-548，批 65）。

    ⭐⭐⭐ 紧凑档**只是把窗口改小**：1280×800 → 860×640，侧栏收成浮层。
    内容可视区从 750px 掉到 462px（少 288px），而**版面密度一档都没跟着变** ——
    卡片内边距、分组间距、页面边距全是完整档那套数。
    ⇒ 竖向余量不到 1px：滚动条从 6 加到 **7px 就当场红**（批 62 实测）。
    ⭐ 这也解释了历史上那次「收窄到 6px，更精致」是怎么来的：**不是审美，是没地方了。**

    ⚠⚠ **而 RN-548 立案说的修法（给 `ui_design_system` 加一档）本身走不通** ——
    批 65 用 AST 数了一遍：全仓 **813 处** `setContentsMargins` / `setSpacing` /
    `setFixedHeight` / `setMinimumHeight` 里，实参来自本模块 token 的只有 **8 处（1%）**，
    `spacing` / `container` 两组 token 的读取点只剩 `gui_widget.py` 6 处。
    ⭐⭐⭐ **给一个没人在读的规格加一档，等于什么都没做。**
    ⇒ 所以这一档不是「另一套 token 让页面去读」，而是一条**上限**：
    由 `ui_style_applier.apply_compact_density()` 在页面建完之后**把已经写死的数收一收**。
    这是唯一够得着那 813 处的办法，也和 `mark_compact_buttons()` 同一个形状。

    ⚠ 只收**竖向**（上下边距、竖向间距）。横向一律不动 —— 这一档买的是竖向余量，
    而紧凑档横向本来就不缺（860 宽只比完整档少 420，侧栏收走的正好抵掉）。
    """

    #: 竖向间距上限（QVBoxLayout.spacing / QGridLayout.verticalSpacing）
    compact_max_vertical_spacing: int = 8
    #: 上下内边距上限（任何 layout 的 contentsMargins 的 top / bottom）
    compact_max_vertical_margin: int = 8


@dataclass
class ScrollbarSpec:
    """滚动条规范。

    ⚠⚠ 2026-09-06 批 62（RN-045 后一半）：v4 那次「收窄到 6px，更精致」
    把可发现性一起收窄掉了。批 61 把把手的对比度从 1.06 推到 3.41~3.80，
    行为题（同题面改前/改后各 24 发）问「这一页显示完了吗、你从哪看出来的」，
    依据提到滚动条的只从 **0/12 变成 3/21** —— **对比度过线了，尺寸没过线**。
    WCAG 2.1 §1.4.11 只管对比度，而「看不看得出这里能滚」是两件事。
    ⚠⚠ 批 62 试过 6 → 10px，**紧凑档当场多出 13 处「最小高超出可视区」**
    （gun_sound 四个页签各 19px + 整页 16px、kill_voice 八个页签各 12px、
    magnifier 由 48 变 60）；退回 6px 全部消失。7px 就已经开始红。
    ⭐⭐⭐ **一个已经零余量的容器，会把任何一次改进都变成一次「变坏」** ——
    那是 RN-529 的题目（26/28 页紧凑档折线以下有内容），排在批 64。
    ⇒ 当时宽度**留在 6px**；可发现性改用**把轨道画出来**买（不占版面）。

    ⚠⚠⚠ **批 64 补跑外审证明那个替代方案无效，RN-045 重开。** 同题面四档：
    修之前 **0/12（0%）** → 只修对比度 **3/21（14%）** → 加宽到 10px **10/20（50%）**
    → 发货那版「6px + 把轨道画出来」**1/24（4%）**。
    ⭐⭐⭐ **我用一个「看起来等价、又不占版面」的替代方案，换掉了一个已经被数
    证明有效的方案 —— 而换的时候手上没有数。** 换来的比只修对比度那版还低。
    ⇒ 批 65 先做 RN-548（给紧凑档一档自己的版面密度，腾出竖向余量），
      再把宽度加回 **10px**。⭐ 那 4px 一直要不起，不是因为它贵，
      是因为**装它的那个容器早就没有余量了**。
    """
    width: int = 10
    border_radius: int = 3
    handle_min_height: int = 32
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
    row_height: int = 32
    header_height: int = 32
    cell_padding_horizontal: int = 10
    cell_padding_vertical: int = 6
    border_width: int = 1


@dataclass
class ListSpec:
    """列表规范"""
    item_height: int = 32
    item_padding_horizontal: int = 10
    item_padding_vertical: int = 6
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
        
        # 组件规范
        self.button = ButtonSpec()
        self.input = InputSpec()
        self.toggle = ToggleSpec()
        self.slider = SliderSpec()
        self.container = ContainerSpec()
        self.density = Density()
        self.scrollbar = ScrollbarSpec()
        self.tooltip = TooltipSpec()
        self.table = TableSpec()
        self.list = ListSpec()

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

    # ⚠⚠ RN-592（批 82 实测，**记在这里是为了挡住下一个人走同一条路**）：
    #   我在这里加过一段「按钮高度也跟着 scale 缩放」，理由看起来很硬 ——
    #   本函数文档写着「按档位缩放**全部字号 token**」，而装字的高度显然该跟着字号走。
    #   ⭐⭐⭐ **实测买 0：1.25 档 41 处纵向放不下 → 还是 41 处。**
    #   根因：下限一超过**调用点写死的上限**，`mark_compact_buttons()` 就打 `fp_short`，
    #   而那个变体**整条摘掉下限**（最坏那颗 `basic`「重置ID」min 被摘到 18、max 钉在 28）。
    #   ⇒ 承重的是调用点那句写死的高度（RN-442 那一族的纵向双胞胎）。已撤回 ——
    #   ⭐ 留着它就是一段「看起来像修好了」的死码。

    base_input = InputSpec()
    for name in ("text_font_size", "textarea_font_size", "combobox_font_size"):
        setattr(ds.input, name, max(9, round(getattr(base_input, name) * scale)))

    _current_font_scale = scale
    return scale


# ========== 使用示例 ==========

if __name__ == "__main__":
    ds = get_design_system()
    
    print(f"主要按钮高度: {ds.button.primary_height}px")
    print(f"输入框圆角: {ds.input.text_border_radius}px")
    print(f"卡片内边距: {ds.container.card_padding}px")
    print(f"标准间距: {ds.spacing.md}px")
