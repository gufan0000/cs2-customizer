# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 149、150（RN-745~750）：工具页、调参页、媒体页换成朴素的设置行。

改前这些页是同一个样子：卡片里套卡片、拉满 1000 px 的下拉框、一行行复述控件值的「当前…」摘要、
同一个动作在卡里和底栏各摆一份。外审 S3 的清单大半出在这里（左缘不齐、卡片不等高、孤零零一颗按钮）。

现在：标签一列、控件定宽、往右留白；能合的合成一张卡；状态没事不说话，有事说在一直露着的底栏上。

⚠ 判据盯的是用户看得到的后果（对不对齐、有没有两层滚动、那句话在不在屏幕上），不盯某页用了哪个工厂。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QFrame, QLabel, QLineEdit, QMessageBox, QScrollArea, QTabWidget, QWidget,
)

REPO = Path(__file__).resolve().parents[1]
for extra in (REPO / "scripts", Path(__file__).resolve().parent):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from _denominator import must_scan  # noqa: E402
from widgets.settings_row import (  # noqa: E402
    PLAIN_CONTROL_WIDTH, PLAIN_LABEL_WIDTH, PLAIN_ROW_MIN_HEIGHT, SettingsRow, plain_row,
)

#: 导航里的全部页面。⚠ 新加一页要加进这张表，`test_the_page_list_is_complete` 盯着。
ALL_PAGES = (
    "basic", "audio_import_wizard", "kill_sound", "kill_voice", "death_sound", "gun_sound", "switch_weapon",
    "reload_sound", "special_sound", "crosshair", "kill_icon", "viewmodel", "magnifier", "flash", "hud_color",
    "screen_effects", "music", "voice_output", "fun_afterlife", "account", "utility", "advanced", "audio_health",
    "audio_task_panel", "audio_replay", "config_snapshot", "preset_center", "about",
)
#: 批 149、150 改过的页：不许卡片套卡片。
PLAIN_PAGES = (
    "advanced", "about", "utility", "account", "audio_health", "audio_replay", "audio_task_panel", "config_snapshot",
    "preset_center", "screen_effects", "magnifier", "viewmodel", "flash", "hud_color", "kill_icon", "voice_output",
    "music", "fun_afterlife", "audio_import_wizard",
)
#: 其中用到 `plain_row` 的页。
PAGES_WITH_ROWS = (
    "advanced", "utility", "account", "screen_effects", "magnifier", "viewmodel", "flash",
    "hud_color", "voice_output", "music", "fun_afterlife",
)
#: 风格条里的一格是列表项（和音效页的风格卡一样），不算又一层卡片。
TILES = ("KillIconStyleCard", "KillIconStyleAddCard", "KillIconLevelCell")
#: Markdown 的记号。工具提示和普通标签都是纯文本，写了就原样显示（批 145 反引号、屏幕特效 `**`、开关提示 `**` 同族）。
MARKDOWN_MARKS = ("**", "`")


@pytest.fixture(scope="module")
def main_window(qapp):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")
    import _audit_neutralize as neutral
    from config import config

    shape = {key: getattr(config, key) for key in ("compact_mode", "ui_expert_mode", "nav_frequent_enabled")}
    neutral.apply(config)
    config.compact_mode = False
    config.ui_expert_mode = True  # 专家页也要建出来
    config.nav_frequent_enabled = False
    monkeypatch.setattr("config.config.save_config", lambda: None, raising=False)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.resize(1280, 800)
    win.show()
    qapp.processEvents()
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()
    monkeypatch.undo()
    # 这几项会落盘到几路 worker 共用的测试配置：钉一个档的人负责还回去
    for key, value in shape.items():
        setattr(config, key, value)
    config.save_config_now()


def _settle(qapp):
    for _ in range(4):
        qapp.processEvents()


