# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-642（批 96 第二刀）：滑块本体不许被涂色；一句提示不许有自己的底色。

## 它守的是什么

用户 2026-09-15 实机指着枪声页说「滑块组件奇怪的背景色」。隔离实验（`H:/tmp/v2_probe_slider3.py`）：
一根裸 QSlider 在深色样式表下，**常态 / masterOff / disabled 三态角点全是 #404252**（text_disabled）。
根因是 QSS 伪状态写在了子控件**前面**：`QSlider:disabled::handle:horizontal {{ background: text_disabled }}`
—— Qt 把它当成 **QSlider 本体**的规则且不看状态，于是每一根滑块整个矩形被涂成禁用文字色。
修法只是把伪状态挪到子控件后面（`::handle:horizontal:disabled`）。

同一批顺手：`#masterOffNotice` 那句话去掉自己的灰底和左侧色条（用户指着那块灰底说「奇怪」）。

## 怎么验

**看像素**，不看文本：一根裸滑块在深色样式表下渲染出来，本体角点必须是透明（parent 透出），
禁用态的把手才是 text_disabled。⚠ 第一版如果只查样式表文本，`:disabled::handle` 这种写法
在文本上完全合法，只有渲染出来才分得开 —— 和「一句描述和它描述的那件事长得一模一样」同族。
"""
from __future__ import annotations

import re

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QSlider, QVBoxLayout


@pytest.fixture(scope="module")
def dark():
    from theme_manager import get_theme_manager
    return get_theme_manager().themes["dark"]


def _render(dark, *, disabled: bool):
    app = QApplication.instance()
    host = QFrame()
    host.setObjectName("card")
    host.setStyleSheet(dark.generate_stylesheet())
    lay = QVBoxLayout(host)
    s = QSlider(Qt.Horizontal)
    s.setObjectName("slider")
    s.setRange(0, 100)
    s.setValue(18)
    s.setEnabled(not disabled)
    lay.addWidget(s)
    host.resize(400, 60)
    host.setAttribute(Qt.WA_DontShowOnScreen, True)
    host.show()
    app.processEvents()
    img = s.grab().toImage()
    size = (s.width(), s.height())
    host.close()
    return size, img


def test_an_enabled_slider_does_not_paint_its_own_body(dark):
    (w, h), img = _render(dark, disabled=False)
    corner = img.pixelColor(10, 1)
    assert corner.alpha() == 0 or corner.name() != dark.colors.text_disabled.lower(), \
        f"启用态滑块的本体角点被涂成了 {corner.name()}（text_disabled={dark.colors.text_disabled}）"
    groove = img.pixelColor(300, h // 2).name()
    assert groove != dark.colors.text_disabled.lower()


def test_the_disabled_look_still_lands_on_the_handle_not_the_body(dark):
    (w, h), img = _render(dark, disabled=True)
    corner = img.pixelColor(10, 1)
    assert corner.alpha() == 0 or corner.name() != dark.colors.text_disabled.lower(), "禁用态也不许涂本体"
    # 把手在 18% 处，中心那一点应是 text_disabled
    handle_x = int(w * 0.18)
    assert img.pixelColor(handle_x, h // 2).name() == dark.colors.text_disabled.lower(), \
        "禁用态的把手不再是 text_disabled —— 伪状态挪位之后规则应该落在把手上，不是消失"


def test_the_pseudo_state_follows_the_subcontrol(dark):
    """文本守卫：`QSlider:disabled::` 这种写法不许再出现（它在文本上合法、在渲染上是另一条规则）。"""
    qss = dark.generate_stylesheet()
    bad = re.findall(r"^\s*(Q\w+:disabled::[\w-]+[^{]*)\{", qss, re.M)
    assert not bad, f"伪状态写在子控件前面：{bad[:3]}"


def test_the_master_off_notice_has_no_background_of_its_own(dark):
    qss = re.sub(r"/\*.*?\*/", "", dark.generate_stylesheet(), flags=re.S)
    m = re.search(r"(?m)^\s*QLabel#masterOffNotice\s*\{([^}]*)\}", qss)
    assert m, "找不到 #masterOffNotice 的规则"
    body = " ".join(m.group(1).split())
    assert "background-color: transparent" in body, body
    assert "border-left" not in body, body
