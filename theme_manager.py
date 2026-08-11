# SPDX-License-Identifier: GPL-3.0-or-later
"""
主题管理系统
提供统一的UI颜色方案和样式标准
集成设计系统规范，确保所有组件遵循统一标准
"""

from dataclasses import dataclass
from typing import Dict
from core.utils.logger import get_logger
from ui_design_system import get_design_system


@dataclass
class ThemeColors:
    """主题颜色定义"""
    # 主背景色
    bg_primary: str          # 主背景
    bg_secondary: str        # 次要背景（卡片、侧边栏等）
    bg_tertiary: str         # 第三背景（悬停、选中等）
    bg_elevated: str         # 浮起元素背景

    # 文字颜色
    text_primary: str        # 主要文字
    text_secondary: str      # 次要文字
    text_tertiary: str       # 第三文字（提示文本等）
    text_disabled: str       # 禁用文字

    # 主题色
    accent_primary: str      # 主题色（主要强调色）
    accent_hover: str        # 主题色悬停
    accent_pressed: str      # 主题色按下
    accent_disabled: str     # 主题色禁用

    # 边框颜色
    border_primary: str      # 主要边框
    border_secondary: str    # 次要边框
    border_focus: str        # 聚焦边框

    # 状态颜色
    success: str             # 成功
    warning: str             # 警告
    error: str               # 错误
    info: str                # 信息

    # 功能颜色
    scrollbar_bg: str        # 滚动条背景
    scrollbar_handle: str    # 滚动条滑块
    scrollbar_hover: str     # 滚动条悬停

    shadow: str              # 阴影颜色

    # v5 新增（None 时由 Theme 在 __post_init__ 自动从既有色推导，
    # 让旧主题定义不破坏；DarkTheme 等显式提供精调值）
    bg_card: str | None = None          # 卡片背景（在 bg_secondary 上提亮一档）
    bg_card_hover: str | None = None    # 卡片 hover 态
    accent_secondary: str | None = None # 次要强调色（cyan 类）
    accent_warm: str | None = None      # 暖色（琥珀，警告/提醒）

    # R4（UP-021/UP-023）新增。两者都**默认自动推导**，不要求各主题手写——
    # 手写 9 份必漏，且以后新增主题会静默不达标。要覆盖就显式给值。
    text_muted: str | None = None       # 提示/辅助正文（hintLabel 等），保证 ≥4.5:1
    text_on_primary: str | None = None  # 落在品牌色上的文字（primaryButton）
    # R7 补 R4 的漏：禁用态**底色**是 bg_tertiary@90 叠在卡片上，而 text_disabled
    # 是按"和常态文字能分辨"选的，压在那个底上只有 1.64~2.33:1（8/8 主题），
    # 等于看不见。WCAG 豁免禁用控件不等于允许它消失。
    text_on_disabled: str | None = None


