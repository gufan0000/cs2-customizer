# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""W5 设计决策收口回归（UP-045 / UP-049 / UP-053 / UP-076 / UP-047）。

这批断言里最值钱的是 `test_qss_uses_no_css_only_keywords`——
它守的是本轮最贵的一个坑，详见该用例的文档串。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def main_window(qapp):
    """建一个真窗口量几何。

    ⚠ conftest 把平台钉在 offscreen，那里**一个真实字体都没有**（UP-068）。
    所以本文件的判据只敢量**不依赖字体度量**的量：
      · 内容左边界 → 由布局边距决定；
      · hintLabel 宽度 → 由 QSS 的 max-width 钳住。
    任何"这段文案放不放得下"的结论都不能在这里下，那要走
    `scripts/layout_overflow_audit.py` 的原生平台档。
    """
    from PySide6.QtWidgets import QSystemTrayIcon

    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)

    from config import config
    config.ui_expert_mode = True

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.show()
    qapp.processEvents()
    win.resize(1200, 800)
    qapp.processEvents()
    yield win
    win.close()
    qapp.processEvents()


@pytest.fixture
def main_window_wide(main_window, qapp):
    """同一个窗口拉宽到 2200 —— UP-053 的限宽只在宽屏上才看得出来。"""
    main_window.resize(2200, 800)
    qapp.processEvents()
    yield main_window
    main_window.resize(1200, 800)
    qapp.processEvents()


# ---------------------------------------------------------------- UP-053 的坑

def test_qss_uses_no_css_only_keywords():
    """QSS 里不许出现 Qt 不认、但 Web CSS 认的关键字。

    本轮实际发生的事：给动作条的 hintLabel 写了一句 `max-width: none`
    想解除限宽——那是 Web CSS 的写法，Qt QSS 的 `max-width` 只接受长度值。
    后果**不是**"这一句被忽略"，而是样式解析出错，把
    `special_sound` 的两个页签顶出可视区 46px / 39px。

    最难查的地方在于**因果完全错位**：改的是 pageActionBar 的一条规则，
    炸的是另一个页面的两个页签。我为此先怀疑了限宽值(720)、怀疑了字号档遍历
    顺序、怀疑了主题个数，还一度得出"这是既有缺陷不是我改的"的错误结论——
    因为我的对照组把 720 改成 99999，而那**没有移除属性本身**，等于没做对照。

    教训：排除一个嫌疑，要移除它而不是把它调小。
    """
    from theme_manager import ThemeManager

    # 值必须是长度/百分比/继承，不能是 CSS 的 none/auto/initial/unset
    bad_values = re.compile(
        r"(?<![-\w])(max-width|min-width|max-height|min-height)\s*:\s*"
        r"(none|auto|initial|unset|revert)\s*;", re.I
    )
    tm = ThemeManager()
    offenders = []
    for name, theme in tm.themes.items():
        qss = theme.generate_stylesheet()
        for match in bad_values.finditer(qss):
            offenders.append(f"{name}: {match.group(0).strip()}")
    assert not offenders, (
        "QSS 里出现了 Qt 不认的 CSS 关键字（会导致样式解析出错、"
        "影响面波及无关页面）：" + "; ".join(offenders)
    )


# ---------------------------------------------------------------- UP-053

def test_hint_label_width_is_capped_on_wide_window(qapp, main_window_wide):
    """宽屏下页面正文说明必须被限宽；动作条里的状态位则**不**限宽。

    实测依据：2200px 窗口下 hintLabel 单行原本拉到 1936px（约 242 个中文字），
    远超舒适行长。限的是文字不是内容区——给内容区限宽会让 4 个页面掉列（R7 实测）。
    """
    from PySide6.QtWidgets import QLabel

    from ui_design_system import get_design_system
    from widgets.page_action_bar import PageActionBar

    win = main_window_wide
    cap = get_design_system().container.hint_max_width

    win.show_page("screen_effects", animated=False)
    qapp.processEvents()
    page = win.pages.get("screen_effects")
    assert page is not None

    in_page, in_bar = [], []
    for label in page.findChildren(QLabel):
        if label.objectName() != "hintLabel" or not label.isVisible() or not label.text():
            continue
        parent = label.parentWidget()
        (in_bar if isinstance(parent, PageActionBar) else in_page).append(label)

    assert in_page, "没找到页面正文里的 hintLabel，判据落空了"
    for label in in_page:
        assert label.width() <= cap, (
            f"正文说明宽 {label.width()}px 超过上限 {cap}px：{label.text()[:20]}"
        )

    # 动作条是横向单行状态位，限宽会让它换行、把常驻动作条顶高——必须豁免
    for label in in_bar:
        assert label.maximumWidth() > cap, "动作条里的 hintLabel 不该被限宽"


