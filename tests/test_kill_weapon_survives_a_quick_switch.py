# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-096：开完枪顺手切副武器，这次击杀仍要算在**开火的那把枪**头上。

**用户实战报回来的**（2026-08-18，死斗）：「击杀音效和图标有时候什么都不播」。
我第一轮看日志得出的结论是「8 次失败全是 `weapon_fiveseven`，那把枪配置里没启用」
—— **那是表象**。用户当场纠正：他全程是拿 AWP 打死人的，五七只是副武器。

⭐ **这条教训值得单写**：日志里那个 `weapon=` 字段是**软件自己解析出来的结论**，
不是观测事实。我拿它当证据做了统计、算了百分比、还画了表，
整套推理都建立在"这 8 次是五七打的"这个**软件自己的断言**之上。
⇒ **用被审对象自己的输出去证明被审对象没问题，是循环论证。**

## 机制（离线复现三个场景确认）

`_resolve_kill_weapon` 的优先级原本是：
本帧弹药下降推断出的开火武器 → **此刻举在手里的武器** → （仅当没有 weapons 快照时）刚开过火的武器。

AWP 打死人之后切副武器是狙击手的标准操作（切枪跑得快），而 `round_kills`
那一包**晚一拍才到**。等它到的时候：

- 弹药变化已经落在**上一包**里 ⇒ 本帧推断不出开火武器；
- 玩家手里举的已经是五七 ⇒ 就地取材，记成五七。

关键在于：**本帧一发子弹都没少，说明这两包之间谁都没开火**，
那这次击杀只可能来自「刚刚开过火的那把枪」（或近战/投掷物）。

⚠ 近战必须让位：刀和电击枪没有弹夹，永远推断不出开火，
一律走这条会把刀杀记成上一把枪 —— RN-016 那条「近战配了没反应」立刻复活。
"""
from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

AWP = "weapon_awp"
FIVE = "weapon_fiveseven"
KNIFE = "weapon_knife"


def _snapshot(active, awp_ammo, five_ammo):
    return {
        "weapon_0": {"name": KNIFE, "state": "active" if active == KNIFE else "holstered"},
        "weapon_1": {"name": FIVE, "ammo_clip": five_ammo,
                     "state": "active" if active == FIVE else "holstered"},
        "weapon_2": {"name": AWP, "ammo_clip": awp_ammo,
                     "state": "active" if active == AWP else "holstered"},
    }


@pytest.fixture()
def handler():
    import gsi_handler_kills as mod
    h = mod.GSIHandlerKills()
    h.last_non_knife_weapon = AWP
    return h


def _resolve(h, prev, cur, active, recent_fire=None, fired_ago=0.0):
    h.previous_weapon_snapshot = h._extract_weapon_snapshot({"weapons": prev})
    current = h._extract_weapon_snapshot({"weapons": cur})
    h.frame_has_weapon_snapshot = True
    h.frame_inferred_fire_weapon = h._infer_fired_weapon(current)
    h.frame_active_weapon = active
    now = time.time()
    h.last_confirmed_fire_weapon = recent_fire or ""
    h.last_confirmed_fire_weapon_time = now - fired_ago
    return h._resolve_kill_weapon(now)


def test_a_kill_after_quick_switching_still_belongs_to_the_gun_that_fired(handler):
    """⭐ 用户那 8 次：AWP 开火 → 切五七 → 击杀包才到，本帧无弹药变化。"""
    got = _resolve(handler,
                   prev=_snapshot(FIVE, 4, 5), cur=_snapshot(FIVE, 4, 5),
                   active=FIVE, recent_fire=AWP, fired_ago=0.3)
    assert got == AWP, (
        f"击杀被记在了「此刻举着的枪」({got}) 上，而不是刚开过火的 AWP。\n"
        "本帧一发子弹都没少 ⇒ 这两包之间没人开火 ⇒ 这次击杀来自上一次开火。")


def test_a_real_kill_with_the_sidearm_is_still_the_sidearm(handler):
    """反面：真用五七打死人（它自己的弹药掉了），不许被改判成 AWP。"""
    got = _resolve(handler,
                   prev=_snapshot(FIVE, 4, 5), cur=_snapshot(FIVE, 4, 4),
                   active=FIVE, recent_fire=AWP, fired_ago=0.3)
    assert got == FIVE, f"五七自己开了火却被记成 {got}"


def test_a_knife_kill_is_still_a_knife_kill(handler):
    """⚠ 近战没有弹夹，永远推断不出开火 —— 一刀切会让 RN-016 复活。"""
    got = _resolve(handler,
                   prev=_snapshot(KNIFE, 4, 5), cur=_snapshot(KNIFE, 4, 5),
                   active=KNIFE, recent_fire=AWP, fired_ago=0.3)
    assert got == KNIFE, (
        f"刀杀被记成了 {got} —— 用户在击杀音效页给近战配的风格又不生效了（RN-016）")


def test_an_old_shot_does_not_hijack_a_later_kill(handler):
    """开火过去很久了就别再抢：超出时限回到「举着的那把」。"""
    got = _resolve(handler,
                   prev=_snapshot(FIVE, 4, 5), cur=_snapshot(FIVE, 4, 5),
                   active=FIVE, recent_fire=AWP, fired_ago=5.0)
    assert got == FIVE, f"5 秒前开的那一枪还在抢击杀归属（得到 {got}）"


def test_the_ordinary_case_is_untouched(handler):
    """举着 AWP 开火打死人 —— 这条路一个字都不该变。"""
    got = _resolve(handler,
                   prev=_snapshot(AWP, 5, 5), cur=_snapshot(AWP, 4, 5), active=AWP)
    assert got == AWP


def test_switch_within_the_same_packet_still_credits_the_shooter(handler):
    """切枪发生在同一包内（弹药变化还看得见）—— 老逻辑本来就对，别改坏。"""
    got = _resolve(handler,
                   prev=_snapshot(AWP, 5, 5), cur=_snapshot(FIVE, 4, 5), active=FIVE)
    assert got == AWP
