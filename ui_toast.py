#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Toast通知系统
提供现代化的提示信息显示
设计原则：优雅、简洁、不干扰
"""

from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QGraphicsDropShadowEffect
from PySide6.QtCore import QTimer, QPropertyAnimation, QEasingCurve, Qt, Signal
from PySide6.QtGui import QFont, QColor
from core.utils.logger import get_logger
from ui_design_system import get_design_system
from theme_manager import get_color


class Toast(QWidget):
    """Toast通知组件"""

    # R4/UP-026: 淡出结束时发这个信号，让管理器回收自己。
    # 原来管理器是去连 `toast.hide_animation.finished` —— 但那个动画对象要到
    # `fade_out()` 里才创建，连接那一刻它还是 None，于是**回收回调从来没连上过**：
    # `ToastManager.toasts` 只增不减，每来一条新 toast 就往下挪 70px，
    # 十几条之后直接飘出屏幕外。用信号就不依赖对象的创建时机了。
    dismissed = Signal()

    # Toast类型
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"

    @staticmethod
    def _hex_to_rgba(hex_color, alpha=0.95):
        """将hex颜色转为rgba字符串"""
        c = QColor(hex_color)
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("Toast")
        
        # 设置为浮动窗口
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        # UI设置 - 自适应尺寸
        self.setMinimumWidth(300)
        self.setMaximumWidth(450)
        
        # 创建布局
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(12)
        
        # 图标标签
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFont(QFont("Segoe UI Emoji", 16))
        layout.addWidget(self.icon_label)
        
        # 消息标签
        self.message_label = QLabel()
        self.message_label.setFont(QFont("Microsoft YaHei", 12))
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label, 1)

        # R1-7: 可选动作按钮(撤销等);默认隐藏
        from PySide6.QtWidgets import QPushButton

        self.action_button = QPushButton()
        self.action_button.setVisible(False)
        self.action_button.setCursor(Qt.PointingHandCursor)
        self.action_button.setFixedHeight(28)
        self._action_callback = None
        self.action_button.clicked.connect(self._on_action_clicked)
        layout.addWidget(self.action_button)
        
        # 添加阴影
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
        
        # 动画
        self.show_animation = None
        self.hide_animation = None
        
        # 自动隐藏定时器
        self.hide_timer = QTimer()
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.fade_out)
    
    def _on_action_clicked(self):
        """动作按钮:回调一次后立即收起(防双击重复撤销)。"""
        cb, self._action_callback = self._action_callback, None
        self.action_button.setEnabled(False)
        if cb is not None:
            try:
                cb()
            except Exception:
                self.logger.exception("toast 动作回调失败")
        self.fade_out()

    def show_message(self, message, toast_type=INFO, duration=3000,
                     action_text=None, action_callback=None):
        """
        显示Toast消息
        
        Args:
            message: 消息文本
            toast_type: 类型（info/success/warning/error）
            duration: 显示时长（毫秒），0表示不自动隐藏
            action_text: 动作按钮文字(如「撤销」);None=无按钮
            action_callback: 点击动作按钮的回调(只触发一次)
        """
        # 设置消息
        self.message_label.setText(message)

        # R1-7: 动作按钮
        self._action_callback = action_callback if action_text else None
        self.action_button.setText(str(action_text or ""))
        self.action_button.setEnabled(True)
        self.action_button.setVisible(bool(action_text))
        
        # 根据类型设置样式
        status_color = get_color('info')
        if toast_type == self.SUCCESS:
            self.icon_label.setText("✓")
            status_color = get_color('success')
        elif toast_type == self.WARNING:
            self.icon_label.setText("⚠")
            status_color = get_color('warning')
        elif toast_type == self.ERROR:
            self.icon_label.setText("✕")
            status_color = get_color('error')
        else:  # INFO
            self.icon_label.setText("ℹ")
            status_color = get_color('info')

        bg_color = self._hex_to_rgba(get_color('bg_secondary'), 0.92)
        text_color = get_color('text_primary')
        icon_color = status_color

        # 应用样式
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_color};
                border-radius: 10px;
                border-left: 3px solid {status_color};
            }}
            QLabel {{
                color: {text_color};
                background: transparent;
                border: none;
            }}
        """)
        self.icon_label.setStyleSheet(f"color: {icon_color}; border: none;")
        self.action_button.setStyleSheet(
            f"QPushButton {{ color: {status_color}; background: transparent;"
            f" border: 1px solid {status_color}; border-radius: 6px;"
            " padding: 2px 12px; font-weight: 600; }"
            f" QPushButton:hover {{ background: {self._hex_to_rgba(status_color, 0.15)}; }}"
        )
        
        # 自适应内容高度
        self.adjustSize()

        # 显示动画
        self.fade_in()
        
        # 设置自动隐藏
        if duration > 0:
            self.hide_timer.start(duration)
    
    def fade_in(self):
        """淡入动画"""
        # 停止旧动画
        if self.show_animation:
            self.show_animation.stop()
        if self.hide_animation:
            self.hide_animation.stop()
        
        # 设置初始透明度
        self.setWindowOpacity(0.0)
        self.show()
        
        # 创建淡入动画
        self.show_animation = QPropertyAnimation(self, b"windowOpacity")
        self.show_animation.setDuration(get_design_system().motion.base)
        self.show_animation.setStartValue(0.0)
        self.show_animation.setEndValue(1.0)
        self.show_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.show_animation.start()
    
    def fade_out(self):
        """淡出动画"""
        # 停止自动隐藏定时器
        self.hide_timer.stop()
        
        # 停止旧动画
        if self.show_animation:
            self.show_animation.stop()
        if self.hide_animation:
            self.hide_animation.stop()
        
        # 创建淡出动画
        self.hide_animation = QPropertyAnimation(self, b"windowOpacity")
        self.hide_animation.setDuration(get_design_system().motion.fast)
        self.hide_animation.setStartValue(self.windowOpacity())
        self.hide_animation.setEndValue(0.0)
        self.hide_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.hide_animation.finished.connect(self.hide)
        self.hide_animation.finished.connect(self.dismissed.emit)
        self.hide_animation.start()


