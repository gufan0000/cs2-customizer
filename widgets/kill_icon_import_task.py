# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""把一次导入挪到后台线程（KI-5）。

不是控件，放在 `widgets/` 只因为它需要 Qt 信号、而且只有设置页用它。

为什么必须挪：导入要把整套帧解码、归一化、（可选）抠背景裁边、再打成图集。
600 帧 1024px 的素材做完这一串是**秒级**的，而在 KI-5 之前这一串全跑在 UI
线程上——表现是点完"导入"整个界面卡死，没有进度、没法取消，而且卡多久由
用户素材的大小决定。

线程模型与 `kill_icon_player` 同款：工作线程只 `emit`，改界面的槽由 Qt 排队
投递回主线程。**别改成 DirectConnection**。

PIL 的 Image 对象在工作线程里创建、在工作线程里用完即弃，不跨线程传——
跨线程传回来的只有一个结果字典。
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from core.kill_icon_import import KillIconImportCancelled, KillIconImportError
from core.utils.logger import get_logger

logger = get_logger("KillIconImportTask")


class KillIconImportTask(QObject):
    """跑一个 `fn(progress, cancel)`，把结果送回主线程。"""

    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = threading.Event()
        self._thread = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, fn, label="导入"):
        if self.running:
            return False
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run, args=(fn, label), daemon=True, name="KillIconImport")
        self._thread.start()
        return True

    def cancel(self):
        self._cancel.set()

    def _run(self, fn, label):
        try:
            result = fn(self._emit_progress, self._cancel.is_set)
        except KillIconImportCancelled:
            self.cancelled.emit()
            return
        except KillIconImportError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # 防御：PIL / zipfile 也可能抛别的
            logger.error(f"{label}失败: {exc}")
            self.failed.emit(f"发生了预料之外的错误：{exc}")
            return
        self.finished.emit(result)

    def _emit_progress(self, done, total, stage):
        self.progress.emit(int(done), int(total), str(stage))
