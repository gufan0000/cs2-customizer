# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""导入器摆好的位置，**产品到底会不会去读**（2026-09-17）。

## 这一族缺陷长什么样

导入报「成功」、文件确实躺在资源目录里、设置页的下拉框里也看得见那个风格 ——
**而进游戏一声不响**。用户不会怀疑导入，他会怀疑软件坏了。

五路审计 + 实测逮到的四条，根都是同一个：
**算落点的三层（识别 / 归类 / 落盘）从来没问过一句「产品那头怎么找」。**

| 摆出来的 | 产品那头找的 | 真源 |
|---|---|---|
| `kill_sounds/清脆/爆头.mp3` | `1.*` ~ `5.*` | `style_creator.CATEGORY_TEMPLATES` 的 `numbered` |
| `gun_sounds/沙漠之鹰/…` | 20+ 个**小写武器代号** | `gun_sound_profiles.GUN_SOUND_WEAPON_TYPES` |
| `round_sounds/回合音效包/胜利/…` | 8 个**固定事件目录名** | `resource_placement.ROUND_BUCKETS` |
| 风格名 `default` | 保留名，产品当它不存在 | `style_creator.validate_style_name` |

⭐⭐⭐ 这四条规则**各自都有真源**，只是没人回头看一眼 ——
所以修法不是新写一张表，是让归类器去读那四张已有的表（`core/resource_readback.py`）。

（本项目测试逐文件跑：
 `python -m pytest tests/test_what_we_write_is_what_the_product_reads.py`）
