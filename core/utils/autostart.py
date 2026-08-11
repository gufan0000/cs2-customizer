# -*- coding: utf-8 -*-
"""开机自启（对标主流系统集成，2026-06-10）。

实现方式：HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run 写入启动项。
- 真实来源是注册表本身（is_enabled 直接读注册表），不在 config 里存镜像，
  避免两处状态打架；
- 冻结 exe 写 exe 路径；源码运行写 "python.exe main_widget.py"（开发用）；
- 全程不需要管理员权限（HKCU 当前用户键）。
"""
from __future__ import annotations

import os
import sys

from core.utils.logger import get_logger

logger = get_logger("Autostart")

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "CS2Customizer"


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    script = os.path.abspath(sys.argv[0] or "main_widget.py")
    return f'"{sys.executable}" "{script}"'


def is_supported() -> bool:
    return sys.platform == "win32"


def is_enabled() -> bool:
    """当前是否已设置开机自启（以注册表为准）。"""
    if not is_supported():
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return bool(str(value).strip())
    except FileNotFoundError:
        return False
    except OSError:
        return False


def refresh_if_enabled() -> bool:
    """升级自愈(2.2.0):已开启自启时,把注册表命令刷新为当前 exe 路径。

    exe 文件名带版本号,覆盖升级后注册表会指向已不存在的旧版 exe——
    每次启动自查一次,不一致就重写,用户无感。仅冻结版生效:
    源码开发运行不许劫持用户配置的 exe 自启项。返回是否发生了重写。
    """
    if not is_supported() or not getattr(sys, "frozen", False):
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
    except (FileNotFoundError, OSError):
        return False
    current = _launch_command()
    if str(value).strip() == current:
        return False
    ok = set_enabled(True)
    if ok:
        logger.info(f"自启路径已随升级自愈 -> {current}")
    return ok


def set_enabled(enabled: bool) -> bool:
    """写入/移除自启项。返回是否成功。"""
    if not is_supported():
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
                logger.info(f"已设置开机自启: {_launch_command()}")
            else:
                try:
                    winreg.DeleteValue(key, _VALUE_NAME)
                    logger.info("已取消开机自启")
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        logger.exception("写入开机自启失败")
        return False
