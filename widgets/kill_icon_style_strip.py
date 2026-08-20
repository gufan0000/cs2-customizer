# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标的风格卡片条（KI-7）。

KI-7 之前这一页选风格用的是一个 `QComboBox`——名字是用户自己起的（或者
zip 包里带的），下拉里全是干巴巴的字符串，**换之前根本不知道会换成什么样**。
这一页最主要的动作就是"挑一套图标"，却是整页里反馈最差的一个控件。

所以换成一排卡片：每张卡上有这套风格的缩略图、名字、齐不齐全，点一下就切。
最后一张是「＋ 导入」，把"装新的"摆在和"选已有的"同一条视线上。

**缩略图是静态第一帧，不是动画**，而且是**逐张懒装**的：

- 卡片只有 ~104x66，动画在这个尺寸上贡献的信息极少；
- 而代价很大——`load_level_animation` 会把整套帧切出来，用户真实的默认风格
  整套 519 帧。风格库里有几套就要装几次，全在建页那一下同步做。
  KI-3 已经为"建页时同步解码整套帧"挨过一次（46 帧 41ms，占建页耗时一半）。

所以这里走 `load_level_thumbnail`（只取第一帧），并且用 0ms 单发定时器
**一次只装一张**，把开销摊到事件循环里。想看动的那份在页面上方的大预览里，
那才是选中的那一套，也只有一套。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
)

from ui_style_applier import keep_single_line

#: 缩略图画布尺寸。卡片宽度由它 + 边距决定。
THUMB_BOX = (104, 66)

#: 一次装一张缩略图，间隔 0ms（让事件循环有机会插进来）。
THUMBNAIL_INTERVAL_MS = 0


class KillIconStyleThumb(QWidget):
    """一张缩略图画布。没图时画一句占位文案，不是留白。"""

    def __init__(self, parent=None, box=THUMB_BOX):
        super().__init__(parent)
        self._box = box
        self._image = None
        self._placeholder = "…"
        self.setFixedSize(box[0], box[1])

    def set_image(self, image, placeholder=None):
        if placeholder is not None:
            self._placeholder = placeholder
        if image is None or image.isNull():
            self._image = None
            self.update()
            return
        box_w, box_h = self._box
        self._image = image.scaled(box_w - 8, box_h - 8, Qt.KeepAspectRatio,
                                   Qt.SmoothTransformation)
        self.update()

    @property
    def has_image(self) -> bool:
        return self._image is not None

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(QColor(255, 255, 255, 36), 1))
        painter.setBrush(QColor(0, 0, 0, 46))
        painter.drawRoundedRect(QRectF(rect), 5, 5)

        if self._image is None:
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(rect, Qt.AlignCenter, self._placeholder)
            painter.end()
            return

        painter.drawImage(
            rect.center().x() - self._image.width() // 2,
            rect.center().y() - self._image.height() // 2,
            self._image,
        )
        painter.end()


class KillIconStyleCard(QFrame):
    """一套风格 = 一张卡。整张卡都可点，不是只有某个按钮可点。"""

    clicked = Signal(str)

    def __init__(self, style_name, parent=None):
        super().__init__(parent)
        self.style_name = str(style_name)
        self._selected = False

        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(4)

        self.thumb = KillIconStyleThumb(self)
        layout.addWidget(self.thumb, 0, Qt.AlignHCenter)

        self.name_label = QLabel(self.style_name)
        self.name_label.setObjectName("cardTitle")
        self.name_label.setAlignment(Qt.AlignCenter)
        # 名字是用户/图标包作者起的，可以任意长。卡片宽度是固定的，
        # 让它按省略号截断，别把整条卡片撑开把后面的卡挤出可视区。
        self.name_label.setFixedWidth(THUMB_BOX[0])
        layout.addWidget(self.name_label)

        self.state_label = QLabel("")
        self.state_label.setObjectName("hintLabel")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setFixedWidth(THUMB_BOX[0])
        layout.addWidget(self.state_label)

        self.set_selected(False)

    # ------------------------------------------------------------------ 状态

    def set_thumbnail(self, image):
        self.thumb.set_image(image, placeholder="无预览")

    def set_level_count(self, ready, total):
        """齐不齐全。这条以前只有点进去才知道，卡片上直接说。"""
        ready = int(ready)
        total = int(total)
        if ready >= total:
            self.state_label.setText("素材齐全")
        elif ready <= 0:
            self.state_label.setText("暂无素材")
        else:
            self.state_label.setText(f"{ready}/{total} 个等级")

    def set_selected(self, selected):
        self._selected = bool(selected)
        # 选中态走属性 + 重新 polish，不在这里手写颜色：颜色只能来自主题
        # token，页面里写死 #RRGGBB 是本项目明令禁止的（8 个主题会各错各的）。
        self.setProperty("selected", "true" if self._selected else "false")
        self.name_label.setText(
            ("✓ " if self._selected else "") + self.style_name
        )
        self.setToolTip(
            f"{self.style_name}{'（当前使用中）' if self._selected else ''}"
        )
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)

    @property
    def selected(self) -> bool:
        return self._selected

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.style_name)
        super().mouseReleaseEvent(event)


