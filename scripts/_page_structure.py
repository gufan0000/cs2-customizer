# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""页面**结构投影**：指纹里那部分与字体无关的东西。

**为什么要单独有这一层**（翻新工程 §9.1）：
`page_fingerprint.py` 的指纹含 `size` / `pos`，而那两项由**文字排出来的宽度**决定 ——
换台机器字体不同，数就不同。它自己也知道，所以字体库为空时**直接拒绝出具指纹**。
⇒ **完整指纹只能当本机判据，进 CI 必然假红。**

而翻新工程需要一条能进 CI 的结构判据（页面还是不是原来那些控件、文案有没有变），
于是把指纹投影掉几何，只留：**类型 / objectName / 启用态 / 文案**。这几项
在任何机器上都一样，可以放心进 CI。

⚠ 本模块**必须保持零副作用**：不设环境变量、不动 `QT_QPA_PLATFORM`、不建 QApplication。
`page_fingerprint.py` 在模块级 `os.environ.pop("QT_QPA_PLATFORM")`（它要真实字体），
判据要是导了它，离屏就被掀掉了 —— 窗口会真的弹到用户脸上。**这就是为什么不复用它。**

**故意不收 `visible`**：它跟父窗口有没有 show、滚动区怎么排都有关，
在 CI 上容易抖成假红。可见性的事交给本机的像素基线与完整指纹去管 ——
判据宁可少管一样，也不要变成一条会随机变红的判据（那种判据最后都会被无视）。
"""
from __future__ import annotations

import re

_TEXT_GETTERS = ("text", "currentText", "title", "value")

#: 控件文案里出现的**绝对路径**必须抹掉再入库。
#: ⚠ 这条是 2026-08-17 由 CI 逼出来的：`kill_voice` 页的状态文案里带一句
#: 「缺失目录: C:\Users\21108\AppData\Local\Temp\cs2customizer_...」，
#: 本机存进基线、runner 上量到的是 `C:\Users\RUNNER~1\...` ——
#: **这类页面的 CI 结构判据永远不可能通过**，而红的原因和被判的那次改动毫无关系。
#: 判据只要有一次"不是我的错也会红"，人就会开始无视它，那它就废了。
#: 只抹路径、不抹别的：文案变了本来就该红，那正是这条判据的用途。
_ABS_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]|/(?:home|Users|tmp|var)/)[^\s\"'，。；：]*")


def _scrub_machine_paths(text: str) -> str:
    return _ABS_PATH.sub("<路径>", text)


#: 文案**和启用态**都由"这台机器怎么样"决定的控件（RN-135）。
#:
#: ⚠ 2026-08-20 由 CI 逼出来的第二次，和上面那条抹路径是同一族：
#: `advanced` 页的权限卡片写着「当前权限：管理员」还是「当前权限：普通用户（推荐）」，
#: 旁边那颗「以管理员身份重启」是亮的还是灰的 —— **全看跑它的进程有没有管理员权限**。
#: CI runner 是管理员，我这台不是，于是这一页的结构判据**在两边永远对不上**，
#: 而红的原因和被判的改动毫无关系。
#:
#: ⭐ 这类"基线把环境事实拍了进去"的缺陷有个共同形状：
#: **它不在第一次采基线时暴露，要等到换一台机器才炸**，
#: 而那时人往往正在查一个完全无关的改动。
#: ⇒ 采基线之前先问一句：**这一页有没有哪个控件是在描述「这台机器」而不是「这个软件」？**
#:
#: 只归一这几条、不归一别的：文案变了本来就该红，那正是这条判据的用途。
_ENV_DEPENDENT_TEXT = (
    (re.compile(r"^当前权限："), "当前权限：<环境相关>"),
)
#: 上面那些控件**同一张卡片里**、启用态也随环境变的按钮。
_ENV_DEPENDENT_ENABLED_TEXT = ("以管理员身份重启",)


def _entry(widget) -> dict:
    out = {
        "type": type(widget).__name__,
        "name": widget.objectName(),
        "enabled": widget.isEnabled(),
    }
    for attr in _TEXT_GETTERS:
        getter = getattr(widget, attr, None)
        if not callable(getter):
            continue
        try:
            val = getter()
        except Exception:
            continue
        if isinstance(val, (str, int, float)) and str(val) != "":
            # 先抹路径再截断：不然截断点会正好落在路径中间，抹了也白抹。
            text = _scrub_machine_paths(str(val))[:120]
            for pattern, replacement in _ENV_DEPENDENT_TEXT:
                if pattern.search(text):
                    text = replacement
                    break
            out["text"] = text
            if text in _ENV_DEPENDENT_ENABLED_TEXT:
                # 这颗按钮亮不亮取决于本进程有没有管理员权限（RN-135）
                out["enabled"] = "<环境相关>"
        break
    return out


def structure(page) -> list[dict]:
    """把一页拍成与字体无关的结构清单，顺序稳定可直接逐条比对。"""
    from PySide6.QtWidgets import QWidget

    items = [_entry(page)]
    items.extend(_entry(child) for child in page.findChildren(QWidget))
    # 不按位置排（位置是字体相关的），按内容排——同样稳定，且跨机器一致。
    items.sort(key=lambda e: (e["type"], e["name"], e.get("text", ""), e["enabled"]))
    return items


def diff(old: list[dict], new: list[dict]) -> list[str]:
    """逐条比对，返回人话差异。空列表 = 完全一致。"""
    import json as _json

    def key(e):
        return _json.dumps(e, sort_keys=True, ensure_ascii=False)

    old_keys = [key(e) for e in old]
    new_keys = [key(e) for e in new]
    old_left = list(old_keys)
    out = []
    for k in new_keys:
        if k in old_left:
            old_left.remove(k)
        else:
            out.append(f"+ 多出: {k}")
    for k in old_left:
        out.append(f"- 少了: {k}")
    return out
