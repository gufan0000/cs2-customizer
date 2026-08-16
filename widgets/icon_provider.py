# SPDX-License-Identifier: GPL-3.0-or-later
"""IconProvider — 封装 qtawesome,做主题色注入和 fallback.

v5 Phase 5 引入,提供统一的 icon 接口,让 Phase 5/6/9 的所有 icon 用法都统一.

设计:
  - 主题感知:icon 颜色随当前主题切换
  - Fallback:qtawesome 不可用时返回空 QIcon(不破坏 widget 渲染)
  - 缓存:同 (name, color, size) 组合的 QIcon 复用,避免重复加载

用法:
    from widgets.icon_provider import get_icon, get_themed_icon

    # 显式颜色
    icon = get_icon("mdi.cog-outline", color="#7c3aed", size=16)

    # 主题感知(随主题切换变色)— 推荐用法
    icon = get_themed_icon("mdi.cog-outline", role="primary")
    # role: "primary" / "secondary" / "muted" / "success" / "warning" / "error"

    btn.setIcon(icon)
    btn.setIconSize(QSize(16, 16))
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

# qtawesome 的延迟加载,失败时进入 fallback 模式
_qta = None
_qta_load_error: Optional[str] = None


def _try_load_qtawesome():
    global _qta, _qta_load_error
    if _qta is not None or _qta_load_error is not None:
        return _qta
    try:
        import qtawesome as qta
        _qta = qta
    except Exception as e:
        _qta_load_error = str(e)
        _qta = None
    return _qta


# 主题色映射:role → ThemeColors 字段名
_ROLE_TO_COLOR_FIELD = {
    "primary":   "text_primary",
    "secondary": "text_secondary",
    "muted":     "text_tertiary",
    "accent":    "accent_primary",
    "success":   "success",
    "warning":   "warning",
    "error":     "error",
    "info":      "info",
}


# 缓存:(name, color, size) -> QIcon
_icon_cache: dict[tuple[str, str, int], QIcon] = {}
_MAX_CACHE = 500


def is_available() -> bool:
    """qtawesome 是否可用."""
    return _try_load_qtawesome() is not None


def _fallback_icon(color: str, size: int) -> QIcon:
    """Phase1-1.8: qtawesome 不可用/异常时的兜底图标。

    画一个半透明圆角小方块（带边框），保证任何环境下图标都"存在且可见"，
    而不是静默消失（此前返回空 QIcon，qtawesome 在个别环境会抛
    TypeError，侧栏图标就全没了）。
    """
    try:
        px_size = max(8, int(size))
        pixmap = QPixmap(px_size, px_size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        base = QColor(color)
        if not base.isValid():
            base = QColor("#888888")
        fill = QColor(base)
        fill.setAlpha(70)
        painter.setBrush(fill)
        pen_color = QColor(base)
        pen_color.setAlpha(180)
        painter.setPen(pen_color)
        margin = max(1.0, px_size * 0.18)
        rect = QRectF(margin, margin, px_size - 2 * margin, px_size - 2 * margin)
        radius = max(1.5, px_size * 0.16)
        painter.drawRoundedRect(rect, radius, radius)
        painter.end()
        return QIcon(pixmap)
    except Exception:
        return QIcon()


def get_icon(name: str, color: str = "#888888", size: int = 16) -> QIcon:
    """获取一个固定颜色的 icon.

    Args:
        name: qtawesome icon 名,如 'mdi.cog-outline'
        color: hex 颜色字符串
        size: 用于缓存键(实际渲染由调用方 setIconSize 控制)

    Returns:
        QIcon — 若 qtawesome 不可用或 name 无效,返回空 QIcon
    """
    cache_key = (name, color, size)
    if cache_key in _icon_cache:
        return _icon_cache[cache_key]

    qta = _try_load_qtawesome()
    if qta is None:
        icon = _fallback_icon(color, size)
    else:
        try:
            icon = qta.icon(name, color=color)
            # 个别环境 qtawesome 不抛错但产出空 icon——同样走兜底
            if icon.isNull():
                icon = _fallback_icon(color, size)
        except Exception:
            icon = _fallback_icon(color, size)

    if len(_icon_cache) < _MAX_CACHE:
        _icon_cache[cache_key] = icon
    return icon


def get_themed_icon(name: str, role: str = "secondary", size: int = 16) -> QIcon:
    """获取一个主题感知的 icon — 颜色取自当前主题对应 role.

    Args:
        name: qtawesome icon 名
        role: "primary" / "secondary" / "muted" / "accent" / "success" / "warning" / "error" / "info"
        size: 缓存键(实际渲染由 setIconSize 控制)

    Returns:
        QIcon

    注意:此 icon 在主题切换后不会自动重渲染,调用方需要在主题切换时手动重设.
    """
    color_field = _ROLE_TO_COLOR_FIELD.get(role, "text_secondary")
    try:
        from theme_manager import get_color
        color = get_color(color_field)
    except Exception:
        color = "#888888"
    return get_icon(name, color=color, size=size)


def clear_cache() -> None:
    """清缓存(主题切换时可调,但通常 icon 在 widget 上的 setIcon 不变,无需清)."""
    _icon_cache.clear()


# ========== 27 页侧栏 icon 映射 ==========

PAGE_ICON_MAP: dict[str, str] = {
    "basic":                "mdi.cog-outline",
    "kill_sound":           "mdi.target",
    "kill_voice":           "mdi.account-voice",
    "death_sound":          "mdi.skull-outline",
    "gun_sound":            "mdi.pistol",
    "switch_weapon":        "mdi.swap-horizontal",
    "reload_sound":         "mdi.reload",
    "special_sound":        "mdi.music-circle",
    "crosshair":            "mdi.crosshairs",
    "kill_icon":            "mdi.image-multiple-outline",
    "viewmodel":            "mdi.eye-outline",
    "magnifier":            "mdi.magnify",
    "flash":                "mdi.flash",
    "hud_color":            "mdi.palette-outline",
    "screen_effects":       "mdi.monitor-screenshot",
    "music":                "mdi.music",
    "voice_output":         "mdi.microphone",
    # V-007（2026-08-16）：这一条**漏了很久**。`get_page_icon` 查不到就静默
    # 返回空 QIcon——不报错、不打日志，只是这一项在侧栏里没有图标，
    # 文字起始位置比同组其它项左移一截，看着像没对齐。
    # 判据见 tests/test_ui_visual_r1_fixes.py::test_every_nav_page_has_an_icon。
    "fun_afterlife":        "mdi.cellphone-play",
    "utility":              "mdi.tools",
    "advanced":             "mdi.cog-transfer-outline",
    "audio_health":         "mdi.heart-pulse",
    "audio_import_wizard":  "mdi.import",
    "audio_task_panel":     "mdi.format-list-checks",
    "audio_replay":         "mdi.replay",
    "preset_center":        "mdi.bookmark-multiple-outline",
    "config_snapshot":      "mdi.content-save-outline",
    "about":                "mdi.information-outline",
}


# R7/D-08(UP-051): 导航选中态用哪个 role。
# D-08 原文没指定颜色，最自然的想法是用 accent_primary（和选中态文字同色）——
# 但实测那是**倒退**：accent 在 navButton:checked 的底(bg_tertiary)上，
# dark 只有 2.88:1、warm 2.28:1、light 2.94:1、rose 2.99:1，
# 四个主题比现在的 secondary(5.9~7.1) 还差，等于把选中项的图标弄得更看不清。
# text_primary 在 8/8 主题都是 9.45~15.91:1，严格优于现状。
# 所以选中 = "primary"，未选中维持 "secondary"。偏离已记 03。
NAV_ICON_ROLE_SELECTED = "primary"
NAV_ICON_ROLE_NORMAL = "secondary"


def apply_nav_icon(button, page_id: str, selected: bool, size: int = 16) -> None:
    """按选中态给导航按钮设置图标（幂等）。

    幂等靠 `fp_nav_icon_role` 动态属性记账：切页时会把所有导航按钮走一遍，
    不记账的话每次切页都要重渲染 20+ 个图标。
    （icon_provider 自身有 (name,color,size) 缓存，但 setIcon 仍会触发重绘。）
    """
    role = NAV_ICON_ROLE_SELECTED if selected else NAV_ICON_ROLE_NORMAL
    if button.property("fp_nav_icon_role") == role:
        return
    icon = get_page_icon(page_id, role=role, size=size)
    if not icon.isNull():
        button.setIcon(icon)
        button.setProperty("fp_nav_icon_role", role)


def get_page_icon(page_id: str, role: str = "secondary", size: int = 16) -> QIcon:
    """获取页面对应的侧栏 icon."""
    name = PAGE_ICON_MAP.get(page_id)
    if not name:
        return QIcon()
    return get_themed_icon(name, role=role, size=size)
