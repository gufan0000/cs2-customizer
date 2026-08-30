# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""crosshair：页面说的两件事，和它真正做的对不上（RN-410 / RN-415）。

## RN-415：五条滑块里有一条对「自定义」完全不生效，而界面一视同仁

⚠ 先说**我差点量错的那一次**：AST 扫 `_paint_custom` 里出现过的**属性名**，
`size` 报「没用到」—— 而它是那个函数的**形参**（`_paint_custom(painter, frame,
cx, cy, size, grow=0)`，`scale = size / 15.0`）。
⭐ **拿「属性名」当「用到了哪些参数」的代理，量的是另一件事。**

⇒ 这份判据**不查代码**，直接量画面：把自定义准心画两遍（同一条滑块取两个值），
比较像素。**改了画面 = 生效；一个像素不动 = 不生效。**

实测（`dark`，一张十字 + 四角的 30×30 图案）：

    size        ✓ 改了画面
    thickness   ✓ 改了画面
    gap         ✗ **一个像素都没动**
    outline     ✓ 改了画面
    alpha       ✓ 改了画面

而五条滑块在页面上**全部 enabled**，`gap` 的 tooltip 还写着
「准星中心留空多少像素。0 表示两条线穿过圆心，会挡住瞄准点。」
—— 那句话在自定义样式下是**假的**。

⭐⭐ 这条判据**不硬写「gap」**：它自己把五条滑块各量一遍，
凡是「在这个样式下改不动任何像素」的，就必须在这个样式下是禁用的。
⇒ 哪天有人加了第六条对自定义无效的滑块，它一样会红。
**一个自己算得出分母的判据，比一份手抄名单活得久。**

## RN-410：唯一一句解释导入格式的话，**扩展名是错的**

    导出默认文件名   my_crosshair.xchr
    两个文件对话框   "准心文件 (*.xchr);;所有文件 (*.*)"
    拖拽接受        (".xchr", ".json")
    而页面那句话     「只认本软件导出的 .json；CS2 官方分享码（CSGO-…）暂不支持。」

⭐ 用户照那句话去找 `.json`，而软件导出的是 `.xchr`，文件对话框也只列 `.xchr`。
⚠ 而且那句话在 **y=1000**，导入按钮在 **y=681** —— 它在按钮**下方 319px**、
且在 750px 折线之外。⭐ CLAUDE.md 那条网站教训：
**解释性文字放在困惑发生的位置之前，不是页尾；放页尾 = 没放。**

