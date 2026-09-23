# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""枪声的缓存预算：多取样不许把音频缓存挤爆（批 103）。

⭐⭐⭐ 这是批 101 自己引进来的回归。那一批把「一个风格只播第一个文件」改成
「最多装 5 个取样、每发随机换」，于是每把枪从 2 个缓存键变成最多 6 个
（规范键 + 最多 4 个取样 + 1 个别名）。而 `_max_sounds` 还是 50 ——
它是按「枪声 10 个键」那个年代定的，且 `load_all_enabled_sounds` 的第 1 轮**不查预算**。

本机实测（一份真实素材包、30 把枪各配一套）：要 **112 格**。
后果不是「少装几个」，而是后装的把先装的挨个挤出去 —— 连 AK-47 都不在缓存里，
进游戏每把枪的第一发都要在 GSI 派发线程上重新扫目录 + 解码。
UP-060 注释里写的那个病原样复发，只是主角从击杀音效换成了枪声。
"""
from __future__ import annotations

import collections
import threading
import types
from pathlib import Path

from core.audio.audio_manager import (
    GUN_SOUND_CACHE_HEADROOM,
    AudioManager,
)
# ⚠ RN-676：`MAX_GUN_SOUND_VARIANTS` 搬到 `gun_sound_profiles` 了（设置页要说出这个数，
#   而 import audio_manager 会把 pygame 一起拖进来）。从**新家**取，别从 re-export 取 ——
#   否则 X7 的契约快照会一直把它算成 audio_manager 的对外面。
from core.gun_sound_profiles import (
    MAX_GUN_SOUND_VARIANTS,
    SUPPORTED_GUN_SOUND_PROFILE_LIST,
)

REPO = Path(__file__).resolve().parents[1]


def _bare_manager(gun_sounds_dir: Path) -> AudioManager:
    """不跑 `__init__` 的 manager（跑它会占音频设备，§3 不许打扰前台）。"""
    m = AudioManager.__new__(AudioManager)
    m._lock = threading.Lock()
    m._sounds = {}
    m._access_order = collections.OrderedDict()
    m._max_sounds = 50
    m.gun_sounds_dir = str(gun_sounds_dir)
    m._styles_scanned = True
    m._on_loaded_callbacks = []
    m._on_error_callbacks = []
    m.logger = types.SimpleNamespace(
        info=lambda *_a, **_k: None, debug=lambda *_a, **_k: None,
        warning=lambda *_a, **_k: None, error=lambda *_a, **_k: None)
    m._style_enabled = lambda s: bool(s) and s not in {"", "0", "none", "off"}
    m._norm_style = lambda s: str(s or "")
    return m


def _fake_pack(root: Path, guns, *, takes: int, style: str = "离子"):
    """造一份「每把枪一套风格、每套 N 个文件」的素材目录。"""
    for gun in guns:
        d = root / gun / style
        d.mkdir(parents=True)
        for i in range(takes):
            (d / f"{i + 1}.wav").write_bytes(b"RIFF....WAVEfmt ")


class _Cfg:
    def __init__(self, guns, style="离子"):
        for gun in guns:
            setattr(self, f"{gun}_style", style)

    def __getattr__(self, _name):
        return "0"


# ============================================================ 上限跟着配置长

def test_the_cache_cap_grows_to_hold_every_enabled_gun_style(tmp_path):
    guns = [p.gun_type for p in SUPPORTED_GUN_SOUND_PROFILE_LIST][:30]
    _fake_pack(tmp_path, guns, takes=MAX_GUN_SOUND_VARIANTS)
    m = _bare_manager(tmp_path)

    before = m._max_sounds
    m._raise_cache_cap_for_guns(_Cfg(guns))

    # 每把枪：min(文件数, 5) 个取样键 + 1 个别名键
    need = len(guns) * (MAX_GUN_SOUND_VARIANTS + 1)
    assert need > before, "夹具没造出「会挤爆」的规模，这条判据在空转"
    assert m._max_sounds == need + GUN_SOUND_CACHE_HEADROOM, (
        f"上限只抬到 {m._max_sounds}，而这份配置需要 {need} 格"
        f"（+{GUN_SOUND_CACHE_HEADROOM} 格留给击杀音那一层）")


def test_the_cap_is_never_lowered(tmp_path):
    """只抬不降：别的功能已经装进来的东西不许因为枪声少了而被挤掉。"""
    guns = ["ak47", "m4a1"]
    _fake_pack(tmp_path, guns, takes=1)
    m = _bare_manager(tmp_path)
    m._max_sounds = 500
    m._raise_cache_cap_for_guns(_Cfg(guns))
    assert m._max_sounds == 500


def test_a_style_with_one_file_only_needs_two_slots(tmp_path):
    """单取样风格不许按 5 个算 —— 否则上限会被抬到用不上的高度。"""
    guns = ["ak47", "awp", "deagle"]
    _fake_pack(tmp_path, guns, takes=1)
    m = _bare_manager(tmp_path)
    m._raise_cache_cap_for_guns(_Cfg(guns))
    assert m._max_sounds == len(guns) * 2 + GUN_SOUND_CACHE_HEADROOM


def test_guns_without_assets_do_not_inflate_the_cap(tmp_path):
    """配了风格但目录里没文件的枪不占格子。"""
    _fake_pack(tmp_path, ["ak47"], takes=3)
    (tmp_path / "awp" / "离子").mkdir(parents=True)  # 空目录
    m = _bare_manager(tmp_path)
    m._raise_cache_cap_for_guns(_Cfg(["ak47", "awp"]))
    assert m._max_sounds == 4 + GUN_SOUND_CACHE_HEADROOM


# ============================================================ 空转守卫：旧行为真的会挤爆

def test_that_judge_sees_the_old_cap_thrashing(tmp_path):
    """把上限钉回 50、不抬，装 30 把枪 ⇒ 先装的必须被挤出去（含 AK-47）。"""
    guns = [p.gun_type for p in SUPPORTED_GUN_SOUND_PROFILE_LIST][:30]
    assert "ak47" in guns
    _fake_pack(tmp_path, guns, takes=MAX_GUN_SOUND_VARIANTS)
    m = _bare_manager(tmp_path)

    loaded_paths: list[str] = []

    def fake_load(key, path, category, weapon_id=None, style=None):
        loaded_paths.append(path)
        m._store(key, object(), path, category, weapon_id=weapon_id, style=style)
        return True

    m.load_sound = fake_load
    m._alias = lambda a, t: m._sounds.__setitem__(a, m._sounds[t]) if t in m._sounds else None
    m._unload_other_styles_for_gun = lambda g, s: None

    for gun in guns:
        m.load_gun_sound(gun, "离子")

    # ⚠ 不要断言 `len(_sounds) <= 50`：**别名键绕过上限**（`_alias` 直接塞进 `_sounds`，
    # 不走 `_store`、不触发淘汰）。它和规范键共享同一个 Sound 对象，所以不吃内存 ——
    # 但也因此「键数」不等于「上限」。守卫要钉的是被挤出去这件事本身。
    assert m._max_sounds == 50, "夹具没在旧上限下跑"
    evicted = [g for g in guns if f"gun-{g}-离子" not in m._sounds]
    assert len(evicted) >= 10, (
        f"30 把枪装进 50 格只挤掉了 {len(evicted)} 把 —— 这条守卫在空转，冲爆那件事没被复现")
    assert "gun-ak47-离子" not in m._sounds, (
        "AK-47 居然还在缓存里 —— 它是最先装的那几把，也是玩家最可能拿来测的那把")


def test_the_preload_raises_the_cap_before_loading_guns():
    """AST：抬上限那一步必须**在**装枪声之前 —— 反了就等于没抬。"""
    import ast

    src = (REPO / "core" / "audio" / "audio_manager.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "load_all_enabled_sounds"
    )
    order = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "_raise_cache_cap_for_guns":
                order.append(("raise", node.lineno))
            elif node.func.attr == "load_gun_sound":
                order.append(("load", node.lineno))
    assert [k for k, _ in order] == ["raise", "load"], f"顺序不对：{order}"
