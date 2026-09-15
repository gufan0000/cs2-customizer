# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-640（视觉回调 · 第二步）：控件的**静止边**要软，hover / focus 边照旧要响。

## 它守的是什么

RN-545 把每个控件的静态边框抬到 WCAG 1.4.11 的 3:1，深色主题上 28 页每个下拉框、
每颗次级按钮、每个输入框都成了一根亮线。用户 2026-09-15 在真机上的原话：
「主要让我觉得难受的就是这些密密麻麻的边框」。

修法不是把 border_primary 调暗（那会把 hover 边一起调暗），是**分家**：
静止态走 `border_control`（`Theme.resting_border()` 唯一推导），hover 仍走 border_primary、
focus 仍走 border_focus。⭐ 放弃的只是静止态的 3:1，且是明知在射程内而放弃 ——
理由写在 `scripts/ui_contrast_audit.py::EXEMPT_CONTROL_REASON`，数字照量照印。

## 怎么验

对每个主题生成样式表，拿 QComboBox / 次级按钮 / 输入框三条**静止**规则里的边框色
和 `Theme.resting_border()` 对，再量它和 hover 边在卡片底上的对比度：静止边必须更软。
focus 规则仍要用 border_focus，且 border_focus 在每个主题上 ≥3:1（这一条不放）。
高对比主题是给低视力用户的，它显式把静止边钉回 border_primary，判据对它另有一格。
"""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load_audit():
    spec = importlib.util.spec_from_file_location(
        "ui_contrast_audit", REPO / "scripts" / "ui_contrast_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def audit():
    return _load_audit()


@pytest.fixture(scope="module")
def themes():
    from theme_manager import get_theme_manager
    return get_theme_manager().themes


def _rule_body(qss: str, selector: str) -> str:
    """选择器**完全匹配**那条规则的花括号内容（不含 :hover / :focus 变体）。"""
    pat = re.compile(r"(?m)^\s*" + re.escape(selector) + r"\s*\{(.*?)\}", re.S)
    m = pat.search(qss)
    assert m, f"样式表里找不到规则 {selector!r}"
    return m.group(1)


def _border_color(body: str) -> str:
    m = re.search(r"border:\s*\d+px\s+solid\s+(#[0-9a-fA-F]{6})", body)
    assert m, f"规则里没有 `border: Npx solid #rrggbb`：\n{body[:300]}"
    return m.group(1).lower()


RESTING_SELECTORS = ("QComboBox", "QPushButton#secondaryButton", "QLineEdit, QSpinBox, QDoubleSpinBox")


def test_the_resting_border_is_softer_than_the_hover_border_in_every_theme(themes, audit):
    from theme_manager import Theme
    softer = 0
    for name, theme in themes.items():
        if name in audit.SKIP_THEMES:
            continue
        c = theme.colors
        qss = theme.generate_stylesheet()
        resting = Theme.resting_border(c).lower()
        for sel in RESTING_SELECTORS:
            assert _border_color(_rule_body(qss, sel)) == resting, f"[{name}] {sel} 的静止边不是 border_control"
        r_rest = audit.worst_contrast(resting, (c.bg_card,))
        r_hover = audit.worst_contrast(c.border_primary, (c.bg_card,))
        if c.border_control and c.border_control.lower() == c.border_primary.lower():
            continue     # 高对比主题：显式钉回亮边，见 test_the_high_contrast_theme_keeps_its_hard_edges
        assert r_rest < r_hover, f"[{name}] 静止边 {resting}（{r_rest:.2f}:1）没有比 hover 边（{r_hover:.2f}:1）软"
        softer += 1
    assert softer >= 5, f"只有 {softer} 个主题做了分家 —— 分母不对"


def test_focus_still_uses_the_loud_border_in_every_theme(themes, audit):
    for name, theme in themes.items():
        if name in audit.SKIP_THEMES:
            continue
        c = theme.colors
        qss = theme.generate_stylesheet()
        for sel in ("QComboBox:focus", "QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus"):
            assert _border_color(_rule_body(qss, sel)) == c.border_focus.lower(), f"[{name}] {sel} 不再走 border_focus"
        ratio = audit.worst_contrast(c.border_focus, (c.bg_primary, c.bg_secondary, c.bg_card))
        assert ratio >= audit.NONTEXT_THRESHOLD, f"[{name}] border_focus 只有 {ratio:.2f}:1 —— 焦点边不许软"


def test_the_high_contrast_theme_keeps_its_hard_edges(themes):
    c = themes["contrast"].colors
    assert c.border_control and c.border_control.lower() == c.border_primary.lower(), \
        "高对比主题是给低视力用户的，静止边必须显式钉回 border_primary"


def test_the_audit_measures_the_resting_border_but_does_not_fail_on_it(audit):
    rows, fresh, _ = audit.audit_nontext()
    measured = [r for r in rows if audit.EXEMPT_CONTROL_TOKEN in r[1]]
    assert len(measured) >= 5, "静止边这一档没被量到 —— 豁免不等于不量"
    assert not [r for r in fresh if audit.EXEMPT_CONTROL_TOKEN in r[1]], "豁免档进了违规名单"
    assert "用户裁定" in audit.EXEMPT_CONTROL_REASON


def test_nav_buttons_do_not_keep_a_focus_ring_after_a_mouse_click():
    """导航按钮只在 Tab 上去时有焦点环（RN-546 要的是键盘可见，不是鼠标残留）。
    按源码验：每处 `setObjectName("navButton")` / `"navGroupHeader"` 之后紧跟 TabFocus。"""
    src = (REPO / "gui_widget.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    named, tab = {}, {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        recv = ast.unparse(node.func.value)
        if node.func.attr == "setObjectName" and node.args and isinstance(node.args[0], ast.Constant) \
                and node.args[0].value in ("navButton", "navGroupHeader"):
            named.setdefault(recv, []).append(node.lineno)
        if node.func.attr == "setFocusPolicy" and node.args and ast.unparse(node.args[0]).endswith("TabFocus"):
            tab.setdefault(recv, []).append(node.lineno)
    assert named, "没找到导航按钮的创建处 —— 判据分母为空"
    for recv, lines in named.items():
        for ln in lines:
            assert any(ln < t <= ln + 12 for t in tab.get(recv, [])), \
                f"{recv} 在第 {ln} 行被命名为导航按钮，之后 12 行内没有 setFocusPolicy(Qt.TabFocus)"
