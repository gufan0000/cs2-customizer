# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""预载调度与 ensure_page_loaded 语义回归测试（R2 复核发现的真回归）。

R2 让 ensure_page_loaded 可以返回 False（"用户正在切页，后台让路"）。
复核实证：当时有三条老调用链把返回值当成功、且已经把页从队列里 pop 掉了，
后果分别是：
1. flash/magnifier/utility 建不成 → _connect_gsi_now 的 is_page_loaded 守卫
   直接跳过 handler 连接 → 自定闪光/开镜放大/道具瞄点整个会话静默失效；
2. 空闲预构建链把页永久丢弃，日志还谎报「就绪」。

另外 UP-014 一度把 viewmodel/voice_output 从预载里删掉，而这两页的构造正是
音板全局热键与视角自动切换线程的唯一启动点——删了等于悄悄关掉两个功能。
"""
from __future__ import annotations



# ==================== ensure_page_loaded 的三态语义 ====================

class _FakeWindow:
    """只实现 ensure_page_loaded 依赖的那几个属性。"""

    def __init__(self, loaded=None, page_loading=False, closing=False):
        self._loaded_pages = set(loaded or [])
        self._page_loading = page_loading
        self._is_closing = closing
        self.built = []

    def _load_page(self, page_id):
        self.built.append(page_id)
        self._loaded_pages.add(page_id)

    # 直接复用真实实现，保证测的是产品代码而不是副本
    def ensure_page_loaded(self, page_id):
        from gui_widget import MainWindow
        return MainWindow.ensure_page_loaded(self, page_id)


def test_returns_true_when_already_loaded():
    w = _FakeWindow(loaded={"crosshair"})
    assert w.ensure_page_loaded("crosshair") is True
    assert w.built == []


def test_builds_and_returns_true():
    w = _FakeWindow()
    assert w.ensure_page_loaded("crosshair") is True
    assert w.built == ["crosshair"]


def test_yields_with_false_while_user_switching():
    """用户正在切页时必须让路，且绝不能建页。"""
    w = _FakeWindow(page_loading=True)
    assert w.ensure_page_loaded("crosshair") is False
    assert w.built == [], "让路时不该构建任何页面"


def test_returns_false_when_closing():
    w = _FakeWindow(closing=True)
    assert w.ensure_page_loaded("crosshair") is False
    assert w.built == []


# ==================== 调用方必须正确处理 False ====================

def _simulate_queue_consumer(window, queue, *, pop_before_check: bool):
    """模拟两种消费模式，验证「先 pop 再忽略返回值」会丢页。"""
    if pop_before_check:
        pid = queue.pop(0)
        window.ensure_page_loaded(pid)          # 旧写法：忽略返回值
        return
    pid = queue[0]
    if window.ensure_page_loaded(pid) is False:  # 新写法：让路重试
        return
    queue.pop(0)


def test_old_pattern_loses_pages():
    """固化"旧写法会丢页"这个事实，防止有人改回去。"""
    w = _FakeWindow(page_loading=True)
    queue = ["flash", "magnifier", "utility"]
    _simulate_queue_consumer(w, queue, pop_before_check=True)
    assert queue == ["magnifier", "utility"]
    assert "flash" not in w._loaded_pages, "flash 被 pop 掉却没建成——功能会静默失效"


def test_new_pattern_keeps_page_in_queue():
    w = _FakeWindow(page_loading=True)
    queue = ["flash", "magnifier", "utility"]
    _simulate_queue_consumer(w, queue, pop_before_check=False)
    assert queue == ["flash", "magnifier", "utility"], "让路时队列不该被消费"

    # 用户切页结束后重试应当成功
    w._page_loading = False
    _simulate_queue_consumer(w, queue, pop_before_check=False)
    assert queue == ["magnifier", "utility"]
    assert "flash" in w._loaded_pages


# ==================== 功能激活页不许被漏掉 ====================

def test_feature_activation_pages_still_get_built():
    """viewmodel / voice_output 必须仍在启动流程里被构建。

    它们的构造函数是「音板全局热键注册」与「视角自动切换线程」的唯一启动点，
    只从预载池删掉、不另行安排构建，等于把两个已开启的付费功能悄悄关掉。
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "main_widget.py"
    text = src.read_text(encoding="utf-8")

    m = re.search(r"FEATURE_ACTIVATION_PAGES\s*=\s*\[([^\]]*)\]", text)
    assert m, "启动流程里应当有一条明确的功能激活队列"
    body = m.group(1)
    assert "viewmodel" in body
    assert "voice_output" in body

    # 且必须真的被调度（有调用点），不能只定义不用
    assert "load_feature_pages" in text
    assert text.count("load_feature_pages") >= 2, "功能激活队列必须被实际调度"


def test_skip_pages_not_in_silent_preload_pool():
    """静默预载池不许包含"构造即起线程/设备"的页。"""
    import re
    from pathlib import Path

    from core.page_traits import DEVICE_OWNING_PAGES

    src = Path(__file__).resolve().parent.parent / "main_widget.py"
    text = src.read_text(encoding="utf-8")
    m = re.search(r"PRELOAD_POOL\s*=\s*\[(.*?)\]", text, re.S)
    assert m, "应当有 PRELOAD_POOL"
    pool = m.group(1)
    # 名单取产品那一份，别在判据里另抄：抄的那份不会跟着产品变，
    # 于是产品新增一个设备页时，这条判据会以"已覆盖"的名义放它进预载池。
    for unsafe in sorted(DEVICE_OWNING_PAGES):
        assert f"'{unsafe}'" not in pool, f"{unsafe} 不该进静默预载池"