def _open(win, qapp, page_id):
    if page_id not in win._page_names:
        pytest.skip(f"这个检出里没有 {page_id} 这一页（开源版是功能子集）")
    win.ensure_page_loaded(page_id)
    win.show_page(page_id, animated=False, force=True)
    _settle(qapp)
    page = win.pages.get(page_id)
    assert page is not None, f"{page_id} 没加载出来"
    return page


def _each_tab(page, qapp):
    """一页的每个页签走一遍：没显示过的页签几何是假的。没有页签就走一次。"""
    tabs = [widget for widget in page.findChildren(QTabWidget) if widget.count()]
    if not tabs:
        yield 0
        return
    widget = tabs[0]
    start = widget.currentIndex()
    for index in range(widget.count()):
        widget.setCurrentIndex(index)
        _settle(qapp)
        yield index
    widget.setCurrentIndex(start)
    _settle(qapp)


def _is_card(widget):
    return isinstance(widget, QFrame) and widget.objectName() == "card"


def _card_of(widget):
    parent = widget.parentWidget()
    while parent is not None:
        if _is_card(parent):
            return parent
        parent = parent.parentWidget()
    return None


def _plain_rows(page):
    return [row for row in page.findChildren(SettingsRow)
            if row.isVisible() and row.label_widget.minimumWidth() == PLAIN_LABEL_WIDTH]


def _outer_scrolls(page):
    """这一页最外层的滚动区（滚动区里的列表不算）。"""
    outer = []
    for scroll in page.findChildren(QScrollArea):
        parent = scroll.parentWidget()
        while parent is not None and parent is not page and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent is page and scroll.isVisible():
            outer.append(scroll)
    return outer


def _layout_audit():
    import layout_overflow_audit

    return layout_overflow_audit


def _set_switch(page, qapp, checked):
    page.master_switch_row.set_checked_by_user(checked)
    _settle(qapp)


def test_the_page_list_is_complete(main_window):
    """分母：新加一页，这几条全站判据不许看不见它。"""
    missing = set(main_window._page_names) - set(ALL_PAGES)
    assert not missing, f"这几页不在 ALL_PAGES 里，全站判据看不见它们：{sorted(missing)}"
    must_scan(main_window._page_names, "导航里的页面", least=20)


@pytest.mark.parametrize("page_id", PLAIN_PAGES)
def test_no_card_sits_inside_another_card(main_window, qapp, page_id):
    """卡片套卡片是这些页看着乱的头号原因：两层边框、两层内边距，左缘永远对不齐。"""
    page = _open(main_window, qapp, page_id)
    cards = must_scan([w for w in page.findChildren(QFrame) if _is_card(w)], f"{page_id} 的卡片")
    nested = [card for card in cards if _card_of(card) is not None and type(card).__name__ not in TILES]
    assert not nested, (
        f"{page_id}：{len(nested)} 张卡片放在另一张卡片里："
        f"{[getattr(getattr(c, 'title_label', None), 'text', str)() for c in nested][:6]}")


def test_a_plain_row_pins_its_control_width(qapp):
    """控件定宽，往右留白：1000 px 宽的下拉框读起来像一堵墙。`width=None` 才用控件自己的宽度。"""
    pinned = QComboBox()
    row = plain_row("样式", pinned)
    assert (pinned.minimumWidth(), pinned.maximumWidth()) == (PLAIN_CONTROL_WIDTH, PLAIN_CONTROL_WIDTH)
    assert row.minimumHeight() == PLAIN_ROW_MIN_HEIGHT, "滑条和勾选框本身矮，不钉行高就比下拉框那几行挤"

    free = QComboBox()
    free_row = plain_row("样式", free, width=None)
    assert free.minimumWidth() == 0
    assert free_row.label_widget.minimumWidth() == PLAIN_LABEL_WIDTH


