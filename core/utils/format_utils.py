# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""UI 数值格式化工具。

背景（Phase1-1.1，2026-06-10）：此前各页面用 ``f"{int(value*100)}%"`` 直接渲染
百分比标签（全仓 30 处），值一旦越界（脏配置/迁移失误）就会显示出
「10000%」这类离谱数字——2.1.2 修过的首页音量 bug 即此模式。
本模块提供统一的"夹紧后格式化"，从根上消灭这一类显示问题。
"""
from __future__ import annotations


def clamp(value, lo: float, hi: float, fallback: float = 0.0) -> float:
    """把 value 安全地夹到 [lo, hi]；不可转 float / NaN 时返回 fallback。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    if v != v:  # NaN
        return fallback
    return max(lo, min(hi, v))


def format_percent(value, lo: float = 0.0, hi: float = 1.0, fallback: float = 0.0) -> str:
    """把比例值（通常 0–1，可指定上限如 2.0=200%）格式化为 'NN%'，自动夹紧。

    >>> format_percent(0.5)
    '50%'
    >>> format_percent(100)      # 脏数据：被夹到上限
    '100%'
    >>> format_percent(1.5, hi=2.0)
    '150%'
    >>> format_percent(None)
    '0%'
    """
    v = clamp(value, lo, hi, fallback)
    return f"{int(round(v * 100))}%"
