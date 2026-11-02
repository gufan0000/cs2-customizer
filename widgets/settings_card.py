# SPDX-License-Identifier: GPL-3.0-or-later
"""SettingsCard — 统一替代散在 18 page 的 _create_section_card.

设计原则(Phase 2):
  - 完全复刻旧 _create_section_card 的视觉(margins 14/12/14/12,spacing 8,
    statusLabel/hintLabel 命名),保证 Phase 3 迁移时视觉零差异.
  - 对外暴露 .body / .title_row / .add_widget 等 API,迁移时尽量小改动.
  - Phase 4-9 在 theme_manager / token 层升级时,所有 SettingsCard 自动跟进.

迁移示例(Phase 3):
    # 旧:
    card, card_layout = self._create_section_card("基础配置", "说明...")
    card_layout.addWidget(my_widget)

    # 新(最小改动):
    from widgets.settings_card import SettingsCard
    card, card_layout = SettingsCard.make("基础配置", "说明...")
    card_layout.addWidget(my_widget)

    # 或更现代:
    card = SettingsCard("基础配置", "说明...")
    card.add_widget(my_widget)
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
)


class SettingsCard(QFrame):
    """卡片容器 — 标题 + 可选描述 + body.

    属性:
        title_label: QLabel | None  — title 标签(setObjectName="statusLabel")
        description_label: QLabel | None  — 描述标签(setObjectName="hintLabel")
        title_row: QHBoxLayout | None  — title 所在的横排,可往里加 action(如帮助按钮)
        body: QVBoxLayout  — 卡片主 layout,直接往里加内容用

    方法:
        add_widget(w): body.addWidget(w)
        add_layout(l): body.addLayout(l)
        add_stretch(s=1): body.addStretch(s)
        add_spacing(px): body.addSpacing(px)
        add_title_action(w): title_row.addWidget(w) — 加在 stretch 之后,靠右显示
    """

    # v5 Phase 6: 5 种语义,决定卡片左色条颜色 + 默认 icon role
    VALID_SEMANTICS = ("config", "info", "status", "warning", "danger", "neutral")
    SEMANTIC_TO_ICON_ROLE = {
        "config":  "accent",
        "info":    "info",
        "status":  "success",
        "warning": "warning",
        "danger":  "error",
        "neutral": "secondary",
    }

    def __init__(
        self,
        title: str | None = None,
        description: str | None = None,
        margins: tuple[int, int, int, int] = (14, 12, 14, 12),
        spacing: int = 8,
        icon: str | None = None,
        icon_role: str | None = None,
        semantic: str = "config",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        # v5 Phase 6: semantic 通过 QProperty 暴露给 QSS [semantic="config"] 选择器
        if semantic not in self.VALID_SEMANTICS:
            raise ValueError(f"invalid semantic: {semantic!r}")
        self._semantic = semantic
        self.setProperty("semantic", semantic)
        # icon_role 默认从 semantic 推导
        if icon_role is None:
            icon_role = self.SEMANTIC_TO_ICON_ROLE.get(semantic, "secondary")

        self._layout = QVBoxLayout(self)
        # 默认值对齐 _create_section_card 多数派(14/12/14/12 + spacing 8).
        # 个别变种(about / hud_color / magnifier / preset_center)用自定义值保视觉一致.
        self._layout.setContentsMargins(*margins)
        self._layout.setSpacing(spacing)

        self.title_row: QHBoxLayout | None = None
        self.title_label: QLabel | None = None
        self.description_label: QLabel | None = None
        self._icon_label = None  # v5 Phase 5: icon 组件

        if title:
            self.title_row = QHBoxLayout()
            self.title_row.setContentsMargins(0, 0, 0, 0)
            self.title_row.setSpacing(8)

            # v5 Phase 5: 可选 icon(在 title 前)
            if icon:
                from widgets.icon_label import IconLabel
                self._icon_label = IconLabel(icon, "", role=icon_role, icon_size=18)
                self.title_row.addWidget(self._icon_label)

            self.title_label = QLabel(title)
            # R7/D-02(UP-043): 从 statusLabel 改名 cardTitle。
            # 不能反过来去改 #statusLabel 的字号——全仓 54 处 setObjectName("statusLabel")
            # 里大量是**状态值**而不是卡片标题（debug_status_label / vb_status_label 等），
            # 动它会误伤一片。改名让 font.card_title 只有一个消费选择器。
            self.title_label.setObjectName("cardTitle")
            self.title_row.addWidget(self.title_label)
            self.title_row.addStretch()
            self._layout.addLayout(self.title_row)

        if description:
            self.description_label = QLabel(description)
            self.description_label.setObjectName("hintLabel")
            self.description_label.setWordWrap(True)
            self._layout.addWidget(self.description_label)

        # 暴露 body,等价于卡片的主 layout(向后追加内容)
        self.body = self._layout

    def add_widget(self, widget: QWidget, *args, **kwargs) -> None:
        self._layout.addWidget(widget, *args, **kwargs)

    def add_layout(self, sublayout, *args, **kwargs) -> None:
        self._layout.addLayout(sublayout, *args, **kwargs)

    def add_stretch(self, stretch: int = 1) -> None:
        self._layout.addStretch(stretch)

    def add_spacing(self, px: int) -> None:
        self._layout.addSpacing(px)

    # ========== title 区操作 ==========

    def add_title_action(self, widget: QWidget) -> None:
        """在 title_row 的 stretch 后追加 widget(靠右显示).
        例:加帮助按钮、状态徽章、操作菜单.
        """
        if self.title_row is None:
            raise RuntimeError("SettingsCard has no title; cannot add title action")
        self.title_row.addWidget(widget)

    def set_title(self, text: str) -> None:
        if self.title_label is not None:
            self.title_label.setText(text)

    def set_description(self, text: str) -> None:
        if self.description_label is not None:
            self.description_label.setText(text)

    # ========== 兼容工厂 ==========

    def set_semantic(self, semantic: str) -> None:
        """改 semantic — 触发 QSS 重新匹配色条颜色."""
        if semantic not in self.VALID_SEMANTICS:
            raise ValueError(f"invalid semantic: {semantic!r}")
        self._semantic = semantic
        self.setProperty("semantic", semantic)
        self.style().unpolish(self)
        self.style().polish(self)

    @property
    def semantic(self) -> str:
        return self._semantic

    @classmethod
    def make(
        cls,
        title: str | None = None,
        description: str | None = None,
        margins: tuple[int, int, int, int] = (14, 12, 14, 12),
        spacing: int = 8,
        icon: str | None = None,
        icon_role: str | None = None,
        semantic: str = "config",
        parent: QWidget | None = None,
    ) -> tuple["SettingsCard", QVBoxLayout]:
        """兼容旧 _create_section_card 返回风格,返回 (card, body_layout) 元组.

        Phase 3 迁移时最小改动:
            # 旧:
            card, card_layout = self._create_section_card(title, desc)
            # 新:
            card, card_layout = SettingsCard.make(title, desc)

        Phase 5+ 可选加 icon:
            card, layout = SettingsCard.make(title, desc, icon="mdi.cog-outline")
        """
        card = cls(
            title=title,
            description=description,
            margins=margins,
            spacing=spacing,
            icon=icon,
            icon_role=icon_role,
            semantic=semantic,
            parent=parent,
        )
        return card, card.body