@pytest.mark.parametrize("page_id", PAGES_WITH_ROWS)
def test_plain_rows_line_up_in_one_column(main_window, qapp, page_id):
    """⭐ 同一张卡里，每一行的控件从同一条竖线开始（外审 S3 报得最多的就是这一条）。"""
    page = _open(main_window, qapp, page_id)
    seen = []
    for tab in _each_tab(page, qapp):
        by_card = {}
        for row in _plain_rows(page):
            seen.append(row)
            # ⚠ `plain_row` 单独建出来时看不出：全局 fix_text_display 建页之后才给标签开折行
            assert not row.label_widget.wordWrap(), f"{page_id}：「{row.label_widget.text()}」这个标签会折行"
            assert row.height() >= PLAIN_ROW_MIN_HEIGHT, (
                f"{page_id} 第 {tab} 页签：「{row.label_widget.text()}」这一行只有 {row.height()} px 高")
            card = _card_of(row)
            left = row.control_widget.mapTo(row.window(), QPoint(0, 0)).x()
            by_card.setdefault(id(card), {})[row.label_widget.text()] = left
            if isinstance(row.control_widget, (QComboBox, QLineEdit)):
                assert row.control_widget.width() <= 360, (
                    f"{page_id}：「{row.label_widget.text()}」的控件拉到了 {row.control_widget.width()} px")
        for lefts in by_card.values():
            assert len(set(lefts.values())) == 1, f"{page_id} 第 {tab} 页签：控件左缘不齐：{lefts}"
    must_scan(seen, f"{page_id} 的设置行", least=2)


@pytest.mark.parametrize("page_id", ("advanced", "magnifier", "preset_center", "utility"))
def test_a_flow_row_leaves_no_blank_tail(main_window, qapp, page_id):
    """用了流式布局的页：内容区不比布局要的高（RN-753，预设中心尾巴上 156 px 空白）。"""
    page = _open(main_window, qapp, page_id)
    seen = 0
    for scroll in page.findChildren(QScrollArea):
        inner = scroll.widget()
        if inner is None or inner.layout() is None or not scroll.isVisible():
            continue
        seen += 1
        need = max(inner.layout().heightForWidth(inner.width()), scroll.viewport().height())
        assert inner.height() <= need, f"{page_id}：内容区 {inner.height()}，布局只要 {need}"
    assert seen >= 1, f"{page_id} 没有看得见的滚动区，这条量了个空"


@pytest.mark.parametrize("page_id, hint_name, button_name", [
    ("config_snapshot", "empty_hint_label", "create_btn"),
    ("audio_task_panel", "empty_history_label", "empty_action_btn"),
    ("audio_replay", "empty_results_label", "empty_goto_btn"),
])
def test_a_list_page_is_one_card_read_top_down(main_window, qapp, monkeypatch, page_id, hint_name, button_name):
    """一个列表和它的操作合成一张卡：先说为什么是空的，再给按钮，最后才是表。"""
    page = _open(main_window, qapp, page_id)
    if page_id == "config_snapshot":
        # 快照存在共用的测试配置目录里，别的判据留下的会让这一页不再是空的（RN-646）
        monkeypatch.setattr("pages.config_snapshot_page.list_snapshots", lambda: [])
        page._reload()
        _settle(qapp)
    cards = [w for w in page.findChildren(QFrame) if _is_card(w) and w.isVisible()]
    assert len(cards) == 1, f"{page_id} 拆成了 {len(cards)} 张卡"
    hint, button = getattr(page, hint_name), getattr(page, button_name)
    assert hint.isVisible(), f"{page_id}：空状态那句话不在屏幕上：{hint.text()!r}"
    assert button.isVisible(), f"{page_id}：空状态没有下一步"
    top = hint.mapTo(page, QPoint(0, 0)).y()
    assert top + hint.height() <= button.mapTo(page, QPoint(0, 0)).y(), f"{page_id}：那句话跑到按钮下面去了"
    # 卡片有 1 px 边框，内容从边框里面开始
    left = cards[0].mapTo(page, QPoint(0, 0)).x() + cards[0].layout().contentsMargins().left()
    assert abs(hint.mapTo(page, QPoint(0, 0)).x() - left) <= 2, f"{page_id}：空状态不靠卡片左缘"


