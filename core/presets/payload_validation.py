# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate imported settings before they reach shared config or Qt controls."""
from __future__ import annotations

import math


_RANGES = {
    "crosshair_size": (5, 50, int), "crosshair_thickness": (1, 10, int),
    "crosshair_gap": (0, 20, int), "crosshair_outline": (0, 4, int),
    "crosshair_alpha": (0, 255, int), "health_warning_threshold": (1, 100, int),
    "flash_max_opacity": (0, 1, float), "flash_image_opacity": (0, 1, float),
    "flash_audio_volume": (0, 1, float),
    "viewmodel_auto_switch_interval": (0.1, 3600, float),
}
_CONTAINERS = {
    "hud_rules": dict, "hud_keymap_enabled": dict, "grenade_sound_styles": dict,
    "crosshair_custom_data": list, "flash_style_params": dict,
    "viewmodel_presets": list, "magnifier": dict,
}
_BOOL_KEYS = {"crosshair_dot", "flash_audio_auto_stop"}


def _number(value, low, high, kind=float):
    return (type(value) in ((int,) if kind is int else (int, float))
            and math.isfinite(value) and low <= value <= high)


def _json_value(value, depth=0):
    if depth > 12:
        return False
    if value is None or type(value) in (str, bool, int):
        return not isinstance(value, str) or len(value) <= 16384
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, (list, tuple)):
        return len(value) <= 4096 and all(_json_value(v, depth + 1) for v in value)
    if isinstance(value, dict):
        return len(value) <= 4096 and all(
            isinstance(k, str) and len(k) <= 128 and _json_value(v, depth + 1)
            for k, v in value.items())
    return False


def _nested_valid(key, value):
    if key == "crosshair_custom_data":
        return len(value) <= 961 and all(
            isinstance(p, (list, tuple)) and len(p) == 2
            and all(_number(n, 0, 30, int) for n in p) for p in value)
    if key == "grenade_sound_styles":
        return all(isinstance(v, str) for v in value.values())
    if key == "hud_keymap_enabled":
        return all(type(v) is bool for v in value.values())
    if key == "flash_style_params":
        return all(
            all(_number(param, 0, 1000) for param in v.values())
            if isinstance(v, dict) else _number(v, 0, 1000)
            for v in value.values())
    if key == "viewmodel_presets":
        return all(isinstance(p, dict) and all(
            (isinstance(v, str) if k in {"name", "key", "hotkey"}
             else _number(v, -100, 180) if k in {"fov", "x", "y", "z", "offset_x", "offset_y", "offset_z"}
             else _json_value(v)) for k, v in p.items()) for p in value)
    if key == "magnifier":
        for k, v in value.items():
            if k == "weapon_settings":
                if not isinstance(v, dict) or not all(type(s) is bool for s in v.values()):
                    return False
            elif k == "zoom_settings":
                if not isinstance(v, dict) or not all(
                    isinstance(s, dict) and all(
                        _number(offset, -10000, 10000, int)
                        for name, offset in s.items() if name in {"x_offset", "y_offset"}
                    ) for s in v.values()
                ):
                    return False
            elif k.endswith("enabled"):
                if type(v) is not bool:
                    return False
            elif k in {"zoom_factor", "base_sensitivity", "sensitivity_multiplier", "debounce_time"}:
                if not _number(v, 0.001, 1000):
                    return False
            elif k in {"hotkey", "primary_hotkey", "secondary_hotkey", "trigger_mode", "sync_trigger_key"}:
                if not isinstance(v, str):
                    return False
    if key == "hud_rules":
        # The HUD normalizer accepts partial/extended rules; known containers must
        # retain their shape so both preview and runtime can inspect them safely.
        for k in ("key_rules", "weapon_rules", "event_rules"):
            if k in value and not isinstance(value[k], dict):
                return False
    return True


def validate_payload(payload, allowed):
    errors = []
    for key, value in payload.items():
        if key not in allowed:
            continue  # Preserved v1 behavior: unrecognized keys are never applied.
        valid = _json_value(value)
        if key in _RANGES:
            valid = valid and _number(value, *_RANGES[key])
        elif key in {"flash_image_position", "flash_image_size"}:
            valid = (valid and isinstance(value, (list, tuple)) and len(value) == 2
                     and all(_number(v, 0, 1) for v in value))
        elif key in _CONTAINERS:
            valid = valid and isinstance(value, _CONTAINERS[key]) and _nested_valid(key, value)
        elif key.endswith("_enabled") or key in _BOOL_KEYS:
            valid = valid and type(value) is bool
        else:
            valid = valid and isinstance(value, str) and len(value) <= 1024
        if not valid:
            errors.append(f"{key}: 设置值的类型、范围或结构无效")
    return errors
