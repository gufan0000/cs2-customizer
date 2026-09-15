# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""X1 动刀前的**第三张网**：主窗那四条链路，行为不许悄悄变。

前两张网（批 55 / 56）冻的是**静态的面**：
契约面 84 个名字、外部效应 11 种定时器。
它们看得见「谁被谁依赖」「构造时对外面做了什么」，
但**看不见「点一下会发生什么」** —— 而 X1 动刀改的正是那个。

这一份钉的是四条链路的行为契约：

| 链路 | 钉住的那件事 |
|---|---|
| 导航 | 每颗导航按钮都指向一个真注册的页；选中态跟着当前页走 |
| 切页 | **懒加载**：切一页只造一页；回头再来复用同一个实例，不重造 |
| 紧凑档 | 往返之后三样都回原状（标志 / 侧栏可见性 / 最小尺寸） |
| 托盘 | 没有托盘的机器上降级而不是崩；有托盘时菜单恰好两项且都接上了 |

⛔ **不碰真系统托盘**（`CLAUDE.md` §3 不打扰前台）：
   `_init_system_tray` 是在函数体里 `from PySide6.QtWidgets import QSystemTrayIcon` 的，
   所以拿一个**替身类**换掉它就能走完整条真实逻辑，而系统托盘区里不会多出一个图标。

⚠ 这里**没有**「Alt+1 跳到屏幕上第一组」那条断言 —— 因为它现在不成立（RN-025）。
   最后一条判据把这件事**当成实测事实钉住**：它红的那天，就是 RN-025 被修好的那天，
   而那时该改的是这条判据，不是把它删掉。
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _build(app):
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    for _ in range(3):
        app.processEvents()
    return win


@pytest.fixture(scope="module")
def win(app):
    w = _build(app)
    yield w
    w.close()
    w.deleteLater()
    app.processEvents()


def _current(win) -> str | None:
    return getattr(win, "_current_page_id", None)


def _other_page(win) -> str:
    """挑一个不是当前页、也不是 basic 的页。⚠ 分母守卫在调用处。"""
    ids = [p for p in win._page_names if p not in (_current(win), "basic")]
    assert len(ids) >= 5, f"能切的页只有 {len(ids)} 个 —— 页面注册表没读到，这条判据在空转"
    return ids[0]


# ------------------------------------------------------------------ 导航

def test_every_nav_button_points_at_a_page_that_is_really_registered(win):
    """⭐ 导航按钮和页面注册表是**两份**东西，它们对不上时屏幕上是一颗点了没反应的按钮。"""
    assert len(win._page_names) >= 20, (
        f"只读到 {len(win._page_names)} 个页面 —— 注册表没解析到，这条判据在空转")
    orphans = sorted(set(win.nav_buttons) - set(win._page_names))
    assert not orphans, (
        f"这几颗导航按钮指向的页不在注册表里：{orphans}\n"
        "⇒ 点下去会切到一个造不出来的页。")


def test_the_nav_selection_follows_the_current_page(win, app):
    """选中态由当前页现算，不由点击那一下自己记着。"""
    target = _other_page(win)
    win.show_page(target, animated=False)
    for _ in range(3):
        app.processEvents()
    checked = {pid for pid, btn in win.nav_buttons.items() if btn.isChecked()}
    assert checked == {target}, (
        f"当前页是 {target}，而侧栏上被选中的是 {sorted(checked)}")


def test_an_unknown_page_id_does_not_take_the_window_down(win, app):
    """健壮性：搜索/深链/托盘都可能递进来一个不存在的 page_id。"""
    before = _current(win)
    win.show_page("这个页不存在", animated=False)
    for _ in range(3):
        app.processEvents()
    assert _current(win) == before, "切到一个不存在的页之后，当前页被改坏了"


# ------------------------------------------------------------------ 切页

