# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R4 · 显示缺陷回归（UP-018 / 019 / 020 / 024 / 025 / 026 / 030 / 032）。

源码级断言一律走 **AST**，不做文本匹配：本轮改动在注释里就写着
`setGraphicsEffect` / `_card_shadow` / `_apply_style` 这些字样（用来解释
为什么不能那么写），文本匹配会把说明文字当成真实调用，白白误报。
这个坑 R3 已经踩过一次（见 tests/test_flash_shutdown.py）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ AST 工具


def _func_node(path: Path, func_name: str, cls_name: str | None = None) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scopes = [tree]
    if cls_name is not None:
        scopes = [n for n in ast.walk(tree)
                  if isinstance(n, ast.ClassDef) and n.name == cls_name]
        assert scopes, f"没找到类 {cls_name}"
    for scope in scopes:
        for node in ast.walk(scope):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return node
    raise AssertionError(f"没找到 {cls_name or path.name}.{func_name}")


def _called_names(node: ast.AST) -> set[str]:
    """节点内所有被调用的函数名（`f()` 取 f，`a.b()` 取 b）。"""
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Attribute):
                out.add(sub.func.attr)
            elif isinstance(sub.func, ast.Name):
                out.add(sub.func.id)
    return out


def _attribute_names(node: ast.AST) -> set[str]:
    return {s.attr for s in ast.walk(node) if isinstance(s, ast.Attribute)}


# --------------------------------------------------- UP-024 / UP-025 阴影所有权


def test_event_filter_no_longer_owns_card_shadow():
    """UP-025：卡片阴影只能有一个主人。

    `SettingsCard` 自己的 enterEvent/leaveEvent 已经在管这枚阴影，
    而 MainWindow.eventFilter 里原本还有第二套：eventFilter 先于控件自身的
    事件处理跑，Leave 时把 alpha 直接写成 30，SettingsCard 的动画只回滚 blur、
    不回滚 alpha。默认 md_alpha 是 120 —— 鼠标**扫过一次**，阴影就永久变成 1/4。
    """
    fn = _func_node(ROOT / "gui_widget.py", "eventFilter", "MainWindow")
    assert "_card_shadow" not in _attribute_names(fn), (
        "eventFilter 又开始碰 _card_shadow 了。阴影归 SettingsCard 唯一持有，"
        "两套控制器抢同一个 QGraphicsDropShadowEffect 必然打架。"
    )


def test_create_card_does_not_install_second_shadow_controller():
    fn = _func_node(ROOT / "gui_widget.py", "_create_card", "MainWindow")
    assert "_card_shadow" not in _attribute_names(fn)


def test_search_highlight_does_not_touch_graphics_effect():
    """UP-024：搜索高亮不许再动 graphicsEffect。

    原实现 `apply_glow(target)` 会把卡片自己的 elevation 阴影顶掉并析构，
    1.6 秒后再 `setGraphicsEffect(None)` —— 这张卡的阴影**永久消失**；
    而 `SettingsCard._shadow` 仍指向已被 Qt 析构的 C++ 对象，
    之后每次 hover 都在 `_animate_shadow_blur` 里抛 RuntimeError。
    """
    fn = _func_node(ROOT / "gui_widget.py", "_highlight_search_target", "MainWindow")
    called = _called_names(fn)
    assert "setGraphicsEffect" not in called, "搜索高亮又开始动 graphicsEffect 了"
    assert "apply_glow" not in called, "apply_glow 会顶掉卡片自己的 elevation 阴影"
    # 改用动态属性方案后，必须真的设了属性
    assert "setProperty" in _called_names(
        _func_node(ROOT / "gui_widget.py", "_step_search_highlight", "MainWindow"))


def test_search_highlight_states_have_qss_rules():
    """高亮靠 QSS 属性选择器，规则缺了就等于没高亮。"""
    from theme_manager import get_theme_manager

    qss = get_theme_manager().themes["dark"].generate_stylesheet()
    for state in ("true", "fade"):
        assert f'QWidget[searchHit="{state}"]' in qss
        assert f'QFrame#card[searchHit="{state}"]' in qss


def test_search_highlight_survives_deleted_target(qtbot=None):
    """目标控件先于定时器被销毁时，不能把异常抛到事件循环里。"""
    import gui_widget

    fn = _func_node(ROOT / "gui_widget.py", "_clear_search_highlight", "MainWindow")
    handlers = [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]
    assert handlers, "_clear_search_highlight 必须容忍目标已析构（RuntimeError）"
    assert gui_widget is not None


# ------------------------------------------------------------- UP-030 双重应用