⇒ 判据要求：那句话里出现的扩展名，必须**和对话框过滤器真源一致**
（从产品代码里取，不在判据里写第二份字面量 —— 抄一份就等于给自己埋一个
「两边各说各的」的坑，而那正是这条缺陷本身的形状）。
"""
from __future__ import annotations

import re

import pytest
from PySide6.QtWidgets import QLabel, QSlider

# ⚠ 主窗夹具用共享那一份，不抄第二份（RN-002 那 9 份名单的形态）。
from tests.test_master_switch_effect_is_honest import (  # noqa: E402
    main_window as _shared_main_window,
)

main_window = _shared_main_window

PAGE = "crosshair"

#: 「大小与粗细」那张卡里的五条滑块。⚠ 这份名单只用来**找控件**，
#: 不用来判断谁生效 —— 谁生效由像素说了算（见 `dead_sliders`）。
SLIDERS = {
    "size_slider": "size",
    "thickness_slider": "thickness",
    "gap_slider": "gap",
    "outline_slider": "outline",
    "alpha_slider": "alpha",
}

#: 每条滑块拿来对比的两个值（都在各自的 min/max 之内）。
PROBE_VALUES = {
    "size": (20, 40),
    "thickness": (2, 6),
    "gap": (0, 18),
    "outline": (0, 3),
    "alpha": (100, 30),
}


def _custom_points():
    """一张十字 + 四角的 30×30 图案 —— 够让任何一条参数都有机会改到像素。"""
    points = [(i, 15) for i in range(4, 27)] + [(15, i) for i in range(4, 27)]
    return points + [(6, 6), (24, 6), (6, 24), (24, 24)]


def _render(params):
    """按给定参数把自定义准心画一遍，返回像素字节。"""
    from PySide6.QtGui import QColor, QImage, QPainter

    import crosshair_overlay as ov

    frame = ov.CrosshairFrame.__new__(ov.CrosshairFrame)
    colour = QColor(0, 255, 0)
    colour.setAlpha(int(255 * params["alpha"] / 100))
    frame.custom_points = _custom_points()
    frame.thickness = params["thickness"]
    frame.rotation = 0
    frame.color = colour
    frame.outline_color = QColor(0, 0, 0, 255)
    frame.gap = params["gap"]
    frame.size = params["size"]

    image = QImage(120, 120, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        if params["outline"]:
            ov._paint_custom(painter, frame, 60, 60, params["size"],
                             grow=params["outline"])
        ov._paint_custom(painter, frame, 60, 60, params["size"])
    finally:
        painter.end()
    return image.constBits().tobytes()


@pytest.fixture(scope="module")
def dead_sliders(qapp):
    """**自己算出来**：自定义样式下，哪几条滑块一个像素都改不动。"""
    base = dict(size=20, thickness=2, gap=0, outline=0, alpha=100)
    baseline = _render(base)
    dead, alive = [], []
    for key, (low, high) in PROBE_VALUES.items():
        probe = dict(base)
        probe[key] = low if base[key] != low else high
        if _render(probe) == baseline:
            probe[key] = high
            if _render(probe) == baseline:
                dead.append(key)
                continue
        alive.append(key)
    return {"dead": dead, "alive": alive, "baseline": baseline}


def test_the_probe_can_tell_a_live_slider_from_a_dead_one(dead_sliders):
    """⭐ 空转守卫：先证明这把尺子**分得出**死活，再让它去指认谁是死的。

    ⚠ 少了这一条，「渲染整个没跑起来」和「五条滑块全是死的」在结果上一样。
    """
    assert dead_sliders["alive"], (
        "五条滑块**一条都没量出变化** —— 那不是缺陷，是渲染这一步就没成")
    assert len(dead_sliders["alive"]) >= 3, (
        f"只有 {dead_sliders['alive']} 量出了变化，其余全判死 —— 尺子可疑")


def _open_page(main_window, qapp):
    main_window.ensure_page_loaded(PAGE)
    main_window.show_page(PAGE, animated=False, force=True)
    qapp.processEvents()
    page = main_window.pages.get(PAGE)
    assert page is not None, "crosshair 没加载出来"
    return page


def _select_style(page, qapp, style_value):
    for button in page.style_group.buttons():
        if button.property("style_value") == style_value:
            button.setChecked(True)
            break
    else:                                               # noqa: PLW0120
        pytest.fail(f"找不到样式单选 {style_value!r}")
    qapp.processEvents()


def test_a_slider_that_changes_nothing_is_disabled(main_window, qapp,
                                                   dead_sliders):
    """⭐⭐ 主刀：在某个样式下改不动任何像素的滑块，**必须在那个样式下禁用**。

    ⭐ 判据**不点名 `gap`** —— 它自己量出谁是死的。
    哪天有人加了第六条对自定义无效的滑块，这条一样会红。
    **一个自己算得出分母的判据，比一份手抄名单活得久。**
    """
    assert dead_sliders["dead"], (
        "没量出任何一条死滑块 —— 如果真的都活了，把这条判据和 RN-415 一起结掉")
    page = _open_page(main_window, qapp)
    was = None
    for button in page.style_group.buttons():
        if button.isChecked():
            was = button.property("style_value")
    try:
        _select_style(page, qapp, "custom")
        bad = []
        for attr, key in SLIDERS.items():
            if key not in dead_sliders["dead"]:
                continue
            slider = getattr(page, attr, None)
            if isinstance(slider, QSlider) and slider.isEnabled():
                bad.append(f"{attr}（{key}）")
        assert not bad, (
            "这些滑块在「自定义」样式下**一个像素都改不动**，却还是可点的：\n  "
            + "\n  ".join(bad)
            + "\n⇒ 可点却没反应是一条缺陷（RN-179）；批 23 之后禁用态是看得出来的。")
    finally:
        if was:
            _select_style(page, qapp, was)


def test_the_sliders_that_do_work_stay_usable(main_window, qapp, dead_sliders):
    """⭐ 阳性对照：真正生效的那几条，在自定义样式下**必须仍然可用**。

    缺了这一条，上一条可以靠「自定义样式下把五条全禁掉」全绿 ——
    而那会把一个能用的功能砍掉四条（批 17：大面积置灰读作「软件坏了」）。
    """
    page = _open_page(main_window, qapp)
    was = next((b.property("style_value") for b in page.style_group.buttons()
                if b.isChecked()), None)
    try:
        _select_style(page, qapp, "custom")
        dead = []
        for attr, key in SLIDERS.items():
            if key not in dead_sliders["alive"]:
                continue
            slider = getattr(page, attr, None)
            if isinstance(slider, QSlider) and not slider.isEnabled():
                dead.append(f"{attr}（{key}）")
        assert not dead, (
            "这几条滑块对自定义准心**是真的有用**，不许一起禁掉：\n  "
            + "\n  ".join(dead))
    finally:
        if was:
            _select_style(page, qapp, was)


def test_a_normal_style_keeps_every_slider(main_window, qapp):
    """反面守卫：换回普通样式，五条**全部**必须可用。

    ⭐ 上一条可以靠「永远禁用 gap」通过 —— 而 `gap` 对十字/T 型是有用的。
    **门禁条件要跟着样式走，不是跟着控件走**（RN-145 / RN-439 同一族）。
    """
    page = _open_page(main_window, qapp)
    was = next((b.property("style_value") for b in page.style_group.buttons()
                if b.isChecked()), None)
    try:
        _select_style(page, qapp, "crosshair")
        off = [attr for attr in SLIDERS
               if isinstance(getattr(page, attr, None), QSlider)
               and not getattr(page, attr).isEnabled()]
        assert not off, (
            f"普通样式下这几条滑块被禁着：{off} —— 它们在这里是有用的")
    finally:
        if was:
            _select_style(page, qapp, was)


# ------------------------------------------------------- RN-410：说的和做的

def _dialog_extensions() -> set[str]:
    """产品代码里那个文件对话框**真正接受**的扩展名。

    ⚠ 从源码里取，不在判据里写第二份字面量 —— 抄一份就等于给自己埋一个
    「两边各说各的」的坑，而那正是这条缺陷本身的形状。
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "pages" / "crosshair_page.py").read_text(encoding="utf-8")
    found = set(re.findall(r"准心文件 \(\*(\.[a-z]+)\)", src))
    assert found, "在 crosshair_page.py 里找不到文件对话框的过滤器 —— 判据在空转"
    return found