class Theme:
    """主题基类"""

    def __init__(self, name: str, colors: ThemeColors):
        self.name = name
        self.colors = colors
        self.logger = get_logger()
        self.ds = get_design_system()  # 引入设计系统
        # v5: 给未显式提供 v5 新字段的主题做兜底,从既有色推导
        self._fill_v5_defaults(colors)

    def _fill_v5_defaults(self, colors: "ThemeColors") -> None:
        """v5 兜底:None 字段从既有色推导.让 DarkTheme 之外的主题不破坏."""
        if colors.bg_card is None:
            # 在 bg_secondary 之上提亮一档(亮度 +6%,饱和度略降)
            colors.bg_card = self._lighten_color(colors.bg_secondary, factor=1.06)
        if colors.bg_card_hover is None:
            colors.bg_card_hover = self._lighten_color(colors.bg_card, factor=1.06)
        if colors.accent_secondary is None:
            # 默认与主色一致(无 dual accent),具体主题可显式覆盖
            colors.accent_secondary = colors.accent_primary
        if colors.accent_warm is None:
            colors.accent_warm = colors.warning
        self._fill_contrast_defaults(colors)

    def _fill_contrast_defaults(self, colors: "ThemeColors") -> None:
        """R4：按 WCAG 数学推导 text_muted / text_on_primary（UP-023 / UP-021）。

        UP-023：`hintLabel` 原本直接吃 `text_tertiary`，9 个主题里 8 个只有
        3.1~3.4:1，达不到 AA 正文的 4.5。按 D-15 只修对比度、**不动 12px 字号**。
        提示文字会同时落在 bg_primary(侧栏/标签栏) / bg_secondary / bg_card 上，
        所以取三者里最差的那个来收敛，只对其中一个达标等于没修。

        UP-021：`primaryButton` 原本硬编码 `color: white`，而按钮底色是
        `lighten(accent) → accent` 的渐变。墨绿/海洋/高对比/暖橙四个主题的品牌色
        亮度高，白字被冲掉（实测 1.4~2.1:1）。这里对渐变**两个端点**分别算，
        取黑白里"最差情况更好"的那个——单看一端会被渐变另一头打脸。
        """
        from core.utils.contrast import best_on_color, ensure_contrast

        if colors.text_muted is None:
            colors.text_muted = ensure_contrast(
                colors.text_tertiary,
                (colors.bg_primary, colors.bg_secondary, colors.bg_card),
            )

        if colors.text_on_primary is None:
            # 由实底品牌色（渐变的主导端）决定黑字还是白字；渐变的浅端
            # 随后由 _accent_gradient_top() 反过来向它收敛，不再让浅端说了算。
            colors.text_on_primary = best_on_color(colors.accent_primary)

        if colors.text_on_disabled is None:
            # 禁用态的实际底色 = bg_tertiary 以 90/255 的 alpha 叠在卡片底上。
            # 必须按**合成后**的底色收敛，按 bg_tertiary 本身算会偏。
            # 目标 3:1 而不是 4.5——禁用控件本就该弱化，但不该消失；
            # 3:1 是 WCAG 给大字/非文字的档，用作"看得清但明显次要"的下限。
            disabled_bg = self._blend_hex(colors.bg_tertiary, 90, colors.bg_card)
            colors.text_on_disabled = ensure_contrast(
                colors.text_disabled, (disabled_bg,), 3.0)

    def _accent_gradient_top(self, base: str | None = None) -> str:
        """主按钮渐变的浅色端，且保证文字在**这一端**也达标（UP-021）。

        主按钮底是 `lighten(accent) → accent` 的对角渐变，文字铺满整个按钮，
        所以浅端就是最坏情况。深色主题实测：白字对浅端只有 **4.00:1**——
        默认主题的保存按钮本身就不达标，光把 `color: white` 换成 token 修不掉。
        这里把浅端往回压到刚好 4.5:1；压过头就干脆退成纯色（不要为了渐变
        牺牲可读性），视觉上只是顶部略收一点亮度。
        """
        from core.utils.contrast import contrast_ratio, ensure_contrast, relative_luminance

        c = self.colors
        base = base or c.accent_primary
        top = self._lighten_color(base)
        fg = c.text_on_primary or "#ffffff"
        if contrast_ratio(fg, top) >= 4.5:
            return top
        fixed = ensure_contrast(top, (fg,), 4.5)
        # 判据必须看**亮度方向**而不是对比度：收敛后的浅端天然比实底对比度低，
        # 拿对比度比大小会让每个主题都误判成"压过头"，把渐变整个压平。
        # `_lighten_color` 保证 top 比 base 亮；若收敛后反而比 base 暗，
        # 渐变就上下颠倒了，这时才退成纯色。
        if relative_luminance(fixed) < relative_luminance(base):
            return base
        return fixed

    def _danger_bg(self) -> str:
        """危险按钮底色——压到文字能达标为止（暖橙/玫瑰主题白字只有 4.41:1）。

        `c.error` 各主题亮度不一，黑白两种字色都够不到 4.5 时，只能动底色。
        取黑白里更优的那个当目标，再把红色朝反方向推。
        """
        from core.utils.contrast import best_on_color, contrast_ratio, ensure_contrast

        bg = self.colors.error
        fg = best_on_color(bg)
        if contrast_ratio(fg, bg) >= 4.5:
            return bg
        return ensure_contrast(bg, (fg,), 4.5)

    def _lighten_color(self, hex_color, factor=1.2):
        """HSV 空间亮化颜色（降低饱和度、提高明度），用于渐变起始色"""
        from PySide6.QtGui import QColor
        c = QColor(hex_color)
        h, s, v, a = c.getHsv()
        c.setHsv(h, max(0, int(s * 0.85)), min(255, int(v * factor)), a)
        return c.name()

    def _darken_color(self, hex_color, factor=0.8):
        """HSV 空间暗化颜色（提高饱和度、降低明度），用于hover/pressed状态"""
        from PySide6.QtGui import QColor
        c = QColor(hex_color)
        h, s, v, a = c.getHsv()
        c.setHsv(h, min(255, int(s * 1.1)), max(0, int(v * factor)), a)
        return c.name()

    def _is_light_theme(self) -> bool:
        """判断主题是浅色还是深色 — 基于 bg_primary 的 HSL 亮度."""
        from PySide6.QtGui import QColor
        return QColor(self.colors.bg_primary).lightnessF() > 0.65

    def _chip_text(self, hex_color: str) -> str:
        """状态徽章文字色 — 浅色主题下自动加深, 保证对比度.

        修复 v2.1.1 浅色主题(浅色/暖橙/玫瑰/极简) 状态徽章 + 次级文字几乎不可读的问题:
        原 QSS 直接用 accent_primary/accent_warm 作为徽章字色, 在浅色背景上对比度 < 3:1.
        此处对浅色主题统一加深: 饱和度补强 + 明度降至 ~50%, 让徽章一眼可见.

        R4(UP-023 同批)补充：原实现对深色主题**原样返回**，于是 chip 的红字
        压在 `bg_card` 上只有 4.00~4.47:1，仍差一口气到 AA。现在两种主题都走
        一次对比度收敛兜底——浅色主题保留原有的"加深"手法（观感已调好），
        只在还不达标时再补推。
        """
        from core.utils.contrast import ensure_contrast

        adjusted = hex_color
        if self._is_light_theme():
            from PySide6.QtGui import QColor
            c = QColor(hex_color)
            h, s, v, a = c.getHsv()
            s_new = min(255, int(s * 1.15) + 30)
            v_new = max(0, int(v * 0.50))
            c.setHsv(h, s_new, v_new, a)
            adjusted = c.name()
        # chip 底色是 bg_card 上叠 28/255 的同色薄染，视觉上仍以 bg_card 为主，
        # 按 bg_card 收敛即可（薄染会让实际对比只增不减）。
        return ensure_contrast(adjusted, (self.colors.bg_card,))

    def _accent_text_on(self, *bg_hex: str) -> str:
        """accent 色**当文字用**时按底色收敛到 AA。

        R8a 补 ghostButton 时量到：直接拿 `accent_primary` 当文字压在 `bg_elevated`
        上，深色主题只有 2.50:1（暖橙 2.62、玫瑰 3.44、紫夜 3.64）—— 6/8 主题不过 AA。
        既有的 `actionButton:hover` 正是这么写的，那是历史欠账（另记 UP-076）。

        R8-W5 收口时把 `actionButton:hover` 也接上了这条收敛，于是本方法要能吃
        **多个**底色：hover 底是 `bg_tertiary → bg_elevated` 的渐变，只按其中一端
        收敛会在另一端翻车。传多个时 `ensure_contrast` 会对所有底色同时达标。
        """
        from core.utils.contrast import ensure_contrast

        return ensure_contrast(self.colors.accent_primary, bg_hex)

    @staticmethod
    def _blend_hex(fg: str, alpha: int, bg: str) -> str:
        """把 fg 以 alpha(0-255) 叠在 bg 上，返回合成色。

        QSS 里的 rgba() 底色最终会和它下面那层混合，算对比度必须用合成结果——
        直接拿 rgba 的原色去算会得出偏乐观的数字。
        """
        from core.utils.contrast import parse_hex, to_hex

        fr, fg_, fb = parse_hex(fg)
        br, bg_, bb = parse_hex(bg)
        k = max(0.0, min(1.0, alpha / 255.0))
        return to_hex((fr * k + br * (1 - k), fg_ * k + bg_ * (1 - k), fb * k + bb * (1 - k)))

    def _on_color(self, hex_color: str) -> str:
        """落在指定底色上的文字色——黑白里取对比度高的那个。

        用于品牌色/语义色之外的实底背景（如 dangerButton 的 `c.error`）。
        品牌色走 `c.text_on_primary`（已按渐变两端算过，见 _fill_contrast_defaults）。
        """
        from core.utils.contrast import best_on_color
        return best_on_color(hex_color)

    def _hex_to_rgba(self, hex_color, alpha):
        """将 hex 颜色转为 rgba() 字符串"""
        from PySide6.QtGui import QColor
        c = QColor(hex_color)
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"

    def generate_stylesheet(self) -> str:
        """生成完整的QSS样式表"""
        c = self.colors  # 简化引用
        spacing = self.ds.spacing
        radius = self.ds.radius
        font = self.ds.font_size
        height = self.ds.height
        button = self.ds.button
        input_spec = self.ds.input
        toggle = self.ds.toggle
        slider = self.ds.slider
        container = self.ds.container
        scrollbar = self.ds.scrollbar
        tooltip = self.ds.tooltip
        table = self.ds.table
        list_spec = self.ds.list

        nav_indicator_width = 3
        # 导航按钮内边距：v2.2 起紧凑化 (10→7) 让一屏可见更多导航项
        nav_padding_vertical = 7
        nav_padding_horizontal = 15
        nav_checked_padding_left = nav_padding_horizontal - nav_indicator_width

        focus_border_width = max(2, input_spec.text_border_width + 1)
        focus_padding_horizontal = max(
            0,
            input_spec.text_padding_horizontal - (focus_border_width - input_spec.text_border_width),
        )
        focus_padding_vertical = max(
            0,
            input_spec.text_padding_vertical - (focus_border_width - input_spec.text_border_width),
        )

        combo_focus_border_width = max(2, input_spec.combobox_border_width + 1)
        combo_focus_padding_horizontal = max(
            0,
            input_spec.combobox_padding_horizontal
            - (combo_focus_border_width - input_spec.combobox_border_width),
        )
        combo_focus_padding_vertical = max(
            0,
            input_spec.combobox_padding_vertical
            - (combo_focus_border_width - input_spec.combobox_border_width),
        )
        textarea_focus_padding = max(
            0,
            input_spec.textarea_padding - (focus_border_width - input_spec.textarea_border_width),
        )

        generic_button_padding_vertical = max(4, spacing.sm - 2)
        generic_button_padding_horizontal = max(12, spacing.lg - 2)
        spin_button_radius = max(3, radius.sm - 2)
        
        return f"""
            /* ========== 全局样式 ========== */
            QMainWindow, QDialog {{
                background-color: {c.bg_primary};
                color: {c.text_primary};
            }}

            * {{
                font-family: "Microsoft YaHei UI", "Segoe UI", Arial;
                outline: none;
            }}

            /* ========== 通用背景规则(优先级最低) ========== */
            /* 所有QWidget默认透明背景,继承父组件颜色 */
            QWidget {{
                background-color: transparent;
            }}

            /* ========== 内容区域样式(覆盖通用规则) ========== */
            /* v4: 主内容区用极微弱的垂直渐变（顶部稍亮带紫调，底部深）— 制造深度感 */
            QMainWindow::centralwidget,
            QMainWindow > QWidget,
            QStackedWidget,
            QStackedWidget#contentArea,
            QStackedWidget > QWidget,
            QStackedWidget#contentArea > QWidget,
            QWidget#rightShell,
            QWidget#contentPage {{
                background-color: {c.bg_primary} !important;
            }}

            /* 主内容容器加微妙的顶部渐变光感 */
            QStackedWidget#contentArea {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {self._hex_to_rgba(c.bg_tertiary, 80)},
                    stop:0.4 {c.bg_primary},
                    stop:1 {c.bg_primary}) !important;
            }}
            
            /* ========== 通用页面容器样式 ========== */
            QScrollArea {{
                background-color: {c.bg_primary};
                border: none;
            }}
            
            QScrollArea > QWidget > QWidget {{
                background-color: {c.bg_primary};
            }}
            
            /* ========== 侧边栏样式 ========== */
            QFrame#sidebar {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {c.bg_secondary}, stop:1 {c.bg_tertiary});
                border: none;
            }}

            QScrollArea#sidebarScroll {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {c.bg_secondary}, stop:1 {c.bg_tertiary});
                border: none;
            }}

            QScrollArea#sidebarScroll > QWidget > QWidget {{
                background: transparent;
            }}

            QWidget#sidebarBrand {{
                background: transparent;
                border-bottom: 1px solid {self._hex_to_rgba(c.border_secondary, 160)};
            }}

            QLabel#sidebarTitleLabel {{
                color: {c.text_primary};
                font-size: {font.xxl}px;
                font-weight: 700;
                background: transparent;
            }}

            QLabel#sidebarVersionLabel {{
                color: {c.text_muted};
                font-size: {font.sm}px;
                font-weight: 500;
                background: transparent;
            }}

            QWidget#sidebarFooter {{
                background: transparent;
                border-top: 1px solid {self._hex_to_rgba(c.border_secondary, 150)};
            }}
            
            /* ========== 导航按钮 ========== */
            QPushButton#navButton {{
                background-color: transparent;
                color: {c.text_secondary};
                border: none;
                text-align: left;
                padding: {nav_padding_vertical}px {nav_padding_horizontal}px;
                font-size: {font.md}px;
                border-radius: {radius.lg}px;
            }}

            QPushButton#navButton:hover {{
                background-color: {c.bg_tertiary};
                color: {c.text_primary};
            }}

            QPushButton#navButton:checked {{
                background-color: {c.bg_elevated};
                color: {c.accent_primary};
                font-weight: 600;
                border-left: {nav_indicator_width}px solid {c.accent_primary};
                padding-left: {nav_checked_padding_left}px;
            }}

            /* 导航分组头（可折叠）— v2.2 紧凑化 */
            QPushButton#navGroupHeader {{
                background-color: transparent;
                color: {c.text_muted};
                border: none;
                text-align: left;
                padding: {spacing.xs}px {spacing.sm + 2}px;
                margin-top: {spacing.xs}px;
                font-size: {font.xs}px;
                font-weight: 700;
                border-radius: {radius.sm}px;
            }}

            QPushButton#navGroupHeader:hover {{
                color: {c.text_secondary};
                background-color: transparent;
            }}

            /* ========== 紧凑模式 ========== */
            QWidget#compactHeader {{
                background-color: {self._hex_to_rgba(c.bg_secondary, 244)};
                border-bottom: 1px solid {c.border_secondary};
            }}

            QPushButton#hamburgerButton {{
                background-color: transparent;
                color: {c.text_primary};
                border: none;
                border-radius: {radius.md}px;
                font-size: 20px;
            }}

            QPushButton#hamburgerButton:hover {{
                background-color: {c.bg_tertiary};
            }}

            QPushButton#modeToggleButton {{
                background-color: transparent;
                color: {c.text_secondary};
                border: 1px solid {c.border_secondary};
                border-radius: {radius.md}px;
                font-size: 16px;
            }}

            QPushButton#modeToggleButton:hover {{
                background-color: {c.bg_tertiary};
                color: {c.text_primary};
                border-color: {c.border_primary};
            }}

            QLabel#compactTitle {{
                color: {c.text_primary};
                font-size: {font.xl}px;
                font-weight: 700;
                background: transparent;
            }}

            QLabel#overlayGroupHeader {{
                color: {c.text_muted};
                font-size: {font.xs}px;
                background: transparent;
            }}

            QFrame#sidebarOverlay {{
                background-color: {c.bg_secondary};
                border-right: 1px solid {c.border_primary};
            }}

            /* ========== 帮助面板 ========== */
            QFrame#helpCard {{
                background-color: {self._hex_to_rgba(c.accent_primary, 15)};
                border-left: 3px solid {c.accent_primary};
                border-radius: {radius.md}px;
            }}
            QLabel#helpCardTitle {{
                color: {c.accent_primary};
                background: transparent;
            }}
            QLabel#helpContent {{
                color: {c.text_secondary};
                font-size: 13px;
                line-height: 1.6;
                background: transparent;
            }}
            QScrollArea#helpScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollArea#helpScrollArea > QWidget > QWidget {{
                background: transparent;
            }}
            QPushButton#helpCloseButton {{
                background: transparent;
                color: {c.text_muted};
                border: none;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton#helpCloseButton:hover {{
                color: {c.text_primary};
            }}

            /* ========== 标签样式 ========== */
            QLabel {{
                color: {c.text_primary};
                font-size: {font.md}px;
                background: transparent;
            }}
            
            /* v4: 启用开关标签用 text_primary（不抢眼），仅由 toggle 本体显示状态 */
            QLabel#switchLabelOn {{
                color: {c.text_primary};
                font-weight: 500;
                background: transparent;
            }}

            QLabel#switchLabelOff {{
                color: {c.text_secondary};
                background: transparent;
            }}

            /* v4: 标题层级清晰，全部用 text_primary，不再用 accent 作标题色 */
            QLabel#titleLabel {{
                color: {c.text_primary};
                font-size: {font.h1}px;
                font-weight: 600;
                letter-spacing: -0.5px;
                background: transparent;
            }}

            QLabel#subtitleLabel {{
                color: {c.text_secondary};
                font-size: {font.lg}px;
                font-weight: 500;
                background: transparent;
            }}

            /* 卡片标题：v4 改用 text_primary 而非 accent，配合左侧装饰承担"分组"语义 */
            QLabel#cardTitle {{
                color: {c.text_primary};
                /* R7/D-02(UP-043): 走专用的 card_title 档(16px)。
                 * 之前这里是 font.xl(18px)，而 SettingsCard 的标题走的是另一条路
                 * (#statusLabel, 14px = 和正文同号，等于没有标题)。
                 * 现在两条路合并到本选择器，阶梯变成 28 → 16 → 14 → 13 → 12。 */
                font-size: {font.card_title}px;
                font-weight: 600;
                letter-spacing: -0.2px;
                background: transparent;
            }}

            QLabel#sectionTitle {{
                color: {c.text_primary};
                font-size: {font.lg}px;
                font-weight: 600;
                background: transparent;
            }}

            /* UP-053: 只给**文字**限宽,不动内容区宽度。
             * 实测 2200px 窗口下 hintLabel 单行拉到 1936px,远超舒适行长；
             * 而 R7 量过「给内容区限宽」会让 4 个页面从 3 列掉到 2 列——
             * 所以限的是这一个标签,卡片网格照旧铺满。 */
            QLabel#hintLabel {{
                color: {c.text_muted};
                font-size: {font.xs}px;
                background: transparent;
                max-width: {container.hint_max_width}px;
            }}

            QLabel#pageLeadLabel {{
                color: {c.text_secondary};
                font-size: {font.sm}px;
                font-weight: 400;
                background: transparent;
            }}

            /* valueLabel 保留 accent，因为它表示"突出数值"语义 */
            QLabel#valueLabel {{
                color: {c.accent_primary};
                font-size: {font.lg}px;
                font-weight: 600;
                background-color: transparent;
            }}

            QLabel#badgeLabel {{
                color: {c.text_secondary};
                font-size: {font.sm}px;
                font-weight: 600;
                padding: 4px 10px;
                border-radius: 10px;
                background-color: {self._hex_to_rgba(c.bg_elevated, 205)};
                border: 1px solid {self._hex_to_rgba(c.border_primary, 150)};
            }}

            QLabel#badgeLabel[tone="info"] {{
                color: {c.accent_primary};
                background-color: {self._hex_to_rgba(c.accent_primary, 26)};
                border: 1px solid {self._hex_to_rgba(c.accent_primary, 90)};
            }}

            QLabel#badgeLabel[tone="positive"] {{
                color: {c.success};
                background-color: {self._hex_to_rgba(c.success, 24)};
                border: 1px solid {self._hex_to_rgba(c.success, 90)};
            }}

            QLabel#badgeLabel[tone="warning"] {{
                color: {c.warning};
                background-color: {self._hex_to_rgba(c.warning, 24)};
                border: 1px solid {self._hex_to_rgba(c.warning, 90)};
            }}

            QLabel#badgeLabel[tone="danger"] {{
                color: {c.error};
                background-color: {self._hex_to_rgba(c.error, 24)};
                border: 1px solid {self._hex_to_rgba(c.error, 90)};
            }}
            
            QLabel#statusLabel {{
                color: {c.text_secondary};
                font-size: {font.md}px;
                font-weight: 600;
                background-color: transparent;
            }}

            /* ========== 音频状态胶囊 ========== */
            QFrame#audioStatusBar {{
                background-color: transparent;
                border: none;
                margin: 1px 0 3px 0;
            }}

            /* v5 Phase 6: audioStatusChip 去圣诞树效应
             * 策略:正常态(success/info)统一灰底,只用文字色标记语义;
             *      异常态(warning/danger)保持满色块,确保一眼可见. */
            QLabel#audioStatusChip {{
                color: {c.text_primary};
                background-color: {c.bg_card};
                border: 1px solid {c.border_secondary};
                border-radius: 13px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: 600;
                min-height: 28px;
            }}

            /* 成功/信息/positive: Phase1-1.5 进一步去圣诞树——
             * 正常态完全中性（灰字灰边），语义色只留给 warn/danger，
             * 让"有问题的 chip"成为整行唯一会跳色的东西。
             * 对标修缮：浅色主题下中性边框加深一档，避免 chip "若隐若现"。 */
            QLabel#audioStatusChip[level="success"],
            QLabel#audioStatusChip[level="positive"],
            QLabel#audioStatusChip[level="info"] {{
                color: {c.text_secondary};
                background-color: {c.bg_card};
                border: 1px solid {self._hex_to_rgba(c.text_tertiary, 120) if self._is_light_theme() else c.border_secondary};
            }}

            /* 警告/错误：保持高对比度，让异常一眼可见 */
            QLabel#audioStatusChip[level="warn"],
            QLabel#audioStatusChip[level="warning"] {{
                color: {self._chip_text(c.accent_warm)};
                background-color: {self._hex_to_rgba(c.accent_warm, 28)};
                border: 1px solid {self._hex_to_rgba(self._chip_text(c.accent_warm), 120)};
            }}

            /* UP-050: StatusChip 声明了 error / neutral 两个 level,但 QSS 里原本
             * 只有 danger —— 于是"GSI・异常"这类 chip 静默掉回基础规则,
             * 渲染成和正常态一模一样的中性灰,异常反而看不出来。补齐两态。 */
            QLabel#audioStatusChip[level="neutral"] {{
                color: {c.text_muted};
                background-color: {c.bg_card};
                border: 1px solid {c.border_secondary};
            }}

            QLabel#audioStatusChip[level="danger"],
            QLabel#audioStatusChip[level="error"] {{
                color: {self._chip_text(c.error)};
                background-color: {self._hex_to_rgba(c.error, 28)};
                border: 1px solid {self._hex_to_rgba(self._chip_text(c.error), 120)};
            }}
            
            /* ========== 卡片/容器样式 ========== */
            /* v5: bg_card 比 bg_secondary 提亮一档,让阴影对比看得见 */
            QFrame#card {{
                background-color: {c.bg_card};
                border-radius: {container.card_border_radius}px;
                border: {container.card_border_width}px solid {c.border_secondary};
                /* R7/D-03(UP-044): 常态**不再有色条**。但这里绝不能留 transparent——
                 * Qt 画圆角边框是描边(pen 居中)，透明描边会露出约 1.5px 的页面底色，
                 * 28 页每张卡的左缘都会出现一道缝。染成和其余三边同色即可，
                 * 观感是"左边缘略厚"而不是"有根条"。
                 * 保住 3px 占位还有个硬理由：宽度改成 1px 时卡内子控件 x 会从 17 变 15，
                 * warn/danger 色条出现/消失时内容会左右跳 2px。 */
                border-left: 3px solid {c.border_secondary};
            }}

            QFrame#card:hover {{
                background-color: {c.bg_card_hover};
                border-color: {c.border_primary};
            }}

            /* R7/D-03(UP-044): 语义色条只留 warn/danger，常态无色条。
             * 实测依据：全仓 78 处 SettingsCard 调用里**只有 1 处**显式传过 semantic，
             * 其余全走默认 "config" —— 也就是说今天每一张卡都挂着同一根紫条，
             * 它没有在区分任何东西，只是装饰。
             * 与 04 §三记录的 audioStatusChip「正常态统一中性灰、只让 warn/danger 跳色」
             * 是同一套状态语言：色条留给真正需要注意的卡。
             * VALID_SEMANTICS 六个值全部保留（它同时是 icon_role 推导表的 key，
             * 删值会让历史调用点直接抛 ValueError），只是常态四个不再画条。
             *
             * ⚠ 这两条必须排在下面的 [searchHit] 之后：三者特异度完全相同
             * （1 id + 1 属性 + 1 类型），QSS 同特异度后来者胜。排在前面的话，
             * 搜索命中那 1.6 秒里 warn/danger 的橙/红条会被高亮的 border-color
             * 简写刷成品牌紫，状态语言被临时抹掉。 */

            /* R4/UP-024: 搜索跳转定位高亮。
             * 原实现给目标装发光 QGraphicsDropShadowEffect，会把卡片自己的
             * elevation 阴影顶掉并析构，1.6s 后置 None —— 阴影永久消失，
             * 且组件里残留的悬垂指针让之后每次 hover 抛 RuntimeError。
             * 改成纯 QSS 属性态：只换颜色不换边框宽度，所以不会引起重排；
             * 强/弱两档由定时器切换，观感是渐隐但零动画开销。 */
            QWidget[searchHit="true"] {{
                background-color: {self._hex_to_rgba(c.accent_primary, 42)};
                border-radius: {radius.md}px;
            }}
            QWidget[searchHit="fade"] {{
                background-color: {self._hex_to_rgba(c.accent_primary, 18)};
                border-radius: {radius.md}px;
            }}
            QFrame#card[searchHit="true"] {{
                background-color: {self._hex_to_rgba(c.accent_primary, 42)};
                border-color: {c.accent_primary};
            }}
            QFrame#card[searchHit="fade"] {{
                background-color: {self._hex_to_rgba(c.accent_primary, 18)};
                border-color: {self._hex_to_rgba(c.accent_primary, 120)};
            }}

            /* R7/D-03(UP-044): warn/danger 色条。**必须排在 [searchHit] 之后**——
             * 三者特异度完全相同（1 id + 1 属性 + 1 类型），QSS 同特异度后来者胜。
             * 排在前面的话，搜索命中的那 1.6 秒里 border-color 简写会把橙/红条
             * 一起刷成品牌紫，状态语言被临时抹掉。 */
            QFrame#card[semantic="warning"] {{
                border-left: 3px solid {c.accent_warm};
            }}
            QFrame#card[semantic="danger"] {{
                border-left: 3px solid {c.error};
            }}

            QFrame#pageActionBar {{
                background-color: {self._hex_to_rgba(c.bg_secondary, 252)};
                border-top: 1px solid {c.border_secondary};
                border-left: 1px solid {c.border_secondary};
                border-right: 1px solid {c.border_secondary};
                border-bottom: 0;
                border-top-left-radius: {container.card_border_radius}px;
                border-top-right-radius: {container.card_border_radius}px;
            }}

            QFrame#pageActionBar QLabel#hintLabel {{
                color: {c.text_secondary};
                font-size: {font.sm}px;
                /* 动作条是横向单行状态位,限宽会让它换行、把常驻动作条顶高,
                 * 所以要把上面那条 #hintLabel 的限宽解除掉。
                 * ⚠ 必须写成一个**合法长度**:Qt QSS 的 max-width 不认 CSS 的
                 * `none`,写 none 会让样式解析出错,实测会把 special_sound 两个
                 * 页签顶出可视区 46px/39px——一个看不出来的写错值,后果落在
                 * 完全无关的另一个页面上。 */
                max-width: 16777215px;
            }}
            
            QFrame#section {{
                background-color: transparent;
                border: none;
                border-bottom: 1px solid {c.border_secondary};
                padding-bottom: {spacing.md}px;
                margin-bottom: {spacing.md}px;
            }}
            
            QFrame#group {{
                background-color: {c.bg_secondary};
                border-radius: {container.groupbox_border_radius}px;
                border: {container.groupbox_border_width}px solid {c.border_secondary};
                padding: {container.groupbox_padding}px;
            }}
            
            QFrame#infoBox {{
                background-color: rgba(74, 158, 255, 0.1);
                border-left: 3px solid {c.accent_primary};
                border-radius: {radius.md}px;
                padding: {spacing.md}px {spacing.lg}px;
            }}
            
            QFrame#warningBox {{
                background-color: rgba(255, 193, 7, 0.1);
                border-left: 3px solid {c.warning};
                border-radius: {radius.md}px;
                padding: {spacing.md}px {spacing.lg}px;
            }}
            
            /* ========== 按钮样式 ========== */
            QPushButton#primaryButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {self._accent_gradient_top()}, stop:1 {c.accent_primary});
                color: {c.text_on_primary};
                border: none;
                border-radius: {button.primary_border_radius}px;
                padding: {button.primary_padding_vertical}px {button.primary_padding_horizontal}px;
                font-weight: 600;
                font-size: {button.primary_font_size}px;
                min-height: {button.primary_height}px;
                min-width: {button.primary_min_width}px;
            }}
            
            QPushButton#primaryButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {self._accent_gradient_top(c.accent_hover)}, stop:1 {c.accent_hover});
            }}

            QPushButton#primaryButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {self._accent_gradient_top(c.accent_pressed)}, stop:1 {c.accent_pressed});
            }}

            /* v5 Phase 9: focus ring — 键盘 Tab 切换可见 */
            QPushButton#primaryButton:focus {{
                border: 2px solid {c.accent_secondary};
                padding: {max(0, button.primary_padding_vertical - 2)}px {max(0, button.primary_padding_horizontal - 2)}px;
            }}

            QPushButton#primaryButton:disabled {{
                background-color: {c.accent_disabled};
                color: {c.text_disabled};
            }}
            
            QPushButton#secondaryButton {{
                background-color: transparent;
                color: {c.text_primary};
                border: {button.secondary_border_width}px solid {c.border_primary};
                border-radius: {button.secondary_border_radius}px;
                padding: {button.secondary_padding_vertical}px {button.secondary_padding_horizontal}px;
                font-size: {button.secondary_font_size}px;
                min-height: {button.secondary_height}px;
                min-width: {button.primary_min_width}px;
            }}
            
            QPushButton#secondaryButton:hover {{
                background-color: {c.bg_tertiary};
                border-color: {c.accent_primary};
            }}

            QPushButton#secondaryButton:pressed {{
                background-color: {c.bg_elevated};
            }}

            /* v5 Phase 9: focus ring */
            QPushButton#secondaryButton:focus {{
                border: 2px solid {c.accent_primary};
                padding: {max(0, button.secondary_padding_vertical - 1)}px {max(0, button.secondary_padding_horizontal - 1)}px;
            }}

            /* 试听分裂按钮(QToolButton)复用 secondary 外观：
               2.2.1 引入 QToolButton 时漏了这段，导致按钮回退默认样式变黑 */
            QToolButton#secondaryButton {{
                background-color: transparent;
                color: {c.text_primary};
                border: {button.secondary_border_width}px solid {c.border_primary};
                border-radius: {button.secondary_border_radius}px;
                padding: {button.secondary_padding_vertical}px {button.secondary_padding_horizontal}px;
                font-size: {button.secondary_font_size}px;
                min-height: {button.secondary_height}px;
            }}

            QToolButton#secondaryButton:hover {{
                background-color: {c.bg_tertiary};
                border-color: {c.accent_primary};
            }}

            QToolButton#secondaryButton:pressed {{
                background-color: {c.bg_elevated};
            }}

            QToolButton#secondaryButton::menu-button {{
                border: none;
                border-left: 1px solid {c.border_primary};
                width: 16px;
            }}

            QPushButton#iconButton {{
                background-color: transparent;
                border: none;
                border-radius: {button.icon_border_radius}px;
                padding: {spacing.sm}px;
                min-width: {button.icon_size}px;
                min-height: {button.icon_size}px;
            }}
            
            QPushButton#iconButton:hover {{
                background-color: {c.bg_tertiary};
            }}
            
            /* 操作按钮（测试、预览等） */
            QPushButton#actionButton {{
                background-color: {c.bg_elevated};
                color: {c.text_primary};
                border: 1px solid {c.border_primary};
                border-radius: {button.action_border_radius}px;
                padding: {button.action_padding_vertical}px {button.action_padding_horizontal}px;
                font-size: {button.action_font_size}px;
                min-height: {button.action_height}px;
                font-weight: 500;
            }}
            
            /* UP-076: 字色按渐变**两端**收敛到 AA。原先直接用 accent_primary,
             * 实测最差端只有 dark 2.50 / warm 2.28 / rose 2.99 / light 2.94 /
             * purple 3.64 —— 5/9 主题不过 AA,而 actionButton 是全站最常见的按钮。
             * border-color 属非文字对比(1.4.11),归 UP-063,本轮按决策不动。 */
            QPushButton#actionButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {c.bg_tertiary}, stop:1 {c.bg_elevated});
                border-color: {c.accent_primary};
                color: {self._accent_text_on(c.bg_tertiary, c.bg_elevated)};
            }}

            QPushButton#actionButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {c.accent_primary}, stop:1 {self._accent_gradient_top()});
                color: {c.text_on_primary};
                border-color: {c.accent_primary};
            }}

            /* v5 Phase 9: focus ring */
            QPushButton#actionButton:focus {{
                border: 2px solid {c.accent_primary};
                padding: {max(0, button.action_padding_vertical - 1)}px {max(0, button.action_padding_horizontal - 1)}px;
            }}

            /* v5 Phase 9: 通用 QPushButton focus(navButton/iconButton 等无显式 :focus 的也走这) */
            QPushButton:focus {{
                outline: none;
            }}

            /* UP-073: `AppButton.ghost()` 从加进来那天起就产出 objectName=ghostButton,
             * 而 QSS 里一条对应规则都没有(源码注释写着"Phase 4 时加",没加成)——
             * 于是它是"5+1 语义按钮"里唯一一个完全没样式的。测试只断言 objectName
             * 相等，所以一直是绿的。这里补齐：无边框无底、仅文字，hover 才浮出底色。 */
            QPushButton#ghostButton {{
                background-color: transparent;
                color: {c.text_secondary};
                border: 1px solid transparent;
                border-radius: {button.action_border_radius}px;
                padding: {button.action_padding_vertical}px {button.action_padding_horizontal}px;
                font-size: {button.action_font_size}px;
                min-height: {button.action_height}px;
                font-weight: 500;
            }}

            QPushButton#ghostButton:hover {{
                background-color: {c.bg_tertiary};
                color: {c.text_primary};
            }}

            QPushButton#ghostButton:pressed {{
                background-color: {c.bg_elevated};
                color: {self._accent_text_on(c.bg_elevated)};
            }}

            QPushButton#ghostButton:focus {{
                border: 2px solid {c.accent_primary};
                padding: {max(0, button.action_padding_vertical - 1)}px {max(0, button.action_padding_horizontal - 1)}px;
            }}

            QPushButton#ghostButton:disabled {{
                color: {c.text_on_disabled};
                background-color: transparent;
            }}
            
            /* UP-017: 页内锚点 chip。不复用 secondaryButton 是因为那条规则带
             * min-width:80——10 个 2~4 字的 chip 各占 80px 会把页面最小宽度顶到
             * 1284px，在禁了横向滚动的页面上直接造成"控件永久够不到"。
             * 这里按内容自适应，配合 FlowLayout 在窄窗口下换行。 */
            QPushButton#anchorChip {{
                background-color: transparent;
                color: {c.text_secondary};
                border: 1px solid {c.border_primary};
                border-radius: {radius.sm}px;
                padding: 2px {spacing.sm}px;
                font-size: {font.xs}px;
                min-width: 0px;
            }}

            QPushButton#anchorChip:hover {{
                background-color: {c.bg_tertiary};
                border-color: {c.accent_primary};
                color: {c.text_primary};
            }}

            QPushButton#anchorChip:pressed {{
                background-color: {c.bg_elevated};
            }}

            /* 危险操作按钮 */
            QPushButton#dangerButton {{
                background-color: {self._danger_bg()};
                color: {self._on_color(self._danger_bg())};
                border: none;
                border-radius: {button.danger_border_radius}px;
                padding: {button.danger_padding_vertical}px {button.danger_padding_horizontal}px;
                font-weight: 600;
                font-size: {button.danger_font_size}px;
                min-height: {button.danger_height}px;
                min-width: {button.primary_min_width}px;
            }}

            QPushButton#dangerButton:hover {{
                background-color: {self._darken_color(c.error, 0.85)};
            }}

            QPushButton#dangerButton:pressed {{
                background-color: {self._darken_color(c.error, 0.7)};
            }}
            
            /* 统一按钮文字显示修复 */
            QPushButton {{
                color: {c.text_primary};
                background-color: {c.bg_tertiary};
                border: 1px solid {c.border_primary};
                border-radius: {button.secondary_border_radius}px;
                text-align: center;
                padding: {generic_button_padding_vertical}px {generic_button_padding_horizontal}px;
                font-size: {font.md}px;
                min-height: {height.sm}px;
            }}

            QPushButton:hover {{
                background-color: {c.bg_elevated};
                border-color: {c.accent_primary};
            }}

            QPushButton:pressed {{
                background-color: {c.bg_secondary};
            }}
            
            /* ========== 复选框样式 ========== */
            QCheckBox {{
                color: {c.text_primary};
                font-size: {font.md}px;
                spacing: {spacing.md - 2}px;
            }}
            
            QCheckBox::indicator {{
                width: {toggle.checkbox_size}px;
                height: {toggle.checkbox_size}px;
                border-radius: {toggle.checkbox_border_radius}px;
                border: {toggle.checkbox_border_width}px solid {c.border_primary};
                background-color: transparent;
            }}
            
            QCheckBox::indicator:checked {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {self._lighten_color(c.accent_primary)}, stop:1 {c.accent_primary});
                border-color: {c.accent_primary};
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMiIgaGVpZ2h0PSIxMiIgdmlld0JveD0iMCAwIDEyIDEyIj48cGF0aCBmaWxsPSJ3aGl0ZSIgZD0iTTEwLjI4IDIuMjhsLTYgNi0yLjU5LTIuNTlhMSAxIDAgMDAtMS40MSAxLjQxbDMuMyAzLjNhMSAxIDAgMDAxLjQxIDBsNi43LTYuN2ExIDEgMCAwMC0xLjQxLTEuNDJ6Ii8+PC9zdmc+);
            }}
            
            QCheckBox::indicator:hover {{
                border-color: {c.accent_primary};
            }}
            
            QCheckBox::indicator:disabled {{
                border-color: {c.border_secondary};
                background-color: {c.bg_secondary};
            }}
            
            /* ========== 单选框样式 ========== */
            QRadioButton {{
                color: {c.text_primary};
                font-size: {font.md}px;
                spacing: {spacing.sm}px;
            }}
            
            QRadioButton::indicator {{
                width: {toggle.radio_size}px;
                height: {toggle.radio_size}px;
                border-radius: {toggle.radio_size // 2}px;
                border: {toggle.radio_border_width}px solid {c.accent_primary};
                background-color: transparent;
            }}
            
            QRadioButton::indicator:checked {{
                background-color: white;
                border: {max(4, toggle.radio_border_width + 3)}px solid {c.accent_primary};
            }}
            
            QRadioButton::indicator:hover {{
                border-color: {c.accent_hover};
            }}
            
            /* ========== 关于页面专用样式 ========== */
            QLabel#logoTitle {{
                color: {c.accent_primary};
            }}
            
            QLabel#versionText {{
                color: {c.text_secondary};
            }}
            
            QLabel#infoLabel {{
                padding: 15px;
                background-color: {c.bg_secondary};
                border-radius: {container.groupbox_border_radius}px;
            }}
            
            /* ========== 列表控件样式 ========== */
            QListWidget, QTableWidget, QTreeWidget, QTableView, QTreeView {{
                background-color: {c.bg_secondary};
                color: {c.text_primary};
                border: 1px solid {c.border_secondary};
                border-radius: {container.groupbox_border_radius}px;
                padding: {spacing.xs + 1}px;
                outline: none;
            }}

            QTableWidget, QTableView {{
                gridline-color: {c.border_secondary};
            }}

            QHeaderView::section {{
                background-color: {c.bg_tertiary};
                color: {c.text_primary};
                border: 1px solid {c.border_secondary};
                border-left: none;
                border-top: none;
                padding: {table.cell_padding_vertical}px {max(10, table.cell_padding_horizontal - 2)}px;
                font-weight: 600;
            }}

            QHeaderView::section:first {{
                border-left: 1px solid {c.border_secondary};
            }}

            QTableCornerButton::section {{
                background-color: {c.bg_tertiary};
                border: 1px solid {c.border_secondary};
            }}
            
            QListWidget::item, QTableWidget::item, QTreeWidget::item, QTableView::item, QTreeView::item {{
                padding: {list_spec.item_padding_vertical}px {list_spec.item_padding_horizontal}px;
                border-radius: {list_spec.item_border_radius}px;
                color: {c.text_primary};
            }}
            
            QListWidget::item:selected, QTableWidget::item:selected, QTreeWidget::item:selected, QTableView::item:selected, QTreeView::item:selected {{
                background-color: {c.accent_primary};
                color: {c.text_on_primary};
            }}
            
            QListWidget::item:hover, QTableWidget::item:hover, QTreeWidget::item:hover, QTableView::item:hover, QTreeView::item:hover {{
                background-color: {c.bg_tertiary};
            }}
            
            /* ========== 滑块样式 ========== */
            QSlider::groove:horizontal {{
                height: {slider.horizontal_height}px;
                background: {c.bg_elevated};
                border-radius: {slider.horizontal_border_radius}px;
            }}
            
            QSlider::sub-page:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {self._lighten_color(c.accent_primary)}, stop:1 {c.accent_primary});
                border-radius: {slider.horizontal_border_radius}px;
            }}
            
            QSlider::handle:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {self._lighten_color(c.accent_primary)}, stop:1 {c.accent_primary});
                width: {slider.horizontal_handle_size}px;
                height: {slider.horizontal_handle_size}px;
                margin: {-((slider.horizontal_handle_size - slider.horizontal_height) // 2)}px 0;
                border-radius: {slider.horizontal_handle_size // 2}px;
                border: 2px solid white;
            }}
            
            QSlider::handle:horizontal:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {self._accent_gradient_top(c.accent_hover)}, stop:1 {c.accent_hover});
                width: {slider.horizontal_handle_size + 2}px;
                height: {slider.horizontal_handle_size + 2}px;
                margin: {-(((slider.horizontal_handle_size + 2) - slider.horizontal_height) // 2)}px 0;
            }}
            
            QSlider::groove:vertical {{
                width: {slider.vertical_width}px;
                background: {c.bg_elevated};
                border-radius: {slider.vertical_border_radius}px;
            }}
            
            QSlider::sub-page:vertical {{
                background: {c.accent_primary};
                border-radius: {slider.vertical_border_radius}px;
            }}
            
            QSlider::handle:vertical {{
                background: {c.accent_primary};
                width: {slider.vertical_handle_size}px;
                height: {slider.vertical_handle_size}px;
                margin: 0 {-((slider.vertical_handle_size - slider.vertical_width) // 2)}px;
                border-radius: {slider.vertical_handle_size // 2}px;
            }}
            
            /* ========== 下拉框样式 ========== */
            QComboBox {{
                background-color: {c.bg_secondary};
                color: {c.text_primary};
                border: {input_spec.combobox_border_width}px solid {c.border_primary};
                border-radius: {input_spec.combobox_border_radius}px;
                padding: {input_spec.combobox_padding_vertical}px {input_spec.combobox_padding_horizontal}px;
                font-size: {input_spec.combobox_font_size}px;
                min-height: {input_spec.combobox_height}px;
            }}
            
            QComboBox:hover {{
                border-color: {c.accent_primary};
            }}
            
            QComboBox:focus {{
                border: {combo_focus_border_width}px solid {c.accent_primary};
                padding: {combo_focus_padding_vertical}px {combo_focus_padding_horizontal}px;
            }}
            
            QComboBox::drop-down {{
                border: none;
                width: {input_spec.combobox_arrow_width + 8}px;
                padding-right: 8px;
            }}
            
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid {c.accent_primary};
                width: 0;
                height: 0;
            }}
            
            QComboBox QAbstractItemView {{
                background-color: {c.bg_secondary};
                color: {c.text_primary};
                selection-background-color: {c.accent_primary};
                selection-color: {c.text_on_primary};
                border: 1px solid {c.border_primary};
                border-radius: {input_spec.combobox_border_radius}px;
                padding: 6px;
                outline: none;
            }}
            
            QComboBox QAbstractItemView::item {{
                padding: 10px 14px;
                border-radius: 6px;
                color: {c.text_primary};
            }}
            
            QComboBox QAbstractItemView::item:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {c.bg_tertiary}, stop:1 transparent);
                color: {c.text_primary};
            }}
            
            QComboBox QAbstractItemView::item:selected {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {c.accent_primary}, stop:1 {self._accent_gradient_top()});
                color: {c.text_on_primary};
            }}
            
            /* ========== 输入框样式 ========== */
            QLineEdit, QSpinBox, QDoubleSpinBox {{
                background-color: {c.bg_secondary};
                color: {c.text_primary};
                border: {input_spec.text_border_width}px solid {c.border_primary};
                border-radius: {input_spec.text_border_radius}px;
                padding: {input_spec.text_padding_vertical}px {input_spec.text_padding_horizontal}px;
                font-size: {input_spec.text_font_size}px;
                min-height: {input_spec.text_height}px;
                selection-background-color: {c.accent_primary};
                selection-color: {c.text_on_primary};
            }}
            
            QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
                border-color: {c.accent_primary};
            }}
            
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border: {focus_border_width}px solid {c.accent_primary};
                padding: {focus_padding_vertical}px {focus_padding_horizontal}px;
            }}
            
            QSpinBox::up-button, QDoubleSpinBox::up-button {{
                background-color: {c.bg_elevated};
                border-radius: {spin_button_radius}px;
                width: 16px;
            }}
            
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {{
                background-color: {c.bg_tertiary};
            }}
            
            QSpinBox::down-button, QDoubleSpinBox::down-button {{
                background-color: {c.bg_elevated};
                border-radius: {spin_button_radius}px;
                width: 16px;
            }}
            
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
                background-color: {c.bg_tertiary};
            }}
            
            /* ========== 滚动条样式 ========== */
            QScrollBar:vertical {{
                background: transparent;
                width: {scrollbar.width}px;
                border-radius: {scrollbar.border_radius}px;
                margin: {scrollbar.margin + 2}px {scrollbar.margin}px;
            }}

            QScrollBar::handle:vertical {{
                background: {self._hex_to_rgba(c.scrollbar_handle, 60)};
                border-radius: {scrollbar.border_radius}px;
                min-height: {scrollbar.handle_min_height}px;
            }}

            QScrollBar::handle:vertical:hover {{
                background: {c.scrollbar_hover};
            }}

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}

            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}

            QScrollBar:horizontal {{
                background: transparent;
                height: {scrollbar.width}px;
                border-radius: {scrollbar.border_radius}px;
                margin: {scrollbar.margin}px {scrollbar.margin + 2}px;
            }}

            QScrollBar::handle:horizontal {{
                background: {self._hex_to_rgba(c.scrollbar_handle, 60)};
                border-radius: {scrollbar.border_radius}px;
                min-width: {scrollbar.handle_min_height}px;
            }}

            QScrollBar::handle:horizontal:hover {{
                background: {c.scrollbar_hover};
            }}
            
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
            
            /* ========== 标签页样式（v4: 胶囊式更现代）========== */
            QTabWidget::pane {{
                border: none;
                background-color: transparent;
                top: 0px;
            }}

            QTabBar {{
                qproperty-drawBase: 0;  /* 去除下方分隔线 */
            }}

            QTabBar::tab {{
                background-color: transparent;
                color: {c.text_muted};
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 8px 16px;
                margin: 2px 3px;
                font-size: {font.sm}px;
                font-weight: 500;
                min-height: 22px;
            }}

            QTabBar::tab:hover {{
                color: {c.text_primary};
                background-color: {self._hex_to_rgba(c.bg_elevated, 120)};
            }}

            QTabBar::tab:selected {{
                color: {c.text_primary};
                background-color: {self._hex_to_rgba(c.accent_primary, 36)};
                border: 1px solid {self._hex_to_rgba(c.accent_primary, 90)};
                font-weight: 600;
            }}
            
            /* ========== 对话框样式 ========== */
            QDialog {{
                background-color: {c.bg_primary};
                color: {c.text_primary};
            }}
            
            /* ========== QMessageBox样式 ========== */
            QMessageBox {{
                background-color: {c.bg_primary};
                color: {c.text_primary};
            }}
            
            QMessageBox QLabel {{
                color: {c.text_primary};
                font-size: 14px;
            }}
            
            QMessageBox QPushButton {{
                background-color: {c.accent_primary};
                color: {c.text_on_primary};
                border: none;
                border-radius: {button.primary_border_radius}px;
                padding: {button.primary_padding_vertical}px {button.primary_padding_horizontal}px;
                font-size: {button.primary_font_size}px;
                min-width: {button.primary_min_width}px;
                min-height: {button.primary_height}px;
            }}
            
            QMessageBox QPushButton:hover {{
                background-color: {c.accent_hover};
            }}
            
            QMessageBox QPushButton:pressed {{
                background-color: {c.accent_pressed};
            }}
            
            /* ========== 文本编辑器样式 ========== */
            QTextEdit, QPlainTextEdit {{
                background-color: {c.bg_secondary};
                color: {c.text_primary};
                border: {input_spec.textarea_border_width}px solid {c.border_secondary};
                border-radius: {input_spec.textarea_border_radius}px;
                padding: {input_spec.textarea_padding}px;
                font-size: {input_spec.textarea_font_size}px;
                selection-background-color: {c.accent_primary};
                selection-color: {c.text_on_primary};
            }}
            
            QTextEdit:focus, QPlainTextEdit:focus {{
                border: {focus_border_width}px solid {c.border_focus};
                padding: {textarea_focus_padding}px;
            }}
            
            /* ========== 进度条样式 ========== */
            QProgressBar {{
                background-color: {c.bg_secondary};
                border: none;
                border-radius: {slider.progressbar_border_radius}px;
                height: {slider.progressbar_height}px;
                text-align: center;
            }}

            QProgressBar::chunk {{
                background-color: {c.accent_primary};
                border-radius: {slider.progressbar_border_radius}px;
            }}
            
            /* ========== 分组框样式 ========== */
            QGroupBox {{
                background-color: {c.bg_secondary};
                border: {container.groupbox_border_width}px solid {c.border_secondary};
                border-radius: {container.groupbox_border_radius}px;
                margin-top: {spacing.xl - 4}px;
                padding: {container.groupbox_padding}px;
                padding-top: {container.groupbox_padding + 12}px;
                font-weight: 600;
                color: {c.text_primary};
            }}

            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: {container.groupbox_padding}px;
                top: 6px;
                padding: 0 {container.groupbox_title_padding}px;
                background-color: {c.bg_secondary};
                color: {c.accent_primary};
                font-size: {font.lg}px;
            }}
            
            /* ========== 工具提示样式 ========== */
            QToolTip {{
                background-color: {c.bg_elevated};
                color: {c.text_primary};
                border: 1px solid {c.border_primary};
                border-radius: {tooltip.border_radius}px;
                padding: {tooltip.padding_vertical}px {tooltip.padding_horizontal}px;
                font-size: {tooltip.font_size}px;
            }}
            
            /* ========== 菜单样式 ========== */
            QMenu {{
                background-color: {c.bg_secondary};
                border: 1px solid {c.border_primary};
                border-radius: {radius.md}px;
                padding: {spacing.xs}px;
            }}
            
            QMenu::item {{
                background-color: transparent;
                color: {c.text_primary};
                padding: {spacing.sm}px {spacing.xl}px {spacing.sm}px {spacing.md}px;
                border-radius: {radius.sm}px;
            }}
            
            QMenu::item:selected {{
                background-color: {c.accent_primary};
                color: {c.text_on_primary};
            }}
            
            QMenu::separator {{
                height: 1px;
                background: {c.border_secondary};
                margin: 4px 8px;
            }}
            
            /* ========== 音乐控制栏样式 - 紧凑卡片化分组 ========== */
            QWidget#musicControlBar {{
                background-color: {c.bg_secondary};
                border-top: none;
            }}

            QWidget#musicControlBar > QWidget,
            QWidget#musicControlBar QWidget#musicFullControls,
            QWidget#musicControlBar QWidget#musicProgressRow,
            QWidget#musicControlBar QWidget#musicControlsRow {{
                background: transparent;
                border: none;
            }}

            QWidget#musicControlBar QWidget#miniBar {{
                background: transparent;
                border: none;
                border-bottom: 1px solid {self._hex_to_rgba(c.border_secondary, 96)};
            }}

            QWidget#musicControlBar QLabel {{
                color: {c.text_primary};
                background: transparent;
            }}

            QWidget#musicControlBar QLabel#musicMiniTrackLabel {{
                color: {c.text_secondary};
                font-size: 12px;
                font-weight: 500;
            }}

            QWidget#musicControlBar QLabel#musicTrackTitle {{
                color: {c.text_primary};
                font-size: 14px;
                font-weight: 700;
            }}

            QWidget#musicControlBar QLabel#musicTrackArtist {{
                color: {c.text_secondary};
                font-size: 12px;
            }}

            QWidget#musicControlBar QLabel#musicTimeLabel {{
                color: {c.text_muted};
                font-size: 12px;
                font-weight: 500;
            }}
            
            QWidget#musicControlBar QPushButton {{
                background-color: transparent;
                color: {c.text_primary};
                border: none;
                border-radius: 8px;
                padding: 0px;
                outline: none;
            }}
            
            QWidget#musicControlBar QPushButton:hover {{
                background-color: {self._hex_to_rgba(c.bg_tertiary, 210)};
                color: {c.accent_primary};
            }}
            
            QWidget#musicControlBar QPushButton:pressed {{
                background-color: {self._hex_to_rgba(c.bg_elevated, 230)};
            }}
            
            QWidget#musicControlBar QPushButton#primaryButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {self._accent_gradient_top()}, stop:1 {c.accent_primary});
                color: {c.text_on_primary};
                border: none;
                border-radius: 10px;
                padding: 0px;
                min-width: 44px;
            }}
            
            QWidget#musicControlBar QPushButton#primaryButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {self._accent_gradient_top(c.accent_hover)}, stop:1 {c.accent_hover});
            }}
            
            QWidget#musicControlBar QPushButton#primaryButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {self._accent_gradient_top(c.accent_pressed)}, stop:1 {c.accent_pressed});
            }}
            
            QWidget#musicControlBar QWidget#musicInfoButton {{
                background-color: {c.bg_elevated};
                border: 1px solid {self._hex_to_rgba(c.border_primary, 140)};
                border-radius: 12px;
                padding: 0px;
            }}

            QWidget#musicControlBar QWidget#musicInfoButton[hovered="true"] {{
                background-color: {self._lighten_color(c.bg_elevated, 1.08)};
                border: 1px solid {self._hex_to_rgba(c.accent_primary, 110)};
            }}

            QWidget#musicControlBar QWidget#musicInfoButton[pressed="true"] {{
                background-color: {self._lighten_color(c.bg_secondary, 1.04)};
                border: 1px solid {self._hex_to_rgba(c.accent_primary, 136)};
            }}

            QWidget#musicControlBar QWidget#musicInfoButton[playState="active"] {{
                background-color: {c.bg_elevated};
                border: 1px solid {self._hex_to_rgba(c.accent_primary, 96)};
            }}

            QWidget#musicControlBar QWidget#musicInfoButton[playState="paused"] {{
                /* 对标修缮：暂停是常态而非异常，不再用 warning 黄边
                   （浅色主题下尤其突兀）；保持中性边框，播放中才点亮 accent */
                background-color: {c.bg_elevated};
                border: 1px solid {self._hex_to_rgba(c.border_primary, 140)};
            }}

            QWidget#musicControlBar QWidget#musicUtilityGroup {{
                background-color: {c.bg_elevated};
                border: 1px solid {self._hex_to_rgba(c.border_primary, 135)};
                border-radius: 12px;
            }}

            QWidget#musicControlBar QPushButton#actionButton {{
                background-color: transparent;
                color: {c.text_primary};
                border: none;
                border-radius: 8px;
                padding: 0px;
                font-size: 16px;
            }}
            
            /* UP-076 同类：音乐控制条的 actionButton 也拿 accent 当字色。
             * 底是半透明色叠在 musicControlBar 的 bg_secondary 上,
             * 必须按**合成后**的颜色收敛——直接拿 rgba 原色算会偏乐观。 */
            QWidget#musicControlBar QPushButton#actionButton:hover {{
                background-color: {self._hex_to_rgba(c.bg_tertiary, 210)};
                color: {self._accent_text_on(self._blend_hex(c.bg_tertiary, 210, c.bg_secondary))};
            }}

            QWidget#musicControlBar QPushButton#actionButton:pressed {{
                background-color: {self._hex_to_rgba(c.bg_primary, 235)};
                color: {self._accent_text_on(self._blend_hex(c.bg_primary, 235, c.bg_secondary))};
            }}
            
            QWidget#musicControlBar QSlider::groove:horizontal {{
                background: {self._hex_to_rgba(c.border_primary, 170)};
                height: 4px;
                border-radius: 2px;
            }}
            
            QWidget#musicControlBar QSlider::add-page:horizontal {{
                background: {self._hex_to_rgba(c.border_primary, 110)};
                border-radius: 2px;
            }}

            QWidget#musicControlBar QSlider::sub-page:horizontal {{
                background: {c.accent_primary};
                height: 4px;
                border-radius: 2px;
            }}
            
            QWidget#musicControlBar QSlider::handle:horizontal {{
                background: {c.accent_primary};
                width: 11px;
                height: 11px;
                margin: -4px 0;
                border-radius: 5px;
                border: 2px solid {c.bg_secondary};
            }}
            
            QWidget#musicControlBar QSlider::handle:horizontal:hover {{
                background: {c.accent_hover};
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }}

            /* ========== 禁用态（UP-022 / D-16）==========
             * 原状：除 primaryButton 外,所有控件的禁用态在视觉上和可用态完全一样。
             * 后果不是"不好看"——用户会反复去点一个点不动的按钮,以为是软件卡了。
             * QSS 没有 opacity,只能走颜色 token：文字灰化 + 底色降级 + 边框淡化。
             * 放在样式表末尾:同特异度下 QSS 后来者胜,保证能压过前面各控件的常态规则;
             * 而 `#primaryButton:disabled` 特异度更高,它自己的规则仍然生效。 */
            QPushButton:disabled,
            QComboBox:disabled,
            QLineEdit:disabled,
            QSpinBox:disabled,
            QDoubleSpinBox:disabled,
            QTextEdit:disabled,
            QPlainTextEdit:disabled {{
                /* R7 补 R4 的漏：这里原来用 text_disabled，而它是按「和常态文字能
                 * 分辨」挑的，压在下面那个 bg_tertiary@90 的底上只有 1.64~2.33:1
                 * （8/8 主题实测），文字等于消失了。text_on_disabled 是按**合成后**
                 * 的底色收敛到 3:1 的——弱化但不隐身。 */
                color: {c.text_on_disabled};
                background-color: {self._hex_to_rgba(c.bg_tertiary, 90)};
                border-color: {self._hex_to_rgba(c.border_secondary, 110)};
            }}

            /* R7/D-06: 危险按钮的禁用态。
             * `#dangerButton` 是 id 选择器（特异度 1,0,1），压过上面那条
             * `QPushButton:disabled`（0,1,1）—— 不显式写这条的话，禁用的危险按钮
             * 会保持满红，和可点的一模一样。
             * 处理方式是**退回中性禁用态而不是"淡红"**：红色的语义是「点下去会毁数据」，
             * 禁用的语义是「你点不了」，两者同时出现是自相矛盾的。
             * （试过 error@70 的淡红方案，实测禁用字只有 1.19~1.74:1，也看不清。） */
            QPushButton#dangerButton:disabled {{
                color: {c.text_on_disabled};
                background-color: {self._hex_to_rgba(c.bg_tertiary, 90)};
                border: 1px solid {self._hex_to_rgba(c.border_secondary, 110)};
            }}

            QPushButton#secondaryButton:disabled,
            QPushButton#actionButton:disabled {{
                color: {c.text_disabled};
                background-color: transparent;
                border-color: {self._hex_to_rgba(c.border_secondary, 110)};
            }}

            QCheckBox:disabled,
            QRadioButton:disabled,
            QLabel:disabled,
            QGroupBox:disabled {{
                color: {c.text_disabled};
            }}

            QRadioButton::indicator:disabled {{
                border-color: {self._hex_to_rgba(c.border_secondary, 110)};
                background-color: {self._hex_to_rgba(c.bg_tertiary, 90)};
            }}

            QSlider:disabled::groove:horizontal,
            QSlider:disabled::sub-page:horizontal {{
                background: {self._hex_to_rgba(c.border_secondary, 110)};
            }}

            QSlider:disabled::handle:horizontal {{
                background: {c.text_disabled};
                border-color: {self._hex_to_rgba(c.border_secondary, 110)};
            }}

            QTabBar::tab:disabled {{
                color: {c.text_disabled};
            }}
        """


