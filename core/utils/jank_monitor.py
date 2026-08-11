# -*- coding: utf-8 -*-
"""主线程卡顿探测器(2.2.0 起常驻)。

原理:50ms 心跳定时器,实际间隔超过阈值=主线程被同步任务卡住。
每次卡顿打一行日志(含启动后秒数),用于定位"冻一下"的元凶与防回归。
开销:每 50ms 一次 perf_counter 比较,可忽略。

2.2.2(UP-002)两处修正:
1. 启动时机提前到 QApplication 创建之后(原先在 window.show() 之后)——
   主窗构建那 1.9~5.0 秒恰恰是最大的一段主线程停顿,原先完全测不到。
2. "启动后 Xs"改用进程真实起点 _BOOT_T0(由调用方传入 t0),原先用探测器自己的
   构造时刻,导致日志里的时间轴整体比真实启动晚约 5.3 秒,没法和[启动相位]对齐。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer

from core.utils.logger import get_logger

_THRESHOLD_MS = 120  # 超过此值视为可感知卡顿
_INTERVAL_MS = 50


class JankMonitor(QObject):
    def __init__(self, parent=None, t0: float | None = None):
        super().__init__(parent)
        self._logger = get_logger("Jank")
        # t0 = 进程启动的真实时刻(perf_counter 口径)。不传则退化为构造时刻,
        # 行为与 2.2.1 一致。
        self._t0 = t0 if t0 is not None else time.perf_counter()
        self._last = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setInterval(_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        now = time.perf_counter()
        stall_ms = (now - self._last) * 1000 - _INTERVAL_MS
        if stall_ms > _THRESHOLD_MS:
            self._logger.info(
                f"[卡顿] 主线程停顿 {stall_ms:.0f}ms (启动后 {now - self._t0:.1f}s)"
            )
        self._last = now


_instance = None


def start_jank_monitor(parent=None, t0: float | None = None) -> JankMonitor:
    """启动常驻卡顿探测器(幂等)。

    Args:
        parent: QObject 父对象,用于生命周期挂靠。
        t0: 进程启动时刻(perf_counter 口径),用于让"启动后 Xs"与[启动相位]对齐。
    """
    global _instance
    if _instance is None:
        _instance = JankMonitor(parent, t0=t0)
    return _instance
