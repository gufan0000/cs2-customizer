# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""资源目录的「代数」：导入一次 +1，各页进页时问一句「我上次扫完之后变过没有」（批 123）。

批 123 让各页直接收拖进来的整包、转交「导入资源」去装。装完用户切回原来那一页 ——
而特殊音效 / 枪声 / 闪光三页**进页根本不重扫**，四个音效页有 10 秒冷却：
**导入报成功，回去一看下拉里没有**，正是「不知道怎么生效」那句外审原话。
⇒ 导入落盘后 `bump()`；页面 `showEvent` 里 `take_news(self)` 为真就重扫，不看冷却。

纯 Python、不碰 Qt：导入在工作线程里跑也能调。
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_generation = 0
_ATTR = "_resource_generation_seen"


def bump() -> int:
    """资源目录刚被写过（导入 / 撤销导入）。"""
    global _generation
    with _lock:
        _generation += 1
        return _generation


def current() -> int:
    return _generation


def take_news(owner) -> bool:
    """`owner` 上次问过之后资源目录变过没有；问过即记下。

    第一次问返回 False：页面刚建出来时自己扫过一遍，不算「错过了」。
    """
    now = _generation
    seen = getattr(owner, _ATTR, None)
    try:
        setattr(owner, _ATTR, now)
    except Exception:
        return False
    return seen is not None and seen != now
