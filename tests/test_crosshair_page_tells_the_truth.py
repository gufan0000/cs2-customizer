# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-174（改判后）：准心页的三条 —— 页头那句假话、底栏主按钮的身份、同名两颗。

## 这条缺陷的来历，比它本身更值得记

外审 **5/6 票**报「找不到保存 / 应用入口」，措辞高度一致，是九条里我
**把握最足**的一条。我当时把它读成「入口的名字起错了」，准备去改按钮名。

查实之后全反了：**这一页压根没有"应用入口"这个东西**。
参数每改一项各自的槽里就 `save_config()` 了，准心是软件自绘的覆盖层，
**不写任何游戏文件**。外审说玩家找不到，是**真的** —— 因为它不存在。

⭐⭐ **票数衡量的是「玩家困惑是真的」，不是「外审对成因的归因是对的」。**
⭐ **当一条建议是「把 X 改成 Y」时，先确认 X 是不是真的存在、真的干那件事。**

坏的是**页头那句话**（原文：「改完点右下角「绘制准心」写进游戏。」），
三个分句全假：

| 分句 | 实际 |
|---|---|
| 「改完点」 | 每改一项当场就存了（`:1053/1063/1074/1121/1130` 各自 `save_config()`）|
| 「写进游戏」 | 那颗按钮**不写任何游戏文件**；它打开的是 30×30 手绘板 |
| 「「绘制准心」」 | 那颗按钮**有一半时间不叫这个** —— 画过之后底栏主按钮变成「导出准心」|

⚠ 原建议「改名为『应用到游戏』」**会变成一句新的假话**（它不写游戏）。
⭐ **文案不许替代码编一个借口。**
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QAbstractButton, QApplication

from config import config
import pages.crosshair_page as crosshair_page_module

REPO = Path(__file__).resolve().parent.parent
PAGE_SRC = REPO / "pages" / "crosshair_page.py"

#: 与 RN-167 棘轮同一条正则（`tests/test_help_copy_names_real_controls.py`）。
#: ⚠ **故意抄一份而不是 import**：那条棘轮问的是「这个名字在源码里存不存在」，
#: 这里问的是「用户这一屏上有没有这颗控件」——两个问题不同，
#: 哪天那边为了它自己的问题放宽动词表，不该悄悄改变这边的判别力。
#:
#: ⚠⚠ **而这份抄件当场付了代价**：第一版抄的是**修好之前**的窄正则
#: （要求动词紧挨引号），于是它看不见「点**右下角**「绘制准心」」——
#: 也就是**它要防的那句原话**。回退验证当场判它假绿：把页头改回那句假话，
#: 判据纹丝不动。
#: ⭐⭐ **抄一份不是问题，抄了一份「修好之前的版本」才是。**
#: ⇒ 抄件照抄，但下面配一条**同步守卫**（`test_this_copy_of_the_regex_is_not_the_stale_one`）。
POSITION = (
    r"(?:右上角|右下角|左上角|左下角|页面底部|页面顶部|底部操作栏|底栏|操作栏|"
    r"底部|顶部|上面|下面|右边|左边|右侧|左侧|页尾|页首|这一页|本页|"
    r"最下面|最上面|卡片里|这里)"
)
CLICK_CONTEXT = re.compile(
    r"(点击|点|按下|按|勾上|勾选|打开|切到|进入|使用|可用|用|选中|回到|去)"
    r"\s*(?:" + POSITION + r"的?\s*)?[「]([^「」]{1,24})[」]"
)

#: 这一页**不写游戏文件**。写游戏文件的通路就这几条，全仓一致。
GAME_WRITE_CALLS = ("cfg_compiler", "write_cfg", "compile_cfg", "write_autoexec")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_page(qapp, monkeypatch):
    """按**状态**建页：`custom_points` 决定有没有自定义准心数据。

    ⚠ 状态必须显式钉死。`tests/conftest.py` 那个配置目录是跨轮次累积的，
    上一轮某条判据存进去的 `crosshair_custom_data` 会让这里"看命"（RN-141）。
    """
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    made = []

    def _make(custom_points: int):
        monkeypatch.setattr(
            config, "crosshair_custom_data",
            [[1, 1]] * custom_points, raising=False)
        page = crosshair_page_module.CrosshairPage()
        made.append(page)
        return page

    yield _make
    for page in made:
        page.deleteLater()
    qapp.processEvents()


