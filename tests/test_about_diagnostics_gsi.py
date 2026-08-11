# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""QA-011：「关于」页诊断信息里的 GSI 状态必须是真的。

原实现 `from gsi_server import get_gsi_server` —— 那个名字在 `gsi_server.py` 里
**根本不存在**（AST 列全模块级绑定：get_active_port / run_flask / GSIServer …，
没有 get_gsi_server）。于是这一行 100% 抛 ImportError、被裸 except 吞成
「GSI: 未知」。用户复制诊断信息发给客服时，最该看的那一行永远没内容。

判据全是行为断言：**同一段代码必须能产出两个不同结果**（跑着=运行中、停了=未运行）。
只断言「不等于未知」是假绿 —— 把 import 修对、继续用不存在的 `is_running`，
会让实际在跑的服务恒报「未运行」，比「未知」更能把排障带偏。
"""
from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtWidgets import QVBoxLayout, QWidget

import gsi_server
from pages.about_page import AboutPage


def _diag_gsi_line(page) -> str:
    text = page._collect_diagnostics()
    for line in text.splitlines():
        if line.startswith("GSI:"):
            return line
    return ""


@pytest.fixture
def running_server():
    """用**真实**的 GSIServer 与它自己的循环把 _running 顶起来。

    刻意不手写 `srv._running = True` —— 那样判据会跟着实现的属性名一起假绿。
    process_data() 自己会置位并空转（不起 Flask、不占端口）。
    """
    srv = gsi_server.GSIServer()
    th = threading.Thread(target=srv.process_data, daemon=True, name="test-gsi-loop")
    th.start()
    deadline = time.time() + 3.0
    while time.time() < deadline and not srv._running:
        time.sleep(0.01)
    assert srv._running, "真实 GSIServer 没能进入运行态，判据前提不成立"
    yield srv
    srv.stop()
    th.join(timeout=3.0)


def _page_with_server(qtbot_parent_holder, srv):
    """造一个扮演主窗口的父 QWidget，把 AboutPage 放进去。"""
    host = QWidget()
    host.gsi_server = srv
    layout = QVBoxLayout(host)
    page = AboutPage()
    layout.addWidget(page)
    qtbot_parent_holder.append(host)   # 防止被 GC
    return page


def test_diagnostics_reports_running_and_the_active_port(running_server, monkeypatch):
    """服务在跑时：必须是「运行中」，端口必须是实际漂移到的那个。"""
    monkeypatch.setattr(gsi_server, "_active_port", 3007, raising=False)
    holder: list = []
    page = _page_with_server(holder, running_server)

    line = _diag_gsi_line(page)
    assert line, "诊断信息里根本没有 GSI 这一行"
    assert "运行中" in line, f"服务在跑却没报运行中：{line}"
    assert "3007" in line, f"端口没跟上实际漂移：{line}"
    assert "未知" not in line, f"又退化成「GSI: 未知」了：{line}"


def test_diagnostics_flips_to_stopped_after_stop(running_server, monkeypatch):
    """停掉之后必须翻成「未运行」。

    这条是防「写死一个字符串骗判据」的关键：同一段代码要能产出两个不同结果。
    """
    monkeypatch.setattr(gsi_server, "_active_port", 3007, raising=False)
    holder: list = []
    page = _page_with_server(holder, running_server)
    assert "运行中" in _diag_gsi_line(page)

    running_server.stop()
    deadline = time.time() + 3.0
    while time.time() < deadline and running_server._running:
        time.sleep(0.01)

    line = _diag_gsi_line(page)
    assert "未运行" in line, f"停了却还报运行中：{line}"
    assert "未知" not in line


def test_diagnostics_without_main_window_says_uninitialized_not_running():
    """审计脚本 / 测试会单独构造页面，`self.window()` 拿到的是页面自己。

    这种情况必须走「未初始化」，既不能抛异常，也**不能谎报运行中**。
    """
    page = AboutPage()
    line = _diag_gsi_line(page)
    assert line, "诊断信息里根本没有 GSI 这一行"
    assert "运行中" not in line, f"没有主窗口却谎报运行中：{line}"
    assert "未初始化" in line or "未知" in line
