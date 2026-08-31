# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 36 · `utility`：这一屏说的话，三处都只说了一半。

改前外审四问（整页图 ×6），**②③④ 三题各 6/6 满票**：

| 问 | 改前 |
|---|---|
| ①「想让点位在游戏里显示，先点哪个」| 6/6「先点总开关」（**对的** —— 就地总开关在第一屏，这一页这点没问题）|
| ②「有没有两颗按钮做同一件事」| **6/6「有」**，逐字答「打开道具文件夹」和「刷新道具列表」|
| ③「有没有点不动的按钮，画面说清为什么了吗」| **6/6「有，而且没说」** |
| ④「三颗『未检测到 / 未载入』，你知道接下来做什么吗」| **6/6「不知道」** |

## ① 底栏是 100% 的副本（RN-452 那 5 组）

`_sync_action_bar` 按页签重配底栏，而它放上去的**五个位置，五个都是卡内
某颗按钮的第二份**：

| 底栏位置 | 卡内那一颗 |
|---|---|
| 次位「打开道具文件夹」| `open_folder_btn` |
| 主位「预览显示」| `preview_btn` |
| 主位「打开当前阵营文件夹」| `open_team_folder_btn` |
| 主位「打开当前地图文件夹」| `open_map_folder_btn` |
| 主位「刷新道具列表」| `refresh_btn` |

⭐⭐⭐ 这是批 31 那条结论（**`PageActionBar` 不是「这一页的主操作在这儿」，
是「把卡内那颗再放一遍」的地方**）在**一页上的极端形态**：
全站 36 处里，这一页占 **5 处**，是最多的一页。

⇒ 按批 31 的裁定规则②（都看得见时，留**离它作用的对象最近**的那一颗）：
卡内那几颗就在它们的语境里（「快速操作」卡 / 显示设置卡），底栏那五个全撤。
⚠ 底栏本身**留着** —— 那句共用回执（「总开关关着…」＋ 当前标签摘要）有它自己的活。

## ② 置灰了，而屏幕上没有一处说为什么（RN-302）

实测：`open_map_folder_btn` / `open_team_folder_btn` **`enabled=False`**，
而两颗的 **tooltip 都是空串**，页面上也没有别的地方解释。
同屏胶囊写着「地图 · 未检测到」「阵营 · 未检测到」——**那是线索，但没连起来**。

⭐ 批 23（RN-150「禁用了但看不出来」）管的是**看不看得出它禁用了**；
这一条问的是**知不知道为什么** —— 两件事，两条判据。

## ③ 三颗「没有」，而没有一处说下一步（RN-300）

「地图 · 未检测到」「阵营 · 未检测到」「道具 · 未载入」。
外审 **6/6 答「不知道」**。
⭐ 同 RN-105 那一族（空状态无引导），但这一页的空状态**不是列表空**，
是**三个状态位都是「没有」** —— 而它们各自的成因不同
（前两个要进对局，第三个要放素材再刷新）。
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
PAGE = REPO / "pages" / "utility_page.py"


def _src() -> str:
    return PAGE.read_text(encoding="utf-8")


def _page(monkeypatch):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    import pages.utility_page as mod
    return app, mod.UtilityPage()


# ------------------------------------------------ ① 底栏不许再放副本

def _bar_actions(src: str) -> list[tuple[str, str]]:
    """底栏配过的 (文案, 绑定方法名)，只算 `visible=True` 的。"""
    out = []
    for n in ast.walk(ast.parse(src)):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        if n.func.attr not in ("configure_primary", "configure_secondary"):
            continue
        if not n.args or not isinstance(n.args[0], ast.Constant):
            continue
        label = n.args[0].value
        if not label:                      # 空文案 = 这个位置空着
            continue
        target = n.args[1].attr if len(n.args) > 1 and isinstance(
            n.args[1], ast.Attribute) else "?"
        out.append((label, target))
    return out


def _card_bound_methods(src: str) -> set[str]:
    """卡内按钮 `clicked.connect(self._foo)` 绑过的方法名。"""
    out = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == "connect" \
                and isinstance(n.func.value, ast.Attribute) \
                and n.func.value.attr == "clicked" and n.args \
                and isinstance(n.args[0], ast.Attribute):
            out.add(n.args[0].attr)
    return out


