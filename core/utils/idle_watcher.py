# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""用户空闲侦测器（2.2.2，UP-005/D-12）。

为什么要有它:启动后的静默预载会在主线程上一页一页地建,每页 200~640ms 不可打断
(实测:全局 42KB QSS 生效时,单页 630~670 个子控件的样式解析就要 215~240ms)。
2.2.0 把调度间隔从 50ms 拉到 200ms,只是把卡顿之间的缝隙拉宽,单次停顿照旧。

治本的办法不是让建页变快(那是 Qt 样式引擎的成本,压不下去),而是**别在用户
正在操作的时候干这件事**。本模块提供"距上次用户输入过了多久"的判据,
让预载队列在用户活跃时主动让路。

只装一个 application 级事件过滤器,回调里只写一个时间戳,开销可忽略。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject


# 视为"用户正在操作"的事件。滚轮/按键/点击是强信号;鼠标移动稍弱但也说明
# 人在看着屏幕操作,预载让路一下没有代价。
_INPUT_EVENTS = frozenset({
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonRelease,
    QEvent.Type.MouseButtonDblClick,
    QEvent.Type.MouseMove,
    QEvent.Type.KeyPress,
    QEvent.Type.KeyRelease,
    QEvent.Type.Wheel,
    QEvent.Type.TouchBegin,
    QEvent.Type.TouchUpdate,
})


class IdleWatcher(QObject):
    """记录最近一次用户输入的时刻。"""

    def __init__(self, app):
        super().__init__(app)
        self._last_input = time.perf_counter()
        self._app = app
        app.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt 命名)
        # 这个函数会被**每一个** Qt 事件调用，包括建页时的成千上万次布局/绘制事件。
        # 复核实测：写成带 try/except 的版本会让建页明显变慢。
        # 所以这里刻意写成最省的形式：一次 type() + 一次 frozenset 命中判断，
        # 不加 try（frozenset in 与属性赋值都不会抛），不做任何其它工作。
        if event.type() in _INPUT_EVENTS:
            self._last_input = time.perf_counter()
        return False  # 绝不吞事件

    def seconds_since_input(self) -> float:
        return time.perf_counter() - self._last_input

    def is_app_active(self) -> bool:
        """本应用是不是当前前台应用。

        为什么需要它:光看"多久没输入"分不清两种完全相反的情形——
          A. 用户去泡咖啡了 → 真空闲,正是干后台活的好时机;
          B. 用户 Alt-Tab 进了 CS2 正在打比赛 → 本应用收不到任何输入,
             "看起来"也空闲,但这恰恰是最不该抢 CPU 的时刻。
        应用未激活时一律不认为空闲,把 B 挡掉。
        """
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is None:
                return False
            return app.applicationState() == Qt.ApplicationState.ApplicationActive
        except Exception:
            return False

    def is_idle(self, threshold_s: float) -> bool:
        """用户是否处于"可以干后台活"的状态。

        两个条件同时成立才算:① 本应用是前台;② 距上次输入超过阈值。
        """
        if not self.is_app_active():
            return False
        return self.seconds_since_input() >= threshold_s

    def note_input(self) -> None:
        """手动标记一次输入（供测试或非事件来源的活动使用）。"""
        self._last_input = time.perf_counter()


_instance = None


def start_idle_watcher(app) -> IdleWatcher:
    """安装全局空闲侦测器（幂等）。"""
    global _instance
    if _instance is None:
        _instance = IdleWatcher(app)
    return _instance


def get_idle_watcher():
    """取已安装的侦测器；未安装返回 None。"""
    return _instance
