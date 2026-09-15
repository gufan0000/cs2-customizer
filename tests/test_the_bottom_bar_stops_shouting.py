# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-504 / RN-552（批 69）：常驻高亮的提交按钮，与父子混排的锚点条。

## RN-504：一颗常驻高亮的提交按钮，本身就在说「还有一件必须做的事没做」

而同一屏的状态芯片同时写着「已存下」/「CFG · 已同步」，玩家判断不出到底存没存。

⭐ **真分母只有 2 页**（立案时按 15 页估）：15 页底栏有可见主按钮，其中 13 颗是
「打开音频资源 / 在屏幕上试播 / 添加音乐」这类**动作**按钮 —— 它们根本没有
「待提交」这回事。⇒ **由页面自己声明**（`set_primary_pending`），不靠猜文案：
⚠ 批 50 RN-524 踩过 —— 那条判据靠「文案里有没有『保存/应用』」认提交按钮，
把「应用到全部武器」这个**动作**判成了说假话。

⚠⚠ 修法只换 `background` 与 `color`，**几何一个像素不许动**
（批 29 RN-447 原话：改「警报级别」不许付出像素 —— 那次换 objectName 凭空
多了 2px，把同一行挤到折行，排版审计当场 11 → 16）。下面有一条判据专门量这个。

## RN-552：锚点条把父级和它自己的子级混排在同一行

外审 `magnifier` **3/3**：「把父级『基础』与子级『倍率』『热键』混排在同一行，
层级错乱」「标签与当前卡片内部子模块**重名**，不知该去哪里配置」。
实测**逐字属实**：5 颗里 3 颗是「基础」的后代，而「基础」离「倍率」只有 **74px**。

⚠ **本条只管这一半。** 同一条 RN 里还捆着 `advanced` 的「9 个同级标签认知过载」——
实测那 9 颗**全是顶层、零嵌套**，那是「同级过多」，是另一件事（要的是信息架构
取舍，不是层级显示）。⭐ 登记册自己写过这条规矩：**一条里捆着两件事时，
正确动作是把两件事拆开、各归各家**（RN-183 那一行的原话）。已拆出 RN-564。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest
from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from _audit_neutralize import (  # noqa: E402
    apply as neutralize_apply, enable_audit_mode)

enable_audit_mode()

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QPushButton, QSystemTrayIcon)

#: 名下有「提交」语义的两页 —— 由页面自己接线声明，这里只是记下它们是谁。
SUBMIT_PAGES = ("hud_color", "viewmodel")


@pytest.fixture(scope="module")
def qapp():
    os.environ.pop("QT_QPA_PLATFORM", None)
    app = QApplication.instance() or QApplication([])
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)
    return app


@pytest.fixture(scope="module")
def win(qapp):
    from _audit_sandbox import block_config_persistence, sandbox_external_writes

    sandbox_external_writes()
    block_config_persistence()
    from config import config

    config.compact_mode = False
    import gui_widget

    w = gui_widget.MainWindow(auto_background_preload=False)
    w.setAttribute(Qt.WA_DontShowOnScreen, True)      # ⛔ 不打扰前台
    w.show()
    qapp.processEvents()
    w.setMinimumSize(1280, 800)
    w.resize(1280, 800)
    qapp.processEvents()
    for _ in neutralize_apply(config, list(w._page_names.keys())):
        pass
    yield w
    w._force_exit = True
    w.close()


def _settle(qapp, n=20):
    for _ in range(n):
        qapp.processEvents()


def _bar(page):
    return next((c for c in page.findChildren(object)
                 if type(c).__name__ == "PageActionBar"), None)


def _goto(win, qapp, page_id):
    win.ensure_page_loaded(page_id)
    win.show_page(page_id, animated=False, force=True)
    _settle(qapp)
    return win.pages[page_id]


# ──────────────────────────────────────────── RN-151

