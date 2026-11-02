# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""风格库：这一页有哪些风格。点一张选中，卡上就能试听（批 146）。

选中了做什么由页面决定（`brushChanged`）：四个音效页是当刷子再去点枪，被击杀页是直接用它。
⚠ 四个音效页刚进来时**没有刷子**：这时点枪名什么都不改，不会误覆盖已经配好的枪。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui_style_applier import keep_single_line

CARD_MIN_WIDTH = 168
CARD_GAP = 8


class ElidedLabel(QLabel):
    """放不下就显示省略号，全名进 tooltip。给用户自己起的名字用（长短没有上限）。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text or "")
        self._sync_elide()

    def full_text(self) -> str:
        return self._full_text

    def _sync_elide(self) -> None:
        shown = self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, max(0, self.width()))
        self.setText(shown)
        self.setToolTip(self._full_text if shown != self._full_text else "")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_elide()

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint


class StyleCard(QPushButton):
    """一张风格卡。整张是一颗可选中的按钮（键盘也够得着），右边那颗圆的是试听。"""

    auditionRequested = Signal(str)

    def __init__(self, style: str, meta: str = "", parent=None):
        super().__init__(parent)
        from widgets.icon_provider import get_themed_icon

        self.style_name = style
        self.setObjectName("styleCard")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(style)
        self.setMinimumWidth(CARD_MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(0)
        words.addStretch(1)
        # ⚠ 两行字都要 keep_single_line：全局给标签开折行之后，卡片的高度变成「按宽度算」，
        # 布局不再问下面的 sizeHint，极简主题下两行字就叠在一起。
        self.name_label = keep_single_line(ElidedLabel(style))
        self.name_label.setObjectName("styleCardName")
        self.name_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        words.addWidget(self.name_label)
        self.meta_label = keep_single_line(QLabel(meta))
        self.meta_label.setObjectName("styleCardMeta")
        self.meta_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.meta_label.setVisible(bool(meta))
        words.addWidget(self.meta_label)
        words.addStretch(1)
        layout.addLayout(words, 1)

        self.play_button = QPushButton(self)
        self.play_button.setObjectName("styleCardPlay")
        self.play_button.setIcon(get_themed_icon("mdi.play", role="secondary", size=18))
        self.play_button.setCursor(Qt.PointingHandCursor)
        self.play_button.setToolTip(f"试听「{style}」")
        self.play_button.setAccessibleName(f"试听 {style}")
        self.play_button.clicked.connect(lambda: self.auditionRequested.emit(self.style_name))
        layout.addWidget(self.play_button, 0, Qt.AlignVCenter)

    def sizeHint(self):
        # 按钮的 sizeHint 不看里面的布局。平时高度由样式表给，极简主题没有样式表。
        # ⚠ 不能用 setMinimumHeight：样式表里写过 min-height，换到极简主题时 Qt 会把它清零。
        hint = super().sizeHint()
        hint.setHeight(max(hint.height(), self.fontMetrics().height() * 2 + 12))
        return hint

    def set_meta(self, meta: str) -> None:
        self.meta_label.setText(meta)
        self.meta_label.setVisible(bool(meta))


class StyleLibrary(QWidget):
    """一格一格的风格卡，列数跟宽度走。对外只有「现在的刷子是谁」。"""

    #: 刷子变了；空串 = 没有刷子。
    brushChanged = Signal(str)
    auditionRequested = Signal(str)

    def __init__(self, parent=None, *, focus_after=None):
        super().__init__(parent)
        self.setObjectName("styleLibrary")
        #: 卡片是列表刷新时才建的，新建的控件排在焦点链最后，Tab 要走完整块武器板才到这里。
        #: 建完接到这颗控件后面。
        self._focus_after = focus_after
        self._cards: dict[str, StyleCard] = {}
        self._brush = ""
        self._cols = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(CARD_GAP)

    # ------------------------------------------------------------ 内容

    def set_styles(self, items: list[tuple[str, str]]) -> None:
        """换一批卡：`[(风格名, 那一行小字), ...]`。名字没变的卡留着，只换小字。"""
        wanted = [name for name, _meta in items]
        if wanted != list(self._cards):
            self._rebuild(items)
        else:
            for name, meta in items:
                self._cards[name].set_meta(meta)
        if self._brush and self._brush not in self._cards:
            self.set_brush("")

    def _rebuild(self, items) -> None:
        for card in self._cards.values():
            self._grid.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards = {}
        for name, meta in items:
            card = StyleCard(name, meta, self)
            card.setChecked(name == self._brush)
            card.clicked.connect(lambda _checked=False, n=name: self._on_card_clicked(n))
            card.auditionRequested.connect(self.auditionRequested)
            self._cards[name] = card
        self._cols = 0
        self._reflow()
        previous = self._focus_after
        if previous is not None:
            for card in self._cards.values():
                QWidget.setTabOrder(previous, card)
                QWidget.setTabOrder(card, card.play_button)
                previous = card.play_button

    def styles(self) -> list[str]:
        return list(self._cards)

    def card(self, style: str) -> StyleCard | None:
        return self._cards.get(style)

    # ------------------------------------------------------------ 刷子

    def brush(self) -> str:
        return self._brush

    def set_brush(self, style: str) -> None:
        style = style if style in self._cards else ""
        changed = style != self._brush
        self._brush = style
        for name, card in self._cards.items():
            card.setChecked(name == style)
        if changed:
            self.brushChanged.emit(style)

    def _on_card_clicked(self, style: str) -> None:
        # 再点同一张 = 放下刷子。QButtonGroup 的互斥不让取消，所以自己管。
        self.set_brush("" if style == self._brush else style)

    # ------------------------------------------------------------ 摆放

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        cols = max(1, (self.width() + CARD_GAP) // (CARD_MIN_WIDTH + CARD_GAP))
        if cols == self._cols:
            return
        for col in range(self._grid.columnCount()):
            self._grid.setColumnStretch(col, 0)
        for card in self._cards.values():
            self._grid.removeWidget(card)
        for index, card in enumerate(self._cards.values()):
            self._grid.addWidget(card, index // cols, index % cols)
        for col in range(cols):
            self._grid.setColumnStretch(col, 1)
        self._cols = cols
