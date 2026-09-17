# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""枪声「套系」：把每把枪各自的风格目录按名字归成一套（2026-09-17 批 101）。

枪声的风格是 per-gun 目录，素材作者给每把枪起的名字天生不同（`ak47/离子AK`、
`negev/离子战神`、`awp/离子大狙`）；按名字取并集再套，「离子AK」只配得到 AK 类 ——
和逐把下拉没有区别。⇒ 按**名字开头**归成一套，各枪各配各的。判据：`tests/test_gun_sound_series.py`。

1. 名字完全相同的同属一套（击杀音那种全局风格的退化情形）；
2. 不同名字共同前缀 ≥ 2 个字（纯 ASCII ≥ 3 个字符）归一套；
3. ⚠ **同一把枪自己带的两个近名不合并**（`ssg08/PUBGAWM` 与 `PUBG消音AWM` 是可选项）；
4. 套系名 = 成员的最长公共前缀；一把枪多个候选时取与套系名相同的、否则最短的，候选都记下来；
5. 覆盖的枪多的排前面。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

MIN_PREFIX_CHARS = 2
MIN_ASCII_PREFIX_CHARS = 3


@dataclass(frozen=True)
class StyleSeries:
    #: 套系名（展示用，也是下拉里的 data）
    key: str
    #: 枪 → 这把枪在这个套系里要配的风格
    picks: dict[str, str] = field(default_factory=dict)
    #: 枪 → 全部候选（只有 >1 个候选的枪才会出现在这里）
    alternatives: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def gun_count(self) -> int:
        return len(self.picks)

    @property
    def label(self) -> str:
        """下拉里的那一项。名字不同的一套写「系列」：各枪各配各的这件事得在控件上就看得见
        （外审批 101 第七轮 2/3：那件事只在灰色长句里，没耐心的玩家不读）。"""
        word = " 系列" if len(set(self.picks.values())) > 1 else ""
        return f"{self.key}{word} · {self.gun_count} 把"


def _common_prefix(a: str, b: str) -> str:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return a[:n]


def prefix_links(a: str, b: str) -> bool:
    """两个不同名字能不能凭开头连成一套（规则 2）。"""
    if a == b:
        return True
    prefix = _common_prefix(a, b).strip()
    if len(prefix) < MIN_PREFIX_CHARS:
        return False
    if prefix.isascii() and len(prefix) < MIN_ASCII_PREFIX_CHARS:
        return False
    return True


def group_style_series(weapon_styles: Mapping[str, Sequence[str]]) -> list[StyleSeries]:
    """`{枪: [风格, ...]}` ⇒ 套系列表（规则见模块说明）。"""
    owners: dict[str, set[str]] = {}
    for gun, styles in weapon_styles.items():
        for style in styles or ():
            name = str(style or "").strip()
            if name:
                owners.setdefault(name, set()).add(gun)
    names = sorted(owners)
    if not names:
        return []

    parent = {name: name for name in names}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if not prefix_links(a, b):
                continue
            # 规则 3：同一把枪自己带的两个近名是可选项，不是一套。
            if owners[a] & owners[b]:
                continue
            parent[find(a)] = find(b)

    clusters: dict[str, list[str]] = {}
    for name in names:
        clusters.setdefault(find(name), []).append(name)

    result: list[StyleSeries] = []
    for members in clusters.values():
        members = sorted(members)
        key = members[0]
        for name in members[1:]:
            key = _common_prefix(key, name)
        key = key.strip() or members[0]
        picks: dict[str, str] = {}
        alternatives: dict[str, tuple[str, ...]] = {}
        per_gun: dict[str, list[str]] = {}
        for name in members:
            for gun in owners[name]:
                per_gun.setdefault(gun, []).append(name)
        for gun, candidates in per_gun.items():
            candidates = sorted(set(candidates), key=lambda s: (s != key, len(s), s))
            picks[gun] = candidates[0]
            if len(candidates) > 1:
                alternatives[gun] = tuple(candidates)
        result.append(StyleSeries(key=key, picks=picks, alternatives=alternatives))

    result.sort(key=lambda s: (-s.gun_count, s.key))
    return result


def find_series(series: Sequence[StyleSeries], key: str) -> StyleSeries | None:
    for item in series:
        if item.key == key:
            return item
    return None
