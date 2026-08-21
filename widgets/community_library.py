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


def guide_empty_library(bar, *, empty: bool, category_key: str, cta_text: str,
                        keep_text: str, keep_callback, message: str) -> bool:
    """风格库空的时候，把底栏改成一条**走得通的路**。回报有没有真的改。

    ⭐ **"打开一个空文件夹"不是一条路** —— 全新安装时那颗最抢眼的按钮
    点开是个空目录，而用户手上没有文件。

    ⚠ **`keep_text` / `keep_callback` 不是可选装饰，是第二步。**
    RN-153 第一版把原来那颗「打开资源目录」整个换掉了，外审当场两发独立点破：
    「文案提示『放进资源目录』却没有打开目录的入口，从社区下载后卡在找路径」。
    ⭐ **我修好了第一步（去哪儿拿），却顺手删掉了第二步（放哪儿去）** ——
    一条三步的路，只把第一步做顺是走不通的。
    ⇒ 这里强制要求调用方把那颗按钮交出来，由本函数挪到 extra 位保住它。

    ⚠ 没有社区站时（开源版）**什么都不做、回报 False**，让调用方保持原样 ——
    一颗指向空地址的按钮比没有按钮更糟。

    ⭐ 这个函数是**全仓唯一一份**空库引导。八个页面的"库空不空"各问各的
    （数据结构完全不同），但"空了该长什么样"只有这一处 ——
    否则八页会长出八个略有差别的空状态，而没有任何东西会发现它们不一样。
    """
    if not empty or not has_category(category_key):
        return False
    bar.configure_primary(cta_text, lambda: open_category(category_key), visible=True)
    # 第二步：原来那颗「打开…文件夹」挪到 extra 位。
    # ⚠ 有些页的 extra 是个带 QMenu 的按钮（风格工具），得先把菜单摘掉，
    # 否则点它弹的还是菜单、回调根本不会跑。
    bar.extra_btn.setMenu(None)
    bar.configure_extra(keep_text, keep_callback, visible=True)
    bar.set_message(message)
    return True


def empty_library_message(what: str, refresh_label: str = "刷新风格列表") -> str:
    """空库时底栏那句话。**先承认软件本来就不带素材**，再给三步。

    ⭐ 不说"本来就没有"的话，用户会以为是自己装坏了（RN-145 的原话）。
    """
    return (f"还没有任何可用{what} —— 本软件不带素材。三步：去社区拿一个包 → "
            f"用旁边那颗按钮打开资源目录放进去 → 点「{refresh_label}」。")


def open_category(key: str) -> bool:
    """用系统浏览器打开这一类资源的社区页面。回报有没有真的打开。"""
    url = category_url(key)
    if not url:
        _logger.warning(f"这个发行版没有社区站分类 {key!r}，未打开")
        return False
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    return bool(QDesktopServices.openUrl(QUrl(url)))
