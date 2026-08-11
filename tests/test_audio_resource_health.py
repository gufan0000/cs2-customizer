import os

from config import config
from core.audio.audio_resource_health import (
    apply_conservative_audio_fix,
    collect_audio_resource_health,
)
from resource_manager import ResourceManager


REQUIRED_AUDIO_DIRS = [
    "kill_sounds",
    "kill_voices",
    "weapon_kill_sounds",
    "weapon_kill_voices",
    "death",
    "switch_weapons",
    "reload_sounds",
    "grenade_sounds",
    "c4_sounds",
    "health_warning",
    "round_sounds",
    "gun_sounds",
]


def _make_audio_root(tmp_path):
    audio_root = tmp_path / "resources" / "audio"
    for rel in REQUIRED_AUDIO_DIRS:
        (audio_root / rel).mkdir(parents=True, exist_ok=True)
    return audio_root


def _patch_config_zero(monkeypatch):
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


def _patch_appdata(monkeypatch, tmp_path):
    def fake_get_app_data_path(relative_path):
        rel = relative_path.replace("/", os.sep).replace("\\", os.sep)
        return str(tmp_path / rel)

    monkeypatch.setattr(ResourceManager, "get_app_data_path", staticmethod(fake_get_app_data_path))


def test_collect_audio_resource_health_ok(tmp_path, monkeypatch):
    audio_root = _make_audio_root(tmp_path)
    _patch_appdata(monkeypatch, tmp_path)
    _patch_config_zero(monkeypatch)

    report = collect_audio_resource_health()
    assert report["summary"]["ok"] is True
    assert report["summary"]["missing_directories"] == 0
    assert report["summary"]["invalid_config_refs"] == 0
    assert str(audio_root) == report["audio_root"]


def test_collect_audio_resource_health_detects_invalid_style(tmp_path, monkeypatch):
    _make_audio_root(tmp_path)
    _patch_appdata(monkeypatch, tmp_path)
    _patch_config_zero(monkeypatch)
    monkeypatch.setattr(config, "death_sound_style", "missing_style", raising=False)

    report = collect_audio_resource_health()
    assert report["summary"]["ok"] is False
    assert report["summary"]["invalid_config_refs"] >= 1
    assert any(issue["key"] == "death_sound_style" for issue in report["invalid_config_refs"])


def test_apply_conservative_audio_fix_creates_dirs_and_resets_invalid_refs(tmp_path, monkeypatch):
    # keep only audio root created; required sub-dirs are missing
    (tmp_path / "resources" / "audio").mkdir(parents=True, exist_ok=True)
    _patch_appdata(monkeypatch, tmp_path)

    # make one invalid config ref
    monkeypatch.setattr(config, "death_sound_style", "bad_style", raising=False)
    monkeypatch.setattr(config, "grenade_sound_styles", {}, raising=False)
    monkeypatch.setattr(config, "weapon_switch_sounds", {}, raising=False)
    monkeypatch.setattr(config, "weapon_reload_sounds", {}, raising=False)

    saved = {"called": False}

    def fake_save_now():
        saved["called"] = True

    monkeypatch.setattr(config, "save_config_now", fake_save_now, raising=False)

    rescanned = {"called": False}

    class _FakeManager:
        _styles_scanned = True

        def ensure_styles_scanned(self):
            rescanned["called"] = True

    # patch runtime manager import target inside function
    import core.audio.runtime_audio as runtime_audio

    monkeypatch.setattr(runtime_audio, "get_runtime_audio_manager", lambda: _FakeManager(), raising=False)

    result = apply_conservative_audio_fix()

    assert saved["called"] is True
    assert rescanned["called"] is True
    assert isinstance(result.get("created_directories"), list)
    assert "death_sound_style" in result.get("reset_config_keys", [])

    # required dirs should exist after fix
    audio_root = tmp_path / "resources" / "audio"
    for rel in REQUIRED_AUDIO_DIRS:
        assert (audio_root / rel).is_dir()

    assert str(getattr(config, "death_sound_style", "")) == "0"
    assert result.get("after", {}).get("summary", {}).get("ok") in (True, False)


# ---------- v2.2.1: 完整性检查 + GSI cfg 组件自检 ----------

def test_incomplete_kill_style_reports_missing_levels(tmp_path, monkeypatch):
    """风格目录存在但缺 3/4 连杀文件时，体检应报告缺失档位。"""
    audio_root = _make_audio_root(tmp_path)
    _patch_appdata(monkeypatch, tmp_path)
    _patch_config_zero(monkeypatch)

    style_dir = audio_root / "kill_sounds" / "mystyle"
    style_dir.mkdir(parents=True)
    for level in (1, 2, 5):
        (style_dir / f"{level}.mp3").write_bytes(b"x")

    monkeypatch.setattr(config, "weapon_kill_sounds", {"weapon_ak47": "mystyle"}, raising=False)
    monkeypatch.setattr(config, "weapon_kill_voices", {}, raising=False)

    report = collect_audio_resource_health()
    incomplete = report["incomplete_styles"]
    assert len(incomplete) == 1
    assert incomplete[0]["missing_levels"] == [3, 4]
    assert "weapon_kill_sounds.weapon_ak47" in incomplete[0]["referenced_by"]
    # 完整性问题是提示性的，不应把 ok 打成 False
    assert report["summary"]["ok"] is True


def test_complete_kill_style_not_reported(tmp_path, monkeypatch):
    audio_root = _make_audio_root(tmp_path)
    _patch_appdata(monkeypatch, tmp_path)
    _patch_config_zero(monkeypatch)

    style_dir = audio_root / "kill_sounds" / "full"
    style_dir.mkdir(parents=True)
    for level in (1, 2, 3, 4, 5):
        (style_dir / f"{level}.mp3").write_bytes(b"x")

    monkeypatch.setattr(config, "weapon_kill_sounds", {"weapon_awp": "full"}, raising=False)
    monkeypatch.setattr(config, "weapon_kill_voices", {}, raising=False)

    report = collect_audio_resource_health()
    assert report["incomplete_styles"] == []


def test_gsi_cfg_check_reports_missing_match_stats(tmp_path, monkeypatch):
    from core.audio.audio_resource_health import check_gsi_cfg_match_stats

    cfg_dir = tmp_path / "game" / "csgo" / "cfg"
    cfg_dir.mkdir(parents=True)
    cfg_path = cfg_dir / "gamestate_integration_cs2customizer.cfg"
    cfg_path.write_text('"data" { "player_state" "1" }', encoding="utf-8")

    monkeypatch.setattr(config, "csgo_dir", str(tmp_path), raising=False)
    result = check_gsi_cfg_match_stats()
    assert result["status"] == "missing_match_stats"

    cfg_path.write_text('"data" { "player_match_stats" "1" }', encoding="utf-8")
    assert check_gsi_cfg_match_stats()["status"] == "ok"


def test_gsi_cfg_check_handles_unconfigured_dir(monkeypatch):
    from core.audio.audio_resource_health import check_gsi_cfg_match_stats

    monkeypatch.setattr(config, "csgo_dir", "", raising=False)
    assert check_gsi_cfg_match_stats()["status"] == "not_configured"