def test_a_subordinate_checkbox_says_on_itself_that_it_is_not_in_effect(win, qapp):
    """RN-151：总开关关着时，那颗从属勾选框要在**自己的文案**里说它不生效。

    现场：勾选框「击杀触发屏幕边缘特效」**画着勾**（默认 True）但被禁用，
    而同屏芯片写「边缘特效 · 关闭」—— 一个画着勾的框，读起来就是「这功能开着」。

    ⭐⭐⭐ 批 82 两个候选的票数（同题面 6 发，地板页 `gun_sound` 两轮都 不会 6/6）：

      | 修法 | 「你会不会以为它现在开着」 |
      |---|---|
      | 旁边那句说明改成点名那颗勾 | **会 6/6**（一票没买到）|
      | **标记进控件自己的文案** | **会 1/6** |

    外审逐字说明了为什么第一个买不到：「没耐心的玩家不会细读长说明，
    **视觉焦点仍在打勾的控件上**」。
    ⇒ ⭐⭐⭐ **「在控件旁边说」和「在控件身上说」，是两件不同的事。**

    ⚠ 这是本批第三次同形（RN-565 那句文案 → 那颗按钮；RN-183 那句底栏 → 整个三层；
    本条那句说明 → 那个勾）：**我改的是「说明那件事的话」，
    而承重的是「那件事本身的那个控件」。**

    ⛔ 不许改成「不禁用」（RN-421 已改判接受禁用），也不许动 `checkState`
    （`_save_config` 走 `isChecked()`，三态会把用户存着的值写坏）。
    """
    from PySide6.QtWidgets import QCheckBox
    page = _goto(win, qapp, "screen_effects")
    box = next((c for c in page.findChildren(QCheckBox)
                if "边缘特效" in (c.text() or "")), None)
    assert box is not None, "screen_effects 上找不到那颗从属勾选框 —— 这条判据的对象没了"

    # ⚠ **自己造那一态**，别指望环境碰巧是那样（判据跑在中和过的配置上）。
    #   ⭐ 这里造的是**场景**，不是被测行为本身 —— 被测的是「那一态下文案说什么」。
    from config import config as _cfg
    box.setChecked(True)
    for _state, expect in ((False, True), (True, False)):
        setattr(_cfg, "screen_effects_enabled", _state)
        page._sync_enabled_state()
        _settle(qapp, 5)
        if expect:
            assert box.isChecked(), "分母守卫：这条判据要的是「画着勾却不生效」那一态"
            assert not box.isEnabled(), "那一态下它应当是禁用的（RN-421 接受禁用）"
            assert "不生效" in box.text(), (
                "总开关关着，而这颗勾选框自己的文案里没说它不生效。\n"
                f"  现在写的是：{box.text()!r}\n"
                "⭐ 旁边那句说明实测买 0 票 —— 玩家的视觉焦点在打勾的控件上。")
        else:
            # ⭐ 阳性对照的另一半：总开关开着时那句话必须**消失** ——
            #   否则一个永远写着「不生效」的文案也能让上面那条全绿。
            assert "不生效" not in box.text(), (
                f"总开关开着，控件文案里却还写着不生效：{box.text()!r}")


# ──────────────────────────────────────────── RN-183

#: 这一页曾经是全站最重的一例：5 颗芯片里 **4 颗**被底栏逐值复述。
_ECHO_PAGE = "viewmodel"


def _chip_values(page) -> list[str]:
    """把这一页顶部那排芯片的**值**取出来（「CFG · 已同步」取「已同步」）。

    ⚠ 芯片按 **objectName `audioStatusChip`** 认，不按类名认：
    仓里另有一个 `widgets/status_chip.py::StatusChip`，而这些页**不用它** ——
    芯片是 `AudioStatusBadgeBar._ensure_chip_pool` 里现造的普通 QLabel。
    ⭐ 我第一版按类名扫，读到 **0 颗**；是分母守卫把它逮住的 ——
    ⭐⭐⭐ 否则这条判据会以「底栏没复述任何芯片」的样子**全绿**，
    而它其实一颗芯片都没看见（同 RN-183 立案里那句假话的来路）。
    """
    out = []
    for c in page.findChildren(QLabel):
        if c.objectName() != "audioStatusChip" or not c.isVisibleTo(page):
            continue
        parts = [p.strip() for p in (c.text() or "").split("·") if p.strip()]
        if len(parts) >= 2:
            out.append(parts[-1])
    return out


def _norm(s: str) -> str:
    keep = "".join(str(s or "").split())
    return "".join(ch for ch in keep if ch not in "·:：。，,、（）()【】[]—-")


