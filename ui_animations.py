#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
UI动画管理器
提供统一的动画API，确保所有动画流畅、专业、稳定
设计原则：优雅、克制、高性能
"""

from PySide6.QtCore import QObject
from core.utils.logger import get_logger


class AnimationManager(QObject):
    """全局动画管理器 - 统一管理所有UI动画"""
    
    # MusicControlBar 仍取用单例；这里只保留实例与清理接口。
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


    # ==================== 辅助方法 ====================
    
    
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