class DarkTheme(Theme):
    """深色主题（v5 美学重做：注入蓝调 + dual accent + 卡片浮起）"""

    def __init__(self):
        colors = ThemeColors(
            # 主背景色 — 5 层灰阶 + 注入 5° 蓝紫调（Linear / Vercel 风）
            # 让 UI 不再是"工程师纯灰",有微妙的色调统一感
            bg_primary="#0a0c12",     # 最底层背景（OLED 黑感）
            bg_secondary="#14171f",   # 次要背景（侧边栏、状态栏）
            bg_tertiary="#1c1f2c",    # 嵌套层 / hover
            bg_elevated="#262a3a",    # 弹出层 / combo box 展开

            # v5 新加：卡片专用,在 secondary 上提亮一档让阴影"浮起"看得见
            bg_card="#1a1d27",        # 卡片底色（关键!阴影对比靠它）
            bg_card_hover="#20242f",  # 卡片 hover 态

            # 文字颜色 — 4 层
            text_primary="#e8e9ed",     # 主文字（标题）
            text_secondary="#a8aab3",   # 次要文字（正文）
            text_tertiary="#6e7081",    # 辅助文字（hint）
            text_disabled="#404252",    # 禁用

            # 主题色 — v5 改 violet（Vercel 风,比 indigo 更华丽现代）
            # 注：accent 总面积仍严格 < 8%，开关/激活态/链接才用
            accent_primary="#7c3aed",     # 主强调（violet）
            accent_hover="#8b4af2",       # hover 提亮
            accent_pressed="#6929d0",     # 按下加深
            accent_disabled="#3d2470",    # 禁用

            # v5 新加：dual accent
            accent_secondary="#06b6d4",   # 次强调（cyan）— 链接/次要 CTA
            accent_warm="#f59e0b",        # 暖色（amber）— 警告/重要提示/倒计时

            # 边框 — 弱化，让 elevation 阴影承担分隔
            border_primary="#2a2d3a",     # 主边框（hover 时使用）
            border_secondary="#1f212c",   # 默认边框（更弱）
            border_focus="#7c3aed",       # focus 用 v5 主色

            # 状态颜色 — 保持 v4 降饱和（已 OK）
            success="#22c55e",     # 翠绿
            warning="#f59e0b",     # 琥珀
            error="#ef4444",       # 红
            info="#7c3aed",        # 信息色 = 主色（统一）

            # 滚动条
            scrollbar_bg="#14171f",
            scrollbar_handle="#2a2d3a",
            scrollbar_hover="#3a3d4d",

            shadow="rgba(0, 0, 0, 0.65)"
        )
        super().__init__("深色主题", colors)


