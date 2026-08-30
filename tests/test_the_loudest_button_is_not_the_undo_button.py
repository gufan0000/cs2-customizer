# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""magnifier：全页最响的那颗按钮，做的是离目标最远的那件事（RN-277 / RN-101）。

## 实测

`magnifier` 底栏的 primary 是全页唯一的高亮紫按钮。它的文案跟着状态变：

    已勾选 54/54  →  「全不选武器」      ← **全新用户看到的就是这一版**
    其余          →  「全选武器」

而 54 把武器 `checkbox.setChecked(True)  # 默认启用` —— 所以**每一个第一次
打开这一页的人**，看到的都是那颗写着「全不选武器」的紫按钮。点一下：
54 个复选框全部清空，`save_settings()` 当场落盘，**没有确认、没有撤销**。

⭐ 而它作用的那 54 个复选框在**第二~三屏**（可视区 750px，武器卡从 y≈1050 起）：
   **按钮钉在第一屏，它唯一能改的东西一个都不在第一屏上。**
   —— 批 27 那条「入口不在第一屏上」的背面：这次是**出口**在第一屏上。

## 外审（行为题，12 发，四问四答，全票一致）

    ① 最显眼的按钮写的是什么、点下去会怎样   12/12 「全不选武器」+ 正确预期「清空 54 把」
    ② 你想让这功能用起来，先点哪              12/12 「总开关」
    ③ 有没有按钮会把你设好的东西弄没          12/12 指认它
    ④ 点它是靠近目标还是反方向                **12/12 「反方向」**

⭐⭐ ② 是这组数里最要紧的一条：用户**知道**该点哪儿。
   所以这不是「找不到入口」，是**全页视觉最重的那颗按钮指着反方向**。
⚠ 外审没有说「我会误点它」——它每次都读对了按钮上的字。
   ⭐ **「这颗按钮方向相反」是实测到的；「用户会误点」是推论，不许当成实测写。**

## 修法

底栏不放主按钮（同 crosshair 批 10：`configure_primary("", None, visible=False)`）。
「全选 / 全不选」本来就在武器卡的表头上，**紧贴着那 54 个复选框** ——
在那儿点，用户看得见自己改了什么。

⚠ 这不是删功能。下面第 3、4 组是**反向守卫**：卡内那三颗按钮必须还在、还接原槽。

## 这份判据为什么不只钉 magnifier 一页

破坏性动作占主按钮位是一族（RN-101 点名 12 页）。所以第 2 组扫**全站**：
底栏 primary 只要可见，文案就不许命中破坏性词表。
⭐ 词表自己带阳性对照（第 5 组）—— 一张从来没命中过任何东西的词表，
和一张写错了的词表，报出来是同一句话（RN-433 那条的又一次现身）。
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from PySide6.QtWidgets import QCheckBox, QPushButton

# ⚠ 主窗夹具用共享那一份，不抄第二份（RN-002 那 9 份名单的形态）。
from tests.test_master_switch_effect_is_honest import (  # noqa: E402
    main_window as _shared_main_window,
)

main_window = _shared_main_window

PAGE = "magnifier"
ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 底栏主按钮位**不许**出现的动作。判据比的是按钮上的**文案**，
#: 因为用户读到的就是它 —— 槽函数叫什么名字用户看不见。
#: ⚠ 加词请一起在 `SPECIMENS` 里加一个会命中它的样例，否则这一格是死的。
DESTRUCTIVE_WORDS = (
    "全不选", "全部取消", "取消全部", "清空", "删除", "移除", "重置", "还原默认",
)

#: 阳性对照样例：每个词至少要有一个字符串命中它。
SPECIMENS = (
    "全不选武器", "全部取消勾选", "取消全部选择", "清空列表",
    "删除这一套", "移除槽位", "重置偏移", "还原默认设置",
)


def _open_page(main_window, qapp, page_id=PAGE):
    main_window.ensure_page_loaded(page_id)
    main_window.show_page(page_id, animated=False, force=True)
    for _ in range(3):
        qapp.processEvents()
    page = main_window.pages.get(page_id)
    assert page is not None, f"打不开 {page_id} —— 判据在空转"
    return page


def _visible_buttons(page):
    return [b for b in page.findChildren(QPushButton) if b.isVisibleTo(page)]


def _bar_buttons(page):
    """底栏那三个槽位。返回 {槽位名: 按钮}，页面没有底栏就返回 {}。"""
    bar = getattr(page, "action_bar", None)
    if bar is None:
        return {}
    out = {}
    for attr in ("primary_btn", "secondary_btn", "extra_btn"):
        btn = getattr(bar, attr, None)
        if btn is not None:
            out[attr] = btn
    return out


