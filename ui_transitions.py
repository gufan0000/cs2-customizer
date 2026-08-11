#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
页面过渡系统
设计原则：干净利落，不干扰用户

注意：不使用 QGraphicsOpacityEffect，因为它会覆盖页面内卡片的
QGraphicsDropShadowEffect（Qt 每个 widget 只能有一个 GraphicsEffect）。
"""

from PySide6.QtCore import QEasingCurve
from core.utils.logger import get_logger


class PageTransitionManager:
    """页面过渡管理器 — 即时切换，不做多余动画"""

    def __init__(self, stacked_widget):
        self.stack = stacked_widget
        self.logger = get_logger("PageTransition")
        self.current_animation = None
        self.is_animating = False
        from ui_design_system import get_design_system
        self.duration = get_design_system().motion.base
        self.easing = QEasingCurve.OutCubic
        self.logger.info("页面过渡管理器已初始化")

    def switch_page(self, new_widget, transition_type='fade_scale'):
        if not new_widget:
            return
        old_widget = self.stack.currentWidget()
        if old_widget == new_widget:
            return
        self.stack.setCurrentWidget(new_widget)

    def set_duration(self, duration):
        self.duration = max(100, min(1000, duration))

    def set_easing(self, easing):
        self.easing = easing

    def cleanup(self):
        if self.current_animation:
            self.current_animation.stop()
            self.current_animation = None
        self.is_animating = False
        self.logger.info("页面过渡管理器已清理")


def create_page_transition(stacked_widget):
    return PageTransitionManager(stacked_widget)