class LightTheme(Theme):
    """浅色主题"""

    def __init__(self):
        colors = ThemeColors(
            # 主背景色 — v2.2 调整：拉开卡片与背景的对比度
            # 旧版 bg_primary #eeecea / bg_secondary #f7f6f4 太接近导致卡片边界模糊
            bg_primary="#e8e6e3",      # 主背景偏暖灰，更深一档
            bg_secondary="#ffffff",    # 卡片纯白，与背景形成清晰分层
            bg_tertiary="#dedcd9",
            bg_elevated="#ffffff",

            # 文字颜色 — 足够深，对比清晰
            text_primary="#1c1c1e",
            text_secondary="#48484a",
            text_tertiary="#8e8e93",
            text_disabled="#aeaeb2",

            # 主题色（蓝色系）— Apple 风格蓝
            accent_primary="#007aff",
            accent_hover="#3395ff",
            accent_pressed="#0062cc",
            accent_disabled="#a0c8f0",

            # 边框颜色 — v2.2 加深以提升卡片可见度
            border_primary="#bdbcb8",
            border_secondary="#cfcdc9",
            border_focus="#007aff",

            # 状态颜色 — v2.2 调深以适配浅色背景，避免过度饱和
            # 旧值 #34c759/#ff9500/#ff3b30 在浅色背景上对比度过强
            success="#1f9e3e",
            warning="#cc7700",
            error="#d63638",
            info="#007aff",

            # 功能颜色
            scrollbar_bg="#e8e7e5",
            scrollbar_handle="#b0afad",
            scrollbar_hover="#8a8987",

            shadow="rgba(0, 0, 0, 0.08)"
        )
        super().__init__("浅色主题", colors)


