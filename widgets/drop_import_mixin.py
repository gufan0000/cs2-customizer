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


class _FileDropFilter(QObject):
    def __init__(self, widget, extensions: Iterable[str], handler: Callable[[List[str]], None]):
        super().__init__(widget)
        self._extensions = tuple(e.lower() for e in extensions)
        self._handler = handler
        widget.setAcceptDrops(True)
        widget.installEventFilter(self)

    def _matched_paths(self, event) -> List[str]:
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return []
        paths = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            p = url.toLocalFile()
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


def enable_file_drop(widget, extensions: Iterable[str], handler: Callable[[List[str]], None]) -> _FileDropFilter:
    """给任意 widget 开启文件拖拽导入,返回 filter(强引用挂在 widget 上)。"""
    filt = _FileDropFilter(widget, extensions, handler)
    # 防 GC:挂到 widget 属性
    existing = getattr(widget, "_file_drop_filters", None)
    if existing is None:
        widget._file_drop_filters = [filt]
    else:
        existing.append(filt)
    return filt
