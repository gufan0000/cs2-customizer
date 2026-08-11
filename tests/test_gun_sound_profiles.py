from __future__ import annotations

import pytest

from core.gun_sound_profiles import (
    FULL_AUTO_GUN_SOUND_WEAPON_TYPES,
    GUN_SOUND_PROFILES,
    GUN_SOUND_WEAPON_TYPES,
    SUPPORTED_GUN_SOUND_WEAPON_TYPES,
    build_gun_sound_duck_plan,
    is_gun_sound_burst,
)


class _DummyConfig:
    gun_sound_duck_ratio = 0.18
    gun_sound_duck_release_ms = 120
    usp_mute_duration = 0.2
    awp_mute_duration = 0.5


def test_usp_burst_plan_is_more_aggressive_than_single():
    profile = GUN_SOUND_PROFILES["usp"]
    cfg = _DummyConfig()

    single = build_gun_sound_duck_plan(cfg, profile, is_burst=False, hold_duration=cfg.usp_mute_duration)
    burst = build_gun_sound_duck_plan(cfg, profile, is_burst=True, hold_duration=cfg.usp_mute_duration)

    assert burst.peak_ratio < single.peak_ratio
    assert burst.sustain_ratio < single.sustain_ratio
    assert burst.release_ms > single.release_ms
    assert burst.hold_duration > single.hold_duration


def test_awp_interval_is_not_misclassified_as_burst():
    profile = GUN_SOUND_PROFILES["awp"]

    assert is_gun_sound_burst(profile, 0.2) is True
    assert is_gun_sound_burst(profile, 0.8) is False


def test_registry_covers_all_supported_firearms_and_taser():
    expected = {
        "glock",
        "usp",
        "hkp2000",
        "p250",
        "fiveseven",
        "cz75a",
        "elite",
        "deagle",
        "revolver",
        "tec9",
        "mac10",
        "mp9",
        "mp7",
        "ump45",
        "p90",
        "bizon",
        "mp5sd",
        "ak47",
        "m4a1",
        "m4a1_silencer",
        "famas",
        "galilar",
        "aug",
        "sg556",
        "awp",
        "ssg08",
        "scar20",
        "g3sg1",
        "nova",
        "xm1014",
        "mag7",
        "sawedoff",
        "m249",
        "negev",
        "taser",
    }

    assert expected.issubset(set(GUN_SOUND_WEAPON_TYPES))
    assert GUN_SOUND_PROFILES["ak47"].display_name == "AK-47"
    assert GUN_SOUND_PROFILES["xm1014"].gsi_names == ("weapon_xm1014",)


def test_runtime_supported_gun_sound_profiles_hide_full_auto_weapons():
    assert "ak47" in FULL_AUTO_GUN_SOUND_WEAPON_TYPES
    assert "mp9" in FULL_AUTO_GUN_SOUND_WEAPON_TYPES
    assert "cz75a" in FULL_AUTO_GUN_SOUND_WEAPON_TYPES
    assert "ak47" not in SUPPORTED_GUN_SOUND_WEAPON_TYPES
    assert "mp9" not in SUPPORTED_GUN_SOUND_WEAPON_TYPES
    assert "cz75a" not in SUPPORTED_GUN_SOUND_WEAPON_TYPES
    assert "xm1014" in SUPPORTED_GUN_SOUND_WEAPON_TYPES
    assert "scar20" in SUPPORTED_GUN_SOUND_WEAPON_TYPES


@pytest.mark.parametrize("gun_type", ["usp", "deagle", "scar20", "g3sg1"])
def test_fast_fire_profiles_have_peak_ducking(gun_type: str):
    profile = GUN_SOUND_PROFILES[gun_type]
    cfg = _DummyConfig()
    setattr(cfg, profile.mute_duration_key, 0.25)

    plan = build_gun_sound_duck_plan(cfg, profile, is_burst=False, hold_duration=0.25)

    assert plan.peak_ratio <= plan.sustain_ratio
    assert plan.peak_ms > 0