def test_an_empty_utility_list_is_only_as_tall_as_its_words(main_window, qapp):
    """没有道具时卡片只有几行字高：一整页的空卡片看着像出了问题。有道具时列表把卡片撑开。"""
    page = _open(main_window, qapp, "utility")
    start = page.tab_widget.currentIndex()
    page.tab_widget.setCurrentIndex(page.tab_widget.count() - 1)
    _settle(qapp)
    try:
        page._show_utility_list(False)
        _settle(qapp)
        empty_height = page.utility_list_card.height()
        assert page.empty_utility_state_widget.isVisible()
        assert _layout_audit()._clipped_labels(page.empty_utility_state_widget) == []
        assert empty_height <= 200, f"空状态的卡片有 {empty_height} px 高"

        page._show_utility_list(True)
        _settle(qapp)
        assert page.utility_list_card.height() >= empty_height + 100, "有道具时列表没撑开"
    finally:
        page._show_utility_list(False)
        page.tab_widget.setCurrentIndex(start)
        _settle(qapp)


def test_a_valid_directory_leaves_no_lonely_button_on_the_bar(main_window, qapp, monkeypatch):
    """S3：目录卡上就有「选择目录」，目录好好的时底栏再摆一颗是孤零零的重复。无效时才给这两颗。"""
    page = _open(main_window, qapp, "advanced")
    bar = page.action_bar
    monkeypatch.setattr(page, "_is_valid_csgo_dir", lambda _path: True)
    page._sync_action_bar()
    assert not bar.secondary_btn.isVisibleTo(bar)
    assert not bar.primary_btn.isVisibleTo(bar)

    monkeypatch.setattr(page, "_is_valid_csgo_dir", lambda _path: False)
    page._sync_action_bar()
    assert bar.secondary_btn.isVisibleTo(bar) and bar.secondary_btn.text() == "选择目录"
    assert bar.primary_btn.isVisibleTo(bar) and bar.primary_btn.text() == "重试自动检测"
    monkeypatch.undo()
    page._sync_action_bar()


def test_the_first_run_dialog_uses_the_new_page_name(main_window, qapp):
    """改名的第二个地方：首次引导还在说「基础设置」，用户在侧栏找不到（批 148 同族）。"""
    from dialogs.onboarding_dialog import OnboardingDialog

    dialog = OnboardingDialog(main_window)
    try:
        words = must_scan([label.text() for label in dialog.findChildren(QLabel) if label.text()], "首次引导的文字", least=3)
        assert not [text for text in words if "基础设置" in text], words
        assert [text for text in words if "总览" in text], "引导不再提起「总览」，这条判据就空转了"
    finally:
        dialog.deleteLater()


def _leftovers(root):
    found = []
    for widget in root.findChildren(QWidget):
        texts = [widget.toolTip()]
        if isinstance(widget, (QLabel, QAbstractButton)):
            texts.append(widget.text())
        elif isinstance(widget, QLineEdit):
            texts.append(widget.placeholderText())
        found.extend(f"{type(widget).__name__}: {text[:60]!r}" for text in texts
                     if any(mark in text for mark in MARKDOWN_MARKS))
    return found


@pytest.mark.parametrize("page_id", ALL_PAGES)
def test_no_page_shows_markdown_marks(main_window, qapp, page_id):
    """⭐ 工具提示和标签是纯文本，`**` 和反引号会原样显示（三次了：批 145、屏幕特效、开关提示）。

    开关开着和关着显示的话不一样，两态都要扫。
    """
    page = _open(main_window, qapp, page_id)
    found = _leftovers(page)
    row = getattr(page, "master_switch_row", None)
    if row is not None:
        was_on = row.is_checked()
        for checked in (True, False):
            _set_switch(page, qapp, checked)
            found += _leftovers(page)
        _set_switch(page, qapp, was_on)
    assert not found, f"{page_id}：\n" + "\n".join(sorted(set(found)))