class GreenTheme(Theme):
    """墨绿主题 — 深底 + 绿色调"""

    def __init__(self):
        colors = ThemeColors(
            bg_primary="#161b18",
            bg_secondary="#1e2722",
            bg_tertiary="#28332c",
            bg_elevated="#303d35",

            text_primary="#d4ddd7",
            text_secondary="#9aaa9f",
            text_tertiary="#6b7d72",
            text_disabled="#455049",

            accent_primary="#4eca6a",
            accent_hover="#6edd84",
            accent_pressed="#3ab856",
            accent_disabled="#2a5e38",

            border_primary="#2e3b32",
            border_secondary="#252f28",
            border_focus="#4eca6a",

            success="#4eca6a",
            warning="#e8b339",
            error="#e85454",
            info="#4eca6a",

            scrollbar_bg="#1a211c",
            scrollbar_handle="#3a4a40",
            scrollbar_hover="#4a5c50",

            shadow="rgba(0, 0, 0, 0.4)"
        )
        super().__init__("墨绿主题", colors)


class PurpleTheme(Theme):
    """紫夜主题 — 深底 + 紫色调"""

    def __init__(self):
        colors = ThemeColors(
            bg_primary="#18161e",
            bg_secondary="#211e2a",
            bg_tertiary="#2c2836",
            bg_elevated="#363040",

            text_primary="#d8d4e0",
            text_secondary="#a49cb2",
            text_tertiary="#756c85",
            text_disabled="#4a4455",

            accent_primary="#9b6dff",
            accent_hover="#b48fff",
            accent_pressed="#8455e8",
            accent_disabled="#4a3570",

            border_primary="#302a3c",
            border_secondary="#272230",
            border_focus="#9b6dff",

            success="#52d980",
            warning="#e8b339",
            error="#e85454",
            info="#9b6dff",

            scrollbar_bg="#1c1922",
            scrollbar_handle="#403a4e",
            scrollbar_hover="#504860",

            shadow="rgba(0, 0, 0, 0.4)"
        )
        super().__init__("紫夜主题", colors)


