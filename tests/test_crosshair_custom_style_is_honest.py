# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-406：选中「自定义」而从没画过 ⇒ **准心一个像素都不画，页面既不拦也不说**。

## 这条是怎么来的

批 10 的**改完复跑**，外审**两轮 6/6 全票**报的是
「『准心样式』里的『自定义』与『绘制准心』入口割裂，不知从何处开始配置」——
说的是**信息架构**。而去读代码之后，底下压着的是一条**功能缺陷**：

```python
# crosshair_overlay._paint_custom
points = frame.custom_points or ()
if not points:
    return          # ← 什么都不画，也不报错
```

⭐⭐ 又一次「现象真、归因偏」——但这次它偏得**不够远**：
它指向的地方确实有东西，只是比它说的更严重。

## 用户实际会遇到什么

1. 打开总开关，在「准心样式」里点「自定义」（**这颗单选是可点的，没有任何阻拦**）；
2. 屏幕上什么都没有；
3. 他去看状态：顶部徽章写着 `样式 · 自定义`，**info 色，和别的样式长得一样**；
4. 紧凑档更糟 —— 那句「自定义 N 点」有 `and custom_points` 的短路，
   **0 点时整句消失**。⭐ **一个在最需要说话的时候恰好闭嘴的提示。**
5. 唯一说出真相的是 `detail_tooltip` 里那句「已保存 0 个自定义像素点」，
   而 tooltip 要**悬停才看得见**（同 RN-131：模态框/悬浮层里的话＝没说）。

## 修法为什么是这个形状

⛔ **不置灰那颗单选**：批 10 刚证过「一颗灰着的东西，形状本身在说
   『这里有个动作，只是现在不能点』」；而且外审那 6/6 票抱怨的**正是入口找不到**，
   把入口藏起来是把症状放大。
⛔ **不自动弹绘制器**：`_open_custom_editor` 是 `QDialog.exec()`，
   点一颗单选按钮弹出模态框是更坏的意外。
⛔ **不静默回落成十字**：那是屏幕上画着 A、状态里写着 B。
✅ **让状态说出后果，并且让颜色携带这个信息**：
   徽章 `info` → **`warning`**，文案从「样式 · 自定义」→「样式 · 自定义（未绘制）」。
   ⭐ 这一条是**结构性**的，不是文案性的 —— 颜色不携带「能不能用」的信息，
   本工程已经单独记过一次（网站那轮：「按钮按品牌着色而不按状态着色」）。

