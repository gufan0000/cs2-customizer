# SPDX-License-Identifier: GPL-3.0-or-later
"""StatusChip — 状态徽章,替代散在 page 里的 audioStatusChip / badgeLabel.

视觉(由 theme_manager QSS 控制 objectName="audioStatusChip" + level property):
    [● 主题・深色]   level=info  / 灰底蓝字
    [● 配置・已保存]  level=success / 灰底绿字(v4 起降饱和)
    [● 音频・需检查2] level=warning / 琥珀
    [● GSI・异常]    level=error   / 红

设计原则(Phase 2):
  - 完全复刻 audioStatusChip 视觉(由 QSS 控制),Phase 4-6 升级时统一跟进
  - 提供清晰 API(set_text / set_level)
  - 不破坏现有 audioStatusChip 用法(QSS 选择器仍然可命中)

构造:
    StatusChip(text, level="info", parent=None)
    level: info / success / positive / warning / error / neutral

用法:
    chip = StatusChip("主题・深色", level="info")
    layout.addWidget(chip)
    chip.set_text("主题・浅色")
    chip.set_level("success")
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget

_VALID_LEVELS = ("info", "success", "positive", "warning", "error", "neutral")


class StatusChip(QLabel):
    """状态徽章."""

    def __init__(
        self,
        text: str = "",
        level: str = "info",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        # 复用既有 audioStatusChip QSS 样式(theme_manager 已有完整定义)
        self.setObjectName("audioStatusChip")
        self._level = level
        self.set_level(level)

    @property
    def level(self) -> str:
        return self._level

    def set_level(self, level: str) -> None:
        """改 level — 通过 setProperty 触发 QSS 重新匹配."""
        if level not in _VALID_LEVELS:
            raise ValueError(f"invalid StatusChip level: {level!r}, expected one of {_VALID_LEVELS}")
        self._level = level
        self.setProperty("level", level)
        # 触发 QSS 重新计算
        self.style().unpolish(self)
        self.style().polish(self)

    def set_text(self, text: str) -> None:
        super().setText(text)
