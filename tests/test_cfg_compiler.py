from core.cfg_compiler import (
    check_bind_conflicts,
    compile_all,
    compile_hud_rules,
    compile_magnifier_runtime,
    compile_viewmodel,
)
from core.hud.rule_model import get_default_hud_rules


class _Cfg:
    pass


def _build_config_obj():
    cfg = _Cfg()
    cfg.csgo_dir = r"C:\cs2"
    cfg.hud_rules_enabled = True
    cfg.hud_rules_profile = "balanced_default"
    cfg.hud_runtime_sync_mode = "safe"
    cfg.hud_rules = get_default_hud_rules("balanced_default")
    cfg.crosshair_reset_enabled = True
    cfg.viewmodel_presets = [
        {"name": "预设1", "key": "F5", "fov": 68, "x": 2.0, "y": 2.0, "z": -1.0},
        {"name": "预设2", "key": "F6", "fov": 54, "x": -2.0, "y": -2.0, "z": -2.0},
    ]
    cfg.viewmodel_cycle_key = "CAPSLOCK"
    cfg.magnifier = {
        "sensitivity_sync_enabled": False,
        "base_sensitivity": 1.0,
        "sensitivity_multiplier": 0.82,
        "sync_trigger_key": "SCROLLLOCK",
    }
    return cfg


def test_compile_all_contains_all_sections():
    cfg = _build_config_obj()
    content, warnings = compile_all(cfg)
    assert "// CS2 Customizer CFG配置文件" in content
    assert "// -- Viewmodel Settings (CS2 Customizer) --" in content
    assert "// -- HUD Rules Begin (CS2 Customizer) --" in content
    assert 'CS2 Customizer CFG配置文件已加载' in content


def test_compile_all_idempotent():
    cfg = _build_config_obj()
    content1, _ = compile_all(cfg)
    content2, _ = compile_all(cfg)
    assert content1 == content2


def test_bind_conflict_detection():
    """不同 section 绑定同一按键时应检测到冲突"""
    cfg = _build_config_obj()
    cfg.magnifier["sensitivity_sync_enabled"] = True
    cfg.magnifier["sync_trigger_key"] = "9"
    cfg.hud_rules["key_rules"]["9"]["enabled"] = True
    cfg.hud_rules["key_rules"]["9"]["color"] = 5

    sections = {
        "magnifier_runtime": compile_magnifier_runtime(cfg),
        "hud_rules": compile_hud_rules(cfg),
    }
    warnings = check_bind_conflicts(sections)
    assert any("9" in w for w in warnings)


def test_viewmodel_disabled_crosshair_no_mouse1():
    cfg = _build_config_obj()
    cfg.crosshair_reset_enabled = False
    cfg.hud_rules_enabled = False
    content = compile_viewmodel(cfg)
    assert "mouse1" not in content


def test_hud_rules_disabled_no_output():
    cfg = _build_config_obj()
    cfg.hud_rules_enabled = False
    content = compile_hud_rules(cfg)
    assert content == ""


def test_no_conflicts_in_default_config():
    cfg = _build_config_obj()
    _, warnings = compile_all(cfg)
    assert warnings == []


def test_viewmodel_skips_mouse1_when_hud_runtime_active():
    """HUD 运行时刷新启用时，viewmodel 不应单独 bind mouse1"""
    cfg = _build_config_obj()
    cfg.crosshair_reset_enabled = True
    cfg.hud_rules_enabled = True
    viewmodel_content = compile_viewmodel(cfg)
    assert "bind mouse1" not in viewmodel_content
    # HUD rules 段应包含合并后的 mouse1
    hud_content = compile_hud_rules(cfg)
    assert "bind mouse1" in hud_content
    assert "cl_crosshair_recoil" in hud_content


def test_viewmodel_has_mouse1_when_hud_disabled():
    """HUD 关闭时，viewmodel 应正常输出准心回正 mouse1 bind"""
    cfg = _build_config_obj()
    cfg.crosshair_reset_enabled = True
    cfg.hud_rules_enabled = False
    viewmodel_content = compile_viewmodel(cfg)
    assert "bind mouse1 +quickrepos_attack" in viewmodel_content


def test_compile_magnifier_runtime_when_enabled():
    cfg = _build_config_obj()
    cfg.magnifier["sensitivity_sync_enabled"] = True
    cfg.magnifier["sync_trigger_key"] = "SCROLLLOCK"

    content = compile_magnifier_runtime(cfg)

    assert "// -- Magnifier Sensitivity Sync (CS2 Customizer) --" in content
    assert 'bind SCROLLLOCK "exec cs2customizer_magnifier_runtime.cfg"' in content


def test_compile_magnifier_runtime_skips_when_disabled():
    cfg = _build_config_obj()
    cfg.magnifier["sensitivity_sync_enabled"] = False

    assert compile_magnifier_runtime(cfg) == ""
