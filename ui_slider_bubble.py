# SPDX-License-Identifier: GPL-3.0-or-later
"""
滑块数值气泡
拖动 QSlider 时在手柄上方显示当前数值
"""

from PySide6.QtCore import (
    Qt, Property, QPropertyAnimation, QEasingCurve, QPoint, QRectF
)
from PySide6.QtGui import QPainter, QColor, QFont, QPainterPath, QFontMetrics
from PySide6.QtWidgets import QWidget
from theme_manager import get_theme_manager


class SliderBubble(QWidget):
    """浮动在滑块手柄上方的数值气泡"""

    ARROW_H = 5
    PADDING_H = 8
    PADDING_V = 4
    RADIUS = 6

    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)

        self._opacity = 0.0
        self._text = ""
        self._font = QFont("Microsoft YaHei", 10, QFont.Bold)
        self._tm = get_theme_manager()

        # 淡入淡出动画
        self._fade_anim = QPropertyAnimation(self, b"bubble_opacity")
        self._fade_anim.setDuration(100)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)

    def show_value(self, text, global_pos):
        """显示气泡并定位"""
        self._text = str(text)
        fm = QFontMetrics(self._font)
        tw = fm.horizontalAdvance(self._text)
        th = fm.height()
        w = tw + self.PADDING_H * 2
        h = th + self.PADDING_V * 2 + self.ARROW_H
        self.setFixedSize(w, h)
        # 气泡居中在手柄上方，箭头指向手柄
        self.move(global_pos.x() - w // 2, global_pos.y() - h - 4)
        if not self.isVisible():
            self.show()
            self._fade_to(1.0)
        self.update()

    def hide_bubble(self):
        """淡出并隐藏"""
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_fade_out_done)
        self._fade_anim.start()

    def _on_fade_out_done(self):
        self._fade_anim.finished.disconnect(self._on_fade_out_done)
        self.hide()

    def _fade_to(self, target):
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(target)
        self._fade_anim.start()

    # ========== Property ==========

    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, val):
        self._opacity = val
        self.update()

    bubble_opacity = Property(float, _get_opacity, _set_opacity)

    # ========== 绘制 ==========

    def paintEvent(self, event):
        if self._opacity <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._opacity)

        colors = self._tm.current_theme.colors
        bg = QColor(colors.accent_primary)

        w, h = self.width(), self.height()
        body_h = h - self.ARROW_H

        # 圆角矩形主体
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, body_h), self.RADIUS, self.RADIUS)

        # 底部小三角
        arrow_x = w / 2
        path.moveTo(arrow_x - 4, body_h)
        path.lineTo(arrow_x, h)
        path.lineTo(arrow_x + 4, body_h)

        p.fillPath(path, bg)

        # 文字
        p.setPen(QColor(255, 255, 255))
        p.setFont(self._font)
        p.drawText(QRectF(0, 0, w, body_h), Qt.AlignCenter, self._text)


def _get_handle_global_pos(slider):
    """计算滑块手柄在屏幕上的中心位置"""
    style = slider.style()
    groove_rect = style.subControlRect(
        style.ComplexControl.CC_Slider, _make_option(slider),
        style.SubControl.SC_SliderHandle, slider
    )
    center = groove_rect.center()
    return slider.mapToGlobal(QPoint(center.x(), groove_rect.top()))


def _make_option(slider):
    """构造 QStyleOptionSlider"""
    from PySide6.QtWidgets import QStyleOptionSlider
    opt = QStyleOptionSlider()
    slider.initStyleOption(opt)
    return opt


# ========== 安装函数 ==========

def install_slider_bubble(slider, format_func=None):
    """
    为 QSlider 安装数值气泡。
    format_func: 可选，接收 int 返回 str，自定义显示格式。
    """
    if hasattr(slider, '_bubble_installed'):
        return
    slider._bubble_installed = True

    bubble = SliderBubble()
    slider._value_bubble = bubble

    fmt = format_func or str

    # 保存原始事件处理
    orig_press = slider.mousePressEvent
    orig_move = slider.mouseMoveEvent
    orig_release = slider.mouseReleaseEvent

    def on_press(event):
        orig_press(event)
        pos = _get_handle_global_pos(slider)
        bubble.show_value(fmt(slider.value()), pos)

    def on_move(event):
        orig_move(event)
        if event.buttons() & Qt.LeftButton:
            pos = _get_handle_global_pos(slider)
            bubble.show_value(fmt(slider.value()), pos)

    def on_release(event):
        orig_release(event)
        bubble.hide_bubble()

    slider.mousePressEvent = on_press
    slider.mouseMoveEvent = on_move
    slider.mouseReleaseEvent = on_release

    # 也监听 valueChanged（键盘操作等）
    def on_value_changed(val):
        if bubble.isVisible():
            pos = _get_handle_global_pos(slider)
            bubble.show_value(fmt(val), pos)

    slider.valueChanged.connect(on_value_changed)
