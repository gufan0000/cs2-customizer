from __future__ import annotations

from core.presets import preset_center


def test_preset_center_export_validate_apply(monkeypatch):
    monkeypatch.setattr(preset_center.config, "save_config_now", lambda: None, raising=False)
    monkeypatch.setattr(preset_center.config, "config_snapshot_auto_before_risky_ops", False, raising=False)

    monkeypatch.setattr(preset_center.config, "hud_rules_enabled", True, raising=False)
    monkeypatch.setattr(preset_center.config, "hud_rules_profile", "balanced_default", raising=False)
    monkeypatch.setattr(preset_center.config, "hud_rules", {"k": 1}, raising=False)
    monkeypatch.setattr(preset_center.config, "hud_runtime_sync_mode", "safe", raising=False)
    monkeypatch.setattr(preset_center.config, "hud_runtime_refresh_key", "w", raising=False)
    monkeypatch.setattr(preset_center.config, "hud_keymap_enabled", {"1": True}, raising=False)

    monkeypatch.setattr(preset_center.config, "screen_effects_enabled", True, raising=False)
    monkeypatch.setattr(preset_center.config, "screen_edge_flash_enabled", True, raising=False)
    monkeypatch.setattr(preset_center.config, "screen_effects_preset", "impact_sparks", raising=False)
    monkeypatch.setattr(preset_center.config, "screen_effects_play_mode", "streak", raising=False)

    monkeypatch.setattr(preset_center.config, "grenade_sound_enabled", True, raising=False)
    monkeypatch.setattr(preset_center.config, "grenade_sound_styles", {"hegrenade": "x"}, raising=False)
    monkeypatch.setattr(preset_center.config, "c4_sound_enabled", True, raising=False)
    monkeypatch.setattr(preset_center.config, "c4_sound_style", "x", raising=False)
    monkeypatch.setattr(preset_center.config, "health_warning_enabled", True, raising=False)
    monkeypatch.setattr(preset_center.config, "health_warning_style", "x", raising=False)
    monkeypatch.setattr(preset_center.config, "health_warning_threshold", 20, raising=False)
    monkeypatch.setattr(preset_center.config, "round_sound_enabled", True, raising=False)
    monkeypatch.setattr(preset_center.config, "round_start_style", "x", raising=False)
    monkeypatch.setattr(preset_center.config, "round_action_style", "x", raising=False)
    monkeypatch.setattr(preset_center.config, "round_win_style", "x", raising=False)
    monkeypatch.setattr(preset_center.config, "round_lose_style", "x", raising=False)
    monkeypatch.setattr(preset_center.config, "round_mvp_style", "x", raising=False)

    bundle = preset_center.export_bundle(["hud_rules", "screen_effects", "special_sound"])
    validation = preset_center.validate_bundle(bundle)
    assert validation.ok is True

    result = preset_center.apply_bundle(bundle, mode="merge")
    assert result.ok is True
    assert "hud_rules" in result.applied_types
    assert "screen_effects" in result.applied_types
    assert "special_sound" in result.applied_types

