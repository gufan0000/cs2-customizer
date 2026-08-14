# SPDX-License-Identifier: GPL-3.0-or-later
"""贴屏浏览器的窗口所有权判定回归测试。

背景：曾经有个回落逻辑，在找不到自己 PID 的窗口时返回任意一个
Chrome_WidgetWin_1 窗口，结果把裁标题栏/贴屏/隐藏/暂停全打到了用户
自己正在看视频的浏览器窗口上。本文件锁死"绝不操作不属于自己的窗口"。
"""
from __future__ import annotations

import os

import pytest

sticky = pytest.importorskip("core.fun.sticky_browser", reason="需要 Windows 与 pywin32")


@pytest.fixture
def browser(tmp_path):
    return sticky.StickyBrowser(str(tmp_path / "profile"), url="https://example.invalid/")


class _FakeProc:
    def __init__(self, pid=4242):
        self.pid = pid

    def poll(self):
        return None


def _patch_window(monkeypatch, *, owner_pid, is_window=True):
    monkeypatch.setattr(sticky.win32gui, "IsWindow", lambda _h: is_window)
    monkeypatch.setattr(
        sticky.win32process, "GetWindowThreadProcessId", lambda _h: (1234, owner_pid)
    )


def test_owns_hwnd_false_without_owned_pids(browser, monkeypatch):
    """还没启动就没有任何窗口属于自己——不能因为"句柄看起来有效"就放行。"""
    _patch_window(monkeypatch, owner_pid=999)
    assert browser._owns_hwnd(12345) is False


def test_owns_hwnd_rejects_foreign_window(browser, monkeypatch):
    """核心回归：别的进程的窗口一律拒绝。"""
    browser._owned_pids = {4242, 4243}
    _patch_window(monkeypatch, owner_pid=777)  # 用户自己的浏览器
    assert browser._owns_hwnd(12345) is False


def test_owns_hwnd_accepts_own_window(browser, monkeypatch):
    browser._owned_pids = {4242, 4243}
    _patch_window(monkeypatch, owner_pid=4243)
    assert browser._owns_hwnd(12345) is True


def test_owns_hwnd_rejects_dead_handle(browser, monkeypatch):
    browser._owned_pids = {4242}
    _patch_window(monkeypatch, owner_pid=4242, is_window=False)
    assert browser._owns_hwnd(12345) is False


def test_owns_hwnd_rejects_zero_handle(browser):
    browser._owned_pids = {4242}
    assert browser._owns_hwnd(0) is False


def test_window_mutations_are_noop_on_foreign_window(browser, monkeypatch):
    """认错窗口时，所有会改窗口状态的调用必须一个都不发出去。"""
    browser.proc = _FakeProc()
    browser.hwnd = 12345
    browser._owned_pids = {4242}
    _patch_window(monkeypatch, owner_pid=777)  # hwnd 其实是别人的

    calls: list[str] = []
    monkeypatch.setattr(sticky.win32gui, "SetWindowLong", lambda *a, **k: calls.append("SetWindowLong"))
    monkeypatch.setattr(sticky.win32gui, "SetWindowPos", lambda *a, **k: calls.append("SetWindowPos"))
    monkeypatch.setattr(sticky.win32gui, "ShowWindow", lambda *a, **k: calls.append("ShowWindow"))
    monkeypatch.setattr(browser, "_set_mute", lambda *a, **k: calls.append("_set_mute"))

    browser._apply_frameless()
    browser.show()
    browser.hide()
    browser.pause()
    browser.resume()

    assert calls == [], f"对不属于自己的窗口发出了操作: {calls}"
    assert browser.is_alive() is False


def test_hide_still_restores_focus_when_window_is_foreign(browser, monkeypatch):
    """即使窗口认错而放弃隐藏，也要把焦点还给游戏，不能把玩家卡在外面。"""
    browser.proc = _FakeProc()
    browser.hwnd = 12345
    browser._owned_pids = {4242}
    _patch_window(monkeypatch, owner_pid=777)

    restored: list[int] = []
    monkeypatch.setattr(sticky, "force_foreground", lambda h, *a, **k: restored.append(h) or True)

    browser.hide(restore_focus_to=999)
    assert restored == [999]


def test_close_clears_ownership(browser, monkeypatch):
    """收尾后所有权必须清空，否则句柄复用会让下一轮误判为自己的窗口。"""
    browser.proc = _FakeProc()
    browser.hwnd = 12345
    browser._owned_pids = {4242}
    monkeypatch.setattr(sticky.subprocess, "run", lambda *a, **k: None)
    browser.close()
    assert browser._owned_pids == set()
    assert browser.hwnd == 0
    _patch_window(monkeypatch, owner_pid=4242)
    assert browser._owns_hwnd(12345) is False


def test_process_tree_includes_self():
    pids = sticky.process_tree_pids(os.getpid())
    assert os.getpid() in pids


def test_process_tree_excludes_unrelated():
    """当前进程的进程树不该包含 PID 4（系统进程），否则树建错了。"""
    pids = sticky.process_tree_pids(os.getpid())
    assert 4 not in pids


def test_target_rect_is_portrait(browser, monkeypatch):
    monkeypatch.setattr(sticky, "_work_area", lambda _a=0: (0, 0, 2560, 1440))
    x, y, w, h = browser.target_rect()
    assert h > w, "贴屏窗口必须是竖的"
    assert abs(w / h - 9 / 16) < 0.02
    assert x + w <= 2560 and y + h <= 1440


def test_target_rect_left_side(tmp_path, monkeypatch):
    monkeypatch.setattr(sticky, "_work_area", lambda _a=0: (0, 0, 2560, 1440))
    left = sticky.StickyBrowser(str(tmp_path), url="x", side="left")
    right = sticky.StickyBrowser(str(tmp_path), url="x", side="right")
    assert left.target_rect()[0] < right.target_rect()[0]