def test_switching_to_a_page_builds_exactly_that_one_page(win, app):
    """⭐⭐ **懒加载是一条性能契约，而它在测试报告上是隐形的。**

    X1 动刀时最容易破的就是它：顺手把预加载打开，28 页会在切一页时全造出来 ——
    而**功能全对、判据全绿**，只是启动慢了几秒。
    """
    target = _other_page(win)
    win.show_page("basic", animated=False)
    for _ in range(3):
        app.processEvents()
    before = set(win.pages)
    assert target not in before

    win.show_page(target, animated=False)
    for _ in range(3):
        app.processEvents()
    grew = set(win.pages) - before
    assert grew == {target}, (
        f"切到 {target} 这一下，新造出来的页是 {sorted(grew)} —— 应该只有它自己。")


def test_coming_back_reuses_the_page_instead_of_rebuilding_it(win, app):
    """回头再来必须是同一个实例：重造会丢掉用户在那一页上的临时输入。

    ⭐⭐ 破坏验证跑了**四次**才咬住，而前三次的「假绿」不是判据的毛病 ——
    **这条性质由三道彼此独立的门守着**，拆一道另外两道照样拦下：

    | 门 | 在哪 |
    |---|---|
    | `show_page` 里的 `if page_id not in self._loaded_pages` | 决定要不要走加载那一支 |
    | `ensure_page_loaded` 里的 `if page_id in self._loaded_pages: return True` | 后台预载的入口 |
    | `_load_page` 里的 `if page_id in self._loaded_pages: return` | 最后一道 |

    ⭐ 同批 44 那条：**一条被多处独立支撑的断言，单点破坏测不出来**。
    ⚠ 而它也解释了这条判据的价值：三道门在 X1 动刀时是**一起**被重写的，
      那时它们不会互相兜底。
    """
    target = _other_page(win)
    win.show_page(target, animated=False)
    for _ in range(3):
        app.processEvents()
    first = win.pages[target]
    win.show_page("basic", animated=False)
    win.show_page(target, animated=False)
    for _ in range(3):
        app.processEvents()
    assert win.pages[target] is first, (
        f"{target} 被重造了一次 —— 页面实例的身份变了。")


# ------------------------------------------------------------------ 紧凑档

def test_compact_mode_round_trips_all_three_things(win, app):
    """⭐ 往返之后三样都要回原状：标志 / 侧栏可见性 / 最小尺寸。

    ⚠ 只验「切过去对不对」是不够的 —— 实测最常见的坏法是**切过去回不来**
    （某一样留在了紧凑档的值上，而屏幕上看不出来）。
    """
    # ⚠ 用 `isVisibleTo(win)` 不是 `isVisible()`：后者要顶层窗口 show 过才为真，
    #   而这里的窗口从没 show 过 ⇒ **恒假**，「侧栏可见性变没变」那一条会永远测不出来。
    #   总纲 §9.1 逐字写过这件事（RN-133 的原话），批 57 又踩了一次。
    was = win._compact_mode
    origin = (win._compact_mode, win.sidebar.isVisibleTo(win),
              (win.minimumWidth(), win.minimumHeight()))
    try:
        win._toggle_compact_mode()
        for _ in range(3):
            app.processEvents()
        flipped = (win._compact_mode, win.sidebar.isVisibleTo(win),
                   (win.minimumWidth(), win.minimumHeight()))
        assert flipped[0] is not origin[0], "切了一下，紧凑档标志没翻"
        assert flipped[1] is not origin[1], "切了一下，侧栏的可见性没跟着变"
        assert flipped[2] != origin[2], "切了一下，最小尺寸没跟着变"
        assert win.config.compact_mode is win._compact_mode, (
            "屏幕已经变了，而写进配置的还是旧值 —— 下次启动会回到另一档。")

        win._toggle_compact_mode()
        for _ in range(3):
            app.processEvents()
        back = (win._compact_mode, win.sidebar.isVisibleTo(win),
                (win.minimumWidth(), win.minimumHeight()))
        assert back == origin, f"往返之后没回原状：{origin} → {back}"
    finally:
        if win._compact_mode is not was:
            win._toggle_compact_mode()
            for _ in range(3):
                app.processEvents()


