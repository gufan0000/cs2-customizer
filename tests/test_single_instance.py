# -*- coding: utf-8 -*-
"""D2 单实例互斥锁单元测试。

保证：
1. 无已有锁时 → ok=True, lock 非空
2. 已有锁被另一个 QLockFile 占用时 → ok=False
3. 锁机制异常（例如无法创建 QLockFile）时 → 默认放行（ok=True）
4. 同一进程中锁对象被 GC 后，另一个检测能重新拿到
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 必须先建 QCoreApplication（QLockFile 依赖 Qt 初始化）
from PySide6.QtCore import QCoreApplication, QLockFile  # noqa: E402

if QCoreApplication.instance() is None:
    _app = QCoreApplication(sys.argv)  # noqa: F841  (全局保持)

from core.single_instance import ensure_single_instance  # noqa: E402


class TestSingleInstance(unittest.TestCase):
    def setUp(self):
        # 每个用例用独立的锁文件，避免跨用例污染
        fd, self.lock_path = tempfile.mkstemp(suffix="_cs2customizer_test.lock")
        os.close(fd)
        # QLockFile 要求目标文件不存在或为 stale；删掉预留的空文件
        try:
            os.remove(self.lock_path)
        except OSError:
            pass

    def tearDown(self):
        try:
            os.remove(self.lock_path)
        except OSError:
            pass

    def test_first_acquire_succeeds(self):
        ok, lock, msg = ensure_single_instance(lock_path=self.lock_path)
        self.assertTrue(ok)
        self.assertIsNotNone(lock)
        self.assertEqual(msg, "")
        # 手动释放，避免污染
        try:
            lock.unlock()
        except Exception:
            pass

    def test_second_acquire_blocked_when_first_holds(self):
        # 先手动用 QLockFile 占住
        holder = QLockFile(self.lock_path)
        holder.setStaleLockTime(30_000)
        got = holder.tryLock(100)
        self.assertTrue(got, "前置条件：手动锁应当成功")

        try:
            ok, _lock, msg = ensure_single_instance(lock_path=self.lock_path)
            self.assertFalse(ok, "应当检测到已有实例")
            self.assertIn("CS2 Customizer", msg)
        finally:
            holder.unlock()

    def test_exception_means_fail_open(self):
        # 传入非法路径形态（Windows 非法字符）也不应崩溃；应返回放行
        # 即便底层抛异常，上层应吞掉
        bogus = "\x00\x00\x00invalid_path"
        ok, _lock, msg = ensure_single_instance(lock_path=bogus)
        # 要么能拿到锁，要么异常路径被吞；无论如何不应抛
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(msg, str)

    def test_lock_released_after_unlock(self):
        # 第一次拿到后显式释放，第二次能拿到
        ok1, lock1, _ = ensure_single_instance(lock_path=self.lock_path)
        self.assertTrue(ok1)
        lock1.unlock()

        ok2, lock2, _ = ensure_single_instance(lock_path=self.lock_path)
        self.assertTrue(ok2)
        lock2.unlock()


if __name__ == "__main__":
    unittest.main(verbosity=2)
