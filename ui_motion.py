# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""装饰性动效的总开关（RN-639，视觉回调第一步）。

管的是**纯装饰**的那几样：按钮水波纹、流光、输入框焦点下划线、滑块数值气泡、
卡片改值时的闪边。它们全是 2026-04-19 一起入库的，各自一个时长、各自一条曲线，
叠在一起用户读到的是「乱」。默认**关**。

不管的：toast（它是功能反馈）、帮助面板与音乐条的收展、开关按钮的滑块位移 ——
那些是「东西去哪了」的空间连续性，不是装饰。

⚠ 这是一个开关，不是删除：`ui_decorative_motion = True` 写进 config 就全站恢复。
每个安装函数在自己的入口问一次这里，**不要**在调用点各判一遍 —— 调用点有 8 处，
漏一处就是「关了但还在动」，而那和「没关」在屏幕上分不开。
"""
from __future__ import annotations

#: 默认值。要改默认请改这一行，别在各安装函数里各写一个。
DEFAULT_ENABLED = False

#: config 里的覆盖键；没有这一项就用默认值。
CONFIG_KEY = "ui_decorative_motion"


def decorative_motion_enabled() -> bool:
    """装饰性动效现在该不该装。config 有覆盖就听 config 的，否则听默认值。"""
    try:
        from config import config
    except Exception:          # noqa: BLE001 - 工装或最小化环境里没有 config
        return DEFAULT_ENABLED
    value = getattr(config, CONFIG_KEY, None)
    if value is None:
        return DEFAULT_ENABLED
    return bool(value)
