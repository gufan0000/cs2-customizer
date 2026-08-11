# -*- coding: utf-8 -*-
"""R4 · 对比度与禁用态回归（UP-021 / UP-022 / UP-023 / UP-050）。

这批缺陷的共同点是：**在某一个主题下才暴露**。人眼在 9 个主题里来回切换是
查不干净的（`primaryButton` 的白字在深紫主题下好好的，到墨绿主题只剩 2.10:1），
所以守门必须是数学的、全主题遍历的。

`scripts/ui_contrast_audit.py` 是同一套判据的命令行版（给 CI 用）；
这里把它固化成 pytest，保证以后有人改主题色时立刻红。
"""
from __future__ import annotations

import pytest

from core.utils.contrast import (
    AA_NORMAL,
    best_on_color,
    contrast_ratio,
    ensure_contrast,
    parse_hex,
    relative_luminance,
    worst_contrast,
)


# ---------------------------------------------------------------- 纯数学部分


def test_parse_hex_forms():
    assert parse_hex("#fff") == (255, 255, 255)
    assert parse_hex("000000") == (0, 0, 0)
    assert parse_hex("#7C3AED") == (0x7C, 0x3A, 0xED)
    # 带 alpha 的 8 位色值忽略 alpha，不应抛
    assert parse_hex("#7c3aedff") == (0x7C, 0x3A, 0xED)
    with pytest.raises(ValueError):
        parse_hex("#12345")


def test_contrast_ratio_known_values():
    """对着 WCAG 规范的已知值校准，防止亮度公式写错。"""
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0, abs=0.01)
    # 顺序无关
    assert contrast_ratio("#777777", "#ffffff") == pytest.approx(
        contrast_ratio("#ffffff", "#777777"))
    # sRGB 中灰 #767676 是 WCAG 官方常引的"白底上刚好 4.5"的临界色
    assert contrast_ratio("#767676", "#ffffff") == pytest.approx(4.54, abs=0.05)


def test_relative_luminance_bounds():
    assert relative_luminance("#000000") == pytest.approx(0.0, abs=1e-6)
    assert relative_luminance("#ffffff") == pytest.approx(1.0, abs=1e-6)


def test_best_on_color_picks_readable_side():
    assert best_on_color("#ffffff") != "#ffffff"     # 白底不能用白字
    assert best_on_color("#000000") == "#ffffff"


def test_ensure_contrast_reaches_target():
    # 浅灰字压在白底上（典型 hintLabel 缺陷形态）
    fixed = ensure_contrast("#aaaaaa", ("#ffffff",), AA_NORMAL)
    assert contrast_ratio(fixed, "#ffffff") >= AA_NORMAL
    # 已达标的不该被动
    assert ensure_contrast("#000000", ("#ffffff",)) == "#000000"


def test_ensure_contrast_multi_background():
    """对多个背景收敛时，必须**所有**背景都达标，而不是随便一个。"""
    bgs = ("#ffffff", "#f0f0f0", "#e6e6e6")
    fixed = ensure_contrast("#b0b0b0", bgs, AA_NORMAL)
    assert worst_contrast(fixed, bgs) >= AA_NORMAL


def test_ensure_contrast_never_raises_on_impossible_target():
    """中灰背景上 21:1 谁也做不到——必须返回尽力值而不是抛异常。

    主题渲染不能因为一个色值算不出来就崩。
    """
    got = ensure_contrast("#808080", ("#808080",), target=21.0)
    assert isinstance(got, str) and got.startswith("#")


# ---------------------------------------------------------- 9 主题全遍历部分


def _themes():
    from theme_manager import get_theme_manager
    # minimal 走系统原生样式（generate_stylesheet 返回空串），
    # 它的 ThemeColors 是占位符、从不参与渲染，审计它只会产生假警报。
    return [(n, t) for n, t in get_theme_manager().themes.items() if n != "minimal"]


def _theme_ids():
    return [n for n, _ in _themes()]