def test_theme_combo_does_not_apply_style_twice():
    """UP-030：`set_theme()` 会同步触发回调、回调里已经 apply 过一次。

    首页下拉里再调一次 `_apply_style()`，42KB 的 QSS 就被整表应用两遍，
    切主题卡顿直接翻倍。高级设置页的同名处理器一直是只调 set_theme 的。
    """
    fn = _func_node(ROOT / "gui_widget.py", "_on_theme_combo_changed", "MainWindow")
    assert "_apply_style" not in _called_names(fn), (
        "set_theme() 的回调链里已经 apply 过样式了，这里再调就是应用两遍"
    )
    assert "set_theme" in _called_names(fn)


def test_apply_style_is_idempotent_for_same_stylesheet():
    """同一份 QSS 应用第二遍必须被挡掉（整表 setStyleSheet 会重解析整棵树）。"""
    fn = _func_node(ROOT / "gui_widget.py", "_apply_style", "MainWindow")
    assert "_applied_stylesheet" in _attribute_names(fn), "缺少幂等闸"
    # 极简主题必须绕开这道闸：它的 QSS 恒为空串，靠文本比对会把
    # "清空新建页面内联样式"这件事整个跳掉。
    src = ast.get_source_segment((ROOT / "gui_widget.py").read_text(encoding="utf-8"), fn) or ""
    assert "minimal" in src


def test_font_scale_change_produces_different_stylesheet():
    """幂等闸的**前提**：字号切换必须让 QSS 文本真的变化。

    切字号走的是 `set_theme(同一主题)` → 回调 → `_apply_style()`。
    如果 QSS 文本不随字号变，那道闸就会把整个"切字号"功能挡死——
    用户选了 125% 却毫无反应。这个前提不显然，值得单独钉住。
    """
    from ui_design_system import apply_font_scale
    from theme_manager import get_theme_manager

    theme = get_theme_manager().themes["dark"]
    try:
        apply_font_scale(1.0)
        small = theme.generate_stylesheet()
        apply_font_scale(1.25)
        large = theme.generate_stylesheet()
    finally:
        apply_font_scale(1.0)

    assert small != large, (
        "字号变了但 QSS 文本没变 —— _apply_style 的幂等闸会把切字号整个挡死"
    )


# ---------------------------------------------------------------- UP-032 阴影条


def test_scroll_shadow_follows_scroll_area_width(qapp):
    """UP-032：滚动区变宽，顶部阴影条要跟着变宽。

    原实现只重写了阴影条**自己**的 resizeEvent —— 而它只有在 `_reposition()`
    把它拉宽时才会 resize，纯自循环。窗口放大后阴影条还停在安装那一刻的宽度。
    """
    from ui_effects import ScrollShadow

    area = QScrollArea()
    area.resize(400, 300)
    shadow = ScrollShadow(area)
    assert shadow.width() == 400

    area.resize(900, 300)
    qapp.sendEvent(area, QEvent(QEvent.Resize))  # 保证过滤器被触发
    qapp.processEvents()
    assert shadow.width() == 900, (
        f"滚动区已经 900 宽，阴影条还停在 {shadow.width()}"
    )
    area.deleteLater()


# ------------------------------------------------------- UP-018 尺寸不被覆写


def test_fixed_size_button_is_not_inflated(qapp):
    """UP-018：调用方 setFixedSize 过的按钮，统一样式不许再抬它的 min 尺寸。

    帮助面板那颗 "?" 是 24×24。原逻辑按文字宽 + padding*2 + 20 算出约 80px，
    把 min 抬到 80 就超过了 max=24，Qt 只好把 max 也放大 —— 20 多个页面上
    那颗小圆钮全变成 80×42 的大方块。
    """
    from ui_style_applier import get_style_applier

    btn = QPushButton("?")
    btn.setFixedSize(24, 24)
    get_style_applier().fix_text_display(btn)

    assert btn.minimumWidth() == 24 and btn.maximumWidth() == 24, (
        f"固定宽被撑到 {btn.minimumWidth()}~{btn.maximumWidth()}"
    )
    assert btn.minimumHeight() == 24 and btn.maximumHeight() == 24


def test_non_fixed_button_still_gets_min_size(qapp):
    """反向保护：没被钉死的按钮，原有的"保证文字不被裁"行为要保留。"""
    from ui_style_applier import get_style_applier

    btn = QPushButton("导出全部配置并生成报告")
    before = btn.minimumWidth()
    get_style_applier().fix_text_display(btn)
    assert btn.minimumWidth() > before


# --------------------------------------------------- UP-019 内联样式 opt-out