def test_the_bottom_bar_does_not_restate_what_the_chips_already_say(win, qapp):
    """RN-183：**底栏不许复述芯片的值。**

    ⭐⭐⭐ 改之前 `viewmodel` 底栏逐字是
    「当前状态：CFG已同步 · 循环键 CAPSLOCK · 自动切换关闭（V） · 共 5 组预设。」——
    **开头就是「当前状态：」，而屏幕上方那一排芯片正是「当前状态」这个控件**；
    5 颗里 4 颗被逐值复述。⇒ 底栏不是在补充，是在用纯文本重画一遍那一排。

    ⭐⭐ 它在源码里的形状是：同一个值被取了四次。撤掉复述之后，
    ruff 当场点出 **9 个**只为「把控件自己的状态再念一遍」而做的取值
    （`cycle_key` / `auto_key` / `preset_count` / `auto_interval` / `crosshair_enabled` …）。

    ⚠ 分工（这条判据守的就是它）：**芯片管当前状态，底栏管「怎么在游戏里生效」** ——
    后者是一句任何状态下都为真的因果（同 RN-502：说动作的后果，不说当前的状态）。
    """
    page = _goto(win, qapp, _ECHO_PAGE)
    bar = _bar(page)
    assert bar is not None, f"{_ECHO_PAGE} 没有底栏 —— 这条判据的对象没了"
    values = _chip_values(page)
    must_scan(values, f"{_ECHO_PAGE} 顶部芯片的值", least=3)

    assert hasattr(bar, "message_label"), "底栏没有 message_label —— 这条判据的对象没了"
    # ⚠ 富文本那一档会把出口链接拼成 <a>，所以先把标签去掉再比（RN-528 接的线）。
    msg = _norm(re.sub(r"<[^>]+>", "", bar.message_label.text()))
    echoed = [v for v in values if _norm(v) and _norm(v) in msg]
    assert not echoed, (
        f"{_ECHO_PAGE} 底栏又在复述芯片的值：{echoed}\n"
        f"  底栏原文：{msg}\n"
        "⭐ 芯片是「当前状态」的唯一真源；底栏只说这一页的改动**怎么在游戏里生效**。"
    )


def test_the_echo_check_can_actually_see_an_echo(win, qapp):
    """⭐ 阳性对照：上一条绿着，可能是真不复述了，也可能是**芯片一颗都没读到**。

    ⛔ RN-585 的教训逐字是「我的探针不可信，别照着它下结论」，而我照着它下了结论；
    而本批 RN-183 自己也栽过同款 —— 立案里那句「第三处『卡片描述』已经空了」
    是拿一支**只量底栏**的探针断言出来的，实测**四个卡片摘要全是活的**。
    """
    page = _goto(win, qapp, _ECHO_PAGE)
    values = _chip_values(page)
    must_scan(values, f"{_ECHO_PAGE} 顶部芯片的值", least=3)
    fake = "当前状态：" + " · ".join(values)
    hit = [v for v in values if _norm(v) and _norm(v) in _norm(fake)]
    assert len(hit) == len(values), (
        "拿改前那句原样的底栏文案去考这把尺子，它却读不出复述 —— "
        f"只认出 {len(hit)}/{len(values)} 颗。上一条的绿不作数。"
    )


# ──────────────────────────────────────────── RN-504

@pytest.mark.parametrize("page_id", SUBMIT_PAGES)
def test_a_submit_button_only_shouts_when_there_is_something_to_submit(
        win, qapp, page_id):
    """**页面自己**必须声明「有没有待提交」—— 刚打开时那颗按钮不许在喊。

    ⚠⚠ 这条判据第一版是假绿的，破坏验证当场逮到：它先自己调一次
    `bar.set_primary_pending(False)` 再断言属性是 "false" ——
    ⭐⭐⭐ **那测的是这个方法本身，不是「页面有没有接线」**；
    把页面里那一行删掉，判据纹丝不动地绿着（批 47 RN-513 逐字那一条，
    而我是在刚写完 RN-563 之后又犯了一次）。
    ⇒ 改成**什么都不碰**，只看页面加载完之后的自然状态。
    """
    page = _goto(win, qapp, page_id)
    bar = _bar(page)
    assert bar is not None, f"{page_id} 没有底栏 —— 分母守卫"
    btn = bar.primary_btn
    assert btn.text().strip(), f"{page_id} 底栏主按钮的文案没了？这条判据的对象没了"

    # ⛔ 到这里为止一次 `set_primary_pending` 都没调过 —— 这才是用户第一眼看到的那一态。
    assert btn.property("fp_pending") == "false", (
        f"{page_id}：刚打开、什么都没改，这颗提交按钮却没声明自己是干净的"
        f"（fp_pending={btn.property('fp_pending')!r}）——\n"
        "⇒ 页面要在同步底栏时调 `action_bar.set_primary_pending(是否有待提交)`。")
    # ⭐⭐⭐ RN-504（批 82 定案）：干净态它要**不在场**，不是「在场但降了色」。
    #   ⚠ 这条判据原来断言的是 `btn.isVisibleTo(page)` —— 它把**当时那个只降色的实现
    #   钉成了规格**，于是真修好之后它反而判红（同批 81 那七条，RN-009 同族）。
    #   三组 A/B 的数逐字：改前 会 6/6 → 隐藏 **不会 6/6** → 禁用（置灰）**会 6/6**，
    #   地板页三组纹丝不动。⭐ **「在场但不可点」和「不在场」不是一回事** ——
    #   而那个差别就是全部的效果（正面证实了 RN-174 那条反向证据）。
    assert not btn.isVisibleTo(page), (
        f"{page_id}：刚打开、什么都没改，这颗提交按钮还在屏幕上。\n"
        "⭐ 在场并可点本身就是那句「还有一件必须做的事没做」，"
        "而同一屏的芯片同时写着「已存下」。")


