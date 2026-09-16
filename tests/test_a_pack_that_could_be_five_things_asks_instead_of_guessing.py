# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""识别器：拿不准的时候必须**问**，而且要给用户看得懂的证据（2026-09-16）。

## 这一条守的是什么

产品里有 **5 类音频共用**「`<武器>/<风格>/*.音频`」这一种结构
（`gun_sounds` / `switch_weapons` / `reload_sounds` /
`weapon_kill_sounds` / `weapon_kill_voices`），扩展名也完全相同。

⭐⭐⭐ **机器在原理上分不清它们。** 所以这里钉的不是"识别得准不准"，
而是**分不清的时候有没有老实说**：

- 分不清 ⇒ `unsure`，且 `preselect` 必须是 **None**；
- ⛔ 不许替用户预选一个。预选错了是**静默的**：文件进了错目录，
  那一类的页面上一个风格都没有，而用户以为自己导进去了。

## 手验逮到过的两件事，都在下面钉死了

1. 同一类命中**多个词**（"CF爆头音效 击杀音效包" 同时命中「击杀音效」和「击杀音」）
   ⇒ 备选里出现两次同一个类。
2. `guesses[0]` 在 `unsure` 档也是个具体类别 ⇒ UI 照着它预选就是替用户瞎猜。

⚠ 两条都不是推理出来的，是**把真实形状喂进去看输出**看出来的。

（本项目测试逐文件跑：
 `python -m pytest tests/test_a_pack_that_could_be_five_things_asks_instead_of_guessing.py`）
