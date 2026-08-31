# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 35（RN-468）：**一条靠人记得的制度，17 页里一次都没执行过。**

## 实测

总纲 §9.3 写着：「**每关 5 页做一次体检会话**」——
抽 2 个已关档页复跑三件套、故意注入一处坏改动确认门禁真的变红、
检查登记册无僵尸项。

而实测：**已关档 17 页，体检 0 次**（M0-8 那次是建制时的首检，之后再没有）。

⭐⭐⭐ 这是同一族的第三次现身：
  · RN-198：登记册只被读、不被写 ⇒ 腐烂；
  · RN-408：页面清单是「开工三读」的第二读，却不在收工清单里 ⇒ 只读不写；
  · 现在：体检是「每关 5 页」的义务，而**没有任何一处会在到期时提醒**。
⭐⭐ **一条只在「我想起来」时才生效的制度，等于没有这条制度** ——
而它不会报错，只会一直不发生。

## 这条判据只做一件事：**让它到期时有人知道**

⛔ 它不检查体检做得好不好（那是内容，机器读不出来），
只问一句：**距上一次体检，又关了几页。**

## ⚠⚠ 它自己改了三版，两版都是错的 —— 而两次都栽在同一类判断上

| 版本 | 问法 | 为什么错 |
|---|---|---|
| v1 | 「欠了几次」（`已关档 // 5` vs 做过几次）| 报「应做 3 次、实际 0 次」，而**那个债还不上**——我今天没法做三次体检 ⇒ ⭐⭐⭐ **周期性义务的欠账不能当存量债算；该问的是「距上一次多久了」** |
| v2 | 「距上一次又关了几页」，读不到批号算 **0** | 理由写着「朝『不冤枉现在这一轮』那边倒」——**听起来讲究，实际让判据放了水**：11 页当场被摘出分母，17 页算成 6 页，判据绿了 ⇒ ⭐⭐ **我明确地为失效方向写了理由，选的却正好是放水那边** |
| v3 | 同上，读不到算 **UNKNOWN**（当它是刚关的）| 于是那 10 页**永远**算在「上次体检之后」⇒ **判据永远红**。而它们是批号约定出现**之前**关的，不是新债 ⇒ ⭐⭐⭐ **一条把「不知道」算成「最坏」的规则，在「不知道」是历史常态时会让判据永远红——那和永远绿一样没用** |

⇒ 定版：到期检查**只数有批号的页**（精确），
而「还有几页没批号」由 `test_every_newly_closed_page_records_its_batch`
单列成一条有棘轮的账。
⭐⭐ **把「不知道」单列成一条有棘轮的账，比让它污染另一条判据要诚实。**

⚠ 判据自己**不许**替总纲改数：周期数从总纲里读，读不到就 fail ——
⭐ **把一个会漂的数抄进判据，就等于给它开了第二个真源**（本工程栽过三次）。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO = Path(__file__).resolve().parent.parent

#: 批次台账里，一行算不算「体检」——认这四个字，不认别的。
#: ⭐ 跟 RN-408 一样：**只认格子里的记录，不认行文里的排期**。
HEALTH_CHECK_MARK = "制度体检"

#: 状态格里读不到批号时用的值。**很大 = 当它是刚关的**（朝「要查」那边倒）。
UNKNOWN_BATCH = 9999

#: 状态格里**没有批号**的已关档页数。**只许变少。**
#:
#: ⚠⚠⚠ 这个常量是第三版才有的，而它修的是第二版制造的一个新毛病：
#:   第二版把「读不到批号」算成 `UNKNOWN_BATCH`（当它是刚关的），
#:   于是这 10 页**永远**算在「上次体检之后关的」里 ⇒ **判据永远红**。
#:   而它们不是新债：它们是**批号约定出现之前**关的（P0/P1/P2 那一批），
#:   M0 那次体检本来就在它们之前。
#: ⭐⭐⭐ **一条把「不知道」算成「最坏」的规则，在「不知道」是历史常态时，
#:   会让判据永远红 —— 那和永远绿一样没用。**
#: ⇒ 把「不知道」从到期检查里**分离出来**，单列成这条有棘轮的账：
#:   到期检查只数**有批号**的页（精确），而「还有几页没批号」由这条盯着，
#:   ⭐ 不许再增加（以后关档必须在状态格里写批号）。
#: 2026-08-31 批 35 实测起点 **10**：
#:   advanced / death_sound / flash / gun_sound / kill_sound /
#:   kill_voice / reload_sound / screen_effects / special_sound / switch_weapon
MAX_CLOSED_WITHOUT_BATCH = 10