def _hits(text):
    return [w for w in DESTRUCTIVE_WORDS if w in (text or "")]


# ======================================================== 1. 防空转 / 分母守卫


def test_the_page_really_has_the_things_this_file_talks_about(main_window, qapp):
    """⭐ 先证明这一页上确实有「底栏」「54 个武器复选框」「卡内那三颗按钮」。

    少了这一条，下面每一条都可能因为「压根没找到」而绿。
    """
    page = _open_page(main_window, qapp)
    assert _bar_buttons(page), "magnifier 没有底部操作栏 —— 下面几条全在空转"

    boxes = getattr(page, "weapon_enabled_vars", None)
    assert isinstance(boxes, dict) and len(boxes) >= 40, (
        f"武器复选框只有 {0 if not boxes else len(boxes)} 个 —— "
        "这一族缺陷的分量正来自「一次改掉几十个」，数不对就别下结论")
    assert all(isinstance(b, QCheckBox) for b in boxes.values())

    texts = {b.text().strip() for b in _visible_buttons(page)}
    for need in ("全选", "全不选", "应用"):
        assert need in texts, (
            f"武器卡/偏移卡里找不到「{need}」按钮 —— "
            "反向守卫（第 3、4 组）会因此变成空转")


def test_every_weapon_starts_checked_so_the_worst_label_is_the_default_one(
        main_window, qapp):
    """⭐ 钉住「最坏那一版文案就是全新用户看到的那一版」这个前提。

    这一条不是在要求「必须默认全选」，而是在说：**只要默认是全选**，
    那颗按钮的文案就必然是破坏性的那一支。哪天默认改了，这条会红，
    提醒重新读一遍上面那段推理 —— 而不是让推理悄悄过期。
    """
    page = _open_page(main_window, qapp)
    boxes = page.weapon_enabled_vars
    checked = sum(1 for b in boxes.values() if b.isChecked())
    assert checked == len(boxes), (
        f"武器默认不再是全选（{checked}/{len(boxes)}）——"
        "本文件开头那段「全新用户看到的就是最坏那一版」的推理要重写")


# ======================================== 2. 主刀：底栏主按钮不许是破坏性动作


def test_no_page_puts_a_destructive_action_in_the_loudest_slot(main_window, qapp):
    """全站：底栏 primary 只要可见，文案就不许命中破坏性词表。

    ⭐ 为什么钉 primary 而不钉全部三个槽位：primary 是**全页唯一**的高亮按钮，
    它携带的信息是「这一页要你做的事就是它」。secondary/extra 是并列的次级动作，
    不承担这个语义。
    """
    checked_pages = 0
    offenders = []
    for pid in list(main_window._page_names):
        try:
            page = _open_page(main_window, qapp, pid)
        except AssertionError:
            continue        # 构造即起设备的页，本判据不去碰
        btns = _bar_buttons(page)
        primary = btns.get("primary_btn")
        if primary is None or not primary.isVisibleTo(page):
            continue
        checked_pages += 1
        hit = _hits(primary.text())
        if hit:
            offenders.append((pid, primary.text().strip(), hit))

    assert checked_pages >= 8, (
        f"只有 {checked_pages} 页有可见的底栏主按钮 —— 分母太小，"
        "这条判据大概率没跑起来（正常应在 15 页上下）")
    assert not offenders, (
        "这几页把破坏性动作放在了全页唯一的高亮主按钮位上：\n  "
        + "\n  ".join(f"{p}：「{t}」命中 {h}" for p, t, h in offenders)
        + "\n⭐ 那个位置的含义是「这一页要你做的事」。"
        "破坏性动作该待在它作用的那堆东西旁边，让用户看得见自己改了什么。")


def test_magnifier_leaves_the_loudest_slot_empty(main_window, qapp):
    """magnifier 这一页**没有**主路径动作 ⇒ 主按钮位就该空着。

    （同 crosshair 批 10：`configure_primary("", None, visible=False)`。
    那一轮外审复跑的判词是「一颗灰着的、紫色的、蹲在右下角的按钮，
    形状本身就在说『这里有个保存动作』」——而这一页同样没有保存动作。）
    """
    page = _open_page(main_window, qapp)
    primary = _bar_buttons(page).get("primary_btn")
    assert primary is not None, "找不到底栏主按钮控件 —— 判据在空转"
    assert not primary.isVisibleTo(page), (
        f"magnifier 底栏又摆出主按钮了：「{primary.text().strip()}」\n"
        "这一页的改动全是即时保存（偏移的 X/Y 有它自己那张卡上的「应用」），"
        "底栏没有该由它承担的动作。")


