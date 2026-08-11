from config import Config


def test_migrate_legacy_hud_fields_to_unified_rules():
    cfg = Config()
    cfg.hud_color_enabled = True
    cfg.hud_color_static = 2
    cfg.hud_color_refresh_key = "a"
    cfg.hud_color_kill_duration = 1.2
    cfg.hud_color_headshot_duration = 0.8
    cfg.hud_color_multi_kill_duration = 2.0
    cfg.hud_color_death_duration = 1.5
    cfg.hud_color_low_health_threshold = 35
    cfg.hud_color_dynamic_map = {
        "default": {"color": 3, "effect": "solid", "alt_color": -1},
        "kill": {"color": 8, "effect": "flash", "alt_color": 7},
        "headshot_kill": {"color": 7, "effect": "flash", "alt_color": 1},
        "multi_kill": {"color": 6, "effect": "blink", "alt_color": 5},
        "death": {"color": 5, "effect": "solid", "alt_color": -1},
        "low_health": {"color": 5, "effect": "blink", "alt_color": 6},
        "bomb_planted": {"color": 6, "effect": "pulse", "alt_color": 5},
    }

    # 传入不含 hud_rules 的 config_data，触发 legacy 迁移路径
    cfg.migrate_hud_legacy_to_rules(config_data={})

    assert cfg.hud_rules_enabled is True
    assert cfg.hud_runtime_refresh_key == "a"
    assert cfg.hud_rules["default_color"] == 3
    assert cfg.hud_rules["event_rules"]["kill"]["enabled"] is True
    assert cfg.hud_rules["event_rules"]["kill"]["main"] == 8
    assert cfg.hud_rules["event_rules"]["kill"]["duration_ms"] == 1200
    assert cfg.hud_rules["event_rules"]["low_health"]["threshold"] == 35


def test_migrate_with_existing_new_rules_only_normalizes():
    cfg = Config()
    cfg.hud_rules_profile = "unknown_profile"
    cfg.hud_runtime_refresh_key = "invalid"
    cfg.hud_rules = {
        "version": 1,
        "default_color": 0,
        "key_rules": {"1": {"enabled": True, "color": 8}},
        "event_rules": {
            "kill": {"enabled": True, "effect": "flash", "main": 8, "alt": 7, "duration_ms": 400},
        },
        "state_rules": {},
    }

    cfg.migrate_hud_legacy_to_rules(config_data={"hud_rules": {}})

    assert cfg.hud_rules_profile == "balanced_default"
    assert cfg.hud_runtime_refresh_key == "w"
    assert cfg.hud_rules["key_rules"]["1"]["enabled"] is True

