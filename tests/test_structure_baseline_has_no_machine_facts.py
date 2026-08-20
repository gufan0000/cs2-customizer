# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""结构基线里不许混进「这台机器怎么样」这种事实（RN-135）。

## 缺陷

`advanced` 页的权限卡片写着「当前权限：管理员」还是「当前权限：普通用户（推荐）」，
旁边那颗「以管理员身份重启」是亮的还是灰的 —— **全看跑它的进程有没有管理员权限**。
CI runner 是管理员、我这台不是，于是这一页的结构判据**在两边永远对不上**：
本机采完基线推上去，CI 当场红，而红的原因和被判的那次改动毫无关系。

同族的上一次是**机器路径**（2026-08-17，`kill_voice` 页状态文案里带
`C:\\Users\\21108\\...`，runner 上是 `C:\\Users\\RUNNER~1\\...`）。

⭐ 这类缺陷的共同形状：**它不在第一次采基线时暴露，要等到换一台机器才炸**，
而那时人往往正在查一个完全无关的改动。
⇒ 采基线之前先问一句：**这一页有没有哪个控件在描述「这台机器」而不是「这个软件」？**

## 判据

不去跑真页面（那反而依赖当前机器的权限），直接喂两个只在环境上不同的假控件，
断言它们投影出来**一模一样**。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "_page_structure", REPO / "scripts" / "_page_structure.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_page_structure"] = mod
    spec.loader.exec_module(mod)
    return mod


ps = _load()


class _FakeWidget:
    """够 `_entry` 用的最小控件：类型名 / objectName / 启用态 / text / 可见性。"""

    def __init__(self, text, enabled=True, name="label", visible=True):
        self._text, self._enabled, self._name = text, enabled, name
        self._visible = visible

    def text(self):
        return self._text

    def objectName(self):
        return self._name

    def isEnabled(self):
        return self._enabled

    def isVisibleTo(self, _root):
        return self._visible


def test_the_privilege_label_projects_the_same_either_way():
    admin = ps._entry(_FakeWidget("当前权限：管理员"))
    normal = ps._entry(_FakeWidget("当前权限：普通用户（推荐）"))
    assert admin == normal, (
        f"权限文案原样进了基线：{admin} vs {normal} —— "
        "本机采、CI 跑，这一页的结构判据永远对不上")


def test_the_elevate_button_projects_the_same_either_way():
    lit = ps._entry(_FakeWidget("以管理员身份重启", enabled=True, name="secondaryButton"))
    grey = ps._entry(_FakeWidget("以管理员身份重启", enabled=False, name="secondaryButton"))
    assert lit == grey, (
        f"提权按钮的启用态原样进了基线：{lit} vs {grey}")


def test_ordinary_text_changes_still_show_up():
    """反面守卫：**别把归一化做成"什么都不比"**。

    这条判据存在的全部理由是"文案变了要红"；归一化只该盖住环境事实那几条。
    """
    a = ps._entry(_FakeWidget("挑一套图标"))
    b = ps._entry(_FakeWidget("挑两套图标"))
    assert a != b, "普通文案改了却投影成一样 —— 这条判据已经什么都管不住了"


def test_hiding_a_widget_shows_up_in_the_projection():
    """投影必须看得见「藏起来了」这件事（RN-134）。

    原先这里**一条可见性都不收**，理由是「`isVisible()` 会因为顶层窗口没 show
    而假红」。那个理由对**那个函数**成立，却把整件事一起否掉了：
    RN-133 我把调试卡片收进专家模式，改完前后两份投影**一模一样** ——
    一条已经修好的缺陷，在结构判据眼里毫无变化。

    ⭐ **「这个具体做法会假红」不等于「这件事不该管」** —— 先换做法，再谈放弃。
    `isVisibleTo(page)` 问的是「这一页要是显示出来，它会不会出现」，
    不问顶层窗口有没有 show，所以既逮得住 hide/show，又不会离屏假红。
    """
    shown = ps._entry(_FakeWidget("内部调试", visible=True), root=object())
    hidden = ps._entry(_FakeWidget("内部调试", visible=False), root=object())
    assert shown != hidden, f"藏起来和显示出来投影成了同一条：{shown}"
    assert shown["visible"] is True and hidden["visible"] is False


def test_visibility_is_only_recorded_when_a_root_is_given():
    """没给 root 就不记可见性 —— 免得留一条「取不到就当可见」的静默兜底。

    静默兜底是本仓最贵的一类错：它让判据在取样失败时**照样通过**。
    """
    assert "visible" not in ps._entry(_FakeWidget("挑一套图标"))


def test_machine_paths_are_still_scrubbed():
    """上一次同族缺陷的守卫，一起钉住（2026-08-17 那条抹路径的规则）。"""
    mine = ps._entry(_FakeWidget(r"缺失目录: C:\Users\21108\AppData\Local\Temp\x"))
    runner = ps._entry(_FakeWidget(r"缺失目录: C:\Users\RUNNER~1\AppData\Local\Temp\x"))
    assert mine == runner, f"机器路径又原样进基线了：{mine} vs {runner}"
