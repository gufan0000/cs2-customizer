# -*- coding: utf-8 -*-
"""卡顿探测器回归测试（UP-002）。

锁住两件事:
1. start_jank_monitor 接受 t0,"启动后 Xs"以进程真实起点计时——否则日志时间轴
   会整体错位(实测约 5.3 秒),没法和 [启动相位] 对齐,性能验收数字就是错的。
2. 探测器确实能抓到主线程停顿,且阈值以下不误报。
"""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QCoreApplication

import core.utils.jank_monitor as jank_mod


@pytest.fixture(autouse=True)
def _reset_singleton():
    """探测器是模块级单例,逐用例重置,避免相互污染。"""
    jank_mod._instance = None
    yield
    inst = jank_mod._instance
    if inst is not None:
        try:
            inst._timer.stop()
        except Exception:
            pass
    jank_mod._instance = None


def _drain(ms: int):
    """跑事件循环 ms 毫秒,让 QTimer 有机会触发。"""
    deadline = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)


def test_t0_is_honoured():
    """传入的 t0 必须被当作计时起点,而不是构造时刻。"""
    fake_t0 = time.perf_counter() - 30.0  # 假装进程 30 秒前就启动了
    monitor = jank_mod.start_jank_monitor(t0=fake_t0)
    assert monitor._t0 == pytest.approx(fake_t0)


def test_t0_defaults_to_now_when_omitted():
    """不传 t0 时退化为构造时刻，保持 2.2.1 的行为。"""
    before = time.perf_counter()
    monitor = jank_mod.start_jank_monitor()
    after = time.perf_counter()
    assert before <= monitor._t0 <= after


def test_start_is_idempotent():
    """重复调用只建一个探测器(常驻单例)。"""
    first = jank_mod.start_jank_monitor()
    second = jank_mod.start_jank_monitor()
    assert first is second


def test_detects_main_thread_stall(caplog):
    """主线程被同步任务卡住时必须记一行,且停顿时长可信。"""
    # 变量本身不再使用，但必须持有引用——监视器被回收后就不再打点
    _monitor = jank_mod.start_jank_monitor(t0=time.perf_counter())
    _drain(120)  # 先让心跳正常跑几拍

    caplog.set_level("INFO", logger="FanPai.Jank")
    caplog.clear()

    # 阻塞主线程 400ms —— 远超 120ms 阈值
    time.sleep(0.4)
    _drain(150)

    stalls = [r.getMessage() for r in caplog.records if "[卡顿]" in r.getMessage()]
    assert stalls, "阻塞 400ms 后应当至少记录一次卡顿"
    assert "主线程停顿" in stalls[0]
    assert "启动后" in stalls[0]


def test_no_false_positive_when_idle(caplog):
    """空闲时不许刷日志(阈值以下不报)。"""
    jank_mod.start_jank_monitor(t0=time.perf_counter())
    caplog.set_level("INFO", logger="FanPai.Jank")
    caplog.clear()

    _drain(300)  # 只跑事件循环,不阻塞

    stalls = [r for r in caplog.records if "[卡顿]" in r.getMessage()]
    assert not stalls, f"空闲期不应报卡顿,实际报了 {len(stalls)} 次"
