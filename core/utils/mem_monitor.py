# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""进程内存采样器(2.2.2,常驻,UP-003)。

为什么要有它:"用久了变卡 / 内存一直涨"是本专项唯一无法回归的指标——
没有任何内存埋点,优化前后没法比对。本模块每 60 秒打一行,
让 scripts/ui_perf_probe.py 能算出"起始 / 峰值 / 增长斜率(MB/h)"。

实现约束(见 docs/ui-perf/04_设计约束与红线.md §四):
- 不引 psutil。打包链路的 hiddenimports 只扫种子文件一层 AST,新增第三方依赖
  可能只在打包版炸;而 ctypes + psapi 是 Windows 自带,零依赖零风险。
- 放在 core/ 而不是根目录:PyArmor 只混淆根目录 .py,新增根模块要同步混淆清单。

开销:每 60 秒一次系统调用,可忽略。取不到值就自动停表,绝不影响软件功能。
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QObject, QTimer

from core.utils.logger import get_logger

_INTERVAL_MS = 60_000  # 60 秒一采样;再密对定位增长趋势没有帮助


def _read_memory_bytes():
    """返回 (工作集, 私有提交) 字节数;失败返回 (0, 0)。

    工作集(WorkingSet)≈ 任务管理器里的"内存"列;
    私有提交(PrivateUsage)排除了共享的 DLL,更能反映本进程自己的增长。
    """
    if os.name != "nt":
        return 0, 0
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)

        kernel32 = ctypes.windll.kernel32
        # 必须显式声明:64 位下 ctypes 默认把返回值当 c_int,会把 HANDLE 截断成
        # 32 位,导致后续调用拿到无效句柄而静默返回 0。
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []

        # GetProcessMemoryInfo 在 psapi.dll;现代 Windows 也在 kernel32 里以
        # K32GetProcessMemoryInfo 导出,两者都试一遍更稳。
        # 注意:库句柄必须在循环体内取。写成元组字面量的话 ctypes.windll.psapi 会在
        # 进入循环前就被求值(触发 LoadLibrary),psapi 加载失败时异常直接冲出循环,
        # 回退分支永远走不到——恰恰在唯一需要回退的场景下失效。
        fn = None
        for lib_name, func_name in (
            ("psapi", "GetProcessMemoryInfo"),
            ("kernel32", "K32GetProcessMemoryInfo"),
        ):
            try:
                fn = getattr(getattr(ctypes.windll, lib_name), func_name)
                break
            except Exception:
                continue
        if fn is None:
            return 0, 0
        fn.restype = wintypes.BOOL
        fn.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]

        ok = fn(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        if not ok:
            return 0, 0
        return int(counters.WorkingSetSize), int(counters.PrivateUsage)
    except Exception:
        return 0, 0


_MAX_CONSECUTIVE_FAILURES = 3


class MemMonitor(QObject):
    def __init__(self, parent=None, t0: float | None = None):
        super().__init__(parent)
        self._logger = get_logger("Mem")
        self._t0 = t0 if t0 is not None else time.perf_counter()
        self._fail_streak = 0
        self._timer = QTimer(self)
        self._timer.setInterval(_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()  # 立即采一次,作为本次会话的起始值

    def _tick(self):
        # 平台不支持是永久性的,直接停表;API 调用失败可能只是瞬时的
        # (安全软件拦一次、启动最繁忙时刻),不能一次失败就永久失明。
        if os.name != "nt":
            self._timer.stop()
            return

        rss, priv = _read_memory_bytes()
        if not rss and not priv:
            self._fail_streak += 1
            if self._fail_streak >= _MAX_CONSECUTIVE_FAILURES:
                self._timer.stop()
                # 必须留痕:否则排查时只看到"这台机器怎么没有 [内存] 行",
                # 无法区分是老版本还是探针挂了。
                self._logger.warning(
                    f"[内存] 连续 {self._fail_streak} 次读取失败,已停止采样"
                )
            return

        self._fail_streak = 0
        elapsed = time.perf_counter() - self._t0
        self._logger.info(
            f"[内存] rss={rss / 1048576:.0f}MB priv={priv / 1048576:.0f}MB "
            f"(启动后 {elapsed:.1f}s)"
        )


_instance = None


def start_mem_monitor(parent=None, t0: float | None = None) -> MemMonitor:
    """启动常驻内存采样器(幂等)。

    Args:
        parent: QObject 父对象,用于生命周期挂靠。
        t0: 进程启动时刻(perf_counter 口径),与卡顿探测器共用同一条时间轴。
    """
    global _instance
    if _instance is None:
        _instance = MemMonitor(parent, t0=t0)
    return _instance
