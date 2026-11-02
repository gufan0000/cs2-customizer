# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 145（RN-734）：页头和底栏只说用户现在要知道的话。

改前 28 页首屏 11550 字，其中一大半在把同一件事说三遍：H1 下面一段说明、
一张「当前状态」卡（标题 + 一排徽章 + 几行摘要）、底栏再复述一遍状态。
用户原话是「不便利、不好看」，这一屏就是原因之一。

现在的版面：H1 紧挨总开关；说明进「?」；徽章只报问题；底栏常态只有按钮；
什么都没有就不占地方。

⚠ 这些话不是删了，是挪到了要用的时候才出现的地方 —— 判据同时盯两头：
屏幕上没有了，而 tooltip / 帮助 / `badge_texts()` 里还在。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QAbstractButton, QLabel, QMessageBox, QVBoxLayout, QWidget

REPO = Path(__file__).resolve().parents[1]
for extra in (REPO / "scripts", Path(__file__).resolve().parent):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from pages.audio_status_badge import (  # noqa: E402
    PROBLEM_HEADS, PROBLEM_LEVELS, AudioStatusBadgeBar, render_badges,
)
from test_master_switch_row import EXPECTED_KEYS  # noqa: E402
from widgets.master_switch_link import MasterSwitchRow  # noqa: E402
from widgets.overlay_requirement import (  # noqa: E402
    REQUIRED_WORDS, overlay_requirement_text,
)
from widgets.page_action_bar import PageActionBar  # noqa: E402
from widgets.page_header import PageHeader  # noqa: E402
from widgets.status_strip import StatusStrip  # noqa: E402

#: warn 级徽章里，这些词头说的不是问题：开关关着、还是空的、还没选 —— 页面上都看得见。
#: 新加一种徽章就得在这儿或 `PROBLEM_HEADS` 里选一边，见 `test_every_warning_head_has_been_sorted`。
NOT_A_PROBLEM = frozenset({
    "C4", "功能", "历史", "回合音量", "地图", "开关", "当前", "快照", "总开关", "扫描", "投掷物",
    "播放", "效果", "显示", "曲目", "来源", "热键", "特效", "状态", "素材来源", "联动", "触发模式",
    "记录", "选中", "阵营", "生效", "道具",
}) | (frozenset({"账号"}) if (REPO / "pages" / "account_page.py").is_file() else frozenset())


@pytest.fixture(scope="module")
def main_window(qapp):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")
    import _audit_neutralize as neutral
    from config import config

    neutral.apply(config)
    config.compact_mode = False
    config.ui_expert_mode = False
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


def _open(win, qapp, page_id):
    win.ensure_page_loaded(page_id)
    win.show_page(page_id, animated=False, force=True)
    for _ in range(4):
        qapp.processEvents()
    page = win.pages.get(page_id)
    assert page is not None, f"{page_id} 没加载出来"
    return page


# ============================================================ 总开关在标题旁边


@pytest.mark.parametrize("page_id", sorted(EXPECTED_KEYS))
def test_every_master_switch_sits_beside_the_page_title(main_window, qapp, page_id):
    """全站 16 颗开关的位置只有一处声明（`make_master_switch_row`），一页都不许跑丢。"""
    page = _open(main_window, qapp, page_id)
    row = page.master_switch_row
    assert isinstance(row.parentWidget(), PageHeader), f"{page_id}：总开关不在页头里"
    assert row.isVisibleTo(page), f"{page_id}：总开关建了，屏幕上看不到"


def test_the_row_says_saved_only_where_that_is_true(qapp):
    """「改动自动保存」只在开着、且这一页真是自动保存时才说（RN 批 24：手动保存的页说了就是假话）。"""

    class AutoPage(QWidget):
        pass

    class ManualPage(QWidget):
        SAVES_AUTOMATICALLY = False

    for cls, says_saved in ((AutoPage, True), (ManualPage, False)):
        row = MasterSwitchRow(cls(), "b145_no_such_key", "功能")
        row._toggle.setChecked(True)
        row._sync_state_text()
        assert row.saved_hint.isHidden() is (not says_saved), cls.__name__
        assert row.effect_notice.isHidden()
        row._toggle.setChecked(False)
        row._sync_state_text()
        assert row.saved_hint.isHidden()
        assert not row.effect_notice.isHidden()


