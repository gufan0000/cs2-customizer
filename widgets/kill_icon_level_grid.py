# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标素材清单板（KI-6）。

KI-6 之前，这一页的分工是拧巴的：设置页上有个"素材导入"卡片，点开是**另一个
对话框**，对话框里又有一份风格下拉和等级下拉，可以和页面上的各选各的。用户
得在两个地方维护同一个心智模型。而"这套风格到底有哪几个等级"没有任何地方
回答得了——唯一的信号是"时长滑条被禁掉了"，靠猜。

所以这里把五个击杀等级摊成一块板，每一格自己回答三个问题：

    有没有素材 · 长什么样 · 在屏幕上待多久

并且**每一格自己就是拖拽目标**：想给 3 杀换素材，就把文件拖到"3 杀"那一格
上，不用先在别处选等级再拖。右键菜单收着替换 / 删除 / 爆头 / 导出 / 撤销。

这个控件**不含任何绘制与几何实现**：预览走 `KillIconPreview`（它又全部委托给
`kill_icon_overlay` 的纯函数），时长换算走 `fps_for_duration`/`duration_for_fps`
那一对互逆函数。准心那边"预览是第二套独立绘制代码"的教训很贵。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QSlider,
    QSizePolicy, QVBoxLayout, QWidget
)

from kill_icon_overlay import duration_for_fps, fps_for_duration
from widgets.drop_import_mixin import enable_file_drop
from widgets.kill_icon_preview import KillIconPreview

#: 展示时长滑条的刻度（0.1 秒一格）。区间取 0.3~5.0 秒：
#: 再短肉眼跟不上，再长会压住下一次击杀。
DURATION_MIN_TICKS = 3
DURATION_MAX_TICKS = 50

#: 每一格认的拖拽后缀。目录与 zip 另有开关，见 `enable_file_drop`。
DROP_EXTENSIONS = (".gif", ".webp", ".apng", ".png", ".avif",
                   ".jpg", ".jpeg", ".bmp", ".json", ".zip")

LEVEL_TITLES = {1: "1 杀", 2: "2 杀", 3: "3 杀", 4: "4 杀", 5: "5 杀 · ACE"}

#: 一格最少要这么宽才装得下预览、滑条和两个按钮。
MIN_CELL_WIDTH = 200

#: 一格允许被压到的**硬**下限。
#:
#: 它必须比 `MIN_CELL_WIDTH` 小不少：列数是按可视区宽度算的，而 QGridLayout
#: 的最小宽度是"当前列数 × 每格最小宽"。两者相等的话，只要列数算大了一点点，
#: 整页就会横向溢出——排版审计里 kill_icon 一开始就是这么亮红的（352px）。
HARD_MIN_CELL_WIDTH = 140


