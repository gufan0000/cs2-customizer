# -*- coding: utf-8 -*-
"""内存采样器回归测试（UP-003）。

锁住三件事:
1. psapi 读数真的能拿到非零值——64 位下若忘了声明 argtypes/restype,HANDLE 会被
   截断成 32 位,调用静默返回 0,埋点看着"在跑"其实一直是空数据。
2. 日志格式与 scripts/ui_perf_probe.py 的解析口径一致(rss=/priv=/启动后 Xs)。
3. 环境不支持时自动停表,绝不刷无用日志、绝不影响软件功能。
"""
from __future__ import annotations

import re
import time

import pytest

import core.utils.mem_monitor as mem_mod

# 与 scripts/ui_perf_probe.py 的 RE_MEM 必须保持一致
_PROBE_RE = re.compile(r"\[内存\]\s*rss=(\d+)MB\s+priv=(\d+)MB\s*\(启动后\s*([\d.]+)s\)")


@pytest.fixture(autouse=True)
def _reset_singleton():
    mem_mod._instance = None
    yield
    inst = mem_mod._instance
    if inst is not None:
        try:
            inst._timer.stop()
        except Exception:
            pass
    mem_mod._instance = None


def test_reads_nonzero_memory():
    """本进程必然占着内存;读到 0 就说明 ctypes 调用姿势错了。"""
    rss, priv = mem_mod._read_memory_bytes()
    assert rss > 0, "工作集读数为 0——检查 GetCurrentProcess 的 restype 声明"
    assert priv > 0, "私有提交读数为 0"
    # 一个 Python 进程怎么也得有几 MB,又不至于上百 GB
    assert 1 * 1024**2 < rss < 100 * 1024**3


def test_log_line_matches_probe_regex(caplog):
    """采样日志必须能被基线探针解析,否则埋了等于没埋。"""
    caplog.set_level("INFO", logger="CS2Customizer.Mem")
    mem_mod.start_mem_monitor(t0=time.perf_counter() - 12.5)

    lines = [r.getMessage() for r in caplog.records if "[内存]" in r.getMessage()]
    assert lines, "构造时应当立即采一次样"

    m = _PROBE_RE.search(lines[0])
    assert m, f"日志格式与探针正则不匹配: {lines[0]}"
    assert int(m.group(1)) > 0
    # t0 生效:启动后秒数应当接近传入的 12.5，而不是 0
    assert float(m.group(3)) >= 12.0


def test_start_is_idempotent():
    first = mem_mod.start_mem_monitor()
    second = mem_mod.start_mem_monitor()
    assert first is second


def test_single_failure_does_not_stop(monkeypatch, caplog):
    """瞬时失败不许永久失明——第一次 _tick 恰在启动最繁忙的时刻。"""
    monkeypatch.setattr(mem_mod, "_read_memory_bytes", lambda: (0, 0))
    caplog.set_level("INFO", logger="CS2Customizer.Mem")

    monitor = mem_mod.start_mem_monitor()

    assert monitor._timer.isActive(), "单次失败不应停表"
    assert monitor._fail_streak == 1
    assert not [r for r in caplog.records if "[内存] rss=" in r.getMessage()]


def test_stops_after_consecutive_failures(caplog):
    """连续失败到阈值才停表，且必须留下 warning——否则排查时无法区分是老版本还是探针挂了。"""
    import core.utils.mem_monitor as m

    caplog.set_level("WARNING", logger="CS2Customizer.Mem")
    monitor = m.start_mem_monitor()
    monitor._fail_streak = 0

    orig = m._read_memory_bytes
    m._read_memory_bytes = lambda: (0, 0)
    try:
        for _ in range(m._MAX_CONSECUTIVE_FAILURES):
            monitor._tick()
    finally:
        m._read_memory_bytes = orig

    assert not monitor._timer.isActive(), "连续失败达阈值后应停表"
    warns = [r.getMessage() for r in caplog.records if "停止采样" in r.getMessage()]
    assert warns, "停表必须留下 warning 痕迹"


def test_failure_streak_resets_on_success(monkeypatch):
    """中间成功一次就要清零，避免零星失败累积到误停表。"""
    monitor = mem_mod.start_mem_monitor()
    monitor._fail_streak = 2
    monitor._tick()  # 真实读数应当成功
    assert monitor._fail_streak == 0


def test_k32_fallback_is_reachable(monkeypatch):
    """psapi 加载失败时必须能回退到 kernel32，而不是整个函数抛出去。

    原写法把 ctypes.windll.psapi 放在 for 的元组字面量里，会在进入循环体前求值，
    异常直接冲出循环 —— 回退分支恰恰在唯一需要它的场景下失效。
    """
    import ctypes

    real_windll = ctypes.windll

    class _FakeWindll:
        def __getattr__(self, name):
            if name == "psapi":
                raise OSError("模拟 psapi.dll 加载失败")
            return getattr(real_windll, name)

    monkeypatch.setattr(ctypes, "windll", _FakeWindll())
    rss, priv = mem_mod._read_memory_bytes()
    assert rss > 0 and priv > 0, "psapi 不可用时应当回退到 kernel32 的 K32 导出"
