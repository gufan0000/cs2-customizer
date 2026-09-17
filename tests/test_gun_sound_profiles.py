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


def test_every_profiled_gun_is_selectable_at_runtime():
    """2026-09-17 反转：这条以前断言 ak47/mp9/cz75a **在排除表里**。

    排除表从仓库首个提交起写死 17 把全自动、上方无一字解释（RN-432），查实没有技术原因
    （前身版本只发过 10 把半自动，2.0 重构把档案扩到 35 把后用它收回到旧的那一档）。
    ⇒ 现在断言的是反面：**档案表里的每一把枪，运行期都必须在。**
    """
    assert FULL_AUTO_GUN_SOUND_WEAPON_TYPES == ()
    assert SUPPORTED_GUN_SOUND_WEAPON_TYPES == GUN_SOUND_WEAPON_TYPES
    assert len(SUPPORTED_GUN_SOUND_WEAPON_TYPES) == 35
    for gun_type in ("ak47", "mp9", "cz75a", "xm1014", "scar20", "negev"):
        assert gun_type in SUPPORTED_GUN_SOUND_WEAPON_TYPES


@pytest.mark.parametrize("gun_type", ["usp", "deagle", "scar20", "g3sg1"])
def test_fast_fire_profiles_have_peak_ducking(gun_type: str):
    profile = GUN_SOUND_PROFILES[gun_type]
    cfg = _DummyConfig()
    setattr(cfg, profile.mute_duration_key, 0.25)

    plan = build_gun_sound_duck_plan(cfg, profile, is_burst=False, hold_duration=0.25)

    assert plan.peak_ratio <= plan.sustain_ratio
    assert plan.peak_ms > 0


# ================================================ RN-254 → 反转：文案不许说有哪类枪「不开放」

#: 2026-08-23 这条判据的形态是「页面文案不许点名 连发/全自动/步枪/冲锋枪/机枪」——
#: 因为那 17 把枪在这一页根本选不到，教用户去调它们是 RN-167 族（点名不存在的东西）。
#: 2026-09-17 全自动开放之后，页签名就叫「步枪 / 冲锋枪 / 机枪」，那张词表的前提没了。
#: ⭐ **判据反转不删**：它记录的教训是「文案说的和页面上有的必须一致」，前提翻面了，
#: 教训还在 —— 现在要防的是反面：页头 / 帮助面板还留着一句「自动武器暂不支持」，
#: 而页签里就摆着 AK-47。⇒ 扫**页面 + 帮助面板**里所有字符串字面量，不许出现这些说法。
_OFF_LIMITS_PHRASES = ("暂未开放", "暂不支持", "不支持", "被排除", "只开放", "只支持", "未开放")


def _page_and_help_strings():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    found = []
    for rel in ("pages/gun_sound_page.py", "ui_help_panel.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.append((rel, node.lineno, node.value))
    return found


def test_the_copy_does_not_say_a_weapon_class_is_off_limits():
    from _denominator import must_scan

    from core.gun_sound_profiles import GUN_SOUND_TAB_GROUPS, SUPPORTED_GUN_SOUND_TAB_GROUPS

    # ⭐ 先证前提：页签一个都没被藏起来，文案才没资格说「某类不开放」。
    assert SUPPORTED_GUN_SOUND_TAB_GROUPS == GUN_SOUND_TAB_GROUPS

    strings = _page_and_help_strings()
    must_scan(strings, "gun_sound 页 + 帮助面板里的字符串字面量", least=20)
    must_scan(_OFF_LIMITS_PHRASES, "_OFF_LIMITS_PHRASES（「不开放」的各种说法）", least=4)

    # 只看**会显示出来、且说的是武器**的那些句子：帮助面板是一个大 dict，别的页面的段落
    # 也在同一个文件里，所以要求句子里同时出现「枪 / 武器」二字之一。
    offenders = [
        (rel, ln, text[:70])
        for rel, ln, text in strings
        if any(p in text for p in _OFF_LIMITS_PHRASES)
        and ("枪" in text or "武器" in text)
        and ("gun_sound" in rel or "枪声" in text)
    ]
    assert not offenders, (
        "枪声页 / 帮助面板还在说有哪类枪不开放，而页签里就摆着它们：\n"
        + "\n".join(f"  {rel}:{ln} -> {text!r}" for rel, ln, text in offenders)
        + "\n⭐ 文案说的和页面上有的必须一致（RN-254 的反面）。"
    )


def test_that_judge_is_not_vacuous():
    """空转守卫：先证明这条判据看得见 2026-09-17 之前页头那句原话。"""
    bad = "开火后压住原始枪声、换成你自己的音效。目前只开放半自动武器（手枪 / 狙击枪 / 霰弹枪 / 宙斯），自动武器暂不支持。"
    assert [p for p in _OFF_LIMITS_PHRASES if p in bad], (
        "词表已经认不出旧页头那句话了 —— 这条判据现在是空转的。"
    )
    assert "枪" in bad or "武器" in bad
