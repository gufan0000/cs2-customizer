"""PageHeader — 27 个 page 顶部"标题 + 副标题"的统一组件.

替代散在每个 page 顶部的样板代码:
    title = QLabel("基础设置")
    title.setObjectName("titleLabel")
    title.setFont(QFont("Microsoft YaHei", 24, QFont.Bold))
    header_row = QHBoxLayout()
    header_row.addWidget(title)
    header_row.addStretch()
    layout.addLayout(header_row)
    self.page_lead_label = QLabel("...")
    self.page_lead_label.setObjectName("pageLeadLabel")
    self.page_lead_label.setWordWrap(True)
    layout.addWidget(self.page_lead_label)

新写法:
    header = PageHeader("基础设置", description="把常用开关...直接.")
    layout.addWidget(header)
    # 加 help button 等到 header_row:
    header.add_title_action(my_help_button)
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QVBoxLayout, QWidget
)


class PageHeader(QWidget):
    """页面标题 + 副标题 widget.

    属性:
        title_label: QLabel  — H1 标题(objectName="titleLabel")
        description_label: QLabel | None  — 副标题(objectName="pageLeadLabel")
        title_row: QHBoxLayout  — 标题所在横排,可往里加 action 按钮等
    """

    def __init__(
        self,
        title: str,
        description: str | None = None,
        title_font_size: int | None = 24,
        icon: str | None = None,
        icon_role: str = "accent",
        spacing: int = 4,
        title_spacing: int | None = 10,
        parent: QWidget | None = None,
    ) -> None:
        """
        title_font_size:
            显式字号。传 `None` 表示**不设 QFont**、完全交给 QSS——
            准心页和账号页原本就是这么写的，替换时必须能表达"不设"，
            否则会把它们从 QSS 字号改成 24。

        spacing:
            标题行与副标题之间的距离。默认 4；R9-C 把 26 个页面的手搓页头
            换成本组件时传各自页面布局原来的 spacing（多数是 12），
            为的是**一个像素都不动**——页头长什么样是视觉决策，
            不该由一次机械重构顺手改掉。四种并存的字号见 UP-092。
        """
        super().__init__(parent)

        # 暴露成 `self.body`：`install_help_panel(header.title_row, header.body, ...)`
        # 靠"在 parent_layout 里找到 header_layout 的下标"来决定帮助面板插哪儿。
        # 传页面主布局是找不到 title_row 的（它在本组件内部），会回退到"插在第 1 位"，
        # 于是帮助面板从"标题与副标题之间"跑到"副标题下面"，副标题上移 12px。
        # R9-C 实测就栽在这里——传 `self.body` 才能插回原位。
        self.body = QVBoxLayout(self)
        layout = self.body
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)

        self.title_row = QHBoxLayout()
        self.title_row.setContentsMargins(0, 0, 0, 0)
        # `title_spacing=None` 表示不调 setSpacing、沿用 Qt 样式的默认间距。
        # 准心页原来就是裸 `QHBoxLayout()`，写死 10 会让右上角那枚 "?" 挪 2px。
        if title_spacing is not None:
            self.title_row.setSpacing(title_spacing)

        # v5 Phase 5: 可选页面 icon
        self._icon_label = None
        if icon:
            from widgets.icon_label import IconLabel
            self._icon_label = IconLabel(icon, "", role=icon_role, icon_size=24)
            self.title_row.addWidget(self._icon_label)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("titleLabel")
        # 显式设字号:对齐多数 page 旧写法(QFont Bold).
        # Phase 4 token 升级后 QSS 会接管,这里仅保留兼容.
        if title_font_size is not None:
            self.title_label.setFont(QFont("Microsoft YaHei", title_font_size, QFont.Bold))
        self.title_row.addWidget(self.title_label)
        self.title_row.addStretch()
        layout.addLayout(self.title_row)

        self.description_label: QLabel | None = None
        if description:
            self.description_label = QLabel(description)
            self.description_label.setObjectName("pageLeadLabel")
            self.description_label.setWordWrap(True)
            layout.addWidget(self.description_label)

    def add_title_action(self, widget: QWidget) -> None:
        """在标题右侧追加 action(如帮助按钮)."""
        self.title_row.addWidget(widget)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_description(self, text: str) -> None:
        if self.description_label is not None:
            self.description_label.setText(text)
