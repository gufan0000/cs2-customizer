"""闪光效果实时预览组件 — 在闪光页基础设置 tab 下方实时显示当前参数效果。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QLinearGradient, QFont
from PySide6.QtWidgets import QSizePolicy, QWidget


COLOR_MAP = {
    "白色": "#ffffff",
    "黑色": "#000000",
    "红色": "#ef4444",
    "绿色": "#10b981",
    "蓝色": "#3b82f6",
    "黄色": "#fde047",
    "青色": "#22d3ee",
    "品红": "#e879f9",
    "橙色": "#fb923c",
}


class FlashPreviewWidget(QWidget):
    """闪光实时预览：模拟游戏画面 + 当前参数闪光叠层。"""

    triggered = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)

        self._bg_color_name = "白色"
        self._opacity_pct = 75
        self._fade_in = True
        self._fade_out = True

        # 用 _flash_alpha 做"试触发"的淡入淡出动画
        self._flash_alpha = 1.0
        self._anim = QPropertyAnimation(self, b"flashAlpha")
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    # ---------- Property: flashAlpha (用于动画) ----------
    def _get_flash_alpha(self) -> float:
        return self._flash_alpha

    def _set_flash_alpha(self, v: float) -> None:
        self._flash_alpha = v
        self.update()

    flashAlpha = Property(float, _get_flash_alpha, _set_flash_alpha)

    # ---------- Public API ----------
    def update_settings(
        self,
        *,
        bg_color: str | None = None,
        opacity_pct: int | None = None,
        fade_in: bool | None = None,
        fade_out: bool | None = None,
    ) -> None:
        if bg_color is not None:
            self._bg_color_name = bg_color
        if opacity_pct is not None:
            self._opacity_pct = max(0, min(100, int(opacity_pct)))
        if fade_in is not None:
            self._fade_in = bool(fade_in)
        if fade_out is not None:
            self._fade_out = bool(fade_out)
        self.update()

    def trigger_preview(self) -> None:
        """模拟一次淡入 + 短暂保持 + 淡出（点击触发）。"""
        if self._anim.state() == QPropertyAnimation.Running:
            self._anim.stop()
        # 起点 0、瞬间到 1、保持后回到 1（基础显示态）
        self._flash_alpha = 0.0
        if self._fade_in:
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.setDuration(180)
            self._anim.start()
        else:
            self._flash_alpha = 1.0
            self.update()
        self.triggered.emit()

    def reset_visible(self) -> None:
        self._flash_alpha = 1.0
        self.update()

    # ---------- Events ----------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.trigger_preview()
        super().mousePressEvent(event)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)

        # 1) 模拟游戏背景（顶部稍亮渐变到底部深色）
        bg = QLinearGradient(0, 0, 0, rect.height())
        bg.setColorAt(0, QColor("#1c1f25"))
        bg.setColorAt(1, QColor("#0a0c10"))
        painter.fillRect(rect, bg)

        # 2) 微噪点装饰（几条暗色横线模拟"地平线"）
        painter.setPen(QPen(QColor(60, 65, 75, 140), 1))
        h = rect.height()
        for ratio in (0.32, 0.48, 0.64, 0.78):
            y = int(rect.top() + h * ratio)
            painter.drawLine(rect.left() + 16, y, rect.right() - 16, y)

        # 3) 简易十字准心（中央）
        cx = rect.center().x()
        cy = rect.center().y()
        painter.setPen(QPen(QColor("#10b981"), 2))
        painter.drawLine(cx - 14, cy, cx - 5, cy)
        painter.drawLine(cx + 5, cy, cx + 14, cy)
        painter.drawLine(cx, cy - 14, cx, cy - 5)
        painter.drawLine(cx, cy + 5, cx, cy + 14)
        # 中心点
        painter.setBrush(QColor("#10b981"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(cx - 1, cy - 1, 2, 2)

        # 4) 闪光叠层
        flash_hex = COLOR_MAP.get(self._bg_color_name, "#ffffff")
        c = QColor(flash_hex)
        # 综合 opacity_pct 与动画 _flash_alpha
        effective_alpha = (self._opacity_pct / 100.0) * self._flash_alpha
        c.setAlphaF(max(0.0, min(1.0, effective_alpha)))
        painter.fillRect(rect, c)

        # 5) 边框
        painter.setPen(QPen(QColor("#2a2e36"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)

        # 6) 顶部右上小标签（提示）
        painter.setPen(QColor(255, 255, 255, 120))
        f = QFont("Microsoft YaHei", 9)
        painter.setFont(f)
        label = f"实时预览 · {self._bg_color_name} · {self._opacity_pct}%   ▷ 点击模拟一次淡入"
        painter.drawText(rect.adjusted(12, 8, -12, 0), Qt.AlignTop | Qt.AlignLeft, label)

        painter.end()
