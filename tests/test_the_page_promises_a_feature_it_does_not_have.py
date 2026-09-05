# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""voice_output：页头承诺的三件事，第一件在产品里**不存在**（RN-451 / RN-184）。

## 一、那句话

页头逐字写着：

    三件事：**把文字转成语音说进游戏**、用快捷键放音板、把击杀音效转给队友听。
    都要先装好虚拟声卡。

帮助面板逐字写着：

    • **语音输出** — 输入文字后按快捷键即可将语音送进游戏语音

而实测：

| 查的东西 | 结果 |
|---|---|
| 这一页的可见文本输入控件（`QLineEdit`/`QTextEdit`/`QPlainTextEdit`）| **0 个** |
| 全仓 TTS 引擎导入（AST 扫 `pyttsx/gtts/edge_tts/sapi/…`）| **0 处**（只有两处 `comtypes`，一处做音量闪避、一处做贴屏浏览器）|
| 全仓函数名像 `speak/synthesize/tts/text_to` 的产品代码 | **0 个**（命中的全是判据文件名）|

⇒ **用户照着这句话去找一个输入框，而这一页没有输入框，整个软件也没有这个功能。**
这是 RN-410（「导出的是 .json」而实际写 `.xchr`）那一族最重的一个实例：
那次是**说错了一个扩展名**，这次是**承诺了一个不存在的功能**。

## ⭐⭐⭐ 二、它是怎么来的 —— 一次「把文案写具体」的改动，把真话改成了假话

    e7f5a31  2026-08-16  fix(ui): UI 视觉巡检 R1 —— 修 7 条渲染缺陷 + 2 类文案缺陷
    - description="这里统一管理语音播放、音板快捷键和音效转发，尽量把高频控制收在首屏。"
    + description="三件事：把文字转成语音说进游戏、用快捷键放音板、把击杀音效转给队友听。…"

旧文案说的是**「语音播放」** —— 含糊，但**是真的**。
新文案把它写具体成了**「把文字转成语音」** —— 具体，而且**是假的**。

而这个说法不是凭空来的：**帮助面板里那句话从 2026-04-19 的 2.0 重构前基线就在**，
中间还经历过 RN-001 那一轮（删掉 237 行**从没被读到过的**帮助文案）——
这一段活了下来，然后在四个月后被当成真源抄进了页头。

> ⭐⭐⭐ **一份没人读的文档不会被证伪，但它会被当成真源抄走。**

## 三、判据怎么写

**分母自己算**：扫全站每一页的可见文案 + 它的帮助面板文案，
凡是出现「要用户键入内容」的说法（`输入文字 / 文字转成语音 / 打字 / 键入 / …`），
那一页就必须有**可见的文本输入控件**。

实测分母：**28 页里只有 `voice_output` 一页命中**，而它 0 个输入框。
⚠ 词表只收「输入**文字**」这一族，不收「输入框 / 输入设备」这种名词 ——
`voice_output` 的「输入设备与配置」说的是麦克风，那是真话。

## 四、RN-184：这一页最显眼的按钮，点下去屏幕上什么都不会发生

槽位列表是内层滚动（视口 314 / 内容 428，这是**对的** —— 槽位数由用户决定，
初始 5、上限 50，RN-177 那条判据按 objectName 放行它）。

但实测：

    加之前：5 个槽位，滚动条 value=0 max=114
    点「添加槽位」
    加之后：6 个槽位，滚动条 value=0 max=200
    新行在内容坐标 y=434，而可视范围只到 314  ⇒ **新行露出 0%**

⭐⭐ 而「添加槽位」正是底栏那颗紫色主按钮（批 29 实测：「这一屏最扎眼的是什么」
18/24 答它）。**全页最响的那颗按钮，点下去在屏幕上不产生任何可见变化。**
⭐ 这是批 28 那条的另一面：那次是「按钮在第一屏，它作用的对象在第三屏」，
这次是「按钮在第一屏，**它造出来的东西落在视口外**」。

