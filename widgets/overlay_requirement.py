# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-429：画在**游戏画面**上的东西，有一个玩家不知道的前提。

CS2 跑**独占全屏**时，任何覆盖层都画不上去 —— 准心、屏幕特效、击杀图标
一个像素都不会出现。玩家在页面上配了半天，进游戏什么都没有，
他不会想到是显示模式的问题，**他会判定「这软件坏了」**。

那正是 RN-407 家族整整六批在防的同一种误判，只是换了一个成因。

## ⭐⭐ 为什么这次「只写文案」是对的

RN-409 的证据格里留着一句警告：「批 10 已证过**文案救不了形状**」。
那次说的是一颗**灰着的、紫色的、蹲在右下角的按钮** —— 形状本身在喊
「这里有个保存动作」，而那一页根本没有保存动作；文案改不动那个形状。

**这里没有相反的形状在说话。** 页面对独占全屏这件事**完全沉默**，
玩家不是被误导，是**根本不知道有这么个前提**。从 0 到 1 的信息，
文案就是对的手段 —— 批 18 那一轮同样是纯文案，
「他知不知道现在就能先调」从 **0% → 57% → 100%**。

> ⭐⭐⭐ **「文案打不动」是对某一条缺陷说的，不是对文案这个手段说的。**

（RN-421 那条禁令同样只适用于「以为已生效」那条轴。这是它第二次被正确地不适用。）

## 语序：先说他能做什么，再说会怎样

批 18 实测过：同一句话把「现在可以调」提到前面，
「他知不知道该干什么」从 57% 到 100%。所以这句是：

    CS2 显示模式选「无边框窗口化」，<东西>才画得到游戏画面上
    —— 独占全屏会把它整个盖住。

**动作在前，后果在后。**

## ⚖ 检测：批 72 补上（RN-434），但**只许加强，不许撤销**

读到独占全屏 ⇒ 话说得更具体；其余一切（含读不到、几个账号读数不一致）
⇒ 原样输出下面那句通用提示。理由与实测见 `core/cs2_video_mode.py`。
"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

#: 这句话挂的 objectName —— 判据与出图都按它找。
OVERLAY_HINT_OBJECT_NAME = "overlayRequirementHint"

#: 这句话必须同时说清「怎么做」和「否则会怎样」。判据按这两个词认。
REQUIRED_WORDS = ("无边框窗口", "独占全屏")


def overlay_requirement_text(thing: str, *, exclusive_now: bool = False) -> str:
    """`thing` = 这一页配的、会画到游戏画面上的那个东西（「准心」「击杀图标」…）。

    `exclusive_now` 只有在**确证**玩家此刻就在独占全屏时才为真（RN-434）。
    ⛔ 它只影响措辞的具体程度，**两档都必须把「怎么做」和「否则会怎样」说全** ——
    `REQUIRED_WORDS` 对两档一视同仁。
    """
    if exclusive_now:
        # ⚠ **动作仍然在前**：第一版写成「读到你现在是独占全屏 —— 先去改…」，
        #   诊断跑到了动作前面，判据当场逮住（批 18 实测：同一句话把
        #   「现在可以调」提到前面，「他知不知道该干什么」57% → 100%）。
        #   ⭐ 加了一条新信息，很容易顺手把语序也换掉。
        return (
            f"⚠ 先去 CS2 把显示模式改成「无边框窗口化」，{thing}才画得到游戏画面上"
            f"——读到你现在正是「独占全屏」，它会把{thing}整个盖住，什么都不会显示。"
        )
    return (
        f"⚠ 先去 CS2 把显示模式选成「无边框窗口化」，{thing}才画得到游戏画面上"
        f"——独占全屏会把它整个盖住，什么都不会显示。"
    )


def make_overlay_requirement_label(thing: str) -> QLabel:
    """建那句话。⚠ 调用方负责把它放进**参数区之前**能看到的位置。

    ⭐ 「解释性文字放在困惑发生的位置之前」—— 放在页尾或帮助面板里等于没放
    （网站那两轮 6 发都说「藏在底部小字里」；`screen_effects` 这条前提
    至今只写在折叠的帮助面板里，等于没写）。
    """
    from core.cs2_video_mode import overlay_is_invisible_now

    label = QLabel(overlay_requirement_text(
        thing, exclusive_now=overlay_is_invisible_now()))
    label.setObjectName(OVERLAY_HINT_OBJECT_NAME)
    label.setWordWrap(True)
    return label


def overlay_requirement_label(page) -> QLabel | None:
    """在一页上找那句话（判据与出图用）。"""
    for label in page.findChildren(QLabel):
        if label.objectName() == OVERLAY_HINT_OBJECT_NAME:
            return label
    return None
