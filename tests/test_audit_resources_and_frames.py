# SPDX-License-Identifier: GPL-3.0-or-later
"""Resource preservation and pure-frame regressions; no large files/devices."""
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("directory", [False, True])
def test_resource_limits_apply_before_copy(tmp_path, monkeypatch, directory):
    from core import resource_import_source as source
    path = tmp_path / "sound.wav"
    path.write_bytes(b"sample")
    monkeypatch.setattr(source.os.path, "getsize", lambda _: 2 * 1024**3)
    with pytest.raises(source.ImportSourceError):
        source.open_source(str(tmp_path if directory else path))


def _plan(tmp_path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"new")
    target = tmp_path / "resources" / "sound.wav"
    return {"recognized": [{"source_path": str(source), "target_abs_path": str(target)}]}, target


def test_disk_preflight_preserves_existing_files(tmp_path, monkeypatch):
    from core import resource_import_source as source
    from core.resource_import_wizard import apply_resource_import_plan
    plan, target = _plan(tmp_path)
    monkeypatch.setattr(source.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    result = apply_resource_import_plan(plan)
    assert result["summary"]["failed_count"] == 1
    assert not target.exists()


def test_cancel_during_copy_leaves_no_partial(tmp_path):
    """分母：本用例创建导入源；目标和临时文件在取消后应为空。"""
    from core.resource_import_wizard import apply_resource_import_plan
    plan, target = _plan(tmp_path)
    calls = iter([False, True])
    result = apply_resource_import_plan(plan, should_cancel=lambda: next(calls, True))
    assert result["cancelled"]
    assert not target.exists()
    assert not list(tmp_path.rglob(".cs2customizer-import-*"))


@pytest.mark.parametrize("target_removed", [False, True])
def test_overwrite_undo_restores_original(tmp_path, target_removed):
    from core.resource_import_wizard import apply_resource_import_plan, undo_import
    plan, target = _plan(tmp_path)
    target.parent.mkdir()
    target.write_bytes(b"original")
    result = apply_resource_import_plan(plan, overwrite_existing=True)
    assert result["summary"]["ok"] and target.read_bytes() == b"new"
    if target_removed:
        target.unlink()
    assert undo_import(result)["summary"]["failed_count"] == 0
    assert target.read_bytes() == b"original"


def test_icon_pack_rejects_overwrite_and_failed_conversion_preserves_pack(tmp_path, monkeypatch):
    from core import kill_icon_pack as pack
    from core.kill_icon_import import KillIconImportError
    from tests.test_kill_icon_pack_ki4 import _FakeResourceManager, _write_pack
    rm = _FakeResourceManager(tmp_path / "store")
    archive = _write_pack(tmp_path / "pack.zip")
    pack.import_pack(str(archive), "original", resource_manager=rm)
    # Capture actual output locations, including metadata and every level.
    root = Path(pack._style_dir(rm, "original"))
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(KillIconImportError):
        pack.import_pack(str(archive), "original", resource_manager=rm, overwrite=False)
    real_convert = pack.convert_to_style
    count = 0
    def failing(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise KillIconImportError("synthetic decode failure")
        return real_convert(*args, **kwargs)
    monkeypatch.setattr(pack, "convert_to_style", failing)
    with pytest.raises(KillIconImportError):
        pack.import_pack(str(archive), "original", resource_manager=rm, overwrite=True)
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("alpha", [0, 32, 128, 255])
def test_all_crosshair_effects_respect_user_alpha(alpha):
    from crosshair_overlay import CrosshairAnimator, CrosshairState, IDLE_ANIMATIONS, KILL_EFFECTS
    for animation in IDLE_ANIMATIONS:
        for effect in KILL_EFFECTS:
            state = CrosshairState(animation=animation, kill_effect=effect, alpha=alpha)
            animator = CrosshairAnimator()
            animator.trigger_kill(state, 10.0)
            frame = animator.advance(state, 10.1)
            assert frame.color.alpha() <= alpha, (animation, effect)
            assert frame.outline_color.alpha() <= alpha
            for overlay in frame.overlays:
                assert overlay.color.alpha() <= alpha, (animation, effect)


def test_gun_duration_roundtrip_preserves_hundredths(qapp, monkeypatch):
    from config import config
    from core.gun_sound_profiles import GUN_SOUND_PROFILES
    from pages.gun_sound_page import GunSoundPage
    monkeypatch.setattr(config, "save_config", lambda: None)
    profiles = {key: profile for key, profile in GUN_SOUND_PROFILES.items()
                if profile.default_mute_duration == 0.18}
    assert len(profiles) == 2
    for profile in profiles.values():
        monkeypatch.setattr(config, profile.mute_duration_key, 0.18)
    page = GunSoundPage()
    try:
        from ui_style_applier import get_style_applier
        get_style_applier().fix_text_display(page)
        for key, profile in profiles.items():
            slider = page.weapon_rows[key]["duration_slider"]
            assert slider.value() == 18
            slider.setValue(19)
            slider.setValue(18)
            assert getattr(config, profile.mute_duration_key) == 0.18
            assert page.weapon_rows[key]["duration_label"].text() == "0.18秒"
            label = page.weapon_rows[key]["duration_label"]
            assert not label.wordWrap()
            assert label.minimumSizeHint().width() >= label.fontMetrics().horizontalAdvance(label.text())
    finally:
        page.close()
        page.deleteLater()


def test_magnifier_hook_reads_no_qt_checkbox():
    from unittest.mock import Mock
    from pages.magnifier_page import MagnifierPage
    checkbox = Mock()
    checkbox.isChecked.side_effect = AssertionError("Qt widget accessed by worker")
    page = SimpleNamespace(current_weapon="weapon_awp", weapon_enabled_vars={"weapon_awp": checkbox},
                           config=SimpleNamespace(magnifier={"weapon_settings": {"weapon_awp": False}}))
    assert MagnifierPage._is_current_weapon_enabled(page) is False
    page.config.magnifier = {"weapon_settings": {"weapon_awp": True}}
    assert MagnifierPage._is_current_weapon_enabled(page) is True
    checkbox.isChecked.assert_not_called()