⚠ 立案（RN-184）说的是「最后一个槽位露不全（只露出 73%）」——
实测是**第 4 行露 68%、第 5 行露 0%**。⭐ 立案的**方向**对，**数**不对，
而真正伤人的那一半（新加的行看不见）立案里根本没提。
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from PySide6.QtWidgets import (QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QScrollArea, QTextEdit)

# ⚠ 主窗夹具用共享那一份，不抄第二份（RN-002 那 9 份名单的形态）。
from tests.test_master_switch_effect_is_honest import (  # noqa: E402
    main_window as _shared_main_window,
)
from _denominator import must_scan

main_window = _shared_main_window

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = "voice_output"

#: 「这句话在要求用户键入内容」的说法。
#: ⚠ 不收「输入框 / 输入设备 / 输入源」这类名词 —— 那说的是设备，不是动作。
TYPING_PROMISES = ("输入文字", "文字转成语音", "文字转语音", "打字", "键入",
                   "输入内容", "填写文字")

#: 阳性样例：每个词至少要能命中一句。⭐ 一张从没命中过的词表和一张写错的词表长得一样。
SPECIMENS = ("输入文字后按快捷键播放", "把文字转成语音说进游戏", "支持文字转语音",
             "在这里打字", "键入一段话", "输入内容后回车", "请填写文字说明")


def _open_page(main_window, qapp, page_id=PAGE):
    main_window.ensure_page_loaded(page_id)
    main_window.show_page(page_id, animated=False, force=True)
    for _ in range(4):
        qapp.processEvents()
    page = main_window.pages.get(page_id)
    assert page is not None, f"打不开 {page_id} —— 判据在空转"
    return page


def _visible_text(page):
    parts = [lb.text() for lb in page.findChildren(QLabel) if lb.isVisibleTo(page)]
    parts += [b.text() for b in page.findChildren(QPushButton) if b.isVisibleTo(page)]
    return "\n".join(parts)


def _text_boxes(page):
    return [e for cls in (QLineEdit, QTextEdit, QPlainTextEdit)
            for e in page.findChildren(cls) if e.isVisibleTo(page)]


#: 否定词：一句**澄清「我们没有这个功能」**的话不算承诺。
#: ⚠ 这一格是**提前**加的，不是被咬出来的 —— 批 29 刚踩过一次同形状的坑：
#:   那次的词表把「先确认 VB-Cable **是否**就绪」这句提问也报成了假话。
#: ⭐ **一条禁止提某个词的判据，会连「说明我们没有它」也一起禁掉** ——
#:   而那句澄清恰恰是这条缺陷修好之后最可能被写下来的话。
_DENIALS = ("不是", "没有", "不支持", "无法", "并非", "暂不")


def _hits(text):
    text = text or ""
    out = set()
    for w in TYPING_PROMISES:
        idx = text.find(w)
        while idx >= 0:
            near = text[max(0, idx - 6):idx]
            if not any(d in near for d in _DENIALS):
                out.add(w)
                break
            idx = text.find(w, idx + 1)
    return sorted(out)


# ============================================ 一、词表自己的阳性对照 / 空转守卫


def test_every_typing_word_can_actually_match_something():
    """⭐ 一张从来没命中过任何东西的词表，和一张写错了的词表，长得一模一样。"""
    assert TYPING_PROMISES, "词表空了 —— 下面那条现在什么都不查"
    for word in TYPING_PROMISES:
        assert any(word in s for s in SPECIMENS), (
            f"词表里的「{word}」在阳性样例里一次都没命中 —— "
            "要么这个词写错了，要么忘了给它配样例")
    for s in SPECIMENS:
        assert _hits(s), f"样例「{s}」没被任何词命中 —— 样例和词表已经对不上了"


# ==================================== 二、说了「要输入文字」，就必须真有输入框