class WarmTheme(Theme):
    """暖橙主题 — 浅暖底 + 橙色调"""

    def __init__(self):
        colors = ThemeColors(
            bg_primary="#f0ebe5",
            bg_secondary="#f8f4ef",
            bg_tertiary="#e4ded6",
            bg_elevated="#f2ede7",

            text_primary="#2c2420",
            text_secondary="#5c4f44",
            text_tertiary="#8c7e72",
            text_disabled="#b0a498",

            accent_primary="#e07830",
            accent_hover="#f09048",
            accent_pressed="#c86820",
            accent_disabled="#c8a888",

            border_primary="#ccc4ba",
            border_secondary="#ddd6cc",
            border_focus="#e07830",

            success="#4aaa5a",
            warning="#e09030",
            error="#d94040",
            info="#e07830",

            scrollbar_bg="#eae4dc",
            scrollbar_handle="#b8b0a4",
            scrollbar_hover="#9a9288",

            shadow="rgba(60, 40, 20, 0.08)"
        )
        super().__init__("暖橙主题", colors)


class ContrastTheme(Theme):
    """高对比主题 — 纯黑底 + 亮白字 + 强蓝"""

    def __init__(self):
        colors = ThemeColors(
            bg_primary="#000000",
            bg_secondary="#141414",
            bg_tertiary="#222222",
            bg_elevated="#2a2a2a",

            text_primary="#ffffff",
            text_secondary="#cccccc",
            text_tertiary="#888888",
            text_disabled="#555555",

            accent_primary="#4dabff",
            accent_hover="#70c0ff",
            accent_pressed="#3090e0",
            accent_disabled="#2a5580",

            border_primary="#404040",
            border_secondary="#2a2a2a",
            border_focus="#4dabff",

            success="#44dd66",
            warning="#ffbb33",
            error="#ff4444",
            info="#4dabff",

            scrollbar_bg="#0a0a0a",
            scrollbar_handle="#505050",
            scrollbar_hover="#686868",

            shadow="rgba(0, 0, 0, 0.6)"
        )
        super().__init__("高对比主题", colors)


