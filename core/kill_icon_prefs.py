# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标的「偏好」纯逻辑（批 118，对标补课）：风格条顺序、最近用过、隐藏、按风格记的位置。

不碰 Qt、不碰 config 对象本身 —— 进来的是值、出去的是新值，页面负责落盘。
"""
from __future__ import annotations

RECENT_KEEP = 8
LAYOUT_KEYS = ("x", "y", "scale")


def ordered_styles(styles, recent=(), hidden=(), keep=""):
    """风格条的顺序：最近用过的在前（越近越前），其余按名字稳定排序；藏起来的不出现。

    以前就是 `os.listdir` 的顺序 —— 装了十几套之后常用的那套可能排在最后。
    `keep`：正在用的那套，就算被藏了也留着（不许把当前风格从条上变没）。
    """
    styles = list(dict.fromkeys(str(s) for s in styles))
    hidden = {str(s) for s in hidden} - {str(keep)}
    visible = [s for s in styles if s not in hidden]
    rank = {s: i for i, s in enumerate(str(r) for r in recent)}
    front = sorted((s for s in visible if s in rank), key=rank.__getitem__)
    rest = sorted(s for s in visible if s not in rank)
    return front + rest


def remember_recent(recent, style, keep=RECENT_KEEP):
    style = str(style)
    return ([style] + [str(s) for s in recent if str(s) != style])[:keep]


def can_hide(styles, hidden, style, current=""):
    """藏完至少还剩一套看得见的，且不能藏正在用的那套（防用户把自己锁死）。"""
    style = str(style)
    if not style or style == str(current):
        return False
    remaining = [s for s in styles if str(s) != style and str(s) not in {str(h) for h in hidden}]
    return bool(remaining)


def layout_of(layouts, style, fallback):
    """这套风格记着的位置/大小；没记过就用 `fallback`（切过来那一刻的全局值 —— 老用户调好的不丢）。"""
    stored = (layouts or {}).get(str(style))
    base = dict(fallback)
    if isinstance(stored, dict):
        for key in LAYOUT_KEYS:
            if key in stored:
                base[key] = stored[key]
    return base


def with_layout(layouts, style, x, y, scale):
    new = dict(layouts or {})
    new[str(style)] = {"x": int(x), "y": int(y), "scale": float(scale)}
    return new
