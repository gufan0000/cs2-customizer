# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 38（2026-09-01）：预设中心这一页说的话，和它做的事对不对得上。

## 主刀：**这一页把「你想打包哪些」当成了「你改了哪些」**

`_on_selection_changed` 里有一句 `self.mark_dirty()`。勾一下「局内视角」
—— 一个纯粹的「这一套包含哪些」的**选择** —— 实测 config 里
**0 个键**发生变化（57 个会被写回的键逐个深拷贝比对过），
而这一句让页面进入 dirty 态。dirty 在 `DirtyPageMixin` 里带着一项权力：

    can_leave_page() → QMessageBox「当前页面有未保存修改，是否保存后离开？」

⇒ 实测四步，每一步都长得完全正常，每一步都是假的：

  ① 勾一下      → 胶囊「状态 · 待应用」          假状态
  ② 底栏        → 「有未应用的预设变更。」        假句子
  ③ 想离开这一页 → 模态框拦人，can_leave_page()=False   假拦截
  ④ 点「保存并离开」→ `_save_changes()` 改动 **0 个键**，
                     却弹「已应用类型: hud_rules, screen_effects, …」 假成功

⭐⭐⭐ **一个假前提，会一路把四个各自正确的机制变成四句假话。**
那四个机制（dirty 标志、状态胶囊、离开确认、应用回执）单看每一个都没写错，
错的是它们共用的那个前提：「这一页有一种叫『未保存的修改』的东西」。

## ⭐⭐ 为什么外审替它作了不在场证明

改前 12 发问「你现在按下『应用当前预设』，软件里会发生什么」：
**0/12 答「会有变化」**，7/12 答「不会有变化」（依据逐字是那颗「状态 · 已同步」胶囊）。
也就是说 —— **它答对了**。

因为上面那四步里，**只有第 ①② 步在屏幕上，而它们要等用户动一下才出现**；
③④ 一个是模态框、一个是 config 的字节，都不在任何一张截图里。

⭐⭐ **看图这把尺子量的是「这一屏此刻说了什么」，量不到「你动一下之后它会说什么」。**
不是尺子方向反了（批 32），是**这个缺陷只在时间轴上存在**，而截图没有时间轴。
⇒ 这一条只能由判据钉住。

## 另一半：**底栏那句话点名的类别，是一份对不上的半份清单**

底栏构造时写死「支持 HUD / 屏幕特效 / 特殊音效 **三域**预设。」，
而同屏往上 250px 就摆着 **7 个**勾选框，引擎 `SUPPORTED_TYPES` 也是 **7** 类。
外审 12 发 **12/12 答「7 类」、12/12 答「矛盾: 有」**，11/12 逐字抄出了那句话。

⭐ 而这句话还是**一次性**的：`_refresh_dirty_ui` 一跑就把它冲掉，再也回不来
—— **它既是假的，又只在零交互的首屏出现，也就是每个人看到的第一眼。**
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "pages" / "preset_center_page.py"


@pytest.fixture()
def page(qapp, monkeypatch):
    """建一页真的 `PresetCenterPage`，并把所有模态框换成探针。

    ⚠ 不 monkeypatch `export_bundle` / `apply_bundle` —— 本文件里好几条断言
      问的正是「真的写回去之后 config 变没变」，替身会把那个问题整个抹掉。
    """
    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: 0)
    import pages.preset_center_page as mod

    p = mod.PresetCenterPage()
    p.resize(1280, 900)
    p.show()
    qapp.processEvents()
    yield p
    p.deleteLater()
    qapp.processEvents()


def _chips(page) -> list[str]:
    bar = page.status_badge_label
    layout = bar.layout()
    if layout is None:
        return []
    out = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        w = item.widget() if item else None
        if isinstance(w, QLabel) and w.objectName() == "audioStatusChip" and not w.isHidden():
            out.append(w.text())
    return out


def _visible_texts(page) -> list[str]:
    return [w.text() for w in page.findChildren(QLabel)
            if w.isVisibleTo(page) and w.text()]


# --------------------------------------------------------------------------
# 空转守卫：先证明这支夹具真的建出了一页能用的东西（RN-169）
# --------------------------------------------------------------------------

