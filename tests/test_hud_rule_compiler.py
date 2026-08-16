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

    # 开火键的 alias 名统一成 quickrepos_attack（原来 HUD 路径自己叫
    # fp_hud_mouse1，两条路径各绑各的，切换 HUD 开关会留下 stale bind）。
    # 老名字仍会被定义成直通，见 core/crosshair_reset.LEGACY_ALIASES。
    assert any(
        "alias +quickrepos_attack " in line and "exec cs2customizer_hud_runtime.cfg" in line
        for line in lines
    )
    assert any(
        "alias -quickrepos_attack " in line and "exec cs2customizer_hud_runtime.cfg" in line
        for line in lines
    )
    assert any("bind mouse1 +quickrepos_attack" in line for line in lines)


def test_compile_cfg_rules_attack_key_merges_crosshair_reset():
    cfg = _build_config_obj()
    cfg.crosshair_reset_enabled = True
    lines = compile_cfg_rules(cfg)

    plus = [line for line in lines if line.startswith("alias +quickrepos_attack ")]
    assert len(plus) == 1
    assert "cl_crosshair_recoil 1" in plus[0]
    assert "exec cs2customizer_hud_runtime.cfg" in plus[0]

    minus = [line for line in lines if line.startswith("alias -quickrepos_attack ")]
    assert len(minus) == 1
    assert "cl_crosshair_recoil 0" in minus[0]
    assert "cl_crosshair_recoil 0" in lines


def test_compile_cfg_rules_defines_legacy_alias_as_passthrough():
    """老 alias 名必须有定义，否则残留的 bind 会把开火键变成死键。"""
    for reset in (False, True):
        cfg = _build_config_obj()
        cfg.crosshair_reset_enabled = reset
        lines = compile_cfg_rules(cfg)
        legacy = [line for line in lines if line.startswith("alias +fp_hud_mouse1 ")]
        assert len(legacy) == 1
        assert "+attack" in legacy[0]
        # 直通不带回正层：万一它被用上，代价只是"少了回正"，不是开不了枪
        assert "cl_crosshair_recoil" not in legacy[0]


def test_get_cfg_paths():
    cs2customizer_cfg, runtime_cfg = get_cfg_paths(r"C:\cs2")
    assert cs2customizer_cfg.endswith(r"game\csgo\cfg\cs2customizer.cfg")
    assert runtime_cfg.endswith(r"game\csgo\cfg\cs2customizer_hud_runtime.cfg")
