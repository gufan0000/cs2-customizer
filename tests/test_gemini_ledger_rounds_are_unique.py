# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""外审台账的轮次编号，在**同一条流**里不许重复。

## 查到最后不是"马虎"，是命名空间被两拨人共用

台账是多个会话共同追加的文件，而里面**并行着两套编号**：

    桌面版（翻新工程）  第 13~17 轮   ← `crosshair` / `kill_icon` / `hud_color` / `advanced`
    网站（官网+社区站） 第 13~17 轮   ← 全站视觉外审 / 用户中心 / 社区首屏 …

两套各自从 1 数起，于是 13~17 每个数字都出现两次 —— **历史上就重着**。
2026-08-20 我以为自己"撞了号"，改了两次编号，其实是把自己的轮次一次次
塞进网站那一串，越改越乱。

⭐ **"两个人撞号"和"一个命名空间被两拨人共用"是两个不同的问题，
而前者的修法（下次小心点）对后者完全无效。**

⇒ 从 2026-08-20 起：**流别写进标题**（`## 桌面 第 N 轮 …`），
网站那一串沿用不带前缀的旧写法。历史上那 5 对重号按既成事实豁免。

## 为什么值得有这么一条判据

这件事我**刚把教训写进台账，下一轮就又犯了**。
⭐ **一条没有判据看着的规矩，等于没有这条规矩** —— 本仓第 N 次证实。
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

LEDGER = Path(__file__).resolve().parent.parent / "docs" / "quality" / "gemini_ledger.md"

#: `## 第 N 轮 …` / `## 桌面 第 N 轮 …` 都要认。前缀就是"流"，没写就是网站那一串。
_ROUND = re.compile(r"^##\s*(\S*?)\s*第\s*(\d+)\s*轮", re.M)

_UNTAGGED = "（未标注·网站串）"

#: 历史既成事实：两套编号并存时期留下的重号。**只准减不准加。**
#: 加新条目之前先问一句：是不是又有第三条流在共用这个命名空间？
GRANDFATHERED = {(_UNTAGGED, n): "桌面版与网站两套编号并行时期（2026-08-19/20）"
                 for n in (13, 14, 15, 16, 17)}


def _rounds() -> list[tuple[str, int]]:
    text = LEDGER.read_text(encoding="utf-8")
    return [(m.group(1) or _UNTAGGED, int(m.group(2))) for m in _ROUND.finditer(text)]


def test_no_two_rounds_share_a_number_within_a_stream():
    if not LEDGER.exists():
        pytest.skip("这个仓没有外审台账")
    counts = Counter(_rounds())
    dupes = {k: c for k, c in counts.items() if c > 1 and k not in GRANDFATHERED}
    assert not dupes, (
        f"台账里这些轮次在同一条流里出现了不止一次：{dupes}\n"
        "台账是多个会话共同追加的文件。\n"
        "⇒ 写之前先 `grep '^## .*第.*轮'` 看清**自己这条流**已有的最大号，再 +1；\n"
        "   桌面版一律写成 `## 桌面 第 N 轮 …`。")


def test_the_grandfathered_list_does_not_rot():
    """豁免名单只准减不准加 —— 里面的重号必须**真的还在**。

    名单最舒服的腐烂方式是"那条早就不重了却没人删"：留着的条目会替下一个人
    把门开着，而门后面正是这条判据要拦的东西。
    """
    if not LEDGER.exists():
        pytest.skip("这个仓没有外审台账")
    counts = Counter(_rounds())
    stale = [k for k in GRANDFATHERED if counts.get(k, 0) <= 1]
    assert not stale, f"这些豁免已经用不上了，删掉：{stale}"


def test_the_scan_actually_finds_rounds():
    """反面守卫：标题格式一变，上面那条就会静默变成「零个轮次、当然不重复」。"""
    if not LEDGER.exists():
        pytest.skip("这个仓没有外审台账")
    rounds = _rounds()
    assert len(rounds) >= 15, (
        f"只扫到 {len(rounds)} 个轮次标题 —— 多半是标题格式变了，"
        "上面那条判据已经什么都管不住了。")
    assert any(stream == "桌面" for stream, _ in rounds), (
        "一条带「桌面」前缀的轮次都没有 —— 分流写法没落地，"
        "那这条判据就只是在看网站那一串。")