⚠ 徽章文案**只加 5 个字**是刻意的：CLAUDE.md 里记着一条血教训 ——
「我把徽章文案改长 ⇒ 芯片换行、比同排另外四颗高一截，而排版审计三条判据一条都没看见」。
"""
from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication, QLabel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crosshair_overlay  # noqa: E402
from config import config  # noqa: E402
from pages import crosshair_page as crosshair_page_module  # noqa: E402

#: 状态里必须出现的那个词。⭐ 判据钉的是「有没有说出后果」，不是具体措辞 ——
#: 所以只钉一个不可省的关键词，措辞怎么调都行。
NOT_DRAWN = "未绘制"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_page(qapp, monkeypatch):
    """按**样式 × 有没有数据**建页。

    ⚠ 两个轴都必须显式钉死：`tests/conftest.py` 那个配置目录是跨轮次累积的，
    上一轮某条判据存进去的值会让这里"看命"（RN-141）。
    """
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    made = []

    def _make(style: str, custom_points: int):
        monkeypatch.setattr(config, "crosshair_style", style, raising=False)
        monkeypatch.setattr(
            config, "crosshair_custom_data",
            [[10, 15], [15, 15], [20, 15]][:custom_points], raising=False)
        page = crosshair_page_module.CrosshairPage()
        made.append(page)
        return page

    yield _make
    for page in made:
        page.deleteLater()
    qapp.processEvents()


def _chips(page) -> list[tuple[str, str]]:
    """状态卡那排徽章 —— (level, text)，只取真在场的。"""
    return [
        (str(chip.property("level") or ""), chip.text().strip())
        for chip in page.findChildren(QLabel)
        if chip.objectName() == "audioStatusChip" and not chip.isHidden()
    ]


# --------------------------------------------------------------------- 事实

def test_a_custom_crosshair_with_no_points_really_draws_nothing():
    """⭐ **先把文案所依赖的那个事实钉死。**

    下面几条判据都在要求页面「说出后果」，而那个后果是
    「屏幕上不会出现准心」。如果哪天渲染器改成了「没数据就画个十字兜底」，
    那几句文案就集体变成假话 —— 而**没有任何一条文案判据看得见这件事**。
    ⭐ **一句文案所依赖的事实，要有判据看着**（同 RN-174 那条
    `..._never_writes_a_game_file`）。
    """
    src = crosshair_overlay.__file__
    import ast
    tree = ast.parse(open(src, encoding="utf-8").read())
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "_paint_custom"),
        None,
    )
    assert fn is not None, "crosshair_overlay 里找不到 _paint_custom —— 这条判据瞎了"
    early_return = any(
        isinstance(node, ast.If)
        and any(isinstance(b, ast.Return) and b.value is None
                for b in ast.walk(node))
        for node in fn.body
    )
    assert early_return, (
        "`_paint_custom` 不再是「没点就直接 return」了 —— "
        "如果它现在有兜底渲染，那么本文件下面那几句「未绘制 ⇒ 不显示准心」"
        "的文案就成了假话，要重新裁一次。"
    )


# ----------------------------------------------------------------- 状态徽章

def test_the_badge_says_the_consequence_not_just_the_name(make_page):
    """⭐⭐ **本条是 RN-406 的主刀。**

    `样式 · 自定义` 这句话是**真的**，但它回答的不是用户此刻的问题。
    用户此刻的问题是「我选了它，为什么屏幕上什么都没有」。
    """
    chips = _chips(make_page("custom", 0))
    style_chips = [(lvl, txt) for lvl, txt in chips if txt.startswith("样式")]
    assert style_chips, f"状态卡里找不到样式徽章：{chips}"
    level, text = style_chips[0]
    assert NOT_DRAWN in text, (
        f"选中「自定义」而一个点都没画，样式徽章却只写 {text!r} —— "
        f"它说的是名字，不是后果。屏幕上此刻一个像素都不会画。"
    )
    assert level == "warning", (
        f"样式徽章的色阶是 {level!r} —— 和「十字」「圆圈」那些正常状态一样。\n"
        f"⭐ 颜色不携带「现在能不能用」的信息，这条本工程单独记过一次。"
    )


def test_the_badge_goes_back_to_normal_once_something_is_drawn(make_page):
    """反向：画过之后不许还在报警。⭐ 一条一直红着的警告等于没有警告。"""
    chips = _chips(make_page("custom", 3))
    style_chips = [(lvl, txt) for lvl, txt in chips if txt.startswith("样式")]
    assert style_chips, f"状态卡里找不到样式徽章：{chips}"
    level, text = style_chips[0]
    assert NOT_DRAWN not in text and level != "warning", (
        f"已经画了 3 个点，样式徽章还是 {level!r} / {text!r}")


@pytest.mark.parametrize("style", ["crosshair", "dot", "circle", "t_shape"])
def test_no_other_style_is_ever_accused_of_being_undrawn(make_page, style):
    """反向：别的样式压根不需要"画"，不许被这条警告扫到。"""
    chips = _chips(make_page(style, 0))
    style_chips = [(lvl, txt) for lvl, txt in chips if txt.startswith("样式")]
    assert style_chips, f"状态卡里找不到样式徽章：{chips}"
    level, text = style_chips[0]
    assert NOT_DRAWN not in text and level != "warning", (
        f"样式 {style} 被判成「未绘制」了：{level!r} / {text!r}")


# --------------------------------------------------------------- 紧凑档摘要

def test_the_compact_summary_does_not_go_quiet_exactly_when_it_matters(make_page):
    """⭐⭐ 原状是 `if style_value == "custom" and custom_points:` ——

    **有点时才说「自定义 N 点」，0 点时整句消失。**
    ⭐ 一个在最需要说话的时候恰好闭嘴的提示，比没有这个提示更糟：
    它让「一切正常」和「什么都画不出来」在紧凑档里长得一模一样。
    """
    page = make_page("custom", 0)
    summary = page.crosshair_summary_label.text()
    assert NOT_DRAWN in summary, (
        f"紧凑摘要在 0 点时没提未绘制：{summary!r}")


def test_the_compact_summary_is_not_crying_wolf(make_page):
    """反向 + 空转守卫：有数据时不许出现那个词，且两种状态确实不同。"""
    empty = make_page("custom", 0).crosshair_summary_label.text()
    drawn = make_page("custom", 3).crosshair_summary_label.text()
    assert NOT_DRAWN not in drawn, f"画过之后紧凑摘要还在报警：{drawn!r}"
    assert empty != drawn, (
        "两种状态的紧凑摘要一模一样 —— 说明页面根本没读 crosshair_custom_data，"
        "上面几条是空转的")


# ----------------------------------------------------------------- 样式卡自己

def test_the_style_card_says_what_is_on_screen_right_now(make_page):
    """他**刚点的那张卡**要当场回答「所以现在屏幕上是什么」。

    ⚠ 这不是「补一句指路」（批 10 刚证过指路无效）——
    主句是**后果**：屏幕上不会出现准心。
    """
    text = make_page("custom", 0).style_summary_label.text()
    assert "不" in text and ("显示" in text or "出现" in text), (
        f"样式卡副文案没说清后果：{text!r}")


def test_the_style_card_is_quiet_when_there_is_nothing_wrong(make_page):
    """反向：正常状态下这张卡不许说这种话。"""
    text = make_page("crosshair", 0).style_summary_label.text()
    assert not ("不显示" in text or "不会出现" in text), (
        f"样式是十字，样式卡却说不显示：{text!r}")


# --------------------------------------------------------------- 自定义卡自己

def test_the_warning_colour_is_not_spent_on_a_perfectly_normal_default(make_page):
    """⭐⭐ 这条是**改前那一轮外审逼出来的，而且它直接和 RN-406 的修法打架**。

    「联动 · 关闭联动」是**默认值**，一个完全正常的状态，却常年顶着一颗橙色警示
    （原代码 `"positive" if kill_effect != "none" else "warning"`）。
    外审改前那一轮 **5 发**点名它「极易误导玩家以为是系统报警或必须配置的异常项」。

    ⭐⭐ 更要命的是：RN-406 刚在**同一排**加了一颗真警告。
    **两颗橙的等于零颗** —— 这是 RN-139「两颗紫的等于零颗」的徽章版。
    ⇒ 一屏上「warning 色」的名额是有限的，花在一个正常状态上，
      真出事的那一颗就不再显眼。
    """
    for style, points, expected_warnings in (("crosshair", 0, 0), ("custom", 0, 1)):
        page = make_page(style, points)
        # 总开关关着时「显示 · 未启用」也是 warning，这里只看它以外的
        warns = [txt for lvl, txt in _chips(page)
                 if lvl == "warning" and not txt.startswith("显示")]
        assert len(warns) == expected_warnings, (
            f"样式={style} 点数={points} 时，除「显示」外还有 {len(warns)} 颗橙色徽章："
            f"{warns}\n⭐ 一屏上 warning 的名额是有限的。")


def test_the_preview_box_does_not_look_like_a_rendering_failure(make_page):
    """⭐⭐ 这条是**我自己看图看出来的**，判据先行那一轮没想到。

    选中「自定义」而没画过时，`paint_crosshair` 画出来的是一张**全透明**的图 ——
    预览框于是变成一个纯黑的大方块。而**那正是缺陷的现场**，现场上一个字都没有。
    ⭐ 它长得像「渲染坏了」，不像「你还没画」。

    ⇒ 这里不放图，放话。⚠ 反向：正常样式下必须放图，不许放话
    （否则这条修法会把预览功能本身换掉）。
    """
    blank = make_page("custom", 0).preview_label
    assert blank.text().strip(), "预览框在「选了自定义但没画」时是空的，什么都没说"
    assert blank.pixmap().isNull(), (
        "预览框既放了话又放了图 —— 那张图是全透明的，只会让人以为渲染坏了")

    drawn = make_page("custom", 3).preview_label
    assert not drawn.pixmap().isNull(), "画过之后预览框不放图了"
    assert not drawn.text().strip(), f"画过之后预览框还在说话：{drawn.text()!r}"

    normal = make_page("crosshair", 0).preview_label
    assert not normal.pixmap().isNull(), "十字样式下预览框不放图了"


def test_the_blank_custom_judgement_has_exactly_one_source(make_page):
    """⭐⭐ **只测「零件好使」证明不了「零件装上了」**（批 10 的假绿就是这个形状）。

    上面几条都能被"在四个地方各抄一份同样的 if"满足 —— 而那正是 RN-107 族
    （同屏两处说法不一致）的制造方式。这条直接查**调用点**：
    `_custom_style_is_blank` 必须被真的调用，且调用它的是那两个同步方法。
    """
    import ast
    tree = ast.parse(open(crosshair_page_module.__file__, encoding="utf-8").read())
    defined = [n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_custom_style_is_blank"]
    assert len(defined) == 1, f"`_custom_style_is_blank` 定义了 {len(defined)} 次"

    callers = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_custom_style_is_blank"):
                callers.add(fn.name)
    assert {"_sync_overview_status", "_sync_panel_summaries"} <= callers, (
        f"`_custom_style_is_blank` 的调用点是 {sorted(callers)} —— "
        f"状态徽章和面板副文案这两条通路必须都走它，否则它们迟早各说各的。"
    )


def test_the_custom_card_stops_being_a_soft_suggestion_when_it_is_the_problem(make_page):
    """他**要去的那张卡**：原文是「先绘制一个常用模板会更高效」——

    那是一句**软建议**，在 `style == custom` 时它已经不是建议了，是必须做的事。
    ⚠ 而在别的样式下它仍然只是建议，不许一律改硬（那会把一句正常的提示
    变成一条永久警告）。
    """
    urgent = make_page("custom", 0).custom_summary_label.text()
    casual = make_page("crosshair", 0).custom_summary_label.text()
    assert urgent != casual, (
        f"自定义卡在「已选中自定义但没画」和「压根没选自定义」两种情况下"
        f"说的是同一句话：{urgent!r}")
    assert "更高效" not in urgent, (
        f"已经选中自定义却一个点都没有，这张卡还在说「会更高效」：{urgent!r}")