class ToastManager:
    """Toast管理器（单例）"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.logger = get_logger("ToastManager")
            self.toasts = []
            self.parent_widget = None
            self._initialized = True
    
    def set_parent(self, parent):
        """设置父窗口"""
        self.parent_widget = parent
    
    # 同屏最多堆几条。超出就把最老的一条提前收掉——
    # 第 4 条往下偏移 210px，已经盖住页面主要内容了。
    MAX_VISIBLE = 3

    def show(self, message, toast_type=Toast.INFO, duration=3000,
             action_text=None, action_callback=None):
        """显示Toast"""
        if not self.parent_widget:
            self.logger.warning("ToastManager未设置parent widget")
            return

        # 超出同屏上限：先请最老的一条淡出（它淡出完会自己走 dismissed 回收）
        while len(self.toasts) >= self.MAX_VISIBLE:
            oldest = self.toasts[0]
            try:
                oldest.fade_out()
            except RuntimeError:
                pass
            # fade_out 是异步的，这里立刻从堆叠里摘掉，避免新 toast 继续往下堆
            self.toasts.pop(0)

        # 创建Toast
        toast = Toast(self.parent_widget)

        # 先出内容再定位：show_message() 里会 adjustSize()，
        # 在那之前 toast.width() 还是构造期的默认宽度，拿它算居中必然偏左。
        toast.show_message(message, toast_type, duration,
                           action_text=action_text, action_callback=action_callback)

        # 计算位置（父窗口顶部居中）
        parent_geo = self.parent_widget.geometry()
        toast_x = parent_geo.x() + (parent_geo.width() - toast.width()) // 2
        toast_y = parent_geo.y() + 20 + len(self.toasts) * 70
        toast.move(toast_x, toast_y)

        # 添加到列表
        self.toasts.append(toast)

        # 淡出结束后回收。连的是 Toast 自己的 dismissed 信号而不是
        # `hide_animation.finished` —— 后者在这一刻还不存在（见 Toast.dismissed 注释）。
        toast.dismissed.connect(lambda t=toast: self._recycle(t))

        return toast

    def _recycle(self, toast):
        """toast 淡出完毕：出列 + 让剩下的补位，不留空档。"""
        if toast in self.toasts:
            self.toasts.remove(toast)
        try:
            toast.deleteLater()
        except RuntimeError:
            pass
        self._restack()

    def _restack(self):
        """重排剩余 toast 的纵向位置。

        不重排的话，中间一条先消失会留下一个 70px 的空洞，
        后面的 toast 就一直挂在原来的位置上。
        """
        if not self.parent_widget:
            return
        try:
            parent_geo = self.parent_widget.geometry()
        except RuntimeError:
            return
        for i, t in enumerate(list(self.toasts)):
            try:
                t.move(parent_geo.x() + (parent_geo.width() - t.width()) // 2,
                       parent_geo.y() + 20 + i * 70)
            except RuntimeError:
                # 已被销毁的从列表里剔掉
                if t in self.toasts:
                    self.toasts.remove(t)
    
    def info(self, message, duration=3000):
        """显示信息Toast"""
        return self.show(message, Toast.INFO, duration)
    
    def success(self, message, duration=3000):
        """显示成功Toast"""
        return self.show(message, Toast.SUCCESS, duration)
    
    def warning(self, message, duration=3000):
        """显示警告Toast"""
        return self.show(message, Toast.WARNING, duration)
    
    def error(self, message, duration=3000):
        """显示错误Toast"""
        return self.show(message, Toast.ERROR, duration)


# 全局访问函数
def get_toast_manager():
    """获取Toast管理器单例"""
    return ToastManager()


def show_toast(message, toast_type=Toast.INFO, duration=3000):
    """快捷函数：显示Toast"""
    return get_toast_manager().show(message, toast_type, duration)


def toast_info(message, duration=3000):
    """快捷函数：信息Toast"""
    return get_toast_manager().info(message, duration)


def toast_success(message, duration=3000):
    """快捷函数：成功Toast"""
    return get_toast_manager().success(message, duration)


def toast_warning(message, duration=3000):
    """快捷函数：警告Toast"""
    return get_toast_manager().warning(message, duration)


def toast_error(message, duration=3000):
    """快捷函数：错误Toast"""
    return get_toast_manager().error(message, duration)


def toast_undo(message, on_undo, duration=8000):
    """R1-7 快捷函数:带「撤销」按钮的 toast(8 秒窗口,回调只触发一次)。"""
    return get_toast_manager().show(
        message, Toast.INFO, duration,
        action_text="撤销", action_callback=on_undo,
    )