class RoseTheme(Theme):
    """玫瑰主题 — 浅粉底 + 玫红色调"""

    def __init__(self):
        colors = ThemeColors(
            bg_primary="#f0eaec",
            bg_secondary="#f8f3f5",
            bg_tertiary="#e4dce0",
            bg_elevated="#f2ecee",

            text_primary="#2c2028",
            text_secondary="#5c4854",
            text_tertiary="#8c7682",
            text_disabled="#b09aa6",

            accent_primary="#d4507a",
            accent_hover="#e06890",
            accent_pressed="#c04068",
            accent_disabled="#c8a0b0",

            border_primary="#ccc2c8",
            border_secondary="#ddd4d8",
            border_focus="#d4507a",

            success="#4aaa5a",
            warning="#e09030",
            error="#d94040",
            info="#d4507a",

            scrollbar_bg="#eae2e6",
            scrollbar_handle="#b8aeb4",
            scrollbar_hover="#9a8e94",

            shadow="rgba(60, 20, 40, 0.08)"
        )
        super().__init__("玫瑰主题", colors)


class OceanTheme(Theme):
    """深海主题 — 深蓝底 + 青蓝色调"""

    def __init__(self):
        colors = ThemeColors(
            bg_primary="#141820",
            bg_secondary="#1a2030",
            bg_tertiary="#242c3a",
            bg_elevated="#2c3444",

            text_primary="#d0d8e4",
            text_secondary="#94a0b4",
            text_tertiary="#667080",
            text_disabled="#404a58",

            accent_primary="#38b0d0",
            accent_hover="#50c8e8",
            accent_pressed="#2898b8",
            accent_disabled="#1e5060",

            border_primary="#283040",
            border_secondary="#202838",
            border_focus="#38b0d0",

            success="#40c878",
            warning="#e0a830",
            error="#e05050",
            info="#38b0d0",

            scrollbar_bg="#161c26",
            scrollbar_handle="#384050",
            scrollbar_hover="#485868",

            shadow="rgba(0, 0, 0, 0.45)"
        )
        super().__init__("深海主题", colors)