# ================================================ 3. 反向守卫：功能不许被删掉


@pytest.mark.parametrize("text,slot_hint", [
    ("全选", "武器卡表头 —— 它紧贴着那 54 个复选框，在那儿点看得见自己改了什么"),
    ("全不选", "同上；把它从底栏撤走**不等于**把这个动作删掉"),
    ("应用", "偏移卡 —— X/Y 两个输入框旁边，这一页唯一真需要点一下的按钮"),
])
def test_the_action_itself_survives_in_the_card(main_window, qapp, text, slot_hint):
    page = _open_page(main_window, qapp)
    found = [b for b in _visible_buttons(page) if b.text().strip() == text]
    assert found, (
        f"卡片里那颗「{text}」不见了。\n本批只是把它从底栏撤走，"
        f"它应该还在：{slot_hint}")
    for b in found:
        assert b.isEnabled(), f"「{text}」还在，但不可点了"


def test_bulk_toggle_still_changes_every_checkbox(main_window, qapp):
    """行为级反向守卫：卡内那两颗按钮**真的还能一次改掉全部**。

    ⚠ 只看「按钮还在」是不够的 —— 批 10 踩过「只测零件好使，
    证明不了零件装上了」。这里直接点它，然后数复选框。
    """
    page = _open_page(main_window, qapp)
    boxes = page.weapon_enabled_vars
    before = {k: b.isChecked() for k, b in boxes.items()}
    try:
        [b for b in _visible_buttons(page) if b.text().strip() == "全不选"][0].click()
        qapp.processEvents()
        assert not any(b.isChecked() for b in boxes.values()), "「全不选」没能清空"
        [b for b in _visible_buttons(page) if b.text().strip() == "全选"][0].click()
        qapp.processEvents()
        assert all(b.isChecked() for b in boxes.values()), "「全选」没能全勾上"
    finally:
        for k, v in before.items():
            boxes[k].setChecked(v)
        qapp.processEvents()


# ======================================= 4. 底栏那句话必须是真的（RN-410 那族）