def _drop_extensions() -> set[str]:
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "pages" / "crosshair_page.py").read_text(encoding="utf-8")
    m = re.search(r"enable_file_drop\(self,\s*\(([^)]*)\)", src)
    assert m, "找不到拖拽接受的扩展名 —— 判据在空转"
    return set(re.findall(r"\"(\.[a-z]+)\"", m.group(1)))


def _export_extension() -> str:
    """导出时**默认写出来**的那个扩展名（真源，不在判据里抄第二份）。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "pages" / "crosshair_page.py").read_text(encoding="utf-8")
    m = re.search(r"\"my_crosshair(\.[a-z]+)\"", src)
    assert m, "找不到导出的默认文件名 —— 判据在空转"
    return m.group(1)


def test_no_sentence_claims_we_export_a_format_we_do_not(main_window, qapp):
    """⭐⭐ 凡是说「本软件导出的 X」，那个 X 必须真的是我们导出的东西。

    改前实测：页面写「只认本软件**导出的 .json**」，
    而导出默认写的是 `my_crosshair.xchr`，两个文件对话框也只列 `*.xchr`。
    ⭐ **用户照那句话去找一个软件根本不产出的文件。**

    ⚠ 第一版判据把「拖拽也收 .json」算进了「接受的格式」，于是这句话
    **算不上假**、判据全绿 —— 可这句话说的不是「能拖进来什么」，
    是「**本软件导出的**是什么」。
    ⭐ **一句话是真是假，要拿它自己声称的那件事去比，不是拿一个更宽的事实去比。**
    """
    page = _open_page(main_window, qapp)
    exported = _export_extension()
    lying, examined = [], 0
    for label in page.findChildren(QLabel):
        if not label.isVisibleTo(page):
            continue
        text = label.text() or ""
        # ⚠ 只取**紧跟在「导出的」后面**的那个扩展名。
        # 第一版收的是「这句话里出现过的所有扩展名」，于是修好之后
        # 「收本软件导出的 .xchr（**.json** 也能直接拖进来）」里那个
        # 讲拖拽的 `.json` 被当成了「我们导出 .json」，判据照红。
        # ⭐ **一个为某句断言划的范围，套到相邻的另一句上就是诬告**
        #   （批 26 那张词表的同一个形状）。
        for claimed in re.findall(r"导出的\s*(\.[a-z]{2,5})", text):
            examined += 1
            if claimed != exported:
                lying.append(f"{text[:70]!r} 说我们导出 {claimed}，"
                             f"实际导出的是 {exported}")
    assert examined, (
        "这一页上没有任何一句在说「本软件导出的 X」—— 判据在空转。"
        "如果那句解释被删了，先确认用户还有别的地方知道导入收什么")
    assert not lying, (
        "这一页在用一个软件不产出的扩展名教用户找文件：\n  " + "\n  ".join(lying))


def test_the_import_button_itself_explains_what_it_takes(main_window, qapp):
    """⭐ 那句解释必须挂在**导入按钮**身上，不能只躺在页尾。

    改前实测：说明在 y=1000，而导入按钮在 y=681 —— 它在按钮**下方 319px**，
    且在 750px 折线之外，按钮自己的 tooltip 是**空的**。
    ⭐ **解释性文字放在困惑发生的位置之前，不是页尾；放页尾 = 没放**
    （CLAUDE.md 那条网站教训，桌面版第二次用上）。
    """
    page = _open_page(main_window, qapp)
    button = page.action_bar.extra_btn
    assert "导入" in button.text(), (
        f"底栏第三颗按钮不是导入了（{button.text()!r}）—— 判据在空转")
    tip = button.toolTip() or ""
    accepted = _dialog_extensions() | _drop_extensions()
    assert tip.strip(), "「导入准心」按钮没有任何说明 —— 它只认某几种文件"
    assert any(ext in tip for ext in accepted), (
        f"导入按钮的说明里没提它到底认什么（现在是 {tip!r}），"
        f"实际接受 {sorted(accepted)}")
    assert "CSGO" in tip or "分享码" in tip, (
        "导入按钮的说明没提**分享码不支持** —— 而那正是玩家手上现成的东西，"
        "也是这条立案里票数最高的那一半")


# ------------------------------------------- RN-414：入口不在第一屏上

def test_the_preview_becomes_the_entry_when_custom_is_blank(main_window, qapp):
    """⭐⭐ 选了「自定义」而一个点都没画时，那块预览框**必须真的可点**。

    天然对照实验（同一页、同一状态、同一个模型，变量只有"看不看得见折线以下"）：

        窗口图（用户真正看到的那一屏）  ①3/3「不知道」   ②3/3「不知道」
        整页无折线图                  ①3/3「绘制准心」 ②3/3「知道，在这一屏上」

    ⇒ 入口不是难找，是**根本不在第一屏上**（单选 y=456、按钮 y=948，
    相距 492px，而可视区 750px）。

    ⚠ 不能就地再放一颗「绘制准心」—— `test_draw_crosshair_appears_exactly_once`
    明令这一屏只许有一颗（RN-404 族）。
    ⭐⭐ 而批 12 的复跑里我自己造过另一半：给预览框加空状态文字之后，
    4 发改说「大面积黑框**看着像画板却点不动**」。那句抱怨是对的，
    而修法不是让它别像画板 —— 是**让它真的可点**。
    """
    from PySide6.QtCore import Qt

    page = _open_page(main_window, qapp)
    was = next((b.property("style_value") for b in page.style_group.buttons()
                if b.isChecked()), None)
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(page, "_custom_style_is_blank", lambda: True)
        page._update_preview()
        qapp.processEvents()
        assert page._preview_is_entry, "空白的自定义预览框不是入口"
        assert page.preview_frame.cursor().shape() == Qt.PointingHandCursor, (
            "它可点，却不是手型光标 —— 可点的东西该长得可点")
        assert page.preview_frame.property("clickable") == "true", (
            "没挂上 `clickable` 属性 ⇒ QSS 那圈边不会出现，"
            "而**手型光标只有把鼠标移过去才看得到**，"
            "实测的困惑恰恰发生在还没移过去的时候")
        assert "点这里" in (page.preview_label.text() or ""), (
            f"预览框里没写「点这里」：{page.preview_label.text()!r}")
    finally:
        mp.undo()
        if was:
            _select_style(page, qapp, was)
        page._update_preview()
        qapp.processEvents()


def test_clicking_the_blank_preview_opens_the_editor(main_window, qapp):
    """接线守卫：**长得可点** ≠ **点了有事发生**（RN-145 那条的老形态）。"""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    page = _open_page(main_window, qapp)
    mp = pytest.MonkeyPatch()
    opened = []
    try:
        mp.setattr(page, "_custom_style_is_blank", lambda: True)
        mp.setattr(page, "_open_custom_editor", lambda: opened.append(1))
        page._update_preview()
        qapp.processEvents()
        event = QMouseEvent(QMouseEvent.Type.MouseButtonRelease,
                            QPointF(10.0, 10.0), QPointF(10.0, 10.0),
                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        page.preview_frame.mouseReleaseEvent(event)
        assert opened, "点了这块「点这里开始画」的框，什么都没发生"
    finally:
        mp.undo()
        page._update_preview()
        qapp.processEvents()
    assert QPoint  # noqa: B018  （保持 import 被用到）


def test_a_drawn_preview_is_not_clickable(main_window, qapp):
    """⭐ 反面守卫：画过之后，这块框**必须变回不可点**。

    一个"有时候能点、有时候不能点、而外观从不变化"的东西，
    比一个从来不能点的还糟 —— 那正是批 26 修掉的那条缺陷的镜像。
    """
    from PySide6.QtCore import Qt

    page = _open_page(main_window, qapp)
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(page, "_custom_style_is_blank", lambda: False)
        page._update_preview()
        qapp.processEvents()
        assert not page._preview_is_entry, "画过之后它还是入口"
        assert page.preview_frame.cursor().shape() != Qt.PointingHandCursor, (
            "画过之后它还挂着手型光标 —— 那是在说「点我」，而点了没用")
        assert page.preview_frame.property("clickable") != "true"
        assert not (page.preview_frame.toolTip() or "").strip(), (
            "画过之后还留着「点这里开始画」的说明")
    finally:
        mp.undo()
        page._update_preview()
        qapp.processEvents()