def test_the_fixture_really_built_the_page(page):
    """⭐ 没有这一条，下面每一条「不许出现 X」的断言都能靠「页面是空的」拿到绿。"""
    assert len(_chips(page)) >= 3, f"状态胶囊只有 {_chips(page)} —— 页面没建全"
    assert len(_visible_texts(page)) >= 15, "可见文本太少，这一页多半没建出来"
    labels = [lb for _a, _t, lb in page._TYPE_CHECKBOX_SPEC]
    assert len(labels) >= 5, f"打包类别只有 {labels} —— 分母塌了"


# --------------------------------------------------------------------------
# 主刀
# --------------------------------------------------------------------------

def test_picking_what_to_package_is_not_an_unsaved_change(page, qapp):
    """勾一下「这一套包含哪些」之后，这一页不许说自己有未保存的修改。

    ⭐ 这条判据同时钉住了那四步里的 ①②③：胶囊、底栏、拦人的模态框
      —— 它们全都只看 `is_dirty()` 一个值。
    """
    page.clear_dirty()
    qapp.processEvents()
    box = page.cb_viewmodel if not page.cb_viewmodel.isChecked() else page.cb_magnifier
    box.setChecked(not box.isChecked())
    qapp.processEvents()

    assert not page.is_dirty(), (
        "勾一下打包范围就把整页标成「未保存」了。\n"
        "⭐ 这一步 config 里一个键都没动（见本模块头的实测），"
        "而 dirty 会让 `can_leave_page()` 弹模态框拦住用户离开。")
    assert "未应用" not in page.action_bar.message_label.text(), (
        f"底栏说「{page.action_bar.message_label.text()}」，而并没有任何改动。")
    assert not any("待应用" in c for c in _chips(page)), (
        f"状态胶囊说 {_chips(page)} —— 「待应用」的那个东西不存在。")


def test_you_can_leave_the_page_after_only_picking_a_scope(page, qapp, monkeypatch):
    """⭐⭐ 这条是上一条的**行为面**，故意分开写。

    上一条问的是「`is_dirty()` 等于什么」，这一条问的是
    「用户想走的时候，屏幕上会不会冒出一个框」。
    ⚠ 只钉前者是不够的 —— 拦人的权力挂在 `can_leave_page()` 上，
      哪天有人换个别的条件去弹那个框，上一条照样是绿的。
    """
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)

    page.clear_dirty()
    qapp.processEvents()
    box = page.cb_viewmodel if not page.cb_viewmodel.isChecked() else page.cb_magnifier
    box.setChecked(not box.isChecked())
    qapp.processEvents()

    assert page.can_leave_page() is True, (
        "只是勾了一下打包范围，就走不掉了。")
    assert not shown, (
        f"离开这一页时弹了框：{shown}\n"
        "⭐ 「你想导出哪些」不是「你改了哪些」——前者没有资格拦人。")


def test_the_only_thing_that_makes_this_page_dirty_is_an_unapplied_import(page):
    """dirty 在这一页只许有一个来源：**读进来一份还没应用的预设包**。

    ⭐ 走 AST 而不是行为，是因为「还有没有第二个来源」这种问题，
      跑一遍摸不出来 —— 没被触发和不存在长得一模一样（批 37）。
    """
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    callers = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "mark_dirty" for n in ast.walk(fn)):
            callers.append(fn.name)

    assert callers, (
        "这一页一处 `mark_dirty()` 都没有了 —— "
        "那么「读进来一份还没应用的预设包」这件事就没人记得住了。\n"
        "⭐ 空转守卫：这条判据要是没有它，把 dirty 整个删掉也能拿到绿。")
    assert sorted(callers) == ["_import_bundle_from_file"], (
        f"`mark_dirty()` 的调用方是 {sorted(callers)}。\n"
        "这一页只有一件事配叫「未保存的修改」：读进来一份预设包、还没应用。\n"
        "⭐ 勾选打包范围**不是** —— 它一个 config 键都不动。")


def test_an_imported_bundle_really_does_make_the_page_dirty(page, qapp):
    """⭐ **阳性对照**：上一条只说「别的都不许」，这一条说「该有的那个真的有」。

    没有它，把 `_import_bundle_from_file` 里那句也删掉，上面两条会更绿。
    """
    page.clear_dirty()
    qapp.processEvents()
    from core.presets.preset_center import export_bundle

    bundle = export_bundle(["hud_rules"])
    page._current_bundle = bundle
    page.mark_dirty()
    qapp.processEvents()
    assert page.is_dirty()
    assert page.can_leave_page.__self__ is page  # 契约还在
    assert any("导入" in c or "读入" in c or "待应用" in c for c in _chips(page)), (
        f"读进来一份还没应用的包时，状态胶囊是 {_chips(page)} —— 没有一颗在说这件事。")