def columns_for_width(width):
    """这么宽的板子摆几列。窄了折行，而不是把每一格挤扁。

    单独拎成纯函数是为了能验：`resize()` 会被子控件的最小尺寸顶回去，
    判据拿不到自己想要的宽度。
    """
    return max(1, min(5, int(width) // MIN_CELL_WIDTH))


class KillIconLevelCell(QFrame):
    """一个击杀等级的现状 + 就地改节奏 + 就地换素材。"""

    files_dropped = Signal(int, list)
    duration_changed = Signal(int, float)
    action_triggered = Signal(str, int)

    def __init__(self, kills, parent=None):
        super().__init__(parent)
        self.kills = int(kills)
        self._frames = 0
        self._static = False
        self._has_headshot = False

        # 直接复用既有的卡片样式，不另开一套 QSS。
        # （手搓 QFrame#card 的棘轮只统计 pages/ 下的处数，这里在 widgets/。）
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.setMinimumWidth(HARD_MIN_CELL_WIDTH)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        self.title_label = QLabel(LEVEL_TITLES.get(self.kills, f"{self.kills} 杀"))
        self.title_label.setObjectName("cardTitle")
        header.addWidget(self.title_label)
        header.addStretch()
        self.badge_label = QLabel("")
        self.badge_label.setObjectName("hintLabel")
        header.addWidget(self.badge_label)
        layout.addLayout(header)

        self.preview = KillIconPreview(box=(168, 108))
        # 预览按 168x108 预缩放，但**允许被压窄**：最小宽度跟着走的话，
        # 五格并排时整块板的最小宽度就下不来了（见 HARD_MIN_CELL_WIDTH）。
        self.preview.setMinimumWidth(0)
        self.preview.setMinimumHeight(96)
        layout.addWidget(self.preview)

        self.info_label = QLabel("")
        self.info_label.setObjectName("hintLabel")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        # 滑条得有名字。没有名字的话，一根光秃秃的滑条配下面一行
        # 「0.60 秒 · 20 FPS」，用户根本判断不出拖的是时长、帧率还是播放进度
        # ——三种都说得通。标题放在上面而不是左边：左边要占宽，而一格能被
        # 压到 140px（HARD_MIN_CELL_WIDTH），塞不下。
        self.slider_caption = QLabel("在屏幕上停留")
        self.slider_caption.setObjectName("hintLabel")
        layout.addWidget(self.slider_caption)

        self.duration_slider = QSlider(Qt.Horizontal)
        self.duration_slider.setMinimum(DURATION_MIN_TICKS)
        self.duration_slider.setMaximum(DURATION_MAX_TICKS)
        self.duration_slider.setValue(10)
        self.duration_slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self.duration_slider)

        self.timing_label = QLabel("无素材")
        self.timing_label.setObjectName("hintLabel")
        layout.addWidget(self.timing_label)

        # ⚠ 这两个按钮**不许 `setFixedHeight`**。
        #
        # `QPushButton#secondaryButton` 的 QSS 里有 `min-height` + `padding`，
        # 默认主题下合起来是 54px。`setFixedHeight(28)` 只把 maximumHeight 设成
        # 28，minimumHeight 仍被 QSS 顶成 54——**Qt 在 min > max 时取 min**，
        # 于是按钮实际 54 高，而布局是按 28 算的格子高度：按钮的下边框被卡片
        # 边缘齐齐切掉一道。判据全绿（几何上"没有溢出"），排版审计也够不着
        # （它只走 pages/，不量对话框），是渲染成 PNG 放大看才发现的。
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.test_btn = QPushButton("测试")
        self.test_btn.setObjectName("secondaryButton")
        self.test_btn.clicked.connect(lambda: self.action_triggered.emit("test", self.kills))
        buttons.addWidget(self.test_btn)

        self.menu_btn = QPushButton("更多…")
        self.menu_btn.setObjectName("secondaryButton")
        self.menu_btn.clicked.connect(lambda: self._show_menu(self.menu_btn.pos()))
        buttons.addWidget(self.menu_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        enable_file_drop(self, DROP_EXTENSIONS,
                         lambda paths: self.files_dropped.emit(self.kills, paths),
                         accept_directories=True)

    # ------------------------------------------------------------------ 状态

    def set_frame_count(self, frames, kind="", exists=None):
        """有多少帧——这一格的"有没有素材"由它决定。

        刻意与 `set_state` 分开：帧数来自**播放器**（它有缓存、也是判据里的
        真源），而预览素材要解码、跑在建页之后的异步刷新里。合在一起的话，
        异步那一步还没跑完时整块板会显示成"全都没素材"。
        """
        self._frames = max(0, int(frames or 0))
        self._static = self._frames == 1
        present = bool(self._frames > 0 if exists is None else exists)

        self.duration_slider.setEnabled(present)
        self.test_btn.setEnabled(present)

        if not present:
            self.badge_label.setText("空缺")
            self.info_label.setText("把 GIF / WebP / PNG 序列文件夹拖进来")
            self.timing_label.setText("无素材")
            return

        # 角标只报"有没有素材"这一件事。以前有爆头素材时它会显示成
        # 「爆头专属」，**把「已就绪」顶掉了**——于是 3 杀那一格看上去像是
        # "这一格是爆头专用的"，而设置页那边爆头明明是个独立勾选框，
        # 两处概念对不上。爆头是这一格的**附加信息**，归到下面那行去。
        self.badge_label.setText("已就绪")
        kind_text = "逐帧目录" if kind == "legacy" else "图集"
        suffix = "（静态）" if self._static else ""
        extra = " · 含爆头专属" if self._has_headshot else ""
        self.info_label.setText(f"{self._frames} 帧 · {kind_text}{suffix}{extra}")
        self.refresh_timing_label()

    def set_state(self, entry, animation=None, has_headshot=False):
        """`entry` 是 `core.kill_icon_library.LevelEntry`；`animation` 可以是 None。"""
        self._has_headshot = bool(has_headshot)
        self.preview.set_animation(animation, "拖素材到这里")
        self.set_frame_count(
            getattr(entry, "frames", 0),
            getattr(entry, "kind", ""),
            exists=bool(getattr(entry, "exists", False)) or int(getattr(entry, "frames", 0) or 0) > 0,
        )

    def set_timing_seconds(self, seconds):
        """回填滑条。**不触发 `duration_changed`**——这是"读回来"，不是用户在改。"""
        ticks = max(DURATION_MIN_TICKS,
                    min(DURATION_MAX_TICKS, int(round(float(seconds or 0.0) * 10))))
        blocked = self.duration_slider.blockSignals(True)
        self.duration_slider.setValue(ticks)
        self.duration_slider.blockSignals(blocked)
        self.refresh_timing_label()

    @property
    def seconds(self) -> float:
        return round(self.duration_slider.value() / 10.0, 1)

    @property
    def is_static(self) -> bool:
        return self._static

    @property
    def frame_count(self) -> int:
        return self._frames

    def refresh_timing_label(self):
        """标签显示**换算回来**的真实时长，不是用户拖的原值。

        帧率必须是整数，30 帧要播 1.7 秒会落到 18fps、实际 1.67 秒——把真实值
        摆出来，免得用户对着"1.7 秒"却量出别的数。单帧素材没有"速度"这回事，
        滑条量的直接就是定格时长，不需要换算。
        """
        if self._frames <= 0:
            self.timing_label.setText("无素材")
            return
        if self._static:
            self.timing_label.setText(f"定格 {self.seconds:.1f} 秒")
            return
        fps = fps_for_duration(self._frames, self.seconds)
        self.timing_label.setText(f"{duration_for_fps(self._frames, fps):.2f} 秒 · {fps} FPS")

    def _on_slider(self, _value):
        self.refresh_timing_label()
        self.duration_changed.emit(self.kills, self.seconds)

    # ------------------------------------------------------------------ 菜单

    def build_menu(self):
        """把菜单**建出来但不弹**。

        判据只能验到这一层：`QMenu.exec` 是模态的，测试进程里没人去点它，
        表现是整个 pytest 卡死（不是失败）。所以"菜单里有哪几项、哪几项该
        灰掉、点了发什么信号"全都验在这个函数上，`_show_menu` 只剩一行 exec。
        """
        menu = QMenu(self)
        has_assets = self._frames > 0

        menu.addAction("替换素材…", lambda: self.action_triggered.emit("replace", self.kills))
        menu.addAction("导入爆头专属素材…",
                       lambda: self.action_triggered.emit("import_hs", self.kills))
        menu.addSeparator()
        export = menu.addAction("导出这一格…",
                                lambda: self.action_triggered.emit("export", self.kills))
        export.setEnabled(has_assets)
        remove = menu.addAction("删除这一格",
                                lambda: self.action_triggered.emit("delete", self.kills))
        remove.setEnabled(has_assets)
        remove_hs = menu.addAction("删除爆头素材",
                                   lambda: self.action_triggered.emit("delete_hs", self.kills))
        remove_hs.setEnabled(self._has_headshot)
        return menu

    def _show_menu(self, position):
        self.build_menu().exec(self.mapToGlobal(position))


class KillIconLevelGrid(QWidget):
    """五个等级摊成一块板。窄的时候折成两行。"""

    files_dropped = Signal(int, list)
    duration_changed = Signal(int, float)
    action_triggered = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns = 0
        self.cells = {}

        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

        for kills in range(1, 6):
            cell = KillIconLevelCell(kills, self)
            cell.files_dropped.connect(self.files_dropped)
            cell.duration_changed.connect(self.duration_changed)
            cell.action_triggered.connect(self.action_triggered)
            self.cells[kills] = cell

        self.set_columns(5)

    #: 列数由**外面**决定（页面知道滚动可视区有多宽），这里不自己 resizeEvent 反算。
    #: 自己反算会形成回路：列数决定最小宽度、最小宽度又顶回自己的宽度。
    def set_columns(self, columns):
        columns = max(1, int(columns))
        if columns == self._columns:
            return
        self._columns = columns
        for cell in self.cells.values():
            self._layout.removeWidget(cell)
        for index, kills in enumerate(sorted(self.cells)):
            self._layout.addWidget(self.cells[kills], index // columns, index % columns)

    def set_state(self, kills, entry, animation=None, has_headshot=False):
        cell = self.cells.get(int(kills))
        if cell is not None:
            cell.set_state(entry, animation, has_headshot)

    def stop_previews(self):
        for cell in self.cells.values():
            cell.preview.stop()
