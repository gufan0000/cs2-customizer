# -*- coding: utf-8 -*-
"""R7 · 设计系统收敛回归（D-01/D-02/D-03/D-06 + 禁用态补漏）。

源码级断言走 AST；能实建控件的一律实建——R7 已经证明过一次：
「重置所有设置」的 setObjectName 被后面一行覆盖回去了，只读源码看不出来。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _strip_qss_comments(qss: str) -> str:
    """剥掉 QSS 里的 /* ... */ 注释再做文本断言。

    本专项已经栽过四次「断言命中自己写的注释」：
    R3 文本匹配、R4 子串匹配、R5 body.find()、R7 这次是**注释被生成进了 QSS**
    （theme_manager 的模板注释会原样进入 generate_stylesheet 的产物）。
    规律：只要断言对象是"文本里有没有某个字样"，就必须先把注释剥干净。
    """
    import re

    return re.sub(r"/\*.*?\*/", "", qss, flags=re.S)


def _themes():
    from theme_manager import get_theme_manager
    return [(n, t) for n, t in get_theme_manager().themes.items() if n != "minimal"]


def _theme_ids():
    return [n for n, _ in _themes()]


# ---------------------------------------------------- D-01 阴影降配


def test_shadow_downgraded():
    from ui_design_system import get_design_system

    e = get_design_system().elevation
    assert e.md_blur <= 16, f"卡片阴影 blur 是 {e.md_blur}，D-01 要求降到 16"
    assert e.md_alpha <= 90, f"卡片阴影 alpha 是 {e.md_alpha}，D-01 要求降到 90"


def test_card_hover_animation_removed():
    """hover blur 动画必须整段删掉，不能改成"瞬时切换"。

    Qt 的 Enter/Leave 按 underMouse 判定，鼠标扫过卡内任何子控件都会走一轮
    Leave→Enter；瞬时切 blur 只会变成跳变闪烁，而且照样要整卡重新软件模糊。
    """
    tree = ast.parse((ROOT / "widgets/settings_card.py").read_text(encoding="utf-8"))
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "enterEvent" not in names, "hover 阴影处理又回来了"
    assert "leaveEvent" not in names
    assert "_animate_shadow_blur" not in names
    # 阴影本身必须还在（层级感是蓝图要的）
    assert "_apply_elevation" in names


# ---------------------------------------------------- D-02 卡片标题


def test_card_title_token_exists_and_beats_body():
    from ui_design_system import get_design_system

    f = get_design_system().font_size
    assert hasattr(f, "card_title"), "缺 font.card_title token"
    assert f.card_title > f.md, (
        f"卡片标题 {f.card_title}px 不比正文 {f.md}px 大 —— 阶梯还是塌的"
    )


def test_settings_card_title_uses_card_title_selector(qapp):
    from widgets.settings_card import SettingsCard

    card = SettingsCard("测试标题")
    assert card.title_label.objectName() == "cardTitle"
    card.deleteLater()


@pytest.mark.parametrize("name", _theme_ids())
def test_card_title_qss_consumes_token(name):
    from ui_design_system import get_design_system

    theme = dict(_themes())[name]
    qss = theme.generate_stylesheet()
    size = get_design_system().font_size.card_title
    block = _strip_qss_comments(qss).split("QLabel#cardTitle {")[1].split("}")[0]
    assert f"font-size: {size}px" in block


# ---------------------------------------------------- D-03 语义色条


@pytest.mark.parametrize("name", _theme_ids())
def test_only_warn_and_danger_have_semantic_bars(name):
    """常态四个语义不再画色条——全仓 78 处调用只有 1 处传过 semantic，
    等于每张卡都挂同一根紫条，它没在区分任何东西。"""
    theme = dict(_themes())[name]
    qss = _strip_qss_comments(theme.generate_stylesheet())
    for gone in ("config", "info", "status", "neutral"):
        assert f'QFrame#card[semantic="{gone}"]' not in qss, f"{gone} 色条应当已删除"
    for kept in ("warning", "danger"):
        assert f'QFrame#card[semantic="{kept}"]' in qss, f"{kept} 色条必须保留"


@pytest.mark.parametrize("name", _theme_ids())
def test_card_base_border_left_is_not_transparent(name):
    """基础规则的左边框绝不能留 transparent。

    Qt 画圆角边框是描边(pen 居中)，透明描边会露出约 1.5px 的页面底色——
    28 页每张卡的左缘都会出现一道缝。
    """
    theme = dict(_themes())[name]
    qss = theme.generate_stylesheet()
    block = _strip_qss_comments(qss).split("QFrame#card {")[1].split("}")[0]
    assert "border-left" in block
    assert "transparent" not in block, "左边框仍是 transparent，卡片左缘会露底色缝"


@pytest.mark.parametrize("name", _theme_ids())
def test_semantic_bars_come_after_search_highlight(name):
    """warn/danger 必须排在 [searchHit] 之后。

    三者特异度完全相同（1 id + 1 属性 + 1 类型），QSS 同特异度后来者胜。
    排前面的话，搜索命中那 1.6 秒里 border-color 简写会把橙/红条刷成品牌紫。
    """
    theme = dict(_themes())[name]
    qss = _strip_qss_comments(theme.generate_stylesheet())
    hit = qss.index('QFrame#card[searchHit="fade"]')
    warn = qss.index('QFrame#card[semantic="warning"]')
    danger = qss.index('QFrame#card[semantic="danger"]')
    assert warn > hit and danger > hit, "语义色条排在了搜索高亮之前，会被高亮盖掉"


def test_semantic_values_all_still_valid():
    """六个语义值全部保留——它同时是 icon_role 推导表的 key，
    删值会让历史调用点直接抛 ValueError。"""
    from widgets.settings_card import SettingsCard

    assert set(SettingsCard.VALID_SEMANTICS) >= {
        "config", "info", "status", "warning", "danger", "neutral"}


# ---------------------------------------------------- 禁用态补漏


@pytest.mark.parametrize("name", _theme_ids())
def test_disabled_text_is_readable_on_disabled_background(name):
    """R4 只查了「禁用色和常态色能否分辨」，没查「禁用文字在**禁用底**上能否看清」。

    禁用底是 bg_tertiary 以 90/255 叠在卡片上；实测 8/8 主题原本只有
    1.64~2.33:1 —— 文字等于消失了。WCAG 豁免禁用控件，不等于允许它隐身。
    """
    from core.utils.contrast import contrast_ratio

    theme = dict(_themes())[name]
    c = theme.colors
    bg = theme._blend_hex(c.bg_tertiary, 90, c.bg_card)
    ratio = contrast_ratio(c.text_on_disabled, bg)
    assert ratio >= 3.0, f"{name} 禁用态文字仅 {ratio:.2f}:1，看不清"


@pytest.mark.parametrize("name", _theme_ids())
def test_danger_button_has_disabled_rule(name):
    """`#dangerButton` 是 id 选择器，特异度压过通用的 `QPushButton:disabled`。

    不显式写这条，禁用的危险按钮会保持满红、和可点的一模一样——
    红色说「点了会毁数据」，禁用说「你点不了」，同时出现是自相矛盾。
    """
    theme = dict(_themes())[name]
    qss = theme.generate_stylesheet()
    assert "QPushButton#dangerButton:disabled" in qss


# ---------------------------------------------------- D-06 危险按钮落地


DANGER_SITES = [
    ("pages/music_page.py", 3),          # 删除歌单 / 删除选中 / 清空列表
    ("pages/advanced_page.py", 1),       # 重置所有设置
    ("pages/preset_center_page.py", 1),  # 删除该图预设
    ("pages/voice_output_page.py", 1),   # 删除音板槽位
    ("dialogs/style_manager_dialog.py", 1),
]


@pytest.mark.parametrize("rel,count", DANGER_SITES)
def test_danger_button_landed(rel, count):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    hits = [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "style_as_danger_button"]
    assert len(hits) == count, f"{rel} 期望 {count} 处危险按钮，实际 {len(hits)}"


def test_reset_all_settings_is_actually_red(qapp):
    """实建控件验证，不看源码。

    R7 踩过：`style_as_danger_button(reset_button)` 写上去了，但后面还有一行
    `style_as_secondary_button(reset_button)` 把 objectName 又改了回去——
    两者都是 setObjectName，谁在后面谁说了算。源码级断言看不出这个。
    """
    from pages.advanced_page import AdvancedPage
    from PySide6.QtWidgets import QPushButton, QWidget

    page = AdvancedPage()
    qapp.processEvents()
    reds = [b.text() for b in page.findChildren(QWidget)
            if isinstance(b, QPushButton) and b.objectName() == "dangerButton"]
    assert "重置所有设置" in reds, f"全站最不可逆的按钮不是红的；当前红按钮={reds}"
    page.deleteLater()
    page.setParent(None)


def test_red_buttons_stay_scarce(qapp):
    """红色语义要稀缺才有效——到处都是红的等于没有红的。"""
    import importlib

    from PySide6.QtWidgets import QPushButton, QWidget

    from ui_style_applier import apply_unified_styles

    total_red = total_btn = 0
    for mod, cls in (("pages.advanced_page", "AdvancedPage"),
                     ("pages.crosshair_page", "CrosshairPage"),
                     ("pages.kill_sound_page", "KillSoundPage")):
        page = getattr(importlib.import_module(mod), cls)()
        apply_unified_styles(page)
        qapp.processEvents()
        btns = [b for b in page.findChildren(QWidget) if isinstance(b, QPushButton)]
        total_btn += len(btns)
        total_red += sum(1 for b in btns if b.objectName() == "dangerButton")
        page.deleteLater()
        page.setParent(None)
    assert total_btn > 0
    assert total_red / total_btn < 0.12, (
        f"{total_red}/{total_btn} 的按钮是红的，红色语义被稀释了"
    )


# ---------------------------------------------------- D-08 导航选中图标


def test_nav_selected_icon_role_improves_contrast():
    """选中态图标不能用 accent_primary —— 那是**倒退**。

    实测在 navButton:checked 的底(bg_tertiary)上：
      accent_primary → dark 2.88 / warm 2.28 / light 2.94 / rose 2.99
      text_primary   → 8 主题全部 9.45~15.91
    四个主题下 accent 比现状的 secondary(5.9~7.1) 还差，等于把选中项弄得更看不清。
    """
    from core.utils.contrast import contrast_ratio
    from widgets.icon_provider import (NAV_ICON_ROLE_NORMAL, NAV_ICON_ROLE_SELECTED,
                                       _ROLE_TO_COLOR_FIELD)

    assert NAV_ICON_ROLE_SELECTED != NAV_ICON_ROLE_NORMAL, "选中态得和未选中态不同色"
    sel_field = _ROLE_TO_COLOR_FIELD[NAV_ICON_ROLE_SELECTED]
    nor_field = _ROLE_TO_COLOR_FIELD[NAV_ICON_ROLE_NORMAL]
    for name, theme in _themes():
        c = theme.colors
        bg = c.bg_tertiary
        sel = contrast_ratio(getattr(c, sel_field), bg)
        nor = contrast_ratio(getattr(c, nor_field), bg)
        assert sel >= nor, (
            f"{name} 选中态图标 {sel:.2f}:1 比未选中态 {nor:.2f}:1 还差 —— 这是倒退"
        )
        assert sel >= 4.5, f"{name} 选中态图标仅 {sel:.2f}:1"


def test_apply_nav_icon_is_idempotent(qapp):
    """切页会把 20+ 个导航按钮走一遍，不记账就是每次切页重渲染一轮图标。"""
    from PySide6.QtWidgets import QPushButton

    from widgets.icon_provider import apply_nav_icon

    btn = QPushButton("x")
    apply_nav_icon(btn, "basic", True)
    assert btn.property("fp_nav_icon_role") == "primary"
    apply_nav_icon(btn, "basic", True)   # 第二次应当直接 return
    assert btn.property("fp_nav_icon_role") == "primary"
    apply_nav_icon(btn, "basic", False)
    assert btn.property("fp_nav_icon_role") == "secondary"
    btn.deleteLater()


def test_nav_icon_refresh_covers_three_paths():
    """切页 / 切页被守卫拦下回滚 / 换主题，三条路都要刷图标。"""
    import ast as _ast

    src = (ROOT / "gui_widget.py").read_text(encoding="utf-8")
    tree = _ast.parse(src)
    callers = set()
    for fn in _ast.walk(tree):
        if not isinstance(fn, _ast.FunctionDef):
            continue
        for n in _ast.walk(fn):
            if (isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
                    and n.func.attr == "_refresh_nav_icons"):
                callers.add(fn.name)
    for path in ("show_page", "_sync_nav_selection_to_current_page", "_on_theme_changed"):
        assert path in callers, f"{path} 没有刷新导航图标"
