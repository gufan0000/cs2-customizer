# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-599：judgment 那一档的问题，必须答得出它模板要的那一行。

⭐⭐⭐ 这条的要害不是「问错了题」，是**问错题之后的失败形态**：
批 79 第一版问的是「你会**先点哪一颗按钮**」——一个选择题。
模板却**强制第一行**是「判断」加 会/不会/说不准。于是它没有报错，
而是跑出了一个**和限流一模一样**的失败：一发卡满 300 秒超时、
一发返回码 0 但空返回，白烧 10 分钟。当时周限 79%，
**差一点被我判成「该换号了」** —— 按 CLAUDE.md 手动跑一发绝对路径的图
（14.6 秒、答对）才排除掉限流。

⇒ ⭐⭐ **空返回 / 超时 / 限流三者长得一模一样**，而其中只有一种是外部原因。
一个能在发出去之前就拒收的检查，省下的不只是 10 分钟，
是**一次把内部缺陷误判成外部限额的机会**。

判定必须是**结构性**的（立案原话：「判『像不像是非题』要给得出反例，
别做成一条靠关键词猜的规则」）：中文是非问只有两种形状 ——
正反式（会不会 / 有没有 / 知道不知道）与句末「吗」。
⚠ 只看疑问词会误伤真的是非题：「你**知不知道**下一步该点**哪里**？」
带疑问词，却是是非题 —— ⭐ 判据是「有没有是非结构」，不是「有没有疑问词」。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from _denominator import must_scan

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gemini_review.py"

#: ⛔ 这些必须收。头两条是**真用过的**题面（批 69 / 批 77），不是设想的。
MUST_ACCEPT = (
    "看完这一屏，你会不会觉得还有一步没做完？",
    "看完这一屏，你会不会以为这个功能已经在生效了？",
    "这一屏上有没有任何一处在说「还有一件必须做的事没做」？",
    "你知不知道下一步该点哪里？",          # ⭐ 带疑问词的**是非题**
    "这两张卡片是不是一样高？",
    "你能不能一眼看出这个开关现在是开着还是关着？",
    "改完之后，这句话还会让人觉得要再点一次保存吗？",
)

#: ⛔ 这些必须拒。第一条是批 79 那次**原样的**题面。
MUST_REJECT = (
    "你会先点哪一颗按钮？",
    "这一屏有什么问题？",
    "玩家第一眼会看哪里？",
    "请描述这一屏的信息层级。",
    "哪一处文案最容易让人误解？",
)


def _load():
    if not SCRIPT.exists():
        pytest.skip(f"外审驱动不在这个克隆里：{SCRIPT}")
    spec = importlib.util.spec_from_file_location("_rn599_review", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_questions_we_actually_used_are_all_accepted():
    """⭐ 反向的代价要说清楚：**误拒一个好题面，等于把一轮 A/B 挡在门外**。

    所以这一半的样本全部取自**真跑过并产出过票数**的题面。
    """
    mod = _load()
    must_scan(MUST_ACCEPT, "该收的题面样本", least=5)
    wrong = [q for q in MUST_ACCEPT if not mod.looks_like_a_yes_no_question(q)]
    assert not wrong, "这些真用过的判断题被误拒了：" + "；".join(wrong)


def test_the_shapes_that_burned_ten_minutes_are_rejected():
    """⛔ 这些答不出「判断|会/不会/说不准」，发出去只会换来一个和限流同形的失败。"""
    mod = _load()
    must_scan(MUST_REJECT, "该拒的题面样本", least=4)
    wrong = [q for q in MUST_REJECT if mod.looks_like_a_yes_no_question(q)]
    assert not wrong, "这些答不出模板那一行的问题被放过了：" + "；".join(wrong)


def test_an_empty_question_is_not_quietly_treated_as_a_yes_no_one():
    """⭐ 分母守卫：空串、纯标点这类输入不许「碰巧通过」。

    ⚠ 一个对空输入返回 True 的检查，会在 `--question ""` 时**静默放行**，
    而那正是这条判据要挡的那个失败（发出去、超时、看起来像限流）。
    """
    mod = _load()
    for junk in ("", "   ", "？", "。。。"):
        assert not mod.looks_like_a_yes_no_question(junk), f"空输入被当成是非题：{junk!r}"
