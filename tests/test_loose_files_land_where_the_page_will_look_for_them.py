# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""归类器：散装文件摆出来的位置，必须是**页面真正会去找的那个位置**（2026-09-16）。

## 这一条守的是什么

"导入成功"和"页面上能看到"是两件事。文件复制过去了、路径也合法，
但只要少一层目录，那一类的设置页就是空的 —— ⭐ **而这个失败是完全静默的**。

⚠⚠ 这不是假想：第一版 `NEEDS_STYLE_NAME` 就漏了带 bucket 的那五类
（`gun_sounds` 之类是「`<武器>/<风格>/文件`」**三层**），摆出来是
`gun_sounds/ak47/AK47.wav`，少了风格那一层。
**是手验一眼看出来的，不是判据逮的** —— 所以现在补上这条判据。

## 三个特例，每一个都长得像别人但不是

| 类 | 它特殊在哪 |
|---|---|
| `death` | 平铺：`audio/death/<风格>.mp3`，**文件本身就是一个风格** |
| `round_sounds` | 中间多一层**固定**子事件（8 个），不问就不知道放哪 |
| `c4_sounds` | 三事件共用一个风格目录，靠**文件名关键词**分辨，认不出就**不响** |

（本项目测试逐文件跑：
 `python -m pytest tests/test_loose_files_land_where_the_page_will_look_for_them.py`）
