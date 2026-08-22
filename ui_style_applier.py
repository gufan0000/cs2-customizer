# SPDX-License-Identifier: GPL-3.0-or-later
"""
UI样式自动应用系统
自动识别组件类型并应用统一的设计规范
"""

from PySide6.QtWidgets import (
    QWidget, QPushButton, QLabel, QLineEdit, QTextEdit, QPlainTextEdit,
    QComboBox, QCheckBox, QRadioButton, QSlider, QSpinBox, QDoubleSpinBox,
    QFrame, QGroupBox, QProgressBar, QScrollArea
)
from PySide6.QtCore import Qt
from ui_design_system import get_design_system


class StyleApplier:
    """样式自动应用器"""
    
    def __init__(self):
        self.ds = get_design_system()

    def _get_button_metrics(self, button: QPushButton):
        """根据按钮类型返回统一的尺寸和 padding 规范"""
        object_name = button.objectName()

        if object_name == "secondaryButton":
            return (
                self.ds.button.primary_min_width,
                self.ds.button.secondary_height,
                self.ds.button.secondary_padding_horizontal,
                self.ds.button.secondary_padding_vertical,
            )
        if object_name == "dangerButton":
            return (
                self.ds.button.primary_min_width,
                self.ds.button.danger_height,
                self.ds.button.danger_padding_horizontal,
                self.ds.button.danger_padding_vertical,
            )
        if object_name == "actionButton":
            return (
                self.ds.button.primary_min_width,
                self.ds.button.action_height,
                self.ds.button.action_padding_horizontal,
                self.ds.button.action_padding_vertical,
            )
        return (
            self.ds.button.primary_min_width,
            self.ds.button.primary_height,
            self.ds.button.primary_padding_horizontal,
            self.ds.button.primary_padding_vertical,
        )
    
    # ========== 主要入口函数 ==========
    
    def apply_unified_styles(self, widget: QWidget, recursive: bool = True):
        """
        为widget及其子组件应用统一样式
        
        Args:
            widget: 要应用样式的组件
            recursive: 是否递归应用到子组件
        """
        # 根据widget类型应用相应的样式
        self._apply_widget_style(widget)
        
        # 递归处理子组件
        if recursive:
            for child in widget.findChildren(QWidget):
                self._apply_widget_style(child)
    
    def _apply_widget_style(self, widget: QWidget):
        """为单个widget应用样式"""
        # 如果已经有objectName，说明已经被手动配置，跳过
        if widget.objectName() and widget.objectName() not in ["", "qt_scrollarea_viewport"]:
            return
        
        # 根据widget类型应用默认objectName
        if isinstance(widget, QPushButton):
            self._style_button(widget)
        elif isinstance(widget, QLabel):
            self._style_label(widget)
        elif isinstance(widget, QLineEdit):
            self._style_lineedit(widget)
        elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
            self._style_textedit(widget)
        elif isinstance(widget, QComboBox):
            self._style_combobox(widget)
        elif isinstance(widget, QCheckBox):
            self._style_checkbox(widget)
        elif isinstance(widget, QRadioButton):
            self._style_radiobutton(widget)
        elif isinstance(widget, QSlider):
            self._style_slider(widget)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            self._style_spinbox(widget)
        elif isinstance(widget, QProgressBar):
            self._style_progressbar(widget)
        elif isinstance(widget, QScrollArea):
            self._style_scrollarea(widget)
        elif isinstance(widget, QFrame):
            self._style_frame(widget)
        elif isinstance(widget, QGroupBox):
            self._style_groupbox(widget)
    
    # ========== 具体组件样式应用 ==========
    
    def _style_button(self, button: QPushButton):
        """统一按钮样式"""
        # UP-070: 这里原本按**按钮文案**猜语义——含"保存/确定"猜 primary、
        # 含"删除/移除"猜 danger。按文案猜"这个操作危不危险"是不可靠的：
        # 「删除本地缓存」（可再生）会被染红，而「重置所有设置」（当场 os.remove
        # config.json 且不可逆）因为没写"删"字反而是灰的——危险色的可信度由此被稀释。
        #
        # 删除前实测过影响面：21 个安全页 + 6 个受限页静态核查，全站只有 1 颗按钮
        # 还在吃这条猜测（viewmodel 的「保存设置到CFG」→ primaryButton），
        # danger / secondary 两条分支命中 **0 次**——所有危险按钮早已显式派名。
        # 那颗按钮已就地改成显式 setObjectName，因此本次删除的观感变化为零。
        #
        # 语义色必须**声明**，不能**猜**。要 primary/danger 请用 AppButton 工厂或
        # page_theme_helper 的 style_as_* ，让危险性写在调用点、看得见、可 review。
        if not button.objectName():
            button.setObjectName("actionButton")
        
        # 设置统一的最小尺寸
        min_width, min_height, _, _ = self._get_button_metrics(button)

        if button.minimumWidth() < min_width:
            button.setMinimumWidth(min_width)
        
        if button.minimumHeight() < min_height:
            button.setMinimumHeight(min_height)
        
        # 设置鼠标光标
        button.setCursor(Qt.PointingHandCursor)
    
    def _style_label(self, label: QLabel):
        """统一标签样式"""
        if not label.objectName():
            text = label.text()
            
            # 根据文字内容判断类型
            if text.endswith('：') or text.endswith(':'):
                label.setObjectName("label")  # 字段标签
            elif len(text) < 20 and ('提示' in text or '说明' in text or '注意' in text):
                label.setObjectName("hintLabel")  # 提示标签
            elif label.font().pixelSize() > 14 or label.font().pointSize() > 14:
                label.setObjectName("titleLabel")  # 标题标签
            else:
                label.setObjectName("label")  # 普通标签
    
    def _style_lineedit(self, lineedit: QLineEdit):
        """统一输入框样式"""
        if not lineedit.objectName():
            lineedit.setObjectName("input")
        # 安装焦点下划线
        try:
            from ui_focus_underline import install_focus_underline
            install_focus_underline(lineedit)
        except Exception:
            pass
        
        # 设置统一的最小高度
        if lineedit.minimumHeight() < self.ds.input.text_height:
            lineedit.setMinimumHeight(self.ds.input.text_height)
    
    def _style_textedit(self, textedit):
        """统一文本编辑框样式"""
        if not textedit.objectName():
            textedit.setObjectName("textEdit")
    
    def _style_combobox(self, combobox: QComboBox):
        """统一下拉框样式"""
        if not combobox.objectName():
            combobox.setObjectName("comboBox")

        # 设置统一的最小高度
        if combobox.minimumHeight() < self.ds.input.combobox_height:
            combobox.setMinimumHeight(self.ds.input.combobox_height)

        combobox.setCursor(Qt.PointingHandCursor)

        # 下拉列表圆角裁剪（去掉系统阴影 + 透明背景让 QSS border-radius 生效）
        try:
            view = combobox.view()
            if view and view.window():
                view.window().setWindowFlags(
                    view.window().windowFlags() | Qt.NoDropShadowWindowHint
                )
                view.window().setAttribute(Qt.WA_TranslucentBackground)
        except Exception:
            pass
    
    def _style_checkbox(self, checkbox: QCheckBox):
        """统一复选框样式"""
        if not checkbox.objectName():
            checkbox.setObjectName("checkBox")
        
        checkbox.setCursor(Qt.PointingHandCursor)
    
    def _style_radiobutton(self, radio: QRadioButton):
        """统一单选框样式"""
        if not radio.objectName():
            radio.setObjectName("radioButton")
        
        radio.setCursor(Qt.PointingHandCursor)
    
    def _style_slider(self, slider: QSlider):
        """统一滑块样式"""
        if not slider.objectName():
            if slider.orientation() == Qt.Horizontal:
                slider.setObjectName("slider")
            else:
                slider.setObjectName("verticalSlider")
        # 安装数值气泡
        try:
            from ui_slider_bubble import install_slider_bubble
            install_slider_bubble(slider)
        except Exception:
            pass
    
    def _style_spinbox(self, spinbox):
        """统一数字输入框样式"""
        if not spinbox.objectName():
            spinbox.setObjectName("spinBox")

        # 设置统一的最小高度
        if spinbox.minimumHeight() < self.ds.input.text_height:
            spinbox.setMinimumHeight(self.ds.input.text_height)
        # 安装焦点下划线
        try:
            from ui_focus_underline import install_focus_underline
            install_focus_underline(spinbox)
        except Exception:
            pass
    
    def _style_progressbar(self, progressbar: QProgressBar):
        """统一进度条样式"""
        if not progressbar.objectName():
            progressbar.setObjectName("progressBar")
    
    def _style_scrollarea(self, scroll_area: QScrollArea):
        """为滚动区域安装顶部阴影"""
        # 跳过侧边栏滚动区域
        if scroll_area.objectName() in ("sidebarScroll",):
            return
        try:
            from ui_effects import install_scroll_shadow
            install_scroll_shadow(scroll_area)
        except Exception:
            pass

    def _style_frame(self, frame: QFrame):
        """统一框架样式"""
        # 判断frame的用途
        if not frame.objectName():
            # 检查frame的形状和阴影
            if frame.frameShape() == QFrame.Box or frame.frameShadow() == QFrame.Raised:
                frame.setObjectName("card")
            elif frame.frameShape() == QFrame.HLine:
                frame.setObjectName("separator")
            elif frame.frameShape() == QFrame.VLine:
                frame.setObjectName("verticalSeparator")
            # 默认不设置，保持透明
    
    def _style_groupbox(self, groupbox: QGroupBox):
        """统一分组框样式"""
        if not groupbox.objectName():
            groupbox.setObjectName("groupBox")
    
    # ========== 特殊组件处理 ==========
    
    @staticmethod
    def _width_is_fixed(widget: QWidget) -> bool:
        """调用方是不是已经把宽度钉死了（setFixedSize / setFixedWidth）。

        Qt 的 setFixedXxx 就是把 min 和 max 设成同一个值，所以这样判最准。
        """
        return widget.minimumWidth() == widget.maximumWidth()

    @staticmethod
    def _height_is_fixed(widget: QWidget) -> bool:
        return widget.minimumHeight() == widget.maximumHeight()


    #: 字段标签的最长字数。超过这个长度的多半是句子而不是标签，照常允许折行。
    FIELD_LABEL_MAX_CHARS = 16

    @classmethod
    def _is_field_label(cls, text: str) -> bool:
        """这段文字是不是**用来称呼旁边那个控件**的字段标签（RN-191）。

        判据取自文案自身：以「:」或「：」结尾、且短。
        ⭐ 不用名单：名单要靠人记得往里加，而这条规则跟着文案自己走。
        """
        t = (text or "").strip()
        return bool(t) and t[-1] in ":：" and len(t) <= cls.FIELD_LABEL_MAX_CHARS

    def fix_text_display(self, widget: QWidget):
        """
        修复文字显示问题
        确保所有文字控件有足够的padding和高度

        UP-018：这里原本无条件抬 min 宽高，把调用方 `setFixedSize()` 的意图冲掉了。
        典型受害者是帮助面板的 "?" 按钮（`ui_help_panel.py` 里 `setFixedSize(24, 24)`）：
        文字 "?" 很窄，但 `min_width_spec` 有下限、`+ padding*2 + 20` 又再加一截，
        算出来约 80px；min 被抬到 80 就超过了 max=24，Qt 只好把 max 也跟着放大，
        于是 20 多个页面上那颗小圆钮全变成 80×42 的大方块。
        现在：**尺寸被钉死的控件一律不碰**——调用方明确表达过意图就该赢。
        """
        if isinstance(widget, QPushButton):
            # 确保按钮文字完整显示
            metrics = widget.fontMetrics()
            text_width = metrics.horizontalAdvance(widget.text())
            text_height = metrics.height()
            min_width_spec, min_height_spec, padding_horizontal, padding_vertical = self._get_button_metrics(widget)

            # 设置最小宽度（文字宽度 + padding）
            if not self._width_is_fixed(widget):
                min_width = max(min_width_spec, text_width + padding_horizontal * 2 + 20)
                if widget.minimumWidth() < min_width:
                    widget.setMinimumWidth(min_width)

            # 设置最小高度
            if not self._height_is_fixed(widget):
                min_height = max(text_height + padding_vertical * 2, min_height_spec)
                if widget.minimumHeight() < min_height:
                    widget.setMinimumHeight(min_height)

        elif isinstance(widget, QLabel):
            # RN-121：**调用方明确说过"我不折行"的，不碰。**
            #
            # 这里原本无条件 `setWordWrap(True)`，把调用方的意图整个冲掉 ——
            # 与正上方 UP-018 那条一模一样的错，只是那条修的是尺寸、这条是换行，
            # 当时没顺手看一眼隔壁分支。
            #
            # 代价：折行的 QLabel 在**横排**布局里会把自己的宽度报小，布局就照那个
            # 窄宽给它。实测 crosshair 标题行的提示只拿到 120px（需要 156px），
            # 而同一行还空着 928px —— 于是断在「统 / 一」中间。
            # ⭐ **折行往往不是"空间不够"的结果，是"我说我能折行"的结果**，
            # 所以它躲得过一切"有没有溢出/有没有截断"的判据。
            #
            # opt-out 沿用本类既有的动态属性做法（见 KEEP_STYLE_PROPERTY）。
            #
            # ⚠⚠ RN-191：RN-121 留了这个 opt-out，**可它是 opt-in 的** ——
            # 得有人想起来在调用处设那个属性，而表单标签的调用方一个都没设。
            # 实测（紧凑档 magnifier）：「主武器热键:」宽 69px、需 73px，
            # **差 4px 就折成两行**（「主武器热」/「键:」），本页共 9 个这样的标签。
            # ⭐ 一个"默认开、需要显式关"的行为，等于"绝大多数地方都开着" ——
            #   opt-out 的存在不代表它被用上了。
            #
            # ⇒ 加一条**从文案自己推得出来**的规则：以「:」「：」结尾的是**字段标签**，
            #   它是用来称呼旁边那个控件的，永远不该折行。
            #   折了它就把自己的宽度报小，布局照那个窄宽给它，于是折得更狠。
            if not widget.property(self.KEEP_WRAP_PROPERTY):
                widget.setWordWrap(not self._is_field_label(widget.text()))
            widget.adjustSize()

        elif isinstance(widget, (QLineEdit, QComboBox)):
            # 确保输入框和下拉框有足够的高度
            if not self._height_is_fixed(widget) and widget.minimumHeight() < self.ds.input.text_height:
                widget.setMinimumHeight(self.ds.input.text_height)
    
    def apply_to_container(self, container: QWidget):
        """
        为容器应用统一样式
        自动识别容器类型并应用相应样式
        """
        if isinstance(container, QFrame):
            # 判断是否是卡片容器
            if (container.frameShape() == QFrame.Box or 
                container.frameShadow() == QFrame.Raised or
                container.layout() is not None):
                container.setObjectName("card")
        elif isinstance(container, QGroupBox):
            container.setObjectName("groupBox")
    
    # ========== 递归清理和应用 ==========
    
    # UP-019: 带这个动态属性的控件，其内联样式不会被清掉。
    KEEP_STYLE_PROPERTY = "fp_keep_style"

    # RN-121: 带这个动态属性的 QLabel，`fix_text_display` 不会替它开启换行。
    KEEP_WRAP_PROPERTY = "fp_keep_wrap"

    def clear_all_styles(self, widget: QWidget, clear_root: bool = True):
        """
        清除所有硬编码样式
        为重新应用统一样式做准备

        UP-019：原本是**无差别**清空每个子控件的内联样式。这个设计出自"代码里
        到处是硬编码颜色"的年代，但那批硬编码早已清干净（R0 实测：QSS 正文
        `#RRGGBB` 字面量 0 个，全站只剩 45 处 setStyleSheet，且基本都是
        从 theme token 现算出来的）。于是它现在只剩副作用——
        `apply_complete_system` 在页面构造完立刻跑一遍，把构造期设的内联样式全抹了：
        武器行的分隔线和 hover 态就是这么消失的，得等用户切一次主题才回来。

        改法：认 `fp_keep_style` 动态属性做 opt-out。控件自己声明"我的样式是
        算出来的、不是硬编码"，清理就绕开它。

        Args:
            widget: 要清除样式的组件
            clear_root: 是否清除根组件的样式（默认True）
        """
        # 清除当前widget的样式（可选）
        if clear_root and not widget.property(self.KEEP_STYLE_PROPERTY):
            widget.setStyleSheet("")

        # 递归清除子组件样式
        for child in widget.findChildren(QWidget):
            if child.property(self.KEEP_STYLE_PROPERTY):
                continue
            child.setStyleSheet("")
    
    def apply_complete_system(self, widget: QWidget):
        """
        应用完整的统一样式系统
        1. 清除所有硬编码样式（不清除根组件样式，因为它可能有全局主题样式表）
        2. 自动设置objectName
        3. 修复文字显示
        """
        # 步骤1: 清除旧样式（不清除根组件的样式表）
        self.clear_all_styles(widget, clear_root=False)
        
        # 步骤2: 应用统一样式和objectName
        self.apply_unified_styles(widget, recursive=True)
        
        # 步骤3: 修复文字显示问题
        for child in widget.findChildren(QWidget):
            self.fix_text_display(child)


