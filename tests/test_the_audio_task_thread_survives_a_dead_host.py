# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-652：宿主被销毁之后，音频任务线程不许抛出未捕获异常。

现场（2026-09-16 资源导入沙箱端到端顺带逮到，`audio_task_runner.py` 本轮未改动，
是既有缺陷）：页面/宿主在 `_run_import_refresh` 跑着时消失 ⇒ `task.fn` 里的 emit
抛 `RuntimeError: Signal source has been deleted`。

⭐ 要害不是"宿主没了"，是**错误处理路径本身依赖那个已经坏掉的东西**。修复前实测的
三级连抛（见 H:/tmp/rn_repro_audio_runner_emit.py）：

  1. `task.fn` 里的 emit 抛      ⇒ 进 except
  2. except 里的 emit **再抛**   ⇒ 同一块里的 `logger.error` 根本没跑到（失败不留日志）
  3. finally 里的 emit **三抛**  ⇒ 新异常**替换掉** 2 那条传播出去，`_push_history` 也丢了

⇒ worker 线程静默死亡；解释器收尾期还会撞上 stderr 缓冲锁
（`Fatal Python error: _enter_buffered_busy`，实测 rc=0xC0000409）。

⚠ 逃出线程的是 **finally 的 `task_finished`**，不是 except 的 `task_progress` ——
所以只补 except 那一处修不掉这条缺陷。下面第 1 条判据钉的就是"一条都不许逃"。
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

from core.audio.audio_task_runner import AudioTaskRunner

_RUNNER_SRC = Path(__file__).resolve().parents[1] / "core" / "audio" / "audio_task_runner.py"


class _Uncaught:
    """接管 threading.excepthook，收集 worker 线程里逃出来的异常。"""

    def __init__(self):
        self.seen: list[tuple[str, str, str]] = []
        self._prev = None

    def __enter__(self):
        self._prev = threading.excepthook

        def hook(args):
            self.seen.append(
                (
                    getattr(args.thread, "name", "?"),
                    args.exc_type.__name__,
                    str(args.exc_value),
                )
            )

        threading.excepthook = hook
        return self

    def __exit__(self, *_exc):
        threading.excepthook = self._prev
        return False

    def describe(self) -> str:
        return "；".join(f"[{t}] {k}: {v}" for t, k, v in self.seen) or "（无）"


def _kill_hard(runner):
    import shiboken6

    shiboken6.delete(runner)


def _kill_deferred(runner):
    from PySide6.QtCore import QCoreApplication, QEvent

    runner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def _run_with_host_killed(kill, fn_tail=None):
    """起一个任务，卡在中途把宿主销毁，再放行它发信号。返回 (runner, worker, tail)。"""
    runner = AudioTaskRunner()
    started = threading.Event()
    may_go = threading.Event()
    tail: dict[str, object] = {}

    def slow_fn(task):
        started.set()
        assert may_go.wait(10.0), "主线程没来得及销毁宿主"
        # 等价于 _run_import_refresh 的第一句进度播报
        runner._safe_emit("task_progress", task.task_id, 25, "刷新导入后的样式索引")
        tail["reached_after_emit"] = True
        if fn_tail is not None:
            fn_tail(task)
        task.message = "任务完成"

    runner._submit_task("unit_test_dead_host", "dead_host", slow_fn)
    assert started.wait(10.0), "worker 线程没起来"
    worker = runner._worker_thread
    assert worker is not None

    kill(runner)
    may_go.set()
    worker.join(15.0)
    return runner, worker, tail


@pytest.mark.parametrize(
    "kill,label",
    [(_kill_hard, "shiboken6.delete"), (_kill_deferred, "deleteLater + DeferredDelete")],
)
def test_a_dead_host_leaves_no_uncaught_exception_in_the_worker_thread(qapp, kill, label):
    """核心判据：宿主怎么没的都行，worker 线程不许留下未捕获异常、不许死。"""
    with _Uncaught() as caught:
        runner, worker, _tail = _run_with_host_killed(kill)
        # excepthook 在线程收尾时调用，join 返回后再给一点点余量
        time.sleep(0.2)

    assert not worker.is_alive(), f"worker 线程 join 超时没结束（{label}）"
    assert not caught.seen, (
        f"宿主被销毁（{label}）之后 worker 线程抛出了未捕获异常：{caught.describe()}\n"
        "修复前这里逃出来的是 finally 里的 task_finished.emit —— "
        "只补 except 那一处是修不掉的。"
    )
    runner.stop()


