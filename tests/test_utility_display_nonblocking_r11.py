# -*- coding: utf-8 -*-
"""R11 / UP-006：`UtilityDisplay` 构造不得阻塞 GUI 线程。

原实现在 `_start_worker` 里 `Process.start()` 之后就地轮询 `status_queue`：

    timeout = 10.0
    while time.time() - start_time < timeout:
        if not self.status_queue.empty(): ...
        time.sleep(0.1)

而这个类是在 **GUI 线程**构造的（`main_widget._connect_utility_later`），
代码自己的注释写着实测约 0.9 秒、最坏 10 秒。用户点开「道具瞄点」页就冻在那。

判据分两条，缺一不可：

1. **结构判据**（AST）：`_start_worker` 里不许再出现 `time.sleep`。
   光有这条不够——把 sleep 换成忙等一样阻塞。
2. **行为判据**：塞一个**永远不报就绪**的假子进程，量构造耗时。
   回退到旧实现时这条会跑满 10 秒超时而变红，比结构判据硬。

⚠ 为什么行为判据要自己造假进程而不是真起一个：真进程起得快，
测不出"最坏情况"；而 UP-006 的伤害恰恰全在最坏情况上。
"""
from __future__ import annotations

import ast
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "utility_display.py"


def _func(name: str) -> ast.FunctionDef:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"utility_display.py 里找不到 {name}")


def _calls(node: ast.AST) -> list[str]:
    """节点里所有函数调用的**点号全名**。走 AST 不看文本——
    这个项目已经因为"用子串判断调用"栽过 4 次（见 README「判断调用永远走 AST」）。"""
    out = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        f = sub.func
        parts = []
        while isinstance(f, ast.Attribute):
            parts.append(f.attr)
            f = f.value
        if isinstance(f, ast.Name):
            parts.append(f.id)
        if parts:
            out.append(".".join(reversed(parts)))
    return out


# ------------------------------------------------------------------ 结构判据


def _call_lines(node: ast.AST, suffix: str) -> list[int]:
    """名字以 `suffix` 结尾的调用**节点**所在行号。

    ⚠ 这个函数存在的唯一原因：本判据的第一版拿源码文本 `src.index("sleep")`
    跟 `src.index("_schedule_ready_poll")` 比先后，结果被 `_start_worker`
    自己的 docstring 骗了——那段文档里引用了旧实现的 `time.sleep(0.1)`，
    位置在最前面，于是判据当场误报。
    **同一个教训在本项目是第 5 次**（前 4 次记在 README「判断调用永远走 AST」），
    而且已经是第二次栽在"我自己写的注释里出现了那几个字"上。
    """
    out = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        f = sub.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name.endswith(suffix):
            out.append(sub.lineno)
    return out


def test_start_worker_no_longer_sleeps_on_the_calling_thread():
    fn = _func("_start_worker")
    assert "self._schedule_ready_poll" in _calls(fn), (
        "_start_worker 不再调用 _schedule_ready_poll —— 分帧等待没了，"
        "又回到 GUI 线程上死等（UP-006）"
    )
    # 退回阻塞等待的兜底分支**允许**有 sleep（没有 Qt 事件循环时才走到），
    # 但它必须排在 `_schedule_ready_poll()` 之后——否则就是"先阻塞再说"。
    poll = min(_call_lines(fn, "_schedule_ready_poll"))
    sleeps = _call_lines(fn, "sleep")
    assert all(line > poll for line in sleeps), (
        f"_start_worker 里有 sleep 排在挂定时器（第 {poll} 行）之前：{sleeps}。"
        "那等于没改——GUI 线程照样先被堵住。"
    )


def test_ready_timer_is_kept_on_the_instance():
    """QTimer 必须留引用。

    只用局部变量的话，函数返回后 Python 侧对象被回收，定时器**静默失效**，
    工作进程永远接不上，而且一行报错都没有——比崩溃更难查。
    """
    fn = _func("_schedule_ready_poll")
    # ⚠ 第一版用 `ast.walk` 扫整个函数找 `self.<x> = ...`，回退验证判它假绿：
    # 嵌套在里面的 `_tick()` 有一句 `self._ready_timer = None`，于是把真正那句
    # `self._ready_timer = timer` 删掉之后，判据照样能找到这个属性名。
    # 改成①只看**本函数顶层**的语句（不进嵌套函数）②要求右值就是那个 QTimer 变量。
    timer_vars = {
        t.id
        for node in fn.body if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name) and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", "") == "QTimer"
    }
    assert timer_vars, "_schedule_ready_poll 里没有构造 QTimer"
    kept = [
        node for node in fn.body if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Name) and node.value.id in timer_vars
        and any(isinstance(t, ast.Attribute) and getattr(t.value, "id", "") == "self"
                and t.attr == "_ready_timer" for t in node.targets)
    ]
    assert kept, (
        "QTimer 没有被赋给 self._ready_timer。只用局部变量的话，函数返回后 "
        "Python 侧对象被回收，定时器**静默失效**——工作进程永远接不上，"
        "而且一行报错都没有，比崩溃更难查。"
    )


def test_cleanup_stops_the_ready_timer():
    fn = _func("cleanup")
    src = ast.get_source_segment(SRC.read_text(encoding="utf-8"), fn) or ""
    assert "_ready_timer" in src and ".stop()" in src, (
        "cleanup 没停就绪定时器——退出链路上它会继续 tick 一个已清理的对象"
    )


# ------------------------------------------------------------------ 行为判据


@pytest.mark.timeout(60) if hasattr(pytest.mark, "timeout") else (lambda f: f)
def test_construction_does_not_block_even_when_the_worker_never_reports_ready():
    """最坏情况：子进程永远不报就绪。构造必须立刻返回。

    旧实现在这里会整整等满 `_READY_TIMEOUT`（10 秒）。
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    import utility_display as ud

    calls = {"start": 0}

    class _NeverReadyProcess:
        """假子进程：起得来、活着，但**永远不往 status_queue 里放东西**。"""

        daemon = True

        def __init__(self, *a, **kw):
            pass

        def start(self):
            calls["start"] += 1

        def is_alive(self):
            return True

        def join(self, timeout=None):
            return None

        def terminate(self):
            return None

    class _SilentQueue:
        def empty(self):
            return True

        def get_nowait(self):
            raise ud._queue.Empty

        def get(self, *a, **kw):
            raise ud._queue.Empty

        def put(self, *a, **kw):
            return None

    real_process, real_queue = ud.Process, ud.Queue
    ud.Process, ud.Queue = _NeverReadyProcess, _SilentQueue
    try:
        t0 = time.perf_counter()
        disp = ud.UtilityDisplay()
        elapsed = time.perf_counter() - t0
    finally:
        ud.Process, ud.Queue = real_process, real_queue

    try:
        assert calls["start"] == 1, "工作进程没被启动"
        # 旧实现这里是 10 秒。给 1 秒的宽限（含 import / pygame 初始化的噪声）。
        assert elapsed < 1.0, (
            f"UtilityDisplay 构造阻塞了 {elapsed:.2f}s —— UP-006 回来了。"
            "GUI 线程上这段等待用户是直接看得见的（页面冻住）。"
        )
        assert disp.worker_ready is False, "假进程从没报过就绪，不该被判为 ready"
        app.processEvents()
    finally:
        disp.cleanup()
