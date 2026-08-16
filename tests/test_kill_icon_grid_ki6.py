# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""KI-6：素材清单板。

KI-6 之前这一页的分工是拧巴的：页面上有个"素材导入"卡片，点开是**另一个
对话框**，对话框里又有一份风格下拉和等级下拉，可以和页面上的各选各的；
而"这套风格到底有哪几个等级"没有任何地方回答得了——唯一的信号是"时长滑条
被禁掉了"，用户得靠猜。

⚠ 这份文件里**不许调 `KillIconLevelCell._show_menu`**：`QMenu.exec` 是模态的，
测试进程里没人去点它，表现是整个 pytest 卡死（不是失败）。右键菜单的判据
只验"动作名 → 干了什么"这条路由。

⚠ **KI-7 之后清单板的宿主是素材工坊对话框，不再是设置页**（设置页只留
"挑一套、放哪儿、开没开"）。所以这里凡是"板子 + 宿主"的判据都换成了
`workshop` 夹具；纯控件的判据仍然只要 `qapp`。
"""
from __future__ import annotations


import pytest

import dialogs.kill_icon_workshop as workshop_module
from config import config
from core.kill_icon_library import LevelEntry
from widgets.kill_icon_level_grid import (
    DURATION_MAX_TICKS, DURATION_MIN_TICKS, KillIconLevelCell, KillIconLevelGrid,
    columns_for_width
)


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch):
    """拦掉所有 QMessageBox 与文件对话框。

    不是图省事：模态框在测试进程里没人点，表现是**永久挂住**而不是失败，
    而且它是真的会画到用户屏幕上的——测试不该打扰前台。
    """
    monkeypatch.setattr(workshop_module.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")), raising=False)
    monkeypatch.setattr(workshop_module.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("", "")), raising=False)


class _StubPlayer:
    def __init__(self, frames=30, fps=30, hold=0.0):
        self._frames = frames
        self._fps = fps
        self._hold = hold
        self.fps_updates = []
        self.hold_updates = []
        self.play_calls = []
        self.loaded_styles = []

    def load_style(self, style):
        self.loaded_styles.append(style)
        return True

    def get_style_fps(self, _style, _kills):
        return self._fps

    def get_style_hold(self, _style, _kills):
        return self._hold

    def get_style_frame_count(self, _style, _kills):
        return self._frames

    def update_fps_for_style(self, style, kills, fps):
        self.fps_updates.append((style, kills, fps))
        return True

    def update_hold_for_style(self, style, kills, hold):
        self.hold_updates.append((style, kills, hold))
        return True

    def play_icon(self, kills, fps=None):
        self.play_calls.append((kills, fps))

    def update_position_offset(self, *_args):
        pass

    def update_scale(self, *_args):
        pass

    def preview_position_and_scale(self, *_args):
        pass


def _make_workshop(monkeypatch, player=None, style="classic"):
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(workshop_module, "load_level_animation",
                        lambda *a, **k: None, raising=False)
    return workshop_module.KillIconWorkshop(style, player=player)


@pytest.fixture
def workshop(qapp, monkeypatch):
    """清单板的宿主。**不是 QDialog.exec**——那是模态的，会把测试挂死；
    这里只是把对话框构造出来，方法照常可调。"""
    dialog = _make_workshop(monkeypatch, player=_StubPlayer(frames=30))
    yield dialog
    dialog.level_grid.stop_previews()
    dialog.deleteLater()


# ==================================================== 1. 每一格自己说清现状


def test_an_empty_cell_says_so_instead_of_just_disabling_a_slider(qapp):
    """空缺的格子要**明说**空缺。

    KI-6 之前"这个等级没素材"的唯一信号是滑条被禁掉——用户得先注意到滑条
    是灰的，再猜出这代表什么。
    """
    cell = KillIconLevelCell(2)
    cell.set_state(LevelEntry(kills=2))

    assert cell.badge_label.text() == "空缺"
    assert "拖" in cell.info_label.text()
    assert cell.timing_label.text() == "无素材"
    assert cell.duration_slider.isEnabled() is False
    assert cell.test_btn.isEnabled() is False
    cell.deleteLater()


def test_a_filled_cell_shows_frames_and_kind(qapp):
    cell = KillIconLevelCell(3)
    cell.set_state(LevelEntry(kills=3, kind="legacy", frames=46, fps=30))

    assert cell.badge_label.text() == "已就绪"
    assert "46 帧" in cell.info_label.text()
    assert "逐帧目录" in cell.info_label.text()
    assert cell.duration_slider.isEnabled() is True
    cell.deleteLater()


def test_a_headshot_variant_is_visible_on_the_cell(qapp):
    """有没有爆头专属素材是"看不见就等于没有"的信息。

    KI-7b 改了摆放位置：以前爆头会把角标上的「已就绪」**顶掉**，于是这一格
    看上去像是"爆头专用的一格"，而设置页那边爆头是个独立勾选框，两处概念
    对不上。现在角标只报有没有素材，爆头归到下面那行——**信息一个不少，
    但不再互相排挤**。判据也跟着改成量"看得见没有"，不再钉死在角标上。
    """
    cell = KillIconLevelCell(4)
    cell.set_state(LevelEntry(kills=4, kind="sheet", frames=12, fps=12),
                   has_headshot=True)
    assert cell.badge_label.text() == "已就绪"
    assert "爆头" in cell.info_label.text()
    cell.deleteLater()


# ==================================================== 2. 单帧素材的时长语义


def test_a_static_asset_measures_hold_not_speed(qapp):
    """对一张静态图来说"播放速度"没有意义，滑条量的直接就是"停多久"。"""
    cell = KillIconLevelCell(1)
    cell.set_state(LevelEntry(kills=1, kind="sheet", frames=1, fps=30, hold_seconds=1.5))
    cell.set_timing_seconds(1.5)

    assert cell.is_static is True
    assert cell.timing_label.text() == "定格 1.5 秒"
    assert "静态" in cell.info_label.text()
    cell.deleteLater()


def test_a_multi_frame_asset_shows_the_rounded_back_duration(qapp):
    """帧率必须是整数，所以时长会被取整"吸"到附近的值上。

    显示用户拖的原值会让他量出来对不上；这里显示的是**换算回来**的真实时长。
    """
    from kill_icon_overlay import duration_for_fps, fps_for_duration

    cell = KillIconLevelCell(1)
    cell.set_frame_count(30)
    cell.set_timing_seconds(1.7)

    fps = fps_for_duration(30, 1.7)
    assert f"{duration_for_fps(30, fps):.2f} 秒" in cell.timing_label.text()
    assert f"{fps} FPS" in cell.timing_label.text()
    cell.deleteLater()


def test_reading_a_value_back_does_not_look_like_a_user_edit(qapp):
    """回填滑条不许触发 `duration_changed`。

    否则打开页面本身就会把"有未保存改动"点亮，用户永远看到一个假的 * 号。
    """
    cell = KillIconLevelCell(1)
    cell.set_frame_count(30)
    seen = []
    cell.duration_changed.connect(lambda *a: seen.append(a))

    cell.set_timing_seconds(2.0)
    assert seen == []

    cell.duration_slider.setValue(25)
    assert seen, "用户真拖的时候必须发信号"
    cell.deleteLater()


def test_static_levels_save_a_hold_and_animated_levels_save_a_frame_rate(qapp, monkeypatch):
    """两种素材落盘的字段不一样，这条把路由钉住。"""
    static = _make_workshop(monkeypatch, player=_StubPlayer(frames=1, hold=1.5))
    static.level_grid.cells[1].duration_slider.setValue(22)
    static._save_timing()
    assert ("classic", 1, 2.2) in static.player.hold_updates
    assert static.player.fps_updates == [], "单帧素材不该去改帧率"
    static.deleteLater()

    animated = _make_workshop(monkeypatch, player=_StubPlayer(frames=30))
    animated.level_grid.cells[1].duration_slider.setValue(20)
    animated._save_timing()
    assert ("classic", 1, 15) in animated.player.fps_updates
    assert animated.player.hold_updates == []
    animated.deleteLater()


# ==================================================== 3. 板子本身


def test_the_grid_folds_when_it_gets_narrow(qapp):
    """五格并排要 1000px 才装得下。窄了折行，而不是把每一格挤扁。"""
    assert columns_for_width(1200) == 5
    assert columns_for_width(620) == 3
    assert columns_for_width(420) == 2
    assert columns_for_width(80) == 1

    grid = KillIconLevelGrid()
    grid.set_columns(2)
    assert grid._layout.itemAtPosition(1, 0) is not None, "第二行要真的摆上东西"
    grid.deleteLater()


def test_the_slider_range_still_means_tenths_of_a_second():
    assert DURATION_MIN_TICKS == 3 and DURATION_MAX_TICKS == 50


def test_every_cell_is_its_own_drop_target(workshop):
    """想给 3 杀换素材就把文件拖到 3 杀那一格上，不用先去别处选等级。"""
    for kills, cell in workshop.level_grid.cells.items():
        filters = getattr(cell, "_file_drop_filters", [])
        assert filters, f"{kills} 杀那一格没有拖拽过滤器"
        assert any(getattr(f, "_accept_directories", False) for f in filters)


def test_the_host_no_longer_reimplements_drawing(qapp):
    """宿主里不许出现第二套绘制代码（KI-3 立的规矩，每次重构都重新验一遍）。"""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent /
              "dialogs" / "kill_icon_workshop.py").read_text(encoding="utf-8")
    painters = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", "")) == "QPainter"
    ]
    assert not painters, "素材工坊又开始自己画了；几何和绘制只能有一份"


# ==================================================== 4. 右键菜单


def test_the_menu_greys_out_what_cannot_be_done(qapp):
    """空格子上"导出/删除"必须是灰的——点了没反应比灰着更让人困惑。

    ⚠ 只能验到 `build_menu` 这一层：`QMenu.exec` 是模态的，测试里一调就
    **卡死而不是失败**。所以 `_show_menu` 被压成一行 exec，逻辑全在这个函数里。
    """
    empty = KillIconLevelCell(1)
    empty.set_state(LevelEntry(kills=1))
    actions = {a.text(): a.isEnabled() for a in empty.build_menu().actions() if a.text()}
    assert actions["替换素材…"] is True, "空格子照样得能导素材进来"
    assert actions["导入爆头专属素材…"] is True
    assert actions["导出这一格…"] is False
    assert actions["删除这一格"] is False
    assert actions["删除爆头素材"] is False
    empty.deleteLater()

    filled = KillIconLevelCell(2)
    filled.set_state(LevelEntry(kills=2, kind="sheet", frames=20, fps=20),
                     has_headshot=True)
    actions = {a.text(): a.isEnabled() for a in filled.build_menu().actions() if a.text()}
    assert actions["导出这一格…"] is True
    assert actions["删除这一格"] is True
    assert actions["删除爆头素材"] is True
    filled.deleteLater()


def test_no_headshot_means_the_headshot_delete_stays_grey(qapp):
    cell = KillIconLevelCell(4)
    cell.set_state(LevelEntry(kills=4, kind="sheet", frames=12, fps=12),
                   has_headshot=False)
    actions = {a.text(): a.isEnabled() for a in cell.build_menu().actions() if a.text()}
    assert actions["删除这一格"] is True
    assert actions["删除爆头素材"] is False
    cell.deleteLater()


@pytest.mark.parametrize("label,action", [
    ("替换素材…", "replace"),
    ("导入爆头专属素材…", "import_hs"),
    ("导出这一格…", "export"),
    ("删除这一格", "delete"),
    ("删除爆头素材", "delete_hs"),
])
def test_each_menu_item_fires_the_right_action(qapp, label, action):
    """菜单项与它该干的事之间的接线。接错了不会报错，只会干成别的事。"""
    cell = KillIconLevelCell(3)
    cell.set_state(LevelEntry(kills=3, kind="sheet", frames=20, fps=20),
                   has_headshot=True)
    seen = []
    cell.action_triggered.connect(lambda name, kills: seen.append((name, kills)))

    for item in cell.build_menu().actions():
        if item.text() == label:
            item.trigger()
    assert seen == [(action, 3)]
    cell.deleteLater()


def test_host_routes_every_menu_action_somewhere(workshop, monkeypatch):
    """宿主这一侧：五个动作各自落到不同的处理上，没有一个是空转的。"""
    calls = []
    monkeypatch.setattr(workshop, "_choose_files_for",
                        lambda kills, variant: calls.append(("choose", kills, variant)))
    monkeypatch.setattr(workshop, "_export_level", lambda kills: calls.append(("export", kills)))
    monkeypatch.setattr(workshop, "_delete_level",
                        lambda kills, variant: calls.append(("delete", kills, variant)))
    monkeypatch.setattr(workshop, "test_level", lambda kills: calls.append(("test", kills)))

    for action in ("test", "replace", "import_hs", "export", "delete", "delete_hs"):
        workshop._on_level_action(action, 2)

    assert calls == [
        ("test", 2),
        ("choose", 2, ""),
        ("choose", 2, "hs"),
        ("export", 2),
        ("delete", 2, ""),
        ("delete", 2, "hs"),
    ]


# ==================================================== 5. 提示条与撤销


def test_deleting_a_level_offers_an_undo(workshop, monkeypatch):
    """删错了的代价是"用户手上那份原素材可能已经没了"。

    而这一步是点一下就能触发的，所以提示条上必须挂着「撤销」。
    """
    recorded = {}

    def _fake_delete(style, kills, variant):
        recorded["args"] = (style, kills, variant)
        return "TOKEN"

    monkeypatch.setattr(workshop_module, "delete_level", _fake_delete)
    monkeypatch.setattr(workshop, "_reload_player", lambda: None)

    workshop._on_level_action("delete", 3)

    assert recorded["args"] == ("classic", 3, "")
    assert workshop.notice_frame.isHidden() is False
    assert workshop.undo_btn.isHidden() is False
    assert workshop._undo_token == "TOKEN"


def test_undo_actually_restores_and_reports_when_it_cannot(workshop, monkeypatch):
    monkeypatch.setattr(workshop_module, "delete_level", lambda *a: "TOKEN")
    monkeypatch.setattr(workshop, "_reload_player", lambda: None)
    workshop._on_level_action("delete", 3)

    monkeypatch.setattr(workshop_module, "restore_level", lambda token: True)
    workshop._undo_last_delete()
    assert "已撤销" in workshop.notice_label.text()

    workshop._on_level_action("delete", 3)
    monkeypatch.setattr(workshop_module, "restore_level", lambda token: False)
    workshop._undo_last_delete()
    assert "撤销失败" in workshop.notice_label.text()


def test_the_notice_replaces_the_old_modal_pile(workshop):
    """保存播放设置以前会弹一个模态框。

    弹窗是这条链最伤"亲民"的地方：导入一次要点两三个框。而且模态框在测试
    进程里没人点就是**卡死**——这条链踩过一次。
    """
    workshop._save_timing()
    assert workshop.notice_frame.isHidden() is False
    assert "已保存" in workshop.notice_label.text()


def test_dismissing_the_notice_drops_the_undo_token(workshop, monkeypatch):
    monkeypatch.setattr(workshop_module, "delete_level", lambda *a: "TOKEN")
    monkeypatch.setattr(workshop, "_reload_player", lambda: None)
    workshop._on_level_action("delete", 2)
    workshop._clear_notice()
    assert workshop._undo_token is None
    assert workshop.notice_frame.isHidden() is True


# ==================================================== 5. 异步装载的窗口期


def test_switching_styles_does_not_report_the_previous_styles_frames(qapp):
    """切风格之后、后台装载完成之前，**不许**拿上一个风格的数糊弄。

    `load_style` 是同步返回、异步装载的：它立刻把 `current_style` 改掉，
    而缓存要等后台线程跑完。KI-6 实测踩到：刚拖进去一个图标包，清单板上
    五个格子显示的是老风格的帧数（46/123/74/75/201）和时长，而且**不会自己好**
    ——要等下一次刷新才对。

    正确行为是回落到读磁盘；磁盘上没有就是 0（这一格显示"空缺"）。
    """
    import kill_icon_player as kp

    player = kp.KillIconPlayer.__new__(kp.KillIconPlayer)
    player.current_style = "老风格"
    player._catalog = {(1, ""): kp.LevelInfo(201, 30, 350, 250)}
    player._catalog_style = "老风格"
    player.animations = {1: {"fps": 30}}

    assert kp.KillIconPlayer.get_style_frame_count(player, "老风格", 1) == 201

    player.current_style = "新风格"          # load_style 干的第一件事
    assert kp.KillIconPlayer.get_style_frame_count(player, "新风格", 1) == 0, \
        "拿到了上一个风格的帧数"
    assert kp.KillIconPlayer.get_style_hold(player, "新风格", 1) == 0.0


def test_the_page_refreshes_itself_when_the_assets_land(qapp, monkeypatch):
    """装载完成要通知页面。不通知的话，回落到读盘虽然不会显示错的数，
    但用户会看到"导入成功了，页面上还是老样子"，同样得再刷一次才好。
    """
    import kill_icon_player as kp
    import pages.kill_icon_page as page_module

    monkeypatch.setattr(page_module.ResourceManager, "list_kill_icon_styles",
                        lambda: ["classic"])
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_icon_style", "classic", raising=False)
    monkeypatch.setattr(page_module, "load_level_animation", lambda *a, **k: None)
    page = page_module.KillIconPage()

    player = kp.KillIconPlayer.__new__(kp.KillIconPlayer)
    kp.QObject.__init__(player)
    player.current_style = "classic"
    player._catalog = {}
    player._catalog_style = None
    player.animations = {}
    player._assets_lock = __import__("threading").Lock()
    player._load_token = 0

    page.set_kill_icon_player(player)
    seen = []
    page._on_assets_ready = lambda style: seen.append(style)
    player.assets_ready.connect(page._on_assets_ready)

    # 用当前的令牌：`set_kill_icon_player` 会顺手起一次装载，令牌已经往前走了，
    # 拿旧令牌回来的结果会被当成"已被更新的一次装载取代"直接丢掉。
    player._handle_assets_ready("classic", player._load_token, {
        (1, ""): (kp.LevelInfo(30, 15, 40, 30), ()),
    })
    # 真实的后台装载线程也会补一枪（风格库里恰好有 classic 时），所以只验
    # "至少通知过一次、且通知的是当前风格"，不数次数。
    assert seen, "装载完成没有通知页面"
    assert set(seen) == {"classic"}
    assert player._catalog_style == "classic"
    page.deleteLater()


# ==================================================== 6. 工坊的摘要


def test_the_workshop_says_how_many_levels_are_covered(qapp, monkeypatch):
    """"这套风格缺哪几个等级"以前没有任何地方回答得了。"""
    full = _make_workshop(monkeypatch, player=_StubPlayer(frames=30))
    assert "5/5 个等级" in full.summary_label.text()
    full.deleteLater()

    empty = _make_workshop(monkeypatch, player=_StubPlayer(frames=0))
    text = empty.summary_label.text()
    assert "0/5 个等级" in text
    assert "缺 1 杀" in text
    empty.deleteLater()