class KillIconStyleAddCard(QFrame):
    """末尾那张「＋ 导入」。和风格卡同宽同高，排在一条线上。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setToolTip("选一个图标包(.zip)、动图或图片导入")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(4)

        self.plus_label = QLabel("＋")
        self.plus_label.setObjectName("cardTitle")
        self.plus_label.setAlignment(Qt.AlignCenter)
        self.plus_label.setFixedSize(THUMB_BOX[0], THUMB_BOX[1])
        layout.addWidget(self.plus_label, 0, Qt.AlignHCenter)

        self.name_label = QLabel("导入")
        self.name_label.setObjectName("cardTitle")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setFixedWidth(THUMB_BOX[0])
        layout.addWidget(self.name_label)

        hint = QLabel("zip / 动图 / 图片")
        hint.setObjectName("hintLabel")
        hint.setAlignment(Qt.AlignCenter)
        hint.setFixedWidth(THUMB_BOX[0])
        layout.addWidget(hint)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class KillIconStyleStrip(QWidget):
    """一排风格卡 + 末尾的导入卡。"""

    style_selected = Signal(str)
    import_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cards = {}
        #: ⚠ 哨兵值，**不能是 `[]`**（RN-124）。`set_styles` 开头有一句
        #: 「列表没变就早退」，而初始值写成 `[]` 时，**第一次拿到空列表也算"没变"**
        #: —— 于是下面那句 `empty_label.setVisible(not styles)` 永远走不到，
        #: 全新用户（风格库本来就是空的）看到的是一片纯黑，没有任何引导。
        #: ⭐ 「没变化就早退」这类优化，第一次调用必须算"有变化"。
        self._order = None
        self._pending = []
        self._thumbnail_loader = None
        self._selected = ""

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

        self.add_card = KillIconStyleAddCard(self)
        self.add_card.clicked.connect(self.import_requested)
        self._layout.addWidget(self.add_card, 0, Qt.AlignTop)
        self._layout.addStretch(1)

        self.empty_label = QLabel("还没有任何风格，点右边的「＋ 导入」装一套。")
        self.empty_label.setObjectName("hintLabel")
        # RN-121：这是**横排里的一行提示**，不许折行。
        # 折行的 QLabel 在 QHBoxLayout 里报的宽度很窄，布局就照那个窄宽给它 ——
        # 实测这一条只拿到 232px（需要 256px），而同一排还空着 700 多 px。
        # ⭐ 折行不是"空间不够"的结果，很多时候是**"我说我能折行"的结果**。
        # ⚠ 走 keep_single_line：光 setWordWrap(False) 会被 fix_text_display 改回去。
        keep_single_line(self.empty_label)
        self.empty_label.hide()
        self._layout.insertWidget(0, self.empty_label)

    # ------------------------------------------------------------------ 内容

    def set_styles(self, styles, selected=""):
        """重建卡片。已经在的卡不重建——重建会把已装好的缩略图一起丢掉。"""
        styles = [str(s) for s in (styles or [])]
        if styles == self._order:
            self.set_selected(selected or self._selected)
            return

        for name, card in list(self.cards.items()):
            if name not in styles:
                self._layout.removeWidget(card)
                card.setParent(None)
                card.deleteLater()
                del self.cards[name]

        self._order = styles
        for index, name in enumerate(styles):
            card = self.cards.get(name)
            if card is None:
                card = KillIconStyleCard(name, self)
                card.clicked.connect(self.style_selected)
                self.cards[name] = card
            self._layout.removeWidget(card)
            self._layout.insertWidget(index, card, 0, Qt.AlignTop)

        self.empty_label.setVisible(not styles)
        self.set_selected(selected or self._selected)
        self._queue_thumbnails([n for n in styles if not self.cards[n].thumb.has_image])

    def set_selected(self, style_name):
        self._selected = str(style_name or "")
        for name, card in self.cards.items():
            card.set_selected(name == self._selected)

    def set_level_count(self, style_name, ready, total):
        card = self.cards.get(str(style_name))
        if card is not None:
            card.set_level_count(ready, total)

    # -------------------------------------------------------------- 缩略图

    def _queue_thumbnails(self, names):
        """排队逐张装，不是一口气装完。见模块开头。"""
        self._pending = [n for n in names if n in self.cards]
        if not self._pending:
            return
        if self._thumbnail_loader is None:
            self._thumbnail_loader = QTimer(self)
            self._thumbnail_loader.setSingleShot(True)
            self._thumbnail_loader.setInterval(THUMBNAIL_INTERVAL_MS)
            self._thumbnail_loader.timeout.connect(self._load_next_thumbnail)
        self._thumbnail_loader.start()

    def _load_next_thumbnail(self):
        from kill_icon_overlay import load_level_thumbnail

        while self._pending:
            name = self._pending.pop(0)
            card = self.cards.get(name)
            if card is None:
                continue
            image = None
            # 从 5 杀往下找第一个有素材的等级：ACE 通常是这套风格里最好看的
            # 那一张，也最能代表它。
            for kills in (5, 4, 3, 2, 1):
                try:
                    image = load_level_thumbnail(name, kills)
                except Exception:
                    image = None
                if image is not None and not image.isNull():
                    break
                image = None
            card.set_thumbnail(image)
            break
        if self._pending and self._thumbnail_loader is not None:
            self._thumbnail_loader.start()

    def load_all_thumbnails_now(self):
        """把排队中的缩略图一次装完。**只给判据用**——没有事件循环的时候
        单发定时器永远不会触发，判据会看到一整排空卡片而误以为功能坏了。"""
        while self._pending:
            self._load_next_thumbnail()
