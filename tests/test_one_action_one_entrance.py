# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-404 / RN-416 / RN-452：**同一个动作，一页只许有一个入口。**

## 这一批最该记的一件事：分母错了，而错的方向是「少数了 9 倍」

RN-188（批 13）量过一次「同屏几颗主按钮」，结论是 **4 页**：
`viewmodel` / `voice_output` / `account` / `about`，各两颗同名的紫按钮。
那份数没错 —— **它数的东西错了**。它的分母是 `objectName == "primaryButton"`，
而「同一个动作出现两次」这件事**跟颜色毫无关系**。

本批（批 31）换了两个分母重量：

| 怎么量 | 数 |
|---|---|
| RN-188：同屏 >1 颗**紫**按钮 | 4 页 / 4 处 |
| 运行时：同屏两颗**同文案**按钮，一颗在底栏一颗在卡内 | **11 页 / 17 组** |
| AST：`configure_primary/secondary` 绑的方法**又**被某颗卡内按钮 `clicked.connect` | **14 页 / 36 处** |

⭐⭐⭐ **`PageActionBar` 在这个产品里不是「这一页的主操作在这儿」，
它是「把卡内某颗按钮再放一遍」的地方** —— 36 处里没有一处是底栏独有的动作。

⭐ 而外审 8 发在 `voice_output` 的**窗口图**上报的那一对，一颗紫的都不是：
两颗「使用说明」（驱动卡内一颗 + 底栏次位一颗）。
**只数紫色的那条判据，结构上不可能看见它。**

## 留哪一颗：两条实测，不是文风

批 31 的裁定（外审行为题 ③「你会点哪一个让它生效」4 页各 4 发支持）：

1. **默认状态下看不见的那一颗，不能当唯一入口。**
   实测（滚动位置 0、完整档）：`about` 卡内那颗露出 **0%**、
   `voice_output` 卡内那颗露出 **0%**（而且它还被总开关降权成了灰色，
   实测填充 `(110,112,129)`，同屏底栏那颗是 `(130,64,243)` —— ⭐ 同一个动作、
   同一个 objectName、同一屏，一颗灰一颗紫）。
2. **两颗都看得见时，留离「它作用的对象」最近的那一颗**；对象不在任何一张卡上
   （开浏览器、弹对话框）就留底栏 —— 底栏常驻可达，是默认归属。

对上四页：

| 页 | 动作 | 撤哪一颗 | 依据 |
|---|---|---|---|
| viewmodel | 保存到CFG | 卡内 | 都可见；对象=整页设置 ⇒ 底栏。外审 ③ **4/4 指底栏** |
| voice_output | 添加槽位 | 卡内 | 卡内那颗 0% 露出 + 被降权成灰 |
| voice_output | 使用说明 | 底栏次位 | 都可见；对象=VB-Cable 驱动，就在那张卡上 |
| account | 登录账号 | 底栏主位 | 都可见；对象=登录表单。外审 ③ **4/4 指卡内** |
| account | 打开官网 | 卡内 | 都可见；对象=外部网站，不在任何卡上 ⇒ 底栏 |
| about | 查看更新日志 | 卡内 | 卡内那颗 0% 露出 |
| about | 打开官网 | 卡内 | 同上 |

## ⛔ 本批只动这四页 —— 剩下 10 页只记账不动刀

RN-188 立案时写死过顺序：**先量分布 → 再定规则 → 再逐个定性**，
并且写了一句 ⭐「先立规则后量分布，等于让规则去决定证据」。
分布这一步本批做完了（上表），但那 10 页**从来没走过「逐个定性」**：
`flash` 底栏那 6 处是**分状态出现**的（同一时刻只露一颗），
`utility` / `audio_*` 几页连档案都还没开。
⇒ 拿一条刚定下的规则去改 10 页没定过性的版面，就是那句话说的错法。
它们记在 `BAR_CARD_DUPLICATE_ACTIONS` 里，由下面第三向判据看着**只许减不许增**。
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

REPO = Path(__file__).resolve().parent.parent

