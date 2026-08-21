# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""「去社区拿一套」这条路，全仓只从这里走（RN-145 / RN-153）。

## 它存在的理由有两个，都很具体

**一、跨发行版的那道门只开一次。**
`service_urls.py` 是**开源版自己所有**的文件 —— 开源版那一份里没有社区站
（那是闭源商业版的运营资产）。所以每一处用到社区地址的代码都得
`try: from service_urls import ... except ImportError`。
⚠ RN-157 就是这么炸的：一处漏了守卫，判据同步到开源仓之后**挂死 300 秒**。
⇒ 那道 `try/except` 在这里写**一次**，八个页面直接问这个模块。

**二、"没有社区站"必须是一个真实的产品形态，不是一个坏掉的按钮。**
`category_url()` 查不到就回空串，调用方据此**换一条真的走得通的路**
（例如退回「打开音频资源」）。
⭐ **一颗指向空地址的按钮比没有按钮更糟** —— 它看起来是出路，点下去什么也没有。
"""
from __future__ import annotations

from core.utils.logger import get_logger

try:
    # ⚠ **结构上可选**，不靠同步管道打补丁：开源版的 `service_urls.py`
    # 归它自己所有，里面没有社区站。
    from service_urls import COMMUNITY_CATEGORY_URLS
except ImportError:                      # pragma: no cover - 只有开源版会走到
    COMMUNITY_CATEGORY_URLS = {}

_logger = get_logger("CommunityLibrary")


def category_url(key: str) -> str:
    """这一类资源在社区站的地址；没有就回空串。

    ⚠ 回空串**不是异常**，是"这个发行版没有社区站"这一形态的正常取值。
    调用方必须据此换一条路，别把空串塞进 `openUrl`。
    """
    return str(COMMUNITY_CATEGORY_URLS.get(key, "") or "")


def has_category(key: str) -> bool:
    return bool(category_url(key))


def open_category(key: str) -> bool:
    """用系统浏览器打开这一类资源的社区页面。回报有没有真的打开。"""
    url = category_url(key)
    if not url:
        _logger.warning(f"这个发行版没有社区站分类 {key!r}，未打开")
        return False
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    return bool(QDesktopServices.openUrl(QUrl(url)))