@pytest.mark.parametrize(
    "kill,label",
    [(_kill_hard, "shiboken6.delete"), (_kill_deferred, "deleteLater + DeferredDelete")],
)
def test_the_task_still_finishes_and_reaches_history_after_the_host_dies(qapp, kill, label):
    """这条把"靠 _worker_loop 兜底接住"和"真的安全发射"分开。

    光有 `_worker_loop` 的兜底 except，上面那条判据也会绿——但 `task.fn` 会在半路
    炸掉、`_push_history` 永远跑不到。⇒ 这里同时要求：emit 之后的业务代码跑到了，
    且任务落进了历史。⭐ 一条判据绿着可能只是因为兜底接住了，不是因为修好了。
    """
    with _Uncaught():
        runner, _worker, tail = _run_with_host_killed(kill)

    assert tail.get("reached_after_emit") is True, (
        f"宿主销毁（{label}）后，task.fn 在进度播报那一句就炸了 —— "
        "业务（含 save_config）会被掐在半路"
    )
    history = runner.get_history(limit=10)
    assert history, f"宿主销毁（{label}）后 _push_history 没跑到，任务连失败记录都没留下"
    assert history[-1]["success"] is True, f"业务本身没失败，不该记成失败：{history[-1]}"
    runner.stop()


def test_a_real_task_failure_is_still_reported_as_a_failure(qapp):
    """⚠ 反向判据：别把 task.fn 的真失败一起吞了。宿主活着，业务照常算失败。"""
    runner = AudioTaskRunner()
    boom = RuntimeError("业务自己炸了")  # 故意也用 RuntimeError，逼安全发射别按类型乱吞

    def failing_fn(task):
        raise boom

    with _Uncaught() as caught:
        runner._submit_task("unit_test_real_failure", "real_failure", failing_fn)
        deadline = time.time() + 10.0
        while time.time() < deadline and not runner.get_history(limit=5):
            time.sleep(0.05)

    history = runner.get_history(limit=5)
    assert history, "任务没落进历史"
    assert history[-1]["success"] is False, f"真失败被吞成了成功：{history[-1]}"
    assert "业务自己炸了" in str(history[-1]["message"]), f"失败原因丢了：{history[-1]}"
    assert not caught.seen, f"真失败不该逃成线程未捕获异常：{caught.describe()}"
    runner.stop()


def test_a_real_failure_still_reaches_history_even_if_the_host_is_dead(qapp):
    """两件坏事叠在一起：业务失败 + 宿主已死 ⇒ 仍要记成失败、仍不许抛。

    这正是修复前三级连抛的那条路径（except 的 emit 抛 ⇒ logger.error 被跳过 ⇒
    finally 的 emit 再抛并逃出去）。
    """

    def boom(_task):
        raise ValueError("导入刷新失败")

    with _Uncaught() as caught:
        runner, worker, _tail = _run_with_host_killed(_kill_hard, fn_tail=boom)
        time.sleep(0.2)

    assert not caught.seen, f"宿主已死 + 业务失败，线程抛了未捕获异常：{caught.describe()}"
    assert not worker.is_alive()
    history = runner.get_history(limit=5)
    assert history, "宿主已死时业务失败，连历史都没留下"
    assert history[-1]["success"] is False, f"业务失败没被记成失败：{history[-1]}"
    assert "导入刷新失败" in str(history[-1]["message"]), f"失败原因丢了：{history[-1]}"
    runner.stop()