def test_the_scan_sees_the_card_buttons():
    """⭐ 先证明它看得见东西（RN-169）。"""
    bound = _card_bound_methods(_src())
    assert len(bound) >= 5, f"只认出 {len(bound)} 颗卡内按钮：{sorted(bound)}"


def test_the_action_bar_is_not_a_second_copy_of_the_cards():
    """⭐⭐⭐ RN-452：这一页的底栏原来**五个位置全是副本**（全站最多）。

    批 31 量过全站 36 处「同一个绑定既配在底栏、又接在卡内按钮上」，
    而**没有一处是底栏独有的动作**。这一页占 5 处。
    ⇒ 按那一批的裁定规则②：都看得见时，留**离它作用的对象最近**的那一颗。
    """
    src = _src()
    bar = _bar_actions(src)
    card = _card_bound_methods(src)
    dup = [(lab, tgt) for lab, tgt in bar if tgt in card]
    assert not dup, (
        "底栏这几个位置放的是卡内按钮的第二份：\n"
        + "\n".join(f"  「{lab}」→ {tgt}（卡内也有一颗接着它）" for lab, tgt in dup)
        + "\n⇒ 撤掉底栏那一份（`configure_*(\"\", None, visible=False)`），"
        "卡内那颗留着 —— 它离它作用的对象更近。"
    )


def test_removing_the_copies_did_not_remove_the_actions(monkeypatch):
    """⭐⭐ 反面守卫：撤的是**副本**，不是动作本身（批 31 那条）。

    **一条只判「坏东西没了」的判据，挡不住「好东西也一起没了」。**
    """
    src = _src()
    card = _card_bound_methods(src)
    for name in ("_open_utility_folder", "_refresh_utilities", "_preview_display",
                 "_open_current_map_folder", "_open_current_team_folder"):
        assert name in card, (
            f"`{name}` 在卡内已经没有按钮接它了 —— 撤副本撤过头，"
            "这件事从此没人能做了。"
        )


def test_the_action_bar_still_carries_its_receipt():
    """⭐ 底栏**留着** —— 那句共用回执（总开关关着 / 当前标签摘要）有它自己的活。

    ⚠ 撤的是「放在底栏的那份按钮副本」，不是底栏本身
    （批 34 在 `fun_afterlife` 上做过相反的判断：那一页**没有**页级主操作，
    所以连底栏都不加。⭐ **同一条规则在两页给出相反答案，正是它有内容的证据。**）
    """
    src = _src()
    assert "set_message" in src, "底栏那句回执没了 —— 撤过头了"
    assert "PageActionBar" in src, "底栏整个没了"


# ------------------------------------------ ② 置灰要说为什么

DISABLED_BUTTONS = ("open_map_folder_btn", "open_team_folder_btn")


def test_a_disabled_button_says_why_it_is_disabled(monkeypatch):
    """⭐ 外审 **6/6**：「有置灰按钮，而画面上没有说为什么」。

    ⚠ 这条跟批 23（RN-150「禁用了但看不出来」）**不是一件事**：
    那一条问「看不看得出它禁用了」，这一条问「**知不知道为什么**」。
    """
    app, page = _page(monkeypatch)
    try:
        app.processEvents()
        naked = []
        for name in DISABLED_BUTTONS:
            btn = getattr(page, name, None)
            assert btn is not None, f"`{name}` 不见了 —— 这条判据已经瞎了"
            if btn.isEnabled():
                continue                        # 进了对局就该能点，不在分母里
            if not (btn.toolTip() or "").strip():
                naked.append(f"{name}（{btn.text()}）")
        assert not naked, (
            "这几颗按钮点不动，而鼠标停上去也不说为什么：\n"
            + "\n".join("  " + n for n in naked)
            + "\n⇒ 它们要的是**进对局之后**才有的地图/阵营，把这句话说出来。"
        )
    finally:
        page.deleteLater()
        app.processEvents()


# ------------------------------------------ ③ 三颗「没有」要说下一步

