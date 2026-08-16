# SPDX-License-Identifier: GPL-3.0-or-later
"""准心「预览」与「实际渲染」的几何一致性判据，以及多屏选屏。

## 为什么判据要长这样

`pages/crosshair_page._update_preview` 原来自己写了一整套绘制分支，和
`crosshair_overlay.paint_crosshair` 各画各的，结果每个样式各错各的：
  · 十字 / T 型：预览半长 = size，实际 = size//2 —— 预览是实际的 **2 倍**
  · 点：预览半径乘了 thickness/2，实际与粗细无关 —— 调粗细预览变、游戏里不变
  · 圆圈：碰巧一致
而当时两边各自的单元测试都是绿的，因为每个测试只验自己那一份"有没有按自己
以为的方式画"。**只有把两边的产物摆在一起比，才可能发现它们不一致。**

所以这里比的是**渲染出来的像素**（各自的可见外接框），不是"有没有调某个函数"。
就算以后有人又在页面里手写一套绘制，只要几何对不上就会红。
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt

from config import config
from crosshair_overlay import (
    CANVAS_PX,
    USER_STYLES,
    CrosshairAnimator,
    CrosshairState,
    paint_crosshair,
    pick_screen,
)


# ── 工具 ────────────────────────────────────────────────────────────────


def _visible_bbox(image: QImage):
    """图上所有非透明像素的外接框 (x0, y0, x1, y1)；全透明返回 None。"""
    left = top = None
    right = bottom = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if (image.pixel(x, y) >> 24) & 0xFF:
                if left is None or x < left:
                    left = x
                if top is None or y < top:
                    top = y
                right = max(right, x)
                bottom = max(bottom, y)
    if left is None:
        return None
    return (left, top, right, bottom)


def _render_overlay(style, size, thickness, custom_points=()):
    state = CrosshairState(
        size=size, thickness=thickness, color="green", style=style,
        animation="none", kill_effect="none", custom_points=custom_points,
    )
    frame = CrosshairAnimator().advance(state, 0.0)
    image = QImage(CANVAS_PX, CANVAS_PX, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    paint_crosshair(painter, frame)
    painter.end()
    return image


def _render_preview(page):
    pixmap = page.preview_label.pixmap()
    assert pixmap is not None and not pixmap.isNull(), "预览没出图"
    return pixmap.toImage()


# ── 几何一致性 ──────────────────────────────────────────────────────────


_CUSTOM = ((15, 10), (15, 20), (10, 15), (20, 15))


@pytest.mark.parametrize("style", USER_STYLES)
@pytest.mark.parametrize("size,thickness", [(10, 1), (20, 2), (40, 6)])
def test_preview_matches_overlay_geometry(qapp, monkeypatch, style, size, thickness):
    """同一份配置下，预览与实际渲染的可见外接框必须逐像素一致。

    旧实现在这里会红得很难看：十字/T 型差一倍，点随粗细漂移。
    """
    import pages.crosshair_page as page_module

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "crosshair_style", style, raising=False)
    monkeypatch.setattr(config, "crosshair_size", size, raising=False)
    monkeypatch.setattr(config, "crosshair_thickness", thickness, raising=False)
    monkeypatch.setattr(config, "crosshair_color", "green", raising=False)
    monkeypatch.setattr(config, "crosshair_animation", "none", raising=False)
    monkeypatch.setattr(config, "crosshair_kill_effect", "none", raising=False)
    monkeypatch.setattr(config, "crosshair_custom_data", [list(p) for p in _CUSTOM], raising=False)

    page = page_module.CrosshairPage()
    try:
        page._update_preview()
        preview = _render_preview(page)
        overlay = _render_overlay(style, size, thickness, custom_points=_CUSTOM)

        assert preview.width() == overlay.width(), "预览画布尺寸与渲染层不一致"
        assert _visible_bbox(preview) == _visible_bbox(overlay), (
            f"{style} size={size} thickness={thickness}: 预览与实际渲染的几何不一致"
        )
    finally:
        page.deleteLater()


def test_preview_size_scales_with_size_setting(qapp, monkeypatch):
    """加大 size，预览必须跟着变大——否则"一致"可能是两边一起画空。"""
    import pages.crosshair_page as page_module

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "crosshair_style", "crosshair", raising=False)
    monkeypatch.setattr(config, "crosshair_thickness", 2, raising=False)
    monkeypatch.setattr(config, "crosshair_color", "green", raising=False)
    monkeypatch.setattr(config, "crosshair_animation", "none", raising=False)

    boxes = []
    page = page_module.CrosshairPage()
    try:
        for size in (10, 30):
            monkeypatch.setattr(config, "crosshair_size", size, raising=False)
            page._update_preview()
            boxes.append(_visible_bbox(_render_preview(page)))
    finally:
        page.deleteLater()

    small, large = boxes
    assert small is not None and large is not None
    assert (large[2] - large[0]) > (small[2] - small[0])


def test_dot_preview_ignores_thickness(qapp, monkeypatch):
    """点准心的大小与粗细无关——这正是旧预览错的地方（它乘了 thickness/2）。"""
    import pages.crosshair_page as page_module

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "crosshair_style", "dot", raising=False)
    monkeypatch.setattr(config, "crosshair_size", 20, raising=False)
    monkeypatch.setattr(config, "crosshair_color", "green", raising=False)
    monkeypatch.setattr(config, "crosshair_animation", "none", raising=False)

    boxes = []
    page = page_module.CrosshairPage()
    try:
        for thickness in (1, 8):
            monkeypatch.setattr(config, "crosshair_thickness", thickness, raising=False)
            page._update_preview()
            boxes.append(_visible_bbox(_render_preview(page)))
    finally:
        page.deleteLater()

    assert boxes[0] == boxes[1], "点准心的预览不该随粗细改变"


# ── 多屏选屏 ────────────────────────────────────────────────────────────


class _FakeScreen:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _ExplodingScreen:
    def name(self):
        raise RuntimeError("驱动抽风")


def test_pick_screen_matches_by_device_name():
    a, b = _FakeScreen(r"\\.\DISPLAY1"), _FakeScreen(r"\\.\DISPLAY2")
    assert pick_screen([a, b], a, r"\\.\DISPLAY2") is b


def test_pick_screen_falls_back_to_primary_when_unknown():
    a, b = _FakeScreen(r"\\.\DISPLAY1"), _FakeScreen(r"\\.\DISPLAY2")
    assert pick_screen([a, b], a, r"\\.\DISPLAY9") is a
    assert pick_screen([a, b], a, None) is a
    assert pick_screen([], a, r"\\.\DISPLAY1") is a


def test_pick_screen_survives_a_broken_screen():
    """一块屏问不出名字不该连累其它屏——游戏那块可能排在它后面。"""
    good = _FakeScreen(r"\\.\DISPLAY2")
    primary = _FakeScreen(r"\\.\DISPLAY1")
    assert pick_screen([_ExplodingScreen(), good], primary, r"\\.\DISPLAY2") is good


def test_game_screen_lookup_never_raises(monkeypatch):
    """取不到游戏窗口时必须安静地退回 None，不能把准心显示整个带崩。"""
    import crosshair_overlay as mod

    monkeypatch.setattr(mod.sys, "platform", "linux")
    assert mod.game_screen_device_name() is None


# ── 2.2.4 补齐的样式参数 ────────────────────────────────────────────────


def _center_is_clear(image, radius):
    """中心半径 radius 内是否全透明。"""
    c = image.width() // 2
    for y in range(c - radius, c + radius + 1):
        for x in range(c - radius, c + radius + 1):
            if (image.pixel(x, y) >> 24) & 0xFF:
                return False
    return True


def _render_state(state):
    frame = CrosshairAnimator().advance(state, 0.0)
    image = QImage(CANVAS_PX, CANVAS_PX, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    paint_crosshair(painter, frame)
    painter.end()
    return image


@pytest.mark.parametrize("style", ["crosshair", "t_shape"])
def test_gap_actually_clears_the_center(style):
    """中心间隙必须真的把瞄准点让出来——这是这项功能存在的全部理由。"""
    solid = _render_state(CrosshairState(style=style, size=40, thickness=2, gap=0))
    gapped = _render_state(CrosshairState(style=style, size=40, thickness=2, gap=6))
    assert not _center_is_clear(solid, 1), "gap=0 时中心本来就该被线盖住"
    assert _center_is_clear(gapped, 3), f"{style} 设了间隙，中心却还是实的"


def test_gap_zero_is_pixel_identical_to_before():
    """gap 默认 0 时，存量用户的观感必须一像素不变。"""
    without = _render_state(CrosshairState(style="crosshair", size=30, thickness=3))
    explicit = _render_state(CrosshairState(style="crosshair", size=30, thickness=3, gap=0))
    assert without == explicit


def test_gap_larger_than_arm_draws_nothing_instead_of_inverting():
    """间隙大于臂长时应当什么都不画，而不是画出反向线段。"""
    image = _render_state(CrosshairState(style="crosshair", size=10, thickness=2, gap=50))
    assert _visible_bbox(image) is None


def _opaque_count(image):
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if (image.pixel(x, y) >> 24) & 0xFF
    )


@pytest.mark.parametrize("style", ["crosshair", "t_shape", "dot", "circle"])
def test_outline_thickens_the_strokes(style):
    """描边要让准星占的像素变多。

    ⚠ 别拿外接框验这件事：十字的外接框由**臂长**决定，笔加粗一圈也不会让它
    变大（FlatCap 不越过端点）。我第一版判据就是这么写的，红了才发现验错了
    东西——描边确实生效，只是不体现在包围盒上。
    """
    plain = _opaque_count(_render_state(CrosshairState(style=style, size=30, thickness=2)))
    outlined = _opaque_count(
        _render_state(CrosshairState(style=style, size=30, thickness=2, outline=2))
    )
    assert outlined > plain, f"{style} 的描边没有生效"


def test_dot_fills_the_center_even_with_a_gap():
    """中心点要盖在形状之上：配合间隙用时，中心必须是实的。"""
    image = _render_state(
        CrosshairState(style="crosshair", size=40, thickness=2, gap=8, dot=True)
    )
    assert not _center_is_clear(image, 1)


def test_alpha_is_applied_to_the_drawn_pixels():
    opaque = _render_state(CrosshairState(style="dot", size=20, alpha=255))
    faded = _render_state(CrosshairState(style="dot", size=20, alpha=100))
    c = CANVAS_PX // 2
    assert ((opaque.pixel(c, c) >> 24) & 0xFF) == 255
    assert 0 < ((faded.pixel(c, c) >> 24) & 0xFF) < 255


def test_outline_fades_together_with_the_crosshair():
    """描边不跟着透明的话，调低不透明度会剩一圈黑边浮在屏幕上。"""
    frame = CrosshairAnimator().advance(
        CrosshairState(style="crosshair", size=30, outline=2, alpha=100), 0.0
    )
    assert frame.outline_color.alpha() == frame.color.alpha()


def test_custom_hex_color_is_honored():
    from crosshair_overlay import resolve_color

    assert resolve_color("#ff00ff").name() == "#ff00ff"
    # 六个固定色名必须继续认——存量配置指向的是它们
    assert resolve_color("green").name() == "#00ff00"
    # 解析不了就退回默认绿，不能画不出来
    assert resolve_color("#zzz").name() == "#00ff00"


def test_preview_canvas_is_one_to_one_with_the_renderer(qapp, monkeypatch):
    """预览画布必须是渲染层那块 CANVAS_PX 物理像素的画布，1:1。

    这条替代了原来"检查有没有调 painter.scale"的 AST 判据——那卡的是旧策略
    的实现形状（按逻辑坐标画、画布放大 dpr 倍）。新做法是按物理像素 1:1 画，
    DPR 只标在 pixmap 上让 Qt 缩到正确的逻辑尺寸。

    ⚠ 别把 DPR 设到 QImage 上：那会让 QPainter 的坐标系变成逻辑像素，而
    frame 的坐标是物理像素，1.25 档下这张 100px 的画布会被当成 80px 用，
    预览反而比游戏里小。我第一版就是这么写的。

    高 DPI 下的清晰度另有 tests/test_page_layout_defects.py::
    test_crosshair_preview_renders_sharp_on_high_dpi 看着（那条用真实屏幕的
    DPR，不 monkeypatch —— QLabel 内部也会读控件自己的 DPR，伪造那个方法
    测到的不是产品行为）。
    """
    import pages.crosshair_page as page_module

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "crosshair_style", "crosshair", raising=False)
    monkeypatch.setattr(config, "crosshair_size", 30, raising=False)
    monkeypatch.setattr(config, "crosshair_thickness", 2, raising=False)
    monkeypatch.setattr(config, "crosshair_animation", "none", raising=False)

    page = page_module.CrosshairPage()
    try:
        page._update_preview()
        pixmap = page.preview_label.pixmap()
        physical = pixmap.width() * pixmap.devicePixelRatio()
        assert abs(physical - CANVAS_PX) < 1.0, (
            f"预览占 {physical} 物理像素，渲染层是 {CANVAS_PX}"
        )
    finally:
        page.deleteLater()
