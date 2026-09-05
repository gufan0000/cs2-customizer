# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-103：状态胶囊长得像可以点的按钮，而它只是一个标签。

## 这条为什么现在才动手

它从 M0（2026-08-17）起就开着，一直只有**票数**（外审 kill_icon 3/3、
全站 20+ 页同构）。批 25 那把带台阶的行为题第一次给了它**行为证据**：

    题面：「这一屏上有没有哪个看着能点的东西，你点下去会觉得
           『怎么没反应』？**没有就写「没有」**」
    12 发 ⇒ **7 发逐字抄出的全是状态胶囊**，6 发答「没有」。

批 26 换一组页面、换一个题面组合复跑，**又是 7/12**。同一个数，两轮独立复现。

## ⭐ 机制不是颜色，是形状 —— 而这是量出来的，不是猜的

那些胶囊在批 16（RN-407）之后**已经被退成中性色了**，所以颜色不可能是原因。

| | 轮廓 vs 卡底 | 填充 vs 卡底 |
|---|---|---|
| `audioStatusChip` | **1.02 ~ 1.59 : 1** | **1.00 : 1**（和卡底一模一样）|
| `secondaryButton`（真按钮）| 1.12 ~ 1.90 : 1 | 1.00 : 1 |

⭐⭐⭐ **胶囊和次按钮在像素上是同一种东西：一个只有极淡轮廓的圆角空框。**

再把「描边到底是不是可点的信号」拿全站证伪一遍（不是只看胶囊）：

    可点 + 带描边   267 个 / 6 种（全是按钮类）
    可点 + 无描边   275 个 / 7 种（下拉、滑块、勾选、输入 —— 各有各的形状语言）
    不可点 + 带描边 273 个 / 3 种：card ×148、**audioStatusChip ×122**、
                                   overlayRequirementHint ×3
    不可点 + 无描边 867 个 / 27 种（全是文字标签）

`card` 和那条告示横幅都比按钮大一个数量级，没人会把 962px 宽的卡当按钮。
⇒ **胶囊是全站唯一一个「按钮尺寸 + 闭合轮廓」的不可点元素。** 假设活下来了。

## ⭐⭐ 修法是四个候选里量出来的，而**候选自己成了机制的阳性对照**

|  | ①「看着能点」指向那一排 | ②读成「可以点的选项」 | ③认出「有问题要处理」 |
|---|---|---|---|
| A 现状 | **7/12** | **7/12** | basic 3/3 真警告 + **4 发假阳性**（同页三发互相矛盾）|
| B 无闭合轮廓 + 左侧色条 | **2/12** | **2/12** | basic 3/3 + **0 假阳性**（12/12 内部一致）|
| C 无框无底纯文字 | 3/12 | 3/12 | basic 3/3 + 2 假阳性 |
| D 中性去框、**警告保留框** | 4/12 | 2/12 | 同 B |

⭐⭐⭐ **D 的那 4 发残留，逐字抄出来的正是它唯一保留了框的那两颗警告胶囊。**
同一屏上，去掉框的没人报、留着框的被点名 —— **框就是那个信号，实锤。**

⚠ 而 ③ 那一栏差点让我把 B 判成"砸了警告信号"（7 → 3）。
逐条读原话才看出来：A 那 7 分里只有 3 分是信号，另外 4 分是**噪声**，
而且是同一页三发三个答案的不一致噪声。
⭐⭐ **票数分不清「信号没了」和「噪声没了」；只有逐条读原话分得清**
（批 24 那条的第二次现身）。

## ⚠⚠ 这份判据为什么量的是**标本**，不是活页面

第一版是全站扫 112 颗真胶囊、量它们渲染出来的形状。**那是错的**：

    QT_QPA_PLATFORM=offscreen（`tests/conftest.py:9`）
    QFontDatabase.families() == 0
    ⇒ 「主题 · 深色」这颗胶囊的 sizeHint 是 **26×40**，
       而同一颗在有字体的进程里是 **99×40**；
       「GSI · 未运行」（含 ASCII）却是 76×40。