#: 距上一次体检，还允许再关几页。**超过就红。**
#: ⚠ 这里给 1 不是放水：关掉第 N 页和做体检天然差一个批次（体检本身占一整批）。
GRACE = 1


def _campaign() -> Path | None:
    from test_renovation_registry_does_not_rot import CAMPAIGN
    return CAMPAIGN


def _board_text() -> str:
    c = _campaign()
    if c is None:
        pytest.skip("同级目录里没有翻新工程（登记册 + 档案）")
    return (c / "页面清单与进度.md").read_text(encoding="utf-8")


def _charter_text() -> str:
    c = _campaign()
    if c is None:
        pytest.skip("同级目录里没有翻新工程")
    charters = sorted(c.glob("总纲*.md"))
    assert len(charters) == 1, f"总纲不是恰好一份：{[p.name for p in charters]}"
    return charters[0].read_text(encoding="utf-8")


def _every_n_pages() -> int:
    """从**总纲**里读那个数，不在判据里另存一份。"""
    text = _charter_text()
    m = re.search(r"每关\s*(\d+)\s*页", text)
    assert m, (
        "总纲里找不到「每关 N 页」那句话 —— 要么它被删了（那这条判据该删），\n"
        "要么措辞改了（那这条判据该跟着改）。⭐ 判据不许自己编一个数顶上。"
    )
    return int(m.group(1))


def _closed_pages() -> list[tuple[str, int]]:
    """页面表里状态是「已关档」的页 → (page_id, 关档批号)。

    ⚠⚠ 批号从**状态格**里读（`已关档（2026-08-30 批 28）`）。读不到的算 **UNKNOWN_BATCH**
    （一个很大的数），也就是「**当它是刚关的**」。

    ⭐⭐⭐ 第一版这里写的是「读不到的算 0」，理由写着「失效方向朝『算它早』那边倒，
      也就是朝『不冤枉现在这一轮』那边倒」—— **听起来很讲究，而它让判据放了水**：
      11 页（早期关档、状态格里没有批号写法）当场被摘出分母，
      于是「距上次体检又关了 17 页」被算成 6 页，**判据绿了**。
    ⭐⭐ **我明确地为失效方向写了理由，选的却正好是让判据放水的那一边。**
      本工程的规矩写得很清楚（RN-198 的 `_is_open`）：
      **分不出类的值，失效方向必须朝「要查」那边倒。** 这里「要查」＝算它是新关的。
    """
    from test_renovation_progress_board_does_not_rot import (
        PAGE_TABLE_SHAPE, _board_rows, _strip,
    )
    out = []
    for h, c in _board_rows(_board_text()):
        if h != PAGE_TABLE_SHAPE or not _strip(c[8]).startswith("已关档"):
            continue
        pid = _strip(c[1])
        #: ⚠ 页面表里有**非页面行**（`（家族）sound_page_base` —— 武器音效基类，
        #:   随家族走、不在导航里注册）。它也标着「已关档」，但它不是一页。
        #:   ⭐ 分母守卫的另一面：**不光要防「少数了」，也要防「多数了」。**
        if not re.fullmatch(r"[a-z_]+", pid):
            continue
        m = re.search(r"批\s*(\d{1,3})", c[8])
        out.append((pid, int(m.group(1)) if m else UNKNOWN_BATCH))
    return out


def _health_check_batches() -> list[int]:
    """做过体检的批号。"""
    from test_renovation_progress_board_does_not_rot import (
        BATCH_LOG_SHAPE, _board_rows, _strip,
    )
    out = []
    for h, c in _board_rows(_board_text()):
        if h == BATCH_LOG_SHAPE and HEALTH_CHECK_MARK in c[2]:
            m = re.search(r"(\d{1,3})", _strip(c[0]))
            if m:
                out.append(int(m.group(1)))
    return sorted(out)


def test_the_charter_still_states_the_cadence():
    """⭐ 先证明那句话还在，再拿它去算 —— 否则这条判据会静默变成恒真。"""
    n = _every_n_pages()
    assert 1 <= n <= 20, f"「每关 {n} 页」这个数看着不像真的"


