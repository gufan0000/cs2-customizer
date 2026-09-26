# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""通用文件拖拽导入(R1-8,2026-06-12)。

为什么用 eventFilter 而不是 mixin 覆写 dragEnterEvent:页面类继承链各异,
运行期给实例挂 filter 零侵入,且 Qt 的虚函数分发对 monkey-patch 不可靠。

用法:
    from widgets.drop_import_mixin import enable_file_drop
    enable_file_drop(page_widget, (".xchr",), self._on_files_dropped)
handler 收到的是「通过扩展名过滤后的本地文件路径列表」;空列表不会回调。
"""
from __future__ import annotations

from typing import Callable, Iterable, List

from PySide6.QtCore import QEvent, QObject


def urls_from_drop(event) -> list:
    """从一个拖拽事件里取 URL 列表；取不到就当"没有"。

    ⛔⛔ **手写 `dragEnterEvent` / `dropEvent` 一律走这个函数**，
    不许再写 `event.mimeData().hasUrls()`：Qt 侧对象被提前回收时 PySide 会还你
    一个光秃秃的 QObject，直接点属性就在 **Qt 的 notify 循环内部**抛
    AttributeError（`dragEnterEvent` 那一侧连 try 都没有）。
    ⭐ RN-674：这条防法本来只是本文件里的一段注释，而全仓另外两处手写的
    **一处都没照做** ⇒ 抽成函数 + 配一条扫得到分母的判据。叙事见登记册。
    """
    mime = event.mimeData() if callable(getattr(event, "mimeData", None)) else None
    if mime is None or not callable(getattr(mime, "hasUrls", None)) or not mime.hasUrls():
        return []
    try:
        return list(mime.urls())
    except Exception:
        return []


class _FileDropFilter(QObject):
    def __init__(self, widget, extensions: Iterable[str], handler: Callable[[List[str]], None],
                 accept_directories: bool = False):
        super().__init__(widget)
        self._extensions = tuple(e.lower() for e in extensions)
        self._handler = handler
        self._accept_directories = bool(accept_directories)
        widget.setAcceptDrops(True)
        widget.installEventFilter(self)

    def _matched_paths(self, event) -> List[str]:
        import os

        # ⭐ 防法只有一份 —— 见 `urls_from_drop` 的 docstring（RN-674）。
        paths = []
        for url in urls_from_drop(event):
            if not url.isLocalFile():
                continue
            p = url.toLocalFile()
            # KI-6：目录路径永远不会以扩展名结尾，所以按后缀过滤时**文件夹恒不匹配**
            # ——DragEnter 都不接受，鼠标是禁止图标，什么提示都没有。而帧序列
            # 的唯一形态就是文件夹，等于最主流的社区素材根本拖不进来。
            if self._accept_directories and os.path.isdir(p):
                paths.append(p)
                continue
            if p.lower().endswith(self._extensions):
                paths.append(p)
        return paths

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if self._matched_paths(event):
                event.acceptProposedAction()
                return True
        elif et == QEvent.Type.Drop:
            paths = self._matched_paths(event)
            if paths:
                event.acceptProposedAction()
                try:
                    self._handler(paths)
                except Exception:
                    # 不再静默吞错:至少记日志(会进诊断信息日志尾部),便于排障
                    try:
                        from core.utils.logger import get_logger
                        get_logger("DropImport").exception("拖拽导入处理失败")
                    except Exception:
                        pass
                return True
        # QObject.eventFilter 基类语义即 False(不拦截);显式返回避免对 event 再做类型分发
        return False


def enable_file_drop(widget, extensions: Iterable[str], handler: Callable[[List[str]], None],
                     accept_directories: bool = False) -> _FileDropFilter:
    """给任意 widget 开启文件拖拽导入,返回 filter(强引用挂在 widget 上)。

    `accept_directories=True` 时文件夹也能拖进来(击杀图标的帧序列)。
    默认关着——别的页面(如准心 .xchr)拖进一个文件夹只会让 handler 收到
    一个它处理不了的路径。
    """
    filt = _FileDropFilter(widget, extensions, handler, accept_directories)
    # 防 GC:挂到 widget 属性
    existing = getattr(widget, "_file_drop_filters", None)
    if existing is None:
        widget._file_drop_filters = [filt]
    else:
        existing.append(filt)
    return filt


def rescan_if_imported(page, *refreshers) -> bool:
    """进页时：上次看过之后「导入资源」装过东西 ⇒ 把这一页的风格列表重扫一遍（批 123）。

    给**进页本来不重扫**的那几页用（特殊音效 / 枪声 / 闪光）；自带冷却重扫的页在自己的
    `showEvent` 里直接问 `resource_generation.take_news`。
    """
    import core.resource_generation as resource_generation

    if not resource_generation.take_news(page):
        return False
    for refresh in refreshers:
        try:
            refresh()
        except Exception:
            from core.utils.logger import get_logger

            get_logger("DropImport").exception("导入后进页重扫失败")
    return True


#: 社区下下来的「一整包」长这样（批 123）。单个音频仍走各页自己的「新建风格」。
PACK_EXTENSIONS = (".zip", ".rar", ".7z")


def enable_pack_drop(widget) -> _FileDropFilter:
    """让一页收「下好的包」：zip / rar / 7z / 文件夹 ⇒ 转交「导入资源」（批 123）。

    ⭐ 和同一页上已有的「拖单个音频 ⇒ 新建风格」并存：两个 filter 各认各的后缀，
    没认出的不拦（`eventFilter` 回 False），另一个照样收得到。
    rar / 7z 也收下 —— 导入页会按文件头认出来并说一句「先解压」，比鼠标变禁止图标强。
    """
    import core.resource_generation as resource_generation
    from widgets.page_route import hand_to_importer

    # 各页都在构造末尾调它、构造时刚扫过一遍 ⇒ 顺手记下「我看到的是这一代」，
    # 之后 `showEvent` 里 `take_news` 才分得清「错过了一次导入」。
    resource_generation.take_news(widget)
    return enable_file_drop(widget, PACK_EXTENSIONS,
                            lambda paths: hand_to_importer(widget, paths),
                            accept_directories=True)
