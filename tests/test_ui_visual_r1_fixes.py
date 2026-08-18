# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""UI 视觉巡检 R1 的六条修复判据（2026-08-16）。

这六条**几何全部合法**，所以 `layout_overflow_audit` 一路绿灯，是靠离屏截图
才看出来的。报告见 `docs/quality/UI视觉巡检_R1_20260816.md`。

⚠ **判据一律避开"文字有没有画出来"**：测试跑在 offscreen 平台上，
本机 offscreen 的 `QFontDatabase.families()` 返回 **0**，字全是方块，
拿渲染像素判文字只会得到假红/假绿。所以这里判的是**根因本身**：
  · 盒模型冲突（min > max）——Qt 取 min，那才是形变的机制；
  · QSS 引用的图片**是不是一个真实存在的文件**——`data:` URI 不是；
  · 容器视口装不装得下内容；
  · 切页后当前导航项在不在可视区。
"""
from __future__ import annotations

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


#: 本机 offscreen 平台的字体库是**空的**，不补一个真字体的话度量全是假的
#: ——实测侧栏导航按钮会被量成 480px 高（比视口还高），于是
#: "当前项在不在可视区"这个判据**永远不可能为真**，回退验证直接把它抓成假绿。
_FALLBACK_FONT = r"C:/Windows/Fonts/msyh.ttc"


def _need_real_fonts(app):
    from PySide6.QtGui import QFontDatabase

    if QFontDatabase.families():
        return
    if not os.path.exists(_FALLBACK_FONT):
        pytest.skip("离屏平台没有字体，且找不到可加载的系统字体，度量不可信")
    if QFontDatabase.addApplicationFont(_FALLBACK_FONT) < 0:
        pytest.skip("字体加载失败，度量不可信")


def _shown_window(app):
    """建一个参与布局但**永不映射到屏幕**的主窗。

    ⚠ **必须调 `show()`**：不调的话所有子控件 `isVisible()` 恒为 False，
    任何"某控件可不可见"的判据都会被整段跳过——**空转成绿**。
    回退验证第一次跑就是这么抓到我的：断点明明把修复删了，判据照样绿。
    """
    from PySide6.QtCore import Qt

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    app.processEvents()
    win.setMinimumSize(1280, 800)
    win.resize(1280, 800)
    app.processEvents()
    return win


# ---------------------------------------------------------------- QSS 图片资源

_IMAGE_URL = re.compile(r"image:\s*url\(([^)]*)\)")


def _all_theme_stylesheets():
    from theme_manager import get_theme_manager

    tm = get_theme_manager()
    original = tm.current_theme_name if hasattr(tm, "current_theme_name") else None
    out = {}
    for name in ("dark", "light", "green", "purple", "ocean", "warm", "rose", "contrast"):
        try:
            tm.set_theme(name)
            out[name] = tm.get_stylesheet()
        except Exception:
            continue
    if original:
        try:
            tm.set_theme(original)
        except Exception:
            pass
    return out


def test_qss_never_uses_data_uri_images(app):
    """**QSS 的 `image:` 不许出现 `data:` URI —— Qt 根本不认。**

    这是本轮最值钱的一条判据，因为它拦的是**一整类**问题而不是一个实例。
    实测 `QPixmap.load("data:image/svg+xml;base64,...")` 返回 **False**：
    不报错、不打日志，**那个图标只是永远不显示**。本项目因此栽过两次——
    复选框对勾（所有已勾选的框都只是个纯色方块，看不出勾没勾）和下拉箭头。
    """
    for theme, qss in _all_theme_stylesheets().items():
        for url in _IMAGE_URL.findall(qss):
            assert not url.strip().strip('"\'').startswith("data:"), (
                f"主题 {theme} 的 QSS 里有 data: URI 图片。Qt 不支持，写了也不显示。"
                "请用 theme_manager._qss_icon() 生成真实 PNG 文件再引用。"
            )


def test_qss_image_urls_point_to_existing_files(app):
    """引用一个不存在的路径，症状和 data URI 一模一样（静默不显示）。"""
    for theme, qss in _all_theme_stylesheets().items():
        for url in _IMAGE_URL.findall(qss):
            path = url.strip().strip('"\'')
            if path.startswith(":/"):        # Qt 资源路径，另当别论
                continue
            assert os.path.exists(path), f"主题 {theme} 的 QSS 引用了不存在的图片: {path}"


def _row_widths(path, alpha_min=40):
    """PNG 逐行的非透明像素数。三角形应当逐行收窄，实心方块则每行等宽。"""
    from PySide6.QtGui import QImage

    img = QImage(path)
    assert not img.isNull(), f"读不出图: {path}"
    rows = []
    for y in range(img.height()):
        n = sum(1 for x in range(img.width()) if img.pixelColor(x, y).alpha() > alpha_min)
        rows.append(n)
    return [n for n in rows if n]


def test_combobox_arrow_is_drawn_with_an_image(app):
    """`QComboBox::down-arrow` 必须靠一张**图片**来画。

    不能靠"透明左右边框 + 实心上边框"拼三角——那是 Web CSS 的技巧，
    Qt 不认，会把四条边照实心画出来。这条判据盯的是"有没有 image:"，
    与"图片长得对不对"是两回事，缺一条都补不上另一条的洞。
    """
    for theme, qss in _all_theme_stylesheets().items():
        block = re.search(r"QComboBox::down-arrow\s*\{([^}]*)\}", qss)
        assert block, f"主题 {theme} 找不到 QComboBox::down-arrow 规则"
        body = block.group(1)
        assert "image:" in body, (
            f"主题 {theme} 的下拉箭头没有用图片。用 border 拼三角形 Qt 不认，"
            "会画成实心方块（全应用 233 个下拉框都会中招）。")
        assert "border-left" not in body and "border-top" not in body, (
            f"主题 {theme} 的下拉箭头又用回了 border 三角形技巧")


def test_down_arrow_icon_is_a_triangle_not_a_block(app):
    """下拉箭头必须是**三角形**。

    原先用的是"透明左右边框 + 实心上边框"这个 **Web CSS 技巧**，
    Qt 的 QSS 不认——它不会把透明边框折成三角，而是四条边照实心画，
    于是全应用 233 个下拉框（19 个页面）右边**全是紫色实心小方块**。
    """
    from theme_manager import _draw_down_arrow, _qss_icon, get_theme_manager

    color = get_theme_manager().current_theme.colors.accent_primary
    path = _qss_icon("down_arrow", color, 10, 6, _draw_down_arrow)
    assert path, "下拉箭头图标没生成出来"
    widths = _row_widths(path)
    assert len(widths) >= 4, "箭头图太矮，判不出形状"
    assert widths[0] > widths[-1] * 2, (
        f"箭头逐行宽度 {widths} 没有收窄 —— 这是个方块不是三角形")


def test_checkbox_check_icon_has_ink(app):
    """已勾选的复选框得真有个勾。原先是 data URI，勾一直没画出来。"""
    from theme_manager import _draw_check, _qss_icon, get_theme_manager

    color = get_theme_manager().current_theme.colors.text_on_primary
    path = _qss_icon("check", color, 12, 12, _draw_check)
    assert path, "对勾图标没生成出来"
    assert sum(_row_widths(path)) > 20, "对勾图几乎是空的"


# ---------------------------------------------------------------- 盒模型冲突

def _assert_no_box_conflict(widget, label):
    """`setFixedSize()` 只压得住**最大**尺寸，QSS 的 `min-height` 会把最小尺寸
    顶上去，而 **Qt 在 min > max 时取 min** —— 帮助按钮就是这么从 24×24
    变成 24×42 的灰胶囊的。判据直接盯这个冲突本身。"""
    mn, mx = widget.minimumSize(), widget.maximumSize()
    assert mn.width() <= mx.width(), (
        f"{label}: 最小宽 {mn.width()} > 最大宽 {mx.width()}，Qt 会取最小值 → 形变")
    assert mn.height() <= mx.height(), (
        f"{label}: 最小高 {mn.height()} > 最大高 {mx.height()}，Qt 会取最小值 → 形变")
    assert widget.width() == widget.height(), (
        f"{label}: {widget.width()}x{widget.height()} 不是正方形，圆角会画成胶囊")


def test_help_button_box_model_is_consistent(app):
    from theme_manager import get_theme_manager
    from ui_help_panel import HelpButton

    previous = app.styleSheet()
    app.setStyleSheet(get_theme_manager().get_stylesheet())
    try:
        btn = HelpButton()
        btn.ensurePolished()
        _assert_no_box_conflict(btn, "帮助按钮")
        assert btn.styleSheet() == "", (
            "帮助按钮又开始自己写内联样式了。它会被 ui_style_applier 的清扫器"
            "抹掉（本类没声明 fp_keep_style），样式必须留在全局 QSS 里。")
    finally:
        app.setStyleSheet(previous)


def test_mode_toggle_button_box_model_is_consistent(app):
    from PySide6.QtWidgets import QPushButton

    from theme_manager import get_theme_manager

    previous = app.styleSheet()
    app.setStyleSheet(get_theme_manager().get_stylesheet())
    try:
        btn = QPushButton("⇔")
        btn.setObjectName("modeToggleIconButton")
        btn.setFixedSize(40, 40)
        btn.ensurePolished()
        _assert_no_box_conflict(btn, "模式切换按钮")
    finally:
        app.setStyleSheet(previous)


def test_every_nav_page_has_an_icon(app):
    """侧栏每一项都必须有图标。

    `get_page_icon()` 查不到就**静默返回空 QIcon**——不报错、不打日志。
    实测 `fun_afterlife`（死亡刷短视频）就这么漏了：28 项里只有它没图标，
    文字起始位置比同组其它项左移一截，看着像没对齐。
    判据直接比对"导航里有哪些页"和"图标表里有哪些页"，不依赖渲染。
    """
    from widgets.icon_provider import PAGE_ICON_MAP

    win = _shown_window(app)
    try:
        missing = [pid for pid in win.nav_buttons if pid not in PAGE_ICON_MAP]
        assert not missing, (
            f"这些侧栏页面在 PAGE_ICON_MAP 里没有图标，会静默渲染成空图标: {missing}")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_sidebar_mode_button_is_not_squeezed_into_a_square(app):
    """侧栏底部那个「紧凑模式 «」是**宽文字按钮**，不许被方形约束压扁。

    它和顶栏的方形图标按钮曾共用 `modeToggleButton` 这个 objectName，
    给共用选择器加 `min-width: 38px; max-width: 38px` 之后，
    这个按钮直接缩成 38px 方块、文字被裁成「奏模式」。
    修完重跑截图才发现——**给共用 objectName 加盒模型约束前，先搜谁在用。**
    """
    from PySide6.QtGui import QFontMetrics

    _need_real_fonts(app)
    win = _shown_window(app)
    try:
        btn = win._sidebar_mode_btn
        # ⚠ 基准**不能用 `sizeHint()`**：它自己也被 QSS 的 max-width 夹住了，
        # 于是"宽度 ≥ sizeHint"恒成立——回退验证第一次就是这么抓到这条假绿的。
        # 拿字体度量做基准才独立于盒模型。
        need = QFontMetrics(btn.font()).horizontalAdvance(btn.text())
        assert btn.width() >= need, (
            f"侧栏模式按钮实际宽 {btn.width()}px，装不下「{btn.text()}」"
            f"所需的 {need}px —— 文字会被裁成残字")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------- 容器与导航

def test_kill_icon_style_strip_viewport_fits_its_content(app):
    """风格库卡片条的视口不许比内容矮。

    它是 `ScrollBarAlwaysOff`（纵向），**裁掉的部分滚都滚不出来**。
    实测曾是视口 124px / 内容 127px，「＋导入」卡最后一行
    「zip / 动图 / 图片」被永久切掉 3px。
    """
    _need_real_fonts(app)
    win = _shown_window(app)
    try:
        win.show_page("kill_icon", animated=False)
        for _ in range(5):
            app.processEvents()
        page = win.pages["kill_icon"]
        need = max(page.style_strip.sizeHint().height(),
                   page.style_strip.minimumSizeHint().height())
        assert page.style_scroll.height() >= need, (
            f"卡片条视口 {page.style_scroll.height()}px 装不下 {need}px 的内容，"
            "而这个滚动区纵向是 AlwaysOff —— 被裁掉的部分用户永远看不到")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_nav_button_nudge_does_not_trust_a_not_yet_laid_out_height(app):
    """按钮还没被布局定高时，校正**不许**把它的高度当成 0。

    这是 2026-08-17 CI 连红三次的最终成因，本机一次都复现不出。
    判据每次带回来的数一模一样：`y=599 高=42 视口=623` ——
    **599 正好等于 623 − 24**，也就是滚动只保证了按钮左上角那个点可见
    （24 是 `ensureWidgetVisible` 的 ymargin），按钮自己那 42px 高度被当成了 0。
    三个不同页面、三次红、同一个 y，这就不是偶发而是算式漏了高度。

    判据**确定性地**造出那个局面：把按钮的高度按成 0 再调校正函数。
    不去复现"布局恰好没落定"那一瞬 —— 那种判据在本机永远绿，等于没有。
    """
    from PySide6.QtCore import QPoint

    _need_real_fonts(app)
    win = _shown_window(app)
    try:
        scroll = win._sidebar_scroll
        viewport = scroll.viewport()
        bar = scroll.verticalScrollBar()
        page_id = list(win._page_names.keys())[-1]
        btn = win.nav_buttons.get(page_id)
        assert btn is not None and btn.isVisible(), "拿不到导航按钮，判据在空转"

        win.show_page(page_id, animated=False)
        for _ in range(2):
            app.processEvents()

        # 造出 runner 上的局面：把按钮顶到"只有左上角在视口里"，且高度尚未定
        hint_h = btn.sizeHint().height()
        assert hint_h > 0, "sizeHint 高度为 0，判据自身失效"
        bar.setValue(0)
        app.processEvents()
        # 把滚动值调到"按钮顶边距视口底 24px"——正是 CI 上那个 y
        while (btn.mapTo(viewport, QPoint(0, 0)).y() > viewport.height() - 24
               and bar.value() < bar.maximum()):
            bar.setValue(bar.value() + 10)
            app.processEvents()
        # 造"布局还没给它定高"的状态。
        # ⚠ 试过两种更直白的写法，都不行，别再走回头路：
        #   · `btn.resize(w, 0)` —— 导航按钮有 QSS 最小高度，会被夹回 42；
        #   · 先 resize 再 `processEvents()` —— 事件泵一转布局就把高度改回去，
        #     校正拿到的又是正常值，判据空转成绿（回退验证当场逮到）。
        # 所以用一个**只在 height() 上说谎**的替身，直接考校正的算式。
        class _NotYetLaidOut:
            def __init__(self, real):
                self._real = real

            def mapTo(self, *args):
                return self._real.mapTo(*args)

            def height(self):
                return 0          # 布局还没给它定高

            def sizeHint(self):
                return self._real.sizeHint()

        win._nudge_nav_button_fully_into_view(scroll, _NotYetLaidOut(btn))
        app.processEvents()

        y = btn.mapTo(viewport, QPoint(0, 0)).y()
        assert y + hint_h <= viewport.height(), (
            f"校正把没定高的按钮当成了 0 高：y={y} sizeHint高={hint_h} "
            f"视口={viewport.height()} 滚动={bar.value()}/{bar.maximum()}")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_nav_button_nudge_fixes_a_short_scroll(app):
    """`ensureWidgetVisible` 少滚了一截时，必须有人把它补回来。

    上面那条判据量的是"正常切页之后在不在视口里"，而它在**本机永远是绿的** ——
    因为本机的布局在调用那一刻就已经落定了。真正会出事的是布局还没落定的机器：
    2026-08-17 CI 上 `hud_color` 的导航项就停在了视口外，本机怎么跑都复现不出。

    所以这条判据**不去复现那一瞬**，直接把滚动条按到一个故意不对的位置，
    然后只调校正函数：补不回来就红。这样它在任何机器上都判得准。
    """
    from PySide6.QtCore import QPoint

    _need_real_fonts(app)
    win = _shown_window(app)
    try:
        scroll = win._sidebar_scroll
        viewport = scroll.viewport()
        bar = scroll.verticalScrollBar()
        assert bar.maximum() > 0, "侧栏没溢出，这条判据在当前尺寸下证明不了任何事"

        # 挑一个在折叠线外的导航项（列表末尾那个一定在）
        page_id = list(win._page_names.keys())[-1]
        btn = win.nav_buttons.get(page_id)
        assert btn is not None and btn.isVisible(), "拿不到导航按钮，判据在空转"

        win.show_page(page_id, animated=False)
        for _ in range(2):
            app.processEvents()

        # 把滚动条按回顶部：现在这一项**一定**在视口外，等价于"少滚了一截"
        bar.setValue(0)
        app.processEvents()
        y_before = btn.mapTo(viewport, QPoint(0, 0)).y()
        assert y_before + btn.height() > viewport.height(), (
            "没造出「露在视口外」的局面，判据在空转")

        win._nudge_nav_button_fully_into_view(scroll, btn)
        app.processEvents()

        y_after = btn.mapTo(viewport, QPoint(0, 0)).y()
        assert 0 <= y_after and y_after + btn.height() <= viewport.height(), (
            f"校正之后 {page_id} 的导航项仍在视口外："
            f"y={y_after} 高={btn.height()} 视口={viewport.height()}")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_sidebar_recovers_when_content_grows_after_the_page_switch(app):
    """侧栏内容**在切页之后**才变高时，当前项必须自己滚回可视区。

    这是 2026-08-17 CI 连红三次的真正成因，本机怎么调窗口尺寸都复现不出：
    切页那一刻算好了滚动位置，**之后**侧栏内容才变高（分组展开、图标换色、
    字体度量在别的机器上不一样），上一次计算于是作废，当前项被挤出视口。
    实测数据 `crosshair(y=599 高=42 视口=623 滚动=61/998)` ——
    滚动条才 61/998，**明明有的是空间可滚，就是没人去滚**。

    前两版修复都失败了，因为它们都在切页那一瞬间测量：
    ① 只补一次 —— 和 `ensureWidgetVisible` 量的是同一份陈旧布局；
    ② 加 0ms singleShot —— 内容是在那之后才变高的，一样赶不上。
    真正管用的是**事件驱动**：盯住侧栏内容的 Resize，它说变完了才算数。

    判据照着这个成因复现：切页 → **从当前项上方**把内容顶下来 → 它必须自己滚回来。
    **不赌时序、不依赖机器快慢**，任何机器上判得一样准。

    ⚠ 第一版是往容器**底部**加高度，回退验证当场判它假绿 —— 底部加空间时
    上面各项的位置根本不变，当前项压根没离开过视口，那是在测一件永远不会
    失败的事。要把它顶出去，必须撑高**它上面**的东西。
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QWidget

    _need_real_fonts(app)
    win = _shown_window(app)
    try:
        viewport = win._sidebar_scroll.viewport()
        container = win._sidebar_nav_container
        for page_id in ("hud_color", "about"):
            btn = win.nav_buttons.get(page_id)
            if btn is None or not btn.isVisible():
                continue
            win.show_page(page_id, animated=False)
            for _ in range(2):
                app.processEvents()

            # 在最上面塞一块高度，把下面所有导航项一起往下顶
            spacer = QWidget(container)
            spacer.setFixedHeight(400)
            container.layout().insertWidget(0, spacer)
            for _ in range(3):
                app.processEvents()

            y = btn.mapTo(viewport, QPoint(0, 0)).y()
            bar = win._sidebar_scroll.verticalScrollBar()
            assert 0 <= y and y + btn.height() <= viewport.height(), (
                f"侧栏内容变高之后，{page_id} 的导航项没有滚回可视区："
                f"y={y} 高={btn.height()} 视口={viewport.height()} "
                f"滚动={bar.value()}/{bar.maximum()}")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_sidebar_keeps_active_nav_item_visible_when_viewport_shrinks(app):
    """侧栏视口变矮之后，当前导航项必须**仍然**完整可见。—— RN-008 的根因判据

    2026-08-17 CI 连红五轮、本机一次都复现不出的那条，根因在这儿：
    切页时把当前项滚进了可视区，**之后**底部音乐控制条 `musicControlBar`（42px）
    才出现，主窗从侧栏身上扣走这 42px，视口跟着矮 42px ——
    刚滚好的那一项正好被挤到视口外，而**滚动内容的高度一点没变**，
    于是装在 `nav_container` 上的再校正钩子根本收不到 Resize，没人来补救。

    ⚠ 上一版判据（切页后逐页看可见性）**证不了这件事**：它只在切页那一刻量，
    量到的是"刚滚完"的状态。视口是后来才缩的。所以那条绿了五轮也没拦住。
    这条专量"视口缩了之后"，把 42px 这个具体数字换成"任意变矮"来证，
    免得哪天音乐条改了高度判据就失效。
    """
    from PySide6.QtCore import QPoint

    _need_real_fonts(app)
    win = _shown_window(app)
    try:
        scroll = win._sidebar_scroll
        viewport = scroll.viewport()
        skip = set(getattr(win, "_preload_skip_pages", ()) or ())
        # 挑一个**必须滚动才看得见**的导航项：贴着视口底的那种才检得出这个缺陷，
        # 本来就在顶部的项怎么缩都还在视口里，拿它证等于空转。
        target = None
        for page_id in reversed(list(win._page_names.keys())):
            if page_id in skip:
                continue
            btn = win.nav_buttons.get(page_id)
            if btn is None:
                continue
            win.show_page(page_id, animated=False)
            for _ in range(2):
                app.processEvents()
            if btn.isVisible() and scroll.verticalScrollBar().value() > 0:
                target = page_id
                break
        assert target, "找不到一个需要滚动才可见的导航项，判据在空转"

        btn = win.nav_buttons[target]
        before = btn.mapTo(viewport, QPoint(0, 0)).y()
        assert 0 <= before and before + btn.height() <= viewport.height(), (
            f"前提就不成立：{target} 切过去之后本来就在视口外 "
            f"(y={before} 高={btn.height()} 视口={viewport.height()})")

        # 模拟音乐条出现：主窗矮一截，侧栏视口跟着矮。
        # 取 42 是因为 `musicControlBar` 就是 42px —— 用真实数字，
        # 免得取个大得离谱的值把一个只在小幅变化下暴露的缺陷放过去。
        was = viewport.height()
        win.setMinimumSize(1280, 100)
        win.resize(1280, win.height() - 42)
        for _ in range(3):
            app.processEvents()
        # 空转守卫：视口没真的变矮，下面那条断言就什么也没证明。
        assert viewport.height() < was, (
            f"视口没有变矮（{was} → {viewport.height()}），这条判据在空转")

        y = btn.mapTo(viewport, QPoint(0, 0)).y()
        bar = scroll.verticalScrollBar()
        assert 0 <= y and y + btn.height() <= viewport.height(), (
            f"侧栏视口从 {was} 缩到 {viewport.height()} 之后，{target} 的导航项"
            f"被挤出了可视区：y={y} 高={btn.height()} 滚动={bar.value()}/{bar.maximum()}")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_sidebar_scrolls_the_active_nav_item_into_view(app):
    """切页之后，当前页的导航项必须在侧栏可视区内。

    默认 1280×800 下侧栏视口只有 657px 而内容要 1403px —— **28 页里 15 页
    在折叠线外**。不自动滚过去的话，用户切到那些页面时侧栏还停在顶部，
    当前项既看不见也没高亮，**彻底失去「我在哪一页」的指示**。
    """
    from PySide6.QtCore import QPoint

    _need_real_fonts(app)
    win = _shown_window(app)
    try:
        viewport = win._sidebar_scroll.viewport()
        # ⚠ **不许把「构造即起设备」的那几页也走一遍**（音乐 / 语音输出 / 自定闪光 /
        # 局内视角 / 开镜放大 / 击杀图标）。第一版这么干了，代价有二：
        #   · 本机跑探针时**直接卡死在音乐页**（那一页构造会真起音频设备）；
        #   · GitHub runner 上 `music` 这一项断言失败（y=569 在视口外），
        #     而本机 150/150 全绿 —— 典型的"只在别人机器上红"。
        # 侧栏滚动跟"切到哪一页"无关，用剩下这些页面证明它一样充分；
        # 名单取产品自己那份 `_preload_skip_pages`，不另抄一份免得漂移。
        # 这也和 layout_overflow_audit / tab_order_audit 的一贯口径一致。
        skip = set(getattr(win, "_preload_skip_pages", ()) or ())
        checked, out_of_view = 0, []
        for page_id in list(win._page_names.keys()):
            if page_id in skip:
                continue
            win.show_page(page_id, animated=False)
            for _ in range(2):
                app.processEvents()
            btn = win.nav_buttons.get(page_id)
            if btn is None or not btn.isVisible():
                continue
            checked += 1
            y = btn.mapTo(viewport, QPoint(0, 0)).y()
            if not (0 <= y and y + btn.height() <= viewport.height()):
                # 诊断信息一次给全：这条判据两次红在别人的机器上，而只报一个 y
                # 根本判不出是"没滚"还是"滚到头了还不够"。不带着数回来，
                # 下一轮就只能继续猜。
                bar = win._sidebar_scroll.verticalScrollBar()
                out_of_view.append(
                    f"{page_id}(y={y} 高={btn.height()} 视口={viewport.height()} "
                    f"滚动={bar.value()}/{bar.maximum()})")
        # ⚠ 没有这一行，上面的 continue 会让整段空转成绿——回退验证抓到过。
        # 空转守卫：没有这一行，上面的两个 continue 会让整段静默跳过、绿得毫无意义。
        # 闭源版 28 页 − 6 页设备页 = 22；开源版少一个账号页 = 21。取 20 留一格余量，
        # 再少就说明有人往跳过名单里加东西了，那时候该来看一眼而不是让它继续绿。
        assert checked >= 20, f"只检了 {checked} 项导航，判据在空转"
        assert win._sidebar_scroll.verticalScrollBar().maximum() > 0, (
            "侧栏根本没溢出，这个判据在当前尺寸下证明不了任何事")
        assert not out_of_view, (
            f"切到这些页面后，它们的导航项仍在侧栏可视区外: {', '.join(out_of_view)}")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()
