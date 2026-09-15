# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-639（视觉回调 · 第一步）：装饰性动效有一个总开关，默认关，关了就一样都不装。

## 它守的是什么

水波纹、流光、输入框焦点下划线、滑块数值气泡、卡片改值闪边 —— 五样都是 2026-04-19
一起入库的，各自一个时长、各自一条曲线。用户 2026-09-15 在真机上的原话是「动画都很奇怪」。
修法不是删（用户可能想要回来），是一个开关：`ui_motion.DEFAULT_ENABLED`，
config 里 `ui_decorative_motion` 可覆盖。

## 怎么验

不建主窗口。给每个安装函数一个裸控件，问它有没有往控件上挂东西：
挂了 ⇒ 开关没管住这一处。⚠ 五处要**逐个**问，「开关关了」和「每个入口都问了开关」
不是一回事 —— 调用点有 8 处，漏一处在屏幕上和没关分不开。
"""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLineEdit, QPushButton, QSlider, QSpinBox, QWidget

import ui_motion


def _installed_effects(widget: QWidget) -> list[str]:
    """控件上挂着的装饰性子控件类名（按类名认，不 import 那些模块以免循环）。"""
    names = {"RippleEffect", "ShimmerEffect", "FocusUnderline"}
    return sorted(type(c).__name__ for c in widget.findChildren(QWidget) if type(c).__name__ in names)


def test_the_default_is_off(monkeypatch):
    # config 没有覆盖键时听默认值；默认值必须是关
    from config import config
    monkeypatch.setattr(config, ui_motion.CONFIG_KEY, None, raising=False)
    assert ui_motion.DEFAULT_ENABLED is False
    assert ui_motion.decorative_motion_enabled() is False


def test_nothing_decorative_gets_installed_when_the_switch_is_off(monkeypatch):
    from config import config
    monkeypatch.setattr(config, ui_motion.CONFIG_KEY, None, raising=False)
    monkeypatch.setattr(ui_motion, "DEFAULT_ENABLED", ui_motion.DEFAULT_ENABLED)  # 断点会翻这一行

    from ui_focus_underline import install_focus_underline
    from ui_ripple_effect import add_ripple_effect
    from ui_shimmer import add_shimmer_effect, add_shimmer_on_hover
    from ui_slider_bubble import install_slider_bubble

    btn = QPushButton("x")
    assert add_ripple_effect(btn) is None
    assert add_shimmer_effect(btn) is None
    assert add_shimmer_on_hover(btn) is None
    assert _installed_effects(btn) == []

    edit, spin = QLineEdit(), QSpinBox()
    install_focus_underline(edit)
    install_focus_underline(spin)
    assert _installed_effects(edit) == [] and _installed_effects(spin) == []
    assert not hasattr(edit, "_focus_underline_installed")

    slider = QSlider()
    install_slider_bubble(slider)
    assert not hasattr(slider, "_bubble_installed")
    assert not hasattr(slider, "_value_bubble")


def test_the_card_border_flash_does_nothing_when_off(monkeypatch):
    from config import config
    monkeypatch.setattr(config, ui_motion.CONFIG_KEY, None, raising=False)
    import gui_widget

    card = QFrame()
    card.setObjectName("card")
    child = QWidget(card)
    # 开关关着时函数在碰 self 之前就返回 —— 所以 self 给 None 也不该炸
    gui_widget.MainWindow._flash_card_border(None, child)
    assert not hasattr(card, "_flash_overlay")


def test_it_is_a_switch_not_a_deletion(monkeypatch):
    """config 里打开 ⇒ 水波纹照常装上。这条防的是「把开关做成了删除」。"""
    from config import config
    monkeypatch.setattr(config, ui_motion.CONFIG_KEY, True, raising=False)
    assert ui_motion.decorative_motion_enabled() is True
    from ui_ripple_effect import add_ripple_effect
    btn = QPushButton("x")
    assert add_ripple_effect(btn) is not None
    assert _installed_effects(btn) == ["RippleEffect"]