def test_no_page_asks_for_typing_it_cannot_accept(main_window, qapp):
    """全站：页面文案里说要用户输入文字，那一页就必须有可见的文本输入控件。

    ⭐ 分母自己算 —— 不点名 `voice_output`。哪天别的页也写了这种话，它一样会红。
    """
    scanned = 0
    offenders = []
    for pid in list(main_window._page_names):
        try:
            page = _open_page(main_window, qapp, pid)
        except AssertionError:
            continue          # 构造即起设备的页，本判据不去碰
        scanned += 1
        hits = _hits(_visible_text(page))
        if hits and not _text_boxes(page):
            offenders.append((pid, hits))

    assert scanned >= 20, (
        f"只扫到 {scanned} 页 —— 分母太小，这条判据大概率没跑起来")
    assert not offenders, (
        "这几页在要求用户输入文字，而它们一个输入框都没有：\n  "
        + "\n  ".join(f"{p}：命中 {h}" for p, h in offenders)
        + "\n⭐ 用户会照着这句话去找一个不存在的东西 —— 同 RN-410"
          "（页面说「导出的是 .json」而实际写 .xchr）。")


def test_the_help_panel_does_not_promise_it_either(main_window, qapp):
    """⭐⭐ 帮助面板也要查 —— **那句假话就是从这儿抄进页头的**。

    帮助面板的文案从 2026-04-19 的重构前基线就在，中间还活过了 RN-001
    那一轮「删掉 237 行从没被读到过的帮助文案」。它没被读，所以也没被证伪，
    然后在四个月后被当成真源抄进了页头。
    ⭐⭐⭐ **一份没人读的文档不会被证伪，但它会被当成真源抄走。**
    """
    from ui_help_panel import PAGE_HELP_TEXTS

    assert PAGE_HELP_TEXTS, "帮助文案表空了 —— 判据在空转"
    page = _open_page(main_window, qapp)
    boxes = _text_boxes(page)
    hits = _hits(PAGE_HELP_TEXTS.get(PAGE, ""))
    assert not (hits and not boxes), (
        f"{PAGE} 的帮助面板在要求用户输入文字（命中 {hits}），"
        f"而这一页有 {len(boxes)} 个输入框。\n"
        "⚠ 页头改了而帮助面板没改，等于那句假话还在原地 —— "
        "而它正是页头那句话的来源。")


def test_no_text_to_speech_engine_is_pretended(main_window, qapp):
    """⭐ 把「有没有这个功能」这件事钉在**产品代码**上，不只钉在文案上。

    ⚠ 走 AST 扫导入，不用 `grep | head`（CLAUDE.md：查「有没有 X」一律走 AST，
    截断会给出「没有」，而「没有」往往正是断言的全部内容）。

    这一条的方向是**反的**：它不要求「必须有 TTS」，它要求
    **「没有 TTS」和「文案不提 TTS」这两件事保持一致**。
    哪天真做了 TTS，这条会提醒把文案改回来。
    """
    engines = must_scan(
        ("pyttsx", "gtts", "edge_tts", "espeak", "sapi", "speechsdk"),
        "要扫的 TTS 引擎名单", least=6)
    found = []
    scanned = must_scan(
        [p for p in sorted((ROOT).rglob("*.py"))
         if not any(part in p.parts for part in
                    (".venv", "build", "dist", "__pycache__", ".build", ".claude", "tests"))],
        "产品代码 *.py（排除 venv/build/tests 等）", least=50)
    for path in scanned:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            for m in mods:
                if any(e in m.lower() for e in engines):
                    found.append((path.name, m))

    page = _open_page(main_window, qapp)
    # ⭐ 第三个分母：这一页得真的有可见文案。页面建不出来时
    #   「文案没有吹牛」会因为**一个字都没有**而变成真的。
    visible = _visible_text(page)
    must_scan(visible.split(), f"{PAGE} 页上的可见文案（按空白切出来的词）", least=5)
    claims = _hits(visible)
    if found:
        pytest.skip(f"仓里出现了 TTS 引擎（{found[:3]}）—— "
                    "如果功能真做了，请把页头那句话加回来，并删掉本条 skip")
    assert not claims, (
        f"仓里一个 TTS 引擎都没有，而 {PAGE} 的文案还在说 {claims}。\n"
        "⭐⭐⭐ 这句话是 2026-08-16 那次「修文案缺陷」加上去的："
        "旧文案「语音播放」含糊但**是真的**，新文案「把文字转成语音」"
        "具体而且**是假的**。")


