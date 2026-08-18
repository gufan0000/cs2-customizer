# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-042：文案不许承诺一个配置里根本不存在的维度。

**这条也是补账的**。RN-042 在 M2 已经"已结"（把 `kill_sound` 副标题里
「可以按武器类别和**连杀数**分开配」改掉），但当时只改了文案、没留判据。
2026-08-18 关档自查交叉核对回退验证时发现，它是两条
「改了产品代码却没有任何东西钉住」之一。

**原缺陷**：副标题说可以按连杀数分开配，而 `config.weapon_kill_sounds`
只有 `weapon → style` **一个**维度，全仓不存在任何按连杀数分配的配置键；
连杀档位是**风格目录内部**按 1..5 命名的文件，用户选不了。
外审两发独立点出「提示可按连杀数分配，但界面上完全找不到入口」。

这条判据是**两头咬**的：

1. 负面 —— 家族里任何一页的引导语都不许再写「按连杀数分开/单独配」；
2. 正面 —— `weapon_kill_sounds` 的值必须仍是**标量**（一个维度）。
   哪天真做出了「按连杀数分开配」，这一半会红，提醒把文案改回来。
   ⚠ 只写负面那一半就成了"永远不许这么说"，那是错的：
   **文案错不错取决于代码做不做得到**，判据必须同时量住那一头。

⚠ **分母不是 `kill_sound` 一页，也不是音效家族**：这句话谁都可能抄，
所以直接复用 RN-077 那个**全站副标题抽取器**（28 页 · 卡片副标题 + 页头 + 变体工厂）。
第一版我自己写了个只认 `PAGE_LEAD` 的抽取器，当场只捞到 4 页 ——
`death_sound` / `gun_sound` / `special_sound` 三页是直接给 `PageHeader(description=...)` 的，
根本没有 `PAGE_LEAD`。⇒ **别造第二个抽取器，去用那个已经有空转守卫的。**
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_no_layout_self_talk_sitewide import (  # noqa: E402
    _copy_sources, _subtitle_literals,
)

REPO = Path(__file__).resolve().parent.parent

#: 「按<某个维度>分开配」这个句式。只拦"承诺可配置"，不拦陈述事实
#: （「一个风格里自带 1~5 连杀的不同音效」是事实，必须放行）。
PROMISE_RE = re.compile(r"按[^，。；]{0,8}连杀[^，。；]{0,8}(分开|分别|单独|各自)[^，。；]{0,4}(配|设|选)")

#: 配置值里出现这些键，才说明"按连杀数分开配"真的做出来了。
STREAK_KEY_RE = re.compile(r"^(level|streak|kill[_-]?count|\d)$", re.I)


def _all_subtitles() -> list[tuple[str, int, str]]:
    out = []
    for path in _copy_sources():
        for lineno, text, _branch in _subtitle_literals(path):
            out.append((path.name, lineno, text))
    return out


def test_the_extractor_actually_sees_the_subtitles():
    """空转守卫：抽取器一旦失效，下面那条就变成永远绿。

    ⚠ 60 这个数不是我拍的，是 RN-077 那条判据已经在用的同一个下限
    （改口径两边会一起红）。
    """
    subs = _all_subtitles()
    assert len(subs) >= 60, (
        f"全站只读到 {len(subs)} 条副标题（RN-077 判据的下限是 60）。\n"
        "抽取器很可能已经失效，下面的判据会永远绿。")


def test_no_page_promises_a_per_streak_configuration():
    offenders = [(n, ln, t) for n, ln, t in _all_subtitles() if PROMISE_RE.search(t)]
    assert not offenders, (
        "文案承诺「按连杀数分开配」，而配置里没有这个维度（RN-042）：\n"
        + "\n".join(f"  {n}:{ln}  {t}" for n, ln, t in offenders)
        + "\n连杀档位是风格目录内部按 1..5 命名的文件，用户选不了。"
        "\n要么改文案，要么真做出这个维度（做出来了，本文件另一条判据会提醒你改回文案）。")


def test_the_kill_sound_config_still_has_no_per_streak_dimension():
    """正面那一半：配置里确实没有连杀这个维度 ⇒ 上面那条禁令仍然成立。

    ⚠ 这条我第一版写错了：我按登记册 RN-042 那句「`weapon_kill_sounds` 只有
    weapon → style 一个维度」去断言"值必须是标量"，跑起来当场红 ——
    真实结构是 `{'enabled': bool, 'style': str}`。**结论没错（确实没有连杀维度），
    但我给判据的机制是错的**，正是「现象真、机制错」那一类。
    改成量真正要害的东西：值里有没有一个按连杀档位分叉的键。
    """
    from config import config

    mapping = getattr(config, "weapon_kill_sounds", None)
    assert isinstance(mapping, dict) and mapping, (
        "拿不到 `config.weapon_kill_sounds`（判据的前提没了，别让它假绿）")

    offenders = {}
    for weapon, value in mapping.items():
        if isinstance(value, (list, tuple)):
            offenders[weapon] = value
        elif isinstance(value, dict):
            streaky = [k for k in value if STREAK_KEY_RE.match(str(k))]
            if streaky:
                offenders[weapon] = value
    assert not offenders, (
        "`weapon_kill_sounds` 里出现了按连杀档位分叉的键 —— "
        "看起来「按连杀数分开配」已经做出来了：\n"
        + "\n".join(f"  {k} = {v!r}" for k, v in list(offenders.items())[:5])
        + "\n如果确实做出来了，请把 RN-042 那句文案改回可以说，并更新本判据。")
