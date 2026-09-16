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

try:  # PySide6 一定带 shiboken6；真缺了也只是少一道预检，兜底仍在 except RuntimeError
    import shiboken6
except Exception:  # pragma: no cover - 正常环境到不了这里
    shiboken6 = None

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
        self._host_gone_logged = False

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, fn, label="导入", cancelled_exc=None, error_exc=None):
        """`cancelled_exc` / `error_exc` 让别的导入链路复用这条线程模型。

        ⚠ 默认值就是击杀图标那两个 ⇒ **现有调用零变化**。
        ⭐ 2026-09-16 泛化：资源导入统一化需要同样的"后台跑 + 进度 + 取消"，
        而再写一个一模一样的 task 类只会让两份各自漂。
        """
        if self.running:
            return False
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run, args=(fn, label, cancelled_exc, error_exc),
            daemon=True, name="KillIconImport")
        self._thread.start()
        return True

    def cancel(self):
        self._cancel.set()

    def _run(self, fn, label, cancelled_exc=None, error_exc=None):
        cancelled_types = (KillIconImportCancelled,) + (
            (cancelled_exc,) if cancelled_exc else ())
        error_types = (KillIconImportError,) + ((error_exc,) if error_exc else ())
        try:
            result = fn(self._emit_progress, self._cancel.is_set)
        except cancelled_types:
            self._safe_emit("cancelled")
            return
        except error_types as exc:
            self._safe_emit("failed", str(exc))
            return
        except Exception as exc:  # 防御：PIL / zipfile 也可能抛别的
            logger.error(f"{label}失败: {exc}")
            self._safe_emit("failed", f"发生了预料之外的错误：{exc}")
            return
        self._safe_emit("finished", result)

    def _safe_emit(self, signal_name, *args) -> bool:
        """发一个面向宿主的通知信号；宿主已被销毁时安全失败并返回 False。

        ⭐⭐⭐ 与 RN-652（`core/audio/audio_task_runner`）**逐字同族**：
        worker 跑在后台线程，而它 emit 的四个信号都挂在 self 上。宿主
        （这个 QObject 的 C++ 部分）一旦在任务跑着时被删，emit 就抛
        `RuntimeError: Signal source has been deleted`。
        本文件已实测复现（`shiboken6.delete(task)` 之后线程被未捕获异常打死）。

        ⚠ 要害不是"宿主没了"，是**错误处理路径本身依赖那个已经坏掉的东西**：
        上面三个 `except` 分支里的 emit 会**再抛一次**，这一次没人接 ⇒
        worker 线程静默死亡，用户看到的是进度框永远停在那儿。

        ⛔ 信号名传字符串而不是直接传 `self.failed`：属性访问本身也要在
        保护区里才算数 —— 把它留在调用处，等于把这条缺陷原样再犯一遍。
        """
        try:
            if shiboken6 is not None and not shiboken6.isValid(self):
                self._note_host_gone(signal_name)
                return False
            getattr(self, signal_name).emit(*args)
            return True
        except RuntimeError:
            # isValid 与 emit 之间还有一个竞态窗口：宿主可能正好在这一瞬被删
            self._note_host_gone(signal_name)
            return False

    def _note_host_gone(self, signal_name):
        """宿主失效整个任务只记一行；记日志这件事本身也绝不许抛。"""
        try:
            if self._host_gone_logged:
                return
            self._host_gone_logged = True
            logger.warning(
                f"[KillIconImport] 宿主已销毁，信号停发"
                f"（首见于 {signal_name}），任务继续跑完")
        except Exception:
            pass

    def _emit_progress(self, done, total, stage):
        self._safe_emit("progress", int(done), int(total), str(stage))