def test_nothing_but_the_title_row_sits_above_the_content(main_window, qapp):
    """页头只有标题行那么高。

    ⚠ 帮助面板折叠时高度是 0，但布局照样给它留一条 spacing（批 145 实测标题下多 12px）。
    """
    page = _open(main_window, qapp, "kill_sound")
    header = page.findChild(PageHeader)
    assert header.height() == header.title_row.geometry().height(), (
        f"页头 {header.height()}px，标题行 {header.title_row.geometry().height()}px")


# ============================================================ 说明进帮助


def test_what_the_lead_said_is_still_in_the_help(qapp):
    header = PageHeader("标题", description="这一页管 <某件事>")
    assert header.description_label.isHidden()
    from ui_help_panel import install_help_panel

    _btn, panel = install_help_panel(header.title_row, header.body, "<p>用法</p>")
    content = panel.findChild(QLabel, "helpContent")
    assert "这一页管 &lt;某件事&gt;" in content.text()
    assert "<p>用法</p>" in content.text()


def test_the_help_panel_takes_no_room_until_opened(qapp):
    header = PageHeader("标题")
    from ui_help_panel import install_help_panel

    _btn, panel = install_help_panel(header.title_row, header.body, "<p>用法</p>")
    assert panel.isHidden()
    panel.expand()
    assert not panel.isHidden()


# ============================================================ 徽章只报问题


def test_only_a_problem_gets_a_chip(qapp):
    host = QWidget()
    bar = AudioStatusBadgeBar()
    QVBoxLayout(host).addWidget(bar)
    badges = [("warn", "开关 · 未开启"), ("info", "已配置 · 0"), ("danger", "资源 · 异常 2")]
    render_badges(bar, badges)
    assert [c.text() for c in bar._chip_pool if not c.isHidden()] == ["资源 · 异常 2"]
    # 算出来的东西一条不少，页面和 tooltip 还在用
    assert bar.badge_texts() == [text for _level, text in badges]
    assert not bar.isHidden()

    render_badges(bar, badges[:2])
    assert bar.isHidden(), "没有问题时这一条不该占地方"


def test_a_bar_without_a_parent_never_becomes_a_window(qapp):
    """⚠ 没有父控件的 QWidget 一 show 就是一扇顶层窗口（§3 不许打扰前台）。"""
    bar = AudioStatusBadgeBar()
    render_badges(bar, [("danger", "资源 · 异常 1")])
    assert not bar.isVisible()
    host = QWidget()
    QVBoxLayout(host).addWidget(bar)
    assert not bar.isHidden(), "进了布局之后，该显示的还得显示"


def _heads_of(text) -> set[str]:
    """一个徽章文字表达式里所有可能的词头。文字可以是常量、f 串，也可以是条件表达式。

    ⚠ 第一版不看条件表达式，「样式 · 自定义（未绘制）」这条真警告因此被静默过滤了。
    """
    heads = set()
    for node in ast.walk(text):
        first = None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            first = node.value
        elif (isinstance(node, ast.JoinedStr) and node.values
              and isinstance(node.values[0], ast.Constant)):
            first = node.values[0].value
        if first and " · " in first:
            heads.add(first.split("·")[0].strip())
    return heads - {""}


