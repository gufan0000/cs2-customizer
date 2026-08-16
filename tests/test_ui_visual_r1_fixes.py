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
        checked, out_of_view = 0, []
        for page_id in list(win._page_names.keys()):
            win.show_page(page_id, animated=False)
            for _ in range(2):
                app.processEvents()
            btn = win.nav_buttons.get(page_id)
            if btn is None or not btn.isVisible():
                continue
            checked += 1
            y = btn.mapTo(viewport, QPoint(0, 0)).y()
            if not (0 <= y and y + btn.height() <= viewport.height()):
                out_of_view.append(f"{page_id}(y={y})")
        # ⚠ 没有这一行，上面的 continue 会让整段空转成绿——回退验证抓到过。
        assert checked >= 20, f"只检了 {checked} 项导航，判据在空转"
        assert win._sidebar_scroll.verticalScrollBar().maximum() > 0, (
            "侧栏根本没溢出，这个判据在当前尺寸下证明不了任何事")
        assert not out_of_view, (
            f"切到这些页面后，它们的导航项仍在侧栏可视区外: {', '.join(out_of_view)}")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()
