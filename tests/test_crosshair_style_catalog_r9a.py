# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R9-A（UP-086）：`t_shape` 补进 UI 当第五个样式。

本文件盯三件事，每一件都对应一种「不报错的错」：

1. **目录漂移**——渲染器认得的样式集，与准心页给用户看的中文名表，必须逐项一致。
   漏一边的后果不是崩溃，是「单选按钮点得中、准心画不出来」或者反过来
   「渲染器支持但用户永远选不到」（`t_shape` 自己就在第二种状态里躺了很久）。
2. **几何画错**——T 型的竖杆**只有下半条**。如果谁把它实现成完整十字，
   像素还是有的、测试还是绿的，只有肉眼能看出不对。所以这里验的是
   「中心线以上没有像素」这个 T 之所以为 T 的性质。
3. **预览与实物不一致**——准心页的预览是另一套独立绘制代码。加样式时忘了改它，
   表现是「预览空白但屏幕上有准心」。用 AST 核对预览分支覆盖了全部样式。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtGui import QImage, QPainter

from crosshair_overlay import USER_STYLES, CrosshairFrame, paint_crosshair
from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent
CANVAS = 100
CENTER = CANVAS // 2


def _render(frame) -> QImage:
    img = QImage(CANVAS, CANVAS, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    painter = QPainter(img)
    paint_crosshair(painter, frame)
    painter.end()
    return img


def _opaque_rows(img: QImage) -> dict[int, int]:
    """每一行有多少个不透明像素。"""
    out = {}
    for y in range(img.height()):
        n = sum(1 for x in range(img.width()) if img.pixelColor(x, y).alpha() > 0)
        if n:
            out[y] = n
    return out


# ==================================================== 1. 目录不许漂移


def test_ui_labels_cover_exactly_the_renderer_styles():
    """准心页的中文名表 ⟺ 渲染器的 USER_STYLES，两边键集与顺序都要一致。

    顺序也管，因为这份表同时决定单选按钮从左到右的排布。
    """
    from pages.crosshair_page import CROSSHAIR_STYLE_LABELS

    assert tuple(CROSSHAIR_STYLE_LABELS) == tuple(USER_STYLES)


def test_default_style_is_a_real_style():
    """`DEFAULT_STYLE` 兼作「样式值不认识时显示什么」的兜底，它自己必须是合法值。"""
    from pages.crosshair_page import CROSSHAIR_STYLE_LABELS, DEFAULT_STYLE

    assert DEFAULT_STYLE in CROSSHAIR_STYLE_LABELS
    assert DEFAULT_STYLE in USER_STYLES


def test_style_labels_are_spelled_out_only_once_in_the_page():
    """防回潮：R9-A 之前这份表在同一个文件里抄了三遍。

    判据是「文件里不再出现第二份含中文样式名的字面量字典」——
    具体做法是数 `"十字"` 这个字符串常量出现几次，多于一次说明又抄了一份。
    """
    src = (REPO / "pages" / "crosshair_page.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    hits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == "十字"
    ]
    assert len(hits) == 1, f"「十字」作为字面量出现了 {len(hits)} 次，样式名表又被抄了一份"


# ==================================================== 2. T 之所以为 T


def test_t_shape_has_no_pixels_above_the_center_line():
    """T 型的竖杆只向下。中心线以上必须是空的——这是它区别于十字的唯一性质。

    回退验证：把 `_paint_t_shape` 的竖杆改成上下各半（即画成十字），这条立刻变红。
    """
    img = _render(CrosshairFrame(style="t_shape", size=40, thickness=2))
    rows = _opaque_rows(img)
    above = {y: n for y, n in rows.items() if y < CENTER - 3}
    below = {y: n for y, n in rows.items() if y > CENTER + 3}

    assert not above, f"中心线以上不该有像素，实际有 {above}"
    assert below, "竖杆应当向下延伸，实际下半部分没有像素"


def test_t_shape_horizontal_bar_spans_the_full_width():
    """横杆是整条（左右各 half），不是半条。"""
    size = 40
    img = _render(CrosshairFrame(style="t_shape", size=size, thickness=1))
    xs = [x for x in range(CANVAS) if img.pixelColor(x, CENTER).alpha() > 0]
    assert xs, "中心行没有任何像素，横杆没画出来"
    # 允许 ±2px 的画笔端点误差
    assert xs[0] <= CENTER - size // 2 + 2
    assert xs[-1] >= CENTER + size // 2 - 2


def test_t_shape_is_visually_distinct_from_crosshair():
    """两者不能画出同一张图——否则 UI 上多一个选项等于骗人。"""
    t = _render(CrosshairFrame(style="t_shape", size=40))
    cross = _render(CrosshairFrame(style="crosshair", size=40))
    assert t != cross


def test_t_shape_rotation_moves_the_stem():
    """旋转动画对 T 型也要生效，且必须绕中心转向量。

    竖杆不是中心对称的，如果照抄十字那套「两条过心线」的旋转写法，
    转出来的会是一条完整的过心线——形状在旋转中途变了。
    """
    base = _render(CrosshairFrame(style="t_shape", size=40))
    turned = _render(CrosshairFrame(style="t_shape", size=40, rotation=180.0))
    assert base != turned

    # 转 180° 后竖杆应当朝上：中心线**以下**变空
    # ⭐ 分母是「这一帧上有像素的行」。渲染整个坏掉时它是空的，
    #   而空的 `rows` 会让下面那条「下方没有像素」变成一句废话。
    rows = _opaque_rows(turned)
    must_scan(rows, "旋转 180° 后仍有不透明像素的行", least=3)
    below = {y: n for y, n in rows.items() if y > CENTER + 3}
    assert not below, f"转 180° 后竖杆应朝上，下方却仍有像素 {below}"


@pytest.mark.parametrize("style", USER_STYLES)
def test_every_user_style_survives_a_full_rotation(style):
    """所有样式在任意角度都不许画崩（抛异常或全空）。"""
    if style == "custom":
        pytest.skip("custom 需要用户点阵数据，由 R8b 的用例覆盖")
    for angle in (0, 37, 90, 180, 271, 359):
        img = _render(CrosshairFrame(style=style, size=40, rotation=float(angle)))
        assert _opaque_rows(img), f"{style} 在 {angle}° 画不出东西"


# ==================================================== 3. 预览要跟得上


def _preview_style_branches() -> set[str]:
    """从 `_update_preview` 的源码里抠出它比较过的样式字面量。"""
    tree = ast.parse((REPO / "pages" / "crosshair_page.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "_update_preview"):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Compare) and isinstance(sub.left, ast.Name) and sub.left.id == "style":
                for comp in sub.comparators:
                    if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                        found.add(comp.value)
    return found


def test_preview_has_no_private_drawing_branches():
    """预览**不许**再按样式分叉。

    这条判据是从反面写的，和它取代的那条正好相反。原来那条数的是
    `_update_preview` 里有没有覆盖到每个样式的 `elif style == "..."` 分支——
    因为当年预览确实是独立的第二套绘制代码，加样式时最容易漏的就是它。

    2026-08-15 把预览改成直接调 `crosshair_overlay.paint_crosshair` 之后，
    「漏样式」这个失效模式**在结构上不可能发生**了，再数分支就没有意义
    （分支数恒为 0）。但另一个失效模式冒了出来：有人图省事又在页面里手写
    一段绘制。那才是真正要防的——两套几何各画各的，正是十字预览大了一倍、
    点准心随粗细漂移的根因。

    几何是否真的一致由 tests/test_crosshair_geometry_parity.py 逐像素比。
    """
    assert not _preview_style_branches(), (
        "预览又开始按样式分叉了：几何只能有一份，改 crosshair_overlay.paint_crosshair"
    )


@pytest.mark.parametrize("style", USER_STYLES)
def test_preview_renders_every_user_style(style, qapp, monkeypatch):
    """每个样式都得在预览里画出东西来——比数分支更强的判据。"""
    from config import config
    import pages.crosshair_page as page_module

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "crosshair_style", style, raising=False)
    monkeypatch.setattr(config, "crosshair_size", 30, raising=False)
    monkeypatch.setattr(config, "crosshair_thickness", 2, raising=False)
    monkeypatch.setattr(config, "crosshair_animation", "none", raising=False)
    monkeypatch.setattr(config, "crosshair_kill_effect", "none", raising=False)
    monkeypatch.setattr(config, "crosshair_custom_data", [[15, 10], [15, 20]], raising=False)

    page = page_module.CrosshairPage()
    try:
        page._update_preview()
        pixmap = page.preview_label.pixmap()
        assert pixmap is not None and not pixmap.isNull(), f"{style} 预览没出图"
        image = pixmap.toImage()
        opaque = any(
            (image.pixel(x, y) >> 24) & 0xFF
            for y in range(image.height())
            for x in range(image.width())
        )
        assert opaque, f"{style} 预览是空白的"
    finally:
        page.deleteLater()


# ==================================================== 4. 破碎联动


def test_shatter_treats_t_shape_as_a_line_style():
    """T 型是线状样式，破碎时应当碎成线段而不是圆点——与十字同族。"""
    from crosshair_overlay import CrosshairAnimator, CrosshairState

    animator = CrosshairAnimator()
    for style, expected_count in (("crosshair", 8), ("t_shape", 8), ("dot", 6)):
        state = CrosshairState(style=style, size=40, kill_effect="shatter")
        animator.trigger_kill(state, 0.0)
        frame = animator.advance(state, 0.05)
        assert len(frame.shatter_fragments) == expected_count, (
            f"{style} 的碎片数应为 {expected_count}"
        )
