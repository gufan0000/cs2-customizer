#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
涟漪效果组件（Material Design Ripple Effect）
为按钮和交互元素提供现代化的点击反馈
设计原则：轻量、流畅、不影响布局
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QPoint, Property, Qt
from PySide6.QtGui import QPainter, QColor
from core.utils.logger import get_logger


class RippleEffect(QWidget):
    """涟漪效果组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("RippleEffect")
        
        # 设置为透明叠加层
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 涟漪参数
        self._radius = 0
        self._opacity = 0.3
        self._center = QPoint(0, 0)
        self._color = QColor(255, 255, 255, 76)  # 半透明白色
        
        # 动画
        self.radius_animation = None
        self.opacity_animation = None
        
        # 隐藏直到触发
        self.hide()
    
    def start_ripple(self, pos, color=None, max_radius=None):
        """
        启动涟漪动画
        
        Args:
            pos: 点击位置（QPoint）
            color: 涟漪颜色（可选）
            max_radius: 最大半径（可选，默认为组件对角线长度）
        """
        # 设置中心点
        self._center = pos
        
        # 设置颜色
        if color:
            self._color = color
        
        # 计算最大半径（到组件最远角的距离）
        if max_radius is None:
            max_radius = max(
                (self.width() ** 2 + self.height() ** 2) ** 0.5,
                200  # 最小半径
            )
        
        # 重置参数
        self._radius = 0
        self._opacity = 0.3
        
        # 显示组件
        self.show()
        self.raise_()  # 置于顶层
        
        # 停止旧动画
        if self.radius_animation:
            self.radius_animation.stop()
        if self.opacity_animation:
            self.opacity_animation.stop()
        
        # 创建半径扩散动画
        self.radius_animation = QPropertyAnimation(self, b"radius")
        self.radius_animation.setDuration(400)
        self.radius_animation.setStartValue(0)
        self.radius_animation.setEndValue(max_radius)
        self.radius_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        # 创建透明度淡出动画
        self.opacity_animation = QPropertyAnimation(self, b"opacity")
        self.opacity_animation.setDuration(400)
        self.opacity_animation.setStartValue(0.3)
        self.opacity_animation.setEndValue(0.0)
        self.opacity_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        # 动画完成后隐藏
        self.opacity_animation.finished.connect(self.hide)
        
        # 启动动画
        self.radius_animation.start()
        self.opacity_animation.start()
    
    def paintEvent(self, event):
        """绘制涟漪"""
        if self._radius <= 0 or self._opacity <= 0:
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 设置颜色和透明度
        color = QColor(self._color)
        color.setAlphaF(self._opacity)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        
        # 绘制圆形涟漪
        painter.drawEllipse(
            self._center,
            int(self._radius),
            int(self._radius)
        )
    
    # Property定义（用于动画）
    def get_radius(self):
        return self._radius
    
    def set_radius(self, value):
        self._radius = value
        self.update()  # 触发重绘
    
    radius = Property(float, get_radius, set_radius)
    
    def get_opacity(self):
        return self._opacity
    
    def set_opacity(self, value):
        self._opacity = value
        self.update()
    
    opacity = Property(float, get_opacity, set_opacity)


def add_ripple_effect(widget, color=None):
    """
    为widget添加涟漪效果
    
    Args:
        widget: 目标组件（通常是按钮）
        color: 涟漪颜色（可选）
    
    Returns:
        RippleEffect实例
    """
    # 创建涟漪效果
    ripple = RippleEffect(widget)
    ripple.setGeometry(widget.rect())
    
    # 设置颜色
    if color:
        ripple._color = color
    
    # 重写widget的mousePressEvent
    original_mouse_press = widget.mousePressEvent
    
    def new_mouse_press(event):
        # 触发涟漪
        ripple.start_ripple(event.pos(), color)
        # 调用原始事件处理
        original_mouse_press(event)
    
    widget.mousePressEvent = new_mouse_press
    
    # 当widget大小改变时，调整ripple大小
    original_resize = widget.resizeEvent
    
    def new_resize(event):
        ripple.setGeometry(widget.rect())
        original_resize(event)
    
    widget.resizeEvent = new_resize
    
    return ripple

