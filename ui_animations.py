#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
UI动画管理器
提供统一的动画API，确保所有动画流畅、专业、稳定
设计原则：优雅、克制、高性能
"""

from PySide6.QtCore import (
    QPropertyAnimation, QSequentialAnimationGroup,
    QEasingCurve, QObject, QPoint, QSize
)
from PySide6.QtWidgets import QGraphicsOpacityEffect
from core.utils.logger import get_logger


class AnimationManager(QObject):
    """全局动画管理器 - 统一管理所有UI动画"""
    
    # 动画时长配置（单位：毫秒）
    DURATION_INSTANT = 100    # 瞬间动画（快速反馈）
    DURATION_FAST = 200       # 快速动画（按钮交互）
    DURATION_NORMAL = 300     # 标准动画（页面切换）
    DURATION_SLOW = 400       # 慢速动画（展开/收起）
    DURATION_THEME = 500      # 主题切换
    
    # 缓动函数配置
    EASING_STANDARD = QEasingCurve.OutCubic      # 标准缓动（最常用）
    EASING_SMOOTH = QEasingCurve.InOutCubic      # 平滑缓动（大型过渡）
    EASING_BOUNCE = QEasingCurve.OutBack         # 弹性回弹（强调）
    EASING_SHARP = QEasingCurve.OutQuad          # 锐利缓动（快速出现）
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            super().__init__()
            self.logger = get_logger("AnimationManager")
            self.active_animations = []  # 活动动画列表
            self.opacity_effects = {}    # 透明度效果缓存
            self._initialized = True
            self.logger.info("动画管理器已初始化")
    
    # ==================== 基础动画方法 ====================
    
    def fade_in(self, widget, duration=None, callback=None):
        """
        淡入动画
        
        Args:
            widget: 目标组件
            duration: 持续时间（毫秒），None使用默认值
            callback: 动画完成回调
        """
        if not widget:
            return None
        
        duration = duration or self.DURATION_NORMAL
        
        # 获取或创建透明度效果
        effect = self._get_opacity_effect(widget)
        effect.setOpacity(0.0)
        
        # 创建动画
        animation = QPropertyAnimation(effect, b"opacity")
        animation.setDuration(duration)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(self.EASING_STANDARD)
        
        # 确保组件可见
        widget.show()
        
        # 设置完成回调
        if callback:
            animation.finished.connect(callback)
        
        # 自动清理
        animation.finished.connect(lambda: self._cleanup_animation(animation))
        
        self.active_animations.append(animation)
        animation.start()
        
        return animation
    
    def fade_out(self, widget, duration=None, hide_on_finish=True, callback=None):
        """
        淡出动画
        
        Args:
            widget: 目标组件
            duration: 持续时间（毫秒）
            hide_on_finish: 完成后是否隐藏组件
            callback: 动画完成回调
        """
        if not widget:
            return None
        
        duration = duration or self.DURATION_NORMAL
        
        # 获取或创建透明度效果
        effect = self._get_opacity_effect(widget)
        
        # 创建动画
        animation = QPropertyAnimation(effect, b"opacity")
        animation.setDuration(duration)
        animation.setStartValue(effect.opacity())
        animation.setEndValue(0.0)
        animation.setEasingCurve(self.EASING_STANDARD)
        
        # 完成后隐藏
        if hide_on_finish:
            animation.finished.connect(widget.hide)
        
        # 设置完成回调
        if callback:
            animation.finished.connect(callback)
        
        # 自动清理
        animation.finished.connect(lambda: self._cleanup_animation(animation))
        
        self.active_animations.append(animation)
        animation.start()
        
        return animation
    
    def fade_toggle(self, widget, duration=None):
        """切换淡入/淡出"""
        if widget.isVisible():
            return self.fade_out(widget, duration)
        else:
            return self.fade_in(widget, duration)
    
    def slide_in(self, widget, direction='bottom', distance=None, duration=None):
        """
        滑入动画
        
        Args:
            widget: 目标组件
            direction: 方向 'left', 'right', 'top', 'bottom'
            distance: 滑动距离（像素），None自动计算
            duration: 持续时间
        """
        if not widget:
            return None
        
        duration = duration or self.DURATION_NORMAL
        
        # 计算滑动距离
        if distance is None:
            if direction in ['left', 'right']:
                distance = widget.width()
            else:
                distance = widget.height()
        
        # 计算起始和结束位置
        start_pos = widget.pos()
        if direction == 'left':
            start_pos = QPoint(start_pos.x() - distance, start_pos.y())
        elif direction == 'right':
            start_pos = QPoint(start_pos.x() + distance, start_pos.y())
        elif direction == 'top':
            start_pos = QPoint(start_pos.x(), start_pos.y() - distance)
        elif direction == 'bottom':
            start_pos = QPoint(start_pos.x(), start_pos.y() + distance)
        
        end_pos = widget.pos()
        
        # 设置起始位置
        widget.move(start_pos)
        widget.show()
        
        # 创建位置动画
        animation = QPropertyAnimation(widget, b"pos")
        animation.setDuration(duration)
        animation.setStartValue(start_pos)
        animation.setEndValue(end_pos)
        animation.setEasingCurve(self.EASING_STANDARD)
        
        # 同时添加淡入效果（fade_in 内部自管理生命周期，无需保留引用）
        self.fade_in(widget, duration)
        
        # 自动清理
        animation.finished.connect(lambda: self._cleanup_animation(animation))
        
        self.active_animations.append(animation)
        animation.start()
        
        return animation
    
    def shake(self, widget, intensity=10, duration=None):
        """
        摇晃动画（用于错误反馈）
        
        Args:
            widget: 目标组件
            intensity: 摇晃强度（像素）
            duration: 持续时间
        """
        if not widget:
            return None
        
        duration = duration or self.DURATION_FAST
        
        original_pos = widget.pos()
        
        # 创建序列动画
        sequence = QSequentialAnimationGroup()
        
        # 左右摇晃3次
        for i in range(3):
            # 向右
            anim_right = QPropertyAnimation(widget, b"pos")
            anim_right.setDuration(duration // 6)
            anim_right.setStartValue(original_pos)
            anim_right.setEndValue(QPoint(original_pos.x() + intensity, original_pos.y()))
            anim_right.setEasingCurve(QEasingCurve.InOutQuad)
            sequence.addAnimation(anim_right)
            
            # 向左
            anim_left = QPropertyAnimation(widget, b"pos")
            anim_left.setDuration(duration // 6)
            anim_left.setStartValue(QPoint(original_pos.x() + intensity, original_pos.y()))
            anim_left.setEndValue(QPoint(original_pos.x() - intensity, original_pos.y()))
            anim_left.setEasingCurve(QEasingCurve.InOutQuad)
            sequence.addAnimation(anim_left)
        
        # 回到原位
        anim_back = QPropertyAnimation(widget, b"pos")
        anim_back.setDuration(duration // 6)
        anim_back.setStartValue(QPoint(original_pos.x() - intensity, original_pos.y()))
        anim_back.setEndValue(original_pos)
        anim_back.setEasingCurve(QEasingCurve.InOutQuad)
        sequence.addAnimation(anim_back)
        
        # 自动清理
        sequence.finished.connect(lambda: self._cleanup_animation(sequence))
        
        self.active_animations.append(sequence)
        sequence.start()
        
        return sequence
    
    def pulse(self, widget, scale_factor=1.05, duration=None, count=1):
        """
        脉冲动画（用于强调）
        
        Args:
            widget: 目标组件
            scale_factor: 放大倍数
            duration: 单次脉冲时长
            count: 脉冲次数
        """
        if not widget:
            return None
        
        duration = duration or self.DURATION_FAST
        
        # 保存原始大小
        original_size = widget.size()
        scaled_size = QSize(
            int(original_size.width() * scale_factor),
            int(original_size.height() * scale_factor)
        )
        
        # 创建序列动画
        sequence = QSequentialAnimationGroup()
        
        for i in range(count):
            # 放大
            anim_grow = QPropertyAnimation(widget, b"size")
            anim_grow.setDuration(duration // 2)
            anim_grow.setStartValue(original_size)
            anim_grow.setEndValue(scaled_size)
            anim_grow.setEasingCurve(self.EASING_STANDARD)
            sequence.addAnimation(anim_grow)
            
            # 缩小
            anim_shrink = QPropertyAnimation(widget, b"size")
            anim_shrink.setDuration(duration // 2)
            anim_shrink.setStartValue(scaled_size)
            anim_shrink.setEndValue(original_size)
            anim_shrink.setEasingCurve(self.EASING_STANDARD)
            sequence.addAnimation(anim_shrink)
        
        # 自动清理
        sequence.finished.connect(lambda: self._cleanup_animation(sequence))
        
        self.active_animations.append(sequence)
        sequence.start()
        
        return sequence
    
    # ==================== 组合动画方法 ====================
    
    def fade_in_scale(self, widget, duration=None, scale_from=0.95):
        """
        淡入动画（移除缩放，避免布局问题）
        
        Args:
            widget: 目标组件
            duration: 持续时间
            scale_from: 已废弃，保留参数兼容性
        """
        # 直接使用淡入动画，不再使用缩放
        return self.fade_in(widget, duration)
    
    def fade_out_scale(self, widget, duration=None, scale_to=0.95, hide_on_finish=True):
        """
        淡出动画（移除缩放，避免布局问题）
        
        Args:
            widget: 目标组件
            duration: 持续时间
            scale_to: 已废弃，保留参数兼容性
            hide_on_finish: 完成后是否隐藏
        """
        # 直接使用淡出动画，不再使用缩放
        return self.fade_out(widget, duration, hide_on_finish)
    
    # ==================== 辅助方法 ====================
    
    def _get_opacity_effect(self, widget):
        """获取或创建组件的透明度效果"""
        widget_id = id(widget)
        
        if widget_id not in self.opacity_effects:
            effect = QGraphicsOpacityEffect()
            effect.setOpacity(1.0)
            widget.setGraphicsEffect(effect)
            self.opacity_effects[widget_id] = effect
        
        return self.opacity_effects[widget_id]
    
    def _cleanup_animation(self, animation):
        """清理已完成的动画"""
        if animation in self.active_animations:
            self.active_animations.remove(animation)
            animation.deleteLater()
    
    def stop_all(self):
        """停止所有动画"""
        for animation in self.active_animations[:]:
            animation.stop()
            self._cleanup_animation(animation)
        self.logger.info("已停止所有动画")
    
    def cleanup(self):
        """清理所有资源"""
        self.stop_all()
        self.opacity_effects.clear()
        self.logger.info("动画管理器已清理")


# ==================== 全局访问函数 ====================

_animation_manager = None

def get_animation_manager():
    """获取动画管理器单例"""
    global _animation_manager
    if _animation_manager is None:
        _animation_manager = AnimationManager()
    return _animation_manager


def animate_fade_in(widget, duration=None):
    """快捷函数：淡入动画"""
    return get_animation_manager().fade_in(widget, duration)


def animate_fade_out(widget, duration=None):
    """快捷函数：淡出动画"""
    return get_animation_manager().fade_out(widget, duration)


def animate_shake(widget, intensity=10):
    """快捷函数：摇晃动画（错误反馈）"""
    return get_animation_manager().shake(widget, intensity)


def animate_pulse(widget, scale_factor=1.05, count=1):
    """快捷函数：脉冲动画（强调）"""
    return get_animation_manager().pulse(widget, scale_factor, count=count)