"""
from __future__ import annotations

import pytest

from core.resource_placement import detect_c4_events, plan_placements
from core.resource_readback import (
    known_buckets,
    layout_of,
    normalize_bucket,
    numbered_slots,
    renumber,
)


def _targets(plan):
    return [item.target_rel_path for item in plan.placements]


def _joined(plan):
    return "\n".join(plan.warnings)


# ------------------------------------------------ ① 编号制：产品只按 1~5 找

def test_a_kill_sound_pack_with_named_files_is_renumbered(tmp_path):
    """⭐⭐⭐ 本文件的主判据。

    `AudioManager._load_range` 对 1~5 逐个 `find_audio_by_stem`，
    而 `list_style_dirs_with_audio` 只要目录里有音频就把它算成一个风格 ⇒
    `清脆/爆头.mp3` 这种包**会出现在设置页的下拉框里，而进游戏一声不响**。
    ⭐ 这是这个功能能犯的最隐蔽的错误：每一步都显示成功。
    """
    plan = plan_placements("kill_sounds",
                           ["清脆/爆头.mp3", "清脆/双杀.mp3"], style_name="清脆")
    assert _targets(plan) == ["audio/kill_sounds/清脆/2.mp3",
                              "audio/kill_sounds/清脆/1.mp3"]
    assert "重命名" in _joined(plan), "替用户改了名却不说，等于偷偷动了他的文件"


def test_a_pack_that_is_already_numbered_is_left_alone():
    """⛔ 官网包最常见的形态就是 `1.mp3`~`5.mp3` —— 重排会打乱作者编好的顺序。"""
    plan = plan_placements("kill_sounds",
                           ["清脆/1.mp3", "清脆/2.mp3", "低沉/1.mp3"],
                           style_name="清脆")
    assert _targets(plan) == ["audio/kill_sounds/清脆/1.mp3",
                              "audio/kill_sounds/清脆/2.mp3",
                              "audio/kill_sounds/低沉/1.mp3"]
    assert "重命名" not in _joined(plan)


def test_each_style_folder_is_numbered_from_one():
    """⚠ 按**风格目录**分别编号。整包一起编会让第二个风格从 4 开始，
    而产品找的是 1~5 —— 那个风格照样不响。"""
    plan = plan_placements(
        "kill_sounds",
        ["甲/a.mp3", "甲/b.mp3", "乙/x.mp3", "乙/y.mp3"], style_name="甲")
    assert sorted(_targets(plan)) == sorted([
        "audio/kill_sounds/甲/1.mp3", "audio/kill_sounds/甲/2.mp3",
        "audio/kill_sounds/乙/1.mp3", "audio/kill_sounds/乙/2.mp3",
    ])


def test_files_beyond_the_five_slots_are_reported_not_silently_dropped():
    """⭐ 多出来的不导入可以，**不说一声**不行。"""
    plan = plan_placements("kill_sounds",
                           [f"清脆/{ch}.mp3" for ch in "abcdefg"],
                           style_name="清脆")
    assert len(plan.placements) == numbered_slots("kill_sounds") == 5
    assert "没有导入" in _joined(plan)
    assert "f.mp3" in _joined(plan) or "g.mp3" in _joined(plan), \
        "要点名是哪几个，不然用户不知道少了什么"


def test_renumber_is_stable_across_two_imports():
    """⛔ 同一个包导两次必须得到同一个结果。

    ⭐ 按包里的条目顺序"先到先得"会让结果取决于打包工具 ——
    `kill_icon_pack._collect_loose_items` 已经为这件事栽过一次。
    """
    first, _ = renumber(["b.mp3", "a.mp3", "c.mp3"], 5)
    second, _ = renumber(["c.mp3", "b.mp3", "a.mp3"], 5)
    assert first == second


# ------------------------------------------------ ② 武器层：产品只认代号

def test_an_uppercase_weapon_folder_is_normalised():
    """⚠ `AK47/` 在 Windows 上碰巧能撞对（文件系统不分大小写），
    ⭐ 而「碰巧能用」和「对」在测试报告上长得一模一样。"""
    plan = plan_placements("gun_sounds", ["AK47/默认/1.wav"], style_name="默认")
    assert _targets(plan) == ["audio/gun_sounds/ak47/默认/1.wav"]


def test_a_chinese_weapon_folder_is_called_out_not_guessed():
    """⛔⛔ 产品按代号找目录，`沙漠之鹰/` 这一套**永远不会响**。

    ⭐ 这里**不猜**（不建「沙鹰 ⇒ deagle」那种黑话表）：猜错一个武器名，
    用户是**进游戏之后**才发现的，而那时他已经不记得导过什么。
    ⇒ 明说，并告诉他该改成什么。
    """
    plan = plan_placements("gun_sounds", ["沙漠之鹰/默认/1.wav"], style_name="默认")
    assert "不会响" in _joined(plan)
    assert "代号" in _joined(plan), "光说不行，要说该改成什么"


def test_a_weapon_that_cannot_be_guessed_asks_instead_of_inventing_one():
    """⛔⛔ 猜不出武器名时曾经兜底成 **「新风格」当武器目录**。

    ⚠ 触发条件很窄，正因为窄才一直没被发现：判断写的是
    「**一个都猜不出**才问」，于是只要包里有一个文件猜得出（`ak47.wav`），
    其余猜不出的就一路走到 `_clean_name("")` 的兜底。
    ⭐⭐ 「有一个能猜出来」不等于「这一包都能猜出来」—— 分母不是同一个。
    """
    plan = plan_placements("gun_sounds",
                           ["沙漠之鹰.wav", "ak47.wav"], style_name="默认")
    assert not plan.placements, "拿不准就不许落盘"
    assert [q["field"] for q in plan.questions] == ["bucket"]
    assert not any("新风格" in item.target_rel_path for item in plan.placements)


def test_the_weapon_list_comes_from_the_product_not_from_here():
    """⛔ 棘轮：武器名单必须**现读产品的表**，不许在导入这边抄一份。"""
    from core.gun_sound_profiles import GUN_SOUND_WEAPON_TYPES

    allowed = known_buckets("gun_sounds")
    assert allowed == frozenset(str(w).lower() for w in GUN_SOUND_WEAPON_TYPES)
    assert len(allowed) >= 20, f"只认出 {len(allowed)} 把武器，多半读错了表"


@pytest.mark.parametrize("raw,expect", [
    ("AK47", "ak47"), ("AK-47", "ak47"), ("ak47", "ak47"),
    ("Desert Eagle", "deagle"), ("M4A4", "m4a1"),
])
def test_known_weapon_spellings_are_normalised(raw, expect):
    """⭐ 只归一**有据可查**的写法（代号本身、产品档案里的 display_name）。"""
    assert normalize_bucket("gun_sounds", raw) == expect


# ------------------------------------------------ ③ 回合事件：用户答过的不许被顶掉

def test_the_answer_the_user_gave_is_not_overwritten_by_a_folder_name():
    """⛔⛔ 用户在弹窗里选了 `win`，而外壳目录名把它顶掉了。

    实测落成 `audio/round_sounds/回合音效包/胜利/1.mp3` —— 产品只认
    8 个固定事件名，这个目录**永远不会被读到**，而导入报成功。
    ⭐⭐ **用户明确回答过的东西，不许再被推断出来的东西覆盖。**
    """
    plan = plan_placements("round_sounds", ["胜利/1.mp3"], style_name="默认",
                           bucket="win", outer_layer="回合音效包")
    assert _targets(plan) == ["audio/round_sounds/win/默认/1.mp3"]


def test_a_round_pack_without_an_event_asks_instead_of_landing():
    plan = plan_placements("round_sounds", ["胜利/1.mp3"], style_name="默认",
                           outer_layer="回合音效包")
    assert [q["field"] for q in plan.questions] == ["bucket"]
    assert not plan.placements


# ------------------------------------------------ ④ 结构层不是内容层

def test_a_category_folder_does_not_become_the_style_name():
    """⛔ `kill_sounds/1.mp3` 曾经落成 `audio/kill_sounds/kill_sounds/1.mp3`。

    ⭐ 一段路径既可能是"结构"也可能是"内容"，分不清就会把结构当成内容 ——
    而用户填的风格名被整个丢掉了。
    """
    plan = plan_placements("kill_sounds", ["kill_sounds/1.mp3"], style_name="清脆")
    assert _targets(plan) == ["audio/kill_sounds/清脆/1.mp3"]


# ------------------------------------------------ ⑤ 风格名要产品收得下

def test_a_reserved_style_name_is_called_out():
    """⚠ `default` 是产品的保留名 —— 目录建得出来，产品当它不存在。"""
    plan = plan_placements("kill_sounds", ["1.mp3"], style_name="default")
    assert "收不下" in _joined(plan)


# ------------------------------------------------ ⑥ 两个文件落到一个位置

def test_two_files_landing_on_one_target_are_reported():
    """⭐ 后一个盖掉前一个，而计数会报两个 —— 用户丢了一个文件还以为都进去了。"""
    plan = plan_placements("death", ["甲/death.mp3", "乙/death.mp3"])
    assert "同一个位置" in _joined(plan)


# ------------------------------------------------ ⑦ C4：很泛的关键词会吃掉别的

def test_a_broad_token_does_not_swallow_the_other_events():
    """⛔ 「安放」的 tokens 里有个很泛的 `bomb`，原来会把
    `bomb_defused.mp3` 认成"安放已就位" ⇒ **该报的"不会响"一个字都没报**。

    ⭐⭐ 一条很泛的关键词会把它旁边那几条的判断一起吃掉，
    而这里的产出正是"不会响"的唯一预警 —— 漏报等于没有预警。
    """
    found = detect_c4_events(["bomb_defused.mp3", "bomb_exploded.mp3"])
    assert "安放" not in found, f"安放被误判成已就位：{found}"
    assert found.get("拆除") == "bomb_defused.mp3"


def test_a_complete_c4_pack_still_matches_all_three():
    found = detect_c4_events(["bomb_planted.mp3", "defuse.mp3", "explode.mp3"])
    assert set(found) == {"安放", "拆除", "爆炸"}


def test_a_c4_pack_missing_an_event_says_which_one():
    plan = plan_placements("c4_sounds", ["风格/bomb_defused.mp3"], style_name="风格")
    assert "安放" in _joined(plan)


# ------------------------------------------------ ⑧ 击杀图标：说清与专用链路的差别

def test_a_kill_icon_pack_missing_levels_is_called_out():
    """⛔ 统一链路只做 `shutil.copy2`，缺等级不会有任何人告诉用户。"""
    paths = [f"{n}.{ext}" for n in ("1", "2") for ext in ("png", "json")]
    plan = plan_placements("kill_icons", paths, style_name="天使")
    assert "3、4、5" in _joined(plan) or "缺" in _joined(plan)


def test_a_loose_kill_icon_pack_is_pointed_at_the_real_importer():
    """⭐ `1.gif` / `3/` 这种"松散包"要打图集，而这条链路不会 ——
    如实说，并把用户指到那条真正能处理它的入口。"""
    plan = plan_placements("kill_icons", ["1.gif", "ace.webp"], style_name="天使")
    assert "击杀图标" in _joined(plan)


# ------------------------------------------------ ⑨ 这一层的真源不许被抄第二份

def test_the_layout_rules_come_from_the_product_template_table():
    """⛔ 棘轮：`numbered` / `single` / `flat` 必须**现读** `CATEGORY_TEMPLATES`。"""
    from core.audio.style_creator import CATEGORY_TEMPLATES

    seen = 0
    for template in CATEGORY_TEMPLATES.values():
        assert layout_of(template.root) == template.layout, template.root
        seen += 1
    assert seen >= 5, f"只对上了 {seen} 条模板，多半读错了表"
    assert layout_of("flash_images") == "free", "产品不挑名字的类要留成 free"