@pytest.mark.parametrize("page_id", SUBMIT_PAGES)
def test_the_pending_flag_follows_the_dirty_state(win, qapp, page_id):
    """而拨到「脏」的时候它得跟着变（上一条只钉住了干净那一态）。"""
    page = _goto(win, qapp, page_id)
    bar = _bar(page)
    bar.set_primary_pending(True)
    # ⭐ 阳性对照的另一半：**脏态它必须回来**。
    #   ⛔ 只钉「干净时不在」的话，一个永远不显示的按钮也能全绿。
    assert bar.primary_btn.isVisibleTo(page), (
        "有待提交内容时这颗按钮却不在场 —— 那玩家就没有提交的入口了")
    _settle(qapp)
    assert bar.primary_btn.property("fp_pending") == "true"
    bar.set_primary_pending(False)
    _settle(qapp)
    assert bar.primary_btn.property("fp_pending") == "false"


@pytest.mark.parametrize("page_id", SUBMIT_PAGES)
def test_changing_the_alarm_level_costs_no_pixels(win, qapp, page_id):
    """两态的几何必须**逐字节相同** —— 只许颜色变。

    ⚠⚠ 量法有讲究：**第一次读到的数是错的**。页面刚建完时这颗按钮的
    `minimumWidth` 还是它的自然 `sizeHint`（实测 `hud_color` 147），
    要等样式表再 polish 一次才落到 QSS 声明的那个值（80）。
    ⭐ 批 66 逐字那一条：「多等几拍再量」——那次我量到 anchorChip
    `min=max=26`，多等几拍是 `min=34/max=26`。
    ⇒ 这里先拨一次让它 polish，**再**开始比两态。
    """
    page = _goto(win, qapp, page_id)
    bar = _bar(page)
    btn = bar.primary_btn

    def geom():
        r = btn.geometry()
        return (r.x(), r.y(), r.width(), r.height(),
                btn.minimumWidth(), btn.minimumHeight(),
                btn.maximumWidth(), btn.maximumHeight())

    bar.set_primary_pending(True)          # 先 polish 一次，把尺子校准
    _settle(qapp)
    bar.set_primary_pending(False)
    _settle(qapp)
    clean = geom()
    bar.set_primary_pending(True)
    _settle(qapp)
    dirty = geom()
    bar.set_primary_pending(False)
    _settle(qapp)

    assert clean == dirty, (
        f"{page_id}：换「警报级别」付出了像素\n"
        f"  干净 {clean}\n  脏   {dirty}\n"
        "⭐ 批 29 RN-447：改警报级别不许付出像素 —— 那次凭空多的 2px "
        "把同一行挤到折行，排版审计当场 11 → 16。")


