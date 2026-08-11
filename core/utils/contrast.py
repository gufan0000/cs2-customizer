# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""WCAG 2.1 对比度计算（纯数学，不依赖 Qt / 不需要 QApplication）。

为什么不用 `QColor`：本模块要被 `scripts/ui_contrast_audit.py` 在 CI 里跑，
也要被单元测试大量调用。纯 Python 实现让它在没有 Qt 平台插件的环境里也能跑，
而且 `ensure_contrast` 的迭代次数不小，省掉 Qt 对象往返更快。

术语（WCAG 2.1 §1.4.3）：
- 正文文字对比度 **≥ 4.5:1** 算 AA 达标；
- 大号文字（≥18pt 或 ≥14pt 加粗）放宽到 3:1；
- 非文字（图标、控件边框）3:1。

本项目的用法见 `theme_manager.Theme._fill_v5_defaults`：
`text_muted` / `text_on_primary` 两个 token 都是**按主题自动推导**的，
而不是 9 套主题各手写一遍——手写必然漏，且新增主题会静默不达标。
"""
from __future__ import annotations

import colorsys

__all__ = [
    "parse_hex",
    "to_hex",
    "relative_luminance",
    "contrast_ratio",
    "worst_contrast",
    "best_on_color",
    "ensure_contrast",
    "AA_NORMAL",
    "AA_LARGE",
]

# WCAG AA 阈值
AA_NORMAL = 4.5   # 正文
AA_LARGE = 3.0    # 大字/图形


def parse_hex(color: str) -> tuple[int, int, int]:
    """`#rgb` / `#rrggbb` / `rrggbb` → (r, g, b)。"""
    s = str(color).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) == 8:      # #rrggbbaa，忽略 alpha
        s = s[:6]
    if len(s) != 6:
        raise ValueError(f"无法解析颜色: {color!r}")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(round(v)))) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _linearize(channel: int) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """WCAG 相对亮度，0.0(黑) ~ 1.0(白)。"""
    r, g, b = parse_hex(color)
    return 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """两色对比度，范围 1.0 ~ 21.0。参数顺序不影响结果。"""
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def worst_contrast(fg: str, backgrounds) -> float:
    """fg 对一组背景中**最差**的那个的对比度。

    同一个 token 会落在多种背景上（如 hintLabel 既在卡片里也在侧栏里），
    只对其中一个达标没有意义。
    """
    bgs = [b for b in backgrounds if b]
    if not bgs:
        return 21.0
    return min(contrast_ratio(fg, b) for b in bgs)


def best_on_color(bg: str, light: str = "#ffffff", dark: str = "#111318") -> str:
    """在 bg 上该用浅字还是深字——取对比度高的那个。

    用于 `text_on_primary`：品牌色亮度跨主题差异极大
    （深紫 #6c3fd8 vs 暖橙 #e8a05a），写死 `color: white` 必然有主题被冲掉。
    """
    return light if contrast_ratio(light, bg) >= contrast_ratio(dark, bg) else dark


def ensure_contrast(fg: str, backgrounds, target: float = AA_NORMAL,
                    max_steps: int = 100) -> str:
    """把 fg 朝远离背景的方向推，直到对所有背景都达标；保色相与饱和度。

    调整的是 HLS 的 L 通道：亮背景就压暗、暗背景就提亮，每步 1%。
    达不到 target 时（例如背景本身是中灰，两头都够不着）返回能取到的
    最佳值——纯黑或纯白，绝不抛异常：主题渲染不能因为一个色值失败而崩。

    Args:
        fg: 起始前景色
        backgrounds: 单个色值或色值序列
        target: 目标对比度，默认 AA 正文 4.5
    """
    bgs = [backgrounds] if isinstance(backgrounds, str) else [b for b in backgrounds if b]
    if not bgs:
        return fg
    if worst_contrast(fg, bgs) >= target:
        return fg

    # 往哪边推：背景整体偏亮就压暗前景，反之提亮
    bg_lum = max(relative_luminance(b) for b in bgs)
    darken = bg_lum > 0.18   # 0.18 ≈ 中灰，sRGB 下的感知中点

    r, g, b = parse_hex(fg)
    h, lightness, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    step = -0.01 if darken else 0.01

    best, best_ratio = fg, worst_contrast(fg, bgs)
    for _ in range(max_steps):
        lightness = max(0.0, min(1.0, lightness + step))
        rr, gg, bb = colorsys.hls_to_rgb(h, lightness, s)
        cand = to_hex((rr * 255, gg * 255, bb * 255))
        ratio = worst_contrast(cand, bgs)
        if ratio > best_ratio:
            best, best_ratio = cand, ratio
        if ratio >= target:
            return cand
        if lightness <= 0.0 or lightness >= 1.0:
            break
    return best