def test_pressing_apply_with_nothing_imported_cannot_report_success(page, qapp, monkeypatch):
    """默认状态下不许出现一颗「按下去 0 个键会变、却报『已应用 N 类』」的按钮。

    ⭐ 这是那四步里的第 ④ 步，而它**结构上不在任何截图里** ——
      改动发生在 config 的字节上，回执发生在一个模态框里。
    """
    said = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **_k: said.append(a[2] if len(a) > 2 else ""))
    page.clear_dirty()
    qapp.processEvents()

    # ⭐ 分母守卫：先证明这一屏上真的有一堆按钮，再让它去断言「没有那一颗」。
    #   （`test_judges_are_not_idling` 的 A 组说的正是这件事：
    #     一条只做 `assert not offenders` 的判据，在分母为空时必然全绿。）
    visible = [b for b in page.findChildren(QPushButton)
               if b.isVisibleTo(page) and b.text()]
    assert len(visible) >= 8, f"这一页只扫到 {len(visible)} 颗可见按钮 —— 分母塌了"

    applies = [b for b in visible if b.isEnabled() and "应用当前预设" in b.text()]
    assert not applies, (
        f"默认状态下还有 {[b.text() for b in applies]} 可点。\n"
        "⭐ 实测按下去 config 的 57 个键**一个都不会变**（它把当前设置打包再原样写回），"
        "而它会弹「已应用类型: …」——一句为空转出具的成功回执。")
    # ⚠ 反面：那颗按钮**必须还在**，只是点不动。
    #   ⭐ 没有这一句，「把整个动作删干净」也能拿到绿 —— 而那样就没人能落地
    #     一份读进来的预设包了（撤重复最容易犯的错是把两颗一起删掉）。
    assert not page.apply_btn.isEnabled()
    assert page.apply_btn.isVisibleTo(page), "「应用读入的预设包」整颗不见了"


def test_applying_the_current_config_back_onto_itself_is_a_no_op(page):
    """⭐ 把上面那条的**前提**单独钉住：这不是「碰巧没变」，是结构上不可能变。

    `export_bundle(当前 config)` → `apply_bundle` 写回同样的值。
    ⚠ 这一条不许被上面那条替代：哪天有人让这颗按钮变得有作用，
      「不许出现这颗按钮」就从「它没用」退化成一条纯粹的版式偏好。
    """
    from config import config
    from core.presets.preset_center import apply_bundle, export_bundle

    bundle = export_bundle(page._selected_types())
    watched = [k for item in bundle["items"] for k in item["payload"]]
    assert len(watched) >= 20, f"只有 {len(watched)} 个键进了包 —— 分母塌了"
    before = {k: copy.deepcopy(getattr(config, k, None)) for k in watched}
    apply_bundle(bundle, mode="merge")
    changed = [k for k in watched if before[k] != getattr(config, k, None)]
    assert not changed, (
        f"把当前配置原样写回自己，居然有 {len(changed)} 个键变了：{changed[:5]}\n"
        "那说明 export/apply 不是互逆的，这一页的问题就不是"
        "「按了没用」而是「按了会悄悄改东西」——两条都得重裁。")


# --------------------------------------------------------------------------
# 另一半：半份清单
# --------------------------------------------------------------------------

def test_no_visible_sentence_names_a_half_list_of_the_supported_kinds(page, qapp):
    """⭐⭐ 这条判据就是这次缺陷的定义。

    这一页上任何一句**枚举类别**的话，只有两种合法说法：

      · 说「这个软件支持哪些」 ⇒ 必须把 **7 类全部**说完；
      · 说「你现在勾了哪些」   ⇒ 必须**等于当前勾选**。

    第三种（点名两三个就停）都是假话。底栏那句
    「支持 HUD / 屏幕特效 / 特殊音效 三域预设。」就是第三种，
    而它出现在**零交互的首屏**上。

    ⚠ 不去钉「三域」这两个字：钉字面量只能拦住这一次的写法。
      ⭐ 批 27 那条 —— 不问这句话是怎么造出来的，只问屏幕上有没有这样一句话。
    """
    labels = [lb for _a, _t, lb in page._TYPE_CHECKBOX_SPEC]
    checked = {lb for attr, _t, lb in page._TYPE_CHECKBOX_SPEC
               if getattr(page, attr).isChecked()}

    texts = _visible_texts(page) + [page.action_bar.message_label.text()]
    offenders = []
    for text in texts:
        named = {lb for lb in labels if lb in text}
        if len(named) < 2:
            continue                      # 点名 0~1 个不算「枚举」
        if named == set(labels) or named == checked:
            continue                      # 两种合法说法
        offenders.append((text, sorted(named)))

    assert not offenders, (
        "这些话点名了一份**对不上的半份清单**：\n  " +
        "\n  ".join(f"「{t}」点名 {n}（共 {len(labels)} 类，当前勾了 {len(checked)} 类）"
                    for t, n in offenders) +
        "\n⭐ 一句枚举类别的话，要么说全部，要么说当前勾选。第三种都是假话。")