def test_no_dialog_shows_markdown_marks(main_window, qapp):
    """界面不只有页面（RN-672）。"""
    import _audit_dialogs

    seen = 0
    for spec, dialog, error in _audit_dialogs.build_all(main_window, qapp):
        assert not error, f"{spec.key} 建不起来：{error}"
        seen += 1
        try:
            assert not _leftovers(dialog), f"{spec.key}：{_leftovers(dialog)}"
        finally:
            dialog.close()
            dialog.deleteLater()
    must_scan(range(seen), "对话框", least=3)


def test_the_screen_effects_switch_does_not_promise_what_it_disables(main_window, qapp):
    """通用那句「可以先调好」在这一页是假话：关着时控件是真禁用的（RN-421）。"""
    page = _open(main_window, qapp, "screen_effects")
    was_on = page.master_switch_row.is_checked()
    try:
        _set_switch(page, qapp, False)
        notice = page.master_switch_row.effect_notice
        assert notice.isVisibleTo(page)
        assert not page.preset_combo.isEnabled(), "控件没禁用了 ⇒ 这句特例可以撤，改回通用那句"
        assert "可以先调好" not in notice.text(), notice.text()
    finally:
        _set_switch(page, qapp, was_on)


def test_the_voice_status_lives_on_the_bar_you_can_see(main_window, qapp):
    """RN-673 同形：状态原来摆在滚动区最下面，折叠线以下 200 多像素。没事不说话，有事说在底栏。"""
    page = _open(main_window, qapp, "voice_output")
    bar, label = page.action_bar, page.action_bar.message_label
    page._set_status_text("▶ 播放: Demo Clip")
    assert label.isVisibleTo(bar) and "Demo Clip" in label.text()
    page._clear_status()
    assert not label.isVisibleTo(bar), f"没事的时候底栏不说话：{label.text()!r}"


@pytest.mark.parametrize("page_id", ["voice_output", "viewmodel"])
def test_the_page_fits_one_screen_at_the_default_size(main_window, qapp, page_id):
    """1280×800 放得下。语音页尤其要紧：外层再滚一层，就和槽位列表叠成两层滚动。

    ⚠ 只量默认容器。音乐条展开时高度变少、外层会滚，那是对的。
    """
    page = _open(main_window, qapp, page_id)
    scrolls = must_scan(_outer_scrolls(page), f"{page_id} 的外层滚动区")
    overflow = [scroll.verticalScrollBar().maximum() for scroll in scrolls]
    assert max(overflow) == 0, f"{page_id}：外层还要滚 {max(overflow)} px"


def test_the_viewmodel_bar_says_whether_it_is_written(main_window, qapp):
    """「CFG 同步」卡撤了：写没写进去，以及当局怎么立刻见效，都说在保存按钮旁边。"""
    page = _open(main_window, qapp, "viewmodel")
    bar, label = page.action_bar, page.action_bar.message_label
    page._loading = False
    try:
        page._mark_unsaved()
        assert label.isVisibleTo(bar) and "还没写进" in label.text(), label.text()
        assert "exec cs2customizer.cfg" in label.text()
        page._mark_saved()
        assert label.isVisibleTo(bar) and "已经写进" in label.text(), label.text()
        assert "exec cs2customizer.cfg" in label.text()
    finally:
        page._mark_saved()