"""
from __future__ import annotations

from core.resource_identify import (
    CERTAIN,
    LIKELY,
    UNSURE,
    WEAPON_SHAPED,
    identify_groups,
    match_category_words,
    read_manifest,
)

#: 五类同构的真实形状：两层目录 + 音频。
FIVE_WAY = ["AK47/默认/1.wav", "AK47/默认/2.wav", "M4A1/默认/1.wav"]


def _only(groups):
    assert len(groups) == 1, f"应该只归成一组，实际 {len(groups)} 组"
    return groups[0]


# ------------------------------------------------- 分不清的时候不许替用户选

def test_a_five_way_shape_with_no_other_signal_is_unsure():
    group = _only(identify_groups(FIVE_WAY, source_name="素材.zip"))
    assert group.confidence == UNSURE, (
        "五类同构的包被判成了有把握 —— 而机器在原理上分不清它们。"
    )


def test_an_unsure_group_preselects_nothing():
    """⭐⭐ 这是本文件最重要的一条。

    `guesses` 非空不代表可以预选：拿不准时那个第一名只是候选表的表头。
    """
    group = _only(identify_groups(FIVE_WAY, source_name="素材.zip"))
    assert group.guesses, "连候选都不给，用户除了放弃没有别的动作可做"
    assert group.preselect is None, (
        "拿不准却预选了一项 —— 用户看到一个已选好的下拉框会默认它是对的，"
        "而选错了是静默的：文件进错目录，那一类的页面上空空如也。"
    )


def test_all_five_candidates_are_offered():
    """五个都要摆出来。⭐ 少摆一个，那个类就永远导不进去。"""
    group = _only(identify_groups(FIVE_WAY, source_name="素材.zip"))
    offered = {guess.spec_key for guess in group.guesses}
    missing = [key for key in WEAPON_SHAPED if key not in offered]
    assert not missing, f"这几类没出现在候选里：{missing}"


def test_every_guess_carries_evidence_a_human_can_read():
    """⭐ 拿不准时给用户的不该是一个干巴巴的下拉框。

    他是看着"这些文件都在 AK47/ 下、分成 2 个子目录"这种事实做判断的。
    """
    group = _only(identify_groups(FIVE_WAY, source_name="素材.zip"))
    for guess in group.guesses:
        assert guess.evidence, f"{guess.label} 这一项没有任何证据"
        assert any("文件" in line for line in guess.evidence), guess.evidence


# ------------------------------------------------- 包名这条信号

def test_the_pack_name_lifts_a_five_way_shape_to_likely():
    """⭐ 杠杆最大的一条：官网下载名就是「资源标题.zip」，而标题几乎总含品类词。
    这一条**不改站端就能吃掉官网包**。"""
    group = _only(identify_groups(FIVE_WAY, source_name="全枪枪声替换v2.zip"))
    assert group.confidence == LIKELY
    assert group.preselect is not None
    assert group.preselect.spec_key == "gun_sounds"


def test_the_longest_word_wins():
    """⚠ 「武器击杀音效」含「击杀音效」、「击杀语音」含「击杀」。

    按出现顺序匹配会把 `weapon_kill_sounds` 判成 `kill_sounds` ——
    两者的目标目录不同，判错了就是装进了错地方。
    """
    hits = match_category_words("武器击杀音效包")
    assert hits, "一个词都没命中"
    assert hits[0][0] == "weapon_kill_sounds", f"最长的词没排第一：{hits[:3]}"


def test_one_category_appears_at_most_once():
    """手验逮到的第一件事：同一类命中多个词会在备选里出现两次。

    ⭐ 命中越多说明**证据越强**，不是候选越多。
    """
    group = _only(identify_groups(
        ["清脆/1.mp3", "低沉/1.mp3"], source_name="CF爆头音效 击杀音效包.zip"))
    keys = [guess.spec_key for guess in group.guesses]
    assert len(keys) == len(set(keys)), f"有类别出现了不止一次：{keys}"


def test_separators_do_not_break_a_word_match():
    """`kill_sound` / `kill-sound` / `kill sound` 是同一个词，官网标题三种写法都有。"""
    for name in ("kill_sound pack", "kill-sound-pack", "KILL SOUND"):
        hits = match_category_words(name)
        assert any(key == "kill_sounds" for key, _ in hits), name


# ------------------------------------------------- 最硬的两条信号

def test_a_spec_directory_in_the_path_is_certain():
    """旧向导那条规则原样保留，它最硬。"""
    groups = identify_groups(
        ["audio/kill_sounds/清脆/1.mp3"], source_name="随便什么名字.zip")
    group = _only(groups)
    assert group.confidence == CERTAIN
    assert group.preselect.spec_key == "kill_sounds"
    assert not group.needs_user, "确定的东西不该再去打扰用户"


def test_a_manifest_that_names_the_category_wins_outright():
    paths = ["cs2customizer_pack.json", "随便/1.mp3"]
    manifest = read_manifest(paths, lambda _p: '{"category": "kill_voices"}')
    group = _only(identify_groups(paths, source_name="x.zip", manifest=manifest))
    assert group.confidence == CERTAIN
    assert group.preselect.spec_key == "kill_voices"


def test_a_manifest_naming_a_category_that_does_not_exist_is_ignored():
    """⛔ 清单是**外来数据**，不许它凭一句话把文件送进任意目录。

    ⭐ 失效方向朝"要问用户"那边倒，不朝"照它说的做"那边倒。
    """
    paths = ["cs2customizer_pack.json", "随便/1.mp3"]
    manifest = read_manifest(paths, lambda _p: '{"category": "../../系统目录"}')
    group = _only(identify_groups(paths, source_name="x.zip", manifest=manifest))
    assert group.confidence != CERTAIN


def test_a_broken_manifest_does_not_blow_up():
    assert read_manifest(["style.json"], lambda _p: "{ 不是 json") == {}
    assert read_manifest(["style.json"], lambda _p: "[1,2,3]") == {}

    def _boom(_path):
        raise OSError("读不了")

    assert read_manifest(["style.json"], _boom) == {}


# ------------------------------------------------- 击杀图标那条硬结构

def test_the_kill_icon_shape_is_recognised():
    """`1~5[hs].png/json` 是全产品**唯一**有硬结构的一类，认它不用问包名。"""
    group = _only(identify_groups(
        ["1.png", "1.json", "2.png", "2.json", "1hs.png", "1hs.json"],
        source_name="天使传说级武器.zip"))
    assert group.preselect is not None
    assert group.preselect.spec_key == "kill_icons"


def test_nothing_in_means_nothing_out():
    assert identify_groups([], source_name="空包.zip") == []