"""
from __future__ import annotations

import pytest

from core.resource_catalog import get_resource_spec
from core.resource_identify import STYLE_SHAPED, WEAPON_SHAPED
from core.resource_placement import (
    C4_EVENT_TOKENS,
    ROUND_BUCKETS,
    detect_c4_events,
    plan_placements,
)


def _targets(plan):
    return [item.target_rel_path for item in plan.placements]


# ------------------------------------------------- 层数：最容易静默错的地方

@pytest.mark.parametrize("spec_key", WEAPON_SHAPED)
def test_a_weapon_shaped_class_keeps_both_its_layers(spec_key):
    """⭐⭐ 这五类是 **bucket + 风格两层都有**。

    第一版漏掉风格那一层，页面上一个风格都读不到 —— 而复制是成功的。
    """
    plan = plan_placements(spec_key, ["AK47.wav"], style_name="沙漠之鹰")
    assert plan.ready, f"{spec_key}: {plan.questions}"
    target = _targets(plan)[0]
    root = get_resource_spec(spec_key).target_rel_root
    assert target.startswith(root + "/"), target
    tail = target[len(root) + 1:]
    assert tail.count("/") == 2, (
        f"{spec_key} 摆成了 `{tail}` —— 这一类的结构是"
        "「<武器或投掷物>/<风格>/文件」三段，少一段页面就读不到。"
    )
    assert "沙漠之鹰" in target, "风格名没进路径"


@pytest.mark.parametrize("spec_key", STYLE_SHAPED)
def test_a_style_shaped_class_has_exactly_one_layer(spec_key):
    plan = plan_placements(spec_key, ["1.mp3"], style_name="清脆")
    assert plan.ready, f"{spec_key}: {plan.questions}"
    root = get_resource_spec(spec_key).target_rel_root
    tail = _targets(plan)[0][len(root) + 1:]
    assert tail == "清脆/1.mp3", tail


# ------------------------------------------------- 特例一：平铺的被击杀音效

def test_death_sounds_are_flat_files_not_style_folders():
    """⭐ 拿真实资源目录看出来的：`audio/death/` 下躺的是 `death1.mp3`，
    而隔壁 `kill_sounds/` 下是 `21冠军/` 这样的目录。

    **同一个 `audio/` 根下两种约定**，而 `resource_catalog` 里两者的声明一模一样。
    """
    plan = plan_placements("death", ["death1.mp3", "death2.mp3"])
    assert _targets(plan) == ["audio/death/death1.mp3", "audio/death/death2.mp3"]
    assert plan.ready, "被击杀音效不该问风格名 —— 文件名就是风格名"
    assert plan.warnings, "要告诉用户「会多出 N 个风格」，否则他看到结果会困惑"


def test_death_does_not_ask_for_a_style_name():
    plan = plan_placements("death", ["x.mp3"])
    assert not plan.questions


# ------------------------------------------------- 特例二：回合音效的子事件

def test_round_sounds_must_be_told_which_event():
    """⚠ 8 个子事件是**固定集合**，不是用户起的名字。
    放错目录那一档永远不响，而导入是"成功"的。"""
    plan = plan_placements("round_sounds", ["a.mp3"], style_name="默认")
    assert not plan.ready
    question = next(q for q in plan.questions if q["field"] == "bucket")
    assert set(question["choices"]) == set(ROUND_BUCKETS)
    assert question["why"], "要说明为什么问，否则用户会随便选一个"


def test_round_sounds_with_the_event_given_land_under_it():
    plan = plan_placements(
        "round_sounds", ["a.mp3"], style_name="默认", bucket="win")
    assert _targets(plan) == ["audio/round_sounds/win/默认/a.mp3"]


def test_an_event_name_outside_the_fixed_set_is_refused():
    """⛔ 不许自由填 —— `win2` 这种目录产品永远不会去读。"""
    plan = plan_placements(
        "round_sounds", ["a.mp3"], style_name="默认", bucket="win2")
    assert not plan.ready, "编造的子事件名被接受了"


# ------------------------------------------------- 特例三：C4 的静默失败

def test_c4_warns_about_the_event_it_cannot_hear():
    """⭐⭐ 这是"装进去了但不会响"的唯一一道预警。

    `find_audio_by_tokens` 一个关键词都没命中就返回 None，**不回落、直接不响**。
    """
    plan = plan_placements(
        "c4_sounds", ["bomb_planted.mp3", "exploded.mp3"], style_name="默认")
    assert plan.ready, "只是提示，不该拦住导入"
    blob = " ".join(plan.warnings)
    assert "拆除" in blob, f"没提醒缺了拆除那一声：{plan.warnings}"
    assert "安放" not in blob, "安放明明命中了，不该报它缺"


def test_c4_with_all_three_events_says_nothing():
    """反面守卫：三声齐全时不许乱报，否则这条提示会被用户学会忽略。"""
    plan = plan_placements(
        "c4_sounds",
        ["planted.mp3", "defuse.mp3", "explode.mp3"],
        style_name="默认")
    assert not [w for w in plan.warnings if "不会响" in w]


@pytest.mark.parametrize("event", list(C4_EVENT_TOKENS))
def test_each_c4_event_can_be_detected_by_a_chinese_filename(event):
    """⭐ 中文文件名也要认 —— 社区里的包大多是中文命名的。"""
    found = detect_c4_events([f"{event}.mp3"])
    assert event in found, f"「{event}.mp3」这个名字没被认出来"


# ------------------------------------------------- 安全：名字不许变成路径

@pytest.mark.parametrize("evil", [
    "../../../evil",
    "..\\..\\evil",
    "a/b",
    "C:evil",
])
def test_a_style_name_can_never_become_a_path(evil):
    """用户打进来的风格名是**外来输入**，它只能是一段目录名。"""
    plan = plan_placements("kill_sounds", ["1.mp3"], style_name=evil)
    target = _targets(plan)[0]
    tail = target[len("audio/kill_sounds/"):]
    assert tail.count("/") == 1, f"风格名把路径撑开了：{target}"
    assert ".." not in target, target


def test_an_empty_style_name_is_asked_for_not_invented():
    """⛔ 不替用户编默认值 —— 编出来的会变成他资源库里一个莫名其妙的目录。"""
    plan = plan_placements("kill_sounds", ["1.mp3"], style_name="   ")
    assert not plan.ready
    assert any(q["field"] == "style_name" for q in plan.questions)


# ------------------------------------------------- 不支持的要老实说

def test_utility_guides_says_it_cannot_place_automatically():
    """⭐ 「地图 / 分组」两层靠文件名猜不出来，而猜错了用户是进游戏才发现的。
    ⇒ 引导他手动放，别假装能自动。"""
    plan = plan_placements("utility_guides", ["smoke.jpg"], style_name="x")
    assert not plan.placements
    assert plan.warnings and "自己放" in " ".join(plan.warnings)


def test_an_unknown_category_is_reported_not_crashed():
    plan = plan_placements("不存在的类别", ["1.mp3"], style_name="x")
    assert not plan.placements
    assert plan.warnings
