"""
iOS 风格开关组件
滑块滑动 + 背景色渐变，与 QCheckBox API 兼容
"""

from PySide6.QtCore import (
    Qt, Signal, Property, QPropertyAnimation, QEasingCurve,
    QVariantAnimation, QSize, QRectF
)
from PySide6.QtGui import QPainter, QColor, QPainterPath
from PySide6.QtWidgets import QWidget
from theme_manager import get_theme_manager


class ToggleSwitch(QWidget):
    """iOS 风格的开关组件"""

    toggled = Signal(bool)

    # 尺寸常量
    WIDTH = 44
    HEIGHT = 24
    KNOB_MARGIN = 2
    KNOB_SIZE = 20  # HEIGHT - 2 * KNOB_MARGIN

    def __init__(self, parent=None, checked=False):
        super().__init__(parent)
        self._checked = checked
        self._knob_x = float(self.WIDTH - self.KNOB_MARGIN - self.KNOB_SIZE if checked else self.KNOB_MARGIN)
        self._bg_color = QColor()

        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

        # 主题颜色
        self._tm = get_theme_manager()
        self._update_colors()
        self._tm.register_theme_changed_callback(self._on_theme_changed)

        # 滑块位置动画
        self._knob_anim = QPropertyAnimation(self, b"knob_x")
        self._knob_anim.setDuration(150)
        self._knob_anim.setEasingCurve(QEasingCurve.OutCubic)

        # 背景色动画
        self._bg_anim = QVariantAnimation()
        self._bg_anim.setDuration(150)
        self._bg_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._bg_anim.valueChanged.connect(self._on_bg_color_changed)

    # ========== 公开 API（兼容 QCheckBox） ==========

    def isChecked(self):
        return self._checked

    def setChecked(self, checked, animated=True):
        if self._checked == checked:
            return
        self._checked = checked
        if animated:
            self._animate(checked)
        else:
            self._knob_x = float(self.WIDTH - self.KNOB_MARGIN - self.KNOB_SIZE if checked else self.KNOB_MARGIN)
            self._update_colors()
            self.update()

    def toggle(self):
        self.setChecked(not self._checked)
        self.toggled.emit(self._checked)

    # ========== Qt Property 用于动画 ==========

    def _get_knob_x(self):
        return self._knob_x

    def _set_knob_x(self, val):
        self._knob_x = val
        self.update()

    knob_x = Property(float, _get_knob_x, _set_knob_x)

    # ========== 内部方法 ==========

    def _update_colors(self):
        colors = self._tm.current_theme.colors
        # v4: 启用态用 accent 但降亮度（避免一片 toggle 像霓虹灯）
        accent = QColor(colors.accent_primary)
        # 略向 bg 混合 12%，让色相保留但饱和度降低
        bg = QColor(colors.bg_primary)
        mixed = QColor(
            int(accent.red() * 0.88 + bg.red() * 0.12),
            int(accent.green() * 0.88 + bg.green() * 0.12),
            int(accent.blue() * 0.88 + bg.blue() * 0.12),
        )
        self._color_on = mixed
        self._color_off = QColor(colors.border_primary)
        self._bg_color = QColor(self._color_on if self._checked else self._color_off)

    def _on_theme_changed(self):
        self._update_colors()
        self.update()

    def _on_bg_color_changed(self, color):
        self._bg_color = color
        self.update()

    def _animate(self, checked):
        # 滑块位置
        self._knob_anim.stop()
        self._knob_anim.setStartValue(self._knob_x)
        end_x = float(self.WIDTH - self.KNOB_MARGIN - self.KNOB_SIZE if checked else self.KNOB_MARGIN)
        self._knob_anim.setEndValue(end_x)
        self._knob_anim.start()

        # 背景色
        self._bg_anim.stop()
        self._bg_anim.setStartValue(QColor(self._bg_color))
        self._bg_anim.setEndValue(QColor(self._color_on if checked else self._color_off))
        self._bg_anim.start()

    # ========== 事件 ==========

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # 背景圆角矩形
        bg_path = QPainterPath()
        bg_path.addRoundedRect(QRectF(0, 0, self.WIDTH, self.HEIGHT), self.HEIGHT / 2, self.HEIGHT / 2)
        p.fillPath(bg_path, self._bg_color)

        # 白色圆形滑块
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QRectF(self._knob_x, self.KNOB_MARGIN, self.KNOB_SIZE, self.KNOB_SIZE))

    def sizeHint(self):
        return QSize(self.WIDTH, self.HEIGHT)

    def deleteLater(self):
        try:
            self._tm.unregister_theme_changed_callback(self._on_theme_changed)
        except Exception:
            pass
        super().deleteLater()