# ==================================== 三、RN-184：加完的那一行必须看得见


def _slot_list(page):
    hits = [s for s in page.findChildren(QScrollArea)
            if s.objectName() == "voiceSlotList"]
    assert len(hits) == 1, f"找到 {len(hits)} 个 voiceSlotList —— 判据在空转"
    return hits[0]


def test_a_newly_added_slot_is_actually_on_screen(main_window, qapp):
    """点「添加槽位」之后，新那一行必须落在视口里。

    实测（批 30，改前）：加完 6 个槽位，新行在内容坐标 y=434，
    而可视范围只到 314 ⇒ **露出 0%**，滚动条纹丝不动停在 0。
    ⭐⭐ 而「添加槽位」正是底栏那颗紫色主按钮 ——
    **全页最响的那颗按钮，点下去在屏幕上不产生任何可见变化。**
    """
    page = _open_page(main_window, qapp)
    sa = _slot_list(page)
    before = set(page.soundboard_slots)
    assert len(before) >= 3, "槽位太少，这条判据量不出滚动"
    try:
        page._add_slot()
        for _ in range(5):
            qapp.processEvents()
        new_ids = set(page.soundboard_slots) - before
        assert len(new_ids) == 1, f"加了一次却多出 {len(new_ids)} 个槽位"
        frame = page.soundboard_slots[next(iter(new_ids))]["frame"]
        inner = sa.widget()
        top = frame.mapTo(inner, frame.rect().topLeft()).y()
        bottom = top + frame.height()
        view_top = sa.verticalScrollBar().value()
        view_bottom = view_top + sa.viewport().height()
        shown = max(0, min(bottom, view_bottom) - max(top, view_top))
        assert shown > 0, (
            f"新加的槽位一个像素都没露出来：它在内容坐标 y {top}~{bottom}，"
            f"而可视范围是 {view_top}~{view_bottom}。\n"
            "⭐ 这一页最显眼的那颗按钮，点下去屏幕上什么都不会发生。")
        assert shown >= frame.height() // 2, (
            f"新加的槽位只露出 {shown}/{frame.height()}px —— 露一半以上才算「看得见」")
    finally:
        for slot_id in set(page.soundboard_slots) - before:
            slot = page.soundboard_slots.pop(slot_id)
            slot["frame"].deleteLater()
            page._slot_delete_buttons.pop(slot_id, None)
            page.current_slot_count = len(page.soundboard_slots)
        # ⚠⚠ **滚动位置也要还原。** `main_window` 是 module 级夹具，
        #   这一条测完之后页面还活着 —— 下一条判据（「开页不许停在列表底部」）
        #   当场判红 222，而那 222 是**我自己刚滚出来的**，不是产品的行为。
        #   ⭐ 同 RN-141 那条：**一个共享的、跨用例累积的前置状态，会把
        #     「我这一条判据改了什么」变成「别人那一条判据看到了什么」。**
        sa.verticalScrollBar().setValue(0)
        qapp.processEvents()


def test_the_slot_list_still_scrolls(main_window, qapp):
    """反向守卫：别用「把视口撑到装得下所有槽位」来糊弄上一条。

    ⭐ 槽位上限是 50 —— 撑到装得下 50 行等于把内层滚动废掉，
    而 RN-177 那条判据正是**特意放行**这个内层滚动的
    （槽位数由用户决定，那是一份列表控件，不是被高度上限钉死的固定内容）。
    """
    page = _open_page(main_window, qapp)
    sa = _slot_list(page)
    inner = sa.widget()
    assert inner is not None
    assert sa.verticalScrollBar().maximum() > 0, (
        "槽位列表已经不滚动了 —— 上一条判据可以靠「把视口撑大」全绿，"
        "而那会让 50 个槽位把整页顶穿")


