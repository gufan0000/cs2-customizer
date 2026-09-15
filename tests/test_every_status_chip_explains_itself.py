# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""状态芯片各自说得清自己（RN-232 / RN-541）。

## 两件事

① **每颗芯片都要有它自己的解释。**
   在此之前只有**整条**有一份共享明细，而且它写死给 `idx == 2` 那一颗 ——
   ⭐⭐ **一个按位置寻址的东西，会在别人重排的那一刻指向另一个对象**：
   批 59 重排状态带（RN-532）之后，那份明细就静悄悄换了主人，而没有任何东西会报。
   实测：「GSI」那颗芯片**连 tooltip 都是空的**，屏幕上只有四个字母，别处一个字都没有。

② **顶栏那颗切换按钮要把话写在自己身上。**
   它原来只有一个「⇔」，解释在 tooltip 里 —— 外审在 4 张图上共 **5 发**
   报「无法识别其具体功能用途」。
   ⭐⭐⭐ **一个只靠悬停才说话的控件，在任何一张静态截图上都是哑的**，
   而用户第一眼看到的也正是那样一张「截图」。

⚠ 补 tooltip **不等于**修好 —— 它只把「一个字都没有」变成「悬停有一句人话」。
  真正写在屏幕上的那一份，是按钮上那两个字。
