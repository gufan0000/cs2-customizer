#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
管理员权限请求工具
自动检测并请求管理员权限
"""
import sys
import os
import ctypes
from core.utils.logger import get_logger

logger = get_logger("RequestAdmin")

def is_admin():
    """检查是否有管理员权限"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def run_as_admin():
    """以管理员身份重新运行程序"""
    if sys.platform != 'win32':
        logger.warning("此功能仅支持Windows系统")
        return False
    
    try:
        # 获取当前脚本路径
        script = os.path.abspath(sys.argv[0])
        params = ' '.join([script] + sys.argv[1:])
        
        # 使用ShellExecute以管理员身份运行
        ret = ctypes.windll.shell32.ShellExecuteW(
            None,           # hwnd
            "runas",        # 以管理员身份运行
            sys.executable, # Python解释器路径
            params,         # 参数（包含脚本路径）
            None,           # 工作目录
            1               # SW_SHOWNORMAL
        )
        
        # 如果成功请求权限（返回值>32），退出当前进程
        if ret > 32:
            return True
        else:
            logger.error(f"请求管理员权限失败，错误代码: {ret}")
            return False
            
    except Exception as e:
        logger.error(f"请求管理员权限时出错: {e}")
        return False

if __name__ == "__main__":
    if is_admin():
        logger.info("✓ 已有管理员权限")
    else:
        logger.warning("✗ 没有管理员权限")
        logger.info("正在请求管理员权限...")
        if run_as_admin():
            logger.info("已请求管理员权限，请在UAC对话框中点击'是'")
        else:
            logger.error("请求失败")