def test_the_bar_message_tells_the_truth_about_what_needs_clicking(
        main_window, qapp):
    """底栏说「要点一下应用」，那就必须真有那颗按钮、且真的接着应用偏移。

    ⭐ 批 27 的教训：**一句话是真是假，要拿它自己声称的那件事去比。**
    所以这里不比「文案里有没有『保存』两个字」，比的是：
      · 说了「应用」⇒ 页面上真有一颗可见的「应用」按钮；
      · 说了「就存下 / 自动保存」⇒ 武器复选框真的接在 `save_settings` 上（AST 验）。

    ## ⚠⚠ 这条判据的第一版是**假绿**的（回退验证当场逮住）

    第一版只写了那两个 `if`：**「你说了就必须是真的」，但没有「你必须说」。**
    于是把那句话整个换成 `""`，两个分支一起跳过，判据照样绿 ——
    而回退验证要防的正是这个（断点：「底栏那句话不再说『要不要点什么』」）。
    ⭐⭐ **一条只在「说了」时才检查的判据，挡不住「干脆不说」。**
      条件式判据的分母是它自己的条件；条件不成立时，它的分母是 0。
    ⇒ 先无条件断言**这句话必须回答那个问题**，再去验它说的是不是真的。
    """
    page = _open_page(main_window, qapp)
    bar = page.action_bar
    message = bar.message_label.text()
    assert message.strip(), "底栏一句话都没有 —— 撤掉按钮之后它是唯一的解释了"

    # ① 无条件：它必须回答「我到底要不要点什么」。
    #    ⚠ 这一页 `SAVES_AUTOMATICALLY = False`，共用回执**不替它说存不存**
    #    （批 24 定的分工）⇒ 这句话是唯一还在回答这个问题的东西。
    assert ("存下" in message or "自动保存" in message), (
        "底栏那句话没有说改动存不存 —— 而底栏两颗按钮都撤了，"
        "这一页 `SAVES_AUTOMATICALLY = False` 时共用回执也不替它说。\n"
        f"现在这句是：{message}")
    assert "应用" in message, (
        "底栏那句话没有点出唯一那个例外（偏移的 X / Y 要点「应用」）——"
        "只说「改完就存下了」在这一页是**半句真话**。\n"
        f"现在这句是：{message}")

    # ② 有条件：说了的每一件事都必须是真的。
    if "应用" in message:
        assert [b for b in _visible_buttons(page) if b.text().strip() == "应用"], (
            f"底栏说了「应用」，但这一页上没有可见的「应用」按钮：\n{message}")

    if "存下" in message or "自动保存" in message:
        src = (ROOT / "pages" / "magnifier_page.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        auto = False
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect"):
                continue
            recv = ast.unparse(node.func.value)
            if "stateChanged" not in recv:
                continue
            if node.args and "save_settings" in ast.unparse(node.args[0]):
                auto = True
        assert auto, (
            "底栏承诺了「改完就存下」，但代码里找不到"
            "`checkbox.stateChanged.connect(self.save_settings)` —— "
            "⭐ 那句话就成了 RN-410 那种「页面自己说的和它自己做的对不上」。")


# ============================================== 5. 词表自己的阳性对照 / 空转守卫


def test_every_destructive_word_can_actually_match_something():
    """⭐ 一张从来没命中过任何东西的词表，和一张写错了的词表，长得一模一样。"""
    assert DESTRUCTIVE_WORDS, "词表空了 —— 第 2 组现在什么都不查"
    for word in DESTRUCTIVE_WORDS:
        assert any(word in s for s in SPECIMENS), (
            f"词表里的「{word}」在阳性样例里一次都没命中 —— "
            "要么这个词写错了，要么忘了给它配样例")
    for s in SPECIMENS:
        assert _hits(s), f"样例「{s}」没被任何词命中 —— 样例和词表已经对不上了"


# ============================================ 6. RN-143：别让它们再长回去

#: 被挤到折行的两句话（RN-143 在本页的两处），连同**实测的字数上界**。
#: 上界怎么来的：紧凑档量到「宽 W / 需 N」，按 N/字数 得到每字约 12.4px，
#: 再用可用宽度 W 反推。留 1 字余量。
#:
#: ⭐⭐ **这条判据故意不量像素。** 判据跑在 `QT_QPA_PLATFORM=offscreen` 的进程里，
#:   而那里 `QFontDatabase.families()` 是 **0**（批 26 踩实）——
#:   在没有字体的进程里量文字宽度，量的是一个用户从没见过的版面。
#:   ⇒ 量「别再变长」不需要字体，量「有没有折行」需要。**只做前者。**
#:   后者由 `scripts/squeezed_label_audit.py` 用真实字体守着（本批把
#:   紧凑档 14→11、紧凑+1.25 档 19→16，magnifier 三处全部清零）。
LENGTH_BUDGET = (
    ("联动关着也能先把数值填好。", 16,
     "灵敏度卡里 2×1 跨行的说明位，紧凑档只有 198px；原文 22 字要 322px，折成 6 行"),
    ("主武器和手枪各自指定放大热键，并选长按还是单击切换。", 27,
     "「热键与触发」卡的副标题，紧凑档 335px；原文 27 字要 336px —— **差 1px** 就折行"),
)


@pytest.mark.parametrize("text,limit,why", LENGTH_BUDGET)
def test_these_hints_do_not_grow_back(text, limit, why):
    src = (ROOT / "pages" / "magnifier_page.py").read_text(encoding="utf-8")
    assert text in src, (
        f"在 magnifier_page.py 里找不到「{text}」—— 文案改了就把这条一起改，"
        "别让它静默失效（RN-093：判据的锚点会随产品代码一起腐烂）")
    assert len(text) <= limit, (
        f"「{text}」已经 {len(text)} 字，超过上界 {limit}。\n它必须放得下一行，因为：{why}\n"
        "⭐ 折行不是「放不下」，是「我说我能折行」—— 折行的 QLabel 会把自己的"
        "宽度报小，于是它躲得过一切「有没有溢出 / 有没有截断」的判据。")


def test_the_length_budget_is_not_vacuous():
    """分母守卫：表空了，上面那条参数化判据**一个用例都不跑**，而 pytest 静默通过。"""
    assert len(LENGTH_BUDGET) >= 2, "RN-143 的字数上界表被清空了 —— 上面那条现在什么都不测"
    for text, limit, why in LENGTH_BUDGET:
        assert text and why and limit > 0
        assert limit >= len(text), f"上界 {limit} 比现有文案 {len(text)} 字还小，这条一建就红"


# ================================ 7. RN-196 横向那 29px：那一行必须能换行


def test_the_nudge_row_can_wrap(main_window, qapp):
    """偏移卡的「微调 / 大幅」那 8 颗方向键，必须待在一个能换行的布局里。

    ## 根因（批 28 查实）

    代码里写的是 `btn.setFixedSize(QSize(30, 26))`，而它们**实际渲染成 80×50**：
    `ui_style_applier._style_button` 在页面建完之后无条件抬最小尺寸，
    而 `setFixedSize` 是把 min 和 max 一起设死 —— 只抬 min 不动 max ⇒
    `min > max` ⇒ Qt 取 min。**调用点写的固定尺寸一个像素都不生效。**
    ⇒ 一行 8 颗 ≈ 800px，顶穿整页最小宽度，紧凑档横向溢出 29px。

    ⭐ **一句无效的声明不是无害的。** 它没有被忽略，它被放大了两倍半。

    ## 为什么钉「能不能换行」而不钉像素

    量宽度要真实字体，而判据跑在 `offscreen`（`QFontDatabase.families()==0`，
    批 26 踩实）——在那里量出来的宽度是用户从没见过的版面。
    ⇒ 这里钉**机制**：那一行是 `FlowLayout`。像素由
    `scripts/layout_overflow_audit.py --compact` 用真实字体守着（29px → 0）。

    ## ⚠⚠ 第一版修法自己踩的坑（改完复跑 3/3 全票逮住的）

    第一版是把 8 颗按钮和两个标签**平铺**进 FlowLayout ——
    于是换行点落进了「大幅」那一组的中间：前 3 颗留在上一行，
    第 4 颗 `v` 掉到下一行最左边。外审判词逐字：「按钮组断裂错位」。
    ⭐⭐ **我修掉了「放不下就溢出」，换来了「放不下就断在一组的中间」。**
      ⭐ **能换行的单位应该是「一组」，不是「一颗」。**
    ⇒ 所以这条判据钉的是**两层**：组内是不可拆的横排，组之间才允许换行。
    """
    from widgets.flow_layout import FlowLayout

    page = _open_page(main_window, qapp)
    arrows = getattr(page, "_arrow_buttons", None)
    assert arrows and len(arrows) == 8, (
        f"方向键不是 8 颗（现在 {0 if not arrows else len(arrows)} 颗）—— "
        "判据在空转，或者这一块被重做了，请重读上面那段根因")

    groups = {}
    for b in arrows:
        parent = b.parentWidget()
        assert parent is not None, "方向键没有父控件 —— 判据在空转"
        groups.setdefault(id(parent), []).append(b)

    assert len(groups) == 2, (
        f"方向键分成了 {len(groups)} 组 —— 应该正好两组（微调 / 大幅）。\n"
        "⭐ 每组必须是一个不可拆的小控件，换行才不会断在组的中间。")
    for members in groups.values():
        assert len(members) == 4, f"某一组只有 {len(members)} 颗方向键，不是 4 颗"

    wraps = set()
    for gid, members in groups.items():
        group = members[0].parentWidget()
        assert not isinstance(group.layout(), FlowLayout), (
            "组**内部**用了 FlowLayout —— 那正是第一版的错法："
            "换行点会落进一组的中间，把 4 颗方向键拆散。组内必须是横排。")
        outer = group.parentWidget()
        assert outer is not None, "方向键组没有外层容器 —— 判据在空转"
        wraps.add(id(outer))
        assert isinstance(outer.layout(), FlowLayout), (
            f"方向键组的外层又变回 {type(outer.layout()).__name__} 了。\n"
            "它必须能换行：8 颗按钮实际是 80×50（不是代码里写的 30×26），"
            "一行摆不下就会把整页最小宽度顶穿。")
    assert len(wraps) == 1, "两组方向键不在同一个可换行容器里"


def test_a_destructive_primary_would_actually_be_caught(main_window, qapp):
    """⭐⭐ 阳性对照：把 magnifier 的主按钮**手工**改回破坏性文案并显示出来，
    第 2 组那条判据必须当场逮住它。

    少了这一条，「全站都合规」和「扫描根本没扫到 primary」在结果上一样。
    """
    page = _open_page(main_window, qapp)
    primary = _bar_buttons(page)["primary_btn"]
    old_text, old_visible = primary.text(), primary.isVisible()
    try:
        primary.setText("全不选武器")
        primary.setVisible(True)
        qapp.processEvents()
        assert primary.isVisibleTo(page)
        assert _hits(primary.text()), "词表没能逮住「全不选武器」——它正是这条判据的由来"
    finally:
        primary.setText(old_text)
        primary.setVisible(old_visible)
        qapp.processEvents()
