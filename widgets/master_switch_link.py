# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""功能页上那颗「去总开关」（RN-144）。

## 它要修的是什么

准心 / 屏幕特效 / 换弹音效三页都把总开关的**状态**摆在首屏
（「显示 · 未启用」「特效 · 未启用」），**却既不能在本页开、也没有入口**。
外审两档 6/6 票：「玩家调完准心进游戏不显示，会以为软件坏了」。

⭐ **把状态摆出来而不给动作，比不摆更糟。** 不摆的话玩家至少不知道有这回事；
摆出来 = 明确告诉他"有个东西没开"，然后让他自己去 22 项导航里翻。

与 RN-108 同一片区但机制不同：RN-108 修的是「基础设置」在侧栏里找不到
（已单独成组置顶），这条说的是**状态在这儿、开关不在这儿**。

## 为什么是一个共用模块而不是各页抄一份

三页要的是同一件事，而这件事里有三样抄漏了**不会报错**的东西：
去哪一页（`basic`）、那一页叫什么（「基础设置」，写进文案里）、
以及跳过去之后要不要指给他看。RN 里已经有一条现成的教训：
**文案里点名的目标名要跟真正的目标走**，抄成字面量早晚对不上。

## 失败时不许一声不吭

`reveal_master_switch` 回报 bool。但更要紧的是**结构上的兜底**：
按钮的 tooltip **永远**写着手动路径（「基础设置」→「功能开关」），
所以哪怕跳转这条路整条坏掉，用户手上也还有一条能走的路。
⇒ 引导的兜底不该是"失败了弹一句话"，而是"这句话本来就一直在"。
"""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from core.utils.logger import get_logger

#: 总开关住在哪一页。三页共用一个真源 —— 页面 id 改了只改这里。
MASTER_SWITCH_PAGE_ID = "basic"
#: 那一页在导航里叫什么。写进按钮文案与 tooltip，别在各页抄字面量。
MASTER_SWITCH_PAGE_NAME = "基础设置"
#: 总开关那张卡叫什么（`gui_widget._create_basic_page` 里的「功能开关」）。
MASTER_SWITCH_CARD_NAME = "功能开关"
#: 按钮文案。刻意**不随开关状态改文案** —— 它是这一页的一条常驻事实
#: （"总开关不在这儿"），不是一条只在关着时才成立的提示。
LINK_TEXT = "去总开关"

_logger = get_logger("MasterSwitchLink")


def manual_path_text(feature_name: str) -> str:
    """手动路径那句话。tooltip 和任何降级文案都从这里取，只有一份。"""
    return (f"「{feature_name}」的总开关在「{MASTER_SWITCH_PAGE_NAME}」页的"
            f"「{MASTER_SWITCH_CARD_NAME}」里。点这里直接跳过去并高亮它。")


def reveal_master_switch(page, config_key: str) -> bool:
    """跳到总开关那一页并高亮对应的那一行。

    回报 True 表示真的定位到了。定位不到时**只记日志、不弹框** ——
    tooltip 里那条手动路径一直在，用户不会没路可走。
    """
    window = page.window() if page is not None else None
    reveal = getattr(window, "reveal_feature_switch", None)
    if not callable(reveal):
        _logger.warning(f"主窗口没有 reveal_feature_switch，{config_key} 的直达跳转空转")
        return False
    try:
        ok = bool(reveal(config_key))
    except Exception as exc:
        _logger.error(f"跳转到总开关失败（{config_key}）: {exc}")
        return False
    if not ok:
        _logger.warning(f"没有找到 {config_key} 对应的总开关，直达跳转空转")
    return ok


def make_master_switch_button(page, config_key: str, feature_name: str) -> QPushButton:
    """建一颗「去总开关」，接线一次接好。"""
    button = QPushButton(LINK_TEXT)
    button.setObjectName("secondaryButton")
    # 写下限不写死宽：中文文案 + 字号缩放 = 截断（UP-094 的教训）。
    button.setMinimumWidth(96)
    button.setFixedHeight(26)
    button.setToolTip(manual_path_text(feature_name))
    button.clicked.connect(lambda: reveal_master_switch(page, config_key))
    return button
