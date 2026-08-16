# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标的两个预览控件（KI-3）。

**两个都刻意不含自己的几何/绘制实现**，全部委托给 `kill_icon_overlay` 的
纯函数。这条是从准心那边买来的教训：准心页当年自己写了第二套预览绘制代码，
结果十字预览大了一倍、点准心随粗细漂移——两套几何各画各的，只有肉眼能发现。

- `KillIconPreview`   —— 页内动画预览。KI-3 之前想看效果只能真弹一次全屏
  叠加层，调帧率/换风格的反馈链长得没法用。
- `KillIconPositionMap` —— 位置示意图。KI-3 之前位置是靠两条 ±200px 的滑条
  盲调，每动一次都得预览一遍试错。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from kill_icon_overlay import (
    TICK_HZ,
    compute_overlay_geometry,
    compute_scaled_size,
    playback_state,
)

#: 位置示意图里假想的屏幕分辨率。用固定值而不是真实屏幕：示意图要表达的是
#: "图标大概落在画面的什么位置"，跟用户当前接了几块屏无关。
REFERENCE_SCREEN = (1920, 1080)


class KillIconPreview(QWidget):
    """按真实节奏循环播放一套帧。

    与叠加层的差别只有一处：这里**循环**播，叠加层播一次就收。
    预览要让用户盯着看，播一次就没了等于逼他反复点按钮。
    """

    def __init__(self, parent=None, box=(200, 140)):
        super().__init__(parent)
        self._box = box
        self._frames = ()
        self._fps = 30
        self._index = 0
        self._elapsed = 0.0
        self._placeholder = "选择风格后在这里预览"
        self.setMinimumSize(box[0], box[1])

        self._timer = QTimer(self)
        self._timer.setInterval(max(1, int(round(1000 / TICK_HZ))))
        self._timer.timeout.connect(self._tick)

    def sizeHint(self):
        """按预缩放画布报期望尺寸。

        `QWidget` 默认的 `sizeHint` 是无效的 (-1,-1)。KI-6 时这个控件一直摆在
        清单板的格子里、由布局拉伸，所以没暴露问题；KI-7 把它摆进一条水平布局
        并且把 `minimumWidth` 放开到 0（窄窗口不能被它顶住）之后，两件事凑一起
        的结果是**宽度收缩成 0，整块预览凭空消失**——而布局本身完全"正常"，
        没有溢出、没有报错，只是那块什么都没有。
        """
        from PySide6.QtCore import QSize

        return QSize(self._box[0], self._box[1])

    # ------------------------------------------------------------------ API

    def set_animation(self, animation, placeholder=None):
        """喂一套 `KillIconAnimation`；`None` 表示没素材。"""
        if placeholder is not None:
            self._placeholder = placeholder
        if animation is None or not animation.frames:
            self._frames = ()
            self._timer.stop()
            self.update()
            return

        # 预缩放一次，别在每次 paintEvent 里现缩：预览控件按 60Hz 重绘，
        # 每帧现缩 350x250 的图是纯浪费。
        target_w, target_h = self._fit(animation.frame_width, animation.frame_height)
        self._frames = tuple(
            frame.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            for frame in animation.frames
        )
        self._fps = animation.fps
        self.restart()

    def set_fps(self, fps):
        """只改节奏不换素材——拖"展示时长"滑条时走这条。"""
        self._fps = max(1, int(fps or 1))
        self.restart()

    def restart(self):
        self._elapsed = 0.0
        self._index = 0
        if self._frames:
            self._timer.start()
        self.update()

    def stop(self):
        self._timer.stop()

    @property
    def has_frames(self) -> bool:
        return bool(self._frames)

    # -------------------------------------------------------------- 内部

    def _fit(self, width, height):
        box_w, box_h = self._box
        ratio = min(box_w / max(1, width), box_h / max(1, height), 1.0)
        return max(1, int(width * ratio)), max(1, int(height * ratio))

    def _tick(self):
        self._elapsed += self._timer.interval() / 1000.0
        state = playback_state(self._elapsed, self._fps, len(self._frames))
        if state is None:
            self._elapsed = 0.0
            state = playback_state(0.0, self._fps, len(self._frames))
            if state is None:
                self._timer.stop()
                return
        index, _opacity = state
        if index != self._index:
            self._index = index
            self.update()

    #: 占位文字与预览框边框之间留的横向余量。
    PLACEHOLDER_PADDING = 6

    def placeholder_box(self, rect=None):
        """占位文字能用的那块地方。"""
        pad = self.PLACEHOLDER_PADDING
        return (self.rect() if rect is None else rect).adjusted(pad, pad, -pad, -pad)

    def placeholder_for_box(self, width, height):
        """这块地方装得下多少占位文字。

        「这套风格还没有素材，拖一个图标包进来」在 220px 的预览框里**两头
        各被切掉一个字**，而且是画在圆角边框**外面**的——看上去像渲染坏了。
        `drawText` 不给约束就是有多长画多长，`Qt.AlignCenter` 只管居中、
        不管装不装得下；而排版审计量的是控件几何，画出界一个字都不会红。

        先让它换行（中文没空格，`TextWordWrap` 会按字断），换行之后还是
        塞不下才打省略号——**宁可少说也不许画到框外面去**。
        """
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QFontMetrics

        width, height = max(0, int(width)), max(0, int(height))
        metrics = QFontMetrics(self.font())
        wrapped = metrics.boundingRect(QRect(0, 0, width, height),
                                       Qt.AlignCenter | Qt.TextWordWrap,
                                       self._placeholder)
        if wrapped.width() <= width and wrapped.height() <= height:
            return self._placeholder
        return metrics.elidedText(self._placeholder, Qt.ElideRight, width)

    def placeholder_draw_spec(self, rect):
        """占位文字**到底怎么画**：`(矩形, 对齐与换行标志, 文字)`。

        单拎出来是为了让判据和 `paintEvent` **读同一份决策**。
        直接去数渲染出来的像素这条路走过，不可靠：离屏平台上前面创建过大量
        控件之后，新控件 `render()` 出来是一张空图，判据于是**单跑绿、
        全量红**，而且红的理由是"一个像素都没画出来"，跟缺陷本身无关。
        """
        box = self.placeholder_box(rect)
        return (box, Qt.AlignCenter | Qt.TextWordWrap,
                self.placeholder_for_box(box.width(), box.height()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawRoundedRect(QRectF(rect), 6, 6)

        if not self._frames:
            box, flags, text = self.placeholder_draw_spec(rect)
            painter.setPen(QColor(160, 160, 160))
            painter.drawText(box, flags, text)
            painter.end()
            return

        frame = self._frames[min(self._index, len(self._frames) - 1)]
        painter.drawImage(
            rect.center().x() - frame.width() // 2,
            rect.center().y() - frame.height() // 2,
            frame,
        )
        painter.end()


class KillIconPositionMap(QWidget):
    """一张缩略的屏幕示意图，标出图标会落在哪儿。

    落点**必须**由 `compute_overlay_geometry` 算——就是叠加层真正用的那个
    函数。自己在这里按比例估一个位置，示意图就会和实际落点慢慢分家，
    而且分家了也没人会发现。

    **蓝框可以直接拖**：画着一张"图标落在这儿"的图、旁边配两条 ±200px 的
    滑条，而图上那块唯一有意义的东西点不动——这是把示意图做成了只读装饰。
    拖出来的值一路回到滑条上，不另存一份（`position_changed` → 页面 setValue）。
    """

    #: 拖拽的取值范围。**必须和设置页那两条滑条一致**，否则拖出来的值滑条
    #: 表示不了，一回填就被 clamp 回去，表现是"拖到边上会往回弹一下"。
    OFFSET_LIMIT = 200

    #: 底部那行说明。它是 `drawText` 画上去的——**排版审计一个字都量不到**
    #: （审计量控件几何，文字画出边界只是被裁掉，控件本身没溢出）。
    #: 加"可拖动"三个字那一版一上来就把两头都截掉了，而且是渲染成图肉眼
    #: 看才发现的。所以现在走 `caption_for_width`：放不下就打省略号，
    #: **宁可少说也不许被裁**——被裁掉的两头看上去像是渲染坏了。
    CAPTION = "可拖动 · 按 1920x1080 画"

    position_changed = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._offset = (0, 0)
        self._scale = 1.0
        self._frame_size = (350, 250)
        self.setMinimumHeight(120)
        self.setMaximumHeight(160)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("直接拖蓝框就能摆位置，和下面两条滑条是同一个值")

    def set_target(self, offset_x, offset_y, scale, frame_size=None):
        self._offset = (int(offset_x or 0), int(offset_y or 0))
        self._scale = float(scale or 1.0)
        if frame_size:
            self._frame_size = frame_size
        self.update()

    # -------------------------------------------------------------- 几何

    def map_geometry(self):
        """示意图在控件里的位置和缩放比：`(map_x, map_y, ratio)`。

        **画和点都读这一份**。以前这段算在 `paintEvent` 里，拖拽要用就得
        再抄一遍——抄出来的第二份迟早和第一份分家，而且是"拖的位置和画的
        位置差一点点"这种没人会报的分家。
        """
        screen_w, screen_h = REFERENCE_SCREEN
        area = self.rect().adjusted(4, 4, -5, -5)
        ratio = min(area.width() / screen_w, area.height() / screen_h)
        map_w, map_h = screen_w * ratio, screen_h * ratio
        return (area.x() + (area.width() - map_w) / 2,
                area.y() + (area.height() - map_h) / 2,
                ratio)

    def icon_geometry(self, offset=None):
        """图标在 1920x1080 参考屏上的 `(x, y, w, h)`。走叠加层那个公式。"""
        screen_w, screen_h = REFERENCE_SCREEN
        icon_w, icon_h = compute_scaled_size(
            self._frame_size[0], self._frame_size[1], 350, self._scale
        )
        return compute_overlay_geometry(
            (0, 0, screen_w, screen_h), 1.0, icon_w, icon_h,
            *(self._offset if offset is None else offset)
        )

    def offset_for_point(self, point):
        """控件上的一个点 → `(offset_x, offset_y)`。

        反解**不自己按比例估**：先问落点公式"零偏移时图标落在哪"，再拿差值
        当偏移。落点公式（`(screen_h*3)//4 - h//2 + 50`）将来要是动了，
        这里自动跟着对。
        """
        map_x, map_y, ratio = self.map_geometry()
        if ratio <= 0:
            return self._offset
        base_x, base_y, w, h = self.icon_geometry((0, 0))
        offset_x = int(round((point.x() - map_x) / ratio - (base_x + w / 2)))
        offset_y = int(round((point.y() - map_y) / ratio - (base_y + h / 2)))
        limit = self.OFFSET_LIMIT
        return (max(-limit, min(limit, offset_x)),
                max(-limit, min(limit, offset_y)))

    def caption_for_width(self, width):
        """这么宽装得下多少说明文字。装不下就省略号，绝不硬画出去。"""
        from PySide6.QtGui import QFontMetrics

        return QFontMetrics(self.font()).elidedText(
            self.CAPTION, Qt.ElideRight, max(0, int(width)))

    def _drag_to(self, point):
        offset = self.offset_for_point(point)
        if offset == self._offset:
            return
        self._offset = offset
        self.update()
        self.position_changed.emit(offset[0], offset[1])

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setCursor(Qt.ClosedHandCursor)
            self._drag_to(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._drag_to(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        screen_w, screen_h = REFERENCE_SCREEN
        map_x, map_y, ratio = self.map_geometry()
        map_w, map_h = screen_w * ratio, screen_h * ratio

        painter.setPen(QPen(QColor(255, 255, 255, 70), 1))
        painter.setBrush(QColor(0, 0, 0, 50))
        painter.drawRoundedRect(QRectF(map_x, map_y, map_w, map_h), 4, 4)

        # 准心位置（画面正中），给用户一个参照物
        painter.setPen(QPen(QColor(120, 220, 140, 160), 1))
        center_x, center_y = map_x + map_w / 2, map_y + map_h / 2
        painter.drawLine(int(center_x - 5), int(center_y), int(center_x + 5), int(center_y))
        painter.drawLine(int(center_x), int(center_y - 5), int(center_x), int(center_y + 5))

        x, y, w, h = self.icon_geometry()

        painter.setPen(QPen(QColor(90, 170, 255, 220), 1))
        painter.setBrush(QColor(90, 170, 255, 70))
        painter.drawRect(QRectF(map_x + x * ratio, map_y + y * ratio, w * ratio, h * ratio))

        painter.setPen(QColor(170, 170, 170))
        text_rect = self.rect().adjusted(6, 0, -6, -2)
        painter.drawText(
            text_rect,
            Qt.AlignBottom | Qt.AlignHCenter,
            self.caption_for_width(text_rect.width()),
        )
        painter.end()