def test_the_red_buttons_warn_only_when_there_is_something_to_lose(main_window, qapp, monkeypatch):
    """空列表的第一屏上亮着三颗红按钮，要删的东西一样都不存在。⚠ 不禁用：点了照样有回应。"""
    page = _open(main_window, qapp, "music")
    tracks, selection = page._track_danger_buttons, page._selection_danger_button
    calm = lambda button: button.property("nothingToLose") == "true"  # noqa: E731
    saved = page.selected_indices
    try:
        page.selected_indices = set()
        monkeypatch.setattr(page.player, "get_playlist", lambda: [])
        page._sync_playlist_panel_status()
        assert all(calm(button) for button in (*tracks, selection))
        assert all(button.isEnabled() for button in (*tracks, selection))

        monkeypatch.setattr(page.player, "get_playlist", lambda: [{"title": "a", "path": "a.mp3", "type": "local"}])
        page._sync_playlist_panel_status()
        assert not any(calm(button) for button in tracks), "有曲目了，「清空」「删列表」该是红的"
        assert calm(selection), "还没选中，「删除选中」没东西可丢"

        page.selected_indices = {0}
        page._sync_playlist_panel_status()
        assert not calm(selection)
    finally:
        page.selected_indices = saved
        monkeypatch.undo()
        page._sync_playlist_panel_status()


def test_the_fun_status_line_keeps_quiet_while_the_switch_says_it(main_window, qapp):
    """开关旁边已经说了「打开后才在游戏里生效」，下面不再说第二遍；开着时才说清在哪些模式里触发。"""
    page = _open(main_window, qapp, "fun_afterlife")
    was_on = page.master_switch_row.is_checked()
    try:
        _set_switch(page, qapp, False)
        page._refresh_status()
        assert not page.status_label.isVisibleTo(page), page.status_label.text()
        _set_switch(page, qapp, True)
        page._refresh_status()
        assert page.status_label.isVisibleTo(page) and page.status_label.text().startswith("已启用")
    finally:
        _set_switch(page, qapp, was_on)


@pytest.mark.parametrize("page_id, scroll_name", [
    ("kill_icon", "styleStripScroll"),
    ("voice_output", "voiceSlotList"),
])
def test_a_list_inside_a_card_has_no_second_background(main_window, qapp, page_id, scroll_name):
    """全局 QSS 给滚动区内容层刷页面底色，放在卡片里就是一块深色矩形，看着像「这里还应该有东西」。"""
    page = _open(main_window, qapp, page_id)
    scroll = page.findChild(QScrollArea, scroll_name)
    assert scroll is not None, f"{page_id} 没有 {scroll_name}"
    for _tab in _each_tab(page, qapp):
        if scroll.isVisible():
            break
    assert scroll.isVisible(), f"{scroll_name} 在哪个页签都看不见"

    card = _card_of(scroll)
    image = card.grab().toImage()
    viewport = scroll.viewport()
    # 右下角：列表靠左排，这里是空白（语音页内容层右边距 8，放得下这一点）
    corner = viewport.mapTo(card, QPoint(viewport.width() - 2, viewport.height() - 2))
    assert image.pixelColor(corner) == image.pixelColor(card.width() // 2, 2), (
        f"{scroll_name} 的空白处不是卡片底色")


def _ui_literals(path):
    """非 docstring 的字符串字面量（f-string 里的片段也算）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


def test_no_markdown_marks_are_written_into_ui_strings():
    """页面扫描只看得见当前状态显示的话。状态文案在分支里，弹窗和导入提示在 core 里，这里一起管。

    只看带中文的字面量：反引号和星号在 glob、控制台键、正则里是正经字符。
    `/*` 是样式表的注释，不显示。
    """
    files = must_scan(
        [REPO / "ui_help_panel.py", REPO / "gui_widget.py"]
        + [path for folder in ("pages", "widgets", "dialogs", "core") for path in sorted((REPO / folder).rglob("*.py"))],
        "界面源码", least=30)
    found = [f"{path.relative_to(REPO)}:{line} {text[:60]!r}" for path in files
             for line, text in _ui_literals(path)
             if any(mark in text for mark in MARKDOWN_MARKS) and "/*" not in text
             and any("\u4e00" <= char <= "\u9fff" for char in text)]
    assert not found, "\n".join(found)