def _warning_heads() -> set[str]:
    """源码里所有可能是警告级的徽章词头（等级写成变量的也算）。"""
    heads = set()
    for path in sorted((REPO / "pages").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Tuple) and len(node.elts) == 2):
                continue
            level, text = node.elts
            levels = {n.value for n in ast.walk(level)
                      if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            if not levels or levels & PROBLEM_LEVELS:
                heads |= _heads_of(text)
    return heads


def test_every_warning_head_has_been_sorted():
    """⭐ 白名单的毛病是新词头会被静默吞掉 —— 所以每个词头都得有人分过类。"""
    heads = _warning_heads()
    assert len(heads) >= 30, f"只扫到 {len(heads)} 个词头，扫描器瞎了"
    unsorted = heads - PROBLEM_HEADS - NOT_A_PROBLEM
    assert not unsorted, (
        f"这些警告级徽章还没决定算不算问题：{sorted(unsorted)}\n"
        "⇒ 真要用户现在处理的进 `PROBLEM_HEADS`；只是重复页面上已有的话，进 `NOT_A_PROBLEM`。")
    stale = NOT_A_PROBLEM - heads
    assert not stale, f"这些词头已经没人用了，从 NOT_A_PROBLEM 删掉：{sorted(stale)}"
    assert not (NOT_A_PROBLEM & PROBLEM_HEADS)


# ============================================================ 有事才占地方


def _strip_with_label(qapp):
    host = QWidget()
    host.setAttribute(Qt.WA_DontShowOnScreen, True)
    layout = QVBoxLayout(host)
    strip = StatusStrip()
    label = QLabel("有话要说")
    QVBoxLayout(strip).addWidget(label)
    layout.addWidget(strip)
    return host, strip, label


def test_an_empty_strip_takes_no_room_and_comes_back(qapp):
    host, strip, label = _strip_with_label(qapp)
    label.hide()
    host.show()
    qapp.processEvents()
    assert strip.isHidden(), "里面什么都没有，这一条还占着地方"
    label.show()
    assert not strip.isHidden(), "里面有话了，这一条回不来"
    label.hide()
    assert strip.isHidden()


def test_a_strip_does_not_judge_before_it_is_first_shown(qapp):
    """⚠ 页面还在搭的时候判「空」会把自己藏起来，后面的子控件加进来也叫不回它。"""
    host, strip, label = _strip_with_label(qapp)
    label.hide()
    assert not strip.isHidden()


def test_a_strip_can_be_asked_before_its_init_finishes():
    """开源 CI 上 eventFilter 在 `__init__` 赋值之前就被问到了（批 152）：默认值要在类上。"""
    from widgets.status_strip import CollapsingFrame

    assert vars(CollapsingFrame).get("_collapse_armed") is False


def test_the_bottom_bar_stays_silent_unless_told_to_speak(qapp):
    host = QWidget()
    bar = PageActionBar(host)
    bar.set_message("当前分类：手枪 · 已配置 0/10")
    assert bar.message_label.isHidden()
    assert "当前分类" in bar.toolTip(), "话不显示了，但悬停还得看得到"
    assert "当前分类" in bar.message_label.text()

    bar.set_message("试听失败", important=True)
    assert not bar.message_label.isHidden()
    assert bar.message_label.text() == "试听失败"


def test_a_bottom_bar_with_nothing_to_offer_takes_no_room(qapp):
    host = QWidget()
    host.setAttribute(Qt.WA_DontShowOnScreen, True)
    bar = PageActionBar(host)
    QVBoxLayout(host).addWidget(bar)
    host.show()
    qapp.processEvents()
    assert bar.isHidden()
    bar.configure_primary("保存", lambda: None)
    assert not bar.isHidden()


def test_the_overlay_note_is_one_short_line_until_it_really_applies():
    """覆盖层那句前提常驻 7 页，平时一行小字；两档都要把「怎么做」和「否则会怎样」说全（RN-429）。"""
    usual = overlay_requirement_text("准心", exclusive_now=False)
    urgent = overlay_requirement_text("准心", exclusive_now=True)
    for text in (usual, urgent):
        for word in REQUIRED_WORDS:
            assert word in text
        assert text.index(REQUIRED_WORDS[0]) < text.index(REQUIRED_WORDS[1]), "动作要排在后果前面"
    assert len(usual) <= 40, f"{len(usual)} 字：{usual}"


# ============================================================ 外壳


def test_the_nav_fits_one_screen_at_the_default_size(main_window, qapp):
    """1280×800、普通模式，23 项不滚动，项高 24。

    ⚠ 高度只能写在 QSS 里：全局 QPushButton 的 min-height 在 polish 时会盖掉 `setFixedHeight`
    （实测 setFixedHeight(24) 之后实高 18，读着是对的，屏幕上挤成一团）。
    """
    assert main_window.height() == 800
    _open(main_window, qapp, "basic")
    shown = [b for b in main_window.nav_buttons.values() if b.isVisible()]
    assert len(shown) >= 20, f"只有 {len(shown)} 项可见，分母不对"
    assert {b.height() for b in shown} == {24}
    assert main_window._sidebar_scroll.verticalScrollBar().maximum() == 0, "默认窗口下侧栏还要滚"


def test_the_frequent_group_is_off_by_default():
    """「常用」把同样几项再摆一遍，把后面的项顶出可视区，顺序每次启动还会变（批 145 改成默认关）。"""
    from config import Config

    assert Config().nav_frequent_enabled is False


def test_every_page_title_starts_at_the_same_x(main_window, qapp):
    """切页时标题不该横向跳。页头是每一页都有的第一样东西（卡片不一定有，见 `test_design_w5`）。"""
    from core.page_traits import DEVICE_OWNING_PAGES

    xs = {}
    for page_id in main_window._page_names:
        if page_id in DEVICE_OWNING_PAGES:
            continue
        title = _open(main_window, qapp, page_id).findChild(QLabel, "titleLabel")
        assert title is not None, f"{page_id} 没有标题"
        xs[page_id] = title.mapTo(main_window, QPoint(0, 0)).x()
    assert len(xs) >= 20, f"只量到 {len(xs)} 页"
    assert len(set(xs.values())) == 1, f"标题横坐标有几种：{xs}"


def test_every_bottom_bar_lines_up_with_the_content(main_window, qapp):
    """底栏的左右缘全站一条线。

    ⚠ 内容全在滚动区里的 9 页根布局没有左右边距，批 145 第一版按钮贴着窗口边（探针图才看到）。
    """
    from core.page_traits import DEVICE_OWNING_PAGES

    stack = main_window.content_stack
    left = stack.mapTo(main_window, QPoint(0, 0)).x()
    insets = {}
    for page_id in main_window._page_names:
        if page_id in DEVICE_OWNING_PAGES:
            continue
        page = _open(main_window, qapp, page_id)
        # 批 146：inline 的操作条在内容里面（风格库标题行、准心参数栏），不是底栏
        bar = next((b for b in page.findChildren(PageActionBar)
                    if b.isVisibleTo(page) and not b.inline), None)
        if bar is not None:
            x = bar.mapTo(main_window, QPoint(0, 0)).x()
            insets[page_id] = (x - left, left + stack.width() - x - bar.width())
    # 批 147：七个音效页的操作条都进了标题行；批 149：目录好好的时高级设置的底栏不显示
    assert len(insets) >= 5, f"只量到 {sorted(insets)}"
    assert set(insets.values()) == {(20, 20)}, insets


def test_the_switch_comes_before_help_in_keyboard_order(main_window, qapp):
    """键盘顺序跟眼睛走：先开关，后右上角的「?」（全站的走查在 `scripts/tab_order_audit.py`）。"""
    page = _open(main_window, qapp, "music")
    assert page.master_switch_row._toggle.nextInFocusChain() is page.findChild(QWidget, "helpButton")


def test_the_full_layout_has_no_top_bar(main_window, qapp):
    """完整档顶栏并进侧栏；紧凑档才有。"""
    _open(main_window, qapp, "kill_sound")
    assert main_window._compact_header.isHidden()
    assert main_window.settings_search_box.isVisibleTo(main_window), "搜索框跟着档位搬家，这一档它在侧栏"


# ============================================================ 折行别被裁


def _layout_audit():
    import layout_overflow_audit

    return layout_overflow_audit


def test_the_layout_audit_sees_a_clipped_label(qapp):
    """尺子自己先过一遍：一段长字塞进写死高度的标签，要报出来。"""
    host = QWidget()
    host.setAttribute(Qt.WA_DontShowOnScreen, True)
    layout = QVBoxLayout(host)
    label = QLabel("这是一句很长的提示，" * 12)
    label.setWordWrap(True)
    label.setFixedHeight(20)
    layout.addWidget(label)
    host.resize(200, 200)
    host.show()
    qapp.processEvents()
    hits = _layout_audit()._clipped_labels(host)
    assert [(have, need > have + 1) for _text, have, need in hits] == [(20, True)]


def test_the_layout_audit_measures_the_shell_too(main_window, qapp):
    """侧栏底部两个字被裁，审计全绿：几把尺子只量页面和对话框（批 145）。"""
    audit = _layout_audit()
    scopes = audit._shell_scopes(main_window)
    assert {"外壳/侧栏", "外壳/顶栏"} <= {name for name, _ in scopes}
    btn = main_window._sidebar_mode_btn
    text = btn.text()
    btn.setText("这里写一句放不下的话")
    qapp.processEvents()
    try:
        hits = [hit for _name, scope in scopes for hit in audit._elided_buttons(scope)]
    finally:
        btn.setText(text)
    assert any(hit[0] == "这里写一句放不下的话" for hit in hits), hits


def test_the_first_dialog_a_new_user_sees_is_not_clipped(qapp):
    """首次引导写死高度 420 时，第一屏的说明被裁成半行（批 145 看图才发现，审计 8/8 全绿）。"""
    from dialogs.onboarding_dialog import OnboardingDialog
    from theme_manager import get_stylesheet

    qapp.setStyleSheet(get_stylesheet())
    dialog = OnboardingDialog()
    dialog.setAttribute(Qt.WA_DontShowOnScreen, True)
    dialog.show()
    qapp.processEvents()
    try:
        assert _layout_audit()._clipped_labels(dialog) == []
    finally:
        dialog.close()
        dialog.deleteLater()


# ============================================================ 首屏字数


def _first_screen_chars(win, page) -> int:
    origin = win.content_stack.mapTo(win, QPoint(0, 0))
    clip = QRect(origin, win.content_stack.size())

    def on_screen(widget):
        if not widget.isVisibleTo(page):
            return False
        return QRect(widget.mapTo(win, QPoint(0, 0)), widget.size()).intersects(clip)

    import re

    total = 0
    for label in page.findChildren(QLabel):
        if on_screen(label):
            total += len(re.sub(r"<[^>]+>", "", label.text() or "").strip())
    for button in page.findChildren(QAbstractButton):
        if on_screen(button):
            total += len((button.text() or "").strip())
    return total


#: 干净配置、1280×800 首屏最多多少字（批 145 实测再留 20 字余量）。只许往下调：加字要有理由。
#: ⚠ 这是离屏进程量的：它没有中文字形，版面和真实平台不同，这些数只能和自己比。
#: 真实平台整站 28 页：批 145 改前 11550 字 → 改后 8937 字。
FIRST_SCREEN_LIMITS = {
    "kill_sound": 200,
    "crosshair": 370,
    "magnifier": 560,
    "viewmodel": 620,
    "screen_effects": 425,
    "basic": 435,
}


#: 没有社区站的发行版（开源版）空库时没有引导卡，置灰的武器板按设计留着
#: （`sound_page_base._sync_community_guidance`），首屏是另一种状态，另记一档：开源版实测 392 + 20。
FIRST_SCREEN_LIMITS_WITHOUT_COMMUNITY = {
    "kill_sound": 412,
}


@pytest.mark.parametrize("page_id", sorted(FIRST_SCREEN_LIMITS))
def test_the_first_screen_does_not_grow_back(main_window, qapp, page_id):
    from widgets import community_library

    page = _open(main_window, qapp, page_id)
    chars = _first_screen_chars(main_window, page)
    limit = FIRST_SCREEN_LIMITS[page_id]
    key = getattr(page, "COMMUNITY_CATEGORY_KEY", "")
    if key and not community_library.has_category(key):
        limit = FIRST_SCREEN_LIMITS_WITHOUT_COMMUNITY.get(page_id, limit)
    assert chars <= limit, f"{page_id} 首屏 {chars} 字，上限 {limit}"