def _visible_button_texts(page) -> list[str]:
    """用户**这一屏上真能看到**的按钮文案。

    ⚠ `isVisible()` 在没 show 过的树上恒为 False，所以看的是
    `isVisibleTo(page)` —— 它回答的是「假设这一页显示出来，它露不露脸」，
    正是我们要问的（同时不必真把窗口摆到屏幕上，见 §3 不许打扰前台）。
    """
    return [
        btn.text().strip()
        for btn in page.findChildren(QAbstractButton)
        if btn.isVisibleTo(page) and btn.text().strip()
    ]


def _header_description() -> str:
    """页头那句描述 —— 取 `PageHeader(...)` 的 `description=` 实参。"""
    tree = ast.parse(PAGE_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "PageHeader":
            continue
        for kw in node.keywords:
            if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
    raise AssertionError("crosshair_page.py 里找不到 PageHeader(description=...)")


# --------------------------------------------------------------------------
# A · 页头那句话
# --------------------------------------------------------------------------

def test_the_header_does_not_name_a_button_to_press():
    """这一页**没有"应用"这个动作**，所以页头点名任何按钮都是在编一条流程。

    ⭐ 与 RN-167 那条棘轮的分工：那条问「点名的控件存不存在」，
    这条问「**该不该有人被点名**」。名字对得上，不代表那句话是真的。
    """
    desc = _header_description()
    named = [name for _verb, name in CLICK_CONTEXT.findall(desc)]
    assert not named, (
        f"准心页页头点名了 {named} —— 而这一页没有任何「点了才生效」的动作："
        f"参数各自的槽里当场 save_config()，准心是软件自绘的覆盖层。"
        f"⇒ 点名一颗按钮就等于告诉玩家「不点就没生效」，那是假的。"
        f"当前页头：{desc!r}")


@pytest.mark.parametrize("lie", ["写进游戏", "写入游戏", "写进 CFG", "写入CFG", "生效到游戏"])
def test_the_header_does_not_claim_it_writes_to_the_game(lie):
    """拦已知的那句假话本身。

    ⚠ 这条是**形状棘轮**，不是发现通道 —— 换个说法它就看不见了。
    真正把成因钉死的是下面那条 `..._never_writes_a_game_file`。

    ⚠⚠ **子串棘轮读不懂否定。** 「**不**写进 CFG」里也含着「写进 CFG」，
    照直匹配会把一句**完全正确**的文案判红，然后人就会去改那句对的话。
    ⇒ 命中前先看前面两个字是不是否定词。
    （同 RN-072/RN-163 那族：判据被自己该放过的东西判红。）
    """
    desc = _header_description()
    negations = ("不", "别", "无需", "不会", "并不")
    for match in re.finditer(re.escape(lie), desc):
        head = desc[max(0, match.start() - 2):match.start()]
        if any(head.endswith(word) for word in negations):
            continue
        raise AssertionError(
            f"页头说它「{lie}」 —— 而这一页一个游戏文件都不写。"
            f"⭐ 文案不许替代码编一个借口。当前页头：{desc!r}")


def test_the_crosshair_page_never_writes_a_game_file():
    """把「写进游戏」那句假话的**成因**钉死，而不只是拦措辞。

    如果哪天准心真的开始往 CFG 里写，这条会红 —— 那时候页头的说法
    就该跟着改回来。⭐ **一句文案所依赖的事实，要有判据看着。**
    （用 AST 查「有没有 X」，不用 grep：截断会给出"没有"，
    而"没有"往往正是断言的全部内容。）
    """
    tree = ast.parse(PAGE_SRC.read_text(encoding="utf-8"))
    hits = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in GAME_WRITE_CALLS:
            hits.add(node.attr)
        if isinstance(node, ast.Name) and node.id in GAME_WRITE_CALLS:
            hits.add(node.id)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name.split(".")[-1] in GAME_WRITE_CALLS:
                    hits.add(alias.name)
    assert not hits, (
        f"准心页现在会写游戏文件了（{sorted(hits)}）—— 页头那句「不写进游戏」"
        f"的说法要重新裁一次，别让文案继续停在旧事实上")


# --------------------------------------------------------------------------
# B · 底栏主按钮的身份
# --------------------------------------------------------------------------

@pytest.mark.parametrize("points", [0, 3])
def test_the_bottom_bar_offers_no_apply_shaped_button(make_page, points):
    """底栏**不许有主按钮** —— 这一页没有"应用"这个动作。

    原状：没画过时主按钮是「绘制准心」（打开手绘板），画过之后变成「导出准心」
    （存 json）—— 同一个位置、同一个视觉重量，两件完全不同的事。

    ⚠⚠ **第一版修法是"把它固定成「导出准心」、没数据时置灰"，当场被外审否掉**：
    「置灰的『导出准心』极易被误认为是『保存/应用』按钮，导致玩家误以为
    当前修改未生效」。⭐⭐ **一颗灰着的、紫色的、蹲在右下角的按钮，形状本身
    就在说「这里有个保存动作，只是现在不能点」** —— 于是我把那条 5/6 票的
    原始困惑**换了个样子留在了原地**。

    ⭐ 主按钮**可以**随状态变，前提是那几个状态是同一条流程的相邻两步
      （闪光页「启动」→「前往效果预览」就是）。而「绘制」和「导出」不是。
    """
    page = make_page(points)
    bar = page.action_bar
    assert bar.primary_btn.isHidden(), (
        f"底栏又出现了主按钮「{bar.primary_btn.text()}」（自定义点数={points}）——"
        f"这一页没有任何「点了才生效」的动作，一颗主按钮形状的东西就是在暗示有")


def test_the_bottom_actions_are_the_same_in_both_states(make_page):
    """底栏提供的动作在两种状态下**是同一组**，只有可点性不同。"""
    def actions(points):
        bar = make_page(points).action_bar
        return [b.text().strip() for b in
                (bar.extra_btn, bar.secondary_btn, bar.primary_btn)
                if not b.isHidden()]

    assert actions(0) == actions(3), (
        f"底栏的动作组随状态变了：没数据 {actions(0)} vs 有数据 {actions(3)}")


def test_the_page_has_exactly_one_primary_button(make_page):
    """全页只许有一颗主按钮，且它是这一页唯一"点了会发生新事情"的动作。

    ⭐ RN-139 的原话：**两颗紫的等于零颗 ——「主」是相对的**（RN-186 同族）。
    删掉底栏那颗之后，剩下的唯一一颗是自定义准心卡片里的「绘制准心」。
    """
    page = make_page(0)
    primaries = [b.text().strip() for b in page.findChildren(QAbstractButton)
                 if b.isVisibleTo(page) and b.objectName() == "primaryButton"]
    assert primaries == ["绘制准心"], f"全页的主按钮是 {primaries}"


def test_the_bottom_line_answers_the_question_that_started_all_this(make_page):
    """底栏那行字要**先回答**「我改的东西保存了吗」，再报状态。

    外审 5/6 票的原始困惑就是这一句 —— 而这一页整屏没有任何"已保存"的回执，
    于是玩家去找一颗保存按钮，而那颗按钮不存在。
    ⭐ **没有回执的自动保存，在用户那里等于没保存。**
    """
    message = make_page(0).action_bar.message_label.text()
    assert "自动保存" in message, f"底栏没说改动已经存了：{message!r}"


def test_that_state_axis_is_not_vacuous(make_page):
    """反空转：上面那条比的两种状态，必须真的是两种状态。

    ⚠ 如果 `crosshair_custom_data` 没被页面读到，两次建页会一模一样，
    上面那条就变成「x == x」。⭐ 一条两边取同一个值的判据，读起来像在比较，
    实际什么也没比。
    """
    empty_msg = make_page(0).action_bar.message_label.text()
    drawn_msg = make_page(3).action_bar.message_label.text()
    assert empty_msg != drawn_msg, (
        "两种状态建出来的底栏完全一样 —— 说明页面根本没读 crosshair_custom_data，"
        "上面那条状态判据是空转的")


@pytest.mark.parametrize("points", [0, 3])
def test_export_is_offered_in_both_states_with_its_reason(make_page, points):
    """「导出准心」在两种状态下都要**在场**：有数据时能点，没数据时禁用。

    ⚠ 让它时有时无，就是把"为什么现在不能导出"这个信息藏起来 ——
    用户看到的是"这个功能不存在"，而不是"还没有东西可导"。
    ⭐ 这与 RN-197 是同一条：**一个只在某种状态下才出现的东西，
    在别的状态里等于没有解释。**
    """
    page = make_page(points)
    texts = [b.text().strip() for b in page.findChildren(QAbstractButton)
             if b.isVisibleTo(page)]
    assert "导出准心" in texts, f"自定义点数={points} 时「导出准心」不在场：{texts}"
    btn = next(b for b in page.findChildren(QAbstractButton)
               if b.text().strip() == "导出准心")
    assert btn.isEnabled() == (points > 0), (
        f"自定义点数={points}，而「导出准心」的可点状态是 {btn.isEnabled()}")


# --------------------------------------------------------------------------
# C · 同名两颗
# --------------------------------------------------------------------------

@pytest.mark.parametrize("points", [0, 3])
def test_draw_crosshair_appears_exactly_once(make_page, points):
    """「绘制准心」在这一屏上只许有一颗。

    原状：底栏一颗（没画过时）+ 自定义准心卡片里一颗（`:1024`），
    **同名、同槽、同功能**。⭐ 与 RN-404（viewmodel 同页两颗「保存到CFG」）
    是同一族 —— 说明这不是某一页的手滑，是**「卡片里放一颗主操作 +
    底栏再放一颗」这个版式本身**会稳定产出的形态。
    """
    page = make_page(points)
    texts = _visible_button_texts(page)
    count = texts.count("绘制准心")
    assert count == 1, (
        f"自定义点数={points} 时这一屏上有 {count} 颗「绘制准心」：{texts}")


def test_the_header_states_the_precondition_for_taking_effect():
    """⚠⚠ 页头说「当场就生效」时，必须同时说清**它的前提**。

    第一版把三句假话改成了一句真话「改哪一项当场就生效」——
    **外审当场指出它还是半真话**（4/6 判高）：
    「总开关默认关闭，玩家调完参数直接进游戏会发现没效果」。
    确实如此：`crosshair_enabled` 关着的时候，"当场就生效"是假的。

    ⭐⭐ **我把三句假话改成一句真话时，漏掉了那句真话自己的前提。**
    ⭐ 一句有条件成立的话，不写条件就等于在大多数情况下是假的
      —— 而这一页的默认状态恰好就是那个"大多数"（总开关默认关闭）。
    """
    desc = _header_description()
    assert "生效" in desc, f"页头不再谈生效了，这条判据该重写：{desc!r}"
    assert "总开关" in desc, (
        f"页头说了「生效」却没说前提（总开关）。默认状态下总开关是关的，"
        f"于是这句话对新用户来说是假的。当前页头：{desc!r}")


def test_the_activation_story_is_told_in_exactly_one_place():
    """「怎么生效」这件事，整页只许说一处。

    原状说了**三处**：页头 description、标题行右侧那条小字
    （「调完直接进游戏看效果」）、以及帮助面板。而其中两处都漏了总开关这个前提。
    ⭐⭐ **同一件事说三遍，任何一遍变假都不会有人发现 —— 因为没人知道有三遍。**
    （外审同一轮也独立报了「顶部胶囊栏、各卡片副标题、底部栏三处重复堆叠」。）
    """
    src = PAGE_SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
        and node.body and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    literals = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    tellers = [s for s in literals if "进游戏" in s and "看" in s]
    assert not tellers, (
        f"页面里又出现了第二处讲「怎么生效」的文案：{tellers}。"
        f"这件事只放页头那一句 —— 多一处就多一处会各自变假的地方")


def test_this_copy_of_the_regex_is_not_the_stale_one():
    """同步守卫：这份抄件必须**跟得上** RN-401 修好之后的判别力。

    ⚠ 第一版抄的是修好**之前**的窄正则（要求动词紧挨引号），
    于是它看不见「点右下角「绘制准心」」—— 也就是它要防的**那句原话**。
    回退验证当场判它假绿：把页头改回那句假话，判据纹丝不动。

    ⭐⭐ **抄一份不是问题，抄了一份「修好之前的版本」才是。**
    ⭐ 这条守卫不要求两份正则逐字相同（它们回答不同的问题，本来就该能各自演进），
      只要求这一份**逮得住那句原话**。
    """
    original_lie = "调准心的形状、颜色、动效和击杀联动。改完点右下角「绘制准心」写进游戏。"
    hits = [name for _verb, name in CLICK_CONTEXT.findall(original_lie)]
    assert hits == ["绘制准心"], (
        f"这份正则看不见 RN-174 那句原话里点名的按钮（抄到了修好之前的版本）：{hits}")