def test_the_flag_is_written_by_every_path_that_applies_the_mode():
    """⭐⭐ **标志和屏幕是两个函数在写，所以它们可以分家。**

    `_apply_compact_mode()` 只动屏幕，`_compact_mode` 这个标志由**调用方**写。
    实测（批 57 探针）：直接调 applier 之后宽度变了 860，而标志仍是 `False`。
    这不是缺陷 —— 真实调用点只有两个，两个都先写标志再 apply。
    ⭐ 但它是一条**只靠「现在只有两个调用点」成立的**不变量：
      X1 动刀时新加第三个调用点，屏幕和标志就会当场分家，而没有任何东西会报。
    ⇒ 这条判据钉的是「调用点还是那两个」。第三个出现时它变红，
      那时要么让 applier 自己写标志，要么在新调用点补上。
    """
    src = (REPO / "gui_widget.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    callers = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "_apply_compact_mode"):
                callers.add(node.name)
    assert callers, "全仓找不到 `_apply_compact_mode` 的调用点 —— 这条判据在空转"
    #: 实测（批 57）：建窗那一处在 `_create_ui` 里（`gui_widget.py:1583`），不在 `__init__`。
    #: ⚠ 我第一版写的是 `__init__` —— **凭印象写的分母，判据一跑就被推翻**。
    assert callers == {"_create_ui", "_toggle_compact_mode"}, (
        f"`_apply_compact_mode` 的调用点变成了 {sorted(callers)}。\n"
        "⇒ 新调用点必须自己把 `self._compact_mode` 写对，"
        "否则屏幕在紧凑档而标志说不是（下次启动会跳回另一档）。")


# ------------------------------------------------------------------ 托盘

def test_a_machine_without_a_tray_degrades_instead_of_crashing(win):
    """离屏环境本来就没有托盘 —— 它必须降级成「没有托盘」，而不是抛异常。"""
    assert win._tray_icon is None, (
        "这台机器上 `isSystemTrayAvailable()` 是假的，却建出了托盘图标 —— "
        "那说明降级分支没走到。")


class _Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)


class _FakeTray:
    """⛔ 托盘的替身：走完 `_init_system_tray` 的真实逻辑，而**系统托盘区里什么都不多**。

    `_init_system_tray` 是在函数体里 `from PySide6.QtWidgets import QSystemTrayIcon` 的，
    所以换掉模块属性就能换掉它拿到的那个类。
    """

    def __init__(self, icon=None, parent=None):
        self.activated = _Signal()
        self.menu = None
        self.shown = False
        self.tip = ""

    @staticmethod
    def isSystemTrayAvailable():
        return True

    def setToolTip(self, text):
        self.tip = text

    def setContextMenu(self, menu):
        self.menu = menu

    def show(self):
        self.shown = True


@pytest.fixture
def tray_win(app, monkeypatch):
    """一台**有托盘**的机器。

    ⚠⚠ 收尾必须 `_force_exit = True` 再 close：`closeEvent` 的第一条分支是
      「`close_action == 'ask'` 且有托盘 ⇒ `_ask_close_action()`」——
      一个**离屏模态框**，没人点得动，整轮 pytest 就停在那里（实测挂满 90 秒）。
    ⭐⭐ 而这正是这一族判据要说的话：**关窗那三条分支只在「有托盘」时才走得到**，
      而本仓既有的窗口测试全跑在没有托盘的离屏环境里 ⇒ 它们**从来没被走过**。
      （同 RN-516：一条判据能不能测到东西，取决于它跑在什么样的机器上。）
    """
    import PySide6.QtWidgets as qtw

    monkeypatch.setattr(qtw, "QSystemTrayIcon", _FakeTray)
    w = _build(app)
    yield w
    w._force_exit = True
    w.close()
    w.deleteLater()
    app.processEvents()


