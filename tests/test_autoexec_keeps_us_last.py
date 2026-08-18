# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""`exec cs2customizer.cfg` 必须排在 autoexec 的最后，否则我们的 alias 会被覆盖。

**用户实战报回来的缺陷**（2026-08-18）：「准星跟随好像也没效果」。
根因不在本仓的任何一行代码里，在他机器上的 `autoexec.cfg`：

    exec cs2customizer.cfg          ← 我们
    exec FastShoot/setup
    exec othercfg.cfg   ← 另一个 cfg 工具，**最后执行**

`othercfg.cfg` 里有一模一样的
`alias +quickrepos_attack "+attack; exec othercfg_hud_runtime.cfg"`，
而全文 `cl_crosshair_recoil` 出现 **0 次**。
同名 alias **后 exec 的赢** ⇒ 我们那两行被原样覆盖，准星跟随静默死掉、零报错。

⚠ **更正（2026-08-19）**：第一版把原因写成「那个工具没有这个功能」——
**那是拿生成出来的 cfg 反推源码，属于循环论证。** 实际是那边**把准心快速回正关着**，
而关闭态输出的正是"直通 alias"（同名、但不带 recoil 那一段）。
⇒ 结论（后执行的覆盖先执行的）不变，但机制完全是另一回事。

⭐ 要害：**本项目与它的上游产品是同一套代码裁出来的，共用同一套 alias 名字空间。**
而 `core/crosshair_reset` 的模块说明写着 `PRIMARY_ALIAS` 改名等于把存量用户的
开火键变成死键 —— **这个碰撞不能靠改名躲过去**，只能靠
① 保证我们最后 exec；② 挪完还冲突就说出来。

同一类风险对任何第三方 cfg 工具都成立（那台机器上还有 FastShoot / f5e）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import crosshair_reset as cr  # noqa: E402

#: 用户机器上的原样内容（脱敏无关，这里就是当时那份的结构）。
REAL_AUTOEXEC = """exec FastShoot/setup
alias +pwaswitchknife slot3
alias -pwaswitchknife lastinv

exec cs2customizer.cfg
exec FastShoot/setup

exec othercfg.cfg
"""

#: 对手那三行（`cl_crosshair_recoil` 一次都没有）。
RIVAL_CFG = (
    'alias +quickrepos_attack "+attack; exec othercfg_hud_runtime.cfg"\n'
    'alias -quickrepos_attack "-attack; exec othercfg_hud_runtime.cfg"\n'
    'bind mouse1 +quickrepos_attack\n'
)

FILES = {"othercfg": RIVAL_CFG, "FastShoot/setup": "bind mouse4 +jump\n"}


def test_the_real_world_conflict_is_detected():
    hits = cr.find_alias_overriders(REAL_AUTOEXEC, FILES.get)
    assert hits == [{"cfg": "othercfg", "aliases": ["quickrepos_attack"]}], (
        f"没认出用户机器上那次覆盖：{hits}")


def test_moving_us_last_actually_resolves_it():
    fixed = cr.rewrite_autoexec_with_us_last(REAL_AUTOEXEC)
    assert cr.exec_order(fixed)[-1] == "cs2customizer", cr.exec_order(fixed)
    assert cr.find_alias_overriders(fixed, FILES.get) == []


def test_rewriting_is_idempotent():
    """已经在最后就一个字都不许动 —— 别每次启动都重写用户自己的文件。"""
    fixed = cr.rewrite_autoexec_with_us_last(REAL_AUTOEXEC)
    assert cr.rewrite_autoexec_with_us_last(fixed) == fixed


def test_rewriting_keeps_every_other_line():
    """只挪我们那一行，用户自己的 alias / 别的 exec 一行都不能丢。"""
    fixed = cr.rewrite_autoexec_with_us_last(REAL_AUTOEXEC)
    for line in REAL_AUTOEXEC.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("exec cs2customizer"):
            continue
        assert line in fixed, f"改写把这一行弄丢了：{line!r}"


def test_a_cfg_before_us_is_not_reported():
    """排在我们**前面**的同名 alias 无害（我们后执行，赢的是我们）。"""
    before = "exec othercfg.cfg\nexec cs2customizer.cfg\n"
    assert cr.find_alias_overriders(before, FILES.get) == []


