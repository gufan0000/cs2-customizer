# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""工装的**界面模式**：这一张图拍的是哪一种用户看见的画面（RN-134）。

## 缺陷

翻新工程从开工到 P2 收尾，**每一个视觉工装都写着 `config.ui_expert_mode = True`**
（截图、排版审计、像素基线、结构投影、耗时基准，各写一份）。
于是十七轮外审、十六页像素基线、每一次排版审计，看的**全是专家视图** ——
而产品默认是 `ui_expert_mode = False`，绝大多数用户根本看不到那个画面。

咬到的是 RN-133：我把「内部调试」卡片收进了专家模式，**改完复跑外审还在报它**
—— 因为截图脚本自己把专家模式打开了。一条已经修好的缺陷，在工装眼里毫无变化。

## 根因：一个开关同时兜着两件事

专家模式在工装里承担了两件**完全不同**的职责：

  (a) **可达性** —— 6 个专家页在普通模式下没有导航入口，
      `MainWindow.show_page()` 命中就直接 return，工装拿不到那一页。**这件是必要的。**
  (b) **视图** —— 顺带把每一页都换成专家视图。**这件没人要过，是副作用。**

而十六处 `win.show_page(pid, animated=False)` **一处都没带 `force`**，全靠 (a) 兜着。
⇒ 那行 `= True` 谁也质疑不了：拿掉它，工装当场少拍 6 页，看起来就是"不能拿掉"。

⭐ **一个开关同时兜着两件事的时候，它就没法被质疑了** ——
质疑的人会立刻被另一件事打回来。**得先把两件事拆开，才谈得上选。**

⇒ 本模块把两件拆开：**可达性走 `goto()`（一律 force），视图走 `--expert`（默认关）。**
"""
from __future__ import annotations

#: 工装的默认界面模式，**必须跟产品默认（`config.ui_expert_mode = False`）一致** ——
#: 工装拍的要是用户看得见的画面，不是开发者看得见的画面。
DEFAULT_EXPERT = False


def add_expert_argument(ap) -> None:
    """给工装装上统一措辞的 `--expert`（默认关）。"""
    ap.add_argument(
        "--expert", action="store_true",
        help="按**专家模式**取样（默认按产品默认的普通模式）。"
             "只有在专门审专家视图时才给 —— 见 RN-134。")


def apply(config, expert: bool) -> bool:
    """定下界面模式。

    ⚠ 必须在 `MainWindow` 构造**之前**调：窗口一进 `__init__` 就据此建导航区，
    构造完再改只会得到"导航是普通、页面是专家"的四不像（同 UP-100 那条紧凑模式）。
    """
    config.ui_expert_mode = bool(expert)
    return bool(expert)


def describe(expert: bool) -> str:
    """报告里必须写清这一批取样是哪一种视图 —— 不写，读的人会默认是普通视图。"""
    return "专家模式（ui_expert_mode=True）" if expert else "普通模式（产品默认）"


def goto(win, page_id: str) -> None:
    """把窗口切到某一页，**不受界面模式影响**。

    `force=True` 是这里的全部要害：普通模式下 6 个专家页没有导航入口，
    不带 force 的 `show_page` 会**静默 return**，工装于是拿着**上一页**的窗口
    继续拍/继续量 —— 不报错，只是那几张图张冠李戴。
    （产品里 force 的正主是搜索跳转：命中被隐藏的页就临时打开它。）
    """
    win.show_page(page_id, animated=False, force=True)


def expert_only_pages(win) -> set:
    """普通模式下没有导航入口的那几页 —— **唯一真相源在 `MainWindow`**，别再抄一份。"""
    return set(getattr(win, "_expert_only_pages", ()) or ())