@pytest.mark.parametrize("name", _theme_ids())
def test_body_text_meets_aa(name):
    """UP-023：正文/次要/提示三档文字在任何背景上都要 ≥4.5:1。"""
    theme = dict(_themes())[name]
    c = theme.colors
    bgs = (c.bg_primary, c.bg_secondary, c.bg_card)
    for token in ("text_primary", "text_secondary", "text_muted"):
        ratio = worst_contrast(getattr(c, token), bgs)
        assert ratio >= AA_NORMAL, f"{name}.{token} 仅 {ratio:.2f}:1"


@pytest.mark.parametrize("name", _theme_ids())
def test_primary_button_text_meets_aa_on_both_gradient_stops(name):
    """UP-021：主按钮底是渐变，文字铺满全按钮 —— **两端**都得达标。

    只看实底那一端会被渐变的浅端打脸：深色主题实测浅端白字只有 4.00:1。
    """
    theme = dict(_themes())[name]
    c = theme.colors
    stops = (theme._accent_gradient_top(), c.accent_primary)
    ratio = worst_contrast(c.text_on_primary, stops)
    assert ratio >= AA_NORMAL, f"{name} 主按钮文字仅 {ratio:.2f}:1"


@pytest.mark.parametrize("name", _theme_ids())
def test_danger_button_text_meets_aa(name):
    theme = dict(_themes())[name]
    bg = theme._danger_bg()
    ratio = contrast_ratio(theme._on_color(bg), bg)
    assert ratio >= AA_NORMAL, f"{name} 危险按钮文字仅 {ratio:.2f}:1"


@pytest.mark.parametrize("name", _theme_ids())
def test_status_chip_text_meets_aa(name):
    theme = dict(_themes())[name]
    c = theme.colors
    for token in ("accent_warm", "error"):
        ratio = contrast_ratio(theme._chip_text(getattr(c, token)), c.bg_card)
        assert ratio >= AA_NORMAL, f"{name} chip {token} 仅 {ratio:.2f}:1"


@pytest.mark.parametrize("name", _theme_ids())
def test_disabled_text_is_distinguishable(name):
    """UP-022：WCAG 豁免禁用控件，但禁用态必须**看得出**和常态不同。

    看不出来的后果不是"不好看"——用户会反复点一个点不动的按钮，以为软件卡了。
    """
    theme = dict(_themes())[name]
    c = theme.colors
    ratio = contrast_ratio(c.text_disabled, c.text_primary)
    assert ratio >= 1.6, f"{name} 禁用态与常态文字仅差 {ratio:.2f}:1，用户分辨不出"


@pytest.mark.parametrize("name", _theme_ids())
def test_stylesheet_has_no_hardcoded_white_text(name):
    """UP-021 的根因是硬编码 `color: white`，锁住别再写回去。

    唯一豁免：QRadioButton 选中指示器的**白色圆心**（那是图形不是文字）。
    """
    import re

    theme = dict(_themes())[name]
    qss = theme.generate_stylesheet()
    # 用前置边界排除 `background-color:` —— 直接子串匹配会把单选框指示器的
    # 白色圆心（图形，不是文字）也算进来，那是误报。
    hits = re.findall(r"(?<![-\w])color:\s*white", qss)
    assert not hits, f"{name} 的 QSS 里仍有 {len(hits)} 处硬编码白字"
    assert "selection-color: white" not in qss, f"{name} 的选中文字色仍硬编码为白"


@pytest.mark.parametrize("name", _theme_ids())
def test_stylesheet_defines_disabled_states(name):
    """UP-022 / D-16：全局禁用态规则组必须存在且覆盖主要控件。"""
    theme = dict(_themes())[name]
    qss = theme.generate_stylesheet()
    for selector in ("QPushButton:disabled", "QComboBox:disabled",
                     "QLineEdit:disabled", "QCheckBox:disabled",
                     "QRadioButton:disabled"):
        assert selector in qss, f"{name} 缺少 {selector}"