def test_the_tray_menu_has_exactly_the_two_actions_it_promises(tray_win):
    """有托盘时：菜单恰好两项，且各自接到真实的方法上。"""
    tray = tray_win._tray_icon
    assert isinstance(tray, _FakeTray), "换了替身之后托盘没建出来 —— 这条判据在空转"
    assert tray.shown, "托盘建出来了却没 show"
    labels = [a.text() for a in tray.menu.actions() if not a.isSeparator()]
    assert labels == ["显示主界面", "退出程序"], (
        f"托盘菜单里是 {labels} —— 它承诺的是「显示主界面 / 退出程序」两项。")
    assert tray.activated.slots == [tray_win._on_tray_activated], (
        "托盘的 activated 没接到 `_on_tray_activated` 上 —— 双击图标不会有反应。")


def test_closing_routes_by_policy_only_when_there_is_a_tray(tray_win, monkeypatch):
    """⭐⭐⭐ 关窗有三条分支（问一下 / 进托盘 / 真退出），**只有有托盘时才分得开**。

    没有托盘时 `tray_ready` 是假的，三条全部塌成「真退出」——
    而本仓所有既有的窗口测试都跑在那一档上。⇒ 这三条在此之前**一次都没被走过**。

    ⚠ 这里不真的关窗，只验路由：`ask` 会去问、`tray` 会去藏、`exit` 会放行。
    """
    from PySide6.QtGui import QCloseEvent

    win, asked, hidden = tray_win, [], []
    monkeypatch.setattr(win, "_ask_close_action", lambda: (asked.append(1), None)[1])
    monkeypatch.setattr(win, "_hide_to_tray", lambda: hidden.append(1))

    win.config.close_action = "ask"
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert asked == [1] and not ev.isAccepted(), (
        "策略是「每次问一下」，而它没问 —— 或者问完还是把窗口关了。")

    win.config.close_action = "tray"
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert hidden == [1] and not ev.isAccepted(), (
        "策略是「进托盘」，而窗口没有被藏起来。")
    assert asked == [1], "策略已经写死是「进托盘」了，它还去问了一遍。"


def test_only_a_click_restores_the_window_from_the_tray(win, monkeypatch):
    """⭐ 路由要认对：只有点击/双击才还原，鼠标划过、气泡消息都不该把窗口拽出来。"""
    from PySide6.QtWidgets import QSystemTrayIcon

    calls = []
    monkeypatch.setattr(win, "_restore_from_tray", lambda: calls.append(1))
    for reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
        win._on_tray_activated(reason)
    assert len(calls) == 2, "点击/双击托盘图标没有还原窗口"
    for reason in (QSystemTrayIcon.Context, QSystemTrayIcon.MiddleClick,
                   QSystemTrayIcon.Unknown):
        win._on_tray_activated(reason)
    assert len(calls) == 2, (
        "右键/中键/未知这几种也把窗口拽出来了 —— 右键要的是菜单，不是还原窗口。")


# ------------------------------------------------------- 常用分组（RN-025 的证据）