一个 26px 宽、圆角 13px 的药丸**整个都是圆角**，"下边框跨了多宽"这种量法
在它身上没有意义 —— 于是 112 颗里只报出 5 颗，而那 5 颗恰好是文案里带 ASCII 的。

⭐⭐⭐ **一个没有字体的进程，会让任何量「形状」的判据量到一个用户从没见过的版面。**
而 `scripts/ui_shot_capture.py` 开头就写着这条（字体库为空时**直接拒绝出图**）——
⭐ **这条知识住在出图脚本里，判据这边不知道。**

⚠ 顺带澄清：批 23（禁用态颜色）和批 25（降权颜色）那两条判据在同一个夹具上
**是对的** —— 它们量的是**颜色**，而颜色不随尺寸变。
⭐ **一份夹具能不能用，取决于你要量什么。**

⇒ 这份判据改成渲染**尺寸钉死的标本**：真样式表、真像素，只是不让缺字体的
文字宽度混进来。而「全站到底有多少颗、在哪些页」由另一条判据管，
数个数不需要字体。
"""
from __future__ import annotations

import colorsys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
)

# ⚠ 主窗夹具用共享那一份，不抄第二份（RN-002 那 9 份名单的形态）。
from tests.test_master_switch_effect_is_honest import (  # noqa: E402
    main_window as _shared_main_window,
)
from _denominator import must_scan

main_window = _shared_main_window

CHIP = "audioStatusChip"

#: 分母下限。实测全站 **27 页 / 122 颗**（而登记册那一格写的是「20+ 页，
#: 旧账实证 10 页」）。⭐ 认出一族是免费的，数清有几个成员不是 —— 又一次。
MIN_CHIPS = 100
MIN_PAGES = 20

#: 标本尺寸。钉死它，缺字体就影响不到形状。
SPECIMEN = (140, 30)

#: 「最底下那一行 ink 横跨了多宽」的分界。标本实测：
#: 闭合的框 ≈ **0.9**、只有左侧色条 ≈ **0.02**（3px / 140px）——
#: 差一个数量级，0.40 落在中间的空档里。
#: ⭐ 一个阈值该定在哪，看的是两边实测值之间有多大的空档，不是我觉得多少合适。
CLOSED_BOX_SPAN = 0.40
#: 左侧色条要覆盖多少比例的行才算「还在」。
LEFT_BAR_ROWS = 0.55

#: 非文字 UI 元件的对比度下限（WCAG 1.4.11）；文字是 4.5。
AA_NON_TEXT = 3.0
AA_TEXT = 4.5

THEMES = ("dark", "light", "green", "purple", "ocean", "warm", "rose", "contrast")


# ------------------------------------------------------------------ 标本

def _hexed(rgb) -> str:
    return "#%02x%02x%02x" % tuple(rgb)


def _render_specimen(qapp, kind: str, level: str | None = None,
                     master_off: bool = False):
    """在一张真卡片上放一颗尺寸钉死的控件，抓它的像素。

    ⚠ 宿主必须是 `QFrame#card` —— 它有实底，抓出来才是不透明的；
      直接 grab 一颗透明底的 QLabel 会得到 `#000000`（那是透明，不是它的底）。
    """
    from theme_manager import get_theme_manager

    host = QFrame()
    host.setObjectName("card")
    if master_off:
        # ⚠ 批 16 那条 `QFrame#card[masterOffHost="true"] QLabel#audioStatusChip`
        #   **特异度比 level 那几条都高**，它一度会把闭合轮廓整个加回来。
        # ⭐ 破坏验证逮到的空转：标本没有这个祖先属性，那条规则就够不着 ——
        #   **一条只在某个祖先属性下才生效的规则，需要一个带那个祖先的标本。**
        host.setProperty("masterOffHost", "true")
    layout = QHBoxLayout(host)
    layout.setContentsMargins(24, 24, 24, 24)
    widget = QLabel("A") if kind == CHIP else QPushButton("A")
    widget.setObjectName(kind)
    if level is not None:
        widget.setProperty("level", level)
    widget.setFixedSize(*SPECIMEN)
    layout.addWidget(widget)
    layout.addStretch()
    host.setStyleSheet(get_theme_manager().get_stylesheet())
    host.setAttribute(Qt.WA_DontShowOnScreen, True)
    host.setFixedSize(SPECIMEN[0] + 120, SPECIMEN[1] + 60)
    host.show()
    for _ in range(3):
        qapp.processEvents()
    image = host.grab().toImage()
    dpr = image.width() / max(1, host.width())
    origin = widget.mapTo(host, widget.rect().topLeft())
    try:
        return _shape(image, dpr, origin, widget.width(), widget.height())
    finally:
        host.hide()
        host.deleteLater()
        qapp.processEvents()


def _shape(image, dpr, origin, logical_w, logical_h):
    """控件画出来的东西：最底下那一行 ink 的横向跨度 + 左边有 ink 的行数占比。

    ⚠⚠ 在**物理像素网格**上扫，不按逻辑坐标逐点取样：`devicePixelRatio` 不为 1 时
    `int((y + dy) * dpr)` 会**跳行**，那条边整行被跳过去，
    打印出来和「那儿本来就没画东西」一模一样。
    ⚠ 只用「最底下那一行的跨度」这一个判据，因为它对**圆角免疫** ——
      第一版按包围盒四条边算，圆角把极值行列削得只剩中段，112 颗只报出 5 颗。
    """
    x0 = int(origin.x() * dpr)
    y0 = int(origin.y() * dpr)
    w = max(1, int(logical_w * dpr))
    h = max(1, int(logical_h * dpr))
    if x0 < 0 or y0 < 0 or x0 + w > image.width() or y0 + h > image.height():
        return None

    from collections import Counter

    counter: Counter = Counter()
    for py in range(h):
        for px in range(w):
            counter[image.pixelColor(x0 + px, y0 + py).getRgb()[:3]] += 1
    card = counter.most_common(1)[0][0]

    rows = []
    for py in range(h):
        ink = [px for px in range(w)
               if image.pixelColor(x0 + px, y0 + py).getRgb()[:3] != card]
        rows.append(ink)
    inked = [i for i, ink in enumerate(rows) if ink]
    if not inked:
        return {"bottom_span": 0.0, "left_rows": 0.0, "card": card}
    lowest = rows[inked[-1]]
    bar_edge = max(2, int(4 * dpr))
    left_rows = sum(1 for ink in rows if ink and min(ink) <= bar_edge)
    # ⚠⚠ 色条**实际画出来是什么颜色**，必须从像素里读，不许拿 token 算一个假设值。
    # ⭐⭐ 第一版对比度判据算的是「**如果**用 `text_tertiary` 会怎样」——
    #   于是把 QSS 里的色条换成几乎看不见的 `border_secondary`（1.02:1），
    #   那条判据**照样全绿**。破坏验证当场逮到。
    #   ⭐ 「文件里有没有」和「屏幕上有没有」之外，还有第三种走神：
    #     **判据算的是一个和屏幕无关的量。**
    bar = Counter()
    for py in range(h):
        for px in range(min(bar_edge + 1, w)):
            colour = image.pixelColor(x0 + px, y0 + py).getRgb()[:3]
            if colour != card:
                bar[colour] += 1
    return {
        "bottom_span": (max(lowest) - min(lowest) + 1) / w,
        "left_rows": left_rows / max(1, len(rows)),
        "card": card,
        "bar": bar.most_common(1)[0][0] if bar else None,
    }


@pytest.fixture(scope="module")
def specimens(qapp):
    from theme_manager import get_theme_manager

    tm = get_theme_manager()
    before = tm.current_theme_name
    out = {}
    try:
        tm.set_theme("dark")
        for level in (None, "info", "warning", "danger"):
            key = f"chip:{level or 'base'}"
            out[key] = _render_specimen(qapp, CHIP, level)
        out["chip:masterOff"] = _render_specimen(qapp, CHIP, "warning",
                                                 master_off=True)
        out["secondaryButton"] = _render_specimen(qapp, "secondaryButton")
        out["actionButton"] = _render_specimen(qapp, "actionButton")
    finally:
        tm.set_theme(before)
    return out


# ------------------------------------------------------------------ 形状

def test_the_specimen_renderer_actually_draws_something(specimens):
    """⭐ 空转守卫：先证明标本真的画出了东西，再让下面几条断言「没问题」。

    ⚠ 少了这一条，「宿主没渲染出来」和「胶囊不是闭合框」在结果上完全一样
    —— 批 14 的候选 B 就废在这儿（一个没渲染出来的候选，拿去比就是在比两张一样的图）。
    """
    missing = [k for k, v in specimens.items() if v is None]
    assert not missing, f"这些标本一个像素都没抓到：{missing}"
    assert specimens["secondaryButton"]["bottom_span"] >= CLOSED_BOX_SPAN, (
        "连**真按钮**的标本都没画出闭合框来 —— 渲染这一步就没成，"
        f"实测 {specimens['secondaryButton']['bottom_span']:.2f}")


@pytest.mark.parametrize("level", [None, "info", "warning", "danger",
                                   "masterOff"])
def test_a_status_chip_is_not_drawn_as_a_closed_box(specimens, level):
    """⭐⭐ 主刀：不可点的东西不许长按钮的形状 —— **不许是闭合的框**。

    ⚠ 四个 level 各判一次：`warning`/`danger` 有自己的一条 QSS 规则，
    只改基础规则的话它们会**原样保留那个框**（候选 D 实测就是这样，
    而外审逐字抄出来的正是那两颗）。
    ⭐ **一条规则有几个特化分支，就要判几次** —— 改了基础忘了特化，
      屏幕上剩下的那几颗照样在冒充按钮。
    """
    shape = specimens[("chip:masterOff" if level == "masterOff"
                       else f"chip:{level or 'base'}")]
    assert shape["bottom_span"] < CLOSED_BOX_SPAN, (
        f"level={level!r} 的状态胶囊被画成了闭合的框："
        f"最底下那行 ink 横跨了 {shape['bottom_span']:.0%} 的宽度"
        f"（阈值 {CLOSED_BOX_SPAN:.0%}）。它一个都点不了，不该长按钮的样子。"
    )


def test_a_real_button_is_still_drawn_as_a_closed_box(specimens):
    """⭐ 阳性对照：真按钮**必须**仍然是闭合的框。

    缺了这一条，上一条可以靠「把全站的边框都删了」全绿 ——
    那样胶囊确实不像按钮了，代价是**按钮也不像按钮了**。
    """
    for name in ("secondaryButton", "actionButton"):
        span = specimens[name]["bottom_span"]
        assert span >= CLOSED_BOX_SPAN, (
            f"{name} 的闭合框没了（最底下那行只横跨 {span:.0%}）—— "
            "修胶囊别把按钮一起修了")


@pytest.mark.parametrize("level", [None, "info", "warning", "danger",
                                   "masterOff"])
def test_the_chip_still_has_something_on_its_left(specimens, level):
    """反面守卫：也不许把胶囊改成「什么都不画」。

    ⭐ 左侧那条色条是它**还在说「这是一组状态项」**的唯一凭据；
    全去掉的话一排短语会糊成一句话（候选 C 那一版的风险）。
    ⚠ 外审四个候选 12/12 全答「分得开」，所以这一条不是靠票数立的，
      是**给未来的自己留的下界**：别哪天顺手把这条也删了。
    """
    shape = specimens[("chip:masterOff" if level == "masterOff"
                       else f"chip:{level or 'base'}")]
    assert shape["left_rows"] >= LEFT_BAR_ROWS, (
        f"level={level!r} 的胶囊左边几乎什么都没画"
        f"（只有 {shape['left_rows']:.0%} 的行有 ink）—— 一排状态会糊成一句话")


# ------------------------------------------------------------------ 分母

@pytest.fixture(scope="module")
def live_chips(main_window, qapp):
    """全站还剩多少颗胶囊、分布在几页。⭐ **数个数不需要字体**，所以这条能跑。"""
    pages, total = set(), 0
    for page_id in list(main_window._page_names.keys()):
        try:
            main_window.ensure_page_loaded(page_id)
            main_window.show_page(page_id, animated=False, force=True)
            qapp.processEvents()
        except Exception:                               # noqa: BLE001
            continue
        page = main_window.pages.get(page_id)
        if page is None:
            continue
        chips = [w for w in page.findChildren(QLabel)
                 if w.objectName() == CHIP and w.isVisibleTo(page)
                 and (w.text() or "").strip()]
        if chips:
            pages.add(page_id)
            total += len(chips)
    return pages, total


def test_no_status_chip_is_allowed_to_wrap(main_window, qapp):
    """状态胶囊按设计就是**一行**，不许有折行的可能（RN-121 的又一次现身）。

    ⚠ `ui_style_applier.fix_text_display()` 给**每一个** QLabel 无条件
    `setWordWrap(True)`，而一个会折行的 QLabel 在横排里**把自己的宽度报小**
    ——实测 `hint 128px` 而文字要 130px，于是它折成两行、比同排高 4px，
    RN-185 那条「同排徽章高度一致」判红。
    ⭐ 这条缺陷**本来只有排版审计那道门看得见**（它不是 pytest），
      而排版审计要跑 510 个组合、几分钟；这里补一条秒级的。
    ⚠ 判 `wordWrap()` 而不是判高度：这个进程没有中文字体，
      高度量出来的是一个用户看不到的版面（见本文件开头）。
    """
    wrapping = []
    seen_chips = 0
    for page_id in must_scan(list(main_window._page_names.keys()),
                             "主窗注册的页面 id", least=20):
        try:
            main_window.ensure_page_loaded(page_id)
            main_window.show_page(page_id, animated=False, force=True)
            qapp.processEvents()
        except Exception:                               # noqa: BLE001
            continue
        page = main_window.pages.get(page_id)
        if page is None:
            continue
        for chip in page.findChildren(QLabel):
            if chip.objectName() != CHIP:
                continue
            seen_chips += 1
            if chip.wordWrap():
                wrapping.append(f"{page_id} · {chip.text().strip()!r}")
    # ⭐ 分母是**真的量到的状态胶囊**。上面那圈 `except: continue` 会把建不出来的页
    #   悄悄踢出分母 —— 全踢光时「没有胶囊折行」是一句自动为真的话。
    must_scan(range(seen_chips), "全站量到的状态胶囊", least=10)
    assert not wrapping, (
        f"{len(wrapping)} 颗状态胶囊还允许折行 —— 折行的 QLabel 会把自己的宽度"
        "报小，然后折成两行、比同排高一截：\n  "
        + "\n  ".join(wrapping[:10])
        + "\n⚠ 光 `setWordWrap(False)` 不够，会被 `fix_text_display()` 改回去，"
        "要走 `keep_single_line()`。")


def test_the_specimen_is_representative_of_the_whole_site(live_chips):
    """⭐ 标本只有一颗，所以必须证明**全站那 122 颗走的是同一条 QSS 规则**。

    量的是「有多少颗控件叫 `audioStatusChip`、分布在几页」——
    这一条不依赖字体，所以在 offscreen 进程里照样成立。
    ⚠ 它同时是上面那些标本判据的**分母守卫**：哪天有人把胶囊改成别的
    objectName，标本判据会继续绿着，而这一条会红。
    """
    pages, total = live_chips
    assert total >= MIN_CHIPS, (
        f"全站只剩 {total} 颗 `{CHIP}`（下限 {MIN_CHIPS}）—— "
        "要么扫描器塌了，要么胶囊换了名字，而标本判据是按名字挑的")
    assert len(pages) >= MIN_PAGES, (
        f"只覆盖 {len(pages)} 页（下限 {MIN_PAGES}）")


# ------------------------------------------------------------------ 颜色

def _contrast(a, b) -> float:
    from core.utils.contrast import contrast_ratio

    return contrast_ratio(a, b)


@pytest.mark.parametrize("theme", THEMES)
def test_the_chip_stays_legible_in_every_theme(theme, qapp):
    """⚠ 改了配色一定要重算对比度 —— 八个主题，一个都不许漏。

    ⚠⚠ **色条那一格量的是渲染出来的像素，不是 token 算出来的假设值。**
    第一版写的是 `contrast_ratio(c.text_tertiary, c.bg_card)` ——
    那等于在问「**如果**用 `text_tertiary` 画会怎样」，
    于是我把 QSS 里的色条换成几乎看不见的 `border_secondary`（1.02:1）之后，
    这条判据**照样全绿**（破坏验证当场逮到）。
    ⭐⭐ 「文件里有没有」之外还有第三种走神：**判据算的是一个和屏幕无关的量。**

    ⭐ 文字那几格仍然按 token 算，因为 `Theme._chip_text()` 收敛的目标一直是
    `bg_card`（它自己的注释：「薄染会让实际对比只增不减」）——
    所以去掉薄染**不可能**让文字更难读，这一条前人已经防住了。
    ⚠ 最紧的一格是 `purple` 的 danger 字 **4.52:1**，离 4.5 只有 0.02 ——
    动 `error` 或 `bg_card` 任何一个都要重跑这条。
    """
    from theme_manager import get_theme_manager

    tm = get_theme_manager()
    before = tm.current_theme_name
    try:
        tm.set_theme(theme)
        # ⚠ **每个 level 各量一次。** 只量 `info` 是不够的：那几条 level 规则
        #   各自都写了自己的 `border-left`，改坏**基础**那条时 `info` 照样是好的
        #   —— 破坏验证当场逮到这条空转。
        #   ⭐ **一条规则有几个特化分支，判据就得走几遍**（本文件第二次记这句）。
        for level in (None, "info", "warning", "danger"):
            shape = _render_specimen(qapp, CHIP, level)
            assert shape is not None and shape["bar"] is not None, (
                f"{theme}/{level}：胶囊标本左边一个像素都没画出来")
            bar = _contrast(_hexed(shape["bar"]), _hexed(shape["card"]))
            assert bar >= AA_NON_TEXT, (
                f"{theme}/level={level!r}：**渲染出来的**左侧色条 "
                f"{_hexed(shape['bar'])} 对卡底 {_hexed(shape['card'])} "
                f"只有 {bar:.2f}:1（下限 {AA_NON_TEXT}）"
                " —— 去掉框之后它是胶囊唯一画出来的东西，看不见就等于没有")

        c = tm.current_theme.colors
        card = c.bg_card
        for label, text_colour in (
                ("中性", c.text_secondary),
                ("warn", tm.current_theme._chip_text(c.accent_warm)),
                ("danger", tm.current_theme._chip_text(c.error))):
            ratio = _contrast(text_colour, card)
            assert ratio >= AA_TEXT, (
                f"{theme}：{label} 胶囊文字对卡底只有 {ratio:.2f}:1"
                f"（下限 {AA_TEXT}）")
    finally:
        tm.set_theme(before)


@pytest.mark.parametrize("theme", THEMES)
def test_a_problem_chip_still_speaks_in_colour(theme, qapp):
    """警告/错误级**必须**仍然和普通级颜色不同 —— 颜色还要携带信息。

    QSS 里那条设计意图（v5 Phase 6）原话：「正常态统一中性灰、只用文字色标记语义；
    异常态保持满色块，确保一眼可见」⇒ 去掉满色块之后，**字色**就是唯一的载体。
    实测外审仍 3/3 认出 `basic` 那两颗真警告，说明颜色接得住。
    """
    from theme_manager import get_theme_manager

    tm = get_theme_manager()
    before = tm.current_theme_name
    try:
        tm.set_theme(theme)
        c = tm.current_theme.colors
        neutral = c.text_secondary.lower()
        for label, colour in (("warn", tm.current_theme._chip_text(c.accent_warm)),
                              ("danger", tm.current_theme._chip_text(c.error))):
            assert colour.lower() != neutral, (
                f"{theme}：{label} 级胶囊的字色和普通级一模一样（{colour}）"
                " —— 去掉满色块之后，颜色是它唯一还能说话的通道")
            saturation = colorsys.rgb_to_hsv(
                *(int(colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)))[1]
            assert saturation > 0.15, (
                f"{theme}：{label} 级字色 {colour} 饱和度只有 {saturation:.2f}，"
                "读起来和中性灰没区别")
    finally:
        tm.set_theme(before)