def test_a_denial_is_not_read_as_a_promise():
    """否定词守卫的阳性对照：一句澄清必须**不**被当成承诺。

    ⭐ 而一句真正的承诺仍然要被逮住 —— 两头都验，否则这个守卫可能是
    「把所有句子都放行」的那一种（同批 25 那张过宽词表的镜像风险）。
    """
    assert not _hits("这里不是文字转语音，音板放的是你自己的音频文件"), (
        "一句澄清被当成了承诺 —— 否定词守卫没生效")
    assert not _hits("本页没有输入文字的地方"), "同上"
    assert _hits("输入文字后按快捷键播放"), (
        "真正的承诺没被逮住 —— 否定词守卫放得太宽，把整条判据废掉了")
    assert _hits("把文字转成语音说进游戏"), "同上"


def test_opening_the_page_does_not_land_at_the_bottom_of_the_list(main_window, qapp):
    """反向守卫：**建页时铺初始槽位不许把列表滚到底。**

    ⭐ 少了这一条，上一条判据可以靠「每加一个槽位都滚到底」全绿 ——
    包括建页时那 5 个初始槽位。那样用户一打开这一页就停在列表末尾，
    第一个槽位反而看不见（`_add_slot(auto_init=True)` 那一路必须不滚）。
    """
    page = _open_page(main_window, qapp)
    sa = _slot_list(page)
    assert sa.verticalScrollBar().value() == 0, (
        f"刚打开这一页，槽位列表就停在 {sa.verticalScrollBar().value()} 而不是顶部 —— "
        "建页铺初始槽位那一路（auto_init）跟着滚了")


# ============================================================ 批 44：RN-450
#
# ⭐⭐⭐ **唯一那颗紫的，把注意力从真正的第一步上拿走了**（RN-139「两颗紫的
# 等于零颗」的反面）。批 29 的行为题：「你会先点哪个」改前 **10/24 答「安装驱动」、
# 8/24 答「添加槽位」**；批 29 只撤了红、加了量程说明，同题同图就变成 **19/24**。
#
# ⚠⚠ 批 44 开工先复量了一遍立案时的说法，**其中一半不成立**：
#   RN-450 原文说「核心前置阻断项被埋掉」——而真窗实测（四档：完整/紧凑 ×
#   音乐条 auto/on）「安装驱动」与「✗ VB-Cable未安装」**四档全部露出 100%**
#   （top=322 / 276，视口最小 479）。它们就在第一屏正中间。
#   ⇒ 真正的问题不是**位置**，是**分量**：驱动那两颗是描边次级，
#     而唯一一颗紫色实心的说的是「添加槽位」—— 一个在驱动没装时做了也白做的动作。
#
# ⚠ 而「页签栏在第一屏之外」那一半**在默认完整档已经不成立**
#   （实测露出 100%；批 30 记的是 9%，批 31 撤掉重复按钮之后它自己浮上来了，没人复量）。
#   只有紧凑档（0%）与音乐条开着（13%）仍然成立 ⇒ 那属于 RN-496 那一族（容器高度），
#   归跨页 C6，不在本批。
#   ⭐ **一条立案会随产品一起改变，而它不会自己改口。**

def _purple_buttons(page):
    from PySide6.QtWidgets import QPushButton

    return [b for b in page.findChildren(QPushButton)
            if b.objectName() == "primaryButton" and b.isVisibleTo(page)]