def test_alt_1_reaches_the_group_that_sits_first_on_screen(app, monkeypatch):
    """⭐⭐⭐ **RN-025（批 58 已修）**：`Alt+1` 必须跳到屏幕上的第一组。

    在此之前：「常用」组是 `nav_layout.insertWidget(0, ...)` 插在视觉最上面的，
    而它**从不进 `self.nav_groups`** ⇒ 每一处遍历 `nav_groups` 的代码都漏了它 ——
    `Alt+1` 跳到屏幕上的**第二**组，最后一组则根本没有快捷键。
    ⇒ 修法是让顺序**从布局现算**（`_nav_groups_in_view()`），并让按钮自己带
      `fp_page_id`（「常用」组的按钮不在 `_page_to_group` 里，那正是病根）。

    ⚠⚠ 它必须自己**造出**常用组：干净配置下没有使用频次数据，这一组根本不出现
      —— 同 RN-516：**一条靠环境里碰巧攒下的东西才成立的判据，在干净机器上是哑的**。
      而 CI 和新装的机器就是干净机器。
    """
    import core.page_usage_tracker as tracker

    seeded = ["kill_sound", "crosshair"]
    monkeypatch.setattr(tracker, "top_pages",
                        lambda n=4, known_pages=None: list(seeded))
    win = _build(app)
    try:
        assert win.frequent_group is not None, (
            "种下了使用频次数据，「常用」组却没出现 —— 这条判据的前提没造起来")

        in_view = win._nav_groups_in_view()
        assert in_view and in_view[0] is win.frequent_group, (
            "侧栏视觉第一组不是「常用」—— `_nav_groups_in_view()` 没按布局现算")
        assert len(in_view) == len(win.nav_groups) + 1, (
            f"视图里 {len(in_view)} 组、静态表里 {len(win.nav_groups)} 组 —— "
            "差的那一个应该正好是「常用」")

        # Alt+1 真的落在常用组的第一页上
        win._goto_nav_group(0)
        for _ in range(3):
            app.processEvents()
        assert _current(win) == seeded[0], (
            f"Alt+1 跳到了 {_current(win)}，而屏幕上第一组的第一页是 {seeded[0]}")

        # 每一组都拿得到快捷键，最后一组不许再被漏掉
        seqs = {sc.key().toString() for sc in win._app_shortcuts}
        want = {f"Alt+{i + 1}" for i in range(len(in_view))}
        assert want <= seqs, f"有分组没拿到 Alt 快捷键：{sorted(want - seqs)}"
    finally:
        win._force_exit = True
        win.close()
        win.deleteLater()
        app.processEvents()


def test_the_compact_drawer_mirrors_the_sidebar_including_the_frequent_group(
        app, monkeypatch):
    """⭐⭐ **RN-539（批 59 已修）**：紧凑档抽屉必须和侧栏一样，含「常用」。

    抽屉原先遍历 `self.nav_groups` —— 那张表不含「常用」⇒
    **紧凑档下用户最常去的那几页在抽屉里根本没有**。这是 RN-025 的同根第二处。

    ⚠ 一个 page_id 会有**两颗**镜像按钮（常用组一颗、它自己的组一颗）——
      侧栏本来就是这样，抽屉照抄才可预测。所以 `_overlay_buttons` 的值是**列表**：
      存成一颗的话前一颗永远同步不到选中态，而那件事在屏幕上看不出来。
    """
    import core.page_usage_tracker as tracker

    seeded = ["kill_sound", "crosshair"]
    monkeypatch.setattr(tracker, "top_pages",
                        lambda n=4, known_pages=None: list(seeded))
    win = _build(app)
    try:
        win._apply_compact_mode(True)
        for _ in range(3):
            app.processEvents()
        win._show_sidebar_overlay()
        for _ in range(3):
            app.processEvents()

        assert win._overlay_buttons, "抽屉一颗镜像按钮都没建出来 —— 这条判据在空转"
        for page_id, btns in win._overlay_buttons.items():
            assert isinstance(btns, list), (
                f"{page_id} 的镜像按钮不是列表 —— 一页两颗时会只剩最后一颗")

        counts = {pid: len(btns) for pid, btns in win._overlay_buttons.items()}
        for pid in seeded:
            assert counts.get(pid, 0) == 2, (
                f"{pid} 在常用组和它自己的组里各该有一颗镜像按钮，实际 {counts.get(pid, 0)} 颗 —— "
                "抽屉没有照抄侧栏")
    finally:
        win._hide_sidebar_overlay()
        if win._compact_mode:
            win._toggle_compact_mode()
        win._force_exit = True
        win.close()
        win.deleteLater()
        app.processEvents()