# ========== 全局访问函数 ==========

_applier_instance = None

def get_style_applier() -> StyleApplier:
    """获取样式应用器单例"""
    global _applier_instance
    if _applier_instance is None:
        _applier_instance = StyleApplier()
    return _applier_instance


# ========== 便捷函数 ==========

def apply_unified_styles(widget: QWidget):
    """
    快捷函数：为widget应用统一样式
    
    使用示例：
        from ui_style_applier import apply_unified_styles
        apply_unified_styles(self)  # 在__init__结尾调用
    """
    applier = get_style_applier()
    applier.apply_complete_system(widget)


def keep_single_line(label) -> "QLabel":
    """标记「这个标签是一行，别替我开换行」（RN-121）。

    `fix_text_display()` 会在页面构造完成后给每个 QLabel `setWordWrap(True)` ——
    **调用方自己设的 False 会被它冲掉，而且悄无声息**。
    代价见 `fix_text_display` 里那段说明：折行的标签在横排里会把宽度报小，
    于是明明还空着 900 多 px，提示却断在词中间。

    ⚠ 只调 `label.setWordWrap(False)` 是**没用的**，必须连这个标记一起给 ——
    本函数两件一起做，省得下次又只做一半。

    返回 label 本身，方便链式写法。
    """
    label.setProperty(StyleApplier.KEEP_WRAP_PROPERTY, True)
    label.setWordWrap(False)
    return label


def keep_inline_style(widget: QWidget) -> QWidget:
    """标记「这个控件的内联样式是按 theme token 算出来的，别抹」（UP-019）。

    `apply_complete_system()` 会在页面构造完成后清空所有子控件的内联样式，
    本意是清掉硬编码颜色。但从 theme token 现算出来的样式也一并遭殃——
    典型是武器行的分隔线和 hover 态，首次进页直接不见，得切一次主题才回来。
    在设置内联样式的地方顺手调一下本函数即可豁免。

    返回 widget 本身，方便链式写法。
    """
    widget.setProperty(StyleApplier.KEEP_STYLE_PROPERTY, True)
    return widget


def fix_button_text(button: QPushButton):
    """快捷函数：修复按钮文字显示"""
    applier = get_style_applier()
    applier.fix_text_display(button)


def make_primary_button(button: QPushButton):
    """快捷函数：将按钮设为主要按钮"""
    button.setObjectName("primaryButton")
    fix_button_text(button)


def make_card(frame: QFrame):
    """快捷函数：将框架设为卡片"""
    frame.setObjectName("card")
