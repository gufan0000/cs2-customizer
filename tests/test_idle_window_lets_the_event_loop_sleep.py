# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-732：窗口什么都不做时，事件循环必须能休眠。

侧栏校正会改视口底边距，每改一次视口就发一次 Resize，而 Resize 又会触发下一轮校正。
默认窗口（高 800~950）下这个循环永不停止：实测空闲单核 98~105%，28 页里 22 页中招。
`_ensuring_nav_visible` 拦不住：第二轮校正在 `singleShot(0)` 里，早出了它的作用域。
143 批和 4000 多条判据都没看见，因为没有任何东西量「空闲」。

这里不量 CPU（墙钟类读数在满载机器上会飘，见 RN-518），量两个确定的数：
安静窗口里侧栏视口收到几次 Resize、事件循环休眠了几次。
"""
from __future__ import annotations

import pytest

#: 窗口高度的来历：800 是 `ui_shot_capture.py` 的完整档；
#: 877 / 938 是默认窗口公式在 1080p、这台开发机（2048×1152）上算出来的值；
#: 1000 是公式的上限（1440p 及以上），本来就不中招，留作对照。
DEFAULT_WINDOW_HEIGHTS = (800, 877, 938, 1000)

SETTLE_MS = 150
QUIET_MS = 200


def _spin(ms):
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.fixture()
def rig(qapp, monkeypatch):
    monkeypatch.setenv("CS2C_NO_GLOBAL_HOTKEYS", "1")
    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")
    from PySide6.QtCore import QAbstractEventDispatcher, QEvent, QObject, Qt

    import _audit_neutralize as neutral
    import _ui_mode
    from config import config

    neutral.apply(config)
    # 批 145：普通模式 23 项一屏放得下，根本走不到校正，把修法拆掉也绿（回退验证当场逮到）。
    # 还要滚的是专家模式 28 项和开着「常用」分组的用户。
    _ui_mode.apply(config, True)
    config.compact_mode = False

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    qapp.processEvents()

    class _ResizeCounter(QObject):
        count = 0

        def eventFilter(self, watched, event):
            if event.type() == QEvent.Resize:
                self.count += 1
            return False

    counter = _ResizeCounter()
    win._sidebar_scroll.viewport().installEventFilter(counter)
    sleeps = {"n": 0}

    def _on_block():
        sleeps["n"] += 1

    dispatcher = QAbstractEventDispatcher.instance()
    dispatcher.aboutToBlock.connect(_on_block)

    def measure():
        _spin(SETTLE_MS)
        counter.count = 0
        sleeps["n"] = 0
        _spin(QUIET_MS)
        return counter.count, sleeps["n"]

    def resize(width, height):
        win.setMinimumSize(0, 0)
        win.resize(width, height)
        qapp.processEvents()

    try:
        yield win, measure, resize
    finally:
        dispatcher.aboutToBlock.disconnect(_on_block)
        win._sidebar_scroll.viewport().removeEventFilter(counter)
        win.close()
        win.deleteLater()


def _verdict(tag, resizes, sleeps):
    if resizes or not sleeps:
        return f"{tag}: 安静 {QUIET_MS}ms 内侧栏视口 Resize {resizes} 次、事件循环休眠 {sleeps} 次"
    return ""


def test_every_page_sleeps_at_the_capture_size(rig):
    """1280×800 逐页量：28 页改前 22 页中招，所以不能只量几页。"""
    import _ui_mode

    win, measure, resize = rig
    resize(1280, 800)
    pages = list(win._page_names.keys())
    from test_one_primary_button_per_screen import EXPECTED_PAGE_IDS

    from pathlib import Path

    # 独立于导航注册表；功能子集没有账号页，但不能漏测仍在检出里的页。
    root = Path(__file__).resolve().parents[1]
    expected = {pid for pid, filename in EXPECTED_PAGE_IDS.items()
                if not filename or (root / "pages" / filename).is_file()}
    assert set(pages) == expected, f"页面集合不对：{set(pages) ^ expected}"
    spinning = []
    for page_id in pages:
        _ui_mode.goto(win, page_id)
        problem = _verdict(page_id, *measure())
        if problem:
            spinning.append(problem)
    assert not spinning, f"{len(spinning)}/{len(pages)} 页空闲时事件循环不休眠：{spinning[:5]}"


@pytest.mark.parametrize("height", DEFAULT_WINDOW_HEIGHTS)
def test_default_window_heights_sleep(rig, height):
    import _ui_mode

    win, measure, resize = rig
    resize(1280, height)
    spinning = []
    for page_id in ("basic", "crosshair"):
        _ui_mode.goto(win, page_id)
        problem = _verdict(f"高 {height} / {page_id}", *measure())
        if problem:
            spinning.append(problem)
    assert not spinning, spinning


def test_it_also_sleeps_with_the_music_bar_present(rig, qapp):
    """音乐条占 42px 且是单向的（RN-195），放过一次音乐的用户永远在这一档。"""
    import _audit_music_bar as mbar
    import _ui_mode

    win, measure, resize = rig
    resize(1280, 800)
    mbar.pin(win, qapp, mbar.MODE_WORST_CASE)
    spinning = []
    for page_id in ("basic", "crosshair"):
        _ui_mode.goto(win, page_id)
        problem = _verdict(f"音乐条 / {page_id}", *measure())
        if problem:
            spinning.append(problem)
    mbar.assert_stable(win)
    assert not spinning, spinning


def test_a_real_viewport_change_still_rescrolls_the_current_item(rig, qapp):
    """别把校正整个掐掉：窗口真变矮了，当前项还得滚回视口里（RN-008）。"""
    from PySide6.QtCore import QPoint

    import _ui_mode

    win, measure, resize = rig
    resize(1280, 1000)
    _ui_mode.goto(win, "about")
    measure()
    resize(1280, 800)
    measure()

    scroll = win._sidebar_scroll
    if scroll.verticalScrollBar().maximum() <= 0:
        pytest.skip("这个高度下侧栏不需要滚动，量不到东西")
    btn = win.nav_buttons["about"]
    y = btn.mapTo(scroll.viewport(), QPoint(0, 0)).y()
    assert y >= 0 and y + btn.height() <= scroll.viewport().height(), (
        f"窗口变矮后当前项没滚回来：y={y} 高={btn.height()} 视口={scroll.viewport().height()}")
