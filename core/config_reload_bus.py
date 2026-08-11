# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""配置重载广播（UP-035）。

**这修的是数据安全洞，不是刷新体验。**

原状：用户点「应用预设」，看到成功提示，切回某个**之前打开过**的页面——
那个页面上的控件还显示着旧值（它只在构造时读过一次配置）。用户随手动一下
滑块，`_on_xxx_changed` 就拿控件里的**旧值** `save_config()`，
把刚应用的整套预设悄悄改回去。配置快照「恢复」同理：回滚功能在已访问过的
页面上直接失效。

全项目 grep 不到任何 `config_reloaded` / `reload_all_pages` 类机制，
所以这里补一个最小的：**core 层模块级回调表**。

为什么放在 core 而不是让 core 直接调 UI：
core 是被 UI 依赖的下层，反过来 import gui_widget 会成环，而且 core 的逻辑
（预设、快照、地图规则）在没有 GUI 的场景下也要能跑（测试、CLI）。
观察者模式让 core 只管"喊一声"，谁来听、听了做什么由上层决定。

线程约定：`notify()` 可能在**任意线程**被调用——例如 `core/presets/map_rules.py`
的按地图自动切预设是 GSI 事件驱动的，跑在后台线程上。订阅方如果要碰 Qt 控件，
**必须自己marshal 回 GUI 线程**（`gui_widget` 用的是 Signal 队列连接）。
"""
from __future__ import annotations

import threading
from typing import Callable, List, Sequence

from core.utils.logger import get_logger

__all__ = ["subscribe", "unsubscribe", "notify", "subscriber_count"]

_logger = get_logger("ConfigReloadBus")
_lock = threading.RLock()
_subscribers: List[Callable[[str, tuple], None]] = []


def subscribe(callback: Callable[[str, tuple], None]) -> None:
    """注册订阅者。重复注册同一个可调用对象会被忽略。

    回调签名：`callback(reason: str, changed_keys: tuple[str, ...])`
    """
    with _lock:
        if callback not in _subscribers:
            _subscribers.append(callback)


def unsubscribe(callback: Callable[[str, tuple], None]) -> None:
    """注销订阅者。没注册过也不报错——调用方不必先判断。"""
    with _lock:
        try:
            _subscribers.remove(callback)
        except ValueError:
            pass


def subscriber_count() -> int:
    with _lock:
        return len(_subscribers)


def notify(reason: str, changed_keys: Sequence[str] | None = None) -> int:
    """广播「配置已被整体改写」。返回成功通知到的订阅者数。

    每个订阅者独立 try/except：**订阅者出错绝不能让写配置这件事失败**。
    配置已经落盘了，此刻抛异常只会让调用方以为应用预设失败，
    而实际上它成功了——那比不刷新界面糟得多。
    """
    with _lock:
        targets = list(_subscribers)
    keys = tuple(changed_keys or ())
    ok = 0
    for cb in targets:
        try:
            cb(str(reason or ""), keys)
            ok += 1
        except Exception:
            _logger.exception("配置重载订阅者执行失败（已忽略，不影响配置写入）")
    if targets:
        _logger.info(f"[配置重载] {reason}: 已通知 {ok}/{len(targets)} 个订阅者")
    return ok