def test_we_own_exactly_the_aliases_we_emit():
    """空转守卫：检测清单要覆盖我们真正会发的每一个 alias 名。

    ⚠ 只查 `quickrepos_attack` 是不够的 —— 老 HUD 路径那个 `fp_hud_mouse1`
    同样会被抢，而且上游产品**也**定义了它。
    """
    assert set(cr.OWNED_ALIASES) >= {
        cr.PRIMARY_ALIAS, cr.SECONDARY_ALIAS, *cr.LEGACY_ALIASES}
    rival_full = RIVAL_CFG + (
        'alias +fp_hud_mouse1 "+attack; exec othercfg_hud_runtime.cfg"\n')
    hits = cr.find_alias_overriders(
        "exec cs2customizer.cfg\nexec othercfg.cfg\n", {"othercfg": rival_full}.get)
    assert hits and set(hits[0]["aliases"]) == {"quickrepos_attack", "fp_hud_mouse1"}, hits


def test_no_autoexec_entry_means_nothing_to_check():
    """我们压根不在 autoexec 里时不许乱报（那是另一条毛病，不归这里管）。"""
    assert cr.find_alias_overriders("exec othercfg.cfg\n", FILES.get) == []
    text = "exec othercfg.cfg\n"
    assert cr.rewrite_autoexec_with_us_last(text) == text


# --------------------------------------------------------------- RN-099


def test_we_only_reorder_once_so_two_products_do_not_fight():
    """⭐ RN-099：**最多只挪一次**，否则两个产品会永久互相抢最后一位。

    2026-08-19 实测到的事故：本项目和它的上游产品**跑的是同一份代码**，
    于是两边都会"把自己挪到最后"——用户机器上的 autoexec 每启动一次就被翻一次，
    前一天刚修好的准星跟随又被覆盖回去。

    ⚠ 两个产品的印记字符串**必须不同**（这里是 `CS2C-`，上游是它自己的）：
    共用同一个字符串的话，"我挪过了"就退化成"有人挪过了"，
    先启动的那个会把后启动的永久挡在门外，谁也别想再挪一次。

    ⭐ 这是 RN-095 只修了一半的证据：**alias 名字空间共用**我认了，
    但**"抢最后一位"这个策略也被共用了**我没认。
    ⇒ 往共享资源里写"我要占据唯一位置"的逻辑，先问一句：
      **如果对面跑的是同一份代码，会发生什么？**
    """
    first = cr.rewrite_autoexec_with_us_last("exec cs2customizer.cfg\nexec other.cfg\n")
    assert cr.exec_order(first)[-1] == "cs2customizer", cr.exec_order(first)
    assert cr.MOVED_MARK in first, "挪完必须留下印记，否则没法知道自己挪过"

    # 对面也挪了一次 —— 现在我们又不是最后一位了
    contested = first.rstrip("\n") + "\nexec other.cfg\n"
    assert cr.exec_order(contested)[-1] == "other"

    again = cr.rewrite_autoexec_with_us_last(contested)
    assert again == contested, (
        "我们又挪了第二次 —— 对面也会再挪，两边永久互相抢最后一位，"
        "每启动一次就改一次用户的文件（RN-099）。")


def test_the_mark_is_what_stops_the_second_move():
    """空转守卫：印记没写进去的话，上面那条判据会因为别的原因通过。"""
    text = "exec cs2customizer.cfg\nexec other.cfg\n"
    moved = cr.rewrite_autoexec_with_us_last(text)
    stripped = moved.replace(cr.MOVED_MARK, "NOPE")
    contested = stripped.rstrip("\n") + "\nexec other.cfg\n"
    assert cr.rewrite_autoexec_with_us_last(contested) != contested, (
        "去掉印记之后居然还是不挪 —— 说明拦住第二次挪动的不是印记，"
        "上面那条判据在验别的东西。")


def test_being_last_is_enough_to_leave_it_alone():
    """已经在最后、且**没有印记**时也必须一个字不动。

    ⚠ 这条是回退验证逼出来的：加了 RN-099 的印记之后，
    「已经在最后就别动」那条守卫被拆掉时 `test_rewriting_is_idempotent`
    **照样绿**——因为印记也能拦住第二次挪动。
    两个机制都能让同一条判据通过 ⇒ 那条判据管不住任何一个。
    ⇒ 一条判据只对应一个机制，别让它同时被两件事满足。
    """
    text = "exec other.cfg\nexec cs2customizer.cfg\n"
    assert cr.MOVED_MARK not in text, "这条判据的前提是没有印记"
    assert cr.rewrite_autoexec_with_us_last(text) == text, (
        "已经在最后却还是改了文件 —— 每次启动都重写用户的 autoexec")