def test_clear_all_styles_respects_keep_flag(qapp):
    """UP-019：打了 `fp_keep_style` 的控件，内联样式不许被抹。"""
    from ui_style_applier import get_style_applier, keep_inline_style

    root = QWidget()
    layout = QVBoxLayout(root)
    kept = QLabel("保我")
    dropped = QLabel("清我")
    kept.setStyleSheet("color: #ff0000;")
    dropped.setStyleSheet("color: #00ff00;")
    keep_inline_style(kept)
    layout.addWidget(kept)
    layout.addWidget(dropped)

    get_style_applier().clear_all_styles(root)

    assert kept.styleSheet() == "color: #ff0000;", "打了标的控件样式被抹了"
    assert dropped.styleSheet() == "", "没打标的控件应当被清理（保留原有行为）"
    root.deleteLater()


@pytest.mark.parametrize("module_path,marker", [
    ("widgets/weapon_row_widget.py", "keep_inline_style"),
    ("pages/utility_page.py", "keep_inline_style"),
    ("pages/magnifier_page.py", "keep_inline_style"),
])
def test_inline_style_sites_are_marked(module_path, marker):
    """构造期设内联样式的地方都得打标，否则首次进页样式还是会丢。"""
    tree = ast.parse((ROOT / module_path).read_text(encoding="utf-8"))
    assert marker in _called_names(tree), f"{module_path} 未调用 {marker}"


# ------------------------------------------------------------------ UP-026 Toast


def test_toast_has_dismissed_signal():
    """UP-026 的根因：管理器去连 `hide_animation.finished`，

    但那个动画对象要到 `fade_out()` 里才创建 —— 连接那一刻它还是 None，
    于是回收回调**从来没连上过**。改用组件自己的信号，就不依赖创建时机了。
    """
    from ui_toast import Toast

    assert hasattr(Toast, "dismissed"), "Toast 需要一个不依赖动画对象的回收信号"


def test_toast_manager_connects_to_dismissed_not_animation():
    fn = _func_node(ROOT / "ui_toast.py", "show", "ToastManager")
    src = ast.get_source_segment((ROOT / "ui_toast.py").read_text(encoding="utf-8"), fn) or ""
    assert "dismissed.connect" in src
    assert "hide_animation.finished.connect" not in src, (
        "hide_animation 在 show() 里还不存在，连它等于没连"
    )


def test_toast_is_recycled_on_dismiss(qapp):
    """淡出结束后必须出列，否则列表只增不减、每条再往下挪 70px。"""
    from ui_toast import ToastManager

    parent = QWidget()
    parent.resize(800, 600)
    mgr = ToastManager()
    mgr.toasts = []          # 单例，隔离本用例
    mgr.set_parent(parent)

    toast = mgr.show("测试消息", duration=0)
    assert toast in mgr.toasts
    toast.dismissed.emit()
    qapp.processEvents()
    assert toast not in mgr.toasts, "淡出后没有出列 —— 列表会无限增长"

    mgr.toasts = []
    parent.deleteLater()


def test_toast_stack_is_capped(qapp):
    """同屏上限：第 4 条会偏移 210px，已经盖住页面主要内容了。"""
    from ui_toast import ToastManager

    parent = QWidget()
    parent.resize(800, 600)
    mgr = ToastManager()
    mgr.toasts = []
    mgr.set_parent(parent)

    for i in range(6):
        mgr.show(f"消息 {i}", duration=0)
    assert len(mgr.toasts) <= ToastManager.MAX_VISIBLE, (
        f"同屏堆了 {len(mgr.toasts)} 条，会飘出屏幕"
    )

    mgr.toasts = []
    parent.deleteLater()


def test_toast_is_centered_using_adjusted_width(qapp):
    """UP-026 的第二个缺陷：居中用的宽度必须是 adjustSize() 之后的。

    原实现先算位置再 `show_message()`，而 adjustSize 在 show_message 里——
    拿构造期的默认宽度算居中，结果永远偏左。
    """
    from ui_toast import ToastManager

    parent = QWidget()
    parent.resize(1000, 600)
    parent.move(0, 0)
    mgr = ToastManager()
    mgr.toasts = []
    mgr.set_parent(parent)

    toast = mgr.show("一条比较长的提示消息用于撑开宽度", duration=0)
    qapp.processEvents()
    expected_x = parent.geometry().x() + (parent.geometry().width() - toast.width()) // 2
    assert abs(toast.x() - expected_x) <= 1, (
        f"toast 在 {toast.x()}，按自适应后的宽度应当在 {expected_x}"
    )

    mgr.toasts = []
    parent.deleteLater()


# ------------------------------------------------------------- UP-020 弹窗配色
#
# 这里原本有一条 `test_update_dialog_has_no_hardcoded_dark_palette`：
# 守的是 `main_widget._apply_dialog_button_style` 里那块 `QDialog#updateInfoDialog`
# 的 QSS 不许再硬编码深色（浅色主题下"稍后关闭"只有 1.08:1）。
# 开源版不做在线更新检查，更新公告弹窗整个不存在了，判据随被测对象一并移除。
