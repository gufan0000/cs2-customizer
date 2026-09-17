# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""枪声风格目录里的多个文件是同一把枪的不同取样，每一发随机换一个（2026-09-17 批 101）。

竞品每发 `PickRandomAudio`，它的「离子AK」5 个 wav 是**真不同的取样**（md5 各异）；
我方 `load_gun_sound` 原来只取目录里的第一个文件 —— 另外四个白放，扫射就是同一个声音复读。

（本项目测试逐文件跑：`python -m pytest tests/test_gun_sound_variants_rotate.py`）
"""
from __future__ import annotations

import ast
from collections import OrderedDict
from pathlib import Path
from threading import Lock

import pygame
import pytest

from core.audio.audio_manager import MAX_GUN_SOUND_VARIANTS, AudioManager

ROOT = Path(__file__).resolve().parent.parent


class _FakeSound:
    def __init__(self, path):
        self.path = str(path)

    def set_volume(self, _v):
        pass

    def stop(self):
        pass


class _SilentLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


def _manager(tmp_path, monkeypatch):
    """不跑 __init__（那会初始化 mixer、占用音频设备），只搭出加载路径需要的字段。"""
    monkeypatch.setattr(pygame.mixer, "Sound", _FakeSound)
    am = AudioManager.__new__(AudioManager)
    am.logger = _SilentLogger()
    am._lock = Lock()
    am._sounds = {}
    am._access_order = OrderedDict()
    am._max_sounds = 50
    am._gun_sound_variants = {}
    am._last_gun_sound_variant = {}
    am._on_loaded_callbacks = []
    am._mixer_ready = True
    am._volume = 0.7
    am._styles_scanned = True
    am.gun_sounds_dir = str(tmp_path)
    am._apply_loudness_normalization = lambda sound: (sound, 1.0)
    return am


def _style(tmp_path, gun, style, n):
    d = tmp_path / gun / style
    d.mkdir(parents=True)
    for i in range(n):
        (d / f"take{i}.wav").write_bytes(b"RIFF")
    return d


def test_every_file_in_a_style_folder_is_loaded_as_a_variant(tmp_path, monkeypatch):
    am = _manager(tmp_path, monkeypatch)
    _style(tmp_path, "ak47", "离子AK", 3)
    assert am.load_gun_sound("ak47", "离子AK") is True
    keys = am.gun_sound_variant_keys("ak47", "离子AK")
    assert keys == ("gun-ak47-离子AK", "gun-ak47-离子AK#1", "gun-ak47-离子AK#2"), keys
    paths = {Path(am._sounds[k].path).name for k in keys}
    assert paths == {"take0.wav", "take1.wav", "take2.wav"}, "三个文件只装了一个"


def test_each_shot_picks_a_different_take_than_the_last(tmp_path, monkeypatch):
    am = _manager(tmp_path, monkeypatch)
    _style(tmp_path, "ak47", "离子AK", 3)
    am.load_gun_sound("ak47", "离子AK")
    picks = [am._pick_gun_sound_variant("gun-ak47-离子AK") for _ in range(60)]
    assert set(picks) == set(am.gun_sound_variant_keys("ak47", "离子AK")), "有的取样从来没轮到"
    assert all(a != b for a, b in zip(picks, picks[1:])), "连着两发同一个取样"


def test_a_single_file_style_still_plays_its_only_file(tmp_path, monkeypatch):
    am = _manager(tmp_path, monkeypatch)
    _style(tmp_path, "awp", "起源", 1)
    am.load_gun_sound("awp", "起源")
    assert am.gun_sound_variant_keys("awp", "起源") == ("gun-awp-起源",)
    assert am._pick_gun_sound_variant("gun-awp-起源") == "gun-awp-起源"
    # 不是枪声的键原样返回
    assert am._pick_gun_sound_variant("kill-x-1") == "kill-x-1"


def test_the_variant_cap_matches_the_channel_pool(tmp_path, monkeypatch):
    assert MAX_GUN_SOUND_VARIANTS == 5
    am = _manager(tmp_path, monkeypatch)
    _style(tmp_path, "negev", "边陲奥丁", 8)
    am.load_gun_sound("negev", "边陲奥丁")
    assert len(am.gun_sound_variant_keys("negev", "边陲奥丁")) == 5


def test_unloading_a_style_drops_its_variants_too(tmp_path, monkeypatch):
    am = _manager(tmp_path, monkeypatch)
    _style(tmp_path, "ak47", "离子AK", 3)
    am.load_gun_sound("ak47", "离子AK")
    assert am.unload_gun_sound("ak47", "离子AK") is True
    assert not [k for k in am._sounds if k.startswith("gun-ak47-离子AK")]
    assert am.gun_sound_variant_keys("ak47", "离子AK") == ()


def test_play_sound_picks_the_take_after_loading_and_before_looking_it_up():
    """AST：`play_sound` 里 `_pick_gun_sound_variant` 必须在 `_load_sound_by_key` 之后、
    `_get_info` 之前 —— 早了变体表还是空的，晚了拿的是规范键那一个文件。"""
    src = (ROOT / "core" / "audio" / "audio_manager.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "play_sound")
    order = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("_load_sound_by_key", "_pick_gun_sound_variant", "_get_info"):
                order.append((node.lineno, node.func.attr))
    order.sort()
    names = [n for _, n in order]
    assert names.index("_load_sound_by_key") < names.index("_pick_gun_sound_variant") < names.index("_get_info"), names


def test_an_evicted_take_is_skipped_instead_of_dropping_the_shot(tmp_path, monkeypatch):
    """缓存预算会淘汰一个取样：挑的时候只在还装着的里面挑，别挑到一个已经不在的键。"""
    am = _manager(tmp_path, monkeypatch)
    _style(tmp_path, "ak47", "离子AK", 3)
    am.load_gun_sound("ak47", "离子AK")
    am._sounds.pop("gun-ak47-离子AK#1")
    picks = {am._pick_gun_sound_variant("gun-ak47-离子AK") for _ in range(40)}
    assert picks == {"gun-ak47-离子AK", "gun-ak47-离子AK#2"}, picks


@pytest.mark.parametrize("bad", ["", "0", "不启用"])
def test_disabled_styles_do_not_load(tmp_path, monkeypatch, bad):
    am = _manager(tmp_path, monkeypatch)
    assert am.load_gun_sound("ak47", bad) is False
