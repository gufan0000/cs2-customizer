# SPDX-License-Identifier: GPL-3.0-or-later
"""别让 Windows 把 CS2 Customizer 当「后台节能进程」降频（EcoQoS，批 116）。

CS2 全屏时 CS2 Customizer 一直在后台。Win11 会给后台进程开 EcoQoS：调度到能效核、限频 ——
症状是「击杀音效 / 闪光有时候慢半拍」，是最难归因的一类。
这里只**关掉执行速度节流**（`PROCESS_POWER_THROTTLING_EXECUTION_SPEED`），
⛔ **不提优先级**：HIGH / REALTIME 会去抢 CS2 自己的输入线程。

收益只能进游戏实测（M7），判据只断言「调用发生、参数对」，不做墙钟门禁。
"""
from __future__ import annotations

import ctypes

from core.utils.logger import get_logger

logger = get_logger("ProcessPower")

PROCESS_POWER_THROTTLING = 4                 # PROCESS_INFORMATION_CLASS::ProcessPowerThrottling
PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1


class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]


def opt_out_of_eco_qos(kernel32=None) -> bool:
    """ControlMask 点名「执行速度」、StateMask 置 0 = 这一项由我们管、且不节流。老系统没这个 API 就算了。

    ⚠ 批 126 进游戏自测逮到：批 116 起这一调用**从来没成功过**。没声明类型时 `GetCurrentProcess()`
    的伪句柄 -1 按 32 位 int 传进 64 位的 HANDLE 参数，高 32 位是 0 ⇒ 句柄无效 ⇒ 每次都「未生效」。
    ⇒ 用自己的 WinDLL 实例声明 argtypes / restype（不改全局 `windll.kernel32`，别的模块也在用它）。"""
    try:
        if kernel32 is None:
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            kernel32.SetProcessInformation.restype = wintypes.BOOL
        state = PROCESS_POWER_THROTTLING_STATE(
            PROCESS_POWER_THROTTLING_CURRENT_VERSION, PROCESS_POWER_THROTTLING_EXECUTION_SPEED, 0)
        ok = bool(kernel32.SetProcessInformation(
            kernel32.GetCurrentProcess(), PROCESS_POWER_THROTTLING,
            ctypes.byref(state), ctypes.sizeof(state)))
    except Exception:
        ok = False
    logger.info(f"[电源] 关闭 EcoQoS 执行速度节流：{'成功' if ok else '未生效（系统不支持或被拒）'}")
    return ok