@pytest.mark.parametrize("page_id", SUBMIT_PAGES)
def test_the_quiet_state_actually_looks_different(win, qapp, page_id):
    """阳性对照：两态**渲染出来的底色必须真的不一样**。

    ⭐ 没有这一条，上面两条全绿只能证明「属性设对了、几何没动」——
    证明不了「屏幕上看得出区别」。而 QSS 选择器的特异度一旦被别的规则压过，
    属性照样是对的、像素一点没变（RN-150 逐字那一族）。
    """
    from PySide6.QtGui import QPixmap

    page = _goto(win, qapp, page_id)
    bar = _bar(page)
    btn = bar.primary_btn

    def fill():
        pm = QPixmap(btn.size())
        pm.fill(Qt.transparent)
        btn.render(pm)
        img = pm.toImage()
        c = img.pixelColor(min(12, img.width() - 1), img.height() // 2)
        return (c.red(), c.green(), c.blue())

    bar.set_primary_pending(True)
    _settle(qapp)
    loud = fill()
    bar.set_primary_pending(False)
    _settle(qapp)
    quiet = fill()

    assert loud != quiet, (
        f"{page_id}：两态渲染出来是同一个颜色 {loud} —— "
        "属性设了、样式表没生效（多半是特异度被别的规则压过，同 RN-150 那一族）。")


def test_the_quiet_state_keeps_its_contrast():
    """干净态的文字对比度，9 套主题都要 ≥4.5:1（WCAG AA）。

    ⚠ CLAUDE.md 逐字：改了配色一定要重算对比度。这里用公式实算，不靠肉眼。
    """
    import theme_manager as TM

    def lum(rgb):
        def ch(v):
            v /= 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = (ch(x) for x in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def hex2rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    themes = [TM.DarkTheme, TM.LightTheme, TM.GreenTheme, TM.PurpleTheme,
              TM.WarmTheme, TM.ContrastTheme, TM.RoseTheme, TM.OceanTheme,
              TM.MinimalTheme]
    must_scan(themes, "参与对比度实算的主题", least=8)

    bad = []
    for cls in themes:
        c = cls().colors
        fg, bg = hex2rgb(c.text_primary), hex2rgb(c.bg_tertiary)
        la, lb = lum(fg), lum(bg)
        ratio = (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
        if ratio < 4.5:
            bad.append(f"{cls.__name__} {ratio:.2f}:1")
    assert not bad, "干净态文字对比度不达标：" + " / ".join(bad)


# ──────────────────────────────────────────── RN-552

def test_no_anchor_chip_is_an_ancestor_of_another(win, qapp):
    """锚点条里**不许有一颗芯片装着另一颗芯片指向的东西**。

    ⭐ 这就是「层级混排」的可测形式：只要没有祖先-后代关系，
    这一排就只有一个层级，「层级错乱」在结构上不成立。
    ⚠ 按**形状**划分母（全站扫锚点条），不点名任何一页 ——
    批 64 那条：判据改成按形状划分母，新页天生进分母。
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QLabel, QScrollArea

    from widgets.anchor_bar import _is_ancestor

    pages_with_bar, offenders = [], []
    for page_id in list(win._page_names.keys()):
        try:
            page = _goto(win, qapp, page_id)
        except Exception:                                    # noqa: BLE001
            continue
        chips = [w for w in page.findChildren(QPushButton)
                 if w.objectName() == "anchorChip"]
        if not chips:
            continue
        pages_with_bar.append(page_id)

        scroll = next((w for w in page.findChildren(QScrollArea)), None)
        body = scroll.widget() if scroll is not None else None
        if body is None:
            continue

        # 芯片 → 目标：从 tooltip 里的完整标题反查这一页的卡片
        # ⚠⚠ **两种载体都要认**：顶层的 `SettingsCard`（有 `title_label`）
        #    与内层的 `QFrame#card`（标题是它里面第一个 QLabel）。
        #    这条判据第一版只认前者 ⇒ `magnifier` 那 3 颗内层芯片
        #    （倍率 / 热键 / 偏移，**正好就是构成父子关系的那三颗**）
        #    根本没进分母，破坏验证当场判它假绿。
        #    ⭐ 又一次：**判据按某个记号划分母，不带那个记号的天生看不见**。
        cards = []
        for w in page.findChildren(object):
            tl = getattr(w, "title_label", None)
            if isinstance(tl, QLabel) and tl.text().strip():
                cards.append((tl.text().strip(), w))
            elif getattr(w, "objectName", lambda: "")() == "card":
                lab = w.findChild(QLabel)
                if lab is not None and lab.text().strip():
                    cards.append((lab.text().strip(), w))
        targets = []
        for chip in chips:
            tip = chip.toolTip()
            full = tip.split("「")[-1].rstrip("」") if "「" in tip else chip.text()
            card = next((c for t, c in cards if t == full), None)
            if card is not None:
                targets.append((chip.text(), card))

        for short, card in targets:
            for other_short, other in targets:
                if other is not card and _is_ancestor(card, other):
                    offenders.append(
                        f"{page_id}：「{short}」装着「{other_short}」"
                        f"（y={card.mapTo(body, QPoint(0, 0)).y()}）")

    must_scan(pages_with_bar, "有锚点条的页", least=2)
    assert not offenders, (
        "锚点条里父级和它自己的子级混排在同一行：\n  " + "\n  ".join(offenders) +
        "\n⭐ 外审 magnifier 3/3 报的就是这个（「标签与当前卡片内部子模块重名，"
        "不知该去哪里配置」），实测 5 颗里 3 颗是「基础」的后代。")


def test_dropping_containers_keeps_the_leaves_not_the_parents():
    """阳性 + 阴性对照：合成一棵父子结构，断言丢掉的是**容器**不是内容。

    ⚠ 方向很容易反：本文件的调用方早就否过「只留顶层」那条路
    （`magnifier` 只扫顶层的话锚点只剩 2 个，而用户想直达的正是内层）。
    ⭐ **去掉容器和只留顶层，方向正好相反。**
    """
    from PySide6.QtWidgets import QWidget

    from widgets.anchor_bar import drop_container_sections

    root = QWidget()
    parent = QWidget(root)
    child_a = QWidget(parent)
    child_b = QWidget(parent)
    sibling = QWidget(root)

    sections = [("基础控制", "基础", parent),
                ("倍率与灵敏度", "倍率", child_a),
                ("热键与触发", "热键", child_b),
                ("武器开镜范围", "武器范围", sibling)]
    kept = [s for _t, s, _w in drop_container_sections(sections)]
    assert kept == ["倍率", "热键", "武器范围"], (
        f"丢错了：留下 {kept}。应当丢掉**容器**「基础」，"
        "留下它的子段和不相关的兄弟段。")

    # 阴性对照：没有嵌套时一颗都不许丢
    flat = [("甲", "甲", QWidget(root)), ("乙", "乙", QWidget(root))]
    assert [s for _t, s, _w in drop_container_sections(flat)] == ["甲", "乙"], (
        "没有嵌套的时候不许丢任何一颗 —— `advanced` 那 9 颗全是顶层，"
        "它的问题是「同级过多」（RN-564），不是层级混排。")


def test_the_message_label_does_not_guess_whether_user_text_is_html():
    """⭐⭐ RN-589：底栏这条回执里塞的多半是**用户自己起的字**，不许让 Qt 猜格式。

    实测（批 75）：全仓 45 处 `set_message` 里 **34 处传的不是字面量** ——
    预设名、导入的文件名都从这里过。而标签原来一个格式都不设 ⇒ `Qt.AutoText`：
    `预设 <玩家自定义> 已应用` 侥幸安全，`已导入 A&lt;B.wav` **被当成富文本**，
    屏幕上少三个字符。
    ⭐⭐ **一个「大多数时候没事」的自动探测，赌的是用户不会给文件起某个名字。**

    ⇒ 默认档必须是 `PlainText`；要富文本得**显式**传 `rich=True`（那几处嵌了页名链接）。
    """
    from PySide6.QtWidgets import QLabel

    from widgets.page_action_bar import PageActionBar

    bar = PageActionBar()
    assert bar.message_label.textFormat() == Qt.PlainText, (
        f"底栏消息标签的格式是 {bar.message_label.textFormat()!r} —— "
        "`AutoText` 会拿用户起的文件名去猜 HTML")

    # 默认档：一个像 HTML 实体的文件名必须原样显示
    nasty = "已导入 A&lt;B.wav"
    bar.set_message(nasty)
    assert nasty in bar.message_label.text(), "默认档把用户的字改写了"
    plain = QLabel()
    plain.setTextFormat(Qt.PlainText)
    plain.setText(bar.message_label.text())
    assert bar.message_label.sizeHint().width() == plain.sizeHint().width(), (
        "默认档量出来的宽度和纯文本档不一样 —— 那几个字符被当标记吃掉了")

    # 富文本档：显式声明才切过去，且 tooltip 必须去标签（RN-578：tooltip 里点不了）
    bar.set_message('去<a href="cs2customizer:page/advanced">高级设置</a>看看', rich=True)
    assert bar.message_label.textFormat() == Qt.RichText, "`rich=True` 没切到富文本"
    tip = bar.message_label.toolTip()
    assert "<a " not in tip and "</a>" not in tip, (
        f"tooltip 里留着标签 —— 那是一个点不动的链接副本：{tip!r}")
    assert "高级设置" in tip, f"去标签把整句话也去掉了：{tip!r}"

    # 切回默认档必须真的切回去（不许一朝富文本、永远富文本）
    bar.set_message(nasty)
    assert bar.message_label.textFormat() == Qt.PlainText, (
        "从富文本档切回来之后格式没还原 —— 下一句用户数据就会被当成 HTML")
