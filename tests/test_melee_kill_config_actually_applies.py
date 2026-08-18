# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-016：近战（刀 / 电击枪）击杀的配置必须真的生效。

**修之前它 100% 是死配置**，两道关卡各堵一半：
1. `_resolve_kill_weapon` 无条件把近战击杀改写成「上一把非刀武器」——
   于是用户在「击杀音效」页里给近战选的风格永远轮不到。
2. 就算改写不成立（这局还没开过枪），留下的也是 GSI 报回来的**皮肤名**
   （`weapon_knife_karambit` 之类，所以原代码才用 `startswith`），
   而配置表的键只有 `weapon_knife` 一个 —— 两边对不上，照样查不到。

⇒ 「设了没反应」是这一类里最难查的缺陷：不报错、不崩溃、日志也正常，
用户只会觉得"这软件的这个功能坏了"。

**默认行为必须一点不变**：没配近战风格的人，刀杀依旧沿用上一把枪的设置。
下面四条把这两半分别钉死，外加一条守住默认。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gsi_handler_kills  # noqa: E402
from config import config  # noqa: E402


class _DummyAudio:
    weapon_kill_sound_styles: dict = {}
    weapon_kill_voice_styles: dict = {}
    kill_sound_styles: list = []
    kill_voice_styles: list = []
    weapon_sounds_dir = ""
    kill_sounds_dir = ""
    weapon_voices_dir = ""
    kill_voices_dir = ""


@pytest.fixture()
def handler(monkeypatch):
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", _DummyAudio())
    return gsi_handler_kills.GSIHandlerKills()


@pytest.mark.parametrize("skin", [
    "weapon_knife",
    "weapon_knife_karambit",
    "weapon_knife_butterfly",
    "weapon_bayonet",   # 反例：CS2 里刺刀不叫 weapon_knife 开头，不该被归一
])
def test_melee_skin_names_normalize_to_the_configured_key(handler, skin):
    """GSI 报的是皮肤名，配置表的键只有 `weapon_knife` —— 必须归一得上。"""
    got = handler._melee_config_key(skin)
    if skin.startswith("weapon_knife"):
        assert got == "weapon_knife", f"{skin} 没归一到配置键，配置永远查不到"
    else:
        assert got == "", f"{skin} 不该被当成近战归一"


def test_taser_normalizes_and_rifles_do_not(handler):
    assert handler._melee_config_key("weapon_taser") == "weapon_taser"
    assert handler._melee_config_key("weapon_ak47") == ""
    assert handler._melee_config_key("") == ""


def test_configured_melee_style_wins_over_the_last_gun(handler, monkeypatch):
    """用户明确给刀配了风格，就必须用他配的 —— 不许再沿用上一把枪。"""
    monkeypatch.setattr(config, "weapon_kill_sounds",
                        {"weapon_knife": "刀专属", "weapon_ak47": "步枪风格"},
                        raising=False)
    handler.last_melee_fallback_weapon = "weapon_ak47"

    got = handler._apply_melee_fallback("weapon_knife_karambit", config.weapon_kill_sounds)
    assert got == "weapon_knife", (
        f"用户给刀配了「刀专属」，实际却用了 {got} 的设置 —— "
        "这就是「设了没反应」：不报错、不崩溃、日志也正常")


def test_unconfigured_melee_still_falls_back_to_the_last_gun(handler, monkeypatch):
    """没配近战的人，默认行为一点不能变：刀杀沿用上一把非刀武器。"""
    monkeypatch.setattr(config, "weapon_kill_sounds",
                        {"weapon_knife": "0", "weapon_ak47": "步枪风格"},
                        raising=False)
    handler.last_melee_fallback_weapon = "weapon_ak47"

    got = handler._apply_melee_fallback("weapon_knife_karambit", config.weapon_kill_sounds)
    assert got == "weapon_ak47", (
        f"没配近战风格时应沿用上一把枪 weapon_ak47，实际是 {got} —— 默认行为被改坏了")


def test_sound_and_voice_decide_independently(handler, monkeypatch):
    """只给刀配了音效、没配语音时：音效走刀的，语音沿用上一把枪。

    ⚠ 这一条是把判断从「武器解析」挪到「各自取键函数」的**唯一理由**。
    放在武器解析里一刀切就做不到这件事，而这个组合是用户完全会碰到的。
    """
    monkeypatch.setattr(config, "weapon_kill_sounds",
                        {"weapon_knife": "刀专属音效"}, raising=False)
    monkeypatch.setattr(config, "weapon_kill_voices",
                        {"weapon_knife": "0"}, raising=False)
    handler.last_melee_fallback_weapon = "weapon_ak47"

    assert handler._apply_melee_fallback(
        "weapon_knife_karambit", config.weapon_kill_sounds) == "weapon_knife"
    assert handler._apply_melee_fallback(
        "weapon_knife_karambit", config.weapon_kill_voices) == "weapon_ak47"


def test_resolve_kill_weapon_no_longer_rewrites_the_weapon_name(handler):
    """武器解析只记回退目标，不再改写武器名 —— 改写是下游按各自配置表做的。"""
    handler.frame_inferred_fire_weapon = "weapon_knife_karambit"
    handler.last_non_knife_weapon = "weapon_ak47"

    got = handler._resolve_kill_weapon()
    assert got == "weapon_knife_karambit", (
        f"武器解析把近战改写成了 {got}；改写一旦发生在这里，"
        "音效和语音就只能共用同一个结论，无法各按各的配置表决定")
    assert handler.last_melee_fallback_weapon == "weapon_ak47"


def test_kill_voice_page_offers_the_melee_category():
    """「击杀语音」页必须和「击杀音效」页一样能配近战 —— 别再一边有一边没有。"""
    from pages.kill_sound_page import KillSoundPage
    from pages.kill_voice_page import KillVoicePage

    sound_melee = {w for ws in KillSoundPage.CATEGORIES.values() for w in ws
                   if w.startswith("weapon_knife") or w == "weapon_taser"}
    voice_melee = {w for ws in KillVoicePage.CATEGORIES.values() for w in ws
                   if w.startswith("weapon_knife") or w == "weapon_taser"}
    assert sound_melee, "「击杀音效」页自己就没有近战，这条判据在空转"
    assert voice_melee == sound_melee, (
        f"两页的近战武器不一致：音效 {sorted(sound_melee)} / 语音 {sorted(voice_melee)}。"
        "刀杀和电人是最想要播报的两种击杀，不该只有一边能配。")
    for weapon in voice_melee:
        assert weapon in KillVoicePage.WEAPON_NAMES, f"{weapon} 没有中文名，界面上会显示原始键名"


def test_both_key_getters_actually_apply_the_melee_fallback():
    """两个取键函数都必须真的调用 `_apply_melee_fallback`。

    ⚠ 上面那些判据测的是**归一函数本身**，谁把调用点删掉它们照样全绿 ——
    而删掉调用点，近战配置就又变回死配置了。所以这里用 AST 钉住调用点。
    用 AST 不用 grep：注释里、字符串里出现同名不算数。
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parent.parent / "gsi_handler_kills.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    wanted = {"_get_weapon_kill_sound_key", "_get_weapon_kill_voice_key"}
    seen = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            seen[node.name] = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "_apply_melee_fallback"
                for n in ast.walk(node))

    assert set(seen) == wanted, f"没找到这些函数：{wanted - set(seen)}"
    missing = sorted(name for name, ok in seen.items() if not ok)
    assert not missing, (
        f"{missing} 没有调用 `_apply_melee_fallback` —— "
        "近战击杀会重新变成「设了没反应」的死配置，而且不报任何错")
