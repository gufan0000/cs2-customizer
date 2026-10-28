# SPDX-License-Identifier: GPL-3.0-or-later
"""2026-10-28: 用户文件在冲突、重复操作和部分写入失败时仍可恢复。"""
import json
from pathlib import Path

import pytest


def test_preset_new_names_do_not_overwrite_case_or_corrupt_files(tmp_path, monkeypatch):
    from core.presets import my_presets as presets
    monkeypatch.setattr(presets, "presets_dir", lambda: str(tmp_path))
    monkeypatch.setattr(presets, "export_bundle", lambda _: {"items": []})
    (tmp_path / "AuditCase.json").write_text("broken", encoding="utf-8")
    kind = next(iter(presets.SUPPORTED_TYPES))
    saved = presets.save_preset("auditcase", [kind])
    assert saved.preset_id.casefold() != "auditcase"
    assert (tmp_path / "AuditCase.json").read_text() == "broken"
    reserved = presets.save_preset("CON", [kind])
    assert Path(reserved.file_path).is_file()


def _import(tmp_path, overwrite=False):
    from core.resource_import_wizard import apply_resource_import_plan
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF" + b"\0" * 16)
    target = tmp_path / "res" / "audio" / "kill_sounds" / "test" / "1.wav"
    if overwrite:
        target.parent.mkdir(parents=True)
        target.write_bytes(b"old")
    result = apply_resource_import_plan({"recognized": [{
        "source_path": str(source), "target_abs_path": str(target),
        "target_rel_path": "audio/kill_sounds/test/1.wav", "spec_key": "kill_sounds",
        "domain": "audio", "conflict": overwrite,
    }]}, dry_run=False, overwrite_existing=overwrite)
    assert result["summary"]["ok"]
    return result, target


def test_concurrent_preset_creation_keeps_every_result(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from core.presets import my_presets as presets
    monkeypatch.setattr(presets, "presets_dir", lambda: str(tmp_path))
    monkeypatch.setattr(presets, "export_bundle", lambda _: {"items": []})
    kind = next(iter(presets.SUPPORTED_TYPES))
    with ThreadPoolExecutor(max_workers=4) as pool:
        saved = list(pool.map(lambda _: presets.save_preset("Case", [kind]), range(4)))
    assert len({item.preset_id.casefold() for item in saved}) == 4
    assert len(list(tmp_path.glob("*.json"))) == 4


@pytest.mark.parametrize("overwrite", [False, True])
def test_undo_preserves_later_edits(tmp_path, overwrite):
    from core.resource_import_wizard import undo_import
    result, target = _import(tmp_path, overwrite)
    target.write_bytes(b"later edit")
    assert not undo_import(result)["summary"]["ok"]
    assert target.read_bytes() == b"later edit"


def test_undo_overwrite_is_consumed_once(tmp_path):
    from core.resource_import_wizard import undo_import
    result, target = _import(tmp_path, True)
    assert undo_import(result)["summary"]["ok"]
    assert target.read_bytes() == b"old"
    assert undo_import(result)["summary"]["ok"]
    assert target.read_bytes() == b"old"


def test_cfg_replace_failure_leaves_original(tmp_path, monkeypatch):
    import cfg_utils
    from core import io_validation
    game = tmp_path / "game" / "csgo" / "cfg"
    game.mkdir(parents=True)
    target = game / "gamestate_integration_cs2customizer.cfg"
    target.write_text("old cfg", encoding="utf-8")
    def fail(*_):
        raise OSError("injected disk failure")
    monkeypatch.setattr(io_validation, "replace_with_retry", fail)
    assert cfg_utils.ensure_cfg_exists(str(tmp_path)) is False
    assert target.read_text() == "old cfg"
    assert list(game.iterdir()) == [target]


def test_autoexec_preserves_non_utf8_bytes(tmp_path):
    import cfg_utils
    game = tmp_path / "game" / "csgo" / "cfg"
    game.mkdir(parents=True)
    target = game / "autoexec.cfg"
    original = b'// \xd6\xd0\xce\xc4\r\nbind x +jump\r\n'
    target.write_bytes(original)
    cfg_utils.setup_autoexec(str(tmp_path))
    assert b"\xd6\xd0\xce\xc4" in target.read_bytes()
    assert Path(str(target) + cfg_utils.AUTOEXEC_BACKUP_SUFFIX).read_bytes() == original


@pytest.mark.parametrize("old", [False, True])
def test_icon_second_replace_failure_rolls_back(tmp_path, monkeypatch, old):
    from core import kill_icon_import as icons
    sprite, meta = tmp_path / "1.png", tmp_path / "1.json"
    if old:
        sprite.write_bytes(b"old image")
        meta.write_text("old metadata")
    real_replace = icons.replace_with_retry
    def fail_second(src, dst):
        if str(dst) == str(meta):
            raise OSError("injected metadata replacement failure")
        real_replace(src, dst)
    monkeypatch.setattr(icons, "replace_with_retry", fail_second)
    with pytest.raises(OSError):
        icons._write_asset_pair(str(sprite), lambda p: Path(p).write_bytes(b"new"),
                                str(meta), {"frames": 2})
    if old:
        assert sprite.read_bytes() == b"old image"
        assert meta.read_text() == "old metadata"
    else:
        assert not sprite.exists() and not meta.exists()


def test_icon_delete_and_restore_roll_back_second_move(tmp_path, monkeypatch):
    from core import kill_icon_library as library
    from test_kill_icon_library_ki5 import _FakeResourceManager, _make_sheet
    manager = _FakeResourceManager(tmp_path)
    sprite, meta = map(Path, _make_sheet(manager, "style", 1))
    before = sprite.read_bytes(), meta.read_bytes()
    real_move = library.shutil.move
    calls = []
    def fail_second(src, dst):
        calls.append((src, dst))
        if len(calls) == 2:
            raise OSError("injected move failure")
        return real_move(src, dst)
    monkeypatch.setattr(library.shutil, "move", fail_second)
    with pytest.raises(OSError):
        library.delete_level("style", 1, resource_manager=manager)
    assert (sprite.read_bytes(), meta.read_bytes()) == before
    monkeypatch.setattr(library.shutil, "move", real_move)
    token = library.delete_level("style", 1, resource_manager=manager)
    calls.clear()
    monkeypatch.setattr(library.shutil, "move", fail_second)
    assert library.restore_level(token, manager) is False
    assert not sprite.exists() and not meta.exists()
    manifest = json.loads((Path(token) / "restore.json").read_text(encoding="utf-8"))
    assert all((Path(token) / name).exists() for name in manifest["moved"])
