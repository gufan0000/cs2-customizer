# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""权限工具：检测管理员身份 / 以管理员身份重启。

背景（2.1.3 强制管理员重构）：
- 2.1.2 及之前：exe 清单 ``uac_admin=True`` + ``main_widget`` 顶层 ``run_as_admin()``
  双重强制提权，每次启动都弹 UAC。
- 2.1.3 起：默认以**普通权限**启动（清单 asInvoker、移除顶层自动提权）。
  实测（2026-06-10，Win10/11）普通权限即可完整使用全屏放大
  （MagInitialize / MagSetFullscreenTransform 均成功），全局热键对
  非提权进程（CS2 默认非提权）同样有效。
- 仅当出现以下两种少数情况时才需要管理员，由 UI 引导用户一键重启提权：
  1. Magnification API 初始化失败（个别安全策略/会话环境）；
  2. 游戏本身以管理员身份运行，导致普通权限的全局热键收不到按键。

设计约束：
- 本模块不依赖 Qt，可在任意早期阶段导入。
- ``restart_as_admin()`` 同时支持源码运行与 PyInstaller 冻结 exe 运行。
- 任何异常都返回 False，绝不让权限逻辑把程序带崩。
"""
from __future__ import annotations

import os
import sys
import subprocess


def is_admin() -> bool:
    """当前进程是否以管理员身份运行。非 Windows / 出错时返回 False。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _build_relaunch_command() -> tuple[str, str]:
    """构造重启命令 (可执行文件, 参数串)。

    - 冻结 exe：``sys.executable`` 就是 CS2 Customizer 本体，参数只带原始 argv[1:]。
    - 源码运行：``sys.executable`` 是 python.exe，参数 = 入口脚本 + argv[1:]。
    """
    if getattr(sys, "frozen", False):
        return sys.executable, subprocess.list2cmdline(sys.argv[1:])
    script = os.path.abspath(sys.argv[0])
    return sys.executable, subprocess.list2cmdline([script] + sys.argv[1:])


def restart_as_admin() -> bool:
    """以管理员身份启动一份新进程（弹 UAC）。

    返回 True 表示新进程已成功请求启动，**调用方应随即正常退出当前进程**
    （例如 ``QApplication.quit()``）；返回 False 表示用户拒绝 UAC 或出错，
    当前进程应继续以普通权限运行。
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        exe, params = _build_relaunch_command()
        workdir = os.getcwd()
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe, params, workdir, 1
        )
        return int(ret) > 32
    except Exception:
        return False
