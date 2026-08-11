"""
HUD rules compiler: unified rules -> CS cfg content.
"""

from __future__ import annotations

import os
import tempfile

from core.hud.rule_model import (
    has_runtime_enabled_rules,
    is_valid_hud_color,
    normalize_hud_rules,
)


HUD_RULES_BEGIN = "// -- HUD Rules Begin (CS2 Customizer) --"
HUD_RULES_END = "// -- HUD Rules End (CS2 Customizer) --"


def compile_cfg_rules(config_obj):
    """
    Compile configurable HUD rules into cs2customizer.cfg lines.
    Static rules (default color, key slot mappings) + multi-key refresh.

    Uses multi-command bind (not alias) so CS2 settings UI can still
    recognize the original action (e.g. +forward) in the bind.
    """
    if not getattr(config_obj, "hud_rules_enabled", False):
        return []

    rules = normalize_hud_rules(
        getattr(config_obj, "hud_rules", {}),
        profile=getattr(config_obj, "hud_rules_profile", "balanced_default"),
    )
    lines = []

    default_color = rules.get("default_color", -1)
    if is_valid_hud_color(default_color):
        lines.append(f"cl_hud_color {default_color}")

    key_rules = rules.get("key_rules", {})
    for i in range(1, 10):
        key = str(i)
        entry = key_rules.get(key, {})
        enabled = bool(entry.get("enabled", False))
        color = entry.get("color", -1)
        if enabled and is_valid_hud_color(color):
            alias_name = f"fp_hud_slot_{key}"
            lines.append(f'alias {alias_name} "slot{i}; cl_hud_color {color}"')
            lines.append(f'bind {key} "{alias_name}"')

    runtime_mode = getattr(config_obj, "hud_runtime_sync_mode", "safe")
    if runtime_mode == "safe" and has_runtime_enabled_rules(rules):
        # W/S/A alias 代理刷新（按下+释放都 exec）
        # 注意：不能同时 alias WASD 四键，CS2 会检测到移动键全部被覆盖后
        # 自动重分配到 IJKL，导致 A/D 失效。保留 D 不 alias。
        move_keys = {
            "w": "+forward",
            "s": "+back",
            # CS2 keyboard side-move commands are +left / +right.
            "a": "+left",
            "d": "+right",
        }
        for key, action in move_keys.items():
            minus_action = action.replace("+", "-")
            alias = f"fp_hud_{key}"
            lines.append(f'alias +{alias} "{action}; exec cs2customizer_hud_runtime.cfg"')
            lines.append(f'alias -{alias} "{minus_action}; exec cs2customizer_hud_runtime.cfg"')
            lines.append(f"bind {key} +{alias}")

        # mouse1 alias 代理刷新（按下+释放都 exec）
        crosshair_reset = getattr(config_obj, "crosshair_reset_enabled", False)
        if crosshair_reset:
            lines.append(
                'alias +fp_hud_mouse1 "+attack;'
                " cl_crosshair_recoil 1;"
                ' exec cs2customizer_hud_runtime.cfg"'
            )
            lines.append(
                'alias -fp_hud_mouse1 "-attack;'
                " cl_crosshair_recoil 0;"
                ' exec cs2customizer_hud_runtime.cfg"'
            )
            lines.append("bind mouse1 +fp_hud_mouse1")
            lines.append("cl_crosshair_recoil 0")
        else:
            lines.append(
                'alias +fp_hud_mouse1 "+attack;'
                ' exec cs2customizer_hud_runtime.cfg"'
            )
            lines.append(
                'alias -fp_hud_mouse1 "-attack;'
                ' exec cs2customizer_hud_runtime.cfg"'
            )
            lines.append("bind mouse1 +fp_hud_mouse1")

    return lines


def has_hud_runtime_refresh(config_obj) -> bool:
    """Check if HUD rules will generate runtime refresh key bindings."""
    if not getattr(config_obj, "hud_rules_enabled", False):
        return False
    rules = normalize_hud_rules(
        getattr(config_obj, "hud_rules", {}),
        profile=getattr(config_obj, "hud_rules_profile", "balanced_default"),
    )
    runtime_mode = getattr(config_obj, "hud_runtime_sync_mode", "safe")
    return runtime_mode == "safe" and has_runtime_enabled_rules(rules)


def build_hud_rules_block(lines):
    if not lines:
        return ""
    return "\n".join([HUD_RULES_BEGIN, *lines, HUD_RULES_END]).strip() + "\n"


def get_cfg_paths(csgo_dir):
    if not csgo_dir:
        return None, None
    cfg_base = os.path.join(csgo_dir, "game", "csgo", "cfg")
    return (
        os.path.join(cfg_base, "cs2customizer.cfg"),
        os.path.join(cfg_base, "cs2customizer_hud_runtime.cfg"),
    )


def get_initial_runtime_color(config_obj):
    rules = normalize_hud_rules(
        getattr(config_obj, "hud_rules", {}),
        profile=getattr(config_obj, "hud_rules_profile", "balanced_default"),
    )
    default_color = rules.get("default_color", 0)
    if is_valid_hud_color(default_color):
        return default_color
    return 0


def write_runtime_cfg(runtime_cfg_path, color):
    cfg_dir = os.path.dirname(runtime_cfg_path)
    os.makedirs(cfg_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=cfg_dir, prefix="hud_runtime_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if is_valid_hud_color(color):
                f.write(f"cl_hud_color {color}\n")
            else:
                f.write("// no hud override\n")
        os.replace(tmp_path, runtime_cfg_path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
