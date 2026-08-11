#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
微光动画效果（Shimmer Effect）
为UI元素添加高光扫过的动画效果
设计原则：微妙、优雅、不干扰
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer, Property, Qt
from PySide6.QtGui import QPainter, QLinearGradient, QColor, QPen
from core.utils.logger import get_logger


class ShimmerEffect(QWidget):
    """微光动画组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("ShimmerEffect")
        
        # 设置为透明叠加层
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 微光参数
        self._position = -1.0  # 微光位置（-1到1）
        self._color = QColor(255, 255, 255, 25)  # 微光颜色（半透明白色）
        self._width = 0.3  # 微光宽度（相对于组件宽度）
        
        # 动画
        self.animation = None
        self.is_running = False
        
        # 隐藏直到触发
        self.hide()
    
    def start_shimmer(self, duration=2000, delay=0, loop=False):
        """
        启动微光动画
        
        Args:
            duration: 动画时长（毫秒）
            delay: 延迟启动（毫秒）
            loop: 是否循环播放
        """
        if delay > 0:
            QTimer.singleShot(delay, lambda: self._start_animation(duration, loop))
        else:
            self._start_animation(duration, loop)
    
    def _start_animation(self, duration, loop):
        """内部：启动动画"""
        # 停止旧动画
        if self.animation:
            self.animation.stop()
        
        # 重置位置
        self._position = -1.0
        
        # 显示组件
        self.show()
        self.raise_()
        
        # 创建动画
        self.animation = QPropertyAnimation(self, b"position")
        self.animation.setDuration(duration)
        self.animation.setStartValue(-1.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Linear)
        
        # 如果循环，动画完成后重新开始
        if loop:
            self.animation.finished.connect(lambda: self._start_animation(duration, loop))
        else:
            self.animation.finished.connect(self.hide)
        
        # 启动动画
        self.animation.start()
        self.is_running = True
    
    def stop_shimmer(self):
        """停止微光动画"""
        if self.animation:
            self.animation.stop()
        self.is_running = False
        self.hide()
    
    def paintEvent(self, event):
        """绘制微光"""
        if not self.isVisible():
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 计算微光的实际位置（像素）
        widget_width = self.width()
        widget_height = self.height()
        
        # 微光中心位置
        center_x = (self._position + 1) / 2 * widget_width
        
        # 微光宽度
        shimmer_width = widget_width * self._width
        
        # 创建线性渐变（微光效果）
        gradient = QLinearGradient(
            center_x - shimmer_width / 2, 0,
            center_x + shimmer_width / 2, 0
        )
        
        # 设置渐变色（从透明→白色→透明）
        transparent = QColor(255, 255, 255, 0)
        gradient.setColorAt(0.0, transparent)
        gradient.setColorAt(0.5, self._color)
        gradient.setColorAt(1.0, transparent)
        
        # 绘制微光
        painter.setPen(QPen(Qt.NoPen))
        painter.setBrush(gradient)
        painter.drawRect(0, 0, widget_width, widget_height)
    
    # Property定义（用于动画）
    def get_position(self):
        return self._position
    
    def set_position(self, value):
        self._position = value
        self.update()  # 触发重绘
    
    position = Property(float, get_position, set_position)


def add_shimmer_effect(widget, duration=2000, delay=0, loop=False, trigger_on_show=True):
    """
    为widget添加微光效果
    
    Args:
        widget: 目标组件
        duration: 动画时长（毫秒）
        delay: 延迟启动（毫秒）
        loop: 是否循环播放
        trigger_on_show: 是否在显示时自动触发
    
    Returns:
        ShimmerEffect实例
    """
    # 创建微光效果
    shimmer = ShimmerEffect(widget)
    shimmer.setGeometry(widget.rect())
    
    # 如果设置了自动触发
    if trigger_on_show:
        original_show = widget.showEvent
        
        def new_show(event):
            shimmer.start_shimmer(duration, delay, loop)
            original_show(event)
        
        widget.showEvent = new_show
    
    # 当widget大小改变时，调整shimmer大小
    original_resize = widget.resizeEvent
    
    def new_resize(event):
        shimmer.setGeometry(widget.rect())
        original_resize(event)
    
    widget.resizeEvent = new_resize
    
    return shimmer


def add_shimmer_on_hover(widget, duration=1500):
    """
    为widget添加hover触发的微光效果
    
    Args:
        widget: 目标组件
        duration: 动画时长（毫秒）
    
    Returns:
        ShimmerEffect实例
    """
    shimmer = add_shimmer_effect(widget, duration, trigger_on_show=False)
    
    # 在hover时触发
    original_enter = widget.enterEvent
    
    def new_enter(event):
        if not shimmer.is_running:
            shimmer.start_shimmer(duration, delay=0, loop=False)
        original_enter(event)
    
    widget.enterEvent = new_enter
    
    return shimmer