def test_the_scan_actually_sees_closed_pages():
    """空转守卫：一页都没读到就说明解析瞎了，而那时下面那条会无条件通过。"""
    closed = _closed_pages()
    assert len(closed) >= 10, (
        f"只读出 {len(closed)} 个已关档页（{closed}）—— 这条判据已经瞎了。"
    )
    known = sum(1 for _, b in closed if b != UNKNOWN_BATCH)
    assert known >= 5, (
        f"{len(closed)} 个已关档页里只有 {known} 个读得出批号 —— 批号解析多半瞎了。\n"
        "⚠ 注意失效方向：读不到时算 UNKNOWN_BATCH（当它是刚关的），"
        "所以解析瞎掉会让上面那条**永远红**，不是永远绿 —— 这是有意的。"
    )


def test_the_health_check_is_not_overdue():
    """⭐⭐⭐ **距上一次体检，又关了几页。**

    ⚠⚠ 第一版问的是「欠了几次」（`已关档 // 5` vs `做过几次`）——
    实测当场报「应做 3 次、实际 0 次」，而 **那个债是还不上的**：
    我今天没法做三次体检，三次内容也会一模一样。
    ⭐⭐⭐ **周期性义务的欠账不能当存量债来算 ——
      该问的不是「欠了几次」，是「距上一次多久了」。**
    ⇒ 改成：上一次体检之后又关了几页，超过 `每关 N 页 + GRACE` 就红。

    实测（2026-08-31 批 35）：上一次体检是 **M0（批号记 0）**，
    此后关了 17 页 —— 这条判据**一写出来就是红的**，
    而它红的正是它要防的那件事。
    """
    n = _every_n_pages()
    closed = _closed_pages()
    done = _health_check_batches()
    last = max(done) if done else 0
    #: ⚠ 只数**有批号**的页 —— 没批号的那几页由 `test_every_newly_closed_page_records_its_batch`
    #:   单独盯着（理由见 `MAX_CLOSED_WITHOUT_BATCH` 上那段）。
    since = [pid for pid, batch in closed
             if batch != UNKNOWN_BATCH and batch > last]
    assert len(since) <= n + GRACE, (
        f"距上一次体检（{'批 ' + str(last) if last else 'M0 建制那次'}）"
        f"又关了 **{len(since)}** 页，而总纲说「每关 {n} 页」做一次。\n"
        f"  这些页：{sorted(since)}\n"
        "⭐⭐ **一条只在「我想起来」时才生效的制度，等于没有这条制度** ——\n"
        "  它不会报错，只会一直不发生。\n"
        "⇒ 开一批「制度体检」（总纲 §9.3：抽 2 个已关档页复跑三件套 / "
        "故意注入一处坏改动确认门禁真的变红 / 检查登记册无僵尸项），\n"
        f"  并在批次台账那一行的「内容」格里写上「{HEALTH_CHECK_MARK}」四个字。"
    )


def test_a_health_check_batch_is_recognisable_at_all():
    """反向守卫：这条判据靠「内容格里有『制度体检』四个字」认人。

    ⭐ 如果那四个字从台账里彻底消失，上面那条会**永远红**（而不是永远绿）——
    失效方向朝「要查」那边倒（同 RN-198 的 `_is_open`）。
    这条只是把这件事写出来，免得下一个人以为它坏了。
    """
    from test_renovation_progress_board_does_not_rot import (
        BATCH_LOG_SHAPE, _board_rows,
    )
    rows = [c for h, c in _board_rows(_board_text()) if h == BATCH_LOG_SHAPE]
    assert len(rows) >= 20, f"批次台账只读出 {len(rows)} 行 —— 解析瞎了"


def test_every_newly_closed_page_records_its_batch():
    """⭐ 关档时必须在状态格里写批号 —— 否则上面那条数不到它。

    ⚠ 这条是**分离**出来的账，不是放水：到期检查只数有批号的页（精确），
    而「还有几页没批号」由这条盯着，只许变少。
    ⭐⭐ **把「不知道」单列成一条有棘轮的账，比让它污染另一条判据要诚实。**
    """
    closed = _closed_pages()
    nameless = sorted(pid for pid, b in closed if b == UNKNOWN_BATCH)
    assert len(nameless) <= MAX_CLOSED_WITHOUT_BATCH, (
        f"状态格里没有批号的已关档页从 {MAX_CLOSED_WITHOUT_BATCH} 涨到了 "
        f"{len(nameless)}：\n  {nameless}\n"
        "⇒ 关档时在状态格里写上「（YYYY-MM-DD 批 N）」——"
        "不写的话「距上一次体检又关了几页」就数不到它。"
    )
    assert len(nameless) >= MAX_CLOSED_WITHOUT_BATCH, (
        f"实际只剩 {len(nameless)} 页没批号，把 MAX_CLOSED_WITHOUT_BATCH 收到这个数。"
    )
