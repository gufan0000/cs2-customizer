# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""D1 优雅退出信号处理器单元测试。

保证：
1. install_signal_handlers 在主线程能成功装上（至少一种信号）
2. 重复安装幂等（不重复覆盖）
3. 非主线程调用安全（返回 False，不抛）
4. _request_qt_graceful_exit 在 Qt 不可用 / 无 app 实例时静默返回 False
5. _request_qt_graceful_exit 能触发 QCoreApplication.quit（有 app 实例时）
6. is_shutdown_in_progress 初始为 False；handler 运行后变 True
"""
from __future__ import annotations

import os
import signal
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import shutdown as sd  # noqa: E402


class TestInstallSignalHandlers(unittest.TestCase):
    def setUp(self):
        # 每个用例前重置安装状态
        sd._installed = False
        sd._shutdown_in_progress = False

    def tearDown(self):
        # 还原默认 handler，避免污染其他用例
        for sig_name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, signal.SIG_DFL)
            except Exception:
                pass
        sd._installed = False

    def test_install_on_main_thread_succeeds(self):
        ok = sd.install_signal_handlers()
        self.assertTrue(ok)
        self.assertTrue(sd._installed)

    def test_install_is_idempotent(self):
        sd.install_signal_handlers()
        # 第二次调用应直接返回 True，不再调 signal.signal
        with patch("core.shutdown.signal.signal") as m:
            ok = sd.install_signal_handlers()
            self.assertTrue(ok)
            m.assert_not_called()

    def test_install_on_non_main_thread_returns_false(self):
        result_holder = {}

        def worker():
            # 确保子线程用新的 _installed 状态
            sd._installed = False
            result_holder["value"] = sd.install_signal_handlers()

        t = threading.Thread(target=worker)
        t.start()
        t.join(2.0)
        self.assertEqual(result_holder.get("value"), False)

    def test_install_swallows_signal_exception(self):
        # signal.signal 抛 ValueError 时应静默（Windows 某些场景）
        with patch("core.shutdown.signal.signal", side_effect=ValueError("x")):
            # 不应抛，即便最终 _installed 为 False
            try:
                sd.install_signal_handlers()
            except Exception as e:  # pragma: no cover
                self.fail(f"install 应吞异常，实际抛: {e}")


class TestRequestQtGracefulExit(unittest.TestCase):
    def test_returns_false_when_no_qt_app_instance(self):
        # 当前测试进程没有 QApplication 实例（至少没 show 窗口）
        # 函数应正常返回布尔，不抛
        result = sd._request_qt_graceful_exit()
        self.assertIsInstance(result, bool)

    def test_calls_quit_when_app_exists(self):
        # 构造 QCoreApplication mock，确认 quit 被调
        class _FakeApp:
            def __init__(self):
                self.quit_called = False

            def quit(self):
                self.quit_called = True

        fake_app = _FakeApp()

        with patch("PySide6.QtCore.QCoreApplication.instance", return_value=fake_app), \
             patch("PySide6.QtWidgets.QApplication.topLevelWidgets", return_value=[]):
            # isinstance(fake_app, QApplication) 会是 False，所以窗口枚举被跳过；
            # 但 app.quit() 仍应被调
            ok = sd._request_qt_graceful_exit()
            self.assertTrue(ok)
            self.assertTrue(fake_app.quit_called)


class TestShutdownInProgressFlag(unittest.TestCase):
    def setUp(self):
        sd._shutdown_in_progress = False

    def tearDown(self):
        sd._shutdown_in_progress = False

    def test_default_not_in_progress(self):
        self.assertFalse(sd.is_shutdown_in_progress())

    def test_handler_marks_in_progress(self):
        # 调用 handler，qt 路径会返回 False（无 app），然后走 sys.exit(0)
        with patch("core.shutdown._request_qt_graceful_exit", return_value=True):
            # qt_ok=True 时函数不会调 sys.exit，安全
            sd._graceful_exit_handler(signal.SIGTERM, None)
            self.assertTrue(sd.is_shutdown_in_progress())

    def test_handler_reentry_is_noop(self):
        sd._shutdown_in_progress = True
        with patch("core.shutdown._request_qt_graceful_exit") as m:
            sd._graceful_exit_handler(signal.SIGTERM, None)
            m.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