def test_the_scope_chip_says_how_many_there_are_not_just_how_many_are_ticked(page):
    """⭐⭐ **这条是改完复跑逼出来的，而它逼出来的是我自己这一批造的。**

    改前：底栏那句假话在，而七个勾选框就在第一屏上 ⇒ 外审 12/12 答「能装 **7** 类」。
    改后第一版：假话没了，可重排把那七个勾选框挪到了折线以下 ⇒
    窗口档 **6/6 答「5」**（那是「你现在勾了几个」），整页档才答 7。

    ⭐ 我修掉了那句假话，同时**把这个问题的答案从第一屏上搬走了**；
      而第一屏上仅存的那颗胶囊「范围 · 5 类」，孤零零地读起来是含糊的 ——
      批 31 那条（一个控件怎么被读，由它的邻居决定）的另一个形态：
      **我搬走的是它的邻居，它自己一个字都没改，意思却变了。**
    ⇒ 让它自带分母。
    """
    total = len(page._TYPE_CHECKBOX_SPEC)
    chips = _chips(page)
    scope = next((c for c in chips if c.startswith("范围")), None)
    assert scope, f"找不到「范围」那颗胶囊：{chips}"
    assert f"/{total}" in scope, (
        f"「{scope}」只说了勾中几个，没说一共几类。\n"
        "⭐ 这颗胶囊在第一屏上，而那七个勾选框不在 —— 它得自己把话说完。")


