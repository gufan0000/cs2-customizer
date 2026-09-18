# SPDX-License-Identifier: GPL-3.0-or-later
"""前台窗口是不是游戏。

**为什么需要它**：开镜放大挂的是**系统级**全局钩子，而它的默认热键就是
**鼠标右键**（`config.magnifier["primary_hotkey"]` / `secondary_hotkey` 都是「右键」）。
没有这道判断时，玩家 Alt-Tab 出去在浏览器里点一下右键 —— 只要 GSI 上报的
武器还留在启用列表里 —— 整个屏幕就会被 `MagSetFullscreenTransform` 放大。
（RN-657，批 104）

⭐⭐⭐ **判断不出来的时候一律返回 True（放行）。**
这道闸是用来挡误触发的，不是用来决定功能能不能用的：一旦某台机器上
`OpenProcess` 因为权限或杀软拿不到进程名，朝"拦"倒会让整个开镜放大**静默失效**，
而那种故障长得和"功能坏了"一模一样、还没有任何日志线索。
（这是本仓对所有"闸"的统一口径：拦错了看得见，静默失效看不见。）
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

#: 和 `core/audio/game_audio_ducker.DEFAULT_TARGET_PROCESS_NAMES` 保持同一份口径
GAME_PROCESS_NAMES = ("cs2.exe", "csgo.exe")

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_MAX_PATH_WIDE = 32768

#: pid → 进程名。开镜是热路径（一局上百次），每次都 OpenProcess 太贵；
#: pid 在进程活着期间不变，游戏也不会一局换好几次 pid。
_pid_name_cache: dict[int, str] = {}
#: 缓存不封顶就是泄漏：桌面上每点一次右键都可能是一个新 pid。
_PID_CACHE_LIMIT = 64


def _user32():
    return ctypes.windll.user32


def _kernel32():
    return ctypes.windll.kernel32


def _process_name_for_pid(pid: int) -> str:
    """拿 pid 的可执行文件名（小写）。拿不到返回空串。"""
    if pid <= 0:
        return ""
    cached = _pid_name_cache.get(pid)
    if cached is not None:
        return cached

    name = ""
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, wintypes.DWORD(pid))
    if handle:
        try:
            buffer = ctypes.create_unicode_buffer(_MAX_PATH_WIDE)
            size = wintypes.DWORD(_MAX_PATH_WIDE)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                name = os.path.basename(buffer.value or "").lower()
        except Exception:
            name = ""
        finally:
            kernel32.CloseHandle(handle)

    if name:
        if len(_pid_name_cache) >= _PID_CACHE_LIMIT:
            _pid_name_cache.clear()
        _pid_name_cache[pid] = name
    return name


def foreground_process_name() -> str:
    """当前前台窗口所属进程的文件名（小写）。拿不到返回空串。"""
    try:
        hwnd = _user32().GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD(0)
        _user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return _process_name_for_pid(int(pid.value))
    except Exception:
        return ""


def game_is_in_foreground(process_names=GAME_PROCESS_NAMES) -> bool:
    """游戏窗口是不是当前前台窗口。**判断不出来时返回 True**（见模块头）。"""
    name = foreground_process_name()
    if not name:
        return True
    return name in {str(item).lower() for item in process_names}


def reset_cache() -> None:
    """判据用：把 pid→名字的缓存清空，免得一条判据的替身喂给下一条。"""
    _pid_name_cache.clear()
