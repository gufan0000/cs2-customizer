# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R1-6 页面使用追踪:计数、衰减排序、排除名单、损坏文件自愈、常用分组装配。"""
import json
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core import page_usage_tracker as put


@pytest.fixture(autouse=True)
def clean_store():
    put.reset()
    yield
    put.reset()


def test_record_and_rank():
    for _ in range(5):
        put.record_page_open("crosshair")
    put.record_page_open("music")
    top = put.top_pages(4)
    assert top[0] == "crosshair"
    assert "music" in top


def test_excluded_pages_never_tracked():
    put.record_page_open("basic")
    put.record_page_open("about")
    assert put.top_pages(4) == []


def test_recency_decay_orders_stale_below_fresh():
    # 旧页:次数多但 60 天没用;新页:次数少但刚用
    data = {
        "old_page": {"count": 30, "last_used": time.time() - 60 * 86400},
        "new_page": {"count": 4, "last_used": time.time()},
    }
    with open(put._store_path(), "w", encoding="utf-8") as f:
        json.dump(data, f)
    top = put.top_pages(2)
    assert top[0] == "new_page"


def test_known_pages_filter_drops_retired_ids():
    put.record_page_open("ghost_page")
    put.record_page_open("crosshair")
    top = put.top_pages(4, known_pages={"crosshair", "music"})
    assert "ghost_page" not in top


def test_corrupt_store_self_heals():
    with open(put._store_path(), "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert put.top_pages(4) == []
    put.record_page_open("crosshair")  # 不抛异常即自愈
    assert put.top_pages(4) == ["crosshair"]


def test_mainwindow_frequent_group_builds(tmp_path):
    """有历史数据时,主窗体装配出「常用」分组且按钮可跳页。"""
    for _ in range(3):
        put.record_page_open("crosshair")
    put.record_page_open("music")

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        assert win.frequent_group is not None
        assert "crosshair" in win._frequent_buttons
        # 点击常用按钮 → 切页 + 选中态同步
        win._frequent_buttons["crosshair"].click()
        assert win.content_stack.currentWidget() is win.pages["crosshair"]
        assert win._frequent_buttons["crosshair"].isChecked()
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


# ==================== UP-016: 去抖落盘 ====================

def test_record_does_not_write_disk_immediately():
    """切页那一帧不该碰磁盘——原先每次切页都同步读+写一次 JSON。"""
    put.reset()
    path = put._store_path()
    before = os.path.getmtime(path) if os.path.exists(path) else 0

    put.record_page_open("crosshair")

    after = os.path.getmtime(path) if os.path.exists(path) else 0
    assert after == before, "record_page_open 不应立即落盘"
    # 但内存里必须已经记上了
    assert put._load().get("crosshair", {}).get("count") == 1


def test_flush_persists_pending_writes():
    """退出兜底 flush 必须把待写数据落盘，否则最后几次统计会丢。"""
    put.reset()
    put.record_page_open("crosshair")
    put.record_page_open("crosshair")
    put.flush()

    with open(put._store_path(), "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk.get("crosshair", {}).get("count") == 2


def test_flush_is_noop_when_clean():
    put.reset()
    put.flush()  # 不该抛
    put.flush()


def test_external_write_is_picked_up():
    """外部改动文件（测试夹具/配置恢复）后必须能读到新内容，不能被缓存挡住。"""
    put.reset()
    put.record_page_open("crosshair")
    put.flush()

    time.sleep(0.01)
    with open(put._store_path(), "w", encoding="utf-8") as f:
        json.dump({"utility": {"count": 99, "last_used": time.time()}}, f)

    top = put.top_pages(2)
    assert top and top[0] == "utility", "缓存不该挡住外部写入"


def test_concurrent_record_and_flush_never_corrupts():
    """去抖 flush 在 Timer 线程写盘，GUI 线程同时改同一个 dict。

    加锁前：json.dump 遍历途中被插入新键会抛 RuntimeError（dict changed size
    during iteration），在 Timer 线程里就是静默丢数据，严重时写出半截 JSON。
    """
    import threading

    put.reset()
    errors = []
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            try:
                put.record_page_open(f"page_{i % 50}")
            except Exception as exc:
                errors.append(("record", exc))
            i += 1

    def flusher():
        while not stop.is_set():
            try:
                put._dirty = True  # 强制每次都真的写
                put.flush()
            except Exception as exc:
                errors.append(("flush", exc))

    threads = [threading.Thread(target=writer), threading.Thread(target=flusher)]
    for t in threads:
        t.daemon = True
        t.start()
    time.sleep(0.6)
    stop.set()
    for t in threads:
        t.join(timeout=2)

    assert not errors, f"并发下不应抛异常: {errors[:3]}"

    # 文件必须仍是合法 JSON（没被写成半截）
    put.flush()
    with open(put._store_path(), "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)


def test_write_is_atomic_no_temp_left():
    """原子写盘：写完不留 .tmp，且文件始终是合法 JSON。"""
    put.reset()
    put.record_page_open("crosshair")
    put.flush()

    path = put._store_path()
    assert not os.path.exists(path + ".tmp"), "不应残留临时文件"
    with open(path, "r", encoding="utf-8") as f:
        assert isinstance(json.load(f), dict)


def test_flush_cancels_pending_timer():
    """退出兜底 flush 必须取消挂起的 daemon Timer。

    退出链路有看门狗（超时 os._exit），让 Timer 在那之后才醒来写盘，
    写到一半被切断就白搭。
    """
    put.reset()
    put.record_page_open("crosshair")
    assert put._flush_timer is not None, "record 后应当有挂起的去抖 timer"
    put.flush()
    assert put._flush_timer is None, "flush 后挂起的 timer 应当已被取消"
