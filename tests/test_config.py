# SPDX-License-Identifier: GPL-3.0-or-later
"""
Config 模块基础测试
"""

from __future__ import annotations

import json

import pytest

from config import Config


class TestConfigSaveLoad:
    def test_default_values(self):
        cfg = Config()
        assert hasattr(cfg, "kill_sound_enabled")
        assert hasattr(cfg, "mode")
        assert hasattr(cfg, "volume")

    def test_save_load_roundtrip(self, tmp_path):
        config_file = tmp_path / "config.json"

        cfg1 = Config()
        cfg1.kill_sound_enabled = False
        cfg1.mode = "3. 死斗模式"
        cfg1.volume = 0.5

        data = {
            "kill_sound_enabled": cfg1.kill_sound_enabled,
            "mode": cfg1.mode,
            "volume": cfg1.volume,
        }
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        cfg2 = Config()
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        cfg2.kill_sound_enabled = config_data.get("kill_sound_enabled", True)
        cfg2.mode = config_data.get("mode", "1. 官匹竞技")
        cfg2.volume = config_data.get("volume", 0.7)

        assert cfg2.kill_sound_enabled is False
        assert cfg2.mode == "3. 死斗模式"
        assert cfg2.volume == 0.5

    def test_debounce_save_config_now(self):
        cfg = Config()
        try:
            cfg.save_config_now()
        except Exception as exc:
            pytest.fail(f"save_config_now raised {exc}")

    def test_gun_sound_master_migrates_from_legacy_flags(self):
        cfg = Config()
        cfg.gun_sound_enabled = False
        cfg.awp_enabled = True

        cfg._normalize_gun_sound_config({})

        assert cfg.gun_sound_enabled is True
        assert cfg.deagle_enabled is True

    def test_gun_sound_master_false_syncs_legacy_flags(self):
        cfg = Config()
        cfg.gun_sound_enabled = False
        cfg.awp_enabled = True
        cfg.deagle_enabled = True

        cfg._normalize_gun_sound_config({"gun_sound_enabled": False})

        assert cfg.awp_enabled is False
        assert cfg.deagle_enabled is False

    def test_gun_sound_ducking_defaults_are_initialized(self):
        cfg = Config()

        assert cfg.gun_sound_ducking_enabled is True
        assert cfg.gun_sound_duck_ratio == pytest.approx(0.18)
        assert cfg.gun_sound_duck_attack_ms == 0
        assert cfg.gun_sound_duck_release_ms == 120
        assert cfg.gun_sound_duck_fallback_hotkey_mode is True
        assert cfg.gun_sound_duck_target_processes == ["cs2.exe", "csgo.exe"]

    def test_gun_sound_ducking_normalization_clamps_invalid_values(self):
        cfg = Config()
        cfg.gun_sound_duck_ratio = 2.5
        cfg.gun_sound_duck_attack_ms = -10
        cfg.gun_sound_duck_release_ms = "3000"
        cfg.gun_sound_duck_target_processes = [" ", "", "cs2.exe"]

        cfg._normalize_gun_sound_ducking_config({})

        assert cfg.gun_sound_duck_ratio == pytest.approx(1.0)
        assert cfg.gun_sound_duck_attack_ms == 0
        assert cfg.gun_sound_duck_release_ms == 2000
        assert cfg.gun_sound_duck_target_processes == ["cs2.exe"]

    def test_new_gun_sound_profiles_are_initialized_and_normalized(self):
        cfg = Config()
        cfg.ak47_style = "不启用"
        cfg.ak47_mute_duration = "0.35"
        cfg.ak47_enabled = 1

        cfg._normalize_gun_sound_config({})

        assert cfg.ak47_style == "0"
        assert cfg.ak47_mute_duration == pytest.approx(0.35)
        assert cfg.ak47_enabled is True