def test_a_broken_execute_task_does_not_take_the_whole_worker_down(qapp):
    """兜底第二层：`_execute_task` 自身炸了（不是 task.fn），worker 也不许被带走。

    ⚠ 这条是破坏验证逼出来的：把 `_safe_emit` 的保护拿掉、只留 `_worker_loop` 的
    兜底，上面那条"无未捕获异常"就绿了 —— 说明兜底那几行当时**没有任何判据守着**。
    ⭐ 一条判据绿着，可能只是因为另一层碰巧接住了。

    做法：让两个任务进同一个 worker 的队列，第一个在 `_execute_task` 里炸。
    没有兜底 ⇒ 线程当场死掉，第二个任务永远没人取（要等下一次 submit）。
    """
    runner = AudioTaskRunner()
    seen: list[str] = []
    gate = threading.Event()
    second_done = threading.Event()

    def exploding_execute(task):
        seen.append(task.task_id)
        if len(seen) == 1:
            # 卡住，好让第二个任务进**同一个** worker 的队列
            gate.wait(10.0)
            raise RuntimeError("_execute_task 自己炸了")
        second_done.set()

    runner._execute_task = exploding_execute  # type: ignore[method-assign]

    with _Uncaught() as caught:
        runner._submit_task("unit_test_worker_guard", "first", lambda _t: None)
        deadline = time.time() + 10.0
        while time.time() < deadline and not seen:
            time.sleep(0.02)
        assert seen, "第一个任务没被取走"
        # worker 此刻活着 ⇒ _ensure_worker 不会新建，第二个任务落进同一条队列
        runner._submit_task("unit_test_worker_guard", "second", lambda _t: None)
        gate.set()
        ok = second_done.wait(10.0)
        time.sleep(0.2)

    assert ok, (
        "第一个任务在 _execute_task 里炸掉之后，第二个任务再没人处理 —— "
        "worker 线程被单个任务带走了（_worker_loop 少了兜底 try/except）"
    )
    assert not caught.seen, f"worker 兜底没接住，异常逃出了线程：{caught.describe()}"
    runner.stop()


def test_the_signal_names_passed_to_safe_emit_all_exist(qapp):
    """`_safe_emit` 收的是字符串名（属性访问必须留在保护区内），拼错了没人会发现。

    ⇒ AST 取出源码里传给 `_safe_emit` 的每一个字面量名字，逐个核对确有其信号。
    """
    tree = ast.parse(_RUNNER_SRC.read_text(encoding="utf-8"))
    used: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "_safe_emit" and node.args:
            first = node.args[0]
            assert isinstance(first, ast.Constant) and isinstance(first.value, str), (
                f"_safe_emit 第一个参数必须是字面量信号名（第 {node.lineno} 行），"
                "否则这条判据核不动它"
            )
            used.add(first.value)

    assert used, "源码里一个 _safe_emit 调用都没有 —— 修复被回退了？"
    runner = AudioTaskRunner()
    for name in sorted(used):
        sig = getattr(runner, name, None)
        assert sig is not None and hasattr(sig, "emit"), f"_safe_emit 用了不存在的信号名：{name!r}"
    runner.stop()


def test_no_bare_signal_emit_is_left_in_the_runner():
    """⛔ 结构判据：模块里不许再出现 `self.<signal>.emit(...)` 这种裸发射。

    按 §1 红线 2 走 AST，不用 grep —— 这条问的正是"有没有 X"。
    """
    src = _RUNNER_SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)

    signal_names = {
        target.id
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef) and cls.name == "AudioTaskRunner"
        for stmt in cls.body
        if isinstance(stmt, ast.Assign)
        for target in stmt.targets
        if isinstance(target, ast.Name)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id == "Signal"
    }
    assert signal_names == {"task_started", "task_progress", "task_finished"}, (
        f"信号集合变了（{sorted(signal_names)}）——先确认新信号也走了 _safe_emit，再改这条判据"
    )

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "emit"):
            continue
        owner = fn.value
        if (
            isinstance(owner, ast.Attribute)
            and owner.attr in signal_names
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "self"
        ):
            offenders.append(f"第 {node.lineno} 行: self.{owner.attr}.emit(...)")

    assert not offenders, (
        "这些 emit 没走 _safe_emit，宿主一死就会抛 RuntimeError 并杀掉 worker 线程：\n  "
        + "\n  ".join(offenders)
    )
