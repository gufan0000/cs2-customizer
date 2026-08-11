#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
UI视觉效果管理器
管理阴影、模糊、发光等视觉效果
设计原则：专业、克制、性能优先
"""

from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsBlurEffect, QWidget
from PySide6.QtGui import QColor
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QEvent, Qt
from core.utils.logger import get_logger


class EffectsManager:
    """视觉效果管理器"""
    
    # 阴影级别配置
    SHADOW_LEVELS = {
        'none': {'blur': 0, 'offset': 0, 'color': (0, 0, 0, 0)},
        'xs': {'blur': 2, 'offset': 1, 'color': (0, 0, 0, 30)},
        'sm': {'blur': 4, 'offset': 2, 'color': (0, 0, 0, 40)},
        'md': {'blur': 8, 'offset': 3, 'color': (0, 0, 0, 50)},
        'lg': {'blur': 12, 'offset': 5, 'color': (0, 0, 0, 60)},
        'xl': {'blur': 20, 'offset': 8, 'color': (0, 0, 0, 70)},
    }
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.logger = get_logger("EffectsManager")
            self.shadow_cache = {}  # 阴影效果缓存
            self.blur_cache = {}    # 模糊效果缓存
            self._initialized = True
            self.logger.info("效果管理器已初始化")
    
    # ==================== 阴影效果 ====================
    
    def apply_shadow(self, widget, level='md', animated=False):
        """
        应用阴影效果
        
        Args:
            widget: 目标组件
            level: 阴影级别 'none', 'xs', 'sm', 'md', 'lg', 'xl'
            animated: 是否动画过渡
        
        Returns:
            QGraphicsDropShadowEffect对象
        """
        if not widget:
            return None
        
        if level not in self.SHADOW_LEVELS:
            self.logger.warning(f"未知的阴影级别: {level}，使用默认值 'md'")
            level = 'md'
        
        config = self.SHADOW_LEVELS[level]
        widget_id = id(widget)
        
        # 获取或创建阴影效果
        if widget_id in self.shadow_cache:
            shadow = self.shadow_cache[widget_id]
        else:
            shadow = QGraphicsDropShadowEffect()
            widget.setGraphicsEffect(shadow)
            self.shadow_cache[widget_id] = shadow
        
        # 应用阴影配置
        if animated and hasattr(shadow, 'blurRadius') and shadow.blurRadius() != config['blur']:
            # 使用动画过渡（暂时简化，直接设置）
            shadow.setBlurRadius(config['blur'])
            shadow.setOffset(0, config['offset'])
            shadow.setColor(QColor(*config['color']))
        else:
            # 直接设置
            shadow.setBlurRadius(config['blur'])
            shadow.setOffset(0, config['offset'])
            shadow.setColor(QColor(*config['color']))
        
        return shadow
    
    def update_shadow_level(self, widget, new_level, duration=200):
        """
        更新组件的阴影级别（带动画过渡）
        
        Args:
            widget: 目标组件
            new_level: 新的阴影级别
            duration: 过渡时长（毫秒）
        """
        if not widget or widget.graphicsEffect() is None:
            self.apply_shadow(widget, new_level)
            return
        
        # 获取当前阴影效果
        shadow = widget.graphicsEffect()
        if not isinstance(shadow, QGraphicsDropShadowEffect):
            self.apply_shadow(widget, new_level)
            return
        
        # 获取目标配置
        if new_level not in self.SHADOW_LEVELS:
            new_level = 'md'
        
        target_config = self.SHADOW_LEVELS[new_level]
        
        # 创建模糊半径动画
        blur_anim = QPropertyAnimation(shadow, b"blurRadius")
        blur_anim.setDuration(duration)
        blur_anim.setStartValue(shadow.blurRadius())
        blur_anim.setEndValue(target_config['blur'])
        blur_anim.setEasingCurve(QEasingCurve.OutCubic)
        
        # 更新颜色和偏移（直接设置，因为这些属性不容易动画）
        shadow.setColor(QColor(*target_config['color']))
        shadow.setOffset(0, target_config['offset'])
        
        blur_anim.start()
    
    def remove_shadow(self, widget):
        """移除组件的阴影效果"""
        if not widget:
            return
        
        widget_id = id(widget)
        if widget_id in self.shadow_cache:
            del self.shadow_cache[widget_id]
        
        widget.setGraphicsEffect(None)
    
    # ==================== 模糊效果 ====================
    
    def apply_blur(self, widget, radius=10):
        """
        应用模糊效果（毛玻璃效果的一部分）
        
        Args:
            widget: 目标组件
            radius: 模糊半径
        
        Returns:
            QGraphicsBlurEffect对象
        """
        if not widget:
            return None
        
        widget_id = id(widget)
        
        # 获取或创建模糊效果
        if widget_id in self.blur_cache:
            blur = self.blur_cache[widget_id]
        else:
            blur = QGraphicsBlurEffect()
            widget.setGraphicsEffect(blur)
            self.blur_cache[widget_id] = blur
        
        blur.setBlurRadius(radius)
        
        return blur
    
    def remove_blur(self, widget):
        """移除组件的模糊效果"""
        if not widget:
            return
        
        widget_id = id(widget)
        if widget_id in self.blur_cache:
            del self.blur_cache[widget_id]
        
        widget.setGraphicsEffect(None)
    
    # ==================== 发光效果 ====================
    
    def apply_glow(self, widget, color=None, radius=15):
        """
        应用发光效果（实际上是带颜色的阴影）
        
        Args:
            widget: 目标组件
            color: 发光颜色（QColor或元组）
            radius: 发光半径
        
        Returns:
            QGraphicsDropShadowEffect对象
        """
        if not widget:
            return None
        
        # 默认使用主题色
        if color is None:
            from theme_manager import get_theme_manager
            theme_manager = get_theme_manager()
            color_str = theme_manager.get_color('accent_primary')
            color = QColor(color_str)
        elif isinstance(color, (tuple, list)):
            color = QColor(*color)
        
        # 创建发光效果（本质是阴影）
        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(radius)
        glow.setOffset(0, 0)  # 发光无偏移
        
        # 设置半透明的颜色
        glow_color = QColor(color)
        glow_color.setAlpha(100)  # 半透明
        glow.setColor(glow_color)
        
        widget.setGraphicsEffect(glow)
        
        return glow
    
    # ==================== 辅助方法 ====================
    
    def cleanup(self):
        """清理所有缓存"""
        self.shadow_cache.clear()
        self.blur_cache.clear()
        self.logger.info("效果管理器已清理")


# ==================== 全局访问函数 ====================

_effects_manager = None

def get_effects_manager():
    """获取效果管理器单例"""
    global _effects_manager
    if _effects_manager is None:
        _effects_manager = EffectsManager()
    return _effects_manager


def apply_shadow(widget, level='md'):
    """快捷函数：应用阴影"""
    return get_effects_manager().apply_shadow(widget, level)


def apply_glow(widget, color=None, radius=15):
    """快捷函数：应用发光效果"""
    return get_effects_manager().apply_glow(widget, color, radius)


def apply_blur(widget, radius=10):
    """快捷函数：应用模糊效果"""
    return get_effects_manager().apply_blur(widget, radius)


class ScrollShadow(QWidget):
    """滚动区域顶部阴影指示器 — 有内容被滚走时显示"""

    def __init__(self, scroll_area, parent=None):
        super().__init__(parent or scroll_area)
        self._scroll_area = scroll_area
        self._opacity = 0.0
        self.setFixedHeight(4)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.raise_()

        # 监听滚动
        vbar = scroll_area.verticalScrollBar()
        if vbar:
            vbar.valueChanged.connect(self._on_scroll)

        # UP-032: 必须监听**滚动区**的尺寸变化，不是自己的。
        # 原来只重写了本控件的 resizeEvent —— 而本控件只有在 _reposition()
        # 把它拉宽时才会 resize，纯自循环。窗口放大时滚动区变宽了，
        # 阴影条却还停在安装那一刻的宽度上，于是顶部只剩一小截阴影。
        scroll_area.installEventFilter(self)

        self._reposition()

    def eventFilter(self, watched, event):
        if watched is self._scroll_area and event.type() == QEvent.Resize:
            self._reposition()
        return super().eventFilter(watched, event)

    def _reposition(self):
        self.setGeometry(0, 0, self._scroll_area.width(), 4)

    def _on_scroll(self, value):
        target = 1.0 if value > 0 else 0.0
        if abs(self._opacity - target) > 0.01:
            self._opacity = target
            self.update()

    def paintEvent(self, event):
        if self._opacity <= 0.01:
            return
        from PySide6.QtGui import QPainter, QLinearGradient
        p = QPainter(self)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0, QColor(0, 0, 0, 30))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), grad)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition()


def install_scroll_shadow(scroll_area):
    """为 QScrollArea 安装顶部滚动阴影"""
    if hasattr(scroll_area, '_scroll_shadow_installed'):
        return
    scroll_area._scroll_shadow_installed = True
    shadow = ScrollShadow(scroll_area)
    scroll_area._scroll_shadow = shadow


