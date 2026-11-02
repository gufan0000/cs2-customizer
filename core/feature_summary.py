# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""总览页每张功能卡那行小字（批 148）。

只说三种东西：数得出来的个数、带单位的数字、用户自己起的名字。
⚠ 不印引擎 id，也不为了好看再抄一份「id → 中文名」的表（同 `core/presets/preset_center`）。
只读配置、不碰磁盘：这条路每次拨开关都走。
"""
from __future__ import annotations

from core.gun_sound_profiles import DISABLED_GUN_SOUND_STYLES, SUPPORTED_GUN_SOUND_WEAPON_TYPES

#: 这些功能的配置是「枪 → 风格」一张表。
WEAPON_TABLES = {
    "kill_sound": "weapon_kill_sounds",
    "kill_voice": "weapon_kill_voices",
    "switch_weapon": "weapon_switch_sounds",
    "reload_sound": "weapon_reload_sounds",
}


def style_is_picked(style) -> bool:
    return str(style or "").strip() not in DISABLED_GUN_SOUND_STYLES


def _guns_line(count: int) -> str:
    return f"已配 {count} 把枪" if count else "还没配枪"


def _style_line(style) -> str:
    return f"风格：{style}" if style_is_picked(style) else "还没选风格"


def feature_summary(switch_id: str, cfg, stale: int = 0) -> tuple[str, str]:
    """功能开着时卡上那行字和它的语气（`warning` 或空串）。`stale` = 配的风格有几项已经不在了。"""
    if stale:
        return f"{stale} 项风格失效", "warning"
    return _summary_line(switch_id, cfg), ""


def _summary_line(switch_id: str, cfg) -> str:
    if switch_id in WEAPON_TABLES:
        table = getattr(cfg, WEAPON_TABLES[switch_id], None) or {}
        return _guns_line(sum(1 for style in table.values() if style_is_picked(style)))
    if switch_id == "gun_sound":
        return _guns_line(sum(1 for gun in SUPPORTED_GUN_SOUND_WEAPON_TYPES
                              if style_is_picked(getattr(cfg, f"{gun}_style", "0"))))
    if switch_id == "death_sound":
        return _style_line(getattr(cfg, "death_sound_style", "0"))
    if switch_id == "kill_icon":
        return _style_line(getattr(cfg, "kill_icon_style", "0"))
    if switch_id == "crosshair":
        return f"大小 {getattr(cfg, 'crosshair_size', 0)}"
    if switch_id == "magnifier":
        magnifier = getattr(cfg, "magnifier", None) or {}
        return f"{magnifier.get('zoom_factor', 2.0):g} 倍 · {magnifier.get('hotkey', '右键')}"
    if switch_id == "flash":
        return f"不透明度 {round(float(getattr(cfg, 'flash_max_opacity', 0.75)) * 100)}%"
    if switch_id == "dynamic_hud":
        return "随击杀、被击杀变色"
    if switch_id == "screen_effects":
        return "击杀时播放"
    if switch_id == "music":
        playlists = getattr(cfg, "music_playlists", None) or {}
        songs = len(playlists.get(getattr(cfg, "music_current_playlist", ""), None) or [])
        return f"{songs} 首歌" if songs else "列表是空的"
    if switch_id == "voice_output":
        slots = getattr(cfg, "voice_output_slots", None) or {}
        filled = sum(1 for slot in slots.values() if isinstance(slot, dict) and slot.get("audio"))
        return f"{filled} 段语音" if filled else "还没配语音"
    if switch_id == "fun_afterlife":
        return "自定义网址" if getattr(cfg, "fun_afterlife_platform", "") == "custom" else "抖音"
    if switch_id == "utility":
        return f"按 {getattr(cfg, 'utility_guide_hotkey', '=')} 呼出"
    if switch_id == "spectator":
        return "观战时不出声"
    return ""