#: 批 31 动完刀之后的**存量债**：页 → 那一页还剩几个「底栏与卡内绑同一个方法」的动作。
#: ⚠ 值是**方法名的元组**，不是个数 —— 个数会在改名时静默对上。
#:
#: ⭐ 这四页（about/account/viewmodel/voice_output）本批清零，所以**不在表里**；
#:   它们改由下面 `test_the_four_renovated_pages_have_exactly_one_entrance` 钉死。
BAR_CARD_DUPLICATE_ACTIONS = {
    "advanced": ("_browse_for_csgo_dir",),
    "audio_health": ("_export_report", "_run_conservative_fix", "_run_health_check"),
    "audio_import_wizard": ("_open_resource_dir", "_open_source_dir",
                            "_run_import", "_scan_source"),
    "audio_replay": ("_export_json", "_refresh_events", "_replay_selected"),
    "audio_task_panel": ("_reload_history",),
    "config_snapshot": ("_create_snapshot", "_reload", "_restore_selected"),
    "flash": ("_open_flash_audio_folder", "_open_flash_images_folder",
              "_preview_flash", "_refresh_audio_styles", "_refresh_styles",
              "_reset_settings"),
    "kill_icon": ("_on_primary_clicked", "_open_workshop"),
    # ⭐ `preset_center` 2026-09-01 批 38 清零 ⇒ 移到下面 `RENOVATED_PAGES`。
    #   撤的是**底栏**那颗（RN-281：它在默认状态下写回 57 个键、0 个会变），
    #   留的是工作台卡内那颗 —— 批 31 规则②「留离它作用的对象最近的那一颗」，
    #   而它作用的对象正是同一张卡里「导入预设包」读进来的那一份。
    # ⭐ `utility` 曾是这张表里**最长的一条（5 处，全站最多的一页）**，
    #   2026-08-31 批 36 清零 ⇒ 移到下面 `RENOVATED_PAGES` 由那几条钉死。
}

#: 已动刀清零的页。清零之后**一处都不许再长回来**。
#: ⭐ 2026-08-31 批 36 加入 `utility` —— 它是原债表里最长的一条（5 处），
#:   而全站 36 处里这一页独占 5 处，是最多的一页。
RENOVATED_PAGES = ("about", "account", "preset_center", "utility",
                   "viewmodel", "voice_output")

#: 本批撤掉的那七个入口，撤的是**副本**，不是动作本身。
#: ⭐ 这张表是**反面守卫**：撤重复最容易犯的错是把两颗一起删掉，
#:   而那种错**不会让上面任何一条判据变红**（重复确实没有了）。
SURVIVING_ENTRANCES = {
    ("viewmodel", "_save_viewmodel_cfg"): "bar",
    ("voice_output", "_add_slot"): "bar",
    ("voice_output", "_show_instructions"): "card",
    ("voice_output", "_export_config"): "card",
    ("account", "_emit_login"): "card",
    # ⚠ account 的「打开官网」撤的是**底栏**那颗，不是卡内那颗 —— 跟 about 相反。
    # ⭐ 理由不是版式偏好，是**状态**：底栏只有在「未登录」这一态才有它
    #   （已登录时底栏次位是「刷新状态」），而卡内两张卡各有一颗、两态都在。
    #   **一个只在某个状态下才出现在底栏的动作，是底栏在补位，不是底栏拥有它。**
    ("account", "_open_website"): "card",
    ("about", "_show_changelog"): "bar",
    ("about", "_open_website"): "bar",
    # ⚠ `utility` 五处**全部留卡内那颗**（批 31 裁定规则②：留离它作用的对象最近的）。
    # ⭐ 底栏本身**留着** —— 那句共用回执（总开关状态 + 当前标签摘要）是它自己的活，
    #   不是副本。同一条规则在 `fun_afterlife`（批 34）上给出的是相反答案
    #   （那一页没有页级主操作，连底栏都不加）—— **而那正是它有内容的证据**。
    ("utility", "_open_utility_folder"): "card",
    ("utility", "_preview_display"): "card",
    ("utility", "_open_current_map_folder"): "card",
    ("utility", "_open_current_team_folder"): "card",
    ("utility", "_refresh_utilities"): "card",
    # ⚠ `preset_center` 留的是**卡内**那颗，和 `utility` 同向、和 `about` 相反。
    # ⭐ 理由不是版式偏好，是**对象**：这个动作作用于「刚读进来的那份预设包」，
    #   而读它进来的那颗按钮就在同一张卡的同一格里（批 31 规则②）。
    ("preset_center", "_save_changes"): "card",
}