@pytest.mark.parametrize("name", _theme_ids())
def test_status_chip_error_and_neutral_levels_exist(name):
    """UP-050：StatusChip 声明了 error / neutral，QSS 里原本只有 danger。

    缺失的后果是异常态**静默**掉回基础规则，渲染成和正常态一样的中性灰。
    """
    theme = dict(_themes())[name]
    qss = theme.generate_stylesheet()
    assert 'QLabel#audioStatusChip[level="error"]' in qss
    assert 'QLabel#audioStatusChip[level="neutral"]' in qss


def test_status_chip_levels_all_have_qss_coverage():
    """反过来卡：StatusChip 允许的每个 level 都必须在 QSS 里有对应规则。

    这样以后给 StatusChip 加新 level 时，忘了补 QSS 会立刻红，
    而不是等用户看到一个"异常但长得像正常"的徽章。
    """
    from theme_manager import get_theme_manager
    from widgets.status_chip import _VALID_LEVELS

    qss = get_theme_manager().themes["dark"].generate_stylesheet()
    missing = [lv for lv in _VALID_LEVELS
               if f'QLabel#audioStatusChip[level="{lv}"]' not in qss]
    assert not missing, f"这些 level 没有 QSS 规则，会静默渲染成中性灰: {missing}"


def test_derived_tokens_are_auto_filled():
    """text_muted / text_on_primary 必须自动推导，不要求各主题手写。

    手写 9 份必漏，而且以后新增主题会静默不达标。
    """
    from theme_manager import Theme, ThemeColors

    colors = ThemeColors(
        bg_primary="#ffffff", bg_secondary="#fafafa", bg_tertiary="#f0f0f0",
        bg_elevated="#ffffff", text_primary="#111111", text_secondary="#444444",
        text_tertiary="#b8b8b8",  # 故意给一个白底上只有 ~1.8:1 的值
        text_disabled="#cccccc",
        accent_primary="#4eca6a", accent_hover="#3fb85a", accent_pressed="#2fa74a",
        accent_disabled="#a8e0b6", border_primary="#e0e0e0",
        border_secondary="#eeeeee", border_focus="#4eca6a",
        success="#2e9e4f", warning="#d08700", error="#d13438", info="#0a84ff",
        scrollbar_bg="#ffffff", scrollbar_handle="#dddddd",
        scrollbar_hover="#cccccc", shadow="rgba(0,0,0,0.05)",
    )
    theme = Theme("测试主题", colors)
    assert colors.text_muted is not None
    assert colors.text_on_primary is not None
    assert contrast_ratio(colors.text_muted, "#ffffff") >= AA_NORMAL
    # 亮绿底上白字只有 2.10:1，自动推导必须选深字
    assert contrast_ratio(colors.text_on_primary, colors.accent_primary) >= AA_NORMAL
    assert theme is not None


def test_explicit_token_overrides_are_respected():
    """显式给了值就不许被自动推导覆盖（留出人工微调的口子）。"""
    from theme_manager import Theme, ThemeColors

    colors = ThemeColors(
        bg_primary="#101010", bg_secondary="#181818", bg_tertiary="#202020",
        bg_elevated="#242424", text_primary="#f0f0f0", text_secondary="#c0c0c0",
        text_tertiary="#808080", text_disabled="#505050",
        accent_primary="#7c3aed", accent_hover="#8b4bf5", accent_pressed="#6b2ad8",
        accent_disabled="#3d2470", border_primary="#303030",
        border_secondary="#282828", border_focus="#7c3aed",
        success="#22c55e", warning="#f59e0b", error="#ef4444", info="#3b82f6",
        scrollbar_bg="#101010", scrollbar_handle="#383838",
        scrollbar_hover="#484848", shadow="rgba(0,0,0,0.4)",
        text_muted="#9a9a9a", text_on_primary="#fff8e7",
    )
    Theme("测试主题", colors)
    assert colors.text_muted == "#9a9a9a"
    assert colors.text_on_primary == "#fff8e7"