# ---------------------------------------------------------------- UP-045

def test_all_pages_share_one_content_left_edge(qapp, main_window):
    """切页时内容不该横向跳。

    改前实测：19 页在 216px、about 在 220px、basic 在 233px，极差 17px。
    判据落在**内容左边界的窗口坐标**上，而不是源码里的 setContentsMargins——
    后者全站有 170 多处、大多是嵌套层，数它们说明不了用户看见什么。
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QFrame

    from widgets.settings_card import SettingsCard

    from core.page_traits import DEVICE_OWNING_PAGES

    win = main_window
    unsafe = DEVICE_OWNING_PAGES  # 名单取产品那一份，别在判据里另抄
    edges = {}
    for pid in win._page_names.keys():
        if pid in unsafe:
            continue
        win.show_page(pid, animated=False)
        qapp.processEvents()
        page = win.pages.get(pid)
        if page is None:
            continue
        cards = [c for c in page.findChildren(SettingsCard) if c.isVisible()]
        cards += [f for f in page.findChildren(QFrame)
                  if f.objectName() == "card" and f.isVisible()]
        if not cards:
            continue
        cards.sort(key=lambda w: (w.mapTo(win, QPoint(0, 0)).y(),
                                  w.mapTo(win, QPoint(0, 0)).x()))
        edges[pid] = cards[0].mapTo(win, QPoint(0, 0)).x()

    assert edges, "一个页面都没量到，判据落空了"
    distinct = sorted(set(edges.values()))
    assert len(distinct) == 1, (
        f"内容左边界有 {len(distinct)} 种（{distinct}），切页会横向跳："
        + ", ".join(f"{p}={x}" for p, x in sorted(edges.items()) if x != distinct[0])
    )


# ---------------------------------------------------------------- UP-049

def test_no_colored_emoji_for_states_that_also_use_monochrome():
    """同一语义不要一半彩色 emoji 一半单色符号。

    改前全站只有 2 个字符混用（voice_output_page 相邻两行的 ✅/❌，
    而同类语义其余 9 处都是 ✓/✗）——所以这是 2 行改动，不是设计工程。
    """
    colored = {"✅", "❌", "✔️", "✖️", "☑️"}
    offenders = []
    for path in sorted((ROOT / "pages").glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for char in colored:
            if char in text:
                offenders.append(f"{path.name} 里有 {char}")
    assert not offenders, "状态语义混用了彩色 emoji：" + "; ".join(offenders)


# ---------------------------------------------------------------- UP-047

def test_app_button_module_is_removed():
    """AppButton 实测零引用且与 style_as_* 职责重叠，已删。"""
    assert not (ROOT / "widgets" / "app_button.py").exists()
    with pytest.raises(ImportError):
        from widgets import AppButton  # noqa: F401


def test_ghost_button_style_still_has_a_producer():
    """删 AppButton 不能让 #ghostButton 变成没有生产者的死样式。

    R8a 为 UP-073 补了整块 #ghostButton QSS，`ui_contrast_audit` 也有两条
    判据挂在它上面。如果全站再没有任何代码产出这个 objectName，
    那些判据会继续报绿——但守的是一条永远不会被命中的规则。
    """
    from PySide6.QtWidgets import QPushButton

    from page_theme_helper import style_as_ghost_button

    button = QPushButton("更多")
    style_as_ghost_button(button)
    assert button.objectName() == "ghostButton"
