from __future__ import annotations

import os
from pathlib import Path

from config import config
from core.resource_health import (
    apply_conservative_resource_fix,
    collect_visual_resource_health,
)
from resource_manager import ResourceManager


VISUAL_RESOURCE_DIRS = [
    "resources/kill_icons",
    "resources/flash_images",
    "resources/flash_audio",
    "resources/utility_guides",
    "resources/crosshair",
]


def _patch_appdata(monkeypatch, tmp_path):
    def fake_get_app_data_path(relative_path):
        rel = relative_path.replace("/", os.sep).replace("\\", os.sep)
        return str(tmp_path / rel)

    monkeypatch.setattr(ResourceManager, "get_app_data_path", staticmethod(fake_get_app_data_path))


def _make_visual_roots(tmp_path):
    for rel in VISUAL_RESOURCE_DIRS:
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)


def _patch_visual_config_defaults(monkeypatch):
    monkeypatch.setattr(config, "death_sound_style", "0", raising=False)
    monkeypatch.setattr(config, "grenade_sound_styles", {}, raising=False)
    monkeypatch.setattr(config, "c4_sound_style", "0", raising=False)
    monkeypatch.setattr(config, "health_warning_style", "0", raising=False)
    monkeypatch.setattr(config, "round_start_style", "0", raising=False)
    monkeypatch.setattr(config, "round_action_style", "0", raising=False)
    monkeypatch.setattr(config, "round_win_style", "0", raising=False)
    monkeypatch.setattr(config, "round_lose_style", "0", raising=False)
    monkeypatch.setattr(config, "round_mvp_style", "0", raising=False)
    monkeypatch.setattr(config, "weapon_switch_sounds", {}, raising=False)
    monkeypatch.setattr(config, "weapon_reload_sounds", {}, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_style", "0", raising=False)
    monkeypatch.setattr(config, "flash_enabled", False, raising=False)
    monkeypatch.setattr(config, "flash_image_style", "none", raising=False)
    monkeypatch.setattr(config, "flash_audio_enabled", False, raising=False)
    monkeypatch.setattr(config, "flash_audio_style", "none", raising=False)
    monkeypatch.setattr(config, "crosshair_enabled", False, raising=False)
    monkeypatch.setattr(config, "crosshair_style", "default", raising=False)
    monkeypatch.setattr(config, "crosshair_custom_data", [], raising=False)
    monkeypatch.setattr(config, "utility_guide_enabled", False, raising=False)


def test_collect_visual_resource_health_ignores_disabled_missing_styles(tmp_path, monkeypatch):
    _patch_appdata(monkeypatch, tmp_path)
    _make_visual_roots(tmp_path)
    _patch_visual_config_defaults(monkeypatch)

    monkeypatch.setattr(config, "kill_icon_style", "missing_style", raising=False)
    monkeypatch.setattr(config, "flash_image_style", "missing_style", raising=False)
    monkeypatch.setattr(config, "flash_audio_style", "missing_style", raising=False)

    report = collect_visual_resource_health()

    assert report["summary"]["ok"] is True
    assert report["summary"]["missing_directories"] == 0
    assert report["summary"]["invalid_config_refs"] == 0


def test_collect_visual_resource_health_reports_enabled_missing_flash_audio_style(tmp_path, monkeypatch):
    _patch_appdata(monkeypatch, tmp_path)
    _make_visual_roots(tmp_path)
    _patch_visual_config_defaults(monkeypatch)

    monkeypatch.setattr(config, "flash_audio_enabled", True, raising=False)
    monkeypatch.setattr(config, "flash_audio_style", "style_missing", raising=False)

    report = collect_visual_resource_health()

    assert report["summary"]["ok"] is False
    assert report["summary"]["invalid_config_refs"] == 1
    assert report["invalid_config_refs"][0]["key"] == "flash_audio_style"


def test_apply_conservative_resource_fix_creates_visual_directories(tmp_path, monkeypatch):
    _patch_appdata(monkeypatch, tmp_path)
    _patch_visual_config_defaults(monkeypatch)

    monkeypatch.setattr(
        "core.resource_health.apply_conservative_audio_fix",
        lambda: {
            "snapshot_id": "",
            "created_directories": [],
            "reset_config_keys": [],
            "before": {"summary": {"ok": True}},
            "after": {"summary": {"ok": True}},
        },
    )

    result = apply_conservative_resource_fix()

    created_visual_directories = set(result.get("created_visual_directories", []))
    expected_roots = {
        str(tmp_path / "resources" / "crosshair"),
        str(tmp_path / "resources" / "flash_audio"),
        str(tmp_path / "resources" / "flash_images"),
        str(tmp_path / "resources" / "kill_icons"),
        str(tmp_path / "resources" / "utility_guides"),
    }

    assert expected_roots.issubset(created_visual_directories)
    for path in expected_roots:
        assert Path(path).is_dir()


def test_ensure_flash_audio_directory_does_not_create_default_style(tmp_path, monkeypatch):
    _patch_appdata(monkeypatch, tmp_path)

    flash_audio_root = Path(ResourceManager.ensure_flash_audio_directory())

    assert flash_audio_root.is_dir()
    assert not (flash_audio_root / "default").exists()
