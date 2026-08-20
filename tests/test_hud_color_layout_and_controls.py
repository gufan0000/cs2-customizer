# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""hud_color 页 B 堆四条的判据（RN-126~129，2026-08-20 用户裁定）。

四条都落在**行为与结构**上，不落在"源码里有没有那一行"。
几何在测试环境里不可信（offscreen 无字体），所以版面那条判**相对顺序**，
"到底有没有落进首屏"由两档像素基线兜底 —— 与 crosshair 那一轮同一套办法。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QLayout, QMessageBox, QScrollArea, QWidget,
)

from config import config
import pages.hud_color_page as page_module


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch):
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0), raising=False)


@pytest.fixture
def page(qapp, monkeypatch):
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    p = page_module.HudColorPage()
    p.setAttribute(Qt.WA_DontShowOnScreen, True)
    yield p
    p.deleteLater()
    qapp.processEvents()


def _card_title(w: QWidget) -> str:
    if not isinstance(w, QFrame) or w.objectName() not in ("card", "settingsCard"):
        return ""
    for lb in w.findChildren(QLabel):
        if lb.objectName() in ("cardTitle", "settingsCardTitle") and lb.text().strip():
            return lb.text().strip()
    return ""


def _titles_in_layout_order(root: QWidget) -> list[str]:
    """按版面从上到下的顺序列出卡片标题。

    ⚠ 滚动区的内容**不在布局树里**（`setWidget` 不是 `addWidget`），
    这一层不下钻的话整页扫出来是空的 —— 而空列表会让顺序判据永远绿。
    """
    titles: list[str] = []

    def descend(w: QWidget):
        if isinstance(w, QScrollArea) and w.widget() is not None:
            inner = w.widget()
            t = _card_title(inner)
            if t:
                titles.append(t)
            if inner.layout() is not None:
                walk(inner.layout())
        elif w.layout() is not None:
            walk(w.layout())

    def walk(layout: QLayout):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget()
            if w is not None:
                t = _card_title(w)
                if t:
                    titles.append(t)
                descend(w)
            elif item.layout() is not None:
                walk(item.layout())

    if root.layout() is not None:
        walk(root.layout())
    return titles


# ------------------------------------------------------------------- RN-126


def test_the_event_rules_come_before_the_number_keys(page):
    """⭐ RN-126：**这一页的核心是"局内事件变色"，它得排在数字键前面。**

    改之前实测：完整档视口折线 725，「事件响应」卡从 y=717 起 —— **只露 8px**；
    紧凑档折线 565、卡在 833，**完全在首屏之外**。而首屏被 9 个数字键（265px）占满。
    外审两档 3/3 都在说「首屏全被数字键占满，核心功能主次颠倒」。
    """
    titles = _titles_in_layout_order(page)
    assert "事件响应" in titles and "数字键颜色映射" in titles, titles
    assert titles.index("事件响应") < titles.index("数字键颜色映射"), (
        f"核心的「事件响应」又排到数字键后面去了：{titles}")


def test_every_card_is_still_there(page):
    """空转守卫：上面那条只管顺序，删掉一张卡它照样绿。"""
    titles = _titles_in_layout_order(page)
    for name in ("预设工作台", "数字键颜色映射", "事件响应"):
        assert name in titles, f"「{name}」卡片不见了：{titles}"


# ------------------------------------------------------------------- RN-127


def test_colour_choices_show_the_colour(page):
    """RN-127：颜色下拉必须**显示颜色**，不能只给「默认 (0)」这种代号。

    色号对应的十六进制本来就在 `core.hud.rule_model.HUD_COLORS` 里
    （`0: ("默认", "#4A90D9")` …），这条改动一个新数据都不需要。
    """
    combo = page.default_color_combo
    with_icon = 0
    for i in range(combo.count()):
        if not combo.itemIcon(i).isNull():
            with_icon += 1
    assert with_icon >= combo.count() - 1, (
        f"{combo.count()} 个颜色选项里只有 {with_icon} 个带色块 —— "
        "一个挑颜色的下拉框不显示颜色")


def test_the_swatches_use_the_real_palette(page):
    """空转守卫：色块得是**那个颜色**，不能是随便一个占位图标。"""
    from core.hud.rule_model import HUD_COLORS
    from PySide6.QtGui import QColor

    combo = page.default_color_combo
    checked = 0
    for i in range(combo.count()):
        value = combo.itemData(i)
        if value not in HUD_COLORS:
            continue
        icon = combo.itemIcon(i)
        assert not icon.isNull(), f"色号 {value} 没有色块"
        img = icon.pixmap(16, 16).toImage()
        got = QColor(img.pixel(8, 8)).name().lower()
        want = HUD_COLORS[value][1].lower()
        assert got == want, f"色号 {value} 的色块是 {got}，而调色板里写的是 {want}"
        checked += 1
    assert checked >= 5, f"只验到 {checked} 个色块，这条守卫没起作用"


# ------------------------------------------------------------------- RN-128


def test_a_number_key_has_exactly_one_switch(page):
    """RN-128：开关只由复选框管，下拉里不许再有一个「不启用」。

    两套开关重叠时，玩家不知道该点哪个，而两者不一致时的行为没人定义过。
    """
    for key, widgets in page.key_widgets.items():
        combo = widgets["color"]
        texts = [combo.itemText(i) for i in range(combo.count())]
        assert "不启用" not in texts, (
            f"数字键 {key} 的颜色下拉里还留着「不启用」——"
            f"它和旁边的复选框是两套开关：{texts}")


def test_the_colour_combo_is_disabled_until_the_key_is_enabled(page, qapp):
    """去掉「不启用」之后，未勾选的键要把下拉置灰 —— 否则看不出它不生效。"""
    key = next(iter(page.key_widgets))
    widgets = page.key_widgets[key]
    widgets["enabled"].setChecked(False)
    qapp.processEvents()
    assert not widgets["color"].isEnabled(), (
        f"数字键 {key} 没启用，颜色下拉却是可点的 —— 改了也不生效，没有任何提示")
    widgets["enabled"].setChecked(True)
    qapp.processEvents()
    assert widgets["color"].isEnabled()


# ------------------------------------------------------------------- RN-129


def test_applying_a_preset_does_not_claim_it_took_effect(page, monkeypatch):
    """RN-129：「应用预设」只填表单，**不许**弹一个像"已经生效了"的确认框。

    改之前它弹「预设已应用 / 预设效果已加载，点击保存后生效。」——
    一个模态确认框在玩家眼里就是"这一步完成了"，而真正写进游戏的是底栏那个保存。
    外审两档 4 发都在问「应用预设之后到底还要不要点保存」。
    """
    shown: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a) or 0))
    page._apply_preset()
    assert not shown, (
        "「应用预设」还在弹模态确认框 —— 它看起来就是「已经生效了」")


def test_applying_a_preset_marks_the_page_dirty(page):
    """反面守卫：不弹框可以，但**必须**留下"还没保存"这个状态。"""
    page._set_dirty(False)
    page._apply_preset()
    assert page._dirty, "应用了预设却不算未保存修改 —— 用户切页时不会被拦"