def test_the_bottom_line_does_not_overstate_what_applying_a_preset_does(page):
    """⭐ 底栏那句话不许说成「换掉你现在的设置」。

    三条应用通路 —— 内置精选 `_apply_starter_pack`、我的预设 `apply_preset`、
    按地图 `apply_rule_for_map` —— **全都是 `mode="merge"`**（AST 实测），
    只写这份预设覆盖到的键。说「换掉你现在的设置」是**朝着更吓人的方向**说过头了。

    ⚠⚠ 这句话的第一版就是这么写的，是**改完复跑**逮住的（紧凑窗口 3/3 报它
      和「模式 · 合并」互相矛盾）—— 批 36 那条第二次现身：
      **这一批最贵的一句话，是我自己补上去的那半句。**
    """
    import core.presets.my_presets as mp

    src = ast.parse((REPO / "core" / "presets" / "my_presets.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(src)
              if isinstance(n, ast.FunctionDef) and n.name == "apply_preset")
    default = fn.args.defaults[-1]
    assert isinstance(default, ast.Constant) and default.value == "merge", (
        "`apply_preset` 的默认模式不是 merge 了 —— 底栏那句话得重新裁一次")
    assert mp is not None

    text = page.action_bar.message_label.text()
    assert "换掉你现在的设置" not in text, (
        f"底栏说「{text}」—— merge 模式只动这份预设覆盖到的键，别的一个不碰。")
    assert "覆盖到的" in text or "别的不动" in text, (
        f"底栏说「{text}」—— 没说清「只动这套预设管的那几类」。")


def test_tab_walks_the_cards_in_the_order_they_are_shown(page, qapp):
    """⭐⭐ **摆放顺序改了，Tab 键的顺序不会跟着改。**

    Qt 的焦点链默认走**构造顺序**，而本批只动了**显示顺序** ——
    首跑 `scripts/tab_order_audit.py` 当场报「[preset_center] 需挪动 8 个」：
    屏幕上第一张卡（内置精选）里的控件，按 Tab 要按到第 12 下才轮到。

    ⭐⭐ 这是判据抓的，我自己出图、外审看图**结构上都不可能看见** ——
      焦点顺序不在任何一张截图里。
      （和本批主刀同形：**截图没有时间轴，也没有键盘。**）

    ⚠ 这里不重造一遍 `tab_order_audit` 的阅读序算法（那份判据自己在跑）。
      这一条只钉一件更窄、也更稳的事：**焦点链先走完靠前那张卡，
      才轮到靠后那张卡** —— 也就是重排必须被跟上。

    ⚠⚠ **这条判据的第一版被回退验证判成假绿**，而原因是它问错了问题：
      它问「从『内置精选』的下拉框出发，一路 Tab 走不走得到工作台的第一个勾选框」——
      ⭐⭐ **而焦点链是一个环**，从任何一个控件出发都必然走到其余每一个。
      **那个问题的答案永远是「能」，跟顺序毫无关系。**
      ⇒ 改成从页面本身这个**固定原点**走完整个环，比两者的**下标**。
    """
    order, node = [], page
    for _ in range(600):
        node = node.nextInFocusChain()
        if node is page or node is None:
            break
        order.append(node)
    assert len(order) >= 20, (
        f"整条焦点链只有 {len(order)} 个控件 —— 这一页有 29 个可聚焦控件，环没走完")
    index = {id(w): i for i, w in enumerate(order)}
    starter = index.get(id(page.starter_combo))
    workbench = index.get(id(page.cb_hud))
    assert starter is not None and workbench is not None, (
        "「内置精选」的下拉框或工作台的第一个勾选框不在焦点链里")
    assert starter < workbench, (
        f"焦点链里「内置精选」排在第 {starter}、工作台的第一个勾选框排在第 {workbench} —— "
        "屏幕上内置精选在上面，Tab 却先走工作台。\n"
        "⭐ Qt 的焦点链默认走**构造顺序**，重排只动了显示顺序。")


def test_nothing_can_silently_throw_away_an_imported_bundle(page, qapp):
    """⭐⭐⭐ 「读进来一份包」这件事，不许被一个不说话的动作抹掉。

    `_render_preview()` 第一句就是 `export_bundle(当前勾选)` 并覆盖 `_current_bundle`。
    改前底栏次位那颗「重新预览」直接绑着它 ⇒ 读进来一份包、还没应用时点一下，
    那份包**一声不响地没了**，而页面仍然 dirty、「应用」仍然亮着，
    按下去应用的是**你自己的当前配置**。

    ⚠⚠ 它本来不显眼。是**我撤掉底栏主按钮之后，它接管了底栏最响的位置**，
      改完复跑当场有一发点它的名（「右下角最醒目的常驻操作是「重新预览」，
      刚进来的玩家无法理解其作用与触发时机」）——
      ⭐ 批 31 逐字再现：**一个控件怎么被读、有多大杀伤力，由它的邻居决定。**

    这条钉两件事：① 底栏不再有任何东西绑着 `_render_preview`；
    ② 改勾选**确实**会把那份包扔掉，所以 dirty 必须跟着落下来
      —— **让标志位重新指向一个真实存在的东西**。
    """
    from PySide6.QtWidgets import QAbstractButton

    # ⭐ 分母守卫：底栏那两颗按钮**是建出来的**（`PageActionBar` 自带 primary/secondary），
    #   本批只是把它们 `setVisible(False)`。先确认我看的是一条真的底栏，
    #   再让它去断言「一颗都没露脸」。
    all_bar = page.action_bar.findChildren(QAbstractButton)
    assert len(all_bar) >= 2, (
        f"底栏里只找到 {len(all_bar)} 个按钮控件 —— `PageActionBar` 换实现了？"
        "那这条判据在断言一件它已经看不见的事")
    bar_buttons = [b for b in all_bar if b.isVisibleTo(page.action_bar)]
    assert not bar_buttons, (
        f"底栏又长出按钮了：{[b.text() for b in bar_buttons]}\n"
        "⭐ 这一页没有该由底栏承担的动作（同 magnifier / utility）。")

    from core.presets.preset_center import export_bundle

    page._current_bundle = export_bundle(["hud_rules"])
    page.mark_dirty()
    qapp.processEvents()
    assert page.is_dirty() and page.apply_btn.isEnabled()

    box = page.cb_viewmodel if not page.cb_viewmodel.isChecked() else page.cb_magnifier
    box.setChecked(not box.isChecked())
    qapp.processEvents()
    assert not page.is_dirty(), (
        "改了勾选，那份读进来的包已经被 `_render_preview` 覆盖掉了，"
        "而页面还说自己有一份待应用的包。")
    assert not page.apply_btn.isEnabled(), (
        "「应用读入的预设包」还亮着，而读进来的那份已经没了 —— "
        "按下去应用的是你自己的当前配置。")


def test_each_kind_has_exactly_one_name_on_screen(page):
    """⭐ 同一类东西在同一屏上不许有两个名字。

    实测：勾选框上写「HUD 规则」，而 `_TYPE_CHECKBOX_SPEC` 的显示名是「HUD」，
    于是预览摘要、我的预设那句话、状态卡 tooltip 全叫它「HUD」——
    改完复跑有一发逐字把这两处并排抄出来当矛盾报。
    """
    for attr, _tid, label in page._TYPE_CHECKBOX_SPEC:
        box_text = getattr(page, attr).text().strip()
        assert box_text == label, (
            f"勾选框上写「{box_text}」，而别处叫它「{label}」——同一类东西两个名字。")


def test_that_half_list_judge_is_not_vacuous(page):
    """⭐ 空转守卫：上一条的分母是「屏幕上枚举类别的句子」——

    要是哪天这一页一句都不枚举了，它就变成恒真。这里造一句假话喂给同一套逻辑，
    确认它认得出来。
    """
    labels = [lb for _a, _t, lb in page._TYPE_CHECKBOX_SPEC]
    fake = f"支持 {labels[0]} / {labels[1]} / {labels[2]} 三域预设。"
    named = {lb for lb in labels if lb in fake}
    assert 2 <= len(named) < len(labels), (
        f"造出来的这句假话只点名了 {named} —— 那条判据的识别逻辑已经失效了")


def test_the_first_paint_message_is_the_same_kind_of_sentence_as_later_ones(page, qapp):
    """⭐ 底栏那句话不许是「构造时写死一句、之后被冲掉再也回不来」的一次性文案。

    原来的写法是 `set_message("支持 … 三域预设。")` 写死在 `_init_ui` 里，
    而 `_refresh_dirty_ui` 一跑就换成别的 —— **那句话只在首屏活着**，
    也就是**只有每个人的第一眼看得到它，而它是假的**。
    ⇒ 现在要求：首屏那句话必须由同一个出口产生（刷新一次，内容不变）。
    """
    first = page.action_bar.message_label.text()
    page._refresh_dirty_ui()
    qapp.processEvents()
    assert page.action_bar.message_label.text() == first, (
        f"首屏写的是「{first}」，刷新一次就变成"
        f"「{page.action_bar.message_label.text()}」——\n"
        "⭐ 那句首屏文案没有第二个人负责，它不会跟着状态走，也没人会去核对它。")


# --------------------------------------------------------------------------
# 折线：新手要的那条路，得在第一屏上
# --------------------------------------------------------------------------

def test_the_only_red_button_is_not_sitting_on_an_empty_shelf(page, qapp):
    """⭐ 全页唯一那颗红按钮「删除该图预设」，在一条绑定都没有时不许是亮的。

    ⚠⚠ **同一页上同一件事，两张卡原来给了相反的处理**：
    「我的预设」一条都没有时会把「删除」禁掉（`refresh_my_presets`，UP-022），
    而「按地图自动切换」那颗红的照样亮着 —— 坐在一张逐字写着
    「尚无地图绑定」的卡上。批 29 RN-447（红「删除」全长在空槽位上）的又一个实例。

    ⚠ 判别到**当前这一张图**：`_on_map_rule_delete` 删的是下拉框里那张图的绑定，
      别的图有绑定并不让这颗按钮有事可做。

    ⚠⚠ **第一版直接 `assert not list_rules()`，当场红在 `['de_ancient']` 上。**
      那条绑定不是产品写的，是**同一场 pytest 里另一支判据**
      （`test_map_preset_rules.py`）写进 `config.map_preset_rules` 之后没收拾。
      ⭐⭐ 批 37 RN-473 隔了一批换了个器官又来一次：上次是固定沙箱目录里
        攒着**产品自己**写的东西，这次是同一个 config 单例里攒着
        **另一支判据**写的东西 —— **共享的可写状态会攒，而攒的东西
        看起来和"这台机器本来就是这样"一模一样。**
      ⇒ 不去量那个飘的值，去量**决定那个值的规则**：两臂各自钉一遍。
    """
    from config import config

    original = getattr(config, "map_preset_rules", None)
    current = str(page.map_combo.currentText()).strip().lower()
    try:
        config.map_preset_rules = {}
        page._refresh_map_rules_label()
        qapp.processEvents()
        assert not page.map_delete_btn.isEnabled(), (
            "一条地图绑定都没有，而那颗红色的「删除该图预设」还是亮的。")
        assert page.map_delete_btn.toolTip(), (
            "禁用了却没说为什么 —— 批 36 那条（tooltip 空串）在这一页的实例。")

        # 阳性对照：这张图真的绑过之后，它必须能点 ——
        # ⭐ 没有这一臂，「一律禁用」也能拿到绿。
        config.map_preset_rules = {current: {"bundle": {}, "saved_at": 0}}
        page._refresh_map_rules_label()
        qapp.processEvents()
        assert page.map_delete_btn.isEnabled(), (
            f"「{current}」已经绑过预设了，而那颗删除按钮点不动。")

        # 反向对照：绑的是**别的图**时，它照样不该亮。
        config.map_preset_rules = {"de_somewhere_else": {"bundle": {}, "saved_at": 0}}
        page._refresh_map_rules_label()
        qapp.processEvents()
        assert not page.map_delete_btn.isEnabled(), (
            "绑的是别的图，而这颗按钮删的是当前这张 —— 它不该是亮的。")
    finally:
        config.map_preset_rules = original if isinstance(original, dict) else {}
        page._refresh_map_rules_label()


def test_the_disabled_buttons_all_say_why(page, qapp):
    """⭐ 本批新禁用的两颗，tooltip 都得说清「为什么现在不能点」。

    批 23（RN-150）问的是「看不看得出它禁用了」，批 36 问的是「知不知道为什么」
    —— **是两个问题**，而这一批一次造出了两颗新的禁用按钮。
    """
    page.clear_dirty()
    qapp.processEvents()
    for name in ("apply_btn", "map_delete_btn"):
        btn = getattr(page, name)
        assert not btn.isEnabled(), f"{name} 在默认状态下居然是可点的"
        assert len(btn.toolTip()) >= 10, (
            f"{name} 禁用着，tooltip 是 {btn.toolTip()!r} —— 没说为什么。")


def test_the_empty_my_presets_hint_names_what_it_would_save(page, qapp):
    """⭐⭐ 这条钉的是**我自己这一批造出来的一个缺陷的修法**。

    重排把「我的预设」提到了工作台之前，于是它那句
    「先在**上面**勾选要包含的类别」当场变成假话（勾选框跑到了下面）。
    ⇒ 照 RN-401 的规矩：不指方向，点名控件；
      而更好的一步是**把答案直接说出来**，让人不必跑一趟。

    ⚠ 说出来就要跟着变：勾选一改，这句话必须重算，
      否则它会**具体而肯定地说错**（批 30 那条）。
    """
    page.my_preset_combo.setCurrentIndex(-1)
    qapp.processEvents()
    text = page.my_preset_hint_label.text()
    labels = [lb for attr, _t, lb in page._TYPE_CHECKBOX_SPEC
              if getattr(page, attr).isChecked()]
    assert labels, "默认一类都没勾？那这条判据的样本不对"
    assert all(lb in text for lb in labels), (
        f"空态那句话是「{text}」，而现在勾中的是 {labels} —— 没把它们说全。")
    assert "上面" not in text and "下面" not in text, (
        f"空态那句话又拿方位指路了：「{text}」（RN-401）")

    before = text
    box = page.cb_viewmodel if not page.cb_viewmodel.isChecked() else page.cb_magnifier
    box.setChecked(not box.isChecked())
    qapp.processEvents()
    assert page.my_preset_hint_label.text() != before, (
        "勾选变了，而那句「会把这 N 类存成一套：…」一个字都没变 —— "
        "它现在是一句具体而肯定的假话。")


@pytest.fixture(scope="module")
def real_window(qapp):
    """⚠⚠ **折线只能在真窗里量。**

    第一版拿一个独立的 `PresetCenterPage().resize(1280, 750)` 去量，
    当场给出「完整档露出 71%，通过」——而**真窗里是 0%**。实测两边差多少：

        独立页 1280×750 : 视口 1268×690 · 内容高 1372 · 一键应用 top=666
        真窗   1280×800 : 视口 1074×673 · 内容高 1851 · 一键应用 top=1058

    宽 194px、内容高差 479px。侧边栏、顶栏、底栏都不在独立页里，
    而它们**正是把视口挤成 673 的那几样东西**。
    ⭐⭐ 批 26 那条换了个器官又来一次：**判据跑在一个用户从没见过的容器里**
      —— 那次是没有中文字体的进程，这次是没有外壳的页面。
    """
    import os

    os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
    os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")
    from PySide6.QtCore import Qt

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
        neutral.apply(config, list(win._page_names.keys()))
        # ⚠ 专家页：普通模式下 `show_page` 会静默 return，必须走 `goto`（force）。
        _ui_mode.goto(win, "preset_center")
        for _ in range(3):
            qapp.processEvents()
        yield win
    finally:
        win.close()
        qapp.processEvents()


def test_the_page_header_is_still_the_first_thing_on_the_page(qapp, real_window):
    """⚠⚠ **这条是被我自己的第一版重排逼出来的。**

    那一版 `insertWidget(index, card)` 从 0 开始插，六张卡占住 0~5，
    把页头一路推到整页**最下面**（实测页头 top=1818，落在折线以下）。
    而那时「一键应用露不露脸」那条判据 —— 本批的主判据 —— **是绿的**。

    ⭐⭐ 批 32 定的规矩是「重排的判据只许钉对象、不许钉数量」。
      它的背面这次才付出代价：**只钉一个对象的判据，看不见我把别的东西挤到哪儿去了。**
    ⇒ 重排类改动至少要有两条：一条钉「该上来的上来了」，
      一条钉「原来在上面的没被挤下去」。
    """
    from PySide6.QtWidgets import QScrollArea

    page = real_window.pages["preset_center"]
    scroll = page.findChild(QScrollArea)
    vp = scroll.viewport()
    lead = page.page_lead_label
    top = lead.mapTo(vp, lead.rect().topLeft()).y()
    assert 0 <= top < 200, (
        f"页头那句话跑到了 y={top}（视口高 {vp.height()}，内容高 {scroll.widget().height()}）。\n"
        "⭐ 重排卡片时把非卡片的东西一起挪了。")


@pytest.mark.parametrize("size,tag", [((1280, 800), "完整档"), ((860, 640), "紧凑档")])
def test_the_one_click_path_is_above_the_fold(qapp, real_window, size, tag):
    """⭐ 改前实测（真窗）：内容高 1851 / 视口 673 ⇒ **64% 的页面在折线以下**，
    而「内置精选 · 一键应用」在 y=1058（露出 **0%**）。

    外审改前 12 发（窗口档）**6/6 说「找不到现成可一键套用的配置」**，
    而同一页的整页无折线图上 **3/6 直接指向「三套开箱即用的体验包」** ——
    ⭐⭐ **答案在页面上，只是不在屏幕上。**

    ⚠ 只钉**对象**，不钉「露出 0% 的控件有几个」（批 32：那种数会把
      「把对的东西搬上来」判成退步）。
    """
    from PySide6.QtWidgets import QScrollArea

    win = real_window
    win.setMinimumSize(*size)
    win.resize(*size)
    for _ in range(3):
        qapp.processEvents()
    page = win.pages["preset_center"]
    scroll = page.findChild(QScrollArea)
    vp = scroll.viewport()
    btn = page.starter_apply_btn
    assert btn.isVisibleTo(page), "「一键应用」不见了"
    # ⚠ 这道守卫原来写的是 `vp.height() <= 700`，而**撤掉底栏那两颗按钮之后
    #   视口自己长到了 714**（`PageActionBar` 少了按钮就矮一截 —— 同批 28：
    #   RN-196 的纵向债有一大半是被一条跟布局无关的改动清掉的）。
    # ⭐ 拿一个会被自己的改动推着走的数当守卫，它迟早会红在一件好事上。
    #   ⇒ 换成问那件它真正想确认的事：**这一页是不是长在真窗里**。
    assert page.window() is win, (
        f"{tag}：量的这一页不在 MainWindow 里 —— 那就不是用户看到的那一屏"
        "（裸页面的视口比真窗宽 194px、内容矮 479px）")
    top = btn.mapTo(vp, btn.rect().topLeft()).y()
    shown = max(0, min(top + btn.height(), vp.height()) - max(top, 0))
    pct = 100.0 * shown / max(1, btn.height())
    assert pct >= 100.0, (
        f"{tag}：内置精选的「一键应用」只露出 {pct:.0f}%"
        f"（top={top}，视口 {vp.width()}x{vp.height()}，内容高 {scroll.widget().height()}）。\n"
        "⭐ 这是这一页上唯一一条不用碰文件、不用先有预设就能换整套配置的路，"
        "而它是新手唯一想要的那条。")
