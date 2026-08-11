# -*- coding: utf-8 -*-
"""D1：信号兼容的优雅退出路径。

目的：
    已有的 closeEvent（gui_widget.MainWindow.closeEvent）已经包含完整的资源
    清理（音频、击杀图标、准心动画、屏幕特效、放大镜、视角、语音输出、闪光、
    动画管理器、效果管理器、页面过渡、config.save_config_now 等）。
    本模块只负责一件事：在"非正常退出路径"下也把 closeEvent 跑一次。

覆盖场景：
    - Ctrl+C 于控制台（SIGINT）
    - 外部 kill / 服务 stop（SIGTERM）
    - Windows 任务管理器"结束任务"（温和模式，Qt 会收到 close 事件）

不覆盖场景（由 OS 决定）：
    - taskkill /f（SIGKILL 等价）
    - 物理断电 / BSOD

设计原则：
    - 所有异常 fail-open：信号处理器自身挂掉时，退化为 Python 默认行为
      （SIGINT → KeyboardInterrupt，SIGTERM → 立即退出），不给用户添乱
    - 对已有 closeEvent 完全零侵入
    - 只在主线程安装信号；其他线程调用静默 no-op（signal.signal 的限制）
"""
from __future__ import annotations

import signal
import sys
import threading

from core.utils.logger import get_logger

logger = get_logger(__name__)

_installed_lock = threading.Lock()
_installed = False
_shutdown_in_progress = False


def _request_qt_graceful_exit() -> bool:
    """请求 Qt 应用优雅退出：关闭所有顶级窗口 → 让事件循环退出。

    返回 True 表示成功发起 Qt 退出流程；False 表示 Qt 不可用或失败。
    close() 会触发 QMainWindow.closeEvent，已有清理逻辑随之执行。
    """
    try:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWidgets import QApplication
    except Exception:
        return False

    try:
        app = QCoreApplication.instance()
        if app is None:
            return False

        # 关闭所有顶级窗口 → 触发各自 closeEvent
        if isinstance(app, QApplication):
            try:
                for w in app.topLevelWidgets():
                    if w is not None and w.isWindow() and w.isVisible():
                        try:
                            w.close()
                        except Exception as e:
                            logger.warning(f"close window 失败: {e}")
            except Exception as e:
                logger.warning(f"枚举顶级窗口失败: {e}")

        # 退出事件循环
        try:
            app.quit()
        except Exception as e:
            logger.warning(f"app.quit 失败: {e}")
        return True
    except Exception as e:
        logger.warning(f"Qt 优雅退出请求异常: {e}")
        return False


def _graceful_exit_handler(signum, frame):  # noqa: ARG001
    """SIGTERM / SIGINT 处理：先请求 Qt 优雅退出，失败再 sys.exit。"""
    global _shutdown_in_progress
    # 防止在 close 过程中再收同一信号导致递归
    if _shutdown_in_progress:
        return
    _shutdown_in_progress = True

    try:
        logger.info(f"收到信号 {signum}，请求优雅关闭")
    except Exception:
        pass

    qt_ok = False
    try:
        qt_ok = _request_qt_graceful_exit()
    except Exception:
        qt_ok = False

    if qt_ok:
        # Qt 已启动退出流程；事件循环会自然返回
        # 不调 sys.exit，避免打断 close 路径
        return

    # Qt 不可用 / 尚未启动：按默认行为退出
    try:
        sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        # 极端兜底
        import os
        os._exit(0)


def install_signal_handlers() -> bool:
    """安装 SIGTERM / SIGINT 处理器。

    只在主线程生效（Python 限制）；其他线程调用返回 False。
    重复调用幂等；任何异常静默退化为未安装状态。
    """
    global _installed
    with _installed_lock:
        if _installed:
            return True

        # signal.signal 只能在主线程调用
        if threading.current_thread() is not threading.main_thread():
            return False

        success_any = False
        for sig_name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, _graceful_exit_handler)
                success_any = True
            except (ValueError, OSError, AttributeError) as e:
                # Windows 不支持部分信号；记录但不阻塞
                try:
                    logger.debug(f"信号 {sig_name} 安装失败（忽略）: {e}")
                except Exception:
                    pass

        _installed = success_any
        return success_any


def is_shutdown_in_progress() -> bool:
    """供外部查询：是否正在走退出流程（便于避免重复操作）。"""
    return _shutdown_in_progress
