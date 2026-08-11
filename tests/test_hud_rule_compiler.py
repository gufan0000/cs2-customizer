# SPDX-License-Identifier: GPL-3.0-or-later
from core.hud.rule_compiler import (
    compile_cfg_rules,
    get_cfg_paths,
)
from core.hud.rule_model import get_default_hud_rules


class _Cfg:
    pass


def _build_config_obj():
    cfg = _Cfg()
    cfg.hud_rules_enabled = True
    cfg.hud_rules_profile = "balanced_default"
    cfg.hud_runtime_sync_mode = "safe"
    cfg.hud_rules = get_default_hud_rules("balanced_default")
    cfg.crosshair_reset_enabled = False
    return cfg


def test_compile_cfg_rules_contains_key_bind_and_alias():
    cfg = _build_config_obj()

    # Disable runtime rules and only keep numeric key mapping.
    for key in cfg.hud_rules["event_rules"]:
        cfg.hud_rules["event_rules"][key]["enabled"] = False
    for key in cfg.hud_rules["state_rules"]:
        cfg.hud_rules["state_rules"][key]["enabled"] = False

    cfg.hud_rules["key_rules"]["1"]["enabled"] = True
    cfg.hud_rules["key_rules"]["1"]["color"] = 8

    lines = compile_cfg_rules(cfg)
    assert any("alias fp_hud_slot_1" in line for line in lines)
    assert any('bind 1 "fp_hud_slot_1"' in line for line in lines)
    assert not any("exec cs2customizer_hud_runtime.cfg" in line for line in lines)


def test_compile_cfg_rules_contains_refresh_proxy_when_runtime_enabled():
    cfg = _build_config_obj()
    lines = compile_cfg_rules(cfg)

    for key in ("w", "s", "a", "d"):
        assert any(
            f"alias +fp_hud_{key}" in line and "exec cs2customizer_hud_runtime.cfg" in line
            for line in lines
        ), f"+alias {key} missing"
        assert any(
            f"alias -fp_hud_{key}" in line and "exec cs2customizer_hud_runtime.cfg" in line
            for line in lines
        ), f"-alias {key} missing"
        assert any(f"bind {key} +fp_hud_{key}" in line for line in lines), f"bind {key} missing"

    assert any('alias +fp_hud_a "+left; exec cs2customizer_hud_runtime.cfg"' == line for line in lines)
    assert any('alias +fp_hud_d "+right; exec cs2customizer_hud_runtime.cfg"' == line for line in lines)

    assert any(
        "alias +fp_hud_mouse1" in line and "exec cs2customizer_hud_runtime.cfg" in line
        for line in lines
    )
    assert any(
        "alias -fp_hud_mouse1" in line and "exec cs2customizer_hud_runtime.cfg" in line
        for line in lines
    )
    assert any("bind mouse1 +fp_hud_mouse1" in line for line in lines)


def test_compile_cfg_rules_mouse1_merges_crosshair_reset():
    cfg = _build_config_obj()
    cfg.crosshair_reset_enabled = True
    lines = compile_cfg_rules(cfg)

    mouse1_plus = [line for line in lines if "alias +fp_hud_mouse1" in line]
    assert len(mouse1_plus) == 1
    assert "cl_crosshair_recoil 1" in mouse1_plus[0]

    mouse1_minus = [line for line in lines if "alias -fp_hud_mouse1" in line]
    assert len(mouse1_minus) == 1
    assert "cl_crosshair_recoil 0" in mouse1_minus[0]
    assert "cl_crosshair_recoil 0" in lines


def test_get_cfg_paths():
    cs2customizer_cfg, runtime_cfg = get_cfg_paths(r"C:\cs2")
    assert cs2customizer_cfg.endswith(r"game\csgo\cfg\cs2customizer.cfg")
    assert runtime_cfg.endswith(r"game\csgo\cfg\cs2customizer_hud_runtime.cfg")
