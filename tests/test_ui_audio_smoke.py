# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from config import config


def _visible_status_chip_texts(status_bar) -> list[str]:
    layout = status_bar.layout()
    if layout is None:
        return []
    texts = []
    for idx in range(layout.count()):
        item = layout.itemAt(idx)
        widget = item.widget() if item else None
        if (
            isinstance(widget, QLabel)
            and widget.objectName() == "audioStatusChip"
            and not widget.isHidden()
        ):
            texts.append(widget.text())
    return texts


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_audio_health_page_smoke(qapp, monkeypatch):
    import pages.audio_health_page as health_page_module

    report = {
        "audio": {"summary": {"ok": True}},
        "visual": {"summary": {"ok": True}},
        "summary": {
            "ok": True,
            "missing_directories": 0,
            "invalid_config_refs": 0,
            "empty_style_dirs": 0,
        }
    }

    monkeypatch.setattr(health_page_module, "collect_resource_system_health", lambda: report)
    monkeypatch.setattr(health_page_module, "format_resource_system_health", lambda _r: "health-ok")
    monkeypatch.setattr(
        health_page_module,
        "apply_conservative_resource_fix",
        lambda: {
            "before": report,
            "after": report,
            "created_visual_directories": [],
            "audio_fix": {
                "created_directories": [],
                "reset_config_keys": [],
            },
        },
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: 0)

    page = health_page_module.AudioHealthPage()
    page._run_health_check()
    page._run_conservative_fix()

    assert "状态" in page.summary_label.text()
    assert "health-ok" in page.report_text.toPlainText()

    page.deleteLater()


class _DummySpecialAudioManager:
    def __init__(self):
        self.grenade_sound_styles = {"hegrenade": ["styleG"]}
        self.c4_sound_styles = ["styleC4"]
        self.health_warning_styles = ["styleH"]
        self.round_start_styles = ["styleStart"]
        self.round_action_styles = ["styleAction"]
        self.round_win_styles = ["styleWin"]
        self.round_lose_styles = ["styleLose"]
        self.round_mvp_styles = ["styleMvp"]
        self.play_calls: list[tuple[str, str]] = []
        self.load_round_calls: list[tuple[str, str]] = []

    def ensure_styles_scanned(self):
        return None

    def scan_grenade_sound_styles(self):
        return self.grenade_sound_styles

    def scan_c4_sound_styles(self):
        return self.c4_sound_styles

    def scan_health_warning_styles(self):
        return self.health_warning_styles

    def scan_round_sound_styles(self):
        return {
            "start": self.round_start_styles,
            "action": self.round_action_styles,
            "win": self.round_win_styles,
            "lose": self.round_lose_styles,
            "mvp": self.round_mvp_styles,
        }

    def load_round_sound(self, round_type: str, style: str):
        self.load_round_calls.append((round_type, style))
        return True

    def play_sound(self, key: str, channel_type: str = "kill_sound", **_kwargs):
        self.play_calls.append((key, channel_type))
        return True

    def play_sound_with_fade(self, key: str, channel_type: str = "round_sound", **_kwargs):
        self.play_calls.append((key, channel_type))
        return True


def test_special_sound_page_smoke(qapp, monkeypatch):
    import pages.special_sound_page as special_page_module

    dummy = _DummySpecialAudioManager()
    monkeypatch.setattr(special_page_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        special_page_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "grenade_sound_styles", {"hegrenade": "styleG"}, raising=False)
    monkeypatch.setattr(config, "c4_sound_style", "styleC4", raising=False)
    monkeypatch.setattr(config, "health_warning_style", "styleH", raising=False)
    monkeypatch.setattr(config, "round_start_style", "styleStart", raising=False)
    monkeypatch.setattr(config, "grenade_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "c4_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "health_warning_enabled", False, raising=False)
    monkeypatch.setattr(config, "round_sound_enabled", False, raising=False)

    page = special_page_module.SpecialSoundPage()
    assert page.tab_widget.count() >= 4

    page._test_grenade_sound("hegrenade")
    page._test_c4_sound()
    page._test_health_warning()
    page._test_round_sound("start")

    assert ("grenade-hegrenade-styleG", "grenade_sound") in dummy.play_calls
    assert ("c4-planted-styleC4", "c4_sound") in dummy.play_calls
    assert ("health-warning-styleH", "health_warning") in dummy.play_calls
    assert any(key.startswith("round-start-") and channel == "round_sound" for key, channel in dummy.play_calls)
    before_chips = _visible_status_chip_texts(page.status_badge_label)
    assert len(before_chips) == 4
    assert "模块 · 0/4" in before_chips
    assert "样式 · 4" in before_chips
    assert "资源 · 正常" in before_chips

    page._on_round_enabled_toggled(True)
    after_chips = _visible_status_chip_texts(page.status_badge_label)
    assert len(after_chips) == 4
    assert "模块 · 1/4" in after_chips

    page.deleteLater()


