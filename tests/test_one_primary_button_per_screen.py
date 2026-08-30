# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-188：「一屏只许一颗主按钮」这条规则，**全站到底成立到什么程度**。

## 这条判据是量出来的，不是想出来的

RN-188 立案时把顺序写死了：

> ⚠ **不能直接上全站铁规**：本仓有刻意让同一个动作在卡里和底栏各出现一次的设计
> （RN-078 的 `viewmodel`「保存到CFG」，两处同名是判过的），一条全站硬判据会当场
> 诬告它。⇒ 要先**量分布**再定规则。
> ⭐ 顺序不能反 —— **先立规则后量分布，等于让规则去决定证据**。

于是先写了 `scripts/primary_button_census.py` 报数。**28/28 页实测（2026-08-26）**：

| 情形 | 页数 | 是哪几页 |
|---|---|---|
| 恰好一颗 | 21 | —— |
| **同屏 >1 颗** | **4** | `viewmodel` / `voice_output` / `account` / `about` |
| 一颗都没有 | 2 | `fun_afterlife` / `audio_task_panel`（2026-08-30 批 28 起 +`magnifier`，见 `KNOWN_NO_PRIMARY`）|
| **数不可复现** | 1 | `audio_health`（后台线程，见 `TIMING_DEPENDENT_PAGES`）|

⚠ 最后那一行是**两支工装打架打出来的**：普查脚本扫到 0 颗、本文件扫到 1 颗。
⭐⭐ **两次测量同一件事得到两个数，那个差值就是被测对象里我还没看见的一个自由度。**

⭐⭐ **而那 4 页，无一例外都是「同一个动作在同一屏出现两次」** ——
不是「两个不同的主动作在竞争」：

    viewmodel     保存到CFG ×2
    voice_output  添加槽位 ×2
    account       登录账号 ×2
    about         查看更新日志 ×2（另有一颗「去 GitHub 点 Star」）

⇒ RN-188 当初担心的那个「刻意设计的例外」**不是例外，是唯一的成因**。
所以规则可以写得很干净：**同屏两颗主按钮而文案相同 = 缺陷**，例外表是空的。

## ⭐⭐ 而这条规则指出了一件更难看的事：RN-078 的裁定制造了 RN-404

RN-078（2026-08-18 已结）的原话是：

> `viewmodel` 卡内与底栏两颗保存按钮**统一为**「保存到CFG」
> （原来一个叫「保存设置到CFG」，两个名字会让人以为是两件事）

它解决了「以为是两件事」，**却造出了「两颗一模一样的紫按钮」**（RN-404，2026-08-23
外审 2/2 报「初次操作难以判断两者差异与点击时机」）。
⭐ 修一条造出下一条 —— 而且这次隔了 5 天、跨了两个条目才被看见。
⇒ **真正该问的从来不是「这两颗叫什么」，是「这一屏的主操作到底归谁」。**

## 这条棘轮怎么用

`KNOWN_DUPLICATE_PRIMARIES` 是**声明式存量债**，三个方向都红：
**新增一页**、**某页变多**、**某页已经不该在册了**。
⚠ 第三向最容易漏 —— 只判「变没变坏」的棘轮在缺陷修好后会永远停在旧数上，
从「守着一条线」退化成「记录一个历史」（同 RN-196 的 `KNOWN_COMPACT_DEBT`）。

## 分母（⭐ 说清楚，别假装全覆盖）

- 只量**产品默认状态**（普通模式 + 全新配置）。同一页在别的状态下可能多长一颗 ——
  **RN-186 就是空库那一态**，那条已单独有判据。
