#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
UI视觉效果管理器
管理阴影、模糊、发光等视觉效果
设计原则：专业、克制、性能优先
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QColor
from PySide6.QtCore import QEvent, Qt


class ScrollShadow(QWidget):
    """滚动区边缘指示条 —— 告诉用户「这个方向还有内容」。

    ## RN-120：原来这东西回答的是**没人问的那个问题**

    它只画**顶部**，而且只在 `value > 0`（也就是**用户已经滚过了**）之后才显示。
    可玩家需要知道的是「下面还有没有」，**在他滚动之前**。
    外审在 crosshair 上 6 发、在 advanced 上 3/3 票都说「缺乏滚动提示、容易漏看」，
    而这个指示器一直好端端地装在那儿 —— 它答的是另一个问题。

    ⭐ **一个装了却没人受益的提示，跟没装的区别只在于：它会让人以为已经装过了。**

    ## 而且它在深色主题上根本画不出来

    渐变写死成 `QColor(0, 0, 0, 30)` —— **深色背景上叠黑色**。
    实测 `bg_primary` 在深色主题里是 `#141820` / `#0a0c12` 这一档，叠完只差 2 个色阶；
    而其中一个主题的 `bg_primary` 就是 `#000000` —— 黑叠黑，**数学上的空操作**。
    （浅色主题上它是有效的，所以这条缺陷在浅色下永远暴露不出来。）
    ⇒ 颜色改成从主题拿 `border_primary`：那个令牌的定义就是「要跟背景分得开」。

    ## 还差一根信号

    原来只连了 `valueChanged`。**页面刚建好时 value 一直是 0**，而 `maximum` 是
    布局排完才定下来的 —— 于是「还没滚动、下面有内容」这个**最要紧的时刻**
    根本不会触发任何一次更新。补 `rangeChanged`。
    """

    EDGE_TOP = "top"
    EDGE_BOTTOM = "bottom"

    #: 渐隐带的高度。**4px 是不够的** —— 实测那一版在截图里只有**一行像素**看得出来
    #: （y=713 亮度 33 / 背景 12，上面三行因为渐变已经衰减到几乎透明）。
    #: 而外审真正在抱怨的也不是"没有提示"，是**贴边那行字被齐腰切开**：
    #: 一条 1px 细线管不了那件事，反而更像一道裁切线。
    #: 18px 约等于一行正文的高度，够把贴边那行字"淡出"而不是"切断"。
    THICKNESS = 18

    def __init__(self, scroll_area, edge=EDGE_TOP, parent=None):
        super().__init__(parent or scroll_area)
        self._scroll_area = scroll_area
        self._edge = edge
        self._opacity = 0.0
        self.setFixedHeight(self.THICKNESS)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.raise_()

        # 监听滚动
        vbar = scroll_area.verticalScrollBar()
        if vbar:
            vbar.valueChanged.connect(self._sync)
            # RN-120：范围是布局排完才定的，只连 valueChanged 会错过「还没滚动」那一刻。
            vbar.rangeChanged.connect(self._on_range_changed)

        # UP-032: 必须监听**滚动区**的尺寸变化，不是自己的。
        # 原来只重写了本控件的 resizeEvent —— 而本控件只有在 _reposition()
        # 把它拉宽时才会 resize，纯自循环。窗口放大时滚动区变宽了，
        # 阴影条却还停在安装那一刻的宽度上，于是顶部只剩一小截阴影。
        scroll_area.installEventFilter(self)

        self._reposition()
        self._sync()

    def eventFilter(self, watched, event):
        if watched is self._scroll_area and event.type() == QEvent.Resize:
            self._reposition()
            self._sync()
        return super().eventFilter(watched, event)

    def _reposition(self):
        w = self._scroll_area.width()
        if self._edge == self.EDGE_BOTTOM:
            self.setGeometry(0, max(0, self._scroll_area.height() - self.THICKNESS),
                             w, self.THICKNESS)
        else:
            self.setGeometry(0, 0, w, self.THICKNESS)

    def has_content_beyond(self) -> bool:
        """这一侧还有没有内容 —— **判据认这一个函数**，不去猜像素。"""
        vbar = self._scroll_area.verticalScrollBar()
        if vbar is None or vbar.maximum() <= 0:
            return False
        if self._edge == self.EDGE_BOTTOM:
            return vbar.value() < vbar.maximum()
        return vbar.value() > 0

    def is_lit(self) -> bool:
        """**这一条现在画不画得出来** —— `paintEvent` 卡的就是这个。

        ⚠ 判据要认它，别认 `has_content_beyond()`：后者是现算的纯函数，
        **跟信号连没连一点关系都没有**。第一版判据认了后者，
        于是把 `rangeChanged` 拆掉它照样绿（回退验证当场 0/1）。
        ⭐ **判据要认"真正决定画面的那个状态"，不是认一个算得出同样答案的函数。**
        """
        return self._opacity > 0.01

    def _on_range_changed(self, _lo, _hi):
        self._sync()

    def _sync(self, *_args):
        target = 1.0 if self.has_content_beyond() else 0.0
        if abs(self._opacity - target) > 0.01:
            self._opacity = target
            self.update()

    #: 贴边那一端的不透明度。不是 255：**留一点透**，让人看得出"下面还有东西"，
    #: 而不是以为内容到此为止。
    EDGE_ALPHA = 235

    def _edge_color(self) -> QColor:
        """**用背景色做渐隐**，让贴边的内容淡出，而不是被切断。

        ⚠ 走到这一版之前拐了两个弯，两个都值得记：

        ① 第一版把颜色从写死的黑改成"从主题拿 `border_primary`"。实算之后发现
           **浅色主题是退步**（合成对比 1.30 → 1.13）—— 深色修好了、浅色弄坏了。
           ⭐ **换一个"看起来更讲究"的颜色源，不等于换一个更能看见的颜色。**
        ② 第二版按背景明暗分方向（浅色压黑、深色提亮），九套主题算下来全部变好。
           **但那还是在画一条线。** 截图实测：4px 渐变里只有**一行像素**真的看得出来，
           而外审 3/3 票抱怨的根本不是"没提示"，是**贴边那行字被齐腰切开** ——
           一条细线不但解决不了，还更像一道裁切线。

        ⇒ 现在渐隐到 `bg_primary`：贴边的字**淡出**，天然读作"还没完"。
        颜色取背景色本身，因此**九套主题自动都对**，不必再分明暗。
        """
        from theme_manager import get_theme_manager

        theme = getattr(get_theme_manager(), "current_theme", None)
        c = QColor(theme.colors.bg_primary) if theme is not None else QColor(0, 0, 0)
        if not c.isValid():
            c = QColor(0, 0, 0)
        c.setAlpha(self.EDGE_ALPHA)
        return c

    def paintEvent(self, event):
        if self._opacity <= 0.01:
            return
        from PySide6.QtGui import QLinearGradient, QPainter

        base = self._edge_color()
        strong = QColor(base)          # 贴边那一端：几乎盖住（见 EDGE_ALPHA）
        fade = QColor(base)
        fade.setAlpha(0)               # 里侧那一端：完全透明

        p = QPainter(self)
        grad = QLinearGradient(0, 0, 0, self.height())
        if self._edge == self.EDGE_BOTTOM:
            grad.setColorAt(0, fade)
            grad.setColorAt(1, strong)
        else:
            grad.setColorAt(0, strong)
            grad.setColorAt(1, fade)
        p.fillRect(self.rect(), grad)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition()


def install_scroll_shadow(scroll_area):
    """给 QScrollArea 装**上下两条**边缘指示（RN-120：原来只装顶部那一条）。"""
    if hasattr(scroll_area, '_scroll_shadow_installed'):
        return
    scroll_area._scroll_shadow_installed = True
    scroll_area._scroll_shadow = ScrollShadow(scroll_area, ScrollShadow.EDGE_TOP)
    scroll_area._scroll_shadow_bottom = ScrollShadow(
        scroll_area, ScrollShadow.EDGE_BOTTOM)