def _attr_name(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _scan(page_id: str):
    """返回 (底栏绑的方法集, 卡内 clicked.connect 绑的方法集)。

    ⚠ 只认**直接写出方法引用**的那一形（`self._foo`）。lambda / partial
    一律不认 —— 认不出的**不算重复**，失效方向朝「不报」那边倒。
    ⭐ 这跟 RN-198 那条「失效方向必须朝要查那边倒」相反，是故意的：
      这条判据的后果是「去删一颗按钮」，误报的代价比漏报大。
    """
    src = REPO / "pages" / f"{page_id}_page.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    bar, card = set(), set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
            continue
        if n.func.attr in ("configure_primary", "configure_secondary") and len(n.args) >= 2:
            if isinstance(n.args[1], (ast.Attribute, ast.Name)):
                bar.add(_attr_name(n.args[1]).replace("self.", ""))
        if (n.func.attr == "connect" and isinstance(n.func.value, ast.Attribute)
                and n.func.value.attr == "clicked" and len(n.args) == 1
                and isinstance(n.args[0], (ast.Attribute, ast.Name))):
            card.add(_attr_name(n.args[0]).replace("self.", ""))
    return bar, card


def _all_page_ids():
    return sorted(p.stem[:-5] for p in (REPO / "pages").glob("*_page.py"))


def _present(page_ids):
    """⚠⚠ **派生的功能子集里，这几页可能整页不存在。**

    实测（开源验收门逮到过三次，见 `test_one_primary_button_per_screen.py`）：
    `cs2-customizer` 里 `account` 整页不在，`about` 被机械替换改过名。
    ⭐ **照闭源版文件集写死的断言，在子集仓里不是「更严」，是「错」。**
    ⇒ 缺的页跳过；但**至少要剩下一页**，否则这条判据就是在空转。
    """
    kept = [p for p in page_ids if (REPO / "pages" / f"{p}_page.py").exists()]
    assert kept, (
        "四页一页都不在 —— 这不像发行版子集，像是这条判据的对象整批改名了")
    return kept


def test_the_scan_is_not_blind():
    """⭐ 空转守卫（RN-169）：先证明它看得见东西，再让它去断言「没问题」。

    `configure_primary` 一旦改名，下面每条断言都会无条件通过。
    """
    pages = _all_page_ids()
    assert len(pages) >= 25, f"只找到 {len(pages)} 个页面文件 —— 扫描器瞎了"
    total_bar = sum(len(_scan(p)[0]) for p in pages)
    assert total_bar >= 20, (
        f"全站只扫到 {total_bar} 处底栏绑定 —— `configure_primary/secondary` "
        "是不是改名了？那样这条判据会永远绿。")


def test_the_four_renovated_pages_have_exactly_one_entrance():
    """⭐⭐ 主刀：这四页里，底栏配的动作**不许**同时接在卡内某颗按钮上。"""
    offenders = []
    for page_id in _present(RENOVATED_PAGES):
        bar, card = _scan(page_id)
        dup = sorted(bar & card)
        if dup:
            offenders.append(f"{page_id}: {dup}")
    assert not offenders, (
        "这几页又长出了「同一个动作两个入口」：\n  " + "\n  ".join(offenders) +
        "\n⭐ 两颗一模一样的按钮，用户没有任何办法判断它们是不是同一件事"
        "（外审改前 16 发 16/16 逐字报出来）。"
        "\n⇒ 要么撤掉副本，要么这是一次获批的改版——那就把这一页挪进 "
        "BAR_CARD_DUPLICATE_ACTIONS 并写明归哪条 RN 管。")


def test_removing_the_copy_did_not_remove_the_action():
    """⭐⭐⭐ 反面守卫：撤的是**副本**，动作本身必须还在。

    撤重复最容易犯的错是**把两颗一起删掉** —— 而那种错
    **不会让上面那条判据变红**（重复确实没有了，只是这件事没人能做了）。
    ⭐ 一条只判「坏东西没了」的判据，挡不住「好东西也一起没了」。
    """
    missing, checked = [], 0
    present = set(_present(RENOVATED_PAGES))
    for (page_id, method), where in sorted(SURVIVING_ENTRANCES.items()):
        if page_id not in present:
            continue
        src = (REPO / "pages" / f"{page_id}_page.py").read_text(encoding="utf-8")
        if f"def {method}(" not in src:
            # ⚠⚠ **子集里这个动作被改名了**（`cs2-customizer` 的 about 页把
            #   `_show_changelog` / `_open_website` 换成了 `_open_releases` /
            #   `_open_repository`）。⭐ **照闭源版的方法名写死，在子集仓里
            #   不是「更严」，是「错」**（第 N 次）。
            #   ⇒ 方法整个不在这个 build 里 ⇒ 样本不可比，跳过（RN-140）。
            continue
        checked += 1
        bar, card = _scan(page_id)
        have = bar if where == "bar" else card
        if method not in have:
            missing.append(
                f"{page_id}.{method} 本该留在{'底栏' if where == 'bar' else '卡内'}，"
                f"实测底栏={sorted(bar)[:6]} 卡内里没有它" if where == "card"
                else f"{page_id}.{method} 本该留在底栏，实测底栏绑定里没有它")
    assert not missing, (
        "有动作被整个删掉了（撤副本撤过头）：\n  " + "\n  ".join(missing))
    # ⭐ 上面两个 `continue` 各自都有正当理由，但**两个加起来可以把这条判据跳空** ——
    #   而跳空的判据和通过的判据长得一模一样。完整产品 8 条、开源子集 4 条。
    assert checked >= 4, (
        f"只核了 {checked}/{len(SURVIVING_ENTRANCES)} 个入口 —— "
        "跳过的太多了，这条反面守卫已经形同虚设。")


def test_the_rest_of_the_debt_only_shrinks():
    """三向棘轮：**新增一页** / **某页变多** / **债表成了博物馆**。

    ⚠ 第三向最容易漏 —— 只判「变没变坏」的棘轮在缺陷修好之后会永远停在旧数上，
    从「守着一条线」退化成「记录一个历史」（同 RN-196 / RN-188）。
    """
    grew, shrank = [], []
    for page_id in _all_page_ids():
        bar, card = _scan(page_id)
        actual = tuple(sorted(bar & card))
        declared = tuple(sorted(BAR_CARD_DUPLICATE_ACTIONS.get(page_id, ())))
        if page_id in RENOVATED_PAGES:
            continue          # 由上面那条判据管，且它要求 0
        if not declared and actual:
            grew.append(f"{page_id}: 新增 {list(actual)}")
        elif declared and actual != declared:
            extra = sorted(set(actual) - set(declared))
            gone = sorted(set(declared) - set(actual))
            if extra:
                grew.append(f"{page_id}: 多出 {extra}")
            if gone:
                shrank.append(f"{page_id}: 债表写着 {list(declared)}，实测已经没有 {gone}")
    assert not grew, ("「同一个动作两个入口」变多了：\n  " + "\n  ".join(grew) +
                      "\n⇒ 别顺手在卡里再放一颗底栏已经有的按钮。")
    assert not shrank, ("存量债表和现实对不上了（多半是修好了没回来删）：\n  " +
                        "\n  ".join(shrank))


@pytest.fixture(scope="module")
def four_pages(qapp):
    """建一次窗，走那四页，收每页**可见**按钮的文案与它在不在底栏里。"""
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
        neutral.apply(config, list(win._page_names.keys()))

        found = {}
        for page_id in _present(RENOVATED_PAGES):
            _ui_mode.goto(win, page_id)
            for _ in range(3):
                qapp.processEvents()
            page = win.pages.get(page_id)
            if page is None:
                continue
            bar = getattr(page, "action_bar", None)

            def _in_bar(w):
                node = w
                while node is not None and node is not page:
                    if bar is not None and node is bar:
                        return True
                    node = node.parentWidget()
                return False

            rows = []
            for b in page.findChildren(QPushButton):
                if not b.isVisibleTo(page):
                    continue
                text = b.text().strip()
                if text:
                    rows.append((text, _in_bar(b)))
            found[page_id] = rows
        yield found
    finally:
        win.close()
        qapp.processEvents()


def test_the_runtime_scan_sees_buttons(four_pages):
    """空转守卫之二：运行时那一半也要先证明自己看得见东西。"""
    assert set(four_pages) == set(_present(RENOVATED_PAGES)), (
        f"只走到 {sorted(four_pages)} —— 页面没建出来？"
        "（这条 fixture 的名字还叫 `four_pages`，而 2026-08-31 批 36 之后是 5 页；"
        "名字没改是因为改名会同时动 6 处引用而不带来任何信息 —— 分母走 "
        "`RENOVATED_PAGES`，不走这个名字。）")
    for page_id, rows in four_pages.items():
        assert len(rows) >= 3, f"{page_id} 只扫到 {len(rows)} 颗可见按钮，扫描器瞎了"


def test_no_visible_button_text_appears_both_in_a_card_and_in_the_bar(four_pages):
    """⭐ 从**用户看得见的那一层**再问一遍同一件事。

    上面那条是 AST（问「代码里绑了几次」），这条是运行时（问「屏幕上有几颗」）。
    ⚠ 两条都要 —— 实测它们的答案不一样：`account` 的 `_open_website`
    在 AST 里绑了两处卡内按钮，而默认状态下只有一颗露脸。
    ⭐ **「写了几遍」和「看得见几颗」是两个问题，而缺陷发生在后者。**
    """
    offenders = []
    for page_id, rows in sorted(four_pages.items()):
        by_text = {}
        for text, in_bar in rows:
            by_text.setdefault(text, []).append(in_bar)
        for text, flags in sorted(by_text.items()):
            if any(flags) and not all(flags):
                offenders.append(f"{page_id}: 「{text}」底栏一颗 + 卡内 {flags.count(False)} 颗")
    assert not offenders, (
        "同一屏上，底栏和卡片里摆着文案完全相同的按钮：\n  " + "\n  ".join(offenders) +
        "\n⭐ 外审改前 16 发全部逐字报出这一对，理由一律是「无法判断是不是同一件事」。")


def test_the_card_that_lost_its_button_says_where_the_action_went():
    """⭐⭐⭐ 撤掉一颗按钮，**它留下的那行字会接管它的位置和读法**。

    改前 4 发**没有一发**提过 `viewmodel` 那行 CFG 状态文字；
    撤掉卡内那颗「保存到CFG」之后，同题同图 **3/3** 说
    「分不清左边那个是可点击的同步按钮还是状态展示」，
    一发逐字写「左侧的更像状态展示或**已置灰的按钮**」。

    原因不在那行字本身（它一个字都没改），而在它的邻居没了 ——
    它成了那张卡最下面、最像动作的东西，而那正是按钮刚才待的位置。
    ⭐ **一个控件怎么被读，由它的邻居决定。**

    ⇒ 两条要求：① 那行字是**整句**，不是短动词短语；
    ② 未保存那一支必须**指出动作去哪儿了**，且点名的按钮真的存在（RN-167 族）。
    """
    from PySide6.QtWidgets import QAbstractButton

    src = (REPO / "pages" / "viewmodel_page.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_mark_unsaved"), None)
    assert fn is not None, "viewmodel_page 里找不到 `_mark_unsaved` —— 这条判据瞎了"
    texts = [n.value for n in ast.walk(fn)
             if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) > 6]
    assert texts, "`_mark_unsaved` 里已经没有文案了 —— 这条判据在空转"
    msg = max(texts, key=len)
    assert msg.endswith("。"), (
        f"未保存时那行字是「{msg}」—— 它得是一句话。"
        "短动词短语 + 一个符号，在按钮刚被撤走的位置上会被读成按钮。")
    assert "保存到CFG" in msg, (
        f"未保存时那行字「{msg}」没说动作去哪儿了。"
        "撤掉入口的那张卡，有义务说清楚入口搬到了哪里（同 RN-131）。")

    # RN-167 族：点名的控件必须真的存在。
    page_ids = ["viewmodel"]
    assert page_ids  # 只是让下面这段的意图显式
    import _audit_neutralize as neutral
    from config import config
    neutral.apply(config)
    import pages.viewmodel_page as vm
    page = vm.ViewmodelPage()
    try:
        labels = {b.text().strip() for b in page.findChildren(QAbstractButton)}
        labels.add(page.action_bar.primary_btn.text().strip())
        assert "保存到CFG" in labels, (
            "那行字点名了「保存到CFG」，而这一页现在没有这颗按钮 —— "
            "文案点名的控件必须存在（RN-167 / RN-401）。")
    finally:
        page.deleteLater()


