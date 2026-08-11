# SPDX-License-Identifier: GPL-3.0-or-later
"""
页面主题应用辅助模块

用于帮助各个页面统一应用主题样式，移除硬编码样式
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QGroupBox, QFrame
from theme_manager import get_theme_manager


def apply_page_theme(widget: QWidget):
    """
    为页面控件应用主题
    
    这个函数会：
    1. 清除所有硬编码的 setStyleSheet()
    2. 让控件使用全局主题样式
    3. 为特定类型的控件设置 objectName 以便样式定位
    
    Args:
        widget: 页面根控件
    """
    # 清除当前控件的硬编码样式
    widget.setStyleSheet("")
    
    # 递归处理所有子控件
    for child in widget.findChildren(QWidget):
        # 清除子控件的硬编码样式
        child.setStyleSheet("")
        
        # 根据控件类型设置合适的 objectName（如果还没有）
        if not child.objectName():
            _set_default_object_name(child)


def _set_default_object_name(widget: QWidget):
    """为控件设置默认的 objectName"""
    
    # 标签类型
    if isinstance(widget, QLabel):
        widget.setObjectName("label")
    
    # 按钮类型 - 根据文本内容判断
    elif isinstance(widget, QPushButton):
        text = widget.text().lower()
        if any(keyword in text for keyword in ['测试', 'test', '预览', 'preview']):
            widget.setObjectName("secondaryButton")
        elif any(keyword in text for keyword in ['保存', 'save', '应用', 'apply', '确定', 'ok']):
            widget.setObjectName("primaryButton")
        elif any(keyword in text for keyword in ['取消', 'cancel', '关闭', 'close']):
            widget.setObjectName("secondaryButton")
        else:
            widget.setObjectName("button")
    
    # 分组框
    elif isinstance(widget, QGroupBox):
        widget.setObjectName("groupBox")
    
    # 分隔线
    elif isinstance(widget, QFrame) and widget.frameShape() in [QFrame.HLine, QFrame.VLine]:
        widget.setObjectName("separator")


def clear_widget_styles(widget: QWidget, recursive=True):
    """
    清除控件的所有硬编码样式
    
    Args:
        widget: 要清除样式的控件
        recursive: 是否递归清除子控件的样式
    """
    widget.setStyleSheet("")
    
    if recursive:
        for child in widget.findChildren(QWidget):
            child.setStyleSheet("")


def register_theme_change_listener(page_widget: QWidget, callback):
    """
    为页面注册主题变化监听器
    
    Args:
        page_widget: 页面控件
        callback: 主题变化时的回调函数
    """
    theme_manager = get_theme_manager()
    theme_manager.register_theme_changed_callback(callback)


# ========== 常用控件样式辅助函数 ==========

def style_as_card(widget: QWidget):
    """
    将控件样式设为卡片样式（通过 objectName）
    
    Args:
        widget: 要设置的控件
    """
    widget.setObjectName("card")
    widget.setStyleSheet("")  # 清除硬编码样式，使用全局主题


def style_as_section_title(label: QLabel):
    """
    将标签样式设为章节标题
    
    Args:
        label: 要设置的标签
    """
    label.setObjectName("sectionTitle")
    label.setStyleSheet("")  # 清除硬编码样式


def style_as_primary_button(button: QPushButton):
    """
    将按钮样式设为主按钮
    
    Args:
        button: 要设置的按钮
    """
    button.setObjectName("primaryButton")
    button.setStyleSheet("")  # 清除硬编码样式
    # UP-080: `_apply_widget_style` 一见到 objectName 非空就 return，
    # 于是**所有显式派名的按钮**都拿不到 `_style_button` 里那句手型光标——
    # 越是重要的按钮（主操作/危险操作）越是显式派名，也就越容易丢。
    # 在这里补上，让"显式声明语义"不再以牺牲交互反馈为代价。
    button.setCursor(Qt.PointingHandCursor)


def style_as_secondary_button(button: QPushButton):
    """
    将按钮样式设为次要按钮
    
    Args:
        button: 要设置的按钮
    """
    button.setObjectName("secondaryButton")
    button.setStyleSheet("")  # 清除硬编码样式
    # UP-080: `_apply_widget_style` 一见到 objectName 非空就 return，
    # 于是**所有显式派名的按钮**都拿不到 `_style_button` 里那句手型光标——
    # 越是重要的按钮（主操作/危险操作）越是显式派名，也就越容易丢。
    # 在这里补上，让"显式声明语义"不再以牺牲交互反馈为代价。
    button.setCursor(Qt.PointingHandCursor)


def style_as_danger_button(button: QPushButton):
    """把按钮标记为**危险操作**（R7/D-06，UP-042）。

    D-06 的口径：仅用于**不可逆的数据丢失**——重置所有设置、删除风格/预设/快照、
    恢复默认 HUD、清空列表。**停用某个功能的开关不算危险。**
    红色语义要稀缺才有效；到处都是红的等于没有红的。

    为什么需要显式声明：`ui_style_applier._style_button()` 会给**没有 objectName**
    的按钮按**文案**猜语义——文字里含「删除/移除/delete/remove」就自动派成
    dangerButton。实测这个猜法两头都错：
      · 「重置所有设置」（全站最不可逆的操作）→ 猜成 actionButton，不红；
      · 「清空列表」（D-06 明文点名）→ 猜成 actionButton，不红；
      · 任何写着「删除」的按钮 → 一律变红，哪怕它有撤销/回收站兜底。
    显式设了 objectName 之后 `_apply_widget_style` 会提前 return，猜名逻辑不再介入。
    """
    button.setObjectName("dangerButton")
    button.setStyleSheet("")  # 清除硬编码样式
    # UP-080: 同 primary/secondary —— 显式派名会让 `_style_button` 整段跳过，
    # 手型光标也一并丢掉。危险按钮更不该缺这点可点击性反馈。
    button.setCursor(Qt.PointingHandCursor)


def style_as_ghost_button(button: QPushButton):
    """把按钮标记为**幽灵按钮**——无边框无底、仅文字，用于次级/可选动作。

    这个语义原本只由 `AppButton.ghost()` 产出。R8-W5 收口删掉零引用的
    `AppButton` 时，如果连它一起删，R8a 刚为 `UP-073` 补上的整块
    `QPushButton#ghostButton` QSS、以及 `ui_contrast_audit.py` 里守着它
    两个交互态的判据，会一起变成**没有生产者的死代码**——
    判据还在跑、还在报绿，但已经没有任何按钮会走到那条规则上。

    所以样式留下，只把产出方式换成全站统一的 `style_as_*` 惯用法。
    """
    button.setObjectName("ghostButton")
    button.setStyleSheet("")  # 清除硬编码样式
    # UP-080: 同 primary/secondary/danger——显式派名会让 `_style_button` 整段跳过
    button.setCursor(Qt.PointingHandCursor)


# ========== 页面初始化辅助函数 ==========

def init_themed_page(page_widget: QWidget):
    """
    初始化一个使用主题的页面
    
    这个函数应该在页面的 __init__ 最后调用
    
    Args:
        page_widget: 页面根控件
    """
    # 清除所有硬编码样式
    apply_page_theme(page_widget)
    
    # 刷新样式
    page_widget.style().unpolish(page_widget)
    page_widget.style().polish(page_widget)
    page_widget.update()


def refresh_page_theme(page_widget: QWidget):
    """
    刷新页面主题（主题切换后调用）
    
    Args:
        page_widget: 页面根控件
    """
    # 清除所有硬编码样式
    apply_page_theme(page_widget)
    
    # 强制刷新样式
    page_widget.style().unpolish(page_widget)
    page_widget.style().polish(page_widget)
    
    # 递归刷新所有子控件
    for child in page_widget.findChildren(QWidget):
        child.style().unpolish(child)
        child.style().polish(child)
    
    page_widget.update()