class _DummyKillVoiceAudioManager:
    def __init__(self, base_dir: Path):
        self.kill_voice_styles = ["styleV"]
        self.weapon_kill_voice_styles = {"weapon_ak47": ["styleV"]}
        self.weapon_voices_dir = str(base_dir / "weapon_kill_voices")
        self.kill_voices_dir = str(base_dir / "kill_voices")
        self._sounds = {}
        self.loaded: list[tuple[str, str]] = []
        self.played: list[str] = []

    def ensure_styles_scanned(self):
        return None

    def unload_kill_voice_for_weapon(self, *_args, **_kwargs):
        return True

    def load_kill_voice_for_weapon(self, *_args, **_kwargs):
        return True

    def load_sound(self, key, path, category, weapon_id=None, style=None):
        self._sounds[key] = type("S", (), {"loaded": True, "path": path})()
        self.loaded.append((key, path))
        return True

    def play_voice(self, key):
        self.played.append(key)
        return True


def test_kill_voice_page_prefers_wav_preview(qapp, monkeypatch, tmp_path):
    import pages.kill_voice_page as kill_voice_module

    style_dir = tmp_path / "weapon_kill_voices" / "weapon_ak47" / "styleV"
    style_dir.mkdir(parents=True, exist_ok=True)
    wav_file = style_dir / "1.wav"
    wav_file.write_bytes(b"RIFF....WAVEfmt ")

    dummy = _DummyKillVoiceAudioManager(tmp_path)
    monkeypatch.setattr(kill_voice_module, "get_runtime_audio_manager", lambda: dummy)
    monkeypatch.setattr(
        kill_voice_module,
        "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0},
    )
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "weapon_kill_voices", {"weapon_ak47": "styleV"}, raising=False)

    page = kill_voice_module.KillVoicePage()
    page._test_weapon_voice("weapon_ak47")

    assert any(path.endswith("1.wav") for _, path in dummy.loaded)
    assert any(key.startswith("voice-weapon_ak47-styleV-1") for key in dummy.played)

    page.deleteLater()


def test_audio_import_wizard_page_smoke(qapp, monkeypatch, tmp_path):
    import pages.audio_import_wizard_page as wizard_module

    source_dir = tmp_path / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    audio_root = tmp_path / "audio_root"
    audio_root.mkdir(parents=True, exist_ok=True)

    report = {
        "source_dir": str(source_dir),
        "resources_root": str(audio_root),
        "domain": "audio",
        "recognized": [
            {
                "source_path": str(source_dir / "kill_sounds" / "default" / "1.wav"),
                "target_rel_path": "kill_sounds/default/1.wav",
                "target_abs_path": str(audio_root / "kill_sounds" / "default" / "1.wav"),
                "spec_key": "kill_sounds",
                "spec_label": "击杀音效",
                "domain": "audio",
                "conflict": False,
            }
        ],
        "unrecognized": [],
        "summary": {
            "scanned_resource_files": 1,
            "recognized_count": 1,
            "unrecognized_count": 0,
            "conflict_count": 0,
            "importable_count": 1,
            "ok": True,
        },
    }
    import_result = {
        "dry_run": True,
        "overwrite_existing": False,
        "copied": [
            {
                "source_path": str(source_dir / "kill_sounds" / "default" / "1.wav"),
                "target_abs_path": str(audio_root / "kill_sounds" / "default" / "1.wav"),
                "target_rel_path": "kill_sounds/default/1.wav",
                "spec_key": "kill_sounds",
                "domain": "audio",
            }
        ],
        "skipped_conflicts": [],
        "failed": [],
        "summary": {
            "copied_count": 1,
            "skipped_conflicts_count": 0,
            "failed_count": 0,
            "ok": True,
        },
    }

    monkeypatch.setattr(wizard_module, "scan_resource_import_candidates", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(wizard_module, "apply_resource_import_plan", lambda *_args, **_kwargs: import_result)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        wizard_module.ResourceManager,
        "get_app_data_path",
        lambda rel: str(
            audio_root
            if rel in ("resources", "resources/audio")
            else audio_root / rel
        ),
    )

    page = wizard_module.AudioImportWizardPage()
    page.source_edit.setText(str(source_dir))
    page.dry_run_checkbox.setChecked(True)

    page._scan_source()
    page._run_import()

    assert "扫描完成" in page.summary_label.text()
    assert "[导入向导扫描结果]" in page.preview_text.toPlainText()
    assert "kill_sounds/default/1.wav" in page.preview_text.toPlainText()

    page.deleteLater()