def test_the_empty_state_explains_itself_on_the_screen_it_happens_on(monkeypatch):
    """⭐⭐⭐ RN-300：解释和它要解释的东西，隔着一整页。

    ⚠⚠ **立案陈述要改**：旧账写「显示『未检测到/未载入』却**无任何操作指引**」——
    实测**有五处**（「等待进入对局」「进入对局后会自动识别…」「自动刷新」
    「系统会自动根据当前阵营加载…」＋帮助面板），
    而它们**一处都不在困惑发生的那一屏上**：默认页签是「基础设置」，
    那五处全在「道具管理」页签和折叠的帮助面板里。
    ⭐⭐⭐ 而三颗「未检测到 / 未载入」胶囊**就在第一屏**。
    外审 **6/6 答「不知道」**。

    ⇒ 修法不是「补一句指引」（已经有五句），是**把它放到胶囊旁边**
      （批 32 那条：**解释性文字要放在困惑发生的位置**）。

    ## ⚠⚠⚠ 这条判据的第一版，我为一个**没验证过的成因**编了一整套东西

    第一版用 `isVisibleTo(page)` 收集全页标签、当场**绿了**。
    我当时的解释是「`isVisibleTo` 对未选中页签里的控件也返回 True」，
    并据此写了一个 `_really_visible` helper、一条守卫、外加一条
    「判据看得见的和用户看得见的不是一回事」的教训。

    **那个成因是假的。** 实测：独立构造下 51 个标签里 `isVisibleTo` 只有 19 个为真，
    另一个页签里那句「等待进入对局」**正确地返回 False**。
    第一版之所以绿，是因为**页头那句话里恰好有「进对局」三个字**
    （「设好热键，进对局按一下就出」）——跟页签毫无关系。

    ⭐⭐⭐ **我为一个从没验证过的成因，写了一个 helper、一条判据和一条「教训」。**
    ⭐ 而拆穿它只花了一条 `print` —— **在给一个现象编解释之前，先去量它。**

    ⇒ 定版：不发明可见性口径，**把断言的范围收到「状态卡」**上 ——
      那才是这条主张本来要说的话：解释得**挨着**那三颗胶囊。

    ## ⚠⚠ 第二个坑：这条判据一度**只在这台机器上**是对的

    定版之后 `_gsi_cfg_ready()` 进来了，指路句分成两支：装好了说「进对局」，
    没装好说「去设 CS2 目录」。而判据只断言了 `"进对局" in near` ——
    它在我这台装了 CS2 的机器上绿，**在 CI 上（没有游戏目录）必然红**。
    ⭐⭐ 一条**取决于本机环境**的判据是 flaky 判据，而 flaky 比没有更坏
      （红过一次「不是我的错」，人就开始无视它，RN-021）。
    ⇒ 改成**把两支都跑一遍**：`_gsi_cfg_ready` 直接打桩成 True / False。
    """
    from PySide6.QtWidgets import QLabel

    app, page = _page(monkeypatch)
    try:
        app.processEvents()
        texts = [(w.text() or "").strip() for w in page.findChildren(QLabel)
                 if w.isVisibleTo(page)]
        blob = " ".join(texts)
        assert "未检测到" in blob, "第一屏上连「未检测到」都没有了 —— 判据已经瞎了"
        card = getattr(page, "status_card", None) or page

        def _near() -> str:
            return " ".join((w.text() or "") for w in card.findChildren(QLabel)
                            if w.isVisibleTo(page))

        # 两支各跑一遍 —— 分支挑的是「有没有 GSI 配置」，不是「在谁的机器上跑」。
        for ready, must_say, why in (
            (True, ("进对局", "进入对局"), "装好了 GSI：该说这两样要进对局才有"),
            (False, ("CS2",), "没装 GSI：该说先去设 CS2 目录，而不是让人白进对局"),
        ):
            page._gsi_cfg_ready = lambda _ready=ready: _ready
            page._gsi_cfg_ready_cache = ready
            page._sync_status_strip()
            app.processEvents()
            near = _near()
            assert any(k in near for k in must_say), (
                f"GSI 配置 ready={ready} 时，状态卡里没说清下一步（{why}）。\n"
                "「地图 · 未检测到」「阵营 · 未检测到」就在第一屏，"
                "而**同一张卡里**得有一处解释它。\n"
                "⚠ 页面别处确实写了五句（「等待进入对局」等），但它们在**另一个页签**里 ——\n"
                "  ⭐ **解释性文字要放在困惑发生的位置**，而困惑发生在这三颗胶囊旁边。\n"
                f"  这张卡当前的文案：{near[:200]!r}"
            )
            assert "刷新" in near, (
                "「道具 · 未载入」旁边没有一处说该怎么让它变成「有」（放素材再刷新）。"
            )
    finally:
        page.deleteLater()
        app.processEvents()
