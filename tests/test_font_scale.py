# -*- coding: utf-8 -*-
"""R1-1 界面字号缩放:token 缩放幂等性、档位收敛、QSS 穿透。"""
import pytest

from ui_design_system import (
    FONT_SCALE_CHOICES,
    FontSize,
    apply_font_scale,
    get_design_system,
    get_font_scale,
    normalize_font_scale,
)


@pytest.fixture(autouse=True)
def _restore_scale():
    yield
    apply_font_scale(1.0)


def test_normalize_clamps_invalid_values():
    assert normalize_font_scale(None) == 1.0
    assert normalize_font_scale("abc") == 1.0
    assert normalize_font_scale(99) == 1.0
    assert normalize_font_scale(0.3) == 1.0
    for choice in FONT_SCALE_CHOICES:
        assert normalize_font_scale(choice) == choice
    # 字符串数字也接受(JSON 配置可能存成字符串)
    assert normalize_font_scale("1.25") == 1.25


def test_apply_scales_tokens_from_factory_baseline():
    ds = get_design_system()
    base = FontSize()
    applied = apply_font_scale(1.25)
    assert applied == 1.25
    assert get_font_scale() == 1.25
    assert ds.font_size.md == round(base.md * 1.25)
    assert ds.font_size.h1 == round(base.h1 * 1.25)
    assert ds.button.primary_font_size == round(13 * 1.25)
    assert ds.input.text_font_size == round(13 * 1.25)


def test_apply_is_idempotent_no_drift():
    ds = get_design_system()
    apply_font_scale(1.1)
    first = ds.font_size.md
    for _ in range(5):
        apply_font_scale(1.1)
    assert ds.font_size.md == first
    # 回到 1.0 应与出厂一致
    apply_font_scale(1.0)
    assert ds.font_size.md == FontSize().md


def test_stylesheet_reflects_scaled_tokens():
    from theme_manager import get_theme_manager

    tm = get_theme_manager()
    apply_font_scale(1.25)
    qss = tm.current_theme.generate_stylesheet()
    scaled_md = round(FontSize().md * 1.25)
    assert f"font-size: {scaled_md}px" in qss
    apply_font_scale(1.0)
    qss_back = tm.current_theme.generate_stylesheet()
    assert f"font-size: {FontSize().md}px" in qss_back


def test_invalid_scale_falls_back_to_default():
    ds = get_design_system()
    applied = apply_font_scale("garbage")
    assert applied == 1.0
    assert ds.font_size.md == FontSize().md