"""
from __future__ import annotations

import os

import inspect
import re
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    import gui_widget
    from PySide6.QtCore import Qt

    w = gui_widget.MainWindow(auto_background_preload=False)
    w.setAttribute(Qt.WA_DontShowOnScreen, True)
    w.resize(1280, 800)
    w.show()
    for _ in range(4):
        app.processEvents()
    w.show_page("basic", animated=False, force=True)
    for _ in range(4):
        app.processEvents()
    yield w
    w._force_exit = True
    w.close()
    w.deleteLater()
    app.processEvents()


def _chips(win):
    """屏幕上真正画出来的那几颗芯片。

    ⚠ **不是** `win.basic_gsi_badge` 那几个 —— 它们是隐藏的载体，
      真正显示的是 `render_badges` 建的芯片池。
      量错对象的话，这条判据会一直绿着而屏幕上什么都没变。
    """
    bar = win.basic_status_badge_label
    return [c for c in bar.findChildren(QLabel)
            if c.text().strip() and not c.isHidden()]


def test_every_status_chip_carries_its_own_explanation(win):
    """⭐⭐ 每颗芯片都要说得出自己是什么，而不是靠排第几去分一份共享的。"""
    chips = _chips(win)
    assert len(chips) >= 5, (
        f"只找到 {len(chips)} 颗芯片 —— 状态带没渲染出来，这条判据在空转")
    mute = [c.text() for c in chips if not (c.toolTip() or "").strip()]
    assert not mute, (
        f"这几颗芯片一句解释都没有：{mute}\n"
        "⭐ 屏幕上就那么几个字（「GSI」对玩家尤其生僻），别处再没有第二处说明。")


def test_no_two_chips_share_one_borrowed_explanation(win):
    """⭐ 反向守卫：解释必须是**各自的**，不是整条那份被某一颗借去了。

    没有这一条，「每颗都有 tooltip」可以靠**给所有芯片贴同一段明细**满足 ——
    那和原来「第 3 颗拿走共享明细」是同一个毛病，只是摊薄了。
    """
    chips = _chips(win)
    tips = [(c.text(), (c.toolTip() or "").strip()) for c in chips]
    distinct = {tip for _t, tip in tips}
    assert len(distinct) >= max(3, len(chips) - 1), (
        "这几颗芯片的解释重样了：\n  "
        + "\n  ".join(f"{t} → {tip[:28]}" for t, tip in tips)
        + "\n⭐ 一句放之四海皆准的话，等于没说。")


def test_the_top_bar_toggle_says_what_it_does_on_itself(win):
    """⭐⭐⭐ 顶栏那颗切换按钮，话要写在按钮上，不能只写在 tooltip 里。"""
    btn = win._mode_toggle_btn
    text = (btn.text() or "").strip()
    assert text, "顶栏那颗切换按钮没有文案"
    letters = [ch for ch in text if ch.isalnum() or "一" <= ch <= "鿿"]
    assert len(letters) >= 2, (
        f"顶栏那颗按钮上只有「{text}」—— 一个图标不说话。\n"
        "⭐ tooltip 在静态截图上是不存在的，而用户第一眼看的就是那张截图。")
    # ⭐⭐ 量 `maximumWidth()`，不量 `width()`（批 60 实测）：
    #   把 `setFixedSize(40, 40)` 打回去之后，`maximumWidth()` 当场变 40，
    #   而 `width()` **仍然报 60** —— 离屏窗口里那颗按钮已经排过版了。
    #   ⇒ 拿 `width()` 断言，这条判据咬不动它要防的那件事。
    #   ⭐ 同批 59：**判据量的东西和承重的东西不是同一个**，就是一条哑判据。
    need = btn.sizeHint().width()
    assert btn.maximumWidth() >= need, (
        f"按钮的宽度被锁在 {btn.maximumWidth()}px，而它的文字要 {need}px —— "
        "锁死之后文字会被裁掉，等于又变回一个纯图标。")
    assert (btn.toolTip() or "").strip(), "按钮上有文案了，tooltip 也别丢"

    # ⭐⭐ 上面那条不等式**单独用是假绿的**（批 60 实测）：把样式表里的
    #   `max-width: 38px` 放回去之后，`maximumWidth` 和 `sizeHint` **一起**
    #   塌到 40 ⇒ 40 >= 40 照样成立。
    #   ⭐⭐⭐ **把两个会一起塌的数放在不等式两边，等于没有不等式。**
    #   ⚠ 也不能改去量字宽：离屏进程没有中文字体，
    #     `horizontalAdvance("⇔ 紧凑") == 0`（批 43 那条）。
    #   ⇒ 补一条**结构**断言，钉住 RN-541 真正拆掉的那一行。
    import theme_manager
    qss = inspect.getsource(theme_manager)
    #   ⚠ 分母要收**每一段**点到这颗按钮的样式 —— 第一版只 `re.search` 一次，
    #     撞上的是 `QPushButton#modeToggleButton, QPushButton#modeToggleIconButton`
    #     那一段（里面没有 max-width），而真正锁宽度的在下一段。
    #     ⭐ 同批 51/58：**按记号划分母，而那个记号出现在不止一处。**
    blocks = re.findall(
        r"(?m)^[ \t]*([^\n{]*modeToggleIconButton[^\n{]*)\{\{(.*?)\}\}",
        qss, re.S)
    assert len(blocks) >= 2, (
        f"只收到 {len(blocks)} 段 modeToggleIconButton 的样式 —— 判据在空转")
    locked = [sel.strip() for sel, body in blocks if "max-width" in body]
    assert not locked, (
        f"样式表又给顶栏那颗按钮上了 `max-width`：{locked}\n"
        "—— 文字会被裁回一个图标。⭐ RN-541 拆掉的就是这一行；高度可以钉，宽度不行。")

def test_a_clickable_switch_name_looks_clickable(win):
    """⭐⭐⭐ RN-235：能点的东西，屏幕上得看得出来能点。

    首页那 17 个功能名**本来就是可点的**（点了直接切到对应页），
    而它原来的可点信号只有两样：**悬停变手型**和 **tooltip** ——
    两样在静态画面上都不存在。
    ⚠ 我先把这条判成「实测后不成立」，依据是各功能页上那句
      「这一颗和首页那颗是同一个」——**而那句话在别的页上，不在这一页上**；
      同一批外审 3 发把这个错判顶了回来。
    ⚠⚠ 补了一句卡片说明之后**复跑又 5 发**：「功能名本身毫无链接或箭头等交互线索，
      不读说明的玩家只会把它当成纯标签」⇒ 记号必须在**名字自己身上**。

    ⭐ 反向也要成立：**没有对应页的那几个不许带记号** ——
      记号本身就是「这个能点、那个不能」的分界，见者有份就等于没说。
    """
    import gui_widget

    page = win.pages["basic"]
    marked, unmarked = [], []
    for sid, tg in win.switches.items():
        label = getattr(tg, "_label", None)
        if label is None or not label.isVisibleTo(page):
            continue
        has_page = gui_widget.MainWindow._get_home_switch_target_page(sid)
        (marked if has_page else unmarked).append((sid, label.text()))

    assert len(marked) >= 12, (
        f"只认出 {len(marked)} 个「有对应页」的开关 —— 分母塌了，这条判据在空转")
    missing = [(sid, t) for sid, t in marked if "›" not in t]
    assert not missing, (
        f"这几个功能名能点，屏幕上却看不出来：{missing}\n"
        "⭐ 悬停手型和 tooltip 在静态画面上都不存在。")
    wrong = [(sid, t) for sid, t in unmarked if "›" in t]
    assert not wrong, (
        f"这几个没有对应页，却带着「能点」的记号：{wrong}\n"
        "⭐ 记号见者有份，就不再是分界。")


def test_an_explained_chip_still_shows_the_specifics():
    """RN-044 后半：那颗有解释的芯片，**明细不许被解释吞掉**。

    ⭐⭐ 这是 RN-232 那次修法的副作用。原来写的是
    `CHIP_EXPLAINS.get(head) or self._detail_tooltip` —— 一个 `or`，
    于是**只要名字在解释表里，那份具体明细就永远轮不到**。
    实测 `audio_health` 四颗芯片，另外三颗都拿得到「缺失目录 N 项，失效引用 N 项…」，
    唯独「音频」那一颗拿不到 —— ⭐ **而它正是会变红的那一颗**。
    玩家悬上去看到的是「『需检查 N』是指有 N 项对不上」这句**定义**，
    从头到尾没有一个字说是**哪 N 项**。立案原话：「红色异常徽章无法点击查看具体错误」。

    ⚠ 阳性对照在第三条断言上：**没被解释表命中的那颗一直是好的** ——
      少了它，这条判据分不清「修好了」和「明细本来就没传进来」。
    """
    from pages.audio_status_badge import (
        CHIP_EXPLAINS, AudioStatusBadgeBar, render_badges,
    )

    DETAIL = "资源体检结果：共发现 3 项问题。缺失目录 2 项，失效引用 1 项。"
    bar = AudioStatusBadgeBar()
    render_badges(bar, [("warn", "音频 · 需检查 3"), ("info", "项目 · 3 项")],
                  detail_tooltip=DETAIL)
    tips = {c.text(): (c.toolTip() or "") for c in bar._chip_pool if not c.isHidden()}
    assert set(tips) == {"音频 · 需检查 3", "项目 · 3 项"}, f"芯片没渲染出来：{tips}"

    assert "缺失目录 2 项" in tips["音频 · 需检查 3"], (
        "会变红的那颗芯片看不到**是哪几项**，只有一句定义：\n  "
        + tips["音频 · 需检查 3"]
        + "\n⇒ 解释与明细要一起给，别用 `or` 让前者压住后者。")
    assert CHIP_EXPLAINS["音频"] in tips["音频 · 需检查 3"], (
        "把明细补回去的时候，不许把 RN-232 那句解释挤掉 —— 两句各回答一个问题。")
    # 阳性对照：名字不在解释表里的那颗，本来就该拿到明细
    assert "缺失目录 2 项" in tips["项目 · 3 项"], (
        "连没被解释表命中的芯片都拿不到明细 —— 那是明细根本没传进来，"
        "这条判据在一个恒定的答案上空转")