- ⚠ 全新配置对音效家族**恰好就是空库态**，对别的页不是。**这是已知缺口。**
- ⛔ 不量专家模式（RN-134）。
"""
from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractButton

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

PRIMARY_OBJECT_NAME = "primaryButton"

#: 2026-08-26 实测存量债：页 → (文案, 颗数)。⚠ **数等于实测值**，不是上限。
#: 每一条都必须指得出它归哪个登记册条目管 —— 一条没有主人的债会永远躺着。
KNOWN_DUPLICATE_PRIMARIES = {
    "viewmodel":    ("保存到CFG", 2),        # RN-404
    "voice_output": ("添加槽位", 2),         # RN-416
    "account":      ("登录账号", 2),         # RN-416
    "about":        ("查看更新日志", 3),     # RN-416（另有一颗「去 GitHub 点 Star」）
}

#: 一颗主按钮都没有的页。**这也是信息**：那几页没有明确的主动作。
#: ⚠ 不判它对错 —— 「该不该有主按钮」是产品裁定，不是排版规则。
#: 放在这里是为了**让它变化时有人知道**。
#:   · `fun_afterlife`：源码里一次 `configure_primary` 都没有；
#:   · `audio_task_panel`：没有任务时 `configure_primary("", None, visible=False)`
#:     ——**状态相关**，而全新配置恰好是空任务态。
#:   · `magnifier`（2026-08-30 批 28 加入，RN-277）：底栏主按钮位原来放的是
#:     「全选武器 / 全不选武器」——54 把武器默认全勾，于是**每个新用户看到的都是
#:     那颗写着「全不选武器」的紫按钮**，点一下 54 个复选框全清空、当场落盘、
#:     没有确认也没有撤销。而它作用的那 54 个复选框在**第二~三屏**。
#:     ⭐⭐ 外审行为题 12 发：「点它是靠近目标还是反方向」**12/12「反方向」**。
#:     这一页的改动全是即时保存（偏移的 X/Y 有它自己那张卡上的「应用」），
#:     **没有该由底栏承担的动作** ⇒ 主按钮位空着（同 crosshair 批 10）。
KNOWN_NO_PRIMARY = {"fun_afterlife", "audio_task_panel", "magnifier"}

#: ⚠⚠ **数不可复现的页，不许进上面两张表。**
#:
#: `audio_health` 的主按钮由 `_sync_action_bar` 配置，而那个方法要等
#: `_run_health_check()` 起的**后台线程**（`threading.Thread(name="AudioHealthScan")`）
#: 把报告送回来才跑 ⇒ **扫到几颗取决于线程什么时候回来**。
#: 实测：`scripts/primary_button_census.py` 扫到 0 颗，本文件扫到 1 颗 ——
#: 同一件事、两个数，差别只在两边 `processEvents()` 抽了几次。
#:
#: ⭐⭐ **两次测量同一件事得到两个数，那个差值就是被测对象里我还没看见的一个自由度。**
#: ⭐ 一个取决于后台线程时序的数进了棘轮，就是一条 flaky 判据 ——
#:   而 flaky 判据比没有判据更坏（红过一次「不是我的错」，人就开始无视它，RN-021）。
#: ⇒ 它要另配一条**不看时序**的判据（断言两个分支都 `configure_primary`），
#:   在本文件里只声明「它不参与计数」。
TIMING_DEPENDENT_PAGES = {"audio_health"}


@pytest.fixture(scope="module")
def sitewide_primaries(qapp, tmp_path_factory):
    """建一次窗、走一遍 28 页，收每页可见的主按钮文案。

    ⚠ 建 28 个页面很贵，所以 module 级只做一次。
    ⚠ `isVisible()` 在离屏窗口上恒为 False ⇒ 用 `isVisibleTo(page)`
      （它回答的是「假设这一页显示出来，它露不露脸」，正是要问的）。
    """
    os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
    os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

    import _audit_neutralize as neutral
    import _ui_mode
    from config import config

    neutral.apply(config)
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.show()
        qapp.processEvents()
        win.setMinimumSize(1280, 800)
        win.resize(1280, 800)
        qapp.processEvents()

        # ⚠ 顺序要害：**先按页中和，再看还剩谁不安全**。
        # 反过来写（先用 `unsafe_pages()` 过滤、再中和）会把 6 个**本来中和之后
        # 就能纳入**的页整片切掉 —— 实测 28 页变 22 页，而判据只会说"扫描器瞎了"，
        # 不会说"是你把它们排掉了"。⭐ 同 RN-030：**一条「排除」被写成「替换」**。
        page_ids = list(win._page_names.keys())
        neutral.apply(config, page_ids)
        page_ids = [p for p in page_ids if p not in neutral.unsafe_pages()]
        found: dict[str, list[str]] = {}
        for page_id in page_ids:
            # ⚠⚠ **必须走 `_ui_mode.goto`，不许自己 `show_page`。**
            # 普通模式下 6 个专家页没有导航入口，不带 `force=True` 的 `show_page`
            # 会**静默 return** —— 实测这条判据第一版因此只走到 22/28 页，
            # 而它给出的解释是「扫描器瞎了」，压根指不到真正的原因。
            # ⭐ 那条教训逐字写在 `_ui_mode.goto` 的注释里，而我在 census 脚本里
            #   用对了、换到判据里又自己抄了一遍 ——
            #   **一个教训只修在它被发现的那条通路上，等于只修了一份副本。**
            _ui_mode.goto(win, page_id)
            for _ in range(3):
                qapp.processEvents()
            page = win.pages.get(page_id)
            if page is None:
                continue
            found[page_id] = [
                b.text().strip()
                for b in page.findChildren(QAbstractButton)
                if b.objectName() == PRIMARY_OBJECT_NAME and b.isVisibleTo(page)
            ]
        yield found
    finally:
        win.close()
        qapp.processEvents()


def test_the_scan_actually_sees_the_pages(sitewide_primaries):
    """⭐ 空转守卫：先证明它看得见东西，再让它去断言「没问题」（RN-169）。

    一次扫出 0 页、或者一颗按钮都没找到的扫描，会让下面每条断言无条件通过。
    """
    assert len(sitewide_primaries) >= 25, (
        f"只走到 {len(sitewide_primaries)} 页 —— 产品里注册着 28 页，"
        "扫描器瞎了（页面没建出来？中和表把太多页排掉了？）")
    total = sum(len(v) for v in sitewide_primaries.values())
    assert total >= 20, (
        f"全站只找到 {total} 颗 `{PRIMARY_OBJECT_NAME}` —— "
        "objectName 是不是改名了？那样这条判据会永远绿。")


def test_no_page_grows_a_new_pair_of_identical_primary_buttons(sitewide_primaries):
    """⭐⭐ 主刀：**同屏两颗主按钮而文案相同**，用户没有任何办法区分它们。

    实测 4 页在册（见模块头）。这条只盯**新增**与**变多**。
    """
    offenders = []
    for page_id, texts in sorted(sitewide_primaries.items()):
        if len(texts) <= 1 or page_id in TIMING_DEPENDENT_PAGES:
            continue
        declared = KNOWN_DUPLICATE_PRIMARIES.get(page_id)
        if declared is None:
            offenders.append(f"{page_id}: 新增 {len(texts)} 颗 {texts}")
        elif len(texts) > declared[1]:
            offenders.append(
                f"{page_id}: 从在册的 {declared[1]} 颗变成 {len(texts)} 颗 {texts}")
    assert not offenders, (
        "这些页的主按钮数量变坏了：\n  " + "\n  ".join(offenders) +
        "\n⭐ 两颗紫的等于零颗——「主」是相对的（RN-139）。"
        "\n如果确实是一次获批的改版，改 KNOWN_DUPLICATE_PRIMARIES 并写明归哪条 RN 管。")


def test_the_debt_table_does_not_become_a_museum(sitewide_primaries):
    """⚠ **第三向**：某页已经修好了，就必须从债表里删掉。

    ⭐ 只判「变没变坏」的棘轮，在缺陷修好之后会永远停在旧数上 ——
    从「守着一条线」退化成「记录一个历史」，而且**没有任何东西会说它退化了**。
    """
    # ⚠⚠ **这张表记的是完整产品的实测值，而派生的功能子集里每一格都可能不同。**
    # 实测（开源验收门逮到）：子集里 `account` **整页不存在**，
    # `about` 的按钮被机械替换改名成「查看发布记录」且少了一颗。
    # ⭐ 「照闭源版文件集写死的断言，在子集仓里不是"更严"，是"错"」——
    #   这已经是一周内第三次同形（批 7 `KNOWN_UNPARSEABLE`、批 8 `assert excluded_files`）。
    #
    # ⇒ 判别式沿用批 11 那条：**缺的页必须连实现文件都不在**，
    #   实现文件还在却没扫到 = 真问题（一整页被摘出导航）。
    # ⇒ 只要缺了任何一页，这份表描述的就不是**这个** build，
    #   skip 的理由是**样本不可比**（RN-140），不是"环境看起来不正常"。
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    missing = [p for p in sorted(KNOWN_DUPLICATE_PRIMARIES) if p not in sitewide_primaries]
    for page_id in missing:
        impl = repo / "pages" / f"{page_id}_page.py"
        assert not impl.exists(), (
            f"债表里的 `{page_id}` 这一轮没被扫到，而 `{impl.relative_to(repo)}` **还在** —— "
            "那不是发行版缺项，是一整页被摘出了导航。")
    if missing:
        pytest.skip(
            f"这份债表记的是完整产品的实测值，而本 checkout 里缺 {missing}"
            "（实现文件也一并不在）⇒ 数不可比，逐格核对没有意义。"
            "⚠ 上面那条「实现文件还在不在」的断言照常跑。")

    stale = []
    for page_id, (text, count) in sorted(KNOWN_DUPLICATE_PRIMARIES.items()):
        texts = sitewide_primaries.get(page_id)
        if texts is None:
            stale.append(f"{page_id}: 在债表里，但这一轮根本没扫到这一页")
        elif len(texts) < count:
            stale.append(f"{page_id}: 债表写 {count} 颗，实测只剩 {len(texts)} 颗 {texts}")
        elif text not in texts:
            stale.append(f"{page_id}: 债表说重复的是「{text}」，实测是 {texts}")
    assert not stale, (
        "存量债表已经和现实对不上了（多半是修好了没回来删）：\n  " +
        "\n  ".join(stale))


def test_every_duplicate_pair_really_is_the_same_action(sitewide_primaries):
    """⭐⭐ 钉住那条**量出来的结论**：全站每一处 >1 颗，都是同一个动作出现两次。

    这不是文风要求。它是规则能写得这么干净的**唯一理由** ——
    如果哪天出现「两个**不同**的主动作在同一屏竞争」，那是另一类问题
    （信息架构，不是重复），得重新裁一次，不能顺手塞进这张债表。
    """
    mixed = []
    for page_id, texts in sorted(sitewide_primaries.items()):
        if len(texts) <= 1:
            continue
        if len(set(texts)) == len(texts):
            mixed.append(f"{page_id}: {texts} —— 几颗**互不相同**的主按钮")
    assert not mixed, (
        "出现了本判据没见过的形态（同屏多颗、且彼此不同）：\n  " + "\n  ".join(mixed) +
        "\n⇒ 这不是「重复」，是「主操作竞争」。别塞进 KNOWN_DUPLICATE_PRIMARIES，"
        "另立条目走裁定。")


def test_the_timing_dependent_page_always_ends_up_with_exactly_one():
    """⭐ `audio_health` 的数不可复现，所以**换一条不看时序的问法**：

    源码里 `_sync_action_bar` 的**每一条分支**都必须 `configure_primary(...)`。
    这样「它最终有几颗」就与后台线程什么时候回来无关了。
    ⭐ **量不稳的东西，就别去量它的值，去量决定那个值的规则。**
    """
    import ast
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "pages" / "audio_health_page.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_sync_action_bar"), None)
    assert fn is not None, "audio_health_page 里找不到 _sync_action_bar —— 这条判据瞎了"

    def _has_primary(arm) -> bool:
        return any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "configure_primary"
            for n in ast.walk(ast.Module(body=list(arm), type_ignores=[]))
        )

    # ⚠ 只挑**真的在分主按钮**的那个 if/else。
    # 第一版拿 `fn.body` 里所有 `ast.If` 挨个查，当场撞上函数开头那句
    # `if not hasattr(self, "action_bar"): return` —— **guard clause 也是一个 If**，
    # 而它当然没有 configure_primary。⭐ 判据的分母要按**它在找什么**来选，
    # 不是按"语法上长得像什么"来选。
    branches = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.If) and n.orelse
        and (_has_primary(n.body) or _has_primary(n.orelse))
    ]
    assert branches, (
        "`_sync_action_bar` 里已经找不到「分主按钮」的那个 if/else 了 —— "
        "要么改写法了、要么主按钮不再分状态。两种都要重新裁一次，别让这条判据空转。")
    for br in branches:
        for arm, name in ((br.body, "if"), (br.orelse, "else")):
            assert _has_primary(arm), (
                f"`_sync_action_bar` 的 {name} 分支没有 configure_primary —— "
                "那一支走完这一页就没有主按钮了，而这件事**只在某个时序下才看得见**。")


def test_pages_without_any_primary_button_are_declared(sitewide_primaries):
    """一颗主按钮都没有的页也要在册 —— **那也是信息**，不是默认值。

    ⚠ 这条不判对错（「该不该有主动作」是产品裁定），它只保证**变化时有人知道**。
    """
    empty = {p for p, t in sitewide_primaries.items() if not t} - TIMING_DEPENDENT_PAGES
    assert empty == KNOWN_NO_PRIMARY, (
        f"「一颗主按钮都没有」的页变了：\n"
        f"  新增：{sorted(empty - KNOWN_NO_PRIMARY)}\n"
        f"  不再是：{sorted(KNOWN_NO_PRIMARY - empty)}\n"
        "⇒ 有页面丢了主动作，或者补上了。两种都该有人看一眼。")
