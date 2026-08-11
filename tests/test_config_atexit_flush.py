# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""A3 配置 atexit flush 单元测试。

保证：
1. 有挂起 timer 时 _atexit_flush 会调用 _do_save_config 并清空 timer
2. 无挂起 timer 时 _atexit_flush 不调 _do_save_config（no-op）
3. _do_save_config 抛异常时 _atexit_flush 吞掉（atexit 钩子必须不抛）
4. 注册 atexit 只执行一次（_atexit_registered 幂等）
"""
from __future__ import annotations

import os
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import Config  # noqa: E402


def _bare_config() -> Config:
    """构造一个"裸" Config 实例，跳过重型 __init__（load_config 等）。"""
    obj = Config.__new__(Config)
    obj._save_timer = None
    obj._save_lock = threading.Lock()
    obj._load_error = None
    obj._atexit_registered = False
    return obj


class TestAtexitFlush(unittest.TestCase):
    def test_flush_noop_when_no_pending(self):
        c = _bare_config()
        with patch.object(c, "_do_save_config") as m:
            c._atexit_flush()
            m.assert_not_called()

    def test_flush_calls_save_when_timer_pending(self):
        c = _bare_config()
        # 长周期 timer，不会自动 fire
        timer = threading.Timer(600, lambda: None)
        c._save_timer = timer
        try:
            with patch.object(c, "_do_save_config") as m:
                c._atexit_flush()
                m.assert_called_once()
            # 应已清空
            self.assertIsNone(c._save_timer)
        finally:
            try:
                timer.cancel()
            except Exception:
                pass

    def test_flush_swallows_save_exception(self):
        c = _bare_config()
        timer = threading.Timer(600, lambda: None)
        c._save_timer = timer
        try:
            with patch.object(
                c, "_do_save_config", side_effect=RuntimeError("disk full")
            ):
                # 绝不允许抛异常（atexit 钩子契约）
                try:
                    c._atexit_flush()
                except Exception as e:  # pragma: no cover
                    self.fail(f"_atexit_flush 应吞异常，实际抛出: {e}")
        finally:
            try:
                timer.cancel()
            except Exception:
                pass

    def test_register_is_idempotent(self):
        c = _bare_config()
        # 模拟两次注册
        with patch("config.atexit.register") as m:
            c._register_atexit_flush()
            c._register_atexit_flush()
            self.assertEqual(m.call_count, 1)
        self.assertTrue(c._atexit_registered)

    def test_register_failure_is_silent(self):
        c = _bare_config()
        with patch("config.atexit.register", side_effect=RuntimeError("x")):
            try:
                c._register_atexit_flush()
            except Exception as e:  # pragma: no cover
                self.fail(f"注册失败应静默，实际抛: {e}")
        self.assertFalse(c._atexit_registered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