def test_the_dirty_flag_is_not_read_back_out_of_a_label():
    """⭐⭐⭐ 一句文案同时是这一页的状态真源时，**任何一次文字润色都是一次行为变更**。

    `viewmodel` 的脏/净判断原来是这么算的（**三处各抄一份**）：

        cfg_text = self._cfg_status_label.text().strip()
        is_dirty = ("未保存" in cfg_text) or ("已修改" in cfg_text)

    底栏那句回执、三张卡的摘要、五颗状态芯片，全都读它。
    于是批 31 只是把那句话改得更像一句话，**整页的脏/净判断当场反了**
    —— 新句子里既没有「未保存」也没有「已修改」。

    ⚠ 逮住它的是既有判据（`test_viewmodel_page_status_strip_tracks_dirty_state`
    断言的是芯片文案，而芯片正好在这条链的下游），不是我。
    ⇒ 现在真源是布尔 `_cfg_dirty`，文案由它渲染，方向单向。
    """
    src = (REPO / "pages" / "viewmodel_page.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        # `self._cfg_status_label.text()` —— 只要还有人读它，就有可能拿它当状态
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "text"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "_cfg_status_label"):
            offenders.append(node.lineno)
    assert not offenders, (
        f"第 {offenders} 行又在读 `_cfg_status_label.text()` —— "
        "那是**画在屏幕上的东西**，不是状态。脏标记的真源是 `_cfg_dirty`。"
        "\n⭐ 一句文案同时是状态真源时，改一个字就是改一次行为。")


def test_about_keeps_exactly_one_purple_button():
    """`about` 改前有**三颗**紫的（两颗「查看更新日志」+ 一颗「去 GitHub 点 Star」）。

    撤掉重复那颗只解决了两颗，剩下的两颗仍然违反 RN-139「一屏只许一颗主按钮」。
    ⭐ 「去 GitHub 点 Star」不是重复，它是**另一个主动作在竞争** ——
      所以修法不是删，是降权：它的分量该由卡片里那句加粗的话给，不该由按钮颜色给
      （批 22：饱和色被读成「这件事正在发生」）。
    """
    impl = REPO / "pages" / "about_page.py"
    if not impl.exists():
        pytest.skip("这个 build 里没有 about 页 —— 样本不可比（RN-140）")
    tree = ast.parse(impl.read_text(encoding="utf-8"))
    primaries = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "style_as_primary_button"
    ]
    assert not primaries, (
        f"`about_page.py` 里还有 {len(primaries)} 处 `style_as_primary_button` —— "
        "这一页的主按钮只该由底栏出（`configure_primary`）。"
        "\n⭐ 卡内再放一颗紫的 = 一屏两颗主按钮（RN-139：两颗紫的等于零颗）。")
