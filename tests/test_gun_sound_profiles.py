# SPDX-License-Identifier: GPL-3.0-or-later
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


# ================================================ RN-254：页面文案不许点名选不到的枪

#: 这一页把 17 把全自动枪排除在外（`FULL_AUTO_GUN_SOUND_WEAPON_TYPES`），
#: 所以页面上的**控件文案**不许再教用户去调它们。
#: ⚠ 2026-08-23 实测：静音覆盖那颗滑块的 tooltip 写着「连发武器往短了调」——
#: 而连发武器在这一页根本选不到。属 RN-167 族（文案点名了这一页不存在的东西），
#: 而 RN-167 那条棘轮只查**按钮名**，看不见这种「点名一类武器」的写法。
#: ⭐ **一个教训只修在它被发现的那条轴上，等于只修了一份副本。**
_CLASSES_NOT_ON_THIS_PAGE = ("连发", "全自动", "步枪", "冲锋枪", "机枪")

#: ⛔ 帮助面板**不在这条判据的管辖里**，那是有意的：
#: `ui_help_panel` 的 gun_sound 段落写着「连发武器（步枪、冲锋枪、机枪）暂未开放」——
#: 那是**明确说明它没有**，正是玩家需要知道的。判据要防的是「教你去调它」，
#: 不是「告诉你没有它」。⇒ 只扫页面自己的控件文案。


def test_the_page_does_not_name_weapon_classes_it_cannot_select():
    import ast
    from pathlib import Path

    from _denominator import must_scan

    src = Path(__file__).resolve().parent.parent / "pages" / "gun_sound_page.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    # ⭐ 两个分母都要在：这一页得真的有文案，那张「这一页选不到的武器类」名单也不许空。
    must_scan([n for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)],
              "gun_sound 页里的字符串字面量", least=20)
    must_scan(_CLASSES_NOT_ON_THIS_PAGE, "_CLASSES_NOT_ON_THIS_PAGE（这一页选不到的武器类）")

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        hit = [w for w in _CLASSES_NOT_ON_THIS_PAGE if w in node.value]
        if hit:
            offenders.append((node.lineno, hit, node.value[:60]))

    assert not offenders, (
        "gun_sound 页的文案点名了这一页选不到的武器类：\n"
        + "\n".join(f"  :{ln} {hit} -> {text!r}" for ln, hit, text in offenders)
        + "\n这一页只开放半自动/单发武器；要么按射速说（「点得快的枪」），"
          "要么明确说「暂未开放」，别教用户去调一个他找不到的东西。"
    )


def test_that_judge_is_not_vacuous():
    """空转守卫：先证明这条判据看得见那句原文。"""
    bad = "太长会盖掉下一枪；连发武器往短了调。"
    assert [w for w in _CLASSES_NOT_ON_THIS_PAGE if w in bad] == ["连发"], (
        "词表已经认不出 RN-254 那句原话了 —— 这条判据现在是空转的。"
    )