class MinimalTheme(Theme):
    """极简主题 - 完全清空样式，使用系统默认外观"""
    
    def __init__(self):
        # 创建一个占位符颜色配置（不会被使用）
        colors = ThemeColors(
            bg_primary="#ffffff",
            bg_secondary="#ffffff",
            bg_tertiary="#f0f0f0",
            bg_elevated="#ffffff",
            text_primary="#000000",
            text_secondary="#555555",
            text_tertiary="#888888",
            text_disabled="#cccccc",
            accent_primary="#808080",
            accent_hover="#999999",
            accent_pressed="#666666",
            accent_disabled="#dddddd",
            border_primary="#e8e8e8",
            border_secondary="#f5f5f5",
            border_focus="#999999",
            success="#888888",
            warning="#888888",
            error="#888888",
            info="#888888",
            scrollbar_bg="#ffffff",
            scrollbar_handle="#d8d8d8",
            scrollbar_hover="#c0c0c0",
            shadow="rgba(0, 0, 0, 0.02)"
        )
        super().__init__("极简主题", colors)
    
    def generate_stylesheet(self) -> str:
        """极简主题返回空样式表，使用系统默认样式"""
        return ""


class ThemeManager:
    """主题管理器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.logger = get_logger()
            self.themes: Dict[str, Theme] = {
                "dark": DarkTheme(),
                "light": LightTheme(),
                "green": GreenTheme(),
                "purple": PurpleTheme(),
                "ocean": OceanTheme(),
                "warm": WarmTheme(),
                "rose": RoseTheme(),
                "contrast": ContrastTheme(),
                "minimal": MinimalTheme()
            }
            self.current_theme_name = "dark"  # 默认深色主题
            self._theme_changed_callbacks = []  # 主题变化回调
            self._initialized = True
    
    @property
    def current_theme(self) -> Theme:
        """获取当前主题"""
        return self.themes[self.current_theme_name]
    
    def register_theme_changed_callback(self, callback):
        """注册主题变化回调"""
        if callback not in self._theme_changed_callbacks:
            self._theme_changed_callbacks.append(callback)
            # 2.1.4 日志降噪：每个组件注册都打 info 会在启动期刷 100+ 条，降为 debug
            self.logger.debug("已注册主题变化回调")

    def unregister_theme_changed_callback(self, callback):
        """注销主题变化回调，防止内存泄漏"""
        try:
            self._theme_changed_callbacks.remove(callback)
        except ValueError:
            pass
    
    def set_theme(self, theme_name: str):
        """设置主题"""
        if theme_name in self.themes:
            old_theme = self.current_theme_name
            self.current_theme_name = theme_name
            self.logger.info(f"已切换主题: {old_theme} -> {theme_name}")
            
            # 触发所有回调
            for callback in self._theme_changed_callbacks:
                try:
                    callback()
                except Exception as e:
                    self.logger.error(f"主题变化回调执行失败: {e}")
        else:
            self.logger.warning(f"未找到主题: {theme_name}")
    
    def get_stylesheet(self) -> str:
        """获取当前主题的样式表"""
        return self.current_theme.generate_stylesheet()
    
    def get_color(self, color_name: str) -> str:
        """获取当前主题的指定颜色"""
        return getattr(self.current_theme.colors, color_name, "#000000")
    
    def register_theme(self, theme_name: str, theme: Theme):
        """注册自定义主题"""
        self.themes[theme_name] = theme
        self.logger.info(f"已注册主题: {theme.name}")


# 全局主题管理器实例
_theme_manager = ThemeManager()


def get_theme_manager() -> ThemeManager:
    """获取主题管理器实例"""
    return _theme_manager


def get_current_theme() -> Theme:
    """获取当前主题"""
    return _theme_manager.current_theme


def get_stylesheet() -> str:
    """获取当前样式表"""
    return _theme_manager.get_stylesheet()


def get_color(color_name: str) -> str:
    """获取当前主题颜色"""
    return _theme_manager.get_color(color_name)
