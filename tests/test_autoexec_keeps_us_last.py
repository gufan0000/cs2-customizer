# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""`exec cs2customizer.cfg` 必须排在 autoexec 的最后，否则我们的 alias 会被覆盖。

**用户实战报回来的缺陷**（2026-08-18）：「准星跟随好像也没效果」。
根因不在本仓的任何一行代码里，在他机器上的 `autoexec.cfg`：

    exec cs2customizer.cfg          ← 我们
    exec FastShoot/setup
    exec fanpai.cfg          ← 另一个 cfg 工具，**最后执行**

`cs2customizer.cfg` 里有一模一样的
`alias +quickrepos_attack "+attack; exec fanpai_hud_runtime.cfg"`，
而全文 `cl_crosshair_recoil` 出现 **0 次**（开源版是功能子集，没这个功能）。
同名 alias **后 exec 的赢** ⇒ 我们那两行被原样覆盖，准星跟随静默死掉、零报错。

⭐ 要害：**开源版是从本仓裁出来的，两个产品共用同一套 alias 名字空间。**
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

exec fanpai.cfg
"""

#: 开源版那三行（`cl_crosshair_recoil` 一次都没有）。
RIVAL_CFG = (
    'alias +quickrepos_attack "+attack; exec fanpai_hud_runtime.cfg"\n'
    'alias -quickrepos_attack "-attack; exec fanpai_hud_runtime.cfg"\n'
    'bind mouse1 +quickrepos_attack\n'
)

FILES = {"fanpai": RIVAL_CFG, "FastShoot/setup": "bind mouse4 +jump\n"}


def test_the_real_world_conflict_is_detected():
    hits = cr.find_alias_overriders(REAL_AUTOEXEC, FILES.get)
    assert hits == [{"cfg": "fanpai", "aliases": ["quickrepos_attack"]}], (
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
    before = "exec cs2customizer.cfg\nexec cs2customizer.cfg\n"
    assert cr.find_alias_overriders(before, FILES.get) == []


def test_we_own_exactly_the_aliases_we_emit():
    """空转守卫：检测清单要覆盖我们真正会发的每一个 alias 名。

    ⚠ 只查 `quickrepos_attack` 是不够的 —— 老 HUD 路径那个 `fp_hud_mouse1`
    同样会被抢，而且开源版**也**定义了它。
    """
    assert set(cr.OWNED_ALIASES) >= {
        cr.PRIMARY_ALIAS, cr.SECONDARY_ALIAS, *cr.LEGACY_ALIASES}
    rival_full = RIVAL_CFG + (
        'alias +fp_hud_mouse1 "+attack; exec fanpai_hud_runtime.cfg"\n')
    hits = cr.find_alias_overriders(
        "exec cs2customizer.cfg\nexec fanpai.cfg\n", {"fanpai": rival_full}.get)
    assert hits and set(hits[0]["aliases"]) == {"quickrepos_attack", "fp_hud_mouse1"}, hits


def test_no_autoexec_entry_means_nothing_to_check():
    """我们压根不在 autoexec 里时不许乱报（那是另一条毛病，不归这里管）。"""
    assert cr.find_alias_overriders("exec cs2customizer.cfg\n", FILES.get) == []
    text = "exec cs2customizer.cfg\n"
    assert cr.rewrite_autoexec_with_us_last(text) == text
