# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-652 的同族：击杀图标导入任务的宿主被销毁之后，线程不许抛出未捕获异常。

## 为什么会有第二份

`core/audio/audio_task_runner` 那条修完（RN-652）之后，
`widgets/kill_icon_import_task.py` 里是**逐条同构**的另一份：
四个信号全挂在 self 上、三处 `except` 分支里各有一次裸 `emit`。
⭐⭐ 而这个类正是资源导入那一批**刚刚复用**的那个 —— 同一个缺陷，
两个调用方，一个修了一个没修。

实测复现（`H:/tmp/repro_kill_icon_emit.py`）：`shiboken6.delete(task)` 之后
worker 线程里逃出 `RuntimeError: Signal source has been deleted`，线程当场死掉，
而用户看到的是**进度框永远停在那儿**。

⭐⭐⭐ 要害不是"宿主没了"，是**错误处理路径本身依赖那个已经坏掉的东西**。

（本项目测试逐文件跑：
 `python -m pytest tests/test_the_kill_icon_task_survives_a_dead_host.py`）
"""
from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

from widgets.kill_icon_import_task import KillIconImportTask

REPO = Path(__file__).resolve().parent.parent
TASK = REPO / "widgets" / "kill_icon_import_task.py"


@pytest.mark.parametrize("blow_up", [False, True])
def test_no_exception_escapes_the_worker_when_the_host_is_gone(qapp, blow_up):
    """⛔ 宿主销毁之后，**一条异常都不许逃出 worker 线程**。

    两种走法都要测：
    - `blow_up=False`：正常跑完 ⇒ `finished` 那一次 emit；
    - `blow_up=True` ：业务抛错 ⇒ 走 `except` 分支里的 emit（**修之前逃的就是这条**）。
    """
    import shiboken6

    escaped = []
    original = threading.excepthook
    threading.excepthook = lambda args: escaped.append(
        f"{args.exc_type.__name__}: {args.exc_value}")

    started = threading.Event()
    release = threading.Event()

    def work(progress, should_cancel):
        started.set()
        release.wait(5)
        progress(1, 2, "干活中")
        if blow_up:
            raise RuntimeError("业务失败")
        return {"ok": True}

    task = KillIconImportTask()
    try:
        assert task.start(work, "测试")
        assert started.wait(5), "worker 没起来，判据的前提不成立"
        shiboken6.delete(task)          # 宿主的 C++ 部分当场销毁
        release.set()
        for _ in range(60):
            if not task_thread_alive(task):
                break
            time.sleep(0.05)
    finally:
        threading.excepthook = original

    assert not escaped, f"worker 线程里逃出了未捕获异常：{escaped}"


def task_thread_alive(task):
    """⚠ `task` 的 C++ 部分已经被删，属性访问要走 `__dict__` 绕开 Qt。"""
    thread = task.__dict__.get("_thread")
    return bool(thread and thread.is_alive())


def test_every_signal_in_the_worker_goes_through_the_safe_path():
    """⭐⭐ 棘轮：worker 线程碰得到的地方**不许出现裸 `self.<信号>.emit(...)`**。

    ⛔ 这条不列举信号名 —— 它拿 `Signal(...)` 的声明现算。
    以后这个类多一个信号、而 `_run` 里忘了走 `_safe_emit`，这条会红。
    ⭐ 同族缺陷之所以能留到今天，正是因为「另一处也有一份」这件事
    没有任何东西盯着（RN-002）。
    """
    tree = ast.parse(TASK.read_text(encoding="utf-8"))

    signals = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", "") == "Signal"):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    signals.add(target.id)
    assert len(signals) >= 3, f"只认出 {len(signals)} 个信号，抽取器多半瞎了"

    worker_names = {"_run", "_emit_progress"}
    bare = []
    for func in ast.walk(tree):
        if not (isinstance(func, ast.FunctionDef) and func.name in worker_names):
            continue
        for node in ast.walk(func):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "emit"):
                continue
            owner = node.func.value
            if (isinstance(owner, ast.Attribute)
                    and owner.attr in signals
                    and isinstance(owner.value, ast.Name)
                    and owner.value.id == "self"):
                bare.append(f"{func.name}:{node.lineno} self.{owner.attr}.emit")
    assert not bare, (
        "worker 线程里还有裸 emit：\n  " + "\n  ".join(bare)
        + "\n⇒ 一律改成 `self._safe_emit(\"<信号名>\", ...)`；"
        "⛔ 传字符串不传 `self.<信号>` —— 属性访问本身也要在保护区里才算数。")


def test_a_real_failure_is_still_reported_when_the_host_is_alive(qapp):
    """⛔ 反面守卫：**别把真失败一起吞了**。

    `_safe_emit` 只吞 `RuntimeError`（PySide6 报"对象已删"的确切类型），
    业务失败照常从 `failed` 信号出去。
    """
    seen = []
    task = KillIconImportTask()
    task.failed.connect(seen.append)

    done = threading.Event()

    def work(progress, should_cancel):
        raise RuntimeError("磁盘满了")

    task.failed.connect(lambda _m: done.set())
    assert task.start(work, "测试")
    for _ in range(60):
        qapp.processEvents()
        if done.is_set():
            break
        time.sleep(0.05)
    assert seen, "宿主还活着的时候，真失败必须报出来"
    assert "磁盘满了" in seen[0]
