# SPDX-License-Identifier: GPL-3.0-or-later
"""v2.2.1: 新建音效风格核心逻辑（core/audio/style_creator.py）测试。"""
from __future__ import annotations

import os

import pytest
from core.audio import style_creator
from resource_manager import ResourceManager


@pytest.fixture()
def audio_root(tmp_path, monkeypatch):
    def fake_get_app_data_path(relative_path):
        rel = str(relative_path).replace("/", os.sep).replace("\\", os.sep)
        return str(tmp_path / rel)

    monkeypatch.setattr(ResourceManager, "get_app_data_path", staticmethod(fake_get_app_data_path))
    root = tmp_path / "resources" / "audio"
    root.mkdir(parents=True)
    return root


def _make_sources(tmp_path, names):
    src_dir = tmp_path / "downloads"
    src_dir.mkdir(exist_ok=True)
    paths = []
    for name in names:
        p = src_dir / name
        p.write_bytes(b"fake-audio")
        paths.append(str(p))
    return paths


def test_validate_style_name():
    assert style_creator.validate_style_name("我的风格") is None
    assert style_creator.validate_style_name("") is not None
    assert style_creator.validate_style_name("0") is not None
    assert style_creator.validate_style_name("default") is not None
    assert style_creator.validate_style_name("bad/name") is not None
    assert style_creator.validate_style_name("a" * 60) is not None


def test_create_numbered_kill_style_renames_in_order(audio_root, tmp_path):
    files = _make_sources(tmp_path, ["ak首杀.mp3", "ak双杀.wav", "三杀.ogg"])
    result = style_creator.create_style("kill_sound", "我的包", files)
    assert result.ok, result.message
    target = audio_root / "kill_sounds" / "我的包"
    assert sorted(os.listdir(target)) == ["1.mp3", "2.wav", "3.ogg"]
    # 提示缺 4、5 连杀
    assert "4" in result.message and "5" in result.message


def test_create_weapon_specific_kill_style(audio_root, tmp_path):
    files = _make_sources(tmp_path, ["a.mp3"])
    result = style_creator.create_style("kill_sound", "专属", files, weapon="weapon_ak47")
    assert result.ok
    assert (audio_root / "weapon_kill_sounds" / "weapon_ak47" / "专属" / "1.mp3").is_file()


def test_create_switch_weapon_style_requires_weapon(audio_root, tmp_path):
    files = _make_sources(tmp_path, ["s.mp3"])
    result = style_creator.create_style("switch_weapon", "刀声", files)
    assert not result.ok and result.error == "weapon_required"

    result = style_creator.create_style("switch_weapon", "刀声", files, weapon="weapon_knife")
    assert result.ok
    assert (audio_root / "switch_weapons" / "weapon_knife" / "刀声" / "1.mp3").is_file()


def test_create_death_style_flat_naming(audio_root, tmp_path):
    files = _make_sources(tmp_path, ["随便叫什么.wav"])
    result = style_creator.create_style("death_sound", "阵亡音", files)
    assert result.ok
    assert (audio_root / "death" / "阵亡音.wav").is_file()


def test_duplicate_style_rejected_unless_overwrite(audio_root, tmp_path):
    files = _make_sources(tmp_path, ["a.mp3"])
    assert style_creator.create_style("kill_sound", "重复", files).ok
    dup = style_creator.create_style("kill_sound", "重复", files)
    assert not dup.ok and dup.error == "style_exists"
    assert style_creator.create_style("kill_sound", "重复", files, overwrite=True).ok


def test_rejects_bad_extension_and_missing_file(audio_root, tmp_path):
    bad = _make_sources(tmp_path, ["not_audio.txt"])
    result = style_creator.create_style("kill_sound", "坏文件", bad)
    assert not result.ok and result.error == "bad_extension"

    result = style_creator.create_style("kill_sound", "缺文件", [str(tmp_path / "ghost.mp3")])
    assert not result.ok and result.error == "file_missing"


def test_rejects_too_many_files(audio_root, tmp_path):
    files = _make_sources(tmp_path, [f"{i}.mp3" for i in range(6)])
    result = style_creator.create_style("kill_sound", "太多", files)
    assert not result.ok and result.error == "too_many_files"


def test_source_files_are_copied_not_moved(audio_root, tmp_path):
    files = _make_sources(tmp_path, ["keep.mp3"])
    result = style_creator.create_style("kill_sound", "复制", files)
    assert result.ok
    assert os.path.isfile(files[0])  # 源文件保留


# ---------- v2.2.1: 风格管理（重命名/安全删除） ----------

def test_rename_style_updates_config_refs(audio_root, tmp_path, monkeypatch):
    from config import config

    files = _make_sources(tmp_path, ["a.mp3"])
    assert style_creator.create_style("kill_sound", "旧名", files).ok
    monkeypatch.setattr(config, "weapon_kill_sounds", {"weapon_ak47": "旧名", "weapon_awp": "0"}, raising=False)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)

    result = style_creator.rename_style("kill_sound", "旧名", "新名")
    assert result.ok, result.message
    assert (audio_root / "kill_sounds" / "新名").is_dir()
    assert not (audio_root / "kill_sounds" / "旧名").exists()
    assert config.weapon_kill_sounds["weapon_ak47"] == "新名"
    assert config.weapon_kill_sounds["weapon_awp"] == "0"  # 未引用的不动


def test_rename_style_rejects_existing_target(audio_root, tmp_path, monkeypatch):
    from config import config

    files = _make_sources(tmp_path, ["a.mp3"])
    assert style_creator.create_style("kill_sound", "甲", files).ok
    assert style_creator.create_style("kill_sound", "乙", files).ok
    monkeypatch.setattr(config, "weapon_kill_sounds", {}, raising=False)

    result = style_creator.rename_style("kill_sound", "甲", "乙")
    assert not result.ok and result.error == "style_exists"


def test_delete_style_moves_to_trash_and_resets_refs(audio_root, tmp_path, monkeypatch):
    from config import config

    files = _make_sources(tmp_path, ["a.mp3"])
    assert style_creator.create_style("kill_sound", "要删", files).ok
    monkeypatch.setattr(config, "weapon_kill_sounds", {"weapon_ak47": "要删"}, raising=False)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)

    result = style_creator.delete_style("kill_sound", "要删")
    assert result.ok, result.message
    assert not (audio_root / "kill_sounds" / "要删").exists()
    trash = audio_root / "_trash"
    assert trash.is_dir() and any("要删" in p.name for p in trash.iterdir())  # 移入回收区而非物理删除
    assert config.weapon_kill_sounds["weapon_ak47"] == "0"


def test_list_style_files(audio_root, tmp_path):
    files = _make_sources(tmp_path, ["x.mp3", "y.wav"])
    assert style_creator.create_style("kill_voice", "查看", files).ok
    listed = style_creator.list_style_files("kill_voice", "查看")
    assert listed == ["1.mp3", "2.wav"]