def test_exactly_one_purple_button_on_this_page(main_window, qapp):
    """① 一屏只许一颗紫的（RN-139 的全站口径，在这一页上钉住）。

    ⚠ 含底栏那颗 —— 它和卡内那些在同一屏上，玩家不分「这颗属于哪个容器」。
    """
    page = _open_page(main_window, qapp)
    purple = _purple_buttons(page)
    assert len(purple) == 1, (
        f"这一页上有 {len(purple)} 颗主按钮："
        f"{[b.text().strip() for b in purple]}\n"
        "⭐ 两颗紫的等于零颗（RN-139）；而零颗紫的也是零颗。"
    )


# ⛔⛔ 这里原本有 `_fill()` 与 `test_the_purple_button_is_whatever_the_first_step_is`
#   ——「驱动没装时，唯一那颗紫的必须是『安装驱动』」。**2026-09-04 批 44 全部撤除，
#   连同产品那边 `_sync_first_step_emphasis()` 那 25 行一起。**
#
# ⭐⭐⭐ 撤除的理由是**实测**，不是口味：带阳性写法的行为题「你会先点哪一个东西」
#   跑了 **48 发**（改前/改后 × 总开关开/关，各 12 发）——
#
#       48/48 全部答「**安装驱动**」，改前改后**一模一样**。
#       引用理由时 **48/48 抄的是文案**（「✗ VB-Cable未安装」/「安装后才能把音频
#       送进游戏语音」/ 页头「都要先装好虚拟声卡」），**只有 3 发提到颜色或高亮**。
#
#   ⇒ 这一页的引导是**那句话**在承担，不是那颗紫按钮。
#     我改的是一个**没有在承重**的东西，而且**没有产生任何可观测的行为差异**。
#     ⛔ 铁约束 2「不引入新复杂度」：零收益的改动不该留在产品里。
#
# ⭐⭐ 而 RN-450 立案时的数是「10/24 答安装驱动、8/24 答添加槽位」——
#   它**已经被批 30 的修法顺手解决了**：RN-451 把页头那句假话换成
#   「两件事：…**都要先装好虚拟声卡**」，而那正是现在 48/48 引用的那句话。
#   ⭐⭐⭐ **一条立案会随产品一起改变，而它不会自己改口**（批 43 同一形态第二次）。
#
# ⇒ 留下的是 `test_exactly_one_purple_button_on_this_page`（RN-139 的口径，
#   在我动手之前就是绿的），外加下面那条把**真正承重的那句话**钉住的判据。


def test_the_page_says_both_halves_of_the_prerequisite(main_window, qapp):
    """③ **RN-450 的真正结论**：驱动没装时，屏幕上必须同时说清两件事 ——
    **「它没装」** 和 **「不装就用不了」**。

    ⭐ 这条不是我想出来的，是行为题**逐字抄回来的**：48 发全部指向「安装驱动」，
    而 48/48 给的理由都是这两句话（只有 3 发提到颜色）。
    ⭐⭐ **一个结论所依赖的事实，要有判据看着**（批 8）——
      在此之前，这一页的引导全靠这两句话，而没有任何东西盯着它们。

    ⚠ 判据只要求「说到了这两件事」，不锁具体措辞：锁措辞会把
      「把这句话写得更好」变成一次判据失败（批 24 那条）。
    """
    page = _open_page(main_window, qapp)
    if page._driver_ready():
        import pytest as _pytest

        _pytest.skip("这台机器上 VB-Cable 已就绪 —— 本条问的是「没装」那一支")

    text = must_scan(_visible_text(page).splitlines(), "这一页的可见文案", least=5)
    joined = " ".join(text)

    says_missing = any(k in joined for k in ("未安装", "待安装", "缺少"))
    says_consequence = any(k in joined for k in ("才能", "才可以", "无法", "不能"))
    assert says_missing, (
        "驱动没装，而屏幕上没有一句说它没装。 "
        "⭐ 行为题 48/48 就是靠这句话找到第一步的。")
    assert says_consequence, (
        "屏幕上说了「没装」，却没说**不装会怎样**。 "
        "⭐ 一句只报状态、不报后果的提示，读的人不知道要不要现在处理它。")
